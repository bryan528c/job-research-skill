from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import urlsplit, urljoin, urlencode,quote,parse_qsl
from urllib.robotparser import RobotFileParser
from .model import EngineError, public_url

USER_AGENT='JobResearchEngine/0.3 (read-only; github.com/bryan528c/job-research-skill)'


class FetchError(EngineError):
    def __init__(self,code: str,message: str,retry_after: int | None=None):
        super().__init__(message);self.code=code;self.retry_after=retry_after


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str,str]
    body: bytes


def retry_delay(value: str | None) -> int:
    if not value:return 60
    try:return max(1,int(value))
    except ValueError:
        try:
            at=parsedate_to_datetime(value)
            if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
            return max(1,int((at-datetime.now(timezone.utc)).total_seconds()))
        except (ValueError,TypeError):return 60


class PublicHTTP:
    """Public reads with narrowly reviewed POST searches, no proxy/cookie reuse.

    Requests must be explicitly enabled by the caller. Source terms/policies must also
    be reviewed. robots.txt alone is NOT permission to ignore a site's terms.
    """
    def __init__(self, *, enabled=False, timeout=20, max_bytes=12_000_000, interval=1.0):
        self.enabled=enabled;self.timeout=timeout;self.max_bytes=max_bytes;self.interval=interval
        self.last={};self.robots_cache={}

    @staticmethod
    def resolve(host: str,port: int) -> str:
        try:records=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
        except OSError as e:raise FetchError('dns_unavailable','DNS resolution failed; no vacancy conclusion') from e
        addresses=sorted({r[4][0] for r in records})
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise FetchError('private_address','DNS resolves to a non-public address')
        return addresses[0]

    def _one(self,url: str,secret_query: dict[str,str] | None=None, *, form: dict | None=None,json_body: dict | None=None,public_tenant: str | None=None,gabia_site_info=False,hyundai_public_read=False) -> Response:
        public_url(url);p=urlsplit(url);host=p.hostname.encode('idna').decode('ascii')
        port=p.port or (443 if p.scheme=='https' else 80);addr=self.resolve(host,port)
        wait=self.interval-(time.monotonic()-self.last.get(host,0))
        if wait>0:time.sleep(wait)
        self.last[host]=time.monotonic()
        target=quote(p.path or '/',safe="/:@!$&'()*+,;=-._~%")
        query=p.query
        if secret_query:
            if p.scheme!='https':raise FetchError('credential_transport','credentials require HTTPS')
            query += ('&' if query else '')+urlencode(secret_query)
        if query:target+='?'+quote(query,safe="=&/?+:;@!$'()*,-._~%[]")
        conn=http.client.HTTPConnection(host,port,timeout=self.timeout)
        try:
            # Resolve once and connect to the checked IP. HTTPS validates the original hostname.
            sock=socket.create_connection((addr,port),timeout=self.timeout)
            if p.scheme=='https':sock=ssl.create_default_context().wrap_socket(sock,server_hostname=host)
            conn.sock=sock
            headers={'Host':p.netloc,'User-Agent':USER_AGENT,'Accept-Encoding':'identity','Accept':'application/json, application/xml, text/html;q=0.8, */*;q=0.5'}
            body=None
            if public_tenant is not None:
                headers['prefix']=public_tenant;headers['Origin']='https://'+public_tenant
                headers['Referer']=headers['Origin']+'/'
            if gabia_site_info:
                headers['x-career-site-domain']='gabia.com';headers['Origin']='https://recruit.gabia.com'
                headers['Referer']='https://recruit.gabia.com/'
            if hyundai_public_read:
                headers['X-HKMC-SERVICE']='HM'
                headers['Content-Type']='application/x-www-form-urlencoded'
            if form is not None:
                body=urlencode(form).encode('utf-8');headers['Content-Type']='application/x-www-form-urlencoded'
                headers['X-Requested-With']='XMLHttpRequest';headers['Referer']='https://www.skcareers.com/Recruit'
            if json_body is not None:
                body=json.dumps(json_body,ensure_ascii=False,separators=(',',':')).encode('utf-8')
                headers['Content-Type']='application/json'
                headers['Origin']='https://www.hanwhain.com' if host=='hwadm.hanwhain.com' else 'https://careers.lg.com'
                headers['Referer']=headers['Origin']+('/portal/apply/recruit' if host=='hwadm.hanwhain.com' else '/apply')
            conn.request('POST' if form is not None or json_body is not None else 'GET',target,body=body,headers=headers)
            r=conn.getresponse();headers={k.lower():v for k,v in r.getheaders()}
            if headers.get('content-encoding','identity').lower() not in {'identity',''}:
                raise FetchError('compressed_response','unexpected compression; no silent truncation')
            body=r.read(self.max_bytes+1)
            if len(body)>self.max_bytes:raise FetchError('response_limit','response exceeds safety limit; incomplete')
            return Response(url,r.status,headers,body)
        except FetchError:raise
        except (OSError,http.client.HTTPException) as e:
            # Do not include raw exception/URL: query credentials could be in lower-level messages.
            raise FetchError('network_error','network request failed',60) from e
        finally:conn.close()

    def get(self,url: str, *, secret_query: dict[str,str] | None=None) -> Response:
        if not self.enabled:raise FetchError('network_disabled','network access not enabled')
        current=public_url(url)
        for _ in range(6):
            response=self._one(current,secret_query)
            if response.status in {301,302,303,307,308}:
                if secret_query:raise FetchError('credential_redirect','credential-bearing redirect refused')
                loc=response.headers.get('location')
                if not loc:raise FetchError('redirect_without_location','invalid redirect')
                current=public_url(urljoin(current,loc));continue
            if response.status==429:
                raise FetchError('rate_limited','source requested backoff',retry_delay(response.headers.get('retry-after')))
            if response.status in {401,403}:raise FetchError('access_denied','authorization/permission required; no bypass')
            if response.status>=500:raise FetchError('upstream_error','source unavailable',60)
            if response.status!=200:raise FetchError('http_'+str(response.status),'unexpected HTTP status; not evidence of all postings closed')
            return response
        raise FetchError('redirect_limit','redirect loop/limit')

    def read_form(self,url: str,fields: dict) -> Response:
        """One observed public search form, not a general POST or application client."""
        if not self.enabled:raise FetchError('network_disabled','network access not enabled')
        if public_url(url)!='https://www.skcareers.com/Recruit/GetRecruitList':
            raise FetchError('write_route_refused','only the reviewed public inventory search route is allowed')
        allowed={'sort','searchText','corpCode','jobRole','recruitType','workingType','workingRegion'}
        if not isinstance(fields,dict) or not set(fields).issubset(allowed) or any(not isinstance(v,str) or len(v)>200 for v in fields.values()):
            raise FetchError('invalid_search_form','only bounded public inventory filters accepted')
        response=self._one(url,form=fields)
        if response.status==429:raise FetchError('rate_limited','source requested backoff',retry_delay(response.headers.get('retry-after')))
        if response.status>=500:raise FetchError('upstream_error','source unavailable',60)
        if response.status!=200:raise FetchError('http_'+str(response.status),'public search unavailable; redirects not followed')
        return response

    def permitted_by_robots(self,url: str) -> bool:
        p=urlsplit(public_url(url));origin=f'{p.scheme}://{p.netloc}'
        if origin not in self.robots_cache:
            try:response=self.get(origin+'/robots.txt')
            except FetchError as e:
                if e.code=='http_404':self.robots_cache[origin]=None
                else:raise FetchError('robots_unavailable','robots policy unavailable; hand off for review') from e
            else:
                parser=RobotFileParser();parser.parse(response.body.decode('utf-8','replace').splitlines())
                self.robots_cache[origin]=parser
        parser=self.robots_cache[origin]
        return True if parser is None else parser.can_fetch('JobResearchEngine',url)

    def read_json(self,url: str,fields: dict) -> Response:
        """Observed LG/Hanwha anonymous job queries; never a generic POST client."""
        if not self.enabled:raise FetchError('network_disabled','network access not enabled')
        base='https://api.careers.lg.com/rmk/job/'
        hanwha='https://hwadm.hanwhain.com/new-backend/portal/api/rcRecruit/'
        routes={'retrieveJobNotices','retrieveJobNoticesList','retrieveJobNoticesDetail'}
        checked=public_url(url)
        if checked not in {base+route for route in routes}|{hanwha+'search-rcrt',hanwha+'get-rcrt'}:
            raise FetchError('write_route_refused','only reviewed anonymous public job read routes are allowed')
        if not isinstance(fields,dict):raise FetchError('invalid_public_query','query must be a bounded object')
        route=checked.removeprefix(base)
        valid=False
        positive=lambda v:not isinstance(v,bool) and (isinstance(v,int) and 0<v<10**12 or isinstance(v,str) and re.fullmatch(r'[1-9][0-9]{0,11}',v) is not None)
        if checked.startswith(hanwha):
            if checked==hanwha+'get-rcrt':
                valid=set(fields)=={'rtSeq','hidnKey','langCd'} and positive(fields.get('rtSeq')) and fields.get('hidnKey') is None and fields.get('langCd') in ('ko','en')
            else:
                switches={'rtNrcrtYn','rtCarrYn','rtIntnYn','rtPermanentWorkYn','rtTempWorkYn'}
                arrays={'sdSeqList','djSeqList','rjSeqList'}
                valid={'langCd','page','size'}.issubset(fields) and set(fields).issubset(switches|arrays|{'langCd','searchText','page','size'})
                for key,value in fields.items():
                    if key=='langCd':valid=valid and value in ('ko','en')
                    elif key=='searchText':valid=valid and isinstance(value,str) and len(value)<=200
                    elif key=='page':valid=valid and isinstance(value,int) and not isinstance(value,bool) and 0<=value<=10000
                    elif key=='size':valid=valid and isinstance(value,int) and not isinstance(value,bool) and 1<=value<=100
                    elif key in switches:valid=valid and value in ('','Y','N')
                    elif key in arrays:valid=valid and (value is None or isinstance(value,list) and len(value)<=100 and all(positive(v) for v in value))
        elif route=='retrieveJobNotices':valid=not fields
        elif route=='retrieveJobNoticesDetail':
            value=fields.get('jobNoticeId')
            valid=set(fields)=={'jobNoticeId'} and not isinstance(value,bool) and (
                isinstance(value,int) and 0<value<10**12 or
                isinstance(value,str) and re.fullmatch(r'[1-9][0-9]{0,11}',value) is not None)
        else:
            strings={'lnbSearch','hashTagText'};arrays={'careerList','companyCodeList','desireLocList','jobGroupList'}
            valid=set(fields).issubset(strings|arrays|{'recDate','order'})
            for key,value in fields.items():
                if key in strings:valid=valid and isinstance(value,str) and len(value)<=200
                elif key in arrays:valid=valid and isinstance(value,list) and len(value)<=100 and all(isinstance(v,str) and len(v)<=80 for v in value)
                elif key=='recDate':valid=valid and isinstance(value,str) and value in {'POST_START_DATE','POST_END_DATE'}
                elif key=='order':valid=valid and isinstance(value,str) and value in {'ASC','DESC'}
        if not valid:raise FetchError('invalid_public_query','only observed bounded job filters accepted')
        response=self._one(checked,json_body=fields)
        if response.status==429:raise FetchError('rate_limited','source requested backoff',retry_delay(response.headers.get('retry-after')))
        if response.status>=500:raise FetchError('upstream_error','source unavailable',60)
        if response.status!=200:raise FetchError('http_'+str(response.status),'public job query unavailable; redirects not followed')
        return response

    def get_jobflex(self,url: str,prefix: str) -> Response:
        """Exact public Jobflex detail GET with its nonsecret UI tenant selector."""
        if not self.enabled:raise FetchError('network_disabled','network access not enabled')
        if not re.fullmatch(r'https://api-recruiter\.recruiter\.co\.kr/position/v2/jobflex/[1-9][0-9]{0,11}',public_url(url)):
            raise FetchError('write_route_refused','only reviewed public Jobflex position detail route allowed')
        if not isinstance(prefix,str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.recruiter\.co\.kr',prefix):
            raise FetchError('invalid_public_tenant','observed public recruiter tenant hostname required')
        response=self._one(url,public_tenant=prefix)
        if response.status==429:raise FetchError('rate_limited','source requested backoff',retry_delay(response.headers.get('retry-after')))
        if response.status>=500:raise FetchError('upstream_error','source unavailable',60)
        if response.status!=200:raise FetchError('http_'+str(response.status),'public Jobflex detail unavailable; redirects not followed')
        return response

    def get_gabia(self,url: str) -> Response:
        """Observed anonymous Gabia site-info/list/detail GETs, without applicant APIs."""
        if not self.enabled:raise FetchError('network_disabled','network access not enabled')
        base='https://recruit-api.gabiaoffice.hiworks.com/v1/career-site/'
        checked=public_url(url);info=checked==base+'tokens/site-information'
        if not info and not re.fullmatch(re.escape(base)+r'offices/[1-9][0-9]{0,8}/announces(?:/[a-z0-9]{6})?',checked):
            raise FetchError('write_route_refused','only reviewed anonymous Gabia career reads allowed')
        response=self._one(checked,gabia_site_info=True) if info else self._one(checked)
        if response.status==429:raise FetchError('rate_limited','source requested backoff',retry_delay(response.headers.get('retry-after')))
        if response.status>=500:raise FetchError('upstream_error','source unavailable',60)
        if response.status!=200:raise FetchError('http_'+str(response.status),'public Gabia read unavailable; redirects not followed')
        return response

    def get_hyundai_detail(self,url: str) -> tuple[Response,Response]:
        """Observed anonymous public detail GETs, gated by an explicit nonsecret flag.

        No password route, applicant API, cookie, token, queue or session reuse.
        The static HM routing header is the one published by the public UI.
        """
        if not self.enabled:raise FetchError('network_disabled','network access not enabled')
        p=urlsplit(public_url(url));pairs=parse_qsl(p.query,keep_blank_values=True)
        values=dict(pairs)
        if (p.scheme!='https' or p.netloc!='talent.hyundai.com' or p.fragment
            or p.path not in {'/apply/applyView.hc','/eng/apply/applyView.hc'}
            or len(pairs)!=len(values) or set(values)-{'nfGubnC','recuYy','recuType','recuCls'}
            or values.get('nfGubnC','')!=''
            or not re.fullmatch(r'20[0-9]{2}',values.get('recuYy',''))
            or not re.fullmatch(r'N[1-9][0-9]?',values.get('recuType',''))
            or not re.fullmatch(r'[1-9][0-9]{0,5}',values.get('recuCls',''))):
            raise FetchError('write_route_refused','only an observed public Hyundai job-detail identity is allowed')
        query=urlencode({'hgrCd':'1','lang':'ko',**{k:values[k] for k in ('recuYy','recuType','recuCls')}})
        base='https://talent.hyundai.com/api/rec/'
        responses=[]
        for route in ('AP-HM-FO-02900','AP-HM-FO-02800'):
            target=base+route+'?'+query
            if not self.permitted_by_robots(target):raise FetchError('robots_disallowed','public detail policy prevents native read')
            response=self._one(target,hyundai_public_read=True)
            if response.status==429:raise FetchError('rate_limited','source requested backoff',retry_delay(response.headers.get('retry-after')))
            if response.status!=200:raise FetchError('http_'+str(response.status),'public Hyundai read unavailable; redirects not followed')
            responses.append(response)
            if route=='AP-HM-FO-02900':
                try:flag=json.loads(response.body)['data']['applySecret']['recuNoticeSecretYn']
                except (ValueError,KeyError,TypeError):flag=None
                if flag!='N':
                    error=FetchError('nonpublic_or_unknown_notice','explicit nonsecret N required; password routes are never called')
                    error.public_gate_response=response
                    raise error
        return responses[0],responses[1]
