"""Cards do not erase or refresh a previously read individual role."""
import unittest
from job_research_engine.store import Store
from job_research_engine.model import Job,Page,EngineError

class InventoryDetailTests(unittest.TestCase):
    def setUp(self):
        self.at='2026-11-09T00:00:00+00:00'
        self.s=Store(':memory:',clock=lambda:self.at)
        self.s.set_profile('p',{})
        self.s.import_companies('synthetic',[{'external_id':'1','name':'Example'}],source_url='https://registry.example',scope='fixture',raw_sha256='a'*64,provenance='fixture')
        self.sid=self.s.add_source('host-json','https://jobs.example/list',company_id=None,policy='host_only',evidence_ref='fixture')
        self.run=self.s.plan_run('p',scope_note='fixture')
        self.s.attach_source(self.run,self.sid)
        self.full=Job('1','Planning','Example','https://jobs.example/1',description='Actual complete duties',apply_url='https://jobs.example/1/apply',detail_verified=True,status='open')
        self.jid=self.ingest(self.full,self.run)['job_ids'][0]
        self.assess()
        self.old=self.s.row('jobs',self.jid)

    def tearDown(self):self.s.close()
    def ingest(self,job,run):
        t=self.s.claim(run,source_ids=[self.sid],kinds=('inventory',))
        return self.s.commit_page(t['id'],t['lease_token'],Page([job],True),source_url='https://jobs.example/list',payload=str(job.content()).encode(),origin='fixture')
    def assess(self):
        j=self.s.row('jobs',self.jid)
        return self.s.assess('p',self.jid,decision='recommend',reason='fixture',evidence_ids=[j['latest_observation_id']],expected_profile_revision=1,expected_content_hash=j['content_hash'])
    def repeat(self,title='Planning'):
        self.at='2026-11-09T01:00:00+00:00'
        run=self.s.plan_run('p',scope_note='repeat',parent_run_id=self.run)
        self.s.attach_source(run,self.sid)
        self.ingest(Job('1',title,'Example','https://jobs.example/1'),run)
        return run
    def test_compatible_card_preserves_body_hash_clock_evidence_and_decision(self):
        self.s.user_event('p',event_key='choice',scope_type='job',target_id=self.jid,kind='decision',value='interested',evidence_ref='explicit fixture')
        run=self.repeat()
        self.assertEqual(self.old,self.s.row('jobs',self.jid))
        j=self.s.list_run_jobs(run)[0]
        self.assertTrue(j['seen_this_run']);self.assertFalse(j['detail_observed_this_run'])
        self.assertEqual(j['effective_decision'],'check')
        self.assertEqual(j['user_state']['decision'],'interested')
        self.assertEqual(j['content']['description'],'Actual complete duties')
    def test_changed_card_fences_recommendation_without_destroying_original(self):
        run=self.repeat('Different role title')
        self.assertEqual(self.old,self.s.row('jobs',self.jid))
        j=self.s.list_run_jobs(run)[0]
        self.assertTrue(j['inventory_detail_conflict']);self.assertFalse(j['assessment_current'])
        with self.assertRaises(EngineError):self.assess()
    def test_real_detail_after_card_updates_and_clears_conflict(self):
        run=self.repeat('Different role title')
        self.at='2026-11-09T02:00:00+00:00'
        t=self.s.claim(run,kinds=('job_detail',),source_ids=[self.sid])
        updated=Job('1','Different role title','Example','https://jobs.example/1',description='New actual duties',detail_verified=True,status='open')
        self.s.commit_detail(t['id'],t['lease_token'],updated,source_url=updated.job_url,payload=b'new details',origin='fixture')
        self.assess();j=self.s.list_run_jobs(run)[0]
        self.assertFalse(j['inventory_detail_conflict']);self.assertTrue(j['detail_observed_this_run'])
        self.assertEqual(j['effective_decision'],'recommend')
    def test_actual_cached_detail_is_not_made_older_by_newer_card(self):
        run=self.repeat()
        t=self.s.claim(run,kinds=('job_detail',),source_ids=[self.sid])
        result=self.s.commit_detail(t['id'],t['lease_token'],self.full,source_url=self.full.job_url,payload=b'original captured detail',origin='fixture',observed_at='2026-11-09T00:30:00+00:00')
        self.assertNotIn('stale_ignored',result)
        self.assertEqual(self.s.row('jobs',self.jid)['last_seen'],'2026-11-09T00:30:00.000000+00:00')
    def test_first_body_older_than_card_retains_both_clocks_and_card_changes(self):
        self.at='2026-11-09T02:00:00+00:00'
        run=self.s.plan_run('p',scope_note='repeat');self.s.attach_source(run,self.sid)
        self.ingest(Job('2','Changed card','Example','https://jobs.example/2'),run)
        t=self.s.claim(run,kinds=('job_detail',),source_ids=[self.sid])
        body=Job('2','Earlier body title','Example','https://jobs.example/2',description='Actual older complete body',detail_verified=True)
        result=self.s.commit_detail(t['id'],t['lease_token'],body,source_url=body.job_url,payload=b'captured earlier body',origin='fixture',observed_at='2026-11-09T01:00:00+00:00')
        j=self.s.row('jobs',result['job_id']);self.assertEqual(j['last_seen'],'2026-11-09T01:00:00.000000+00:00')
        self.assertTrue(self.s._inventory_detail_conflict(j));self.assertTrue(j['detail_verified'])
    def test_changed_campaign_card_also_fences_its_preserved_role_children(self):
        child=self.s.split_campaign(self.run,self.jid,[{'role_key':'planning','title':'Planning track','description':'Actual complete duties','source_quote':'Actual complete duties'}],evidence_ref='fixture')[0]
        j=self.s.row('jobs',child)
        self.s.assess('p',child,decision='recommend',reason='fixture',evidence_ids=[j['latest_observation_id']],expected_profile_revision=1,expected_content_hash=j['content_hash'])
        run=self.repeat('Changed campaign')
        current=next(j for j in self.s.list_run_jobs(run) if j['id']==child)
        self.assertTrue(current['inventory_detail_conflict']);self.assertEqual(current['effective_decision'],'check')
        with self.assertRaises(EngineError):self.s.assess('p',child,decision='recommend',reason='fixture',evidence_ids=[j['latest_observation_id']],expected_profile_revision=1,expected_content_hash=j['content_hash'])

if __name__=='__main__':unittest.main()
