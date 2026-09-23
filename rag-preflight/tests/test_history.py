"""Transactional cumulative-deletion telemetry and schema migration."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from rag_preflight import SQLiteSnapshotStore, UnsafePlanError
from test_review_fixes import document, shrink, snap


class CommitHistoryTests(unittest.TestCase):
    def test_four_passing_plans_surface_forty_percent(self):
        # Same fractions as the 2,000-document incident, kept small for this suite.
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(snap(*(document(str(i),20) for i in range(20)))))
            for retained in (18,16,14,12):
                store.commit(store.plan(snap(*(shrink(str(i),20,retained) for i in range(20)))))
            report = store.deletion_summary(last_commits=4)
            self.assertEqual(report['start_chunks'],400)
            self.assertEqual(report['end_chunks'],240)
            self.assertEqual(report['chunks_removed'],160)
            self.assertEqual(report['ordinary_removed_chunks'],160)
            self.assertEqual(report['net_shrink_fraction'],.4)
            self.assertEqual(report['gross_removed_fraction'],.4)
            self.assertEqual(report['commits_considered'],4)
            with self.assertRaisesRegex(UnsafePlanError,'40/240'):
                store.plan(snap(*(shrink(str(i),20,10) for i in range(20))))
            self.assertEqual(store.deletion_summary(last_commits=4),report)
            self.assertNotIn('revision',json.dumps(report))

    def test_identity_churn_is_not_net_content_loss(self):
        item=document('d',20)
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(snap(item)))
            changed=deepcopy(item)
            for c in changed[2][:2]:c['chunk_key']='new-'+c['chunk_key']
            store.commit(store.plan(snap(changed)))
            report=store.deletion_summary(last_commits=1)
            self.assertEqual(report['chunks_removed'],2)
            self.assertEqual(report['chunks_added'],2)
            self.assertEqual(report['gross_removed_fraction'],.1)
            self.assertEqual(report['net_shrink_fraction'],0)

    def test_exempt_and_retired_categories(self):
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(snap(document('retired',10),document('allowed',20),document('ordinary',20))))
            store.commit(store.plan(snap(shrink('allowed',20,10),shrink('ordinary',20,18)),
                                    retire_documents=['retired'],allow_shrink={'allowed':.5}))
            r=store.deletion_summary(last_commits=1)
            self.assertEqual((r['ordinary_removed_chunks'],r['allowance_removed_chunks'],r['retirement_removed_chunks']),(2,10,10))
            self.assertEqual(r['chunks_removed'],22)
            self.assertEqual(r['net_shrink_fraction'],22/50)
            row=store.commit_history(limit=1)[0]
            self.assertEqual(row['before_chunks'],50)
            self.assertEqual(row['after_chunks'],28)
            self.assertIn('corpus_fraction',row['policy'])

    def test_noop_stale_and_metadata_commits(self):
        item=document('d',20)
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(snap(item)))
            stale=store.plan(snap(shrink('d',20,18)))
            store.commit(store.plan(snap(item)))
            self.assertEqual(len(store.commit_history()),1)
            md=deepcopy(item);md[2][0]['metadata']['label']='new'
            store.commit(store.plan(snap(md)))
            self.assertEqual(len(store.commit_history()),2)
            self.assertEqual(store.deletion_summary(last_commits=1)['chunks_removed'],0)
            with self.assertRaises(UnsafePlanError):store.commit(stale)
            self.assertEqual(len(store.commit_history()),2)

    def test_history_write_failure_rolls_back_ledger(self):
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(snap(document('d',20))))
            base=store.revision
            store._db.execute("CREATE TRIGGER reject_history BEFORE INSERT ON commits BEGIN SELECT RAISE(ABORT,'history failure'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                store.commit(store.plan(snap(shrink('d',20,18))))
            self.assertEqual(store.revision,base)
            self.assertEqual(store.counts()['chunks'],20)
            self.assertEqual(len(store.commit_history()),1)

    def test_migrated_history_is_explicitly_incomplete_and_persistent(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ledger.db'
            with SQLiteSnapshotStore(path) as store:
                store.commit(store.plan(snap(document('d',20))))
                store._db.execute('DROP TABLE commits')
                store._db.execute('DROP TABLE history_origin')
                store._db.execute('PRAGMA user_version=1')
            with SQLiteSnapshotStore(path) as store:
                self.assertEqual(store._db.execute('PRAGMA user_version').fetchone()[0],2)
                r=store.deletion_summary()
                self.assertFalse(r['history_complete'])
                self.assertEqual(r['baseline_chunks_at_history_start'],20)
                self.assertIn('pre_tracking_commit_history',r['checks_unverified'])
                store.commit(store.plan(snap(shrink('d',20,18))))
            with SQLiteSnapshotStore(path) as store:
                self.assertEqual(store.deletion_summary(last_commits=1)['chunks_removed'],2)
                self.assertFalse(store.deletion_summary()['history_complete'])
                self.assertTrue(store.verify().passed)

    def test_empty_import_and_bounded_history(self):
        with SQLiteSnapshotStore(':memory:') as store:
            self.assertEqual(store.deletion_summary()['commits_considered'],0)
            self.assertIsNone(store.deletion_summary()['net_shrink_fraction'])
            store.commit(store.plan(snap(document('d',20))))
            self.assertIsNone(store.deletion_summary(last_commits=1)['gross_removed_fraction'])
            with patch.object(store,'_decode_document',side_effect=AssertionError('payload read')):
                self.assertEqual(len(store.commit_history(limit=1)),1)
                self.assertEqual(store.deletion_summary(last_commits=1)['end_chunks'],20)
            for value in (0,-1,True,1.5):
                with self.assertRaises(ValueError):store.deletion_summary(last_commits=value)
                with self.assertRaises(ValueError):store.commit_history(limit=value)


    def test_unknown_legacy_classification_stays_unverified(self):
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(snap(document('d',20))))
            plan=store.plan(snap(shrink('d',20,18)))
            plan=replace(plan, update=replace(plan.update,deletion_policy=()))
            store.commit(plan)
            r=store.deletion_summary(last_commits=1)
            self.assertEqual(r['chunks_removed'],2)
            self.assertIsNone(r['ordinary_removed_chunks'])
            self.assertIn('removal_classification',r['checks_unverified'])

    def test_failed_schema_migration_rolls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ledger.db'
            with SQLiteSnapshotStore(path) as store:
                store.commit(store.plan(snap(document('d',20))))
                store._db.execute('DROP TABLE commits')
                store._db.execute('DROP TABLE history_origin')
                store._db.execute('CREATE TABLE history_origin(id INTEGER PRIMARY KEY, history_complete INTEGER CHECK(history_complete=9),baseline_chunks INTEGER)')
                store._db.execute('PRAGMA user_version=1')
            with self.assertRaises(sqlite3.IntegrityError):SQLiteSnapshotStore(path)
            from contextlib import closing
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='commits'").fetchone())
                self.assertEqual(db.execute('SELECT sum(chunk_count) FROM documents').fetchone()[0],20)
