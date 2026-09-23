"""Manifest-backed completeness and embedding validation.

Page numbers are one-based. Receipts come from the extractor; the library can
validate those claims, but cannot independently inspect an original document.
"""
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, replace, field
import json
import math
from numbers import Real
from typing import Any

from .core import audit_chunks


def _name(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonblank string')


def _pages(value: Iterable[int], field: str) -> tuple[int, ...]:
    value = tuple(value)
    if any(type(p) is not int or p < 1 for p in value) or len(set(value)) != len(value):
        raise ValueError(f'{field} must contain unique positive integer page numbers')
    return tuple(sorted(value))


def canonical_json(value: Any) -> str:
    """Canonical JSON for JSON-native data; rejects nonfinite numbers and nonstring keys."""
    def check(item: Any) -> None:
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child)
            return
        raise ValueError('Value must contain only finite, JSON-native data with string keys')
    check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def normalize_units(value: Iterable[str | int], field: str = 'units') -> tuple[str, ...]:
    """Positive integers become page:N. Strings are exact stable identifiers.

    1 and 'page:1' refer to the same unit; '1' is a distinct string identifier.
    """
    if isinstance(value, (str, bytes, Mapping)):
        raise ValueError(f'{field} must be a sequence of unit identifiers')
    result = []
    for unit in value:
        if type(unit) is int and unit > 0:
            result.append(f'page:{unit}')
        elif isinstance(unit, str) and unit.strip():
            result.append(unit)
        else:
            raise ValueError(f'{field} contains an invalid unit identifier')
    if len(set(result)) != len(result):
        raise ValueError(f'{field} contains duplicate canonical unit identifiers')
    return tuple(sorted(result))


@dataclass(frozen=True)
class DocumentSpec:
    document_id: str
    source_version: str
    expected_pages: tuple[int, ...] | None = None
    allowed_empty_pages: tuple[int, ...] = ()
    min_chunks: int = 1
    expected_units: tuple[str | int, ...] | None = None
    allowed_empty_units: tuple[str | int, ...] = ()

    def __post_init__(self) -> None:
        _name(self.document_id, 'document_id')
        _name(self.source_version, 'source_version')
        if self.expected_pages is not None:
            if self.expected_units is not None or self.allowed_empty_units:
                raise ValueError('Use either page aliases or unit fields, not both')
            pages = _pages(self.expected_pages, 'expected_pages')
            if not pages:
                raise ValueError('expected_pages must not be empty; omit coverage for an unverified audit')
            object.__setattr__(self, 'expected_pages', pages)
            object.__setattr__(self, 'expected_units', normalize_units(pages))
            object.__setattr__(self, 'allowed_empty_units', normalize_units(_pages(self.allowed_empty_pages, 'allowed_empty_pages')))
        else:
            if self.allowed_empty_pages:
                raise ValueError('allowed_empty_pages requires expected_pages')
            if self.expected_units is not None:
                object.__setattr__(self, 'expected_units', normalize_units(self.expected_units))
            object.__setattr__(self, 'allowed_empty_units', normalize_units(self.allowed_empty_units))
        if self.expected_units is None and self.allowed_empty_units:
            raise ValueError('Empty-unit allowances require an expected unit inventory')
        if self.expected_units is not None and not set(self.allowed_empty_units) <= set(self.expected_units):
            raise ValueError('Allowed empty units must be expected units')
        if type(self.min_chunks) is not int or self.min_chunks < 0:
            raise ValueError('min_chunks must be a nonnegative integer')


    def to_dict(self) -> dict[str, Any]:
        """Canonical unit-form manifest, including when constructed with page aliases."""
        return {'document_id': self.document_id, 'source_version': self.source_version,
                'expected_units': None if self.expected_units is None else list(self.expected_units),
                'allowed_empty_units': list(self.allowed_empty_units), 'min_chunks': self.min_chunks}


@dataclass(frozen=True)
class ExtractionReceipt:
    document_id: str
    source_version: str
    processed_pages: tuple[int, ...] | None = None
    empty_pages: tuple[int, ...] = ()
    failed_pages: tuple[int, ...] = ()
    completed: bool = False
    processed_units: tuple[str | int, ...] | None = None
    empty_units: tuple[str | int, ...] = ()
    failed_units: tuple[str | int, ...] = ()

    def __post_init__(self) -> None:
        _name(self.document_id, 'document_id')
        _name(self.source_version, 'source_version')
        if self.processed_pages is not None:
            if self.processed_units is not None or self.empty_units or self.failed_units:
                raise ValueError('Use either page aliases or unit fields, not both')
            for old, new in [('processed_pages', 'processed_units'), ('empty_pages', 'empty_units'), ('failed_pages', 'failed_units')]:
                pages = _pages(getattr(self, old), old)
                object.__setattr__(self, old, pages)
                object.__setattr__(self, new, normalize_units(pages))
        else:
            if self.empty_pages or self.failed_pages:
                raise ValueError('Page aliases require processed_pages')
            for field in ('processed_units', 'empty_units', 'failed_units'):
                value = getattr(self, field)
                object.__setattr__(self, field, normalize_units(() if value is None else value, field))
        if type(self.completed) is not bool:
            raise ValueError('completed must be a boolean')


    def to_dict(self) -> dict[str, Any]:
        return {'document_id': self.document_id, 'source_version': self.source_version,
                'processed_units': list(self.processed_units or ()), 'empty_units': list(self.empty_units),
                'failed_units': list(self.failed_units), 'completed': self.completed}


@dataclass(frozen=True)
class AcceptancePolicy:
    required_metadata: tuple[str, ...] = ('source',)
    max_warnings: int | None = None
    require_documents: bool = True
    require_namespace: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.required_metadata, str):
            raise ValueError('required_metadata must be a sequence of keys')
        keys = tuple(self.required_metadata)
        for key in keys:
            _name(key, 'metadata key')
        object.__setattr__(self, 'required_metadata', tuple(dict.fromkeys(keys)))
        if self.max_warnings is not None and (type(self.max_warnings) is not int or self.max_warnings < 0):
            raise ValueError('max_warnings must be a nonnegative integer or None')
        if type(self.require_namespace) is not bool:
            raise ValueError('require_namespace must be a boolean')
        if type(self.require_documents) is not bool:
            raise ValueError('require_documents must be a boolean')


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    document_id: str | None = None
    chunk_index: int | None = None
    chunk_key: str | None = None
    suggestion: str | None = None


@dataclass(frozen=True)
class ValidationReport:
    findings: tuple[Finding, ...]
    checks_run: tuple[str, ...]
    checks_skipped: tuple[str, ...] = ()
    max_warnings: int | None = None
    measurements: dict[str, int] = field(default_factory=dict)

    @property
    def errors(self) -> int:
        return sum(f.severity == 'error' for f in self.findings)

    @property
    def warnings(self) -> int:
        return sum(f.severity == 'warning' for f in self.findings)

    @property
    def passed(self) -> bool:
        return self.errors == 0 and (self.max_warnings is None or self.warnings <= self.max_warnings)

    def summary(self) -> str:
        return f"{'PASS' if self.passed else 'FAIL'}: {self.errors} errors, {self.warnings} warnings"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.update(passed=self.passed, errors=self.errors, warnings=self.warnings)
        return result

    def metrics(self) -> dict[str, Any]:
        counts = Counter((f.code, f.severity) for f in self.findings)
        return {**self.measurements, 'errors': self.errors, 'warnings': self.warnings,
                'passed': self.passed, 'checks_skipped': len(self.checks_skipped),
                'findings': [dict(code=k[0], severity=k[1], occurrences=n) for k, n in sorted(counts.items())]}

    def by_document(self) -> dict[str | None, tuple[Finding, ...]]:
        groups: dict[str | None, list[Finding]] = {}
        for finding in self.findings:
            groups.setdefault(finding.document_id, []).append(finding)
        return {key: tuple(value) for key, value in groups.items()}

    def raise_for_errors(self) -> None:
        if not self.passed:
            raise ValidationError(self)


class ValidationError(ValueError):
    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        super().__init__(report.summary())


def audit_ingestion(documents: Iterable[DocumentSpec], receipts: Iterable[ExtractionReceipt],
                    chunks: Iterable[Mapping[str, Any]], *, policy: AcceptancePolicy | None = None,
                    namespace: str | None = None, max_tokens: int | None = None, token_counter: Callable[[str], int] | None = None) -> ValidationReport:
    """Check expected source inventory, extraction receipts, and chunk coverage.

    Chunk metadata requires document_id, source_version and pages (a JSON list).
    Each chunk also requires a top-level chunk_key unique within its document.
    """
    policy = AcceptancePolicy() if policy is None else policy
    if not isinstance(policy, AcceptancePolicy):
        raise TypeError('policy must be AcceptancePolicy')
    docs, receipts, chunks = tuple(documents), tuple(receipts), tuple(chunks)
    if any(not isinstance(d, DocumentSpec) for d in docs):
        raise TypeError('documents must contain DocumentSpec objects')
    if any(not isinstance(r, ExtractionReceipt) for r in receipts):
        raise TypeError('receipts must contain ExtractionReceipt objects')
    findings = []
    def add(code, message, doc=None, index=None, severity='error'):
        findings.append(Finding(code, severity, message, doc, index))
    if not docs and policy.require_documents:
        add('empty_inventory', 'Expected document inventory is empty.')
    doc_map = {d.document_id: d for d in docs}
    for document_id, count in Counter(d.document_id for d in docs).items():
        if count > 1:
            add('duplicate_document', 'Document appears more than once in inventory.', document_id)
    receipt_map = {r.document_id: r for r in receipts}
    for document_id, count in Counter(r.document_id for r in receipts).items():
        if count > 1:
            add('duplicate_receipt', 'Multiple extraction receipts for one document.', document_id)
    for item_receipt in receipts:
        if item_receipt.document_id not in doc_map:
            add('unexpected_receipt', 'Receipt is outside the expected inventory.', item_receipt.document_id)
    base = audit_chunks(chunks, required_metadata=policy.required_metadata,
                        max_tokens=max_tokens, token_counter=token_counter)
    for issue in base.issues:
        record = chunks[issue.chunk_index]
        md = record.get('metadata') if isinstance(record, Mapping) else None
        doc_id = md.get('document_id') if isinstance(md, Mapping) else None
        findings.append(Finding(issue.code, issue.severity, issue.message,
                                doc_id if isinstance(doc_id, str) else None, issue.chunk_index))
    coverage: dict[str, set[str]] = {d.document_id: set() for d in docs}
    counts: Counter[str] = Counter()
    chunk_keys = set()
    for index, record in enumerate(chunks):
        if not isinstance(record, Mapping):
            continue
        md = record.get('metadata')
        if not isinstance(md, Mapping):
            continue
        try:
            canonical_json(dict(md))
        except ValueError:
            add('invalid_json_metadata', 'Metadata must be finite JSON-native data.', index=index)
        if namespace is not None and 'namespace' in md and md['namespace'] != namespace:
            add('namespace_mismatch', 'Chunk namespace contradicts supplied namespace.', index=index)
        if policy.require_namespace and ('namespace' not in md or namespace is None):
            add('namespace_missing', 'Namespace policy requires supplied and recorded namespace.', index=index)
        doc_id = md.get('document_id')
        if not isinstance(doc_id, str) or doc_id not in doc_map:
            add('unexpected_chunk_document', 'Chunk has no known document_id.', index=index)
            continue
        doc = doc_map[doc_id]
        if md.get('source_version') != doc.source_version:
            add('chunk_version_mismatch', 'Chunk version does not match expected source version.', doc_id, index)
        key = record.get('chunk_key')
        if not isinstance(key, str) or not key.strip():
            add('invalid_chunk_key', 'Provide a nonblank stable chunk_key.', doc_id, index)
        elif (doc_id, key) in chunk_keys:
            add('duplicate_chunk_key', 'chunk_key must be unique within its document.', doc_id, index)
        else:
            chunk_keys.add((doc_id, key))
        legacy = doc.expected_pages is not None
        normalized: tuple[str, ...]
        units = md.get('units', md.get('pages'))
        try:
            if 'units' in md and 'pages' in md:
                raise ValueError('Ambiguous coverage fields')
            if units is None and doc.expected_units is None:
                normalized = ()
            else:
                if not isinstance(units, list) or not units:
                    raise ValueError('Coverage must be a nonempty JSON list')
                if 'units' not in md:
                    _pages(units, 'pages')
                normalized = normalize_units(units)
        except (ValueError, TypeError):
            add('invalid_chunk_pages' if legacy else 'invalid_chunk_units',
                'Provide units as a nonempty list of unique identifiers, or valid legacy pages.', doc_id, index)
            continue
        if doc.expected_units is not None and not set(normalized) <= set(normalize_units(doc.expected_units)):
            add('unexpected_chunk_page' if legacy else 'unexpected_chunk_unit', 'Chunk references units outside the source inventory.', doc_id, index)
        text = record.get('text')
        if isinstance(text, str) and text.strip():
            coverage[doc_id].update(normalized)
            counts[doc_id] += 1
    missing_unit_count = 0
    for doc in docs:
        doc_id = doc.document_id
        receipt = receipt_map.get(doc_id)
        legacy = doc.expected_pages is not None
        def code(page_code: str) -> str:
            return page_code if legacy else page_code.replace('pages', 'units').replace('page', 'unit')
        expected = None if doc.expected_units is None else set(normalize_units(doc.expected_units))
        empty: set[str] = set()
        if receipt is None:
            add('missing_receipt', 'Expected document has no extraction receipt.', doc_id)
        else:
            processed = set(normalize_units(receipt.processed_units or ()))
            empty = set(normalize_units(receipt.empty_units))
            failed = set(normalize_units(receipt.failed_units))
            if receipt.source_version != doc.source_version:
                add('receipt_version_mismatch', 'Receipt version does not match inventory.', doc_id)
            if not receipt.completed:
                add('extraction_incomplete', 'Extractor has not declared this document complete.', doc_id)
            if failed:
                add(code('failed_pages'), f'Extraction failed on units {sorted(failed)}.', doc_id)
            if expected is not None and processed != expected:
                add(code('processed_pages_mismatch'), f'Missing units {sorted(expected - processed)}; unexpected units {sorted(processed - expected)}.', doc_id)
            if not empty <= processed or (expected is not None and not failed <= expected) or failed & processed:
                add(code('invalid_receipt_pages'), 'Receipt page sets are inconsistent.', doc_id)
            if not empty <= set(normalize_units(doc.allowed_empty_units)):
                add(code('unapproved_empty_pages'), f'Unexpected empty units {sorted(empty - set(normalize_units(doc.allowed_empty_units)))}.', doc_id)
            if empty & coverage[doc_id]:
                add(code('empty_page_has_chunks'), 'Pages declared empty also have nonempty chunks.', doc_id)
        if expected is None:
            add('completeness_unverified', 'No independent expected-unit inventory was supplied.', doc_id, severity='warning')
        else:
            missing = expected - empty - coverage[doc_id]
            missing_unit_count += len(missing)
            if missing:
                add(code('missing_chunk_pages'), f'No nonempty chunks cover units {sorted(missing)}.', doc_id)
        if counts[doc_id] < doc.min_chunks:
            add('insufficient_chunks', f'Expected at least {doc.min_chunks} nonempty chunks; got {counts[doc_id]}.', doc_id)
    from .quality import audit_chunk_unit_yield
    yields = audit_chunk_unit_yield(chunks)
    findings.extend(yields.findings)
    enriched = []
    for finding in findings:
        finding_record = chunks[finding.chunk_index] if finding.chunk_index is not None else None
        key = finding_record.get('chunk_key') if isinstance(finding_record, Mapping) else None
        enriched.append(replace(finding, chunk_key=key if isinstance(key, str) else None,
                                suggestion=finding.suggestion or 'Inspect the source manifest, extraction receipt and referenced record.'))
    skipped = (*base.checks_skipped, *(f'completeness:{d.document_id}' for d in docs if d.expected_units is None))
    return ValidationReport(tuple(enriched), (*base.checks_run, 'document_completeness', 'chunk_identity', 'json_metadata', *yields.checks_run),
                            (*skipped, *yields.checks_skipped), policy.max_warnings,
                            dict(documents_audited=len(doc_map), chunks_audited=len(chunks), missing_units=missing_unit_count))


def audit_embeddings(expected_chunk_ids: Iterable[str], embeddings: Iterable[Mapping], *,
                     dimensions: int, backend: str = 'python',
                     detect_duplicates: bool = True, norm_range: tuple[float, float] | None = None,
                     max_warnings: int | None = None) -> ValidationReport:
    """Validate keyed vectors. Duplicate vectors and configured norm outliers warn.

    The optional numpy backend processes one vector at a time, keeping extra
    memory bounded by vector dimension. Neither backend proves model provenance.
    """
    import hashlib
    import struct
    if type(dimensions) is not int or dimensions < 1:
        raise ValueError('dimensions must be a positive integer')
    if backend not in ('python', 'numpy'):
        raise ValueError('backend must be python or numpy')
    if type(detect_duplicates) is not bool:
        raise ValueError('detect_duplicates must be boolean')
    AcceptancePolicy(max_warnings=max_warnings)
    if norm_range is not None:
        if len(norm_range) != 2 or any(isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v) for v in norm_range) or not 0 <= norm_range[0] <= norm_range[1]:
            raise ValueError('norm_range must contain finite bounds 0 <= min <= max')
    np: Any = None
    if backend == 'numpy':
        try:
            import numpy as numpy_module
            np = numpy_module
        except ImportError as exc:
            raise ImportError('Install rag-preflight[numpy] for the numpy backend') from exc
    if isinstance(expected_chunk_ids, str):
        raise ValueError('expected_chunk_ids must be an iterable of IDs')
    expected = tuple(expected_chunk_ids)
    for expected_id in expected:
        _name(expected_id, 'chunk ID')
    if len(set(expected)) != len(expected):
        raise ValueError('expected_chunk_ids must be unique')
    expected_set = set(expected)
    found: set[str] = set()
    hashes: dict[bytes, str] = {}
    findings: list[Finding] = []
    def add(code: str, message: str, index: int | None = None, severity: str = 'error') -> None:
        findings.append(Finding(code, severity, message, chunk_index=index))
    records_checked = 0
    for index, record in enumerate(embeddings):
        records_checked += 1
        if not isinstance(record, Mapping):
            add('invalid_embedding', 'Embedding record must be a mapping.', index)
            continue
        key = record.get('chunk_id')
        known = isinstance(key, str) and key in expected_set
        repeated_id = known and key in found
        if not known:
            add('unexpected_embedding', 'Embedding has an unexpected chunk_id.', index)
        else:
            assert isinstance(key, str)
            if repeated_id:
                add('duplicate_embedding', 'More than one embedding for a chunk ID.', index)
            found.add(key)
        vector = record.get('vector')
        if vector is None or isinstance(vector, (str, bytes, Mapping)):
            add('invalid_vector', 'Vector must be an iterable of real numbers.', index)
            continue
        try:
            if np is not None:
                if isinstance(vector, np.ndarray):
                    array = np.asarray(vector)
                    has_bool = False
                else:
                    raw_values = tuple(vector)
                    has_bool = any(isinstance(v, bool) for v in raw_values)
                    array = np.asarray(raw_values)
                if array.ndim != 1:
                    add('invalid_vector', 'Vector must be one-dimensional.', index)
                    continue
                length = len(array)
                valid = array.dtype.kind in 'fiu' and not has_bool and bool(np.isfinite(array).all())
                if valid:
                    with np.errstate(over='ignore', invalid='ignore'):
                        array = np.array(array, dtype='<f8', copy=True)
                    valid = bool(np.isfinite(array).all())
                if valid:
                    array[array == 0] = 0.0  # canonicalize signed zero
                    zero = not bool(np.any(array))
                    peak = float(np.max(np.abs(array))) if length else 0.0
                    norm = peak * float(np.linalg.norm(array / peak)) if peak else 0.0
                    payload = array.tobytes() if detect_duplicates else b''
            else:
                values = tuple(vector)
                length = len(values)
                valid = all(not isinstance(v, bool) and isinstance(v, Real) and math.isfinite(v) for v in values)
                if valid:
                    floats = tuple(0.0 if v == 0 else float(v) for v in values)
                    zero = not any(floats)
                    norm = math.hypot(*floats)
                    payload = struct.pack(f'<{length}d', *floats) if detect_duplicates else b''
        except TypeError:
            add('invalid_vector', 'Vector must be an iterable of real numbers.', index)
            continue
        except (OverflowError, ValueError):
            add('nonfinite_embedding', 'Vector cannot be represented as finite real values.', index)
            continue
        if length != dimensions:
            add('embedding_dimensions', f'Expected {dimensions} dimensions; got {length}.', index)
        if not valid:
            add('nonfinite_embedding', 'Vector contains non-real or nonfinite values.', index)
            continue
        if length and zero:
            add('zero_embedding', 'Vector contains only zeros.', index)
        if norm_range is not None and not norm_range[0] <= norm <= norm_range[1]:
            add('embedding_norm_outlier', f'Norm {norm:g} is outside configured range.', index, 'warning')
        if detect_duplicates and known and not repeated_id and length == dimensions:
            assert isinstance(key, str)
            digest = hashlib.sha256(payload).digest()
            if digest in hashes:
                add('duplicate_vector', f'Vector matches chunk ID {hashes[digest]}; review whether inputs also match.', index, 'warning')
            else:
                hashes[digest] = key
    for key in sorted(expected_set - found):
        add('missing_embedding', f'No vector for chunk ID {key}.')
    checks = ['embedding_correspondence', 'embedding_dimensions', 'finite_values', 'nonzero_vectors']
    if detect_duplicates:
        checks.append('duplicate_vectors')
    if norm_range is not None:
        checks.append('embedding_norms')
    return ValidationReport(tuple(findings), tuple(checks), max_warnings=max_warnings,
                            measurements=dict(expected_embeddings=len(expected_set), embedding_records_checked=records_checked))
