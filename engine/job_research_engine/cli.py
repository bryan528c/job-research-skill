from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from . import __version__
from .model import EngineError,dump
from .store import Store
from .registry import import_registry
from .transport import PublicHTTP
from .worker import collect,import_host_capture
from .report import render,handoff
from .registries import sync_registry,PROVIDERS
from .identity import reconcile,unlink_company,override_identifier,revoke_identifier_override
from .runtime import session,packet,summary,universe_audit
from .discovery import discover
from .legacy import recheck_legacy
from .model import Job
from .funnel import candidate_audit


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description='Job Research durable engine. Internal agent interface; users speak naturally.')
    p.add_argument('--version',action='version',version=__version__)
    p.add_argument('--db',type=Path,required=True,help='Explicit private DB outside the public repository')
    s=p.add_subparsers(dest='cmd',required=True)
    s.add_parser('init')
    q=s.add_parser('sync-registry');q.add_argument('provider',choices=PROVIDERS);q.add_argument('--year',type=int);q.add_argument('--allow-network',action='store_true');q.add_argument('--budget-seconds',type=float,default=40);q.add_argument('--restart',action='store_true')
    s.add_parser('reconcile-companies')
    q=s.add_parser('unlink-company');q.add_argument('alias_id');q.add_argument('--reason',required=True)
    q=s.add_parser('override-identifier');q.add_argument('correction',type=Path)
    q=s.add_parser('revoke-identifier-override');q.add_argument('override_id');q.add_argument('--reason',required=True)
    q=s.add_parser('session');q.add_argument('profile_id');q.add_argument('request');q.add_argument('--new-cycle',action='store_true');q.add_argument('--host',default='codex')
    q=s.add_parser('summary');q.add_argument('run_id')
    q=s.add_parser('universe-audit');q.add_argument('run_id');q.add_argument('--dimension',choices=['registry','industry','group'],default='registry');q.add_argument('--after',default='');q.add_argument('--page-size',type=int,default=100)
    q=s.add_parser('candidate-audit');q.add_argument('run_id');q.add_argument('--report-id');q.add_argument('--after',default='');q.add_argument('--page-size',type=int,default=100)
    q=s.add_parser('expand-employers');q.add_argument('run_id')
    q=s.add_parser('discover');q.add_argument('run_id');q.add_argument('--allow-network',action='store_true');q.add_argument('--budget-seconds',type=float,default=30);q.add_argument('--strategy',choices=['balanced','oldest'],default='balanced')
    q=s.add_parser('recheck-legacy');q.add_argument('run_id');q.add_argument('--allow-network',action='store_true');q.add_argument('--budget-seconds',type=float,default=35)
    q=s.add_parser('packet');q.add_argument('run_id');q.add_argument('--section',choices=['jobs','tasks','legacy'],default='jobs');q.add_argument('--after',default='');q.add_argument('--page-size',type=int,default=50)
    q=s.add_parser('profile');q.add_argument('profile_id');q.add_argument('facts',type=Path)
    q=s.add_parser('import-registry');q.add_argument('path',type=Path);q.add_argument('--kind',choices=['dart','krx-html','csv'],required=True);q.add_argument('--registry',required=True);q.add_argument('--source-url',required=True);q.add_argument('--scope',required=True);q.add_argument('--completeness',choices=['partial','unknown','complete_source_snapshot'],default='partial');q.add_argument('--fixture',action='store_true')
    q=s.add_parser('import-legacy');q.add_argument('profile_id');q.add_argument('records',type=Path)
    q=s.add_parser('companies');q.add_argument('--after',default='');q.add_argument('--page-size',type=int,default=100)
    q=s.add_parser('source');q.add_argument('config',type=Path)
    q=s.add_parser('plan');q.add_argument('profile_id');q.add_argument('--scope-note',required=True);q.add_argument('--targeted',action='store_true');q.add_argument('--company-ids',type=Path);q.add_argument('--parent-run')
    q=s.add_parser('attach-source');q.add_argument('run_id');q.add_argument('source_id')
    q=s.add_parser('collect');q.add_argument('run_id');q.add_argument('--allow-network',action='store_true');q.add_argument('--budget-seconds',type=float);q.add_argument('--details',action='store_true');q.add_argument('--source-id',action='append',default=None)
    q=s.add_parser('split-job');q.add_argument('run_id');q.add_argument('job_id');q.add_argument('roles',type=Path);q.add_argument('--evidence-ref',required=True)
    q=s.add_parser('next-task');q.add_argument('run_id');q.add_argument('--kind',action='append',default=[]);q.add_argument('--lease-seconds',type=int,default=600)
    q=s.add_parser('ingest');q.add_argument('task_id');q.add_argument('lease_token');q.add_argument('capture',type=Path);q.add_argument('--source-url',required=True);q.add_argument('--tool-ref',required=True);q.add_argument('--observed-at');q.add_argument('--fixture',action='store_true')
    q=s.add_parser('complete-host-task');q.add_argument('task_id');q.add_argument('lease_token');q.add_argument('result',type=Path)
    q=s.add_parser('capture-detail');q.add_argument('task_id');q.add_argument('lease_token');q.add_argument('job',type=Path);q.add_argument('--source-url',required=True);q.add_argument('--tool-ref',required=True)
    q=s.add_parser('block-task');q.add_argument('task_id');q.add_argument('lease_token');q.add_argument('--code',required=True);q.add_argument('--note',required=True)
    q=s.add_parser('retry-task');q.add_argument('task_id');q.add_argument('--reason',required=True)
    for name in ('review-packet','coverage'):
        q=s.add_parser(name);q.add_argument('run_id')
    q=s.add_parser('assess');q.add_argument('assessment',type=Path)
    q=s.add_parser('decision');q.add_argument('event',type=Path)
    q=s.add_parser('audit');q.add_argument('record',type=Path)
    q=s.add_parser('report');q.add_argument('run_id');q.add_argument('--offer-followup',action='store_true');q.add_argument('--text-only',action='store_true')
    q=s.add_parser('handoff');q.add_argument('report_id');q.add_argument('number',type=int);q.add_argument('--profile-id',required=True);q.add_argument('--facts',type=Path)
    a=p.parse_args(argv)
    try:
        with Store(a.db) as store:
            cmd=a.cmd
            if cmd=='init':result={'engine_version':__version__,'schema':2,'database':str(a.db),'persistent_read_write':'created/opened','scheduler':'not_configured'}
            elif cmd=='sync-registry':result=sync_registry(store,a.provider,year=a.year,transport=PublicHTTP(enabled=a.allow_network,max_bytes=30_000_000),budget_seconds=a.budget_seconds,restart=a.restart)
            elif cmd=='reconcile-companies':result=reconcile(store)
            elif cmd=='unlink-company':unlink_company(store,a.alias_id,reason=a.reason);result={'unlinked':a.alias_id}
            elif cmd=='override-identifier':result={'identifier_override_id':override_identifier(store,**read_json(a.correction))}
            elif cmd=='revoke-identifier-override':result={'revoked':revoke_identifier_override(store,a.override_id,reason=a.reason)}
            elif cmd=='session':result=session(store,a.profile_id,request=a.request,host=a.host,new_cycle=a.new_cycle)
            elif cmd=='summary':result=summary(store,a.run_id)
            elif cmd=='universe-audit':result=universe_audit(store,a.run_id,dimension=a.dimension,after=a.after,page_size=a.page_size)
            elif cmd=='candidate-audit':result=candidate_audit(store,a.run_id,report_id=a.report_id,after=a.after,page_size=a.page_size)
            elif cmd=='expand-employers':result={'job_employers_added_to_unresolved_frontier':store.expand_employer_frontier(a.run_id)}
            elif cmd=='discover':result=discover(store,a.run_id,transport=PublicHTTP(enabled=a.allow_network),budget_seconds=a.budget_seconds,strategy=a.strategy)
            elif cmd=='recheck-legacy':result=recheck_legacy(store,a.run_id,transport=PublicHTTP(enabled=a.allow_network),budget_seconds=a.budget_seconds)
            elif cmd=='packet':result=packet(store,a.run_id,section=a.section,after=a.after,page_size=a.page_size)
            elif cmd=='profile':result={'profile_revision':store.set_profile(a.profile_id,read_json(a.facts))}
            elif cmd=='import-registry':result=import_registry(store,a.path,kind=a.kind,registry=a.registry,source_url=a.source_url,scope=a.scope,completeness=a.completeness,provenance='fixture' if a.fixture else 'host_import')
            elif cmd=='import-legacy':result={'preserved_legacy_records':store.import_legacy(a.profile_id,read_json(a.records))}
            elif cmd=='companies':
                if not 1<=a.page_size<=10000:raise EngineError('page-size must be 1..10000; this is paging, not a search cap')
                rows=[dict(r) for r in store.db.execute('SELECT * FROM companies WHERE id>? ORDER BY id LIMIT ?',(a.after,a.page_size+1))]
                more=len(rows)>a.page_size;rows=rows[:a.page_size]
                result={'companies':rows,'has_more':more,'next_cursor':rows[-1]['id'] if more else None}
            elif cmd=='source':result={'source_id':store.add_source(**read_json(a.config))}
            elif cmd=='plan':result={'run_id':store.plan_run(a.profile_id,scope='targeted' if a.targeted else 'broad',scope_note=a.scope_note,company_ids=read_json(a.company_ids) if a.company_ids else None,parent_run_id=a.parent_run)}
            elif cmd=='attach-source':store.attach_source(a.run_id,a.source_id);result={'attached':True}
            elif cmd=='collect':result=collect(store,a.run_id,transport=PublicHTTP(enabled=a.allow_network),budget_seconds=a.budget_seconds,include_details=a.details,source_ids=a.source_id)
            elif cmd=='split-job':result={'individual_job_ids':store.split_campaign(a.run_id,a.job_id,read_json(a.roles),evidence_ref=a.evidence_ref)}
            elif cmd=='next-task':result=store.claim(a.run_id,kinds=tuple(a.kind or ['legacy_recheck','source_discovery','missing_job_recheck','detail_discovery','inventory']),lease_seconds=a.lease_seconds)
            elif cmd=='ingest':result=import_host_capture(store,a.task_id,a.lease_token,a.capture.read_bytes(),source_url=a.source_url,tool_ref=a.tool_ref,observed_at=a.observed_at,fixture=a.fixture)
            elif cmd=='complete-host-task':result={'observation_id':store.complete_host_task(a.task_id,a.lease_token,**read_json(a.result))}
            elif cmd=='capture-detail':result=store.commit_detail(a.task_id,a.lease_token,Job(**read_json(a.job)),source_url=a.source_url,payload=a.job.read_bytes(),origin='host_export',tool_ref=a.tool_ref)
            elif cmd=='block-task':store.fail_task(a.task_id,a.lease_token,code=a.code,note=a.note);result={'status':'blocked'}
            elif cmd=='retry-task':result={'status':'queued','task_id':store.retry_blocked(a.task_id,reason=a.reason)}
            elif cmd=='review-packet':result=store.review_packet(a.run_id)
            elif cmd=='coverage':result=store.coverage(a.run_id)
            elif cmd=='assess':result={'assessment_id':store.assess(**read_json(a.assessment))}
            elif cmd=='decision':result={'event_id':store.user_event(**read_json(a.event))}
            elif cmd=='audit':result={'audit_id':store.record_audit(**read_json(a.record))}
            elif cmd=='report':
                result=render(store,a.run_id,offer_followup=a.offer_followup)
                if a.text_only:print(result['text'],end='');return 0
            elif cmd=='handoff':print(handoff(store,a.report_id,a.number,profile_id=a.profile_id,selected_facts=read_json(a.facts) if a.facts else []),end='');return 0
            else:raise EngineError('unknown command')
            print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
        return 0
    except (EngineError,OSError,ValueError,KeyError,TypeError) as e:
        print(json.dumps({'error':type(e).__name__,'message':str(e)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
