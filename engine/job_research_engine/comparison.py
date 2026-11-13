"""Small independently specified cohorts, not nationwide recall or blind scoring.

The host supplies exact individual-role identities and evidence. This module
does not browse, infer suitability from titles, or certify the host's judgment.
Private cohort and candidate exports must remain outside the public repository.
"""
from collections import Counter
from .model import EngineError, required, timestamp


MODES={'natural_unseeded','direct_seeded','restored_snapshot','host_followthrough'}


def deadline_matches(actual,expected,precision=None):
    if precision=='minute' and actual.get('kind')==expected.get('kind')=='datetime':
        return timestamp(actual['at']).replace(second=0,microsecond=0)==timestamp(expected['at']).replace(second=0,microsecond=0)
    return actual==expected


def compare(cohort,run):
    if cohort.get('schema')!=1 or run.get('schema')!=1:
        raise EngineError('comparison schema 1 required')
    required(cohort.get('provenance'),'independent cohort provenance')
    for field in ('started_at','finished_at'):timestamp(run.get(field))
    if timestamp(run['finished_at'])<timestamp(run['started_at']):raise EngineError('comparison observation window is reversed')
    mode=run.get('mode')
    if mode not in MODES:raise EngineError('comparison mode required')
    if mode=='natural_unseeded' and run.get('sample_seeded') is not False:
        raise EngineError('natural discovery requires an explicit unseeded input declaration')
    if run.get('blind') is not False:
        raise EngineError('this diagnostic does not establish evaluator blinding')
    roles=cohort.get('roles');records=run.get('records')
    if not isinstance(roles,list) or not roles or not isinstance(records,list):
        raise EngineError('independent individual roles and actual run records required')
    ids=[required(r.get('sample_id'),'sample identity') for r in roles]
    if len(ids)!=len(set(ids)):raise EngineError('duplicate independent sample identity')
    totals=Counter({k:0 for k in ('source_unregistered','missed','unreviewed','misclassified',
        'report_omission','report_unexpected','duplicate','deadline_error','link_error','application_state_error','unconfirmed')})
    result=[];carried=0;new=0
    for role in roles:
        # Identity is explicit: observed canonical URL plus individual role key.
        # A campaign parent or a similar title/new round cannot satisfy a role.
        identities=role.get('identities')
        if not identities or any(not isinstance(x,list) or len(x)!=2 for x in identities):
            raise EngineError('sample requires exact [posting URL, individual role key] identities')
        keys={tuple(x) for x in identities}
        found=[r for r in records if (r.get('job_url'),r.get('role_key','')) in keys]
        errors=[];expected=role.get('expected',{})
        if not role['sample_id'] in run.get('registered_samples',[]):errors.append('source_unregistered')
        if not found:errors.append('missed')
        if len(found)>1:errors.append('duplicate')
        if found:
            if any(r.get('collected_before_pass') is False for r in found):new+=1
            elif all(r.get('collected_before_pass') is True for r in found):carried+=1
            if not any(r.get('assessment_current') for r in found):errors.append('unreviewed')
            allowed=expected.get('decisions',[])
            if allowed and not any(r.get('assessment_current') and r.get('decision') in allowed for r in found):
                if any(r.get('assessment_current') for r in found):errors.append('misclassified')
            if expected.get('visible') is True and not any(r.get('in_report') for r in found):
                errors.append('report_omission')
            if expected.get('visible') is False and any(r.get('in_report') for r in found):errors.append('report_unexpected')
            application=expected.get('application')
            if application and not all(r.get('application')==application for r in found):errors.append('application_state_error')
            deadline=expected.get('deadline')
            if deadline and not any(deadline_matches(r.get('deadline',{}),deadline,expected.get('deadline_precision')) for r in found):errors.append('deadline_error')
            if any(r.get('link_state')=='error' for r in found):errors.append('link_error')
            if not any(r.get('detail_verified') and r.get('status') in {'open','closed'} for r in found):errors.append('unconfirmed')
            status=expected.get('status')
            if status and status!='unknown' and any(r.get('status') not in {status,'unknown'} for r in found):
                if 'misclassified' not in errors:errors.append('misclassified')
        else:errors.append('unconfirmed')
        totals.update(errors)
        result.append({'sample_id':role['sample_id'],'matched_records':len(found),
            'job_ids':[r['job_id'] for r in found],'errors':errors})
    return {'schema':1,'mode':mode,'blind':False,'sample_seeded':run.get('sample_seeded'),
        'started_at':run['started_at'],'finished_at':run['finished_at'],'individual_sample_roles':len(roles),
        'counts':dict(totals),'items':result,
        'matched_before_pass':carried,'newly_collected_in_pass':new,
        'interpretation':'Overlapping diagnostic counts for this independent small cohort only; no national recall, unique-company count or automated AI-judgment validation.'}
