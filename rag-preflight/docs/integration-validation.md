# Real integration validation: separate application

Two separate research-paper RAG reference applications and executable integration
harnesses now exist: one for Chroma and one for FAISS. Both retain bounded live
OpenAI evidence alongside simulated failure/recovery tests. The live three-paper
trial does not establish broad retrieval quality or production reliability. They
share an application-only pipeline package and keep store-specific
adapters and dependencies in their own projects. Their
embedding/tokenizer/vector-store/application dependencies remain in its own project
and lockfile. No SDK, model runtime, retrieval framework or chatbot enters core.

## What belongs in the library

Framework-neutral source/receipt validation, chunk integrity, guarded plans,
embedding-declaration checks, ID reconciliation, namespace consistency, explicit
cost evidence, reports/metrics and SQLite history already belong here. The final
review fixes improve these APIs. Additional core features should follow a reproducible
integration failure the current contracts cannot handle, rather than speculative
provider abstractions. Cumulative history currently provides visibility; optional
before-write job-budget enforcement is a separate policy decision, not implied.

## Application acceptance contract

| Scenario | Required observable evidence |
|---|---|
| First ingestion | Independently inventoried source units, real model/tokenizer configuration, exact embedding inputs/counts at request boundary, vector validation, durable ledger commit. |
| Repeat unchanged ingestion | No new embedding calls; vector/index inventory still agrees. |
| Metadata-only edit | Zero new embedding calls when matching vectors are reusable; read-back shows changed metadata. |
| One text edit | Calls correspond to planned changed inputs; vector/text/provenance read-back matches intended update. |
| Dropped document/page | Independent receipt/audit fails before embedding or vector writes; comparison without Preflight demonstrates actual missing representation. |
| Chunker/parser shrink regression | Guard rejects unsafe deletion before vector mutation. Four safe batches expose rolling cumulative decline, without claiming a hard cumulative gate. |
| Partial vector-write failure | Ledger remains on previous committed revision; persisted operation journal permits an idempotent retry or explicit rollback. |
| Crash after writes, before ledger commit | Restart reads actual database state and journal; no guessed success or automatic blind deletion. |
| Concurrent/stale writer | Application namespace lock/generation switch plus stale-base rejection prevents overlapping destructive apply. |
| Drift/read-back failure | Missing/orphan IDs detected by complete same-scope scans; wrong vector/text/metadata detected through explicit payload comparisons. |
| Query and citations | Real retrieval returns source path/unit citations checked against the retained source evidence; hallucinated references are not accepted. |

Run each applicable scenario with and without Preflight on the same input and
model/index configuration. Record actual calls, indexed IDs/content, failure timing,
restart behavior, and operator effort. A passing ID comparison is not a vector-
content check; matching producer model labels are not proof of model execution.

## Implemented structure and remaining exit criteria

1. The Chroma adapter and durable journal are implemented outside the library.
   Offline tests exercise persistent writes, read-back and restart recovery.
2. The bounded OpenAI acceptance runs retain request-boundary token evidence,
   requested and returned model identifiers, and sanitized results. API keys,
   vectors, request IDs and raw source text are excluded. Do not generalize these
   runs into provider reliability or broad retrieval-quality claims.
3. Fault and restart/recovery checks are automated with persisted local evidence.
   A live comparison must be repeatable by another engineer. Its report must state what was actually
   exercised and what remains unverified.
4. The FAISS application uses an application-owned ID/text/metadata/provenance
   mapping, atomically persisted local payloads and a rebuilt exact FAISS index.
   Its persistence/deletion behavior is tested for this small corpus. Do not assume
   Chroma semantics transfer unchanged, and do not treat this full-payload rewrite
   design as a large-corpus store.
   FAISS documents that deletion can shift IDs in sequential indexes, while explicit
   ID mappings behave differently: [official operation semantics](https://github.com/facebookresearch/faiss/wiki/Special-operations-on-indexes).
5. Have engineers attach Preflight to existing pipelines. Record time to first useful
   finding, additional source evidence required, legitimate updates blocked, false
   positives and prevented failures. Use those observations to improve documentation
   or narrowly scoped APIs.

The outcome is a maintained reference integration that engineers can adapt, plus
regression evidence for the library. It is not automatically a deployable production
chatbot. Application access controls, provider reliability, retrieval quality,
backup, crash consistency and operational ownership need their own validation.
Both applications have offline vector-store verification and completed bounded
OpenAI ingestion and answer runs. Neither is production-proven by the three-paper
test corpus.
