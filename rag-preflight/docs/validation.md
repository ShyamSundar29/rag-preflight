# Validation record — unreleased 0.1.0

## 2026-09-20 front-door and compatibility update

The updated source suite ran 191 unittest tests on local CPython 3.14.6 with
182 passing and 9 optional skips. The separate Python 3.12 application
environment ran the same 191 tests with 188 passing and 3 optional framework
skips. Mypy passed all 17 core source files with the configured Python 3.10
target and optional site packages excluded. A reviewer independently reported
191 passing tests on Python 3.10.12; this agent did not run that interpreter.

The `check` command now distinguishes empty supported scopes, unavailable
readers, incomplete reads, audited failures and successful supported scopes.
`--expected` uses an independent minimum file list. The JSON and text reports
agree on which checks remain unverified. Tests include bounded examples, missing
files, path rejection, reader absence, invalid UTF-8 and partial reads. Snapshot
readers name unknown schema versions before checking version-1 fields. Public
finding-code, deletion-default and stored-format commitments are in
[compatibility.md](compatibility.md).

The public-corpus trial was rerun with RFC 9110 PDF and pandas README downloaded
into a temporary cache: 2 documents, 210 units, 701 chunks, all 11 injected
scenarios true. Its natural short-license warning and within-unit truncation
limitations remain. Separate Chroma and FAISS applications passed 17 and 18
offline source tests respectively after extracting a shared application-only
pipeline; both use simulated vectors. Live OpenAI acceptance remains unverified
because no API key is configured and no generation model has been selected.

The paragraphs below preserve earlier revision results as a historical record.

Current local verification: CPython 3.14.6, macOS arm64, 2026-09-14.
No publication, deployment, or public repository creation was performed.

## Tests and static checks

Before editing, the repository unittest runner executed 120 tests: 114 passed,
6 optional tests skipped. Pytest was absent; this repository uses unittest.
The scale/evidence update suite executed 151 tests. With optional dependencies installed,
all 151 passed, with zero skips (18.891 seconds in this local run).
The dependency-free source run executed 151 tests: 144 passed and 7 optional checks
were skipped.
The additional tests cover 10,000 repetitive chunks, bounded output/exact counts,
full-corpus deletion policies, partial SQLite payload reads and stale plans,
text/strict baselines, multi-unit keys, existing-index source/export evidence,
actual-input cost estimates, metrics, namespaces, and bounded/incremental runs.

Mypy passes for all 16 source files using the configured Python 3.10 target and
a dependency-free import environment. A separate Python 3.14-target check passes
with optional libraries installed. NumPy 2.5.3 stubs contain Python 3.12 syntax,
so they cannot be parsed under the 3.10 target; the core check intentionally uses
the clean import environment. Runtime Python 3.10 was not available locally.
The user independently reports a full run on Python 3.10.12: 151 tests executed,
148 passed, 3 framework tests skipped because optional framework packages were
absent. This closes the reported runtime gap for that revision. It was not rerun
by this agent, and it does not certify the new commit-history changes on 3.10;
updated-revision and broader platform CI checks remain necessary.
The configured multi-platform CI matrix has not run for this unpublished project.

Optional integrations verified locally: NumPy 2.5.3, pypdf 6.18.1,
langchain-core 1.6.3, llama-index-core 0.14.24, LangGraph 1.2.11. Framework tests
exercise actual Document/TextNode interfaces and both graph branches. A third-party
LangSmith deprecation warning is emitted on Python 3.14; tests pass.
All six Python examples ran successfully. Chunk CLI examples correctly exited 1
for their intentional findings; ingestion, first plan, embeddings and existing-index
CLI workflows exited 0. Detailed and compact chunk output were exercised.

## Public-source trial

See [corpus-results.json](corpus-results.json) and `scripts/corpus_trial.py` for
source URLs, exact downloaded checksums, findings and local measurements. The
rerun used RFC 9110 PDF and pandas README: 2 documents, 210 units, 701 chunks.
All 11 injected scenarios passed. Baseline passed with one low-unit-yield warning
for a naturally short license section, illustrating a heuristic false positive.
Token-limit checks were explicitly skipped.

Coverage and median-yield checks still missed truncation within a represented unit;
uniform truncation also escaped the yield heuristic. These known limits were
reproduced, not removed from the trial. In this local run validation of 2,000
vectors of 1,536 dimensions took 1.077 seconds with Python lists and 0.040 seconds
with NumPy arrays, excluding construction. This is not a throughput guarantee.
The trial uses dummy vectors and does not measure retrieval quality or live-provider
provenance. Upstream sources can change; cache and hashes identify this run. Raw
source downloads are not redistributed.

## Remaining deployment validation

No live vector-store adapter/provider request, distributed writer coordination,
restart/recovery application trial, million-chunk load test or security certification
is claimed. ID reconciliation does not verify vector/text/metadata contents.
Ledger transactions do not make external vector writes atomic. Namespace consistency
is not access control. Passing tests alone does not establish production readiness.
Core audits/baselines/run receipts retain batch inventories in memory. Existing-index
and reconciliation inventories use proportional temporary disk; file-sized working
memory and touched-document payload memory can still be large. Per-plan deletion
limits do not enforce cumulative job budgets. Heuristic warnings have false positives.


## Distribution verification

Version 0.1.0 source and wheel distributions were built from a temporary source
copy using setuptools 84.0.0 / build 1.6.1, with build outputs outside the source
repository. The wheel was installed with --no-deps into a clean virtual environment.
`pip check` passed; metadata has no unconditional third-party runtime requirements.
The isolated installed-wheel run executed 151 tests: 144 passed, 7 optional checks
skipped. Package import path was verified to point into that environment, with no
source-tree/PYTHONPATH fallback. The installed console entry point produced the
compact summary and expected rejection status on the intentional failure example.
Source and wheel distributions remain unreleased and were not uploaded anywhere.


## Final review update verification

After the preceding 151-test revision, the final review update adds compact Python
JSON defaults, source-enforced taxonomy coverage, SQLite schema-2 commit history,
rolling deletion measurements and explicit evidence documentation. Its suite executes
162 tests: all 162 passed with optional integrations installed; the dependency-free
source run passed 155 and skipped 7 optional tests. Both mypy environments passed
for all 16 source files. All seven Python examples and CLI workflows passed their
expected statuses; the corpus trial again passed all 11 injected scenarios.

The exact 2,000-document / 40,000-chunk incident was rerun against the new history:
four allowed commits removed 16,000 chunks, and deletion_summary(last_commits=4)
reported start=40,000, end=24,000, removals=16,000, net_shrink_fraction=0.40.
This is visibility, not a new cumulative hard gate. Identity churn, scoped categories,
no-op/stale commits, failed history writes, failed schema migration, unknown legacy
classification and reopen persistence have regression coverage.

The user's independently reported Python 3.10.12 run applies to the preceding
151-test revision. The new 162-test revision was exercised on CPython 3.14.6 locally
and statically checked for Python 3.10; runtime 3.10 re-verification remains external.
No Chroma/FAISS application or real embedding-provider trial was added to core.
The separate integration-validation.md describes that follow-up's acceptance contract.


Final installed-wheel verification: 162 tests executed in an isolated dependency-free
environment, 155 passed and 7 optional checks skipped. Import path was verified to
be the installed package; pip check passed and metadata has no unconditional
third-party requirements. Compact default and explicit detailed output were verified.
All core files also parse using Python 3.10 grammar; this is not a runtime 3.10 test.
Final artifacts contain the same package files as the wheel exercised above.


## Independent verification of the 162-test build

The user reports that the updated 162-test revision passed on Python 3.10.12:
159 tests passed and 3 optional framework tests were skipped. They also independently
verified the dependency-free wheel, CLI, checksums and migration/history behavior.
This closes the reported Python 3.10 runtime gap for that build. It is attributed
external verification, not an agent-run check of subsequent changes.


## Operator review fixes

On CPython 3.14.6, the updated suite executes 169 tests: all 169 passed with
optional integrations installed; the dependency-free source run passed 162 and
skipped 7 optional tests. Both mypy environments passed for all 16 source files,
including the configured Python 3.10 static target. All seven Python examples and
CLI workflows passed their expected statuses. The cached public-corpus trial
passed all 11 injected scenarios; its existing limitations remain unchanged.

Regression tests cover the initial-population window adjustment, genuine zero
baselines, later retirement and repopulation, legacy history origins, and read-only
CLI inspection without creation or migration. The current 169-test build has not
been runtime-tested locally on Python 3.10; the independent result above applies
to the preceding 162-test build. Version 0.1.0 remains unreleased.

Installed-wheel verification also executed 169 tests: 162 passed, 7 optional
checks skipped. The isolated import resolves to site-packages, pip check passes,
and package metadata contains no unconditional runtime dependencies. Installed
console commands returned the expected 0.40 summary and two history entries.
The final distributions retain identical package code to this tested wheel.


## CLI discoverability follow-up

The user independently reports 169 tests on Python 3.10.12 for the preceding
build, with 3 optional framework tests skipped (166 passed). This is attributed
verification of that build, not a local runtime check of the four new CLI tests.

CLI discovery adds regression coverage for top-level help, each command's help,
unknown commands, explicit chunks and legacy file invocation compatibility.
Extensionless missing bare input names now require chunks INPUT or ./INPUT to
distinguish them from command names. Version 0.1.0 remains unreleased.

Local CPython 3.14.6 validation passed all 173 tests with optional integrations.
The isolated dependency-free installed wheel passed 166 tests and skipped 7
optional tests (173 total). Mypy passed all 16 source files at the configured
Python 3.10 target; all seven examples and CLI workflows passed expected statuses.
The installed top-level help lists all six commands. pip check passed. This CLI-only
follow-up did not rerun the corpus trial; the preceding trial's 11 scenarios passed.


## Missing-argument and export documentation follow-up

On local CPython 3.14.6, all 181 tests passed with optional integrations installed.
Mypy passed 16 source files with the configured Python 3.10 target. All seven Python
examples and CLI workflows passed expected statuses. The cached corpus trial
again passed all 11 injected scenarios, retaining its known limitations.

The user independently reports 173 passing tests on Python 3.10.12 for the
preceding shipped build. This is attributed evidence; the new 181-test build
has not been runtime-tested locally on Python 3.10.

The export recipes were reviewed against linked official store/driver documentation
and executed with simulated clients to check pagination, evidence preservation,
fetch omissions, PostgreSQL cursor behavior and atomic output on failure. No live
Chroma, Qdrant, PostgreSQL or Pinecone service was tested: configured services and
credentials are unavailable in this workspace. Application SDKs remain outside core.

Dependency-free source and isolated installed-wheel verification each executed
181 tests: 174 passed and 7 optional checks skipped. Both mypy environments passed
all 16 files. The installed console returned 2 for no arguments and 0 for explicit
help. Import resolves to site-packages; pip check passed and package metadata has
no unconditional runtime dependencies. Final package code is byte-identical to
the tested installed wheel; build output stays outside the source repository.

## Current-source folder follow-up

The folder-only entry point and format helpers increased the suite to 186 tests.
On Python 3.12.13, 183 passed and the three optional framework tests were skipped
in 19.832 seconds. Focused tests exercised duplicate basenames in different
directories, static HTML script exclusion, UTF-8 read failure, symlink exclusion,
real python-docx body/table extraction, real python-pptx slide/blank-slide
behavior, and a generated PDF page containing an image object but no extractable
text. The finding-taxonomy test covers `likely_image_only_page`.

Mypy 2.3.1 passed all 17 core source files using the Python 3.10 target in a clean
environment without NumPy. The cached RFC 9110/pandas corpus trial again passed
all 11 injected scenarios; its within-unit/uniform truncation limits remain.

The dependency-free wheel was clean-installed with no unconditional runtime
packages. Import and `check_source_folder` were verified from site-packages. Its
installed suite executed the same 186 tests: 177 passed and 9 optional tests were
skipped because PDF, Office and framework extras were intentionally absent.
Running `rag-preflight check` on PDFs without `[pdf]` returned status 1 and named
each read failure rather than silently omitting it. A separate optional-dependency
run successfully checked the three research PDFs: 3 files, 67 page units, zero
missing units, with absent expected files, historical index coverage and
within-unit completeness marked unverified. This revision has not been rerun on
Python 3.10 at runtime.
