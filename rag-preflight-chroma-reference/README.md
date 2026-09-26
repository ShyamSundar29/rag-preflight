# Research-paper RAG: Chroma reference application

**Separate application, version 0.1.0, unreleased.** This integrates the already-built
RAG Preflight wheel with PDF extraction, implemented explicit OpenAI embedding calls, persistent
local Chroma, guarded ingestion, read-back verification, recovery and citation-bearing
question answering. It does not add Chroma, OpenAI or chatbot dependencies to the
RAG Preflight library core. A separate FAISS reference application now exists;
its tests and evidence are reported in its own directory, not here. Both depend
on the application-only `rag-preflight-reference-common` package for the shared
source inventory, OpenAI requests, guarded apply, journal and CLI workflow.
This project owns the Chroma adapter and its configuration; it does not import
FAISS.

**Platform scope: Python 3.12+ on macOS, Linux, and Windows.** The local writer
lock uses `fcntl` on macOS/Linux and `msvcrt` on Windows; hosted CI runs the full
clean-clone application suite on Linux and Windows. The bounded live evidence described below
uses real OpenAI embeddings and generation; it is acceptance evidence for this
fixture, not a production reliability claim.

The key comparison is at **re-ingestion**: a PDF page omitted downstream would
otherwise remove its indexed chunks. `demonstrate-omission` deletes records only in
an isolated clone and shows Preflight rejecting the same candidate before any API
or write on the guarded collection. The main collection is verified afterward.

The current bounded live and offline evidence is:

| Scenario | New embedding inputs | Estimated embedding cost at caller-supplied $0.02/M | Evidence |
|---|---:|---:|---|
| First three-paper ingestion | 171 | $0.00134166 | Live OpenAI embeddings; 67,083 measured input tokens and complete read-back |
| Unchanged candidate | 0 | $0 | Live run; persistent Chroma and ledger verified |
| Metadata tag only | 0 | $0 | Live run; vectors reused |
| Synthetic two-chunk text edit | 2 | $0.00001468 | Live OpenAI embeddings in an isolated clone; PDF and main index unchanged |
| Page omitted downstream | 0 before rejection | $0 before rejection | Guard rejects faulty receipt; isolated clone loses 3 IDs; live comparison recorded |

These costs exclude query embeddings, generation, retries, database and network
work. A real paragraph edit may touch a different number of chunks and can shift
ordinal identities. The preview does not show a real PDF edit or OpenAI billing.

## Downloaded corpus and verification

The three PDFs are in the sibling `../pdfs/` directory and are **not copied into**
this application. The pinned [manifest](corpus/manifest.json) records exact names,
arXiv pages, local file SHA-256 hashes and independently observed page counts. The
[verification record](corpus/verification.json) records local file-magic, page-tree,
extractable-text and visual first-page checks. The pages show the intended titles
and arXiv version marks; all 67 pages extract nonblank text. Each local PDF was byte-identical
to its version-pinned arXiv PDF downloaded temporarily for comparison. Keep the originals unchanged.

The three source files are 19, 18 and 30 pages. The current page-local splitter
produces 171 candidate chunks. ExtractionResult.chunks() splits **inside pages**;
it can cut context at page boundaries, and the word splitter normalizes whitespace.
This is an explicit quality limitation. Page metadata proves representation, not
that every paragraph is searchable. No OCR, table understanding or retrieval-quality
claim is inferred from PDF extraction alone.

## Install and run locally

Use Python 3.12+ on macOS, Linux, or Windows for this application. The local
cross-platform lock coordinates only this application's processes. The library
itself still supports 3.10+.
The frozen [dependency versions](requirements.lock) are separate from the library
and are the versions used for local validation. In a fresh application environment (for a wheel installed outside this folder,
pass `--app-root /absolute/path/to/rag-preflight-chroma-reference` before the command
or set `RAG_PREFLIGHT_CHROMA_ROOT` to that folder):

```sh
cd rag-preflight-chroma-reference
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e ../rag-preflight
.venv/bin/python -m pip install --no-deps -e ../rag-preflight-reference-common
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python ../scripts/fetch_corpus.py
.venv/bin/python -m rag_preflight_reference verify-papers
.venv/bin/python -m rag_preflight_reference dry-run
```

`fetch_corpus.py` is the clone-safe first-run step. It downloads only the three
versioned arXiv URLs declared in the manifest, verifies each SHA-256 and page
count, and atomically places valid files in the ignored sibling `../pdfs/`
directory. It refuses unexpected PDFs and never silently replaces a mismatched
existing file.
If a proxy blocks arXiv, the error names the exact URL, expected SHA-256 and
destination path. Download that versioned file on an approved connected machine,
copy it to the stated path, and rerun; existing valid files are verified offline.

Before adopting the application, the library's lower-friction front door can
check the same independent source list: `rag-preflight check ../pdfs --expected
corpus/expected-files.txt`. Keep the list outside the source folder. This checks
current source coverage; `verify-papers` adds pinned hashes/page counts, and
`verify-index` checks what the application committed to Chroma. See the library's
`docs/check-to-pipeline.md` for how those evidence levels connect.

`verify-papers` and `dry-run` make **no paid API calls**. The first tokenizer use may
fetch encoding data into ignored `state/tokenizer-cache`; a one-time network
connection to `openaipublic.blob.core.windows.net` is required unless that cache
is present. A blocked download produces cache-path and `TIKTOKEN_CACHE_DIR`
instructions instead of a proxy traceback. See the shared package's
`TOKENIZER_CACHE.md` for the URL, cache filename and SHA-256. The old
`RAG_PREFLIGHT_REFERENCE_ROOT` name remains a temporary Chroma-only alias; setting
both names to different paths is rejected. In the verified three-paper
candidate, the dry-run counted 67,083 actual tokenizer input tokens and estimated
$0.00134166 for first embeddings at the caller-supplied $0.02/M setting. This is an
**estimate**, not billing evidence. Recheck [current OpenAI model pricing](https://developers.openai.com/api/docs/models/text-embedding-3-small)
before a live run. Query embedding and generation costs are separate.

The default ingestion embedding budget is $0.25 and is checked against
estimated and measured token usage. The price is configurable: pass
`--embedding-price-per-million CURRENT_PRICE` and
`--embedding-budget-usd LIMIT` before the command when prices or your budget
change. Both settings must be finite and nonnegative. This cap does not include
query embeddings or generation.

For live embeddings, configure `OPENAI_API_KEY` in the local environment. Never put
it in a source file, `.env` committed to a repository, or chat. Confirm the key is
available to the process, then:

```sh
.venv/bin/python -m rag_preflight_reference ingest
.venv/bin/python -m rag_preflight_reference verify-index
.venv/bin/python -m rag_preflight_reference ingest  # repeat: expected 0 new embeddings
.venv/bin/python -m rag_preflight_reference ingest --metadata-tag reviewed
.venv/bin/python -m rag_preflight_reference demonstrate-omission 2005.11401v4.pdf page:4
.venv/bin/python -m rag_preflight_reference preview-text-edit 2005.11401v4.pdf
.venv/bin/python -m rag_preflight_reference demonstrate-text-edit 2005.11401v4.pdf
```

Choose the generation model explicitly for every live question. The bounded
acceptance evidence used `gpt-5.6-luna`; callers should pass the model appropriate
for their own evaluation and check its current pricing and access before asking:

```sh
.venv/bin/python -m rag_preflight_reference ask \
  "What two kinds of memory does RAG combine?" --generation-model MODEL_ID
.venv/bin/python -m rag_preflight_reference compare-omission OMISSION_RUN_ID \
  "How is each Wikipedia article split to build RAG's document index?" \
  --generation-model MODEL_ID
```

The application embeds both indexed chunks and questions with
`text-embedding-3-small`. It sends explicit vectors to Chroma, never delegates
embedding to Chroma's embedding function. Generation uses OpenAI Responses with
`store=False` and a configurable output cap that defaults to 300 tokens. Increase
it explicitly with `--max-output-tokens` when a model reports an incomplete
`max_output_tokens` response. The app records measured OpenAI token
usage and request IDs when available. No API key or raw paper text is included in
structured metrics or default event logs.
`compare-omission` verifies the clone, embeds one shared question once, and uses
the same query vector and generation model on both indexes. It records two
retrieval/answer views. Another page may contain the answer, so the clone need
not abstain; each recorded comparison requires human review to establish the
observed consequence.
In the pinned extracted fixture, the 100-word chunking fact appears on page 4.
The live intact index answered with that fact, while the verified page-4 omission
clone stated that its supplied passages did not specify the answer. The earlier
page-2 comparison remains in the evidence as a useful counterexample: repeated
evidence on page 9 kept that answer available despite the omission. The repository
owner reviewed the page-4 intact answer, its page-4 citation, the damaged answer's
factual refusal, and the observed causal difference on 2026-09-26; the damaged
answer's separate citation-support flag remains unreviewed.
The selective-edit command changes two synthetic chunk inputs, calls the embedding
provider only for those inputs, writes only to an isolated clone, and verifies the
main index remained unchanged. It does not claim that the underlying PDF changed.
The bounded live evidence includes this comparison; causal interpretation still
requires human review for each run because other indexed pages can contain the
same answer. The recorded page-4 run has that review; the page-2 result shows why
the review cannot be inferred automatically.

A write-interruption scenario is available with `ingest --fail-after-upserts`, but
run it in a disposable state directory or after backing up local state. It leaves
a durable pending operation and intentionally blocks ordinary ingestion/questions
until `recover` replays the recorded vectors or verifies post-commit state. The
ledger stays uncommitted until complete Chroma read-back succeeds. Chroma writes
and SQLite commits are **not atomic together**.

For offline regression checks, run `.venv/bin/python -m unittest discover -s tests -v`
and the application mypy command in [validation](docs/validation.md). The tests
execute local Chroma and use only a clearly labeled simulated provider; they do
not spend API credits.

The optional `scripts/offline_evidence.py` generates durable local Chroma state
and a [reviewed simulated-run summary](reviewed-results/offline-evidence.json)
with [curated run checks](reviewed-results/offline-runs/first/summary.json) that
ship without raw paper text, vectors or state. The summary names the ignored
full run files and a regeneration command. Simulated retrieval rows are
individually marked and omit meaningless SHA-vector distances.
Its `proof_kind` and unverified checks make clear that it spends **zero** API
credits and cannot substitute for live OpenAI integration.

## Storage and evidence

| Path | Role |
|---|---|
| `../pdfs/` | Original user-downloaded PDFs. |
| `corpus/manifest.json` | Independently expected filenames, hashes and page counts. |
| `state/chroma/` | Local persistent Chroma collection. |
| `state/ledger.db` | RAG Preflight's SQLite committed inventory. |
| `state/pending-operation.json` | Durable idempotent apply journal; includes full chunk text/vectors locally. |
| `state/committed-payloads.json` | Last independently recorded payload reference for complete read-back. |
| `runs/<run-id>/` | Audits, plans, cost estimate, request/write events, verification and summary. |
| `reviewed-results/` | Curated simulated checks and a sanitized bounded live-run summary. |

`state/`, `runs/` and `.venv/` are ignored by Git. Do not publish database files,
raw-text journals, API keys or full paper text without a separate license/privacy
review. Evidence is kept separately from Chroma so failed/replaced indexes do not
erase the sequence of events. [Design and acceptance criteria](docs/design.md) and
[local validation](docs/validation.md) state exactly which checks ran.

The library is suitable for controlled production evaluation as an ingestion guard. Through 2026-09-25 this
application completed bounded live runs with `text-embedding-3-small` and
`gpt-5.6-luna`; the sanitized [live evidence](reviewed-results/live-openai-evidence.json)
records 171 indexed chunks, complete read-back, zero embeddings on unchanged and
metadata-only runs, a live two-chunk selective edit, all four fixed questions,
an out-of-scope abstention, the redundant page-2 omission result, and a page-4
unique-fact comparison whose damaged clone could no longer supply the chunking
answer. This single three-paper run
does not establish retrieval quality, billing accuracy, production reliability,
or independent adoption. The app assumes one local writer using an advisory file lock; external writers, source
mutations and distributed deployments need their own coordination and recovery.
Namespace consistency is not access control. Citation labels refer to retrieved
passages, not verified answer factuality. Empty or weak retrieval should cause
abstention. Human citation-support and factuality review of the fixed
[question set](corpus/questions.json) remains outstanding. Evidence schema 3
records `reviewed`, `unreviewed`, and `not_applicable` at each reviewable claim
and derives a scenario-indexed `human_review_summary`; the current overall
status is `partial`.
Use the private wheel or source distribution for handoff. Both omit `.venv/`,
`state/` and `runs/`; zipping the working folder directly would include those
large local artifacts.

Official API references: [Chroma collection operations](https://docs.trychroma.com/reference/python/collection), [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings), and [OpenAI Responses text generation](https://developers.openai.com/api/docs/guides/text).
