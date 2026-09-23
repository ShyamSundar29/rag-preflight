"""Explicit-vector Chroma adapter for the shared application protocol."""
from typing import Any, Iterable, cast
from rag_preflight_reference_common.store import (Payload, verify_payloads,
    reference_metadata as chroma_metadata)
from .config import Settings


class ChromaStore:
    def __init__(self, settings: Settings, *, collection_name: str | None = None,
                 create: bool = True):
        import chromadb
        settings.state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.settings = settings
        self.client = chromadb.PersistentClient(
            path=str(settings.state_root / 'chroma'),
            settings=chromadb.Settings(anonymized_telemetry=False))
        name = collection_name or settings.collection_name
        self.collection = (self.client.get_or_create_collection(name=name, embedding_function=None)
                           if create else self.client.get_collection(name=name, embedding_function=None))

    def ids(self) -> set[str]:
        result: set[str] = set()
        offset = 0
        while True:
            page = self.collection.get(limit=200, offset=offset, include=[])
            ids = page['ids']
            if not ids:
                break
            for chunk_id in ids:
                if chunk_id in result:
                    raise ValueError('Duplicate Chroma ID during enumeration')
                result.add(chunk_id)
            offset += len(ids)
        if len(result) != self.collection.count():
            raise ValueError('Chroma enumeration changed or returned incomplete scope')
        return result

    def get(self, chunk_ids: Iterable[str]) -> dict[str, Payload]:
        wanted = list(chunk_ids)
        if not wanted:
            return {}
        result: dict[str, Payload] = {}
        for position in range(0, len(wanted), 100):
            page = self.collection.get(ids=wanted[position:position + 100],
                                       include=['documents', 'metadatas', 'embeddings'])
            embeddings = page.get('embeddings')
            documents = page.get('documents')
            metadatas = page.get('metadatas')
            if embeddings is None or documents is None or metadatas is None:
                raise ValueError('Chroma did not return requested payload columns')
            if (len(page['ids']) != len(documents)
                    or len(page['ids']) != len(metadatas)
                    or len(page['ids']) != len(embeddings)):
                raise ValueError('Chroma read-back columns have inconsistent lengths')
            for chunk_id, text, metadata, vector in zip(
                    page['ids'], documents, metadatas, embeddings):
                if chunk_id in result:
                    raise ValueError('Duplicate Chroma ID in read-back')
                if text is None or metadata is None:
                    raise ValueError('Chroma payload missing text or metadata')
                result[chunk_id] = Payload(chunk_id, text, dict(metadata),
                                           tuple(float(value) for value in vector))
        return result

    def upsert(self, payloads: list[Payload]) -> None:
        for position in range(0, len(payloads), 50):
            batch = payloads[position:position + 50]
            if not batch:
                continue
            self.collection.upsert(ids=[p.chunk_id for p in batch],
                embeddings=cast(Any, [list(p.vector) for p in batch]),
                documents=[p.text for p in batch],
                metadatas=[p.metadata for p in batch])

    def delete(self, chunk_ids: Iterable[str]) -> None:
        ids = list(chunk_ids)
        for position in range(0, len(ids), 100):
            self.collection.delete(ids=ids[position:position + 100])

    def query(self, vector: tuple[float, ...], count: int = 5) -> list[dict[str, Any]]:
        page = self.collection.query(query_embeddings=cast(Any, [list(vector)]), n_results=count,
                                     include=['documents', 'metadatas', 'distances'])
        documents = page.get('documents')
        metadatas = page.get('metadatas')
        distances = page.get('distances')
        if documents is None or metadatas is None or distances is None:
            raise ValueError('Chroma did not return requested query columns')
        return [dict(chunk_id=i, text=t, metadata=m, distance=d)
                for i, t, m, d in zip(page['ids'][0], documents[0],
                                      metadatas[0], distances[0])]
