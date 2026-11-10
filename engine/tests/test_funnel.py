import unittest
from datetime import datetime,timezone
from job_research_engine.store import Store
from job_research_engine.model import Job,Page,EngineError
from job_research_engine.report import render
from job_research_engine.funnel import candidate_audit


class FunnelTests(unittest.TestCase):
    def setUp(self):
        self.at=datetime(2030,1,1,tzinfo=timezone.utc)
        self.s=Store(':memory:',clock=lambda:self.at.isoformat())
        self.s.set_profile('p',{})
        self.s.import_companies('fixture',[{'external_id':'1','name':'Universe'}],source_url='https://registry.example/list',scope='fixture',raw_sha256='a'*64,provenance='fixture')
        self.source=self.s.add_source('host-json','https://jobs.example/list',company_id=None,policy='host_only',evidence_ref='synthetic')
        self.rid=self.s.plan_run('p',scope_note='fixture')

    def tearDown(self):self.s.close()

    def test_unknown_collection_and_evaluation_never_count_as_exclusion(self):
        task=self.s.claim(self.rid)
        jobs=[Job('1','Title only','Synthetic','https://jobs.example/1'),
              Job('2','Observed duties','Synthetic','https://jobs.example/2',description='Actual duties',detail_verified=True)]
        self.s.commit_page(task['id'],task['lease_token'],Page(jobs,True),source_url='https://jobs.example/list',payload=b'fixture',origin='fixture')
        result=candidate_audit(self.s,self.rid,page_size=1)
        self.assertEqual(result['stage_counts'],{'assessment_missing_or_stale':1,'detail_or_role_gap':1})
        self.assertTrue(result['has_more']);self.assertEqual(result['exclusion_reason_groups'],[])
        second=candidate_audit(self.s,self.rid,after=result['next_cursor'],page_size=1)
        self.assertFalse(second['has_more']);self.assertNotEqual(result['items'][0]['job_id'],second['items'][0]['job_id'])

    def test_future_opening_fenced_and_recheck_survives_new_run(self):
        task=self.s.claim(self.rid)
        job=Job('1','Upcoming','Synthetic','https://jobs.example/1',description='Actual duties',detail_verified=True,application_opens_at='2030-01-02T12:00:00+09:00')
        jid=self.s.commit_page(task['id'],task['lease_token'],Page([job],True),source_url='https://jobs.example/list',payload=b'fixture',origin='fixture')['job_ids'][0]
        row=self.s.row('jobs',jid)
        kwargs=dict(reason='Synthetic review',evidence_ids=[row['latest_observation_id']],expected_profile_revision=1,expected_content_hash=row['content_hash'])
        with self.assertRaises(EngineError):self.s.assess('p',jid,decision='recommend',**kwargs)
        self.s.assess('p',jid,decision='check',report_tier='upcoming',**kwargs)
        self.assertEqual(candidate_audit(self.s,self.rid)['stage_counts'],{'application_not_open_yet':1})
        self.assertIsNone(self.s.claim(self.rid,kinds=('job_detail',)))
        report=render(self.s,self.rid);self.assertEqual(report['mapping'],[])
        self.assertEqual(report['coverage']['retained_non_actionable_checks'][0]['job_id'],jid)
        repeat=self.s.plan_run('p',scope_note='repeat')
        self.assertIsNone(self.s.claim(repeat,kinds=('job_detail',)))
        self.at=datetime(2030,1,2,3,0,tzinfo=timezone.utc)
        self.assertIsNotNone(self.s.claim(repeat,kinds=('job_detail',)))
        self.assertNotEqual(self.s.row('tasks',self.s.db.execute("SELECT id FROM tasks WHERE run_id=? AND kind='job_detail'",(repeat,)).fetchone()[0])['status'],'done')

    def test_default_opening_field_does_not_rewrite_existing_job_hash(self):
        content=Job('1','Plain','Synthetic','https://jobs.example/1').content()
        self.assertNotIn('application_opens_at',content)
        with self.assertRaises(EngineError):Job('2','Bad date','Synthetic','https://jobs.example/2',application_opens_at='2030-01-02').validate()

    def test_existing_reporting_rows_survive_constraint_extension_with_backup(self):
        task=self.s.claim(self.rid)
        jid=self.s.commit_page(task['id'],task['lease_token'],Page([Job('1','Observed','Synthetic','https://jobs.example/1',description='Duties',detail_verified=True)],True),source_url='https://jobs.example/list',payload=b'fixture',origin='fixture')['job_ids'][0]
        row=self.s.row('jobs',jid)
        aid=self.s.assess('p',jid,decision='check',reason='Needs source check',evidence_ids=[row['latest_observation_id']],expected_profile_revision=1,expected_content_hash=row['content_hash'],report_tier='source_gap')
        self.s.db.execute('ALTER TABLE assessment_reporting RENAME TO fixture_new_constraints')
        self.s.db.execute("CREATE TABLE assessment_reporting(assessment_id TEXT PRIMARY KEY REFERENCES assessments(id),report_tier TEXT NOT NULL CHECK(report_tier IN ('actionable','source_gap','future_pool')))")
        self.s.db.execute('INSERT INTO assessment_reporting SELECT * FROM fixture_new_constraints')
        before=[tuple(r) for r in self.s.db.execute('SELECT * FROM assessment_reporting')]
        self.s._migrate_reporting_constraints()
        self.assertEqual([tuple(r) for r in self.s.db.execute('SELECT * FROM assessment_reporting')],before)
        self.assertEqual([tuple(r) for r in self.s.db.execute('SELECT * FROM assessment_reporting_legacy_constraints')],before)
        self.s._migrate_reporting_constraints()
        self.assertEqual(self.s.db.execute('PRAGMA foreign_key_check').fetchall(),[])


if __name__=='__main__':unittest.main()
