# Changelog

## 0.1.0 (unreleased)

- Replace the POSIX-only writer lock with dependency-free `fcntl`/`msvcrt`
  locking and test real two-process exclusion on Linux and Windows.
- Record requested and API-returned embedding/generation model names.
- Add an isolated live selective-edit scenario that embeds exactly the planned
  inputs while preserving the guarded main index.
- Add MIT license metadata and clone-safe repository packaging.
- Add an actionable tiktoken proxy/offline-cache error and verified manual cache
  instructions for first-run environments that block the tokenizer host.
- Add a reusable `assert_vector_store_contract()` utility and self-tests for new
  reference adapters; Chroma and FAISS run the same contract. Contract checks
  use explicit failures and remain active when Python runs with `-O`.
- Extracted the shared application-only pipeline from the Chroma and FAISS
  reference projects behind a small vector-store interface.
