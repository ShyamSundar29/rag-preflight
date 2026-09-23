# From `check` to guarded re-ingestion

`check` is a read-only source diagnostic. Its current file/page evidence is useful
before the first ingest, but it cannot prove that a prior vector write succeeded.
Keep an independent source list and a durable ingestion ledger for updates.

1. Maintain `expected-files.txt` **outside the source folder** from the source of truth, with one root-relative
   supported path per line. Do not generate it from the folder being checked.
   Run `rag-preflight check ./documents --expected expected-files.txt`. Exit 0
   means the supported current scope passed; 1 means audited findings; 2 means
   an input, reader, or incomplete-evidence problem. All nonzero results stop the
   update. Fix unsupported/excluded files before treating the folder as complete.
2. In the ingestion job, enumerate document and unit IDs before extraction.
   Preserve source versions, successful/failed unit receipts and stable chunk keys.
   The core [source-to-ledger example](../examples/source_to_ledger.py) shows the
   API sequence with a fake store; it does not perform real embeddings or writes.
3. Build a candidate snapshot and ask `SQLiteSnapshotStore.plan()` for the guarded
   update. Review deletion-policy counts and exceptions. Embed only `plan.embed_ids`;
   validate those returned vectors and their declared input/model/pipeline metadata.
4. Under an application-level writer lock, confirm the source versions and plan
   base still match. Journal the pending operation, upsert planned payloads, read
   them back, apply guarded deletions, verify the complete target ID inventory and
   payloads, then commit the ledger. If a write fails, recover from the journal;
   SQLite and external vector writes are not one transaction. The detailed
   [production contract](production.md) covers races and recovery.
5. Reconcile the committed ledger against a complete vector-store ID enumeration
   on a schedule. Matching IDs do not prove matching text, metadata or vectors;
   applications should read back those payloads too.

The sibling `rag-preflight-chroma-reference` application is the maintained,
store-specific implementation of steps 2–5 for the pinned three-paper PDF corpus.
Its `verify-papers`, `dry-run`, `ingest`, `verify-index`, `recover`, `ask`, and
`demonstrate-omission` commands exercise the sequence. It uses OpenAI only when
the local `OPENAI_API_KEY` is configured; the offline provider is explicitly a
simulation. The FAISS reference application follows the same contract, with
separate dependencies and local state. An application-only common package owns
their shared workflow; each application's adapter implements the five-operation
store interface. None of these packages is part of the core runtime dependency set.
