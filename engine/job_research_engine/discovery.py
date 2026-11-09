"""A real, bounded employer frontier; unresolved companies remain in the run."""
import json
import re
import time
from urllib.parse import urlsplit
from .htmltools import html,links
from .korean import detect_kind
from .model import EngineError
from .transport import PublicHTTP,FetchError

def discover(store,run_id,*,transport=None,budget_seconds=30):
    transport=transport or PublicHTTP();started=time.monotonic();checked=0;found=0;blocked=0
    while time.monotonic()-started<budget_seconds:
        task=store.claim(run_id,kinds=('source_discovery',),lease_seconds=180)
        if not task:break
        company=store.row('companies',task['company_id']);url=company.get('homepage')
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
            response=transport.get(url);root=html(response.body);candidates=[]
            for target,label,node in links(root,response.url):
                if re.search(r'채용|인재채용|careers?|recruit|join us|job opening',label+' '+urlsplit(target).path,re.I):
                    if target not in candidates:candidates.append(target)
            if not candidates:
                # Retain the actual attempted page even when discovery was unsuccessful.
                with store.transaction():
                    store._observe(task,response.url,response.body,media_type=response.headers.get('content-type','text/html'),
                      origin=getattr(transport,'evidence_origin','native_http'),tool_ref=None,observed_at=None)
                raise FetchError('career_link_not_found','public homepage inspected; host/company or group search still required')
            for target in candidates:
                kind=detect_kind(target)
                source=store.add_source(kind,target,company_id=company['id'],policy='robots',
                    evidence_ref='official homepage '+response.url,settings={'employer':company['name']})
                store.attach_source(run_id,source);found+=1
            with store.transaction():
                oid=store._observe(task,response.url,response.body,media_type=response.headers.get('content-type','text/html'),
                  origin=getattr(transport,'evidence_origin','native_http'),tool_ref=None,observed_at=None)
                store._check_lease(task['id'],task['lease_token'])
                store.db.execute("UPDATE tasks SET status='done',finished_at=?,lease_token=NULL,lease_until=NULL WHERE id=?",(store._now(),task['id']))
                store._log('task',task['id'],'native_source_discovery',{'observation':oid,'observed_links':candidates})
            checked+=1
        except FetchError as e:
            store.fail_task(task['id'],task['lease_token'],code=e.code,note=str(e),retry_after=e.retry_after);blocked+=1
        except (EngineError,ValueError,KeyError) as e:
            store.fail_task(task['id'],task['lease_token'],code='homepage_contract_failure',note=str(e));blocked+=1
    return {'homepages_checked_with_career_links':checked,'sources_discovered':found,'blocked_attempts':blocked,
            'stop_reason':'execution_checkpoint' if time.monotonic()-started>=budget_seconds else 'no_ready_discovery_tasks'}
