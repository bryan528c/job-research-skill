"""Explain narrowing without equating uncollected/unreviewed work to exclusions."""
from collections import Counter
import json
from .model import EngineError,digest,timestamp


def candidate_audit(store,run_id,*,report_id=None,after='',page_size=100):
    if not 1<=page_size<=1000:raise EngineError('page size must be1..1000; not a recommendation quota')
    run=store.row('runs',run_id)
    jobs=store.list_run_jobs(run_id)
    records=[];counts=Counter();reasons=Counter()
    recruiting=Counter();applications=Counter();assessment_states=Counter()
    expected=set()
    for j in jobs:
        recruiting[j['recruiting_status']]+=1
        applications[j['user_state']['application']]+=1
        assessment_states['current' if j['assessment_current'] else 'missing_or_stale']+=1
        if j['recruiting_status']=='closed' or j['deadline_elapsed']:stage='closed_or_deadline_elapsed'
        elif j['decomposed_campaign'] or j['equivalent_decomposition']:stage='decomposed_container'
        elif not j['detail_verified'] or j['content'].get('requires_role_split'):stage='detail_or_role_gap'
        elif j['application_not_open_yet']:stage='application_not_open_yet'
        elif not j['fresh_application']:stage='user_decision_or_application_retained'
        elif not j['assessment_current']:stage='assessment_missing_or_stale'
        elif j['effective_decision']=='exclude':stage='assessed_exclude'
        elif j['effective_decision']=='recommend':stage='recommend'
        elif j['report_tier']=='actionable':stage='important_check'
        else:stage='retained_'+j['report_tier']
        counts[stage]+=1
        if stage=='assessed_exclude':reasons[digest(j['assessment']['reason'])]+=1
        if j['fresh_application'] and j['recruiting_status']!='closed' and j['effective_decision'] in {'recommend','check'} and j['report_tier']=='actionable':expected.add(j['id'])
        records.append({'job_id':j['id'],'source_id':j['source_id'],'title':j['title'],
            'employer':j['employer'],'stage':stage,'effective_decision':j['effective_decision'],
            'assessment_current':j['assessment_current'],'report_tier':j['report_tier'],
            'latest_observation_id':j['latest_observation_id'],'content_hash':j['content_hash'],
            'first_seen':j['first_seen'],'assessment_created_at':j['assessment']['created_at'] if j['assessment'] else None})
    comparison=None
    if report_id:
        report=store.row('reports',report_id)
        if report['profile_id']!=run['profile_id']:raise EngineError('report belongs to another profile')
        mapping=json.loads(report['mapping_json']);shown={jid for m in mapping for jid in [m['job_id'],*m.get('equivalent_job_ids',[])]}
        by_id={r['job_id']:r for r in records}
        unreported=expected-shown
        new=[];changed=[];potential=[]
        for jid in sorted(unreported):
            row=by_id[jid]
            if timestamp(row['first_seen'])>timestamp(report['created_at']):new.append(jid)
            elif row['assessment_created_at'] and timestamp(row['assessment_created_at'])>timestamp(report['created_at']):changed.append(jid)
            else:potential.append(jid)
        comparison={'report_id':report_id,'report_created_at':report['created_at'],
            'stored_mapping_count':len(mapping),'current_actionable_count':len(expected),
            'currently_actionable_not_in_checkpoint':sorted(unreported),
            'new_since_checkpoint':new,'reassessed_since_checkpoint':changed,
            'potential_omissions_requiring_historical_review':potential,
            'checkpoint_items_now_changed_or_inactive':sorted(shown-expected),
            'note':'A saved checkpoint is immutable. Later collection/reassessment is not a historical report omission.'}
    records.sort(key=lambda r:r['job_id'])
    page=[r for r in records if r['job_id']>after][:page_size+1];more=len(page)>page_size;page=page[:page_size]
    return {'run_id':run_id,'source_role_records':len(jobs),'stage_counts':dict(sorted(counts.items())),
        'recruiting_status_counts':dict(sorted(recruiting.items())),
        'application_state_counts':dict(sorted(applications.items())),
        'assessment_state_counts':dict(sorted(assessment_states.items())),
        'coverage_unit':'source and individual-role records, not unique vacancies or firms',
        'unreviewed_is_not_excluded':True,'national_coverage':'unknown',
        'exclusion_reason_groups':[{'reason_sha256':key,'source_role_records':n} for key,n in reasons.most_common()],
        'report_comparison':comparison,'items':page,'has_more':more,
        'next_cursor':page[-1]['job_id'] if more else None}
