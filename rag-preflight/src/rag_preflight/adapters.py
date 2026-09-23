"""Dependency-free converters for public text/metadata interfaces, not loaders."""
from collections import defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
import json
from typing import Any
from .ingestion import normalize_units


def assign_chunk_keys(chunks: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Assign (document, unit, ordinal) keys to an ordered, complete document batch.

    Unit order is not source-significant: normalization sorts canonical units. Existing keys are rejected to avoid
    accidental identity changes. Ordinals are positional WITHIN a unit: inserting
    a chunk renames later chunks in that unit. Prefer source-native persistent IDs.
    """
    counts: dict[tuple[str, tuple[str, ...]], int] = defaultdict(int)
    result = []
    for chunk in chunks:
        item = deepcopy(dict(chunk))
        if 'chunk_key' in item:
            raise ValueError('Refusing to replace an existing chunk_key')
        md = item.get('metadata')
        if not isinstance(md, Mapping):
            raise ValueError('metadata is required')
        doc = md.get('document_id')
        if not isinstance(doc, str) or not doc.strip():
            raise ValueError('document_id is required')
        units = normalize_units(md.get('units', md.get('pages', ())))
        if not units:
            raise ValueError('Key assignment requires at least one source unit per chunk')
        pair = (doc, units)
        item['chunk_key'] = json.dumps([doc, units[0] if len(units) == 1 else list(units), counts[pair]], ensure_ascii=False, separators=(',', ':'))
        counts[pair] += 1
        result.append(item)
    return result


def _convert(items: Iterable[Any], text_attribute: str) -> list[dict[str, Any]]:
    result = []
    for item in items:
        text = getattr(item, text_attribute, None)
        md = getattr(item, 'metadata', None)
        if not isinstance(text, str) or not isinstance(md, Mapping):
            raise TypeError(f'Expected {text_attribute}: str and metadata: Mapping')
        record: dict[str, Any] = {'text': text, 'metadata': deepcopy(dict(md))}
        if 'chunk_key' in md:
            record['chunk_key'] = md['chunk_key']
        result.append(record)
    return result


def from_langchain_documents(documents: Iterable[Any]) -> list[dict[str, Any]]:
    """Copy page_content and metadata. Does not invent identity, units or receipts."""
    return _convert(documents, 'page_content')


def from_llama_index_nodes(nodes: Iterable[Any]) -> list[dict[str, Any]]:
    """Copy TextNode.text and metadata, without embedding-mode metadata injection."""
    return _convert(nodes, 'text')
