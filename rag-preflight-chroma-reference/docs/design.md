# Chroma reference: requirements, design and acceptance contract

The guarded pipeline, source inventory, OpenAI request boundary and operation
journal are shared with the FAISS application through the separate
`rag-preflight-reference-common` package. This project supplies the Chroma
adapter and local configuration. The shared package is outside the dependency-
free RAG Preflight library core.

This project is an executable integration, not a second library feature set. It
consumes a private 0.1.0 RAG Preflight wheel. The library's separate folder-check
helpers and optional Office extras do not add OpenAI or Chroma to its core.

## Requirements trace

| ID | Behavior | Evidence / regression |
|---|---|---|
| R1 | Independently enumerate exact supported PDF scope before extraction. | Pinned manifest, page counts, hash checks; missing-source test. |
| R2 | Fail before paid API or vector mutation on missing/failed units and bad chunks. | Extraction receipts, `audit_ingestion`, `audit_chunks`, omission test. |
| R3 | Embed only guarded `plan.embed_ids`, with request-boundary usage evidence and budget. | Cost estimate, embedding audit, event log, metadata-only/no-op tests and bounded live calls. |
| R4 | Store explicit text, metadata and vectors in persistent Chroma; reopen/read back all three. | Complete ID/payload/vector checks, drift test and bounded live read-back. |
| R5 | Keep Chroma apply and SQLite commit ordered, journaled and recoverable. | Upsert-verify-delete-verify-commit sequence; interruption and post-commit repair tests. |
| R6 | Compare naive omission with guarded rejection without harming main index. | Isolated cloned Chroma collection; page:2 scenario. |
| R7 | Ask with real query embeddings, retrieved paper/page labels and limited OpenAI generation. | `ask` command and live question-bank run; human citation review pending. |
| R8 | Maintain separate configuration, state, evidence and dependency versions. | `requirements.lock`, run artifacts, ignored state, operator review. |
| R9 | Present offline evidence without suggesting semantic retrieval proof. | Curated run checks, per-row simulated labels, no simulated distances. |
| R10 | Expose a selective text-edit plan and same-question omission comparison. | Live synthetic two-chunk clone and live shared-query comparison; causal interpretation remains human-reviewed. |

## Apply state machine

```text
independent PDF inventory -> extraction receipts -> audits -> candidate snapshot
-> ledger plan -> exact-token estimate and budget -> pending journal
-> OpenAI embedding batches -> plan-linked vector audit
-> Chroma upserts -> upsert read-back -> explicit-ID deletions
-> complete ID/text/metadata/vector read-back -> SQLite ledger CAS commit
-> last committed payload evidence -> run summary
```

The journal persists full candidate text and received vectors locally. A crash
between a successful provider response and the journal fsync can still repeat a
paid call on recovery; the application does not claim exactly-once API billing. Run
summaries name the provider type; simulated-provider runs explicitly mark live
OpenAI calls unverified. On restart,
it reuses successfully received vectors. If the ledger base changed, recovery does
not replay writes: it accepts only a no-op plan plus full Chroma read-back against
the recorded target. Otherwise it requires operator action. This is local crash
recovery, not distributed atomicity. No deletion happens on a failed audit.

The app's writer lock spans plan and apply. This coordinates its own local processes;
it cannot lock external Chroma clients or a changing source filesystem. A full
same-scope Chroma enumeration and ledger reconciliation is required before a new
operation. Chroma offset scans rely on stable writes. The required list of PDFs is
fixed by the manifest; editing PDF bytes requires an explicit new manifest and
operator review, not silent adoption of a changed file. The lock uses `fcntl`;
Windows has not been validated. Wheel/sdist handoffs exclude `.venv`, Chroma
state and full run journals.

`source_id` is the exact PDF filename within the explicitly scoped sibling directory.
It is not inferred from a basename search across arbitrary paths. Chunk keys are
page-local ordinals and can shift after insertion. Page-boundary splitting and PDF
parser ordering are known quality constraints; they do not invalidate inventory
checks but can affect retrieval. Fixed model/pipeline IDs are declared provenance,
not cryptographic proof of model execution. Request-boundary OpenAI events provide
stronger observational evidence but still depend on honest client logs.

## Acceptance gates

1. **Local design gate:** all downloaded PDFs parse, page counts/hash/title/version
   agree locally, full candidate audits pass, Chroma fake-provider tests pass.
2. **Live embedding gate:** `OPENAI_API_KEY` available; successful OpenAI responses
   observed; measured usage and vectors recorded; Chroma reopened and payloads
   verified. A dummy-vector run cannot satisfy this gate.
3. **Failure/recovery gate:** isolated omission comparison and durable interrupted
   apply, restart and read-back verified against live-index generation.
4. **QA gate:** chosen generation model, bounded question set, retrieved citations,
   abstention behavior and answer-support review recorded. Citation syntax alone
   cannot prove factual support.
5. **Transfer gate:** independent engineer repeats the commands in a new local
   environment and records friction/false positives. Until this happens, the
   integration is evidence-producing but not operationally proven.

Do not claim a live gate passed because a unit test passed. Any blocked gate stays
explicitly unverified in `docs/validation.md` and reviewed results.


The journal holds the full three-paper payload and vectors in one JSON document.
This is deliberate for a bounded reference corpus and is **not** a scalable journal
format for millions of chunks. An external vector writer, mutable PDF directory,
or multi-host worker requires generation control beyond this local application.
Retrieved paper text can also contain instructions; the generation prompt is not
a security boundary. Citation syntax does not prove factual support.
