"""Regression checks for the unreleased scale and evidence workflows."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from rag_preflight import (audit_chunks, WarningBaseline, assign_chunk_keys, plan_update,
    UnsafePlanError, SQLiteSnapshotStore, estimate_embedding_cost, RunReceipt,
    audit_existing_index, audit_ingestion, AcceptancePolicy, build_snapshot, reconcile)
from test_review_fixes import document, shrink, snap


class AggregationTests(unittest.TestCase):
    def test_ten_thousand_exact_bounded_and_details(self):
        report = audit_chunks([{'text':'tiny','metadata':{'source':'s'}} for _ in range(10000)], min_chars=20)
        groups = {g['code']:g for g in report.by_code(max_examples=3)}
        self.assertEqual(groups['short_chunk']['occurrences'],10000)
        self.assertEqual(groups['duplicate_text']['occurrences'],9999)
        self.assertEqual(groups['duplicate_text']['affected_chunks'],10000)
        self.assertEqual(groups['short_chunk']['chunk_indices'],[0,1,2])
        self.assertEqual(report.warnings,19999)
        self.assertTrue(report.passed)
        self.assertNotIn('issues',report.to_dict())
        self.assertLess(len(json.dumps(report.to_dict())),1200)
        compact = json.dumps(report.to_dict(max_examples=3))
        smaller = audit_chunks([{'text':'tiny','metadata':{'source':'s'}} for _ in range(1000)],min_chars=20)
        self.assertLess(abs(len(compact)-len(json.dumps(smaller.to_dict(detailed=False,max_examples=3)))),30)
        self.assertEqual(len(report.to_dict(detailed=True)['issues']),19999)
        self.assertLess(len(compact),1200)
        self.assertEqual(len(report.metrics()['findings']),2)

    def test_same_code_severity_groups(self):
        r=audit_chunks([{'text':'x','metadata':{'source':'s'}}],min_chars=10)
        r=replace(r,issues=(*r.issues,replace(r.issues[0],severity='error')))
        self.assertEqual([(g['code'],g['severity'],g['occurrences']) for g in r.by_code()],
                         [('short_chunk','error',1),('short_chunk','warning',1)])
        self.assertFalse(r.passed)

    def test_severity_and_pass_fail(self):
        r=audit_chunks([{'text':''}, {'text':'x'}])
        self.assertFalse(r.passed)
        self.assertEqual(r.errors,3)
        self.assertEqual(r.to_dict(detailed=False)['errors'],3)
        with self.assertRaises(ValueError):r.by_code(max_examples=-1)


class CorpusPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old=snap(*(document(str(i),10) for i in range(5000)))

    def test_all_ten_percent_allowed(self):
        new=snap(*(shrink(str(i),10,9) for i in range(5000)))
        plan=plan_update(self.old,new)
        self.assertEqual(len(plan.removed),5000)
        self.assertEqual(dict(plan.deletion_policy)['ordinary_committed_chunks'],50000)
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(self.old))
            self.assertEqual(len(store.plan(new).update.removed),5000)

    def test_partial_payloads_and_full_denominator(self):
        new=snap(*(shrink(str(i),10,9) for i in range(150)))
        direct=plan_update(self.old,new)
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(self.old))
            original=store._decode_document
            with patch.object(store,'_decode_document', wraps=original) as decode:
                p=store.plan(new)
                self.assertEqual(decode.call_count,150)
            self.assertEqual(len(p.update.target.documents),150)
            self.assertEqual(p.update.removed,direct.removed)
            self.assertEqual(dict(p.update.deletion_policy),dict(direct.deletion_policy))
            store.commit(store.plan(snap(document('extra',10))))
            with self.assertRaises(UnsafePlanError):store.commit(p)

    def test_twenty_percent_blocked_and_parity(self):
        old=snap(*(document(str(i),20) for i in range(300)))
        new=snap(*(shrink(str(i),20,16) for i in range(300)))
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(old))
            errors=[]
            for f in (lambda:plan_update(old,new),lambda:store.plan(new)):
                with self.assertRaises(UnsafePlanError) as c:f()
                errors.append(str(c.exception))
            self.assertEqual(errors,['Corpus deletion fraction exceeds limit: 1200/6000']*2)

    def test_exempt_cannot_dilute_and_named_order(self):
        old=snap(document('huge',1000),document('a',10),document('z',10))
        new=snap(shrink('huge',1000,1),shrink('a',10,8),shrink('z',10,8))
        for options in (dict(allow_shrink={'huge':1}),):
            with self.assertRaisesRegex(UnsafePlanError,'4/20'):plan_update(old,new,**options)
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(old))
            with self.assertRaisesRegex(UnsafePlanError,'4/20'):
                store.plan(new,allow_shrink={'huge':1})
        new=snap(shrink('a',10,8),shrink('z',10,8))
        with self.assertRaisesRegex(UnsafePlanError,'4/20'):plan_update(old,new,retire_documents=['huge'])
        with self.assertRaisesRegex(UnsafePlanError,'for a'):
            plan_update(old,snap(shrink('z',10,5),shrink('a',10,5)),max_removed_chunks=0)

    def test_invalid_and_inclusive(self):
        for x in (-1,True,float('nan'),1.1):
            with self.assertRaises(ValueError):plan_update(None,snap(document()),max_corpus_delete_fraction=x)
        old=snap(document('a',20))
        self.assertEqual(len(plan_update(old,snap(shrink('a',20,17))).removed),3)


class TextBaselineTests(unittest.TestCase):
    def setUp(self):
        self.chunks=[{'chunk_key':'k','text':'short','metadata':{'document_id':'d','source':'s','label':'old'}}]
        self.report=audit_chunks(self.chunks,min_chars=20)

    def test_metadata_backfill_modes(self):
        changed=deepcopy(self.chunks);changed[0]['metadata']['label']='new'
        report=audit_chunks(changed,min_chars=20)
        for mode,expected in [('strict',0),('text',1)]:
            b=WarningBaseline.capture(self.report,self.chunks,scope='policy/v1',fingerprint_mode=mode)
            self.assertEqual(b.compare(report,changed,scope='policy/v1').accepted_warnings,expected)

    def test_text_identity_escalation_and_policy(self):
        b=WarningBaseline.capture(self.report,self.chunks,scope='v1',fingerprint_mode='text')
        changed=deepcopy(self.chunks);changed[0]['text']='edit'
        self.assertFalse(b.compare(audit_chunks(changed,min_chars=20),changed,scope='v1').passed)
        escalated=replace(self.report,issues=(replace(self.report.issues[0],severity='error'),))
        self.assertFalse(b.compare(escalated,self.chunks,scope='v1').passed)
        with self.assertRaises(ValueError):b.compare(self.report,self.chunks,scope='v2')
        with self.assertRaises(ValueError):b.compare(self.report,self.chunks,scope='v1',fingerprint_mode='strict')
        self.assertFalse(b.compare(audit_chunks(self.chunks,min_chars=30),self.chunks,scope='v1').passed)

    def test_occurrences_and_save_legacy(self):
        chunks=self.chunks*3;r=audit_chunks(chunks,min_chars=20)
        b=WarningBaseline.capture(r,chunks,scope='v1',fingerprint_mode='text')
        more=chunks+self.chunks;r2=audit_chunks(more,min_chars=20)
        c=b.compare(r2,more,scope='v1')
        self.assertEqual(c.accepted_warnings,5)
        self.assertEqual(c.report.warnings,2)
        self.assertEqual(c.metrics()['baseline_accepted_warnings'],5)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.json';b.save(p)
            self.assertEqual(b,WarningBaseline.load(p))
            strict=WarningBaseline.capture(self.report,self.chunks,scope='v1')
            p.write_text(json.dumps(dict(schema_version=1,scope='v1',fingerprints=list(strict.fingerprints))))
            loaded=WarningBaseline.load(p)
            self.assertEqual(loaded.fingerprint_mode,'strict')
            self.assertTrue(loaded.compare(self.report,self.chunks,scope='v1').passed)

    def test_safety_report_refused(self):
        d,r,c=document()
        with self.assertRaises(TypeError):WarningBaseline.capture(audit_ingestion([d],[r],c),c,scope='v1')


class KeyTests(unittest.TestCase):
    def test_multi_single_delimiters_order_and_aliases(self):
        def record(units):return {'text':'x','metadata':{'document_id':'d|,[]','units':units}}
        inputs=[record(['b|,[]','a']),record(['a','b|,[]']),record([1]),record(['page:1'])]
        before=deepcopy(inputs);out=assign_chunk_keys(inputs)
        self.assertEqual(inputs,before)
        self.assertEqual(json.loads(out[0]['chunk_key']),['d|,[]',['a','b|,[]'],0])
        self.assertEqual(json.loads(out[1]['chunk_key'])[-1],1)
        self.assertEqual(out[2]['chunk_key'],json.dumps(['d|,[]','page:1',0],separators=(',',':')))
        self.assertEqual(json.loads(out[3]['chunk_key'])[-1],1)
        pages=assign_chunk_keys([{'metadata':{'document_id':'d','pages':[2,1]}}])
        self.assertEqual(json.loads(pages[0]['chunk_key']),['d',['page:1','page:2'],0])
        with self.assertRaises(ValueError):assign_chunk_keys(out)


class CostTests(unittest.TestCase):
    def estimate(self,plan,**kwargs):
        return estimate_embedding_cost(plan,price_per_million_tokens='2',currency='USD',**kwargs)

    def test_first_edit_metadata_and_scope(self):
        item=document('d',4);old=snap(item);first=plan_update(None,old)
        counts={i:10 for i in first.embed_ids}
        est=self.estimate(first,token_counts=counts,comparison_ids=counts,comparison_scope='candidate batch d')
        self.assertEqual(est.tokens_to_embed,40);self.assertEqual(est.estimated_cost,Decimal('.00008'))
        self.assertEqual(est.avoided_cost,0)
        changed=deepcopy(item);changed[2][0]['text']='changed'
        plan=plan_update(old,snap(changed))
        est=self.estimate(plan,embedding_inputs={i:'prefix input text' for i in counts},tokenizer=lambda s:len(s.split()),
                          comparison_ids=counts,comparison_scope='candidate batch d')
        self.assertEqual(est.tokens_to_embed,3);self.assertEqual(est.comparison_tokens,12)
        self.assertEqual(est.avoided_cost,Decimal('.000018'))
        md=deepcopy(item);md[2][0]['metadata']['label']='backfill'
        plan=plan_update(old,snap(md))
        self.assertEqual(self.estimate(plan).tokens_to_embed,0)
        self.assertEqual(self.estimate(plan,token_counts=counts,comparison_ids=counts,comparison_scope='candidate batch d').avoided_cost,Decimal('.00008'))
        self.assertTrue(est.to_dict()['estimate'])

    def test_missing_and_invalid_evidence(self):
        plan=plan_update(None,snap(document()))
        with self.assertRaisesRegex(ValueError,'Missing actual'):self.estimate(plan)
        for price in (-1,True,float('nan'),'bad'):
            with self.assertRaises(ValueError):estimate_embedding_cost(plan,price_per_million_tokens=price,currency='USD')
        for count in (-1,True,1.5):
            with self.assertRaises(ValueError):self.estimate(plan,token_counts={plan.embed_ids[0]:count})
        with self.assertRaises(ValueError):self.estimate(plan,token_counts={},comparison_ids=plan.embed_ids)
        with self.assertRaises(ValueError):self.estimate(plan,token_counts={},comparison_ids=(),comparison_scope='batch')


    def test_tokenizer_and_currency_validation(self):
        plan=plan_update(None,snap(document()))
        inputs={i:'prefix text' for i in plan.embed_ids}
        for invalid in (-1, True, 1.2):
            with self.assertRaises(ValueError):self.estimate(plan,embedding_inputs=inputs,tokenizer=lambda text:invalid)
        with self.assertRaises(ValueError):estimate_embedding_cost(plan,price_per_million_tokens=0,currency='')
        with self.assertRaises(ValueError):self.estimate(plan,embedding_inputs=inputs)


class NamespaceMetricsTests(unittest.TestCase):
    def test_optional_matching_required_contradiction(self):
        d,r,c=document()
        self.assertTrue(audit_ingestion([d],[r],c,namespace='n').passed)
        policy=AcceptancePolicy(require_namespace=True)
        self.assertFalse(audit_ingestion([d],[r],c,namespace='n',policy=policy).passed)
        for item in c:item['metadata']['namespace']='n'
        self.assertTrue(audit_ingestion([d],[r],c,namespace='n',policy=policy).passed)
        c[0]['metadata']['namespace']='other'
        with self.assertRaises(ValueError):build_snapshot([d],[r],c,namespace='n',pipeline_id='p',embedding_model='m')
        with self.assertRaises(UnsafePlanError):plan_update(snap(document()),snap(document(),namespace='other'))
        with SQLiteSnapshotStore(':memory:') as store:
            store.commit(store.plan(snap(document())))
            with self.assertRaises(UnsafePlanError):store.plan(snap(document(),namespace='other'))

    def test_missing_units_measured_and_identifiers_excluded(self):
        d,r,c=document(count=4);report=audit_ingestion([d],[r],c[:1])
        self.assertEqual(report.metrics()['missing_units'],3)
        self.assertEqual(sum(f.code=='missing_chunk_units' for f in report.findings),1)
        encoded=json.dumps(report.metrics())
        self.assertNotIn('document_id',encoded);self.assertNotIn('chunk_key',encoded)
        plan=plan_update(None,snap(document()))
        self.assertEqual(plan.metrics()['planned_embeddings'],4)
        self.assertNotIn('completed_embeddings',plan.metrics())
        self.assertNotIn('namespace',reconcile(['a'],[],namespace='n').metrics())


class RunTests(unittest.TestCase):
    def complete(self,**kwargs):
        return RunReceipt('run',('a','b'),enumeration_completed=True,pagination_completed=True,
                          consistent_snapshot=True,scope='complete',**kwargs)

    def test_downstream_failure_independent_inventory(self):
        receipt=self.complete(processed_ids=('a',),failed_ids=('b',))
        self.assertFalse(receipt.audit().passed)
        self.assertEqual(receipt.audit().metrics()['records_enumerated'],2)
        self.assertFalse(receipt.deletion_eligible)

    def test_pagination_interruption_duplicates_changes(self):
        r=self.complete(processed_ids=('a','b'))
        self.assertTrue(r.deletion_eligible)
        for broken in (replace(r,pagination_completed=False),replace(r,enumeration_completed=False),
                       replace(r,enumerated_ids=('a','a','b')),replace(r,start_watermark='1',end_watermark='2'),
                       replace(r,processed_ids=('a',)),replace(r,processed_ids=('a','b','unknown'))):
            self.assertFalse(broken.audit().passed)
            self.assertFalse(broken.deletion_eligible)

    def test_incremental_unseen_preserved_and_bounded(self):
        r=self.complete(processed_ids=('a','b'))
        for scope in ('incremental','bounded'):
            partial=replace(r,scope=scope)
            self.assertIn('whole_corpus_completeness',partial.audit().checks_unverified)
            self.assertFalse(partial.deletion_eligible)
        old=snap(document('a'),document('b'),document('unseen'))
        self.assertIn('unseen',plan_update(old,snap(document('a'))).preserved_documents)


class ExistingIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'sources';self.root.mkdir()
        self.export=Path(self.temp.name)/'export.jsonl'

    def write(self,records):self.export.write_text('\n'.join(json.dumps(r) for r in records),encoding='utf-8')
    def audit(self,**kwargs):
        return audit_existing_index(self.root,self.export,export_complete=True,source_scope_complete=True,
                                    unit_metadata_complete=True,**kwargs)
    def codes(self,r):return {g['code']:g['occurrences'] for g in r.groups}

    def test_absent_orphan_hash_and_empty(self):
        (self.root/'a.txt').write_text('source a');(self.root/'b.md').write_text('source b')
        self.write([dict(id='1',source_id='a.txt',units=['file'],text='',
                         source_fingerprint=dict(algorithm='sha256',basis='file_bytes',value='0'*64)),
                    dict(id='2',source_id='gone.txt',units=['file'],text='old')])
        report=self.audit();codes=self.codes(report)
        self.assertEqual(codes['source_not_indexed'],1)
        self.assertEqual(codes['indexed_source_orphan'],1)
        self.assertEqual(codes['source_hash_mismatch'],1)
        self.assertEqual(codes['empty_indexed_text'],1)
        self.assertEqual(report.metrics()['missing_units'],2)
        self.assertFalse(report.passed)

    def test_duplicate_filenames_are_paths(self):
        for folder in ('x','y'):
            (self.root/folder).mkdir();(self.root/folder/'same.txt').write_text('text')
        self.write([dict(id='1',source_id='x/same.txt',units=['file'],text='text')])
        r=self.audit()
        g=next(g for g in r.groups if g['code']=='source_not_indexed')
        self.assertEqual(g['examples'],['y/same.txt'])

    def test_missing_evidence_is_unverified(self):
        (self.root/'a.txt').write_text('text');self.write([dict(id='1')])
        r=self.audit()
        for check in ('source_mapping','source_absence','unit_representation','source_version_comparison','indexed_text_nonempty'):
            self.assertIn(check,r.checks_unverified)
        self.assertNotIn('source_not_indexed',self.codes(r))
        self.assertIn('full_unit_content_searchability',r.checks_unverified)
        self.write([dict(id='1',source_id='a.txt',units=['file'],source_fingerprint={'algorithm':'version','value':'today'})])
        self.assertIn('source_version_comparison',self.audit().checks_unverified)

    def test_partial_and_enumeration_read_failures(self):
        (self.root/'a.txt').write_text('text');self.write([])
        r=audit_existing_index(self.root,self.export,source_scope_complete=True)
        self.assertNotIn('source_not_indexed',self.codes(r))
        real_walk=os.walk
        def failing_walk(*args,**kwargs):
            if Path(args[0]).resolve() == self.root.resolve():
                kwargs['onerror'](PermissionError('failure'))
                return iter(())
            return real_walk(*args,**kwargs)
        with patch('rag_preflight.existing.os.walk',side_effect=failing_walk):
            r=self.audit()
        self.assertIn('source_enumeration_failed',self.codes(r))
        self.assertIn('index_orphans',r.checks_unverified)
        (self.root/'bad.txt').write_bytes(b'\xff')
        self.assertIn('source_read_failed',self.codes(self.audit()))

    def test_malformed_duplicates_conflicting_versions(self):
        (self.root/'a.txt').write_text('text')
        record=dict(id='1',source_id='a.txt',units=['file'],text='text',
                    source_fingerprint=dict(algorithm='sha256',basis='file_bytes',value='0'*64))
        other=deepcopy(record);other['id']='2';other['source_fingerprint']['value']='1'*64
        conflict=deepcopy(record);conflict['text']='different'
        self.write([record,record,conflict,other,{},dict(id='3',source_id='../outside.txt')])
        r=self.audit();c=self.codes(r)
        self.assertEqual(c['duplicate_index_record'],1);self.assertEqual(c['conflicting_index_record'],1)
        self.assertEqual(c['conflicting_source_versions'],1);self.assertEqual(c['malformed_index_record'],2)
        self.assertIn('source_absence',r.checks_unverified)

    def test_symlink_not_followed(self):
        outside=Path(self.temp.name)/'outside.txt';outside.write_text('secret')
        (self.root/'link.txt').symlink_to(outside);self.write([])
        r=self.audit();self.assertIn('source_path_excluded',self.codes(r))
        self.assertEqual(r.measurements['documents_audited'],0)

    @unittest.skipUnless(importlib.util.find_spec('pypdf'),'optional PDF')
    def test_missing_page_coverage(self):
        from pypdf import PdfWriter
        writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.add_blank_page(width=100,height=100)
        with (self.root/'a.pdf').open('wb') as f:writer.write(f)
        self.write([dict(id='1',source_id='a.pdf',units=[1],text='indexed page one')])
        r=self.audit();self.assertEqual(r.measurements['missing_units'],1)
        self.assertEqual(next(g for g in r.groups if g['code']=='missing_indexed_unit')['examples'],[{'source':'a.pdf','unit':'page:2'}])

    def test_declared_versions_conflict_without_hash_proof(self):
        (self.root/'a.txt').write_text('text')
        self.write([dict(id=str(i),source_id='a.txt',units=['file'],text='text',source_version=v)
                    for i,v in enumerate(('v1','v2'))])
        r=self.audit()
        self.assertIn('conflicting_source_versions',self.codes(r))
        self.assertNotIn('source_hash_mismatch',self.codes(r))
        self.assertIn('source_version_comparison',r.checks_unverified)

    def test_export_read_and_json_errors(self):
        (self.root/'a.txt').write_text('text')
        self.export.write_text('{"id":"1","id":"2"}\nnot-json\n')
        r=self.audit();self.assertEqual(self.codes(r)['malformed_index_record'],2)
        self.export.unlink()
        r=self.audit();self.assertIn('index_export_read_failed',self.codes(r))
        self.assertIn('source_absence',r.checks_unverified)

    def test_bounded_examples_and_metrics(self):
        (self.root/'a.txt').write_text('text')
        self.write([dict(id=str(i),source_id='a.txt',units=['file'],text='') for i in range(10000)])
        r=self.audit(max_examples=2)
        group=next(g for g in r.groups if g['code']=='empty_indexed_text')
        self.assertEqual(group['occurrences'],10000)
        self.assertEqual(len(group['examples']),2)
        self.assertLess(len(json.dumps(r.to_dict())),1800)
        self.assertNotIn('a.txt',json.dumps(r.metrics()))
