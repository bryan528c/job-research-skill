from __future__ import annotations
import csv
from html.parser import HTMLParser
import io
import re
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from .model import EngineError, digest, public_url
from .store import Store


def safe_xml(payload: bytes) -> ET.Element:
    if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
        raise EngineError('DTD/entities not supported')
    try:return ET.fromstring(payload)
    except ET.ParseError as e:raise EngineError('invalid XML') from e


def dart_rows(payload: bytes) -> list[dict]:
    """Official corpCode XML or ZIP. This does NOT classify companies as midsized/large."""
    if payload[:2]==b'PK':
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            entries=[i for i in z.infolist() if i.filename.upper().endswith('.XML')]
            if len(entries)!=1 or entries[0].file_size>150_000_000 or entries[0].compress_size==0 or entries[0].file_size/entries[0].compress_size>200:
                raise EngineError('invalid/oversized registry archive')
            payload=z.read(entries[0])
    root=safe_xml(payload)
    if root.findtext('status') not in {None,'000'}:
        raise EngineError('registry API error; not an empty census')
    out=[]
    for node in root.findall('list'):
        code=(node.findtext('corp_code') or '').strip();name=(node.findtext('corp_name') or '').strip()
        if not code or not name:raise EngineError('DART row missing identity')
        out.append({'external_id':code,'name':name,'facts':{
            'dart_corp_code':code,'stock_code':(node.findtext('stock_code') or '').strip(),
            'modified_date':node.findtext('modify_date'),'scope':'DART disclosing companies, not every Korean legal entity'}})
    if not out:raise EngineError('DART XML contains no company list')
    return out


class _TableParser(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.row=[];self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in {'td','th'}:self.cell=[]
    def handle_endtag(self,tag):
        if tag in {'td','th'} and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.row:self.rows.append(self.row)
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)


def krx_html_rows(payload: bytes) -> list[dict]:
    decoded=None
    for encoding in ('utf-8-sig','cp949'):
        try:decoded=payload.decode(encoding);break
        except UnicodeDecodeError:pass
    if decoded is None:raise EngineError('unsupported KRX encoding')
    p=_TableParser();p.feed(decoded)
    header=None;result=[]
    for row in p.rows:
        if '회사명' in row and '종목코드' in row:header=row;continue
        if header and len(row)==len(header):
            r=dict(zip(header,row));code=r['종목코드'].strip()
            if code.isdigit():code=code.zfill(6)
            if not re.fullmatch(r'[A-Za-z0-9]{6}',code):raise EngineError('KRX row missing valid listing identity')
            site=(r.get('홈페이지') or '').strip()
            if site:
                try:site=public_url(site if '://' in site else 'https://'+site)
                except EngineError:site=None
            result.append({'external_id':code.zfill(6),'name':r['회사명'],
                'industry':r.get('업종'),'homepage':site or None,
                'facts':{'stock_code':code,'scope':'KRX listed entities only','region':r.get('지역'),
                         'homepage_source_text':r.get('홈페이지')}})
    if not result:raise EngineError('KRX table missing/changed; cannot report zero companies')
    return result


def csv_rows(payload: bytes) -> list[dict]:
    """Normalized official exports. Preserve group/size evidence; do not infer from listing."""
    try:reader=csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))
    except UnicodeDecodeError as e:raise EngineError('CSV must be UTF-8') from e
    if not {'external_id','name'}.issubset(set(reader.fieldnames or [])):
        raise EngineError('registry CSV needs external_id,name')
    rows=[]
    for r in reader:
        rows.append({k:v for k,v in r.items() if k in {'external_id','name','group_name','size_class','industry','homepage'} and v})
    return rows


def import_registry(store: Store, path: Path, *, kind: str, registry: str, source_url: str,
                    scope: str, completeness='partial',provenance='host_import') -> dict:
    payload=path.read_bytes()
    if len(payload)>150_000_000:raise EngineError('registry input exceeds safety size')
    parsers={'dart':dart_rows,'krx-html':krx_html_rows,'csv':csv_rows}
    if kind not in parsers:raise EngineError('unsupported registry parser')
    return store.import_companies(registry,parsers[kind](payload),source_url=source_url,
            raw_sha256=digest(payload),scope=scope,completeness=completeness,provenance=provenance)
