"""Cheap, explicitly heuristic text-quality checks."""
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math
from statistics import median
from typing import Any
from .ingestion import Finding, ValidationReport, normalize_units


@dataclass(frozen=True)
class YieldPolicy:
    min_units: int = 5
    min_median_chars: int = 200
    min_ratio: float = 0.1

    def __post_init__(self) -> None:
        if type(self.min_units) is not int or self.min_units < 3:
            raise ValueError('min_units must be an integer >= 3')
        if type(self.min_median_chars) is not int or self.min_median_chars < 1:
            raise ValueError('min_median_chars must be a positive integer')
        if isinstance(self.min_ratio, bool) or not isinstance(self.min_ratio, (int, float)) or not math.isfinite(self.min_ratio) or not 0 < self.min_ratio < 1:
            raise ValueError('min_ratio must be in (0, 1)')


def audit_unit_yield(unit_texts: Mapping[str, Mapping[str, str]], *, policy: YieldPolicy | None = None) -> ValidationReport:
    """Compare stripped character yields to each document's median; warnings only.

    Pass raw extraction text when available. Uniform truncation, naturally short
    units and OCR quality need other evidence. No expected inventory is inferred.
    """
    policy = policy or YieldPolicy()
    findings, run, skipped = [], [], []
    for doc, units in sorted(unit_texts.items()):
        if not isinstance(doc, str) or not doc.strip() or not isinstance(units, Mapping):
            raise ValueError('Expected document IDs mapped to unit/text mappings')
        normalize_units(units.keys())
        if any(not isinstance(t, str) for t in units.values()):
            raise ValueError('Unit texts must be strings')
        counts = {u: len(t.strip()) for u, t in units.items()}
        center = median(counts.values()) if counts else 0
        check = f'unit_text_yield:{doc}'
        if len(counts) < policy.min_units or center < policy.min_median_chars:
            skipped.append(check)
            continue
        run.append(check)
        for unit, count in sorted(counts.items()):
            if count < center * policy.min_ratio:
                findings.append(Finding('low_unit_text_yield', 'warning',
                    f'Unit {unit!r} has {count} characters; document median is {center:g}.',
                    document_id=doc, suggestion='Compare with the source; short units can be legitimate.'))
    return ValidationReport(tuple(findings), tuple(run), tuple(skipped))


def audit_chunk_unit_yield(chunks: Iterable[Mapping[str, Any]], *, policy: YieldPolicy | None = None) -> ValidationReport:
    """Estimate yield from single-unit chunks. Skip documents with ambiguous attribution.

    Overlap can inflate counts. Prefer audit_unit_yield on raw extraction texts.
    """
    groups: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    ambiguous = set()
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            continue
        md = chunk.get('metadata')
        if not isinstance(md, Mapping) or not isinstance(md.get('document_id'), str):
            continue
        doc = md['document_id']
        try:
            units = normalize_units(md.get('units', md.get('pages', ())))
        except (ValueError, TypeError):
            ambiguous.add(doc)
            continue
        text = chunk.get('text')
        if len(units) != 1 or not isinstance(text, str):
            ambiguous.add(doc)
            continue
        groups[doc][units[0]].append(text)
    report = audit_unit_yield({doc: {u: ''.join(texts) for u, texts in units.items()}
                              for doc, units in groups.items() if doc not in ambiguous}, policy=policy)
    return ValidationReport(report.findings, report.checks_run,
        (*report.checks_skipped, *(f'unit_text_yield:{d}:ambiguous' for d in sorted(ambiguous))))
