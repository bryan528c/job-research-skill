"""Synthetic regressions for real discovery starvation and exposed-branch follow-through."""
import json
import unittest
from job_research_engine.store import Store
from job_research_engine.identity import link_companies
from job_research_engine.frontier import discovery_frontier
from job_research_engine.discovery import discover,career_links
from job_research_engine.htmltools import html
from job_research_engine.model import Job, Page, EngineError
from job_research_engine.transport import Response
from job_research_engine.worker import collect


class FrontierTests(unittest.TestCase):
    def setUp(self):
        self.s = Store(':memory:')
        self.s.set_profile('p', {})
        self.s.import_companies('krx', [
            {'external_id':'a','name':'A','industry':'Manufacturing','homepage':'https://a.example','facts':{'stock_code':'000001'}},
            {'external_id':'b','name':'B','industry':'Manufacturing','homepage':'https://b.example'},
            {'external_id':'c','name':'C','industry':'Retail','homepage':'https://c.example'},
            {'external_id':'d','name':'Unknown','industry':'Retail'},
        ],source_url='https://registry.example/export',scope='synthetic',raw_sha256='a'*64,provenance='fixture')
        self.rid = self.s.plan_run('p',scope_note='synthetic broad')

    def tearDown(self):
        self.s.close()

    def test_no_homepage_stays_visible_without_wasting_native_attempts(self):
        unknown=self.s.db.execute("SELECT t.* FROM tasks t JOIN companies c ON c.id=t.company_id WHERE c.name='Unknown'").fetchone()
        plan=discovery_frontier(self.s,self.rid)
        self.assertEqual(plan['unknown_homepage_tasks_retained'],1)
        self.assertNotIn(unknown['id'],[c['task_id'] for c in plan['candidates']])
        self.assertEqual(self.s.row('tasks',unknown['id'])['attempts'],0)
        self.assertEqual(self.s.row('tasks',unknown['id'])['created_at'],unknown['created_at'])

    def test_next_scope_precedes_second_same_industry_after_resume(self):
        plan=discovery_frontier(self.s,self.rid)
        first=plan['candidates'][0]
        task=self.s.claim(self.rid,kinds=('source_discovery',),task_id=first['task_id'])
        self.s.fail_task(task['id'],task['lease_token'],code='robots_unavailable',note='synthetic failure')
        resumed=discovery_frontier(self.s,self.rid)
        self.assertNotEqual(first['scope_key'],resumed['candidates'][0]['scope_key'])
        self.assertEqual(self.s.row('tasks',first['task_id'])['created_at'],first['created_at'])

    def test_proven_component_supplies_homepage_without_name_merge(self):
        self.s.import_companies('ftc',[{'external_id':'same','name':'Different label','group_name':'Group','facts':{'stock_code':'000001'}}],
            source_url='https://registry.example/group',scope='synthetic',raw_sha256='b'*64,provenance='fixture')
        a=self.s.db.execute("SELECT id FROM companies WHERE name='A'").fetchone()[0]
        other=self.s.db.execute("SELECT id FROM companies WHERE name='Different label'").fetchone()[0]
        link_companies(self.s,other,a,evidence_ref='synthetic shared official code')
        repeat=self.s.plan_run('p',scope_note='repeat')
        plan=discovery_frontier(self.s,repeat)
        member=[c for c in plan['candidates'] if c['identity_component']==a]
        self.assertEqual(len(member),1)
        self.assertEqual(member[0]['scope_key'],['group','Group'])
        self.assertEqual(member[0]['homepage'],'https://a.example')
        self.assertEqual(plan['duplicate_component_tasks_retained'],1)

    def test_career_subdomain_is_observed_even_when_anchor_is_an_icon(self):
        class HTTP:
            evidence_origin='fixture'
            def permitted_by_robots(self,url):return True
            def get(self,url):return Response(url,200,{'content-type':'text/html'},b'<a href="https://careers.example/"><img alt=""></a>')
        result=discover(self.s,self.rid,transport=HTTP(),budget_seconds=10)
        self.assertGreater(result['sources_discovered'],0)
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM tasks WHERE status='queued' AND kind='source_discovery'").fetchone()[0],1)

    def test_finished_alias_homepage_is_not_restarted_by_another_registry_task(self):
        self.s.import_companies('mme',[{'external_id':'alias','name':'Alias','facts':{'stock_code':'000001'}}],
            source_url='https://registry.example/cert',scope='fixture',raw_sha256='d'*64,provenance='fixture')
        a=self.s.db.execute("SELECT id FROM companies WHERE name='A'").fetchone()[0]
        alias=self.s.db.execute("SELECT id FROM companies WHERE name='Alias'").fetchone()[0]
        link_companies(self.s,alias,a,evidence_ref='synthetic exact identifier')
        run=self.s.plan_run('p',scope_note='repeat')
        first=next(c for c in discovery_frontier(self.s,run)['candidates'] if c['identity_component']==a)
        task=self.s.claim(run,kinds=('source_discovery',),task_id=first['task_id'])
        self.s.fail_task(task['id'],task['lease_token'],code='robots_denied',note='fixture')
        plan=discovery_frontier(self.s,run)
        self.assertFalse(any(c['identity_component']==a for c in plan['candidates']))
        self.assertEqual(plan['already_attempted_component_tasks_retained'],1)
        self.assertEqual(self.s.row('tasks',task['id'])['status'],'blocked')

    def test_source_filter_cannot_lease_other_or_empty_branches(self):
        one=self.s.add_source('host-json','https://jobs.example/a',company_id=None,policy='host_only',evidence_ref='synthetic')
        two=self.s.add_source('host-json','https://jobs.example/b',company_id=None,policy='host_only',evidence_ref='synthetic')
        self.s.attach_source(self.rid,one);self.s.attach_source(self.rid,two)
        self.assertIsNone(self.s.claim(self.rid,source_ids=[]))
        result=collect(self.s,self.rid,include_details=True,source_ids=[two])
        self.assertEqual(result['blocked_or_failed_attempts'],1)
        statuses={r['source_id']:r['status'] for r in self.s.db.execute("SELECT source_id,status FROM tasks WHERE kind='inventory'")}
        self.assertEqual(statuses[one],'queued');self.assertEqual(statuses[two],'blocked')
        with self.assertRaises(EngineError):self.s.claim(self.rid,source_ids=one)

    def test_career_information_is_not_a_verified_recruiting_inventory(self):
        candidates,info=career_links(html('<a href="/recruit/people">인재상</a><a href="/recruit/faq">채용 FAQ</a><a href="/recruit/list">채용공고</a>'.encode()),'https://company.example')
        self.assertEqual(candidates,['https://company.example/recruit/list'])
        self.assertEqual(len(info),2)

    def test_certificate_record_inherits_proven_industry_and_homepage(self):
        self.s.import_companies('mme',[{'external_id':'cert','name':'Certificate label','facts':{'stock_code':'000001'}}],
            source_url='https://registry.example/cert',scope='fixture',raw_sha256='c'*64,provenance='fixture')
        a=self.s.db.execute("SELECT id FROM companies WHERE name='A'").fetchone()[0]
        cert=self.s.db.execute("SELECT id FROM companies WHERE name='Certificate label'").fetchone()[0]
        link_companies(self.s,cert,a,evidence_ref='synthetic exact official code')
        repeat=self.s.plan_run('p',scope_note='repeat certificate frontier')
        item=next(c for c in discovery_frontier(self.s,repeat)['candidates'] if c['identity_component']==a)
        self.assertEqual(item['registry'],'mme')
        self.assertEqual(item['scope_key'],['industry','Manufacturing'])
        self.assertEqual(item['homepage_record_id'],a)

    def test_group_homepage_owner_is_not_every_postings_legal_employer(self):
        owner=self.s.db.execute("SELECT id FROM companies WHERE name='A'").fetchone()[0]
        source=self.s.add_source('host-json','https://group.example/list',company_id=owner,policy='host_only',evidence_ref='synthetic homepage link',settings={'job_company_binding':'unverified_homepage_reference'})
        self.s.attach_source(self.rid,source);task=self.s.claim(self.rid,source_ids=[source])
        jid=self.s.commit_page(task['id'],task['lease_token'],Page([Job('1','Planning','Actual posting display','https://group.example/1')],True),source_url='https://group.example/list',payload=b'fixture',origin='fixture')['job_ids'][0]
        job=self.s.row('jobs',jid)
        self.assertNotEqual(job['company_id'],owner)
        self.assertEqual(self.s.row('companies',job['company_id'])['registry'],'discovered-employers')


if __name__=='__main__':unittest.main()
