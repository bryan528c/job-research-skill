"""Reversible, evidence-based links. Source records and histories are never deleted."""
import json
import uuid
from collections import defaultdict
from urllib.parse import urlsplit
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


def effective_identifiers(store,company,*,overrides=None):
    result=identifiers(company)
    rows=overrides if overrides is not None else store.db.execute(
        'SELECT * FROM identifier_overrides WHERE company_id=? AND revoked_at IS NULL',(company['id'],)).fetchall()
    for row in rows:
        if result.get(row['field']) not in {row['source_value'],row['corrected_value']}:
            raise EngineError('identifier override source drift; explicit review required')
        result[row['field']]=row['corrected_value']
    return result


def identifier_override_drifts(store):
    result=[]
    for row in store.db.execute('SELECT * FROM identifier_overrides WHERE revoked_at IS NULL'):
        actual=identifiers(store.row('companies',row['company_id'])).get(row['field'])
        if actual not in {row['source_value'],row['corrected_value']}:
            result.append({'company_id':row['company_id'],'override_id':row['id'],'field':row['field'],'actual':actual})
    return result


def _component(store,root):
    return store.db.execute('''WITH RECURSIVE members(id) AS (
        SELECT ? UNION SELECT a.alias_id FROM company_aliases a JOIN members m ON a.canonical_id=m.id
        ) SELECT c.* FROM companies c JOIN members m ON c.id=m.id''',(root,)).fetchall()


def override_identifier(store,company_id,field,*,expected_source_value,corrected_value,evidence_ids,reason):
    """Human-reviewed correction overlay; raw registry IDs/facts never change."""
    required(reason,'identifier correction reason')
    if field not in IDENTIFIERS:raise EngineError('unknown official identifier field')
    fake={'facts_json':dump({field:corrected_value})}
    if identifiers(fake).get(field)!=corrected_value:raise EngineError('normalized official identifier required')
    with store.transaction():
        company=store.row('companies',company_id)
        if identifiers(company).get(field)!=expected_source_value:raise EngineError('source identifier changed; review the new official record')
        evidence=[store.row('observations',oid) for oid in set(evidence_ids)]
        if len({urlsplit(o['source_url']).hostname for o in evidence if o['origin'] in {'native_http','host_export','fixture'}})<2:
            raise EngineError('independent observed source domains required for identifier correction')
        previous=store.db.execute('SELECT * FROM identifier_overrides WHERE company_id=? AND field=? AND revoked_at IS NULL',(company_id,field)).fetchone()
        if previous:
            if previous['source_value']==expected_source_value and previous['corrected_value']==corrected_value:return previous['id']
            raise EngineError('active correction exists; revoke explicitly before replacement')
        root=canonical(store,company_id)
        oid=uuid.uuid4().hex
        store.db.execute('INSERT INTO identifier_overrides VALUES(?,?,?,?,?,?,?,?,NULL)',
            (oid,company_id,field,expected_source_value,corrected_value,dump(sorted(set(evidence_ids))),reason,store._now()))
        values=defaultdict(set)
        for member in _component(store,root):
            for key,value in effective_identifiers(store,dict(member)).items():values[key].add(value)
        if any(len(v)>1 for v in values.values()):raise EngineError('correction conflicts with the active identity component')
        store._log('identifier_override',oid,'created',{'company_id':company_id,'field':field,'raw_registry_facts_preserved':True})
    return oid


def revoke_identifier_override(store,override_id,*,reason):
    required(reason,'correction undo reason')
    with store.transaction():
        row=store.row('identifier_overrides',override_id)
        if row['revoked_at']:return False
        root=canonical(store,row['company_id'],_check_corrections=False)
        store.db.execute('UPDATE identifier_overrides SET revoked_at=? WHERE id=?',(store._now(),override_id))
        values=defaultdict(set)
        for member in _component(store,root):
            for key,value in effective_identifiers(store,dict(member)).items():values[key].add(value)
        if any(len(v)>1 for v in values.values()):raise EngineError('undo the dependent alias before revoking its identifier evidence')
        store._log('identifier_override',override_id,'revoked',{'reason':reason})
    return True


def review_identity_conflict(store,conflict_id,*,disposition,evidence_ids,reason):
    required(reason,'identity conflict review reason')
    if disposition not in {'linked_after_correction','historical_relationship','distinct_entities','unresolved'}:
        raise EngineError('unknown identity review disposition')
    with store.transaction():
        conflict=store.row('identity_conflicts',conflict_id)
        if not evidence_ids:raise EngineError('identity review requires actual observations')
        for oid in evidence_ids:store.row('observations',oid)
        if disposition=='linked_after_correction':
            ids=json.loads(conflict['companies_json'])
            if len(ids)<2 or len({canonical(store,cid) for cid in ids})!=1:
                raise EngineError('conflict cannot be resolved before its exact members have a proven consistent alias')
            values=defaultdict(set)
            for cid in ids:
                for key,value in effective_identifiers(store,store.row('companies',cid)).items():values[key].add(value)
            if any(len(v)>1 for v in values.values()):raise EngineError('effective official identifiers still conflict')
            store.db.execute('UPDATE identity_conflicts SET resolved=1 WHERE id=?',(conflict_id,))
        # Explaining a historical relationship or different entities does not
        # prove which conflicting source identifier is correct.
        review=uuid.uuid4().hex
        store.db.execute('INSERT INTO identity_conflict_reviews VALUES(?,?,?,?,?,?)',
            (review,conflict_id,disposition,dump(sorted(set(evidence_ids))),reason,store._now()))
        return review

def canonical(store, company_id, *, _check_corrections=True):
    seen=set()
    while True:
        if company_id in seen:raise EngineError('corporate alias cycle')
        seen.add(company_id)
        row=store.db.execute('SELECT canonical_id FROM company_aliases WHERE alias_id=?',(company_id,)).fetchone()
        if not row:
            if _check_corrections:
                for member in _component(store,company_id):effective_identifiers(store,dict(member))
            return company_id
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
            for field,value in effective_identifiers(store,member).items():
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
    overlays=defaultdict(list)
    for row in store.db.execute('SELECT * FROM identifier_overrides WHERE revoked_at IS NULL'):overlays[row['company_id']].append(row)
    known={};drifts=[]
    for cid,company in companies.items():
        try:known[cid]=effective_identifiers(store,company,overrides=overlays[cid])
        except EngineError:known[cid]={};drifts.append(cid)
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
        try:root=min(canonical(store,cid) for cid in ids)
        except EngineError:rejections+=1;continue
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
            'unidentified_source_records':unresolved,'identifier_override_drift_records':drifts,'national_unique_companies':'unknown',
            'note':'components are resolved source records, not a census of all Korean legal entities'}
