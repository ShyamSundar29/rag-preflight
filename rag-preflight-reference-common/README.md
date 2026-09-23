# Shared reference application pipeline

**0.1.0, unreleased.** This application-only package holds the three-paper source
inventory, OpenAI request boundary, guarded plan/apply/recovery sequence, and CLI
dispatch used by the sibling Chroma and FAISS reference applications. It is not
part of the dependency-free RAG Preflight core. Store adapters implement the
small `VectorStore` protocol in `store.py`; their separate projects own storage,
index semantics and dependencies.

This package is a maintenance boundary, not a general vector-store SDK or a
production deployment abstraction. The offline tests in each application still
exercise its actual adapter. Live OpenAI calls remain unverified until a local
API key and generation model are configured.

Third adapters can run `assert_vector_store_contract(factory)` from
`rag_preflight_reference_common.testing`. The factory receives a `create` boolean
and must reopen the same isolated three-dimensional test store. The contract
checks complete ID enumeration, reads, replacement upserts, idempotent deletion,
nearest-query fields, persistence after reopen and full payload verification.

The first tokenizer use may need a separate data download even for `dry-run`.
Restricted-network setup and the verified cache artifact are documented in
[TOKENIZER_CACHE.md](TOKENIZER_CACHE.md). Loader failures are reported without a
raw proxy traceback and include `TIKTOKEN_CACHE_DIR` recovery instructions.
