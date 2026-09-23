"""Observe repeated safe-batch shrinkage without claiming a cumulative hard gate."""
from rag_preflight import (DocumentSpec, ExtractionReceipt, SQLiteSnapshotStore,
                           build_snapshot)


def candidate(count):
    document = DocumentSpec('manual', 'v1', expected_units=('file',))
    receipt = ExtractionReceipt('manual', 'v1', processed_units=('file',), completed=True)
    chunks = [{'chunk_key': str(i), 'text': f'Passage {i}', 'metadata': {
        'source': 'manual.txt', 'document_id': 'manual', 'source_version': 'v1',
        'units': ['file']}} for i in range(count)]
    return build_snapshot([document], [receipt], chunks, namespace='example',
                          pipeline_id='positional-v1', embedding_model='declarations-only')


with SQLiteSnapshotStore(':memory:') as ledger:
    ledger.commit(ledger.plan(candidate(20)))
    for retained in (18, 16, 14, 12):
        ledger.commit(ledger.plan(candidate(retained)))
    summary = ledger.deletion_summary(last_commits=4)
    print(summary)
    assert summary['net_shrink_fraction'] == .4
# No vector writes or real embeddings occur in this ledger-only example.
