"""Deterministic manifests and advisory update plans. No database operations."""
from dataclasses import asdict, dataclass
from collections.abc import Callable, Iterable, Mapping
from typing import Any
import hashlib
import json
import math
from pathlib import Path
import os
import tempfile

from .ingestion import AcceptancePolicy, DocumentSpec, ExtractionReceipt, ValidationReport, _name, audit_ingestion, canonical_json


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def stable_chunk_id(namespace: str, document_id: str, chunk_key: str) -> str:
    """Identity is scoped by namespace, document and caller-supplied stable key.

    Raw text/version are deliberately not part of identity. A changed logical
    chunk can overwrite its existing vector; separate documents never dedupe IDs.
    """
    for field, value in (('namespace', namespace), ('document_id', document_id), ('chunk_key', chunk_key)):
        _name(value, field)
    return _digest(['rag-preflight.chunk.v1', namespace, document_id, chunk_key])


@dataclass(frozen=True, order=True)
class DocumentState:
    document_id: str
    source_version: str


@dataclass(frozen=True, order=True)
class ChunkState:
    chunk_id: str
    document_id: str
    chunk_key: str
    text_hash: str
    metadata_hash: str
    embedding_hash: str


def _hash_string(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


@dataclass(frozen=True)
class Snapshot:
    """Hash-only inventory from a validated batch, or merged committed inventory.

    Treat persisted snapshots as trusted application state. Hashes detect changes
    and accidental corruption, not malicious edits or parser dishonesty.
    """
    namespace: str
    pipeline_id: str
    embedding_model: str
    documents: tuple[DocumentState, ...]
    chunks: tuple[ChunkState, ...]

    def __post_init__(self) -> None:
        for field in ('namespace', 'pipeline_id', 'embedding_model'):
            _name(getattr(self, field), field)
        docs, chunks = tuple(self.documents), tuple(self.chunks)
        if any(not isinstance(d, DocumentState) for d in docs) or any(not isinstance(c, ChunkState) for c in chunks):
            raise ValueError('Invalid snapshot record types')
        for doc in docs:
            _name(doc.document_id, 'document_id')
            _name(doc.source_version, 'source_version')
        ids = {d.document_id for d in docs}
        if len(ids) != len(docs) or len({c.chunk_id for c in chunks}) != len(chunks):
            raise ValueError('Duplicate snapshot document or chunk IDs')
        for chunk in chunks:
            if chunk.document_id not in ids:
                raise ValueError('Snapshot chunk references unknown document')
            if chunk.chunk_id != stable_chunk_id(self.namespace, chunk.document_id, chunk.chunk_key):
                raise ValueError('Snapshot chunk ID does not match its identity')
            if not all(_hash_string(getattr(chunk, f)) for f in ('text_hash', 'metadata_hash', 'embedding_hash')):
                raise ValueError('Snapshot contains an invalid hash')
            if chunk.embedding_hash != _digest([chunk.text_hash, self.embedding_model, self.pipeline_id]):
                raise ValueError('Snapshot embedding hash does not match configuration')
        object.__setattr__(self, 'documents', tuple(sorted(docs)))
        object.__setattr__(self, 'chunks', tuple(sorted(chunks)))

    def _payload(self) -> dict[str, Any]:
        return {'schema_version': 1, 'namespace': self.namespace, 'pipeline_id': self.pipeline_id,
                'embedding_model': self.embedding_model, 'documents': [asdict(d) for d in self.documents],
                'chunks': [asdict(c) for c in self.chunks]}

    @property
    def revision(self) -> str:
        return _digest(self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), 'revision': self.revision}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Snapshot":
        if not isinstance(data, dict) or 'schema_version' not in data:
            raise ValueError('Invalid snapshot schema')
        version = data['schema_version']
        if type(version) is not int:
            raise ValueError('Snapshot schema_version must be an integer')
        if version != 1:
            direction = 'newer than this reader' if version > 1 else 'no migration available'
            raise ValueError(f'Unsupported snapshot schema version {version}: {direction}; reader supports version 1')
        if set(data) != {'schema_version', 'namespace', 'pipeline_id', 'embedding_model', 'documents', 'chunks', 'revision'}:
            raise ValueError('Invalid snapshot schema version 1 fields')
        if not isinstance(data['documents'], list) or not isinstance(data['chunks'], list):
            raise ValueError('Snapshot records must be JSON arrays')
        try:
            snapshot = cls(data['namespace'], data['pipeline_id'], data['embedding_model'],
                           tuple(DocumentState(**d) for d in data['documents']),
                           tuple(ChunkState(**c) for c in data['chunks']))
        except (TypeError, KeyError) as exc:
            raise ValueError('Invalid snapshot records') from exc
        if data['revision'] != snapshot.revision:
            raise ValueError('Snapshot revision mismatch')
        return snapshot

    def save(self, path: str | Path) -> None:
        """Atomic file replacement, NOT a concurrent writer lock or database commit."""
        _atomic_json(path, self.to_dict())

    @classmethod
    def load(cls, path: str | Path) -> "Snapshot":
        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate JSON key in snapshot')
                result[key] = value
            return result
        return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique_keys))


def build_snapshot(documents: Iterable[DocumentSpec], receipts: Iterable[ExtractionReceipt],
                   chunks: Iterable[Mapping[str, Any]], *, namespace: str, pipeline_id: str,
                   embedding_model: str, policy: AcceptancePolicy | None = None,
                   max_tokens: int | None = None, token_counter: Callable[[str], int] | None = None) -> Snapshot:
    """Validate completeness first; invalid batches never become snapshots.

    Keep pipeline_id/model identifiers immutable and versioned. Include chunking,
    preprocessing, embedding dimensions and model revision in these identifiers.
    """
    documents, receipts, chunks = tuple(documents), tuple(receipts), tuple(chunks)
    report = audit_ingestion(documents, receipts, chunks, policy=policy, namespace=namespace,
                             max_tokens=max_tokens, token_counter=token_counter)
    report.raise_for_errors()
    if any(d.expected_units is None for d in documents):
        raise ValueError('A replacement snapshot requires verified completeness for every document')
    states = []
    for record in chunks:
        md = dict(record['metadata'])
        if ('namespace' in md and md['namespace'] != namespace) or ((policy or AcceptancePolicy()).require_namespace and 'namespace' not in md):
            raise ValueError('Chunk namespace missing or contradicts snapshot namespace')
        text_hash = _digest(record['text'])
        states.append(ChunkState(stable_chunk_id(namespace, md['document_id'], record['chunk_key']),
                                 md['document_id'], record['chunk_key'], text_hash, _digest(md),
                                 _digest([text_hash, embedding_model, pipeline_id])))
    return Snapshot(namespace, pipeline_id, embedding_model,
                    tuple(DocumentState(d.document_id, d.source_version) for d in documents), tuple(states))


class UnsafePlanError(ValueError):
    """A requested update would violate a scope, deletion, or concurrency guard."""


@dataclass(frozen=True)
class UpdatePlan:
    base_revision: str | None
    target: Snapshot
    added: tuple[str, ...]
    changed: tuple[str, ...]
    unchanged: tuple[str, ...]
    removed: tuple[str, ...]
    embed_ids: tuple[str, ...]
    retired_documents: tuple[str, ...]
    preserved_documents: tuple[str, ...]
    shrink_allowances: tuple[tuple[str, float], ...] = ()
    deletion_policy: tuple[tuple[str, Any], ...] = ()

    @property
    def upsert_ids(self) -> tuple[str, ...]:
        return tuple(sorted((*self.added, *self.changed)))

    @property
    def plan_id(self) -> str:
        return _digest([self.base_revision, self.target.revision])

    def assert_base(self, current: Snapshot | None) -> None:
        """Check the base under your application's lock/CAS transaction.

        Checking alone does not prevent a race after this function returns.
        """
        if (None if current is None else current.revision) != self.base_revision:
            raise UnsafePlanError('Stale plan: committed snapshot changed; rebuild the plan')

    def metrics(self) -> dict[str, Any]:
        return dict(documents_in_target=len(self.target.documents), proposed_deletions=len(self.removed),
                    planned_embeddings=len(self.embed_ids), proposed_upserts=len(self.upsert_ids),
                    retired_documents=len(self.retired_documents), deletion_policy=dict(self.deletion_policy))

    def to_dict(self) -> dict[str, Any]:
        return {'schema_version': 1, 'plan_id': self.plan_id, 'base_revision': self.base_revision,
                'target_revision': self.target.revision, 'added': list(self.added),
                'changed': list(self.changed), 'unchanged': list(self.unchanged),
                'removed': list(self.removed), 'embed_ids': list(self.embed_ids),
                'upsert_ids': list(self.upsert_ids), 'retired_documents': list(self.retired_documents),
                'preserved_documents': list(self.preserved_documents), 'shrink_allowances': dict(self.shrink_allowances), 'deletion_policy': dict(self.deletion_policy)}


def plan_update(previous: Snapshot | None, current: Snapshot, *, retire_documents: Iterable[str] = (),
                max_delete_fraction: float = 0.25, allow_shrink: Mapping[str, float] | None = None,
                max_removed_chunks: int | None = None,
                max_shrinking_documents: int | None = None,
                max_corpus_delete_fraction: float = 0.15,
                _committed_chunk_count: int | None = None) -> UpdatePlan:
    """Plan a document-scoped replacement, preserving documents absent from current.

    Entire document retirement must be explicit. A present document is a complete
    replacement (enforced by build_snapshot). Metadata-only changes still upsert,
    but need no new embedding. The returned target is the MERGED inventory.
    """
    if not isinstance(current, Snapshot) or (previous is not None and not isinstance(previous, Snapshot)):
        raise TypeError('Use Snapshot objects created by build_snapshot or loaded from trusted state')
    if isinstance(max_delete_fraction, bool) or not isinstance(max_delete_fraction, (int, float)) or not math.isfinite(max_delete_fraction) or not 0 <= max_delete_fraction <= 1:
        raise ValueError('max_delete_fraction must be in [0, 1]')
    if isinstance(max_corpus_delete_fraction, bool) or not isinstance(max_corpus_delete_fraction, (int, float)) or not math.isfinite(max_corpus_delete_fraction) or not 0 <= max_corpus_delete_fraction <= 1:
        raise ValueError('max_corpus_delete_fraction must be in [0, 1]')
    for name, batch_limit in [('max_removed_chunks', max_removed_chunks), ('max_shrinking_documents', max_shrinking_documents)]:
        if batch_limit is not None and (type(batch_limit) is not int or batch_limit < 0):
            raise ValueError(f'{name} must be a nonnegative integer or None')
    if isinstance(retire_documents, str):
        raise ValueError('retire_documents must be an iterable of IDs')
    retired_items = tuple(retire_documents)
    for doc in retired_items:
        _name(doc, 'retired document ID')
    if len(set(retired_items)) != len(retired_items):
        raise ValueError('Duplicate retirement IDs')
    retired = set(retired_items)
    old_docs = {} if previous is None else {d.document_id: d for d in previous.documents}
    new_docs = {d.document_id: d for d in current.documents}
    if retired - old_docs.keys():
        raise UnsafePlanError('Cannot retire documents absent from the committed inventory')
    if retired & new_docs.keys():
        raise UnsafePlanError('A document cannot be updated and retired in the same plan')
    allowances = {} if allow_shrink is None else dict(allow_shrink)
    for doc_id, limit in allowances.items():
        if doc_id not in old_docs or doc_id not in new_docs or doc_id in retired:
            raise UnsafePlanError('Shrink allowances must name existing documents being updated')
        if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit) or not 0 <= limit <= 1:
            raise ValueError('Shrink allowances must be finite fractions in [0, 1]')
    preserved = old_docs.keys() - new_docs.keys() - retired
    if previous is not None:
        if previous.namespace != current.namespace:
            raise UnsafePlanError('Cannot compare different namespaces')
        if (previous.pipeline_id, previous.embedding_model) != (current.pipeline_id, current.embedding_model) and preserved:
            raise UnsafePlanError('Pipeline/model changes require all retained documents in the batch')
    old = {} if previous is None else {c.chunk_id: c for c in previous.chunks}
    merged = {key: value for key, value in old.items() if value.document_id in preserved}
    merged.update({c.chunk_id: c for c in current.chunks})
    added = merged.keys() - old.keys()
    removed = old.keys() - merged.keys()
    old_counts: dict[str, int] = {}
    removed_counts: dict[str, int] = {}
    for state in old.values():
        if state.document_id not in retired:
            old_counts[state.document_id] = old_counts.get(state.document_id, 0) + 1
    for key in removed:
        doc_id = old[key].document_id
        if doc_id not in retired:
            removed_counts[doc_id] = removed_counts.get(doc_id, 0) + 1
    for doc_id, count in sorted(removed_counts.items()):
        if count / old_counts[doc_id] > allowances.get(doc_id, max_delete_fraction):
            raise UnsafePlanError(f'Per-document deletion fraction exceeds limit for {doc_id}')
    # These are plan-local budgets, independent of the per-document fraction.
    # Count documents losing ANY old IDs, including replacement identity churn.
    ordinary_counts = {d: n for d, n in removed_counts.items() if d not in allowances}
    if max_shrinking_documents is not None and len(ordinary_counts) > max_shrinking_documents:
        raise UnsafePlanError(f'Batch shrinking documents {len(ordinary_counts)} exceeds limit {max_shrinking_documents}')
    if max_removed_chunks is not None and sum(ordinary_counts.values()) > max_removed_chunks:
        raise UnsafePlanError(f'Batch removed chunks {sum(ordinary_counts.values())} exceeds limit {max_removed_chunks}')
    committed_count = len(old) if _committed_chunk_count is None else _committed_chunk_count
    exempt_count = sum(1 for c in old.values() if c.document_id in retired or c.document_id in allowances)
    denominator = committed_count - exempt_count
    ordinary_removed = sum(ordinary_counts.values())
    if denominator and ordinary_removed / denominator > max_corpus_delete_fraction:
        raise UnsafePlanError(f'Corpus deletion fraction exceeds limit: {ordinary_removed}/{denominator}')
    effective = dict(per_document_fraction=max_delete_fraction, corpus_fraction=max_corpus_delete_fraction,
                     max_removed_chunks=max_removed_chunks, max_shrinking_documents=max_shrinking_documents,
                     committed_chunks=committed_count, exempt_chunks=exempt_count,
                     ordinary_committed_chunks=denominator, ordinary_removed_chunks=ordinary_removed,
                     shrinking_documents=len(ordinary_counts), proposed_deletions=len(removed),
                     retirement_removed_chunks=sum(old[k].document_id in retired for k in removed),
                     allowance_removed_chunks=sum(n for d, n in removed_counts.items() if d in allowances))
    changed = {key for key in merged.keys() & old.keys() if merged[key] != old[key]}
    unchanged = merged.keys() & old.keys() - changed
    embed = added | {key for key in changed if merged[key].embedding_hash != old[key].embedding_hash}
    target = Snapshot(current.namespace, current.pipeline_id, current.embedding_model,
                      tuple(new_docs.values()) + tuple(old_docs[key] for key in preserved), tuple(merged.values()))
    return UpdatePlan(None if previous is None else previous.revision, target,
                      tuple(sorted(added)), tuple(sorted(changed)), tuple(sorted(unchanged)),
                      tuple(sorted(removed)), tuple(sorted(embed)), tuple(sorted(retired)), tuple(sorted(preserved)), tuple(sorted(allowances.items())), tuple(sorted(effective.items())))


def audit_plan_embeddings(plan: UpdatePlan, embeddings: Iterable[Mapping[str, Any]], *, dimensions: int,
                          mode: str = 'embed', backend: str = 'python',
                          norm_range: tuple[float, float] | None = None,
                          max_warnings: int | None = None) -> ValidationReport:
    """Check plan coverage and recorded model/pipeline/input provenance.

    Each record requires chunk_id, vector, embedding_model, pipeline_id and
    input_hash (the exact input text hash in the target ChunkState). These labels
    are trusted producer declarations, not proof of which model generated a vector.
    mode='embed' covers new embeddings; mode='upsert' covers all final payloads.
    """
    from .ingestion import Finding, ValidationReport, audit_embeddings
    if not isinstance(plan, UpdatePlan) or mode not in ('embed', 'upsert'):
        raise ValueError('Supply an UpdatePlan and mode embed or upsert')
    records = tuple(embeddings)
    expected = plan.embed_ids if mode == 'embed' else plan.upsert_ids
    report = audit_embeddings(expected, records, dimensions=dimensions, backend=backend,
                              norm_range=norm_range, max_warnings=max_warnings)
    findings = list(report.findings)
    states = {c.chunk_id: c for c in plan.target.chunks}
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        key = record.get('chunk_id')
        state = states.get(key) if isinstance(key, str) else None
        if state is None:
            continue
        for field, value in [('embedding_model', plan.target.embedding_model),
                             ('pipeline_id', plan.target.pipeline_id), ('input_hash', state.text_hash)]:
            if record.get(field) != value:
                findings.append(Finding('embedding_provenance_mismatch', 'error',
                                        f'{field} does not match the planned embedding input.', state.document_id,
                                        index, state.chunk_key, 'Check the producer model/configuration and input fingerprint.'))
    return ValidationReport(tuple(findings), (*report.checks_run, 'declared_embedding_provenance'),
                            report.checks_skipped, max_warnings,
                            {**report.measurements, 'planned_embeddings': len(plan.embed_ids)})


def _atomic_json(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', delete=False) as handle:
            temporary = handle.name
            json.dump(payload, handle, sort_keys=True, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
