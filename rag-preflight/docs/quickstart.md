# Quickstart (unreleased 0.1.0)

Install from the local wheel; there is no published release:

```sh
python -m pip install --force-reinstall --no-deps /path/to/rag_preflight-0.1.0-py3-none-any.whl
python examples/first_run.py
rag-preflight chunks.jsonl --min-chars 40 --json --max-examples 3
rag-preflight chunks.jsonl --min-chars 40 --details
rag-preflight check ./documents  # current-source folder check, no manifest/export
rag-preflight check ./documents --expected expected-files.txt
```

```python
from rag_preflight import audit_chunks, WarningBaseline
chunks = [{'chunk_key': 'intro', 'text': 'Short.',
           'metadata': {'source': 'manual.txt', 'document_id': 'manual'}}]
report = audit_chunks(chunks, min_chars=40)
print(report.table(max_examples=3))
print(report.metrics())
# Review warnings before accepting a baseline.
baseline = WarningBaseline.capture(report, chunks, scope='manual/min40-v1',
                                   fingerprint_mode='text')
print(baseline.compare(report, chunks, scope='manual/min40-v1').metrics())
```

Without an independent source inventory this audits chunk integrity, not source
completeness. Use `DocumentSpec`, extraction receipts and `build_snapshot` for
validated replacement batches; see `examples/source_to_ledger.py` and
`examples/safe_reingestion.py`. PDF extraction is optional (`[pdf]`); core has no
third-party runtime dependencies. Generic callable extraction and thin converter/key
helpers do not replace your parser or chunker. Within-unit truncation can remain
undetected; lexical and yield warnings have false positives.
`check` derives its current inventory from supported files under the requested
root, then extracts and chunks inside page/slide/file units. Supply an independently
maintained `expected-files.txt` with root-relative supported paths, one per line,
to detect absent files. It does not verify past ingestion or vector contents. PDF
support needs `[pdf]`; Word/PowerPoint
need `[office]`. Static HTML and UTF-8 text use only the standard library.
`report = check_source_folder(path)` provides compact `to_dict()`, identity-free
`metrics()`, and detailed `report.audit.findings` for debugging. Supported symlink
paths, read failures and incomplete walks are reported rather than omitted.
An empty supported scope, unavailable reader, or incomplete processing returns
exit 2; audited findings return 1; only a clean supported scope returns 0.
See [check to guarded ingestion](check-to-pipeline.md) for the next step.

CLI workflows:

```sh
rag-preflight ingestion examples/ingestion.json
rag-preflight embeddings examples/embeddings.json
rag-preflight plan - candidate.json
rag-preflight plan committed.json candidate.json --max-delete-fraction .25 \
  --max-corpus-delete-fraction .15
rag-preflight existing-index ./sources ./index-export.jsonl --json \
  --export-complete --source-scope-complete --unit-metadata-complete
```

The manifest workflow expects `documents`, `receipts`, `chunks`, and optionally
`policy`; snapshot output additionally needs `namespace`, `pipeline_id`, and
`embedding_model`. Embedding input expects `expected_chunk_ids`, `embeddings`, and
`dimensions`. Plan inputs are trusted saved snapshots. All workflows report/gate;
none writes a vector database. Existing-index checks may be unverified even with no
errors; see [export format and scope rules](existing-index.md). CLI examples using
candidate/committed snapshots require you to create those files first.

Read [API notes](api.md) for actual-input cost estimation, metadata-only reuse,
row-oriented receipts and structured measurements. Apply ordering, external write
failure recovery and access controls belong to your application; use the
[production integration contract](production.md).


Updated unpublished builds keep version 0.1.0; use --force-reinstall when an older
0.1.0 wheel is already installed. Python chunk JSON is now compact by default;
request `report.to_dict(detailed=True)` for individual findings. For SQLite rolling
deletion visibility run `ledger.deletion_summary(last_commits=4)` after commit;
see [history/window rules](api.md#cumulative-deletion-visibility-sqlite). History
makes cumulative shrinkage visible but does not block it automatically.


For an existing schema-2 ledger, inspect without mutation:

```sh
rag-preflight ledger summary ledger.db --json
rag-preflight ledger history ledger.db --limit 4 --json
```

The default young-ledger window reports post-population fractions and explicitly
marks any adjustment. Missing/legacy files return an error rather than creating or
upgrading data during inspection.

CLI discovery: `rag-preflight --help` lists every workflow;
`rag-preflight existing-index --help` shows export/scope options.
Use `rag-preflight chunks INPUT.jsonl` for explicit chunk auditing; the legacy
`rag-preflight INPUT.jsonl` form remains supported. Unknown bare command names
return status 2; extensionless files can be passed with `chunks INPUT` or `./INPUT`.

CLI invocation requires a command or chunk input file. No arguments return exit
status 2 with usage on stderr; explicit `--help` and `-h` return status 0.

Use the [store export recipes](export-recipes.md) to prepare existing-index JSONL
without adopting a ledger or adding store SDKs to the library.
