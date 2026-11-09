"""Reversible, evidence-based links. Source records and histories are never deleted."""
import json
import uuid
from collections import defaultdict
from .model import EngineError,dump,stable_id,required
from .registries import digits

IDENTIFIERS={'legal_registration':13,'business_registration':10,'stock_code':6}

def identifiers(company):
    facts=json.loads(company['facts_json'])
    return {key:value for key,length in IDENTIFIERS.items() if (value:=digits(facts.get(key),length))}

def canonical(store, company_id):
    seen=set()
    while True:
        if company_id in seen:raise EngineError('corporate alias cycle')
        seen.add(company_id)
        row=store.db.execute('SELECT canonical_id FROM company_aliases WHERE alias_id=?',(company_id,)).fetchone()
        if not row:return company_id
        company_id=row[0]

def link_companies(store, alias_id, canonical_id, *, evidence_ref):
    required(evidence_ref,'official identity evidence')
    a,b=store.row('companies',alias_id),store.row('companies',canonical_id)
    ai,bi=identifiers(a),identifiers(b)
    shared={k:v for k,v in ai.items() if bi.get(k)==v}
    conflicting={k for k in ai.keys()&bi.keys() if ai[k]!=bi[k]}
    if not shared or conflicting:raise EngineError('identical official identifiers required; names alone cannot merge legal entities')
    root=canonical(store,canonical_id)
    if root==alias_id:raise EngineError('corporate alias cycle/self-link')
    existing=store.db.execute('SELECT canonical_id FROM company_aliases WHERE alias_id=?',(alias_id,)).fetchone()
    if existing:
        if canonical(store,existing[0])==root:return False
        raise EngineError('existing alias conflicts; undo explicitly before relinking')
    evidence={'shared':shared,'reference':evidence_ref}
    with store.transaction():
        store.db.execute('INSERT INTO company_aliases VALUES(?,?,?,?,?)',(alias_id,root,'shared official identifiers',dump(evidence),store._now()))
        store.db.execute('INSERT INTO identity_events VALUES(?,?,?,?,?,?)',(uuid.uuid4().hex,alias_id,root,'link',dump(evidence),store._now()))
    return True

def unlink_company(store,alias_id,*,reason):
    required(reason,'undo reason')
    with store.transaction():
        old=store.db.execute('SELECT * FROM company_aliases WHERE alias_id=?',(alias_id,)).fetchone()
        if not old:raise EngineError('no active alias')
        store.db.execute('DELETE FROM company_aliases WHERE alias_id=?',(alias_id,))
        store.db.execute('INSERT INTO identity_events VALUES(?,?,?,?,?,?)',(uuid.uuid4().hex,alias_id,old['canonical_id'],'unlink',dump({'reason':reason,'previous':dict(old)}),store._now()))

def reconcile(store):
    companies={r['id']:dict(r) for r in store.db.execute('SELECT * FROM companies')}
    index=defaultdict(list);links=0;conflicts=0
    for cid,company in companies.items():
        for field,value in identifiers(company).items():index[(field,value)].append(cid)
    for (field,value),ids in sorted(index.items()):
        if len(ids)<2:continue
        # A conflict anywhere in an identifier cluster prevents transitive accidental merging.
        all_identifiers=[identifiers(companies[cid]) for cid in ids]
        if any(len({d[k] for d in all_identifiers if k in d})>1 for k in IDENTIFIERS):
            conflict=stable_id(field,value,*sorted(ids));conflicts+=1
            store.db.execute('INSERT OR IGNORE INTO identity_conflicts VALUES(?,?,?,?,?,0)',(conflict,field+':'+value,dump(sorted(ids)),'conflicting official identifiers; no automatic link',store._now()))
            continue
        root=min(canonical(store,cid) for cid in ids)
        for cid in sorted(ids):
            if cid==root:continue
            try:links+=int(link_companies(store,cid,root,evidence_ref='registry snapshots / '+field+':'+value))
            except EngineError:
                conflicts+=1
    aliases=store.db.execute('SELECT COUNT(*) FROM company_aliases').fetchone()[0]
    unresolved=sum(not identifiers(c) for c in companies.values())
    return {'source_company_records':len(companies),'active_proven_identity_links':aliases,
            'identity_components':len(companies)-aliases,'new_links':links,'conflict_clusters':conflicts,
            'unidentified_source_records':unresolved,'national_unique_companies':'unknown',
            'note':'components are resolved source records, not a census of all Korean legal entities'}
