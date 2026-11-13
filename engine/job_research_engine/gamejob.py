"""Observed public GameJob detail and its two same-posting HTML frames.

These are read contracts, not application or login routes. A category result is
discovery evidence only; a supplied detail URL is never natural-discovery proof.
"""
from dataclasses import replace
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from .htmltools import html, links, media_references
from .model import EngineError, Job, Page, public_url

HOSTS={'gamejob.co.kr','www.gamejob.co.kr'}
FRAMES={'/Recruit/GI_Read_Comt_Ifrm':'duties',
        '/Recruit/GI_Read_GI_Comment_Ifrm':'requirements'}


def posting_id(url):
    p=urlsplit(public_url(url));query=parse_qs(p.query,keep_blank_values=True)
    if p.hostname not in HOSTS or p.path!='/Recruit/GI_Read/View':return None
    ids=query.get('GI_No',[])
    if len(ids)!=1 or not re.fullmatch(r'[1-9][0-9]*',ids[0]):return None
    if set(query)-{'GI_No'}:return None
    return ids[0]


def is_list_url(url):
    p=urlsplit(public_url(url))
    return p.hostname in HOSTS and p.path=='/Recruit/joblist'


def discovery_page(payload,url):
    if not is_list_url(url):raise EngineError('Observed public GameJob category URL required')
    targets=list(dict.fromkeys(target for target,_,_ in links(html(payload),url) if posting_id(target)))
    # The public header contains many other categories. Enqueueing those as job
    # details can starve all actual postings and silently move the filter scope.
    # Pagination still needs a separately observed contract: one page is partial.
    return Page([],True,inventory_complete=False,discovered_urls=targets,
        scope_note='Exact visible GameJob detail links only; category filters/pagination are not exhausted')


def frame_kind(url,identity):
    p=urlsplit(public_url(url));query=parse_qs(p.query,keep_blank_values=True)
    if p.hostname not in HOSTS or p.path not in FRAMES or query.get('gno')!=[identity] or set(query)-{'gno','v1'}:
        raise EngineError('GameJob frame must be the observed public description for this exact posting')
    if 'v1' in query and query['v1']!=['']:raise EngineError('Unexpected GameJob description-frame selector')
    return FRAMES[p.path]


def parse_detail(payload,url):
    identity=posting_id(url)
    if not identity:raise EngineError('Exact public GameJob detail URL required')
    root=html(payload)
    header=next((n for n in root.walk() if n.has_class('view__header-title')),None)
    info=next((n for n in root.walk() if n.has_class('content__recruit-data')),None)
    title=next((n.text() for n in header.walk('h1') if n.text()),'') if header else ''
    employer=next((n.text() for n in header.walk() if n.has_class('corp-name')),'') if header else ''
    if not title or not employer or not info:raise EngineError('GameJob detail metadata missing; no empty/closed assumption')
    fields={}
    for row in info.walk('dl'):
        label=next((n.text() for n in row.walk('dt')),'')
        value=next((n.text() for n in row.walk('dd')),'')
        if label:fields[label]=value
    frames=[]
    for node in root.walk('iframe'):
        src=node.attrs.get('src')
        if not src:continue
        target=urljoin(url,src)
        if urlsplit(target).path not in FRAMES:continue
        frames.append({'kind':frame_kind(target,identity),'url':public_url(target)})
    if len(frames)!=2 or {f['kind'] for f in frames}!={'duties','requirements'}:
        raise EngineError('Both observed GameJob duties and requirements frames are required')
    status_text=info.text()
    closed=any(value in status_text for value in ('채용이 마감','모집이 마감','접수가 마감','접수마감'))
    apply=any('disabled' not in n.attrs and (n.attrs.get('value')=='지원하기' or n.text()=='지원하기')
              for n in info.walk() if n.tag in {'input','button','a'})
    end={'kind':'rolling','source_text':fields.get('마감일')} if re.search(r'채용\s*시\s*마감|상시',fields.get('마감일','')) else {'kind':'unknown'}
    location=''
    for node in root.walk():
        if node.has_class('job-sub-section') and any(n.text()=='근무지역' for n in node.walk() if n.has_class('job-sub-section__title')):
            location=next((n.text() for n in node.walk() if n.has_class('job-sub-section__body')),'');break
    job=Job(identity,title,employer,url,description='',location=location,
        status='closed' if closed else 'open' if apply else 'unknown',deadline=end,detail_verified=False,
        source_context={'provider':'gamejob','source_fields':fields,'observed_description_frames':frames},
        raw={'pending_reason':'Read both exact observed duties and requirements frames; login/application actions are not followed'})
    job.validate();return job


def description_frame(payload,url,identity):
    kind=frame_kind(url,identity);root=html(payload)
    body=next(root.walk('body'),root)
    text=body.text()
    if not text or any(x in text for x in ('Access Denied','Forbidden','접근 권한이 없습니다')):
        raise EngineError('GameJob description unavailable; not a closed posting')
    remote,inline,frames=media_references(body,url)
    return {'kind':kind,'text':text,'media_urls':remote,'inline_media':inline,'iframe_urls':frames}


def with_descriptions(job,parts,observation_ids):
    if len(parts)!=2 or {p['kind'] for p in parts}!={'duties','requirements'}:
        raise EngineError('Both same-posting GameJob description reads are required')
    media=any(p['media_urls'] or p['inline_media'] or p['iframe_urls'] for p in parts)
    # Pictures can contain qualifications. Surrounding text alone cannot clear
    # their review; the host can make that distinction after actual inspection.
    return replace(job,description='\n\n'.join(p['kind']+'\n'+p['text'] for p in parts),
        detail_verified=not media,
        source_context={**job.source_context,'body_observation_ids':observation_ids},
        raw={**job.raw,'description_parts':parts,'pending_reason':'Body media needs host inspection' if media else ''})
