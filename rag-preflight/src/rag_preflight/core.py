"""Auditing without modifying input or calling external services."""
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
import math
import re
from statistics import median
from typing import Any


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    chunk_index: int
    message: str
    suggestion: str
    related_indices: tuple[int, ...] = ()


@dataclass(frozen=True)
class AuditReport:
    total_chunks: int
    issues: tuple[Issue, ...]
    checks_run: tuple[str, ...]
    checks_skipped: tuple[str, ...]
    length_statistics: dict[str, float | int] = field(default_factory=dict)

    @property
    def errors(self) -> int:
        return sum(i.severity == "error" for i in self.issues)

    @property
    def warnings(self) -> int:
        return sum(i.severity == "warning" for i in self.issues)

    @property
    def passed(self) -> bool:
        """True when there are no errors; warnings may still exist."""
        return self.errors == 0

    def summary(self) -> str:
        return (f"{'PASS' if self.passed else 'FAIL'}: {self.total_chunks} chunks, "
                f"{self.errors} errors, {self.warnings} warnings")

    def by_code(self, *, max_examples: int = 5) -> list[dict[str, Any]]:
        """Exact counts with bounded output; detailed findings remain in memory."""
        if type(max_examples) is not int or max_examples < 0:
            raise ValueError('max_examples must be a nonnegative integer')
        groups: dict[tuple[str, str], list[Issue]] = defaultdict(list)
        for issue in self.issues:
            groups[(issue.code, issue.severity)].append(issue)
        result = []
        for (code, severity), issues in sorted(groups.items()):
            affected = {i for issue in issues for i in (issue.chunk_index, *issue.related_indices)}
            result.append(dict(code=code, severity=severity, occurrences=len(issues),
                               affected_chunks=len(affected), chunk_indices=sorted(affected)[:max_examples]))
        return result

    def table(self, *, max_examples: int = 5) -> str:
        lines = [self.summary(), 'CODE  SEVERITY  OCCURRENCES  AFFECTED CHUNKS  EXAMPLES']
        lines.extend(f"{g['code']}  {g['severity']}  {g['occurrences']}  {g['affected_chunks']}  {g['chunk_indices']}"
                     for g in self.by_code(max_examples=max_examples))
        return '\n'.join(lines)

    def metrics(self) -> dict[str, Any]:
        return dict(chunks_audited=self.total_chunks, errors=self.errors, warnings=self.warnings,
                    passed=self.passed, checks_skipped=len(self.checks_skipped),
                    findings=[{k: v for k, v in g.items() if k != 'chunk_indices'} for g in self.by_code()])

    def to_dict(self, *, detailed: bool = False, max_examples: int = 5) -> dict[str, Any]:
        if not detailed:
            return dict(total_chunks=self.total_chunks, passed=self.passed, errors=self.errors,
                        warnings=self.warnings, checks_run=list(self.checks_run),
                        checks_skipped=list(self.checks_skipped), length_statistics=self.length_statistics,
                        findings=self.by_code(max_examples=max_examples))
        result = asdict(self)
        result.update(passed=self.passed, errors=self.errors, warnings=self.warnings)
        return result


def audit_chunks(
    chunks: Iterable[Mapping[str, Any]],
    *,
    required_metadata: Iterable[str] = ("source",),
    max_tokens: int | None = None,
    token_counter: Callable[[str], int] | None = None,
    boilerplate_min_chunks: int = 3,
    boilerplate_ratio: float = 0.5,
    boilerplate_min_chars: int = 12,
    min_chars: int | None = None,
    distinctive_term_fraction: float | None = None,
    lexical_min_chunks: int = 5,
) -> AuditReport:
    """Audit records with ``text`` and optional ``metadata`` mappings.

    Token counting is disabled unless both max_tokens and a model-specific
    token_counter are supplied. Duplicates normalize whitespace, preserving
    case. Boilerplate checks repeated first/last nonblank lines across records.
    Records are materialized in memory. Input is never modified.
    """
    if (max_tokens is None) != (token_counter is None):
        raise ValueError("Supply both max_tokens and token_counter, or neither")
    if max_tokens is not None and (type(max_tokens) is not int or max_tokens < 1):
        raise ValueError("max_tokens must be a positive integer")
    if token_counter is not None and not callable(token_counter):
        raise TypeError("token_counter must be callable")
    for name, value, minimum in (("boilerplate_min_chunks", boilerplate_min_chunks, 2),
                                 ("boilerplate_min_chars", boilerplate_min_chars, 1)):
        if type(value) is not int or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}")
    if isinstance(boilerplate_ratio, bool) or not isinstance(boilerplate_ratio, (int, float)) or not 0 < boilerplate_ratio <= 1:
        raise ValueError("boilerplate_ratio must be in (0, 1]")
    if isinstance(required_metadata, str):
        raise TypeError("required_metadata must be an iterable of keys, not a string")
    keys = tuple(required_metadata)
    if any(not isinstance(k, str) or not k.strip() for k in keys):
        raise ValueError("Required metadata keys must be nonempty strings")
    keys = tuple(dict.fromkeys(keys))
    if isinstance(chunks, (str, bytes, Mapping)):
        raise TypeError("chunks must be an iterable of records")
    if min_chars is not None and (type(min_chars) is not int or min_chars < 1):
        raise ValueError('min_chars must be a positive integer or None')
    if distinctive_term_fraction is not None and (isinstance(distinctive_term_fraction, bool) or not isinstance(distinctive_term_fraction, (int, float)) or not 0 < distinctive_term_fraction <= 1):
        raise ValueError('distinctive_term_fraction must be in (0, 1]')
    if type(lexical_min_chunks) is not int or lexical_min_chunks < 2:
        raise ValueError('lexical_min_chunks must be an integer >= 2')
    records = list(chunks)
    issues: list[Issue] = []
    seen: dict[str, int] = {}
    boundary_lines: dict[str, list[int]] = defaultdict(list)
    valid_texts = 0
    lengths: list[int] = []
    terms: dict[int, set[str]] = {}

    def add(code, severity, index, message, suggestion, related=()):
        issues.append(Issue(code, severity, index, message, suggestion, related))

    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            add("invalid_record", "error", index, "Record must be a mapping.", "Provide text and metadata fields.")
            continue
        metadata = record.get("metadata", {})
        if not isinstance(metadata, Mapping):
            add("invalid_metadata", "error", index, "Metadata must be a mapping.", "Provide metadata as a dictionary.")
        else:
            for key in keys:
                meta_value = metadata.get(key)
                if meta_value is None or (isinstance(meta_value, str) and not meta_value.strip()) or (isinstance(meta_value, (list, dict, tuple, set)) and not meta_value):
                    add("missing_metadata", "error", index, f"Required metadata {key!r} is missing or empty.", f"Populate metadata[{key!r}].")
        text = record.get("text")
        if not isinstance(text, str):
            add("invalid_text", "error", index, "Text must be a string.", "Extract document text before auditing.")
            continue
        normalized = " ".join(text.split())
        if not normalized:
            add("empty_text", "error", index, "Text is empty or whitespace only.", "Remove the record or fix text extraction.")
            continue
        valid_texts += 1
        lengths.append(len(text.strip()))
        if min_chars is not None and lengths[-1] < min_chars:
            add('short_chunk', 'warning', index, f'Chunk has {lengths[-1]} characters; floor is {min_chars}.',
                'Inspect for truncation or combine with context if appropriate.')
        if distinctive_term_fraction is not None:
            terms[index] = set(re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE))
        if normalized in seen:
            first = seen[normalized]
            add("duplicate_text", "warning", index, f"Text duplicates chunk {first} after whitespace normalization.", "Review provenance before removing duplicate content.", (first,))
        else:
            seen[normalized] = index
        if token_counter is not None:
            try:
                count = token_counter(text)
            except Exception as exc:
                raise ValueError(f"token_counter failed for chunk {index}") from exc
            if type(count) is not int or count < 0:
                raise ValueError(f"token_counter must return a nonnegative Python integer (chunk {index})")
            assert max_tokens is not None
            if count > max_tokens:
                add("token_limit", "error", index, f"Text contains {count} tokens; limit is {max_tokens}.", "Split the text or revise the configured token budget.")
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        # A one-line record is not sufficient evidence of a header or footer.
        if len(lines) >= 2:
            for line in sorted({lines[0], lines[-1]}):
                if len(line) >= boilerplate_min_chars:
                    boundary_lines[line].append(index)

    threshold = max(boilerplate_min_chunks, math.ceil(boilerplate_ratio * valid_texts))
    for indices in boundary_lines.values():
        if len(indices) >= threshold:
            # No raw content in reports: locate candidates through record indices.
            for index in indices:
                add("repeated_boilerplate", "warning", index,
                    f"A boundary line repeats in {len(indices)} chunks.",
                    "Inspect the first and last lines; remove only confirmed headers or footers.")
    extra_run, extra_skipped = ['chunk_length_distribution'], []
    if min_chars is not None:
        extra_run.append('short_chunk')
    else:
        extra_skipped.append('short_chunk')
    if distinctive_term_fraction is not None and len(terms) >= lexical_min_chunks:
        extra_run.append('low_distinctiveness')
        frequencies = Counter(term for values in terms.values() for term in values)
        for index, values in terms.items():
            if len(values) >= 3 and all(frequencies[t] / len(terms) >= distinctive_term_fraction for t in values):
                add('low_distinctiveness', 'warning', index,
                    'All terms occur in a high fraction of this batch.',
                    'Review repetitive navigation or generic text; this does not predict semantic retrieval.')
    else:
        extra_skipped.append('low_distinctiveness')
    ordered = sorted(lengths)
    stats = {'count': len(ordered), 'min': min(ordered, default=0),
             'median': median(ordered) if ordered else 0,
             'p95': ordered[math.ceil(.95 * len(ordered)) - 1] if ordered else 0,
             'max': max(ordered, default=0)}
    checks = ["record_structure", "empty_text", "duplicate_text", "required_metadata", "repeated_boilerplate"]
    if token_counter is not None:
        checks.append("token_limit")
    return AuditReport(len(records), tuple(sorted(issues, key=lambda i: (i.chunk_index, i.code))),
                       tuple(checks + extra_run), tuple(extra_skipped + ([] if token_counter is not None else ["token_limit"])), stats)
