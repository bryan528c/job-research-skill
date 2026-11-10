import unittest
from job_research_engine.store import Store
from job_research_engine.model import EngineError,Job,Page
from job_research_engine.runtime import universe_audit

class UniverseAudit(unittest.TestCase):
    def test_source_records_are_not_a_unique_company_or_group_completion_count(self):
        with Store(':memory:') as s:
            s.set_profile('p',{})
            for registry in ('one','two'):
                s.import_companies(registry,[{'external_id':'1','name':'Same display','industry':'Synthetic industry','group_name':'Synthetic group'}],source_url='https://registry.example/list',scope='synthetic overlapping sources',raw_sha256='a'*64,provenance='fixture')
            cid=s.db.execute('SELECT id FROM companies ORDER BY id LIMIT 1').fetchone()[0]
            source=s.add_source('host-json','https://jobs.example/list',company_id=cid,policy='host_only',evidence_ref='synthetic direct association')
            s.add_source('host-json','https://group.example/list',company_id=None,policy='host_only',evidence_ref='synthetic group-wide channel')
            rid=s.plan_run('p',scope_note='fixture')
            task=s.claim(rid,task_id=s.db.execute("SELECT id FROM tasks WHERE run_id=? AND source_id=? AND kind='inventory'",(rid,source)).fetchone()[0])
            s.commit_page(task['id'],task['lease_token'],Page([Job('1','Planning','Same display','https://jobs.example/1')],True),source_url='https://jobs.example/list',payload=b'actual host fixture',origin='host_export',tool_ref='synthetic')
            result=universe_audit(s,rid,dimension='group');row=result['items'][0]
            self.assertEqual(row['source_records'],2);self.assertEqual(row['observed_source_records'],1)
            self.assertEqual(result['unassigned_group_or_ats_channels'],1)
            self.assertEqual(result['national_unique_companies'],'unknown');self.assertEqual(result['national_coverage'],'unknown')
            first=universe_audit(s,rid,page_size=1);self.assertTrue(first['has_more'])
            last=universe_audit(s,rid,after=first['next_cursor'],page_size=1)
            self.assertFalse(last['has_more']);self.assertNotEqual(first['items'][0]['key'],last['items'][0]['key'])
            with self.assertRaises(EngineError):universe_audit(s,rid,dimension='invented')
            with self.assertRaises(EngineError):universe_audit(s,rid,page_size=0)

if __name__=='__main__':unittest.main()
