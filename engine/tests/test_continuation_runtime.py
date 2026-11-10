"""Synthetic regressions from actual continuation failures; not live measurements."""
import unittest
import json
from contextlib import contextmanager
from zoneinfo import ZoneInfoNotFoundError
from job_research_engine.report import render
from unittest.mock import patch,MagicMock
from job_research_engine.transport import PublicHTTP,Response,FetchError
from job_research_engine.registries import dart_web_rows,sync_registry
from job_research_engine.store import Store
from job_research_engine.model import Job,Page,LeaseLost,EngineError
from test_live_contracts import workbook,table
from job_research_engine.korean import detect_kind,parse_detail,parse_ninehire
from job_research_engine.htmltools import html
from job_research_engine.adapters import plain
from job_research_engine.worker import collect

class PublicJobReads(unittest.TestCase):
    def test_korean_poster_wire_url_encodes_unicode_without_double_encoding_observed_escapes(self):
        t=PublicHTTP(enabled=True);t.interval=0
        url='http://cdn.example/공고/%ED%95%9C.png?name=채용&already=%EC%9B%90'
        with patch.object(t,'resolve',return_value='8.8.8.8'),patch('job_research_engine.transport.socket.create_connection'),patch('job_research_engine.transport.http.client.HTTPConnection') as connection:
            response=connection.return_value.getresponse.return_value
            response.status=200;response.getheaders.return_value=[];response.read.return_value=b'original poster bytes'
            actual=t.get(url)
            target=connection.return_value.request.call_args.args[1]
            self.assertEqual(target,'/%EA%B3%B5%EA%B3%A0/%ED%95%9C.png?name=%EC%B1%84%EC%9A%A9&already=%EC%9B%90')
            self.assertEqual(actual.url,url);self.assertEqual(actual.body,b'original poster bytes')

    def test_registered_greeting_custom_domain_follows_observed_details_without_domain_whitelist(self):
        base='https://custom.example/apply';detail='https://custom.example/ko/o/123'
        listing={'props':{'pageProps':{'dehydratedState':{'queries':[{'queryKey':['openings'],'state':{'data':[{'openingId':123,'title':'Planning','deploy':True}]}}]}}}}
        body={'props':{'pageProps':{'dehydratedState':{'queries':[{'queryKey':['getOpeningById',123],'state':{'data':{'success':True,'data':{'groupInfo':{'name':'Synthetic'},'jobPositionSetting':{},'openingsInfo':{'openingId':123,'title':'Planning','detail':'<p>Actual individual duties</p>','status':'OPEN'}}}}}]}}}}
        payloads={base:('<a href="/ko/o/123">Planning</a><script id="__NEXT_DATA__">'+json.dumps(listing)+'</script>').encode(),detail:('<script id="__NEXT_DATA__">'+json.dumps(body)+'</script>').encode()}
        class Transport:
            evidence_origin='fixture'
            def get(self,url,**kwargs):return Response(url,200,{'content-type':'text/html'},payloads[url])
        with Store(':memory:') as s:
            s.set_profile('p',{})
            s.import_companies('fixture',[{'external_id':'1','name':'Universe'}],source_url='https://registry.example/a',scope='fixture',raw_sha256='a'*64,provenance='fixture')
            s.add_source('greeting-list',base,company_id=None,settings={'employer':'Synthetic'},policy='public_api',evidence_ref='Actual synthetic provider association')
            rid=s.plan_run('p',scope_note='fixture')
            result=collect(s,rid,transport=Transport(),include_details=True)
            self.assertEqual(result['pages_committed'],2);self.assertEqual(result['blocked_or_failed_attempts'],0)
            self.assertTrue(s.db.execute('SELECT detail_verified FROM jobs WHERE job_url=?',(detail,)).fetchone()[0])

    def test_sk_poster_only_is_pending_and_bound_to_the_same_notice(self):
        body='''<main><h2 class="title">Training and roles</h2><div class="floating-box">
          <div class="box-detail-item"><span class="label">Company</span><span class="value">Synthetic</span></div>
          <div class="box-detail-item"><span class="label">Employment Type</span><span class="value">Trainee</span></div>
          </div><img src="https://d3g1pwhebgacef.cloudfront.net/JobNotice/R123/Info/poster.png">
          <img src="https://d3g1pwhebgacef.cloudfront.net/JobNotice/OTHER/Info/site.png"></main>'''.encode()
        job=parse_detail('skcareers-detail',body,'https://www.skcareers.com/Recruit/Detail/R123',{})
        self.assertFalse(job.detail_verified);self.assertTrue(job.requires_role_split)
        self.assertEqual(job.source_context['Employment Type'],'Trainee')
        self.assertEqual(job.raw['media_urls'],['https://d3g1pwhebgacef.cloudfront.net/JobNotice/R123/Info/poster.png'])
        with self.assertRaises(EngineError):
            parse_detail('skcareers-detail',body.replace(b'/R123/',b'/OTHER/'),'https://www.skcareers.com/Recruit/Detail/R123',{})

    def test_gabia_nonsecret_site_header_is_exactly_scoped(self):
        t=PublicHTTP(enabled=True);url='https://recruit-api.gabiaoffice.hiworks.com/v1/career-site/tokens/site-information'
        with patch.object(t,'_one',return_value=Response(url,200,{},b'{}')) as call:
            t.get_gabia(url);call.assert_called_once_with(url,gabia_site_info=True)
        for target in (url.replace('tokens/site-information','applicants'),url+'?access_token=private',url.replace('hiworks.com','example.org')):
            with self.subTest(url=target),self.assertRaises(EngineError):t.get_gabia(target)

    def test_ninehire_department_is_not_the_legal_employer_label(self):
        data={'props':{'pageProps':{'recruitment':{'addressKey':'abc','title':'Planning','companyName':'Synthetic Employer','affiliation':{'title':'Quality Department'},'reception':{}},'jobPosting':{'content':'<p>Actual duties</p>'}}}}
        body=('<script id="__NEXT_DATA__">'+json.dumps(data)+'</script>').encode()
        job=parse_ninehire(body,'https://jobs.example/job_posting/abc')
        self.assertEqual(job.employer,'Synthetic Employer');self.assertEqual(job.raw['affiliation'],'Quality Department')

    def test_lotte_deadline_uses_observed_body_time_for_the_same_header_date(self):
        body='''<div class="board-head"><span class="title">Planning</span><span class="board-type">Synthetic</span>
        <span class="date-detail">2026.10.27 ~ 2026.11.09</span></div><div class="board-content">
        Actual duties. 접수기간 : 2026년 10월 27일 (화) 10:00 ~ 2026년 11월 9일(월) 23:00 접수방법 : 공식 홈페이지</div>'''.encode()
        job=parse_detail('lotte-detail',body,'https://recruit.lotte.co.kr/apply/announcement/detail/1',{})
        self.assertEqual(job.deadline,{'kind':'datetime','at':'2026-11-09T23:00:00+09:00'})

    def test_jobflex_header_cannot_target_user_or_application_endpoints(self):
        t=PublicHTTP(enabled=True);url='https://api-recruiter.recruiter.co.kr/position/v2/jobflex/123'
        with patch.object(t,'_one',return_value=Response(url,200,{},b'{}')) as call:
            t.get_jobflex(url,'synthetic.recruiter.co.kr')
            call.assert_called_once_with(url,public_tenant='synthetic.recruiter.co.kr')
        for target,prefix in [(url.replace('/position/v2/jobflex/123','/applicant/123'),'synthetic.recruiter.co.kr'),
                              (url,'private.internal'),(url,'synthetic.recruiter.co.kr\r\nCookie: x')]:
            with self.subTest(target=target,prefix=prefix),self.assertRaises(FetchError):t.get_jobflex(target,prefix)

    def test_inert_text_flushes_trailing_ampersand_metadata(self):
        self.assertEqual(html(b'R&D/QA').text(),'R&D/QA')
        self.assertEqual(plain('R&D/QA'),'R&D/QA')

    def test_observed_custom_greeting_application_link_and_display_division(self):
        url='https://recruit-hanwhaocean.com/ko/o/123'
        data={'props':{'pageProps':{'dehydratedState':{'queries':[{'queryKey':['getOpeningById',123],
            'state':{'data':{'success':True,'data':{'groupInfo':{'name':'Group'},'jobPositionSetting':{'jobPositions':[{'workspacePlace':{'location':'Observed workplace'}},{'workspacePlace':{'location':'Observed workplace'}}]},
                'openingsInfo':{'openingId':123,'title':'Planning','detail':'<p>Actual duties</p>',
                    'status':'OPEN','workspaceDivision':{'division':'Observed subsidiary'}}}}}}]}}}}
        body=('<a href="/ko/apply">Apply</a><a href="/ko/a/login?returnTo=cHVibGlj">지원하기</a><script id="__NEXT_DATA__">'+json.dumps(data)+'</script>').encode()
        job=parse_detail(detect_kind(url),body,url,{})
        self.assertEqual(job.employer,'Observed subsidiary')
        self.assertEqual(job.location,'Observed workplace')
        self.assertEqual(job.apply_url,'https://recruit-hanwhaocean.com/ko/a/login?returnTo=cHVibGlj')

    def test_interrupted_single_export_restarts_without_a_duplicate_full_page(self):
        body=table(['회사명','종목코드'],[['Synthetic','000001']])
        class Transport:
            evidence_origin='fixture'
            def get(self,url):return Response(url,200,{},body)
        with Store(':memory:') as s:
            with patch.object(s,'import_companies',side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):sync_registry(s,'krx',transport=Transport())
            old=s.db.execute('SELECT id FROM registry_syncs').fetchone()[0]
            result=sync_registry(s,'krx',transport=Transport())
            self.assertNotEqual(old,result['sync_id']);self.assertEqual(result['raw_rows'],1)
            self.assertEqual(s.db.execute('SELECT status FROM registry_syncs WHERE id=?',(old,)).fetchone()[0],'invalid')
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM registry_acquisitions').fetchone()[0],2)

    def test_dart_preserves_official_alphanumeric_stock_identity(self):
        payload=workbook([['회사이름','법인등록번호','사업자등록번호','종목코드','홈페이지'],
                         ['Synthetic','1101110000001','1118100001','0022x0','']])
        self.assertEqual(dart_web_rows(payload)[0]['facts']['stock_code'],'0022X0')

    def test_only_reviewed_lg_job_reads_are_dispatched(self):
        t=PublicHTTP(enabled=True);url='https://api.careers.lg.com/rmk/job/retrieveJobNoticesDetail'
        with patch.object(t,'_one',return_value=Response(url,200,{},b'{}')) as call:
            t.read_json(url,{'jobNoticeId':'123'})
            call.assert_called_once_with(url,json_body={'jobNoticeId':'123'})
        for target,body in [(url.replace('retrieveJobNoticesDetail','saveFavorites'),{}),
                            (url,{'jobNoticeId':123,'resume':'private'}),(url,{'jobNoticeId':True}),
                            (url+'?token=private',{'jobNoticeId':123}),
                            (url.replace('Detail','List'),{'companyCodeList':['x']*101})]:
            with self.subTest(target=target,body=body),self.assertRaises((FetchError,ValueError)):
                t.read_json(target,body)

    def test_public_json_backoff_and_redirects_are_not_silently_followed(self):
        t=PublicHTTP(enabled=True);url='https://api.careers.lg.com/rmk/job/retrieveJobNotices'
        with patch.object(t,'_one',return_value=Response(url,429,{'retry-after':'600'},b'')):
            with self.assertRaises(FetchError) as e:t.read_json(url,{})
            self.assertEqual(e.exception.retry_after,600)
        with patch.object(t,'_one',return_value=Response(url,302,{'location':'/save'},b'')) as call:
            with self.assertRaises(FetchError):t.read_json(url,{})
            self.assertEqual(call.call_count,1)

    def test_hanwha_public_query_refuses_hidden_or_user_routes(self):
        t=PublicHTTP(enabled=True);base='https://hwadm.hanwhain.com/new-backend/portal/api/rcRecruit/'
        body={'rtSeq':123,'hidnKey':None,'langCd':'ko'}
        with patch.object(t,'_one',return_value=Response(base+'get-rcrt',200,{},b'{}')) as call:
            t.read_json(base+'get-rcrt',body)
            call.assert_called_once_with(base+'get-rcrt',json_body=body)
        for url,data in [(base+'get-rcrt',{**body,'hidnKey':'hidden'}),(base+'save-rcrt',body),
                         (base+'search-rcrt',{'langCd':'ko','page':0,'size':10001}),
                         (base+'search-rcrt',{'langCd':'ko','page':0,'size':20,'userId':'private'})]:
            with self.subTest(url=url,data=data),self.assertRaises(FetchError):t.read_json(url,data)

class RefinedRoles(unittest.TestCase):
    def test_explicit_parent_closure_preserves_child_duties_and_decisions_when_body_disappears(self):
        with Store(':memory:') as s:
            s.set_profile('p',{})
            s.import_companies('fixture',[{'external_id':'1','name':'Universe'}],source_url='https://registry.example/a',scope='fixture',raw_sha256='a'*64,provenance='fixture')
            source=s.add_source('host-json','https://jobs.example/list',company_id=None,evidence_ref='synthetic',policy='host_only')
            rid=s.plan_run('p',scope_note='fixture');task=s.claim(rid)
            parent=Job('1','Campaign','Synthetic','https://jobs.example/1',status='open',description='Role A: planning; Role B: other duties',detail_verified=True)
            jid=s.commit_page(task['id'],task['lease_token'],Page([parent],True),source_url=parent.job_url,payload=b'open',origin='fixture')['job_ids'][0]
            children=s.split_campaign(rid,jid,[{'role_key':'a','title':'Role A','description':'Planning duties','source_quote':'Role A:'},
              {'role_key':'b','title':'Role B','description':'Other duties','source_quote':'Role B:','recruiting_status':'closed'}],evidence_ref='fixture')
            self.assertEqual([s.row('jobs',j)['recruiting_status'] for j in children],['open','closed'])
            s.user_event('p',event_key='selected',scope_type='job',target_id=children[0],kind='decision',value='interested',evidence_ref='explicit synthetic selection')
            tid=s._enqueue(rid,'job_detail',jid+':closed',source_id=source,payload={'job_id':jid});task=s.claim(rid,task_id=tid,kinds=('job_detail',))
            closed=Job('1',parent.title,parent.employer,parent.job_url,status='closed',description='',detail_verified=False)
            s.commit_detail(tid,task['lease_token'],closed,source_url=parent.job_url,payload=b'closed source without description',origin='fixture')
            child=s.row('jobs',children[0])
            self.assertEqual(child['recruiting_status'],'closed');self.assertEqual(json.loads(child['content_json'])['description'],'Planning duties')
            self.assertEqual(s.latest_user_state('p',child)['decision'],'interested')
            self.assertFalse(next(j for j in s.list_run_jobs(rid) if j['id']==children[0])['fresh_application'])

    def test_korean_date_rollover_keeps_elapsed_candidates_without_fresh_submission_advice(self):
        with Store(':memory:',clock=lambda:'2026-11-09T23:30:00+00:00') as s:
            s.set_profile('p',{'timezone':'Asia/Seoul'})
            s.import_companies('fixture',[{'external_id':'1','name':'Universe'}],source_url='https://registry.example/a',scope='fixture',raw_sha256='a'*64,provenance='fixture')
            s.add_source('host-json','https://jobs.example/list',company_id=None,evidence_ref='synthetic',policy='host_only')
            rid=s.plan_run('p',scope_note='rollover fixture');task=s.claim(rid)
            job=Job('1','Planning','Synthetic','https://jobs.example/1',description='Actual duties',detail_verified=True,deadline={'kind':'date','date':'2026-11-09','timezone':'Asia/Seoul'})
            jid=s.commit_page(task['id'],task['lease_token'],Page([job],True),source_url=job.job_url,payload=b'fixture',origin='fixture')['job_ids'][0]
            current=s.row('jobs',jid)
            s.assess('p',jid,decision='recommend',reason='Synthetic fit, source deadline remains independent',evidence_ids=[current['latest_observation_id']],expected_profile_revision=1,expected_content_hash=current['content_hash'])
            with patch('job_research_engine.report.ZoneInfo',side_effect=ZoneInfoNotFoundError('stdlib-only Windows fixture')):
                report=render(s,rid)
            self.assertIn('2026-11-10',report['text']);self.assertEqual(report['mapping'],[])
            self.assertIn('마감이 지난 기존 후보 1건',report['text'])
            self.assertEqual(len(s.list_run_jobs(rid)),1);self.assertEqual(s.row('jobs',jid)['recruiting_status'],'open')

    def test_private_historical_decision_needs_no_fabricated_web_url(self):
        with Store(':memory:') as s:
            s.set_profile('p',{})
            s.import_companies('fixture',[{'external_id':'1','name':'Universe'}],source_url='https://registry.example/a',scope='fixture',raw_sha256='a'*64,provenance='fixture')
            s.import_legacy('p',[{'key':'old-round','employer':'Synthetic','role':'Planning','provenance':'Explicit user decision: did not apply to that round'}])
            rid=s.plan_run('p',scope_note='fixture');task=s.claim(rid,kinds=('legacy_recheck',))
            with self.assertRaises(EngineError):s.complete_host_task(task['id'],task['lease_token'],evidence_url=None,evidence_text='read',tool_ref='actual private record reading',outcome={'disposition':'scoped_user_decline','source_quote':'invented quote'})
            oid=s.complete_host_task(task['id'],task['lease_token'],evidence_url=None,evidence_text='Scoped original decision, application outcome unknown',tool_ref='actual private record reading',outcome={'disposition':'scoped_user_decline','source_quote':'Explicit user decision: did not apply to that round','company_wide':False})
            obs=s.row('observations',oid)
            self.assertEqual(obs['origin'],'private_record');self.assertTrue(obs['source_url'].startswith('urn:job-research:legacy:'))
            self.assertEqual(s.coverage(rid)['production_observations'],0)
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM user_events').fetchone()[0],0)

    @contextmanager
    def image_fixture(self):
        with Store(':memory:') as s:
            s.set_profile('p',{})
            s.import_companies('fixture',[{'external_id':'1','name':'Universe'}],source_url='https://registry.example/a',scope='fixture',raw_sha256='a'*64,provenance='fixture')
            source=s.add_source('host-json','https://jobs.example/list',company_id=None,evidence_ref='synthetic',policy='host_only')
            rid=s.plan_run('p',scope_note='image fixture');task=s.claim(rid)
            job=Job('1','Planning','Synthetic','https://jobs.example/1')
            jid=s.commit_page(task['id'],task['lease_token'],Page([job],True),source_url=job.job_url,payload=b'list',origin='fixture')['job_ids'][0]
            task=s.claim(rid,kinds=('job_detail',))
            s.commit_detail(task['id'],task['lease_token'],job,source_url=job.job_url,payload=b'image detail v1',origin='fixture')
            yield s,rid,jid,source,job

    def test_new_image_detail_reopens_completed_review(self):
        with self.image_fixture() as (s,rid,jid,source,job):
            task=s.claim(rid,kinds=('image_review',))
            verified=Job('1','Planning','Synthetic',job.job_url,description='Actually read image text',detail_verified=True)
            s.commit_detail(task['id'],task['lease_token'],verified,source_url=job.job_url,payload=b'viewed v1',origin='fixture')
            tid=s._enqueue(rid,'job_detail',jid+':refresh',source_id=source,payload={'job_id':jid})
            refresh=s.claim(rid,kinds=('job_detail',),task_id=tid)
            s.commit_detail(tid,refresh['lease_token'],job,source_url=job.job_url,payload=b'image detail v2',origin='fixture')
            reopened=s.claim(rid,kinds=('image_review',))
            self.assertIsNotNone(reopened)
            self.assertEqual(json.loads(reopened['payload_json'])['expected_content_hash'],s.row('jobs',jid)['content_hash'])
            self.assertGreaterEqual(s.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],4)

    def test_older_source_capture_cannot_replace_newer_detail(self):
        with self.image_fixture() as (s,rid,jid,source,job):
            tid=s._enqueue(rid,'job_detail',jid+':old-capture',source_id=source,payload={'job_id':jid})
            task=s.claim(rid,kinds=('job_detail',),task_id=tid)
            old=Job('1','Old','Synthetic',job.job_url,description='Obsolete older duties',detail_verified=True)
            before=s.row('jobs',jid)['content_hash']
            receipt=s.commit_detail(tid,task['lease_token'],old,source_url=job.job_url,payload=b'older raw capture',origin='fixture',observed_at='2026-01-01T00:00:00+00:00')
            self.assertTrue(receipt['stale_ignored']);self.assertEqual(s.row('jobs',jid)['content_hash'],before)
            self.assertEqual(s.row('tasks',tid)['status'],'blocked')

    def test_equivalent_old_capture_does_not_rewind_source_freshness(self):
        with self.image_fixture() as (s,rid,jid,source,job):
            before=s.row('jobs',jid)
            tid=s._enqueue(rid,'job_detail',jid+':same-old-capture',source_id=source,payload={'job_id':jid})
            task=s.claim(rid,kinds=('job_detail',),task_id=tid)
            s.commit_detail(tid,task['lease_token'],job,source_url=job.job_url,payload=b'image detail v1',origin='fixture',observed_at='2026-01-01T00:00:00+00:00')
            after=s.row('jobs',jid)
            self.assertEqual(after['last_seen'],before['last_seen'])
            self.assertEqual(after['latest_observation_id'],before['latest_observation_id'])

    def test_image_worker_cannot_overwrite_a_newer_review_input(self):
        with self.image_fixture() as (s,rid,jid,source,job):
            old=s.claim(rid,kinds=('image_review',))
            tid=s._enqueue(rid,'job_detail',jid+':refresh',source_id=source,payload={'job_id':jid})
            refresh=s.claim(rid,kinds=('job_detail',),task_id=tid)
            s.commit_detail(tid,refresh['lease_token'],job,source_url=job.job_url,payload=b'image detail v2',origin='fixture')
            verified=Job('1','Planning','Synthetic',job.job_url,description='Stale read',detail_verified=True)
            with self.assertRaises(LeaseLost):s.commit_detail(old['id'],old['lease_token'],verified,source_url=job.job_url,payload=b'old read',origin='fixture')
            self.assertFalse(s.row('jobs',jid)['detail_verified'])
            self.assertIsNotNone(s.claim(rid,kinds=('image_review',)))

    def test_verified_new_text_supersedes_queued_and_leased_image_work(self):
        for leased in (False,True):
            with self.subTest(leased=leased),self.image_fixture() as (s,rid,jid,source,job):
                old=s.claim(rid,kinds=('image_review',)) if leased else None
                tid=s._enqueue(rid,'job_detail',jid+':now-text',source_id=source,payload={'job_id':jid})
                task=s.claim(rid,kinds=('job_detail',),task_id=tid)
                verified=Job('1','Planning','Synthetic',job.job_url,description='New actual text replaces image-only input',detail_verified=True)
                s.commit_detail(tid,task['lease_token'],verified,source_url=job.job_url,payload=b'new real text',origin='fixture')
                self.assertIsNone(s.claim(rid,kinds=('image_review',)))
                if old:
                    with self.assertRaises(LeaseLost):s.commit_detail(old['id'],old['lease_token'],verified,source_url=job.job_url,payload=b'old image read',origin='fixture')

    def test_first_page_total_is_enforced_when_terminal_page_omits_it(self):
        with Store(':memory:') as s:
            s.set_profile('p',{})
            s.import_companies('fixture',[{'external_id':'1','name':'Universe'}],source_url='https://registry.example/a',scope='fixture',raw_sha256='a'*64,provenance='fixture')
            source=s.add_source('host-json','https://jobs.example/list',company_id=None,evidence_ref='synthetic',policy='host_only')
            rid=s.plan_run('p',scope_note='paginated fixture')
            task=s.claim(rid)
            s.commit_page(task['id'],task['lease_token'],Page([Job('1','A','Synthetic','https://jobs.example/1')],False,'1',expected_total=3),source_url='https://jobs.example/list',payload=b'first',origin='fixture')
            task=s.claim(rid)
            result=s.commit_page(task['id'],task['lease_token'],Page([Job('2','B','Synthetic','https://jobs.example/2')],True,expected_total=None),source_url='https://jobs.example/list?page=1',payload=b'last',origin='fixture')
            self.assertEqual(result['gap'],'inventory_total_mismatch')
            self.assertEqual(s.coverage(rid)['sources_exhausted'],0)

    def test_detail_employer_refinement_and_child_application_path_stay_consistent(self):
        with Store(':memory:') as s:
            s.set_profile('p',{})
            s.import_companies('fixture',[{'external_id':'1','name':'Universe'}],source_url='https://registry.example/a',scope='fixture',raw_sha256='a'*64,provenance='fixture')
            source=s.add_source('host-json','https://jobs.example/list',company_id=None,evidence_ref='synthetic',policy='host_only')
            rid=s.plan_run('p',scope_note='fixture');task=s.claim(rid)
            parent=Job('1','Campaign','Group label','https://jobs.example/1',apply_url='https://jobs.example/old',description='Role A: planning duties',detail_verified=True,requires_role_split=False)
            jid=s.commit_page(task['id'],task['lease_token'],Page([parent],True),source_url=parent.job_url,payload=b'fixture',origin='fixture')['job_ids'][0]
            roles=[{'role_key':'a','title':'Role A','description':'Planning duties','source_quote':'Role A:'}]
            child=s.split_campaign(rid,jid,roles,evidence_ref='fixture')[0]
            visible={j['id']:j for j in s.list_run_jobs(rid)}
            self.assertFalse(visible[jid]['fresh_application']);self.assertTrue(visible[child]['fresh_application'])
            s.user_event('p',event_key='decline',scope_type='job',target_id=child,kind='decision',value='declined',evidence_ref='synthetic explicit decision')
            tid=s._enqueue(rid,'job_detail',jid,source_id=source,payload={'job_id':jid})
            detail=s.claim(rid,task_id=tid,kinds=('job_detail',))
            refined=Job('1','Campaign','Actual Subsidiary','https://jobs.example/1',apply_url='https://jobs.example/new',description=parent.description,detail_verified=True,requires_role_split=True)
            s.commit_detail(tid,detail['lease_token'],refined,source_url=refined.job_url,payload=b'refined fixture',origin='fixture')
            current=s.row('jobs',jid)
            self.assertEqual(s.row('companies',current['company_id'])['name'],'Actual Subsidiary')
            self.assertEqual(s.split_campaign(rid,jid,roles,evidence_ref='refined fixture'),[child])
            latest=s.row('jobs',child)
            self.assertEqual(latest['apply_url'],refined.apply_url);self.assertEqual(latest['employer'],refined.employer)
            self.assertEqual(s.latest_user_state('p',latest)['decision'],'declined')

if __name__=='__main__':unittest.main()
