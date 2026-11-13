"""Synthetic identity contracts; no live registry or private company records."""
import json
import unittest

from job_research_engine.identity import identifiers, link_companies, reconcile, unlink_company
from job_research_engine.model import EngineError, dump, stable_id
from job_research_engine.store import Store


class IdentityContinuation(unittest.TestCase):
    def setUp(self):
        self.s=Store(':memory:')

    def tearDown(self):
        self.s.close()

    def company(self,key,**facts):
        self.s.import_companies('synthetic',[{'external_id':key,'name':'Synthetic entity','facts':facts}],
            source_url='https://registry.example.org/identity',raw_sha256=key,scope='fixture',provenance='fixture')
        return stable_id('synthetic',key)

    def test_alphanumeric_stock_code_keeps_letters_and_normalizes_case(self):
        a=self.company('a',stock_code=' 0123b0 ')
        b=self.company('b',stock_code='0123B0')
        self.assertEqual(identifiers(self.s.row('companies',a)),{'stock_code':'0123B0'})
        self.assertTrue(link_companies(self.s,a,b,evidence_ref='synthetic official stock identifier'))

    def test_alphanumeric_stock_code_does_not_collapse_into_numeric_code(self):
        a=self.company('a',stock_code='01A234')
        b=self.company('b',stock_code='001234')
        with self.assertRaises(EngineError):
            link_companies(self.s,a,b,evidence_ref='synthetic mismatched stock identifiers')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM company_aliases').fetchone()[0],0)

    def test_stock_code_rejects_zero_and_embedded_punctuation(self):
        for value in ('000000','012-3B0','0123B0 suffix',''):
            self.assertNotIn('stock_code',identifiers({'facts_json':dump({'stock_code':value})}))

    def test_name_alone_remains_insufficient(self):
        a=self.company('a');b=self.company('b')
        with self.assertRaises(EngineError):
            link_companies(self.s,a,b,evidence_ref='synthetic equal names')

    def test_direct_link_checks_the_canonical_root(self):
        root=self.company('root',legal_registration='1101110000001',business_registration='1234567891')
        bridge=self.company('bridge',business_registration='1234567891')
        candidate=self.company('candidate',legal_registration='1101110000002',business_registration='1234567891')
        self.assertTrue(link_companies(self.s,bridge,root,evidence_ref='synthetic shared business identity'))
        with self.assertRaises(EngineError):
            link_companies(self.s,candidate,bridge,evidence_ref='synthetic root conflict')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM company_aliases').fetchone()[0],1)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM identity_events').fetchone()[0],1)

    def test_component_member_conflict_is_checked_after_source_update(self):
        root=self.company('root',business_registration='1234567891')
        bridge=self.company('bridge',business_registration='1234567891')
        link_companies(self.s,bridge,root,evidence_ref='synthetic initial evidence')
        self.company('bridge',business_registration='1234567891',legal_registration='1101110000002')
        candidate=self.company('candidate',business_registration='1234567891',legal_registration='1101110000001')
        with self.assertRaises(EngineError):
            link_companies(self.s,candidate,root,evidence_ref='synthetic conflicting component member')

    def test_consistent_link_is_idempotent_and_reversible(self):
        a=self.company('a',legal_registration='1101110000001')
        b=self.company('b',legal_registration='1101110000001')
        self.assertTrue(link_companies(self.s,a,b,evidence_ref='synthetic exact official identity'))
        self.assertFalse(link_companies(self.s,a,b,evidence_ref='synthetic repeated observation'))
        unlink_company(self.s,a,reason='synthetic undo')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM companies').fetchone()[0],2)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM identity_events').fetchone()[0],2)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM company_aliases').fetchone()[0],0)

    def test_root_can_use_identifier_proved_by_a_consistent_component_member(self):
        root=self.company('root',legal_registration='1101110000001',business_registration='1234567891')
        bridge=self.company('bridge',business_registration='1234567891',stock_code='0123B0')
        candidate=self.company('candidate',stock_code='0123B0')
        link_companies(self.s,bridge,root,evidence_ref='synthetic exact business identity')
        self.assertTrue(link_companies(self.s,candidate,root,evidence_ref='synthetic exact stock identity in component'))
        self.assertEqual(self.s.db.execute('SELECT canonical_id FROM company_aliases WHERE alias_id=?',(candidate,)).fetchone()[0],root)

    def test_idempotent_component_link_does_not_require_fields_on_the_root_row(self):
        root=self.company('root',legal_registration='1101110000001')
        bridge=self.company('bridge',legal_registration='1101110000001',business_registration='1234567891')
        leaf=self.company('leaf',business_registration='1234567891')
        link_companies(self.s,bridge,root,evidence_ref='synthetic exact legal identity')
        link_companies(self.s,leaf,bridge,evidence_ref='synthetic exact business identity')
        self.assertFalse(link_companies(self.s,leaf,root,evidence_ref='synthetic repeated component identity'))
        self.assertEqual(reconcile(self.s)['link_rejections'],0)

    def test_link_rejections_are_not_counted_as_identifier_conflict_clusters(self):
        root=self.company('root',legal_registration='1101110000001',business_registration='1234567891')
        bridge=self.company('bridge',business_registration='1234567891',stock_code='0123B0')
        candidate=self.company('candidate',legal_registration='1101110000002',stock_code='0123B0')
        link_companies(self.s,bridge,root,evidence_ref='synthetic component bridge')
        result=reconcile(self.s)
        self.assertEqual(result['conflict_clusters'],0)
        self.assertGreaterEqual(result['link_rejections'],1)
        self.assertEqual(result['stored_unresolved_conflict_records'],0)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM company_aliases').fetchone()[0],1)

    def test_source_export_conflict_records_are_distinct_from_current_clusters(self):
        self.company('a',legal_registration='1101110000001',business_registration='1234567891')
        self.company('b',legal_registration='1101110000001',business_registration='1234567892')
        self.s.db.execute('INSERT INTO identity_conflicts VALUES(?,?,?,?,?,0)',
            ('source-issue','legal:1101110000001','[]','source export conflicting business_registration; rows retained separately',self.s._now()))
        first=reconcile(self.s);second=reconcile(self.s)
        self.assertEqual(first['conflict_clusters'],1)
        self.assertEqual(first['new_conflict_records'],1)
        self.assertEqual(second['new_conflict_records'],0)
        self.assertEqual(second['stored_unresolved_conflict_records'],2)
        self.assertEqual(second['link_rejections'],0)
        self.assertEqual(json.loads(self.s.db.execute("SELECT companies_json FROM identity_conflicts WHERE id='source-issue'").fetchone()[0]),[])


if __name__=='__main__':
    unittest.main()
