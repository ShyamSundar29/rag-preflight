"""Explicit warning baselines for chunk audits; safety errors cannot be accepted."""
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any
from .core import AuditReport, Issue


def _fingerprint(issue: Issue, chunks: Sequence[Mapping[str, Any]], mode: str = 'strict') -> str:
    def identity(index: int) -> Any:
        # Exact record content makes changes new findings; array position is excluded.
        record = chunks[index]
        if mode == 'strict':
            return record
        md = record.get('metadata', {})
        identity = {k: md[k] for k in ('source', 'document_id', 'chunk_key', 'units', 'pages') if k in md}
        return {'text': record.get('text'), 'chunk_key': record.get('chunk_key'), 'metadata': identity}
    value = [issue.code, issue.severity, identity(issue.chunk_index),
             [identity(i) for i in issue.related_indices], issue.suggestion]
    if mode == 'text' and issue.code != 'duplicate_text':
        value.append(issue.message)
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(',', ':')).encode()).hexdigest()


def _check(report: AuditReport, chunks: Sequence[Mapping[str, Any]]) -> None:
    if not isinstance(report, AuditReport):
        raise TypeError('Baselines apply only to audit_chunks reports, never ingestion or plan safety checks')
    if len(chunks) != report.total_chunks:
        raise ValueError('Supply the exact records used to produce this report')
    for issue in report.issues:
        if any(type(i) is not int or not 0 <= i < len(chunks) for i in (issue.chunk_index, *issue.related_indices)):
            raise ValueError('Invalid issue location')


@dataclass(frozen=True)
class BaselineComparison:
    report: AuditReport
    accepted_warnings: int
    resolved_warnings: int

    def metrics(self) -> dict[str, Any]:
        return {**self.report.metrics(), 'baseline_accepted_warnings': self.accepted_warnings,
                'baseline_resolved_warnings': self.resolved_warnings, 'baseline_passed': self.passed}

    @property
    def passed(self) -> bool:
        """Gate on any new finding, including warnings; existing errors always fail."""
        return not self.report.issues


@dataclass(frozen=True)
class WarningBaseline:
    scope: str
    fingerprints: tuple[str, ...]
    fingerprint_mode: str = 'strict'

    def __post_init__(self) -> None:
        if self.fingerprint_mode not in ('strict', 'text'):
            raise ValueError('fingerprint_mode must be strict or text')
        if not isinstance(self.scope, str) or not self.scope.strip():
            raise ValueError('Baseline scope must name the corpus and audit policy version')
        if not isinstance(self.fingerprints, tuple) or any(not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v) for v in self.fingerprints):
            raise ValueError('Invalid baseline fingerprints')

    @classmethod
    def capture(cls, report: AuditReport, chunks: Sequence[Mapping[str, Any]], *, scope: str, fingerprint_mode: str = 'strict') -> 'WarningBaseline':
        _check(report, chunks)
        return cls(scope, tuple(sorted(_fingerprint(i, chunks, fingerprint_mode) for i in report.issues if i.severity == 'warning')), fingerprint_mode)

    def compare(self, report: AuditReport, chunks: Sequence[Mapping[str, Any]], *, scope: str, fingerprint_mode: str | None = None) -> BaselineComparison:
        _check(report, chunks)
        if fingerprint_mode is not None and fingerprint_mode != self.fingerprint_mode:
            raise ValueError('Baseline fingerprint mode mismatch')
        if scope != self.scope:
            raise ValueError('Baseline scope/policy mismatch')
        available = Counter(self.fingerprints)
        kept, accepted = [], 0
        for issue in report.issues:
            fingerprint = _fingerprint(issue, chunks, self.fingerprint_mode) if issue.severity == 'warning' else None
            if fingerprint is not None and available[fingerprint]:
                available[fingerprint] -= 1
                accepted += 1
            else:
                kept.append(issue)
        return BaselineComparison(replace(report, issues=tuple(kept)), accepted, sum(available.values()))

    def save(self, path: str | Path) -> None:
        from .reingestion import _atomic_json
        _atomic_json(path, {'schema_version': 2, 'fingerprint_mode': self.fingerprint_mode, 'scope': self.scope, 'fingerprints': list(self.fingerprints)})

    @classmethod
    def load(cls, path: str | Path) -> 'WarningBaseline':
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate JSON key')
                result[key] = value
            return result
        value = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique)
        if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value['schema_version'] not in (1, 2):
            raise ValueError('Unsupported baseline schema')
        expected = {'schema_version', 'scope', 'fingerprints'} | ({'fingerprint_mode'} if value['schema_version'] == 2 else set())
        if set(value) != expected or not isinstance(value['fingerprints'], list):
            raise ValueError('Unsupported baseline schema')
        return cls(value['scope'], tuple(value['fingerprints']), value.get('fingerprint_mode', 'strict'))
