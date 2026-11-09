"""Resumable keyless official registry acquisition; scope is source-specific."""
from datetime import date
from io import BytesIO
import json
import re
import time
from urllib.parse import urlencode
import uuid
import xml.etree.ElementTree as ET
import zipfile
from .htmltools import html
from .model import EngineError, digest, dump, public_url, stable_id
from .registry import krx_html_rows, safe_xml
from .transport import PublicHTTP, FetchError

PROVIDERS = {
 'krx': ('https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13',
         'KRX listed corporations export; listing does not establish company size'),
 'dart-web': ('https://dart.fss.or.kr/dsae001/downloadExcel.do',
              'DART public company overview export; not all Korean corporations; no corpCode API key needed'),
 'ftc': ('https://www.egroup.go.kr/egps/ps/io/kap/selectAjaxPsitnCmpnySumryList.do',
         'FTC designated-year domestic affiliate memberships; one company can belong to multiple groups'),
 'mme': ('https://www.mme.or.kr/PGMV0110.do',
         'Public confirmation-certificate issuances in selected year; may include cancelled certificates; not all midsized companies'),
}

def digits(value, length):
    value=re.sub(r'[^0-9]','',value or '')
    return value if len(value)==length and set(value)!={'0'} else None

def homepage(value):
    value=(value or '').strip()
    if not value or value in {'-','없음'}:return None
    try:return public_url(value if '://' in value else 'https://'+value)
    except EngineError:return None

class CheckedXML:
    def __init__(self, stream):self.stream=stream;self.tail=b''
    def read(self, size=-1):
        data=self.stream.read(size);scan=(self.tail+data).upper()
        if b'<!DOCTYPE' in scan or b'<!ENTITY' in scan:raise EngineError('DTD/entities prohibited')
        self.tail=scan[-16:];return data

def xlsx_rows(payload):
    """Stream a bounded official XLSX without executing formulas/external links."""
    ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    try:
        with zipfile.ZipFile(BytesIO(payload)) as z:
            infos=z.infolist()
            if sum(x.file_size for x in infos)>300_000_000 or any(x.file_size>250_000_000 or x.file_size/max(1,x.compress_size)>200 for x in infos):
                raise EngineError('registry workbook exceeds bounded uncompressed size')
            sheets=[x.filename for x in infos if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',x.filename)]
            if len(sheets)!=1:raise EngineError('expected one registry worksheet')
            strings=[]
            if 'xl/sharedStrings.xml' in z.namelist():
                strings=[''.join(n.itertext()) for n in safe_xml(z.read('xl/sharedStrings.xml'))]
            with z.open(sheets[0]) as stream:
                context=ET.iterparse(CheckedXML(stream),events=('start','end'))
                _,root=next(context)
                for event,node in context:
                    if event!='end' or node.tag!=ns+'row':continue
                    result={}
                    for cell in node.findall(ns+'c'):
                        if cell.find(ns+'f') is not None:raise EngineError('formula in registry identity data')
                        column=re.sub(r'\d','',cell.attrib.get('r',''))
                        value=cell.findtext(ns+'v') or ''
                        if cell.attrib.get('t')=='s':value=strings[int(value)]
                        elif cell.attrib.get('t')=='inlineStr':value=''.join(cell.find(ns+'is').itertext())
                        result[column]=value.strip()
                    yield result
                    node.clear();root.clear()
    except (zipfile.BadZipFile,ET.ParseError,IndexError,KeyError) as e:
        raise EngineError('invalid registry workbook') from e

def dart_web_rows(payload):
    records=xlsx_rows(payload);header=next(records,None)
    if not header or not {'회사이름','법인등록번호','사업자등록번호','종목코드'}.issubset(header.values()):
        raise EngineError('DART public workbook headers changed')
    rows=[]
    for record in records:
        r={name:record.get(column,'') for column,name in header.items()}
        if not r.get('회사이름'):raise EngineError('DART row missing company name')
        legal=digits(r.get('법인등록번호'),13);biz=digits(r.get('사업자등록번호'),10)
        # The export does not include corp_code. Keep unresolved rows as independent records.
        identity='legal:'+legal if legal else 'business:'+biz if biz else 'unresolved:'+digest(dump(r))
        facts={'legal_registration':legal,'business_registration':biz,
               'stock_code':digits(r.get('종목코드'),6),'listed_market':r.get('법인구분'),
               'identity_unresolved':not bool(legal or biz),'source_company_name':r.get('공시회사명'),
               'homepage_source_text':r.get('홈페이지'),
               'homepage_unusable':bool(r.get('홈페이지')) and homepage(r.get('홈페이지')) is None}
        rows.append({'external_id':identity,'name':r['회사이름'],'industry':r.get('업종명'),
                     'homepage':homepage(r.get('홈페이지')),'facts':facts})
    if not rows:raise EngineError('empty DART export')
    return rows

def table_records(payload, required):
    root=html(payload);out=[];headers=None
    for tr in root.walk('tr'):
        cells=[n.text() for n in tr.children if getattr(n,'tag',None) in {'td','th'}]
        if set(required).issubset(cells):headers=cells;continue
        if headers and len(cells)==len(headers):out.append(dict(zip(headers,cells)))
    if not headers:raise EngineError('official registry table missing; not an empty census')
    return root,out

def ftc_page(payload, page, year):
    _,records=table_records(payload,{'공개년월','기업집단명','소속회사명','법인등록번호'})
    total=re.search(rb'totCnt\s*=\s*(\d+)',payload)
    if not total:raise EngineError('FTC pagination total missing')
    rows=[]
    for r in records:
        legal=digits(r['법인등록번호'],13);biz=digits(r.get('사업자등록번호'),10)
        if not r['공개년월'].startswith(str(year)):raise EngineError('FTC returned another designated year')
        identity='legal:'+legal if legal else 'business:'+biz if biz else 'unresolved:'+digest(dump(r))
        rows.append({'external_id':identity,'name':r['소속회사명'],'group_name':r['기업집단명'],
                     'industry':r.get('영위업종'),'facts':{'legal_registration':legal,'business_registration':biz,
                     'designation_month':r['공개년월'],'group_memberships':[r['기업집단명']],
                     'identity_unresolved':not bool(legal or biz)}})
    return rows,int(total.group(1)), page*100>=int(total.group(1))

def mme_page(payload, page, year):
    root,records=table_records(payload,{'기업명','사업자등록번호','발급번호','유효기간'})
    options=[int(x) for x in re.findall(rb'jsMovePage\((\d+)\)',payload)]
    last=max([page,*options]);rows=[]
    for r in records:
        if not r['발급번호'].startswith(str(year)+'-'):raise EngineError('MME year filter ignored')
        biz=digits(r['사업자등록번호'],10)
        if not biz:raise EngineError('MME business identity missing')
        rows.append({'external_id':'business:'+biz,'name':r['기업명'],
          'facts':{'business_registration':biz,'certificate_records':[{'number':r['발급번호'],'valid_period':r['유효기간']}],
                   'size_evidence':'certificate_issuance_only_cancellation_not_disclosed'}})
    if not rows:raise EngineError('premature empty MME page')
    return rows,None,page>=last

def collapse_rows(rows):
    result={};duplicates=0;conflicts=[]
    for r in rows:
        key=r['external_id'];old=result.get(key)
        if not old:result[key]=r;continue
        duplicates+=1
        conflicting=False
        for field in ('legal_registration','business_registration'):
            a,b=old.get('facts',{}).get(field),r.get('facts',{}).get(field)
            if a and b and a!=b:conflicts.append({'identity':key,'field':field});conflicting=True
        if conflicting:
            # An official export can contain branches, stale numbers or bad identities.
            # Retain the good rows and every conflict separately instead of blocking the whole census.
            variant={**r,'external_id':key+':variant:'+digest(dump(r))[:20],
                     'facts':{**r.get('facts',{}),'identity_conflict':True}}
            result[variant['external_id']]=variant
            continue
        for field in ('group_memberships','certificate_records'):
            values=old['facts'].get(field,[])
            for v in r.get('facts',{}).get(field,[]):
                if v not in values:values.append(v)
            if values:old['facts'][field]=values
        if old.get('group_name')!=r.get('group_name') and r.get('group_name'):
            old['group_name']=' / '.join(old['facts']['group_memberships'])
        if old['name']!=r['name']:
            old['facts'].setdefault('source_name_variants',[old['name']])
            if r['name'] not in old['facts']['source_name_variants']:old['facts']['source_name_variants'].append(r['name'])
    return list(result.values()),duplicates,conflicts

def page_url(provider, year, page):
    base=PROVIDERS[provider][0]
    if provider=='ftc':return base+'?'+urlencode({'sch_applYear':year,'pageIndex':page,'pageUnit':100})
    if provider=='mme':return base+'?'+urlencode({'search_year':year,'df_curr_page':page,'df_row_per_page':100})
    return base

def parse(provider,payload,page,year):
    if provider=='ftc':return ftc_page(payload,page,year)
    if provider=='mme':return mme_page(payload,page,year)
    rows=krx_html_rows(payload) if provider=='krx' else dart_web_rows(payload)
    return rows,len(rows),True

def sync_registry(store, provider, *, year=None, transport=None, budget_seconds=40, restart=False):
    if provider not in PROVIDERS:raise EngineError('unknown official registry')
    year=year or date.today().year
    transport=transport or PublicHTTP(max_bytes=30_000_000)
    if getattr(transport,'evidence_origin',None)=='fixture':origin='fixture'
    else:origin='native_registry'
    session=store.db.execute("SELECT * FROM registry_syncs WHERE provider=? AND year=? AND status IN ('running','blocked') ORDER BY created_at DESC LIMIT 1",(provider,year)).fetchone()
    if restart:session=None
    if session:
        session=dict(session);sid=session['id'];page=session['next_page']
    else:
        sid=uuid.uuid4().hex;page=1
        store.db.execute("INSERT INTO registry_syncs VALUES(?,?,?,1,'running',?,NULL,NULL)",(sid,provider,year,store._now()))
    started=time.monotonic();attempted=0
    while time.monotonic()-started<budget_seconds:
        url=page_url(provider,year,page)
        try:
            response=transport.get(url);rows,total,terminal=parse(provider,response.body,page,year)
            fingerprint=digest(dump(rows))
            previous=store.db.execute('SELECT * FROM registry_acquisitions WHERE sync_id=? ORDER BY page',(sid,)).fetchall()
            if any(p['fingerprint']==fingerprint for p in previous):raise EngineError('registry server repeated a page')
            totals={p['expected_total'] for p in previous if p['expected_total'] is not None}
            if total is not None and totals and total not in totals:raise EngineError('registry total changed; restart separate snapshot')
            with store.transaction():
                store.db.execute('INSERT INTO registry_acquisitions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                  (sid,page,response.url,store._now(),digest(response.body),fingerprint,total,dump(rows),response.body,
                   response.headers.get('content-type','application/octet-stream'),origin))
                store.db.execute("UPDATE registry_syncs SET next_page=?,status='running',error=NULL WHERE id=?",(page+1,sid))
            attempted+=1
            if terminal:
                acquisitions=store.db.execute('SELECT * FROM registry_acquisitions WHERE sync_id=? ORDER BY page',(sid,)).fetchall()
                allrows=[r for p in acquisitions for r in json.loads(p['rows_json'])]
                if total is not None and len(allrows)!=total:raise EngineError('registry raw row total mismatch')
                if len(acquisitions)>1:
                    # Recheck the head to detect a moving inventory. Dynamic HTML/session bytes do not count as changes.
                    head=transport.get(page_url(provider,year,1));headrows,headtotal,_=parse(provider,head.body,1,year)
                    if digest(dump(headrows))!=acquisitions[0]['fingerprint'] or headtotal!=acquisitions[0]['expected_total']:
                        raise EngineError('registry first page changed during traversal; partial snapshot retained')
                combined,duplicates,conflicts=collapse_rows(allrows)
                combined_hash=digest(dump([{'page':p['page'],'url':p['source_url'],'sha256':p['sha256']} for p in acquisitions]))
                result=store.import_companies(provider,combined,source_url=PROVIDERS[provider][0],raw_sha256=combined_hash,
                    scope=PROVIDERS[provider][1]+f'; year={year}; raw_rows={len(allrows)}',
                    completeness='partial' if conflicts else 'complete_source_snapshot',provenance=origin)
                result.update(sync_id=sid,provider=provider,year=year,pages=len(acquisitions),raw_rows=len(allrows),
                              duplicate_identity_rows=duplicates,identity_conflicts=len(conflicts))
                store.db.execute("UPDATE registry_syncs SET status='done',snapshot_id=?,error=NULL WHERE id=?",(result['snapshot_id'],sid))
                for issue in conflicts:
                    store.db.execute('INSERT OR IGNORE INTO identity_conflicts VALUES(?,?,?,?,?,0)',
                      (stable_id(sid,dump(issue)),issue['identity'],dump([]),'source export conflicting '+issue['field']+'; rows retained separately',store._now()))
                store._log('registry',result['snapshot_id'],'acquisition_validation',result)
                return result
            page+=1
        except (EngineError,OSError,ValueError,KeyError) as exc:
            code=getattr(exc,'code','registry_contract_failure')
            # A terminal snapshot that failed validation must restart separately; never resume past its end.
            saved=store.db.execute('SELECT 1 FROM registry_acquisitions WHERE sync_id=? AND page=?',(sid,page)).fetchone()
            state='invalid' if saved else 'blocked'
            store.db.execute('UPDATE registry_syncs SET status=?,error=? WHERE id=?',(state,code+': '+str(exc),sid))
            return {'sync_id':sid,'provider':provider,'status':'blocked','next_page':page,'reason':code,'detail':str(exc),'pages_saved':page-1}
    return {'sync_id':sid,'provider':provider,'status':'checkpoint','next_page':page,'pages_saved':page-1,'pages_this_call':attempted}
