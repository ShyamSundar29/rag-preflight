import copy
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import tempfile
import unittest
from rag_preflight import audit_chunks
from rag_preflight.cli import main


def record(text='Useful content', **metadata):
    return {'text': text, 'metadata': {'source': 'guide.pdf', **metadata}}


class AuditTests(unittest.TestCase):
    def test_clean_generator_and_no_mutation(self):
        records = [record(page=0), record('Other content', page=1)]
        before = copy.deepcopy(records)
        report = audit_chunks(iter(records), required_metadata=['source', 'page'])
        self.assertTrue(report.passed)
        self.assertEqual(report.issues, ())
        self.assertEqual(records, before)
        self.assertEqual(report.checks_skipped, ('short_chunk', 'low_distinctiveness', 'token_limit'))

    def test_empty_and_invalid_records(self):
        report = audit_chunks([None, {'text': 42}, record(' \n\t'), {'text': 'ok', 'metadata': []}])
        self.assertEqual({i.code for i in report.issues}, {'invalid_record', 'invalid_text', 'empty_text', 'invalid_metadata', 'missing_metadata'})
        self.assertFalse(report.passed)

    def test_metadata_missing_and_false_values(self):
        report = audit_chunks([record(page=0), record(page=False), record(page=' '), record(page=[]), record()], required_metadata=['page'])
        self.assertEqual([i.chunk_index for i in report.issues if i.code == 'missing_metadata'], [2, 3, 4])

    def test_duplicate_whitespace_but_not_case(self):
        report = audit_chunks([record('A B'), record(' A\n B '), record('a b')])
        duplicates = [i for i in report.issues if i.code == 'duplicate_text']
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].related_indices, (0,))
        self.assertTrue(report.passed)

    def test_exact_token_boundary(self):
        report = audit_chunks([record('one two'), record('one two three')], max_tokens=2, token_counter=lambda s: len(s.split()))
        self.assertEqual([i.chunk_index for i in report.issues], [1])
        self.assertEqual(report.checks_skipped, ('short_chunk', 'low_distinctiveness'))

    def test_bad_configuration(self):
        for kwargs in [dict(max_tokens=10), dict(token_counter=len), dict(max_tokens=0, token_counter=len), dict(required_metadata='source'), dict(boilerplate_ratio=0), dict(boilerplate_ratio=float('nan')), dict(boilerplate_min_chunks=1), dict(boilerplate_min_chars=True)]:
            with self.subTest(kwargs=kwargs), self.assertRaises((TypeError, ValueError)):
                audit_chunks([], **kwargs)
        for records in ['text', {'text': 'hi'}]:
            with self.assertRaises(TypeError):
                audit_chunks(records)

    def test_invalid_counter_output(self):
        for result in [True, -1, 1.2, '2']:
            with self.subTest(result=result), self.assertRaises(ValueError):
                audit_chunks([record()], max_tokens=2, token_counter=lambda s: result)

    def test_counter_failure(self):
        def broken(text):
            raise RuntimeError('broken')
        with self.assertRaisesRegex(ValueError, 'chunk 0'):
            audit_chunks([record()], max_tokens=2, token_counter=broken)

    def test_boilerplate(self):
        report = audit_chunks([record(f'Company handbook\nSection {i}\nPage footer text') for i in range(3)])
        warnings = [i for i in report.issues if i.code == 'repeated_boilerplate']
        self.assertEqual(len(warnings), 6)
        self.assertTrue(report.passed)
        self.assertNotIn('Company handbook', json.dumps(report.to_dict()))

    def test_boilerplate_counts_records_not_occurrences(self):
        report = audit_chunks([record('Repeated header\nbody\nRepeated header'), record('unique')])
        self.assertEqual(report.warnings, 0)

    def test_single_line_duplicates_are_not_boilerplate(self):
        report = audit_chunks([record('A repeated sentence') for _ in range(3)])
        self.assertEqual({i.code for i in report.issues}, {'duplicate_text'})

    def test_empty_dataset_is_explicit(self):
        report = audit_chunks([])
        self.assertEqual(report.total_chunks, 0)
        self.assertTrue(report.passed)
        self.assertEqual(json.loads(json.dumps(report.to_dict(detailed=True)))['issues'], [])

    def test_cli_json_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chunks.json'
            path.write_text(json.dumps([record(), record()]))
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main([str(path), '--json']), 0)
            self.assertEqual(json.loads(out.getvalue())['warnings'], 1)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(path), '--fail-on-warnings']), 1)
            path.write_text(json.dumps([record('')]))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(path)]), 1)
            path.write_text('{}')
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(path)]), 2)

    def test_cli_jsonl_and_bad_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chunks.jsonl'
            path.write_text(json.dumps(record()) + '\n\n')
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(path)]), 0)
            path.write_text('{bad')
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(path)]), 2)


if __name__ == '__main__':
    unittest.main()
