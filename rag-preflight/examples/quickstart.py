from rag_preflight import audit_chunks

chunks = [
    {'text': 'Company handbook\nEmployees receive 20 days of leave.', 'metadata': {'source': 'handbook.pdf', 'page': 1}},
    {'text': 'Company handbook\nContact HR to request leave.', 'metadata': {'source': 'handbook.pdf', 'page': 2}},
    {'text': 'Company handbook\nLeave requests require approval.', 'metadata': {'source': 'handbook.pdf', 'page': 3}},
    {'text': 'Company handbook\nContact HR to request leave.', 'metadata': {'source': 'handbook.pdf', 'page': 2}},
    {'text': '  ', 'metadata': {}},
]
report = audit_chunks(chunks, required_metadata=['source', 'page'])
print(report.summary())
for issue in report.issues:
    print(f'{issue.severity.upper()} chunk {issue.chunk_index}: {issue.code} - {issue.message}')
print('Skipped:', ', '.join(report.checks_skipped))
