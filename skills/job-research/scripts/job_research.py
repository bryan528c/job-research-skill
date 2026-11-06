#!/usr/bin/env python3
"""Optional offline checks/rendering, not a crawler or an autonomous matching engine.

The host supplies factual observations. These checks detect inconsistent records; they
cannot authenticate observations, establish live URL availability or measure open-web recall.
Python 3.10+, standard library only. No network, credentials, telemetry, or automatic writes.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime
import ipaddress
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import parse_qsl, urlsplit

VERSION = '0.2.0-rc.1'

class ValidationError(ValueError):
    """An internal record is missing or inconsistent; ask the host to resolve it."""


def text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f'{name}: nonempty string required')
    return value.strip()


def public_url(value: str) -> str:
    """Conservative display validation, NOT a network request or ownership check."""
    value = text(value, 'URL')
    if re.search(r'[\s\x00-\x1f\x7f<>\\]', value):
        raise ValidationError('URL: whitespace, control characters or unsafe delimiters')
    p = urlsplit(value)
    try:
        port = p.port
    except ValueError as exc:
        raise ValidationError('URL: invalid port') from exc
    if p.scheme.lower() not in {'https', 'http'} or not p.netloc or not p.hostname:
        raise ValidationError('URL: public http/https URL required')
    if p.username is not None or p.password is not None:
        raise ValidationError('URL: embedded credentials prohibited')
    host = p.hostname.lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
        raise ValidationError('URL: private-network name prohibited')
    if '%' in host or host.isdecimal():
        raise ValidationError('URL: ambiguous encoded/numeric host')
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        try:
            ascii_host = host.encode('idna').decode('ascii')
        except UnicodeError as exc:
            raise ValidationError('URL: malformed host') from exc
        if '.' not in ascii_host or not re.fullmatch(r'[a-z0-9.-]+', ascii_host):
            raise ValidationError('URL: public DNS name required')
        if any(not part or part.startswith('-') or part.endswith('-') for part in ascii_host.split('.')):
            raise ValidationError('URL: malformed DNS labels')
    else:
        if not addr.is_global:
            raise ValidationError('URL: non-public address prohibited')
    sensitive = {'token', 'access_token', 'refresh_token', 'id_token', 'session',
                 'sessionid', 'session_id', 'jsessionid', 'phpsessid', 'sid',
                 'api_key', 'apikey', 'password', 'secret', 'authorization',
                 'signature', 'credential', 'x-amz-signature', 'x-amz-credential'}
    for key, _ in parse_qsl(p.query, keep_blank_values=True):
        key = key.lower()
        if key in sensitive or key.endswith(('_token', '_secret', '_signature')):
            raise ValidationError('URL: credential/session query prohibited; resolve a public URL')
    # Tokens sometimes occur in a fragment or Java-style path. Fail closed on obvious forms.
    if re.search(r'(?i)(?:[;#&])(?:access_token|sessionid|jsessionid|api_key|token)=', value):
        raise ValidationError('URL: credential/session component prohibited')
    return value


def aware_timestamp(value: Any, name: str = 'timestamp') -> datetime:
    raw = text(value, name)
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValidationError(f'{name}: ISO datetime required') from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValidationError(f'{name}: timezone offset required')
    return dt


def deadline_label(d: dict[str, Any]) -> str:
    if not isinstance(d, dict):
        raise ValidationError('deadline: object required')
    kind = d.get('kind')
    if kind == 'datetime':
        dt = aware_timestamp(d.get('at'), 'deadline.at')
        zone = d.get('timezone') or dt.strftime('UTC%z')
        return f'{dt:%Y-%m-%d %H:%M} {zone}'
    if kind == 'date':
        try:
            day = date.fromisoformat(text(d.get('date'), 'deadline.date'))
        except ValueError as exc:
            raise ValidationError('deadline.date: ISO calendar date required') from exc
        if d.get('at') or d.get('time'):
            raise ValidationError('date-only deadline cannot silently carry a time')
        zone = f" · {d['timezone']}" if d.get('timezone') else ''
        return f'{day.isoformat()}{zone} · 마감 시각 미기재'
    if kind == 'rolling':
        return '상시채용 · 현재 접수 상태 별도 확인'
    if kind == 'unknown':
        return '마감 미확인'
    raise ValidationError('deadline.kind must be datetime/date/rolling/unknown')


def validate_job(job: dict[str, Any]) -> None:
    if not isinstance(job, dict):
        raise ValidationError('job: object required')
    for key in ('id', 'employer', 'role', 'round', 'reason'):
        text(job.get(key), f'job.{key}')
    if job.get('decision') not in {'recommend', 'check', 'exclude'}:
        raise ValidationError('job.decision invalid')
    if job.get('recruiting_status') not in {'open', 'closed', 'unknown'}:
        raise ValidationError('job.recruiting_status invalid')
    aware_timestamp(job.get('checked_at'), 'job.checked_at')
    deadline_label(job.get('deadline'))
    links = job.get('links')
    if not isinstance(links, list) or not links:
        raise ValidationError('job.links: at least one observed URL required')
    for link in links:
        public_url(link.get('url'))
        if link.get('kind') not in {'official_job', 'apply', 'platform', 'homepage', 'fallback'}:
            raise ValidationError('link.kind invalid')
        if link.get('status') not in {'verified', 'login_required', 'unverified', 'blocked', 'dead'}:
            raise ValidationError('link.status invalid')
        if link['status'] in {'verified', 'login_required'}:
            aware_timestamp(link.get('checked_at'), 'link.checked_at')
    if job['decision'] == 'recommend':
        if job['recruiting_status'] != 'open' or job.get('blocking_unknowns'):
            raise ValidationError('recommendation has consequential unresolved recruitment/eligibility')
        if not any(l['kind'] in {'official_job', 'platform', 'apply'} and
                   l['status'] in {'verified', 'login_required'} for l in links):
            raise ValidationError('recommendation needs an observed role-specific route, not a generic homepage')


def md(value: str) -> str:
    """Keep observations from injecting Markdown structures; URLs are handled separately."""
    return re.sub(r'([\\`*_{}\[\]<>])', r'\\\1', ' '.join(str(value).split()))


def link_line(job: dict[str, Any]) -> str:
    labels = {'official_job': '공식 공고', 'apply': '지원하기', 'platform': '공고(채용사이트)',
              'homepage': '기업 홈페이지', 'fallback': '대체 확인 경로'}
    results: list[str] = []
    seen: set[str] = set()
    for link in job['links']:
        url = public_url(link['url'])
        if url in seen or link['status'] == 'dead':
            continue
        seen.add(url)
        label = labels[link['kind']]
        if link['status'] == 'login_required':
            label += '·로그인 필요'
        elif link['status'] in {'unverified', 'blocked'}:
            label += '·직접 확인 미완료'
        # Encoded parentheses avoid breaking ordinary Markdown destination syntax.
        results.append(f"[{label}]({url.replace('(', '%28').replace(')', '%29')})")
    return ' · '.join(results)


def render_report(report: dict[str, Any]) -> str:
    """Preserve host's verified deadline ordering, never discard worthwhile jobs for top-N."""
    text(report.get('report_id'), 'report_id')
    lines = [f"## {md(text(report.get('date_label'), 'date_label'))} 채용 리서치",
             '', f"**{md(text(report.get('conclusion'), 'conclusion'))}**", '']
    numbers: set[int] = set()
    actionable = [j for j in report.get('jobs', []) if j.get('decision') != 'exclude'
                  and j.get('user_decision') != 'declined' and j.get('application_stage') != 'submitted']
    expanded = set(report.get('expanded_job_ids', [actionable[0]['id']] if actionable else []))
    for job in actionable:
        validate_job(job)
        number = job.get('report_number')
        if not isinstance(number, int) or isinstance(number, bool) or number < 1 or number in numbers:
            raise ValidationError('report_number must be positive and unique in this report')
        numbers.add(number)
        label = '추천' if job['decision'] == 'recommend' else '확인 필요'
        heading = f"**{number}. {md(job['employer'])} — {md(job['role'])} | {md(deadline_label(job['deadline']))} · {label}**"
        caution = f" 주의: {md(job['risk'])}" if job.get('risk') else ''
        if job['id'] in expanded:
            lines += [heading, md(job['reason']) + caution, link_line(job), '']
        else:
            lines += [heading, md(job['reason']) + caution + ' ' + link_line(job), '']
    if report.get('change_note'):
        lines += [f"변경: {md(report['change_note'])}", '']
    if report.get('limitation'):
        lines += [md(report['limitation']), '']
    if report.get('next_action'):
        lines += [f"**오늘 할 일:** {md(report['next_action'])}", '']
    if report.get('offer_followup') and numbers:
        lines.append("지원 준비를 이어가려면 ‘공고 번호 + 지원 준비’ 또는 ‘공고 번호 + 새 채팅용 프롬프트’라고 해줘.")
    return '\n'.join(lines).rstrip()+'\n'


def resolve_selection(reports: list[dict[str, Any]], selection: str, report_id: str | None = None) -> dict[str, Any]:
    selection = text(selection, 'selection')
    scoped = [r for r in reports if report_id is None or r.get('report_id') == report_id]
    if report_id is not None and not scoped:
        raise ValidationError('unknown report_id; do not guess another report')
    if selection.isdecimal() and report_id is None and len(scoped) != 1:
        raise ValidationError('ambiguous report number: specify the referenced report')
    matches = []
    for r in scoped:
        for job in r.get('jobs', []):
            if (selection.isdecimal() and job.get('report_number') == int(selection)) or job.get('id') == selection:
                matches.append(job)
    identities = {j['id'] for j in matches}
    if len(matches) != 1:
        # Even an identical job observed in two reports has distinct freshness; do not choose silently.
        raise ValidationError('selection does not uniquely identify one observed job/report')
    validate_job(matches[0])
    return matches[0]


def minimal_facts(facts: list[str]) -> list[str]:
    if not isinstance(facts, list):
        raise ValidationError('selected facts must be an explicit list, never a whole memory object')
    clean=[]
    for fact in facts:
        fact = text(fact, 'career fact')
        if re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', fact) or re.search(r'\b\d{6}-[1-4]\d{6}\b', fact):
            raise ValidationError('contact/identity data is unnecessary for a career-planning handoff')
        if re.search(r'(?i)(api[_ -]?key|access[_ -]?token|password|비밀번호)\s*[:=]', fact):
            raise ValidationError('possible credential in transfer facts')
        clean.append(fact)
    return clean


def make_handoff(job: dict[str, Any], selected_facts: list[str], goal: str, progress: str | None = None) -> str:
    """Visible user-selected draft only. No web refresh or cross-provider transfer is performed."""
    validate_job(job)
    facts = minimal_facts(selected_facts)
    goal = text(goal, 'goal')
    progress = progress if progress is not None else job.get('application_stage', '미확인')
    if job.get('user_decision') == 'declined':
        raise ValidationError('user declined this job; obtain an explicit change before preparing it')
    lines = ['아래 선택 공고의 지원 준비를 이어가줘. 이 대화 밖의 메모리나 파일에 접근할 수 있다고 가정하지 마.', '',
             '[선택 공고]', f"회사: {job['employer']}", f"직무: {job['role']}", f"회차: {job['round']}",
             f"공고 식별자: {job['id']}", f"공식 마감: {deadline_label(job['deadline'])}",
             f"마지막 관찰: {job['checked_at']}", f"관찰된 모집 상태: {job['recruiting_status']}"]
    for link in job['links']:
        if link['status'] != 'dead':
            lines.append(f"{link['kind']} ({link['status']}): {public_url(link['url'])}")
    lines += ['', '[관련 개인 근거 — 이 프롬프트로 전달하기로 선택한 사실만]']
    lines += [f'- {fact}' for fact in facts] if facts else ['아직 전달된 개인 근거 없음. 필요한 사실만 짧게 질문해.']
    lines += ['', '[판단과 미확인]', f"현재 판단: {job['decision']}", f"경험 연결: {job['reason']}"]
    if job.get('risk'): lines.append(f"주의: {job['risk']}")
    for unknown in job.get('blocking_unknowns', []): lines.append(f'필수 확인: {unknown}')
    for key, label in [('duties','핵심업무'),('requirements','필수요건'),('selection_process','전형')]:
        if job.get(key): lines.append(f"{label}: {job[key]}")
    lines += [f'현재 지원 단계: {progress}', '', '[요청]', goal,
              '먼저 공고·마감·지원 경로·문항을 최신 공식 자료로 재확인해. 웹 접근이 없으면 그 한계를 밝혀.',
              '모집 종료라면 새 지원 가능으로 표시하지 말고 기존 접수 여부와 후속 전형을 구분해.',
              '핵심업무→내 실제 경험→준비 공백→다음 행동 순서로 계획해. 질문·글자수는 실제 양식 확인 전 만들지 마.',
              '없는 성과·역할·자격·지원 이력·합격률을 만들지 마. 관련 자료가 없으면 필요한 부분만 요청해.',
              '내가 선택한 단계부터 시작하고, 지원서 제출·기업 연락·예약 변경·외부 업로드는 별도 허락 없이 하지 마.']
    return '\n'.join(lines)+'\n'


def audit_receipt(run: dict[str, Any]) -> dict[str, Any]:
    """Check internal accountability; a passed check is not verified browsing or market recall."""
    errors=[]; warnings=[]
    if run.get('skill_version') != VERSION: errors.append('loaded_skill_version_mismatch_or_unknown')
    observations=run.get('observations', [])
    ids=[o.get('id') for o in observations]
    if not ids or any(not x for x in ids) or len(ids)!=len(set(ids)):
        errors.append('missing_or_duplicate_observations')
    obs_ids=set(ids)
    for obs in observations:
        if not obs.get('source_url') and not obs.get('tool_ref'): errors.append('observation_without_source')
        if obs.get('source_url'):
            try: public_url(obs['source_url'])
            except ValidationError: errors.append('unsafe_source_url')
        try: aware_timestamp(obs.get('observed_at'), 'observed_at')
        except ValidationError: errors.append('observation_without_timestamp')
    def refs_valid(refs):
        return isinstance(refs,list) and bool(refs) and all(x in obs_ids for x in refs)
    broad=run.get('scope')=='broad'
    branches=run.get('branches',[])
    if broad and not branches: errors.append('broad_scope_without_branches')
    pending=[]
    branch_ids=[b.get('id') for b in branches]
    if len(branch_ids)!=len(set(branch_ids)) or any(not x for x in branch_ids): errors.append('invalid_branch_identity')
    for b in branches:
        status=b.get('status')
        if status=='checked' and not refs_valid(b.get('evidence_refs')): errors.append('checked_branch_without_evidence')
        elif status=='not_applicable' and not b.get('reason'): errors.append('unjustified_not_applicable')
        elif status in {'gap','deferred'}:
            if b.get('material',True): pending.append(b.get('id'))
            if not b.get('first_gap_at') or not b.get('revisit_trigger'): errors.append('gap_without_age_or_revisit')
        elif status not in {'checked','not_applicable','gap','deferred'}: errors.append('invalid_branch_status')
    if broad:
        for dimension in ['older_open','uncertain_exclusions']:
            check=run.get(dimension,{})
            if check.get('status')=='checked':
                if not refs_valid(check.get('evidence_refs')): errors.append(dimension+'_without_evidence')
            elif check.get('status')=='not_applicable' and check.get('reason'): pass
            else: pending.append(dimension)
        counters=run.get('counter_searches',[])
        if not counters: pending.append('counter_search')
        for check in counters:
            if not refs_valid(check.get('evidence_refs')): errors.append('counter_search_without_evidence')
            if not check.get('different_route_reason'): errors.append('counter_search_not_distinct')
            if check.get('new_fit_ids') and not check.get('followthrough_refs'):
                pending.append('new_fit_branch_unexpanded')
            elif check.get('followthrough_refs') and not refs_valid(check['followthrough_refs']):
                errors.append('followthrough_without_evidence')
    candidates=run.get('candidates',[])
    candidate_ids=[c.get('id') for c in candidates]
    if len(candidate_ids)!=len(set(candidate_ids)): errors.append('duplicate_candidate_identity')
    shown=set(run.get('displayed_job_ids',[]))
    retained=set(run.get('retained_job_ids',[]))
    if retained:
        view=run.get('retained_view',{})
        if not view.get('location') or not refs_valid(view.get('evidence_refs')):
            errors.append('retained_list_not_proven_accessible')
    for c in candidates:
        status=c.get('decision')
        if status not in {'recommend','check','exclude','pending'}: errors.append('candidate_without_disposition')
        if status=='pending' and c.get('material',True): pending.append('unreviewed_candidate:'+str(c.get('id')))
        if status=='exclude' and (not c.get('reason') or not refs_valid(c.get('evidence_refs'))):
            errors.append('exclusion_without_evidence')
        if status=='recommend' and c.get('actionable',True) and c['id'] not in shown|retained:
            errors.append('recommended_candidate_lost_from_report')
    if not shown|retained <= set(candidate_ids): errors.append('report_contains_unknown_candidate')
    if run.get('scope_status')=='complete' and (pending or errors): errors.append('unsupported_scope_complete')
    if not run.get('stop_reason'): errors.append('stop_reason_missing')
    assurance=run.get('evidence_assurance','unknown')
    if assurance=='trace_verified' and not run.get('trace_crosscheck_receipt'):
        errors.append('unsupported_trace_verified_claim')
    warnings.append('Record consistency only: supplied evidence is not authenticated; open-web completeness is not measurable here.')
    if run.get('save_status') not in {'confirmed','not_available','failed','not_requested'}:
        warnings.append('Save status is unknown, not success.')
    return {'status':'fail' if errors else 'pass','errors':sorted(set(errors)),
            'material_gaps':sorted(set(pending)),'warnings':warnings}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('audit','report'):
        p=sub.add_parser(name);p.add_argument('input',type=Path)
    p=sub.add_parser('handoff');p.add_argument('input',type=Path);p.add_argument('--job-id',required=True)
    p.add_argument('--facts',type=Path,help='JSON array of explicitly selected relevant facts; not full memory')
    p.add_argument('--goal',default='지원 방향과 준비 계획을 먼저 정리해줘.')
    p.add_argument('--progress',default=None)
    args=parser.parse_args()
    try:
        obj=json.loads(args.input.read_text(encoding='utf-8'))
        if args.command=='audit':
            result=audit_receipt(obj);print(json.dumps(result,ensure_ascii=False,indent=2));return int(result['status']=='fail')
        if args.command=='report': print(render_report(obj),end='')
        else:
            job=resolve_selection([obj],args.job_id,obj.get('report_id'))
            facts=json.loads(args.facts.read_text(encoding='utf-8')) if args.facts else []
            print(make_handoff(job,facts,args.goal,args.progress),end='')
        return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(f'Error: {exc}',file=sys.stderr);return 2

if __name__=='__main__':
    raise SystemExit(main())
