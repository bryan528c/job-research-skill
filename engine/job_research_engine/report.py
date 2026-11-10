from __future__ import annotations
from datetime import datetime,timezone,timedelta
import json
import re
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from .model import EngineError,public_url,timestamp
from .store import Store


def md(value) -> str:
    return re.sub(r'([\\`*_{}\[\]<>])',r'\\\1',' '.join(str(value).split()))

def local_zone(name):
    try:return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        # The Korean source contract remains usable on stdlib-only Windows.
        return timezone(timedelta(hours=9)) if name=='Asia/Seoul' else timezone.utc if name in {'UTC','Etc/UTC'} else None


def deadline_label(d: dict) -> str:
    kind=d['kind']
    if kind=='datetime':
        dt=timestamp(d['at'])
        original=datetime.fromisoformat(d['at'].replace('Z','+00:00'))
        clock=original.strftime('%H:%M:%S' if original.second or original.microsecond else '%H:%M')
        if original.microsecond:clock+='.'+f'{original.microsecond:06d}'.rstrip('0')
        return original.strftime('%Y-%m-%d ')+clock+original.strftime(' %z')
    if kind=='date':return d['date']+' · 마감 시각 미기재'
    return '상시채용' if kind=='rolling' else '마감 미확인'


def deadline_key(d: dict,zone: str) -> tuple:
    # Date-only has no invented time. Within the same local day, it is displayed first
    # because its time is unknown, not because it was asserted to be midnight.
    if d['kind']=='datetime':
        dt=timestamp(d['at'])
        tz=local_zone(zone);local=dt.astimezone(tz) if tz else dt
        return (0,local.date().isoformat(),1,dt.isoformat())
    if d['kind']=='date':return (0,d['date'],0,'')
    return (1,'',0,'')


def past_deadline(d:dict,asof: str,zone: str) -> bool:
    if d['kind']=='datetime':return timestamp(d['at'])<timestamp(asof)
    if d['kind']=='date':
        tz=local_zone(d.get('timezone') or zone)
        if tz is None:return False
        local=timestamp(asof).astimezone(tz)
        return d['date']<local.date().isoformat()
    return False


def render(store: Store,run_id: str, *, conclusion: str | None=None,offer_followup=False) -> dict:
    run=store.row('runs',run_id);profile=store.row('profiles',run['profile_id'])
    facts=json.loads(profile['facts_json']);zone=facts.get('timezone','UTC')
    rows=store.list_run_jobs(run_id);coverage=store.coverage(run_id)
    actionable=[j for j in rows if j['fresh_application'] and j['recruiting_status']!='closed' and j['effective_decision'] in {'recommend','check'} and j['report_tier']=='actionable']
    actionable.sort(key=lambda j:(deadline_key(j['content']['deadline'],zone),j['employer'],j['title'],j['id']))
    # Preserve every worthwhile candidate. Age/freshness warnings never delete its identity.
    tz=local_zone(zone);asof=timestamp(store._now())
    day=(asof.astimezone(tz) if tz else asof).date().isoformat()
    lines=[f'## {day} 채용 리서치','']
    recs=sum(j['effective_decision']=='recommend' and not past_deadline(j['content']['deadline'],store._now(),zone) for j in actionable)
    lines.append(conclusion or (f'지원 검토 {recs}건, 확인 필요 {len(actionable)-recs}건.' if actionable else '확인된 추천이 아직 없어.'))
    lines.append('');mapping=[]
    for num,j in enumerate(actionable,1):
        assessment=j['assessment'] or {};decision=j['effective_decision'];warnings=[]
        if not j['assessment_current']:warnings.append('개인 조건 또는 공고 변경 후 재평가 필요')
        if not j['seen_this_run']:warnings.append('이전 후보 보존 · 현재 모집 상태 재확인 필요')
        if past_deadline(j['content']['deadline'],store._now(),zone):
            decision='check';warnings.append('표시된 마감 경과 · 연장/새 회차 확인 전 제출 권고 아님')
        if assessment.get('risk'):warnings.append(assessment['risk'])
        label='추천' if decision=='recommend' else '확인 필요'
        lines.append(f"**{num}. {md(j['employer'])} — {md(j['title'])} | {md(deadline_label(j['content']['deadline']))} · {label}**")
        lines.append(md(assessment.get('reason','경험 연결 재확인 필요'))+(' '+md(' / '.join(warnings)) if warnings else ''))
        url=public_url(j['job_url']).replace('(','%28').replace(')','%29')
        links=f'[공고]({url})'
        if j['apply_url'] and j['apply_url']!=j['job_url']:
            target=public_url(j['apply_url']).replace('(','%28').replace(')','%29')
            links+=f' · [지원하기]({target})'
        lines.extend([links,''])
        mapping.append({'number':num,'job_id':j['id'],'content_hash':j['content_hash'],'effective_decision':decision})
    pending=sum(j['effective_decision']=='pending' and j['fresh_application'] and j['recruiting_status']!='closed' for j in rows)
    if pending:lines.extend([f'평가 전 후보 {pending}건은 제외하지 않고 보존했어.',''])
    elapsed=sum(j['deadline_elapsed'] and j['recruiting_status']!='closed' and j['effective_decision'] in {'recommend','check'} for j in rows)
    if elapsed:lines.extend([f'표시된 마감이 지난 기존 후보 {elapsed}건은 연장·새 회차 확인 대기로 보존했어.',''])
    gaps=[j for j in rows if j['effective_decision']=='check' and j['report_tier']!='actionable']
    if gaps:
        lines.extend(['원문 보완 대기와 미래 인재풀은 현재 지원 검토와 구분해 보존했어.',''])
    coverage={**coverage,'retained_non_actionable_checks':[{'job_id':j['id'],'content_hash':j['content_hash'],'report_tier':j['report_tier']} for j in gaps]}
    if coverage['status']!='scope_checked':
        lines.extend(['일부 기업·공고의 수집 또는 검증이 남아 있어 이번 조사는 부분 결과야.',''])
    if offer_followup and actionable:lines.append('원하는 공고만 “번호 + 지원 준비” 또는 “번호 + 새 채팅용 프롬프트”로 이어갈 수 있어.')
    body='\n'.join(lines).rstrip()+'\n'
    report_id=store.save_report(run_id,body,mapping,coverage)
    return {'report_id':report_id,'text':body,'mapping':mapping,'coverage':coverage}


def handoff(store: Store,report_id: str,number: int, *, profile_id: str,selected_facts: list[str] | None=None) -> str:
    job=store.select_report_job(report_id,number,profile_id=profile_id)
    state=store.latest_user_state(profile_id,job)
    if state['decision']=='declined':raise EngineError('user declined; explicit reversal required')
    facts=selected_facts or []
    for fact in facts:
        if re.search(r'(?i)(password|access_token|api_key|비밀번호)\s*[:=]',fact) or re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',fact):
            raise EngineError('unnecessary credentials/contact information in handoff')
    content=json.loads(job['content_json'])
    lines=['이 공고의 지원 준비를 이어가줘. 이전 대화나 다른 AI 메모리에 접근한다고 가정하지 마.',
        f"회사: {job['employer']}",f"직무: {job['title']}",f"회차: {job['round_key']}",
        f"공고: {job['job_url']}",f"마감: {deadline_label(content['deadline'])}",
        f"마지막 관찰: {job['last_seen']}",f"관찰된 모집 상태: {job['recruiting_status']}",
        f"지원 진행: {state['application']}"]
    if job['apply_url']:lines.append('지원: '+job['apply_url'])
    if facts:lines+=['선택하여 전달하는 개인 근거:']+['- '+f for f in facts]
    else:lines.append('개인 사실은 전달하지 않았다. 현재 채팅에서 접근 가능한 관련 메모리부터 확인하고 판단에 필요한 사실만 물어봐.')
    lines+=['먼저 현재 공고·마감·지원 방식·문항을 원문으로 재확인해. 종료된 공고를 새 접수 가능으로 바꾸지 마.',
        '핵심업무와 개인 경험을 비교하고 준비 공백, 우선 작업을 제시해. 성과·문항·글자 제한은 만들지 마.',
        '제출·기업 연락·외부 업로드·예약 변경은 별도 승인 없이 하지 마.']
    return '\n'.join(lines)+'\n'
