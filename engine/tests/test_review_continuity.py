"""Synthetic regressions: no employer or private user records are fixtures."""
from dataclasses import replace
import json
import unittest

from job_research_engine.model import EngineError, Job, Page
from job_research_engine.store import Store
from job_research_engine.report import render
from job_research_engine.funnel import candidate_audit
from job_research_engine.worker import collect
from job_research_engine.transport import FetchError
from job_research_engine.korean import parse_detail


class ReviewContinuity(unittest.TestCase):
    def setUp(self):
        self.at = '2030-04-01T00:00:00+00:00'
        self.s = Store(':memory:', clock=lambda: self.at)
        self.s.set_profile('p', {'timezone': 'Asia/Seoul'})
        self.s.import_companies('fixture', [{'external_id': '1', 'name': 'Synthetic'}],
            source_url='https://registry.example/list', scope='synthetic',
            raw_sha256='a'*64, provenance='fixture')
        self.sid = self.s.add_source('host-json', 'https://jobs.example/list',
            company_id=None, policy='host_only', evidence_ref='synthetic')
        self.rid = self.s.plan_run('p', scope_note='synthetic')
        self.s.attach_source(self.rid, self.sid)

    def tearDown(self):
        self.s.close()

    def ingest(self, jobs):
        task = self.s.claim(self.rid, kinds=('inventory',), source_ids=[self.sid])
        return self.s.commit_page(task['id'], task['lease_token'], Page(jobs, True),
            source_url='https://jobs.example/list', payload=b'synthetic', origin='fixture')['job_ids']

    def job(self, key='1', **changes):
        return replace(Job(key, 'Synthetic planning', 'Synthetic', 'https://jobs.example/'+key,
            description='Entry: no required experience. Senior: seven years required.',
            detail_verified=True), **changes)

    def assess(self, jid, **changes):
        job = self.s.row('jobs', jid)
        values = dict(decision='recommend', reason='Synthetic actual project evidence',
            evidence_ids=[job['latest_observation_id']], expected_profile_revision=1,
            expected_content_hash=job['content_hash'])
        self.s.assess('p', jid, **dict(values, **changes))

    def test_opening_due_candidate_returns_to_actionable_review_without_becoming_open(self):
        jid = self.ingest([self.job(status='unknown', application_opens_at='2030-04-02T00:00:00+00:00')])[0]
        self.assess(jid, decision='check', report_tier='upcoming', blocking_unknowns=['Opening confirmation'])
        self.assertEqual(render(self.s, self.rid)['mapping'], [])
        self.at = '2030-04-03T00:00:00+00:00'
        row = self.s.list_run_jobs(self.rid)[0]
        self.assertTrue(row['opening_recheck_due'])
        self.assertFalse(row['assessment_current'])
        self.assertEqual(row['recruiting_status'], 'unknown')
        self.assertEqual(row['effective_decision'], 'check')
        report = render(self.s, self.rid)
        self.assertEqual([m['job_id'] for m in report['mapping']], [jid])
        self.assertIn('접수 시작 후', report['text'])

    def test_english_explicit_closure_preserves_exact_notice_round(self):
        payload=b'''<main><h2 class="title">Synthetic planning</h2><div class="detail-content-item">Duties: planning.</div></main>
        <div class="floating-box"><div class="box-detail-item"><span class="label">Company</span><span class="value">Synthetic</span></div>
        <div class="box-detail-item"><span class="label">Application Period</span><span class="value">October 27, 2030~November 10, 2030</span></div>
        <div class="box-detail-item"><span class="label">Closing Time</span><span class="value">23:59</span></div></div><button>Application closed</button>'''
        a=parse_detail('skcareers-detail',payload,'https://www.skcareers.com/Recruit/Detail/R999999',{})
        b=parse_detail('skcareers-detail',payload,'https://www.skcareers.com/Recruit/Detail/R999998',{})
        self.assertEqual(a.status,'closed')
        korean=parse_detail('skcareers-detail',payload.replace(b'Application closed','지원서 접수마감'.encode()),
            'https://www.skcareers.com/Recruit/Detail/R999999',{})
        self.assertEqual(korean.status,'closed')
        self.assertNotEqual(a.external_id,b.external_id)
        self.assertEqual(a.deadline['at'],'2030-11-10T23:59:00+09:00')

    def test_submission_follows_evidenced_same_posting_but_not_same_title_round(self):
        a, b, other = self.ingest([self.job('1'), self.job('2'), self.job('3', round_key='new-round')])
        for jid in [a, b, other]: self.assess(jid)
        self.s.link_postings(a, b, evidence_ref='synthetic exact observed crosslink and same role/round')
        self.s.user_event('p', event_key='submitted', scope_type='job', target_id=a,
            kind='application', value='submitted', evidence_ref='synthetic explicit user record')
        rows = {j['id']:j for j in self.s.list_run_jobs(self.rid)}
        self.assertEqual(rows[b]['user_state']['application'], 'submitted')
        self.assertEqual(rows[other]['user_state']['application'], 'not_started')
        self.assertEqual([m['job_id'] for m in render(self.s, self.rid)['mapping']], [other])
        self.s.set_profile('q', {})
        self.assertEqual(self.s.latest_user_state('q', self.s.row('jobs', b))['application'], 'not_started')
        self.s.unlink_postings(a, b, reason='synthetic reversal')
        self.assertEqual(self.s.latest_user_state('p', self.s.row('jobs', b))['application'], 'not_started')

    def test_same_posting_link_refuses_campaign_parent_and_its_distinct_role(self):
        parent = self.ingest([self.job()])[0]
        child = self.s.split_campaign(self.rid, parent, [{'role_key':'entry', 'title':'Entry',
            'description':'Entry: no required experience.', 'source_quote':'Entry: no required experience.'}],
            evidence_ref='synthetic source section')[0]
        with self.assertRaises(EngineError):
            self.s.link_postings(parent, child, evidence_ref='synthetic invalid equivalence')

    def test_equivalent_postings_are_rendered_once_and_reconciled_without_loss(self):
        a,b,distinct=self.ingest([self.job('1'),self.job('2'),self.job('3',round_key='different')])
        for jid in [a,b,distinct]:self.assess(jid)
        self.s.link_postings(a,b,evidence_ref='synthetic verified exact-role/round crosslink')
        report=render(self.s,self.rid)
        self.assertEqual(len(report['mapping']),2)
        represented={jid for item in report['mapping'] for jid in [item['job_id'],*item.get('equivalent_job_ids',[])]}
        self.assertEqual(represented,{a,b,distinct})
        self.assertEqual(candidate_audit(self.s,self.rid,report_id=report['report_id'])['report_comparison']['currently_actionable_not_in_checkpoint'],[])
        wrong=[dict(m) for m in report['mapping']]
        wrong[0]['equivalent_job_ids']=[distinct]
        with self.assertRaises(EngineError):self.s.save_report(self.rid,'incorrect duplicate grouping',wrong,report['coverage'])

    def test_submitted_and_closed_are_counted_on_independent_axes(self):
        jid = self.ingest([self.job(status='closed')])[0]
        self.s.user_event('p', event_key='submitted', scope_type='job', target_id=jid,
            kind='application', value='submitted', evidence_ref='synthetic user record')
        audit = candidate_audit(self.s, self.rid)
        self.assertEqual(audit['recruiting_status_counts']['closed'], 1)
        self.assertEqual(audit['application_state_counts']['submitted'], 1)
        self.assertEqual(audit['assessment_state_counts']['missing_or_stale'], 1)
        self.assertEqual(render(self.s, self.rid)['mapping'], [])

    def test_header_deadline_correction_does_not_refresh_or_overwrite_unread_body(self):
        jid=self.ingest([self.job()])[0];self.assess(jid)
        old=self.s.row('jobs',jid);self.at='2030-04-02T00:00:00+00:00'
        oid=self.s.amend_deadline(self.rid,jid,deadline={'kind':'date','date':'2030-04-06'},
            expected_content_hash=old['content_hash'],source_url='https://official.example/round1',
            evidence_text='Synthetic official header: deadline 2030-04-06, time unspecified.',
            tool_ref='synthetic direct header observation',observed_at=self.at)
        new=self.s.row('jobs',jid);content=json.loads(new['content_json'])
        self.assertEqual(new['last_seen'],old['last_seen'])
        self.assertEqual(new['latest_observation_id'],old['latest_observation_id'])
        self.assertEqual(content['description'],json.loads(old['content_json'])['description'])
        self.assertEqual(content['deadline'],{'kind':'date','date':'2030-04-06'})
        self.assertFalse(self.s.list_run_jobs(self.rid)[0]['assessment_current'])
        with self.assertRaises(EngineError):self.assess(jid)
        self.assess(jid,evidence_ids=[old['latest_observation_id'],oid])
        self.assertTrue(self.s.list_run_jobs(self.rid)[0]['assessment_current'])
        count=self.s.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
        with self.assertRaises(EngineError):
            self.s.amend_deadline(self.rid,jid,deadline={'kind':'date','date':'2030-04-07'},
                expected_content_hash=old['content_hash'],source_url='https://official.example/round1',
                evidence_text='Stale worker',tool_ref='synthetic',observed_at=self.at)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],count)
        tid=self.s._enqueue(self.rid,'job_detail','captured-earlier',source_id=self.sid,payload={'job_id':jid})
        task=self.s.claim(self.rid,kinds=('job_detail',),task_id=tid)
        self.s.commit_detail(tid,task['lease_token'],self.job(deadline={'kind':'date','date':'2030-04-09'}),
            source_url='https://jobs.example/1',payload=b'whole body actually captured before header correction',origin='fixture',
            observed_at='2030-04-01T12:00:00+00:00')
        current=self.s.row('jobs',jid)
        self.assertEqual(json.loads(current['content_json'])['deadline'],{'kind':'date','date':'2030-04-06'})
        self.assertEqual(current['last_seen'],'2030-04-01T12:00:00.000000+00:00')

    def test_campaign_requirements_remain_role_scoped(self):
        parent = self.ingest([self.job(requires_role_split=True)])[0]
        entry, senior = self.s.split_campaign(self.rid, parent, [
            {'role_key':'entry','title':'Entry','description':'Entry: no required experience.',
             'source_quote':'Entry: no required experience.',
             'source_sections':{'required':['no required experience']}},
            {'role_key':'senior','title':'Senior','description':'Senior: seven years required.',
             'source_quote':'Senior: seven years required.',
             'source_sections':{'required':['seven years required']}}
        ], evidence_ref='synthetic separately observed role sections')
        entry_body = json.loads(self.s.row('jobs',entry)['content_json'])
        senior_body = json.loads(self.s.row('jobs',senior)['content_json'])
        self.assertEqual(entry_body['role_source_sections']['required'], ['no required experience'])
        self.assertEqual(senior_body['role_source_sections']['required'], ['seven years required'])
        self.assess(entry)
        self.assess(senior,decision='exclude')
        self.assertEqual([m['job_id'] for m in render(self.s,self.rid)['mapping']], [entry])
        with self.assertRaises(EngineError):
            self.s.split_campaign(self.rid,parent,[{'role_key':'bad','title':'Entry',
                'description':'Entry: no required experience.','source_quote':'Entry: no required experience.',
                'source_sections':{'required':['seven years required']}}],evidence_ref='synthetic sibling leak')

    def test_403_keeps_body_assessment_and_submission_and_records_access_gap(self):
        jid = self.ingest([self.job()])[0]
        self.assess(jid)
        self.s.user_event('p',event_key='submitted',scope_type='job',target_id=jid,
            kind='application',value='submitted',evidence_ref='synthetic user record')
        before = self.s.row('jobs',jid)
        self.s.db.execute("UPDATE sources SET policy='robots' WHERE id=?",(self.sid,))
        self.s._enqueue(self.rid,'job_detail',jid,source_id=self.sid,payload={'job_id':jid})
        class Denied:
            def permitted_by_robots(self,url):return True
            def get(self,*args,**kw):raise FetchError('access_denied','HTTP 403')
        result=collect(self.s,self.rid,transport=Denied(),include_details=True,source_ids=[self.sid])
        self.assertEqual(result['blocked_or_failed_attempts'],1)
        self.assertEqual(before,self.s.row('jobs',jid))
        self.assertEqual(self.s.list_run_jobs(self.rid)[0]['user_state']['application'],'submitted')
        self.assertEqual(self.s.db.execute("SELECT error_code FROM tasks WHERE kind='job_detail'").fetchone()[0],'access_denied')
        self.assertEqual(render(self.s,self.rid)['mapping'],[])


if __name__ == '__main__': unittest.main()
