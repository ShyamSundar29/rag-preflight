"""Reusable behavioral contract for reference-application store adapters."""
from collections.abc import Callable
from typing import Any, cast

from .store import Payload, VectorStore, verify_payloads


_REVIEW_STATES = {'reviewed', 'unreviewed', 'not_applicable'}


def _require(condition: bool, message: str) -> None:
    """Raise even when Python runs with optimization and removes assert statements."""
    if not condition:
        raise AssertionError(message)


def summarize_human_review(evidence: dict[str, Any]) -> dict[str, Any]:
    """Derive the review summary for schema-3 curated live evidence.

    Review state remains attached to the claim it describes. This derived
    summary prevents a broad top-level boolean from contradicting a reviewed
    scenario while other scenarios are still unreviewed.
    """
    scenarios: dict[str, list[str]] = {
        'four_question_set': [
            status
            for question in evidence['questions']
            for status in question['review_status'].values()
        ],
        'page_2_omission_comparison': list(
            evidence['omission_comparison']['review_status'].values()),
        'unique_fact_omission_comparison': [
            *evidence['unique_fact_omission_comparison']['review_status'].values(),
            *evidence['unique_fact_omission_comparison']['guarded'][
                'review_status'].values(),
            *evidence['unique_fact_omission_comparison']['damaged_clone'][
                'review_status'].values(),
        ],
    }
    _require(all(status in _REVIEW_STATES for values in scenarios.values()
                 for status in values), 'unknown human-review status')

    def summarize(values: list[str]) -> dict[str, Any]:
        counts = {name: values.count(name) for name in sorted(_REVIEW_STATES)}
        reviewable = counts['reviewed'] + counts['unreviewed']
        if reviewable == 0:
            status = 'not_applicable'
        elif counts['unreviewed'] == 0:
            status = 'reviewed'
        elif counts['reviewed'] == 0:
            status = 'unreviewed'
        else:
            status = 'partial'
        return {'status': status, 'reviewed_checks': counts['reviewed'],
                'unreviewed_checks': counts['unreviewed'],
                'not_applicable_checks': counts['not_applicable']}

    by_scenario = {name: summarize(values) for name, values in scenarios.items()}
    totals = summarize([status for values in scenarios.values() for status in values])
    return {**totals, 'scenarios': by_scenario}


def assert_vector_store_contract(factory: Callable[[bool], VectorStore]) -> None:
    """Exercise the semantics required by the shared reference workflow.

    ``factory(create)`` must open the same isolated store each time. Passing
    ``False`` must reopen existing durable state rather than create it. The
    fixture uses three-dimensional vectors so adapter-specific settings must
    select dimension 3. Assertion failures name the violated behavior.
    """
    store = factory(True)
    _require(store.ids() == set(), 'new store must have an empty complete ID inventory')
    _require(store.get(()) == {}, 'empty read must return an empty mapping')
    first = Payload('first', 'first text', {'source_id': 'first'}, (1.0, 0.0, 0.0))
    second = Payload('second', 'second text', {'source_id': 'second'}, (0.0, 1.0, 0.0))
    store.upsert([first, second])
    _require(store.ids() == {'first', 'second'},
             'upserted IDs must be completely enumerable')
    _require(store.get(['first', 'missing']) == {'first': first},
             'reads must omit unknown IDs')
    _require(bool(verify_payloads(store, {'first': first, 'second': second},
                                  complete_ids={'first', 'second'})['passed']),
             'payload read-back failed')
    hits = store.query((0.9, 0.1, 0.0), count=1)
    _require(len(hits) == 1 and hits[0].get('chunk_id') == 'first',
             'nearest query result is wrong')
    required = {'chunk_id', 'text', 'metadata', 'distance'}
    _require(required <= set(hits[0]), 'query result lacks required fields')
    replacement = Payload('first', 'revised text', {'source_id': 'first', 'revision': 2},
                          (0.8, 0.2, 0.0))
    store.upsert([replacement])
    raw_replaced = store.get(['first']).get('first')
    _require(raw_replaced is not None, 'replacement payload must remain readable')
    replaced = cast(Payload, raw_replaced)
    _require((replaced.text, replaced.metadata) == (replacement.text, replacement.metadata),
             'upsert must replace text and metadata')
    _require(bool(verify_payloads(store, {'first': replacement})['passed']),
             'upsert must replace the vector within read-back tolerance')
    store.delete(['second', 'unknown'])
    _require(store.ids() == {'first'}, 'delete must remove named IDs and tolerate unknown IDs')
    reopened = factory(False)
    _require(reopened.ids() == {'first'}, 'reopen must preserve the complete ID inventory')
    final: dict[str, Any] = verify_payloads(reopened, {'first': replacement},
                                            complete_ids={'first'})
    _require(bool(final['passed']), f'reopened payload verification failed: {final}')
