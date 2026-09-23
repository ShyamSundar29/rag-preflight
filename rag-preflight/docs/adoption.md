# Adoption and integrations

Start with `python examples/first_run.py`. A manifest is unnecessary for chunk
quality findings. Call `audit_chunks(records, min_chars=40,
distinctive_term_fraction=.8)` on your own chunks. Character statistics are always
reported: count, min, median, nearest-rank p95 and max for nonblank string texts.
The short-chunk floor and lexical check are opt-in to preserve existing policies.
Missing/disabled checks are named in `checks_skipped`.

The lexical check tokenizes Unicode letters/numbers, case-folds them, and warns
when every distinct term occurs in at least the configured fraction of the batch.
It requires at least five nonblank chunks and three distinct terms per candidate.
It is a repetitive-text heuristic, not a prediction that a chunk will never be
retrieved. Multilingual segmentation, code and semantic retrievers need evaluation
on their own inputs. It does not call an embedding service.

## Establish completeness

For a PDF, install `pip install '.[pdf]'` and use:

```python
from rag_preflight import pypdf_receipt, audit_ingestion, audit_unit_yield
result = pypdf_receipt('manual.pdf', document_id='catalog/manual')
chunks = result.chunks(lambda text: [text[i:i+800] for i in range(0, len(text), 800)],
                       source='manual.pdf')
report = audit_ingestion([result.document], [result.receipt], chunks)
report.raise_for_errors()
yield_report = audit_unit_yield({result.document.document_id: dict(result.texts)})
```

The PDF shim uses the public `PdfReader.pages` and `PageObject.extract_text()` APIs,
reads one byte copy, and hashes those bytes as `source_version`. It gets the page
count before attempting text extraction. Successful units include blanks; failed
units are separate. A completed receipt means all units were attempted, not that
all succeeded. Page-tree or file-open failures raise because no trustworthy
inventory can be established. Exception types are recorded without raw messages.
There is no OCR, timeout, retry, or memory sandbox. Blank scanned pages need OCR
or deliberate empty-page approval, not automatic acceptance. See the
[pypdf extraction documentation](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).

For HTML, markdown sections, transcripts or database rows, enumerate source-native
unit IDs first and pass `DocumentSpec` plus a per-unit callable to
`receipt_from_callable(spec, extract_unit)`. The callable receives canonical string
IDs in canonical sorted order. The result contains `document`, `receipt`, `texts`
and `failures`; `chunks()` optionally splits within each unit. Run the completeness
audit after splitting to catch a splitter that drops a whole unit. A source revision
must identify the same consistent source view that enumeration and extraction read.
See `examples/source_to_ledger.py` for a runnable example.

`assign_chunk_keys(records)` uses a JSON-encoded document ID, canonical unit ID and
zero-based ordinal within that unit. Supply the complete ordered chunk set for each
updated document in one call. Keys are collision-safe for delimiter-containing IDs;
existing keys are rejected. Multi-unit chunks require application-defined keys.
An insertion shifts subsequent ordinal keys **within that unit**. Persistent
source-native chunk IDs are better when available. Whole-document character offsets
also shift after earlier edits; do not assume `start_index` is persistent identity.
Do not change an existing key scheme without planning for identity churn/deletions.

## Converters and graph routing

`from_langchain_documents(documents)` copies `page_content` and `metadata`.
`from_llama_index_nodes(nodes)` copies text-only `TextNode.text` and `metadata`.
Both copy an existing metadata `chunk_key` to the top-level field. They require no
framework imports and do not fabricate source versions, unit inventories, receipts,
or keys. Incomplete metadata is fine for a basic chunk audit; supply independent
source evidence before building replacement snapshots.

Run `examples/langgraph_gate.py` with LangGraph installed for a validation node and
conditional branches to an embedding hook or halt. The hook deliberately performs
no external write: production must build a deletion-guarded plan before embedding,
validate produced vectors, and coordinate apply/commit. This follows the documented
[LangGraph node and conditional-edge APIs](https://docs.langchain.com/oss/python/langgraph/graph-api).

## Baselines for an existing corpus

```python
from rag_preflight import audit_chunks, WarningBaseline
scope = 'tenant-a/knowledge-base/quality-policy-v1'
report = audit_chunks(chunks, min_chars=40, distinctive_term_fraction=.8)
# Explicit one-time acceptance after reviewing warnings:
WarningBaseline.capture(report, chunks, scope=scope, fingerprint_mode='text').save('baseline.json')
# On subsequent runs (do not recapture automatically):
comparison = WarningBaseline.load('baseline.json').compare(report, chunks, scope=scope)
if not comparison.passed:
    print(comparison.report.to_dict())  # new warnings plus every error
```

Baselines apply only to `audit_chunks` warnings. Ingestion, embedding, completeness
and deletion safety checks cannot be baselined by this API. Existing errors still
fail. Strict fingerprints include exact records; text mode ignores unrelated
metadata while keeping text, source/chunk identity and finding information. Neither
mode includes array position; duplicate occurrences are counted. Changed content
makes a finding new. No raw chunk text is stored in the file. Supply the exact
records audited, and change `scope` when the corpus boundary or audit policy changes.
Warning severity escalations remain errors. `accepted_warnings` and
`resolved_warnings` support reporting. Use `comparison.passed` to gate on new
warnings; `comparison.report.passed` retains ordinary no-errors report semantics.

## Limits of text-yield warnings

`audit_ingestion` now estimates per-unit yield from single-unit chunks. The default
warns below 10% of the document median, only with at least five units and a median
of at least 200 stripped characters. Multi-unit attribution skips the whole
document with a named check. Chunk overlap can inflate estimates.

Use `audit_unit_yield({document_id: {unit_id: extracted_text}})` with raw extraction
text for cleaner evidence. `YieldPolicy` configures sample size, median floor and
ratio; `audit_chunk_unit_yield` also accepts it. These are **warnings**, so set an
appropriate warning gate if they should block a job. Naturally short title pages
can warn. Uniform truncation, missing text within an otherwise typical-length unit,
and poor OCR may remain undetected. Coverage and yield do not prove semantic fidelity.

For source/export audits without a ledger see [existing-index auditing](existing-index.md).
For row/API enumeration jobs, cost estimates and metrics see [API notes](api.md).
