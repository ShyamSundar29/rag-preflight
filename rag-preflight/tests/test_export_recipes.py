"""Execute the shipped documentation blocks against simulated read clients."""
import json
from pathlib import Path
import re
from types import SimpleNamespace
import tempfile
import unittest


class ExportRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / 'docs/export-recipes.md'
        cls.namespace = {}
        for block in re.findall(r"```python\n(.*?)```", source.read_text(), re.S):
            exec(compile(block, str(source), 'exec'), cls.namespace)

    def test_chroma_pagination_and_missing_evidence(self):
        class Collection:
            def get(self, **args):
                assert args['include'] == ['documents', 'metadatas']
                return ({'ids': ['a'], 'metadatas': [None], 'documents': ['']}
                        if args['offset'] == 0 else {'ids': []})
        rows = list(self.namespace['chroma_records'](Collection()))
        self.assertEqual(rows, [{'id': 'a', 'text': ''}])
        class Broken:
            def get(self, **args):
                return {'ids': ['a'], 'metadatas': [], 'documents': [None]}
        with self.assertRaises(ValueError):list(self.namespace['chroma_records'](Broken()))

    def test_qdrant_follows_short_page_offset(self):
        calls = []
        class Client:
            def scroll(self, **args):
                calls.append(args['offset'])
                assert not args['with_vectors']
                return ([SimpleNamespace(id=str(len(calls)), payload={'source_id': 'a.txt'})],
                        99 if args['offset'] is None else None)
        rows = list(self.namespace['qdrant_records'](Client(), 'c'))
        self.assertEqual(calls, [None, 99])
        self.assertEqual(len(rows), 2)

    def test_pinecone_fetch_batches_and_missing_ids(self):
        calls = []
        class Index:
            def list(self, **args):
                assert args['namespace'] == 'n'
                yield [str(i) for i in range(501)]
            def fetch(self, **args):
                calls.append(len(args['ids']))
                return SimpleNamespace(vectors={i: SimpleNamespace(metadata={}) for i in args['ids']})
        self.assertEqual(len(list(self.namespace['pinecone_records'](Index(), 'n'))), 501)
        self.assertEqual(calls, [500, 1])
        class Broken(Index):
            def fetch(self, **args):return SimpleNamespace(vectors={})
        with self.assertRaises(ValueError):list(self.namespace['pinecone_records'](Broken(), 'n'))

    def test_postgres_transaction_and_streaming_cursor(self):
        calls = []
        class Cursor:
            def __enter__(self):return self
            def __exit__(self, *args):pass
            def execute(self, sql):calls.append(sql)
            def __iter__(self):return iter([('a', {'source_id': 'a.txt'}, 'text')])
        class Connection:
            def transaction(self):return Cursor()
            def execute(self, sql):calls.append(sql)
            def cursor(self, **args):
                self.cursor_instance = Cursor()
                return self.cursor_instance
        connection = Connection()
        rows = list(self.namespace['pgvector_records'](connection))
        self.assertEqual(connection.cursor_instance.itersize, 500)
        self.assertIn('REPEATABLE READ, READ ONLY', calls[0])
        self.assertEqual(rows[0]['text'], 'text')

    def test_writer_does_not_publish_failed_export(self):
        def broken():
            yield {'id': 'a'}
            raise RuntimeError('pagination failed')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'export.jsonl'
            path.write_text('original')
            with self.assertRaises(RuntimeError):self.namespace['write_export'](broken(), path)
            self.assertEqual(path.read_text(), 'original')
            self.assertEqual(list(Path(folder).iterdir()), [path])
            self.namespace['write_export']([{'id': 'b'}], path)
            self.assertEqual(json.loads(path.read_text()), {'id': 'b'})

    def test_mapping_keeps_provenance_and_unknowns(self):
        row = self.namespace['record']('a', {'source_id': 'nested/a.pdf',
              'units_json': '["page:1","page:2"]', 'source_sha256': 'a' * 64})
        self.assertEqual(row['units'], ['page:1', 'page:2'])
        self.assertEqual(row['source_fingerprint']['basis'], 'file_bytes')
        self.assertNotIn('text', row)
        self.assertEqual(self.namespace['record']('b', None), {'id': 'b'})
