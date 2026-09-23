"""Read-only source versus existing-index JSONL audit; no vector-store SDKs."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import sqlite3
import tempfile
from io import BytesIO
from .evidence import EvidenceBuilder, EvidenceReport
from .ingestion import normalize_units

TEXT_SUFFIXES = ('.txt', '.md', '.rst')
SUPPORTED_SUFFIXES = (*TEXT_SUFFIXES, '.pdf')


def _source_id(value: object) -> str:
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('source_id must be a root-relative POSIX path')
    p = PurePosixPath(value)
    if p.is_absolute() or any(v in ('', '.', '..') for v in value.split('/')):
        raise ValueError('source_id must be a canonical root-relative POSIX path')
    return value


def audit_existing_index(source_root: str | Path, export: str | Path, *,
                         export_complete: bool = False, source_scope_complete: bool = False,
                         unit_metadata_complete: bool = False, max_examples: int = 5) -> EvidenceReport:
    """Audit supported files under root using path-based source IDs.

    Complete flags attest identical scope/generation and consistent enumeration.
    Fingerprints use {'algorithm':'sha256','basis':'file_bytes','value':hex}.
    Only such fingerprints are comparable. Unit metadata establishes representation,
    never full content searchability or historical extraction success.
    Inventories live on SQLite disk; working memory grows with file/record size.
    """
    for flag in (export_complete, source_scope_complete, unit_metadata_complete):
        if type(flag) is not bool:
            raise ValueError('Completeness flags must be booleans')
    b = EvidenceBuilder(max_examples)
    root = Path(source_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('source_root must be a directory')
    source_ok, export_ok = True, True
    unverified = []
    with tempfile.TemporaryDirectory(prefix='rag-preflight-index-') as directory:
        db = sqlite3.connect(str(Path(directory)/'evidence.db'))
        try:
            db.executescript('''CREATE TABLE sources(id TEXT PRIMARY KEY, hash TEXT, units TEXT);
                CREATE TABLE records(id TEXT PRIMARY KEY, source TEXT, payload TEXT);
                CREATE INDEX record_source ON records(source);
                CREATE TABLE coverage(source TEXT, unit TEXT, PRIMARY KEY(source,unit));
                CREATE TABLE versions(source TEXT, value TEXT, PRIMARY KEY(source,value));
                CREATE TABLE declared_versions(source TEXT, value TEXT, PRIMARY KEY(source,value));''')
            def enumeration_error(exc: OSError) -> None:
                nonlocal source_ok
                source_ok = False
                b.add('source_enumeration_failed', type(exc).__name__)
            for folder, dirs, files in os.walk(root, followlinks=False, onerror=enumeration_error):
                dirs.sort()
                for name in list(dirs):
                    if Path(folder, name).is_symlink():
                        dirs.remove(name)
                        source_ok = False
                        b.add('source_path_excluded', Path(folder, name).relative_to(root).as_posix())
                for name in sorted(files):
                    path = Path(folder, name)
                    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                        continue
                    sid = path.relative_to(root).as_posix()
                    if path.is_symlink() or not path.resolve().is_relative_to(root):
                        source_ok = False
                        b.add('source_path_excluded', sid)
                        continue
                    try:
                        raw = path.read_bytes()
                        digest = hashlib.sha256(raw).hexdigest()
                        if path.suffix.lower() == '.pdf':
                            from pypdf import PdfReader
                            reader = PdfReader(BytesIO(raw))
                            units = [f'page:{i+1}' for i in range(len(reader.pages))]
                            for unit, page in zip(units, reader.pages):
                                try:
                                    page.extract_text()
                                except Exception as exc:
                                    b.add('source_extraction_failed', {'source': sid, 'unit': unit, 'error': type(exc).__name__})
                        else:
                            raw.decode('utf-8') # explicit supported encoding, no guesses
                            units = ['file']
                        db.execute('INSERT INTO sources VALUES(?,?,?)', (sid, digest, json.dumps(units)))
                    except Exception as exc:
                        source_ok = False
                        b.add('source_read_failed', {'source': sid, 'error': type(exc).__name__})
            record_count, missing_source, missing_units, missing_fingerprint, missing_text = 0, 0, 0, 0, 0
            try:
                with Path(export).open(encoding='utf-8') as handle:
                    for line_number, line in enumerate(handle, 1):
                        if not line.strip():
                            continue
                        record_count += 1
                        try:
                            def unique(pairs):
                                result = {}
                                for k, v in pairs:
                                    if k in result:
                                        raise ValueError('Duplicate JSON key')
                                    result[k] = v
                                return result
                            record = json.loads(line, object_pairs_hook=unique)
                            if not isinstance(record, dict) or not isinstance(record.get('id'), str) or not record['id'].strip():
                                raise ValueError('Each record requires a nonblank id')
                            record_source = _source_id(record['source_id']) if 'source_id' in record else None
                            record_units = normalize_units(record['units']) if 'units' in record else None
                            if 'text' in record and not isinstance(record['text'], str):
                                raise ValueError('Exported text must be a string')
                            version_label = record.get('source_version')
                            if version_label is not None and (not isinstance(version_label, str) or not version_label.strip()):
                                raise ValueError('source_version must be a nonblank string when available')
                            fp = record.get('source_fingerprint')
                            comparable = None
                            if fp is not None:
                                if not isinstance(fp, dict):
                                    raise ValueError('Fingerprint must be an object')
                                if fp.get('algorithm') == 'sha256' and fp.get('basis') == 'file_bytes':
                                    comparable = fp.get('value')
                                    if not isinstance(comparable, str) or len(comparable) != 64 or any(c not in '0123456789abcdef' for c in comparable):
                                        raise ValueError('Invalid SHA-256 file fingerprint')
                            payload = json.dumps(record, sort_keys=True, allow_nan=False)
                            prior = db.execute('SELECT payload FROM records WHERE id=?', (record['id'],)).fetchone()
                            if prior is not None:
                                if prior[0] != payload:
                                    export_ok = False
                                b.add('duplicate_index_record' if prior[0] == payload else 'conflicting_index_record', line_number)
                            else:
                                db.execute('INSERT INTO records VALUES(?,?,?)', (record['id'], record_source, payload))
                            if record_source is None:
                                missing_source += 1
                            if record_units is None:
                                missing_units += 1
                            if comparable is None:
                                missing_fingerprint += 1
                            if 'text' not in record:
                                missing_text += 1
                            elif not record['text'].strip():
                                b.add('empty_indexed_text', line_number)
                            if record_source is not None:
                                if version_label is not None:
                                    db.execute('INSERT OR IGNORE INTO declared_versions VALUES(?,?)', (record_source, version_label))
                                if Path(record_source).suffix.lower() not in SUPPORTED_SUFFIXES:
                                    unverified.append('records_outrecord_sourcee_supported_source_scope')
                                if record_units is not None and ('text' not in record or record['text'].strip()):
                                    for unit in record_units:
                                        db.execute('INSERT OR IGNORE INTO coverage VALUES(?,?)', (record_source, unit))
                                if comparable is not None:
                                    db.execute('INSERT OR IGNORE INTO versions VALUES(?,?)', (record_source, comparable))
                                    source = db.execute('SELECT hash FROM sources WHERE id=?', (record_source,)).fetchone()
                                    if source is not None and source[0] != comparable:
                                        b.add('source_hash_mismatch', line_number)
                        except (ValueError, TypeError, KeyError) as exc:
                            export_ok = False
                            b.add('malformed_index_record', {'line': line_number, 'error': type(exc).__name__})
            except (OSError, UnicodeError) as exc:
                export_ok = False
                b.add('index_export_read_failed', type(exc).__name__)
            for (record_source,) in db.execute('SELECT source FROM versions GROUP BY source HAVING count(*)>1 UNION SELECT source FROM declared_versions GROUP BY source HAVING count(*)>1 ORDER BY source'):
                b.add('conflicting_source_versions', record_source)
            # Bad/missing provenance prevents definitive absence claims: unidentified
            # records might represent any otherwise absent source/unit.
            absence_verified = export_complete and source_ok and export_ok and not missing_source
            orphan_verified = source_scope_complete and source_ok and export_ok
            if not absence_verified:
                unverified.append('source_absence')
            if not orphan_verified:
                unverified.append('index_orphans')
            missing_source_count, orphan_count, missing_unit_count = 0, 0, 0
            if absence_verified:
                for (record_source,) in db.execute('SELECT id FROM sources WHERE NOT EXISTS(SELECT 1 FROM records WHERE records.source=sources.id) ORDER BY id'):
                    b.add('source_not_indexed', record_source)
                    missing_source_count += 1
            if orphan_verified:
                for (record_source,) in db.execute('SELECT DISTINCT source FROM records WHERE source IS NOT NULL AND NOT EXISTS(SELECT 1 FROM sources WHERE sources.id=records.source) ORDER BY source'):
                    if Path(record_source).suffix.lower() in SUPPORTED_SUFFIXES:
                        b.add('indexed_source_orphan', record_source)
                        orphan_count += 1
            coverage_verified = absence_verified and unit_metadata_complete and not missing_units
            if not coverage_verified:
                unverified.append('unit_representation')
            else:
                for record_source, units_json in db.execute('SELECT id,units FROM sources ORDER BY id'):
                    for unit in json.loads(units_json):
                        if db.execute('SELECT 1 FROM coverage WHERE source=? AND unit=?', (record_source, unit)).fetchone() is None:
                            b.add('missing_indexed_unit', {'source': record_source, 'unit': unit})
                            missing_unit_count += 1
            if missing_source:
                unverified.append('source_mapping')
            if missing_fingerprint:
                unverified.append('source_version_comparison')
            if missing_text:
                unverified.append('indexed_text_nonempty')
            unverified.extend(['historical_ingestion_success', 'full_unit_content_searchability'])
            return b.report(dict(documents_audited=db.execute('SELECT count(*) FROM sources').fetchone()[0],
                                 exported_records=record_count, sources_missing=missing_source_count,
                                 orphan_sources=orphan_count, missing_units=missing_unit_count,
                                 records_without_source=missing_source, records_without_units=missing_units,
                                 records_without_comparable_fingerprint=missing_fingerprint,
                                 records_without_text=missing_text), unverified)
        finally:
            db.close()
