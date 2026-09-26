# Research-paper RAG: FAISS reference application

**Version 0.1.0, unreleased.** This is a separate application of RAG Preflight
for the same three PDFs in `../pdfs/`. It calls OpenAI explicitly for embeddings
and citation-bearing generation when a local `OPENAI_API_KEY` and generation model
are provided. It does not add FAISS, OpenAI, or application dependencies to the
library core. The Chroma application remains separate. Both applications depend
on the application-only `rag-preflight-reference-common` package for the PDF
inventory, OpenAI requests, guarded apply, journal and CLI workflow. Each owns
its own configuration and vector-store adapter; neither imports the other's SDK.

FAISS is an in-process similarity-search library, not a transactional vector
database. This application stores authoritative text, metadata and vectors in
an atomic local JSON payload file and rebuilds an exact `IndexFlatL2` FAISS index
from that file on restart. This design makes the small fixed corpus testable but
rewrites the full payload on each mutation. It is **not** a scaling claim for
large corpora or distributed/multiwriter systems. The application holds one
local `fcntl` writer lock, journals unfinished operations, verifies payloads and
complete IDs, then commits the Preflight SQLite ledger. External writes and
ledger commits are not atomic together. macOS/Linux Python 3.12+ is the
supported local test scope; Windows is unvalidated.

## Install and inspect without API calls

From this directory, use Python 3.12+ and install the unpublished packages from
the sibling source directories in the clone:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e ../rag-preflight
.venv/bin/python -m pip install --no-deps -e ../rag-preflight-reference-common
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python ../scripts/fetch_corpus.py
.venv/bin/python -m rag_preflight_faiss_reference verify-papers
.venv/bin/python -m rag_preflight_faiss_reference dry-run
```

The corpus script downloads only the three versioned arXiv URLs in the pinned
manifest, checks every SHA-256 and page count, and atomically publishes valid
files under the ignored sibling `../pdfs/` directory. It refuses unexpected PDFs
and mismatched existing files.
If a proxy blocks arXiv, the error names the exact URL, expected SHA-256 and
destination path. Download that versioned file on an approved connected machine,
copy it to the stated path, and rerun; existing valid files are verified offline.

Start with `rag-preflight check ../pdfs --expected corpus/expected-files.txt`
when using the updated library wheel. Keep the independent list outside the
source folder. This checks current source coverage; `verify-papers` adds pinned
hashes/page counts, and `verify-index` checks this application's indexed state.

The first tokenizer use may download encoding data. `verify-papers` checks the
pinned hashes and independently listed page counts before extraction. `dry-run`
reports the guarded plan and actual tokenizer-input counts without spending API
credits. The data comes from `openaipublic.blob.core.windows.net`; restricted
environments can pre-populate the verified file described in the shared package's
`TOKENIZER_CACHE.md` and set `TIKTOKEN_CACHE_DIR`. Failures print those recovery
details without a raw proxy traceback. Estimated embedding cost uses a caller-supplied price, defaults to
`$0.02` per million tokens, and is **not** provider billing evidence. Set
`--embedding-price-per-million` and `--embedding-budget-usd` before the command
to reflect current prices and your limit. The default ingestion budget is $0.25;
query embedding, generation, retries and network/database costs are outside it.
Generation defaults to a 300-token output cap; use `--max-output-tokens` before
the command when the selected model needs a larger explicit cap.

## Live end-to-end run

Set `OPENAI_API_KEY` locally, never in the repository or chat. After reviewing
the dry-run and the model's current price, run:

```sh
.venv/bin/python -m rag_preflight_faiss_reference ingest
.venv/bin/python -m rag_preflight_faiss_reference verify-index
.venv/bin/python -m rag_preflight_faiss_reference ingest  # expected: zero new embeddings
.venv/bin/python -m rag_preflight_faiss_reference ingest --metadata-tag reviewed
.venv/bin/python -m rag_preflight_faiss_reference demonstrate-omission 2005.11401v4.pdf page:4
.venv/bin/python -m rag_preflight_faiss_reference demonstrate-text-edit 2005.11401v4.pdf
.venv/bin/python -m rag_preflight_faiss_reference ask \
  "What two kinds of memory does RAG combine?" --generation-model MODEL_ID
.venv/bin/python -m rag_preflight_faiss_reference compare-omission OMISSION_RUN_ID \
  "How is each Wikipedia article split to build RAG's document index?" \
  --generation-model MODEL_ID
```

`demonstrate-omission` deletes a page's records only from a separate local clone,
shows that a naive replacement would lose them, and confirms that Preflight
rejects the incomplete candidate before API calls or main-index writes. A
matching citation label proves only that the answer refers to a retrieved chunk;
it does not prove the statement is true. Another page may contain the answer,
so the omission comparison needs human review. The generation model remains
caller-selected. The bounded 2026-09-21 acceptance run used `gpt-5.6-luna`;
callers should select and evaluate the model appropriate for their own accuracy
and cost requirements.

In the pinned extracted fixture, the 100-word chunking fact appears on page 4.
The live intact index answered with that fact, while the verified page-4 omission
clone stated that its supplied passages did not specify the answer. The earlier
page-2 comparison remains in the evidence as a counterexample: repeated evidence
on page 9 kept that answer available despite the omission. The repository owner
reviewed the page-4 intact answer, its page-4 citation, the damaged answer's
factual refusal, and the observed causal difference on 2026-09-26; the damaged
answer's separate citation-support flag remains unreviewed.

`demonstrate-text-edit` modifies exactly two synthetic chunk inputs, embeds only
those inputs, verifies an isolated clone, and leaves the PDFs, ledger, and main
index unchanged. It proves selective API execution, not a real document edit.

To test crash recovery, use an isolated `--state-root` and `--runs-root`, run
`ingest --fail-after-upserts`, then `recover` and `verify-index`. The operation
journal prevents new writes until recovery. `preview-text-edit` is a plan-only
synthetic change; it never edits a PDF or makes a paid call.

## Evidence and limits

| Location | Contents |
|---|---|
| `../pdfs/` | Original user-provided papers; not copied into this project. |
| `corpus/manifest.json` | Independent expected PDF names, byte hashes, page counts. |
| `state/faiss/*.json` | Local text, metadata and vectors; FAISS index rebuilt from these. |
| `state/ledger.db` | Preflight committed inventory. |
| `state/pending-operation.json` | Durable operation journal with local raw payloads. |
| `state/committed-payloads.json` | Independent payload reference for read-back. |
| `runs/<run-id>/` | Audits, plans, API events, verification and summaries. |
| `reviewed-results/` | Curated simulated checks and a sanitized bounded live-run summary. |

`state/`, `runs/` and `.venv/` are ignored. Do not publish raw papers, vectors,
journals or API keys. The offline tests use simulated vectors and no paid calls;
they establish control flow and recovery, **not** live OpenAI accuracy or
retrieval quality. A clean `verify-index` checks this application's payloads and
IDs but cannot prove every paragraph was extracted or every cited answer is
factually supported. The three-paper corpus is a limited acceptance fixture,
not an operational track record.

The sanitized [live evidence](reviewed-results/live-openai-evidence.json) records
bounded runs through 2026-09-25 with 171 real `text-embedding-3-small` vectors, complete
FAISS payload/ID read-back, zero new embeddings for unchanged and metadata-only
runs, a live two-chunk selective edit, four `gpt-5.6-luna` answers including an
out-of-scope abstention, a redundant page-2 omission, and a page-4 unique-fact
comparison whose damaged clone could no longer supply the chunking answer.
The record includes requested and returned model names plus per-request token
counts and input hashes. It excludes API keys, vectors, raw source text and request
IDs. It does not verify provider billing, broad retrieval quality, citation
support, factuality, or production reliability.

Run `.venv/bin/python -m unittest discover -s tests -v` for local tests.
The FAISS adapter also runs the reusable
`rag_preflight_reference_common.testing.assert_vector_store_contract` suite.
`scripts/offline_evidence.py` regenerates the curated simulated-run evidence in
an isolated ignored `state/offline-evidence/` and `runs/offline-evidence/`. Inspect
those paths before rerunning; the script refuses to overwrite them. Its
[reviewed summary](reviewed-results/offline-evidence.json) records zero paid
calls, 171 first-ingestion inputs, zero inputs on unchanged/metadata-only runs,
an isolated three-ID page omission, and preserved guarded-index state.
