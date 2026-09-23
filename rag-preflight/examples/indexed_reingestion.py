"""Indexed ledger demo only: no external vector database writes."""
import json
from pathlib import Path
import tempfile
from rag_preflight import DocumentSpec, ExtractionReceipt, SQLiteSnapshotStore, build_snapshot


def main():
    data=json.loads(Path(__file__).with_name('ingestion.json').read_text())
    candidate=build_snapshot([DocumentSpec(**d) for d in data['documents']],
        [ExtractionReceipt(**r) for r in data['receipts']],data['chunks'],
        namespace=data['namespace'],pipeline_id=data['pipeline_id'],embedding_model=data['embedding_model'])
    with tempfile.TemporaryDirectory() as directory,SQLiteSnapshotStore(Path(directory)/'state.db') as store:
        first=store.plan(candidate)
        # Demo simulates successful external writes. Actual applications commit
        # only after validation, confirmed database writes and concurrency checks.
        store.commit(first)
        retry=store.plan(candidate)
        print('Indexed inventory:',store.counts())
        print('Retry upserts:',len(retry.update.upsert_ids))
        before = store.revision
        print('No-op preserved revision:',store.commit(retry)==before)


if __name__=='__main__':
    main()
