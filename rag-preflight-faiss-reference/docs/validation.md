# Validation status - 2026-09-25

The FAISS application is separate from the core library and the Chroma reference.
Its pinned corpus is the same three local PDFs, 67 independently listed pages and
171 page-local candidate chunks. The source manifest records file SHA-256 values.

The local Python 3.12 suite passes 20 tests; regression scenarios use a simulated provider.
It covers pinned-source validation, first ingestion, no-op and metadata-only
re-ingestion, selective edit preview, exact FAISS search after restart, isolated
omission, rejection before main-index writes, payload/ID drift, interruption,
journal recovery, citations and provider-request boundaries. Mypy passed on all
nine application source files. It now also runs the reusable shared adapter
contract. The common package passes two self-tests covering that contract and the
restricted-network tokenizer diagnostic. These are local results, not live provider proof.

The bounded live acceptance begun on 2026-09-23 and extended on 2026-09-25 used `text-embedding-3-small` and
`gpt-5.6-luna`. Initial ingestion completed 171 inputs in 11 embedding requests
with 67,083 measured input tokens. Complete read-back verified 171 IDs and
payloads. Unchanged and metadata-only runs each performed zero embeddings. An
isolated synthetic two-chunk edit completed exactly two embedding inputs. All four
fixed questions ran live, and the unrelated parking-policy question correctly
abstained. The page-2 omission remained answerable from repeated page-9 evidence.
A second live comparison removed page 4: the intact index answered its 100-word
chunking fact, while the omission clone stated that its passages did not specify
the answer. The sanitized
record is `reviewed-results/live-openai-evidence.json`; it includes requested and
returned model names, per-request token counts and input hashes, while excluding
API keys, request IDs, vectors and raw source text. On 2026-09-26, repository
owner Shyam Sundar reviewed the page-4 intact answer's factuality and citation,
the damaged answer's factual refusal, and the observed causal difference. Its
damaged-answer citation claim and the other answers remain unreviewed unless their
fields say otherwise. Provider billing, broad retrieval quality and production
reliability remain unverified.

The shared application-only package owns ingestion, provider requests, journal
and CLI dispatch; this project owns the 120-line FAISS adapter and settings.
The payload JSON file is authoritative local state. The FAISS `IndexFlatL2`
search index is rebuilt from it after restart. Full-payload rewrite cost, memory
growth, local `fcntl` lock and lack of distributed coordination limit this
reference design to controlled small corpora. Chroma and FAISS results should
be compared with the same source hashes, question set and generation model; do
not compare simulated-vector rankings as retrieval-quality evidence.

The durable offline run is summarized in `reviewed-results/offline-evidence.json`
and curated per-run JSON. It used `SimulatedProvider` with zero paid calls. Full
journals and local FAISS payload state remain ignored under `runs/` and `state/`.
