import json
import unittest
from job_research_engine.store import Store
from job_research_engine.model import EngineError,Page,stable_id
from job_research_engine.identity import (override_identifier,effective_identifiers,identifiers,
    link_companies,canonical,unlink_company,revoke_identifier_override,reconcile,review_identity_conflict)
from job_research_engine.frontier import discovery_frontier


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.s=Store(':memory:');self.s.set_profile('p',{})
        self.a=self.company('a','1101110000001');self.b=self.company('b','1101110000002')
        sources=[self.s.add_source('host-json',u,company_id=None,policy='host_only',evidence_ref='synthetic official observation') for u in ('https://registry.example/a','https://filing.example/b')]
        self.rid=self.s.plan_run('p',scope_note='synthetic')
        self.evidence=[]
        for sid in sources:
            task=self.s.claim(self.rid,source_ids=[sid])
            self.evidence.append(self.s.commit_page(task['id'],task['lease_token'],Page([],True,expected_total=0),source_url=self.s.row('sources',sid)['url'],payload=b'synthetic independent proof',origin='fixture')['observation_id'])

    def tearDown(self):self.s.close()

    def company(self,key,legal):
        self.s.import_companies('fixture',[{'external_id':key,'name':'Same name','homepage':'https://company.example',
            'facts':{'legal_registration':legal,'business_registration':'1234567891'}}],source_url='https://registry.example/list',scope='fixture',raw_sha256=key+legal,provenance='fixture')
        return stable_id('fixture',key)

    def correct(self):
        return override_identifier(self.s,self.a,'legal_registration',expected_source_value='1101110000001',corrected_value='1101110000002',evidence_ids=self.evidence,reason='Synthetic cross-source correction')

    def test_correction_preserves_original_keys_and_survives_repeat_import(self):
        original=dict(self.s.row('companies',self.a));oid=self.correct()
        self.assertEqual(self.s.row('companies',self.a),original)
        self.assertEqual(identifiers(original)['legal_registration'],'1101110000001')
        self.assertEqual(effective_identifiers(self.s,original)['legal_registration'],'1101110000002')
        self.company('a','1101110000001')
        self.assertEqual(effective_identifiers(self.s,self.s.row('companies',self.a))['legal_registration'],'1101110000002')
        self.assertEqual(self.correct(),oid)
        self.assertTrue(link_companies(self.s,self.a,self.b,evidence_ref='synthetic reviewed correction'))

    def test_new_source_drift_fences_aliases_and_native_homepage_lending(self):
        self.correct();link_companies(self.s,self.a,self.b,evidence_ref='synthetic')
        self.company('a','1101110000003')
        with self.assertRaises(EngineError):canonical(self.s,self.b)
        self.assertIn(self.a,reconcile(self.s)['identifier_override_drift_records'])
        plan=discovery_frontier(self.s,self.rid)
        self.assertEqual(plan['candidates'],[]);self.assertEqual(plan['identifier_drift_tasks_retained'],2)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM company_aliases').fetchone()[0],1)

    def test_undo_keeps_history_and_requires_dependent_alias_undo(self):
        oid=self.correct();link_companies(self.s,self.a,self.b,evidence_ref='synthetic')
        with self.assertRaises(EngineError):revoke_identifier_override(self.s,oid,reason='synthetic undo')
        self.assertIsNone(self.s.row('identifier_overrides',oid)['revoked_at'])
        unlink_company(self.s,self.a,reason='synthetic explicit unlink')
        self.assertTrue(revoke_identifier_override(self.s,oid,reason='synthetic correction undo'))
        self.assertIsNotNone(self.s.row('identifier_overrides',oid)['revoked_at'])
        self.assertEqual(effective_identifiers(self.s,self.s.row('companies',self.a))['legal_registration'],'1101110000001')

    def test_missing_independent_observation_or_changed_raw_is_not_a_correction(self):
        for expected,evidence in [('1101110000001',self.evidence[:1]),('1101110000099',self.evidence)]:
            with self.assertRaises(EngineError):override_identifier(self.s,self.a,'legal_registration',expected_source_value=expected,corrected_value='1101110000002',evidence_ids=evidence,reason='synthetic')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM identifier_overrides').fetchone()[0],0)

    def test_explicit_undo_recovers_from_source_drift_without_losing_history(self):
        oid=self.correct();link_companies(self.s,self.a,self.b,evidence_ref='synthetic')
        self.company('a','1101110000003')
        with self.assertRaises(EngineError):revoke_identifier_override(self.s,oid,reason='source drift')
        unlink_company(self.s,self.a,reason='source drift; preserve evidence')
        self.assertTrue(revoke_identifier_override(self.s,oid,reason='explicit correction review after drift'))
        self.assertEqual(canonical(self.s,self.a),self.a)
        self.assertIsNotNone(self.s.row('identifier_overrides',oid)['revoked_at'])

    def test_conflict_review_does_not_resolve_a_still_conflicting_pair(self):
        reconcile(self.s)
        old=dict(self.s.db.execute('SELECT * FROM identity_conflicts').fetchone())
        with self.assertRaises(EngineError):review_identity_conflict(self.s,old['id'],disposition='linked_after_correction',evidence_ids=self.evidence,reason='synthetic')
        self.correct();link_companies(self.s,self.a,self.b,evidence_ref='synthetic reviewed correction')
        review_identity_conflict(self.s,old['id'],disposition='linked_after_correction',evidence_ids=self.evidence,reason='synthetic')
        current=self.s.row('identity_conflicts',old['id'])
        self.assertEqual(current['resolved'],1)
        self.assertEqual(current['companies_json'],old['companies_json'])
        self.assertEqual(current['reason'],old['reason'])


if __name__=='__main__':unittest.main()
