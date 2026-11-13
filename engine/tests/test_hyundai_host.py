"""Synthetic adapter tests. These do not prove actual market/AI/browser completion."""
from copy import deepcopy
import unittest
from job_research_engine.model import EngineError
from job_research_engine.hyundai import parse_rendered,identity

URL='https://talent.hyundai.com/apply/applyView.hc?nfGubnC=&recuYy=2022&recuType=N4&recuCls=1001'
def fixture():
    return {'url':URL,'requested_url':URL,'title':'2026년 합성 역할','body_text':'메뉴\n2026년 합성 역할\n채용시까지 2025-01-01 15:45 ~ 채용시까지\n직무상세\n합성 제품 업무\n지원자격\n학사\n추천공고\n2030-10-10 09:00 ~ 2030-10-30 17:00',
        'sections':[{'text':'직무상세\n합성 제품 업무','html':'<dt>직무상세</dt><dd>합성 제품 업무</dd>'},{'text':'지원자격\n3년 이상 필수','html':''},{'text':'우대사항\n6년 이상 우대, 원어민 영어 우대','html':''},{'text':'근무지역\n합성 지역 외 2건','html':''},{'text':'','html':'<dt>비밀번호</dt><dd><input type="password" id="password"><input type="hidden" value=""></dd>'}],
        'images':[],'iframes':[],'buttons':[{'id':'btnApply','label':'지원하기'}],'links':[]}

class HostContract(unittest.TestCase):
    def test_url_identity_survives_title_year_and_rolling_date(self):
        job=parse_rendered(fixture(),single_role_reviewed=True)
        self.assertEqual(job.external_id,'2022:N4:1001');self.assertEqual(job.deadline['kind'],'rolling')
        self.assertEqual(job.published_at,'2025-01-01T15:45:00+09:00')
        self.assertNotIn('2030-10',job.description)
    def test_preferences_and_unexpanded_locations_remain_source_text(self):
        job=parse_rendered(fixture(),single_role_reviewed=True)
        self.assertEqual(job.source_context['role_sections']['지원자격'],'3년 이상 필수')
        self.assertEqual(job.source_context['role_sections']['우대사항'],'6년 이상 우대, 원어민 영어 우대')
        self.assertEqual(job.location,'합성 지역 외 2건')
    def test_blank_password_modal_is_never_role_content(self):
        job=parse_rendered(fixture(),single_role_reviewed=True)
        self.assertNotIn('password',job.description);self.assertNotIn('비밀번호',job.description)
    def test_no_per_job_application_verification_is_invented(self):
        job=parse_rendered(fixture(),single_role_reviewed=True)
        self.assertIsNone(job.apply_url)
        self.assertFalse(job.source_context['application_start_evidence']['actual_apply_url_verified'])
        self.assertTrue(job.source_context['application_start_evidence']['visible_button'])
    def test_media_needs_real_independent_review(self):
        r=fixture();src='https://talent.hyundai.com/hrecu/synthetic-poster.png';r['images']=[{'src':src,'alt':''}]
        job=parse_rendered(r,single_role_reviewed=True);self.assertFalse(job.detail_verified)
        verified=parse_rendered(r,visual_reviewed_urls={src},single_role_reviewed=True);self.assertTrue(verified.detail_verified)
    def test_single_role_review_not_assumed(self):
        self.assertTrue(parse_rendered(fixture()).requires_role_split)
    def test_no_recommendation_period_fallback(self):
        r=fixture();r['body_text']=r['body_text'].replace('채용시까지 2025-01-01 15:45 ~ 채용시까지\n','')
        with self.assertRaises(EngineError):parse_rendered(r)
    def test_no_mismatched_or_queue_identity(self):
        r=fixture();r['requested_url']=URL.replace('1001','1002')
        with self.assertRaises(EngineError):parse_rendered(r)
        with self.assertRaises(EngineError):identity(URL.replace('nfGubnC=','nfGubnC=Y'))
        with self.assertRaises(EngineError):identity(URL+'&recuCls=1001')
    def test_conflicting_role_sections_block(self):
        r=fixture();r['sections'].append({'text':'지원자격\n다른 조건','html':''})
        with self.assertRaises(EngineError):parse_rendered(r)
    def test_image_only_or_queue_shell_is_not_verified(self):
        r=fixture();r['sections']=[{'text':'','html':'<img src="/hrecu/synthetic.png">'}]
        with self.assertRaises(EngineError):parse_rendered(r)

if __name__=='__main__':unittest.main(verbosity=2)
