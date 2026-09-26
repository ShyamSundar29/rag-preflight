"""Local FAISS behavior, durable failure recovery and PDF evidence."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import tiktoken
from rag_preflight import SQLiteSnapshotStore, stable_chunk_id
from rag_preflight_faiss_reference.app import ReferenceApp
from rag_preflight_faiss_reference.config import Settings
from rag_preflight_faiss_reference.corpus import CandidateRejected, prepare
from rag_preflight_faiss_reference.provider import Answer, EmbeddingBatch
from rag_preflight_faiss_reference.store import FaissStore, Payload
from rag_preflight_reference_common.testing import assert_vector_store_contract


class FakeProvider:
    """Only for local fault tests; never presented as live embedding evidence."""
    def __init__(self):
        self.calls = 0
        self.inputs = 0
        self.tokens = 0
        self.answers = 0
    def embed(self, inputs):
        self.calls += 1
        self.inputs += len(inputs)
        encoding = tiktoken.encoding_for_model('text-embedding-3-small')
        tokens = sum(len(encoding.encode(text)) for text in inputs)
        self.tokens += tokens
        vectors = []
        for text in inputs:
            digest = hashlib.sha256(text.encode()).digest()
            vectors.append(tuple((digest[i % 32] - 127) / 500 for i in range(1536)))
        return EmbeddingBatch(tuple(vectors), tokens, 'fake-local-test')
    def answer(self, question, contexts):
        self.answers += 1
        return Answer('The provided passage supports this answer [1].', 10, 10,
                      'fake-local-test')


class FailSecondBatchProvider(FakeProvider):
    """One transient failure after a successful batch, with no hidden retry."""
    def __init__(self):
        super().__init__()
        self.failed = False
    def embed(self, inputs):
        if self.calls == 1 and not self.failed:
            self.failed = True
            self.calls += 1
            raise RuntimeError('injected second embedding batch failure')
        return super().embed(inputs)


class CorpusTests(unittest.TestCase):
    def test_curated_offline_evidence_is_simulated_and_excludes_raw_payloads(self):
        root = Settings.local().root
        reviewed = json.loads((root / 'reviewed-results/offline-evidence.json').read_text())
        self.assertEqual(reviewed['schema_version'], 2)
        self.assertEqual(reviewed['proof_kind'], 'offline_local_faiss_simulated_vectors')
        self.assertEqual(reviewed['paid_api_calls'], 0)
        self.assertFalse(reviewed['independent_live_proof'])
        self.assertEqual(reviewed['first_planned_embeddings'], 171)
        self.assertEqual(reviewed['unchanged_planned_embeddings'], 0)
        self.assertEqual(reviewed['metadata_planned_embeddings'], 0)
        self.assertTrue(reviewed['guarded_index_preserved'])
        for files in reviewed['curated_run_files'].values():
            for name in files:
                item = json.loads((root / 'reviewed-results' / name).read_text())
                self.assertNotIn('candidate_payloads', item)
                self.assertNotIn('vectors', item)

    def test_curated_live_evidence_is_sanitized_and_bounded(self):
        root = Settings.local().root
        evidence = json.loads((root / 'reviewed-results/live-openai-evidence.json').read_text())
        self.assertEqual(evidence['proof_kind'], 'bounded_live_openai_reference_run')
        self.assertEqual(evidence['backend'], 'faiss')
        self.assertEqual(evidence['embedding']['first_ingestion']['completed_inputs'], 171)
        self.assertEqual(evidence['embedding']['unchanged_reingestion']['completed_inputs'], 0)
        self.assertEqual(evidence['embedding']['metadata_only_reingestion']['completed_inputs'], 0)
        self.assertTrue(evidence['index_readback']['passed'])
        boundaries = evidence['evidence_boundaries']
        self.assertTrue(boundaries['live_openai_embeddings_verified'])
        self.assertTrue(boundaries['live_openai_generation_verified'])
        self.assertFalse(boundaries['api_key_recorded'])
        self.assertFalse(boundaries['provider_billing_dashboard_verified'])
        self.assertFalse(boundaries['independently_reproduced'])
        self.assertTrue(boundaries['requested_and_response_models_recorded'])
        requests = evidence['embedding']['first_ingestion']['requests']
        self.assertEqual(sum(row['actual_input_tokens'] for row in requests), 67083)
        self.assertEqual(sum(len(row['input_hashes']) for row in requests), 171)
        self.assertTrue(all(row['requested_model'] == 'text-embedding-3-small'
                            for row in requests))
        self.assertTrue(all(row['response_model'] == 'text-embedding-3-small'
                            for row in requests))
        settings = Settings.local()
        candidate = prepare(settings)
        chunks = {stable_chunk_id(settings.namespace, row['metadata']['document_id'],
                                  row['chunk_key']): row for row in candidate.chunks}
        texts = [chunks[key]['text'] for key in sorted(chunks)]
        self.assertEqual([hashlib.sha256(text.encode()).hexdigest() for text in texts],
                         [value for row in requests for value in row['input_hashes']])
        encoding = tiktoken.encoding_for_model(settings.embedding_model)
        self.assertEqual([sum(len(encoding.encode(text)) for text in texts[start:start + 16])
                          for start in range(0, len(texts), 16)],
                         [row['actual_input_tokens'] for row in requests])
        self.assertTrue(all(status == 'live'
                            for status in evidence['scenario_status'].values()))
        self.assertEqual(evidence['embedding']['two_chunk_edit']['completed_inputs'], 2)
        self.assertEqual(len(evidence['questions']), 4)
        self.assertIn('cannot answer', evidence['questions'][3]['answer'].lower())
        unique = evidence['unique_fact_omission_comparison']
        question = "How is each Wikipedia article split to build RAG's document index?"
        self.assertEqual(unique['question'], question)
        self.assertEqual(unique['removed_page'], {'source_id': '2005.11401v4.pdf',
            'unit': 'page:4', 'removed_chunk_count': 3})
        self.assertTrue(unique['guarded_index_preserved'])
        self.assertTrue(unique['guarded_update_rejected'])
        self.assertTrue(unique['causal_answer_loss_human_reviewed'])
        self.assertEqual(unique['query_embedding']['actual_input_tokens'], 14)
        self.assertEqual(unique['query_embedding']['input_hash'],
                         hashlib.sha256(question.encode()).hexdigest())
        self.assertIn('100 words', unique['guarded']['answer'])
        self.assertIn('do not specify', unique['damaged_clone']['answer'])
        self.assertTrue(any('page:4' in row['units']
                            for row in unique['guarded']['retrieved_sources']))
        self.assertFalse(any('page:4' in row['units']
                             for row in unique['damaged_clone']['retrieved_sources']))
        for view in ('guarded', 'damaged_clone'):
            self.assertEqual(unique[view]['requested_model'], 'gpt-5.6-luna')
            self.assertEqual(unique[view]['response_model'], 'gpt-5.6-luna')
            self.assertTrue(unique[view]['answer_factuality_human_reviewed'])
        self.assertTrue(unique['guarded']['citation_claim_support_human_reviewed'])
        self.assertFalse(unique['damaged_clone']['citation_claim_support_human_reviewed'])
        self.assertEqual(unique['human_review'], {
            'reviewed_by': 'Shyam Sundar',
            'reviewed_on': '2026-09-26',
            'scope': [
                'intact_answer_factuality',
                'intact_page_4_citation_support',
                'damaged_answer_factuality',
                'causal_answer_loss',
            ],
            'unreviewed': ['damaged_answer_citation_support'],
        })
        values = []
        def collect(value):
            if isinstance(value, dict):
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
            elif isinstance(value, str):
                values.append(value)
        collect(evidence)
        self.assertFalse(any(value.startswith('sk-') for value in values))
        self.assertFalse(any(value.startswith(('req_', 'resp_')) for value in values))

    def test_three_pinned_pdfs_and_faulted_page(self):
        settings = Settings.local()
        expected = (settings.root / 'corpus/expected-files.txt').read_text().splitlines()
        self.assertEqual(expected, sorted(p['source_id'] for p in
                                         json.loads(settings.manifest.read_text())['papers']))
        candidate = prepare(settings)
        self.assertEqual(len(candidate.documents), 3)
        self.assertEqual(sum(len(d.expected_units or ()) for d in candidate.documents), 67)
        self.assertEqual(len(candidate.chunks), 171)
        self.assertTrue(candidate.audit['passed'])
        self.assertTrue(candidate.chunk_audit['passed'])
        unique_fact = [row for row in candidate.chunks if '100-word' in row['text'].lower()]
        self.assertTrue(unique_fact)
        self.assertTrue(all(row['metadata']['document_id'] == '2005.11401v4.pdf'
                            and row['metadata']['units'] == ['page:4']
                            for row in unique_fact))
        for evidence in candidate.source_evidence:
            self.assertEqual(len(evidence['sha256']), 64)
            self.assertFalse(evidence['extraction_failed_units'])
            self.assertFalse(evidence['extraction_empty_units'])
        with self.assertRaises(CandidateRejected) as caught:
            prepare(settings, fail_unit=('2005.11401v4.pdf', 'page:2'))
        self.assertIn('missing_chunk_units', {x['code'] for x in caught.exception.audit['findings']})

    def test_installed_style_app_root_options_run_without_api_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Settings.local().root
            state = Path(folder) / 'state'
            runs = Path(folder) / 'runs'
            for command in ('verify-papers', 'dry-run'):
                result = subprocess.run([sys.executable, '-m', 'rag_preflight_faiss_reference',
                    '--app-root', str(root), '--state-root', str(state),
                    '--runs-root', str(runs), command], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['paid_api_calls'], 0)
            self.assertFalse((state / 'ledger.db').exists())

    def test_incomplete_declared_source_scope_fails_before_api(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = root / 'pdfs'
            sources.mkdir()
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'schema_version': 1,
                'scope': 'exactly_listed_pdfs', 'papers': [{'source_id': 'missing.pdf',
                'sha256': 'a' * 64, 'pages': 1}]}))
            settings = replace(Settings.local(), source_root=sources, manifest=manifest)
            with self.assertRaisesRegex(ValueError, 'scope differs'):
                prepare(settings)

    def test_invalid_prices_fail_before_paid_calls(self):
        for price in ('-1', 'nan', 'bad'):
            with self.assertRaises(ValueError):
                replace(Settings.local(), embedding_price_per_million=price)
            result = subprocess.run([sys.executable, '-m', 'rag_preflight_faiss_reference',
                '--embedding-price-per-million', price, 'dry-run'],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('finite nonnegative', result.stderr)

    def test_cli_no_arguments_fail_and_help_succeeds(self):
        executable = sys.executable
        for args, status in (([], 2), (['--help'], 0)):
            result = subprocess.run([executable, '-m', 'rag_preflight_faiss_reference', *args],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, status, result.stderr)


class FaissIntegrationTests(unittest.TestCase):
    def settings(self, folder):
        base = Settings.local()
        root = Path(folder)
        return replace(base, state_root=root / 'state', runs_root=root / 'runs')

    def test_shared_vector_store_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = replace(self.settings(folder), embedding_dimensions=3)
            assert_vector_store_contract(lambda create: FaissStore(
                settings, collection_name='contract', create=create))

    def test_exact_search_rebuilds_from_durable_payloads(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = replace(self.settings(folder), embedding_dimensions=3)
            store = FaissStore(settings)
            store.upsert([Payload('a', 'first', {'source_id': 'a'}, (1.0, 0.0, 0.0)),
                          Payload('b', 'second', {'source_id': 'b'}, (0.0, 1.0, 0.0))])
            self.assertEqual(store.query((0.9, 0.1, 0.0), count=1)[0]['chunk_id'], 'a')
            reopened = FaissStore(settings, create=False)
            self.assertEqual(reopened.ids(), {'a', 'b'})
            self.assertEqual(reopened.query((0.1, 0.9, 0.0), count=1)[0]['chunk_id'], 'b')
            clone = FaissStore(settings, collection_name='isolated')
            clone.upsert(list(reopened.get(reopened.ids()).values()))
            clone.delete(['a'])
            self.assertEqual(clone.ids(), {'b'})
            self.assertEqual(reopened.ids(), {'a', 'b'})
            state = json.loads(reopened.path.read_text())
            state['records']['a']['vector'] = [1.0]
            reopened.path.write_text(json.dumps(state))
            with self.assertRaisesRegex(ValueError, 'dimensions'):
                FaissStore(settings, create=False)

    def test_first_ingestion_noop_metadata_only_omission_and_answer(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = self.settings(folder)
            app = ReferenceApp(settings)
            provider = FakeProvider()
            first = app.ingest(provider)
            self.assertEqual(first['status'], 'committed')
            self.assertEqual(first['provider_type'], 'FakeProvider')
            self.assertIn('live_openai_embedding_calls', first['checks_unverified'])
            self.assertEqual(first['planned_embeddings'], 171)
            self.assertEqual(first['completed_embedding_inputs'], 171)
            self.assertEqual(first['actual_embedding_tokens'], provider.tokens)
            self.assertEqual(first['verified_index_ids'], 171)
            preview = app.preview_text_edit('2005.11401v4.pdf')
            self.assertEqual(preview['planned_embeddings'], 2)
            self.assertEqual(preview['proposed_deletions'], 0)
            self.assertEqual(preview['paid_api_calls'], 0)
            self.assertFalse(preview['source_files_modified'])
            self.assertLess(float(preview['cost_estimate']['estimated_cost']), 0.00134166)
            live_edit = app.demonstrate_text_edit(provider, '2005.11401v4.pdf')
            self.assertEqual(live_edit['planned_embeddings'], 2)
            self.assertEqual(live_edit['completed_embedding_inputs'], 2)
            self.assertTrue(live_edit['clone_vector_store_verified'])
            self.assertFalse(live_edit['main_vector_store_modified'])
            calls = provider.calls
            repeated = app.ingest(provider)
            self.assertEqual(repeated['planned_embeddings'], 0)
            self.assertEqual(provider.calls, calls)
            metadata = app.ingest(provider, metadata_tag='reviewed')
            self.assertEqual(metadata['planned_embeddings'], 0)
            self.assertEqual(metadata['actual_embedding_tokens'], 0)
            self.assertEqual(provider.calls, calls)
            with SQLiteSnapshotStore(app.ledger_path, read_only=True) as ledger:
                self.assertEqual(ledger.counts()['chunks'], 171)
                self.assertTrue(ledger.verify().passed)
            check = app.demonstrate_omission('2005.11401v4.pdf', 'page:2')
            self.assertGreater(check['naive_removed_ids'], 0)
            self.assertTrue(check['guarded']['blocked_before_api_or_vector_write'])
            self.assertTrue(check['guarded_index_preserved'])
            comparison = ReferenceApp(replace(settings, generation_model='fake-test-model')) \
                .compare_omission_answer(provider, check['run_id'],
                                         'What is on the omitted page?')
            self.assertEqual(comparison['removed_ids_verified'], check['naive_removed_ids'])
            self.assertEqual(comparison['query_embedding_calls'], 1)
            self.assertIn('causal_answer_loss_manual_review', comparison['checks_unverified'])
            self.assertTrue(all('distance' not in hit
                for view in comparison['views'].values() for hit in view['retrieved']))
            question = app.ask(provider, 'What does the RAG paper combine?')
            self.assertTrue(question['retrieved'])
            self.assertIn('[1]', question['answer'])
            self.assertEqual(provider.answers, 3)
            self.assertEqual(len(question['retrieved'][0]['units']), 1)
            self.assertEqual(question['retrieval_evidence'], 'SIMULATED_VECTORS_NO_RETRIEVAL_PROOF')
            self.assertTrue(all(row['embedding_evidence'] == 'SIMULATED_VECTORS_NO_RETRIEVAL_PROOF'
                                and 'distance' not in row for row in question['retrieved']))

    def test_interrupted_apply_keeps_ledger_and_recovers_without_new_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = self.settings(folder)
            app = ReferenceApp(settings)
            provider = FakeProvider()
            with self.assertRaisesRegex(RuntimeError, 'Injected failure'):
                app.ingest(provider, fail_after_upserts=True)
            calls = provider.calls
            self.assertTrue((settings.state_root / 'pending-operation.json').exists())
            with SQLiteSnapshotStore(app.ledger_path, read_only=True) as ledger:
                self.assertEqual(ledger.counts()['chunks'], 0)
            self.assertEqual(len(FaissStore(settings).ids()), 171)
            with self.assertRaisesRegex(ValueError, 'pending operation'):
                app.ingest(provider)
            recovered = ReferenceApp(settings).recover(provider)
            self.assertEqual(recovered['status'], 'committed')
            self.assertEqual(provider.calls, calls)
            self.assertFalse((settings.state_root / 'pending-operation.json').exists())
            with SQLiteSnapshotStore(app.ledger_path, read_only=True) as ledger:
                self.assertEqual(ledger.counts()['chunks'], 171)

    def test_second_embedding_batch_failure_persists_first_batch_and_recovers(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = self.settings(folder)
            app = ReferenceApp(settings)
            failing = FailSecondBatchProvider()
            with self.assertRaisesRegex(RuntimeError, 'second embedding batch'):
                app.ingest(failing)
            pending = json.loads((settings.state_root / 'pending-operation.json').read_text())
            self.assertEqual(len(pending['vectors']), 16)
            self.assertEqual(pending['actual_embedding_tokens'], failing.tokens)
            self.assertFalse(FaissStore(settings).ids())
            with SQLiteSnapshotStore(app.ledger_path, read_only=True) as ledger:
                self.assertEqual(ledger.counts()['chunks'], 0)
            recovery = FakeProvider()
            result = ReferenceApp(settings).recover(recovery)
            self.assertEqual(result['completed_embedding_inputs'], 171)
            self.assertEqual(recovery.inputs, 155)
            self.assertEqual(len(FaissStore(settings).ids()), 171)

    def test_readback_drift_blocks_new_ingestion(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = self.settings(folder)
            app = ReferenceApp(settings)
            provider = FakeProvider()
            app.ingest(provider)
            store = FaissStore(settings)
            victim = next(iter(store.ids()))
            store.delete([victim])
            calls = provider.calls
            with self.assertRaises(ValueError):
                app.ingest(provider)
            self.assertEqual(provider.calls, calls)

    def test_estimated_budget_stops_before_embedding_call(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = replace(self.settings(folder), max_estimated_embedding_usd='0.00001')
            provider = FakeProvider()
            with self.assertRaisesRegex(ValueError, 'budget'):
                ReferenceApp(settings).ingest(provider)
            self.assertEqual(provider.calls, 0)
            self.assertFalse((settings.state_root / 'pending-operation.json').exists())

    def test_measured_budget_excess_stays_blocked_on_recovery(self):
        class Inflated(FakeProvider):
            def embed(self, inputs):
                result = super().embed(inputs)
                return EmbeddingBatch(result.vectors, 20_000_000, result.request_id)
        with tempfile.TemporaryDirectory() as folder:
            settings = self.settings(folder)
            provider = Inflated()
            app = ReferenceApp(settings)
            with self.assertRaisesRegex(ValueError, 'Measured embedding usage'):
                app.ingest(provider)
            self.assertEqual(len(FaissStore(settings).ids()), 0)
            self.assertTrue((settings.state_root / 'pending-operation.json').exists())
            with self.assertRaisesRegex(ValueError, 'Measured embedding usage'):
                app.recover(provider)

    def test_crash_after_commit_can_rebuild_committed_payload_file(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = self.settings(folder)
            app = ReferenceApp(settings)
            provider = FakeProvider()
            result = app.ingest(provider)
            calls = provider.calls
            run = settings.runs_root / result['run_id']
            operation = json.loads((run / 'operation.json').read_text())
            (settings.state_root / 'committed-payloads.json').unlink()
            (settings.state_root / 'pending-operation.json').write_text(
                json.dumps(operation))
            recovered = ReferenceApp(settings).recover(provider)
            self.assertEqual(recovered['status'], 'recovered_after_commit')
            self.assertEqual(provider.calls, calls)
            self.assertTrue((settings.state_root / 'committed-payloads.json').exists())
            self.assertFalse((settings.state_root / 'pending-operation.json').exists())
