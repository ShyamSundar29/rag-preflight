import copy
import math
import unittest
from rag_preflight import (AcceptancePolicy, DocumentSpec, ExtractionReceipt,
                          ValidationError, audit_ingestion, audit_embeddings)
from rag_preflight.ingestion import canonical_json


def doc(key='manual', version='v1', pages=(1, 2), **kwargs):
    return DocumentSpec(key, version, pages, **kwargs)


def receipt(key='manual', version='v1', pages=(1, 2), **kwargs):
    return ExtractionReceipt(key, version, pages, completed=kwargs.pop('completed', True), **kwargs)


def chunk(key='p1', text='First page', document='manual', version='v1', pages=None, **extra):
    return {'chunk_key': key, 'text': text, 'metadata': {
        'source': 'manual.pdf', 'document_id': document, 'source_version': version,
        'pages': [1] if pages is None else pages, **extra}}


def batch():
    return [chunk(), chunk('p2', 'Second page', pages=[2])]


class IngestionTests(unittest.TestCase):
    def codes(self, docs=None, receipts=None, chunks=None, **kwargs):
        result = audit_ingestion([doc()] if docs is None else docs,
                                 [receipt()] if receipts is None else receipts,
                                 batch() if chunks is None else chunks, **kwargs)
        return {f.code for f in result.findings}

    def test_valid_complete(self):
        records = batch()
        before = copy.deepcopy(records)
        report = audit_ingestion([doc()], [receipt()], records)
        self.assertTrue(report.passed)
        self.assertEqual(records, before)
        self.assertIn('token_limit', report.checks_skipped)

    def test_absent_document_detected(self):
        codes = self.codes(docs=[doc(), doc('absent')])
        self.assertTrue({'missing_receipt', 'missing_chunk_pages', 'insufficient_chunks'} <= codes)

    def test_missing_page_even_when_extractor_claims_complete(self):
        self.assertIn('missing_chunk_pages', self.codes(chunks=[chunk()]))

    def test_receipt_does_not_claim_processed_page(self):
        self.assertIn('processed_pages_mismatch', self.codes(receipts=[receipt(pages=(1,))]))

    def test_failed_and_unfinished_extraction(self):
        codes = self.codes(receipts=[receipt(pages=(1,), failed_pages=(2,), completed=False)])
        self.assertTrue({'failed_pages', 'extraction_incomplete'} <= codes)

    def test_version_mismatch(self):
        codes = self.codes(receipts=[receipt(version='v0')], chunks=[chunk(version='v0')])
        self.assertTrue({'receipt_version_mismatch', 'chunk_version_mismatch'} <= codes)

    def test_allowed_empty_page(self):
        self.assertEqual(self.codes(docs=[doc(allowed_empty_pages=(2,))], receipts=[receipt(empty_pages=(2,))], chunks=[chunk()]), set())

    def test_unapproved_empty_and_inconsistent_empty(self):
        self.assertIn('unapproved_empty_pages', self.codes(receipts=[receipt(empty_pages=(2,))], chunks=[chunk()]))
        self.assertIn('empty_page_has_chunks', self.codes(docs=[doc(allowed_empty_pages=(2,))], receipts=[receipt(empty_pages=(2,))]))
        self.assertIn('invalid_receipt_pages', self.codes(receipts=[receipt(pages=(1,), empty_pages=(2,))]))

    def test_duplicates_and_unexpected_inventory(self):
        self.assertIn('duplicate_document', self.codes(docs=[doc(), doc()]))
        self.assertIn('duplicate_receipt', self.codes(receipts=[receipt(), receipt()]))
        self.assertIn('unexpected_receipt', self.codes(receipts=[receipt('other')]))
        self.assertIn('unexpected_chunk_document', self.codes(chunks=[chunk(document='other')]))

    def test_bad_chunk_key_and_pages(self):
        for pages in [None, [], [0], [True], ['1'], [1, 1], '1']:
            record = chunk()
            record['metadata']['pages'] = pages
            with self.subTest(pages=pages):
                self.assertIn('invalid_chunk_pages', self.codes(chunks=[record]))
        self.assertIn('unexpected_chunk_page', self.codes(chunks=[chunk(pages=[3])]))
        self.assertIn('invalid_chunk_key', self.codes(chunks=[chunk(key=' ')]))
        self.assertIn('duplicate_chunk_key', self.codes(chunks=[chunk(), chunk()]))

    def test_empty_text_cannot_satisfy_coverage(self):
        codes = self.codes(chunks=[chunk(text=' '), chunk('p2', pages=[2])])
        self.assertIn('missing_chunk_pages', codes)

    def test_json_metadata_strict(self):
        for bad in [float('nan'), {1: 'bad'}, ('tuple',), object()]:
            with self.subTest(bad=bad):
                self.assertIn('invalid_json_metadata', self.codes(chunks=[chunk(extra=bad)]))
        self.assertEqual(canonical_json({'z': [1, True, None], 'a': 'é'}), canonical_json({'a': 'é', 'z': [1, True, None]}))

    def test_acceptance_policy(self):
        records = [chunk(), chunk('p2', text='First page', pages=[2])]
        report = audit_ingestion([doc()], [receipt()], records, policy=AcceptancePolicy(max_warnings=0))
        self.assertFalse(report.passed)
        self.assertEqual(report.errors, 0)
        with self.assertRaises(ValidationError) as context:
            report.raise_for_errors()
        self.assertIs(context.exception.report, report)
        self.assertIn('manual', report.by_document())
        self.assertFalse(report.to_dict()['passed'])

    def test_no_inventory_default_rejects(self):
        self.assertIn('empty_inventory', self.codes(docs=[], receipts=[], chunks=[]))
        self.assertTrue(audit_ingestion([], [], [], policy=AcceptancePolicy(require_documents=False)).passed)

    def test_invalid_configuration(self):
        for pages in [(), (0,), (True,), (1, 1)]:
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                doc(pages=pages)
        for kwargs in [dict(allowed_empty_pages=(3,)), dict(min_chunks=-1), dict(min_chunks=True)]:
            with self.assertRaises(ValueError):
                doc(**kwargs)
        for kwargs in [dict(required_metadata='source'), dict(max_warnings=-1), dict(max_warnings=True), dict(require_documents=1)]:
            with self.assertRaises(ValueError):
                AcceptancePolicy(**kwargs)
        with self.assertRaises(ValueError):
            receipt(completed='yes')
        with self.assertRaises(TypeError):
            audit_ingestion([{}], [], [])
        with self.assertRaises(TypeError):
            audit_ingestion([], [{}], [])

    def test_token_checks_integrated(self):
        self.assertIn('token_limit', self.codes(max_tokens=1, token_counter=lambda s: len(s.split())))


class EmbeddingTests(unittest.TestCase):
    def test_valid_keyed_order_independent(self):
        report = audit_embeddings(['a', 'b'], [{'chunk_id': 'b', 'vector': [1., 2.]}, {'chunk_id': 'a', 'vector': (0, 1)}], dimensions=2)
        self.assertTrue(report.passed)

    def test_missing_extra_duplicate(self):
        report = audit_embeddings(['a', 'b'], [{'chunk_id': key, 'vector': [1]} for key in ['a', 'a', 'c']], dimensions=1)
        self.assertEqual({f.code for f in report.findings}, {'missing_embedding', 'unexpected_embedding', 'duplicate_embedding'})

    def test_bad_numbers_and_shapes(self):
        cases = [([0, 0], 'zero_embedding'), ([1], 'embedding_dimensions'), ([math.nan, 1], 'nonfinite_embedding'), ([math.inf, 1], 'nonfinite_embedding'), ([True, 1], 'nonfinite_embedding'), (['1', 1], 'nonfinite_embedding'), ('12', 'invalid_vector'), (None, 'invalid_vector'), ([10**10000, 1], 'nonfinite_embedding')]
        for vector, expected in cases:
            with self.subTest(expected=expected):
                report = audit_embeddings(['a'], [{'chunk_id': 'a', 'vector': vector}], dimensions=2)
                self.assertIn(expected, {f.code for f in report.findings})

    def test_invalid_record(self):
        self.assertFalse(audit_embeddings(['a'], [None], dimensions=1).passed)

    def test_invalid_configuration(self):
        for dims in [0, True, 1.5]:
            with self.assertRaises(ValueError):
                audit_embeddings([], [], dimensions=dims)
        for ids in [['a', 'a'], 'a', [' ']]:
            with self.assertRaises(ValueError):
                audit_embeddings(ids, [], dimensions=1)

class CompletenessEdgeTests(unittest.TestCase):
    def test_wholly_blank_document_requires_explicit_permission(self):
        spec = doc(pages=(1,), allowed_empty_pages=(1,), min_chunks=0)
        report = audit_ingestion([spec], [receipt(pages=(1,), empty_pages=(1,))], [])
        self.assertTrue(report.passed)
        strict = doc(pages=(1,), allowed_empty_pages=(1,))
        self.assertFalse(audit_ingestion([strict], [receipt(pages=(1,), empty_pages=(1,))], []).passed)

    def test_page_crossing_chunk_covers_both_pages(self):
        self.assertTrue(audit_ingestion([doc()], [receipt()], [chunk(pages=[1,2])]).passed)

    def test_receipt_outside_inventory_is_rejected(self):
        self.assertFalse(audit_ingestion([doc()], [receipt(pages=(1,2,3), failed_pages=(4,))], batch()).passed)

    def test_malformed_documents_and_metadata_do_not_pass(self):
        for item in [None, {'metadata': None}, {'metadata': {'document_id': []}}, {'metadata': {'document_id': 'manual', 'pages': [1], 'source_version': 'v1'}}]:
            with self.subTest(item=item):
                self.assertFalse(audit_ingestion([doc()], [receipt()], [item]).passed)
