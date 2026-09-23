# Local operator runbook

Before paid calls, review PDF hashes, supported-file scope, source/page evidence,
embedding token estimate and current OpenAI prices. Keep `OPENAI_API_KEY` only in
the process environment. Restrict local state and run evidence; journals include
full chunk text and vectors. Back up the state directory before fault injection.

For a normal run, execute `verify-papers`, `dry-run`, `ingest`, then `verify-index`.
Check `runs/<run-id>/summary.json` for planned versus completed embedding inputs,
actual tokens, proposed deletions and read-back. `status: committed` means the
local Chroma/ledger checks completed in that run; it is not vector-store
transactionality or retrieval-quality certification.

Before live acceptance, `preview-text-edit SOURCE_ID` is a read-only **synthetic**
two-chunk edit. It builds a hypothetical source version and exact-token plan;
neither PDF files nor Chroma are changed. Keep that scenario separate from a
real document edit and from billed OpenAI usage. Once a generation model is
chosen, use `compare-omission OMISSION_RUN_ID QUESTION --generation-model MODEL_ID`
after `demonstrate-omission`. It verifies both indexes, embeds one shared query,
and records both retrieval/answer views. Review whether the selected question
depends on the removed page; answer loss or abstention is never assumed.

`reviewed-results/offline-evidence.json` ships with curated, non-text run files
under `reviewed-results/offline-runs/`. The full `runs/` and Chroma `state/` remain
ignored local artifacts. Regenerate independently without overwriting existing
state, for example `python scripts/offline_evidence.py --state-root NEW_STATE \
--runs-root NEW_RUNS --output NEW_SUMMARY`. Simulated answers have per-row labels
and no distances. These files prove local workflow behavior only.

If `pending-operation.json` exists, ordinary ingestion and questions stop. Do not
remove the file to make the command run. Read its run ID and corresponding
`runs/<run-id>/` reports. Confirm the source files remain at the recorded hashes.
Run `recover`; it replays stored vectors where the ledger base is unchanged and
verifies the complete Chroma state before ledger commit. If the ledger changed
independently or payloads disagree, stop and restore/repair manually from a trusted
backup. Never blind-delete IDs to make reconciliation pass.

The controlled omission scenario clones the committed payloads into a separate
Chroma collection and deletes a selected page there. It verifies the guarded main
collection remained complete. The clone remains in `state/chroma/` for inspection;
clean up old clones only after preserving reviewed summaries. External vector
writers or multiple hosts are outside the local writer-lock contract.

For a clean rerun, use a new separate state directory or a backed-up copy. Do not
wipe the main test state while its evidence is still needed. The reviewed summary
should retain run IDs, dependency versions, source hashes, actual model responses,
failed stages and limits, without API keys or copyrighted full-text dumps.
