"""Useful young-ledger windows and non-mutating operator inspection."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from rag_preflight import SQLiteSnapshotStore
from rag_preflight.cli import main
from test_review_fixes import document, shrink, snap


class LedgerInspectionTests(unittest.TestCase):
    def populate(self,store):
        store.commit(store.plan(snap(document('d',20))))
        for n in (18,16,14,12):store.commit(store.plan(snap(shrink('d',20,n))))

    def cli(self,args):
        out,err=StringIO(),StringIO()
        with redirect_stdout(out),redirect_stderr(err):status=main(args)
        return status,out.getvalue(),err.getvalue()

    def test_default_window_uses_post_population_baseline(self):
        with SQLiteSnapshotStore(':memory:') as store:
            self.populate(store)
            r=store.deletion_summary()
            self.assertEqual((r['start_chunks'],r['end_chunks'],r['chunks_removed']),(20,12,8))
            self.assertEqual((r['gross_removed_fraction'],r['net_shrink_fraction']),(.4,.4))
            self.assertTrue(r['window_adjusted'])
            self.assertEqual(r['initial_commits_excluded'],1)
            self.assertEqual(r['commits_considered'],4)
            self.assertEqual(r['baseline_basis'],'after_initial_population')
            explicit=store.deletion_summary(last_commits=4)
            self.assertFalse(explicit['window_adjusted'])
            self.assertEqual(explicit['gross_removed_fraction'],r['gross_removed_fraction'])
            self.assertEqual(len(store.commit_history()),5)

    def test_empty_and_only_import_are_still_unverified_ratios(self):
        with SQLiteSnapshotStore(':memory:') as store:
            self.assertIsNone(store.deletion_summary()['gross_removed_fraction'])
            store.commit(store.plan(snap(document('d',20))))
            self.assertIsNone(store.deletion_summary()['gross_removed_fraction'])
            self.assertFalse(store.deletion_summary()['window_adjusted'])

    def test_retirement_and_repopulation_are_not_hidden(self):
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(snap(document('d',20))))
            store.commit(store.plan(snap(),retire_documents=['d']))
            store.commit(store.plan(snap(document('new',20))))
            r=store.deletion_summary()
            self.assertEqual(r['chunks_removed'],20)
            self.assertEqual(r['chunks_added'],20)
            self.assertEqual(r['gross_removed_fraction'],1)
            self.assertEqual(r['net_shrink_fraction'],0)
            # A requested window starting at genuine re-population remains zero.
            r=store.deletion_summary(last_commits=1)
            self.assertIsNone(r['gross_removed_fraction'])
            self.assertFalse(r['window_adjusted'])

    def test_initial_empty_setup_then_population(self):
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(snap()))
            self.populate(store)
            r=store.deletion_summary()
            self.assertEqual(r['initial_commits_excluded'],2)
            self.assertEqual(r['gross_removed_fraction'],.4)

    def test_cli_json_and_database_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ledger with spaces.db'
            with SQLiteSnapshotStore(path) as store:self.populate(store)
            before=path.read_bytes()
            status,out,err=self.cli(['ledger','summary',str(path),'--json'])
            self.assertEqual(status,0,err)
            self.assertEqual(json.loads(out)['gross_removed_fraction'],.4)
            status,out,err=self.cli(['ledger','history',str(path),'--limit','2','--json'])
            self.assertEqual(status,0,err)
            self.assertEqual(len(json.loads(out)),2)
            self.assertEqual(path.read_bytes(),before)
            with SQLiteSnapshotStore(path,read_only=True) as store:
                with self.assertRaises(ValueError):store.commit(store.plan(snap(document('d',20))))
                with self.assertRaises(sqlite3.OperationalError):store._db.execute('DELETE FROM documents')

    def test_missing_legacy_and_corrupt_files_fail_without_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'missing.db'
            status,out,err=self.cli(['ledger','summary',str(path),'--json'])
            self.assertEqual(status,2);self.assertFalse(path.exists())
            with SQLiteSnapshotStore(path) as store:
                store._db.execute('PRAGMA user_version=1')
            before=path.read_bytes()
            status,out,err=self.cli(['ledger','summary',str(path)])
            self.assertEqual(status,2);self.assertIn('upgrade explicitly',err)
            self.assertEqual(path.read_bytes(),before)
            path.write_bytes(b'not sqlite')
            before=path.read_bytes()
            self.assertEqual(self.cli(['ledger','summary',str(path)])[0],2)
            self.assertEqual(path.read_bytes(),before)

    def test_incomplete_migrated_history_keeps_its_anchor(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'old.db'
            with SQLiteSnapshotStore(path) as store:
                store.commit(store.plan(snap(document('d',20))))
                store._db.execute('DROP TABLE commits');store._db.execute('DROP TABLE history_origin')
                store._db.execute('PRAGMA user_version=1')
            with SQLiteSnapshotStore(path) as store:
                store.commit(store.plan(snap(shrink('d',20,18))))
                r=store.deletion_summary()
                self.assertEqual(r['gross_removed_fraction'],.1)
                self.assertFalse(r['window_adjusted'])
                self.assertFalse(r['history_complete'])
                self.assertIn('pre_tracking_commit_history',r['checks_unverified'])
