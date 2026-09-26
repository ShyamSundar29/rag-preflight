# RAG Preflight

Validate source completeness, embeddings, and document updates before changing a
RAG vector database. **Version 0.1.0 release candidate.** Python 3.10+. MIT license.
The core has no third-party runtime dependencies and makes no network calls.

RAG Preflight validates source coverage, chunk integrity, embedding declarations,
and proposed ingestion changes. It produces reports and guarded update plans;
your application controls embedding, retrieval, and vector-store writes.

See the [quickstart](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/quickstart.md), [API and migration notes](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/api.md),
[existing-index JSONL workflow](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/existing-index.md), [failure taxonomy](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/failures.md),
and [public API, policy and stored-format commitments](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/compatibility.md).
New workflows include compact reports, text-scoped baselines, embedding cost estimates,
structured metrics, and bounded receipts for rows/APIs/crawlers.

## Why use it?

The highest-value moment is updating an existing index: an extraction regression
can turn missing output into unintended deletion of live indexed material.

An ingestion job can finish while some source material never becomes searchable.
An update can leave stale chunks behind; a retry can repeat work. This library
compares an independent source inventory with extracted chunks and produces a
repeatable, guarded update plan. It works with ordinary Python data.

**Build the expected inventory from the source system, not successful parser output.**

## Try it

For a first look at **current source extraction**, point the CLI at a folder:

```sh
python -m pip install 'rag-preflight[pdf,office]'
rag-preflight check ./documents
rag-preflight check ./documents --json --max-examples 3
rag-preflight check ./documents --expected expected-files.txt
```

`check` discovers supported files and builds an in-memory source/page-or-slide
inventory before chunking. It needs no handwritten manifest or index export.
Without an external expected-file list it **cannot discover a document already
missing from the folder**; it checks the files that are present. `--expected`
accepts independently maintained UTF-8 root-relative supported paths, one per
line. It checks this minimum inventory only after a complete directory walk;
additional files are allowed. An empty folder or missing optional reader is an
input/incomplete outcome (exit 2), audited findings exit 1, and a clean supported
scope exits 0. A partial read never passes.
Supported files are UTF-8 `.txt`, `.md`, `.rst`, static `.html`/`.htm`, PDFs,
and optional `.docx`/`.pptx`. Missing optional readers and unreadable files fail
the check; paths outside the root are not followed. A PDF page with image objects
but no extractable text gets a **likely** image-only warning and may need OCR.
Word checks body paragraphs and table cells as one file unit; PowerPoint checks
slide text and table cells. Headers, footers, notes, text boxes, images, charts,
scripts and within-unit truncation are not fully validated. The report explicitly
marks **historical indexing unverified**: use `existing-index` with a complete
export or managed ingestion receipts to check what reached a vector store. Working
memory grows with the extracted corpus; batch large folders. The user reported
36 PDFs/804 pages in 30 seconds at 71 MB peak and 300 text files in 0.1 seconds;
these are local observations, not a general memory bound or performance promise.
File sizes, parser behavior and measurement method were not supplied.
See [check to guarded ingestion](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/check-to-pipeline.md) for a path from this
diagnostic to a maintained pipeline.

### Messy-document acceptance

The repository includes a reproducible, generated real-format acceptance suite:

```sh
python -m pip install -e '.[pdf,office]'
python scripts/messy_document_acceptance.py
```

It exercises invalid UTF-8, empty/damaged/encrypted PDFs, an image-only PDF, a
1,000-paragraph DOCX, an image-heavy PPTX, static HTML, a missing expected file,
and an unsupported file. Linux and Windows CI run the suite with the real optional
readers. These license-safe fixtures test known failure handling; they are not
evidence from an external production corpus. See
[messy-document acceptance](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/messy-documents.md).

Open a terminal in the extracted `rag-preflight` source directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python examples/safe_reingestion.py
python examples/indexed_reingestion.py
python -m unittest discover -s tests -v
```

Windows activation: `.venv\Scripts\activate`.
Release archives are not committed to this source repository. To build a local
wheel explicitly:

```bash
python -m pip install build
python -m build --outdir ../artifacts
python -m pip install ../artifacts/rag_preflight-0.1.0-py3-none-any.whl
```

The ignored `artifacts` directory is created by that command; it is not part of
the source repository. Until the first PyPI upload, use this source-build path.
The repository must be publicly readable when the release is published so the
package's Repository, Documentation, Issues and Changelog links resolve for users.

## Capabilities

| Area | Behavior |
| --- | --- |
| Completeness | Missing documents, receipts, units, failed extraction, version mismatches, explicit blank units |
| Source types | Caller units such as pages, Markdown sections, transcript segments, message IDs and record keys; folder check supports PDF/text/HTML and optional Office subset |
| Chunk checks | Empty text, metadata, duplicates, boilerplate, length distribution, optional short/low-distinctiveness warnings and token limits |
| Update planning | Stable IDs; added, changed, unchanged and removed chunks; metadata-only updates skip embedding |
| Deletion protection | Explicit retirement; narrowly scoped shrink allowances; unrelated documents stay protected |
| Embeddings | IDs, dimensions, finite values, zero vectors, duplicate-vector warnings, configurable norm warnings |
| Plan-linked validation | Coverage and declared model, pipeline and embedding-input fingerprints |
| State | Portable JSON snapshots or document-indexed SQLite storage with revision-checked ledger commits |
| Integration | Python API, JSON CLI, PDF/generic receipt producers, key helper, thin framework converters, optional NumPy |
| Operations | Full ledger verification, ID reconciliation, warning baselines, per-unit text-yield warnings |

## Useful on the first run

```python
from rag_preflight import audit_chunks
report = audit_chunks(
    [{"text": "Home help contact", "metadata": {"source": "help.html"}}],
    min_chars=40, distinctive_term_fraction=.8,
)
print(report.to_dict())
```

No manifest is needed for chunk checks. This example warns about a short chunk;
lexical analysis needs at least five chunks. See [adoption](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/adoption.md) for
PDF extraction receipts, generic extraction, chunk keys, framework converters,
warning baselines and a runnable LangGraph validation gate.

## How it fits existing frameworks

LangChain indexing already tracks records and supports cleanup modes. Its
[API documentation](https://reference.langchain.com/python/langchain-core/indexing/api)
warns that full cleanup can remove wanted documents when the loader returns only
a subset. LlamaIndex's [ingestion pipeline](https://developers.llamaindex.ai/python/framework/module_guides/loading/ingestion_pipeline/)
already skips unchanged documents and reprocesses changed ones using a docstore.
RAG Preflight adds an independent source-completeness audit and explicit deletion
budgets before applying changes. Diffing alone is not its distinguishing feature.
Keep a single owner for deletion decisions: another cleanup pass can bypass the
approved plan. Converters do not automatically integrate the two indexing engines.

## Source units instead of fake pages

```python
from rag_preflight import DocumentSpec, ExtractionReceipt, audit_ingestion

documents = [DocumentSpec(
    "handbook", "etag-123",
    expected_units=("section:leave", "section:approval"),
)]
receipts = [ExtractionReceipt(
    "handbook", "etag-123",
    processed_units=("section:leave", "section:approval"), completed=True,
)]
chunks = [
    {"chunk_key": "leave", "text": "Employees receive 20 days of leave.",
     "metadata": {"document_id": "handbook", "source_version": "etag-123",
                  "source": "handbook.md", "units": ["section:leave"]}},
    {"chunk_key": "approval", "text": "Managers approve leave requests.",
     "metadata": {"document_id": "handbook", "source_version": "etag-123",
                  "source": "handbook.md", "units": ["section:approval"]}},
]
report = audit_ingestion(documents, receipts, chunks)
report.raise_for_errors()
```

Units are canonical strings. Positive integers are convenience aliases: `1` becomes
`"page:1"`; literal `"1"` is a different unit. Duplicate canonical IDs are rejected.
Whitespace and case in string identifiers are preserved. Unit IDs must come from
source structure; adding fake unit IDs does not establish meaningful completeness.

The earlier `expected_pages`, `processed_pages`, `empty_pages`, `failed_pages`,
`allowed_empty_pages` and chunk metadata `pages` remain accepted for PDFs. Do not
supply both page and unit forms for the same object. `DocumentSpec.to_dict()` and
`ExtractionReceipt.to_dict()` export the canonical unit representation, including
when constructed with page aliases.

For approved blank content, declare `allowed_empty_units` on the specification and
`empty_units` on the receipt. They remain part of `processed_units`. A source known
to contain no units can declare `expected_units=()` with `min_chunks=0`.
Omitting `expected_units` means coverage is unknown: the audit reports
`completeness_unverified` and a skipped check. **It cannot produce a replacement
snapshot**, even if warnings are otherwise allowed.

## Policies and exact token counts

```python
from rag_preflight import AcceptancePolicy
policy = AcceptancePolicy(required_metadata=("source",), max_warnings=0)
```

The ingestion API always requires valid identity, version and unit information
when coverage is declared. Metadata must use finite JSON-native data. Findings
include document ID, chunk key/index where available, a code and a suggested action.
Use `report.to_dict()` or `report.by_document()`.

Supply both `max_tokens` and `token_counter` to `audit_ingestion` or `build_snapshot`
for exact limits, using the actual embedding pipeline's tokenizer. Without them,
`token_limit` is explicitly skipped. Model-specific prefixes/special tokens must be
included in your counter. The CLI does not guess token counts.

## Build and compare snapshots

```python
from rag_preflight import build_snapshot, plan_update
candidate = build_snapshot(documents, receipts, chunks,
    namespace="tenant-a/kb", pipeline_id="parser-v1/chunker-v1",
    embedding_model="provider/model-revision/dimensions-1536")
plan = plan_update(None, candidate)  # First ingestion
```

For updates, pass the committed previous snapshot as the first argument. Stable
chunk IDs depend on namespace, document ID and chunk_key. Same identity with changed
text requests embedding; changed metadata requests an upsert but no new embedding.
Keep keys stable across retries. Documents omitted from the candidate are preserved.

```python
# Retire only this named document. Other documents keep their deletion guards.
plan = plan_update(previous, candidate, retire_documents=["obsolete-doc"])

# Allow removal of up to 80% of this document's previous chunk IDs only.
plan = plan_update(previous, candidate, allow_shrink={"handbook": 0.8})
```

Default `max_delete_fraction=0.25` applies per document. Independent batch guards
use `max_corpus_delete_fraction=0.15` over the full committed ordinary inventory.
Absolute `max_removed_chunks` and `max_shrinking_documents` budgets are optional
(default `None`). Both retired and scoped-exempt documents are excluded from the
ordinary numerator and denominator. Review these configurable initial policies,
and configure the independent corpus threshold when raising document limits.
A replacement that changes IDs counts even if its net chunk count does not shrink.
Per-document checks run first in sorted ID order, then optional absolute budgets,
then the corpus fraction. JSON and SQLite use shared logic and matching errors.

The 300-document case (20 chunks each, reduced to 16) now fails: 300 documents lose
1,200 chunks even though every document is below 25%. Exact configured limits pass;
exceeding them fails. Configure the independent limits for your workload; absolute budgets set to `None`
disables one batch limit in Python. Budgets apply to one plan, not accumulated jobs.

Named retirements are excluded. Documents with validated scoped shrink allowances
use their own per-document limit and are excluded from ordinary batch budgets.
Invalid, unknown, retired or non-updated allowance targets are rejected. Exceptions
never relax guards for other documents or completeness requirements. The plan records
the allowances; applications should log their configured batch budgets alongside it.

Changing a model/pipeline identifier requires every retained document in the batch
and requests re-embedding. Include actual model revision, dimension and preprocessing
changes in these identifiers. The library does not create/migrate database indexes.

## Validate embeddings against the plan

```python
from rag_preflight import audit_plan_embeddings
# embedding_records come from your producer, including its recorded provenance:
# {"chunk_id": ..., "vector": [...], "embedding_model": ...,
#  "pipeline_id": ..., "input_hash": ...}
report = audit_plan_embeddings(plan, embedding_records, dimensions=1536, mode="embed")
report.raise_for_errors()
```

`input_hash` is the exact text fingerprint stored in the corresponding target
ChunkState.text_hash. `mode="embed"` covers exactly `plan.embed_ids`;
`mode="upsert"` covers all `plan.upsert_ids`, including reused vectors. The latter
must also be validated before uploading. These checks validate producer declarations,
not mathematical proof of which model created a vector. Capture provenance where
the embedding request is made; do not relabel vectors to make checks pass.

The lower-level `audit_embeddings` remains available. Identical vectors across
IDs warn by default; they can be legitimate for identical inputs. Set
`detect_duplicates=False` to disable the check. Configure `norm_range=(low, high)`
for your model; no universal norm threshold is assumed. `max_warnings=0` turns
warnings into rejection under the acceptance policy.

For optional acceleration: install `.[numpy]` and pass `backend="numpy"` to either
embedding audit. The backend works one vector at a time, including direct NumPy
arrays. No whole-corpus vector matrix is allocated by the validator.

## Recommended state: SQLite ledger

```python
from rag_preflight import SQLiteSnapshotStore
with SQLiteSnapshotStore("ingestion.db") as store:
    stored_plan = store.plan(candidate, allow_shrink={})
    update = stored_plan.update
    # Validate embeddings/payloads, acquire your application lock, recheck base,
    # and confirm vector-store upserts/deletes before committing the ledger.
    store.assert_base(stored_plan)
    # ... external writes, with concurrency protection ...
    store.commit(stored_plan)
```

**Use SQLite for operational state; use JSON for portable export/interchange.**
The SQLite backend loads only touched documents; its nested UpdatePlan.target is
**the touched scope**, not the whole corpus. Never use that subset to replace the
full ledger outside `store.commit`. The store applies touched documents and explicit
retirements transactionally while preserving other rows. A stale commit is rejected;
a no-op keeps the revision. `document_ids()` enumerates the ledger without loading
payloads. `load_documents(ids)` exports selected documents; exporting all IDs to one
JSON snapshot still requires whole-corpus memory. `verify()` scans every stored
revision, identity and chunk count plus SQLite integrity. `chunk_ids()` streams
verified IDs one document at a time. See [operator and apply checks](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/production.md)
for `reconcile()` and its complete-namespace requirements.

Portable JSON snapshots still use schema version 1; existing hash-only snapshots
remain loadable. SQLite storage uses schema version 2, migrated from version 1, with per-document
snapshot blobs and an indexed document table. Import a JSON snapshot by planning and
committing it as an initial batch. Large initial imports can commit whole documents
in successive batches without constructing a full-corpus Snapshot.

SQLite protects the ledger, not a vector database transaction. Hold an application
lock across base verification, external writes and ledger commit, or use a generation
switch. See [production integration](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/production.md).

## Cumulative deletion visibility

```python
# After successful external writes and ledger.commit(stored_plan):
print(ledger.deletion_summary())
# Detailed bounded commit records are explicitly available:
print(ledger.commit_history(limit=4))
```

The summary exposes repeated-batch shrinkage with full-corpus window counts, gross
ID removals, net shrinkage and exempt removal categories. It does not impose a
cumulative hard gate or verify external writes. SQLite schema 1 migrates to 2;
pre-tracking history remains explicitly unverified. Young-ledger windows explicitly
exclude initial population when necessary for a meaningful nonzero baseline. See [window and migration
rules](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/api.md#cumulative-deletion-visibility-sqlite).

Python `AuditReport.to_dict()` now defaults to compact output; `.issues` and
`to_dict(detailed=True)` retain debugging detail. This pre-1.0 change makes the
Python JSON shape match the CLI. Taxonomy coverage is tested against source.
For adoption validation, use the separate [Chroma/FAISS integration contract](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/integration-validation.md).

## CLI

Read-only scheduled ledger inspection:

```sh
rag-preflight ledger summary ledger.db --json
rag-preflight ledger history ledger.db --limit 4 --json
```

Missing files fail rather than being created; legacy schemas require an explicit
writable upgrade. The summary identifies its actual comparison window and baseline.


```bash
rag-preflight examples/chunks.json --json --min-chars 40 --distinctive-term-fraction .8
rag-preflight ingestion examples/ingestion.json --snapshot candidate.json
rag-preflight plan - candidate.json
rag-preflight plan committed.json candidate.json --retire obsolete-doc
rag-preflight plan committed.json candidate.json --allow-shrink '{"handbook": 0.8}'
rag-preflight embeddings vectors.json
```

The last input contains `expected_chunk_ids`, `embeddings`, `dimensions`. CLI plans
are advisory JSON; SQLite and plan-linked embedding validation use the Python API.
Exit codes: 0 accepted, 1 validation rejection, 2 invalid input or unsafe plan.
A failed audit leaves an existing candidate file unchanged: check exit status.

## Evidence and limits

The included [public-corpus trial](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/corpus-results.json) covers an RFC PDF and
pandas Markdown README, 210 source units and 701 chunks, plus eleven injected scenarios. The unmodified Markdown source produces one
low-yield warning for a short license section; see the recorded finding.
It is a small real-source trial with dummy vectors, not a production load test.
Reproduce with `pip install '.[trial,numpy]'` followed by
`python scripts/corpus_trial.py --output results.json` (downloads public sources).
Source hashes are recorded; upstream files can change.

The library does not parse source files in its core, detect semantic correctness,
PII/prompt injection, or prove within-unit content completeness. It relies on trusted
source manifests and receipts. Batch validation and individual-document snapshots
still use memory proportional to their input. A single enormous document remains
an in-memory unit even with SQLite.

See [validation](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/validation.md), [changelog](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/CHANGELOG.md),
[contributing](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/CONTRIBUTING.md), and [license](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/LICENSE). GitHub Actions exercises
Python 3.10 through 3.14 on Linux plus Python 3.12 on macOS and Windows; separate
jobs cover optional integrations, messy documents and clean-clone reference apps.

CLI discovery: `rag-preflight --help` lists every workflow;
`rag-preflight existing-index --help` shows export/scope options.
Use `rag-preflight chunks INPUT.jsonl` for explicit chunk auditing; the legacy
`rag-preflight INPUT.jsonl` form remains supported. Unknown bare command names
return status 2; extensionless files can be passed with `chunks INPUT` or `./INPUT`.


## Deployment evidence and responsibility

RAG Preflight produces validation reports and guarded update plans. It does not
write to your vector store; your application performs embedding requests, vector
writes, read-back checks and recovery. Explicit ledger commits do write to the
library's SQLite inventory. Ledger transactions do not make external writes atomic.

The mechanisms and tests provide evidence of capability, not a guarantee that the
library is safe in every pipeline. Validate source mapping, completeness evidence,
namespace policy, locking, write visibility and recovery against your deployment.
The project has a reproducible limited corpus trial and independent reviewer checks,
not established operational history across independent production deployments.
External users and deployments must supply that operational evidence after release.

Its strongest use case is the next ingestion of a changing corpus: loader omissions
can otherwise become unintended index deletions. Initial ingestion also benefits
from source coverage, chunk integrity and embedding checks; retrieval quality and
prompt design remain outside scope. “Second ingestion” describes updating an index,
not prompt injection or model training.

For existing pipelines, start with the [store export recipes](https://github.com/ShyamSundar29/rag-preflight/blob/main/rag-preflight/docs/export-recipes.md).

CLI invocation requires a command or chunk input file. No arguments return exit
status 2 with usage on stderr; explicit `--help` and `-h` return status 0.
