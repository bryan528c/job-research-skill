"""Synthetic boundary tests; live branch collection is recorded privately."""
import json
import unittest

from job_research_engine.legacy_sources import (
    detect_kind, gabia_office_no, gabia_public_request, parse_detail,
    parse_gabia_detail, parse_gabia_list, parse_ninehire_detail, parse_page,
)
from job_research_engine.model import EngineError


def envelope(data):
    return json.dumps({'data': data}).encode()


def announcement(**updates):
    row = {'announce_id': 'abc123', 'announce_name': 'Synthetic planning',
           'announce_type': 'PUB', 'experience': 'NEW',
           'apply_start_date': '2026-10-26 00:00:00',
           'apply_finish_date': '2026-11-15 23:59:00',
           'description': '<p>Intern starts January 2027. Plan product requirements.</p>',
           'category_position': [{'category_name': 'Planning'}]}
    row.update(updates)
    return row


def ninehire(content, **updates):
    recruitment = {'addressKey': 'AbCd1234', 'title': 'Synthetic campaign',
                   'companyName': 'Synthetic', 'jobPostingIsActive': True,
                   'status': 'in_progress', 'reception': {'canSubmit': True,
                   'endAt': '2026-11-22T14:59:59Z'}, 'recruitmentId': 'synthetic-public-id'}
    recruitment.update(updates)
    data = {'props': {'pageProps': {'recruitment': recruitment, 'jobPosting': {'content': content}}}}
    return ('<script id="__NEXT_DATA__" type="application/json">'+json.dumps(data)+'</script>').encode()


class LegacySourceContracts(unittest.TestCase):
    URL = 'https://recruit.gabia.com/recruit/view/abc123'
    AT = '2026-11-09T08:00:00Z'

    def test_exact_anonymous_requests_never_need_applicant_credentials(self):
        first = gabia_public_request('site-information')
        self.assertEqual(first['headers'], {'x-career-site-domain': 'gabia.com'})
        self.assertEqual(gabia_office_no(envelope({'office_no': 1})), 1)
        detail = gabia_public_request('gabia-detail', self.URL, office_no=1)
        self.assertTrue(detail['url'].endswith('/offices/1/announces/abc123'))
        self.assertEqual(detail['method'], 'GET'); self.assertEqual(detail['headers'], {})
        for number in (True, '1', 0):
            with self.assertRaises(EngineError):gabia_public_request('gabia-detail', self.URL, office_no=number)

    def test_old_encrypted_or_foreign_round_is_not_mapped_to_current_key(self):
        for url in ('https://careers.gabia.com/recruit/view/?seq=old-round',
                    'https://example.org/recruit/view/abc123', self.URL+'?token=secret'):
            with self.assertRaises(EngineError):gabia_public_request('gabia-detail', url, office_no=1)

    def test_shell_and_denied_response_are_not_empty_inventory(self):
        for payload in (b'<html><body></body></html>', b'{"error":"denied"}', envelope({})):
            with self.assertRaises(EngineError):parse_gabia_list(payload, as_of=self.AT)
        page = parse_gabia_list(envelope([]), as_of=self.AT)
        self.assertTrue(page.terminal);self.assertEqual(page.expected_total, 0)

    def test_full_array_total_and_distinct_round_ids_survive(self):
        page = parse_gabia_list(envelope([announcement(), announcement(announce_id='def456')]), as_of=self.AT)
        self.assertEqual(page.expected_total, 2);self.assertEqual(len(page.jobs), 2)
        self.assertTrue(all(not job.detail_verified for job in page.jobs))
        with self.assertRaises(EngineError):parse_gabia_list(envelope([announcement(), announcement()]), as_of=self.AT)

    def test_array_dispatch_rejects_fake_pagination_or_unknown_provider(self):
        source={'kind':'gabia-list','url':'https://recruit.gabia.com/recruit/jobs','settings_json':'{}'}
        self.assertEqual(parse_page(source,envelope([announcement()]),as_of=self.AT).expected_total,1)
        with self.assertRaises(EngineError):parse_page(source,envelope([]),'2',as_of=self.AT)
        with self.assertRaises(EngineError):parse_page(dict(source,kind='ninehire-list'),envelope([]),as_of=self.AT)

    def test_description_and_real_future_start_are_preserved(self):
        job = parse_gabia_detail(envelope(announcement()), self.URL, as_of=self.AT)
        self.assertIn('January 2027', job.description); self.assertEqual(job.status, 'open')
        self.assertTrue(job.detail_verified);self.assertIsNone(job.apply_url)
        self.assertEqual(job.deadline['at'], '2026-11-15T23:59:00+09:00')

    def test_past_round_remains_closed_and_date_only_does_not_invent_clock(self):
        job = parse_gabia_detail(envelope(announcement(apply_start_date='2025-10-26 00:00:00',
                                apply_finish_date='2025-11-15 23:59:00')), self.URL, as_of=self.AT)
        self.assertEqual(job.status, 'closed')
        job = parse_gabia_detail(envelope(announcement(apply_finish_date='2026-11-15')), self.URL, as_of=self.AT)
        self.assertEqual(job.deadline['kind'], 'date');self.assertEqual(job.status, 'unknown')

    def test_mismatched_identity_or_naive_observation_fails(self):
        with self.assertRaises(EngineError):parse_gabia_detail(envelope(announcement(announce_id='xyz987')), self.URL, as_of=self.AT)
        with self.assertRaises(EngineError):parse_gabia_detail(envelope(announcement()), self.URL, as_of='2026-11-09T08:00:00')

    def test_image_only_and_multiple_roles_keep_explicit_review_boundary(self):
        job = parse_gabia_detail(envelope(announcement(description='<img src="https://cdn.example.org/poster.png">')), self.URL, as_of=self.AT)
        self.assertFalse(job.detail_verified);self.assertTrue(job.requires_role_split)
        self.assertEqual(job.raw['media_urls'], ['https://cdn.example.org/poster.png'])
        job = parse_gabia_detail(envelope(announcement(category_position=[{}, {}])), self.URL, as_of=self.AT)
        self.assertTrue(job.requires_role_split)

    def test_apply_url_is_stored_only_when_observed_for_actual_detail(self):
        target = 'https://recruit.gabia.com/recruit/abc123/signup'
        job = parse_gabia_detail(envelope(announcement()), self.URL, {'observed_apply_url':target}, as_of=self.AT)
        self.assertEqual(job.apply_url, target)
        with self.assertRaises(EngineError):
            parse_gabia_detail(envelope(announcement()), self.URL,
                               {'observed_apply_url':'https://recruit.gabia.com/recruit/wrong1/signup'}, as_of=self.AT)

    def test_ninehire_image_campaign_keeps_open_status_and_original_media(self):
        payload = ninehire('<img src="https://cdn.example.org/full-poster.jpg"><a href="https://example.org/benefits">Benefits</a>')
        job = parse_ninehire_detail(payload, 'https://career.example.org/job_posting/AbCd1234')
        self.assertFalse(job.detail_verified);self.assertTrue(job.requires_role_split)
        pending = parse_ninehire_detail(ninehire('<img src="https://cdn.example.org/full-poster.jpg">'), 'https://career.example.org/job_posting/AbCd1234')
        self.assertFalse(pending.detail_verified);self.assertTrue(pending.requires_role_split)
        self.assertEqual(pending.status, 'open');self.assertEqual(pending.raw['media_urls'], ['https://cdn.example.org/full-poster.jpg'])
        self.assertIn('https://example.org/benefits', job.raw['external_detail_urls'])

    def test_ninehire_wrong_detail_is_not_accepted(self):
        with self.assertRaises(EngineError):parse_ninehire_detail(ninehire('<p>Actual duty</p>'), 'https://career.example.org/job_posting/WrongKey')

    def test_ninehire_affiliation_is_not_an_employer(self):
        payload=ninehire('<p>Actual duty</p>', affiliation={'title':'Synthetic Quality Division'})
        job=parse_ninehire_detail(payload,'https://career.example.org/job_posting/AbCd1234')
        self.assertEqual(job.employer,'Synthetic')
        self.assertEqual(job.raw['affiliation']['title'],'Synthetic Quality Division')

    def test_greeting_image_pending_preserves_structured_career_not_title_guess(self):
        props = {'dehydratedState': {'queries': [{'queryKey':['getOpeningById'], 'state': {'data': {
            'success':True, 'data': {'openingsInfo': {'openingId':123, 'title':'Synthetic',
            'detail':'<img src="https://cdn.example.org/poster.png">', 'status':'OPEN'},
            'groupInfo':{'name':'Synthetic'}, 'jobPositionSetting':{'jobPositions':[
            {'id':77, 'jobPositionCareer':{'careerType':'NOT_MATTER'},
             'jobPositionEmployment':{'employmentType':'FULL_TIME_WORKER'},
             'workspacePlace':{'location':'Synthetic city'}}]}}}}}]}}
        payload = ('<script id="__NEXT_DATA__">'+json.dumps({'props':{'pageProps':props}})+'</script>').encode()
        job = parse_detail('legacy-greeting-detail', payload, 'https://synthetic.career.greetinghr.com/ko/o/123')
        self.assertFalse(job.detail_verified);self.assertTrue(job.requires_role_split)
        self.assertEqual(job.location,'Synthetic city')
        self.assertEqual(job.raw['source_positions'][0]['career']['careerType'],'NOT_MATTER')


if __name__ == '__main__':
    unittest.main()
