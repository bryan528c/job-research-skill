"""Inert contracts observed while following official legacy-employer branches.

Gabia's current public site reads anonymous JSON, whereas the initial HTML can
contain a soft 404 before its client renders the live inventory.  The request
specification below describes those exact GETs; it performs no network calls.
Ninehire's image-only descriptions remain pending evidence rather than becoming
empty inventories or verified text.  No suitability or personal judgments occur
in this module.  Existing adapters must explicitly register these contracts.
"""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import json
import re
from urllib.parse import urljoin, urlsplit

from .htmltools import Node, html, links, next_data
from .korean import deadline, parse_detail as korean_detail, parse_ninehire
from .model import EngineError, Job, Page, public_url

KST = timezone(timedelta(hours=9))
GABIA_API = 'https://recruit-api.gabiaoffice.hiworks.com'
GABIA_SITE = 'https://recruit.gabia.com'
KINDS = {'gabia-list', 'gabia-detail', 'legacy-ninehire-detail', 'legacy-greeting-detail'}


def detect_kind(url):
    p = urlsplit(public_url(url))
    if p.hostname == 'recruit.gabia.com' and not p.query:
        if p.path.rstrip('/') == '/recruit/jobs':
            return 'gabia-list'
        if re.fullmatch(r'/recruit/view/[a-z0-9]{6}/?', p.path):
            return 'gabia-detail'
    return None


def gabia_public_request(kind, job_url=None, *, office_no=None):
    """Exact public UI GETs, including its literal nonsecret tenant selector.

    First fetch site-information and extract its office_no.  A transport must
    separately apply DNS/redirect/robots checks and may not reuse applicant
    cookies or credentials.  Never send these headers to arbitrary hosts.
    """
    if kind == 'site-information':
        return {'method': 'GET',
                'url': GABIA_API + '/v1/career-site/tokens/site-information',
                'headers': {'x-career-site-domain': 'gabia.com'}}
    if isinstance(office_no, bool) or not isinstance(office_no, int) or not 0 < office_no < 10**9:
        raise EngineError('Observed public Gabia office number required')
    if kind not in {'gabia-list', 'gabia-detail'} or detect_kind(job_url) != kind:
        raise EngineError('Exact current Gabia public job URL required; old encrypted rounds are separate')
    url = GABIA_API + f'/v1/career-site/offices/{office_no}/announces'
    if kind == 'gabia-detail':
        url += '/' + urlsplit(job_url).path.rstrip('/').rsplit('/', 1)[-1]
    return {'method': 'GET', 'url': url, 'headers': {}}


def _json_data(payload):
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeError) as error:
        raise EngineError('Official public JSON missing; a shell is not an empty inventory') from error
    if not isinstance(value, dict) or 'data' not in value:
        raise EngineError('Official public JSON envelope changed')
    return value['data']


def gabia_office_no(payload):
    data = _json_data(payload)
    value = data.get('office_no') if isinstance(data, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 10**9:
        raise EngineError('Anonymous Gabia site information missing office number')
    return value


def _gabia_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9]{6}', value):
        raise EngineError('Gabia short-key identity missing or changed')
    return value


def _non_link_text(node):
    if node.tag in {'a', 'script', 'style', 'noscript'}:
        return ''
    return ' '.join(' '.join(_non_link_text(c) if isinstance(c, Node) else c
                            for c in node.children).split())


def _gabia_clock(value):
    # These Korean public site fields display identically as local Korean times
    # in its actual UI; do not invent an end-of-day time for date-only values.
    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
        try:
            return {'kind': 'datetime', 'at': datetime.strptime(value, '%Y-%m-%d %H:%M:%S').replace(tzinfo=KST).isoformat()}
        except ValueError:
            return {'kind': 'unknown', 'source_text': value}
    return deadline(value)


def _gabia_status(row, as_of):
    start, end = _gabia_clock(row.get('apply_start_date')), _gabia_clock(row.get('apply_finish_date'))
    if start['kind'] != 'datetime' or end['kind'] != 'datetime':
        return 'unknown'
    at = as_of or datetime.now(timezone.utc)
    if isinstance(at, str):
        try:
            at = datetime.fromisoformat(at.replace('Z', '+00:00'))
        except ValueError as error:
            raise EngineError('Timezone-aware observation time required') from error
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise EngineError('Timezone-aware observation time required')
    begin, finish = datetime.fromisoformat(start['at']), datetime.fromisoformat(end['at'])
    if finish < begin:
        raise EngineError('Gabia application period is reversed')
    return 'closed' if at > finish else 'open' if at >= begin else 'unknown'


def _gabia_base(row, url, employer, as_of, *, detailed=False, apply_url=None):
    identity = _gabia_id(row.get('announce_id'))
    title = row.get('announce_name')
    if not isinstance(title, str) or not title.strip():
        raise EngineError('Gabia announcement title missing')
    markup = row.get('description') or '' if detailed else ''
    if not isinstance(markup, str):
        raise EngineError('Gabia description contract changed')
    body = html(markup.encode('utf-8'))
    description = body.text()
    positions = row.get('category_position') or []
    locations = row.get('category_location') or []
    if not isinstance(positions, list) or not isinstance(locations, list):
        raise EngineError('Gabia category contract changed')
    media = [public_url(urljoin(url, n.attrs['src'])) for n in body.walk('img') if n.attrs.get('src')]
    verified = detailed and bool(_non_link_text(body) if media else description)
    if apply_url and apply_url != GABIA_SITE + '/recruit/' + identity + '/signup':
        raise EngineError('Observed application destination does not match this Gabia announcement')
    return Job(identity, title.strip(), employer, url,
               # Store only a destination actually observed for this detail. A
               # button's navigation pattern alone is not proof of each result.
               apply_url=public_url(apply_url) if apply_url else None,
               description=description, status=_gabia_status(row, as_of),
               deadline=_gabia_clock(row.get('apply_finish_date')),
               published_at=row.get('created_at'),
               location=' / '.join(str(r.get('category_name') or '') for r in locations if isinstance(r, dict)),
               detail_verified=verified,
               requires_role_split=len(positions) > 1 or detailed and not verified,
               raw={'provider': 'gabia-public', 'announce_type': row.get('announce_type'),
                    'experience': row.get('experience'), 'category_position': positions,
                    'employment_type': row.get('category_type') or [],
                    'department': row.get('category_department') or [],
                    'media_urls': media,
                    'external_detail_urls': [u for u, label, n in links(body, url)],
                    'apply_action': 'observed public start URL' if apply_url else 'onsite 지원하기; destination needs host observation',
                    'pending_reason': 'image-only/empty public description; inspect original media' if detailed and not verified else None,
                    'source_application_period': {'start': row.get('apply_start_date'), 'end': row.get('apply_finish_date')},
                    'required_files': row.get('file_json_information') or []})


def parse_gabia_list(payload, url=GABIA_SITE + '/recruit/jobs', settings=None, *, as_of=None):
    if detect_kind(url) != 'gabia-list':
        raise EngineError('Current Gabia list URL required')
    rows = _json_data(payload)
    if not isinstance(rows, list):
        raise EngineError('Gabia public inventory array missing; not zero jobs')
    employer = (settings or {}).get('employer') or '가비아'
    jobs = [_gabia_base(row, GABIA_SITE + '/recruit/view/' + _gabia_id(row.get('announce_id')),
                        employer, as_of) for row in rows if isinstance(row, dict)]
    if len(jobs) != len(rows):
        raise EngineError('Gabia inventory row contract changed')
    page = Page(jobs, terminal=True, expected_total=len(rows),
                scope_note='Entire anonymous official Gabia announces response; browser unfiltered inventory count must reconcile independently')
    page.validate()
    return page


def parse_gabia_detail(payload, url, settings=None, *, as_of=None):
    if detect_kind(url) != 'gabia-detail':
        raise EngineError('Current Gabia short-key detail URL required')
    row = _json_data(payload)
    if not isinstance(row, dict):
        raise EngineError('Gabia public detail object missing')
    identity = _gabia_id(row.get('announce_id'))
    if identity != urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]:
        raise EngineError('Gabia detail does not match requested announcement')
    config = settings or {}
    job = _gabia_base(row, url, config.get('employer') or '가비아', as_of,
                      detailed=True, apply_url=config.get('observed_apply_url') or config.get('observed_apply_urls',{}).get(identity))
    job.validate()
    return job


def parse_page(source, payload, cursor=None, *, as_of=None):
    if source['kind'] != 'gabia-list' or cursor not in (None, ''):
        raise EngineError('Only the entire observed Gabia public array is supported here')
    try:
        settings = json.loads(source.get('settings_json') or '{}')
    except (ValueError, TypeError) as error:
        raise EngineError('Source settings must be a JSON object') from error
    if not isinstance(settings, dict):
        raise EngineError('Source settings must be a JSON object')
    return parse_gabia_list(payload, source['url'], settings, as_of=as_of)


def parse_ninehire_detail(payload, url):
    root = html(payload)
    props = next_data(root)
    recruitment, post = props.get('recruitment'), props.get('jobPosting')
    if not isinstance(recruitment, dict) or not isinstance(post, dict):
        raise EngineError('Ninehire detail objects missing; no closed-round assumption')
    identity = recruitment.get('addressKey')
    if not isinstance(identity, str) or identity != urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]:
        raise EngineError('Ninehire detail identity mismatch')
    body = html((post.get('content') or '').encode('utf-8'))
    media = [public_url(urljoin(url, n.attrs['src'])) for n in body.walk('img') if n.attrs.get('src')]
    if (_non_link_text(body) if media else body.text()):
        job = parse_ninehire(payload, url)
    else:
        reception = recruitment.get('reception') or {}
        status = 'open' if recruitment.get('jobPostingIsActive') is True and reception.get('canSubmit') is True and recruitment.get('status') == 'in_progress' else 'closed' if recruitment.get('closedAt') or recruitment.get('jobPostingIsActive') is False or recruitment.get('status') in {'closed', 'finished'} else 'unknown'
        job = Job(identity, recruitment.get('externalTitle') or recruitment.get('title') or '',
                  recruitment.get('companyName') or '', url,
                  description=body.text(), status=status, deadline=deadline(reception.get('endAt') or recruitment.get('endAt')),
                  published_at=recruitment.get('createdAt'), requires_role_split=True,
                  raw={'provider': 'ninehire', 'recruitment_id': recruitment.get('recruitmentId'),
                       'application_login_required': recruitment.get('applicantLoginEnabled'),
                       'apply_action': 'onsite button; original media requires inspection',
                       'pending_reason': 'image-only/empty description; original media is not text-verified'})
    job = replace(job, employer=recruitment.get('companyName') or job.employer,
                  raw=dict(job.raw, media_urls=media,
                               # Affiliation is an internal unit on the observed
                               # site (e.g. Quality Division), not its employer.
                               affiliation=recruitment.get('affiliation'),
                               employer_identity='source companyName display; contract legal employer may need confirmation',
                               external_detail_urls=[u for u, label, n in links(body, url)]))
    job.validate()
    return job


def parse_detail(kind, payload, url, settings=None, *, as_of=None):
    if kind == 'gabia-detail':
        return parse_gabia_detail(payload, url, settings, as_of=as_of)
    if kind == 'legacy-ninehire-detail':
        return parse_ninehire_detail(payload, url)
    if kind == 'legacy-greeting-detail':
        job = korean_detail('greeting-detail', payload, url, settings or {})
        props = next_data(html(payload))
        detail = next((q.get('state', {}).get('data', {}).get('data')
                       for q in props.get('dehydratedState', {}).get('queries', [])
                       if 'getOpeningById' in q.get('queryKey', [])), None)
        positions = (detail.get('jobPositionSetting') or {}).get('jobPositions') or [] if detail else []
        source_positions = [{'id': p.get('id'), 'career': p.get('jobPositionCareer'),
                             'employment': p.get('jobPositionEmployment'),
                             'occupation': (p.get('workspaceOccupation') or {}).get('occupation'),
                             'job': (p.get('workspaceJob') or {}).get('job'),
                             'location': (p.get('workspacePlace') or {}).get('location')}
                            for p in positions]
        job = replace(job, location=' / '.join(dict.fromkeys(p['location'] for p in source_positions if p['location'])),
                      raw=dict(job.raw, source_positions=source_positions))
        if not job.detail_verified:
            job = replace(job, requires_role_split=True,
                          raw=dict(job.raw, pending_reason='image-only/empty description; inspect original media'))
        job.validate()
        return job
    raise EngineError('Unsupported legacy continuation detail contract')
