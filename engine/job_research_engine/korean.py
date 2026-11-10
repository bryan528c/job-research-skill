"""Inert parsers for observed Korean ATS/group pages and public platform HTML.

No authenticated APIs, application submission, or title-based suitability decisions.
"""
from dataclasses import replace
from datetime import datetime,timezone,timedelta
import json
import re
from urllib.parse import urljoin,urlsplit,parse_qsl,urlencode,urlunsplit
from .htmltools import html,next_data,links
from .model import EngineError,Job,Page,public_url,stable_id

def text_html(value):
    return html((value or '').encode()).text()

def deadline(raw):
    if not raw:return {'kind':'unknown'}
    if isinstance(raw,(int,float)) and not isinstance(raw,bool):
        # Public platform fields are Unix milliseconds (13 digits), or Unix seconds (10 digits).
        if 1_000_000_000_000<=raw<=4_102_444_800_000:
            return {'kind':'datetime','at':datetime.fromtimestamp(raw/1000,timezone.utc).astimezone(timezone(timedelta(hours=9))).isoformat()}
        if 1_000_000_000<=raw<=4_102_444_800:
            return {'kind':'datetime','at':datetime.fromtimestamp(raw,timezone.utc).astimezone(timezone(timedelta(hours=9))).isoformat()}
        return {'kind':'unknown','source_text':str(raw)}
    if not isinstance(raw,str):return {'kind':'unknown','source_text':str(raw)}
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw):return {'kind':'date','date':raw,'timezone':'Asia/Seoul'}
    try:
        at=datetime.fromisoformat(raw.replace('Z','+00:00'))
        if at.tzinfo is not None:return {'kind':'datetime','at':at.astimezone(timezone(timedelta(hours=9))).isoformat()}
    except ValueError:pass
    return {'kind':'unknown','source_text':raw}

def parse_ninehire(payload,url):
    root=html(payload);props=next_data(root)
    r=props.get('recruitment');post=props.get('jobPosting')
    if not isinstance(r,dict) or not isinstance(post,dict):raise EngineError('Ninehire job detail missing; listing requires rendered host/sitemap discovery')
    content=text_html(post.get('content'))
    if not content:raise EngineError('Ninehire description missing or image-only; host inspection required')
    reception=r.get('reception') or {}
    status='open' if r.get('jobPostingIsActive') is True and reception.get('canSubmit') is True and r.get('status')=='in_progress' else 'closed' if r.get('closedAt') or r.get('jobPostingIsActive') is False or r.get('status') in {'closed','finished'} else 'unknown'
    apply=[target for target,label,_ in links(root,url) if '지원하기' in label and target!=url]
    # The same URL can contain multiple departments. Preserve a container until the host splits it.
    campaign=any(mark in content for mark in ('[세부 직무]','모집부문별','모집 부문별'))
    job=Job(str(r['addressKey']),r.get('externalTitle') or r['title'],r['companyName'],url,
            apply_url=apply[0] if apply else None,description=content,location=' / '.join(x.get('addressName','') for x in r.get('jobLocations',[])),
            status=status,deadline=deadline(reception.get('endAt') or r.get('endAt')),published_at=r.get('createdAt'),
            detail_verified=True,requires_role_split=campaign,raw={'provider':'ninehire','application_login_required':r.get('applicantLoginEnabled'),
                'recruitment_id':r.get('recruitmentId'),'affiliation':(r.get('affiliation') or {}).get('title'),
                'apply_action':'onsite button' if not apply else 'observed link'})
    return job

def parse_applyin(payload,url,*,detail=False):
    try:data=json.loads(payload)
    except ValueError as e:raise EngineError('Applyin public response changed; no login/API bypass') from e
    raw=data.get('data');rows=[raw] if detail and isinstance(raw,dict) else raw
    if not isinstance(rows,list):raise EngineError('Applyin inventory/detail shape changed')
    employer=(data.get('organization') or {}).get('name');jobs=[]
    for r in rows:
        linkmap=r.get('links') or {};joburl=linkmap.get('jobs.show') or url
        org=employer or r.get('organizationName')
        if not org:org=(data.get('meta') or {}).get('employer')
        description=text_html(r.get('content') or '')
        jobs.append(Job(str(r['id']),r['title'],org or 'employer association required',joburl,
            apply_url=linkmap.get('jobs.start-application'),description=description,
            status='open' if r.get('statusCode')=='Open' and not r.get('isAfterApplicationEndDate') else 'closed' if r.get('statusCode') in {'Closed','Close'} or r.get('isAfterApplicationEndDate') else 'unknown',
            deadline=deadline(r.get('end')),published_at=r.get('start'),detail_verified=bool(description),
            requires_role_split=True,raw={'provider':'applyin','positions':r.get('positions'),'attachments':r.get('attachments'),
              'media_urls':[public_url(urljoin(url,n.attrs['src'])) for n in html((r.get('content') or '').encode()).walk('img') if n.attrs.get('src')]}))
    return jobs,data

def parse_sk(payload,url):
    root=html(payload)
    titles=[n.text() for n in root.walk('h2') if n.has_class('title')]
    # Sidebar classes have been verified against the public detail HTML.
    sidebar=next((n for n in root.walk() if n.has_class('floating-box')),None)
    title=titles[-1] if titles else ''
    if not title:
        titles=[n.text() for n in root.walk('h2') if not n.has_class('detail-content-title')];title=titles[-1] if titles else ''
    blocks=[n.text() for n in root.walk() if n.has_class('detail-content-item')]
    content='\n'.join(blocks)
    main=next((n for n in root.walk('main')),root);text=main.text()
    identity=urlsplit(url).path.rsplit('/',1)[-1]
    media=[]
    for node in main.walk('img'):
        target=urljoin(url,node.attrs.get('src',''));parsed=urlsplit(target)
        # Accept only this notice's observed poster, never shared site imagery.
        if (parsed.hostname=='d3g1pwhebgacef.cloudfront.net'
                and parsed.path.startswith('/JobNotice/'+identity+'/Info/')):
            target=public_url(target)
            if target not in media:media.append(target)
    if not title or not (content.strip() or media):raise EngineError('SK job detail contract missing')
    fields={}
    if sidebar:
        for item in sidebar.walk():
            if not item.has_class('box-detail-item'):continue
            label=next((n.text() for n in item.walk() if n.has_class('label')),'')
            value=next((n.text() for n in item.walk() if n.has_class('value')),'')
            fields[label]=value
    employer=fields.get('회사') or fields.get('Company') or ''
    if not employer:raise EngineError('SK legal employer display missing; host required')
    period=fields.get('지원 기간') or fields.get('Application Period') or ''
    dates=re.findall(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일',period)
    end={'kind':'unknown'}
    if len(dates)>=2:
        end={'kind':'date','date':'%04d-%02d-%02d'%tuple(map(int,dates[1])),'timezone':'Asia/Seoul'}
    elif '~' in period:
        # The site serves English dates to some clients, independently of its Korean labels.
        raw=period.split('~')[-1].split('(')[0].strip()
        try:end={'kind':'date','date':datetime.strptime(raw,'%B %d, %Y').date().isoformat(),'timezone':'Asia/Seoul'}
        except ValueError:pass
    clock=fields.get('마감 시간') or fields.get('Closing Time')
    if end['kind']=='date' and clock and re.fullmatch(r'\d{2}:\d{2}',clock):end={'kind':'datetime','at':end['date']+'T'+clock+':00+09:00'}
    candidates=[n for n in root.walk() if n.tag in {'button','a'} and ('지원하기' in n.text() or 'Apply'==n.text())]
    open_button=any('disabled' not in n.attrs for n in candidates)
    closed=any(x in text for x in ('접수가 마감','모집이 마감','채용이 마감'))
    # Do not fabricate the login URL from JavaScript. Host may record its actually observed destination.
    apply_url=None
    for n in candidates:
        # Parse only an inert, literal navigation target. Never evaluate onclick code.
        match=re.fullmatch(r'''location\.href\s*=\s*["']([^"']+)["'];?''',n.attrs.get('onclick','').strip())
        if match:apply_url=public_url(urljoin(url,match.group(1)))
    return Job(identity,title,employer,url,description=content,apply_url=apply_url,
               location=fields.get('근무지') or fields.get('근무지역') or fields.get('Location') or '',
               deadline=end,status='closed' if closed else 'open' if open_button else 'unknown',detail_verified=bool(content.strip()),
               requires_role_split=not bool(content.strip()),source_context=fields,
               raw={'provider':'skcareers','apply_action':'onsite login-required button','media_urls':media})

def detect_kind(url):
    from .groups import detect_kind as group_kind
    if (kind:=group_kind(url)):return kind
    from .domestic import detect_kind as domestic_kind
    if (kind:=domestic_kind(url)):return kind
    from .legacy_sources import detect_kind as legacy_kind
    if (kind:=legacy_kind(url)):return kind
    p=urlsplit(url)
    if (p.hostname or '').endswith('.recruiter.co.kr') and re.fullmatch(r'/career/jobs/[1-9][0-9]*/?',p.path):return 'jobflex-detail'
    if p.hostname=='www.skcareers.com' and p.path.startswith('/Recruit/Detail/'):return 'skcareers-detail'
    if '/job_posting/' in p.path:return 'ninehire-detail'
    if (p.hostname or '').endswith('.applyin.co.kr'):
        return 'applyin-detail' if re.fullmatch(r'/jobs/\d+',p.path) else 'applyin-list'
    if p.hostname=='linkareer.com':return 'linkareer-detail' if p.path.startswith('/activity/') else 'linkareer-list'
    if (p.hostname or '').endswith('saramin.co.kr') and '/jobs/relay/view' in p.path:return 'saramin-detail'
    if (p.hostname or '').endswith('jobkorea.co.kr') and '/recruit/gi_read/' in p.path.lower():return 'jobkorea-detail'
    if p.hostname=='recruit.lotte.co.kr':return 'lotte-detail' if '/announcement/detail/' in p.path else 'lotte-list'
    if (p.hostname or '').endswith('.career.greetinghr.com') or p.hostname=='recruit-hanwhaocean.com':return 'greeting-detail' if re.search(r'/(?:ko/|en/)?o/\d+',p.path) else 'greeting-list'
    return 'html-discovery'

def parse_detail(kind,payload,url,settings):
    if kind=='cj-detail':
        from .groups import parse_cj_detail
        return parse_cj_detail(payload,url,settings)
    if kind=='doosan-detail':
        from .groups import parse_doosan_detail
        return parse_doosan_detail(payload,url,settings)
    from .domestic import KINDS,parse_detail as domestic_detail,parse_jobflex_detail
    if kind=='jobflex-detail':return parse_jobflex_detail(payload,url,settings)
    if kind in KINDS:return domestic_detail(kind,payload,url,settings)
    from .legacy_sources import parse_gabia_detail,parse_ninehire_detail
    if kind=='gabia-detail':return parse_gabia_detail(payload,url,settings)
    if kind=='greeting-detail':
        root=html(payload);data=next_data(root);result=None
        for query in data.get('dehydratedState',{}).get('queries',[]):
            if 'getOpeningById' in query.get('queryKey',[]):result=query['state']['data']
        if not result or not result.get('success'):raise EngineError('Greeting detail data missing; not a closed-round assumption')
        data=result['data'];r=data['openingsInfo'];markup=r.get('detail') or '';description=text_html(markup)
        positions=(data.get('jobPositionSetting') or {}).get('jobPositions') or []
        # Greeting's location is a user-defined place label, often the company
        # name. The separate place field holds the actual address.
        locations=[];position_metadata=[]
        for p in positions:
            place=p.get('workspacePlace') or {};career=p.get('jobPositionCareer') or {};employment=p.get('jobPositionEmployment') or {}
            address=place.get('place') if isinstance(place.get('place'),str) else ''
            label=place.get('location') if isinstance(place.get('location'),str) else ''
            value=address or label
            if value and value not in locations:locations.append(value)
            position_metadata.append({'position_id':p.get('id'),'place_label':label,'address':address,
                'career':{k:career[k] for k in ('careerType','careerFrom','careerTo') if k in career},
                'employment_type':employment.get('employmentType')})
        candidates=[(u,label.strip()) for u,label,_ in links(root,url) if label.strip() in {'지원하기','입사지원','Apply','Apply now','Apply Now'}
                    and not re.fullmatch(r'/(?:ko/|en/)?(?:apply|recruit|home)/?',urlsplit(u).path)]
        candidates.sort(key=lambda x:('지원' in x[1],'/o/'+str(r['openingId'])+'/' in x[0]),reverse=True)
        apply=candidates[0][0] if candidates else None
        employer=settings.get('employer') or (r.get('workspaceDivision') or {}).get('division') or data['groupInfo']['name']
        return Job(str(r['openingId']),r['title'],employer,url,apply_url=apply,
            description=description,location=' / '.join(locations),deadline=deadline(r.get('dueDate')),status='open' if r.get('status')=='OPEN' else 'closed' if r.get('status')=='CLOSED' else 'unknown',
            detail_verified=bool(description),requires_role_split=len(positions)>1,
            source_context={'position_metadata':position_metadata} if position_metadata else {},
            raw={'provider':'greeting','employer_identity':'group display; individual legal employer needs confirmation',
              'media_urls':[public_url(urljoin(url,n.attrs['src'])) for n in html(markup.encode()).walk('img') if n.attrs.get('src')]})
    if kind=='lotte-detail':
        root=html(payload);head=next((n for n in root.walk() if n.has_class('board-head')),None)
        body=next((n for n in root.walk() if n.has_class('board-content')),None)
        if not head or not body:raise EngineError('Lotte detail contract missing')
        title=next((n.text() for n in head.walk() if n.has_class('title')),'')
        employer=next((n.text() for n in head.walk() if n.has_class('board-type')),'')
        dates=next((n.text() for n in head.walk() if n.has_class('date-detail')),'')
        end=re.findall(r'\d{4}\.\d{2}\.\d{2}',dates)
        closes=deadline(end[-1].replace('.','-')) if end else {'kind':'unknown'}
        period=re.search(r'접수기간\s*:?\s*(.*?)접수방법',body.text())
        if period and closes['kind']=='date':
            matches=re.findall(r'(\d{4})[년.\-/]\s*(\d{1,2})[월.\-/]\s*(\d{1,2})(?:일)?\s*(?:\([^)]*\))?\s*(\d{1,2}):(\d{2})',period.group(1))
            clocks={f'{int(h):02d}:{int(m):02d}' for y,mo,d,h,m in matches if f'{int(y):04d}-{int(mo):02d}-{int(d):02d}'==closes['date']}
            if len(clocks)==1:closes={'kind':'datetime','at':closes['date']+'T'+next(iter(clocks))+':00+09:00'}
        identity=urlsplit(url).path.rstrip('/').rsplit('/',1)[-1]
        apply=None
        if any(re.fullmatch(r"goNext\('"+re.escape(identity)+r"'\)",n.attrs.get('onclick','')) for n in root.walk('a')) and '/apply/terms/' in root.raw_text():
            apply=public_url(urljoin(url,'/apply/terms/'+identity))
        return Job(identity,title,employer,url,apply_url=apply,description=body.text(),
            deadline=closes,
            status='open' if '접수중' in head.text() else 'closed' if '접수마감' in head.text() else 'unknown',
            detail_verified=bool(body.text()),requires_role_split=True,
            raw={'provider':'lotte','media_urls':[public_url(urljoin(url,n.attrs['src'])) for n in body.walk('img') if n.attrs.get('src')]})
    if kind=='ninehire-detail':return parse_ninehire_detail(payload,url)
    if kind=='skcareers-detail':return parse_sk(payload,url)
    if kind=='applyin-detail':
        jobs,_=parse_applyin(payload,url,detail=True)
        if len(jobs)!=1:raise EngineError('Applyin detail identity mismatch')
        return replace(jobs[0],employer=settings.get('employer') or jobs[0].employer)
    if kind=='linkareer-detail':
        root=html(payload);data=next_data(root)
        state=data.get('__APOLLO_STATE__') or {};identity=urlsplit(url).path.rstrip('/').rsplit('/',1)[-1]
        activity=state.get('Activity:'+identity)
        if isinstance(activity,dict):
            detail=activity.get('detailText') or {}
            if isinstance(detail,dict) and detail.get('__ref'):detail=state.get(detail['__ref'],{})
            markup=detail.get('text','') if isinstance(detail,dict) else str(detail)
            desc=text_html(markup)
            apply=activity.get('applyDetail')
            if apply:
                try:apply=public_url(apply)
                except EngineError:apply=None
            end=deadline(activity.get('recruitCloseAt'))
            if activity.get('dateRepresentation')=='DAY' and end['kind']=='datetime':end={'kind':'date','date':end['at'][:10],'timezone':'Asia/Seoul'}
            return Job(identity,activity['title'],activity['organizationName'],url,apply_url=apply,description=desc,
                       deadline=end,status='unknown',detail_verified=bool(desc),requires_role_split=True,
                       raw={'provider':'linkareer','official_status_recheck_required':True,
                            'media_urls':[public_url(urljoin(url,n.attrs['src'])) for n in html(markup.encode()).walk('img') if n.attrs.get('src')]})
        # Use only data already shipped in the public HTML, never the platform's private API.
        candidates=[]
        def walk(o):
            if isinstance(o,dict):
                if o.get('title') and (o.get('content') or o.get('description')):candidates.append(o)
                for value in o.values():walk(value)
            elif isinstance(o,list):
                for value in o:walk(value)
        walk(data)
        if not candidates:raise EngineError('Linkareer detail needs host/image inspection')
        r=max(candidates,key=lambda x:len(str(x.get('content') or x.get('description'))))
        desc=text_html(r.get('content') or r.get('description'))
        employer=r.get('organizationName') or r.get('companyName') or settings.get('employer')
        if not employer:raise EngineError('Linkareer employer not established')
        return Job(urlsplit(url).path.rsplit('/',1)[-1],r['title'],employer,url,description=desc,
                   deadline=deadline(r.get('recruitCloseAt')),status='unknown',detail_verified=bool(desc),requires_role_split=True)
    if kind in {'saramin-detail','jobkorea-detail'}:
        from .adapters import parse_jsonld
        page=parse_jsonld(payload,url)
        if len(page.jobs)!=1:raise EngineError('platform detail requires host DOM/image inspection')
        # Structured metadata is a discovery signal, never live application confirmation.
        return replace(page.jobs[0],status='unknown',requires_role_split=True)
    raise EngineError('unsupported detail contract; authorized host inspection required')

def parse_korean_page(source,payload,cursor=None):
    kind=source['kind'];url=source['url'];settings=json.loads(source['settings_json'])
    if kind.endswith('-detail'):
        job=parse_detail(kind,payload,url,settings)
        return Page([job],True,expected_total=1,scope_note='One actual detail; not the employer inventory')
    if kind=='greeting-list':
        root=html(payload);data=next_data(root);rows=None
        for query in data.get('dehydratedState',{}).get('queries',[]):
            if query.get('queryKey')==['openings']:rows=query['state']['data']
        if not isinstance(rows,list):raise EngineError('Greeting public openings absent; host rendering required')
        observed={urlsplit(target).path.rstrip('/').rsplit('/',1)[-1]:target for target,_,_ in links(root,url) if re.search(r'/o/\d+',target)}
        jobs=[]
        for r in rows:
            if r.get('deploy') is not True:continue
            identity=str(r['openingId'])
            if identity not in observed:raise EngineError('Greeting opening has no observed public detail link')
            employer=settings.get('employer') or (r.get('workspaceDivision') or {}).get('division') or (r.get('group') or {}).get('name')
            if not employer:raise EngineError('Greeting displayed employer missing')
            jobs.append(Job(identity,r['title'],employer,observed[identity],deadline=deadline(r.get('dueDate')),published_at=r.get('openDate'),detail_verified=False))
        return Page(jobs,True,expected_total=len(jobs),scope_note='Public server-rendered Greeting openings only; legal employer/individual details still require validation')
    if kind=='lotte-list':
        root=html(payload);match=re.search(r'전체\s*\(([\d,]+)\)',root.text())
        if not match:raise EngineError('Lotte inventory total missing')
        jobs=[]
        for card in root.walk():
            if not card.has_class('job-card-group'):continue
            targets=[(u,label) for u,label,_ in links(card,url) if '/announcement/detail/' in u]
            if len(targets)!=1:continue
            target,title=targets[0]
            employer=next((n.text() for n in card.walk() if n.has_class('cmp-name')),'')
            raw=next((n.text() for n in card.walk() if n.has_class('date')),'');dates=re.findall(r'\d{4}\.\d{2}\.\d{2}',raw)
            jobs.append(Job(urlsplit(target).path.rsplit('/',1)[-1],title,employer,target,
               deadline=deadline(dates[-1].replace('.','-')) if dates else {'kind':'unknown'},detail_verified=False))
        return Page(jobs,True,expected_total=int(match.group(1).replace(',','')),scope_note='Lotte public current list; count mismatch is a gap, not silently truncated')
    if kind=='applyin-list':
        jobs,data=parse_applyin(payload,url)
        employer=settings.get('employer') or (data.get('organization') or {}).get('name')
        if not employer:raise EngineError('verified Applyin employer association required')
        jobs=[replace(j,employer=employer) for j in jobs]
        meta=data.get('meta') or {}
        paginated=bool(data.get('links',{}).get('next') or meta.get('last_page',1)>1)
        return Page(jobs,True,expected_total=meta.get('total',len(jobs)),inventory_complete=not paginated,
                    scope_note='Observed public Applyin jobs inventory; campaigns require individual-role expansion')
    if kind=='skcareers-list':
        data=json.loads(payload)
        if data.get('success') is not True or not isinstance(data.get('list'),list):raise EngineError('SK public inventory search failed')
        jobs=[Job(str(r['noticeID']),r['title'],r['corpName'],'https://www.skcareers.com/Recruit/Detail/'+str(r['noticeID']),
                  location=r.get('workingArea',''),deadline=deadline(r.get('end')),detail_verified=False) for r in data['list']]
        return Page(jobs,True,expected_total=int(data['totalCount']),scope_note='SK public UI inventory response; individual details still pending')
    if kind in {'linkareer-list','saramin-list','jobkorea-list','html-discovery'}:
        root=html(payload);urls=[]
        patterns={'linkareer-list':r'/activity/\d+','saramin-list':r'/(?:jobs/relay|jobs/view|recruit/view)',
                  'jobkorea-list':r'/Recruit/GI_Read/\d+','html-discovery':r'/(?:job_posting/|jobs/\d+|Recruit/Detail/|recruit|careers)'}
        for target,_,node in links(root,url):
            if re.search(patterns[kind],target,re.I) and target not in urls:urls.append(target)
        if not urls:raise EngineError('no public job links in HTML; rendered host/search needed')
        return Page([],True,inventory_complete=False,scope_note='Public visible links only; platform pagination and role details remain unverified',discovered_urls=urls)
    raise EngineError('unsupported Korean page')
