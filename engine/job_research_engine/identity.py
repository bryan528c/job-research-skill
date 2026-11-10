"""Reversible, evidence-based links. Source records and histories are never deleted."""
import json
import uuid
from collections import defaultdict
from .model import EngineError,dump,stable_id,required
from .registries import digits
from .registry import normalize_stock_code

IDENTIFIERS={'legal_registration':13,'business_registration':10,'stock_code':6}

def identifiers(company):
    facts=json.loads(company['facts_json'])
    result={key:value for key,length in IDENTIFIERS.items() if key!='stock_code'
            and (value:=digits(facts.get(key),length))}
    # KRX short codes can contain letters. Do not erase them or turn a different
    # security into a numeric match; source parsers already pad numeric exports.
    stock=normalize_stock_code(facts.get('stock_code'))
    if stock:
        result['stock_code']=stock
    return result

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
    with store.transaction():
        store.row('companies',alias_id);store.row('companies',canonical_id)
        root=canonical(store,canonical_id);alias_root=canonical(store,alias_id)
        if root==alias_id:raise EngineError('corporate alias cycle/self-link')
        existing=store.db.execute('SELECT canonical_id FROM company_aliases WHERE alias_id=?',(alias_id,)).fetchone()
        if existing and canonical(store,existing[0])!=root:
            raise EngineError('existing alias conflicts; undo explicitly before relinking')
        members=store.db.execute('''WITH RECURSIVE component(component_root,id) AS (
            SELECT ?,? UNION SELECT ?,? UNION
            SELECT c.component_root,a.alias_id FROM company_aliases a JOIN component c ON a.canonical_id=c.id
        ) SELECT c.*,m.component_root FROM companies c JOIN component m ON c.id=m.id''',
            (root,root,alias_root,alias_root)).fetchall()
        values=defaultdict(set)
        by_root=defaultdict(lambda:defaultdict(set))
        for member in members:
            for field,value in identifiers(member).items():
                values[field].add(value);by_root[member['component_root']][field].add(value)
        if any(len(v)>1 for v in values.values()):
            raise EngineError('conflicting official identifiers in canonical alias component; review and undo explicitly')
        if existing:return False
        # The selected root need not itself carry every field proved by its
        # linked records. Require a shared identifier across the two complete,
        # internally consistent components rather than a name or an empty root.
        shared={field:next(iter(common)) for field in IDENTIFIERS
                if (common:=by_root[root][field]&by_root[alias_root][field])}
        if not shared:raise EngineError('identical official identifiers required; names alone cannot merge legal entities')
        evidence={'shared':shared,'reference':evidence_ref}
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
    known={cid:identifiers(c) for cid,c in companies.items()}
    index=defaultdict(list);links=0;conflicts=0;rejections=0;new_conflicts=0
    for cid,company in companies.items():
        for field,value in known[cid].items():index[(field,value)].append(cid)
    for (field,value),ids in sorted(index.items()):
        if len(ids)<2:continue
        # A conflict anywhere in an identifier cluster prevents transitive accidental merging.
        all_identifiers=[known[cid] for cid in ids]
        if any(len({d[k] for d in all_identifiers if k in d})>1 for k in IDENTIFIERS):
            conflict=stable_id(field,value,*sorted(ids));conflicts+=1
            inserted=store.db.execute('INSERT OR IGNORE INTO identity_conflicts VALUES(?,?,?,?,?,0)',(conflict,field+':'+value,dump(sorted(ids)),'conflicting official identifiers; no automatic link',store._now()))
            new_conflicts+=inserted.rowcount
            continue
        root=min(canonical(store,cid) for cid in ids)
        for cid in sorted(ids):
            if cid==root:continue
            try:links+=int(link_companies(store,cid,root,evidence_ref='registry snapshots / '+field+':'+value))
            except EngineError:
                rejections+=1
    aliases=store.db.execute('SELECT COUNT(*) FROM company_aliases').fetchone()[0]
    unresolved=sum(not v for v in known.values())
    return {'source_company_records':len(companies),'active_proven_identity_links':aliases,
            'identity_components':len(companies)-aliases,'new_links':links,'conflict_clusters':conflicts,
            'link_rejections':rejections,'new_conflict_records':new_conflicts,
            'stored_unresolved_conflict_records':store.db.execute('SELECT COUNT(*) FROM identity_conflicts WHERE resolved=0').fetchone()[0],
            'unidentified_source_records':unresolved,'national_unique_companies':'unknown',
            'note':'components are resolved source records, not a census of all Korean legal entities'}
