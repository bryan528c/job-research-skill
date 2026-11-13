from __future__ import annotations
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from job_research_engine.model import EngineError,LeaseLost,Job,Page,digest,public_url,timestamp
from job_research_engine.store import Store
from job_research_engine.adapters import parse_page,request_url
from job_research_engine.registry import dart_rows,krx_html_rows,csv_rows
from job_research_engine.transport import PublicHTTP,FetchError,Response,retry_delay
from job_research_engine.worker import collect,import_host_capture
from job_research_engine.report import render,handoff,deadline_label,past_deadline

T0='2026-11-09T00:00:00+00:00'
T1='2026-11-09T01:00:00+00:00'

class Clock:
    def __init__(self):self.value=T0
    def __call__(self):return self.value


def sample(i='1',**kw):
    d=dict(external_id=i,title='서비스기획 '+i,employer='합성기업',job_url='https://jobs.example/'+i,
        description='요구사항 분석 및 정책 설계. 테스트 전용 합성 공고.',detail_verified=True)
    d.update(kw);return Job(**d)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'private.sqlite';self.clock=Clock()
        self.s=Store(self.path,clock=self.clock);self.s.set_profile('p',{'roles':['기획'],'timezone':'Asia/Seoul'})
        self.s.import_companies('synthetic',[{'external_id':'c1','name':'합성기업'}],source_url='https://registry.example/list',raw_sha256=digest(b'fixture'),scope='synthetic test only',provenance='fixture')
        self.cid=self.s.db.execute('SELECT id FROM companies').fetchone()[0]
        self.sid=self.s.add_source('host-json','https://jobs.example/list',company_id=self.cid,evidence_ref='test source association',policy='host_only')
        self.rid=self.s.plan_run('p',scope_note='synthetic test corpus')
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def ingest(self,jobs=None,terminal=True,next_cursor=None,total=None,complete=True,run=None):
        task=self.s.claim(run or self.rid)
        p=Page(jobs or [],terminal,next_cursor,total,complete)
        result=self.s.commit_page(task['id'],task['lease_token'],p,source_url='https://jobs.example/list',payload=json.dumps([j.content() for j in p.jobs],ensure_ascii=False).encode(),origin='fixture')
        return task,result
    def assess(self,jid,decision='recommend',**kw):
        j=self.s.row('jobs',jid);p=self.s.row('profiles','p')
        return self.s.assess('p',jid,decision=decision,reason='합성 개인 근거와 일치',evidence_ids=[j['latest_observation_id']],expected_profile_revision=p['revision'],expected_content_hash=j['content_hash'],**kw)
    def test_database_reopen_persists(self):
        self.ingest([sample()]);self.s.close();self.s=Store(self.path,clock=self.clock)
        self.assertEqual(self.s.coverage(self.rid)['unique_source_jobs'],1)
    def test_atomic_page_and_checkpoint(self):
        _,r=self.ingest([sample()],terminal=False,next_cursor='page2')
        self.assertEqual(r['task_status'],'queued');self.assertEqual(self.s.claim(self.rid)['cursor'],'page2')
    def test_fenced_expired_worker(self):
        old=self.s.claim(self.rid,lease_seconds=1);self.clock.value=T1;new=self.s.claim(self.rid)
        self.assertNotEqual(old['lease_token'],new['lease_token'])
        with self.assertRaises(LeaseLost):self.s.commit_page(old['id'],old['lease_token'],Page([],True),source_url='https://jobs.example/list',payload=b'[]',origin='fixture')
    def test_crash_lease_recovery(self):
        old=self.s.claim(self.rid,lease_seconds=1);self.s.close();self.clock.value=T1;self.s=Store(self.path,clock=self.clock)
        new=self.s.claim(self.rid);self.assertEqual(old['id'],new['id']);self.assertEqual(new['attempts'],2)
    def test_concurrent_claim_single_owner(self):
        results=[]
        def f():
            with Store(self.path,clock=self.clock) as s:results.append(s.claim(self.rid))
        threads=[threading.Thread(target=f) for _ in range(4)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sum(r is not None for r in results),1)
    def test_rollback_invalid_page(self):
        with self.assertRaises(EngineError):self.ingest([sample(),sample()])
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],0)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
    def test_pagination_cycle_rejected(self):
        self.ingest([sample()],False,'2');task=self.s.claim(self.rid)
        with self.assertRaises(EngineError):self.s.commit_page(task['id'],task['lease_token'],Page([],False,'2'),source_url='https://jobs.example/list',payload=b'[]',origin='fixture')
    def test_truncated_inventory_not_complete(self):
        _,r=self.ingest([sample()],total=2)
        self.assertEqual(r['gap'],'inventory_total_mismatch');self.assertEqual(self.s.coverage(self.rid)['sources_exhausted'],0)
    def test_changed_total_not_complete(self):
        self.ingest([sample()],False,'2',total=2)
        _,r=self.ingest([sample('2')],total=3)
        self.assertIsNotNone(r['gap'])
    def test_resume_blocks_restart_clean_snapshot(self):
        task,r=self.ingest([sample()],total=2)
        new=self.s.retry_blocked(task['id'],reason='upstream stabilized')
        self.assertNotEqual(task['id'],new)
        self.assertEqual(self.s.row('tasks',task['id'])['status'],'superseded')
        self.ingest([sample(),sample('2')],total=2)
        self.assertEqual(self.s.coverage(self.rid)['sources_exhausted'],1)
    def test_absence_never_closes_job(self):
        _,r=self.ingest([sample()]);jid=r['job_ids'][0];self.assess(jid)
        self.clock.value=T1;r2=self.s.plan_run('p',scope_note='next snapshot',parent_run_id=self.rid)
        self.ingest([],total=0,run=r2)
        self.assertEqual(self.s.row('jobs',jid)['recruiting_status'],'open')
        self.assertEqual(self.s.list_run_jobs(r2)[0]['effective_decision'],'check')
        self.assertTrue(any(g['type']=='missing_job_recheck' for g in self.s.coverage(r2)['material_gaps']))
    def test_three_run_candidate_survives(self):
        _,r=self.ingest([sample()]);jid=r['job_ids'][0];self.assess(jid)
        r2=self.s.plan_run('p',scope_note='second');r3=self.s.plan_run('p',scope_note='third',parent_run_id=r2)
        self.assertIn(jid,[j['id'] for j in self.s.list_run_jobs(r3)])
    def test_submitted_not_new_recommendation(self):
        _,r=self.ingest([sample()]);jid=r['job_ids'][0];self.assess(jid)
        self.s.user_event('p',event_key='submitted1',scope_type='job',target_id=jid,kind='application',value='submitted',evidence_ref='synthetic user confirmed')
        out=render(self.s,self.rid)
        self.assertEqual(out['mapping'],[])
        self.assertEqual(self.s.row('jobs',jid)['recruiting_status'],'open')
    def test_scoped_decline_not_company_ban(self):
        _,r=self.ingest([sample(),sample('2')]);a,b=r['job_ids'];self.assess(a);self.assess(b)
        self.s.user_event('p',event_key='declined1',scope_type='job',target_id=a,kind='decision',value='declined',evidence_ref='user: this posting only')
        out=render(self.s,self.rid);self.assertEqual([x['job_id'] for x in out['mapping']],[b])
    def test_user_event_idempotent(self):
        _,r=self.ingest([sample()]);jid=r['job_ids'][0]
        args=dict(event_key='d',scope_type='job',target_id=jid,kind='decision',value='declined',evidence_ref='user')
        x=self.s.user_event('p',**args);self.assertEqual(x,self.s.user_event('p',**args))
        args['value']='interested'
        with self.assertRaises(EngineError):self.s.user_event('p',**args)
    def test_profile_isolation(self):
        _,r=self.ingest([sample()]);jid=r['job_ids'][0];self.assess(jid)
        self.s.set_profile('q',{'roles':['기획']});r2=self.s.plan_run('q',scope_note='separate profile')
        self.assertEqual(self.s.list_run_jobs(r2),[])
    def test_profile_change_invalidates_assessment(self):
        _,r=self.ingest([sample()]);jid=r['job_ids'][0];self.assess(jid)
        self.s.set_profile('p',{'roles':['사업'],'timezone':'Asia/Seoul'})
        self.assertFalse(self.s.list_run_jobs(self.rid)[0]['assessment_current'])
        self.assertEqual(self.s.list_run_jobs(self.rid)[0]['effective_decision'],'check')
    def test_same_profile_no_revision_bump(self):
        rev=self.s.set_profile('p',{'roles':['기획'],'timezone':'Asia/Seoul'});self.assertEqual(rev,1)
    def test_stale_assessment_cas_rejected(self):
        _,r=self.ingest([sample()]);jid=r['job_ids'][0];j=self.s.row('jobs',jid)
        with self.assertRaises(EngineError):self.s.assess('p',jid,decision='recommend',reason='x',evidence_ids=[j['latest_observation_id']],expected_profile_revision=99,expected_content_hash=j['content_hash'])
    def test_unknown_details_cannot_recommend(self):
        _,r=self.ingest([sample(detail_verified=False)])
        with self.assertRaises(EngineError):self.assess(r['job_ids'][0])
    def test_blocking_unknown_cannot_recommend(self):
        _,r=self.ingest([sample()])
        with self.assertRaises(EngineError):self.assess(r['job_ids'][0],blocking_unknowns=['start date'])
    def test_no_evidence_exclusion_rejected(self):
        _,r=self.ingest([sample()]);j=self.s.row('jobs',r['job_ids'][0])
        with self.assertRaises(EngineError):self.s.assess('p',j['id'],decision='exclude',reason='title only',evidence_ids=[],expected_profile_revision=1,expected_content_hash=j['content_hash'])
    def test_content_change_keeps_history(self):
        _,r=self.ingest([sample()]);jid=r['job_ids'][0];self.assess(jid)
        self.clock.value=T1;r2=self.s.plan_run('p',scope_note='new requirements')
        self.ingest([sample(description='changed requirements')],run=r2)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM job_versions WHERE job_id=?',(jid,)).fetchone()[0],2)
        self.assertFalse(self.s.list_run_jobs(r2)[0]['assessment_current'])
    def test_older_capture_cannot_overwrite(self):
        self.clock.value=T1;_,r=self.ingest([sample(description='newer')]);jid=r['job_ids'][0]
        r2=self.s.plan_run('p',scope_note='old replay');task=self.s.claim(r2)
        self.s.commit_page(task['id'],task['lease_token'],Page([sample(description='older')],True),source_url='https://jobs.example/list',payload=b'old',origin='fixture',observed_at=T0)
        self.assertEqual(json.loads(self.s.row('jobs',jid)['content_json'])['description'],'newer')
    def test_same_title_different_roles_not_merge(self):
        _,r=self.ingest([sample('1',title='기획'),sample('2',title='기획')]);self.assertEqual(len(r['job_ids']),2)
    def test_new_round_separate(self):
        _,r=self.ingest([sample(round_key='round1'),sample(round_key='round2')]);self.assertEqual(len(r['job_ids']),2)
    def test_exact_identity_dedup_across_runs(self):
        self.ingest([sample()]);r2=self.s.plan_run('p',scope_note='again');self.ingest([sample()],run=r2)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
    def test_all_recommendations_rendered(self):
        _,r=self.ingest([sample(str(i)) for i in range(12)])
        for jid in r['job_ids']:self.assess(jid)
        report=render(self.s,self.rid)
        self.assertEqual(len(report['mapping']),12)
        self.assertIn('12.',report['text'])
    def test_report_omission_is_error(self):
        _,r=self.ingest([sample()]);self.assess(r['job_ids'][0])
        with self.assertRaises(EngineError):self.s.save_report(self.rid,'short report',[],{})
    def test_report_numbers_bound_to_report(self):
        _,r=self.ingest([sample(),sample('2')]);a,b=r['job_ids'];self.assess(a);self.assess(b)
        report=render(self.s,self.rid)
        picked=self.s.select_report_job(report['report_id'],2,profile_id='p')
        self.assertEqual(picked['id'],report['mapping'][1]['job_id'])
        with self.assertRaises(EngineError):self.s.select_report_job(report['report_id'],2,profile_id='q')
    def test_handoff_selected_only(self):
        _,r=self.ingest([sample('1'),sample('2')]);[self.assess(j) for j in r['job_ids']]
        report=render(self.s,self.rid);out=handoff(self.s,report['report_id'],1,profile_id='p',selected_facts=['합성 요구사항 정의 경험'])
        self.assertIn('https://jobs.example/1',out);self.assertNotIn('https://jobs.example/2',out)
        self.assertIn('재확인',out)
    def test_handoff_decline_requires_reversal(self):
        _,r=self.ingest([sample()]);jid=r['job_ids'][0];self.assess(jid);rep=render(self.s,self.rid)
        self.s.user_event('p',event_key='d',scope_type='job',target_id=jid,kind='decision',value='declined',evidence_ref='user')
        with self.assertRaises(EngineError):handoff(self.s,rep['report_id'],1,profile_id='p')
    def test_unchecked_company_remains_in_denominator(self):
        self.s.import_companies('synthetic',[{'external_id':'c2','name':'새 합성기업'}],source_url='https://registry.example/list',raw_sha256=digest(b'2'),scope='fixture',provenance='fixture')
        r2=self.s.plan_run('p',scope_note='all registered')
        cov=self.s.coverage(r2);self.assertEqual(cov['companies_planned'],2)
        self.assertTrue(any(x['type']=='source_discovery' for x in cov['material_gaps']))
    def test_no_scope_shrink(self):
        self.s.db.execute('DELETE FROM run_companies WHERE run_id=?',(self.rid,))
        self.assertIn('original_company_scope_shrunk',self.s.coverage(self.rid)['errors'])
    def test_unassessed_jobs_not_excluded(self):
        self.ingest([sample()]);self.assertEqual(self.s.list_run_jobs(self.rid)[0]['effective_decision'],'pending')
        self.assertIn('평가 전 후보 1건',render(self.s,self.rid)['text'])
    def test_broad_audit_not_optional(self):
        _,r=self.ingest([sample()]);self.assess(r['job_ids'][0]);cov=self.s.coverage(self.rid)
        self.assertEqual(cov['status'],'partial');self.assertTrue(any(g['type']=='missing_audit' for g in cov['material_gaps']))
    def test_counter_discovery_without_followthrough_gap(self):
        _,r=self.ingest([sample()]);self.assess(r['job_ids'][0])
        self.s.record_audit(self.rid,kind='counter_search',method='fixture alternate inventory',evidence_ids=[r['observation_id']],discovered_job_ids=r['job_ids'])
        self.assertTrue(any(g['type']=='counter_search_followthrough' for g in self.s.coverage(self.rid)['material_gaps']))
    def test_foreign_run_evidence_rejected(self):
        _,r=self.ingest([sample()]);r2=self.s.plan_run('p',scope_note='another')
        with self.assertRaises(EngineError):self.s.record_audit(r2,kind='counter_search',method='wrong observation',evidence_ids=[r['observation_id']])
    def test_host_export_needs_reference(self):
        task=self.s.claim(self.rid)
        with self.assertRaises(EngineError):self.s.commit_page(task['id'],task['lease_token'],Page([],True),source_url='https://jobs.example/list',payload=b'[]',origin='host_export')
    def test_fixture_not_production_observation(self):
        self.ingest([sample()]);self.assertEqual(self.s.coverage(self.rid)['production_observations'],0)
    def test_source_discovery_real_task_path(self):
        self.s.import_companies('synthetic',[{'external_id':'c3','name':'다른 합성기업'}],source_url='https://registry.example/list',raw_sha256=digest(b'3'),scope='fixture',provenance='fixture')
        cid=self.s.db.execute("SELECT id FROM companies WHERE external_id='c3'").fetchone()[0]
        rid=self.s.plan_run('p',scope_note='discovery',company_ids=[cid])
        task=self.s.claim(rid,kinds=('source_discovery',))
        sid=self.s.add_source('host-json','https://new.example/jobs',company_id=cid,evidence_ref='host observation 1')
        self.s.complete_host_task(task['id'],task['lease_token'],evidence_url='https://new.example/jobs',evidence_text='Observed official source association',tool_ref='fixture host ref',outcome={'source_id':sid})
        self.assertEqual(self.s.claim(rid)['source_id'],sid)
    def test_aging_gap_not_reset_on_new_run(self):
        self.s.db.execute('UPDATE sources SET enabled=0')
        r2=self.s.plan_run('p',scope_note='no source');first=self.s.db.execute("SELECT created_at FROM tasks WHERE run_id=? AND kind='source_discovery'",(r2,)).fetchone()[0]
        self.clock.value=T1;r3=self.s.plan_run('p',scope_note='still missing')
        later=self.s.db.execute("SELECT created_at FROM tasks WHERE run_id=? AND kind='source_discovery'",(r3,)).fetchone()[0]
        self.assertEqual(first,later)


class ParserTests(unittest.TestCase):
    def src(self,kind,**settings):return {'kind':kind,'url':'https://jobs.example/list','settings_json':json.dumps({'employer':'합성기업',**settings})}
    def test_greenhouse_contents(self):
        body=json.dumps({'jobs':[{'id':1,'title':'기획','absolute_url':'https://jobs.example/1','content':'&lt;p&gt;기획 담당&lt;/p&gt;','location':{'name':'Seoul'}}],'meta':{'total':1}}).encode()
        page=parse_page(self.src('greenhouse'),body);self.assertEqual(page.jobs[0].description,'기획 담당');self.assertTrue(page.jobs[0].detail_verified)
    def test_greenhouse_error_not_empty(self):
        with self.assertRaises(EngineError):parse_page(self.src('greenhouse'),b'{"error":"unauthorized"}')
    def test_ashby_unlisted_not_broadcast(self):
        body=json.dumps({'jobs':[{'title':'a','jobUrl':'https://jobs.example/a','isListed':False},{'title':'b','jobUrl':'https://jobs.example/b','isListed':True,'descriptionPlain':'sample'}]}).encode()
        p=parse_page(self.src('ashby'),body);self.assertEqual(len(p.jobs),1);self.assertEqual(p.expected_total,1)
    def test_work24_pagination(self):
        b=b'<wantedRoot><total>2</total><startPage>1</startPage><display>1</display><wanted><wantedAuthNo>a</wantedAuthNo><company>C</company><title>PM</title><wantedInfoUrl>https://jobs.example/a</wantedInfoUrl><closeDt>20261118</closeDt></wanted></wantedRoot>'
        p=parse_page(self.src('work24'),b);self.assertFalse(p.terminal);self.assertEqual(p.next_cursor,'2');self.assertEqual(p.jobs[0].deadline['kind'],'date');self.assertFalse(p.jobs[0].detail_verified)
    def test_work24_open_campaign_not_verified_role(self):
        b=b'<dhsOpenEmpInfoList><total>1</total><startPage>1</startPage><display>100</display><dhsOpenEmpInfo><empSeqno>1</empSeqno><empWantedTitle>Campaign</empWantedTitle><empBusiNm>C</empBusiNm><empWantedHomepgDetail>https://jobs.example/a</empWantedHomepgDetail></dhsOpenEmpInfo></dhsOpenEmpInfoList>'
        p=parse_page(self.src('work24-open'),b);self.assertFalse(p.jobs[0].detail_verified);self.assertTrue(p.jobs[0].external_id.startswith('campaign:'))
    def test_work24_premature_empty(self):
        with self.assertRaises(EngineError):parse_page(self.src('work24'),b'<wantedRoot><total>100</total><startPage>1</startPage><display>10</display></wantedRoot>')
    def test_work24_repeated_page(self):
        with self.assertRaises(EngineError):parse_page(self.src('work24'),b'<wantedRoot><total>0</total><startPage>1</startPage><display>10</display></wantedRoot>','2')
    def test_work24_api_cap_partial(self):
        b=b'<wantedRoot><total>1001</total><startPage>1000</startPage><display>1</display><wanted><wantedAuthNo>a</wantedAuthNo><company>C</company><title>PM</title><wantedInfoUrl>https://jobs.example/a</wantedInfoUrl></wanted></wantedRoot>'
        p=parse_page(self.src('work24'),b,'1000');self.assertTrue(p.terminal);self.assertFalse(p.inventory_complete)
    def test_jsonld_never_full_inventory_claim(self):
        b=b'<script type="application/ld+json">{"@type":"JobPosting","title":"PM","hiringOrganization":{"name":"C"},"description":"Policy design","validThrough":"2026-11-18"}</script>'
        p=parse_page(self.src('jsonld'),b);self.assertFalse(p.inventory_complete);self.assertEqual(p.jobs[0].status,'unknown')
    def test_jsonld_empty_not_no_jobs(self):
        p=parse_page(self.src('jsonld'),b'<html>JavaScript needed</html>');self.assertFalse(p.inventory_complete)
    def test_sitemap_requires_content_inspection(self):
        p=parse_page(self.src('sitemap'),b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://jobs.example/a</loc></url></urlset>')
        self.assertEqual(p.discovered_urls,['https://jobs.example/a']);self.assertFalse(p.inventory_complete)
    def test_xml_entities_rejected(self):
        with self.assertRaises(EngineError):parse_page(self.src('sitemap'),b'<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///etc/passwd">]><urlset/>')
    def test_host_terminal_explicit(self):
        with self.assertRaises(EngineError):parse_page(self.src('host-json'),b'{"jobs":[]}')
    def test_dart_codes_not_size_classification(self):
        b=b'<result><list><corp_code>00000001</corp_code><corp_name>Example</corp_name><stock_code>000001</stock_code></list></result>'
        r=dart_rows(b);self.assertNotIn('size_class',r[0]);self.assertEqual(r[0]['external_id'],'00000001')
    def test_dart_zip_parsing(self):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('CORPCODE.xml','<result><list><corp_code>01</corp_code><corp_name>Example</corp_name></list></result>')
        self.assertEqual(len(dart_rows(b.getvalue())),1)
    def test_dart_api_failure_not_zero(self):
        with self.assertRaises(EngineError):dart_rows(b'<result><status>020</status><message>limit</message></result>')
    def test_krx_company_list(self):
        b='<table><tr><th>회사명</th><th>종목코드</th><th>업종</th></tr><tr><td>합성</td><td>123</td><td>제조</td></tr></table>'.encode('cp949')
        r=krx_html_rows(b);self.assertEqual(r[0]['external_id'],'000123');self.assertNotIn('size_class',r[0])
    def test_changed_krx_layout_fails_closed(self):
        with self.assertRaises(EngineError):krx_html_rows(b'<html>blocked</html>')
    def test_csv_identity_required(self):
        with self.assertRaises(EngineError):csv_rows(b'name\ncompany\n')
    def test_secret_filters_rejected(self):
        src=self.src('work24',filters={'authKey':'not-a-real-key'});src['url']='https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L01.do'
        with self.assertRaises(EngineError):request_url(src,None)
    def test_request_does_not_include_key(self):
        src=self.src('work24',page_size=50);src['url']='https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L01.do'
        url,env=request_url(src,'2');self.assertIn('startPage=2',url);self.assertNotIn('authKey',url);self.assertEqual(env,'WORK24_API_KEY')


class SafetyTests(unittest.TestCase):
    def test_private_urls_rejected(self):
        for u in ['http://127.0.0.1/x','http://169.254.169.254/x','http://[::1]/','javascript:alert(1)','https://u:p@example.com','https://example.com/?authKey=secret','https://example.com/?access_token=x']:
            with self.subTest(url=u),self.assertRaises(EngineError):public_url(u)
    def test_functional_id_query_preserved(self):
        u='https://jobs.example/details?id=123';self.assertEqual(public_url(u),u)
    def test_dns_private_rejected(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(FetchError):PublicHTTP.resolve('jobs.example',443)
    def test_network_disabled(self):
        with self.assertRaises(FetchError):PublicHTTP().get('https://jobs.example/')
    def test_redirect_private_rejected(self):
        t=PublicHTTP(enabled=True,interval=0)
        with patch.object(t,'_one',return_value=Response('https://jobs.example/',302,{'location':'http://127.0.0.1/'},b'')):
            with self.assertRaises(EngineError):t.get('https://jobs.example/')
    def test_credential_redirect_refused(self):
        t=PublicHTTP(enabled=True)
        with patch.object(t,'_one',return_value=Response('https://jobs.example/',302,{'location':'https://jobs.example/new'},b'')):
            with self.assertRaises(FetchError):t.get('https://jobs.example/',secret_query={'authKey':'test-not-real'})
    def test_429_honors_backoff(self):
        t=PublicHTTP(enabled=True)
        with patch.object(t,'_one',return_value=Response('https://jobs.example/',429,{'retry-after':'120'},b'')):
            with self.assertRaises(FetchError) as cm:t.get('https://jobs.example/')
            self.assertEqual(cm.exception.retry_after,120)
    def test_robots_denied(self):
        t=PublicHTTP(enabled=True)
        with patch.object(t,'get',return_value=Response('https://jobs.example/robots.txt',200,{},b'User-agent: *\nDisallow: /')):
            self.assertFalse(t.permitted_by_robots('https://jobs.example/'))
    def test_date_without_time_preserved(self):
        label=deadline_label({'kind':'date','date':'2026-11-10'});self.assertNotIn('23:59',label)
    def test_date_same_day_not_assumed_closed(self):
        self.assertFalse(past_deadline({'kind':'date','date':'2026-11-09'},T0,'Asia/Seoul'))
    def test_naive_timestamp_rejected(self):
        with self.assertRaises(EngineError):timestamp('2026-11-09T10:00:00')


if __name__=='__main__':unittest.main()
