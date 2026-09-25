"""Read-only evidence, guarded apply, explicit recovery, and question answering."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from typing import Callable, TypeVar

from rag_preflight import SQLiteSnapshotStore, estimate_embedding_cost, stable_chunk_id, plan_update
from .app import ReferenceApp
from .config import Settings
from .corpus import CandidateRejected, prepare
from .provider import OpenAIProvider
from .store import VectorStore, verify_payloads
from .tokenizer import encoding_for_model


SettingsT = TypeVar('SettingsT', bound=Settings)


def parser(prog: str, backend_name: str, root_env: str) -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog=prog,
        description=f'Separate evidence-driven {backend_name}/OpenAI application')
    command.add_argument('--app-root', type=Path,
                         help=f'Directory containing corpus/manifest.json; can also set {root_env}')
    command.add_argument('--source-root', type=Path,
                         help='Exact supported PDF directory; defaults to APP_ROOT/../pdfs')
    command.add_argument('--state-root', type=Path,
                         help='Local vector-store/ledger/journal directory; defaults to APP_ROOT/state')
    command.add_argument('--runs-root', type=Path,
                         help='Separate run-evidence directory; defaults to APP_ROOT/runs')
    command.add_argument('--embedding-price-per-million',
                         help='Current caller-supplied USD price for embedding cost estimate')
    command.add_argument('--embedding-budget-usd',
                         help='Maximum estimated and measured ingestion embedding spend')
    command.add_argument('--max-output-tokens', type=int,
                         help='Generation output cap; defaults to the application setting')
    sub = command.add_subparsers(dest='command', required=True)
    sub.add_parser('verify-papers', help='Check pinned PDF scope, extraction and Preflight audits')
    sub.add_parser('dry-run', help='Prepare a guarded plan and exact-token embedding estimate; no API calls')
    ingest = sub.add_parser('ingest', help='Embed planned inputs, write/read-back vector store, then commit ledger')
    ingest.add_argument('--metadata-tag')
    ingest.add_argument('--fail-after-upserts', action='store_true',
                        help='Inject a persistent failure before ledger commit')
    sub.add_parser('recover', help='Replay a pending journal idempotently or verify post-commit state')
    sub.add_parser('verify-index', help='Read complete vector-store IDs, payloads and ledger evidence')
    ask = sub.add_parser('ask', help='Embed question, retrieve and answer with paper/page citations')
    ask.add_argument('question')
    ask.add_argument('--generation-model', required=True,
                     help='Explicit OpenAI generation model; chosen at live-run time')
    scenario = sub.add_parser('demonstrate-omission',
        help='Compare isolated naive deletion with guarded Preflight rejection')
    scenario.add_argument('source_id')
    scenario.add_argument('unit', help='Canonical page:N unit')
    edit = sub.add_parser('preview-text-edit',
        help='Plan-only synthetic source edit; compare selective embedding cost without API calls')
    edit.add_argument('source_id')
    edit.add_argument('--edited-chunks', type=int, default=2)
    live_edit = sub.add_parser('demonstrate-text-edit',
        help='Embed a synthetic selective edit into an isolated verified clone')
    live_edit.add_argument('source_id')
    live_edit.add_argument('--edited-chunks', type=int, default=2)
    comparison = sub.add_parser('compare-omission',
        help='Ask the same question of guarded index and verified omission clone')
    comparison.add_argument('omission_run_id')
    comparison.add_argument('question')
    comparison.add_argument('--generation-model', required=True)
    return command


def main(argv: list[str] | None, settings_type: type[SettingsT],
         app_type: Callable[[SettingsT], ReferenceApp],
         store_factory: Callable[..., VectorStore],
         prog: str, backend_name: str) -> int:
    args = parser(prog, backend_name, settings_type.ROOT_ENV).parse_args(
        sys.argv[1:] if argv is None else argv)
    try:
        settings = settings_type.local(args.app_root)
        if args.source_root is not None:
            settings = replace(settings, source_root=args.source_root.resolve())
        if args.state_root is not None:
            settings = replace(settings, state_root=args.state_root.resolve())
        if args.runs_root is not None:
            settings = replace(settings, runs_root=args.runs_root.resolve())
        if args.embedding_price_per_million is not None:
            settings = replace(settings,
                               embedding_price_per_million=args.embedding_price_per_million)
        if args.embedding_budget_usd is not None:
            settings = replace(settings,
                               max_estimated_embedding_usd=args.embedding_budget_usd)
        if args.max_output_tokens is not None:
            settings = replace(settings, max_output_tokens=args.max_output_tokens)
        app = app_type(settings)
        if args.command == 'verify-papers':
            candidate = prepare(settings)
            result = {'source_evidence': list(candidate.source_evidence),
                      'ingestion_audit': candidate.audit,
                      'chunk_audit': candidate.chunk_audit,
                      'candidate_chunks': len(candidate.chunks),
                      'paid_api_calls': 0}
        elif args.command == 'dry-run':
            candidate = prepare(settings)
            if app.ledger_path.exists():
                with SQLiteSnapshotStore(app.ledger_path, read_only=True) as ledger:
                    plan = ledger.plan(candidate.snapshot).update
            else:
                plan = plan_update(None, candidate.snapshot)
            encoding = encoding_for_model(settings.embedding_model)
            counts = {stable_chunk_id(settings.namespace, row['metadata']['document_id'], row['chunk_key']):
                      len(encoding.encode(row['text'])) for row in candidate.chunks}
            cost = estimate_embedding_cost(plan,
                price_per_million_tokens=settings.embedding_price_per_million,
                currency='USD', token_counts=counts,
                comparison_ids=tuple(sorted(counts)),
                comparison_scope='complete listed three-paper candidate batch')
            result = {'plan': plan.to_dict(), 'cost_estimate': cost.to_dict(), 'paid_api_calls': 0}
        elif args.command == 'verify-index':
            with SQLiteSnapshotStore(app.ledger_path, read_only=True) as ledger:
                store = store_factory(settings, create=False)
                prior = app._prior(ledger, store)
                result = {'passed': True, 'ledger_revision': ledger.revision,
                          'ledger_counts': ledger.counts(),
                          'read_back': verify_payloads(store, prior, complete_ids=set(prior)),
                          'paid_api_calls': 0}
        elif args.command == 'demonstrate-omission':
            result = app.demonstrate_omission(args.source_id, args.unit)
        elif args.command == 'preview-text-edit':
            result = app.preview_text_edit(args.source_id, edited_chunks=args.edited_chunks)
        else:
            if not os.getenv('OPENAI_API_KEY'):
                raise ValueError('OPENAI_API_KEY is not configured; set it locally, never in the repository')
            if args.command in {'ask', 'compare-omission'}:
                settings = replace(settings, generation_model=args.generation_model)
                app = app_type(settings)
            provider = OpenAIProvider(settings)
            if args.command == 'ingest':
                result = app.ingest(provider, metadata_tag=args.metadata_tag,
                                    fail_after_upserts=args.fail_after_upserts)
            elif args.command == 'demonstrate-text-edit':
                result = app.demonstrate_text_edit(provider, args.source_id,
                                                   edited_chunks=args.edited_chunks)
            elif args.command == 'recover':
                result = app.recover(provider)
            elif args.command == 'compare-omission':
                result = app.compare_omission_answer(provider, args.omission_run_id,
                                                     args.question)
            else:
                result = app.ask(provider, args.question)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except CandidateRejected as exc:
        print(json.dumps({'error': str(exc), 'ingestion_audit': exc.audit}, indent=2),
              file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f'Reference application error: {exc}', file=sys.stderr)
        return 2
