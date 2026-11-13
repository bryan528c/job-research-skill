"""Observed rendered inventories plus anonymous native detail reads.

SSR homepage layout JSON is not a zero-job inventory. The host must follow
actual visible pagination and click cards to expose their public job URLs.
"""
from collections import Counter
import json,re
from urllib.parse import urlsplit
from .model import EngineError,Job,Page,public_url


def parse_rendered_inventory(payload,url,settings):
    try:data=json.loads(payload)
    except (ValueError,UnicodeError) as e:raise EngineError('Ninehire inventory requires actual rendered host capture, not homepage layout HTML') from e
    if not isinstance(data,dict) or not isinstance(data.get('pages'),list) or not data['pages'] or not isinstance(data.get('details'),list):
        raise EngineError('actual Ninehire pages and clicked detail paths required')
    pages=data['pages'];details=data['details'];numbers=[];titles=[]
    for page in pages:
        try:numbers.append(int(page['active']))
        except (KeyError,ValueError,TypeError) as e:raise EngineError('actual visible page number required') from e
        if not isinstance(page.get('titles'),list) or not page['titles']:raise EngineError('visible card titles required')
        titles.extend(page['titles'])
    if numbers!=list(range(1,len(pages)+1)):raise EngineError('pagination missing/repeated; resume host inventory')
    if Counter(titles)!=Counter(d.get('title') for d in details):raise EngineError('clicked details do not reconcile with visible cards')
    complete=data.get('actual_end') is True
    if complete and (str(pages[-1].get('next_disabled')).lower()!='true' or any(str(p.get('next_disabled')).lower()!='false' for p in pages[:-1])):
        raise EngineError('actual final disabled next-page control required')
    employer=settings.get('employer')
    if not employer:raise EngineError('observed employer display required; legal binding is separate')
    origin=urlsplit(public_url(url));jobs=[];seen=set()
    for item in details:
        target=public_url(item['url']);p=urlsplit(target)
        match=re.fullmatch(r'/job_posting/([A-Za-z0-9]{4,40})/?',p.path)
        if p.scheme!='https' or p.netloc!=origin.netloc or p.query or p.fragment or not match:
            raise EngineError('actual same-site Ninehire detail URL required; no applicant or authentication paths')
        key=match.group(1)
        if key in seen:raise EngineError('duplicate clicked posting identity')
        seen.add(key);jobs.append(Job(key,item['title'],employer,target,status='unknown',detail_verified=False))
    return Page(jobs,True,expected_total=len(jobs) if complete else None,inventory_complete=complete,
        scope_note='Actual unfiltered rendered Ninehire cards, clicked URLs and final control; individual native details and legal employers separate')
