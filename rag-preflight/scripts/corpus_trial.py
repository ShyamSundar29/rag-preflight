"""Reproducible public-source trial. Requires pypdf; numpy benchmarks are optional.

Run from the project root: python scripts/corpus_trial.py --cache-dir /tmp/rag-corpus
Raw downloaded corpus files are not redistributed in the release archive.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
import urllib.request

from rag_preflight import (DocumentSpec, ExtractionReceipt, AcceptancePolicy, ValidationError,
    audit_ingestion, build_snapshot, plan_update, audit_plan_embeddings, audit_embeddings,
    SQLiteSnapshotStore, pypdf_receipt, receipt_from_callable, audit_chunk_unit_yield)

SOURCES = {
    'rfc9110.pdf': 'https://www.rfc-editor.org/rfc/rfc9110.pdf',
    'pandas.md': 'https://raw.githubusercontent.com/pandas-dev/pandas/main/README.md',
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir',type=Path,default=Path(tempfile.gettempdir())/'rag-corpus')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    args.cache_dir.mkdir(parents=True,exist_ok=True)
    docs,receipts,chunks,sources=[],[],[],[]
    for filename,url in SOURCES.items():
        path=args.cache_dir/filename
        if not path.exists():
            with urllib.request.urlopen(url,timeout=30) as response:
                path.write_bytes(response.read())
        data=path.read_bytes(); checksum=hashlib.sha256(data).hexdigest()
        sources.append({'url':url,'sha256':checksum,'bytes':len(data)})
        if path.suffix=='.pdf':
            extraction=pypdf_receipt(path,document_id=filename)
        else:
            text=data.decode('utf-8')
            # Inventory comes from source heading locations, not parser output.
            starts=[m.start() for m in re.finditer(r'^#{1,6}\s+.+$',text,re.M)]
            boundaries=sorted(set([0,*starts,len(text)]))
            unit_text={f'section-offset:{a}':text[a:b] for a,b in zip(boundaries,boundaries[1:])}
            spec=DocumentSpec(filename,checksum,expected_units=tuple(unit_text))
            extraction=receipt_from_callable(spec,unit_text.__getitem__)
        docs.append(extraction.document)
        receipts.append(extraction.receipt)
        chunks.extend(extraction.chunks(
            lambda text:[text[i:i+800] for i in range(0,len(text),800) if text[i:i+800].strip()],source=url))
    def build(records=chunks, inventory=docs, extraction=receipts):
        return build_snapshot(inventory,extraction,records,namespace='public-trial',pipeline_id='pypdf+markdown/char800-v1',embedding_model='dummy-demo/dim2')
    started=time.perf_counter()
    report=audit_ingestion(docs,receipts,chunks)
    duration=time.perf_counter()-started
    baseline=build()
    results={}
    first_doc=docs[0].document_id;first_unit=docs[0].expected_units[0]
    missing=[c for c in chunks if not(c['metadata']['document_id']==first_doc and first_unit in c['metadata']['units'])]
    missing_report=audit_ingestion(docs,receipts,missing)
    results['omitted_source_unit_rejected']=not missing_report.passed
    try:
        build(missing)
        results['incomplete_snapshot_blocked']=False
    except ValidationError:
        results['incomplete_snapshot_blocked']=True
    lost_doc=[c for c in chunks if c['metadata']['document_id']!=first_doc]
    results['omitted_document_rejected']=not audit_ingestion(docs,receipts[1:],lost_doc).passed
    modified=deepcopy(chunks);modified[0]['text']+=' Revised.'
    changed=plan_update(baseline,build(modified))
    results['one_text_edit_one_embedding']=len(changed.changed)==len(changed.embed_ids)==1
    metadata=deepcopy(chunks);metadata[0]['metadata']['label']='new'
    backfill=plan_update(baseline,build(metadata))
    results['metadata_backfill_zero_embeddings']=len(backfill.changed)==1 and not backfill.embed_ids
    retained=[c for c in chunks if c['metadata']['document_id']==first_doc]
    retirement=plan_update(baseline,build(retained,docs[:1],receipts[:1]),retire_documents=[docs[1].document_id])
    results['named_retirement_with_default_guard']=bool(retirement.removed)
    results['completed_retry_noop']=not plan_update(changed.target,build(modified)).upsert_ids
    state=next(c for c in changed.target.chunks if c.chunk_id in changed.embed_ids)
    wrong=[{'chunk_id':state.chunk_id,'vector':[1.,2.],'embedding_model':'WRONG','pipeline_id':baseline.pipeline_id,'input_hash':state.text_hash}]
    results['wrong_declared_model_rejected']=not audit_plan_embeddings(changed,wrong,dimensions=2).passed
    duplicates=audit_embeddings(['a','b'],[{'chunk_id':k,'vector':[1.,2.]} for k in ['a','b']],dimensions=2)
    results['identical_vectors_warn']=any(f.code=='duplicate_vector' for f in duplicates.findings)
    # This limitation is deliberate: a unit label does not prove full paragraph content.
    truncated=deepcopy(chunks);truncated[0]['text']=truncated[0]['text'][:20]
    def yield_findings(records):
        return {(f.document_id,f.message) for f in audit_ingestion(docs,receipts,records).findings
                if f.code=='low_unit_text_yield'}
    baseline_yields=yield_findings(chunks)
    limitations={'within_unit_truncation_not_detected':not (yield_findings(truncated)-baseline_yields)}
    tiny_unit=[]
    first_seen=False
    for chunk in deepcopy(chunks):
        if chunk['metadata']['document_id']==first_doc and first_unit in chunk['metadata']['units']:
            if first_seen:
                continue
            first_seen=True
            chunk['text']='abc'
        tiny_unit.append(chunk)
    results['whole_unit_text_yield_warns']=bool(yield_findings(tiny_unit)-baseline_yields)
    uniform=deepcopy(chunks)
    for chunk in uniform:
        chunk['text']='x'
    limitations['uniform_truncation_not_detected_by_yield']=not audit_chunk_unit_yield(uniform).findings

    with tempfile.TemporaryDirectory() as directory,SQLiteSnapshotStore(Path(directory)/'state.db') as store:
        store.commit(store.plan(baseline))
        partial=store.plan(build(retained,docs[:1],receipts[:1]))
        results['indexed_plan_contains_only_touched_document']=len(partial.update.target.documents)==1
        indexed_bytes=Path(directory,'state.db').stat().st_size+Path(directory,'state.db-wal').stat().st_size
    vector_count=2000; dimensions=1536
    benchmarks={}
    for backend in ('python','numpy'):
        try:
            if backend=='numpy':
                import numpy as np
                vectors=[{'chunk_id':str(i),'vector':np.full(dimensions,float(i+1))} for i in range(vector_count)]
            else:
                vectors=[{'chunk_id':str(i),'vector':[float(i+1)]*dimensions} for i in range(vector_count)]
            started=time.perf_counter()
            audit_embeddings([str(i) for i in range(vector_count)],vectors,dimensions=dimensions,backend=backend)
            benchmarks[backend]=time.perf_counter()-started
        except ImportError:
            benchmarks[backend]='not installed'
    result={'sources':sources,'documents':len(docs),'source_units':sum(len(d.expected_units) for d in docs),
        'chunks':len(chunks),'baseline':{'passed':report.passed,'findings':dict(Counter(f.code for f in report.findings)),
        'audit_seconds':duration,'skipped':list(report.checks_skipped), 'finding_details':report.to_dict()['findings']},'injected_scenarios':results,
        'known_limits':limitations,'snapshot_json_bytes':len(json.dumps(baseline.to_dict()).encode()),
        'sqlite_bytes_including_wal':indexed_bytes,'vector_benchmark':{'count':vector_count,'dimensions':dimensions,
        'seconds':benchmarks,'note':'Validation only; data construction excluded. Python lists versus NumPy arrays. Single local run, no throughput guarantee.'}}
    if args.output:
        args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    if not report.passed or not all(results.values()):
        raise SystemExit(1)


if __name__=='__main__':
    main()
