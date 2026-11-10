"""Observed public LG/Hanwha UI contracts; no applicant or authenticated endpoints.

These adapters consume the anonymous responses used by the official pages. Free-form
editor/image campaigns remain host review work. A current list is a source snapshot,
not evidence of national coverage or of a specific applicant's progress.
"""
from datetime import datetime, timedelta, timezone
from html import unescape
import json
import re
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from .htmltools import html, links
from .model import EngineError, Job, Page, public_url

KINDS={'lgcareers-list','lgcareers-detail','hanwhain-list','hanwhain-detail'}
LG_API='https://api.careers.lg.com/rmk/job/'
HANWHA_API='https://hwadm.hanwhain.com/new-backend/portal/api/rcRecruit/'


def _json(payload):
    try:data=json.loads(payload)
    except (ValueError,UnicodeDecodeError) as exc:raise EngineError('public job JSON missing; not an empty inventory') from exc
    if not isinstance(data,dict):raise EngineError('public job response must be an object')
    return data


def _text(value):
    if not isinstance(value,str):return ''
    # A closing wrapper also flushes HTMLParser's trailing ambiguous '&name'
    # buffer (for plain source titles such as R&D/QA), without executing markup.
    return html(('<div>'+unescape(value)+'</div>').encode('utf-8')).text()


def _date(raw):
    if not raw:return {'kind':'unknown'}
    if not isinstance(raw,str):raise EngineError('unexpected public deadline format')
    value=raw.strip()
    for pattern in ('%Y.%m.%d %H:%M','%Y-%m-%d %H:%M','%Y.%m.%d %H:%M:%S','%Y-%m-%dT%H:%M:%S'):
        try:at=datetime.strptime(value,pattern).replace(tzinfo=timezone(timedelta(hours=9)))
        except ValueError:continue
        return {'kind':'datetime','at':at.isoformat()}
    for pattern in ('%Y.%m.%d','%Y-%m-%d'):
        try:day=datetime.strptime(value,pattern).date()
        except ValueError:continue
        return {'kind':'date','date':day.isoformat(),'timezone':'Asia/Seoul'}
    return {'kind':'unknown','source_text':value}


def _id(value):
    if isinstance(value,bool) or not re.fullmatch(r'[1-9]\d{0,11}',str(value)):
        raise EngineError('positive public posting ID required')
    return str(value)


def detect_kind(url):
    p=urlsplit(public_url(url))
    if p.hostname=='careers.lg.com' and p.path.rstrip('/')=='/apply':return 'lgcareers-list'
    if p.hostname=='careers.lg.com' and p.path.rstrip('/')=='/apply/detail':return 'lgcareers-detail'
    if p.hostname=='www.hanwhain.com':
        path=p.path.removeprefix('/portal').rstrip('/')
        if path=='/apply/recruit':return 'hanwhain-list'
        if path=='/apply/recruit/detail':return 'hanwhain-detail'
    return None


def request_spec(kind,url,cursor=None,settings=None):
    """Exact reviewed read-JSON request; transport validates fields again."""
    settings=settings or {}
    if kind not in KINDS or detect_kind(url)!=kind:raise EngineError('official public UI source mismatch')
    p=urlsplit(url);query=parse_qs(p.query)
    if set(query)-({'id'} if kind=='lgcareers-detail' else {'rtSeq'} if kind=='hanwhain-detail' else set()):
        raise EngineError('unreviewed public source query; hidden/preview routes prohibited')
    if kind=='lgcareers-list':
        if cursor is not None:raise EngineError('LG list is one full response with client-side pagination')
        fields={'lnbSearch':'','hashTagText':'','recDate':'POST_START_DATE','order':'DESC',
                'careerList':[],'companyCodeList':[],'desireLocList':[],'jobGroupList':[]}
        fields.update(settings.get('filters',{}))
        return LG_API+'retrieveJobNoticesList',fields
    if kind=='lgcareers-detail':
        return LG_API+'retrieveJobNoticesDetail',{'jobNoticeId':int(_id((query.get('id') or [''])[0]))}
    if kind=='hanwhain-detail':
        return HANWHA_API+'get-rcrt',{'rtSeq':int(_id((query.get('rtSeq') or [''])[0])),'hidnKey':None,'langCd':'ko'}
    page=int(cursor or '0')
    fields={'langCd':'ko','searchText':'','sdSeqList':None,'rtNrcrtYn':'','rtCarrYn':'','rtIntnYn':'',
            'rtPermanentWorkYn':'','rtTempWorkYn':'','djSeqList':None,'rjSeqList':None,
            'page':page,'size':20}
    fields.update(settings.get('filters',{}));fields['page']=page
    return HANWHA_API+'search-rcrt',fields


def _lg_data(payload):
    data=_json(payload)
    if data.get('status')!='S' or not isinstance(data.get('data'),dict):
        raise EngineError('LG anonymous query unsuccessful; not an empty list')
    return data['data']


def _hanwha_data(payload):
    data=_json(payload)
    if data.get('success') is not True or not isinstance(data.get('data'),dict):
        raise EngineError('Hanwha anonymous query unsuccessful; not an empty list')
    return data['data']


def parse_page(source,payload,cursor=None):
    kind=source['kind'];url=source['url']
    if kind.endswith('-detail'):
        return Page([parse_detail(kind,payload,url)],True,expected_total=1,
                    scope_note='One official public detail, not the employer inventory')
    if kind=='lgcareers-list':
        data=_lg_data(payload);rows=data.get('jobNoticeList');total=data.get('listCount')
        if not isinstance(rows,list) or isinstance(total,bool) or not isinstance(total,int):
            raise EngineError('LG full-list rows/declared count missing')
        jobs=[]
        for r in rows:
            identity=_id(r['jobNoticeId'])
            jobs.append(Job(identity,_text(r['jobNoticeName']),r['companyName'],
                'https://careers.lg.com/apply/detail?id='+identity,
                deadline=_date(r.get('recEndDateTime')),location=r.get('workLocationName') or '',
                status='open' if r.get('noticeStatus')=='POSTING' and r.get('recAvail')==1 else 'unknown',
                raw={'provider':'lgcareers','company_code':r.get('companyCode')},detail_verified=False))
        page=Page(jobs,True,expected_total=total,scope_note='Unfiltered LG public UI response; its desktop pages slice this returned array')
    elif kind=='hanwhain-list':
        data=_hanwha_data(payload);rows=data.get('list');more=data.get('hasNext')
        if not isinstance(rows,list) or not isinstance(more,bool):raise EngineError('Hanwha list rows/hasNext missing')
        total=data.get('filteredCount')
        if total is None:total=data.get('totalCount')
        if total is not None and (isinstance(total,bool) or not isinstance(total,int)):
            raise EngineError('Hanwha declared total is not an integer')
        current=int(cursor or '0')
        if current==0 and total is None:raise EngineError('Hanwha initial page needs a declared inventory total')
        if more and not rows:raise EngineError('Hanwha premature empty page')
        jobs=[Job(_id(r['rtSeq']),_text(r['rtNm']),r['sdNm'],
            'https://www.hanwhain.com/portal/apply/recruit/detail?rtSeq='+_id(r['rtSeq']),
            deadline=_date(r.get('rtAcptEndDttm')),published_at=r.get('rtAcptStrtDttm'),
            status='unknown',detail_verified=False,raw={'provider':'hanwhain'}) for r in rows]
        page=Page(jobs,not more,str(current+1) if more else None,expected_total=total,
            scope_note='Hanwha public current list, zero-based server pagination; later counts may be null')
    else:raise EngineError('unsupported domestic inventory')
    page.validate();return page


def _section(label,value):
    value=_text(value)
    return label+': '+value if value else ''


def parse_detail(kind,payload,url,settings=None):
    settings=settings or {}
    if detect_kind(url)!=kind:raise EngineError('domestic detail UI URL mismatch')
    if kind=='lgcareers-detail':
        expected=_id((parse_qs(urlsplit(url).query).get('id') or [''])[0])
        bundle=_lg_data(payload).get('jobNoticesDetail')
        if not isinstance(bundle,dict) or not isinstance(bundle.get('jobNoticesDetail'),dict):
            raise EngineError('LG detail/role bundle missing')
        r=bundle['jobNoticesDetail'];identity=_id(r['jobNoticeId'])
        if identity!=expected:raise EngineError('LG returned a different posting')
        context={key:r.get(key) for key in ('jobNoticeName','careerTypeCode','careerTypeName','recruitTypeCode','recruitTypeName','recAvail','applyAvailable','recStartDate','recEndDate') if r.get(key) is not None}
        common='\n'.join(filter(None,(_section(label,r.get(field)) for label,field in
            [('원 공고','jobNoticeName'),('경력 구분','careerTypeName'),('채용 구분','recruitTypeName'),
             ('공통 지원자격','qualForAppInfo'),('전형','recProcessInfo'),('제출방법','submitMethodInfo'),('기타','otherInfo')])))
        roles=[]
        for role in bundle.get('recList') or []:
            title=role.get('jobGroupName') or role.get('jobCodeName') or role.get('orgName')
            if not title:raise EngineError('LG role title missing')
            quote_text='모집직무: '+_text(title)
            section='\n'.join(filter(None,[quote_text]+[_section(label,role.get(field)) for label,field in
                [('조직','orgName'),('조직 소개','detailContext'),('주요업무','mainTask'),('전공','majorCodeName'),
                 ('필수사항','requiredItem'),('우대사항','preferredItem'),('근무지','locationName')]]))
            roles.append({'role_key':'sector-'+_id(role['recSectorId']),'title':_text(title),
                          'description':section+'\n'+common,'source_quote':quote_text})
        description='\n\n'.join([common]+[role['description'].split('\n'+common)[0] if common else role['description'] for role in roles]).strip()
        verified=bool(roles) and r.get('isImageFile')!='Y'
        available=r.get('applyAvailable')=='Y' and r.get('recAvail')==1 and r.get('viewFlag')=='Y'
        job=Job(identity,_text(r['jobNoticeName']),r['companyName'],url,
            apply_url='https://careers.lg.com/login?callBackUrl=/apply/detail?id='+identity if available else None,
            description=description,location=r.get('workLocation') or '',deadline=_date(r.get('recEndDate')),
            status='open' if available else 'unknown',published_at=r.get('recStartDate'),detail_verified=verified,
            requires_role_split=len(roles)>1 or not verified,source_context=context,
            raw={'provider':'lgcareers','role_sections':roles,'company_code':r.get('companyCode'),
                 'application_login_required':True,'apply_provenance':'Official public UI login navigation observed for the same route template',
                 'image_file_info':r.get('imgFileInfos'),'image_file_id':r.get('imageFileId'),'media_urls':[]})
    elif kind=='hanwhain-detail':
        expected=_id((parse_qs(urlsplit(url).query).get('rtSeq') or [''])[0]);r=_hanwha_data(payload).get('item')
        if not isinstance(r,dict) or _id(r.get('rtSeq'))!=expected:raise EngineError('Hanwha detail identity missing/mismatch')
        if r.get('rtHidnYn')=='Y':raise EngineError('hidden Hanwha posting is outside the public inventory adapter')
        # Some normally listed public posts still return an unused hidden-key
        # metadata field. Never consume, expose or send it in another request.
        context={key:r.get(key) for key in ('rtNm','rtMdeTp','rtNrcrtYn','rtCarrYn','rtIntnYn','rtPermanentWorkYn','rtTempWorkYn','rtAcptStrtDttm','rtAcptEndDttm') if r.get(key) is not None}
        common='\n'.join(filter(None,(_section(label,r.get(field)) for label,field in
            [('원 공고','rtNm'),('공통 응시자격','rtExmQlf'),('전형','rtExmProc'),('접수방법','rtRctPrd'),('기타','rtEct')])))
        markup=r.get('rtMdeCont') or '';tree=html(markup.encode('utf-8'));media=[]
        for node in tree.walk('img'):
            if node.attrs.get('src'):
                media.append(public_url(urljoin(url,node.attrs['src'])))
        external=[];observed_apply=[]
        for target,label,node in links(tree,url):
            if urlsplit(target).hostname!='www.hanwhain.com' and target not in external:external.append(target)
            image_labels=' '.join(img.attrs.get('alt','') for img in node.walk('img'))
            if re.search(r'지원하기|입사지원|apply(?: now)?',label+' '+image_labels,re.I) and target not in observed_apply:
                observed_apply.append(target)
        roles=[];units=r.get('unitDt') or []
        if not isinstance(units,list):raise EngineError('Hanwha role units missing')
        if r.get('rtMdeTp')=='FORM':
            for unit in units:
                quote_text='모집단위: '+_text(unit.get('ruNm'))
                section='\n'.join(filter(None,[quote_text]+[_section(label,unit.get(field)) for label,field in
                    [('세부업무·자격·우대','ruDtlJob'),('계획인원','ruRcrtPrsn'),('근무지역','ruWorkpl')]]))
                roles.append({'role_key':'unit-'+_id(unit['ruSeq']),'title':_text(unit.get('ruNm')),
                              'description':section+'\n'+common,'source_quote':quote_text,
                              'recruiting_status':'closed' if unit.get('ruClsYn')=='Y' else 'open' if unit.get('ruClsYn')=='N' else 'unknown'})
            verified=bool(roles) and all(_text(u.get('ruDtlJob')) for u in units)
            description='\n\n'.join([common]+[role['description'].split('\n'+common)[0] if common else role['description'] for role in roles]).strip()
        elif r.get('rtMdeTp')=='EDITOR':
            # unitDt may contain stale template text invisible in editor mode. Never
            # prefer it to the actually rendered editor; expose it only for host audit.
            visible=_text(markup);description=(visible+'\n'+common).strip()
            verified=bool(visible) and (not media or bool(list(tree.walk('table'))))
        else:raise EngineError('Hanwha unknown display mode requires host review')
        statuses={u.get('ruClsYn') for u in units} if r.get('rtMdeTp')=='FORM' else set()
        status='closed' if statuses=={'Y'} else 'open' if 'N' in statuses else 'unknown'
        apply=None
        if len(observed_apply)==1:apply=observed_apply[0]
        elif r.get('rtMdeTp')=='FORM' and r.get('rtApplyHidnYn')=='N':
            callback='/apply/recruit/detail?rtSeq='+expected
            apply='https://www.hanwhain.com/portal/login/login?returnUrl='+quote(callback,safe='')
        job=Job(expected,_text(r['rtNm']),r['sdNm'],url,apply_url=apply,description=description,
            location=' / '.join(dict.fromkeys(_text(u.get('ruWorkpl')) for u in units if u.get('ruWorkpl'))) if r.get('rtMdeTp')=='FORM' else '',
            deadline=_date(r.get('rtAcptEndDttm')),published_at=r.get('rtAcptStrtDttm'),status=status,
            detail_verified=verified,requires_role_split=r.get('rtMdeTp')!='FORM' or len(roles)>1 or not verified,
            source_context=context,
            raw={'provider':'hanwhain','role_sections':roles,'display_mode':r.get('rtMdeTp'),'editor_markup':markup,
                 'unit_metadata_for_host_audit':units,'media_urls':list(dict.fromkeys(media)),
                 'external_detail_urls':external,'application_login_required':bool(apply and urlsplit(apply).hostname=='www.hanwhain.com'),
                 'apply_provenance':'Observed 지원하기 editor anchor' if observed_apply else 'Official public browser support button navigated to this login route template' if apply else 'Application path requires host verification'})
    else:raise EngineError('unsupported domestic detail')
    job.validate();return job


def jobflex_request(url):
    """Public tenant selector observed in the official page, never an auth key."""
    p=urlsplit(public_url(url))
    if not (p.hostname or '').endswith('.recruiter.co.kr') or p.query or p.fragment:
        raise EngineError('public Jobflex detail URL required')
    match=re.fullmatch(r'/career/jobs/([1-9]\d{0,11})/?',p.path)
    if not match:raise EngineError('Jobflex detail path mismatch')
    return 'https://api-recruiter.recruiter.co.kr/position/v2/jobflex/'+match.group(1),p.hostname


def parse_jobflex_detail(payload,url,settings):
    endpoint,prefix=jobflex_request(url);r=_json(payload)
    employer=settings.get('employer')
    if not isinstance(employer,str) or not employer.strip():
        raise EngineError('Jobflex tenant needs an independently evidenced employer association')
    if not r.get('title') or not isinstance(r.get('jobDescription'),str):
        raise EngineError('Jobflex public detail missing; not a closed-posting assumption')
    markup=r['jobDescription'];tree=html(markup.encode('utf-8'));description=_text(markup)
    media=[public_url(urljoin(url,n.attrs['src'])) for n in tree.walk('img') if n.attrs.get('src')]
    status='closed' if r.get('submissionStatus')=='POST_SUBMISSION' else 'open' if r.get('submissionStatus')=='IN_SUBMISSION' and r.get('writeButtonStatus')=='OPEN' else 'unknown'
    end=_date(r.get('endDateTime'))
    if end['kind']=='unknown' and r.get('announcementType')=='ALWAYS':end={'kind':'rolling'}
    job=Job(urlsplit(url).path.rstrip('/').rsplit('/',1)[-1],_text(r['title']),employer,url,
        apply_url=public_url(r['applyUrl']) if r.get('applyUrl') else None,description=description,
        deadline=end,status=status,published_at=r.get('startDateTime'),detail_verified=bool(description),requires_role_split=True,
        raw={'provider':'jobflex','tenant_prefix':prefix,'media_urls':list(dict.fromkeys(media)),
             'apply_provenance':'Actual public position response applyUrl, not a constructed application URL',
             'role_sections':[],'description_type':r.get('jobDescriptionType'),'announcement_type':r.get('announcementType')})
    job.validate();return job
