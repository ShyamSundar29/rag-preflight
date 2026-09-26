"""Self-test the public adapter contract and restricted-network diagnostics."""
import errno
import multiprocessing
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from rag_preflight_reference_common import journal
from rag_preflight_reference_common.journal import writer_lock
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


def _acquire_in_child(root, started, acquired):
    started.set()
    with writer_lock(Path(root)):
        acquired.set()


class CommonContractTests(unittest.TestCase):
    def test_windows_lock_path_retries_contention_and_unlocks(self):
        calls = []
        attempts = 0
        def locking(file_number, mode, count):
            nonlocal attempts
            calls.append((file_number, mode, count))
            if mode == 1 and attempts == 0:
                attempts += 1
                raise OSError(errno.EACCES, 'busy')
        fake = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
        with tempfile.TemporaryFile('w+b') as stream, \
                mock.patch.object(journal, '_WINDOWS', True), \
                mock.patch.dict(sys.modules, {'msvcrt': fake}), \
                mock.patch.object(journal.time, 'sleep') as sleep:
            with journal._locked_stream(stream):
                self.assertEqual(stream.read(1), b'\0')
        self.assertEqual([mode for _, mode, _ in calls], [1, 1, 2])
        sleep.assert_called_once_with(0.05)

    def test_writer_lock_serializes_processes(self):
        context = multiprocessing.get_context('spawn')
        with tempfile.TemporaryDirectory() as folder, writer_lock(Path(folder)):
            started = context.Event()
            acquired = context.Event()
            process = context.Process(target=_acquire_in_child,
                                      args=(folder, started, acquired))
            process.start()
            try:
                self.assertTrue(started.wait(5))
                self.assertFalse(acquired.wait(0.3))
            except BaseException:
                if process.is_alive():
                    process.terminate()
                    process.join(5)
                raise
        try:
            self.assertTrue(acquired.wait(5))
            process.join(5)
            self.assertEqual(process.exitcode, 0)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(5)

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
