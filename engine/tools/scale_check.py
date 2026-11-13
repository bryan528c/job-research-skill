"""Synthetic scale/state test, NOT live-company coverage or a market benchmark."""
from pathlib import Path
import argparse
import json
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from job_research_engine.store import Store
from job_research_engine.model import Job,Page,digest

p=argparse.ArgumentParser();p.add_argument('--companies',type=int,default=10000);p.add_argument('--output',type=Path)
a=p.parse_args();start=time.perf_counter()
with tempfile.TemporaryDirectory() as td:
    path=Path(td)/'synthetic.sqlite'
    with Store(path) as store:
        store.set_profile('synthetic',{'timezone':'Asia/Seoul'})
        rows=[{'external_id':str(i),'name':f'Synthetic company {i}'} for i in range(a.companies)]
        store.import_companies('synthetic-scale',rows,source_url='https://registry.example/synthetic',raw_sha256=digest(b'synthetic'),scope='synthetic generated rows; not Korean companies',provenance='fixture')
        import_seconds=time.perf_counter()-start
        cids=[r[0] for r in store.db.execute('SELECT id FROM companies ORDER BY id LIMIT 10')]
        for i,cid in enumerate(cids):store.add_source('host-json',f'https://jobs.example/{i}',company_id=cid,evidence_ref='synthetic fixture')
        run=store.plan_run('synthetic',scope_note='synthetic 10000-company durability test')
        for i in range(len(cids)):
            t=store.claim(run)
            jobs=[Job(str(j),f'Role {j}',f'Synthetic {i}',f'https://jobs.example/{i}/{j}',description='Synthetic requirements',detail_verified=True) for j in range(25)]
            store.commit_page(t['id'],t['lease_token'],Page(jobs,True,expected_total=25),source_url=f'https://jobs.example/{i}',payload=json.dumps([j.content() for j in jobs]).encode(),origin='fixture')
        before=store.coverage(run)
    with Store(path) as reopened:
        after=reopened.coverage(run)
        assert before['companies_planned']==after['companies_planned']==a.companies
        assert after['unique_source_jobs']==len(cids)*25
        assert after['companies_registered_sources_checked']==len(cids)
        assert after['status']=='partial'
        assert after['production_observations']==0
    result={'kind':'synthetic_scale_and_restart_only','companies_generated':a.companies,
        'source_inventories_generated':len(cids),'jobs_generated':len(cids)*25,
        'company_source_discovery_tasks_unfinished':a.companies-len(cids),
        'source_coverage_reported':'partial','national_coverage':'unknown',
        'reopen_preserved_counts':True,'import_seconds':round(import_seconds,3),
        'total_seconds':round(time.perf_counter()-start,3),'live_network_calls':0,
        'note':'Timing is for this execution host and synthetic data, not a production capacity SLA.'}
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if a.output:a.output.write_text(text+'\n',encoding='utf-8')
    print(text)
