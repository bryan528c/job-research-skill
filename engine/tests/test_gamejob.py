"""Synthetic HTML; actual public-site reads are recorded outside Git."""
from dataclasses import replace
import unittest
from job_research_engine.gamejob import parse_detail,description_frame,with_descriptions,posting_id,discovery_page
from job_research_engine.korean import detect_kind
from job_research_engine.model import EngineError
from job_research_engine.store import Store
from job_research_engine.transport import Response,FetchError
from job_research_engine.worker import collect

URL='https://gamejob.co.kr/Recruit/GI_Read/View?GI_No=12345'
OUTER='''<div class="view__header-title"><div class="corp-name">Synthetic Studio</div><h1>Development PM</h1></div>
<article class="content__recruit-data"><dl><dt>경력</dt><dd>무관</dd></dl>
<dl><dt>고용형태</dt><dd>정규직</dd></dl><dl><dt>마감일</dt><dd>채용시 마감</dd></dl>
<input value="지원하기"></article>
<iframe src="/Recruit/GI_Read_Comt_Ifrm?gno=12345&v1" title="담당업무"></iframe>
<iframe src="/Recruit/GI_Read_GI_Comment_Ifrm?gno=12345&v1" title="자격요건"></iframe>'''.encode()
DUTIES=b'<html><body><h2>Duties</h2><p>Coordinate milestones and automation.</p></body></html>'
REQUIRED=b'<html><body><h2>Requirements</h2><p>Personal projects accepted; no required tenure.</p></body></html>'

class GameJobTests(unittest.TestCase):
    def test_category_navigation_never_starves_actual_posting_details_or_proves_exhaustion(self):
        url='https://www.gamejob.co.kr/Recruit/joblist?duty=25&menucode=duty'
        payload=b'''<a href="/Recruit/Main">Home</a><a href="/Recruit/joblist?genre=8">Other category</a>
        <a href="/Recruit/GI_Read/View?GI_No=12345">Planning</a><a href="/Recruit/GI_Read/View?GI_No=12345">Duplicate</a>
        <a href="/Recruit/Apply?GI_No=12345">Apply</a>'''
        page=discovery_page(payload,url)
        self.assertEqual(detect_kind(url),'gamejob-list')
        self.assertEqual(page.discovered_urls,['https://www.gamejob.co.kr/Recruit/GI_Read/View?GI_No=12345'])
        self.assertFalse(page.inventory_complete)
        self.assertEqual(page.jobs,[])
    def test_detail_is_individual_discovery_with_both_unread_frames(self):
        job=parse_detail(OUTER,URL)
        self.assertEqual(detect_kind(URL),'gamejob-detail')
        self.assertEqual(job.employer,'Synthetic Studio')
        self.assertEqual(job.status,'open')
        self.assertEqual(job.deadline['kind'],'rolling')
        self.assertEqual(job.source_context['source_fields']['경력'],'무관')
        self.assertFalse(job.detail_verified)
        self.assertIsNone(job.apply_url)
        self.assertEqual(len(job.source_context['observed_description_frames']),2)

    def test_qualification_frame_is_required_and_images_stay_unreviewed(self):
        job=parse_detail(OUTER,URL);frames=job.source_context['observed_description_frames']
        a=description_frame(DUTIES,frames[0]['url'],job.external_id)
        b=description_frame(REQUIRED,frames[1]['url'],job.external_id)
        full=with_descriptions(job,[a,b],['outer','duties','requirements'])
        self.assertTrue(full.detail_verified)
        self.assertIn('no required tenure',full.description)
        with self.assertRaises(EngineError):with_descriptions(job,[a],['outer','duties'])
        b=description_frame(REQUIRED.replace(b'</body>',b'<img src="https://media.example/requirements.png"></body>'),frames[1]['url'],job.external_id)
        self.assertFalse(with_descriptions(job,[a,b],['outer','duties','requirements']).detail_verified)

    def test_other_round_or_application_routes_are_never_read_contracts(self):
        self.assertIsNone(posting_id(URL+'&submit=true'))
        self.assertIsNone(posting_id('https://gamejob.co.kr/Recruit/apply?GI_No=12345'))
        for target in ['https://gamejob.co.kr/Recruit/GI_Read_Comt_Ifrm?gno=9',
                       'https://gamejob.co.kr/Recruit/Apply?gno=12345',
                       'https://other.example/Recruit/GI_Read_Comt_Ifrm?gno=12345']:
            with self.assertRaises(EngineError):description_frame(DUTIES,target,'12345')
        with self.assertRaises(EngineError):parse_detail(OUTER.replace(b'gno=12345',b'gno=9'),URL)

    def test_explicit_closure_and_access_denial_are_separate(self):
        closed=parse_detail(OUTER.replace('채용시 마감'.encode(),'접수가 마감되었습니다'.encode()),URL)
        self.assertEqual(closed.status,'closed')
        with self.assertRaises(EngineError):parse_detail(b'<html>Forbidden</html>',URL)
        with self.assertRaises(EngineError):description_frame(b'<body>Access Denied</body>',
            'https://gamejob.co.kr/Recruit/GI_Read_Comt_Ifrm?gno=12345','12345')

    def test_actual_worker_saves_separate_frame_observations_and_idempotent_job(self):
        with Store(':memory:') as s:
            s.set_profile('p',{})
            s.import_companies('fixture',[{'external_id':'1','name':'Synthetic'}],source_url='https://registry.example/list',
                scope='fixture',raw_sha256='a'*64,provenance='fixture')
            sid=s.add_source('gamejob-detail',URL,company_id=None,policy='robots',evidence_ref='synthetic supplied detail')
            rid=s.plan_run('p',scope_note='synthetic');s.attach_source(rid,sid)
            class Read:
                evidence_origin='fixture'
                calls=[]
                def permitted_by_robots(self,url):return True
                def get(self,url,**kw):
                    self.calls.append(url)
                    body=OUTER if '/View?' in url else REQUIRED if 'GI_Comment' in url else DUTIES
                    return Response(url,200,{'content-type':'text/html'},body)
            transport=Read()
            result=collect(s,rid,transport=transport,include_details=True,source_ids=[sid])
            self.assertEqual(result['blocked_or_failed_attempts'],0)
            jobs=s.list_run_jobs(rid)
            self.assertEqual(len(jobs),1)
            self.assertTrue(jobs[0]['detail_verified'])
            self.assertEqual(len(transport.calls),3)
            self.assertEqual(s.db.execute('SELECT COUNT(DISTINCT source_url) FROM observations').fetchone()[0],3)
            self.assertIn('Personal projects accepted',jobs[0]['content']['description'])
            self.assertEqual(collect(s,rid,transport=transport,include_details=True,source_ids=[sid])['pages_committed'],0)

if __name__=='__main__':unittest.main()
