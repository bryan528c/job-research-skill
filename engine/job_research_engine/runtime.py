"""Private cross-process restoration for a natural-language host request."""
import json
import uuid
from .model import EngineError,digest,dump,required

def state_signature(store,profile_id,run_id):
    """Execution invariants, excluding new host-session receipts and lease wall time."""
    data={
      'profile':dict(store.row('profiles',profile_id)),
      'legacy':[dict(r) for r in store.db.execute('SELECT * FROM legacy_records WHERE profile_id=? ORDER BY id',(profile_id,))],
      'decisions':[dict(r) for r in store.db.execute('SELECT * FROM user_events WHERE profile_id=? ORDER BY id',(profile_id,))],
      'jobs':[tuple(r) for r in store.db.execute('SELECT job_id,carried FROM run_jobs WHERE run_id=? ORDER BY job_id',(run_id,))],
      'job_state':[tuple(r) for r in store.db.execute('SELECT j.* FROM jobs j JOIN run_jobs rj ON rj.job_id=j.id WHERE rj.run_id=? ORDER BY j.id',(run_id,))],
      'versions':[tuple(r) for r in store.db.execute('SELECT v.* FROM job_versions v JOIN run_jobs rj ON rj.job_id=v.job_id WHERE rj.run_id=? ORDER BY v.job_id,v.content_hash',(run_id,))],
      'assessments':[tuple(r) for r in store.db.execute('SELECT * FROM assessments WHERE profile_id=? ORDER BY id',(profile_id,))],
      'reports':[tuple(r) for r in store.db.execute('SELECT * FROM reports WHERE profile_id=? ORDER BY id',(profile_id,))],
      'source_progress':[tuple(r) for r in store.db.execute('SELECT * FROM run_sources WHERE run_id=? ORDER BY source_id',(run_id,))],
      'tasks':[tuple(r) for r in store.db.execute('SELECT id,kind,status,cursor,created_at,error_code FROM tasks WHERE run_id=? ORDER BY id',(run_id,))],
      'scope':[r[0] for r in store.db.execute('SELECT company_id FROM run_companies WHERE run_id=? ORDER BY company_id',(run_id,))],
    }
    return digest(dump(data))

def summary(store,run_id):
    run=store.row('runs',run_id);profile=run['profile_id']
    counts=lambda sql,args=():store.db.execute(sql,args).fetchone()[0]
    tasks=[dict(r) for r in store.db.execute('SELECT kind,status,COUNT(*) AS count,MIN(created_at) AS oldest FROM tasks WHERE run_id=? GROUP BY kind,status ORDER BY kind,status',(run_id,))]
    return {'run_id':run_id,'profile_id':profile,'profile_revision':store.row('profiles',profile)['revision'],
      'planned_source_company_records':counts('SELECT COUNT(*) FROM run_companies WHERE run_id=?',(run_id,)),
      'jobs':counts('SELECT COUNT(*) FROM run_jobs WHERE run_id=?',(run_id,)),
      'legacy_preserved':counts('SELECT COUNT(*) FROM legacy_records WHERE profile_id=?',(profile,)),
      'legacy_unresolved':counts('SELECT COUNT(*) FROM legacy_records WHERE profile_id=? AND resolution_json IS NULL',(profile,)),
      'user_events':counts('SELECT COUNT(*) FROM user_events WHERE profile_id=?',(profile,)),
      'task_groups':tasks,'state_sha256':state_signature(store,profile,run_id),'national_coverage':'unknown',
      'scheduler':'not_modified','stop_reason':run['stop_reason']}

def session(store,profile_id,*,request,host='codex',new_cycle=False,scope_note=None):
    required(request,'natural-language request');store.row('profiles',profile_id)
    old=store.db.execute("SELECT id FROM runs WHERE profile_id=? AND status='running' ORDER BY created_at DESC LIMIT 1",(profile_id,)).fetchone()
    if old and not new_cycle:run_id=old[0];restored=True
    else:
        run_id=store.plan_run(profile_id,scope_note=scope_note or request,parent_run_id=old[0] if old else None);restored=False
    result=summary(store,run_id);sid=uuid.uuid4().hex
    store.db.execute('INSERT INTO host_sessions VALUES(?,?,?,?,?,?,?)',(sid,profile_id,run_id,request,host,store._now(),dump(result)))
    return {**result,'session_id':sid,'restored_existing_run':restored,
      'next':'Use packet pages, collect native sources, resolve host tasks, assess duties against stored facts, audit and report. No recommendation quota.'}

def packet(store,run_id,*,section='jobs',after='',page_size=50):
    if not 1<=page_size<=1000:raise EngineError('page size must be 1..1000; follow cursors to exhaustion')
    run=store.row('runs',run_id)
    if section=='jobs':
        rows=[j for j in store.list_run_jobs(run_id) if j['id']>after]
        rows.sort(key=lambda j:j['id']);items=rows[:page_size];more=len(rows)>page_size
    elif section in {'tasks','legacy'}:
        if section=='tasks':
            query="SELECT * FROM tasks WHERE run_id=? AND status NOT IN ('done','superseded') AND id>? ORDER BY id LIMIT ?";args=(run_id,after,page_size+1)
        else:
            query='SELECT * FROM legacy_records WHERE profile_id=? AND id>? ORDER BY id LIMIT ?';args=(run['profile_id'],after,page_size+1)
        rows=[dict(r) for r in store.db.execute(query,args)];items=rows[:page_size];more=len(rows)>page_size
    else:raise EngineError('unknown packet section')
    return {'items':items,'section':section,'has_more':more,'next_cursor':items[-1]['id'] if more else None}
