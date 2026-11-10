"""Host adapter for actual normal-browser Hyundai DOM captures.

Only the recognized visible job sections are normalized. Password-modal HTML,
recommendations, navigation and footer are never interpreted as role requirements.
No network, browser automation, credentials, applications or DB writes live here.
"""
from datetime import datetime
from urllib.parse import urlsplit, parse_qsl, quote
import re
from job_research_engine.model import Job, EngineError, public_url

ROLE_LABELS=('조직소개','직무상세','지원자격','우대사항','전형단계','기타')
META_LABELS=('부문','분야','직급','근무지역')
DECORATIVE='https://talent.hyundai.com/static/images/apply/detail_list_banner.png'

def identity(url):
    p=urlsplit(public_url(url));pairs=parse_qsl(p.query,keep_blank_values=True);q=dict(pairs)
    if (p.scheme!='https' or p.netloc!='talent.hyundai.com' or p.fragment
        or p.path not in ('/apply/applyView.hc','/eng/apply/applyView.hc')
        or len(pairs)!=len(q) or set(q)-{'nfGubnC','recuYy','recuType','recuCls'}
        or q.get('nfGubnC','')!=''
        or not re.fullmatch(r'20\d{2}',q.get('recuYy',''))
        or not re.fullmatch(r'N[1-9]\d?',q.get('recuType',''))
        or not re.fullmatch(r'[1-9]\d{0,5}',q.get('recuCls',''))):
        raise EngineError('expected observed public Hyundai detail identity; never queue/private routes')
    return tuple(q[k] for k in ('recuYy','recuType','recuCls'))

def parse_rendered(record,*,visual_reviewed_urls=frozenset(),single_role_reviewed=False,role_properties=None):
    """Normalize an actual host DOM export; caller supplies independent review facts."""
    observed_url=record.get('url');requested=record.get('requested_url') or observed_url
    ids=identity(observed_url)
    if identity(requested)!=ids:raise EngineError('requested and rendered Hyundai identities differ')
    title=record.get('title');body=record.get('body_text')
    if not isinstance(title,str) or not title.strip() or not isinstance(body,str):
        raise EngineError('actual rendered title/body missing; not an empty inventory')
    own_start=body.find(title)
    if own_start<0:raise EngineError('rendered subject absent from visible body')
    role={};metadata={}
    for section in record.get('sections',[]):
        text=section.get('text','').strip()
        if not text:continue  # excludes the blank hidden password-modal DL
        label,_,value=text.partition('\n');label=label.strip();value=value.strip()
        target=role if label in ROLE_LABELS else metadata if label in META_LABELS else None
        if target is None:continue
        if label in target and target[label]!=value:raise EngineError('conflicting visible role sections require host review')
        target[label]=value
    if not role.get('직무상세') or not role.get('지원자격'):
        raise EngineError('actual duty/eligibility text absent; host/image review remains required')
    header=body[own_start:]
    boundaries=[header.find('\n'+label) for label in ROLE_LABELS if '\n'+label in header]
    if not boundaries:raise EngineError('own visible role boundary missing; do not borrow recommendation dates')
    header=header[:min(boundaries)]
    period=re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*~\s*(채용시까지|\d{4}-\d{2}-\d{2} \d{2}:\d{2})',header)
    if not period:raise EngineError('own visible posting period missing; no recommendation-card dates')
    begin,finish=period.groups();published=datetime.strptime(begin,'%Y-%m-%d %H:%M').isoformat()+'+09:00'
    deadline=({'kind':'rolling','source_text':'채용시까지'} if finish=='채용시까지' else
              {'kind':'datetime','at':datetime.strptime(finish,'%Y-%m-%d %H:%M').isoformat()+'+09:00','timezone':'Asia/Seoul','source_text':finish})
    media=[];needs_visual=[]
    for image in record.get('images',[]):
        src=public_url(image['src'])
        reviewed=src==DECORATIVE or src in visual_reviewed_urls
        media.append({**image,'classification':'decorative' if src==DECORATIVE else 'host-reviewed title/recommendation banner' if reviewed else 'requires_visual_review','visual_reviewed':reviewed})
        if not reviewed:needs_visual.append(src)
    frames=record.get('iframes',[])
    if frames:needs_visual.extend(str(f) for f in frames)
    desc=title+'\n'+begin+' ~ '+finish
    for label in ROLE_LABELS:
        if role.get(label):desc+='\n\n'+label+'\n'+role[label]
    for label in META_LABELS:
        if label in metadata:desc+='\n\n'+label+'\n'+metadata[label]
    current_path=urlsplit(observed_url).path
    own_query='?recuYy='+ids[0]+'&recuCls='+ids[2]+'&recuType='+ids[1]
    login_rule='https://talent.hyundai.com'+('/eng' if current_path.startswith('/eng/') else '')+'/signin/signin.hc?returnUrl='+quote(current_path+own_query,safe='')
    context={'public_identity':{'year':int(ids[0]),'type':ids[1],'id':int(ids[2])},'metadata':metadata,'role_sections':role,'media':media,'iframes':frames,
        'employer_display_source':'Actual official Hyundai talent DOM/footer; legal-registry binding remains a separate audit',
        'role_properties':role_properties or {},
        'application_start_evidence':{'visible_button':any(b.get('id')=='btnApply' and b.get('label')=='지원하기' for b in record.get('buttons',[])),
            'source_rule':'observed public applyView#btnApply -> loadingConfirm -> common.js login alert and encoded own returnUrl',
            'login_start_url_from_public_UI_rule':login_rule,'per_posting_button_click':'not_run for these51; prior3 shared-rule UI clicks verified separately',
            'post_login_path':'not_run; authentication and application are outside this collection','actual_apply_url_verified':False},
        'single_role_reviewed':single_role_reviewed,'unreviewed_media':needs_visual}
    return Job(external_id=':'.join(ids),title=title,employer='현대자동차',job_url=observed_url,apply_url=None,
        description=desc,location=metadata.get('근무지역',''),status='open',deadline=deadline,published_at=published,
        detail_verified=not needs_visual,requires_role_split=not single_role_reviewed,source_context=context,raw={'host_dom_capture':record})
