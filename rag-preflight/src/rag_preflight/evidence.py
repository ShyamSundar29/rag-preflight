"""Bounded evidence reports, with JSON-compatible, identity-free measurements."""
from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvidenceReport:
    groups: tuple[dict[str, Any], ...]
    measurements: dict[str, Any]
    checks_unverified: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not any(g['severity'] == 'error' for g in self.groups)

    def metrics(self) -> dict[str, Any]:
        return {**self.measurements, 'passed': self.passed,
                'errors': sum(g['occurrences'] for g in self.groups if g['severity'] == 'error'),
                'warnings': sum(g['occurrences'] for g in self.groups if g['severity'] == 'warning'),
                'checks_unverified': len(self.checks_unverified),
                'findings': [{k: v for k, v in g.items() if k != 'examples'} for g in self.groups]}

    def to_dict(self) -> dict[str, Any]:
        return {**self.metrics(), 'findings': list(self.groups),
                'checks_unverified': list(self.checks_unverified)}

    def table(self) -> str:
        return '\n'.join([f"{'PASS' if self.passed else 'FAIL'} (unverified checks: {len(self.checks_unverified)})",
                          'CODE  SEVERITY  OCCURRENCES  EXAMPLES',
                          *(f"{g['code']}  {g['severity']}  {g['occurrences']}  {g['examples']}" for g in self.groups)])


class EvidenceBuilder:
    def __init__(self, max_examples: int) -> None:
        if type(max_examples) is not int or max_examples < 0:
            raise ValueError('max_examples must be a nonnegative integer')
        self.limit = max_examples
        self.counts: Counter[tuple[str, str]] = Counter()
        self.examples: dict[tuple[str, str], list[Any]] = {}

    def add(self, code: str, example: Any = None, *, count: int = 1, severity: str = 'error') -> None:
        key = (code, severity)
        self.counts[key] += count
        samples = self.examples.setdefault(key, [])
        if len(samples) < self.limit and example is not None:
            samples.append(example)

    def report(self, measurements: dict[str, Any], unverified: list[str]) -> EvidenceReport:
        return EvidenceReport(tuple(dict(code=k[0], severity=k[1], occurrences=n,
                                         examples=self.examples[k]) for k, n in sorted(self.counts.items())),
                              measurements, tuple(sorted(set(unverified))))
