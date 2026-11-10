"""Synthetic contracts from inspected public UI routes, not live coverage proof."""
import json
import unittest
from job_research_engine.domestic import parse_page,parse_detail,request_spec,detect_kind,parse_jobflex_detail,jobflex_request
from job_research_engine.model import EngineError


def encoded(data):return json.dumps(data).encode()


def lg_detail(rows=None,**overrides):
    job={'jobNoticeId':101,'jobNoticeName':'Synthetic campaign','companyName':'Synthetic',
         'recEndDate':'2026.11.12 18:00','isImageFile':'N','applyAvailable':'Y','recAvail':1,'viewFlag':'Y',
         'qualForAppInfo':'Common qualification'}
    job.update(overrides)
    return encoded({'status':'S','data':{'jobNoticesDetail':{'jobNoticesDetail':job,'recList':rows or [
        {'recSectorId':1,'jobGroupName':'Planning','mainTask':'<p>Plan and verify requirements</p>',
         'requiredItem':'Required experience','preferredItem':'Preferred certificate'}]}}})


def hanwha_detail(**overrides):
    item={'rtSeq':201,'rtNm':'Synthetic campaign','sdNm':'Synthetic','rtMdeTp':'FORM',
          'rtAcptEndDttm':'2026.11.13 17:00','rtApplyHidnYn':'N','rtHidnYn':'N','rtHidnKey':None,
          'rtExmQlf':'Common qualification','unitDt':[{'ruSeq':301,'ruNm':'Planning',
           'ruDtlJob':'Plan and verify requirements','ruWorkpl':'Seoul','ruClsYn':'N'}]}
    item.update(overrides)
    return encoded({'success':True,'data':{'item':item}})


class DomesticContracts(unittest.TestCase):
    def test_lg_full_response_keeps_declared_total_for_store_gap_check(self):
        source={'kind':'lgcareers-list','url':'https://careers.lg.com/apply'}
        page=parse_page(source,encoded({'status':'S','data':{'listCount':2,'jobNoticeList':[
            {'jobNoticeId':101,'jobNoticeName':'Synthetic','companyName':'Synthetic',
             'noticeStatus':'POSTING','recAvail':1,'recEndDateTime':'2026.11.12 18:00'}]}}))
        self.assertTrue(page.terminal);self.assertEqual(page.expected_total,2)
        self.assertEqual(len(page.jobs),1);self.assertFalse(page.jobs[0].detail_verified)

    def test_lg_empty_or_denied_contract_is_not_zero_jobs(self):
        for response in ({'status':'F','data':{}},{'status':'S','data':{}},{'status':'S','data':{'listCount':0}}):
            with self.subTest(response=response),self.assertRaises(EngineError):
                parse_page({'kind':'lgcareers-list','url':'https://careers.lg.com/apply'},encoded(response))

    def test_lg_explicit_role_boundaries_keep_required_and_preferred_separate(self):
        payload=lg_detail(rows=[{'recSectorId':1,'jobGroupName':'Planning','mainTask':'Duty A','requiredItem':'Must A'},
                                {'recSectorId':2,'jobGroupName':'Analysis','mainTask':'Duty B','preferredItem':'Prefer B'}])
        job=parse_detail('lgcareers-detail',payload,'https://careers.lg.com/apply/detail?id=101')
        self.assertTrue(job.requires_role_split);self.assertTrue(job.detail_verified)
        self.assertEqual(len(job.raw['role_sections']),2)
        for role in job.raw['role_sections']:self.assertIn(role['source_quote'],job.description)
        self.assertIn('필수사항: Must A',job.description);self.assertIn('우대사항: Prefer B',job.description)
        self.assertEqual(job.deadline['at'],'2026-11-12T18:00:00+09:00')

    def test_lg_mismatched_detail_is_rejected(self):
        with self.assertRaises(EngineError):parse_detail('lgcareers-detail',lg_detail(),'https://careers.lg.com/apply/detail?id=102')

    def test_lg_image_mode_is_not_verified_from_common_qualifications(self):
        job=parse_detail('lgcareers-detail',lg_detail(isImageFile='Y'),'https://careers.lg.com/apply/detail?id=101')
        self.assertFalse(job.detail_verified);self.assertTrue(job.requires_role_split)

    def test_hanwha_pagination_null_later_count_preserves_cursor(self):
        source={'kind':'hanwhain-list','url':'https://www.hanwhain.com/portal/apply/recruit'}
        row={'rtSeq':201,'rtNm':'Synthetic','sdNm':'Synthetic'}
        first=parse_page(source,encoded({'success':True,'data':{'list':[row],'hasNext':True,'totalCount':2,'filteredCount':2}}))
        last=parse_page(source,encoded({'success':True,'data':{'list':[dict(row,rtSeq=202)],'hasNext':False,'totalCount':None,'filteredCount':None}}),'1')
        self.assertEqual(first.next_cursor,'1');self.assertEqual(first.expected_total,2)
        self.assertTrue(last.terminal);self.assertIsNone(last.expected_total)

    def test_hanwha_initial_total_and_has_next_are_required(self):
        source={'kind':'hanwhain-list','url':'https://www.hanwhain.com/portal/apply/recruit'}
        for data in ({'list':[],'hasNext':False},{'list':[],'totalCount':0},{'list':[],'totalCount':1,'hasNext':True}):
            with self.subTest(data=data),self.assertRaises(EngineError):parse_page(source,encoded({'success':True,'data':data}))

    def test_hanwha_form_roles_are_individual_and_closed_unit_preserved(self):
        job=parse_detail('hanwhain-detail',hanwha_detail(unitDt=[
            {'ruSeq':301,'ruNm':'Planning','ruDtlJob':'Duty A','ruClsYn':'N'},
            {'ruSeq':302,'ruNm':'Analysis','ruDtlJob':'Duty B','ruClsYn':'Y'}]),
            'https://www.hanwhain.com/portal/apply/recruit/detail?rtSeq=201')
        self.assertTrue(job.requires_role_split);self.assertTrue(job.detail_verified)
        self.assertEqual(job.raw['role_sections'][1]['recruiting_status'],'closed')
        self.assertIn('returnUrl=%2Fapply%2Frecruit%2Fdetail%3FrtSeq%3D201',job.apply_url)

    def test_hanwha_editor_never_prefers_stale_hidden_unit_template(self):
        job=parse_detail('hanwhain-detail',hanwha_detail(rtMdeTp='EDITOR',
            rtMdeCont='<table><tr><td>Actual editor planning duties</td></tr></table>',
            unitDt=[{'ruSeq':301,'ruNm':'Planning','ruDtlJob':'Stale sales template','ruClsYn':'N'}]),
            'https://www.hanwhain.com/portal/apply/recruit/detail?rtSeq=201')
        self.assertIn('Actual editor planning duties',job.description)
        self.assertNotIn('Stale sales template',job.description)
        self.assertTrue(job.requires_role_split);self.assertEqual(job.raw['role_sections'],[])
        self.assertEqual(job.location,'');self.assertEqual(job.status,'unknown')

    def test_hanwha_poster_and_external_ats_remain_review_work(self):
        job=parse_detail('hanwhain-detail',hanwha_detail(rtMdeTp='EDITOR',
            rtMdeCont='<p>Follow the posting below.</p><a href="https://synthetic.recruiter.co.kr/career/jobs/12"><img src="https://cdn.example.org/poster.png" alt="지원하기"></a>'),
            'https://www.hanwhain.com/portal/apply/recruit/detail?rtSeq=201')
        self.assertFalse(job.detail_verified);self.assertTrue(job.requires_role_split)
        self.assertEqual(job.raw['media_urls'],['https://cdn.example.org/poster.png'])
        self.assertEqual(job.apply_url,'https://synthetic.recruiter.co.kr/career/jobs/12')

    def test_editor_marketing_or_document_link_is_not_application_path(self):
        for target in ('https://example.org/marketing','https://example.org/guide.pdf'):
            job=parse_detail('hanwhain-detail',hanwha_detail(rtMdeTp='EDITOR',rtMdeCont=f'<a href="{target}">Company guide</a>'),
                'https://www.hanwhain.com/portal/apply/recruit/detail?rtSeq=201')
            self.assertIsNone(job.apply_url);self.assertEqual(job.raw['external_detail_urls'],[target])

    def test_hanwha_hidden_detail_is_rejected(self):
        with self.assertRaises(EngineError):parse_detail('hanwhain-detail',hanwha_detail(rtHidnYn='Y'),
            'https://www.hanwhain.com/portal/apply/recruit/detail?rtSeq=201')

    def test_unused_hidden_key_metadata_is_not_consumed_or_persisted(self):
        job=parse_detail('hanwhain-detail',hanwha_detail(rtHidnKey='synthetic-unused-key',rtHidnYn='N'),
            'https://www.hanwhain.com/portal/apply/recruit/detail?rtSeq=201')
        self.assertNotIn('synthetic-unused-key',json.dumps(job.raw))
        self.assertNotIn('synthetic-unused-key',json.dumps(job.content()))

    def test_request_contract_is_exact_ui_source_and_no_hidden_query(self):
        url,body=request_spec('hanwhain-list','https://www.hanwhain.com/portal/apply/recruit','2')
        self.assertTrue(url.endswith('/search-rcrt'));self.assertEqual(body['page'],2);self.assertEqual(body['size'],20)
        url,body=request_spec('lgcareers-detail','https://careers.lg.com/apply/detail?id=101')
        self.assertEqual(body,{'jobNoticeId':101})
        with self.assertRaises(EngineError):request_spec('hanwhain-detail','https://www.hanwhain.com/portal/apply/recruit/detail?rtSeq=201&hidnKey=secret')
        with self.assertRaises(EngineError):request_spec('lgcareers-detail','https://not-official.example.org/apply/detail?id=101')
        self.assertIsNone(detect_kind('https://www.hanwhain.com/portal/login/login'))

    def test_date_only_deadline_does_not_invent_end_of_day(self):
        job=parse_detail('lgcareers-detail',lg_detail(recEndDate='2026.11.12'),'https://careers.lg.com/apply/detail?id=101')
        self.assertEqual(job.deadline,{'kind':'date','date':'2026-11-12','timezone':'Asia/Seoul'})

    def test_plain_title_with_unterminated_ampersand_is_not_lost(self):
        title='Synthetic R&D/QA campaign'
        job=parse_detail('lgcareers-detail',lg_detail(jobNoticeName=title),'https://careers.lg.com/apply/detail?id=101')
        self.assertEqual(job.title,title)

    def test_jobflex_image_only_detail_preserves_actual_apply_url(self):
        data={'title':'Synthetic R&D','jobDescription':'<img src="https://cdn.example.org/poster.png">',
              'endDateTime':'2026-11-12T23:59:59','submissionStatus':'IN_SUBMISSION','writeButtonStatus':'OPEN',
              'applyUrl':'https://synthetic.recruiter.co.kr/v1/applicant/write-resume/login?jobnoticeSn=123&systemKindCode=MRS2'}
        job=parse_jobflex_detail(encoded(data),'https://synthetic.recruiter.co.kr/career/jobs/101',{'employer':'Synthetic'})
        self.assertFalse(job.detail_verified);self.assertTrue(job.requires_role_split)
        self.assertEqual(job.apply_url,data['applyUrl']);self.assertEqual(job.status,'open')
        self.assertEqual(job.deadline['at'],'2026-11-12T23:59:59+09:00')

    def test_jobflex_no_employer_association_or_non_detail_route_is_rejected(self):
        with self.assertRaises(EngineError):parse_jobflex_detail(encoded({'title':'Synthetic','jobDescription':'Duty'}),
            'https://synthetic.recruiter.co.kr/career/jobs/101',{})
        with self.assertRaises(EngineError):jobflex_request('https://synthetic.recruiter.co.kr/v1/applicant/write-resume/login?jobnoticeSn=123')

    def test_jobflex_no_end_date_is_rolling_only_when_explicit(self):
        data={'title':'Synthetic','jobDescription':'Duties','submissionStatus':'POST_SUBMISSION'}
        unknown=parse_jobflex_detail(encoded(data),'https://synthetic.recruiter.co.kr/career/jobs/101',{'employer':'Synthetic'})
        self.assertEqual(unknown.deadline['kind'],'unknown');self.assertEqual(unknown.status,'closed')
        rolling=parse_jobflex_detail(encoded(dict(data,announcementType='ALWAYS')),
            'https://synthetic.recruiter.co.kr/career/jobs/101',{'employer':'Synthetic'})
        self.assertEqual(rolling.deadline['kind'],'rolling')


if __name__=='__main__':unittest.main()
