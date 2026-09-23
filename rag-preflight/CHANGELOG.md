# Changelog

## 0.1.0 (unreleased) — current-source adoption update

- Make the text footer list only checks actually left unverified; with
  `--expected`, expected-file absence is no longer described as unchecked.
- Declare public finding-code/default-policy compatibility and stored-format
  migration rules; newer snapshot versions now fail with their version number.
- Classify `check` setup/incomplete outcomes separately from audited failures;
  explain common read errors in plain language without hiding diagnostic types.
- Add independent minimum-file inventory to `check --expected` and Python API;
  show excluded files and provide a path to guarded integration.
- Added read-only `check_source_folder()` and `rag-preflight check DIR`, with
  current file/page/slide inventory, bounded plain-language examples and explicit
  unverified historical index coverage.
- Added static UTF-8 HTML/text readers and optional Word/PowerPoint receipt
  subsets; empty PDF pages with image objects get a heuristic warning.
- Kept core runtime dependencies empty and version 0.1.0 unreleased.

## 0.1.0 — Unreleased

- Exit 2 on missing CLI arguments while explicit help remains exit 0.
- Add paginated read-only export recipes and qualify deployment responsibility/evidence.

- List all workflows in top-level CLI help, add explicit chunks command, and diagnose
  unknown bare commands while retaining legacy JSON/JSONL file invocation.

### Operator review fixes

- Adjust young-ledger summary windows to exclude initial setup/population when
  needed for a nonzero comparison; expose actual window/baseline metadata.
- Preserve null ratios for genuine zero baselines and retain later retirement/re-population.
- Add read-only ledger summary/history JSON CLI and optional read_only store access.
- Reject missing files and legacy schemas during inspection without creating/migrating.
- Attribute independent Python 3.10.12 verification of the preceding 162-test build.

### Final review fixes

- Make Python AuditReport JSON compact by default; detailed=True retains all findings.
- Add transactional SQLite commit history and identity-free rolling deletion summaries,
  separating gross ID removals, net shrinkage and ordinary/scoped/retired removals.
- Migrate SQLite inventory schema 1 to 2 atomically; report prior history as unverified.
  Portable JSON schema 1 remains unchanged; history adds visibility, not a hard gate.
- Enforce finding taxonomy coverage with source extraction tests and legacy unit aliases.
- Add an existing-index evidence ladder and separate real-integration validation contract.
- Record user-reported independent Python 3.10.12 verification with attribution.

### Scale and evidence update

- Add exact code/severity aggregation, bounded samples, compact CLI JSON/text and metrics.
- Add full-corpus 15% deletion guards with 25% per-document defaults, optional absolute
  budgets, full-inventory SQL counts and recorded effective policies.
- Add schema-2 strict/text warning baselines; schema-1 files retain strict semantics.
- Support canonical multi-unit ordinal keys while preserving single-unit outputs.
- Add read-only source-directory / existing-index JSONL API and CLI audits.
- Add explicit token-evidence embedding cost estimates and bounded run receipts.
- Enforce supplied namespace consistency and optional required metadata policy.
- Add regression coverage, API/migration guides and a complete finding taxonomy.

### Earlier prepublication review fixes

- Add independent plan-local chunk/document
  deletion budgets (now optional, alongside corpus-relative protection); deterministic per-document-first errors shared by both APIs.
- Add whole-ledger ID enumeration, streamed chunk IDs and verification.
- Add source-driven PDF/generic receipt producers and unit-scoped ordinal keys.
- Add dependency-free LangChain/LlamaIndex text converters and a LangGraph gate example.
- Add chunk length statistics, configurable short/low-distinctiveness warnings,
  and conservative unit-yield warnings with explicit skipped checks and limitations.
- Add bounded-report, disk-backed ID reconciliation and warning-only baseline files.
- Recommend SQLite operational state and JSON interchange; document evidence,
  ID-only apply limits, source requirements and framework cleanup ownership.


All development remains part of the unpublished initial release.

- Added chunk validation, source-unit completeness, explicit blank/unknown coverage,
  and compatibility aliases for existing PDF page manifests.
- Fixed named retirement to preserve other documents' deletion guards.
- Added scoped shrink allowances without relaxing unrelated document limits.
- Fixed safe import of the command-line entry module.
- Added duplicate-vector/norm warnings, optional NumPy backend, and plan-linked
  checks of declared embedding model, pipeline and exact input fingerprint.
- Added document-indexed SQLite state, touched-scope planning, stale-commit checks
  and transactional ledger updates. Portable JSON snapshot schema 1 remains supported.
- Added typed package marker, checked annotations, author/keyword/classifier metadata,
  version-independent CI wheel selection, and separated downloadable build artifacts.
- Added regression tests and a reproducible trial using an RFC PDF and pandas README.

No package or public repository has been published. Project URLs will be populated
when actual repository/documentation destinations exist.
