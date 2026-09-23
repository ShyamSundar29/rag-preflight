# Audit an existing index without adopting the ledger

Export records from your current pipeline/store as UTF-8 JSONL (one object per line):

```json
{"id":"vector-42","source_id":"papers/topic/paper.pdf","units":["page:1","page:2"],"text":"indexed text","source_fingerprint":{"algorithm":"sha256","basis":"file_bytes","value":"<64 lowercase hex characters>"}}
```

`id` is required. An optional nonblank `source_version` is a producer declaration;
contradictory labels for one source are reported, but labels are never compared
with source bytes as content-hash proof. The other fields are optional evidence, with missing checks
reported explicitly as unverified. `source_id` must be a canonical, root-relative
POSIX path with no absolute prefix, backslash, `.` or `..` segments. Matching is
exact and case-sensitive; duplicate basenames in different directories are distinct.
Export your native source identifiers through this explicit mapping. There is no
basename guessing. Unknown extra export fields are retained for duplicate/conflict
comparison but do not prove provenance.

## Export evidence ladder

These rows build on the preceding evidence. Flags attest the same supported source
scope and a consistent scan; they are not inferred from populated fields.

| Evidence available | Checks unlocked | Additional prerequisite / remaining unknown |
|---|---|---|
| `id` | Valid records; duplicate/conflicting IDs | Source coverage, versions, units and text remain unverified. |
| Add `source_id` | Exact root-relative mapping; source absence and orphan checks | Absence requires complete export and successful source enumeration; orphans require complete declared source scope. Unidentified/malformed/conflicting records prevent respective definitive claims. |
| Add `units` | Missing unit representation | Complete export, accurate units on every record and `unit_metadata_complete=True`; unit labels never prove full-page searchability. |
| Add comparable `source_fingerprint` | SHA-256 file-bytes version comparisons; conflicting fingerprints | Comparison needs a successfully read matching source. Timestamps/opaque labels are not byte-hash proof; partial exports can still show positive mismatches. |

Optional `text` independently enables empty-indexed-text checks. Missing text stays
unverified even at the final rung. Newly extracted sources never establish historical
indexing success.

Source discovery recursively supports `.pdf` and UTF-8 `.txt`, `.md`, `.rst` files
(case-insensitive suffixes). Text files have one unit, `file`; PDF units are
one-based `page:N` (integer aliases supported). Markdown headings are not inferred
as units in this workflow. Unsupported files are outside the declared scope. Records
with unsupported suffixes report scope unverified rather than definitive orphans.
Symlinks are excluded and reported; no external paths are followed implicitly.
Unreadable files, directories, malformed JSON, repeated JSON keys and record
conflicts are reported. Such failures prevent definitive absence/orphan claims.
PDF discovery requires the optional `rag-preflight[pdf]` extra. Without it PDF
read evidence fails explicitly while independent text-file checks continue.

```sh
rag-preflight existing-index ./sources ./index-export.jsonl --json \
  --export-complete --source-scope-complete --unit-metadata-complete \
  --max-examples 5
```

```python
from rag_preflight import audit_existing_index
report = audit_existing_index(
    './sources', './index-export.jsonl',
    export_complete=True, source_scope_complete=True,
    unit_metadata_complete=True, max_examples=5,
)
print(report.table())
print(report.metrics())
```

Do not use completeness flags for a sampled export, incremental source feed,
filtered directory subset, or inconsistent scans. Both enumerations must refer to
the same supported source scope and generation. Source absence needs a complete
export and successful source enumeration/read evidence; unknown source identifiers
in records prevent that proof. Orphan claims need a complete declared source scope.
Unit absence additionally needs an explicit assertion that exported unit metadata
is complete, and unit evidence on every record. Positive hash mismatches and empty
exported text can be checked on partial evidence. Duplicate records count extra
occurrences; contradictory records sharing an ID fail. Distinct comparable hashes
for one source also fail. Reports count missing sources, orphan sources and missing
units exactly, with bounded examples per code/severity.

Only SHA-256 **file bytes** fingerprints in the shown object schema are compared
with source hashes. Arbitrary timestamps, ETags, parser versions, text hashes and
opaque version labels are not content-hash proof. Source files must be stable during
the scan; this workflow cannot freeze your files or vector database. Each source
is read as one byte copy; PDF extraction attempts come from that same copy.
New source extraction establishes present evidence, never historical indexing
success. Represented unit IDs establish representation only, not that every page
paragraph is searchable or that vector contents match. Exported text absence
remains unverified, and empty exported text is an error. Blank PDF pages may need
operator review: this workflow has no empty-page exemption inference.

Reports distinguish pass/fail findings from unverified checks: `passed=True` means
no detected errors, **not** verified full ingestion. Always inspect
`checks_unverified`. Inventory uses temporary SQLite, with disk proportional to
sources/records/units; Python retains bounded examples with file/record-sized working memory.
A very large file/PDF still requires memory for that file. Exact duplicate comparison
stores full export payloads on disk. No deletions, repairs or vector-store SDK calls
are performed. CLI exits 0 for no detected errors (possibly unverified), 1 for
findings, 2 for invalid invocation/root input.

Store-specific [read-only export recipes](export-recipes.md) cover Chroma, Qdrant,
pgvector/PostgreSQL and Pinecone without adding dependencies to the library.
