# API and compatibility notes (0.1.0, unreleased)

RAG Preflight validates source coverage, chunk integrity, embedding declarations,
and proposed ingestion changes. It produces reports and guarded update plans;
your application controls embedding, retrieval, and vector-store writes.

## Reports and metrics

`check_source_folder(root, max_examples=5, expected=None)` is a read-only, current-source entry
point. It enumerates supported files under the resolved root before extracting,
uses root-relative POSIX document IDs, and rejects symlink paths and read failures
as evidence errors. It builds `DocumentSpec` and receipts in memory from file
bytes and PDF page trees or PowerPoint slide lists; no manifest file is required.
It cannot report a file that vanished before folder enumeration without an
independent expected-file list. `expected` names a UTF-8 file with one canonical
root-relative POSIX supported path per line. It is a required minimum, not an
exact whitelist; extra files are audited. Empty lines are ignored, while duplicate,
absolute, parent-traversal and unsupported paths are rejected. Symlinks are never
followed. Incomplete enumeration leaves expected-file absence unverified.
`report.outcome` is `passed`, `audit_failed`, `no_supported_files`,
`reader_unavailable`, or `incomplete`; `report.passed` is true only for `passed`.
The CLI uses exit 0, 1, and 2 for those categories respectively.
`FolderCheckReport.to_dict()` groups findings with bounded examples, while
`report.audit.findings` keeps detailed records. `metrics()` has counts only,
without ID/text labels. `rag-preflight check DIR --json --details` requests the
detailed audit. The default word splitter uses 400 words with 40 words of overlap
**inside each source unit**; it is not a tokenizer, OCR system or chunking framework.
Memory grows with all extracted text/chunks in the submitted folder.

The file subset is UTF-8 `.txt`, `.md`, `.rst`, static `.html`/`.htm`, PDFs
(`rag-preflight[pdf]`), `.docx` and `.pptx` (`rag-preflight[office]`).
`text_file_receipt`, `docx_receipt` and `pptx_receipt` are optional helpers;
Office imports occur only when called. Word body paragraphs/table cells become
one `body` unit; PowerPoint slides are independent `slide:N` units. Headers,
footers, notes, floating shapes, JS-rendered HTML, images, charts and embedded
objects are not wholly inspected. A nonempty unit may still lose paragraphs.
`pypdf_receipt(...).likely_image_only_units` records blank-text PDF pages with
image objects as a heuristic; inspection failures remain unverified. A new
extraction cannot establish that those records historically reached an index.
Use an existing-index export or an application's persisted ingestion receipts
for historical claims.

`audit_chunks(records, ...)` returns `AuditReport`. `issues` explicitly retains
all detailed findings. `to_dict()` now defaults to compact output and omits
individual issues; `to_dict(detailed=True)` explicitly returns the detailed shape.
`to_dict(max_examples=5)` configures the compact sample bound. `by_code()`
returns a sorted list grouped by `(code, severity)` with exact `occurrences`,
`affected_chunks`, and bounded `chunk_indices`. Related indices count as affected
(e.g. the original duplicate). A chunk counts once per group, even if several
findings affect it. `table()` is a concise summary. CLI JSON now defaults to
compact output; use `--details` for the former detailed shape.

Output grows with distinct rules and the sample limit, not repeated occurrences
(except count digit length). This is **bounded output, not bounded audit memory**:
chunk audits materialize records and findings; aggregation also builds affected
index sets. Bound submitted batches yourself. Warning/error totals and ordinary
acceptance semantics are unchanged.

`metrics()` on chunk/validation/evidence/reconciliation reports, update plans, and
baseline comparisons returns JSON-compatible measurements. Finding groups use
code/severity, without text, document IDs, chunk IDs, or namespace labels. Ingestion
`missing_units` counts actual uncovered units, not finding objects. Skipped and
unverified checks are counts in metrics; inspect reports for their identities.
`planned_embeddings` is a plan count, never a completed embedding-call count.
Instrument actual requests, retries, successes and latency in your application.
Stored plans expose `stored.update.metrics()`; its target document count is scoped.
Baseline metrics include accepted and resolved warnings. No exporter/server is needed.

## Deletion policy

`plan_update()` and `SQLiteSnapshotStore.plan()` share guards and error messages:

- `max_delete_fraction=0.25`: removed prior chunk IDs / prior document chunks.
- `max_corpus_delete_fraction=0.15`: ordinary removed prior IDs / ordinary full
  committed chunks, including untouched documents.
- `max_removed_chunks=None`, `max_shrinking_documents=None`: optional independent
  absolute ceilings. Existing explicit values still work.

These are configurable initial policies, not universal guarantees. The lower
corpus threshold intentionally blocks widespread 20% deletion while permitting
widespread 10% deletion. Removed IDs measure identity churn as well as content
removal. Per-document checks run first in deterministic document-ID order.
Retirements remain explicit. Validated `allow_shrink={document_id: fraction}`
checks each named document against its own limit. Both retirements and named
allowances are excluded from **both** the ordinary numerator and denominator;
a huge exempt document cannot dilute ordinary protection. Tighter named limits
also exclude that document from ordinary budgets; review exemptions deliberately.
An all-exempt corpus has denominator zero and no ordinary deletion budget usage.
Newly added chunks do not enlarge the denominator.

The effective policy, committed/exempt/ordinary counts, shrinking document count,
and proposed deletion count are recorded in `plan.deletion_policy` and plan JSON.
SQLite obtains full counts with SQL aggregates over stored counts, without reading
untouched payloads. Counts are trusted ledger state; use `verify()` for corruption
checks. Partial planning remains proportional to touched payloads, plus the
count-table aggregate scan. Stale plans still fail under ledger CAS.

Migration: old callers raising only `max_delete_fraction` or absolute limits may
now hit the independent 15% corpus guard. Explicitly review and configure
`max_corpus_delete_fraction` too. Portable JSON snapshot schemas remain version 1. SQLite schema 1 migrates to 2
for commit history; older package builds cannot open schema 2. Back up ledgers
before upgrading and use the updated package for subsequent access.
Per-plan policies **do not enforce cumulative limits** across repeated batches;
use job-level cumulative budgets and migration review in the orchestrator.

## Cumulative deletion visibility (SQLite)

`ledger.deletion_summary(last_commits=4)` returns identity-free, JSON-compatible
rolling measurements. It includes `commits_considered`, `start_chunks`, `end_chunks`,
`chunks_added`, `chunks_removed`, ordinary/allowance/retirement removal counts,
`net_chunk_change`, `net_shrink_chunks`, `net_shrink_fraction`, and
`gross_removed_fraction`. For 40,000 -> 24,000 chunks over four commits with
16,000 removals and no additions, both fractions are 0.40. This remains visible
even though each individual plan passed its guards.

The denominator is the **full inventory immediately before the oldest commit in
the requested window**, including exempt documents; cumulative category totals
are separate measurements, not alternative ordinary deletion gates. Net shrinkage
is max(start-end, 0). Gross removals count prior IDs, including identity churn,
and can exceed 100% across replacement cycles. Additions can offset net shrinkage
without erasing gross removals. Neither measurement proves source-content loss.
If a selected window starts at ledger creation with zero inventory, and includes
commits after the first population, the summary excludes the initial setup/population
prefix. This yields the post-population comparison baseline for young ledgers.
`window_adjusted`, `initial_commits_excluded`, `baseline_basis`, and
`commits_considered` expose the change explicitly. It does not discard later
retirements/re-population or substitute an unrelated historical denominator.
An empty ledger, an import-only window, or a window starting at later re-population
still has null fractions when its starting inventory is genuinely zero. Windows
otherwise count imports, metadata-only updates and additions. Detailed history
retains every recorded commit; no-op retries produce no history row.

`ledger.commit_history(limit=10)` explicitly returns bounded detailed rows, newest
first, including timestamps, revision chain, counts and recorded effective policy.
The rolling summary omits revisions, IDs and text for structured logs. Reads load
no document payloads. History is stored on disk and grows with commits; returned
rows are bounded by the requested window, not a fixed retention policy. Protect
and back up the ledger; these records are trusted operational state, not an
authenticated audit log or evidence of external vector-store success.

SQLite schema 2 adds history tables in one transaction. Existing schema-1 inventory
is preserved. `history_complete=False`, `baseline_chunks_at_history_start`, and
`checks_unverified=['pre_tracking_commit_history']` expose the unavailable past;
no historical removals are invented. New ledgers track from creation. If removal
classification is unavailable on a manually constructed legacy plan, category totals
are null with `removal_classification` unverified. Use plans produced by the store.
Rollback/stale commits add no rows; reopen preserves history.

**This is visibility, not cumulative enforcement.** Log/alert on the summary after
commit. For a job-level hard budget, freeze a starting inventory and review the
aggregate job before writes; check it under your application namespace lock.
Rejecting only in the final ledger commit is too late if vector deletions have
already happened. A configurable ledger hard gate is not added in this update.
JSON snapshots remain stateless and do not acquire implicit history files.

## Warning baselines

`WarningBaseline.capture(report, records, scope='corpus/audit-policy-v1',
fingerprint_mode='text')` selects text-scoped fingerprints; `'strict'` is default.
Strict fingerprints include the whole record. Text fingerprints include exact
text, stable source/document/chunk identity and unit/page metadata, plus finding
code, severity, related record identities, suggestion, and relevant rule messages.
They ignore unrelated metadata, including version/label backfills. Current chunk
warning rules depend on text, not other metadata; source and unit fields still
participate because they identify the affected content. Future metadata-dependent
rules must include the metadata that determines their findings.

Duplicate messages contain positional indices, so those messages are excluded;
related record identities remain included. Duplicate occurrences are a multiset:
acceptance consumes one saved fingerprint for each occurrence. Adding repeated
content beyond the saved count surfaces additional warnings. Reordering identical
records does not create distinct identities. Policy thresholds, batch scope, and
batch-relative lexical/boilerplate rules require a new **scope** when their meaning
changes. The baseline cannot infer policy equivalence from a finding alone.

Schema 2 stores fingerprint mode. Schema 1 remains readable as strict. Unknown
schemas and explicit mode/scope mismatches raise `ValueError`. `compare(...,
fingerprint_mode='text')` can assert the intended comparison mode; omitted mode
uses the file's recorded mode. Only chunk-audit warnings can be accepted. Errors
remain visible, and ingestion, embedding, provenance and deletion reports cannot
be passed to baseline capture/compare. Baseline comparison gates on any new finding,
including warnings; ordinary chunk audit passes when there are no errors.

## Chunk-key and extraction helpers

`assign_chunk_keys(records)` copies inputs and refuses existing keys. Keys encode
`[document_id, unit_or_unit_list, ordinal_within_unit_tuple]` as JSON, avoiding
delimiter collisions. Single-unit output is unchanged. Existing `normalize_units`
sorts canonical identifiers, so unit order is **not source-significant**. `[2,1]`
and `['page:1','page:2']` identify the same tuple; integer 1 aliases `page:1`,
but string `'1'` is distinct. Inserting chunks shifts subsequent ordinals within
the same tuple. Prefer source-native persistent keys when available.

`ExtractionResult.chunks()` splits **within units** and may cut context at page
boundaries. It is a convenience adapter, not a chunking framework. To supply
cross-page chunks, create records yourself with nonempty `text`, accurate
`metadata.units=['page:1','page:2']`, `document_id`, `source_version`, and `source`;
assign keys or supply persistent keys, then audit against independently produced
receipts. Do not invent unit labels to pass coverage checks. Multi-unit chunks
skip the ambiguous chunk-attributed yield heuristic.

## Namespace consistency

`audit_ingestion(..., namespace='collection')` and `build_snapshot(namespace=...)`
reject contradictory recorded `metadata.namespace`. Metadata namespace is optional
by default. `AcceptancePolicy(require_namespace=True)` requires it and the supplied
namespace. Snapshot identity comparisons and SQLite plans/commits reject cross-
namespace changes. This is consistency enforcement, not authentication,
authorization, or tenant isolation. Application and database access controls remain
responsible for those protections.

## Embedding cost estimates

`estimate_embedding_cost(plan, price_per_million_tokens='0.50', currency='USD',
token_counts={chunk_id: actual_input_tokens}, comparison_ids=candidate_batch_ids,
comparison_scope='re-embed candidate batch')` returns an explicitly labeled estimate.
Alternatively supply `embedding_inputs={id: exact_preprocessed_input}` and
`tokenizer=callback` returning a nonnegative Python integer. Inputs/counts must
include prefixes and preprocessing at the embedding-request boundary. Supply counts
for every `plan.embed_ids` and every explicit comparison ID; missing evidence
raises. Pricing is caller-supplied and finite/nonnegative; no provider prices or
token guesses are built in. Costs use Decimal and serialize as strings.

A comparison consists of unique target IDs including all planned embeddings. The
avoided cost compares the plan with re-embedding **those IDs**, not the full corpus
unless that corpus was explicitly measured. No comparison means no savings claim.
Metadata-only reuse has zero new tokens and may be estimated without counts when
no comparison is requested. Hash-only snapshots cannot recover original inputs.
Database, generation, network and retry costs are excluded.

## Run receipts for rows, APIs and crawlers

`RunReceipt(run_id, enumerated_ids, processed_ids=..., failed_ids=...,
enumeration_completed=True, pagination_completed=True, scope='bounded',
start_watermark=..., end_watermark=..., consistent_snapshot=True)` records source
IDs **before** processing. The producer must persist independent enumeration as
pages arrive; never derive expected IDs from successful outputs. Only mark
pagination complete after the terminal page/cursor condition is confirmed.
`audit()` reports duplicates (extra occurrences), unexpected IDs, missing outcomes,
failures, conflicting outcomes, interruption and changing watermarks.

`bounded` and `incremental` runs establish processing coverage for enumerated IDs,
not whole-corpus completeness. They always report whole-corpus coverage unverified;
`deletion_eligible` is false. Even a completed `complete` run requires an explicit
consistent-snapshot assertion, no failures and no changing watermark before evidence
is eligible. Eligibility does not perform/authorize deletion or relax planning
checks. Use a repeatable source snapshot/watermark or external freeze; equality of
arbitrary markers alone is not proof of stability. If markers are unavailable,
assert consistency only when an external source guarantee establishes it.

Receipts materialize IDs and sets in memory. They are for bounded runs; for large
streams persist enumeration/outcomes externally and bound runs. This API is not
a disk-backed streaming receipt ledger. No automatic conversion to a full replacement
snapshot is provided. Incremental updates submit only complete touched documents;
`plan_update` preserves unseen documents. Explicit retirements must come from separate
complete evidence. Managed ingestion users without receipts can still audit chunks
and reconcile IDs, while source coverage stays unverified.


## Read-only operator CLI

```sh
rag-preflight ledger summary ledger.db --last-commits 10 --json
rag-preflight ledger history ledger.db --limit 4 --json
```

Both commands print JSON (also without --json). Exit 0 means the inspection succeeded,
not that deletion was safe or whole history verified; exit 2 means bad input/schema
or a database read failure. Missing files are not created. Schema 1 is not implicitly
migrated: back up and explicitly open with a writable updated store to upgrade first.
Inspection uses `SQLiteSnapshotStore(path, read_only=True)`, SQLite mode=ro and
query_only; it performs no DDL, journal-mode changes, inventory commits or migrations.
Read-only Python access offers the same behavior. Live WAL inspection requires access
to SQLite's WAL/shared-memory state and its normal read-lock coordination; do not use
an immutable database URI against a changing live ledger. Summary/history reads load
no document payloads. A successful summary remains measurements, not a hard gate.

CLI invocation requires a command or chunk input file. No arguments return exit
status 2 with usage on stderr; explicit `--help` and `-h` return status 0.
