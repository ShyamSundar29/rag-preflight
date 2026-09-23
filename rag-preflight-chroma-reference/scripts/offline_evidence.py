"""Generate reviewable local Chroma evidence; simulated vectors, zero paid calls."""
import hashlib
import json
import argparse
from pathlib import Path
from dataclasses import replace

import tiktoken
from rag_preflight_reference.app import ReferenceApp
from rag_preflight_reference.config import Settings
from rag_preflight_reference.journal import atomic_json
from rag_preflight_reference.provider import Answer, EmbeddingBatch


class SimulatedProvider:
    def __init__(self):
        self.calls = 0
        self.tokens = 0
    def embed(self, inputs):
        self.calls += 1
        encoding = tiktoken.encoding_for_model('text-embedding-3-small')
        tokens = sum(len(encoding.encode(text)) for text in inputs)
        self.tokens += tokens
        vectors = []
        for text in inputs:
            digest = hashlib.sha256(text.encode('utf-8')).digest()
            vectors.append(tuple((digest[i % 32] - 127) / 500 for i in range(1536)))
        return EmbeddingBatch(tuple(vectors), tokens, 'simulated-local-only')
    def answer(self, question, contexts):
        return Answer('Simulated answer [1]. This does not test model quality.',
                      0, 0, 'simulated-local-only')


def curate(settings: Settings, reviewed: dict, destination: Path) -> dict:
    """Ship small source/run checks without raw text, vectors or state files."""
    curated: dict[str, list[str]] = {}
    for scenario, key in [('first', 'first_run_id'), ('unchanged', 'unchanged_run_id'),
                          ('metadata', 'metadata_run_id'), ('omission', 'omission_run_id'),
                          ('simulated_answer', 'answer_run_id')]:
        source_dir = settings.runs_root / reviewed[key]
        target_dir = destination.parent / 'offline-runs' / scenario
        names = (('summary.json', 'cost-estimate.json', 'verification.json',
                  'ingestion-audit.json', 'source-evidence.json')
                 if scenario in ('first', 'unchanged', 'metadata') else
                 ('summary.json', 'guarded-rejection.json') if scenario == 'omission'
                 else ('answer.json', 'query-embedding-audit.json'))
        curated[scenario] = []
        for name in names:
            source = source_dir / name
            if not source.is_file():
                raise ValueError(f'Missing local run evidence for {scenario}: {name}')
            target = target_dir / name
            atomic_json(target, json.loads(source.read_text()))
            curated[scenario].append(target.relative_to(destination.parent).as_posix())
    if 'synthetic_edit_preview' in reviewed:
        path = destination.parent / 'offline-runs/synthetic_edit/preview.json'
        atomic_json(path, reviewed['synthetic_edit_preview'])
        curated['synthetic_edit'] = [path.relative_to(destination.parent).as_posix()]
    reviewed['schema_version'] = 2
    reviewed['curated_run_files'] = curated
    reviewed['raw_run_files'] = 'local ignored runs; full journals and Chroma state are not shipped'
    reviewed['reproduction'] = ('python scripts/offline_evidence.py --state-root NEW_STATE_PATH '
                                 '--runs-root NEW_RUNS_PATH --output NEW_SUMMARY_PATH')
    reviewed['independent_live_proof'] = False
    old_rows = reviewed.pop('question_retrieved_passages', None)
    if old_rows is not None:
        reviewed['simulated_question_returned_rows'] = old_rows
    atomic_json(destination, reviewed)
    return reviewed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root', type=Path)
    parser.add_argument('--runs-root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--curate-existing', action='store_true',
                        help='Create shareable reduced run evidence from an existing local run')
    args = parser.parse_args()
    settings = Settings.local()
    settings = replace(settings,
        state_root=args.state_root or settings.root / 'state/offline-evidence',
        runs_root=args.runs_root or settings.root / 'runs/offline-evidence')
    destination = args.output or settings.root / 'reviewed-results/offline-evidence.json'
    if args.curate_existing:
        reviewed = json.loads(destination.read_text())
        reviewed['synthetic_edit_preview'] = ReferenceApp(settings).preview_text_edit(
            '2005.11401v4.pdf')
        print(json.dumps(curate(settings, reviewed, destination), indent=2))
        return
    if settings.state_root.exists() or settings.runs_root.exists():
        raise SystemExit('Offline evidence already exists; inspect it before rerunning')
    app = ReferenceApp(settings)
    provider = SimulatedProvider()
    first = app.ingest(provider)
    calls_after_first = provider.calls
    unchanged = app.ingest(provider)
    metadata = app.ingest(provider, metadata_tag='offline-review')
    omission = app.demonstrate_omission('2005.11401v4.pdf', 'page:2')
    answer = app.ask(provider, 'What two kinds of memory does RAG combine?')
    preview = app.preview_text_edit('2005.11401v4.pdf')
    if (first['planned_embeddings'] != 171 or unchanged['planned_embeddings'] != 0
            or metadata['planned_embeddings'] != 0 or provider.calls != calls_after_first + 1
            or not omission['guarded_index_preserved'] or not answer['retrieved']
            or preview['planned_embeddings'] != 2 or preview['paid_api_calls'] != 0):
        raise RuntimeError('Offline acceptance assertions failed')
    reviewed = {'schema_version': 2, 'proof_kind': 'offline_local_chroma_simulated_vectors',
        'paid_api_calls': 0, 'live_openai_embeddings_verified': False,
        'live_openai_generation_verified': False,
        'first_run_id': first['run_id'], 'unchanged_run_id': unchanged['run_id'],
        'metadata_run_id': metadata['run_id'], 'omission_run_id': omission['run_id'],
        'answer_run_id': answer['run_id'],
        'first_planned_embeddings': first['planned_embeddings'],
        'first_simulated_tokens': first['actual_embedding_tokens'],
        'unchanged_planned_embeddings': unchanged['planned_embeddings'],
        'metadata_planned_embeddings': metadata['planned_embeddings'],
        'naive_removed_page_ids': omission['naive_removed_ids'],
        'guarded_index_preserved': omission['guarded_index_preserved'],
        'simulated_question_returned_rows': len(answer['retrieved']),
        'synthetic_edit_preview': preview,
        'checks_unverified': ['real_openai_embedding_requests', 'real_openai_generation',
                              'retrieval_quality', 'answer_factuality']}
    print(json.dumps(curate(settings, reviewed, destination), indent=2))


if __name__ == '__main__':
    main()
