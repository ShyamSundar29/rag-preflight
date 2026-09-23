# Export an existing vector index to JSONL

These read-only recipes run in **your application's environment**, using clients you
already configure. No store SDK is imported or required by RAG Preflight. Credentials,
connection creation and SDK version pinning belong to your application. The recipes
were checked against official documentation; regression tests exercise their Python
logic with simulated clients, not live services. Validate them against your deployed
SDK and a small known collection before exporting a live corpus.

Choose exactly one collection/namespace/table containing the supported source scope.
Do not use similarity search as an inventory. Finish every page. Freeze writes or use
a consistent snapshot/immutable generation, and wait for the store's visibility
requirements. A completed pagination loop alone does not establish a consistent scan.
If files change independently, the source and index scans still need a shared generation.
Read operations may incur provider costs. Nothing here deletes or repairs an index.

## Shared mapping and atomic JSONL writer

Copy this block before one store block. Metadata field names below are a convention
for these recipes, **not** assumptions made by the library. Adapt them explicitly:
`source_id` must already be a canonical root-relative POSIX path, such as
`papers/topic.pdf`. Map native identifiers through an explicit lookup if needed; never
strip to a basename. Missing metadata stays missing so checks remain unverified.
`units_json` is a JSON string containing an array, usable with flat-metadata stores;
`units` is an array where supported. PDF labels are `page:1`, etc.; text-file units
are `file`. Convert zero-based pages only if you know your ingestion convention.

`source_sha256` must be the SHA-256 of original file bytes **recorded at ingestion**.
Do not compute a fresh hash and attach it to historical index records, or substitute
text hashes, timestamps, ETags or opaque versions. Omit it when unavailable.
`text` must be the stored indexed text, not newly extracted source text.

```python
import json
import os
from pathlib import Path
import tempfile


def record(vector_id, metadata, text=None):
    metadata = metadata or {}
    result = {"id": str(vector_id)}
    for key in ("source_id", "source_version"):
        if metadata.get(key) is not None:
            result[key] = metadata[key]
    if metadata.get("units") is not None:
        result["units"] = metadata["units"]
    elif metadata.get("units_json") is not None:
        result["units"] = json.loads(metadata["units_json"])
    if metadata.get("source_sha256") is not None:
        result["source_fingerprint"] = {
            "algorithm": "sha256", "basis": "file_bytes",
            "value": metadata["source_sha256"],
        }
    if text is not None:
        result["text"] = text
    return result


def write_export(records, destination):
    destination = Path(destination)
    fd, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".partial")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            for item in records:
                stream.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
```

The destination is replaced only after iteration succeeds. Failures propagate; do
not catch them and declare a truncated export complete. This protects the output
file, not the consistency of the remote scan. Working memory is bounded by a page
plus an individual record; unusually large metadata/text can still require memory.
The auditor, rather than these exporters, detects duplicate/conflicting records.

## Chroma

Use an existing `collection`; no query embedding is requested. Freeze writes for
offset pagination. Null documents are omitted; empty strings remain empty evidence.

```python
def chroma_records(collection):
    offset = 0
    while True:
        batch = collection.get(limit=500, offset=offset,
                               include=["documents", "metadatas"])
        ids = batch["ids"]
        if not ids:
            break
        metadata = batch.get("metadatas")
        documents = batch.get("documents")
        if metadata is not None and len(metadata) != len(ids):
            raise ValueError("Chroma metadata length mismatch")
        if documents is not None and len(documents) != len(ids):
            raise ValueError("Chroma document length mismatch")
        for position, vector_id in enumerate(ids):
            yield record(vector_id, metadata[position] if metadata is not None else None,
                         documents[position] if documents is not None else None)
        offset += len(ids)

# write_export(chroma_records(collection), "index-export.jsonl")
```

Reference: [Chroma get and pagination](https://docs.trychroma.com/docs/querying-collections/query-and-get).

## Qdrant

Use an existing `client` and `collection_name`. Payload `text` is application-defined.
Follow the returned offset even when a page is short; `None` means completion.
Freeze writes or export a consistent restored snapshot. Vectors are not needed.

```python
def qdrant_records(client, collection_name):
    offset = None
    while True:
        points, next_offset = client.scroll(
            collection_name=collection_name, limit=500, offset=offset,
            with_payload=True, with_vectors=False)
        for point in points:
            payload = point.payload or {}
            yield record(point.id, payload, payload.get("text"))
        if next_offset is None:
            break
        if next_offset == offset:
            raise ValueError("Qdrant pagination did not advance")
        offset = next_offset

# write_export(qdrant_records(client, "papers"), "index-export.jsonl")
```

Reference: [Qdrant scroll](https://api.qdrant.tech/api-reference/points/scroll-points).

## pgvector / PostgreSQL

pgvector stores vectors in an application-defined PostgreSQL table. This example
uses **psycopg 3**, a dedicated idle `connection`, and a table `rag_chunks` with
columns `id`, `metadata` (JSON/JSONB) and `indexed_text`. Adapt the static SQL to your
schema and declared scope; never interpolate untrusted table/column names. No
vector values or pgvector-specific functions are needed. The server cursor avoids
loading all rows; repeatable-read gives a transaction snapshot of this table.
It does not freeze the source directory.

```python
def pgvector_records(connection):
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        with connection.cursor(name="preflight_export") as cursor:
            cursor.itersize = 500
            cursor.execute("SELECT id, metadata, indexed_text FROM rag_chunks ORDER BY id")
            for vector_id, metadata, text in cursor:
                yield record(vector_id, metadata, text)

# write_export(pgvector_records(connection), "index-export.jsonl")
```

References: [PostgreSQL repeatable-read](https://www.postgresql.org/docs/current/transaction-iso.html),
[psycopg server-side cursors](https://www.psycopg.org/psycopg3/docs/advanced/cursors.html#server-side-cursors).

## Pinecone vector indexes

Use an existing vector `index` and explicit `namespace`. This recipe targets
serverless **vector indexes**, not the Documents API. ID listing is not supported
for pod-based indexes; use an independently complete application ID inventory or
another supported export mechanism there. Never replace enumeration with top-k search.
The SDK list iterator advances pages; fetch in batches of at most 500 IDs.
A listed-but-unfetchable record aborts the export instead of silently disappearing.
Freeze writes and satisfy visibility requirements before declaring completion.

```python
def pinecone_records(index, namespace):
    for page_ids in index.list(namespace=namespace):
        for start in range(0, len(page_ids), 500):
            ids = page_ids[start:start + 500]
            response = index.fetch(ids=ids, namespace=namespace)
            vectors = response.vectors
            for vector_id in ids:
                if vector_id not in vectors:
                    raise ValueError("Pinecone listed ID missing from fetch")
                metadata = vectors[vector_id].metadata or {}
                yield record(vector_id, metadata, metadata.get("text"))

# write_export(pinecone_records(index, "papers"), "index-export.jsonl")
```

References: [Pinecone ID listing](https://docs.pinecone.io/guides/manage-data/list-record-ids),
[Pinecone fetch](https://docs.pinecone.io/guides/manage-data/fetch-data).

## Run the audit

Start without completeness assertions:

```sh
rag-preflight existing-index ./sources ./index-export.jsonl --json
```

Inspect `checks_unverified` even when exit status is 0. Only add `--export-complete`
after a successful, consistent, full export of the declared index scope. Only add
`--source-scope-complete` when the directory is the entire corresponding supported
source scope, and `--unit-metadata-complete` when every record's unit metadata is
accurate and complete. Empty namespaces require independent evidence that they
were truly empty. Successful reads never prove vector contents or searchability.
See [the evidence ladder and export schema](existing-index.md).
