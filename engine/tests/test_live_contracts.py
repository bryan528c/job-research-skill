"""Synthetic regression cases motivated by observed source/Windows failures.
These are not live-market or model-quality measurements.
"""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from io import BytesIO
from zipfile import ZipFile
from xml.sax.saxutils import escape
from job_research_engine.model import EngineError,Job,Page,public_url,dump
from job_research_engine.store import Store
from job_research_engine.registry import krx_html_rows
from job_research_engine.registries import collapse_rows,dart_web_rows,ftc_page,mme_page,sync_registry
from job_research_engine.identity import reconcile,unlink_company,link_companies
from job_research_engine.runtime import session,state_signature,packet
from job_research_engine.korean import parse_sk,parse_ninehire,parse_applyin,parse_korean_page,parse_detail
from job_research_engine.transport import PublicHTTP,Response,FetchError
from job_research_engine.worker import collect

def table(header,rows):
    return ('<table><tr>'+''.join('<th>'+h+'</th>' for h in header)+'</tr>'+''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</table>').encode()

def workbook(rows,formula=False):
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main';output=BytesIO()
    xml='<worksheet xmlns="'+ns+'"><sheetData>'
    for number,values in enumerate(rows,1):
        xml+='<row>'+''.join(f'<c r="{chr(65+i)}{number}" t="inlineStr"><is><t>{escape(v)}</t></is>'+('<f>HYPERLINK("https://example.org")</f>' if formula else '')+'</c>' for i,v in enumerate(values))+'</row>'
    xml+='</sheetData></worksheet>'
    with ZipFile(output,'w') as z:z.writestr('xl/worksheets/sheet1.xml',xml)
    return output.getvalue()

class RegistryContracts(unittest.TestCase):
    def test_alphanumeric_krx_codes_are_not_lost(self):
        data=table(['회사명','종목코드','홈페이지'],[['Synthetic','0022X0','www.example.org']])
        r=krx_html_rows(data)[0]
        self.assertEqual(r['external_id'],'0022X0');self.assertEqual(r['homepage'],'https://www.example.org')

    def test_invalid_unicode_homepage_does_not_discard_dart_company(self):
        payload=workbook([['회사이름','법인등록번호','사업자등록번호','종목코드','홈페이지'],
                         ['Synthetic','1101110000001','111-81-00001','','example.org？invalid']])
        rows=dart_web_rows(payload)
        self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['homepage']);self.assertTrue(rows[0]['facts']['homepage_unusable'])
        with self.assertRaises(EngineError):public_url('https://example.org？invalid')

    def test_formula_registry_is_not_executed(self):
        with self.assertRaises(EngineError):dart_web_rows(workbook([['会社']],formula=True))

    def test_official_identity_conflicts_preserve_both_rows(self):
        rows=[{'external_id':'legal:1','name':'Branch A','facts':{'legal_registration':'1','business_registration':'a'}},
              {'external_id':'legal:1','name':'Branch B','facts':{'legal_registration':'1','business_registration':'b'}}]
        out,duplicates,conflicts=collapse_rows(rows)
        self.assertEqual(len(out),2);self.assertEqual(len(conflicts),1)
        self.assertEqual({r['name'] for r in out},{'Branch A','Branch B'})

    def test_ftc_overlapping_affiliations_are_not_unique_corporation_counts(self):
        payload=table(['공개년월','기업집단명','소속회사명','법인등록번호'],[
            ['202605','Group A','Synthetic','1101110000001'],['202605','Group B','Synthetic','1101110000001']])+b'<script>totCnt=2;</script>'
        rows,total,_=ftc_page(payload,1,2026);out,duplicates,_=collapse_rows(rows)
        self.assertEqual(total,2);self.assertEqual(len(out),1);self.assertEqual(duplicates,1)
        self.assertEqual(out[0]['facts']['group_memberships'],['Group A','Group B'])

    def test_mme_issuance_is_not_size_classification(self):
        rows,_,terminal=mme_page(table(['기업명','사업자등록번호','발급번호','유효기간'],[
          ['Synthetic','111-81-00001','2026-1','2026-04-01 ~ 2027-03-31']]),1,2026)
        self.assertTrue(terminal);self.assertNotIn('size_class',rows[0]);self.assertIn('cancellation',rows[0]['facts']['size_evidence'])

    def test_changed_registry_total_never_completes(self):
        def data(page,total):
            rows=[['202605','Group','Synthetic '+str(page*100+i),str(1101110000000+page*100+i)] for i in range(100)]
            return table(['공개년월','기업집단명','소속회사명','법인등록번호'],rows)+f'<script>totCnt={total};</script>'.encode()
        class Transport:
            evidence_origin='fixture'
            def get(self,url):return Response(url,200,{},data(1,201) if 'pageIndex=1&' in url else data(2,202))
        with Store(':memory:') as s:
            result=sync_registry(s,'ftc',year=2026,transport=Transport())
            self.assertEqual(result['status'],'blocked');self.assertEqual(s.db.execute('SELECT COUNT(*) FROM companies').fetchone()[0],0)
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM registry_acquisitions').fetchone()[0],1)

class DurableContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'private.sqlite';self.s=Store(self.path)
        self.s.set_profile('p',{'timezone':'Asia/Seoul'})
        self.s.import_companies('a',[{'external_id':'1','name':'Synthetic','facts':{'legal_registration':'1101110000001'}}],source_url='https://registry.example.org/a',scope='fixture',raw_sha256='a'*64,provenance='fixture')
        self.cid=self.s.db.execute('SELECT id FROM companies').fetchone()[0]
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def source(self,kind='host-json'):
        return self.s.add_source(kind,'https://jobs.example.org/list',company_id=self.cid,evidence_ref='synthetic',policy='public_api')
    def observed(self,job=None):
        src=self.source();rid=self.s.plan_run('p',scope_note='synthetic');task=self.s.claim(rid)
        j=job or Job('1','Planning','Synthetic','https://jobs.example.org/1',description='Planning and analysis',detail_verified=True)
        result=self.s.commit_page(task['id'],task['lease_token'],Page([j],True,expected_total=1),source_url='https://jobs.example.org/list',payload=b'fixture',origin='fixture')
        return rid,result['job_ids'][0]

    def test_names_never_merge_but_proven_identifiers_can_be_undone(self):
        self.s.import_companies('b',[{'external_id':'2','name':'Synthetic','facts':{'legal_registration':'1101110000002'}},
          {'external_id':'3','name':'Other brand','facts':{'legal_registration':'1101110000001'}}],source_url='https://registry.example.org/b',scope='fixture',raw_sha256='b'*64,provenance='fixture')
        result=reconcile(self.s);self.assertEqual(result['active_proven_identity_links'],1)
        alias=self.s.db.execute('SELECT alias_id FROM company_aliases').fetchone()[0]
        unlink_company(self.s,alias,reason='synthetic review')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM companies').fetchone()[0],3)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM identity_events').fetchone()[0],2)

    def test_fresh_process_restores_legacy_decision_and_original_gap_age(self):
        rid,jid=self.observed()
        self.s.import_legacy('p',[{'key':'old','employer':'Synthetic','role':'Old round','provenance':'historical unknown stage'}])
        self.s.user_event('p',event_key='decision',scope_type='job',target_id=jid,kind='decision',value='declined',evidence_ref='synthetic explicit decision')
        rid2=self.s.plan_run('p',scope_note='repeat',parent_run_id=rid)
        before=state_signature(self.s,'p',rid2);self.s.close()
        code='from job_research_engine.store import Store; from job_research_engine.runtime import session; import sys,json; s=Store(sys.argv[1]); print(json.dumps(session(s,"p",request="continue")));s.close()'
        result=subprocess.run([sys.executable,'-c',code,str(self.path)],capture_output=True,text=True,check=True)
        restored=json.loads(result.stdout);self.s=Store(self.path)
        self.assertEqual(restored['state_sha256'],before);self.assertTrue(restored['restored_existing_run'])
        self.assertEqual(self.s.latest_user_state('p',self.s.row('jobs',jid))['decision'],'declined')

    def test_campaign_cannot_be_recommended_until_individual_roles_are_extracted(self):
        rid,jid=self.observed(Job('1','Campaign','Synthetic','https://jobs.example.org/1',description='Role A: planning. Role B: accounting.',detail_verified=True,requires_role_split=True))
        parent=self.s.row('jobs',jid)
        with self.assertRaises(EngineError):self.s.assess('p',jid,decision='recommend',reason='Planning evidence',evidence_ids=[parent['latest_observation_id']],expected_profile_revision=1,expected_content_hash=parent['content_hash'])
        children=self.s.split_campaign(rid,jid,[{'role_key':'a','title':'Role A','description':'Planning duties. Entry-level.','source_quote':'Role A: planning.'}],evidence_ref='synthetic actual extraction')
        self.assertEqual(len(children),1);self.assertFalse(self.s.list_run_jobs(rid)[0]['fresh_application'])
        with self.assertRaises(EngineError):self.s.split_campaign(rid,jid,[{'role_key':'x','title':'Invented','description':'Invented job','source_quote':'Not on page'}],evidence_ref='synthetic')

    def test_detail_upgrade_preserves_inventory_count_and_user_state(self):
        rid,jid=self.observed(Job('1','Planning','Synthetic','https://jobs.example.org/1'))
        self.s.user_event('p',event_key='submitted',scope_type='job',target_id=jid,kind='application',value='submitted',evidence_ref='synthetic user report')
        task=self.s.claim(rid,kinds=('job_detail',))
        self.s.commit_detail(task['id'],task['lease_token'],Job('1','Planning','Synthetic','https://jobs.example.org/1',description='Actual detailed duties',detail_verified=True),source_url='https://jobs.example.org/1',payload=b'details',origin='fixture')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM pages').fetchone()[0],1)
        self.assertEqual(self.s.latest_user_state('p',self.s.row('jobs',jid))['application'],'submitted')

    def test_schema1_migration_keeps_records_and_creates_backup(self):
        self.s.db.execute("UPDATE meta SET value='1' WHERE key='schema_version'");self.s.close();self.s=Store(self.path)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM companies').fetchone()[0],1)
        self.assertEqual(len(list(self.path.parent.glob('*.bak.sqlite'))),1)

    def test_packet_pagination_does_not_drop_last_candidate(self):
        rid,jid=self.observed()
        result=packet(self.s,rid,page_size=1);self.assertEqual(result['items'][0]['id'],jid);self.assertFalse(result['has_more'])

    def test_new_cycle_preserves_original_blocked_inventory_age(self):
        rid,jid=self.observed()
        source=self.s.row('jobs',jid)['source_id']
        self.s.db.execute("UPDATE tasks SET status='blocked',created_at='2026-01-01T00:00:00.000000+00:00' WHERE run_id=? AND kind='inventory'",(rid,))
        original=self.s.db.execute("SELECT id FROM tasks WHERE run_id=? AND kind='inventory'",(rid,)).fetchone()[0]
        retry=self.s.retry_blocked(original,reason='changed inventory snapshot')
        self.assertNotEqual(original,retry)
        next_run=self.s.plan_run('p',scope_note='continue old gaps',parent_run_id=rid)
        task=self.s.db.execute("SELECT created_at FROM tasks WHERE run_id=? AND source_id=? AND kind='inventory'",(next_run,source)).fetchone()
        self.assertEqual(task[0],'2026-01-01T00:00:00.000000+00:00')

    def test_restoration_hash_detects_actual_assessment_change(self):
        rid,jid=self.observed();before=state_signature(self.s,'p',rid);job=self.s.row('jobs',jid)
        self.s.assess('p',jid,decision='check',reason='Synthetic missing essential fact',evidence_ids=[job['latest_observation_id']],
                      expected_profile_revision=1,expected_content_hash=job['content_hash'])
        self.assertNotEqual(before,state_signature(self.s,'p',rid))

    def test_platform_employer_expands_frontier_without_name_only_legal_merge(self):
        src=self.s.add_source('host-json','https://platform.example.org/list',company_id=None,evidence_ref='synthetic platform',policy='public_api')
        rid=self.s.plan_run('p',scope_note='platform discovery');task=self.s.claim(rid)
        result=self.s.commit_page(task['id'],task['lease_token'],Page([Job('new','Planning','Synthetic','https://jobs.example.org/new',description='Actual duties',detail_verified=True)],True,expected_total=1),source_url='https://platform.example.org/list',payload=b'synthetic platform',origin='fixture')
        job=self.s.row('jobs',result['job_ids'][0]);self.assertNotEqual(job['company_id'],self.cid)
        company=self.s.row('companies',job['company_id']);self.assertTrue(json.loads(company['facts_json'])['identity_unresolved'])
        self.assertIsNotNone(self.s.db.execute("SELECT id FROM tasks WHERE run_id=? AND company_id=? AND kind='source_discovery'",(rid,job['company_id'])).fetchone())

    def test_registry_audit_requires_real_acquisition_membership_in_run(self):
        rid,jid=self.observed()
        with self.assertRaises(EngineError):self.s.record_audit(rid,kind='registry_scope',method='forged source receipt',evidence_ids=['registry:missing:1'])
        payload=table(['회사명','종목코드'],[['Synthetic listed','000001']])
        class Transport:
            evidence_origin='fixture'
            def get(self,url):return Response(url,200,{},payload)
        result=sync_registry(self.s,'krx',transport=Transport())
        another=self.s.plan_run('p',scope_note='actual acquisition represented in scope')
        self.assertTrue(self.s.record_audit(another,kind='registry_scope',method='synthetic acquisition membership check',evidence_ids=['registry:'+result['sync_id']+':1']))

    def test_failed_parser_retains_actual_body_for_host_recovery(self):
        self.source('greenhouse');rid=self.s.plan_run('p',scope_note='changed response')
        class Transport:
            evidence_origin='fixture'
            def get(self,url,secret_query=None):return Response(url,200,{},b'<html>Changed public shape</html>')
        # Use the documented endpoint so failure is in the response parser, not request validation.
        self.s.db.execute("UPDATE sources SET url='https://boards-api.greenhouse.io/v1/boards/synthetic/jobs'")
        collect(self.s,rid,transport=Transport())
        obs=self.s.db.execute('SELECT payload FROM observations').fetchone()
        self.assertEqual(bytes(obs[0]),b'<html>Changed public shape</html>')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)

class KoreanContracts(unittest.TestCase):
    def test_platform_millisecond_date_preserves_day_precision(self):
        data={'props':{'pageProps':{'__APOLLO_STATE__':{'Activity:1':{'title':'Synthetic planning','organizationName':'Synthetic',
          'detailText':{'__ref':'Text:1'},'recruitCloseAt':1795359599999,'dateRepresentation':'DAY'},'Text:1':{'text':'<p>Actual duties</p>'}}}}}
        payload=('<script id="__NEXT_DATA__">'+json.dumps(data)+'</script>').encode()
        job=parse_detail('linkareer-detail',payload,'https://linkareer.com/activity/1',{})
        self.assertEqual(job.deadline['kind'],'date');self.assertNotIn('at',job.deadline)
    def test_greeting_uses_observed_links_and_timezone_not_server_display(self):
        data={'props':{'pageProps':{'dehydratedState':{'queries':[{'queryKey':['openings'],'state':{'data':[
          {'openingId':1,'deploy':True,'title':'Synthetic planning','group':{'name':'Synthetic Group'},'dueDate':'2026-11-20T14:59:59Z'}]}}]}}}}
        payload=('<a href="/o/1">Synthetic planning</a><script id="__NEXT_DATA__">'+json.dumps(data)+'</script>').encode()
        source={'kind':'greeting-list','url':'https://synthetic.career.greetinghr.com/ko/recruit','settings_json':'{}'}
        page=parse_korean_page(source,payload)
        self.assertEqual(page.jobs[0].deadline['at'],'2026-11-20T23:59:59+09:00')
        self.assertEqual(page.expected_total,1)

    def test_lotte_total_is_not_replaced_by_found_cards(self):
        payload='''전체(13)<div class="job-card-group"><div class="cmp-name">Synthetic</div>
          <a href="/apply/announcement/detail/1">Planning</a><p class="date">2026.11.01 ~ 2026.11.20</p></div>'''.encode()
        page=parse_korean_page({'kind':'lotte-list','url':'https://recruit.lotte.co.kr/apply/announcement/','settings_json':'{}'},payload)
        self.assertEqual(len(page.jobs),1);self.assertEqual(page.expected_total,13)

    def test_sk_employer_and_deadline_come_from_labelled_fields(self):
        body='''<a>같은 회사 공고 더 보기 비슷한 직무</a><div class="detail-content-item">Actual duties and requirements</div>
          <div class="floating-box"><h2 class="box-title">Synthetic planning</h2>
          <div class="box-detail-item"><div class="label">회사</div><div class="value">Synthetic Employer</div></div>
          <div class="box-detail-item"><div class="label">지원 기간</div><div class="value">October 27, 2026(Tue)~November 10, 2026(Tue)</div></div>
          <div class="box-detail-item"><div class="label">마감 시간</div><div class="value">23:59</div></div>
          <button onclick='location.href="/User/Login?returnUrl=%2FRecruit%2FDetail%2FR1"'>지원하기</button></div>'''
        job=parse_sk(body.encode(),'https://www.skcareers.com/Recruit/Detail/R1')
        self.assertEqual(job.employer,'Synthetic Employer');self.assertEqual(job.deadline['at'],'2026-11-10T23:59:00+09:00')
        self.assertIn('/User/Login?',job.apply_url)

    def test_ninehire_closed_post_does_not_become_open(self):
        data={'props':{'pageProps':{'recruitment':{'addressKey':'synth','title':'Planning','companyName':'Synthetic','jobPostingIsActive':False,'status':'closed','reception':{'canSubmit':False}},'jobPosting':{'content':'<p>Actual duties</p>'}}}}
        payload=('<script id="__NEXT_DATA__" type="application/json">'+json.dumps(data)+'</script>').encode()
        self.assertEqual(parse_ninehire(payload,'https://jobs.example.org/job_posting/synth').status,'closed')

    def test_image_only_applyin_needs_host_review(self):
        payload=json.dumps({'data':{'id':1,'title':'Synthetic campaign','statusCode':'Open','content':'<img src="https://images.example.org/poster.jpg">','links':{}},'meta':{}}).encode()
        jobs,_=parse_applyin(payload,'https://synthetic.applyin.co.kr/jobs/1',detail=True)
        self.assertFalse(jobs[0].detail_verified);self.assertEqual(jobs[0].raw['media_urls'],['https://images.example.org/poster.jpg'])

    def test_read_form_cannot_be_repurposed_for_application_submission(self):
        transport=PublicHTTP(enabled=True)
        with self.assertRaises(FetchError):transport.read_form('https://www.skcareers.com/Recruit/Apply',{})
        with self.assertRaises(FetchError):transport.read_form('https://www.skcareers.com/Recruit/GetRecruitList',{'resume':'private'})

if __name__=='__main__':unittest.main()
