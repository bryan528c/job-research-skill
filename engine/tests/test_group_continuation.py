"""Synthetic anonymous group-site contracts, separate from real market results."""
import json
import unittest
from job_research_engine.groups import CJ,DOOSAN,cj_request,parse_cj_page,parse_cj_detail,parse_doosan_page,parse_doosan_detail
from job_research_engine.model import EngineError

def cjrow(i,**kwargs):
    return dict(zz_jo_num=str(i),gubun='1',tot_cnt=12,zz_title='Synthetic duty',compnm='Synthetic employer',zz_close_yn='N',zz_open_yn='Y',zz_till_hire='N',zz_end_dt_str='2026.11.12',zz_end_hh='17',zz_end_mi='05',**kwargs)

class GroupContracts(unittest.TestCase):
    def test_greeting_company_place_label_is_separate_from_address_and_career(self):
        from job_research_engine.korean import parse_detail
        data={'groupInfo':{'name':'Synthetic employer'},'openingsInfo':{'openingId':123,'title':'Actual role','status':'OPEN','detail':'<p>Actual duties; four years or equivalent competence. English preferred.</p>'},
              'jobPositionSetting':{'jobPositions':[{'id':5,'workspacePlace':{'location':'Synthetic employer','place':'대한민국 서울특별시 용산구'},'jobPositionCareer':{'careerType':'EXPERIENCED','careerFrom':4,'careerTo':None},'jobPositionEmployment':{'employmentType':'FULL_TIME_WORKER'}}]}}
        raw=('<script id="__NEXT_DATA__">'+json.dumps({'props':{'pageProps':{'dehydratedState':{'queries':[{'queryKey':['getOpeningById',123],'state':{'data':{'success':True,'data':data}}}]}}}})+'</script>').encode()
        job=parse_detail('greeting-detail',raw,'https://careers.example/ko/o/123',{})
        self.assertEqual(job.location,'대한민국 서울특별시 용산구')
        meta=job.source_context['position_metadata'][0]
        self.assertEqual(meta['place_label'],'Synthetic employer')
        self.assertEqual(meta['career']['careerFrom'],4)
        self.assertEqual(meta['employment_type'],'FULL_TIME_WORKER')
        self.assertIn('or equivalent competence',job.description)

    def cj_detail(self,body):
        return ('''<div id="contents"><div class="tit-wrap view"><p class="title">Exact role</p><p class="company">Synthetic</p><ul class="meta-info"><li><span class="closing">D-2</span>2026.11.01 ~ 2026.11.12</li><li>경력</li></ul></div><button onclick="copyUrl('123');return false;">Copy</button><ul class="detail-list">'''+body+'''</ul><div>Unrelated privacy popup cannot verify an image role</div></div>''').encode()

    def test_cj_link_only_poster_stays_unverified_with_downstream_branch(self):
        job=parse_cj_detail(self.cj_detail('<li><h3>직무소개</h3><img src="data:image/png;base64,c3ludGhldGlj"><img src="https://media.example/poster.png"><a href="https://careers.example/jobs">공고리스트</a></li>'),CJ+'detail.fo?zz_jo_num=123')
        self.assertFalse(job.detail_verified);self.assertTrue(job.requires_role_split)
        self.assertEqual(job.raw['external_detail_urls'],['https://careers.example/jobs']);self.assertIsNone(job.apply_url)
        self.assertEqual(job.raw['embedded_image_count'],1)

    def test_cj_same_round_clock_is_kept_without_nesting_source_context_on_repeat(self):
        body=self.cj_detail('<li><h3>직무소개</h3><p>Actual individual duties, required five years, English preferred.</p></li>')
        previous={'external_id':'123','deadline':{'kind':'datetime','at':'2026-11-12T17:05:00+09:00'},'source_context':{'gubun':'1','zz_target_1':'B'}}
        job=parse_cj_detail(body,CJ+'detail.fo?zz_jo_num=123',{'listing_job':previous})
        repeated=parse_cj_detail(body,job.job_url,{'listing_job':job.content()})
        self.assertTrue(job.detail_verified);self.assertTrue(job.requires_role_split)
        self.assertEqual(job.deadline,previous['deadline']);self.assertEqual(job.source_context,repeated.source_context)
        with self.assertRaises(EngineError):parse_cj_detail(body,CJ+'detail.fo?zz_jo_num=124')

    def test_cj_public_get_filters_cannot_become_applicant_queries(self):
        self.assertIn('pageVal=2',cj_request(CJ+'list.fo','2'))
        for settings in ({'filters':{'user_seq':'private'}},{'filters':{'sch_title':object()}}):
            with self.assertRaises(EngineError):cj_request(CJ+'list.fo',settings=settings)
        with self.assertRaises(EngineError):cj_request(CJ+'resume.fo')

    def test_cj_sidebar_retains_explicit_employment_and_exact_role(self):
        sidebar='<div class="floating-box"><ul class="info-list"><li><strong class="label">직무명</strong>Exact individual duty</li><li><strong class="label">근무형태</strong><span>정규직</span></li><li><strong class="label">채용구분</strong>경력</li><li><strong class="label">근무지</strong>서울</li></ul></div>'
        raw=self.cj_detail('<li>Actual duties, English preferred</li>')+sidebar.encode()
        # In the observed site this metadata belongs to the contents container.
        raw=raw.replace(b'</div><div class="floating-box">',b'<div class="floating-box">')+b'</div>'
        job=parse_cj_detail(raw,CJ+'detail.fo?zz_jo_num=123')
        self.assertEqual(job.source_context['header_fields']['근무형태'],'정규직')
        self.assertEqual(job.source_context['header_fields']['직무명'],'Exact individual duty')
        self.assertEqual(job.location,'서울')

    def test_cj_login_route_must_match_visible_cta_and_anonymous_posting(self):
        login='https://recruit.cj.net/recruit/ko/member/login/login.fo?returnUrl='+CJ+'bestDetail.fo?zz_jo_num=123'
        support='''<button onclick="applyRecruit('123','Y');">지원하기</button><script>function applyRecruit(seq, agrYn) {var w_ko_g_user_seq = "";if (w_ko_g_user_seq == "") {window.location.href = "'''+login+'''";}else{transaction(privateApplicantStatus);}}</script>'''
        raw=self.cj_detail('<li>Actual individual duties</li>')+support.encode()
        job=parse_cj_detail(raw,CJ+'detail.fo?zz_jo_num=123')
        self.assertEqual(job.apply_url,login)
        for changed in (raw.replace(b'zz_jo_num=123"',b'zz_jo_num=999"'),raw.replace(b'var w_ko_g_user_seq = ""',b'var w_ko_g_user_seq = "member"'),raw.replace(b"applyRecruit('123','Y');",b"submitApplication('123','Y');")):
            self.assertIsNone(parse_cj_detail(changed,job.job_url).apply_url)

    def test_cj_pages_use_declared_total_and_actual_job_routes_and_time(self):
        first=parse_cj_page(json.dumps({'ErrorCode':0,'ds_newRecruitList':[cjrow(i) for i in range(10)]}).encode())
        self.assertFalse(first.terminal);self.assertEqual(first.next_cursor,'2');self.assertEqual(first.expected_total,12)
        self.assertEqual(first.jobs[0].deadline['at'],'2026-11-12T17:05:00+09:00')
        row=cjrow('J20261101');row.update(gubun='2',zz_till_hire='Y')
        last=parse_cj_page(json.dumps({'ErrorCode':'0','ds_newRecruitList':[cjrow(10),row]}).encode(),'2')
        self.assertTrue(last.terminal);self.assertEqual(last.jobs[1].deadline,{'kind':'rolling'})
        self.assertEqual(last.jobs[1].job_url,CJ+'bestDetail.fo?direct=N&zz_jo_num=J20261101')
        self.assertIsNone(last.jobs[1].apply_url)

    def test_cj_empty_and_inconsistent_totals_are_not_completed_inventories(self):
        for rows in ([],[cjrow(1),{**cjrow(2),'tot_cnt':13}]):
            with self.assertRaises(EngineError):parse_cj_page(json.dumps({'ErrorCode':0,'ds_newRecruitList':rows}).encode())

    def list_html(self,paging=''):
        return ('''<a class="list-tit" onclick="goDetail('123', 'PUBLIC', 'CAREER', 'COMPANY');"><div class="company">Synthetic employer<span class="badge-type">경력</span></div><strong>Actual title</strong><div class="deadline">2026-11-01 ~ 2026-11-12</div></a><ul class="pagination"><strong>1</strong>'''+paging+'</ul>').encode()

    def test_doosan_requires_end_control_and_preserves_display_career_separately(self):
        page=parse_doosan_page(self.list_html());self.assertTrue(page.inventory_complete)
        job=page.jobs[0];self.assertEqual(job.employer,'Synthetic employer')
        self.assertEqual(job.source_context['career_label'],'경력')
        self.assertEqual(job.job_url,DOOSAN+'?REC_ID=123&mode=goDetail')
        self.assertEqual(job.deadline['kind'],'date')
        self.assertFalse(parse_doosan_page(self.list_html('<a onclick="nextPage(2)">2</a>')).inventory_complete)
        with self.assertRaises(EngineError):parse_doosan_page(self.list_html().replace(b'pagination',b'unknown'))

    def test_doosan_inert_navigation_rejects_script_side_effects(self):
        with self.assertRaises(EngineError):parse_doosan_page(self.list_html().replace(b"goDetail('123'",b"sendApplication('123'"))

    def test_doosan_individual_duties_keep_common_requirements_and_observed_status(self):
        body='''<input name="REC_ID" value="123"><h2 class="h2-title">Mixed campaign</h2><div class="view-list-wrap"><ul class="tb-con-res"><li><dl><dt>자회사/BG</dt><dd>Synthetic employer</dd></dl><dl><dt>모집분야</dt><dd>Role A</dd></dl><dl><dt>수행업무/전공/자격요건</dt><dd>Develop systems; required five years; English preferred</dd></dl></li></ul></div><table><tr><th>자격요건</th><td>Common verified requirement</td></tr><tr><th>진행상태</th><td>접수중(~2026.11.12)</td></tr></table>'''.encode()
        job=parse_doosan_detail(body,DOOSAN+'?REC_ID=123&mode=goDetail')
        self.assertTrue(job.detail_verified);self.assertEqual(job.status,'open');self.assertIsNone(job.apply_url)
        role=job.raw['role_sections'][0]
        self.assertIn('required five years',role['description']);self.assertIn('Common verified requirement',role['description'])
        self.assertIn(role['source_quote'],job.description)
        continuation='''<ul class="tb-con-res"><li><dl><dt>자회사/BG</dt><dd>Synthetic employer</dd></dl><dl><dt>모집분야</dt><dd></dd></dl><dl><dt>수행업무/전공/자격요건</dt><dd>Required continuation, not a second vacancy</dd></dl></li></ul>'''.encode()
        continued=parse_doosan_detail(body.replace(b'</div><table>',continuation+b'</div><table>'),job.job_url)
        self.assertEqual(len(continued.raw['role_sections']),1)
        self.assertIn('Required continuation',continued.description)
        self.assertIn('Required continuation',continued.raw['role_sections'][0]['description'])
        with self.assertRaises(EngineError):parse_doosan_detail(body,DOOSAN+'?REC_ID=124&mode=goDetail')

if __name__=='__main__':unittest.main()
