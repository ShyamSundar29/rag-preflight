"""Independent fixed-scope PDF inventory and page-boundary extraction."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from rag_preflight import (AcceptancePolicy, DocumentSpec, ExtractionReceipt, Snapshot,
                           audit_chunks, audit_ingestion, build_snapshot, pypdf_receipt)
from .config import Settings
from .tokenizer import encoding_for_model


@dataclass(frozen=True)
class Candidate:
    documents: tuple[DocumentSpec, ...]
    receipts: tuple[ExtractionReceipt, ...]
    chunks: tuple[dict[str, Any], ...]
    snapshot: Snapshot
    audit: dict[str, Any]
    chunk_audit: dict[str, Any]
    source_evidence: tuple[dict[str, Any], ...]


def load_manifest(settings: Settings) -> tuple[dict[str, Any], ...]:
    data = json.loads(settings.manifest.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or data.get('scope') != 'exactly_listed_pdfs':
        raise ValueError('Unsupported or incomplete corpus manifest')
    papers = data.get('papers')
    if not isinstance(papers, list) or not papers:
        raise ValueError('Manifest needs a nonempty independent PDF inventory')
    names: set[str] = set()
    for item in papers:
        if not isinstance(item, dict) or not isinstance(item.get('source_id'), str):
            raise ValueError('Invalid manifest paper')
        name = item['source_id']
        if name in names or '/' in name or '\\' in name or name in {'.', '..'} or not name.endswith('.pdf'):
            raise ValueError(f'Invalid or repeated manifest source_id: {name}')
        names.add(name)
        if not isinstance(item.get('sha256'), str) or len(item['sha256']) != 64:
            raise ValueError(f'Missing source byte hash: {name}')
        if type(item.get('pages')) is not int or item['pages'] < 1:
            raise ValueError(f'Missing independent page count: {name}')
    actual = {p.name for p in settings.source_root.iterdir() if p.suffix.lower() == '.pdf'}
    if actual != names:
        raise ValueError(f'PDF scope differs from manifest; missing={sorted(names-actual)}, extra={sorted(actual-names)}')
    return tuple(sorted(papers, key=lambda p: p['source_id']))


def split_page(text: str, settings: Settings) -> list[str]:
    """Bounded, page-local words; token count checks include normalized final input."""
    encoding = encoding_for_model(settings.embedding_model)
    words = text.split()
    if not words:
        return []
    output: list[str] = []
    position = 0
    while position < len(words):
        end = position
        count = 0
        while end < len(words):
            delta = len(encoding.encode((' ' if end > position else '') + words[end]))
            if end > position and count + delta > settings.chunk_token_limit - 20:
                break
            count += delta
            end += 1
        if end == position:
            end += 1
        part = ' '.join(words[position:end])
        while len(encoding.encode(part)) > settings.chunk_token_limit and end > position + 1:
            end -= 1
            part = ' '.join(words[position:end])
        if len(encoding.encode(part)) > settings.chunk_token_limit:
            raise ValueError('One word exceeds embedding chunk limit')
        if not part.strip():
            raise ValueError('Empty chunk after splitting')
        output.append(part)
        if end == len(words):
            break
        position = max(position + 1, end - settings.chunk_overlap_words)
    return output


def prepare(settings: Settings, *, fail_unit: tuple[str, str] | None = None,
            metadata_tag: str | None = None) -> Candidate:
    """Fails before planning/API calls on missing PDFs, failed pages or drift."""
    papers = load_manifest(settings)
    documents: list[DocumentSpec] = []
    receipts: list[ExtractionReceipt] = []
    chunks: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for item in papers:
        name = item['source_id']
        path = settings.source_root / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != settings.source_root.resolve():
            raise ValueError(f'Unsafe or missing source file: {name}')
        initial_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if initial_hash != item['sha256']:
            raise ValueError(f'Source fingerprint differs from pinned download: {name}')
        extraction = pypdf_receipt(path, document_id=name)
        if len(extraction.document.expected_units or ()) != item['pages']:
            raise ValueError(f'PDF page count differs from independent manifest: {name}')
        if extraction.document.source_version != initial_hash or hashlib.sha256(path.read_bytes()).hexdigest() != initial_hash:
            raise ValueError(f'Source changed during enumeration/extraction: {name}')
        document, receipt = extraction.document, extraction.receipt
        expected_units = document.expected_units
        if expected_units is None:
            raise ValueError(f'PDF unit inventory is unavailable: {name}')
        if receipt.processed_units is None:
            raise ValueError(f'PDF processing receipt is unavailable: {name}')
        if fail_unit is not None and fail_unit[0] == name:
            unit = fail_unit[1]
            if unit not in expected_units:
                raise ValueError(f'Fault unit outside source inventory: {unit}')
            receipt = ExtractionReceipt(name, document.source_version,
                processed_units=tuple(u for u in receipt.processed_units if u != unit),
                empty_units=tuple(u for u in receipt.empty_units if u != unit),
                failed_units=tuple(sorted(set(receipt.failed_units) | {unit})), completed=True)
        documents.append(document)
        receipts.append(receipt)
        for chunk in extraction.chunks(lambda page: split_page(page, settings), source=name):
            if fail_unit is not None and fail_unit == (name, chunk['metadata']['units'][0]):
                continue
            chunk['metadata']['namespace'] = settings.namespace
            if metadata_tag is not None:
                chunk['metadata']['review_tag'] = metadata_tag
            chunks.append(chunk)
        evidence.append({'source_id': name, 'sha256': initial_hash, 'pages': item['pages'],
                         'arxiv_page': item['arxiv_page'], 'title': item['title'],
                         'extraction_failed_units': list(extraction.receipt.failed_units),
                         'extraction_empty_units': list(extraction.receipt.empty_units)})
    policy = AcceptancePolicy(required_metadata=('source', 'document_id', 'source_version', 'units', 'namespace'),
                              require_documents=True, require_namespace=True)
    ingestion = audit_ingestion(documents, receipts, chunks, policy=policy, namespace=settings.namespace)
    quality = audit_chunks(chunks, required_metadata=('source', 'document_id', 'source_version'),
                           min_chars=80)
    if not ingestion.passed or not quality.passed:
        raise CandidateRejected(ingestion.to_dict(), quality.to_dict())
    snapshot = build_snapshot(documents, receipts, chunks, policy=policy,
        namespace=settings.namespace, pipeline_id=settings.pipeline_id,
        embedding_model=settings.embedding_model)
    return Candidate(tuple(documents), tuple(receipts), tuple(chunks), snapshot,
                     ingestion.to_dict(), quality.to_dict(), tuple(evidence))


class CandidateRejected(ValueError):
    def __init__(self, audit: dict[str, Any], chunk_audit: dict[str, Any]):
        self.audit = audit
        self.chunk_audit = chunk_audit
        super().__init__('Source/receipt/chunk candidate rejected before embedding or vector writes')
