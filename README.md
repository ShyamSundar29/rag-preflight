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

## Clone quickstart

The reference corpus is public but intentionally not committed. From a clone,
create an application environment, install all local packages from source, then
download and verify the exact versioned PDFs:

```sh
python3.12 -m venv rag-preflight-chroma-reference/.venv
rag-preflight-chroma-reference/.venv/bin/python -m pip install -r rag-preflight-chroma-reference/requirements.lock
rag-preflight-chroma-reference/.venv/bin/python -m pip install --no-deps -e rag-preflight -e rag-preflight-reference-common -e rag-preflight-chroma-reference
rag-preflight-chroma-reference/.venv/bin/python scripts/fetch_corpus.py
rag-preflight-chroma-reference/.venv/bin/python -m rag_preflight_reference verify-papers
rag-preflight-chroma-reference/.venv/bin/python -m rag_preflight_reference dry-run
```

The FAISS README gives the matching FAISS commands. Corpus setup downloads only
the URLs in the pinned manifest and verifies SHA-256 and page counts before
publishing each file under the ignored `pdfs/` directory.
If a proxy blocks arXiv, the error names the exact URL, expected SHA-256 and
destination path. Download that versioned file on an approved connected machine,
copy it to the stated path, and rerun; existing valid files are verified offline.

## Repository boundaries

Raw PDFs, virtual environments, API credentials, local vector state, run journals,
and built distributions are intentionally excluded from Git. The reference
applications retain source manifests, lock files, tests, and sanitized reviewed
evidence. See each package README for installation, corpus preparation, validation,
and known limitations.

No component treats namespace checking as access control, reconciliation as vector
content verification, citation labels as factual proof, or a successful local test
run as production history.
