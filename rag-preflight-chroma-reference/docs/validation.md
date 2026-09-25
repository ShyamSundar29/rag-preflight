# Validation status - 2026-09-23

The latest bounded live acceptance run completed the full four-question bank,
including a correct abstention for the unrelated parking-policy question. It also
performed exactly two OpenAI embedding inputs for an isolated synthetic two-chunk
edit. Requested and returned model names, per-request token counts and input
hashes are retained in the sanitized live evidence. The 11 initial embedding
requests total 171 inputs and 67,083 tokens. A live guarded-versus-omission query
changed retrieval and citations; it did not remove the answer because another
indexed page contained sufficient evidence. Human citation and factuality review
remains outstanding.

Local PDFs passed file-magic, SHA-256, `pdfinfo` page-tree, pypdf text extraction
and rendered first-page title/version checks. Counts: 19, 18 and 30 pages;
67 pages total and no extraction-empty page. Local-byte hashes are in the manifest.
All three version-pinned arXiv PDFs were byte-identical to the user downloads, and PDF content layout beyond first pages
was not visually reviewed in full.

The Chroma app uses Python 3.12.13, chromadb 1.5.9, OpenAI Python SDK 2.54.0,
pypdf 6.18.1, tiktoken 0.14.0 and the installed RAG Preflight 0.1.0 wheel.
The tokenizer encoding was downloaded into ignored application state. The local
candidate has 171 chunks and no ingestion or chunk-audit errors/warnings. Exact
first-ingestion embedding-input tokenizer count: 67,083. At supplied $0.02 per
million tokens, estimated embedding cost: $0.00134166. No paid API usage is inferred
from these numbers.

On 2026-09-21 a bounded live run used `text-embedding-3-small` and
`gpt-5.6-luna`. Initial ingestion completed 171 inputs in 11 embedding requests
with 67,083 measured input tokens. Complete read-back verified 171 IDs and
payloads. Unchanged and metadata-only runs each performed zero embeddings. One
question embedding used 10 tokens, and one Responses API call used 1,995 input
and 42 output tokens. The resulting answer cited retrieved passages 1 and 3.
The sanitized record is `reviewed-results/live-openai-evidence.json`; API keys,
request IDs, vectors and raw source text are excluded. Provider billing, citation
support, factuality, broad retrieval quality and production reliability remain
unverified.

The final source-tree check passed 15 tests on Python 3.12.13 in 43.520 seconds.
Mypy reported no issues in nine application source files, Python compilation
passed, and `pip check` found no broken requirements in the application venv.
The staged wheel and source distribution were built outside the source directory.
A separate clean Python 3.12.13 virtualenv installed 87 locked integration
packages, the existing dependency-free RAG Preflight wheel, and the staged
application wheel. `pip check` passed; isolated Python (`-I`) ran the same 15
tests against the installed application in 48.448 seconds. The installed CLI
passed `verify-papers` (171 chunks, zero API calls) and `dry-run` (171 planned
embeddings, 67,083 tokenizer-input tokens, $0.00134166 estimated embedding
cost, zero API calls). Package contents and final artifact checksums are recorded
with the private distributions. Version 0.1.0 remains private/unreleased.
FAISS is a separate application and is not part of this Chroma test result.

2026-09-19 update: after adding the independent expected-file list and tightening
Chroma payload-response checks, the local Python 3.12 source suite passed 17 tests.
Mypy passed on all nine application source files. The updated library wheel's
`check ../pdfs --expected corpus/expected-files.txt --json` passed against all
three PDFs and 67 pages. Live OpenAI calls remain unverified in this environment.

2026-09-20 update: the same 17 tests passed after the duplicated ingestion,
provider, journal and CLI workflow moved into the separate application-only
`rag-preflight-reference-common` package. The Chroma adapter remains here. No
paid OpenAI call was made in this validation run.

2026-09-21 update: the source suite passes 21 tests after adding the shared
adapter contract, Chroma root-variable migration and a simulated blocked-tokenizer
CLI check. The common package separately passes its two self-tests. A failed
tokenizer download now exits 2 with cache recovery instructions and no traceback.
The later bounded live run described above closes the API integration gap while
retaining the stated evidence limits.


A durable **simulated-provider** run was generated separately from unit tests in
`runs/offline-evidence/` and `state/offline-evidence/`. Its small reviewed summary
is `reviewed-results/offline-evidence.json`: first ingestion planned 171 vectors,
unchanged and metadata-only updates planned zero new vectors, naive page omission
removed 3 IDs in an isolated clone, and the guarded main collection remained
complete. The provider is explicitly `SimulatedProvider`; paid calls are zero and
real OpenAI embedding/generation checks remain unverified. A fresh process then
reopened the persistent local Chroma index and verified all 171 IDs and payloads
against the ledger and committed reference. This is local persistence evidence,
not provider or deployment evidence.

## Feedback follow-up

The source and clean installed-wheel application suites now execute 16 tests; all
16 passed in 46.210 and 45.094 seconds respectively. Mypy passed all nine source
files, and the clean integration environment has no broken requirements. The
additional test verifies the shipped curated offline evidence, per-row simulated
retrieval markings, omitted simulated distances, and the synthetic edit artifact.

A new simulated-provider run in ignored `state/offline-evidence-v2/` and
`runs/offline-evidence-v2/` produced the shipped schema-2 reviewed result. Curated
reports include first, unchanged, metadata-only, omission, simulated-answer and
synthetic-edit checks; full payload journals and Chroma state remain local. A
fresh process reopened and verified all 171 Chroma payloads. The plan-only text
edit changes two embedding inputs: 734 tokenizer-input tokens and $0.00001468
estimated at the supplied $0.02/M, with zero API calls. It updates metadata for
the edited source's chunks, so planned upserts exceed embeddings; vector reuse
remains explicit. The PDFs and vector store were not modified.

The application also retains an offline same-query guarded/omission-clone test
using a simulated provider. The bounded live comparison and measured OpenAI
request evidence are recorded separately in `live-openai-evidence.json`.

A later focused regression injects a failure on embedding batch two. The first
16 vectors and measured tokens remain in the journal, neither Chroma nor the ledger
is written, and recovery requests only the remaining 155 inputs before complete
read-back and commit. This is simulated-provider recovery evidence, not proof of
a particular OpenAI failure response.
