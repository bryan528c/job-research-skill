import unittest
from job_research_engine.report import deadline_label,past_deadline,posting_link_label

class DeadlineZoneTests(unittest.TestCase):
    def test_korean_display_converts_actual_utc_to_next_day_without_losing_seconds(self):
        d={'kind':'datetime','at':'2026-11-10T15:00:01.250Z'}
        self.assertEqual(deadline_label(d,'Asia/Seoul'),'2026-11-11 00:00:01.25 +0900')
        self.assertFalse(past_deadline(d,'2026-11-10T15:00:01.200Z','Asia/Seoul'))
        self.assertTrue(past_deadline(d,'2026-11-10T15:00:01.251Z','Asia/Seoul'))
    def test_korean_morning_date_only_is_not_midnight_or_previous_utc_day(self):
        d={'kind':'date','date':'2026-11-11'}
        self.assertEqual(deadline_label(d,'Asia/Seoul'),'2026-11-11 · 마감 시각 미기재')
        self.assertFalse(past_deadline(d,'2026-11-10T22:00:00Z','Asia/Seoul'))
        self.assertTrue(past_deadline(d,'2026-11-11T15:00:00Z','Asia/Seoul'))
    def test_official_and_platform_destinations_are_not_conflated(self):
        self.assertEqual(posting_link_label('https://m.jobkorea.co.kr/Recruit/GI_Read/123',{'posting_link_kind':'official'}),'외부 플랫폼 상세')
        self.assertEqual(posting_link_label('https://company.example/campaign',{'posting_link_kind':'official_campaign'}),'공식 공채 상세')
        self.assertEqual(posting_link_label('https://unknown.example/123',{}),'공고 상세')

if __name__=='__main__':unittest.main()
