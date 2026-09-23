"""Exact FAISS adapter with atomic payload state and restart rebuilding."""
from dataclasses import asdict
import json
import math
import re
from typing import Any, Iterable
from rag_preflight_reference_common.store import (Payload, verify_payloads,
    reference_metadata as faiss_metadata)
from .config import Settings
from .journal import atomic_json


class FaissStore:
    """Single-writer exact L2 search over an atomically stored local payload set.

    Caller holds the application's writer lock. Every mutation persists the
    complete payload set and rebuilds the in-memory FAISS index. This is suitable
    for the small pinned corpus, not an unbounded or distributed vector database.
    """
    def __init__(self, settings: Settings, *, collection_name: str | None = None,
                 create: bool = True):
        import faiss
        import numpy as np
        self._faiss = faiss
        self._np = np
        self.settings = settings
        name = collection_name or settings.collection_name
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Invalid local FAISS collection name')
        self.path = settings.state_root / 'faiss' / f'{name}.json'
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if (data.get('schema_version') != 1 or data.get('collection') != name
                    or data.get('dimensions') != settings.embedding_dimensions
                    or not isinstance(data.get('records'), dict)):
                raise ValueError('Incompatible or corrupt local FAISS payload state')
            rows = {}
            for key, value in data['records'].items():
                if (not isinstance(key, str) or not isinstance(value, dict)
                        or value.get('chunk_id') != key or not isinstance(value.get('text'), str)
                        or not isinstance(value.get('metadata'), dict)):
                    raise ValueError('Invalid FAISS payload record')
                row = Payload(key, value['text'], value['metadata'], tuple(value['vector']))
                self._validate(row)
                rows[key] = row
            self._rows = rows
        elif create:
            self._rows = {}
            self._persist(self._rows)
        else:
            raise FileNotFoundError(f'Local FAISS collection does not exist: {name}')
        self._rebuild(self._rows)

    def _validate(self, row: Payload) -> None:
        if (not isinstance(row.chunk_id, str) or not row.chunk_id
                or not isinstance(row.text, str) or not isinstance(row.metadata, dict)
                or len(row.vector) != self.settings.embedding_dimensions
                or any(isinstance(x, bool) or not isinstance(x, (int, float))
                       or not math.isfinite(x) for x in row.vector)):
            raise ValueError('Invalid FAISS payload or vector dimensions')

    def _persist(self, rows: dict[str, Payload]) -> None:
        atomic_json(self.path, {'schema_version': 1, 'collection': self.path.stem,
            'dimensions': self.settings.embedding_dimensions,
            'records': {key: asdict(value) for key, value in sorted(rows.items())}})

    def _rebuild(self, rows: dict[str, Payload]) -> None:
        self._ordered = sorted(rows)
        self._index = self._faiss.IndexFlatL2(self.settings.embedding_dimensions)
        if self._ordered:
            vectors = self._np.asarray([rows[key].vector for key in self._ordered],
                                       dtype='float32')
            if not self._np.isfinite(vectors).all():
                raise ValueError('FAISS float32 conversion produced nonfinite values')
            self._index.add(vectors)
        if self._index.ntotal != len(rows):
            raise ValueError('FAISS index count differs from payload inventory')

    def ids(self) -> set[str]:
        if self._index.ntotal != len(self._rows):
            raise ValueError('FAISS index count differs from payload inventory')
        return set(self._rows)

    def get(self, chunk_ids: Iterable[str]) -> dict[str, Payload]:
        return {key: self._rows[key] for key in chunk_ids if key in self._rows}

    def upsert(self, payloads: list[Payload]) -> None:
        if len({row.chunk_id for row in payloads}) != len(payloads):
            raise ValueError('Duplicate ID in FAISS upsert batch')
        for row in payloads:
            self._validate(row)
        target = dict(self._rows)
        target.update((row.chunk_id, row) for row in payloads)
        self._rebuild(target)
        self._persist(target)
        self._rows = target

    def delete(self, chunk_ids: Iterable[str]) -> None:
        target = dict(self._rows)
        for key in chunk_ids:
            target.pop(key, None)
        self._rebuild(target)
        self._persist(target)
        self._rows = target

    def query(self, vector: tuple[float, ...], count: int = 5) -> list[dict[str, Any]]:
        if len(vector) != self.settings.embedding_dimensions or count < 1:
            raise ValueError('Invalid FAISS query dimensions or result count')
        if any(not math.isfinite(x) for x in vector):
            raise ValueError('Nonfinite FAISS query vector')
        if not self._ordered:
            return []
        query = self._np.asarray([vector], dtype='float32')
        if not self._np.isfinite(query).all():
            raise ValueError('FAISS query overflows float32')
        distances, positions = self._index.search(query, min(count, len(self._ordered)))
        return [dict(chunk_id=key, text=self._rows[key].text,
                     metadata=self._rows[key].metadata, distance=float(distance))
                for distance, position in zip(distances[0], positions[0])
                if position >= 0 for key in (self._ordered[int(position)],)]
