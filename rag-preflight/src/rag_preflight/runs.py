"""Framework-neutral receipts for independently enumerated, bounded source runs."""
from collections import Counter
from dataclasses import dataclass
from .evidence import EvidenceBuilder, EvidenceReport


@dataclass(frozen=True)
class RunReceipt:
    run_id: str
    enumerated_ids: tuple[str, ...]
    processed_ids: tuple[str, ...] = ()
    failed_ids: tuple[str, ...] = ()
    enumeration_completed: bool = False
    pagination_completed: bool = False
    scope: str = 'bounded'
    start_watermark: str | None = None
    end_watermark: str | None = None
    consistent_snapshot: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip() or self.scope not in ('bounded', 'complete', 'incremental'):
            raise ValueError('Supply run identity and bounded, complete, or incremental scope')
        for field in ('enumerated_ids', 'processed_ids', 'failed_ids'):
            values = getattr(self, field)
            if isinstance(values, (str, bytes)):
                raise ValueError('IDs must be an iterable, not a string')
            values = tuple(values)
            if any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError('IDs must be nonblank strings')
            object.__setattr__(self, field, values)
        for field in ('enumeration_completed', 'pagination_completed', 'consistent_snapshot'):
            if type(getattr(self, field)) is not bool:
                raise ValueError(f'{field} must be boolean')
        for field in ('start_watermark', 'end_watermark'):
            v = getattr(self, field)
            if v is not None and (not isinstance(v, str) or not v.strip()):
                raise ValueError('Watermarks must be nonblank strings or None')

    def audit(self, *, max_examples: int = 5) -> EvidenceReport:
        b = EvidenceBuilder(max_examples)
        expected, processed, failed = set(self.enumerated_ids), set(self.processed_ids), set(self.failed_ids)
        for field in ('enumerated_ids', 'processed_ids', 'failed_ids'):
            for key, n in sorted(Counter(getattr(self, field)).items()):
                if n > 1:
                    b.add('duplicate_run_id', {'field': field, 'id': key}, count=n-1)
        for key in sorted(processed | failed):
            if key not in expected:
                b.add('unexpected_run_record', key)
        for key in sorted(failed):
            b.add('run_processing_failed', key)
        for key in sorted(processed & failed):
            b.add('conflicting_run_outcome', key)
        for key in sorted(expected - processed - failed):
            b.add('run_processing_missing', key)
        if not self.enumeration_completed or not self.pagination_completed:
            b.add('run_enumeration_incomplete')
        changed = self.start_watermark is not None and self.end_watermark is not None and self.start_watermark != self.end_watermark
        if changed:
            b.add('source_changed_during_run')
        unverified = []
        if not self.consistent_snapshot:
            unverified.append('source_snapshot_consistency')
        if self.scope != 'complete' or not self.enumeration_completed or not self.pagination_completed or not self.consistent_snapshot or changed:
            unverified.append('whole_corpus_completeness')
        return b.report(dict(records_enumerated=len(expected), records_processed=len(processed),
                             records_failed=len(failed), records_missing=len(expected-processed-failed)), unverified)

    @property
    def deletion_eligible(self) -> bool:
        """Evidence eligibility only; deletion still requires a guarded update plan."""
        report = self.audit(max_examples=0)
        return report.passed and not report.checks_unverified
