# Changelog

## 0.1.0 (unreleased) — shared application pipeline update

- Record a sanitized bounded live OpenAI/Chroma acceptance run without API keys,
  request IDs, raw paper text or vectors.
- Rename the application root variable to `RAG_PREFLIGHT_CHROMA_ROOT`; temporarily
  accept the older Chroma-only name and reject contradictory values.
- Report tokenizer host/cache recovery instructions for restricted networks and
  run the reusable shared store-adapter contract against Chroma.
- Extracted the duplicated ingestion, OpenAI request, journal and CLI workflow
  into the application-only `rag-preflight-reference-common` package. Chroma
  storage and settings stay here; the library core remains dependency-free.

## 0.1.0 (unreleased) — evidence and selective-edit update

- Ship safe curated offline run checks and explicit regeneration pointers.
- Mark simulated retrieval per row and omit SHA-vector distances.
- Add a plan-only synthetic two-chunk edit with exact input-token cost estimate.
- Add a read-only same-question omission comparison for future live OpenAI
  acceptance; answer loss remains a human-reviewed observation.
- Verify a second embedding batch failure persists the first successful batch,
  performs no Chroma write, and recovery requests only the remaining inputs.
- Make platform and Windows limits prominent.

## 0.1.0 - Unreleased

- Separate research-paper Chroma/OpenAI application and frozen local dependency list.
- Pinned three-paper PDF source manifest and local file/extraction verification.
- Guarded page-local ingestion, exact-token cost estimate and explicit embedding calls.
- Chroma upsert/read-back/reconciliation, durable journal and restart recovery.
- Isolated naive omission comparison and paper/page-cited question-answering path.
- Offline Chroma fault and regression tests plus bounded live OpenAI validation.
