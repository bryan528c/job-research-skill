#!/usr/bin/env python3
"""Grade externally recorded agent output against a fixed synthetic oracle.
Not an agent runner. Do not provide the oracle to the agent being evaluated.
"""
from pathlib import Path
import argparse,json

ROOT=Path(__file__).resolve().parent

def grade(capture:dict,oracle:dict)->dict:
    known=set(oracle['all_job_ids'])
    for key in ['observed_job_ids','recommended_job_ids','check_job_ids','excluded_job_ids','report_job_ids']:
        vals=capture.get(key)
        if not isinstance(vals,list) or any(not isinstance(x,str) for x in vals):
            raise ValueError(f'{key} must be a list of job IDs')
        if len(vals)!=len(set(vals)): raise ValueError(f'{key} contains duplicates')
        if not set(vals)<=known: raise ValueError(f'{key} contains unknown IDs')
    observed=set(capture['observed_job_ids']);recommended=set(capture['recommended_job_ids'])
    excluded=set(capture['excluded_job_ids']);reported=set(capture['report_job_ids'])
    gold=set(oracle['recommend'])
    seen=gold&observed;true=gold&recommended
    return {'scope':'fixed_synthetic_corpus_only','observed_recall':len(seen)/len(gold) if gold else None,
            'recommendation_recall':len(true)/len(gold) if gold else None,
            'recommendation_precision':len(true)/len(recommended) if recommended else None,
            'missed_gold_job_ids':sorted(gold-observed),
            'false_exclusion_job_ids':sorted(gold&excluded),
            'false_recommendation_job_ids':sorted(recommended-gold),
            'lost_in_report_job_ids':sorted(recommended-reported),
            'trace_received':bool(capture.get('host_trace_ref')),
            'note':'A supplied capture/trace reference is not authenticated here. No open-web or production recall claim.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path);a=p.parse_args()
    capture=json.loads(a.capture.read_text(encoding='utf-8'))
    oracle=json.loads((ROOT/'oracles/discovery.expected.json').read_text(encoding='utf-8'))
    print(json.dumps(grade(capture,oracle),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
