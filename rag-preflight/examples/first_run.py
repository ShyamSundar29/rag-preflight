"""Useful findings without a manifest, provider, or vector database."""
from rag_preflight import audit_chunks

chunks = [
    {'text': 'Home help contact', 'metadata': {'source': f'page-{i}.html'}}
    for i in range(5)
]
chunks.append({'text': 'Configure the retention period in the archive settings before uploading documents.',
               'metadata': {'source': 'archive.html'}})
report = audit_chunks(chunks, min_chars=40, distinctive_term_fraction=.8)
print(report.table(max_examples=3))
print('Length distribution:', report.length_statistics)
# report.issues and report.to_dict(detailed=True) retain debugging detail.

