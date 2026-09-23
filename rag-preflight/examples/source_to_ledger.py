"""Independent source inventory, honest extraction, and reconciled fake-store apply."""
from pathlib import Path
import tempfile
from rag_preflight import (DocumentSpec, receipt_from_callable, build_snapshot,
    SQLiteSnapshotStore, reconcile)

# In production enumerate these IDs from the source API/database before extraction.
source = {'section:leave': 'Annual leave is 20 days.', 'section:approval': 'Request manager approval.'}
spec = DocumentSpec('handbook', 'source-revision-1', expected_units=tuple(source))
extraction = receipt_from_callable(spec, source.__getitem__)
chunks = extraction.chunks(source='handbook.md')
candidate = build_snapshot([spec], [extraction.receipt], chunks,
    namespace='demo', pipeline_id='source-sections-v1', embedding_model='demo-model')

with tempfile.TemporaryDirectory() as directory, SQLiteSnapshotStore(Path(directory)/'ledger.db') as ledger:
    planned = ledger.plan(candidate)
    # Fake vector store to demonstrate ID checks; no embeddings or real writes.
    vector_ids = set(planned.update.upsert_ids)
    vector_ids.difference_update(planned.update.removed)
    # Initial batch is the complete namespace. For partial batches see production.md.
    applied = reconcile((c.chunk_id for c in candidate.chunks), vector_ids,
                        namespace=candidate.namespace, inventory_complete=True)
    if not applied.passed:
        raise RuntimeError(applied.to_dict())
    ledger.commit(planned)
    ledger.verify().raise_for_errors()
    assert reconcile(ledger.chunk_ids(), vector_ids, namespace='demo', inventory_complete=True).passed
    print('Committed and reconciled', ledger.counts())
