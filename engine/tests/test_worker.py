from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
from job_research_engine.store import Store
from job_research_engine.model import EngineError,Job,Page
from job_research_engine.transport import Response,FetchError
from job_research_engine.worker import collect
from job_research_engine.cli import main
from test_engine import Clock,sample,T1

class FakeTransport:
    evidence_origin='fixture'
    def __init__(self,handler):self.handler=handler;self.calls=[]
    def get(self,url,secret_query=None):
        self.calls.append(url);return self.handler(url,secret_query)
    def permitted_by_robots(self,url):return True

class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.sqlite';self.clock=Clock();self.s=Store(self.path,clock=self.clock)
        self.s.set_profile('p',{})
        self.s.import_companies('fixture',[{'external_id':'1','name':'Synthetic'}],source_url='https://registry.example/x',raw_sha256='f'*64,scope='synthetic',provenance='fixture')
        self.cid=self.s.db.execute('SELECT id FROM companies').fetchone()[0]
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def src(self,kind='greenhouse',url='https://boards-api.greenhouse.io/v1/boards/synthetic/jobs',policy='public_api'):
        return self.s.add_source(kind,url,company_id=self.cid,evidence_ref='synthetic fixture',policy=policy,settings={'employer':'Synthetic'})
    def runid(self):return self.s.plan_run('p',scope_note='synthetic worker test')
    def test_worker_collects_real_parser_and_database(self):
        self.src();r=self.runid()
        transport=FakeTransport(lambda u,k:Response(u,200,{'content-type':'application/json'},json.dumps({'jobs':[{'id':1,'title':'PM','absolute_url':'https://jobs.example/1','content':'Planning'}],'meta':{'total':1}}).encode()))
        result=collect(self.s,r,transport=transport)
        self.assertEqual(result['pages_committed'],1);self.assertEqual(result['coverage']['unique_source_jobs'],1)
        self.assertEqual(result['coverage']['production_observations'],0)
    def test_all_pages_processed_not_first_page_only(self):
        self.src('work24','https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L01.do');r=self.runid()
        def respond(url,key):
            n=int(parse_qs(urlsplit(url).query)['startPage'][0])
            body=f'<wantedRoot><total>3</total><startPage>{n}</startPage><display>1</display><wanted><wantedAuthNo>{n}</wantedAuthNo><company>C</company><title>PM</title><wantedInfoUrl>https://jobs.example/{n}</wantedInfoUrl></wanted></wantedRoot>'.encode()
            return Response(url,200,{},body)
        transport=FakeTransport(respond)
        with patch.dict('os.environ',{'WORK24_API_KEY':'synthetic-not-a-real-key'}):out=collect(self.s,r,transport=transport)
        self.assertEqual(len(transport.calls),3);self.assertEqual(out['coverage']['unique_source_jobs'],3)
    def test_missing_api_key_does_not_report_empty(self):
        self.src('work24','https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L01.do');r=self.runid()
        with patch.dict('os.environ',{},clear=True):out=collect(self.s,r,transport=FakeTransport(lambda *a:None))
        self.assertEqual(out['coverage']['status'],'partial');self.assertEqual(out['blocked_or_failed_attempts'],1)
        self.assertTrue(any(g.get('reason')=='missing_credential' for g in out['coverage']['material_gaps']))
    def test_failed_source_does_not_stop_other_sources(self):
        self.src();self.src('greenhouse','https://boards-api.greenhouse.io/v1/boards/other/jobs');r=self.runid()
        def handler(url,key):
            if '/synthetic/' in url:raise FetchError('denied','test')
            return Response(url,200,{},b'{"jobs":[],"meta":{"total":0}}')
        result=collect(self.s,r,transport=FakeTransport(handler))
        self.assertEqual(result['pages_committed'],1);self.assertEqual(result['blocked_or_failed_attempts'],1)
    def test_budget_checkpoint_not_complete(self):
        self.src();r=self.runid();result=collect(self.s,r,transport=FakeTransport(lambda *a:None),budget_seconds=0)
        self.assertEqual(result['stop_reason'],'execution_budget_checkpoint');self.assertEqual(result['coverage']['sources_exhausted'],0)
    def test_429_task_is_delayed(self):
        self.src();r=self.runid()
        def f(*args):raise FetchError('rate_limited','test',120)
        result=collect(self.s,r,transport=FakeTransport(f))
        task=self.s.db.execute('SELECT * FROM tasks WHERE run_id=?',(r,)).fetchone()
        self.assertEqual(task['status'],'queued');self.assertGreater(task['not_before'],self.s._now())
        self.assertEqual(result['pages_committed'],0)
    def test_host_only_source_remains_visible(self):
        self.src('host-json','https://jobs.example/list','host_only');r=self.runid();collect(self.s,r,transport=FakeTransport(lambda *a:None))
        self.assertEqual(len(self.s.review_packet(r)['blocked_tasks']),1)
    def test_native_policy_cannot_mark_inventory_done(self):
        self.src('host-json','https://jobs.example/list','host_only');r=self.runid();task=self.s.claim(r)
        with self.assertRaises(EngineError):self.s.complete_host_task(task['id'],task['lease_token'],evidence_url='https://jobs.example/list',evidence_text='done',tool_ref='test',outcome={})
    def test_legacy_import_idempotent_and_kept(self):
        records=[{'key':'a','employer':'Synthetic','role':'Planning','provenance':'historical assistant assessment, not current verification'}]
        self.s.import_legacy('p',records);self.s.import_legacy('p',records);self.src();r=self.runid()
        self.assertEqual(len(self.s.review_packet(r)['legacy_records']),1)
        self.assertTrue(any(g['type']=='legacy_recheck' for g in self.s.coverage(r)['material_gaps']))
    def test_legacy_conflicting_reimport_not_overwrite(self):
        record={'key':'a','employer':'Synthetic','role':'Planning','provenance':'historical'};self.s.import_legacy('p',[record]);record['role']='Engineering'
        with self.assertRaises(EngineError):self.s.import_legacy('p',[record])
    def test_empty_universe_is_not_national_run(self):
        with Store(':memory:') as s:
            s.set_profile('x',{})
            with self.assertRaises(EngineError):s.plan_run('x',scope_note='nationwide')
    def test_cli_fresh_start(self):
        with patch('sys.stdout'):
            self.assertEqual(main(['--db',str(Path(self.tmp.name)/'other.sqlite'),'init']),0)
    def test_targeted_scope_does_not_carry_unrelated_jobs(self):
        self.src('host-json','https://jobs.example/list','host_only');r=self.runid();t=self.s.claim(r)
        self.s.commit_page(t['id'],t['lease_token'],Page([sample()],True),source_url='https://jobs.example/list',payload=b'{}',origin='fixture')
        self.s.import_companies('fixture',[{'external_id':'2','name':'Other'}],source_url='https://registry.example/list',raw_sha256='a'*64,scope='fixture',provenance='fixture')
        c2=self.s.db.execute("SELECT id FROM companies WHERE external_id='2'").fetchone()[0]
        targeted=self.s.plan_run('p',scope='targeted',scope_note='one company',company_ids=[c2])
        self.assertEqual(self.s.list_run_jobs(targeted),[])
    def test_unknown_schema_no_silent_destruction(self):
        self.s.db.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
        with self.assertRaises(EngineError):Store(self.path)

if __name__=='__main__':unittest.main()
