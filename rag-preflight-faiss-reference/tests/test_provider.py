"""Verify the OpenAI request boundary without spending API credits."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from rag_preflight_faiss_reference.config import Settings
from rag_preflight_faiss_reference.provider import OpenAIProvider


class FakeEmbeddings:
    def __init__(self):self.calls = []
    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(index=1, embedding=[2.0]),
                                     SimpleNamespace(index=0, embedding=[1.0])],
            usage=SimpleNamespace(total_tokens=7), _request_id='request-a')


class FakeResponses:
    def __init__(self):self.calls = []
    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text='A cited answer [1].', id='answer-a',
            status='completed',
            usage=SimpleNamespace(input_tokens=11, output_tokens=4))


class ProviderBoundaryTests(unittest.TestCase):
    def provider(self):
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.settings = replace(Settings.local(), generation_model='explicit-model')
        provider.client = SimpleNamespace(embeddings=FakeEmbeddings(),
                                          responses=FakeResponses())
        return provider

    def test_embedding_model_inputs_order_and_actual_usage(self):
        provider = self.provider()
        result = provider.embed(['first', 'second'])
        self.assertEqual(result.vectors, ((1.0,), (2.0,)))
        self.assertEqual(result.actual_tokens, 7)
        call = provider.client.embeddings.calls[0]
        self.assertEqual(call['model'], 'text-embedding-3-small')
        self.assertEqual(call['input'], ['first', 'second'])
        self.assertEqual(call['encoding_format'], 'float')

    def test_generation_requires_explicit_model_and_store_false(self):
        provider = self.provider()
        answer = provider.answer('question', [('1', 'context')])
        self.assertEqual((answer.input_tokens, answer.output_tokens), (11, 4))
        call = provider.client.responses.calls[0]
        self.assertEqual(call['model'], 'explicit-model')
        self.assertFalse(call['store'])
        self.assertEqual(call['max_output_tokens'], 300)
        provider.settings = replace(provider.settings, generation_model=None)
        with self.assertRaisesRegex(ValueError, 'Choose'):
            provider.answer('question', [('1', 'context')])

    def test_bad_embedding_indices_are_rejected(self):
        provider = self.provider()
        provider.client.embeddings.create = lambda **kwargs: SimpleNamespace(
            data=[SimpleNamespace(index=2, embedding=[1.0])],
            usage=SimpleNamespace(total_tokens=7))
        with self.assertRaisesRegex(ValueError, 'indices'):
            provider.embed(['first'])

    def test_incomplete_generation_is_not_accepted(self):
        provider = self.provider()
        provider.client.responses.create = lambda **kwargs: SimpleNamespace(
            status='incomplete', output_text='partial', usage=None)
        with self.assertRaisesRegex(ValueError, 'did not complete'):
            provider.answer('question', [('1', 'context')])
