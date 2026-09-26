# Failure taxonomy (0.1.0)

Every public finding code is listed below. Warnings are heuristics or explicit
unknowns; errors block ordinary validation. Caller warning budgets/baseline gates
can be stricter. Findings never apply repairs. EvidenceReport pass means no detected
errors and can coexist with unverified checks.

| Code | Severity | Actual trigger | Remediation | Known limitation |
|---|---|---|---|---|
| chunk_version_mismatch | error | Chunk source_version differs from manifest. | Rebuild consistent candidate from source. | Opaque version labels are trusted declarations. |
| completeness_unverified | warning | Document expected_units is None. | Supply independent unit inventory. | build_snapshot refuses this even if warnings accepted. |
| conflicting_index_record | error | Same exported ID has different payload. | Produce consistent export generation. | Export cannot prove definitive absences after conflicts. |
| conflicting_run_outcome | error | Same ID both processed and failed. | Resolve run outcome. | No retry policy inferred. |
| conflicting_source_versions | error | One source has multiple distinct comparable hashes or multiple distinct declared version labels. | Export coherent source generation or review deliberate versioned records. | One finding per source; retained historical versions may be intentional. |
| duplicate_chunk_key | error | Key repeats within same document. | Provide unique logical keys. | Separate documents may share keys. |
| duplicate_document | error | Same document ID appears repeatedly in manifest. | Deduplicate independent inventory. | Count is one finding per repeated ID, not extra occurrences. |
| duplicate_embedding | error | Expected chunk ID occurs more than once. | Supply one vector per expected ID. | Does not choose which vector to keep. |
| duplicate_index_record | error | Same exported ID and full payload repeats. | Export each indexed ID once. | Counts extra occurrences; distinct IDs with identical text are not record duplicates. |
| duplicate_receipt | error | More than one receipt for a document. | Supply one coherent receipt. | Cannot reconcile contradictory extractor claims automatically. |
| duplicate_run_id | error | Repeated enumerated/processed/failed primary key. | Fix pagination overlap/duplicate outcomes. | Counts extra occurrences in each stream; bounded in-memory run. |
| duplicate_text | warning | Whitespace-normalized case-sensitive text repeats an earlier chunk. | Review source provenance before removing. | Batch-local; duplicates can be legitimate; N duplicates create N-1 findings. |
| duplicate_vector | warning | Valid expected nonrepeated-ID vector has same canonical float64 bytes as earlier vector. | Review whether inputs should produce identical vectors. | Legitimate for identical inputs; detection can be disabled. |
| embedding_dimensions | error | Vector length differs from configured dimensions. | Use expected model/dimension output. | Model label is not verified. |
| embedding_norm_outlier | warning | Finite vector norm outside caller configured range. | Review provider normalization and policy. | No universal valid norm range; disabled without bounds. |
| embedding_provenance_mismatch | error | Declared model, pipeline, or input_hash differs from target. | Fingerprint at actual request boundary; use plan configuration. | Matching declarations cannot prove which model generated vector. |
| empty_indexed_text | error | Available exported string text is blank. | Inspect indexed payload/extraction. | Missing text is unverified, not empty; vector contents unchecked. |
| empty_inventory | error | No documents supplied while policy requires documents. | Supply independent inventory or explicitly allow a known empty batch. | Empty batch is not proof of a complete external corpus. |
| empty_page_has_chunks | error | Receipt-declared empty units also have nonempty chunk representation. | Correct extractor/chunker disagreement. | Unit labels are trusted. |
| empty_text | error | Text normalizes to blank. | Fix extraction or deliberately omit empty units with valid evidence. | Blank pages need explicit ingestion allowances. |
| empty_unit_has_chunks | error | Receipt-declared empty units also have nonempty chunk representation. | Correct extractor/chunker disagreement. | Unit labels are trusted. |
| extraction_incomplete | error | Receipt completed is false. | Finish extraction and record terminal completion. | completed remains producer attestation. |
| failed_pages | error | Receipt failed-unit set is nonempty. | Repair/retry failed source units. | One finding can describe multiple failed units. |
| failed_units | error | Receipt failed-unit set is nonempty. | Repair/retry failed source units. | One finding can describe multiple failed units. |
| index_export_read_failed | error | Export file read/UTF-8 decoding fails. | Fix export access/encoding and rerun. | Positive checks before failure may remain; absence unverified. |
| indexed_source_orphan | error | Mapped supported source path absent from complete successfully read source scope. | Review stale index/source scope. | No deletion performed; partial scope never authorizes claim. |
| insufficient_chunks | error | Nonempty chunk count below document min_chunks. | Repair extraction/chunking or review legitimate minimum. | Minimum alone is weak completeness evidence. |
| invalid_chunk_key | error | Chunk key is missing, blank, or not string. | Supply persistent key or use ordinal helper. | Positional helper keys can shift on insertion. |
| invalid_chunk_pages | error | Coverage missing/empty/invalid, duplicates canonical units, or both units and pages supplied. | Provide accurate unique units or legacy positive pages. | Absent coverage permitted only for unknown expected inventory; cannot prove paragraphs. |
| invalid_chunk_units | error | Coverage missing/empty/invalid, duplicates canonical units, or both units and pages supplied. | Provide accurate unique units or legacy positive pages. | Absent coverage permitted only for unknown expected inventory; cannot prove paragraphs. |
| invalid_embedding | error | Embedding record is not mapping. | Supply keyed vector records. | Validation is not an embedding call. |
| invalid_json_metadata | error | Metadata contains non-JSON-native or nonfinite values or nonstring keys. | Normalize metadata to finite JSON values. | No semantics/access policy verification. |
| invalid_metadata | error | metadata is not a mapping. | Supply JSON-native metadata. | Presence does not prove truthful provenance. |
| invalid_receipt_pages | error | Empty not subset of processed, failed outside expected, or failed intersects processed. | Correct receipt set semantics. | Does not inspect original source. |
| invalid_receipt_units | error | Empty not subset of processed, failed outside expected, or failed intersects processed. | Correct receipt set semantics. | Does not inspect original source. |
| invalid_record | error | Chunk is not a mapping. | Supply text/metadata record. | Does not infer source completeness. |
| invalid_text | error | Chunk text is not a string. | Extract or convert text first. | No OCR or parsing is performed by the audit. |
| invalid_vector | error | Vector is missing, noniterable, string/mapping, or not one-dimensional under NumPy. | Supply one-dimensional real numeric vector. | No provider SDK calls. |
| ledger_document_corrupt | error | Payload schema/hash/configuration/document identity/count fails verification. | Restore trusted document/ledger backup. | Recomputed malicious hashes/deleted rows may evade checks. |
| ledger_integrity | error | SQLite integrity_check returns non-ok result. | Stop apply and restore trusted backup. | Severe database damage may raise DatabaseError instead. |
| ledger_state | error | Stored namespace/model/pipeline blank or revision token invalid. | Restore trusted ledger state. | CAS token is not authenticated full-corpus history. |
| low_distinctiveness | warning | With enough batch chunks and at least three terms, every term occurs in configured fraction of batch term sets. | Review generic/navigation content. | Lexical heuristic; does not prove poor semantic retrieval. |
| low_unit_text_yield | warning | Enough units and sufficient document median, but unit stripped yield is below min_ratio * median. | Compare raw source and extraction. | Uniform truncation escapes detection; short units legitimate; overlap inflates chunk yield; multi-unit attribution skips. |
| likely_image_only_page | warning | The optional PDF reader finds image objects on a page whose extracted text is blank. | Inspect the page and consider OCR before indexing. | Images can be decorative; absence of extractable text is not proof that the page is scanned or that OCR will succeed. Image inspection can fail and remain unverified. |
| malformed_index_record | error | Invalid JSON/object/id/path/units/text/comparable hash, repeated JSON keys, or nonfinite serialized record. | Correct export and rerun. | Malformed lines make export evidence incomplete. |
| missing_chunk_pages | error | Expected nonempty units have no nonempty chunk representation after receipt-empty subtraction. | Repair dropped-unit chunking. | Represented unit does not prove complete page content; metrics count units. |
| missing_chunk_units | error | Expected nonempty units have no nonempty chunk representation after receipt-empty subtraction. | Repair dropped-unit chunking. | Represented unit does not prove complete page content; metrics count units. |
| missing_embedding | error | Expected ID has no embedding record. | Generate missing vectors. | An invalid present vector produces its own errors, not missing-record error. |
| missing_expected_source | error | A path independently listed with `check --expected` is absent after complete root enumeration. | Restore the file or correct the independently maintained list, then rerun. | The list is a minimum file inventory, not evidence of historical indexing or within-file completeness. An incomplete walk leaves absence unverified. |
| missing_indexed_unit | error | Expected source unit lacks nonempty-or-text-unavailable representation with complete export/unit evidence. | Review dropped page/unit representation. | Blank PDF units can be legitimate; no full-page-searchability proof. |
| missing_metadata | error | Configured required field is None, blank, or an empty container. | Populate required fields. | Unconfigured fields are not checked. |
| missing_receipt | error | Expected document lacks extraction receipt. | Capture extractor outcomes independently. | No receipt can be inferred from chunks. |
| namespace_mismatch | error | Recorded metadata namespace contradicts supplied namespace. | Use the intended collection namespace consistently. | Consistency only; not tenant isolation. |
| namespace_missing | error | Required-namespace policy lacks supplied namespace or recorded namespace field. | Supply namespace and record matching metadata. | Optional by default; not authorization. |
| nonfinite_embedding | error | Vector has boolean/non-real/nonfinite or unrepresentable values. | Validate actual producer output. | Finite values do not prove usefulness/model identity. |
| processed_pages_mismatch | error | Processed set differs from known expected set. | Attempt every expected unit and correct unexpected labels. | No expected set means this check is unverified. |
| processed_units_mismatch | error | Processed set differs from known expected set. | Attempt every expected unit and correct unexpected labels. | No expected set means this check is unverified. |
| receipt_version_mismatch | error | Receipt version differs from manifest. | Extract a consistent source revision. | Labels alone do not prove bytes. |
| repeated_boilerplate | warning | A first/last nonblank line of sufficient length occurs in max(minimum, ceil(ratio * valid texts)) records. | Inspect boundaries; remove confirmed boilerplate. | Requires multiline records; shared content can be meaningful. |
| run_enumeration_incomplete | error | Enumeration or pagination terminal completion is false. | Resume/restart source enumeration. | Unseen records cannot be deleted from incomplete run evidence. |
| run_processing_failed | error | Enumerated/downstream failed set contains ID. | Retry/repair and record outcome. | One finding per unique failed ID. |
| run_processing_missing | error | Enumerated ID has neither success nor failure outcome. | Complete downstream processing or record failure. | Only enumerated run coverage, not external whole corpus. |
| short_chunk | warning | Stripped character length is below configured min_chars. | Review truncation or combine context. | Naturally short content can be valid; disabled by default. |
| source_changed_during_run | error | Available start/end watermarks differ. | Use stable source snapshot or rerun consistently. | Matching markers alone are not a consistency proof. |
| source_enumeration_failed | error | Directory walk onerror receives filesystem failure. | Restore enumeration permissions/stability and rerun. | Definitive absence/orphan claims disabled. |
| source_extraction_failed | error | Inventoried PDF page extraction raises. | Repair PDF/parser or use independent extraction. | New extraction failure is not evidence of historical index failure. |
| source_hash_mismatch | error | Comparable SHA-256 file-bytes export hash differs from present source bytes. | Review changed source and index revision. | Does not treat arbitrary timestamps/version labels as hashes; per record. |
| source_not_indexed | error | Supported source has no mapped record in verified complete export. | Review missing ingestion. | Requires complete export, successful sources, no unidentified records; present evidence only. |
| source_path_excluded | error | Supported symlink file or symlink directory excluded; resolved path outside root excluded. | Provide explicit safe root-local source copies/scope. | No implicit external traversal; exclusions disable completeness claims. |
| source_read_failed | error | Supported source cannot be read/decoded/inventoried, including missing PDF/Office reader, invalid UTF-8, empty or corrupt file. | Fix file/encoding/permissions or install the matching optional extra. | Common causes are summarized in plain language; the exception type remains in detailed evidence. Failure disables completeness claims. |
| token_limit | error | Caller tokenizer count exceeds configured max_tokens. | Split exact inputs or change reviewed budget. | Requires explicit tokenizer; no guessing/prefix injection. |
| unapproved_empty_pages | error | Receipt empty units are not explicitly allowed. | Inspect source; approve legitimate blanks explicitly. | Approval is caller responsibility. |
| unapproved_empty_units | error | Receipt empty units are not explicitly allowed. | Inspect source; approve legitimate blanks explicitly. | Approval is caller responsibility. |
| unexpected_chunk_document | error | document_id is absent, invalid, or outside manifest. | Preserve source identity. | Does not discover source inventory. |
| unexpected_chunk_page | error | Chunk unit is outside independent expected inventory. | Correct unit metadata/source scope. | Does not verify actual text belongs to that unit. |
| unexpected_chunk_unit | error | Chunk unit is outside independent expected inventory. | Correct unit metadata/source scope. | Does not verify actual text belongs to that unit. |
| unexpected_embedding | error | chunk_id is missing, invalid, or not expected. | Align vectors with exact planned IDs. | ID correspondence does not prove vector content. |
| unexpected_receipt | error | Receipt names a document outside manifest. | Align manifest and receipt scope. | Scope is caller-declared. |
| unexpected_run_record | error | Processed or failed ID absent from independent enumeration. | Align downstream run identity with source enumeration. | Cannot reconstruct expected set from output. |
| zero_embedding | error | Nonempty vector is all zero. | Repair generation and inspect inputs. | Nonzero does not prove semantic quality. |

## Non-finding safety failures and unverified checks

Planning raises `UnsafePlanError` for cross-namespace comparisons, incomplete
pipeline/model migration scope, invalid retirement/allowance scope, per-document
limits (with document ID), absolute budgets, corpus fraction, and stale bases.
Invalid parameters/schema/evidence raise ValueError/TypeError; source-root invocation
errors fail the CLI rather than claiming an empty successful scan. Cost estimates
refuse missing/invalid counts/pricing; they do not generate safety findings.

Reconciliation reports measurements rather than finding codes: `missing_count`,
`orphan_count`, `duplicate_expected_count`, `duplicate_observed_count`. Missing/orphan
IDs come from set differences; duplicates count extra occurrences. `inventory_complete`
must attest both scans, otherwise report cannot pass. Remediation is read-back/scope
review; matching IDs do not verify vectors/text/metadata.

Existing-index unverified checks are source_absence, index_orphans,
unit_representation, source_mapping, source_version_comparison,
indexed_text_nonempty, records_outside_supported_source_scope,
historical_ingestion_success and full_unit_content_searchability. Missing scope,
failed scans or absent/incomparable evidence prevent the respective checks. The last
two are always unverified by this workflow. Run checks include
source_snapshot_consistency and whole_corpus_completeness; bounded/delta runs never
establish whole-corpus coverage. Supply independent evidence rather than hiding
unknowns. Core token/heuristic checks may be skipped when disabled or attribution
is insufficient; batch-relative warnings have natural-content false positives.

Neither baseline acceptance nor a passing suite proves production readiness. No
vector-content audit, retrieval evaluation, tenant authorization, external-write
atomicity or historical ingestion-success proof is implied.
