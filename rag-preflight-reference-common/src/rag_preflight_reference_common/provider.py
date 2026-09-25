"""OpenAI request boundary: real model calls and measured usage, no hidden retries."""
from dataclasses import dataclass
import hashlib
from typing import Protocol

from .config import Settings


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: tuple[tuple[float, ...], ...]
    actual_tokens: int
    request_id: str | None
    requested_model: str | None = None
    response_model: str | None = None


@dataclass(frozen=True)
class Answer:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    response_id: str | None
    requested_model: str | None = None
    response_model: str | None = None


class Provider(Protocol):
    def embed(self, inputs: list[str]) -> EmbeddingBatch: ...
    def answer(self, question: str, contexts: list[tuple[str, str]]) -> Answer: ...


class OpenAIProvider:
    def __init__(self, settings: Settings):
        from openai import OpenAI
        self.settings = settings
        # Retry attempts need explicit, independently logged evidence.
        self.client = OpenAI(max_retries=0, timeout=30.0)

    def embed(self, inputs: list[str]) -> EmbeddingBatch:
        if not inputs or any(not isinstance(value, str) or not value.strip() for value in inputs):
            raise ValueError('Embedding inputs must be nonempty strings')
        response = self.client.embeddings.create(model=self.settings.embedding_model,
                                                  input=inputs, encoding_format='float')
        data = sorted(response.data, key=lambda row: row.index)
        if [row.index for row in data] != list(range(len(inputs))):
            raise ValueError('OpenAI embedding response indices do not match inputs')
        vectors = tuple(tuple(float(x) for x in row.embedding) for row in data)
        actual = response.usage.total_tokens
        if type(actual) is not int or actual < 0:
            raise ValueError('OpenAI embedding usage is missing')
        response_model = getattr(response, 'model', None)
        if not isinstance(response_model, str) or not response_model:
            raise ValueError('OpenAI embedding response model is missing')
        return EmbeddingBatch(vectors, actual, getattr(response, '_request_id', None),
                              self.settings.embedding_model, response_model)

    def answer(self, question: str, contexts: list[tuple[str, str]]) -> Answer:
        if not contexts:
            raise ValueError('Generation requires retrieved context')
        if not self.settings.generation_model:
            raise ValueError('Choose an OpenAI generation model for the ask command')
        context = '\n\n'.join(f'[{label}] {text}' for label, text in contexts)
        response = self.client.responses.create(
            model=self.settings.generation_model, store=False,
            max_output_tokens=self.settings.max_output_tokens,
            instructions=('Answer only from the supplied research-paper passages. '
                          'Cite supporting passages as [1], [2], etc. '
                          'If evidence is insufficient, say you cannot answer from the papers. '
                          'Do not invent paper titles, page numbers or citations.'),
            input=f'Question: {question}\n\nPassages:\n{context}')
        if response.status != 'completed':
            details = getattr(response, 'incomplete_details', None)
            reason = getattr(details, 'reason', None)
            suffix = f' ({reason})' if isinstance(reason, str) and reason else ''
            raise ValueError(f'OpenAI generation did not complete: {response.status}{suffix}')
        usage = response.usage
        response_model = getattr(response, 'model', None)
        if not isinstance(response_model, str) or not response_model:
            raise ValueError('OpenAI generation response model is missing')
        return Answer(response.output_text,
                      None if usage is None else usage.input_tokens,
                      None if usage is None else usage.output_tokens,
                      response.id, self.settings.generation_model, response_model)


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()
