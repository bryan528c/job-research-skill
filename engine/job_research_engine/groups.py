"""Observed anonymous CJ and Doosan read contracts; no applicant actions."""
import json
import re
from urllib.parse import parse_qs,urlencode,urlsplit,urljoin
from .htmltools import html,Node
from .model import EngineError,Job,Page,public_url,stable_id

CJ='https://recruit.cj.net/recruit/ko/recruit/recruit/'
DOOSAN='https://career.doosan.com/dsp/sa/RecList.jsp'
KINDS={'cj-list','cj-detail','doosan-list','doosan-detail'}

def detect_kind(url):
    p=urlsplit(public_url(url));q=parse_qs(p.query)
    if p.scheme=='https' and p.netloc=='recruit.cj.net':
        if p.path==urlsplit(CJ+'list.fo').path:return 'cj-list'
        if p.path in {urlsplit(CJ+'detail.fo').path,urlsplit(CJ+'bestDetail.fo').path}:return 'cj-detail'
    if p.scheme=='https' and p.netloc=='career.doosan.com' and p.path=='/dsp/sa/RecList.jsp':
        if q.get('mode')==['goDetail'] and re.fullmatch(r'[1-9][0-9]{0,14}',(q.get('REC_ID') or [''])[0]):return 'doosan-detail'
        if not q:return 'doosan-list'
    return None

def cj_request(url,cursor=None,settings=None):
    if detect_kind(url)!='cj-list':raise EngineError('observed CJ public list URL required')
    page=str(cursor or '1')
    if not re.fullmatch(r'[1-9][0-9]{0,4}',page):raise EngineError('positive CJ page required')
    fields={'pageVal':page,'pageIndex':'10','orderDesc':'1','sch_title':'','arrGubun':'',
            'arrRecBu':'','arrRecJob':'','arrRecArea':'','schArea':'N'}
    filters=(settings or {}).get('filters',{})
    if set(filters)-{'sch_title','arrGubun','arrRecBu','arrRecJob','arrRecArea'} or any(not isinstance(v,str) or len(v)>200 for v in filters.values()):
        raise EngineError('only bounded observed public job filters allowed')
    fields.update(filters)
    if any(filters.values()):fields['schArea']='Y'
    return CJ+'searchNewGonggoList.fo?'+urlencode(fields)

def _date(raw,hour=None,minute=None):
    value=str(raw or '').strip().replace('.','-')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):return {'kind':'unknown'}
    h,m=str(hour or '').strip(),str(minute or '').strip()
    if re.fullmatch(r'\d{1,2}',h) and re.fullmatch(r'\d{1,2}',m) and int(h)<24 and int(m)<60:
        return {'kind':'datetime','at':value+f'T{int(h):02d}:{int(m):02d}:00+09:00'}
    return {'kind':'date','date':value,'timezone':'Asia/Seoul'}

def _one(node,tag,cls=None):
    return next((n for n in node.walk(tag) if cls is None or n.has_class(cls)),None)

def parse_cj_page(payload,cursor=None):
    try:data=json.loads(payload)
    except ValueError as exc:raise EngineError('CJ public job response is not JSON') from exc
    rows=data.get('ds_newRecruitList')
    if str(data.get('ErrorCode'))!='0' or not isinstance(rows,list) or not rows:
        raise EngineError('CJ empty/error response has no independently declared zero total')
    totals={r.get('tot_cnt') for r in rows}
    if len(totals)!=1:raise EngineError('CJ inventory total changed within a page')
    total=next(iter(totals))
    if isinstance(total,bool) or not isinstance(total,int) or total<1:raise EngineError('CJ declared total missing')
    jobs=[]
    for r in rows:
        identity=str(r.get('zz_jo_num') or '')
        if not re.fullmatch(r'[A-Z0-9]{1,32}',identity):raise EngineError('CJ posting identity missing')
        if r.get('gubun') not in {'1','2'}:raise EngineError('CJ unknown public detail route')
        route='detail.fo?' if r['gubun']=='1' else 'bestDetail.fo?direct=N&'
        end={'kind':'rolling'} if r.get('zz_till_hire')=='Y' else _date(r.get('zz_end_dt_str'),r.get('zz_end_hh'),r.get('zz_end_mi'))
        jobs.append(Job(identity,r['zz_title'],r['compnm'],CJ+route+'zz_jo_num='+identity,
            location=r.get('location_cd_nm') or '',deadline=end,detail_verified=False,
            status='closed' if r.get('zz_close_yn')=='Y' else 'open' if r.get('zz_close_yn')=='N' and r.get('zz_open_yn')=='Y' else 'unknown',
            source_context={k:r.get(k) for k in ('gubun','zz_target_1','zz_mthr_yn','zz_str_dt_str')},raw={'provider':'cj'}))
    if len({j.external_id for j in jobs})!=len(jobs):raise EngineError('CJ repeated IDs in page')
    page=int(cursor or '1');more=page*10<total
    return Page(jobs,not more,str(page+1) if more else None,expected_total=total,
        scope_note='CJ anonymous unfiltered public GET used by official search; parent and downstream ATS details are separate')

def parse_doosan_page(payload):
    root=html(payload);nav=_one(root,'ul','pagination')
    if nav is None:raise EngineError('Doosan inventory pagination/end control missing')
    # Current contract is one unfiltered server-rendered page. A new page link
    # must produce a material gap until its cursor contract is reviewed.
    terminal=not any(n.attrs.get('href') not in {None,'','#','javascript:void(0);'} or n.attrs.get('onclick') for n in nav.walk('a'))
    jobs=[]
    for a in root.walk('a'):
        if not a.has_class('list-tit'):continue
        match=re.fullmatch(r"goDetail\('([1-9][0-9]{0,14})',\s*'([A-Z0-9_]+)',\s*'([A-Z0-9_]+)',\s*'([A-Z0-9_]+)'\);?",a.attrs.get('onclick','').strip())
        if not match:raise EngineError('Doosan inert public detail navigation changed')
        company=_one(a,'div','company');title=_one(a,'strong');period=_one(a,'div','deadline')
        if company is None or title is None or period is None:raise EngineError('Doosan inventory fields missing')
        employer=' '.join(' '.join(c for c in company.children if isinstance(c,str)).split())
        career=_one(company,'span','badge-type');dates=re.findall(r'\d{4}-\d{2}-\d{2}',period.text())
        jobs.append(Job(match[1],title.text(),employer,DOOSAN+'?'+urlencode({'REC_ID':match[1],'mode':'goDetail'}),
            deadline=_date(dates[-1]) if dates else {'kind':'unknown'},detail_verified=False,
            source_context={'career_label':career.text() if career else '', 'recruitment_type':match[3]},raw={'provider':'doosan'}))
    if not jobs or len({j.external_id for j in jobs})!=len(jobs):raise EngineError('Doosan missing/repeated listing IDs')
    return Page(jobs,True,inventory_complete=terminal,scope_note='Unfiltered rendered Doosan list and single-page end navigation; no national completeness claim')

def parse_doosan_detail(payload,url,settings=None):
    if detect_kind(url)!='doosan-detail':raise EngineError('Doosan public detail identity required')
    root=html(payload);identity=parse_qs(urlsplit(url).query)['REC_ID'][0]
    actual=next((n.attrs.get('value') for n in root.walk('input') if n.attrs.get('name')=='REC_ID'),None)
    if actual!=identity:raise EngineError('Doosan returned a different/missing posting identity')
    title=_one(root,'h2','h2-title');area=_one(root,'div','view-list-wrap')
    if title is None or area is None:raise EngineError('Doosan detail body contract missing')
    fields={}
    for tr in root.walk('tr'):
        th=_one(tr,'th');td=_one(tr,'td')
        if th and td and th.text() in {'자격요건','전형절차','접수방법','진행상태','기타사항','채용공고'}:fields[th.text()]=td.text()
    common='\n'.join(k+': '+v for k,v in fields.items())
    roles=[]
    for row in area.walk('ul'):
        if not row.has_class('tb-con-res'):continue
        cells={}
        for dl in row.walk('dl'):
            dt=_one(dl,'dt');dd=_one(dl,'dd')
            if dt and dd:cells[dt.text()]=dd.text()
        role_title=cells.get('모집분야');duties=cells.get('수행업무/전공/자격요건') or cells.get('수행업무/전공/자격요건 등')
        if not role_title:
            if not roles or not duties or cells.get('자회사/BG') not in {'',roles[-1]['source_org']}:
                raise EngineError('Doosan individual role title missing or ambiguous continuation')
            # Blank subsequent cells continue the same displayed/rowspan role.
            # Preserve their requirements; do not invent extra openings.
            roles[-1]['source_section']+='\n이어지는 원문: '+duties
            roles[-1]['description']=roles[-1]['source_section']+'\n'+common
            continue
        quote='모집분야: '+role_title
        section='\n'.join([quote]+[k+': '+v for k,v in cells.items() if k!='모집분야'])
        roles.append({'role_key':'duty-'+stable_id(cells.get('자회사/BG',''),role_title,cells.get('지역',''))[:16],
            'title':role_title,'source_quote':quote,'source_section':section,'description':section+'\n'+common,'body_present':bool(duties),
            'employer':cells.get('자회사/BG','').split('/')[0].strip(),'location':cells.get('지역',''),'source_org':cells.get('자회사/BG','')})
    if not roles:raise EngineError('Doosan role sections missing')
    if len({r['role_key'] for r in roles})!=len(roles):raise EngineError('Doosan ambiguous duplicate individual roles')
    employer=(settings or {}).get('employer') or next((n.text() for n in area.walk('dd')),None)
    if not employer:raise EngineError('Doosan observed employer display missing')
    description='원 공고: '+title.text()+'\n'+common+'\n\n'+'\n\n'.join(r['source_section'] for r in roles)
    period=fields.get('채용공고') or fields.get('진행상태','');dates=re.findall(r'\d{4}[-.]\d{2}[-.]\d{2}',period)
    status='open' if '접수중' in fields.get('진행상태','') else 'closed' if any(x in fields.get('진행상태','') for x in ('마감','종료')) else 'unknown'
    return Job(identity,title.text(),employer,url,description=description,status=status,
        location=' / '.join(dict.fromkeys(r['location'] for r in roles if r['location'])),
        deadline=_date(dates[-1]) if dates else {'kind':'unknown'},detail_verified=all(r['body_present'] for r in roles),
        requires_role_split=len(roles)>1,raw={'provider':'doosan','role_sections':roles,'apply_action':'Observed online application button; login destination requires host observation',
          'media_urls':[public_url(n.attrs['src']) for n in area.walk('img') if n.attrs.get('src','').startswith('https://')]})

def _body_text(node):
    if node.tag in {'a','h3','svg','script','style','noscript'}:return ''
    return ' '.join(' '.join(_body_text(c) if isinstance(c,Node) else c for c in node.children).split())

def _cj_public_apply(root,identity):
    # Read the observed anonymous branch as data. Never execute page JavaScript
    # or follow the authenticated status/resume transaction.
    if not any(re.fullmatch(r"applyRecruit\('"+re.escape(identity)+r"','[YN]'\);?",n.attrs.get('onclick','').strip()) for n in root.walk('button')):
        return None
    script=root.raw_text()
    branch=re.search(r'function\s+applyRecruit\(seq,\s*agrYn\)\s*\{(.*?)\}\s*else\s*\{',script,re.S)
    if not branch:return None
    text=branch.group(1)
    if not re.search(r'var\s+w_ko_g_user_seq\s*=\s*""\s*;',text) or not re.search(r'if\s*\(w_ko_g_user_seq\s*==\s*""\)',text):return None
    target=re.search(r'window\.location\.href\s*=\s*"([^"]+)"\s*;',text)
    if not target:return None
    target=public_url(target.group(1));parsed=urlsplit(target)
    if parsed.scheme!='https' or parsed.netloc!='recruit.cj.net' or parsed.path!='/recruit/ko/member/login/login.fo':return None
    returned=parse_qs(parsed.query).get('returnUrl',[])
    if len(returned)!=1 or detect_kind(returned[0])!='cj-detail' or parse_qs(urlsplit(returned[0]).query).get('zz_jo_num')!=[identity]:return None
    return target


def parse_cj_detail(payload,url,settings=None):
    if detect_kind(url)!='cj-detail':raise EngineError('CJ observed public detail route required')
    identity=(parse_qs(urlsplit(url).query).get('zz_jo_num') or [''])[0]
    if not re.fullmatch(r'[A-Z0-9]{1,32}',identity):raise EngineError('CJ public posting ID missing')
    root=html(payload)
    area=next((n for n in root.walk('div') if n.attrs.get('id')=='contents'),None)
    if area is None:raise EngineError('CJ detail shell is not a verified empty/closed posting')
    head=next((n for n in area.walk('div') if n.has_class('tit-wrap') and n.has_class('view')),None)
    body=_one(area,'ul','detail-list')
    if head is None or body is None:raise EngineError('CJ detail/header fields changed')
    title=_one(head,'p','title');employer=_one(head,'p','company');meta=_one(head,'ul','meta-info')
    if title is None or employer is None or meta is None:raise EngineError('CJ title/employer/period missing')
    identity_seen=any(re.search(r"(?:copyUrl|bookmarkGonggo|applyRecruit)\('"+re.escape(identity)+r"'",n.attrs.get('onclick','')) for n in area.walk())
    if not identity_seen:raise EngineError('CJ returned unconfirmed posting identity')
    dates=re.findall(r'\d{4}\.\d{2}\.\d{2}',meta.text())
    end={'kind':'rolling'} if '채용시까지' in meta.text() else _date(dates[-1]) if dates else {'kind':'unknown'}
    previous=(settings or {}).get('listing_job') or {}
    prior=previous.get('deadline') or {}
    if previous.get('external_id')==identity and end['kind']=='date' and prior.get('kind')=='datetime' and prior['at'][:10]==end['date']:
        end=prior
    # A visible same-date time may refine a date-only header. Keep uncertain or
    # contradictory times separate rather than inventing 23:59.
    full=body.text();clocks=set()
    for y,mo,d,h,m in re.findall(r'(\d{4})[년.\-/]\s*(\d{1,2})[월.\-/]\s*(\d{1,2})(?:일)?\s*(?:\([^)]*\))?\s*(\d{1,2}):(\d{2})',full):
        day=f'{int(y):04d}-{int(mo):02d}-{int(d):02d}'
        if day==(end.get('date') or end.get('at','')[:10]):clocks.add(_date(day,h,m).get('at'))
    if len(clocks)==1 and None not in clocks:end={'kind':'datetime','at':next(iter(clocks))}
    badges=[n.text() for n in meta.walk('span') if n.has_class('closing') or n.has_class('box-txt')]
    closed=any(t.strip() in {'마감','접수마감','채용마감'} for t in badges)
    active=any(t.startswith('D-') or t=='상시' for t in badges)
    media=[];embedded=0
    for n in body.walk('img'):
        target=n.attrs.get('src') or ''
        if not target:continue
        if target.startswith('data:image/'):
            embedded+=1;continue # Retained in immutable HTML for host image review, never an HTTP URL.
        try:target=public_url(urljoin(url,target))
        except EngineError:continue
        if target not in media:media.append(target)
    from .htmltools import links
    external=list(dict.fromkeys(u for u,label,n in links(body,url) if urlsplit(u).hostname!='recruit.cj.net'))
    context={'header_metadata':meta.text()}
    sidebar=_one(area,'div','floating-box');fields={}
    if sidebar:
        for item in sidebar.walk('li'):
            label=_one(item,'strong','label')
            if label is None or label.text() not in {'회사명','직무명','근무형태','채용구분','근무지'}:continue
            value=item.text().removeprefix(label.text()).strip()
            if value:fields[label.text()]=value
    if fields:context['header_fields']=fields
    old_context=previous.get('source_context') or {}
    listing={k:old_context[k] for k in ('gubun','zz_target_1','zz_mthr_yn','zz_str_dt_str') if k in old_context}
    if not listing:listing=old_context.get('listing_metadata') or {}
    if listing:context['listing_metadata']=listing
    apply=_cj_public_apply(root,identity)
    return Job(identity,title.text(),employer.text(),url,apply_url=apply,description='원 공고: '+title.text()+'\n'+full,
        status='closed' if closed else 'open' if active else 'unknown',deadline=end,
        location=fields.get('근무지') or previous.get('location',''),detail_verified=bool(_body_text(body)),requires_role_split=True,
        source_context=context,raw={'provider':'cj','media_urls':media,'embedded_image_count':embedded,'external_detail_urls':external,
            'apply_action':'Observed anonymous login route; post-login application not inspected' if apply else 'Actual support button; final login path remains host verification'})
