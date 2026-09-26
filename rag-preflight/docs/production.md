# Production integration contract — 0.1.0

This library validates inputs and creates advisory plans. The application owns
source authenticity, authorization, provider calls, vector writes, concurrency and
committed state. Passing the test suite is not production certification.

## Source inventory and unit coverage

Capture an authoritative inventory at a known source version before extraction.
Use an object version, checksum or ETag for source_version. Units can identify PDF
pages, Markdown sections, messages, transcript spans or rows. The extractor records
success, failure and intentional emptiness against that inventory.

A unit is covered when at least one nonempty chunk references it. This detects a
missing unit, not a missing paragraph within a covered unit. Do not create the
expected inventory from successful extraction output. Do not invent unit names to
silence completeness findings. Unit IDs and stable chunk keys should be derived
from stable source identifiers when possible; positional keys cause more changes
when text is inserted at the beginning.

Omitted expected_units means coverage is unknown; the audit warns and lists it as
skipped. build_snapshot rejects unverified completeness, regardless of warning
policy. An explicit empty unit inventory is different: use expected_units=() and
min_chunks=0 for a known empty source. Approved blank units must be declared by both
the specification and receipt. Page aliases remain supported for existing callers.

Versions are opaque, not chronological. Verify the upstream source version again
if it can change during the run; the library cannot know that a supplied older
version is stale.

## Identity, hashes and declared provenance

Chunk identity is SHA-256 over algorithm version, namespace, document ID and stable
chunk key. The namespace must match the application's actual collection/tenant
scope. A namespace string does not enforce access permissions.

Text hashes preserve exact text. Metadata hashes sort object keys but preserve
list order. Include every persisted metadata field, including authorization labels,
so metadata changes trigger upserts. Access policy enforcement remains external.

Embedding hashes incorporate text hash, model and pipeline IDs. Version identifiers
when dimensions, model revisions, preprocessing, tokenizer/prefixes, normalization
or chunking configuration change. If embedding input includes metadata, include that
input in text or version the relevant configuration.

audit_plan_embeddings checks exact requested ID coverage and producer-declared
embedding_model, pipeline_id and input_hash. Mode embed validates newly generated
vectors; mode upsert validates all final payloads, including reused vectors.
Fingerprint provenance at the actual request boundary. A vector cannot prove its
own model identity; attaching correct-looking labels after the fact defeats the
check. Duplicate vectors and configured norm outliers warn, because identical
inputs can legitimately produce identical vectors.

## Deletion rules

A candidate document replaces the full prior document; assemble partial extraction
batches into a complete document before validation. Omitted documents are preserved.
Whole-document retirement requires an explicit named retire_documents entry.

Retirements and validated named `allow_shrink` documents are excluded from both
the ordinary deletion numerator and denominator. Named allowances retain their own
per-document fraction checks; unrelated documents retain the default 25% limit.
An independent corpus limit defaults to 15% of **full committed ordinary chunks**,
including untouched documents. Optional absolute budgets default to None. SQLite
uses a SQL count aggregate rather than loading every payload. Per-document checks
run first, sorted by document ID. Plans record effective policy and relevant counts.
These are initial configurable policies, not universal safety guarantees; they do
not bypass source completeness, namespace or model checks. See [policy and migration
notes](api.md#deletion-policy). Per-plan limits do not impose cumulative job limits.

## Apply ordering and failure recovery

1. Read committed state and build a validated candidate from the source manifest.
2. Produce a plan; retain candidate text and metadata keyed by stable chunk ID.
   Hash-only snapshots cannot reconstruct upload payloads.
3. Generate and validate the requested new vectors. Assemble and validate all
   upsert payloads. For metadata-only changes, reuse a vector only when its original
   provenance matches; regenerate missing or invalid reusable vectors.
4. Acquire an application namespace lock, re-read committed revision and verify
   the plan's base. Hold concurrency protection through write and state commit.
   Recheck source versions and authorization.
5. Confirm all upserts and the visibility required by your database before deleting
   old IDs. Delete only the planned IDs within the correct namespace; make retries
   idempotent. Confirm deletion success.
6. Commit state only after successful required external operations. Release the lock.

A failure after partial upserts can expose mixed versions to readers even if the
ledger has not advanced. Replay the same plan against unchanged committed state;
do not infer committed state from a partially written vector database. For strict
reader consistency, write a new generation/collection and switch a reader-visible
pointer atomically, then clean old generations later. The library does not implement
that mechanism. Model/dimension changes may require a new physical collection.

JSON UpdatePlan.assert_base and indexed store.assert_base are comparisons, not locks.
A successful check followed by unlocked external writes still has a race.

## Storage choices and schema

Portable JSON Snapshot schema 1 remains unchanged and loadable. It is suitable for
small inventories and explicit exports. It loads the full supplied snapshot.
Source-manifest unit aliases are separate from this hash-only snapshot schema.
Snapshot.save uses file fsync and atomic replacement, not a CAS operation or
cross-store transaction, and does not promise directory-entry power-loss durability.

SQLiteSnapshotStore uses schema 2 (transactionally migrated from schema 1): an indexed document table of
per-document snapshot blobs plus namespace/model/pipeline/revision state. Planning
loads touched documents only. A stored plan's nested target contains only that
scope; store.commit merges it transactionally into the ledger. Never use that target
to replace the entire corpus through a separate snapshot save.

Store commits use BEGIN IMMEDIATE and a revision comparison. Stale commits are
rejected; a failed transaction rolls back all ledger writes. The WAL/synchronous
settings govern local SQLite persistence. They do not protect a vector database.
SQLite paths should be on filesystems appropriate for SQLite locking; this backend
is not a distributed/cloud object store. Store files/WAL state belong to the
application's operational backup strategy.

Initial imports can be performed one complete document/batch at a time. The store
loads/hashes only touched document payloads on subsequent plans. Large individual
documents still require memory for that document. Model/pipeline migrations require
all retained documents and can therefore be expensive. Schema versions are checked;
unsupported versions are rejected, not silently migrated.

## Trust, resource limits and observability

Create candidates with build_snapshot. Public Python Snapshot constructors and
Snapshot.from_dict/load are for trusted persisted state; constructing one manually
bypasses source validation. Fingerprints detect accidental changes, not malicious
recomputation. Protect your ledger. Hashes are not encryption: identifiers, source
versions and chunk keys can be sensitive, and low-entropy content may be guessed.

A ledger does not prove vector-store integrity after external deletion or corruption.
Reconciliation with the live store is a separate task. A no-op plan will not restore
records removed outside the controlled pipeline.

Core audits materialize a batch; bound input sizes and never mutate records during
validation. Duplicates/boilerplate checks only see the submitted batch. SQLite fixes
whole-corpus planning for partial updates, not every in-memory limit. Optional NumPy
validation is per vector, with extra memory proportional to vector dimensions.
Log plan IDs, base/target revisions, scoped exceptions, check coverage, counts,
latency and rejected operations, without unnecessarily exposing raw content.

The public-corpus trial uses actual documents but dummy vectors. No live embedding
provider, vector-database visibility/failure semantics, distributed lock, million-
chunk load test or security audit has been completed for this release. Add those
integration checks for your deployment before production adoption.

## Operator verification and reconciliation

SQLite is the recommended operational ledger. Use JSON as a portable snapshot
format or a small-corpus alternative, with the same shared planning guards.
`document_ids()` returns sorted IDs (memory proportional to document count).
`verify()` walks every payload and reports corrupted document IDs, revision or
configuration mismatches, invalid stored chunk counts, and SQLite integrity errors.
Severe SQLite damage can raise `sqlite3.DatabaseError`; treat that as verification
failure and restore a trusted backup. Verification never repairs data. It loads
one document at a time, but the report grows with detected failures. Hashes detect
accidental corruption, not an attacker who rewrites both data and hashes. The CAS
revision token cannot authenticate a deleted row or reconstruct ledger history.

`chunk_ids()` streams verified IDs under a consistent read transaction. Exhaust or
close the generator before another transactional method on that store connection.
A long read can retain WAL history while other connections write. Do not share a
store instance concurrently across threads.

```python
from rag_preflight import reconcile
ledger.verify().raise_for_errors()
report = reconcile(
    ledger.chunk_ids(),
    vector_ids_from_complete_namespace_scan,
    namespace='tenant-a/kb',
    inventory_complete=True,
)
if not report.passed:
    print(report.to_dict())
```

`missing_ids` exist in the ledger but not the vector store; `orphan_ids` exist only
in the vector store. Counts cover all entries; ID samples default to 100 per kind.
Duplicate input IDs also fail. Inputs stream into a temporary disk-backed SQLite
index; disk space grows with the inventory, rather than Python sets holding all
IDs in memory. Temporary files are removed on success or failure. The caller must
provide matching namespace/generation scope and explicitly attest that **both**
scans are complete. Incomplete scans produce a report that cannot pass.

Post-commit reconciliation checks drift against the committed ledger. To verify
apply **before commit**, compare the complete intended target namespace against a
complete, consistent vector-store enumeration after writes become visible. For a
partial StoredPlan, build the intended stream from old ledger IDs excluding
`update.removed`, followed by `update.added`; the changed IDs already exist. Do not
compare `StoredPlan.update.target.chunks` alone against a whole namespace: that
snapshot only covers the touched documents. Example inside the application's lock:

```python
ledger.assert_base(stored_plan)
# Apply exact upserts/deletes and wait for the store's documented read visibility.
removed = set(stored_plan.update.removed)

def intended_ids():
    for chunk_id in ledger.chunk_ids():
        if chunk_id not in removed:
            yield chunk_id
    yield from stored_plan.update.added

report = reconcile(intended_ids(), vector_ids_from_complete_namespace_scan,
                   namespace=stored_plan.update.target.namespace,
                   inventory_complete=True)
if not report.passed:
    raise RuntimeError('Vector ID apply verification failed; keep the old ledger revision')
ledger.commit(stored_plan)
```

ID agreement cannot detect an existing ID with the wrong vector, stale text or
metadata. Verify payload hashes/provenance through your store adapter when those
matter. `commit()` does not call the vector database or enforce reconciliation;
the application remains responsible for this ordering, locking, retries and
recovery after partial external writes. No cross-store atomic transaction is claimed.

Batch deletion budgets are local to a single plan. Splitting a full migration
into many small commits can avoid a count threshold. Review the complete migration
or maintain job-level cumulative budgets in the orchestrator. Initial imports have
no previous chunks to delete and do not consume these budgets.


## New evidence workflows

Use [existing-index audits](existing-index.md) for source/export comparison without
adopting this ledger. Complete scope flags are application attestations, not inferred
from newly extracted files. Keep scans consistent and inspect unverified checks.
For database/API/crawler jobs, [run receipts](api.md#run-receipts-for-rows-apis-and-crawlers)
record independently enumerated IDs and outcomes; bounded/delta runs cannot establish
whole-corpus coverage or deletion eligibility. Persist large inventories externally.

Use `report.metrics()`, `plan.metrics()` and baseline comparison metrics in structured
logs. These default measurements omit raw identity labels. Record completed embedding
requests separately. Cost estimates need actual preprocessed request token counts and
an explicitly named comparison batch; retain text/count evidence beside hash-only
snapshots. Text-scoped baselines can tolerate unrelated metadata backfills; strict
mode remains default. Version baseline policy scopes when thresholds or batch-relative
rules change. Namespace metadata is optional unless required by policy, and supplied
namespace contradictions fail. Namespace consistency is not access control.


## Cumulative deletion monitoring

After successful external operations and ledger commit, log
`ledger.deletion_summary(last_commits=4)`. Four individually safe batches can still
shrink the corpus by 40%; the summary surfaces that slide. Compare both gross ID
removals and net inventory decline, and inspect exempt removal categories. Additions
or rekeying can make these measures diverge. Before-write cumulative enforcement
still belongs to the orchestrator; this release adds history, not a hard gate.
See [window definitions and migration](api.md#cumulative-deletion-visibility-sqlite).

The separate [integration validation contract](integration-validation.md) defines
embedding, read-back and crash/recovery checks. Chroma and FAISS reference
applications now exist outside the core. They retain both simulated failure tests
and bounded live OpenAI evidence for ingestion, retrieval, omission and selective
re-embedding. They are executable test harnesses, not core SDK integrations or
production-service guarantees.


For scheduled monitoring use `rag-preflight ledger summary ledger.db --json`.
Inspection is read-only, does not create a missing file or implicitly migrate an old
ledger. The default window now excludes the initial population prefix when it would
otherwise prevent meaningful fractions and subsequent commits provide a comparison.
Check `window_adjusted`, `initial_commits_excluded` and `baseline_basis` in logs.
Later full retirements/re-population remain in the data. Ratios for genuinely zero
baselines stay null; this is not evidence of zero deletions.


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
