# Changelog

## 0.1.0 (unreleased)

- Add clone-safe source installation, pinned corpus fetching, MIT licensing,
  clean-checkout CI, response-model evidence, and a live selective-edit command.
- Record a sanitized bounded live OpenAI/FAISS acceptance run without API keys,
  request IDs, raw paper text or vectors.
- Report tokenizer host/cache recovery instructions for restricted networks and
  run the reusable shared store-adapter contract against FAISS.
- Added a separate FAISS/OpenAI application for the same pinned three-paper
  corpus and Preflight guarded-ingestion contract used by the Chroma reference.
- Added exact L2 FAISS retrieval, atomic local payload state, restart rebuilding,
  omission comparison, read-back checks, operation journal and recovery.
- Moved duplicated ingestion, QA and CLI code into an application-only shared
  package; the FAISS adapter and settings remain independent from Chroma.
- Keep offline provider tests explicitly separate from the bounded live evidence.
