"""Coverage-aware ordering of existing discovery tasks; no population quota.

Only proven identity components may lend homepages or group labels. Unknown
homepages remain host work, rather than consuming a native network checkpoint.
"""
from collections import defaultdict
from .model import EngineError
from .identity import identifier_override_drifts


def discovery_frontier(store, run_id):
    store.row('runs', run_id)
    at = store._now()
    companies = {r['id']: dict(r) for r in store.db.execute(
        'SELECT id,name,registry,industry,group_name,homepage FROM companies')}
    parents = dict(store.db.execute('SELECT alias_id,canonical_id FROM company_aliases'))
    roots = {}

    def root(cid):
        path = []
        while cid in parents:
            if cid in path:
                raise EngineError('corporate alias cycle')
            if cid in roots:
                cid = roots[cid]
                break
            path.append(cid)
            cid = parents[cid]
        for item in path:
            roots[item] = cid
        return cid

    members = defaultdict(list)
    for cid, company in companies.items():
        members[root(cid)].append(company)
    registry_order = {'mme': 0, 'ftc': 0, 'krx': 1, 'dart-web': 2}
    homepage_order = {'krx':0,'dart-web':1}
    component_data = {}
    drift_roots={root(r['company_id']) for r in identifier_override_drifts(store)}
    for cid, family in members.items():
        homes = sorted((c for c in family if c['homepage'] and cid not in drift_roots),
            key=lambda c: (homepage_order.get(c['registry'], 4), c['id']))
        groups = {c['group_name'] for c in family if c['group_name']}
        industries={c['industry'] for c in family if c['industry']}
        component_data[cid] = (homes, next(iter(groups)) if len(groups) == 1 else None,
            next(iter(industries)) if len(industries)==1 else None)
    tasks = [dict(r) for r in store.db.execute(
        "SELECT * FROM tasks WHERE run_id=? AND kind='source_discovery'", (run_id,))]
    attempted = defaultdict(set)
    ready = []
    unknown = 0
    aliases_retained = 0
    drift_tasks=0
    candidates = {}
    attempted_tasks=defaultdict(set)
    for task in tasks:
        if task['attempts'] or task['status'] in ('done','blocked','deferred'):
            attempted_tasks[root(task['company_id'])].add(task['id'])
    already_attempted=0
    for task in tasks:
        company = companies[task['company_id']]
        identity = root(company['id'])
        homes, inherited_group, inherited_industry = component_data[identity]
        group = company['group_name'] or inherited_group
        key = ('group', group) if group else ('industry', company['industry'] or inherited_industry or '[unclassified]')
        # Count real attempts, including blocked pages, rather than treating an
        # entire group as checked because a global ATS was seen.
        if task['attempts'] or task['status'] in ('done', 'blocked', 'deferred'):
            attempted[key].add(identity)
        due = ((task['status'] == 'queued' and task['not_before'] <= at) or
               (task['status'] == 'leased' and task['lease_until'] and task['lease_until'] <= at))
        if not due:
            continue
        if attempted_tasks[identity] and task['id'] not in attempted_tasks[identity]:
            # Another registry alias must not restart this same homepage scan.
            # Explicit retries of the attempted task and a new run still work.
            already_attempted+=1
            continue
        if not homes:
            if identity in drift_roots:drift_tasks+=1
            else:unknown += 1
            continue
        donor = homes[0]
        item = {'task_id': task['id'], 'company_id': company['id'],
            'identity_component': identity, 'company': company['name'],
            'registry': company['registry'], 'scope_key': list(key),
            'homepage': donor['homepage'], 'homepage_record_id': donor['id'],
            'created_at': task['created_at'], 'priority': task['priority']}
        # Multiple source IDs for one proven component do not consume the same
        # execution slice. Their tasks and original ages remain intact.
        rank = (registry_order.get(company['registry'], 4), task['created_at'], task['id'])
        if identity in candidates:
            aliases_retained += 1
        if identity not in candidates or rank < candidates[identity][0]:
            candidates[identity] = (rank, item)
    buckets = defaultdict(list)
    for _, item in candidates.values():
        buckets[tuple(item['scope_key'])].append(item)
    for key, items in buckets.items():
        items.sort(key=lambda c: (registry_order.get(c['registry'], 4), -c['priority'], c['created_at'], c['task_id']))
        for offset, item in enumerate(items):
            item['scope_attempt_rank'] = len(attempted[key]) + offset
            ready.append(item)
    ready.sort(key=lambda c: (c['scope_attempt_rank'],
        registry_order.get(c['registry'], 4), c['created_at'], c['task_id']))
    return {'candidates': ready, 'ready_proven_components': len(ready),
        'unknown_homepage_tasks_retained': unknown,
        'duplicate_component_tasks_retained': aliases_retained,
        'already_attempted_component_tasks_retained':already_attempted,
        'identifier_drift_tasks_retained':drift_tasks,
        'coverage_unit': 'source records and proven identity components; not unique Korean firms',
        'national_coverage': 'unknown'}
