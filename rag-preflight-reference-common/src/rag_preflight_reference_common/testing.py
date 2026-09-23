"""Reusable behavioral contract for reference-application store adapters."""
from collections.abc import Callable
from typing import Any, cast

from .store import Payload, VectorStore, verify_payloads


def _require(condition: bool, message: str) -> None:
    """Raise even when Python runs with optimization and removes assert statements."""
    if not condition:
        raise AssertionError(message)


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
