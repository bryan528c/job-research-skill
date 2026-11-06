#!/usr/bin/env python3
"""Synthetic fixture browser, no real network. Oracle is not read or returned.
Use search/open/inventory to evaluate an agent in a controlled small job universe.
"""
from pathlib import Path
import argparse,hashlib,json,os,re
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent

def search(pages:list[dict],query:str,field:str='title')->list[dict]:
    terms=[t.casefold() for t in re.split(r'\s+',query.strip()) if t]
    if not terms: return []
    out=[]
    for page in pages:
        hay=(page.get('title','') if field=='title' else page.get('body','') if field=='body'
             else page.get('title','')+' '+page.get('body','')).casefold()
        if any(t in hay for t in terms):
            out.append({k:page[k] for k in ['page_id','title','employer','url']})
    return out

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('search');p.add_argument('query');p.add_argument('--field',choices=['title','body','all'],default='title')
    p=sub.add_parser('open');p.add_argument('page_id')
    p=sub.add_parser('inventory');p.add_argument('employer')
    a=parser.parse_args()
    pages=json.loads((ROOT/'fixtures/discovery/pages.json').read_text(encoding='utf-8'))['pages']
    if a.cmd=='search': result=search(pages,a.query,a.field)
    elif a.cmd=='open': result=[p for p in pages if p['page_id']==a.page_id]
    else: result=[{k:p[k] for k in ['page_id','title','employer','url']} for p in pages if p['employer']==a.employer]
    output={'synthetic':True,'results':result}
    # Evaluator configures this outside the agent prompt. Record actual source
    # operations and returned bytes, not the agent's retrospective claim.
    trace=os.environ.get('JOB_RESEARCH_FIXTURE_TRACE')
    if trace:
        payload=json.dumps(output,ensure_ascii=False,sort_keys=True)
        event={'timestamp':datetime.now(timezone.utc).isoformat(),
               'operation':a.cmd,'arguments':vars(a),'output':output,
               'output_sha256':hashlib.sha256(payload.encode()).hexdigest()}
        with Path(trace).open('a',encoding='utf-8') as f:
            f.write(json.dumps(event,ensure_ascii=False)+'\n')
    print(json.dumps(output,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
