from dataclasses import replace
import importlib
import tempfile
import unittest
from pathlib import Path
from rag_preflight import (DocumentSpec, ExtractionReceipt, AcceptancePolicy, Snapshot,
    audit_ingestion, build_snapshot, plan_update, UnsafePlanError, audit_embeddings,
    audit_plan_embeddings, SQLiteSnapshotStore)


def document(key='d', count=4, units=None, text_prefix='text'):
    expected = tuple(f'section:{i}' for i in range(count)) if units is None else tuple(units)
    d=DocumentSpec(key,'v1',expected_units=expected)
    r=ExtractionReceipt(key,'v1',processed_units=expected,completed=True)
    chunks=[{'chunk_key':str(i),'text':f'{text_prefix} {i}', 'metadata':{
        'document_id':key,'source_version':'v1','source':f'{key}.md','units':[unit]}}
        for i,unit in enumerate(expected)]
    return d,r,chunks


def snap(*items, **kwargs):
    docs,receipts,chunks=[],[],[]
    for d,r,c in items:
        docs.append(d);receipts.append(r);chunks.extend(c)
    return build_snapshot(docs,receipts,chunks,namespace=kwargs.get('namespace','n'),
        pipeline_id=kwargs.get('pipeline_id','p'),embedding_model=kwargs.get('embedding_model','m'),
        policy=AcceptancePolicy(require_documents=bool(items)))


def shrink(key, original, retained):
    d,r,c=document(key,original)
    c=c[:retained]
    # A legitimate revision consolidates the same source-unit coverage into fewer chunks.
    c[-1]['metadata']['units']=[f'section:{i}' for i in range(retained-1,original)]
    return d,r,c


class GuardFixTests(unittest.TestCase):
    def test_retire_one_of_two_and_eight(self):
        for n in (2,8):
            old=snap(*(document(str(i),1) for i in range(n)))
            current=snap(*(document(str(i),1) for i in range(n-1)))
            plan=plan_update(old,current,retire_documents=[str(n-1)])
            self.assertEqual(len(plan.removed),1)

    def test_retirement_does_not_authorize_other_deletion(self):
        old=snap(document('retired',100),document('keep',20))
        with self.assertRaises(UnsafePlanError):
            plan_update(old,snap(shrink('keep',20,12)),retire_documents=['retired'])

    def test_scoped_shrink_accepts_known_change(self):
        old=snap(document('handbook',20),document('other',20))
        current=snap(shrink('handbook',20,12),document('other',20))
        with self.assertRaises(UnsafePlanError):
            plan_update(old,current)
        plan=plan_update(old,current,allow_shrink={'handbook':0.4})
        self.assertEqual(len(plan.removed),8)
        self.assertEqual(plan.to_dict()['shrink_allowances'],{'handbook':0.4})

    def test_allowance_does_not_authorize_other_document(self):
        old=snap(document('a',20),document('b',20))
        with self.assertRaises(UnsafePlanError):
            plan_update(old,snap(shrink('a',20,12),shrink('b',20,12)),allow_shrink={'a':0.8})

    def test_invalid_allowances(self):
        old=snap(document())
        for allowances in [{'unknown':1}, {'d':True},{'d':float('nan')},{'d':-0.1},{'d':1.1}]:
            with self.subTest(allowances=allowances),self.assertRaises(ValueError):
                plan_update(old,old,allow_shrink=allowances)

    def test_main_module_import_is_safe(self):
        self.assertTrue(callable(importlib.import_module('rag_preflight.__main__').main))


class UnitTests(unittest.TestCase):
    def test_markdown_and_message_units(self):
        self.assertTrue(snap(document(units=('section:intro','message:456','row:7'))))

    def test_integer_canonicalization(self):
        d=DocumentSpec('d','v',expected_units=(1,'section:intro'))
        self.assertEqual(d.expected_units,('page:1','section:intro'))
        self.assertEqual(DocumentSpec('d','v',expected_units=(1,'1')).expected_units,('1','page:1'))
        with self.assertRaises(ValueError):
            DocumentSpec('d','v',expected_units=(1,'page:1'))

    def test_missing_unit(self):
        d,r,c=document()
        report=audit_ingestion([d],[r],c[:-1])
        self.assertIn('missing_chunk_units',{f.code for f in report.findings})

    def test_unknown_coverage_reports_skip_but_cannot_snapshot(self):
        d=DocumentSpec('d','v1')
        r=ExtractionReceipt('d','v1',completed=True)
        c=[{'chunk_key':'x','text':'hello','metadata':{'source':'a.md','document_id':'d','source_version':'v1'}}]
        report=audit_ingestion([d],[r],c)
        self.assertIn('completeness:d',report.checks_skipped)
        self.assertTrue(report.passed)
        with self.assertRaises(ValueError):
            build_snapshot([d],[r],c,namespace='n',pipeline_id='p',embedding_model='m')

    def test_known_empty_source(self):
        d=DocumentSpec('d','v1',expected_units=(),min_chunks=0)
        r=ExtractionReceipt('d','v1',processed_units=(),completed=True)
        self.assertTrue(audit_ingestion([d],[r],[]).passed)

    def test_reject_ambiguous_aliases(self):
        with self.assertRaises(ValueError):
            DocumentSpec('d','v',expected_pages=(1,),expected_units=('a',))
        with self.assertRaises(ValueError):
            ExtractionReceipt('d','v',processed_pages=(1,),processed_units=('a',))
        d,r,c=document()
        c[0]['metadata']['pages']=[1]
        self.assertFalse(audit_ingestion([d],[r],c).passed)

    def test_invalid_units(self):
        for units in [('',),(True,),(0,),({},),'section:one']:
            with self.subTest(units=units),self.assertRaises(ValueError):
                DocumentSpec('d','v',expected_units=units)

    def test_empty_unit_handling(self):
        d=DocumentSpec('d','v',expected_units=('intro','blank'),allowed_empty_units=('blank',))
        r=ExtractionReceipt('d','v',processed_units=('intro','blank'),empty_units=('blank',),completed=True)
        c=[{'chunk_key':'x','text':'intro','metadata':{'source':'a','document_id':'d','source_version':'v','units':['intro']}}]
        self.assertTrue(audit_ingestion([d],[r],c).passed)


class VectorFixTests(unittest.TestCase):
    def test_duplicate_and_norm_are_warnings(self):
        records=[{'chunk_id':k,'vector':[1.,0.]} for k in ['a','b']]
        report=audit_embeddings(['a','b'],records,dimensions=2,norm_range=(2,3))
        self.assertEqual(report.errors,0)
        self.assertEqual(report.warnings,3)
        self.assertFalse(audit_embeddings(['a','b'],records,dimensions=2,max_warnings=0).passed)

    def test_disable_duplicate_check(self):
        records=[{'chunk_id':k,'vector':[1.,0.]} for k in ['a','b']]
        self.assertEqual(audit_embeddings(['a','b'],records,dimensions=2,detect_duplicates=False).warnings,0)

    def test_signed_zero_equivalence(self):
        records=[{'chunk_id':'a','vector':[1.,-0.]},{'chunk_id':'b','vector':[1.,0.]}]
        self.assertEqual(audit_embeddings(['a','b'],records,dimensions=2).warnings,1)

    def test_plan_provenance_and_coverage(self):
        plan=plan_update(None,snap(document(count=2)))
        records=[{'chunk_id':c.chunk_id,'vector':[1.,i+1.],'embedding_model':'m','pipeline_id':'p','input_hash':c.text_hash} for i,c in enumerate(plan.target.chunks)]
        self.assertTrue(audit_plan_embeddings(plan,records,dimensions=2).passed)
        for field in ['embedding_model','pipeline_id','input_hash']:
            modified=[dict(r) for r in records];modified[0][field]='wrong'
            self.assertFalse(audit_plan_embeddings(plan,modified,dimensions=2).passed)
        self.assertFalse(audit_plan_embeddings(plan,records[:-1],dimensions=2).passed)
        self.assertFalse(audit_plan_embeddings(plan,records+records[:1],dimensions=2).passed)

    def test_upsert_mode_covers_metadata_only_changes(self):
        before=document(count=1);after=document(count=1);after[2][0]['metadata']['label']='staff'
        plan=plan_update(snap(before),snap(after))
        self.assertFalse(plan.embed_ids)
        self.assertTrue(audit_plan_embeddings(plan,[],dimensions=2).passed)
        self.assertFalse(audit_plan_embeddings(plan,[],dimensions=2,mode='upsert').passed)

    def test_numpy_parity(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest('Optional numpy not installed')
        records=[{'chunk_id':'a','vector':[1.,0.]},{'chunk_id':'b','vector':[1.,-0.]},
                 {'chunk_id':'c','vector':[0.,0.]},{'chunk_id':'d','vector':[float('nan'),1.]}]
        a=audit_embeddings(['a','b','c','d'],records,dimensions=2,norm_range=(.5,1.5))
        b=audit_embeddings(['a','b','c','d'],records,dimensions=2,norm_range=(.5,1.5),backend='numpy')
        self.assertEqual([(f.code,f.severity) for f in a.findings],[(f.code,f.severity) for f in b.findings])
        self.assertTrue(audit_embeddings(['x'],[{'chunk_id':'x','vector':np.array([1.,2.],dtype='float32')}],dimensions=2,backend='numpy').passed)
        self.assertFalse(audit_embeddings(['x'],[{'chunk_id':'x','vector':[True,1]}],dimensions=2,backend='numpy').passed)


class StoreTests(unittest.TestCase):
    def test_partial_plan_never_loads_other_blobs(self):
        with tempfile.TemporaryDirectory() as folder, SQLiteSnapshotStore(Path(folder)/'state.db') as store:
            store.commit(store.plan(snap(document('a'),document('b'))))
            # Corrupt an unrelated blob. Planning 'a' must not fetch or deserialize it.
            store._db.execute("UPDATE documents SET snapshot='not json' WHERE document_id='b'")
            plan=store.plan(snap(document('a',text_prefix='edited')))
            self.assertEqual({d.document_id for d in plan.update.target.documents},{'a'})
            store.commit(plan)
            self.assertEqual(store.counts(),{'documents':2,'chunks':8})

    def test_reopen_noop_and_retirement(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db'
            with SQLiteSnapshotStore(path) as store:
                rev=store.commit(store.plan(snap(document('a'),document('b'))))
            with SQLiteSnapshotStore(path) as store:
                self.assertEqual(store.revision,rev)
                self.assertEqual(store.commit(store.plan(snap(document('a')))),rev)
                store.commit(store.plan(snap(),retire_documents=['b']))
                self.assertEqual(store.counts(),{'documents':1,'chunks':4})

    def test_stale_writer_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db'
            with SQLiteSnapshotStore(path) as a, SQLiteSnapshotStore(path) as b:
                a.commit(a.plan(snap(document())))
                stale=b.plan(snap(document(text_prefix='B')))
                a.commit(a.plan(snap(document(text_prefix='A'))))
                with self.assertRaises(UnsafePlanError):
                    b.commit(stale)

    def test_partial_model_migration_rejected(self):
        with tempfile.TemporaryDirectory() as folder,SQLiteSnapshotStore(Path(folder)/'s.db') as store:
            store.commit(store.plan(snap(document('a'),document('b'))))
            with self.assertRaises(UnsafePlanError):
                store.plan(snap(document('a'),embedding_model='new'))
            store.commit(store.plan(snap(document('a'),document('b'),embedding_model='new')))
            self.assertEqual(store.load_documents(['b']).embedding_model,'new')

    def test_rollback_all_document_writes(self):
        with tempfile.TemporaryDirectory() as folder,SQLiteSnapshotStore(Path(folder)/'s.db') as store:
            import sqlite3
            original=snap(document('a'),document('b'))
            rev=store.commit(store.plan(original))
            store._db.execute("CREATE TRIGGER fail_b BEFORE UPDATE ON documents WHEN NEW.document_id='b' BEGIN SELECT RAISE(ABORT,'simulated disk failure'); END")
            plan=store.plan(snap(document('a',text_prefix='new'),document('b',text_prefix='new')))
            with self.assertRaises(sqlite3.DatabaseError):
                store.commit(plan)
            self.assertEqual(store.revision,rev)
            self.assertEqual(store.load_documents(['a','b']),original)

    def test_store_shrink_guard_equivalence(self):
        with tempfile.TemporaryDirectory() as folder,SQLiteSnapshotStore(Path(folder)/'s.db') as store:
            store.commit(store.plan(snap(document('a',20),document('b',20))))
            with self.assertRaises(UnsafePlanError):
                store.plan(snap(shrink('a',20,12)))
            store.commit(store.plan(snap(shrink('a',20,12)),allow_shrink={'a':.4}))
            self.assertEqual(store.counts()['chunks'],32)

class AdditionalReviewTests(unittest.TestCase):
    def test_canonical_manifest_export(self):
        legacy=DocumentSpec('pdf','v',expected_pages=(1,2),allowed_empty_pages=(2,))
        restored=DocumentSpec(**legacy.to_dict())
        self.assertEqual(restored.expected_units,legacy.expected_units)
        receipt=ExtractionReceipt('pdf','v',processed_pages=(1,2),empty_pages=(2,),completed=True)
        self.assertEqual(ExtractionReceipt(**receipt.to_dict()).processed_units,receipt.processed_units)

    def test_numpy_rejects_bool_in_generator(self):
        try:
            import numpy
        except ImportError:
            self.skipTest('Optional numpy not installed')
        result=audit_embeddings(['a'],[{'chunk_id':'a','vector':iter([True,1])}],dimensions=2,backend='numpy')
        self.assertFalse(result.passed)

    def test_norm_and_backend_configuration(self):
        for kwargs in [{'backend':'bad'}, {'norm_range':(-1,2)}, {'norm_range':(2,1)}, {'norm_range':(0,float('inf'))}, {'max_warnings':-1}]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                audit_embeddings([],[],dimensions=2,**kwargs)

    def test_store_schema_version_rejection(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'future.db'
            from contextlib import closing
            with closing(sqlite3.connect(path)) as db:
                db.execute('PRAGMA user_version=99')
            with self.assertRaises(ValueError):
                SQLiteSnapshotStore(path)
