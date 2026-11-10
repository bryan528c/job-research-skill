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
      'assessment_reporting':[tuple(r) for r in store.db.execute('SELECT ar.* FROM assessment_reporting ar JOIN assessments a ON a.id=ar.assessment_id WHERE a.profile_id=? ORDER BY ar.assessment_id',(profile_id,))],
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


def universe_audit(store,run_id,*,dimension='registry',after='',page_size=100):
    """Compare actual attributed observations with source-record scope, paged.

    Global group/ATS channels are reported separately: a group inventory does
    not prove that every constituent legal entity was independently checked.
    """
    store.row('runs',run_id)
    if dimension not in {'registry','industry','group'}:raise EngineError('unknown universe dimension')
    if not 1<=page_size<=1000:raise EngineError('page size must be1..1000; follow remaining cursors')
    field={'registry':'registry','industry':'industry','group':'group_name'}[dimension]
    rows=store.db.execute(f'''WITH observed AS (
        SELECT t.company_id FROM observations o JOIN tasks t ON t.id=o.task_id
          WHERE t.run_id=? AND t.company_id IS NOT NULL AND o.origin IN ('native_http','host_export')
        UNION SELECT j.company_id FROM jobs j JOIN job_sightings js ON js.job_id=j.id
          JOIN observations o ON o.id=js.observation_id
          WHERE js.run_id=? AND j.company_id IS NOT NULL AND o.origin IN ('native_http','host_export')
      ), scope AS (
        SELECT c.*,COALESCE(NULLIF(c.{field},''),'[unclassified]') AS scope_key,
          EXISTS(SELECT 1 FROM observed v WHERE v.company_id=c.id) AS observed_record,
          EXISTS(SELECT 1 FROM sources s WHERE s.company_id=c.id AND s.enabled=1) AS direct_channel,
          EXISTS(SELECT 1 FROM tasks t WHERE t.run_id=? AND t.company_id=c.id
            AND t.kind='source_discovery' AND t.status NOT IN ('done','superseded')) AS missing_channel_gap
        FROM run_companies rc JOIN companies c ON c.id=rc.company_id WHERE rc.run_id=?
      ) SELECT scope_key AS key,COUNT(*) AS source_records,SUM(observed_record) AS observed_source_records,
          SUM(direct_channel) AS records_with_direct_channel,SUM(missing_channel_gap) AS unresolved_channel_records,
          SUM(homepage IS NOT NULL AND homepage!='') AS records_with_official_homepage
        FROM scope WHERE scope_key>? GROUP BY scope_key ORDER BY scope_key LIMIT ?''',
        (run_id,run_id,run_id,run_id,after,page_size+1)).fetchall()
    more=len(rows)>page_size;items=[dict(r) for r in rows[:page_size]]
    unassigned=store.db.execute('''SELECT COUNT(*) FROM run_sources rs JOIN sources s ON s.id=rs.source_id
        WHERE rs.run_id=? AND s.enabled=1 AND s.company_id IS NULL''',(run_id,)).fetchone()[0]
    return {'dimension':dimension,'items':items,'has_more':more,'next_cursor':items[-1]['key'] if more else None,
      'coverage_unit':'source_company_record; registry overlaps and unresolved identities retained',
      'attribution':'direct company-ID evidence only; global group/ATS observations are not expanded to every legal entity',
      'unassigned_group_or_ats_channels':unassigned,'national_unique_companies':'unknown','national_coverage':'unknown'}
