# Changelog

## 0.1.0 (unreleased)

- Add an actionable tiktoken proxy/offline-cache error and verified manual cache
  instructions for first-run environments that block the tokenizer host.
- Add a reusable `assert_vector_store_contract()` utility and self-tests for new
  reference adapters; Chroma and FAISS run the same contract. Contract checks
  use explicit failures and remain active when Python runs with `-O`.
- Extracted the shared application-only pipeline from the Chroma and FAISS
  reference projects behind a small vector-store interface.
