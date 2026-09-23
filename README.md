# RAG Preflight workspace

Private, unreleased workspace for RAG Preflight 0.1.0 and its reference
applications.

RAG Preflight validates source coverage, chunk integrity, embedding declarations,
and proposed ingestion changes. It produces reports and guarded update plans;
the integrating application controls embedding, retrieval, and vector-store
writes.

## Packages

| Directory | Purpose |
|---|---|
| `rag-preflight/` | Dependency-free core library and CLI. |
| `rag-preflight-reference-common/` | Shared application-only ingestion, OpenAI, evidence, and recovery workflow. |
| `rag-preflight-chroma-reference/` | Local Chroma/OpenAI research-paper reference application. |
| `rag-preflight-faiss-reference/` | Local FAISS/OpenAI research-paper reference application. |

Each package keeps its own README, changelog, tests, build metadata, and version.
All remain at version 0.1.0 and unreleased.

## Repository boundaries

Raw PDFs, virtual environments, API credentials, local vector state, run journals,
and built distributions are intentionally excluded from Git. The reference
applications retain source manifests, lock files, tests, and sanitized reviewed
evidence. See each package README for installation, corpus preparation, validation,
and known limitations.

No component treats namespace checking as access control, reconciliation as vector
content verification, citation labels as factual proof, or a successful local test
run as production history.
