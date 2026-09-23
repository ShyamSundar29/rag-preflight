"""Self-test the public adapter contract and restricted-network diagnostics."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rag_preflight_reference_common.store import Payload
from rag_preflight_reference_common.testing import assert_vector_store_contract
from rag_preflight_reference_common.tokenizer import (CL100K_CACHE_NAME,
    CL100K_SHA256, CL100K_URL, TokenizerUnavailableError, encoding_for_model)


class MemoryStore:
    def __init__(self, state):
        self.state = state
    def ids(self):
        return set(self.state)
    def get(self, chunk_ids):
        return {key: self.state[key] for key in chunk_ids if key in self.state}
    def upsert(self, payloads):
        self.state.update((row.chunk_id, row) for row in payloads)
    def delete(self, chunk_ids):
        for key in chunk_ids:
            self.state.pop(key, None)
    def query(self, vector, count=5):
        ranked = sorted(self.state.values(), key=lambda row:
            sum((left-right) ** 2 for left, right in zip(row.vector, vector)))[:count]
        return [dict(chunk_id=row.chunk_id, text=row.text, metadata=row.metadata,
                     distance=sum((left-right) ** 2 for left, right in zip(row.vector, vector)))
                for row in ranked]


class CommonContractTests(unittest.TestCase):
    def test_reusable_contract_checks_required_behavior(self):
        state: dict[str, Payload] = {}
        assert_vector_store_contract(lambda create: MemoryStore(state))

    def test_tokenizer_failure_explains_offline_cache(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch('rag_preflight_reference_common.tokenizer.tiktoken.encoding_for_model',
                           side_effect=RuntimeError('proxy details')):
            with self.assertRaises(TokenizerUnavailableError) as caught:
                encoding_for_model('text-embedding-3-small', cache_dir=folder)
        message = str(caught.exception)
        self.assertIn(CL100K_URL, message)
        self.assertIn(CL100K_SHA256, message)
        self.assertIn(str(Path(folder) / CL100K_CACHE_NAME), message)
        self.assertIn('TIKTOKEN_CACHE_DIR', message)
        self.assertNotIn('proxy details', message)
