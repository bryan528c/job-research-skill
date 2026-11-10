from __future__ import annotations

from datetime import date
from html import unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from .model import EngineError, Job, Page, public_url, stable_id, timestamp
from .registry import safe_xml


class _Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style'}:self.hidden+=1
        elif tag in {'p','div','li','br'}:self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in {'script','style'}:self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)


def plain(value: str) -> str:
    p=_Text();p.feed(unescape(value or ''));p.close();return '\n'.join(s.strip() for s in ''.join(p.parts).splitlines() if s.strip())


def _json(payload: bytes):
    try:return json.loads(payload)
    except (ValueError,UnicodeDecodeError) as e:raise EngineError('invalid JSON; possible login/blocked page') from e


def _deadline(raw: str | None) -> dict:
    raw=(raw or '').strip()
    if re.fullmatch(r'\d{8}',raw):raw=f'{raw[:4]}-{raw[4:6]}-{raw[6:]}'
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw):
        try:date.fromisoformat(raw)
        except ValueError:pass
        else:return {'kind':'date','date':raw}
    if raw:
        try:timestamp(raw)
        except EngineError:pass
        else:return {'kind':'datetime','at':raw}
    return {'kind':'unknown',**({'source_text':raw} if raw else {})}


def request_url(source: dict, cursor: str | None) -> tuple[str,str | None]:
    """Return a credential-free endpoint plus an optional environment variable name."""
    settings=json.loads(source['settings_json'])
    kind=source['kind'];url=public_url(source['url']);p=urlsplit(url)
    from .groups import cj_request,detect_kind as group_kind
    if kind=='cj-list':return cj_request(url,cursor,settings),None
    if kind in {'doosan-list','doosan-detail','cj-detail'}:
        if group_kind(url)!=kind:raise EngineError('group public route mismatch')
        return url,None
    from .domestic import KINDS
    if kind in KINDS or kind in {'jobflex-detail','gabia-list','gabia-detail'}:return url,None
    query=dict(parse_qsl(p.query,keep_blank_values=True));secret=None
    if kind=='greenhouse':
        if p.hostname!='boards-api.greenhouse.io' or not re.fullmatch(r'/v1/boards/[^/]+/jobs',p.path.rstrip('/')):
            raise EngineError('Greenhouse source must use the documented read-only job-board endpoint')
        query['content']='true'
    elif kind=='ashby':
        if p.hostname!='api.ashbyhq.com' or not p.path.startswith('/posting-api/job-board/'):
            raise EngineError('Ashby source must use public posting-api')
    elif kind in {'work24','work24-open'}:
        endpoint='callOpenApiSvcInfo210L01.do' if kind=='work24' else 'callOpenApiSvcInfo210L21.do'
        if p.hostname!='www.work24.go.kr' or p.path!='/cm/openApi/call/wk/'+endpoint:
            raise EngineError('Work24 endpoint mismatch')
        params=settings.get('filters',{})
        if not isinstance(params,dict):raise EngineError('filters must be object')
        if any(k.lower() in {'authkey','calltp','returntype','startpage','display'} for k in params):
            raise EngineError('filters cannot override protocol/credential parameters')
        page=int(cursor or '1');size=int(settings.get('page_size',100))
        if not 1<=page<=1000 or not 1<=size<=100:raise EngineError('Work24 documented pagination limit reached; partition source')
        query.update(params);query.update(callTp='L',returnType='XML',startPage=str(page),display=str(size))
        secret='WORK24_API_KEY'
    elif kind not in {'host-json','jsonld','sitemap','ninehire-list','ninehire-detail','applyin-list','applyin-detail','skcareers-list','skcareers-detail','linkareer-list','linkareer-detail','saramin-list','jobkorea-list','html-discovery','lotte-list','lotte-detail','greeting-list','greeting-detail'}:
        raise EngineError('unsupported adapter; keep source in host work queue')
    return public_url(urlunsplit((p.scheme,p.netloc,p.path,urlencode(query),''))),secret


def parse_page(source: dict, payload: bytes, cursor: str | None=None) -> Page:
    kind=source['kind'];settings=json.loads(source['settings_json']);employer=settings.get('employer')
    if kind=='ninehire-list' or settings.get('inventory_contract')=='ninehire-rendered':
        from .ninehire import parse_rendered_inventory
        return parse_rendered_inventory(payload,source['url'],settings)
    from .groups import parse_cj_page,parse_cj_detail,parse_doosan_page,parse_doosan_detail
    if kind=='cj-list':return parse_cj_page(payload,cursor)
    if kind=='doosan-list':return parse_doosan_page(payload)
    if kind=='doosan-detail':return Page([parse_doosan_detail(payload,source['url'],settings)],True,expected_total=1,scope_note='One public Doosan detail, not a group inventory')
    if kind=='cj-detail':return Page([parse_cj_detail(payload,source['url'],settings)],True,expected_total=1,scope_note='One public CJ detail, not a group inventory')
    from .domestic import KINDS,parse_page as domestic_page
    if kind in KINDS:return domestic_page(source,payload,cursor)
    if kind in {'gabia-list','gabia-detail'}:
        from .legacy_sources import parse_page as legacy_page,parse_gabia_detail
        return legacy_page(source,payload,cursor) if kind=='gabia-list' else Page([parse_gabia_detail(payload,source['url'],settings)],True,expected_total=1,scope_note='One actual Gabia detail, inventory separate')
    if kind=='jobflex-detail':
        from .domestic import parse_jobflex_detail
        return Page([parse_jobflex_detail(payload,source['url'],settings)],True,expected_total=1,scope_note='One public Jobflex detail; employer inventory is separate')
    if kind in {'ninehire-detail','applyin-list','applyin-detail','skcareers-list','skcareers-detail','linkareer-list','linkareer-detail','saramin-list','jobkorea-list','html-discovery','lotte-list','lotte-detail','greeting-list','greeting-detail'}:
        from .korean import parse_korean_page
        return parse_korean_page(source,payload,cursor)
    if kind=='greenhouse':
        data=_json(payload)
        if not isinstance(data,dict) or not isinstance(data.get('jobs'),list):raise EngineError('Greenhouse inventory shape changed')
        if not employer:raise EngineError('verified employer association required')
        jobs=[]
        for r in data['jobs']:
            jobs.append(Job(external_id=str(r['id']),title=r['title'],employer=employer,
                job_url=r['absolute_url'],description=plain(r.get('content','')),
                location=(r.get('location') or {}).get('name',''),
                detail_verified=bool(r.get('content')),raw=r))
        total=(data.get('meta') or {}).get('total')
        return Page(jobs,True,expected_total=int(total) if total is not None else len(jobs),scope_note='One public Greenhouse board; not all company hiring channels')
    if kind=='ashby':
        data=_json(payload)
        if not isinstance(data,dict) or not isinstance(data.get('jobs'),list):raise EngineError('Ashby inventory shape changed')
        if not employer:raise EngineError('verified employer association required')
        jobs=[]
        for r in data['jobs']:
            if r.get('isListed') is False:continue # direct-link-only postings are not public directory entries
            description=r.get('descriptionPlain') or plain(r.get('descriptionHtml',''))
            jobs.append(Job(external_id=r['jobUrl'],title=r['title'],employer=employer,
                job_url=r['jobUrl'],apply_url=r.get('applyUrl'),description=description,
                location=r.get('location',''),published_at=r.get('publishedAt'),
                detail_verified=bool(description),raw=r))
        return Page(jobs,True,expected_total=len(jobs),scope_note='Listed public postings on this Ashby board only')
    if kind in {'work24','work24-open'}:
        root=safe_xml(payload)
        expected_root='wantedRoot' if kind=='work24' else 'dhsOpenEmpInfoList'
        if root.tag!=expected_root:raise EngineError('Work24 error/shape mismatch, not an empty inventory')
        try:
            total=int(root.findtext('total'));page=int(root.findtext('startPage'));size=int(root.findtext('display'))
        except (ValueError,TypeError) as e:raise EngineError('Work24 missing pagination metadata') from e
        if page!=int(cursor or '1') or size<=0:raise EngineError('server repeated/wrong page')
        jobs=[]
        for r in root.findall('wanted' if kind=='work24' else 'dhsOpenEmpInfo'):
            raw={x.tag:(x.text or '') for x in r}
            if kind=='work24':
                jobs.append(Job(external_id=raw['wantedAuthNo'],title=raw['title'],employer=raw['company'],
                    job_url=raw['wantedInfoUrl'],location=raw.get('region',''),deadline=_deadline(raw.get('closeDt')),
                    published_at=raw.get('regDt'),raw=raw,detail_verified=False))
            else:
                jobs.append(Job(external_id='campaign:'+raw['empSeqno'],title=raw['empWantedTitle'],employer=raw['empBusiNm'],
                    job_url=raw['empWantedHomepgDetail'],deadline=_deadline(raw.get('empWantedEndt')),
                    published_at=raw.get('empWantedStdt'),raw=raw,detail_verified=False,requires_role_split=True))
        if not jobs and (page-1)*size<total:raise EngineError('premature empty API page')
        terminal=page*size>=total
        capped=page>=1000 and not terminal
        return Page(jobs,terminal or capped,None if terminal or capped else str(page+1),
            expected_total=total,inventory_complete=not capped,
            scope_note='API-filtered inventory; campaign entries require role-by-role expansion; page cap needs partition' if capped else 'API-filtered inventory, details/role eligibility not verified')
    if kind=='host-json':
        data=_json(payload)
        if not isinstance(data,dict) or not isinstance(data.get('jobs'),list) or not isinstance(data.get('terminal'),bool):
            raise EngineError('host inventory needs jobs and explicit terminal flag')
        jobs=[]
        for r in data['jobs']:
            fields={k:r[k] for k in Job.__dataclass_fields__ if k in r}
            jobs.append(Job(**fields))
        return Page(jobs,data['terminal'],data.get('next_cursor'),data.get('expected_total'),
                    data.get('inventory_complete',False),data.get('scope_note','host-declared scope'),data.get('discovered_urls',[]))
    if kind=='jsonld':return parse_jsonld(payload,source['url'])
    if kind=='sitemap':
        root=safe_xml(payload)
        urls=[public_url(n.text.strip()) for n in root.iter() if n.tag.split('}')[-1]=='loc' and n.text]
        return Page([],True,inventory_complete=False,scope_note='Sitemap discovery only; URL contents uninspected',discovered_urls=urls)
    raise EngineError('unsupported adapter')


class _LD(HTMLParser):
    def __init__(self):super().__init__();self.active=False;self.buf=[];self.blocks=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('type','').lower()=='application/ld+json':self.active=True;self.buf=[]
    def handle_data(self,data):
        if self.active:self.buf.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.active:self.blocks.append(''.join(self.buf));self.active=False


def parse_jsonld(payload: bytes, source_url: str) -> Page:
    try:text=payload.decode('utf-8-sig')
    except UnicodeDecodeError as e:raise EngineError('HTML encoding needs host inspection') from e
    parser=_LD();parser.feed(text);jobs=[]
    def nodes(obj):
        if isinstance(obj,list):
            for item in obj:yield from nodes(item)
        elif isinstance(obj,dict):
            yield obj
            if '@graph' in obj:yield from nodes(obj['@graph'])
    for block in parser.blocks:
        try:obj=json.loads(block)
        except ValueError:continue
        for r in nodes(obj):
            types=r.get('@type',[]);types=[types] if isinstance(types,str) else types
            if 'JobPosting' not in types:continue
            org=r.get('hiringOrganization') or {};url=r.get('url') or source_url
            ident=r.get('identifier') or {}
            external=str(ident.get('value')) if isinstance(ident,dict) and ident.get('value') else stable_id(url,r.get('title',''))
            jobs.append(Job(external_id=external,title=r['title'],employer=org['name'],job_url=url,
                description=plain(r.get('description','')),deadline=_deadline(r.get('validThrough')),
                published_at=r.get('datePosted'),status='unknown',detail_verified=bool(r.get('description')),raw=r))
    # Structured data alone cannot prove live application state or inventory exhaustion.
    return Page(jobs,True,inventory_complete=False,scope_note='JSON-LD candidates; live state and full inventory require confirmation')
