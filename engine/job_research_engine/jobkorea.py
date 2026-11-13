"""Read inert, public JobKorea HTML data. Never evaluate page JavaScript.

Description text records use UTF-8 byte lengths, not line lengths. A module
record can immediately follow a long HTML record without a separating newline.
"""
import json,re
from urllib.parse import parse_qs,urljoin,urlsplit
from .htmltools import html,media_references
from .model import EngineError,public_url


def page_metadata(payload):
    """Labelled public page fields, kept separate from an unread job body."""
    descriptions=[n.attrs.get('content','') for n in html(payload).walk('meta')
        if n.attrs.get('name','').lower()=='description']
    if len(descriptions)!=1:return {}
    text=descriptions[0];result={'source_text':text}
    experience=re.search(r'(?:^|[,，])\s*경력\s*:\s*(.*?)(?=\s*[,，]|$)',text)
    if experience:result['experience_requirement']=experience.group(1).strip()
    end=re.search(r'(?:^|[,，])\s*마감일\s*:\s*(\d{4}-\d{2}-\d{2})(?=\s*[,，]|\s*$)',text)
    if end:
        from datetime import date
        try:date.fromisoformat(end.group(1))
        except ValueError:pass
        else:result['deadline']={'kind':'date','date':end.group(1),'timezone':'Asia/Seoul'}
    return result


def _walk(value):
    yield value
    if isinstance(value,dict):
        for item in value.values():yield from _walk(item)
    elif isinstance(value,list):
        for item in value:yield from _walk(item)


def public_records(payload):
    if len(payload)>8_000_000:raise EngineError('public HTML too large')
    parts=[];decoder=json.JSONDecoder()
    for script in html(payload).walk('script'):
        text=script.raw_text().strip();prefix='self.__next_f.push('
        if not text.startswith(prefix):continue
        try:value,end=decoder.raw_decode(text,len(prefix))
        except ValueError:continue
        if text[end:].strip() not in {')',');'}:continue
        if isinstance(value,list) and len(value)==2 and value[0]==1 and isinstance(value[1],str):parts.append(value[1])
    if not parts:raise EngineError('public text stream absent; host review required')
    data=''.join(parts).encode('utf-8');values={};texts={};pos=0;count=0
    while pos<len(data):
        while pos<len(data) and data[pos] in b'\r\n':pos+=1
        if pos==len(data):break
        count+=1
        if count>10000:raise EngineError('too many public records')
        match=re.match(rb'([0-9a-f]*):',data[pos:])
        if not match:raise EngineError('public record framing changed')
        key=match[1].decode();pos+=match.end()
        if data[pos:pos+1]==b'T':
            length=re.match(rb'T([0-9a-f]+),',data[pos:])
            if not length:raise EngineError('invalid byte-text framing')
            size=int(length[1],16);pos+=length.end()
            if not 0<size<=4_000_000 or pos+size>len(data):raise EngineError('incomplete byte-text record')
            try:texts[key]=data[pos:pos+size].decode('utf-8')
            except UnicodeDecodeError as e:raise EngineError('invalid UTF8 byte-text') from e
            pos+=size
        elif data[pos:pos+1] and data[pos:pos+1] in b'[{"-0123456789tfn':
            rest=data[pos:].decode('utf-8')
            try:value,end=decoder.raw_decode(rest)
            except ValueError as e:raise EngineError('public JSON record changed') from e
            values[key]=value;pos+=len(rest[:end].encode('utf-8'))
        else:
            end=data.find(b'\n',pos)
            if end<0:break
            pos=end+1
    return values,texts


def observed_iframe(payload,source_url,external_id):
    values,_=public_records(payload);found=set();origin=urlsplit(public_url(source_url))
    if origin.hostname not in {'www.jobkorea.co.kr','m.jobkorea.co.kr'}:raise EngineError('observed public JobKorea host required')
    for value in values.values():
        for node in _walk(value):
            if not isinstance(node,dict) or node.get('data-sentry-element')!='IframeViewer' or not isinstance(node.get('src'),str):continue
            target=public_url(urljoin(source_url,node['src']));p=urlsplit(target)
            if p.hostname==origin.hostname and p.path=='/Recruit/GI_Read_Comt_Ifrm' and parse_qs(p.query).get('Gno')==[str(external_id)]:found.add(target)
    if len(found)!=1:raise EngineError('one source-matching observed description iframe required')
    return found.pop()


def description_body(payload,source_url,external_id):
    root=html(payload)
    if any('self.__next_f.push(' in n.raw_text() for n in root.walk('script')):
        values,texts=public_records(payload);refs=set()
        for value in values.values():
            for node in _walk(value):
                if not isinstance(node,dict) or node.get('data-sentry-element')!='GIReadDetailContentIframeClient' or str(node.get('jobId'))!=str(external_id):continue
                ref=node.get('htmlContent')
                if isinstance(ref,str) and re.fullmatch(r'\$[0-9a-f]+',ref):refs.add(ref[1:])
        if len(refs)!=1 or next(iter(refs)) not in texts:raise EngineError('job-matching public description reference absent')
        markup=texts[refs.pop()];root=html(markup.encode('utf-8'))
    else:
        markup=payload.decode('utf-8')
        if len(root.text().strip())<80:raise EngineError('empty/short iframe requires host inspection')
    media,inline,frames=media_references(root,source_url)
    return {'description':root.text(),'media_urls':media,'inline_media':inline,
            'embedded_frames':frames,'detail_verified':bool(root.text().strip()) and not(media or inline or frames)}
