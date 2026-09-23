"""ID reconciliation using a temporary on-disk index, with bounded report samples."""
from collections.abc import Iterable
from dataclasses import asdict, dataclass
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReconciliationReport:
    namespace: str
    inventory_complete: bool
    expected_count: int
    observed_count: int
    missing_count: int
    orphan_count: int
    duplicate_expected_count: int
    duplicate_observed_count: int
    missing_ids: tuple[str, ...]
    orphan_ids: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.inventory_complete and not (self.missing_count or self.orphan_count or
            self.duplicate_expected_count or self.duplicate_observed_count)

    def metrics(self) -> dict[str, Any]:
        return {k: v for k, v in self.to_dict().items() if k not in ('namespace', 'missing_ids', 'orphan_ids')}

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), 'passed': self.passed}


def reconcile(ledger_ids: Iterable[str], store_ids: Iterable[str], *, namespace: str,
              inventory_complete: bool = False, max_examples: int = 100) -> ReconciliationReport:
    """Compare IDs from the same namespace/generation and a consistent read.

    Caller must explicitly attest that BOTH enumerations are complete. Default
    incomplete reports cannot pass. This checks IDs, not vector/metadata contents,
    and neither applies changes nor authorizes commit. Duplicate IDs also fail.
    Disk grows with inventory size; reports retain at most max_examples per kind.
    """
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError('namespace is required')
    if type(inventory_complete) is not bool:
        raise ValueError('inventory_complete must be a bool')
    if type(max_examples) is not int or max_examples < 0:
        raise ValueError('max_examples must be a nonnegative integer')
    if isinstance(ledger_ids, (str, bytes)) or isinstance(store_ids, (str, bytes)):
        raise TypeError('Pass iterables of IDs, not strings')
    with tempfile.TemporaryDirectory(prefix='rag-preflight-reconcile-') as directory:
        db = sqlite3.connect(str(Path(directory) / 'ids.sqlite'))
        try:
            db.execute('CREATE TABLE ids (id TEXT PRIMARY KEY, expected INTEGER NOT NULL DEFAULT 0, observed INTEGER NOT NULL DEFAULT 0)')
            for values, column in ((ledger_ids, 'expected'), (store_ids, 'observed')):
                for value in values:
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError('IDs must be nonblank strings')
                    db.execute(f'INSERT INTO ids(id,{column}) VALUES(?,1) ON CONFLICT(id) DO UPDATE SET {column}={column}+1', (value,))
            def count(condition: str) -> int:
                return db.execute(f'SELECT count(*) FROM ids WHERE {condition}').fetchone()[0]
            def sample(condition: str) -> tuple[str, ...]:
                return tuple(row[0] for row in db.execute(f'SELECT id FROM ids WHERE {condition} ORDER BY id LIMIT ?', (max_examples,)))
            return ReconciliationReport(namespace, inventory_complete, count('expected>0'), count('observed>0'),
                count('expected>0 AND observed=0'), count('observed>0 AND expected=0'),
                db.execute('SELECT coalesce(sum(max(expected-1,0)),0) FROM ids').fetchone()[0],
                db.execute('SELECT coalesce(sum(max(observed-1,0)),0) FROM ids').fetchone()[0],
                sample('expected>0 AND observed=0'), sample('observed>0 AND expected=0'))
        finally:
            db.close()
