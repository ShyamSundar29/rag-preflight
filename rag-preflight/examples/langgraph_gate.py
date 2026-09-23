"""Install langgraph. Validation routes to an embedding hook or halt, without network calls."""
from typing import Any, TypedDict
from langgraph.graph import StateGraph, START, END
from rag_preflight import DocumentSpec, receipt_from_callable, audit_ingestion

class State(TypedDict, total=False):
    documents: list[Any]
    receipts: list[Any]
    chunks: list[dict[str, Any]]
    report: dict[str, Any]
    status: str


def validate(state: State) -> dict[str, Any]:
    report = audit_ingestion(state['documents'], state['receipts'], state['chunks'])
    return {'report': report.to_dict()}


def route(state: State) -> str:
    return 'embed' if state['report']['passed'] else 'halt'


def embedding_hook(state: State) -> dict[str, str]:
    # Build a guarded plan before calling your real provider. Then validate vectors.
    return {'status': 'ready_for_guarded_planning'}


def halt(state: State) -> dict[str, str]:
    return {'status': 'validation_rejected'}


def make_graph():
    builder = StateGraph(State)
    builder.add_node('validate', validate)
    builder.add_node('embed', embedding_hook)
    builder.add_node('halt', halt)
    builder.add_edge(START, 'validate')
    builder.add_conditional_edges('validate', route, {'embed': 'embed', 'halt': 'halt'})
    builder.add_edge('embed', END)
    builder.add_edge('halt', END)
    return builder.compile()


if __name__ == '__main__':
    doc = DocumentSpec('d', 'v', expected_units=('intro',))
    extracted = receipt_from_callable(doc, lambda unit: 'A complete introduction.')
    state: State = {'documents': [doc], 'receipts': [extracted.receipt],
                    'chunks': extracted.chunks(source='example.md')}
    graph = make_graph()
    assert graph.invoke(state)['status'] == 'ready_for_guarded_planning'
    state['chunks'] = []
    assert graph.invoke(state)['status'] == 'validation_rejected'
    print('Both validation branches verified.')
