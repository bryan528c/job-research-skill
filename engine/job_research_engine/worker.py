from __future__ import annotations
import json
import os
import re
import time
from urllib.parse import urlsplit
from .adapters import parse_page,request_url
from .model import EngineError,LeaseLost
from .store import Store
from .transport import FetchError,PublicHTTP


def collect(store: Store,run_id: str, *, transport=None, budget_seconds: float | None=None,include_details=False,source_ids=None) -> dict:
    """Drain ready native source-page tasks. Budget is a checkpoint, never a completeness target."""
    transport=transport or PublicHTTP();started=time.monotonic();pages=0;blocked=0
    while True:
        if budget_seconds is not None and time.monotonic()-started>=budget_seconds:
            reason='execution_budget_checkpoint';break
        task=store.claim(run_id,kinds=('inventory','job_detail','detail_discovery') if include_details else ('inventory',),lease_seconds=180,source_ids=source_ids)
        if not task:reason='no_ready_native_tasks';break
        source=store.row('sources',task['source_id'])
        response=None
        try:
            if source['policy'] in {'host_only','unreviewed'}:
                raise FetchError('host_or_policy_review_required','source must be inspected through an authorized host or approved adapter')
            if task['kind']=='inventory' and json.loads(source['settings_json']).get('inventory_requires_host'):
                raise FetchError('host_inventory_required','Use the actual rendered list/end controls; native detail reads remain separate')
            url,secret_env=request_url(source,task['cursor'])
            if task['kind']!='inventory':
                url=json.loads(task['payload_json']).get('url') or store.row('jobs',json.loads(task['payload_json'])['job_id'])['job_url']
            if source['policy']=='robots' and not transport.permitted_by_robots(url):
                raise FetchError('robots_disallowed','respect robots restriction; use another permitted source')
            secrets=None
            if secret_env:
                value=os.environ.get(secret_env)
                if not value:raise FetchError('missing_credential',f'{secret_env} not configured; other sources continue')
                secrets={'authKey':value}
            from .domestic import KINDS as DOMESTIC_KINDS,request_spec,jobflex_request
            from .korean import detect_kind
            actual_kind=source['kind'] if task['kind']=='inventory' else detect_kind(url)
            if (task['kind']!='inventory' and (source['kind']=='ninehire-list' or json.loads(source['settings_json']).get('inventory_contract')=='ninehire-rendered')
                and urlsplit(url).netloc==urlsplit(source['url']).netloc and re.fullmatch(r'/job_posting/[A-Za-z0-9]{4,40}/?',urlsplit(url).path)):
                actual_kind='ninehire-detail'
            if (task['kind']!='inventory' and source['kind']=='greeting-list'
                and urlsplit(url).netloc==urlsplit(source['url']).netloc
                and re.fullmatch(r'/(?:ko/|en/)?o/[1-9][0-9]*/?',urlsplit(url).path)):
                actual_kind='greeting-detail'
            if actual_kind in {'gabia-list','gabia-detail'}:
                from .legacy_sources import gabia_public_request,gabia_office_no
                settings=json.loads(source['settings_json'])
                if not settings.get('office_no'):
                    info=transport.get_gabia(gabia_public_request('site-information')['url'])
                    settings['office_no']=gabia_office_no(info.body)
                    with store.transaction():
                        store._check_lease(task['id'],task['lease_token'])
                        store._observe(task,info.url,info.body,media_type='application/json',origin=getattr(transport,'evidence_origin','native_http'),tool_ref=None,observed_at=None)
                        store.db.execute('UPDATE sources SET settings_json=? WHERE id=?',(json.dumps(settings),source['id']))
                    source['settings_json']=json.dumps(settings)
                api=gabia_public_request(actual_kind,url,office_no=settings['office_no'])['url']
                response=transport.get_gabia(api)
            elif actual_kind=='jobflex-detail':
                api,prefix=jobflex_request(url);response=transport.get_jobflex(api,prefix)
            elif actual_kind in DOMESTIC_KINDS:
                api,fields=request_spec(actual_kind,url,task['cursor'] if task['kind']=='inventory' else None,json.loads(source['settings_json']))
                response=transport.read_json(api,fields)
            elif source['kind']=='skcareers-list' and task['kind']=='inventory':
                if source['policy']!='public_read_form':raise FetchError('read_form_policy_required','public inventory form needs explicit reviewed policy')
                response=transport.read_form(url,{'sort':'2','searchText':'','corpCode':'','jobRole':'','recruitType':'','workingType':'','workingRegion':'',**json.loads(source['settings_json']).get('filters',{})})
            else:response=transport.get(url,secret_query=secrets)
            if task['kind']!='inventory':
                from .korean import detect_kind,parse_detail
                detail_settings=json.loads(source['settings_json'])
                prior_id=json.loads(task['payload_json']).get('job_id')
                if actual_kind=='cj-detail' and prior_id:
                    detail_settings['listing_job']=json.loads(store.row('jobs',prior_id)['content_json'])
                job=parse_detail(actual_kind,response.body,url,detail_settings)
                iframe=job.source_context.get('observed_description_iframe') if actual_kind=='jobkorea-detail' else None
                if iframe:
                    from dataclasses import replace
                    from .jobkorea import description_body
                    # Retain both actual reads, at their separate clocks. The
                    # body route is an observed public src, never an invented API.
                    with store.transaction():
                        store._check_lease(task['id'],task['lease_token'])
                        outer_oid=store._observe(task,response.url,response.body,media_type='text/html',origin=getattr(transport,'evidence_origin','native_http'),tool_ref=None,observed_at=None)
                    if source['policy']=='robots' and not transport.permitted_by_robots(iframe):raise FetchError('robots_disallowed','observed description iframe restricted')
                    response=transport.get(iframe)
                    body=description_body(response.body,response.url,job.external_id)
                    job=replace(job,description=body['description'],detail_verified=body['detail_verified'],
                        raw={**job.raw,**{k:v for k,v in body.items() if k not in {'description','detail_verified'}}},
                        source_context={**job.source_context,'metadata_only':False,'outer_observation_id':outer_oid})
                store.commit_detail(task['id'],task['lease_token'],job,source_url=response.url,payload=response.body,
                                    origin=getattr(transport,'evidence_origin','native_http'))
                pages+=1;continue
            page=parse_page(source,response.body,task['cursor'])
            result=store.commit_page(task['id'],task['lease_token'],page,source_url=response.url,
                payload=response.body,media_type=response.headers.get('content-type','application/octet-stream'),
                origin=getattr(transport,'evidence_origin','native_http'))
            pages+=1
            if result['gap']:blocked+=1
        except LeaseLost:
            blocked+=1 # Another worker owns it now; no stale writes.
        except FetchError as exc:
            store.fail_task(task['id'],task['lease_token'],code=exc.code,note=str(exc),retry_after=exc.retry_after)
            blocked+=1
        except (EngineError,KeyError,TypeError,ValueError) as exc:
            if response is not None:
                with store.transaction():
                    store._check_lease(task['id'],task['lease_token'])
                    oid=store._observe(task,response.url,response.body,media_type=response.headers.get('content-type','application/octet-stream'),
                        origin=getattr(transport,'evidence_origin','native_http'),tool_ref=None,observed_at=None)
                    content=json.loads(store.row('tasks',task['id'])['payload_json']);content['failed_observation_id']=oid
                    store.db.execute('UPDATE tasks SET payload_json=? WHERE id=?',(json.dumps(content),task['id']))
            store.fail_task(task['id'],task['lease_token'],code='parse_or_contract_failure',note=str(exc)[:500])
            blocked+=1
    coverage=store.checkpoint(run_id,stop_reason=reason)
    return {'pages_committed':pages,'blocked_or_failed_attempts':blocked,'stop_reason':reason,'coverage':coverage}


def import_host_capture(store: Store,task_id: str,token: str,payload: bytes, *, source_url: str,
                        tool_ref: str,observed_at: str | None=None,fixture=False) -> dict:
    task=store.row('tasks',task_id);source=store.row('sources',task['source_id'])
    page=parse_page(source,payload,task['cursor'])
    return store.commit_page(task_id,token,page,source_url=source_url,payload=payload,
        origin='fixture' if fixture else 'host_export',tool_ref=tool_ref,observed_at=observed_at)
