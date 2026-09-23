from dataclasses import replace
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from rag_preflight import (AcceptancePolicy, Snapshot, UnsafePlanError, ValidationError,
                          build_snapshot, plan_update, stable_chunk_id)
from test_ingestion import doc, receipt, chunk, batch


def snapshot(records=None, documents=None, receipts=None, **kwargs):
    return build_snapshot([doc()] if documents is None else documents,
                          [receipt()] if receipts is None else receipts,
                          batch() if records is None else records, namespace=kwargs.pop('namespace', 'tenant-a'),
                          pipeline_id=kwargs.pop('pipeline_id', 'parser-1/chunker-1'),
                          embedding_model=kwargs.pop('embedding_model', 'model-1/dim-2'), **kwargs)


class ReingestionTests(unittest.TestCase):
    def test_bootstrap_and_noop_retry(self):
        current = snapshot()
        plan = plan_update(None, current)
        self.assertEqual(len(plan.added), 2)
        self.assertEqual(plan.embed_ids, plan.upsert_ids)
        self.assertEqual(plan.target, current)
        retry = plan_update(current, current)
        self.assertEqual(retry.upsert_ids, ())
        self.assertEqual(retry.removed, ())
        self.assertEqual(len(retry.unchanged), 2)

    def test_stable_scoped_ids(self):
        self.assertEqual(stable_chunk_id('a', 'b', 'c'), stable_chunk_id('a', 'b', 'c'))
        self.assertEqual(len({stable_chunk_id(*parts) for parts in [('a','b','c'),('b','b','c'),('a','c','c'),('a','b','d'),('a:b','c','d'),('a','b:c','d')]}), 6)
        with self.assertRaises(ValueError):
            stable_chunk_id('', 'b', 'c')

    def test_text_change_same_identity_reembeds(self):
        old = snapshot()
        records = batch()
        records[0]['text'] = 'Revised first page'
        new = snapshot(records)
        plan = plan_update(old, new)
        self.assertEqual(len(plan.changed), 1)
        self.assertEqual(plan.embed_ids, plan.changed)
        self.assertEqual(plan.removed, ())

    def test_metadata_change_upserts_without_reembedding(self):
        records = batch()
        records[0]['metadata']['access_group'] = 'staff'
        plan = plan_update(snapshot(), snapshot(records))
        self.assertEqual(len(plan.changed), 1)
        self.assertEqual(plan.embed_ids, ())
        self.assertEqual(plan.upsert_ids, plan.changed)

    def test_version_only_change(self):
        records = batch()
        for record in records:
            record['metadata']['source_version'] = 'v2'
        plan = plan_update(snapshot(), snapshot(records, [doc(version='v2')], [receipt(version='v2')]))
        self.assertEqual(len(plan.changed), 2)
        self.assertFalse(plan.embed_ids)

    def test_order_and_metadata_key_order_do_not_change_revision(self):
        base = snapshot()
        for ordered in itertools.permutations(batch()):
            records = []
            for record in ordered:
                records.append({**record, 'metadata': dict(reversed(list(record['metadata'].items())))})
            self.assertEqual(snapshot(records).revision, base.revision)

    def test_exact_text_hash_not_whitespace_normalized(self):
        records = batch()
        records[0]['text'] += ' '
        self.assertEqual(len(plan_update(snapshot(), snapshot(records)).embed_ids), 1)

    def test_incomplete_cannot_build_snapshot(self):
        with self.assertRaises(ValidationError):
            snapshot([chunk()])
        with self.assertRaises(ValidationError):
            snapshot(receipts=[receipt(completed=False)])

    def test_omitted_documents_are_preserved(self):
        old = snapshot(batch() + [chunk('other', document='other', pages=[1])],
                       [doc(), doc('other', pages=(1,))], [receipt(), receipt('other', pages=(1,))])
        plan = plan_update(old, snapshot())
        self.assertEqual(plan.preserved_documents, ('other',))
        self.assertEqual(len(plan.target.chunks), 3)
        self.assertFalse(plan.removed)
        self.assertEqual(plan.target.revision, old.revision)

    def test_explicit_retirement_and_delete_fraction(self):
        empty = snapshot([], [], [], policy=AcceptancePolicy(require_documents=False))
        plan = plan_update(snapshot(), empty, retire_documents=['manual'])
        self.assertEqual(len(plan.removed), 2)
        self.assertFalse(plan.target.documents)
        self.assertEqual(plan.retired_documents, ('manual',))

    def test_chunk_removed_from_complete_document(self):
        old_records = batch() + [chunk('extra', 'Extra passage', pages=[2])]
        with self.assertRaises(UnsafePlanError):
            plan_update(snapshot(old_records), snapshot())
        plan = plan_update(snapshot(old_records), snapshot(), max_delete_fraction=0.5, max_corpus_delete_fraction=.5)
        self.assertEqual(len(plan.removed), 1)
        self.assertFalse(plan.upsert_ids)

    def test_invalid_retirement(self):
        for retired in [['unknown'], ['manual'], 'manual', ['manual', 'manual']]:
            with self.subTest(retired=retired), self.assertRaises((UnsafePlanError, ValueError)):
                plan_update(snapshot(), snapshot(), retire_documents=retired)

    def test_namespace_mismatch(self):
        with self.assertRaises(UnsafePlanError):
            plan_update(snapshot(), snapshot(namespace='other'))

    def test_model_and_pipeline_migration_reembeds(self):
        for kwargs in [dict(embedding_model='model-2'), dict(pipeline_id='parser-2')]:
            plan = plan_update(snapshot(), snapshot(**kwargs))
            self.assertEqual(len(plan.embed_ids), 2)
            self.assertEqual(len(plan.changed), 2)

    def test_partial_model_migration_rejected(self):
        old = snapshot(batch() + [chunk(document='other', pages=[1])], [doc(), doc('other', pages=(1,))], [receipt(), receipt('other', pages=(1,))])
        with self.assertRaises(UnsafePlanError):
            plan_update(old, snapshot(embedding_model='model-2'))

    def test_stale_plan_guard(self):
        old = snapshot()
        plan = plan_update(old, snapshot(pipeline_id='parser-2'))
        plan.assert_base(old)
        with self.assertRaises(UnsafePlanError):
            plan.assert_base(plan.target)
        with self.assertRaises(UnsafePlanError):
            plan.assert_base(None)
        plan_update(None, old).assert_base(None)

    def test_roundtrip_and_tamper_detection(self):
        current = snapshot()
        self.assertEqual(Snapshot.from_dict(json.loads(json.dumps(current.to_dict()))), current)
        data = current.to_dict()
        data['chunks'][0]['text_hash'] = '0' * 64
        with self.assertRaises(ValueError):
            Snapshot.from_dict(data)
        for field, value in [('schema_version', 99), ('schema_version', True), ('revision', 'bad'), ('chunks', {}), ('documents', {})]:
            data = current.to_dict()
            data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                Snapshot.from_dict(data)
        newer = current.to_dict()
        newer['schema_version'] = 2
        newer['future_field'] = 'introduced by a future writer'
        with self.assertRaisesRegex(ValueError, 'version 2: newer than this reader'):
            Snapshot.from_dict(newer)
        older = current.to_dict()
        older['schema_version'] = 0
        with self.assertRaisesRegex(ValueError, 'version 0: no migration available'):
            Snapshot.from_dict(older)

    def test_snapshot_structural_validation(self):
        current = snapshot()
        for kwargs in [dict(documents=current.documents * 2), dict(chunks=current.chunks * 2), dict(documents=()), dict(namespace=''), dict(chunks=(replace(current.chunks[0], chunk_id='bad'),)), dict(chunks=(replace(current.chunks[0], metadata_hash='bad'),))]:
            with self.assertRaises(ValueError):
                replace(current, **kwargs)

    def test_atomic_save_load_and_failed_replace(self):
        current = snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            current.save(path)
            self.assertEqual(Snapshot.load(path), current)
            before = path.read_bytes()
            with patch('rag_preflight.reingestion.os.replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    snapshot(pipeline_id='new').save(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
            path.write_text('{"revision": "a", "revision": "b"}')
            with self.assertRaises(ValueError):
                Snapshot.load(path)

    def test_no_raw_content_in_snapshot_or_plan(self):
        current = snapshot()
        self.assertNotIn('First page', json.dumps(current.to_dict()))
        self.assertNotIn('manual.pdf', json.dumps(current.to_dict()))
        self.assertNotIn('First page', json.dumps(plan_update(None, current).to_dict()))

    def test_plan_is_deterministic(self):
        old, new = snapshot(), snapshot(pipeline_id='new')
        self.assertEqual(plan_update(old, new).to_dict(), plan_update(old, new).to_dict())

    def test_bad_delete_configuration(self):
        for limit in [-1, 2, True, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                plan_update(None, snapshot(), max_delete_fraction=limit)

class SnapshotEdgeTests(unittest.TestCase):
    def test_empty_update_preserves_inventory_without_retirement(self):
        empty = snapshot([], [], [], policy=AcceptancePolicy(require_documents=False))
        old = snapshot()
        plan = plan_update(old, empty)
        self.assertEqual(plan.target, old)
        self.assertEqual(plan.removed, ())

    def test_delete_threshold_is_inclusive(self):
        records = batch() + [chunk('third', 'Third', pages=[2]), chunk('fourth', 'Fourth', pages=[2])]
        plan = plan_update(snapshot(records), snapshot(records[:-1]), max_corpus_delete_fraction=.25)
        self.assertEqual(len(plan.removed), 1)

    def test_unicode_identity_and_metadata_roundtrip(self):
        records = batch()
        records[0]['metadata']['title'] = 'తెలుగు café'
        current = snapshot(records, namespace='組織')
        self.assertEqual(Snapshot.from_dict(json.loads(json.dumps(current.to_dict()))), current)
