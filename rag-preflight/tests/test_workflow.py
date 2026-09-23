import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import tempfile
import unittest
from rag_preflight import Snapshot, audit_embeddings, plan_update
from rag_preflight.cli import main
from test_ingestion import batch, chunk, doc, receipt
from test_reingestion import snapshot


class WorkflowTests(unittest.TestCase):
    def test_retry_after_partial_upsert_does_not_advance_committed_state(self):
        old = snapshot()
        records = batch()
        records[0]['text'] = 'Updated one'
        records[1]['text'] = 'Updated two'
        new = snapshot(records)
        plan = plan_update(old, new)
        committed = old
        sink = {c.chunk_id: c for c in old.chunks}
        states = {c.chunk_id: c for c in new.chunks}
        first = plan.upsert_ids[0]
        sink[first] = states[first]  # Simulate success then connection failure.
        self.assertEqual(committed, old)
        # Replay the same deterministic writes under the application lock.
        retry = plan_update(committed, new)
        self.assertEqual(plan.plan_id, retry.plan_id)
        retry.assert_base(committed)
        for key in retry.upsert_ids:
            sink[key] = states[key]
        for key in retry.removed:
            sink.pop(key, None)
        committed = retry.target
        self.assertEqual(sink, {c.chunk_id: c for c in committed.chunks})
        self.assertFalse(plan_update(committed, new).upsert_ids)

    def test_removal_guard_applies_per_document(self):
        from rag_preflight import UnsafePlanError
        records = batch() + [chunk(str(i), f'extra {i}', document='large', pages=[1]) for i in range(20)]
        old = snapshot(records, [doc(), doc('large', pages=(1,))], [receipt(), receipt('large', pages=(1,))])
        candidate = snapshot(records=[chunk('one', 'Both pages', pages=[1,2])])
        with self.assertRaises(UnsafePlanError):
            plan_update(old, candidate)  # Globally under 25%, but all manual IDs removed.

    def test_metadata_only_vectors_can_be_reused_and_validated(self):
        old = snapshot()
        records = batch()
        records[0]['metadata']['source'] = 'renamed.pdf'
        plan = plan_update(old, snapshot(records))
        self.assertFalse(plan.embed_ids)
        payloads = [{'chunk_id': key, 'vector': [0.5, 0.5]} for key in plan.upsert_ids]
        self.assertTrue(audit_embeddings(plan.upsert_ids, payloads, dimensions=2).passed)

    def test_manifest_cli_and_snapshot_plan(self):
        example = Path(__file__).resolve().parents[1] / 'examples/ingestion.json'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'candidate.json'
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(['ingestion', str(example), '--snapshot', str(path)]), 0)
            self.assertTrue(json.loads(out.getvalue())['passed'])
            self.assertEqual(len(Snapshot.load(path).chunks), 2)
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(['plan', '-', str(path)]), 0)
            self.assertEqual(len(json.loads(out.getvalue())['added']), 2)
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(['plan', str(path), str(path)]), 0)
            self.assertEqual(json.loads(out.getvalue())['upsert_ids'], [])

    def test_bad_batch_does_not_write_or_replace_snapshot(self):
        example = Path(__file__).resolve().parents[1] / 'examples/ingestion.json'
        data = json.loads(example.read_text())
        data['chunks'].pop()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'batch.json'
            target = Path(directory) / 'candidate.json'
            source.write_text(json.dumps(data))
            target.write_text('prior snapshot sentinel')
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['ingestion', str(source), '--snapshot', str(target)]), 1)
            self.assertEqual(target.read_text(), 'prior snapshot sentinel')

    def test_embeddings_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'vectors.json'
            source.write_text(json.dumps({'expected_chunk_ids': ['a'], 'dimensions': 2,
                                          'embeddings': [{'chunk_id': 'a', 'vector': [1, 0]}]}))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['embeddings', str(source)]), 0)
            source.write_text('{}')
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(['embeddings', str(source)]), 2)
