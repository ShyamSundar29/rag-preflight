"""Shared guarded apply, persisted evidence, restart recovery, and QA."""
from dataclasses import asdict, replace
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from rag_preflight import (AcceptancePolicy, SQLiteSnapshotStore, Snapshot, audit_embeddings,
                           audit_plan_embeddings, build_snapshot,
                           pypdf_receipt,
                           estimate_embedding_cost, reconcile, stable_chunk_id)
from .config import Settings
from .corpus import CandidateRejected, load_manifest, prepare, split_page
from .journal import atomic_json, pending, read_pending, writer_lock
from .provider import OpenAIProvider, Provider, text_hash
from .store import VectorStore, Payload, verify_payloads
from .tokenizer import encoding_for_model


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(event, sort_keys=True, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def json_payload(payloads: dict[str, Payload]) -> dict[str, Any]:
    return {key: asdict(value) for key, value in sorted(payloads.items())}


def parse_payloads(item: dict[str, Any]) -> dict[str, Payload]:
    return {key: Payload(key, row['text'], row['metadata'], tuple(row['vector']))
            for key, row in item.items()}


class ReferenceApp:
    def __init__(self, settings: Settings,
                 store_factory: Callable[..., VectorStore],
                 metadata_builder: Callable[[dict[str, Any], Settings], dict[str, Any]]):
        self.settings = settings
        self.store_factory = store_factory
        self.metadata_builder = metadata_builder

    @property
    def ledger_path(self) -> Path:
        return self.settings.state_root / 'ledger.db'

    @property
    def committed_path(self) -> Path:
        return self.settings.state_root / 'committed-payloads.json'

    def _synthetic_text_edit(self, source_id: str, edited_chunks: int) -> tuple[
            list[dict[str, Any]], Snapshot]:
        if type(edited_chunks) is not int or edited_chunks < 1:
            raise ValueError('edited_chunks must be a positive integer')
        candidate = prepare(self.settings)
        if source_id not in {doc.document_id for doc in candidate.documents}:
            raise ValueError('Source is outside the pinned corpus')
        selected = [row for row in candidate.chunks
                    if row['metadata']['document_id'] == source_id]
        if len(selected) < edited_chunks:
            raise ValueError('Source has too few chunks for this hypothetical edit')
        keys = {row['chunk_key'] for row in selected[:edited_chunks]}
        original = next(doc.source_version for doc in candidate.documents
                        if doc.document_id == source_id)
        synthetic = hashlib.sha256(json.dumps(['synthetic-text-edit-preview', original,
                                               sorted(keys)]).encode()).hexdigest()
        documents = tuple(replace(doc, source_version=synthetic) if doc.document_id == source_id
                          else doc for doc in candidate.documents)
        receipts = tuple(replace(receipt, source_version=synthetic)
                         if receipt.document_id == source_id else receipt
                         for receipt in candidate.receipts)
        recorded = json.loads(self.committed_path.read_text()) if self.committed_path.exists() else {}
        rows = []
        for row in candidate.chunks:
            clone = {'text': row['text'], 'chunk_key': row['chunk_key'],
                     'metadata': dict(row['metadata'])}
            key = stable_chunk_id(self.settings.namespace, clone['metadata']['document_id'],
                                  clone['chunk_key'])
            if key in recorded and 'review_tag' in recorded[key]['metadata']:
                clone['metadata']['review_tag'] = recorded[key]['metadata']['review_tag']
            if clone['metadata']['document_id'] == source_id:
                clone['metadata']['source_version'] = synthetic
                if clone['chunk_key'] in keys:
                    clone['text'] += ' Hypothetical revised source sentence for plan-only evidence.'
            rows.append(clone)
        policy = AcceptancePolicy(required_metadata=('source', 'document_id', 'source_version',
                                                      'units', 'namespace'),
                                  require_documents=True, require_namespace=True)
        snapshot = build_snapshot(documents, receipts, rows, policy=policy,
                                  namespace=self.settings.namespace,
                                  pipeline_id=self.settings.pipeline_id,
                                  embedding_model=self.settings.embedding_model)
        return rows, snapshot

    def preview_text_edit(self, source_id: str, *, edited_chunks: int = 2) -> dict[str, Any]:
        """Plan-only synthetic two-chunk edit; does not assert a PDF was edited."""
        rows, snapshot = self._synthetic_text_edit(source_id, edited_chunks)
        with SQLiteSnapshotStore(self.ledger_path, read_only=True) as ledger:
            store = self.store_factory(self.settings, create=False)
            self._prior(ledger, store)
            if ledger.counts()['chunks'] == 0:
                raise ValueError('First ingest the original corpus before an edit preview')
            plan = ledger.plan(snapshot).update
        encoding = encoding_for_model(self.settings.embedding_model)
        counts = {stable_chunk_id(self.settings.namespace, row['metadata']['document_id'],
                                  row['chunk_key']): len(encoding.encode(row['text']))
                  for row in rows}
        cost = estimate_embedding_cost(plan,
            price_per_million_tokens=self.settings.embedding_price_per_million,
            currency='USD', token_counts=counts,
            comparison_ids=tuple(sorted(counts)),
            comparison_scope='hypothetical complete three-paper candidate batch')
        return {'scenario': 'synthetic_text_edit_preview', 'source_id': source_id,
                'synthetic_source_version': True, 'source_files_modified': False,
                'vector_store_modified': False, 'paid_api_calls': 0,
                'edited_chunk_inputs': edited_chunks,
                'planned_embeddings': len(plan.embed_ids),
                'planned_upserts': len(plan.upsert_ids),
                'proposed_deletions': len(plan.removed),
                'cost_estimate': cost.to_dict(),
                'checks_unverified': ['real_document_edit', 'live_openai_requests',
                                      'actual_provider_billing']}

    def demonstrate_text_edit(self, provider: Provider, source_id: str, *,
                              edited_chunks: int = 2) -> dict[str, Any]:
        """Embed a synthetic selective edit in an isolated clone, never the main index."""
        run_id = uuid4().hex
        run_dir = self.settings.runs_root / run_id
        run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        with writer_lock(self.settings.state_root):
            if read_pending(self.settings.state_root) is not None:
                raise ValueError('Recover pending operation before the selective-edit demonstration')
            rows, snapshot = self._synthetic_text_edit(source_id, edited_chunks)
            with SQLiteSnapshotStore(self.ledger_path, read_only=True) as ledger:
                main = self.store_factory(self.settings, create=False)
                prior = self._prior(ledger, main)
                if not prior:
                    raise ValueError('First ingest the complete three-paper corpus')
                plan = ledger.plan(snapshot).update
                if len(plan.embed_ids) != edited_chunks or plan.removed:
                    raise ValueError('Synthetic edit did not produce the expected selective plan')
                chunks = {stable_chunk_id(self.settings.namespace,
                            row['metadata']['document_id'], row['chunk_key']): row for row in rows}
                texts = [chunks[key]['text'] for key in plan.embed_ids]
                encoding = encoding_for_model(self.settings.embedding_model)
                counts = {key: len(encoding.encode(row['text'])) for key, row in chunks.items()}
                cost = estimate_embedding_cost(plan,
                    price_per_million_tokens=self.settings.embedding_price_per_million,
                    currency='USD', token_counts=counts,
                    comparison_ids=tuple(sorted(chunks)),
                    comparison_scope='synthetic complete three-paper candidate batch')
                if cost.estimated_cost > Decimal(self.settings.max_estimated_embedding_usd):
                    raise ValueError('Estimated embedding spend exceeds experiment budget')
                embedded = provider.embed(texts)
                if len(embedded.vectors) != len(plan.embed_ids):
                    raise ValueError('Provider returned a different number of selective-edit vectors')
                states = {chunk.chunk_id: chunk for chunk in plan.target.chunks}
                records = [dict(chunk_id=key, vector=vector,
                                embedding_model=self.settings.embedding_model,
                                pipeline_id=self.settings.pipeline_id,
                                input_hash=states[key].text_hash)
                           for key, vector in zip(plan.embed_ids, embedded.vectors)]
                audit = audit_plan_embeddings(plan, records,
                    dimensions=self.settings.embedding_dimensions, mode='embed')
                audit.raise_for_errors()
                atomic_json(run_dir / 'embedding-audit.json', audit.to_dict())
                input_hashes = [text_hash(text) for text in texts]
                append_event(run_dir / 'embedding-events.jsonl', {
                    'stage': 'synthetic_selective_edit',
                    'requested_model': embedded.requested_model,
                    'response_model': embedded.response_model,
                    'input_hashes': input_hashes, 'count': len(texts),
                    'actual_tokens': embedded.actual_tokens,
                    'request_id': embedded.request_id, 'successful': True})
                replacement = dict(zip(plan.embed_ids, embedded.vectors))
                target = {}
                for key, row in chunks.items():
                    vector = replacement.get(key)
                    if vector is None:
                        if key not in prior:
                            raise ValueError(f'No reusable committed vector for {key}')
                        vector = prior[key].vector
                    metadata = self.metadata_builder({**row['metadata'],
                                                      'chunk_key': row['chunk_key']},
                                                     self.settings)
                    target[key] = Payload(key, row['text'], metadata, tuple(vector))
                clone = self.store_factory(self.settings,
                    collection_name='edit_' + run_id[:20])
                clone.upsert(list(prior.values()))
                clone.upsert([target[key] for key in plan.upsert_ids])
                clone_check = verify_payloads(clone, target, complete_ids=set(target))
                main_check = verify_payloads(main, prior, complete_ids=set(prior))
                if not clone_check['passed'] or not main_check['passed']:
                    raise ValueError('Selective-edit clone or guarded main-index verification failed')
                output = {'scenario': 'synthetic_selective_edit_live', 'run_id': run_id,
                    'source_id': source_id, 'source_files_modified': False,
                    'main_vector_store_modified': False, 'clone_vector_store_verified': True,
                    'planned_embeddings': len(plan.embed_ids),
                    'completed_embedding_inputs': len(embedded.vectors),
                    'planned_upserts': len(plan.upsert_ids), 'proposed_deletions': 0,
                    'actual_embedding_tokens': embedded.actual_tokens,
                    'requested_model': embedded.requested_model,
                    'response_model': embedded.response_model,
                    'input_hashes': input_hashes, 'cost_estimate': cost.to_dict(),
                    'checks_unverified': ['real_document_edit', 'actual_provider_billing'] +
                        ([] if isinstance(provider, OpenAIProvider)
                         else ['live_openai_embedding_calls'])}
                atomic_json(run_dir / 'selective-edit.json', output)
                return output

    def _prior(self, ledger: SQLiteSnapshotStore, store: VectorStore) -> dict[str, Payload]:
        recorded = json.loads(self.committed_path.read_text()) if self.committed_path.exists() else {}
        prior = parse_payloads(recorded)
        expected_ids = set(ledger.chunk_ids())
        if expected_ids != set(prior):
            raise ValueError('Ledger and independently recorded committed payload IDs differ')
        report = reconcile(expected_ids, store.ids(), namespace=self.settings.namespace,
                           inventory_complete=True)
        if not report.passed:
            raise ValueError(f'Complete ledger/vector store ID reconciliation failed: {report.to_dict()}')
        check = verify_payloads(store, prior, complete_ids=expected_ids)
        if not check['passed']:
            raise ValueError('vector store read-back differs from committed payload evidence')
        return prior

    def _record_run(self, run_dir: Path, item: dict[str, Any]) -> None:
        atomic_json(run_dir / 'operation.json', item)

    def _complete(self, item: dict[str, Any], ledger: SQLiteSnapshotStore,
                  store: VectorStore) -> dict[str, Any]:
        vectors = item['vectors']
        if set(item['embed_ids']) - set(vectors):
            raise ValueError('Operation has missing successful embeddings')
        target: dict[str, Payload] = {}
        for key, row in item['candidate_payloads'].items():
            vector = vectors.get(key) or item['prior_vectors'].get(key)
            if vector is None:
                raise ValueError(f'Missing vector or reusable committed vector: {key}')
            target[key] = Payload(key, row['text'], row['metadata'], tuple(vector))
        return json_payload(target)

    def _finish(self, item: dict[str, Any], ledger: SQLiteSnapshotStore,
                store: VectorStore, *, fail_after_upserts: bool = False) -> dict[str, Any]:
        actual_cost = (Decimal(self.settings.embedding_price_per_million)
                       * item['actual_embedding_tokens'] / Decimal(1_000_000))
        if actual_cost > Decimal(self.settings.max_estimated_embedding_usd):
            raise ValueError('Measured embedding usage exceeded experiment budget; no vector writes')
        candidate = Snapshot.from_dict(item['candidate_snapshot'])
        plan = ledger.plan(candidate)
        if plan.base_revision != item['base_revision'] or plan.plan_id != item['plan_id']:
            raise ValueError('Pending operation is stale; explicit operator recovery required')
        if set(plan.update.embed_ids) != set(item['embed_ids']) or set(plan.update.removed) != set(item['removed_ids']):
            raise ValueError('Pending operation does not match the current guarded plan')
        target = parse_payloads(self._complete(item, ledger, store))
        if set(target) != {c.chunk_id for c in candidate.chunks}:
            raise ValueError('Candidate payload IDs do not match validated snapshot')
        upserts = [target[key] for key in plan.update.upsert_ids]
        store.upsert(upserts)
        append_event(Path(item['run_dir']) / 'write-events.jsonl',
                     {'stage': 'upsert_returned', 'count': len(upserts)})
        check = verify_payloads(store, {p.chunk_id: p for p in upserts})
        atomic_json(Path(item['run_dir']) / 'upsert-verification.json', check)
        if not check['passed']:
            raise ValueError('vector store upsert read-back failed; ledger unchanged')
        if fail_after_upserts:
            raise RuntimeError('Injected failure after upsert read-back, before deletions/ledger commit')
        store.delete(plan.update.removed)
        append_event(Path(item['run_dir']) / 'write-events.jsonl',
                     {'stage': 'delete_returned', 'count': len(plan.update.removed)})
        final = verify_payloads(store, target, complete_ids=set(target))
        atomic_json(Path(item['run_dir']) / 'verification.json', final)
        if not final['passed']:
            raise ValueError('Final vector store read-back failed; ledger unchanged')
        ledger.assert_base(plan)
        revision = ledger.commit(plan)
        ledger.verify().raise_for_errors()
        if set(ledger.chunk_ids()) != set(target):
            raise ValueError('Ledger inventory differs from completed vector store state')
        atomic_json(self.committed_path, json_payload(target))
        item['status'] = 'committed'
        item['committed_revision'] = revision
        self._record_run(Path(item['run_dir']), item)
        atomic_json(pending(self.settings.state_root), item)
        summary = {'status': 'committed', 'run_id': item['run_id'], 'ledger_revision': revision,
                   'provider_type': item['provider_type'],
                   'planned_embeddings': len(item['embed_ids']),
                   'completed_embedding_inputs': len(item['vectors']),
                   'actual_embedding_tokens': item['actual_embedding_tokens'],
                   'proposed_deletions': len(item['removed_ids']),
                   'verified_index_ids': len(target), 'vector_readback_passed': True,
                   'checks_unverified': item['embedding_checks_unverified']}
        atomic_json(Path(item['run_dir']) / 'summary.json', summary)
        pending(self.settings.state_root).unlink()
        return summary

    def _embed_remaining(self, item: dict[str, Any], provider: Provider,
                         plan: Any) -> None:
        states = {chunk.chunk_id: chunk for chunk in plan.update.target.chunks}
        for position in range(0, len(item['embed_ids']), 16):
            keys = [key for key in item['embed_ids'][position:position + 16]
                    if key not in item['vectors']]
            if not keys:
                continue
            texts = [item['candidate_payloads'][key]['text'] for key in keys]
            try:
                result = provider.embed(texts)
            except Exception as exc:
                append_event(Path(item['run_dir']) / 'embedding-events.jsonl',
                    {'stage': 'ingestion', 'model': self.settings.embedding_model,
                     'input_hashes': [text_hash(text) for text in texts],
                     'count': len(keys), 'successful': False,
                     'error_type': type(exc).__name__})
                raise
            if len(result.vectors) != len(keys):
                raise ValueError('Provider returned a different number of vectors')
            # Correspondence for the complete plan is checked after all batches.
            for key, vector in zip(keys, result.vectors):
                item['vectors'][key] = list(vector)
            item['actual_embedding_tokens'] += result.actual_tokens
            actual_cost = (Decimal(self.settings.embedding_price_per_million)
                           * item['actual_embedding_tokens'] / Decimal(1_000_000))
            append_event(Path(item['run_dir']) / 'embedding-events.jsonl',
                {'stage': 'ingestion', 'model': self.settings.embedding_model,
                 'requested_model': result.requested_model,
                 'response_model': result.response_model,
                 'input_hashes': [text_hash(text) for text in texts],
                 'count': len(keys), 'actual_tokens': result.actual_tokens,
                 'request_id': result.request_id, 'successful': True})
            atomic_json(pending(self.settings.state_root), item)
            if actual_cost > Decimal(self.settings.max_estimated_embedding_usd):
                raise ValueError('Measured embedding usage exceeded experiment budget; no vector writes')
            self._record_run(Path(item['run_dir']), item)
        records = [dict(chunk_id=key, vector=item['vectors'][key],
                        embedding_model=self.settings.embedding_model,
                        pipeline_id=self.settings.pipeline_id,
                        input_hash=states[key].text_hash)
                   for key in item['embed_ids']]
        report = audit_plan_embeddings(plan.update, records,
            dimensions=self.settings.embedding_dimensions, mode='embed')
        atomic_json(Path(item['run_dir']) / 'embedding-audit.json', report.to_dict())
        report.raise_for_errors()
        item['status'] = 'embeddings_ready'
        atomic_json(pending(self.settings.state_root), item)
        self._record_run(Path(item['run_dir']), item)

    def ingest(self, provider: Provider, *, metadata_tag: str | None = None,
               fail_after_upserts: bool = False) -> dict[str, Any]:
        run_id = uuid4().hex
        run_dir = self.settings.runs_root / run_id
        run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        with writer_lock(self.settings.state_root):
            if read_pending(self.settings.state_root) is not None:
                raise ValueError('A pending operation exists; run recover before a new ingestion')
            try:
                candidate = prepare(self.settings, metadata_tag=metadata_tag)
            except CandidateRejected as exc:
                atomic_json(run_dir / 'ingestion-audit.json', exc.audit)
                atomic_json(run_dir / 'chunk-audit.json', exc.chunk_audit)
                raise
            atomic_json(run_dir / 'source-evidence.json',
                        {'papers': list(candidate.source_evidence), 'scope_complete': True})
            atomic_json(run_dir / 'ingestion-audit.json', candidate.audit)
            atomic_json(run_dir / 'chunk-audit.json', candidate.chunk_audit)
            with SQLiteSnapshotStore(self.ledger_path) as ledger:
                store = self.store_factory(self.settings)
                prior = self._prior(ledger, store)
                plan = ledger.plan(candidate.snapshot)
                chunks = {stable_chunk_id(self.settings.namespace,
                            row['metadata']['document_id'], row['chunk_key']): row
                          for row in candidate.chunks}
                if len(chunks) != len(candidate.chunks):
                    raise ValueError('Duplicate candidate chunk identities')
                encoding = encoding_for_model(self.settings.embedding_model)
                counts = {key: len(encoding.encode(row['text'])) for key, row in chunks.items()}
                cost = estimate_embedding_cost(plan.update,
                    price_per_million_tokens=self.settings.embedding_price_per_million,
                    currency='USD', token_counts=counts,
                    comparison_ids=tuple(sorted(chunks)),
                    comparison_scope='complete listed three-paper candidate batch')
                atomic_json(run_dir / 'plan.json', plan.update.to_dict())
                atomic_json(run_dir / 'cost-estimate.json', cost.to_dict())
                atomic_json(run_dir / 'config.json', {'namespace': self.settings.namespace,
                    'pipeline_id': self.settings.pipeline_id,
                    'embedding_model': self.settings.embedding_model,
                    'generation_model': self.settings.generation_model,
                    'provider_type': type(provider).__name__,
                    'live_openai_provider': isinstance(provider, OpenAIProvider),
                    'papers': len(candidate.documents), 'chunks': len(chunks),
                    'tokenizer': 'tiktoken.encoding_for_model',
                    'embedding_price_per_million': self.settings.embedding_price_per_million,
                    'max_estimated_embedding_usd': self.settings.max_estimated_embedding_usd})
                if cost.estimated_cost > Decimal(self.settings.max_estimated_embedding_usd):
                    raise ValueError('Estimated embedding spend exceeds experiment budget')
                item: dict[str, Any] = {'schema_version': 1, 'status': 'prepared',
                    'run_id': run_id, 'run_dir': str(run_dir),
                    'provider_type': type(provider).__name__,
                    'embedding_checks_unverified':
                        ['historical_openai_model_execution_proof'] +
                        ([] if isinstance(provider, OpenAIProvider)
                         else ['live_openai_embedding_calls']),
                    'base_revision': plan.base_revision, 'plan_id': plan.plan_id,
                    'candidate_snapshot': candidate.snapshot.to_dict(),
                    'source_hashes': {e['source_id']: e['sha256'] for e in candidate.source_evidence},
                    'embed_ids': list(plan.update.embed_ids),
                    'removed_ids': list(plan.update.removed),
                    'candidate_payloads': {key: {'text': row['text'],
                        'metadata': self.metadata_builder({**row['metadata'], 'chunk_key': row['chunk_key']},
                                                    self.settings)}
                        for key, row in chunks.items()},
                    'prior_vectors': {key: list(row.vector) for key, row in prior.items()},
                    'vectors': {}, 'actual_embedding_tokens': 0}
                atomic_json(pending(self.settings.state_root), item)
                self._record_run(run_dir, item)
                self._embed_remaining(item, provider, plan)
                return self._finish(item, ledger, store,
                                    fail_after_upserts=fail_after_upserts)

    def recover(self, provider: Provider) -> dict[str, Any]:
        with writer_lock(self.settings.state_root):
            item = read_pending(self.settings.state_root)
            if item is None:
                raise ValueError('No pending operation to recover')
            if item.get('schema_version') != 1:
                raise ValueError('Unsupported operation journal schema')
            for name, original in item['source_hashes'].items():
                source = self.settings.source_root / name
                if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != original:
                    raise ValueError(f'Source changed since pending operation: {name}')
            with SQLiteSnapshotStore(self.ledger_path) as ledger:
                store = self.store_factory(self.settings)
                candidate = Snapshot.from_dict(item['candidate_snapshot'])
                if ledger.revision != item['base_revision']:
                    # Crash after ledger commit: accept only a no-op plan and full
                    # read-back of the recorded target, not an inferred success.
                    newer = ledger.plan(candidate)
                    if newer.update.upsert_ids or newer.update.removed:
                        raise ValueError('Ledger changed independently; manual recovery required')
                    target = parse_payloads(self._complete(item, ledger, store))
                    verification = verify_payloads(store, target, complete_ids=set(target))
                    if not verification['passed']:
                        raise ValueError('Post-commit vector store read-back failed; manual recovery required')
                    atomic_json(self.committed_path, json_payload(target))
                    pending(self.settings.state_root).unlink()
                    summary = {'status': 'recovered_after_commit', 'run_id': item['run_id'],
                               'ledger_revision': ledger.revision,
                               'verified_index_ids': len(target)}
                    atomic_json(Path(item['run_dir']) / 'recovery.json', summary)
                    return summary
                plan = ledger.plan(candidate)
                if plan.plan_id != item['plan_id']:
                    raise ValueError('Replanned operation changed; manual recovery required')
                self._embed_remaining(item, provider, plan)
                result = self._finish(item, ledger, store)
                atomic_json(Path(item['run_dir']) / 'recovery.json', result)
                return result

    def ask(self, provider: Provider, question: str) -> dict[str, Any]:
        if not question.strip():
            raise ValueError('Question is empty')
        with writer_lock(self.settings.state_root):
            if read_pending(self.settings.state_root) is not None:
                raise ValueError('Pending write must recover before a verified answer')
            with SQLiteSnapshotStore(self.ledger_path, read_only=True) as ledger:
                store = self.store_factory(self.settings, create=False)
                self._prior(ledger, store)
                run_id = uuid4().hex
                run_dir = self.settings.runs_root / run_id
                run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
                query = provider.embed([question])
                if len(query.vectors) != 1:
                    raise ValueError('Query embedding count mismatch')
                query_audit = audit_embeddings(['question'],
                    [{'chunk_id': 'question', 'vector': query.vectors[0]}],
                    dimensions=self.settings.embedding_dimensions)
                atomic_json(run_dir / 'query-embedding-audit.json', query_audit.to_dict())
                query_audit.raise_for_errors()
                append_event(run_dir / 'embedding-events.jsonl',
                    {'stage': 'query', 'model': self.settings.embedding_model,
                     'requested_model': query.requested_model,
                     'response_model': query.response_model,
                     'input_hashes': [text_hash(question)], 'count': 1,
                     'actual_tokens': query.actual_tokens,
                     'request_id': query.request_id, 'successful': True})
                hits = store.query(query.vectors[0], count=5)
                citations = []
                contexts = []
                live_embeddings = isinstance(provider, OpenAIProvider)
                for index, hit in enumerate(hits, 1):
                    md = hit['metadata']
                    units = json.loads(md['units_json'])
                    citation = {'number': index, 'source_id': md['source_id'],
                                'units': units, 'chunk_id': hit['chunk_id'],
                                'embedding_evidence': ('openai_request_recorded' if live_embeddings
                                                       else 'SIMULATED_VECTORS_NO_RETRIEVAL_PROOF')}
                    if live_embeddings:
                        citation['distance'] = hit['distance']
                    citations.append(citation)
                    contexts.append((str(index), hit['text']))
                if not contexts:
                    answer = 'I cannot answer from the indexed papers.'
                    generation: dict[str, Any] = {'called': False, 'input_tokens': 0,
                                                  'output_tokens': 0}
                else:
                    generated = provider.answer(question, contexts)
                    append_event(run_dir / 'generation-events.jsonl',
                        {'model': self.settings.generation_model,
                         'requested_model': generated.requested_model,
                         'response_model': generated.response_model,
                         'input_tokens': generated.input_tokens,
                         'output_tokens': generated.output_tokens,
                         'response_id': generated.response_id, 'successful': True})
                    allowed = set(range(1, len(contexts) + 1))
                    claimed = {int(n) for n in re.findall(r'\[(\d+)\]', generated.text)}
                    if not claimed <= allowed:
                        raise ValueError('Generated answer cites an unprovided passage')
                    if not claimed and 'cannot answer' not in generated.text.lower():
                        raise ValueError('Generated factual answer has no passage citation')
                    answer = generated.text
                    generation = {'called': True, 'model': self.settings.generation_model,
                                  'requested_model': generated.requested_model,
                                  'response_model': generated.response_model,
                                  'input_tokens': generated.input_tokens,
                                  'output_tokens': generated.output_tokens,
                                  'response_id': generated.response_id,
                                  'claimed_citation_numbers': sorted(claimed)}
                result = {'run_id': run_id, 'question': question, 'answer': answer,
                          'provider_type': type(provider).__name__,
                          'retrieval_evidence': ('live_openai_embedding_request_recorded' if live_embeddings
                                                 else 'SIMULATED_VECTORS_NO_RETRIEVAL_PROOF'),
                          'retrieved': citations, 'generation': generation,
                          'checks_unverified': ['citation_claim_support', 'answer_factuality'] +
                              ([] if isinstance(provider, OpenAIProvider)
                               else ['live_openai_embedding_and_generation_calls'])}
                atomic_json(run_dir / 'answer.json', result)
                return result

    def demonstrate_omission(self, source_id: str, unit: str) -> dict[str, Any]:
        """Real deletion on an isolated cloned collection, guarded rejection on main."""
        papers = {paper['source_id']: paper for paper in load_manifest(self.settings)}
        if source_id not in papers:
            raise ValueError('Omission source is outside the declared PDF scope')
        source_path = self.settings.source_root / source_id
        if (source_path.is_symlink() or hashlib.sha256(source_path.read_bytes()).hexdigest()
                != papers[source_id]['sha256']):
            raise ValueError('Omission source differs from pinned source evidence')
        with writer_lock(self.settings.state_root):
            if read_pending(self.settings.state_root) is not None:
                raise ValueError('Recover pending operation before comparison')
            with SQLiteSnapshotStore(self.ledger_path, read_only=True) as ledger:
                main = self.store_factory(self.settings)
                prior = self._prior(ledger, main)
                if not prior:
                    raise ValueError('First ingest the complete three-paper corpus')
                run_id = uuid4().hex
                run_dir = self.settings.runs_root / run_id
                run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
                clone = self.store_factory(self.settings, collection_name='naive_' + run_id[:20])
                clone.upsert(list(prior.values()))
                extraction = pypdf_receipt(source_path,
                                           document_id=source_id)
                if unit not in (extraction.document.expected_units or ()):
                    raise ValueError('Omission unit is outside the PDF page inventory')
                # This is the naive replacement inventory: trust successful
                # extraction output, then delete IDs missing from that output.
                naive_chunks = [row for row in extraction.chunks(
                    lambda page: split_page(page, self.settings), source=source_id)
                    if unit not in row['metadata']['units']]
                naive_ids = {stable_chunk_id(self.settings.namespace, source_id,
                                              row['chunk_key']) for row in naive_chunks}
                old_source_ids = {key for key, row in prior.items()
                                  if row.metadata['source_id'] == source_id}
                selected = sorted(old_source_ids - naive_ids)
                if not selected:
                    raise ValueError('Omission scenario selected no existing representation')
                clone.delete(selected)
                naive = verify_payloads(clone,
                    {key: row for key, row in prior.items() if key not in selected},
                    complete_ids=set(prior) - set(selected))
                if not naive['passed']:
                    raise ValueError('Naive-clone manipulation did not produce expected index state')
                try:
                    prepare(self.settings, fail_unit=(source_id, unit))
                except CandidateRejected as exc:
                    guarded = {'blocked_before_api_or_vector_write': True,
                               'finding_codes': sorted({f['code'] for f in exc.audit['findings']})}
                    atomic_json(run_dir / 'guarded-rejection.json', exc.audit)
                else:
                    raise ValueError('Faulted source unexpectedly passed the guard')
                preserved = verify_payloads(main, prior, complete_ids=set(prior))
                if not preserved['passed']:
                    raise ValueError('Guarded index changed during omission demonstration')
                result = {'run_id': run_id, 'source_id': source_id, 'unit': unit,
                          'naive_candidate_ids_for_source': len(naive_ids),
                          'naive_removed_ids': len(selected),
                          'naive_remaining_ids': len(clone.ids()),
                          'guarded': guarded, 'guarded_index_preserved': True,
                          'comparison_scope': 'isolated copy versus guarded main collection',
                          'checks_unverified': ['retrieval_impact_of_removed_page']}
                atomic_json(run_dir / 'summary.json', result)
                return result

    def compare_omission_answer(self, provider: Provider, omission_run_id: str,
                                question: str) -> dict[str, Any]:
        """Read-only same-query comparison after an omission clone exists.

        A missing page does not guarantee answer loss: another indexed page may
        contain the same fact. The observed answers require human review.
        """
        if not re.fullmatch(r'[0-9a-f]{32}', omission_run_id):
            raise ValueError('Use the omission run ID returned by demonstrate-omission')
        if not isinstance(question, str) or not question.strip():
            raise ValueError('Supply a nonblank question')
        if not self.settings.generation_model:
            raise ValueError('Choose an explicit generation model for the comparison')
        omission_path = self.settings.runs_root / omission_run_id / 'summary.json'
        omission = json.loads(omission_path.read_text())
        if (omission.get('run_id') != omission_run_id
                or omission.get('comparison_scope') != 'isolated copy versus guarded main collection'
                or not omission.get('guarded_index_preserved')):
            raise ValueError('Omission run evidence is incomplete or inconsistent')
        with writer_lock(self.settings.state_root):
            if read_pending(self.settings.state_root) is not None:
                raise ValueError('Recover pending operation before question comparison')
            with SQLiteSnapshotStore(self.ledger_path, read_only=True) as ledger:
                main = self.store_factory(self.settings, create=False)
                prior = self._prior(ledger, main)
                removed = {key for key, row in prior.items()
                           if row.metadata['source_id'] == omission['source_id']
                           and omission['unit'] in json.loads(row.metadata['units_json'])}
                if len(removed) != omission['naive_removed_ids']:
                    raise ValueError('Omission clone scope no longer matches committed inventory')
                clone = self.store_factory(self.settings,
                    collection_name='naive_' + omission_run_id[:20], create=False)
                clone_expected = {key: row for key, row in prior.items() if key not in removed}
                clone_check = verify_payloads(clone, clone_expected,
                                              complete_ids=set(clone_expected))
                if not clone_check['passed']:
                    raise ValueError('Omission clone changed since its verified deletion')
                run_id = uuid4().hex
                run_dir = self.settings.runs_root / run_id
                run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
                query = provider.embed([question])
                query_audit = audit_embeddings(['question'],
                    [{'chunk_id': 'question', 'vector': query.vectors[0]}]
                    if len(query.vectors) == 1 else [],
                    dimensions=self.settings.embedding_dimensions)
                atomic_json(run_dir / 'query-embedding-audit.json', query_audit.to_dict())
                query_audit.raise_for_errors()
                append_event(run_dir / 'embedding-events.jsonl',
                    {'stage': 'shared_comparison_query', 'model': self.settings.embedding_model,
                     'requested_model': query.requested_model,
                     'response_model': query.response_model,
                     'input_hashes': [text_hash(question)], 'count': 1,
                     'actual_tokens': query.actual_tokens,
                     'request_id': query.request_id, 'successful': True})
                live = isinstance(provider, OpenAIProvider)
                views: dict[str, Any] = {}
                for label, store in [('guarded', main), ('omission_clone', clone)]:
                    hits = store.query(query.vectors[0], count=5)
                    contexts = [(str(n), hit['text']) for n, hit in enumerate(hits, 1)]
                    rows = []
                    for n, hit in enumerate(hits, 1):
                        row = {'number': n, 'source_id': hit['metadata']['source_id'],
                               'units': json.loads(hit['metadata']['units_json']),
                               'chunk_id': hit['chunk_id'],
                               'embedding_evidence': ('openai_request_recorded' if live
                                                      else 'SIMULATED_VECTORS_NO_RETRIEVAL_PROOF')}
                        if live:
                            row['distance'] = hit['distance']
                        rows.append(row)
                    if contexts:
                        generated = provider.answer(question, contexts)
                        claimed = {int(n) for n in re.findall(r'\[(\d+)\]', generated.text)}
                        if not claimed <= set(range(1, len(contexts) + 1)):
                            raise ValueError('Generated comparison answer cites an unprovided passage')
                        if not claimed and 'cannot answer' not in generated.text.lower():
                            raise ValueError('Generated comparison answer has no passage citation')
                        answer = generated.text
                        generation = {'called': True, 'input_tokens': generated.input_tokens,
                                      'output_tokens': generated.output_tokens,
                                      'response_id': generated.response_id,
                                      'requested_model': generated.requested_model,
                                      'response_model': generated.response_model,
                                      'claimed_citation_numbers': sorted(claimed)}
                        append_event(run_dir / 'generation-events.jsonl',
                            {'index': label, 'model': self.settings.generation_model,
                             'requested_model': generated.requested_model,
                             'response_model': generated.response_model,
                             'input_tokens': generated.input_tokens,
                             'output_tokens': generated.output_tokens,
                             'response_id': generated.response_id, 'successful': True})
                    else:
                        answer = 'I cannot answer from the indexed papers.'
                        generation = {'called': False, 'input_tokens': 0,
                                      'output_tokens': 0}
                    views[label] = {'retrieved': rows, 'answer': answer,
                                    'generation': generation}
                result = {'run_id': run_id, 'omission_run_id': omission_run_id,
                          'question': question, 'provider_type': type(provider).__name__,
                          'retrieval_evidence': ('live_openai_embedding_request_recorded' if live
                                                 else 'SIMULATED_VECTORS_NO_RETRIEVAL_PROOF'),
                          'removed_ids_verified': len(removed),
                          'query_embedding_calls': 1, 'views': views,
                          'checks_unverified': ['answer_factuality', 'citation_claim_support',
                                                'causal_answer_loss_manual_review'] +
                              ([] if live else ['live_openai_embedding_and_generation_calls'])}
                atomic_json(run_dir / 'comparison.json', result)
                return result
