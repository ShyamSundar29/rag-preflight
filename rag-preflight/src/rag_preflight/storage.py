"""Document-indexed SQLite snapshot ledger. Does not write to a vector database."""
from collections import defaultdict
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from .ingestion import Finding, ValidationReport
from .reingestion import ChunkState, DocumentState, Snapshot, UpdatePlan, UnsafePlanError, _digest, plan_update


@dataclass(frozen=True)
class StoredPlan:
    """The nested plan contains only touched documents, not the full corpus."""
    base_revision: str | None
    update: UpdatePlan
    previous_scope_revision: str | None

    @property
    def plan_id(self) -> str:
        return _digest([self.base_revision, self.update.plan_id])


class SQLiteSnapshotStore:
    """One namespace per database; document-addressed snapshot schema version 2.

    Planning loads only documents named in the candidate or retirements. SQLite
    transactions protect ledger commits. External vector writes still need an
    application lock or generation switch spanning plan verification and apply.
    """
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        if type(read_only) is not bool:
            raise ValueError('read_only must be boolean')
        self.path = str(path)
        self.read_only = read_only
        location = Path(path).resolve(strict=True).as_uri() + '?mode=ro' if read_only else self.path
        self._db = sqlite3.connect(location, uri=read_only, timeout=30, isolation_level=None)
        try:
            self._db.execute('PRAGMA busy_timeout=30000')
            if read_only:
                self._db.execute('PRAGMA query_only=ON')
                if self._db.execute('PRAGMA user_version').fetchone()[0] != 2:
                    raise ValueError('Read-only inspection requires SQLite schema 2; upgrade explicitly with a writable store')
                return
            self._db.execute('PRAGMA journal_mode=WAL')
            self._db.execute('PRAGMA synchronous=FULL')
            with self._transaction(write=True):
                version = self._db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, 1, 2):
                    raise ValueError('Unsupported SQLite snapshot schema')
                self._db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK (id=1), namespace TEXT NOT NULL, pipeline_id TEXT NOT NULL, embedding_model TEXT NOT NULL, revision TEXT NOT NULL)')
                self._db.execute('CREATE TABLE IF NOT EXISTS documents (document_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, chunk_count INTEGER NOT NULL)')
                self._db.execute("""CREATE TABLE IF NOT EXISTS commits (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    committed_at TEXT NOT NULL, base_revision TEXT, revision TEXT NOT NULL UNIQUE,
                    before_chunks INTEGER NOT NULL CHECK(before_chunks>=0),
                    after_chunks INTEGER NOT NULL CHECK(after_chunks>=0),
                    added_chunks INTEGER NOT NULL CHECK(added_chunks>=0),
                    removed_chunks INTEGER NOT NULL CHECK(removed_chunks>=0),
                    ordinary_removed_chunks INTEGER, allowance_removed_chunks INTEGER,
                    retirement_removed_chunks INTEGER, policy TEXT NOT NULL)""")
                self._db.execute('CREATE TABLE IF NOT EXISTS history_origin (id INTEGER PRIMARY KEY CHECK(id=1), history_complete INTEGER NOT NULL, baseline_chunks INTEGER NOT NULL)')
                if self._db.execute('SELECT 1 FROM history_origin WHERE id=1').fetchone() is None:
                    self._db.execute('INSERT INTO history_origin VALUES(1,?,?)',
                                     (int(self._state() is None and self.counts()['documents'] == 0), self.counts()['chunks']))
                self._db.execute('PRAGMA user_version=2')
        except BaseException:
            self._db.close()
            raise

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> 'SQLiteSnapshotStore':
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self, write: bool = False) -> Iterator[None]:
        if write and self.read_only:
            raise ValueError('Read-only ledger cannot commit or migrate')
        self._db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        try:
            yield
            self._db.execute('COMMIT')
        except BaseException:
            self._db.execute('ROLLBACK')
            raise

    def _state(self) -> tuple[str, str, str, str] | None:
        return self._db.execute('SELECT namespace, pipeline_id, embedding_model, revision FROM state WHERE id=1').fetchone()

    @property
    def revision(self) -> str | None:
        row = self._state()
        return None if row is None else row[3]

    def counts(self) -> dict[str, int]:
        docs, chunks = self._db.execute('SELECT count(*), coalesce(sum(chunk_count),0) FROM documents').fetchone()
        return {'documents': docs, 'chunks': chunks}

    @staticmethod
    def _history_limit(value: int) -> None:
        if type(value) is not int or value < 1:
            raise ValueError('History limit must be a positive integer')

    def commit_history(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Bounded detailed history, newest first; revisions are for debugging."""
        self._history_limit(limit)
        with self._transaction():
            cursor = self._db.execute('SELECT * FROM commits ORDER BY sequence DESC LIMIT ?', (limit,))
            names = [column[0] for column in cursor.description]
            result = []
            for values in cursor:
                row = dict(zip(names, values))
                row['policy'] = json.loads(row['policy'])
                result.append(row)
            return result

    def deletion_summary(self, *, last_commits: int = 10) -> dict[str, Any]:
        """Rolling ledger measurements, not a cumulative deletion gate.

        Window counts non-noop commits, with the initial-prefix exception below.
        Fractions use the inventory BEFORE its oldest commit, not a sliding sum
        of denominators. When initial population creates a zero denominator and
        later commits exist in the window, exclude the initial prefix explicitly.
        Genuine zero baselines still yield None, not guessed ratios.
        Gross ID removals can exceed 100% or represent replacement identity churn.
        """
        self._history_limit(last_commits)
        with self._transaction():
            rows = self._db.execute('SELECT before_chunks,after_chunks,added_chunks,removed_chunks,ordinary_removed_chunks,allowance_removed_chunks,retirement_removed_chunks,sequence FROM commits ORDER BY sequence DESC LIMIT ?', (last_commits,)).fetchall()
            complete, baseline = self._db.execute('SELECT history_complete,baseline_chunks FROM history_origin WHERE id=1').fetchone()
            current = self.counts()['chunks']
            excluded = 0
            if rows and rows[-1][0] == 0:
                initial = self._db.execute('SELECT sequence,before_chunks FROM commits WHERE after_chunks>0 ORDER BY sequence LIMIT 1').fetchone()
                if initial is not None and initial[1] == 0 and rows[-1][7] <= initial[0] < rows[0][7]:
                    retained = [row for row in rows if row[7] > initial[0]]
                    excluded = len(rows)-len(retained)
                    rows = retained
            start = rows[-1][0] if rows else current
            end = rows[0][1] if rows else current
            def total(column: int) -> int | None:
                return sum(row[column] for row in rows) if all(row[column] is not None for row in rows) else None
            removed = sum(row[3] for row in rows)
            shrink = max(start-end, 0)
            return dict(requested_commits=last_commits, commits_considered=len(rows),
                        history_complete=bool(complete), baseline_chunks_at_history_start=baseline,
                        window_adjusted=bool(excluded), initial_commits_excluded=excluded,
                        baseline_basis=('after_initial_population' if excluded else
                                        'before_oldest_commit' if rows else 'current_inventory_no_commits'),
                        start_chunks=start, end_chunks=end, chunks_added=sum(row[2] for row in rows),
                        chunks_removed=removed, ordinary_removed_chunks=total(4),
                        allowance_removed_chunks=total(5), retirement_removed_chunks=total(6),
                        net_chunk_change=end-start, net_shrink_chunks=shrink,
                        net_shrink_fraction=shrink/start if start else None,
                        gross_removed_fraction=removed/start if start else None,
                        checks_unverified=([] if complete else ['pre_tracking_commit_history']) +
                            (['removal_classification'] if any(n is None for row in rows for n in row[4:7]) else []))

    def document_ids(self) -> tuple[str, ...]:
        """Enumerate sorted IDs without loading document payloads."""
        return tuple(row[0] for row in self._db.execute('SELECT document_id FROM documents ORDER BY document_id'))

    def chunk_ids(self) -> Iterator[str]:
        """Stream verified IDs in one read transaction, one document in memory.

        Consume or close this generator before calling another transactional store
        method. It is ordered by document, not globally by chunk ID.
        """
        with self._transaction():
            state = self._state()
            for doc_id, blob, count in self._db.execute('SELECT document_id,snapshot,chunk_count FROM documents ORDER BY document_id'):
                item = self._decode_document(doc_id, blob, count, state)
                for chunk in item.chunks:
                    yield chunk.chunk_id

    @staticmethod
    def _decode_document(doc_id: str, blob: str, count: int,
                         state: tuple[str, str, str, str] | None) -> Snapshot:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate JSON key in stored document')
                result[key] = value
            return result
        item = Snapshot.from_dict(json.loads(blob, object_pairs_hook=unique))
        if state is None or (item.namespace, item.pipeline_id, item.embedding_model) != state[:3] or len(item.documents) != 1 or item.documents[0].document_id != doc_id:
            raise ValueError('Stored document does not match the ledger identity/configuration')
        if type(count) is not int or len(item.chunks) != count:
            raise ValueError('Stored chunk_count does not match verified payload')
        return item

    def verify(self) -> ValidationReport:
        """Read and verify every row in a consistent transaction; never repair.

        Verifies per-document revisions and SQLite integrity. The ledger revision
        is a CAS token, not a cryptographic proof of the entire ledger/history.
        Corruption of both payload and its hash requires a trusted external backup.
        """
        findings = []
        with self._transaction():
            for row in self._db.execute('PRAGMA integrity_check'):
                if row[0] != 'ok':
                    findings.append(Finding('ledger_integrity', 'error', str(row[0])))
            state = self._state()
            if state is not None and (any(not isinstance(v, str) or not v.strip() for v in state[:3]) or
                                      len(state[3]) != 64 or any(c not in '0123456789abcdef' for c in state[3])):
                findings.append(Finding('ledger_state', 'error', 'Invalid ledger identity or revision token.'))
            for doc_id, blob, count in self._db.execute('SELECT document_id,snapshot,chunk_count FROM documents ORDER BY document_id'):
                try:
                    self._decode_document(doc_id, blob, count, state)
                except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
                    findings.append(Finding('ledger_document_corrupt', 'error',
                        f'Stored document verification failed ({type(exc).__name__}).', document_id=doc_id))
        return ValidationReport(tuple(findings), ('sqlite_integrity', 'all_document_revisions', 'ledger_identity', 'stored_chunk_counts'))

    def _load_scope(self, ids: Iterable[str], state: tuple[str, str, str, str]) -> Snapshot:
        docs: list[DocumentState] = []
        chunks: list[ChunkState] = []
        # Indexed lookups avoid SQL parameter limits and never read unrelated blobs.
        for doc_id in sorted(set(ids)):
            row = self._db.execute('SELECT snapshot,chunk_count FROM documents WHERE document_id=?', (doc_id,)).fetchone()
            if row is not None:
                item = self._decode_document(doc_id, row[0], row[1], state)
                docs.extend(item.documents)
                chunks.extend(item.chunks)
        return Snapshot(state[0], state[1], state[2], tuple(docs), tuple(chunks))

    def load_documents(self, ids: Iterable[str]) -> Snapshot | None:
        """Export selected documents. Missing IDs are omitted; no state returns None."""
        if isinstance(ids, str):
            raise ValueError('ids must be an iterable of document IDs')
        with self._transaction():
            state = self._state()
            return None if state is None else self._load_scope(ids, state)

    def plan(self, candidate: Snapshot, *, retire_documents: Iterable[str] = (),
             max_delete_fraction: float = 0.25,
             allow_shrink: Mapping[str, float] | None = None,
             max_removed_chunks: int | None = None,
             max_shrinking_documents: int | None = None,
             max_corpus_delete_fraction: float = 0.15) -> StoredPlan:
        if isinstance(retire_documents, str):
            raise ValueError('retire_documents must be an iterable of IDs')
        retired = tuple(retire_documents)
        if any(not isinstance(i, str) or not i.strip() for i in retired):
            raise ValueError('Retirement IDs must be nonblank strings')
        ids = {d.document_id for d in candidate.documents} | set(retired)
        with self._transaction():
            state = self._state()
            previous = None if state is None else self._load_scope(ids, state)
            if state is not None and (candidate.pipeline_id, candidate.embedding_model) != state[1:3]:
                # Query only IDs/counts, not the corpus payloads.
                assert previous is not None
                selected = len(previous.documents)
                total = self._db.execute('SELECT count(*) FROM documents').fetchone()[0]
                if selected != total:
                    raise UnsafePlanError('Pipeline/model changes require all retained documents in the batch')
            update = plan_update(previous, candidate, retire_documents=retired,
                                 max_delete_fraction=max_delete_fraction, allow_shrink=allow_shrink,
                                 max_removed_chunks=max_removed_chunks,
                                 max_shrinking_documents=max_shrinking_documents,
                                 max_corpus_delete_fraction=max_corpus_delete_fraction,
                                 _committed_chunk_count=self.counts()['chunks'])
            return StoredPlan(None if state is None else state[3], update,
                              None if previous is None else previous.revision)

    def assert_base(self, plan: StoredPlan) -> None:
        if self.revision != plan.base_revision:
            raise UnsafePlanError('Stale indexed plan; rebuild against the current ledger')

    def commit(self, plan: StoredPlan) -> str:
        """CAS ledger commit after successful external writes; not a cross-store transaction.

        On a stale base nothing is persisted. Callers must prevent external write
        races separately. A no-op plan keeps the ledger revision unchanged.
        """
        if not isinstance(plan, StoredPlan):
            raise TypeError('Use a StoredPlan returned by this store')
        with self._transaction(write=True):
            self.assert_base(plan)
            update = plan.update
            state = self._state()
            if state is not None and update.target.namespace != state[0]:
                raise UnsafePlanError('Namespace mismatch')
            if plan.previous_scope_revision == update.target.revision:
                assert plan.base_revision is not None
                return plan.base_revision
            before_chunks = self.counts()['chunks']
            groups = defaultdict(list)
            for chunk in update.target.chunks:
                groups[chunk.document_id].append(chunk)
            for doc_id in update.retired_documents:
                self._db.execute('DELETE FROM documents WHERE document_id=?', (doc_id,))
            for doc in update.target.documents:
                one = Snapshot(update.target.namespace, update.target.pipeline_id, update.target.embedding_model,
                               (doc,), tuple(groups[doc.document_id]))
                self._db.execute('INSERT INTO documents(document_id,snapshot,chunk_count) VALUES(?,?,?) ON CONFLICT(document_id) DO UPDATE SET snapshot=excluded.snapshot,chunk_count=excluded.chunk_count',
                                 (doc.document_id, json.dumps(one.to_dict(), separators=(',', ':')), len(one.chunks)))
            revision = _digest([plan.base_revision, plan.plan_id])
            self._db.execute('INSERT INTO state VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET namespace=excluded.namespace,pipeline_id=excluded.pipeline_id,embedding_model=excluded.embedding_model,revision=excluded.revision',
                             (update.target.namespace, update.target.pipeline_id, update.target.embedding_model, revision))
            policy = dict(update.deletion_policy)
            removed = len(update.removed)
            # Unknown categories stay unverified for manually constructed legacy
            # plans; do not invent ordinary/exempt classification from totals.
            categories = [policy.get(k) for k in ('ordinary_removed_chunks', 'allowance_removed_chunks', 'retirement_removed_chunks')]
            if any(type(n) is not int or n < 0 for n in categories) or sum(n for n in categories if isinstance(n, int)) != removed:
                categories = [None, None, None] if removed else [0, 0, 0]
            self._db.execute('INSERT INTO commits(committed_at,base_revision,revision,before_chunks,after_chunks,added_chunks,removed_chunks,ordinary_removed_chunks,allowance_removed_chunks,retirement_removed_chunks,policy) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (datetime.now(timezone.utc).isoformat(), plan.base_revision, revision, before_chunks,
                 before_chunks + len(update.added) - removed, len(update.added), removed,
                 *categories, json.dumps(policy, sort_keys=True, allow_nan=False)))
            return revision
