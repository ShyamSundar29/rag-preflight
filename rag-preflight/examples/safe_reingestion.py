"""A complete in-memory update demo. Dummy vectors; no external services."""
from copy import deepcopy
import json
from pathlib import Path
from rag_preflight import (DocumentSpec, ExtractionReceipt, ValidationError,
                          audit_embeddings, audit_plan_embeddings, build_snapshot, plan_update, stable_chunk_id)


def make_snapshot(data):
    return build_snapshot(
        [DocumentSpec(**d) for d in data['documents']],
        [ExtractionReceipt(**r) for r in data['receipts']], data['chunks'],
        namespace=data['namespace'], pipeline_id=data['pipeline_id'],
        embedding_model=data['embedding_model'],
    )


data = json.loads(Path(__file__).with_name('ingestion.json').read_text())
old = make_snapshot(data)
updated = deepcopy(data)
updated['chunks'][0]['text'] = 'Employees have 25 days of leave.'
updated['documents'][0]['source_version'] = 'v2'
updated['receipts'][0]['source_version'] = 'v2'
for item in updated['chunks']:
    item['metadata']['source_version'] = 'v2'
new = make_snapshot(updated)
plan = plan_update(old, new)
print('Update:', len(plan.changed), 'upserts;', len(plan.embed_ids), 'new embeddings;', len(plan.removed), 'deletions')

# Dummy vectors only demonstrate correspondence checks, not meaningful embeddings.
states = {state.chunk_id: state for state in plan.target.chunks}
new_vectors = [{'chunk_id': key, 'vector': [0.3, 0.7],
                'embedding_model': plan.target.embedding_model, 'pipeline_id': plan.target.pipeline_id,
                'input_hash': states[key].text_hash} for key in plan.embed_ids]
audit_plan_embeddings(plan, new_vectors, dimensions=2).raise_for_errors()

# In production, hold a namespace lock and verify base revision for the entire
# apply/commit sequence, or use a transactional generation-switch design.
committed = old
plan.assert_base(committed)
records = {stable_chunk_id(data['namespace'], r['metadata']['document_id'], r['chunk_key']): r
           for r in updated['chunks']}
vectors = {state.chunk_id: [0.1, 0.9] for state in old.chunks}
vectors.update({item['chunk_id']: item['vector'] for item in new_vectors})
upserts = [{'chunk_id': key, 'vector': vectors[key], 'text': records[key]['text'],
            'metadata': records[key]['metadata'], 'embedding_model': plan.target.embedding_model,
            'pipeline_id': plan.target.pipeline_id, 'input_hash': states[key].text_hash} for key in plan.upsert_ids]
audit_plan_embeddings(plan, upserts, dimensions=2, mode='upsert').raise_for_errors()
print('Prepared', len(upserts), 'validated upsert payloads')
# No real writes in this demo. After confirmed upserts, deletes, and visibility:
committed = plan.target
retry = plan_update(committed, new)
print('Retry:', len(retry.upsert_ids), 'upserts;', len(retry.removed), 'deletions')

broken = deepcopy(updated)
broken['chunks'].pop()
try:
    make_snapshot(broken)
except ValidationError as exc:
    print('Incomplete extraction blocked:', sorted({f.code for f in exc.report.findings}))
