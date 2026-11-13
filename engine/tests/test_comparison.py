import copy,unittest
from job_research_engine.comparison import compare
from job_research_engine.model import EngineError

class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.cohort={'schema':1,'provenance':'synthetic independent evaluator',
            'roles':[{'sample_id':'a','identities':[['https://jobs.example/round1','entry']],
                'expected':{'decisions':['recommend','check'],'visible':True,'status':'open',
                    'deadline':{'kind':'date','date':'2030-04-06'}}}]}
        self.record={'job_id':'a','job_url':'https://jobs.example/round1','role_key':'entry',
            'assessment_current':True,'decision':'recommend','in_report':True,'detail_verified':True,
            'status':'open','link_state':'verified','deadline':{'kind':'date','date':'2030-04-06'}}
        self.run={'schema':1,'mode':'natural_unseeded','blind':False,'sample_seeded':False,
            'started_at':'2030-04-01T00:00:00+00:00','finished_at':'2030-04-01T00:01:00+00:00',
            'registered_samples':['a'],'records':[self.record]}

    def test_distinct_round_and_campaign_do_not_count_as_discovery(self):
        self.run['records']=[dict(self.record,job_url='https://jobs.example/round2'),dict(self.record,role_key='')]
        result=compare(self.cohort,self.run)
        self.assertEqual(result['counts']['missed'],1)
        self.assertEqual(result['counts']['unconfirmed'],1)
        self.assertEqual(result['counts']['misclassified'],0)

    def test_independent_error_axes_detect_loss_classification_duplicates_and_deadline(self):
        bad=dict(self.record,decision='exclude',in_report=False,deadline={'kind':'unknown'},link_state='error')
        self.run['records']=[bad,dict(bad,job_id='mirror')]
        result=compare(self.cohort,self.run)
        for key in ['misclassified','report_omission','duplicate','deadline_error','link_error']:
            self.assertEqual(result['counts'][key],1,key)
        self.assertEqual(result['counts']['missed'],0)

    def test_unreviewed_and_unknown_are_not_exclusion(self):
        self.run['records']=[dict(self.record,assessment_current=False,status='unknown',detail_verified=False)]
        result=compare(self.cohort,self.run)
        self.assertEqual(result['counts']['unreviewed'],1)
        self.assertEqual(result['counts']['unconfirmed'],1)
        self.assertEqual(result['counts']['misclassified'],0)

    def test_seeded_or_unproven_blind_run_cannot_claim_natural_blind_comparison(self):
        self.run['sample_seeded']=True
        with self.assertRaises(EngineError):compare(self.cohort,self.run)
        self.run['mode']='direct_seeded';self.run['blind']=True
        with self.assertRaises(EngineError):compare(self.cohort,self.run)
        self.run['blind']=False
        self.assertEqual(compare(self.cohort,self.run)['counts']['missed'],0)

if __name__=='__main__':unittest.main()
