"""Revalidate recovery hints without inventing applications or closing old rounds."""
import json
import time
from .korean import detect_kind,parse_detail
from .model import EngineError,dump
from .transport import PublicHTTP,FetchError

def recheck_legacy(store,run_id,*,transport=None,budget_seconds=35):
    transport=transport or PublicHTTP();started=time.monotonic();observed=0;blocked=0
    while time.monotonic()-started<budget_seconds:
        task=store.claim(run_id,kinds=('legacy_recheck',),lease_seconds=180)
        if not task:break
        lid=json.loads(task['payload_json'])['legacy_id']
        record=json.loads(store.db.execute('SELECT payload_json FROM legacy_records WHERE id=?',(lid,)).fetchone()[0])
        try:
            url=record.get('url_hint')
            if not url:raise FetchError('legacy_detail_url_unknown','historical hint has no role-specific URL; independent host search remains necessary')
            if not transport.permitted_by_robots(url):raise FetchError('robots_disallowed','native path restricted; keep role for another authorized route')
            response=transport.get(url);metadata={'url':response.url,'provider':detect_kind(response.url)}
            try:
                job=parse_detail(metadata['provider'],response.body,response.url,{'employer':record['employer']})
                metadata.update(title=job.title,observed_status=job.status,detail_verified=job.detail_verified,requires_role_split=job.requires_role_split)
            except (EngineError,ValueError,KeyError):
                metadata['detail_contract']='host_reading_required'
            with store.transaction():
                store._check_lease(task['id'],task['lease_token'])
                oid=store._observe(task,response.url,response.body,media_type=response.headers.get('content-type','application/octet-stream'),
                  origin=getattr(transport,'evidence_origin','native_http'),tool_ref=None,observed_at=None)
                # A successful GET alone cannot prove old-round identity, suitability or an application result.
                store.db.execute("UPDATE tasks SET payload_json=? WHERE id=?",(dump({'legacy_id':lid,'observation_id':oid,'current_observation':metadata}),task['id']))
            store.fail_task(task['id'],task['lease_token'],code='legacy_identity_review',note='Actual source saved; host must compare legal employer, individual role and round before resolution')
            observed+=1
        except FetchError as exc:
            store.fail_task(task['id'],task['lease_token'],code=exc.code,note=str(exc),retry_after=exc.retry_after);blocked+=1
        except (EngineError,ValueError,KeyError) as exc:
            store.fail_task(task['id'],task['lease_token'],code='legacy_contract_failure',note=str(exc)[:500]);blocked+=1
    return {'actual_legacy_pages_saved':observed,'blocked_attempts':blocked,'stop_reason':'execution_checkpoint' if time.monotonic()-started>=budget_seconds else 'no_ready_legacy_tasks',
            'application_states':'unchanged; historical unknowns remain unknown'}
