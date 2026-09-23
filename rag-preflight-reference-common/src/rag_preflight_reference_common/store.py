"""Application-only vector-store boundary and shared read-back checks."""
from dataclasses import dataclass
import json
import math
from typing import Any, Iterable, Protocol

from .config import Settings


@dataclass(frozen=True)
class Payload:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    vector: tuple[float, ...]


class VectorStore(Protocol):
    """Only the operations the reference ingestion/QA workflow actually uses."""
    def ids(self) -> set[str]: ...
    def get(self, chunk_ids: Iterable[str]) -> dict[str, Payload]: ...
    def upsert(self, payloads: list[Payload]) -> None: ...
    def delete(self, chunk_ids: Iterable[str]) -> None: ...
    def query(self, vector: tuple[float, ...], count: int = 5) -> list[dict[str, Any]]: ...


def reference_metadata(metadata: dict[str, Any], settings: Settings) -> dict[str, Any]:
    return {'source_id': metadata['document_id'],
            'source_version': metadata['source_version'],
            'units_json': json.dumps(metadata['units'], separators=(',', ':')),
            'chunk_key': metadata.get('chunk_key', ''),
            'namespace': settings.namespace,
            'embedding_model': settings.embedding_model,
            'pipeline_id': settings.pipeline_id,
            **({'review_tag': metadata['review_tag']} if 'review_tag' in metadata else {})}


def verify_payloads(store: VectorStore, expected: dict[str, Payload],
                    *, complete_ids: set[str] | None = None,
                    vector_tolerance: float = 2e-5) -> dict[str, Any]:
    """Compare text, metadata, vectors and optionally complete IDs after writes."""
    actual = store.get(expected)
    errors: list[dict[str, str]] = []
    for key, planned in expected.items():
        stored = actual.get(key)
        if stored is None:
            errors.append({'code': 'missing_record', 'chunk_id': key})
            continue
        if stored.text != planned.text:
            errors.append({'code': 'text_mismatch', 'chunk_id': key})
        if stored.metadata != planned.metadata:
            errors.append({'code': 'metadata_mismatch', 'chunk_id': key})
        if len(stored.vector) != len(planned.vector) or any(
                not math.isfinite(a) or abs(a - b) > vector_tolerance
                for a, b in zip(stored.vector, planned.vector)):
            errors.append({'code': 'vector_mismatch', 'chunk_id': key})
    enumerated = store.ids() if complete_ids is not None else None
    if complete_ids is not None:
        assert enumerated is not None
        for key in sorted(complete_ids - enumerated):
            errors.append({'code': 'missing_id', 'chunk_id': key})
        for key in sorted(enumerated - complete_ids):
            errors.append({'code': 'orphan_id', 'chunk_id': key})
    return {'passed': not errors, 'payloads_checked': len(expected),
            'ids_checked': len(enumerated) if enumerated is not None else None,
            'errors': errors,
            'checks_unverified': [] if complete_ids is not None else ['complete_id_inventory']}
