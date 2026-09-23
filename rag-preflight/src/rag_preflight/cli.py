"""Audit RAG ingestion and inspect guarded plans. Exit 0: pass, 1: audited findings, 2: input/incomplete."""
import argparse
import json
from pathlib import Path
import sys
from .core import audit_chunks


COMMANDS = {
    'check': 'Audit supported source files; optional independent expected-file list',
    'chunks': 'Audit chunk integrity in JSON or JSONL',
    'ingestion': 'Validate a document manifest and extraction batch',
    'embeddings': 'Validate keyed vectors and embedding declarations',
    'plan': 'Compare snapshots and guard proposed ingestion changes',
    'ledger': 'Inspect rolling deletion measurements and commit history',
    'existing-index': 'Compare source files with an existing index export',
}


def command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='rag-preflight', description=__doc__,
        epilog='Legacy chunk audit: rag-preflight INPUT.json[l] [options]. '
               'Use rag-preflight COMMAND --help for workflow options. '
               'For extensionless input paths, use chunks INPUT or ./INPUT.')
    commands = parser.add_subparsers(dest='command')
    for name, description in COMMANDS.items():
        commands.add_parser(name, help=description)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        command_parser().print_usage(file=sys.stderr)
        print('Input error: a command or chunk input file is required; use --help.', file=sys.stderr)
        return 2
    if argv[0] in {'-h', '--help'}:
        command_parser().print_help()
        return 0
    if (not argv[0].startswith('-') and argv[0] not in COMMANDS
            and not Path(argv[0]).suffix and '/' not in argv[0]
            and '\\' not in argv[0] and not Path(argv[0]).exists()):
        print(f"Unknown command: {argv[0]!r}. Available commands: "
              + ', '.join(COMMANDS)
              + '. Use chunks INPUT for an extensionless input file.', file=sys.stderr)
        return 2
    if argv[0] == 'chunks':
        return chunks_main(argv[1:])
    if argv[0] == 'check':
        return check_main(argv[1:])
    if argv and argv[0] == 'ledger':
        return ledger_main(argv[1:])
    if argv and argv[0] == 'existing-index':
        return existing_main(argv[1:])
    if argv and argv[0] in {'ingestion', 'embeddings', 'plan'}:
        return workflow_main(argv)
    return chunks_main(argv)


def check_main(argv: list[str]) -> int:
    from .folder import check_source_folder
    parser = argparse.ArgumentParser(prog='rag-preflight check',
        description='Read-only current-source completeness audit; does not verify a historical index')
    parser.add_argument('source_root', type=Path)
    parser.add_argument('--expected', type=Path,
                        help='Independent UTF-8 list of required root-relative supported paths')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--details', action='store_true')
    parser.add_argument('--max-examples', type=int, default=5)
    args = parser.parse_args(argv)
    try:
        report = check_source_folder(args.source_root, max_examples=args.max_examples,
                                     expected=args.expected)
        print(json.dumps(report.to_dict(detailed=args.details, max_examples=args.max_examples), indent=2)
              if args.json else report.table(max_examples=args.max_examples))
        if args.details and not args.json:
            for finding in report.audit.findings:
                print(f'[{finding.severity}] {finding.document_id}: {finding.code}: {finding.message}')
        return (0 if report.passed else 1 if report.outcome == 'audit_failed' else 2)
    except (OSError, ValueError, TypeError) as exc:
        print(f'Input error: {exc}', file=sys.stderr)
        return 2


def chunks_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='rag-preflight chunks', description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--require", nargs="*", default=["source"], metavar="KEY")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--fail-on-warnings", action="store_true")
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--max-examples", type=int, default=5)
    parser.add_argument("--min-chars", type=int)
    parser.add_argument("--distinctive-term-fraction", type=float)
    args = parser.parse_args(argv)
    try:
        content = args.input.read_text(encoding="utf-8")
        if args.input.suffix.lower() == ".jsonl":
            records = [json.loads(line) for line in content.splitlines() if line.strip()]
        else:
            records = json.loads(content)
            if not isinstance(records, list):
                raise ValueError("JSON input must be an array")
        report = audit_chunks(records, required_metadata=args.require, min_chars=args.min_chars,
                              distinctive_term_fraction=args.distinctive_term_fraction)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(report.to_dict(detailed=args.details, max_examples=args.max_examples), indent=2))
    else:
        print(report.table(max_examples=args.max_examples))
        if args.details:
            for issue in report.issues:
                print(f"[{issue.severity}] chunk {issue.chunk_index}: {issue.code}: {issue.message}")
        if report.checks_skipped:
            print("Skipped: " + ", ".join(report.checks_skipped))
    return int(not report.passed or (args.fail_on_warnings and report.warnings > 0))


def workflow_main(argv: list[str]) -> int:
    """Manifest and embedding workflows, dispatched by main()."""
    from .ingestion import (AcceptancePolicy, DocumentSpec, ExtractionReceipt,
                            audit_embeddings, audit_ingestion)
    from .reingestion import Snapshot, build_snapshot, plan_update
    parser = argparse.ArgumentParser(prog='rag-preflight')
    commands = parser.add_subparsers(dest='command', required=True)
    ingestion = commands.add_parser('ingestion', help='Validate a document manifest and extraction batch')
    ingestion.add_argument('input', type=Path)
    ingestion.add_argument('--snapshot', type=Path, help='Write a validated candidate snapshot, not committed database state')
    embeddings = commands.add_parser('embeddings', help='Validate keyed vectors')
    embeddings.add_argument('input', type=Path)
    planner = commands.add_parser('plan', help='Compare trusted snapshots; no database writes')
    planner.add_argument('previous', help='Committed snapshot path, or - for first ingestion')
    planner.add_argument('current', type=Path, help='Validated candidate snapshot')
    planner.add_argument('--retire', nargs='*', default=[])
    planner.add_argument('--max-delete-fraction', type=float, default=0.25)
    planner.add_argument('--max-removed-chunks', type=int, default=None)
    planner.add_argument('--max-shrinking-documents', type=int, default=None)
    planner.add_argument('--max-corpus-delete-fraction', type=float, default=.15)
    planner.add_argument('--allow-shrink', type=json.loads, default={}, help='JSON mapping of document IDs to allowed removal fractions')
    args = parser.parse_args(argv)
    try:
        if args.command == 'plan':
            previous = None if args.previous == '-' else Snapshot.load(args.previous)
            result = plan_update(previous, Snapshot.load(args.current), retire_documents=args.retire,
                                 max_delete_fraction=args.max_delete_fraction, allow_shrink=args.allow_shrink,
                                 max_removed_chunks=args.max_removed_chunks,
                                 max_shrinking_documents=args.max_shrinking_documents,
                                 max_corpus_delete_fraction=args.max_corpus_delete_fraction)
            print(json.dumps(result.to_dict(), indent=2))
            return 0
        data = json.loads(args.input.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('Workflow input must be a JSON object')
        if args.command == 'embeddings':
            report = audit_embeddings(data['expected_chunk_ids'], data['embeddings'], dimensions=data['dimensions'],
                                      backend=data.get('backend', 'python'), detect_duplicates=data.get('detect_duplicates', True),
                                      norm_range=data.get('norm_range'), max_warnings=data.get('max_warnings'))
        else:
            documents = [DocumentSpec(**item) for item in data['documents']]
            receipts = [ExtractionReceipt(**item) for item in data['receipts']]
            policy = AcceptancePolicy(**data.get('policy', {}))
            report = audit_ingestion(documents, receipts, data['chunks'], policy=policy, namespace=data.get('namespace'))
            if args.snapshot and report.passed:
                if args.snapshot.resolve() == args.input.resolve():
                    raise ValueError('Snapshot output must not overwrite input')
                build_snapshot(documents, receipts, data['chunks'], policy=policy,
                               namespace=data['namespace'], pipeline_id=data['pipeline_id'],
                               embedding_model=data['embedding_model']).save(args.snapshot)
        print(json.dumps(report.to_dict(), indent=2))
        return int(not report.passed)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        print(f'Workflow error: {exc}', file=sys.stderr)
        return 2


def existing_main(argv: list[str]) -> int:
    from .existing import audit_existing_index
    parser = argparse.ArgumentParser(prog='rag-preflight existing-index')
    parser.add_argument('source_root', type=Path)
    parser.add_argument('export', type=Path)
    parser.add_argument('--export-complete', action='store_true')
    parser.add_argument('--source-scope-complete', action='store_true')
    parser.add_argument('--unit-metadata-complete', action='store_true')
    parser.add_argument('--max-examples', type=int, default=5)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = audit_existing_index(args.source_root, args.export,
            export_complete=args.export_complete, source_scope_complete=args.source_scope_complete,
            unit_metadata_complete=args.unit_metadata_complete, max_examples=args.max_examples)
        print(json.dumps(report.to_dict(), indent=2) if args.json else report.table())
        return int(not report.passed)
    except (OSError, ValueError, TypeError) as exc:
        print(f'Input error: {exc}', file=sys.stderr)
        return 2


def ledger_main(argv: list[str]) -> int:
    """Read-only ledger inspection. Missing/legacy files are never created/upgraded."""
    import sqlite3
    from .storage import SQLiteSnapshotStore
    parser = argparse.ArgumentParser(prog='rag-preflight ledger')
    commands = parser.add_subparsers(dest='command', required=True)
    summary = commands.add_parser('summary', help='Rolling deletion measurements')
    summary.add_argument('path', type=Path)
    summary.add_argument('--last-commits', type=int, default=10)
    summary.add_argument('--json', action='store_true')
    history = commands.add_parser('history', help='Bounded detailed commit history')
    history.add_argument('path', type=Path)
    history.add_argument('--limit', type=int, default=10)
    history.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        with SQLiteSnapshotStore(args.path, read_only=True) as ledger:
            result = (ledger.deletion_summary(last_commits=args.last_commits) if args.command == 'summary'
                      else ledger.commit_history(limit=args.limit))
        # Both modes produce inspectable JSON; --json is explicit for scripts.
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f'Ledger inspection error: {exc}', file=sys.stderr)
        return 2
