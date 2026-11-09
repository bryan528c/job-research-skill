from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urlsplit, urljoin, urlencode
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
    """GET-only, no proxy/cookie reuse, public IP pinning and per-host pacing.

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

    def _one(self,url: str,secret_query: dict[str,str] | None=None, *, form: dict | None=None) -> Response:
        public_url(url);p=urlsplit(url);host=p.hostname.encode('idna').decode('ascii')
        port=p.port or (443 if p.scheme=='https' else 80);addr=self.resolve(host,port)
        wait=self.interval-(time.monotonic()-self.last.get(host,0))
        if wait>0:time.sleep(wait)
        self.last[host]=time.monotonic()
        target=p.path or '/'
        query=p.query
        if secret_query:
            if p.scheme!='https':raise FetchError('credential_transport','credentials require HTTPS')
            query += ('&' if query else '')+urlencode(secret_query)
        if query:target+='?'+query
        conn=http.client.HTTPConnection(host,port,timeout=self.timeout)
        try:
            # Resolve once and connect to the checked IP. HTTPS validates the original hostname.
            sock=socket.create_connection((addr,port),timeout=self.timeout)
            if p.scheme=='https':sock=ssl.create_default_context().wrap_socket(sock,server_hostname=host)
            conn.sock=sock
            headers={'Host':p.netloc,'User-Agent':USER_AGENT,'Accept-Encoding':'identity','Accept':'application/json, application/xml, text/html;q=0.8, */*;q=0.5'}
            body=None
            if form is not None:
                body=urlencode(form).encode('utf-8');headers['Content-Type']='application/x-www-form-urlencoded'
                headers['X-Requested-With']='XMLHttpRequest';headers['Referer']='https://www.skcareers.com/Recruit'
            conn.request('POST' if form is not None else 'GET',target,body=body,headers=headers)
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
