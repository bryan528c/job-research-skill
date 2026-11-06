#!/usr/bin/env python3
"""Grade externally recorded agent output against a fixed synthetic oracle.
Not an agent runner. Do not provide the oracle to the agent being evaluated.
"""
from pathlib import Path
import argparse,hashlib,json

ROOT=Path(__file__).resolve().parent

def trace_observations(events:list[dict])->set[str]:
    """Check recorded fixture outputs; not a cryptographic host attestation."""
    opened=set()
    for event in events:
        output=event['output']
        raw=json.dumps(output,ensure_ascii=False,sort_keys=True).encode()
        if hashlib.sha256(raw).hexdigest()!=event.get('output_sha256'):
            raise ValueError('trace output hash mismatch')
        if output.get('synthetic') is not True:
            raise ValueError('only synthetic fixture traces are accepted')
        if event['operation']=='open':
            opened.update(p['job_id'] for p in output['results'] if p.get('job_id'))
    return opened

def grade(capture:dict,oracle:dict,trace:list[dict]|None=None)->dict:
    known=set(oracle['all_job_ids'])
    for key in ['observed_job_ids','recommended_job_ids','check_job_ids','excluded_job_ids','report_job_ids']:
        vals=capture.get(key)
        if not isinstance(vals,list) or any(not isinstance(x,str) for x in vals):
            raise ValueError(f'{key} must be a list of job IDs')
        if len(vals)!=len(set(vals)): raise ValueError(f'{key} contains duplicates')
        if not set(vals)<=known: raise ValueError(f'{key} contains unknown IDs')
    observed=set(capture['observed_job_ids']);recommended=set(capture['recommended_job_ids'])
    excluded=set(capture['excluded_job_ids']);reported=set(capture['report_job_ids'])
    checked=set(capture['check_job_ids'])
    if recommended&excluded or recommended&checked or excluded&checked:
        raise ValueError('a job cannot have conflicting decisions')
    if not (recommended|checked|excluded|reported)<=observed:
        raise ValueError('decided/reported job was not observed')
    if trace is not None and observed!=trace_observations(trace):
        raise ValueError('capture observations do not match actual fixture opens')
    gold=set(oracle['recommend'])
    seen=gold&observed;true=gold&recommended
    return {'scope':'fixed_synthetic_corpus_only','observed_recall':len(seen)/len(gold) if gold else None,
            'recommendation_recall':len(true)/len(gold) if gold else None,
            'recommendation_precision':len(true)/len(recommended) if recommended else None,
            'missed_gold_job_ids':sorted(gold-observed),
            'false_exclusion_job_ids':sorted(gold&excluded),
            'false_recommendation_job_ids':sorted(recommended-gold),
            'lost_in_report_job_ids':sorted(recommended-reported),
            'check_job_mismatch_ids':sorted(checked^set(oracle.get('check',[]))),
            'trace_output_consistency_checked':trace is not None,
            'trace_received':bool(capture.get('host_trace_ref')),
            'note':'Fixture output hashes and observation IDs can be checked, but are not host authentication. No open-web or production recall claim.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path)
    p.add_argument('--trace',type=Path);a=p.parse_args()
    capture=json.loads(a.capture.read_text(encoding='utf-8'))
    oracle=json.loads((ROOT/'oracles/discovery.expected.json').read_text(encoding='utf-8'))
    trace=[json.loads(line) for line in a.trace.read_text().splitlines() if line] if a.trace else None
    print(json.dumps(grade(capture,oracle,trace),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
