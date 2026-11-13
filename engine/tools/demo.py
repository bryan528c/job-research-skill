"""End-to-end local demo with synthetic data only. Does not search the real web."""
from pathlib import Path
import argparse,json,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from job_research_engine.store import Store
from job_research_engine.model import Job,Page,digest
from job_research_engine.report import render,handoff
p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path);a=p.parse_args()
with tempfile.TemporaryDirectory() as td:
    path=Path(td)/'private.sqlite'
    with Store(path) as s:
        s.set_profile('fictional',{'timezone':'Asia/Seoul','experience':'합성 요구사항 정의·검수 경험'})
        s.import_companies('fixture',[{'external_id':'001','name':'가상별 기업'},{'external_id':'002','name':'가상달 기업'}],source_url='https://registry.example/demo',raw_sha256=digest(b'demo'),scope='synthetic demonstration',provenance='fixture')
        cid=s.db.execute("SELECT id FROM companies WHERE external_id='001'").fetchone()[0]
        sid=s.add_source('host-json','https://careers.example/jobs',company_id=cid,evidence_ref='synthetic demo source')
        s.import_legacy('fictional',[{'key':'old-001','employer':'이전 합성기업','role':'기획','provenance':'synthetic old report, not reverified'}])
        run=s.plan_run('fictional',scope_note='synthetic demo; one company still has no source')
        t=s.claim(run)
        jobs=[Job('p01','서비스기획','가상별 기업','https://careers.example/jobs/p01',description='합성 정책·화면 흐름 기획',detail_verified=True,deadline={'kind':'date','date':'2026-11-12'}),
              Job('p02','사업기획','가상별 기업','https://careers.example/jobs/p02',description='합성 고객조사·사업제안',detail_verified=True,deadline={'kind':'datetime','at':'2026-11-15T17:00:00+09:00'})]
        obs=s.commit_page(t['id'],t['lease_token'],Page(jobs,True,expected_total=2),source_url='https://careers.example/jobs',payload=json.dumps([j.content() for j in jobs],ensure_ascii=False).encode(),origin='fixture')
        for idx,jid in enumerate(obs['job_ids']):
            j=s.row('jobs',jid)
            s.assess('fictional',jid,decision='recommend' if idx==0 else 'check',reason='합성 사용자 경험과 핵심 업무가 연결됨',risk='' if idx==0 else '근무 시작일 확인 필요',blocking_unknowns=[] if idx==0 else ['근무 시작일'],evidence_ids=[obs['observation_id']],expected_profile_revision=1,expected_content_hash=j['content_hash'])
        report=render(s,run)
        selected=handoff(s,report['report_id'],1,profile_id='fictional',selected_facts=['합성 요구사항 정의·검수 경험'])
        second=s.plan_run('fictional',scope_note='synthetic later run',parent_run_id=run)
        assert len(s.list_run_jobs(second))==2
    with Store(path) as reopened:assert len(reopened.list_run_jobs(second))==2
    result={'kind':'synthetic_end_to_end','report_id':report['report_id'],'run_id':run,'next_run_id':second,
            'report_job_count':len(report['mapping']),'restart_preserved_candidates':2,'coverage':'partial',
            'network_calls':0,'user_data_used':False}
    if a.output_dir:
        a.output_dir.mkdir(parents=True,exist_ok=True)
        (a.output_dir/'demo-report.ko.md').write_text('> 합성 데이터 실행 예시. 실제 채용 결과가 아님.\n\n'+report['text'],encoding='utf-8')
        (a.output_dir/'demo-handoff.ko.txt').write_text(selected,encoding='utf-8')
        (a.output_dir/'demo.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
