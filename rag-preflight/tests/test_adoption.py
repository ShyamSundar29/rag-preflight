from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from rag_preflight import (SQLiteSnapshotStore, plan_update, UnsafePlanError, DocumentSpec,
    receipt_from_callable, pypdf_receipt, assign_chunk_keys, from_langchain_documents,
    from_llama_index_nodes, audit_ingestion, audit_chunks, audit_unit_yield,
    audit_chunk_unit_yield, YieldPolicy, reconcile, WarningBaseline)
from test_review_fixes import document, shrink, snap


class BatchGuardTests(unittest.TestCase):
    def test_full_corpus_regression_and_path_parity(self):
        old = snap(*(document(str(i),20) for i in range(300)))
        new = snap(*(shrink(str(i),20,16) for i in range(300)))
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(old))
            for kwargs, message in [({'max_shrinking_documents':100}, 'Batch shrinking documents 300 exceeds limit 100'),
                 ({'max_removed_chunks':1000}, 'Batch removed chunks 1200 exceeds limit 1000')]:
                for make in (lambda: plan_update(old,new,**kwargs), lambda: store.plan(new,**kwargs)):
                    with self.assertRaises(UnsafePlanError) as caught:
                        make()
                    self.assertEqual(str(caught.exception), message)
            # Explicit independent budget changes permit this reviewed migration.
            self.assertEqual(len(store.plan(new,max_shrinking_documents=300,max_removed_chunks=1200,max_corpus_delete_fraction=.2).update.removed),1200)

    def test_single_edit_and_named_error_before_batch_error(self):
        old=snap(document('z',20),document('a',20),document('preserved',100))
        new=snap(shrink('z',20,10),shrink('a',20,10))
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(old))
            for make in (lambda: plan_update(old,new,max_removed_chunks=0),lambda: store.plan(new,max_removed_chunks=0)):
                with self.assertRaisesRegex(UnsafePlanError,'Per-document deletion fraction exceeds limit for a'):
                    make()
        self.assertEqual(len(plan_update(old,snap(shrink('a',20,16))).removed),4)

    def test_scoped_exceptions_leave_batch_protection(self):
        old=snap(document('retire',100),document('approved',20),document('ordinary',20))
        new=snap(shrink('approved',20,12),shrink('ordinary',20,16))
        options=dict(retire_documents=['retire'],allow_shrink={'approved':.8},max_removed_chunks=3)
        with self.assertRaisesRegex(UnsafePlanError,'Batch removed chunks 4'):
            plan_update(old,new,**options)
        options['max_removed_chunks']=4
        options['max_corpus_delete_fraction']=.2
        self.assertEqual(len(plan_update(old,new,**options).removed),112)

    def test_invalid_limits(self):
        for name in ('max_removed_chunks','max_shrinking_documents'):
            for value in (-1,True,1.2,'1'):
                with self.assertRaises(ValueError):
                    plan_update(None,snap(document()),**{name:value})


class ExtractionTests(unittest.TestCase):
    def test_success_blank_failure_and_continued_attempts(self):
        attempted=[]
        def extract(unit):
            attempted.append(unit)
            if unit=='bad': raise RuntimeError('secret')
            return None if unit=='blank' else 'content'
        spec=DocumentSpec('d','v',expected_units=('good','bad','blank','last'),allowed_empty_units=('blank',))
        result=receipt_from_callable(spec,extract)
        self.assertEqual(attempted,list(spec.expected_units))
        self.assertEqual(result.receipt.processed_units,('blank','good','last'))
        self.assertEqual(result.receipt.failed_units,('bad',))
        self.assertEqual(result.failures,(('bad','RuntimeError'),))
        self.assertFalse(audit_ingestion([spec],[result.receipt],result.chunks(source='d')).passed)

    def test_inventory_required_and_interrupt_propagates(self):
        with self.assertRaises(ValueError): receipt_from_callable(DocumentSpec('d','v'),lambda u:'x')
        def interrupt(unit): raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            receipt_from_callable(DocumentSpec('d','v',expected_units=('a',)),interrupt)

    def test_good_extraction_and_dropped_unit(self):
        spec=DocumentSpec('d','v',expected_units=('one','two'))
        result=receipt_from_callable(spec,lambda u:u+' text')
        chunks=result.chunks(source='test.md')
        self.assertTrue(audit_ingestion([spec],[result.receipt],chunks).passed)
        dropped=result.chunks(lambda text:[] if text.startswith('two') else [text],source='test.md')
        self.assertIn('missing_chunk_units',[i.code for i in audit_ingestion([spec],[result.receipt],dropped).findings])
        with self.assertRaises(TypeError): result.chunks(lambda t:t,source='x')

    def test_pdf_independent_page_inventory(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest('optional pypdf')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'blank.pdf'
            writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.add_blank_page(width=100,height=100)
            writer.write(str(path))
            result=pypdf_receipt(path,document_id='stable-id')
            self.assertEqual(result.document.expected_units,('page:1','page:2'))
            self.assertEqual(result.receipt.empty_units,('page:1','page:2'))
            self.assertEqual(len(result.document.source_version),64)
            self.assertFalse(audit_ingestion([result.document],[result.receipt],[]).passed)

    def test_keys_isolate_units_and_do_not_mutate(self):
        chunks=[{'text':'a','metadata':{'document_id':'d','units':['a']}},
                {'text':'b','metadata':{'document_id':'d','units':['b']}}]
        original=deepcopy(chunks);first=assign_chunk_keys(chunks)
        expanded=assign_chunk_keys([chunks[0],chunks[0],chunks[1]])
        self.assertEqual(first[1]['chunk_key'],expanded[2]['chunk_key'])
        self.assertEqual(chunks,original)
        self.assertEqual(len({c['chunk_key'] for c in expanded}),3)
        with self.assertRaises(ValueError): assign_chunk_keys(first)
        self.assertEqual(len(assign_chunk_keys([{'metadata':{'document_id':'d','units':['a','b']}}])),1)

    def test_converters_preserve_but_never_fabricate_metadata(self):
        for convert, attribute in [(from_langchain_documents,'page_content'),(from_llama_index_nodes,'text')]:
            obj=SimpleNamespace(**{attribute:'text','metadata':{'source':'s'}})
            records=convert([obj]);self.assertEqual(records,[{'text':'text','metadata':{'source':'s'}}])
            records[0]['metadata']['source']='changed';self.assertEqual(obj.metadata['source'],'s')
            with self.assertRaises(TypeError): convert([object()])


class QualityTests(unittest.TestCase):
    def test_length_stats_and_lexical_warning(self):
        chunks=[{'text':'common generic navigation','metadata':{}} for _ in range(5)]
        report=audit_chunks(chunks,required_metadata=(),min_chars=30,distinctive_term_fraction=.8)
        self.assertEqual(report.length_statistics['median'],25)
        self.assertEqual(sum(i.code=='short_chunk' for i in report.issues),5)
        self.assertEqual(sum(i.code=='low_distinctiveness' for i in report.issues),5)
        chunks[-1]['text']='uniquely specific scientific observation'
        report=audit_chunks(chunks,required_metadata=(),distinctive_term_fraction=.8)
        self.assertNotIn(4,[i.chunk_index for i in report.issues if i.code=='low_distinctiveness'])

    def test_yield_warning_and_honest_limit(self):
        texts={str(i):str(i)*3000 for i in range(6)};texts['0']='abc'
        report=audit_unit_yield({'d':texts})
        self.assertEqual([i.code for i in report.findings],['low_unit_text_yield'])
        self.assertEqual(audit_unit_yield({'d':{k:'abc' for k in texts}}).findings,())
        self.assertTrue(audit_unit_yield({'d':{k:'abc' for k in texts}}).checks_skipped)
        self.assertFalse(audit_unit_yield({'d':texts},policy=YieldPolicy(min_units=10)).checks_run)

    def test_ingestion_yield_and_ambiguous_units_skip(self):
        d,r,c=document('d',6)
        for i,chunk in enumerate(c): chunk['text']=str(i)*3000
        c[0]['text']='abc'
        self.assertIn('low_unit_text_yield',[i.code for i in audit_ingestion([d],[r],c).findings])
        c[0]['metadata']['units']=['section:0','section:1']
        report=audit_chunk_unit_yield(c)
        self.assertFalse(report.findings);self.assertIn('unit_text_yield:d:ambiguous',report.checks_skipped)


class OperatorTests(unittest.TestCase):
    def test_enumerate_verify_and_corrupt_unloaded_document(self):
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(snap(document('a'),document('b'))))
            self.assertEqual(store.document_ids(),('a','b'))
            self.assertEqual(len(list(store.chunk_ids())),8)
            self.assertTrue(store.verify().passed)
            store._db.execute("UPDATE documents SET chunk_count=999 WHERE document_id='b'")
            self.assertIsNotNone(store.load_documents(['a']))
            report=store.verify();self.assertFalse(report.passed)
            self.assertEqual(report.findings[0].document_id,'b')
            with self.assertRaises(ValueError): list(store.chunk_ids())

    def test_duplicate_json_and_revision_tampering(self):
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(snap(document())))
            blob=store._db.execute('SELECT snapshot FROM documents').fetchone()[0]
            store._db.execute('UPDATE documents SET snapshot=?',('{"schema_version":1,'+blob[1:],))
            self.assertFalse(store.verify().passed)
            value=json.loads(blob);value['revision']='0'*64
            store._db.execute('UPDATE documents SET snapshot=?',(json.dumps(value),))
            self.assertFalse(store.verify().passed)

    def test_reconcile_all_cases_and_bounded_samples(self):
        report=reconcile((str(i) for i in range(10)),['0','0','orphan'],namespace='n',inventory_complete=True,max_examples=2)
        self.assertEqual((report.missing_count,report.orphan_count,report.duplicate_observed_count),(9,1,1))
        self.assertEqual(len(report.missing_ids),2);self.assertFalse(report.passed)
        self.assertFalse(reconcile(['a'],['a'],namespace='n').passed)
        self.assertTrue(reconcile(['a'],['a'],namespace='n',inventory_complete=True).passed)
        self.assertTrue(reconcile([],[],namespace='n',inventory_complete=True).passed)
        with self.assertRaises(ValueError): reconcile([''],[],namespace='n')
        with self.assertRaises(TypeError): reconcile('a',[],namespace='n')

    def test_baseline_new_changed_resolved_and_errors(self):
        chunks=[{'text':'small','metadata':{'source':'s'}}]
        report=audit_chunks(chunks,min_chars=20)
        baseline=WarningBaseline.capture(report,chunks,scope='kb/quality-v1')
        self.assertTrue(baseline.compare(report,chunks,scope='kb/quality-v1').passed)
        changed=[{'text':'other','metadata':{'source':'s'}}]
        self.assertFalse(baseline.compare(audit_chunks(changed,min_chars=20),changed,scope='kb/quality-v1').passed)
        errors=[{'text':'','metadata':{}}]
        bad=audit_chunks(errors)
        captured=WarningBaseline.capture(bad,errors,scope='x')
        self.assertFalse(captured.compare(bad,errors,scope='x').passed)
        with self.assertRaises(ValueError): baseline.compare(report,chunks,scope='other')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'baseline.json';baseline.save(path)
            self.assertEqual(WarningBaseline.load(path),baseline)
            path.write_text('{"schema_version":1,"schema_version":1}')
            with self.assertRaises(ValueError): WarningBaseline.load(path)
        resolved=[{'text':'a sufficiently detailed description of this document','metadata':{'source':'s'}}]
        self.assertEqual(baseline.compare(audit_chunks(resolved,min_chars=20),resolved,scope='kb/quality-v1').resolved_warnings,1)
