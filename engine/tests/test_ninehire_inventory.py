import json
import unittest
from copy import deepcopy
from job_research_engine.ninehire import parse_rendered_inventory
from job_research_engine.legacy_sources import parse_ninehire_detail
from job_research_engine.model import EngineError


def detail(active=True,content='<p>Actual synthetic duties</p>',state='in_progress',closed=None,**extra):
    data={'recruitment':{'addressKey':'Abcd1234','title':'Synthetic role','companyName':'Synthetic employer','status':state,'closedAt':closed,'jobPostingIsActive':active,'reception':{'canSubmit':True}},'jobPosting':{'isActive':active,'content':content}}
    data['recruitment'].update(extra)
    return ('<script id="__NEXT_DATA__" type="application/json">'+json.dumps({'props':{'pageProps':data}})+'</script>').encode()


class NinehireInventoryTests(unittest.TestCase):
    def inventory(self):
        return {'actual_end':True,'pages':[{'active':'1','titles':['A','B'],'next_disabled':'false'},{'active':'2','titles':['C'],'next_disabled':'true'}],
            'details':[{'title':title,'url':'https://custom.example/job_posting/'+key} for title,key in [('A','Abcd1234'),('B','Efgh5678'),('C','Ijkl1234')]]}

    def test_text_and_image_publication_off_does_not_assert_recruiting_closed(self):
        for content in ('<p>Actual duties</p>','<img src="https://images.example/poster.png">'):
            with self.subTest(content=content):
                job=parse_ninehire_detail(detail(False,content),'https://custom.example/job_posting/Abcd1234')
                self.assertEqual(job.status,'unknown')
                self.assertFalse(job.source_context['ninehire_source_status']['posting_active'])
                self.assertTrue(job.source_context['ninehire_source_status']['can_submit'])

    def test_explicit_closure_and_verified_open_remain_distinct(self):
        self.assertEqual(parse_ninehire_detail(detail(),'https://custom.example/job_posting/Abcd1234').status,'open')
        self.assertEqual(parse_ninehire_detail(detail(False,state='closed'),'https://custom.example/job_posting/Abcd1234').status,'closed')

    def test_surrounding_text_does_not_prove_image_duties_were_read(self):
        for content in ('<p>Benefits and employment conditions</p><img src="https://images.example/role.png">','<p>General introduction</p><iframe src="https://docs.example/actual-role"></iframe>'):
            job=parse_ninehire_detail(detail(content=content),'https://custom.example/job_posting/Abcd1234')
            self.assertFalse(job.detail_verified)
            self.assertEqual(job.status,'open')
            self.assertIn('host inspection',job.raw['pending_reason'])

    def test_inline_image_remains_reviewable_without_becoming_a_network_url(self):
        job=parse_ninehire_detail(detail(content='<p>Employment conditions</p><img src="data:image/png;base64,cGl4ZWxz">'),'https://custom.example/job_posting/Abcd1234')
        self.assertFalse(job.detail_verified)
        self.assertEqual(job.raw['media_urls'],[])
        self.assertEqual(job.raw['inline_media'][0]['bytes'],6)
        self.assertEqual(len(job.raw['inline_media'][0]['sha256']),64)

    def test_old_closure_with_current_live_flags_requires_review(self):
        job=parse_ninehire_detail(detail(closed='2025-01-01T00:00:00Z'),'https://custom.example/job_posting/Abcd1234')
        self.assertEqual(job.status,'unknown')
        self.assertEqual(job.source_context['ninehire_source_status']['closed_at'],'2025-01-01T00:00:00Z')

    def test_observed_until_filled_and_open_ended_are_not_lost_as_unknown(self):
        for kind in ('until_filled','open_ended'):
            job=parse_ninehire_detail(detail(deadlineType=kind),'https://custom.example/job_posting/Abcd1234')
            self.assertEqual(job.deadline['kind'],'rolling')
            self.assertNotIn('at',job.deadline)

    def test_actual_page_end_and_clicked_paths_reconcile(self):
        page=parse_rendered_inventory(json.dumps(self.inventory()).encode(),'https://custom.example/recruit',{'employer':'Synthetic'})
        self.assertEqual(page.expected_total,3);self.assertTrue(page.inventory_complete)
        self.assertTrue(all(not j.detail_verified for j in page.jobs))

    def test_layout_html_missing_page_and_missing_click_are_gaps(self):
        for data in (b'<html>Homepage layout only</html>',json.dumps({**self.inventory(),'details':[]}).encode(),json.dumps({**self.inventory(),'pages':[self.inventory()['pages'][1]]}).encode()):
            with self.assertRaises(EngineError):parse_rendered_inventory(data,'https://custom.example/recruit',{'employer':'Synthetic'})

    def test_enabled_next_is_not_complete_and_partial_checkpoint_can_resume(self):
        data=self.inventory();data['pages'][-1]['next_disabled']='false'
        with self.assertRaises(EngineError):parse_rendered_inventory(json.dumps(data).encode(),'https://custom.example/recruit',{'employer':'Synthetic'})
        data['actual_end']=False
        self.assertFalse(parse_rendered_inventory(json.dumps(data).encode(),'https://custom.example/recruit',{'employer':'Synthetic'}).inventory_complete)

    def test_duplicate_or_application_path_never_becomes_a_job_detail(self):
        for target in ('https://custom.example/job_posting/Abcd1234','https://custom.example/job_posting/Efgh5678/apply','https://other.example/job_posting/Efgh5678'):
            data=self.inventory();data['details'][1]['url']=target
            with self.assertRaises(EngineError):parse_rendered_inventory(json.dumps(data).encode(),'https://custom.example/recruit',{'employer':'Synthetic'})


if __name__=='__main__':unittest.main()
