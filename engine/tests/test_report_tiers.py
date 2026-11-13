import unittest
from job_research_engine.store import Store
from job_research_engine.model import EngineError,Job,Page
from job_research_engine.report import render,deadline_label
from job_research_engine.runtime import state_signature

class ReportTiers(unittest.TestCase):
    def test_actual_deadline_seconds_survive_report_without_inventing_date_only_time(self):
        self.assertEqual(deadline_label({'kind':'datetime','at':'2030-04-06T23:59:59+09:00'}),'2030-04-06 23:59:59 +0900')
        self.assertEqual(deadline_label({'kind':'datetime','at':'2030-04-06T23:59:00+09:00'}),'2030-04-06 23:59 +0900')
        self.assertEqual(deadline_label({'kind':'datetime','at':'2030-04-06T23:59:59.123000+09:00'}),'2030-04-06 23:59:59.123 +0900')
        self.assertNotIn('23:59',deadline_label({'kind':'date','date':'2030-04-06'}))

    def test_source_gaps_and_future_pools_are_retained_without_becoming_application_advice(self):
        with Store(':memory:') as s:
            s.set_profile('p',{})
            s.import_companies('fixture',[{'external_id':'1','name':'Universe'}],source_url='https://registry.example/list',scope='fixture',raw_sha256='a'*64,provenance='fixture')
            s.add_source('host-json','https://jobs.example/list',company_id=None,policy='host_only',evidence_ref='synthetic')
            rid=s.plan_run('p',scope_note='fixture');task=s.claim(rid)
            jobs=[Job(str(n),'Synthetic '+str(n),'Synthetic','https://jobs.example/'+str(n),description='Observed source body',status='open',detail_verified=True) for n in range(3)]
            ids=s.commit_page(task['id'],task['lease_token'],Page(jobs,True),source_url='https://jobs.example/list',payload=b'fixture',origin='fixture')['job_ids']
            for i,jid in enumerate(ids):
                row=s.row('jobs',jid)
                s.assess('p',jid,decision='recommend' if i==0 else 'check',reason='Synthetic duties reviewed',evidence_ids=[row['latest_observation_id']],expected_profile_revision=1,expected_content_hash=row['content_hash'],report_tier=['actionable','source_gap','future_pool'][i])
            report=render(s,rid)
            self.assertEqual([m['job_id'] for m in report['mapping']],[ids[0]])
            self.assertEqual({j['job_id'] for j in report['coverage']['retained_non_actionable_checks']},set(ids[1:]))
            self.assertEqual(len(s.list_run_jobs(rid)),3)
            with self.assertRaises(EngineError):s.save_report(rid,'Missing recommendation',[],report['coverage'])
            with self.assertRaises(EngineError):s.save_report(rid,'Lost retained gap',report['mapping'],{})
            row=s.row('jobs',ids[0])
            with self.assertRaises(EngineError):s.assess('p',ids[0],decision='recommend',reason='Cannot hide recommendation',evidence_ids=[row['latest_observation_id']],expected_profile_revision=1,expected_content_hash=row['content_hash'],report_tier='source_gap')
            before=state_signature(s,'p',rid)
            s.db.execute("UPDATE assessment_reporting SET report_tier='source_gap' WHERE report_tier='future_pool'")
            self.assertNotEqual(before,state_signature(s,'p',rid))

if __name__=='__main__':unittest.main()
