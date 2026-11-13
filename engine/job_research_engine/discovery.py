"""A real, bounded employer frontier; unresolved companies remain in the run."""
import json
import re
import time
from urllib.parse import urlsplit
from .htmltools import html,links
from .korean import detect_kind
from .model import EngineError
from .transport import PublicHTTP,FetchError


INFORMATIONAL_LABELS={'인재상','인사제도','인재육성','교육제도','복리후생','복지제도','채용절차','채용절차안내',
    '채용프로세스','전형절차','채용문의','채용faq','faq','채용q&a','q&a','지원서수정','지원결과확인',
    '합격자조회','전형결과확인','people','culture','benefits','welfare','recruitmentprocess'}


def career_links(root,url):
    candidates=[];informational=[]
    for target,label,node in links(root,url):
        if not re.search(r'채용|인재채용|careers?|recruit|join us|job opening',label+' '+urlsplit(target).netloc+' '+urlsplit(target).path,re.I):continue
        folded=re.sub(r'\s+','',label).lower()
        if folded in INFORMATIONAL_LABELS:
            informational.append({'url':target,'label':label});continue
        if target not in candidates:candidates.append(target)
    return candidates,informational

def discover(store,run_id,*,transport=None,budget_seconds=30,strategy='balanced'):
    if strategy not in {'balanced','oldest'}:raise EngineError('unknown discovery strategy')
    transport=transport or PublicHTTP();started=time.monotonic();checked=0;found=0;blocked=0
    plan=None;candidate_iter=None;scope_attempts=[]
    if strategy=='balanced':
        from .frontier import discovery_frontier
        plan=discovery_frontier(store,run_id);candidate_iter=iter(plan['candidates'])
    while time.monotonic()-started<budget_seconds:
        candidate=next(candidate_iter,None) if candidate_iter is not None else None
        if candidate_iter is not None and candidate is None:break
        task=store.claim(run_id,kinds=('source_discovery',),lease_seconds=180,task_id=candidate['task_id'] if candidate else None)
        if not task and candidate:continue
        if not task:break
        company=store.row('companies',task['company_id']);url=candidate['homepage'] if candidate else company.get('homepage')
        if candidate:scope_attempts.append({k:candidate[k] for k in ('task_id','company_id','scope_key','homepage_record_id')})
        if not url:
            # Official identity links can supply another registry's homepage without name matching.
            from .identity import canonical
            identity=canonical(store,company['id'])
            related=store.db.execute('''SELECT c.homepage FROM companies c LEFT JOIN company_aliases a ON a.alias_id=c.id
                WHERE (c.id=? OR a.canonical_id=?) AND c.homepage IS NOT NULL ORDER BY c.id LIMIT 1''',(identity,identity)).fetchone()
            if related:url=related[0]
        try:
            if not url:raise FetchError('official_homepage_unknown','official identifier/name search required through host; company retained')
            if not transport.permitted_by_robots(url):raise FetchError('robots_disallowed','homepage policy prevents native scan; use another permitted source')
            response=transport.get(url);root=html(response.body);candidates,informational=career_links(root,response.url)
            if not candidates:
                # Retain the actual attempted page even when discovery was unsuccessful.
                with store.transaction():
                    store._observe(task,response.url,response.body,media_type=response.headers.get('content-type','text/html'),
                      origin=getattr(transport,'evidence_origin','native_http'),tool_ref=None,observed_at=None)
                raise FetchError('career_link_not_found','public homepage inspected; host/company or group search still required')
            for target in candidates:
                kind=detect_kind(target)
                source=store.add_source(kind,target,company_id=company['id'],policy='robots',
                    evidence_ref='official homepage '+response.url,settings={'employer':company['name'],'discovery_stage':'candidate_career_link; inventory/details not yet verified','job_company_binding':'unverified_homepage_reference','homepage_record_id':candidate['homepage_record_id'] if candidate else company['id']})
                store.attach_source(run_id,source);found+=1
            with store.transaction():
                oid=store._observe(task,response.url,response.body,media_type=response.headers.get('content-type','text/html'),
                  origin=getattr(transport,'evidence_origin','native_http'),tool_ref=None,observed_at=None)
                store._check_lease(task['id'],task['lease_token'])
                store.db.execute("UPDATE tasks SET status='done',finished_at=?,lease_token=NULL,lease_until=NULL WHERE id=?",(store._now(),task['id']))
                store._log('task',task['id'],'native_source_discovery',{'observation':oid,'observed_links':candidates,'informational_links_not_inventories':informational})
            checked+=1
        except FetchError as e:
            store.fail_task(task['id'],task['lease_token'],code=e.code,note=str(e),retry_after=e.retry_after);blocked+=1
        except (EngineError,ValueError,KeyError) as e:
            store.fail_task(task['id'],task['lease_token'],code='homepage_contract_failure',note=str(e));blocked+=1
    return {'homepages_checked_with_career_links':checked,'sources_discovered':found,'blocked_attempts':blocked,
            'strategy':strategy,'scope_attempts':scope_attempts,
            'frontier':{k:v for k,v in plan.items() if k!='candidates'} if plan else None,
            'stop_reason':'execution_checkpoint' if time.monotonic()-started>=budget_seconds else 'no_ready_discovery_tasks'}
