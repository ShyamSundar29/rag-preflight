"""Current-source folder check; never infers historical vector-store coverage."""
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import hashlib
import os

from .evidence import EvidenceBuilder, EvidenceReport
from .extract import (docx_receipt, pptx_receipt, pypdf_receipt,
                      text_file_receipt, ExtractionResult)
from .ingestion import AcceptancePolicy, ValidationReport, audit_ingestion


SUPPORTED_SUFFIXES = ('.pdf', '.txt', '.md', '.rst', '.html', '.htm', '.docx', '.pptx')


def _split_words(text: str, *, words_per_chunk: int = 400, overlap: int = 40) -> list[str]:
    """Deterministic default, within each unit. These are words, not model tokens."""
    words = text.split()
    if not words:
        return []
    result = []
    start = 0
    while start < len(words):
        result.append(' '.join(words[start:start + words_per_chunk]))
        if start + words_per_chunk >= len(words):
            break
        start += words_per_chunk - overlap
    return result


@dataclass(frozen=True)
class FolderCheckReport:
    """Compact public report; `audit.findings` remains available for debugging."""
    audit: ValidationReport
    source_evidence: EvidenceReport
    files_discovered: int
    files_audited: int
    units_enumerated: int
    unsupported_files: int
    image_only_units: int
    expected_files: int | None = None
    missing_expected_files: int = 0
    reader_unavailable_files: int = 0

    @property
    def outcome(self) -> str:
        """Separate unusable evidence from findings in an audited source scope."""
        groups = self.source_evidence.groups
        read_failures = next((g for g in groups if g['code'] == 'source_read_failed'), None)
        incomplete = any(g['code'] in ('source_enumeration_failed', 'source_path_excluded')
                         for g in groups) or read_failures is not None
        if incomplete:
            if (self.files_audited == 0 and self.files_discovered > 0
                    and self.reader_unavailable_files == self.files_discovered
                    and not any(g['code'] in ('source_enumeration_failed', 'source_path_excluded')
                                for g in groups)):
                return 'reader_unavailable'
            return 'incomplete'
        if self.files_discovered == 0 and self.expected_files is None:
            return 'no_supported_files'
        if not self.audit.passed or not self.source_evidence.passed:
            return 'audit_failed'
        return 'passed'

    @property
    def passed(self) -> bool:
        return self.outcome == 'passed'

    def by_code(self, *, max_examples: int = 5) -> list[dict[str, Any]]:
        if type(max_examples) is not int or max_examples < 0:
            raise ValueError('max_examples must be a nonnegative integer')
        counts: Counter[tuple[str, str]] = Counter()
        examples: dict[tuple[str, str], list[Any]] = {}
        for finding in self.audit.findings:
            key = (finding.code, finding.severity)
            counts[key] += 1
            sample = examples.setdefault(key, [])
            if len(sample) < max_examples:
                sample.append({'source': finding.document_id, 'message': finding.message})
        for group in self.source_evidence.groups:
            key = (group['code'], group['severity'])
            counts[key] += group['occurrences']
            sample = examples.setdefault(key, [])
            sample.extend(group['examples'][:max(0, max_examples - len(sample))])
        return [dict(code=code, severity=severity, occurrences=amount,
                     examples=examples.get((code, severity), []))
                for (code, severity), amount in sorted(counts.items())]

    def metrics(self) -> dict[str, Any]:
        groups = self.by_code(max_examples=0)
        return {'files_discovered': self.files_discovered,
                'files_audited': self.files_audited,
                'units_enumerated': self.units_enumerated,
                'chunks_audited': self.audit.measurements['chunks_audited'],
                'missing_units': self.audit.measurements['missing_units'],
                'likely_image_only_units': self.image_only_units,
                'unsupported_files': self.unsupported_files,
                'expected_files': self.expected_files,
                'missing_expected_files': self.missing_expected_files,
                'reader_unavailable_files': self.reader_unavailable_files,
                'outcome': self.outcome,
                'errors': sum(g['occurrences'] for g in groups if g['severity'] == 'error'),
                'warnings': sum(g['occurrences'] for g in groups if g['severity'] == 'warning'),
                'passed': self.passed,
                'checks_skipped': len(self.audit.checks_skipped),
                'checks_unverified': len(self.source_evidence.checks_unverified),
                'findings': [{k: v for k, v in group.items() if k != 'examples'} for group in groups]}

    def to_dict(self, *, detailed: bool = False, max_examples: int = 5) -> dict[str, Any]:
        result = {**self.metrics(), 'findings': self.by_code(max_examples=max_examples),
                  'checks_unverified': list(self.source_evidence.checks_unverified),
                  'scope': 'supported current source files only; no historical index proof'}
        if detailed:
            result['detailed_audit'] = self.audit.to_dict()
        return result

    def table(self, *, max_examples: int = 5) -> str:
        label = {'passed': 'PASS', 'audit_failed': 'FAIL', 'incomplete': 'INCOMPLETE',
                 'reader_unavailable': 'READER UNAVAILABLE',
                 'no_supported_files': 'NO SUPPORTED FILES'}[self.outcome]
        lines = [f"{label}: {self.files_audited}/{self.files_discovered} supported files audited, "
                 f"{self.units_enumerated} units, {self.audit.measurements['missing_units']} missing chunk units, "
                 f"{self.unsupported_files} unsupported files excluded",
                 'CODE  SEVERITY  OCCURRENCES']
        if self.outcome == 'no_supported_files':
            lines.insert(1, 'No supported files were found. Check the folder path and supported extensions.')
        elif self.outcome == 'reader_unavailable':
            lines.insert(1, 'Files were found, but their optional reader is unavailable; install the indicated extra.')
        for group in self.by_code(max_examples=max_examples):
            lines.append(f"{group['code']}  {group['severity']}  {group['occurrences']}")
            for sample in group['examples']:
                if isinstance(sample, dict):
                    source = sample.get('source', 'source')
                    unit = sample.get('unit')
                    if group['code'] == 'likely_image_only_page':
                        lines.append(f'  {unit} of {source} has images but no extractable text; OCR may be needed.')
                    elif group['code'] in ('missing_chunk_units', 'missing_chunk_pages'):
                        lines.append(f"  {source}: {sample['message']} Check extraction and chunking; page content may be unsearchable.")
                    elif group['code'] in ('unapproved_empty_units', 'unapproved_empty_pages'):
                        lines.append(f"  {source}: {sample['message']} No extractable text was returned; inspect the source and consider OCR.")
                    elif group['code'] == 'source_read_failed':
                        reason = sample.get('reason')
                        if reason == 'reader_unavailable':
                            extra = sample.get('install_extra', 'the required format')
                            lines.append(f'  {source}: optional reader is missing; install rag-preflight[{extra}].')
                        else:
                            explanation = {'invalid_utf8': 'not valid UTF-8 text',
                                           'empty_file': 'file is empty',
                                           'encrypted_pdf': 'PDF is encrypted and no password was supplied',
                                           'invalid_pdf': 'file is damaged or not a readable PDF',
                                           'permission_denied': 'permission denied while reading file',
                                           'source_changed': 'source changed while it was being read'}.get(
                                               str(reason), 'could not read source; inspect the file and reader logs')
                            lines.append(f'  {source}: {explanation}.')
                    elif group['code'] == 'missing_expected_source':
                        lines.append(f'  {source}: expected file is absent from the source folder.')
                    elif source is None:
                        lines.append(f'  {sample.get("message", sample)}')
                    else:
                        lines.append(f'  {source}: {sample.get("message", sample.get("error", sample))}')
                else:
                    lines.append(f'  {sample}')
        descriptions = {
            'expected_files_outside_current_folder': 'expected files absent from this folder',
            'historical_index_coverage': 'historical indexing',
            'within_unit_text_completeness': 'complete within-unit text capture',
            'complete_source_enumeration': 'complete source enumeration',
            'complete_source_processing': 'complete source processing',
            'expected_file_absence': 'expected-file absence after an incomplete walk',
            'image_inspection': 'PDF image inspection',
            'unsupported_file_types': 'unsupported file types',
        }
        if self.source_evidence.checks_unverified:
            lines.append('Unverified: ' + ', '.join(
                descriptions.get(check, check) for check in self.source_evidence.checks_unverified) + '.')
        return '\n'.join(lines)


def _expected_ids(path: str | Path) -> set[str]:
    """Read an independently maintained minimum inventory of root-relative files."""
    result: set[str] = set()
    for number, raw in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        if not raw.strip():
            continue
        value = raw.strip()
        if ('\\' in value or PurePosixPath(value).is_absolute()
                or any(part in ('', '.', '..') for part in value.split('/'))
                or PurePosixPath(value).suffix.lower() not in SUPPORTED_SUFFIXES):
            raise ValueError(f'Invalid root-relative supported path on expected-list line {number}')
        if value in result:
            raise ValueError(f'Duplicate expected path on line {number}: {value}')
        result.add(value)
    if not result:
        raise ValueError('Expected-file list is empty')
    return result


def _read_failure(path: Path, exc: Exception) -> dict[str, str]:
    name = type(exc).__name__
    reason = ('reader_unavailable' if isinstance(exc, (ImportError, ModuleNotFoundError)) else
              'invalid_utf8' if isinstance(exc, UnicodeError) else
              'empty_file' if name == 'EmptyFileError' else
              'encrypted_pdf' if path.suffix.lower() == '.pdf' and name in
                  ('FileNotDecryptedError', 'WrongPasswordError') else
              'invalid_pdf' if path.suffix.lower() == '.pdf' and name in ('PdfReadError', 'PdfStreamError') else
              'permission_denied' if isinstance(exc, PermissionError) else
              'source_changed' if isinstance(exc, ValueError) and str(exc) == 'Source changed during extraction' else
              'unknown_read_error')
    result = {'error': name, 'reason': reason}
    if reason == 'reader_unavailable':
        result['install_extra'] = 'pdf' if path.suffix.lower() == '.pdf' else 'office'
    return result


def check_source_folder(source_root: str | Path, *, max_examples: int = 5,
                        expected: str | Path | None = None) -> FolderCheckReport:
    """Enumerate the filesystem before extraction; check a fresh candidate only.

    Source IDs are root-relative POSIX paths, so duplicate basenames stay distinct.
    Symlinks are excluded. Working memory grows with the extracted corpus/chunks;
    use bounded batches for large directories. The source tree/page or slide list
    is current evidence, not a signed manifest or past indexing success. Without
    an external expected-file list, a document absent from the directory itself
    cannot be detected.
    """
    evidence = EvidenceBuilder(max_examples)
    expected_ids = _expected_ids(expected) if expected is not None else None
    root = Path(source_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('source_root must be a directory')
    docs, receipts, chunks = [], [], []
    discovered = unsupported = units = image_only = reader_unavailable = 0
    unverified = ['historical_index_coverage', 'within_unit_text_completeness']
    if expected_ids is None:
        unverified.append('expected_files_outside_current_folder')
    seen: set[str] = set()
    enumeration_complete = True
    def walk_error(exc: OSError) -> None:
        nonlocal enumeration_complete
        enumeration_complete = False
        evidence.add('source_enumeration_failed', type(exc).__name__)
        unverified.append('complete_source_enumeration')
    for folder, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        dirs.sort()
        for name in list(dirs):
            if Path(folder, name).is_symlink():
                dirs.remove(name)
                enumeration_complete = False
                evidence.add('source_path_excluded', Path(folder, name).relative_to(root).as_posix())
                unverified.append('complete_source_enumeration')
        for name in sorted(files):
            path = Path(folder, name)
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                unsupported += 1
                continue
            discovered += 1
            sid = path.relative_to(root).as_posix()
            seen.add(sid)
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    enumeration_complete = False
                    evidence.add('source_path_excluded', sid)
                    unverified.append('complete_source_enumeration')
                    continue
                suffix = path.suffix.lower()
                producer = (pypdf_receipt if suffix == '.pdf' else
                            docx_receipt if suffix == '.docx' else
                            pptx_receipt if suffix == '.pptx' else text_file_receipt)
                extracted: ExtractionResult = producer(path, document_id=sid)
                if hashlib.sha256(path.read_bytes()).hexdigest() != extracted.document.source_version:
                    raise ValueError('Source changed during extraction')
                docs.append(extracted.document)
                receipts.append(extracted.receipt)
                chunks.extend(extracted.chunks(_split_words, source=sid))
                units += len(extracted.document.expected_units or ())
                image_only += len(extracted.likely_image_only_units)
                for unit in extracted.likely_image_only_units:
                    evidence.add('likely_image_only_page', {'source': sid, 'unit': unit}, severity='warning')
                if extracted.image_inspection_failed_units:
                    unverified.append('image_inspection')
            except Exception as exc:
                failure = _read_failure(path, exc)
                reader_unavailable += failure['reason'] == 'reader_unavailable'
                evidence.add('source_read_failed', {'source': sid, **failure})
                unverified.append('complete_source_processing')
    missing_expected = 0
    if expected_ids is not None:
        if enumeration_complete:
            missing = expected_ids - seen
            missing_expected = len(missing)
            for sid in sorted(missing):
                evidence.add('missing_expected_source', {'source': sid})
        else:
            unverified.append('expected_file_absence')
    if unsupported:
        unverified.append('unsupported_file_types')
    # The folder command classifies zero readable sources itself; keep the
    # low-level ingestion API's required-inventory behavior unchanged.
    audit = audit_ingestion(docs, receipts, chunks,
                            policy=AcceptancePolicy(require_documents=bool(docs)))
    return FolderCheckReport(audit, evidence.report({}, unverified), discovered,
                             len(docs), units, unsupported, image_only,
                             len(expected_ids) if expected_ids is not None else None,
                             missing_expected, reader_unavailable)
