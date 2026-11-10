from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import sqlite3
import uuid
from typing import Any, Iterator

from .model import (EngineError, Job, LeaseLost, Page, canonical_time, digest, dump,
                    now, public_url, required, stable_id, timestamp)

SCHEMA_VERSION = 2
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS registry_snapshots(
 id TEXT PRIMARY KEY, registry TEXT NOT NULL, source_url TEXT NOT NULL,
 observed_at TEXT NOT NULL, raw_sha256 TEXT NOT NULL, scope TEXT NOT NULL,
 completeness TEXT NOT NULL, provenance TEXT NOT NULL, rows_seen INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS companies(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, registry TEXT NOT NULL, external_id TEXT NOT NULL,
 group_name TEXT, size_class TEXT, industry TEXT, homepage TEXT,
 facts_json TEXT NOT NULL DEFAULT '{}', first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
 UNIQUE(registry,external_id));
CREATE TABLE IF NOT EXISTS company_memberships(
 snapshot_id TEXT NOT NULL REFERENCES registry_snapshots(id),
 company_id TEXT NOT NULL REFERENCES companies(id), PRIMARY KEY(snapshot_id,company_id));
CREATE TABLE IF NOT EXISTS company_aliases(
 alias_id TEXT PRIMARY KEY REFERENCES companies(id), canonical_id TEXT NOT NULL REFERENCES companies(id),
 reason TEXT NOT NULL, evidence_ref TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(
 id TEXT PRIMARY KEY, company_id TEXT REFERENCES companies(id), kind TEXT NOT NULL,
 url TEXT NOT NULL, policy TEXT NOT NULL, evidence_ref TEXT NOT NULL,
 settings_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 last_complete_at TEXT, last_attempt_at TEXT, first_seen TEXT NOT NULL,
 UNIQUE(kind,url,company_id));
CREATE TABLE IF NOT EXISTS profiles(
 id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 1,
 facts_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id),
 profile_revision INTEGER NOT NULL, created_at TEXT NOT NULL, finished_at TEXT,
 status TEXT NOT NULL, scope TEXT NOT NULL, scope_note TEXT NOT NULL, stop_reason TEXT,
 engine_version TEXT NOT NULL, parent_run_id TEXT REFERENCES runs(id));
CREATE TABLE IF NOT EXISTS run_companies(
 run_id TEXT NOT NULL REFERENCES runs(id), company_id TEXT NOT NULL REFERENCES companies(id),
 PRIMARY KEY(run_id,company_id));
CREATE TABLE IF NOT EXISTS run_sources(
 run_id TEXT NOT NULL REFERENCES runs(id), source_id TEXT NOT NULL REFERENCES sources(id),
 completed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(run_id,source_id));
CREATE TABLE IF NOT EXISTS tasks(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), kind TEXT NOT NULL,
 key TEXT NOT NULL, source_id TEXT REFERENCES sources(id), company_id TEXT REFERENCES companies(id),
 payload_json TEXT NOT NULL, cursor TEXT, status TEXT NOT NULL,
 priority INTEGER NOT NULL, created_at TEXT NOT NULL, not_before TEXT NOT NULL,
 lease_token TEXT, lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0,
 error_code TEXT, error_note TEXT, finished_at TEXT,
 UNIQUE(run_id,kind,key));
CREATE INDEX IF NOT EXISTS tasks_ready ON tasks(status,not_before,priority,created_at);
CREATE TABLE IF NOT EXISTS observations(
 id TEXT PRIMARY KEY, source_id TEXT REFERENCES sources(id), task_id TEXT REFERENCES tasks(id),
 source_url TEXT NOT NULL, observed_at TEXT NOT NULL, origin TEXT NOT NULL,
 tool_ref TEXT, sha256 TEXT NOT NULL, media_type TEXT NOT NULL,
 payload BLOB NOT NULL, UNIQUE(source_id,sha256,observed_at));
CREATE TABLE IF NOT EXISTS pages(
 task_id TEXT NOT NULL REFERENCES tasks(id), cursor_key TEXT NOT NULL,
 observation_id TEXT NOT NULL REFERENCES observations(id), next_cursor TEXT,
 terminal INTEGER NOT NULL, expected_total INTEGER, item_count INTEGER NOT NULL,
 PRIMARY KEY(task_id,cursor_key));
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
 external_id TEXT NOT NULL, round_key TEXT NOT NULL, company_id TEXT REFERENCES companies(id),
 employer TEXT NOT NULL, title TEXT NOT NULL, job_url TEXT NOT NULL, apply_url TEXT,
 content_json TEXT NOT NULL, content_hash TEXT NOT NULL, recruiting_status TEXT NOT NULL,
 detail_verified INTEGER NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
 latest_observation_id TEXT NOT NULL REFERENCES observations(id),
 UNIQUE(source_id,external_id,round_key));
CREATE TABLE IF NOT EXISTS job_versions(
 job_id TEXT NOT NULL REFERENCES jobs(id), content_hash TEXT NOT NULL,
 observation_id TEXT NOT NULL REFERENCES observations(id), observed_at TEXT NOT NULL,
 content_json TEXT NOT NULL, PRIMARY KEY(job_id,content_hash));
CREATE TABLE IF NOT EXISTS job_sightings(
 run_id TEXT NOT NULL REFERENCES runs(id), job_id TEXT NOT NULL REFERENCES jobs(id),
 task_id TEXT NOT NULL REFERENCES tasks(id), observation_id TEXT NOT NULL REFERENCES observations(id),
 PRIMARY KEY(run_id,job_id,task_id));
CREATE TABLE IF NOT EXISTS run_jobs(
 run_id TEXT NOT NULL REFERENCES runs(id), job_id TEXT NOT NULL REFERENCES jobs(id),
 carried INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(run_id,job_id));
CREATE TABLE IF NOT EXISTS assessments(
 id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id),
 profile_revision INTEGER NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id),
 content_hash TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
 risk TEXT NOT NULL, unknowns_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS assessments_latest ON assessments(profile_id,job_id,created_at);
CREATE TABLE IF NOT EXISTS assessment_reporting(
 assessment_id TEXT PRIMARY KEY REFERENCES assessments(id), report_tier TEXT NOT NULL
 CHECK(report_tier IN ('actionable','source_gap','future_pool')));
CREATE TABLE IF NOT EXISTS user_events(
 id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id),
 event_key TEXT NOT NULL, scope_type TEXT NOT NULL, target_id TEXT NOT NULL,
 kind TEXT NOT NULL, value TEXT NOT NULL, evidence_ref TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(profile_id,event_key));
CREATE TABLE IF NOT EXISTS audit_checks(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), kind TEXT NOT NULL,
 method TEXT NOT NULL, evidence_json TEXT NOT NULL, discovered_json TEXT NOT NULL,
 followed_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS legacy_records(
 id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id),
 external_key TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 resolution_json TEXT, UNIQUE(profile_id,external_key));
CREATE TABLE IF NOT EXISTS reports(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), profile_id TEXT NOT NULL,
 created_at TEXT NOT NULL, body TEXT NOT NULL, mapping_json TEXT NOT NULL,
 audit_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS change_log(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL, entity_id TEXT NOT NULL,
 action TEXT NOT NULL, at TEXT NOT NULL, detail_json TEXT NOT NULL);
"""
SCHEMA += """
CREATE INDEX IF NOT EXISTS sources_company ON sources(company_id,enabled);
CREATE INDEX IF NOT EXISTS tasks_company_kind ON tasks(company_id,kind,status,created_at);
CREATE INDEX IF NOT EXISTS tasks_gap_identity ON tasks(kind,key,status,created_at,run_id);
CREATE INDEX IF NOT EXISTS tasks_source_gap ON tasks(source_id,kind,status,created_at);
CREATE INDEX IF NOT EXISTS changes_entity_time ON change_log(entity,entity_id,at);
CREATE INDEX IF NOT EXISTS jobs_source ON jobs(source_id);
CREATE INDEX IF NOT EXISTS sightings_task ON job_sightings(task_id,job_id);
CREATE INDEX IF NOT EXISTS events_profile_target ON user_events(profile_id,target_id,kind,created_at);
CREATE INDEX IF NOT EXISTS aliases_canonical ON company_aliases(canonical_id);
CREATE TABLE IF NOT EXISTS registry_syncs(
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, year INTEGER NOT NULL, next_page INTEGER NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL, snapshot_id TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS registry_acquisitions(
 sync_id TEXT NOT NULL REFERENCES registry_syncs(id), page INTEGER NOT NULL,
 source_url TEXT NOT NULL, observed_at TEXT NOT NULL, sha256 TEXT NOT NULL, fingerprint TEXT NOT NULL,
 expected_total INTEGER, rows_json TEXT NOT NULL, payload BLOB NOT NULL, media_type TEXT NOT NULL,
 origin TEXT NOT NULL, PRIMARY KEY(sync_id,page));
CREATE TABLE IF NOT EXISTS identity_events(
 id TEXT PRIMARY KEY, alias_id TEXT NOT NULL, canonical_id TEXT NOT NULL,
 action TEXT NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS identity_conflicts(
 id TEXT PRIMARY KEY, identifier TEXT NOT NULL, companies_json TEXT NOT NULL, reason TEXT NOT NULL,
 created_at TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS job_links(
 id TEXT PRIMARY KEY, left_id TEXT NOT NULL REFERENCES jobs(id), right_id TEXT NOT NULL REFERENCES jobs(id),
 relation TEXT NOT NULL, evidence_ref TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(left_id,right_id,relation));
CREATE TABLE IF NOT EXISTS host_sessions(
 id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id), run_id TEXT NOT NULL REFERENCES runs(id),
 request TEXT NOT NULL, host TEXT NOT NULL, created_at TEXT NOT NULL, restored_json TEXT NOT NULL);
"""

class Store:
    """Single-machine, multi-profile SQLite store. Not a remotely exposed service.

    Collection facts are shared within this file. Personal assessments/decisions are
    profile scoped. Use separate private files for people who must not share a catalog.
    """
    def __init__(self, path: str | Path, *, clock=now):
        self.path = Path(path) if str(path) != ":memory:" else None
        self.clock = clock
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.is_symlink():
                raise EngineError("database symlinks not supported")
            # Privacy also depends on filesystem/OS account permissions; no encryption claim.
            if not self.path.exists():
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
        self.db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        old = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if old and int(old[0]) not in {1, SCHEMA_VERSION}:
            self.db.close()
            raise EngineError("database schema mismatch; explicit migration/backup required")
        if old and int(old[0]) == 1 and self.path:
            backup = self.path.with_name(self.path.name + '.schema1-' + uuid.uuid4().hex + '.bak.sqlite')
            target=sqlite3.connect(str(backup))
            try:
                self.db.backup(target)
            finally:
                target.close()
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT INTO meta VALUES('schema_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(SCHEMA_VERSION),))

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _now(self) -> str:
        return canonical_time(self.clock())

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def _log(self, entity: str, identity: str, action: str, detail: Any) -> None:
        self.db.execute("INSERT INTO change_log(entity,entity_id,action,at,detail_json) VALUES(?,?,?,?,?)",
                        (entity, identity, action, self._now(), dump(detail)))

    def row(self, table: str, identity: str) -> dict[str, Any]:
        if table not in {"companies", "sources", "profiles", "runs", "tasks", "observations", "jobs", "reports"}:
            raise EngineError("unsupported lookup")
        result = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (identity,)).fetchone()
        if result is None:
            raise EngineError(f"unknown {table} id: {identity}")
        return dict(result)

    def import_legacy(self, profile_id: str, records: list[dict]) -> int:
        self.row("profiles",profile_id)
        with self.transaction():
            for record in records:
                key = required(record.get("key"),"legacy identity")
                required(record.get("provenance"),"legacy provenance")
                required(record.get("employer"),"legacy employer")
                required(record.get("role"),"legacy role")
                lid = stable_id(profile_id,key)
                old = self.db.execute("SELECT payload_json FROM legacy_records WHERE id=?",(lid,)).fetchone()
                if old and old[0] != dump(record):
                    raise EngineError("legacy import conflict; preserve both observations for review")
                self.db.execute("INSERT OR IGNORE INTO legacy_records VALUES(?,?,?,?,?,NULL)",
                    (lid,profile_id,key,dump(record),self._now()))
            self._log("profile",profile_id,"legacy_import",{"records":len(records)})
        return len(records)

    def set_profile(self, profile_id: str, facts: dict[str, Any]) -> int:
        required(profile_id, "profile id")
        encoded = dump(facts)
        with self.transaction():
            old = self.db.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
            if old and old["facts_json"] == encoded:
                return old["revision"]
            rev = old["revision"] + 1 if old else 1
            self.db.execute("INSERT INTO profiles VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,facts_json=excluded.facts_json,updated_at=excluded.updated_at",
                            (profile_id, rev, encoded, self._now()))
            self._log("profile", profile_id, "revision", {"revision": rev})
        return rev

    def import_companies(self, registry: str, rows: list[dict[str, Any]], *, source_url: str,
                         raw_sha256: str, scope: str, completeness: str = "partial",
                         provenance: str = "host_import", observed_at: str | None = None) -> dict[str, Any]:
        """Preserve source identities; names alone never auto-merge legal entities."""
        required(registry, "registry")
        public_url(source_url)
        required(scope, "registry scope")
        if completeness not in {"complete_source_snapshot", "partial", "unknown"}:
            raise EngineError("bad registry completeness")
        if provenance not in {"native_registry", "host_import", "fixture"}:
            raise EngineError("bad registry provenance")
        if not rows:
            raise EngineError("empty registry import is not a completed census")
        observed_at = canonical_time(observed_at or self._now())
        sid = stable_id(registry, source_url, raw_sha256, observed_at)
        seen = set()
        for r in rows:
            key = required(r.get("external_id"), "company external_id")
            required(r.get("name"), "company name")
            if key in seen:
                raise EngineError("duplicate company ID in registry snapshot")
            seen.add(key)
            if r.get("homepage"):
                public_url(r["homepage"])
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO registry_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                (sid, registry, source_url, observed_at, raw_sha256, scope, completeness, provenance, len(rows)))
            for r in rows:
                cid = stable_id(registry, r["external_id"])
                facts = dump(r.get("facts", {}))
                self.db.execute("""INSERT INTO companies VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                    group_name=COALESCE(excluded.group_name,companies.group_name),
                    size_class=COALESCE(excluded.size_class,companies.size_class),
                    industry=COALESCE(excluded.industry,companies.industry),
                    homepage=COALESCE(excluded.homepage,companies.homepage),
                    facts_json=excluded.facts_json,last_seen=excluded.last_seen""",
                    (cid, r["name"], registry, r["external_id"], r.get("group_name"),
                     r.get("size_class"), r.get("industry"), r.get("homepage"), facts, observed_at, observed_at))
                self.db.execute("INSERT OR IGNORE INTO company_memberships VALUES(?,?)", (sid, cid))
            self._log("registry", sid, "import", {"rows": len(rows), "provenance": provenance})
        return {"snapshot_id": sid, "rows": len(rows), "scope": scope,
                "completeness": completeness, "national_completeness": "unknown"}

    def add_source(self, kind: str, url: str, *, company_id: str | None,
                   evidence_ref: str, policy: str = "host_only", settings: dict | None = None) -> str:
        public_url(url)
        required(evidence_ref, "source association evidence")
        if policy not in {"public_api", "public_read_form", "robots", "host_only", "unreviewed"}:
            raise EngineError("invalid source access policy")
        if company_id:
            self.row("companies", company_id)
        source_id = stable_id(kind, url, company_id or "aggregator")
        with self.transaction():
            self.db.execute("""INSERT INTO sources(id,company_id,kind,url,policy,evidence_ref,settings_json,first_seen)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                policy=excluded.policy,evidence_ref=excluded.evidence_ref,settings_json=excluded.settings_json""",
                (source_id, company_id, required(kind, "adapter kind"), url, policy,
                 evidence_ref, dump(settings or {}), self._now()))
            self._log("source", source_id, "registered", {"kind": kind, "policy": policy})
        return source_id

    def _enqueue(self, run_id: str, kind: str, key: str, *, source_id=None,
                 company_id=None, payload=None, priority=0, first_created=None) -> str:
        tid = stable_id(run_id, kind, key)
        at = self._now()
        if first_created is None:
            gap_column,gap_value=('source_id',source_id) if kind=='inventory' and source_id else ('key',key)
            first_created=self.db.execute('''SELECT MIN(t.created_at) FROM tasks t JOIN runs r ON r.id=t.run_id
              WHERE t.kind=? AND t.'''+gap_column+'''=?
              AND t.status NOT IN ('done','superseded')
              AND r.profile_id=(SELECT profile_id FROM runs WHERE id=?)''',(kind,gap_value,run_id)).fetchone()[0]
        self.db.execute("""INSERT OR IGNORE INTO tasks
            (id,run_id,kind,key,source_id,company_id,payload_json,status,priority,created_at,not_before)
            VALUES(?,?,?,?,?,?,?,'queued',?,?,?)""",
            (tid, run_id, kind, key, source_id, company_id, dump(payload or {}),
             priority, first_created or at, at))
        return tid

    def plan_run(self, profile_id: str, *, scope: str = "broad", scope_note: str,
                 company_ids: list[str] | None = None, parent_run_id: str | None = None) -> str:
        from . import __version__
        profile = self.row("profiles", profile_id)
        required(scope_note, "scope description")
        if scope not in {"broad", "targeted"}:
            raise EngineError("unknown scope")
        if parent_run_id:
            parent = self.row("runs", parent_run_id)
            if parent["profile_id"] != profile_id:
                raise EngineError("cannot inherit another profile")
        if company_ids is None:
            company_ids = [r[0] for r in self.db.execute("SELECT id FROM companies ORDER BY id")]
        company_ids = sorted(set(company_ids))
        if not company_ids:
            raise EngineError("no company universe loaded; do not pretend nationwide coverage")
        for cid in company_ids:
            self.row("companies", cid)
        rid = uuid.uuid4().hex
        with self.transaction():
            self.db.execute("INSERT INTO runs VALUES(?,?,?,?,NULL,'running',?,?,NULL,?,?)",
                (rid, profile_id, profile["revision"], self._now(), scope, scope_note, __version__, parent_run_id))
            for cid in company_ids:
                self.db.execute("INSERT INTO run_companies VALUES(?,?)", (rid, cid))
                sources = self.db.execute("SELECT id FROM sources WHERE company_id=? AND enabled=1", (cid,)).fetchall()
                if not sources:
                    company = self.row('companies',cid)
                    facts = json.loads(company['facts_json'])
                    priority = 10 if company['group_name'] or facts.get('certificate_records') else 0
                    self._enqueue(rid, "source_discovery", cid, company_id=cid,priority=priority)
                for src in sources:
                    self.db.execute("INSERT OR IGNORE INTO run_sources VALUES(?,?,0)", (rid, src[0]))
                    self._enqueue(rid, "inventory", src[0], source_id=src[0], company_id=cid)
            # Registered public aggregators complement rather than replace company inventories.
            for src in self.db.execute("SELECT id FROM sources WHERE company_id IS NULL AND enabled=1").fetchall():
                self.db.execute("INSERT INTO run_sources VALUES(?,?,0)", (rid, src[0]))
                self._enqueue(rid, "inventory", src[0], source_id=src[0])
            # Broad runs carry the full previous pool. Targeted requests respect their declared scope.
            self.db.execute("""INSERT OR IGNORE INTO run_jobs(run_id,job_id,carried)
                SELECT ?,rj.job_id,1 FROM run_jobs rj JOIN runs r ON r.id=rj.run_id
                JOIN jobs j ON j.id=rj.job_id WHERE r.profile_id=? AND
                (?='broad' OR j.company_id IN (SELECT company_id FROM run_companies WHERE run_id=?))""",
                (rid, profile_id, scope, rid))
            if scope == "broad":
                for legacy in self.db.execute("SELECT id,created_at FROM legacy_records WHERE profile_id=? AND resolution_json IS NULL", (profile_id,)).fetchall():
                    self._enqueue(rid, "legacy_recheck", legacy["id"], payload={"legacy_id":legacy["id"]},
                                  priority=20, first_created=legacy["created_at"])
            self._carry_unresolved_work(rid)
            self._log("run", rid, "plan_frozen", {"companies": len(company_ids), "company_ids": company_ids, "scope": scope})
        return rid

    def _carry_unresolved_work(self, run_id: str) -> int:
        """Carry outstanding detail/image/host work; caller owns the transaction.

        Inventory scans and company/legacy planning are rebuilt by plan_run. Other
        gaps must survive even if an intervening older engine run omitted them.
        The most recent outcome wins, including a previous worker finishing after
        the next run was planned, so a completed review is not revived.
        Leases belong to the old worker; payload, cursor and backoff still persist.
        """
        run = self.row('runs', run_id)
        rows = self.db.execute('''SELECT * FROM (
            SELECT t.*,ROW_NUMBER() OVER (
                PARTITION BY t.kind,t.key ORDER BY
                    MAX(r.created_at,COALESCE(t.finished_at,r.created_at),COALESCE(
                        (SELECT MAX(c.at) FROM change_log c WHERE c.entity='task' AND c.entity_id=t.id),
                        r.created_at)) DESC,
                    r.rowid DESC,t.rowid DESC
            ) AS occurrence FROM tasks t JOIN runs r ON r.id=t.run_id
            WHERE r.profile_id=? AND t.run_id!=?
            AND t.kind NOT IN ('inventory','source_discovery','legacy_recheck')
        ) WHERE occurrence=1 AND status NOT IN ('done','superseded')''',
            (run['profile_id'],run_id)).fetchall()
        carried = 0
        for task in rows:
            if task['company_id'] and not self.db.execute(
                    'SELECT 1 FROM run_companies WHERE run_id=? AND company_id=?',
                    (run_id,task['company_id'])).fetchone():
                continue
            if task['source_id'] and not self.db.execute(
                    'SELECT 1 FROM run_sources WHERE run_id=? AND source_id=?',
                    (run_id,task['source_id'])).fetchone():
                continue
            payload=json.loads(task['payload_json'])
            if run['scope']=='targeted' and not task['company_id'] and not payload.get('job_id'):
                source_company=self.row('sources',task['source_id'])['company_id'] if task['source_id'] else None
                if not source_company:
                    continue
            if payload.get('job_id') and not self.db.execute(
                    'SELECT 1 FROM run_jobs WHERE run_id=? AND job_id=?',
                    (run_id,payload['job_id'])).fetchone():
                continue
            if self.db.execute('SELECT 1 FROM tasks WHERE run_id=? AND kind=? AND key=?',
                    (run_id,task['kind'],task['key'])).fetchone():
                continue
            tid=self._enqueue(run_id,task['kind'],task['key'],source_id=task['source_id'],
                company_id=task['company_id'],payload=payload,priority=task['priority'],
                first_created=task['created_at'])
            self.db.execute('''UPDATE tasks SET cursor=?,status=?,not_before=?,attempts=?,
                error_code=?,error_note=?,finished_at=? WHERE id=?''',
                (task['cursor'],'queued' if task['status']=='leased' else task['status'],
                 task['not_before'],task['attempts'],task['error_code'],task['error_note'],
                 task['finished_at'],tid))
            self.db.execute('''INSERT INTO pages SELECT ?,cursor_key,observation_id,next_cursor,
                terminal,expected_total,item_count FROM pages WHERE task_id=?''',(tid,task['id']))
            carried += 1
        self._log('run',run_id,'unresolved_work_carried',{'tasks':carried})
        return carried

    def attach_source(self, run_id: str, source_id: str) -> None:
        run, src = self.row("runs", run_id), self.row("sources", source_id)
        if run["status"] != "running":
            raise EngineError("run is not accepting new work")
        with self.transaction():
            if src["company_id"]:
                self.db.execute("INSERT OR IGNORE INTO run_companies VALUES(?,?)", (run_id, src["company_id"]))
            self.db.execute("INSERT OR IGNORE INTO run_sources VALUES(?,?,0)", (run_id, source_id))
            self._enqueue(run_id, "inventory", source_id, source_id=source_id, company_id=src["company_id"])
            self._log("run", run_id, "scope_expanded", {"source": source_id})

    def claim(self, run_id: str, *, kinds: tuple[str, ...] = ("inventory",), lease_seconds: int = 120,task_id: str | None=None) -> dict | None:
        if lease_seconds <= 0 or not kinds:
            raise EngineError("positive lease and task kinds required")
        run = self.row("runs", run_id)
        if run["status"] != "running":
            raise EngineError("run is not running")
        at = self._now()
        until = (timestamp(at) + timedelta(seconds=lease_seconds)).isoformat(timespec="microseconds")
        placeholders = ",".join("?" for _ in kinds)
        with self.transaction():
            # Aging ensures ordinary work eventually competes with fresh urgent work.
            while True:
                task = self.db.execute(f"""SELECT * FROM tasks WHERE run_id=? AND kind IN ({placeholders})
                    AND ((status='queued' AND not_before<=?) OR (status='leased' AND lease_until<=?))
                    AND (? IS NULL OR id=?)
                    ORDER BY priority + (julianday(?) - julianday(created_at))*24 DESC,created_at,id LIMIT 1""",
                    (run_id, *kinds, at, at, task_id, task_id, at)).fetchone()
                if task is None:
                    return None
                if task['kind'] not in {'inventory','source_discovery','legacy_recheck'}:
                    # An older still-valid worker may finish/fail after this run was
                    # planned. Honor that outcome before leasing a queued copy.
                    latest=self.db.execute('''SELECT t.* FROM tasks t JOIN runs r ON r.id=t.run_id
                        WHERE r.profile_id=? AND t.kind=? AND t.key=? ORDER BY
                        MAX(r.created_at,COALESCE(t.finished_at,r.created_at),COALESCE(
                            (SELECT MAX(c.at) FROM change_log c WHERE c.entity='task' AND c.entity_id=t.id),
                            r.created_at)) DESC,r.rowid DESC,t.rowid DESC LIMIT 1''',
                        (run['profile_id'],task['kind'],task['key'])).fetchone()
                    if latest['id']!=task['id'] and (latest['status'] in {'done','superseded','blocked','deferred'}
                            or (latest['status']=='queued' and latest['not_before']>at)):
                        self.db.execute('''UPDATE tasks SET status=?,not_before=?,error_code=?,error_note=?,
                            finished_at=?,payload_json=?,cursor=?,attempts=MAX(attempts,?),priority=?,
                            created_at=MIN(created_at,?),lease_token=NULL,lease_until=NULL WHERE id=?''',
                            (latest['status'],latest['not_before'],latest['error_code'],latest['error_note'],
                             latest['finished_at'],latest['payload_json'],latest['cursor'],latest['attempts'],
                             latest['priority'],latest['created_at'],task['id']))
                        self._log('task',task['id'],'outcome_synchronized',{'from_task':latest['id']})
                        continue
                break
            token = uuid.uuid4().hex
            self.db.execute("UPDATE tasks SET status='leased',lease_token=?,lease_until=?,attempts=attempts+1 WHERE id=?",
                            (token, until, task["id"]))
            result = self.row("tasks", task["id"])
        return result

    def _check_lease(self, task_id: str, token: str) -> dict:
        task = self.row("tasks", task_id)
        if task["status"] != "leased" or task["lease_token"] != token or task["lease_until"] <= self._now():
            raise LeaseLost("stale/expired lease; this worker cannot commit")
        return task

    def fail_task(self, task_id: str, token: str, *, code: str, note: str,
                  retry_after: int | None = None) -> None:
        with self.transaction():
            self._check_lease(task_id, token)
            state = "queued" if retry_after is not None else "blocked"
            next_at = (timestamp(self._now()) + timedelta(seconds=max(0, retry_after or 0))).isoformat(timespec="microseconds")
            self.db.execute("""UPDATE tasks SET status=?,not_before=?,error_code=?,error_note=?,
                lease_token=NULL,lease_until=NULL WHERE id=?""", (state, next_at, code, note, task_id))
            self._log("task", task_id, state, {"code": code})

    def retry_blocked(self, task_id: str, *, reason: str) -> str:
        required(reason, "retry reason")
        with self.transaction():
            task = self.row("tasks", task_id)
            if task["status"] not in {"blocked", "deferred"}:
                raise EngineError("only blocked/deferred work can be retried")
            committed = self.db.execute("SELECT 1 FROM pages WHERE task_id=?", (task_id,)).fetchone()
            if task["kind"] == "inventory" and committed:
                # Start a new scan rather than mixing two changing inventory snapshots.
                self.db.execute("UPDATE tasks SET status='superseded' WHERE id=?", (task_id,))
                new_id = self._enqueue(task["run_id"], "inventory", task["key"]+":retry:"+uuid.uuid4().hex,
                    source_id=task["source_id"], company_id=task["company_id"],
                    priority=task["priority"], first_created=task["created_at"])
                self.db.execute("UPDATE run_sources SET completed=0 WHERE run_id=? AND source_id=?", (task["run_id"],task["source_id"]))
            else:
                new_id = task_id
                self.db.execute("UPDATE tasks SET status='queued',not_before=? WHERE id=?", (self._now(), task_id))
            self._log("task", task_id, "retry", {"reason": reason, "active_task": new_id})
        return new_id

    def _observe(self, task: dict, source_url: str, payload: bytes, *, media_type: str,
                 origin: str, tool_ref: str | None, observed_at: str | None) -> str:
        if origin=='private_record':
            legacy_id=json.loads(task['payload_json']).get('legacy_id')
            owner=self.db.execute('SELECT profile_id FROM legacy_records WHERE id=?',(legacy_id,)).fetchone()
            if task['kind']!='legacy_recheck' or source_url!='urn:job-research:legacy:'+str(legacy_id) or not owner or owner[0]!=self.row('runs',task['run_id'])['profile_id']:
                raise EngineError('private evidence must reference this profile legacy record')
        else:public_url(source_url)
        if origin not in {"native_http", "host_export", "fixture", "private_record"}:
            raise EngineError("invalid evidence origin")
        if origin in {"host_export","private_record"} and not tool_ref:
            raise EngineError("host export requires an actual observation reference")
        at = canonical_time(observed_at or self._now())
        if timestamp(at) > timestamp(self._now()) + timedelta(minutes=5):
            raise EngineError("observation is in the future")
        oid = stable_id(task["source_id"] or task["id"], source_url, digest(payload), at)
        self.db.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)",
            (oid, task["source_id"], task["id"], source_url, at, origin, tool_ref, digest(payload), media_type, payload))
        return oid

    def _catalog_employer(self,source: dict,employer: str,run_id: str,observation_id: str) -> str:
        if source['company_id']:return source['company_id']
        # This is an unresolved source employer, not an asserted legal entity or size class.
        registry='discovered-employers';external=stable_id(source['id'],employer);cid=stable_id(registry,external)
        at=self._now();obs=self.row('observations',observation_id)
        facts={'identity_unresolved':True,'identity_kind':'source_employer_display',
               'discovery_source':source['id'],'observation_id':observation_id}
        self.db.execute('''INSERT INTO companies VALUES(?,?,?,?,NULL,NULL,NULL,NULL,?,?,?)
            ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen''',(cid,employer,registry,external,dump(facts),at,at))
        snapshot=stable_id(registry,source['id'],observation_id)
        self.db.execute('INSERT OR IGNORE INTO registry_snapshots VALUES(?,?,?,?,?,?,?,?,?)',
            (snapshot,registry,obs['source_url'],obs['observed_at'],obs['sha256'],'Observed employer labels; legal identity and company size unresolved','partial',
             'fixture' if obs['origin']=='fixture' else 'host_import',1))
        self.db.execute('INSERT OR IGNORE INTO company_memberships VALUES(?,?)',(snapshot,cid))
        self.db.execute('UPDATE registry_snapshots SET rows_seen=(SELECT COUNT(*) FROM company_memberships WHERE snapshot_id=?) WHERE id=?',(snapshot,snapshot))
        self.db.execute('INSERT OR IGNORE INTO run_companies VALUES(?,?)',(run_id,cid))
        self._enqueue(run_id,'source_discovery',cid,company_id=cid,payload={'identity_review_required':True})
        return cid

    def expand_employer_frontier(self,run_id: str) -> int:
        self.row('runs',run_id);updated=0
        with self.transaction():
            for job in self.db.execute('''SELECT j.* FROM jobs j JOIN run_jobs rj ON rj.job_id=j.id
                WHERE rj.run_id=? AND j.company_id IS NULL''',(run_id,)).fetchall():
                source=self.row('sources',job['source_id'])
                cid=self._catalog_employer(source,job['employer'],run_id,job['latest_observation_id'])
                self.db.execute('UPDATE jobs SET company_id=? WHERE id=?',(cid,job['id']));updated+=1
            self._log('run',run_id,'employer_frontier_expanded',{'job_records_associated':updated})
        return updated

    def commit_page(self, task_id: str, token: str, page: Page, *, source_url: str,
                    payload: bytes, media_type: str = "application/json", origin="native_http",
                    tool_ref=None, observed_at=None) -> dict:
        """Atomic observations + jobs + cursor checkpoint, fenced by a live lease."""
        page.validate()
        with self.transaction():
            task = self._check_lease(task_id, token)
            if task["kind"] != "inventory" or not task["source_id"]:
                raise EngineError("not an inventory task")
            cursor_key = task["cursor"] or "__first__"
            if (page.next_cursor is not None and page.next_cursor == task["cursor"]) or (page.next_cursor is not None and
                self.db.execute("SELECT 1 FROM pages WHERE task_id=? AND cursor_key=?", (task_id,page.next_cursor)).fetchone()):
                raise EngineError("pagination loop detected; no completion")
            oid = self._observe(task, source_url, payload, media_type=media_type,
                origin=origin, tool_ref=tool_ref, observed_at=observed_at)
            at = self.row("observations", oid)["observed_at"]
            source = self.row("sources", task["source_id"])
            inserted = []
            for job in page.jobs:
                company_id=source['company_id'] or self._catalog_employer(source,job.employer,task['run_id'],oid)
                jid = stable_id(source["id"], job.external_id, job.round_key)
                content, encoded = job.content(), dump(job.content())
                chash = digest(encoded)
                old = self.db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
                # Replayed older snapshots cannot overwrite newer facts.
                if old and at < old["last_seen"]:
                    self.db.execute("INSERT OR IGNORE INTO job_sightings VALUES(?,?,?,?)", (task["run_id"],jid,task_id,oid))
                    self.db.execute("INSERT OR IGNORE INTO run_jobs VALUES(?,?,0)", (task["run_id"],jid))
                    continue
                self.db.execute("""INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET company_id=excluded.company_id,employer=excluded.employer,title=excluded.title,
                    job_url=excluded.job_url,apply_url=excluded.apply_url,content_json=excluded.content_json,
                    content_hash=excluded.content_hash,recruiting_status=excluded.recruiting_status,
                    detail_verified=excluded.detail_verified,last_seen=excluded.last_seen,
                    latest_observation_id=excluded.latest_observation_id""",
                    (jid, source["id"],job.external_id,job.round_key,company_id,
                     job.employer,job.title,job.job_url,job.apply_url,encoded,chash,job.status,
                     int(job.detail_verified),at,at,oid))
                # The explicit columns above are intentionally tested against the migration.
                self.db.execute("INSERT OR IGNORE INTO job_versions VALUES(?,?,?,?,?)", (jid,chash,oid,at,encoded))
                self.db.execute("INSERT OR IGNORE INTO job_sightings VALUES(?,?,?,?)", (task["run_id"],jid,task_id,oid))
                self.db.execute("INSERT OR IGNORE INTO run_jobs VALUES(?,?,0)", (task["run_id"],jid))
                if not old or old["content_hash"] != chash:
                    self._log("job", jid, "new" if not old else "changed", {"observation": oid})
                inserted.append(jid)
                if not job.detail_verified:
                    self._enqueue(task['run_id'],'job_detail',jid,source_id=source['id'],company_id=source['company_id'],
                                  payload={'job_id':jid,'url':job.job_url},priority=15)
            self.db.execute("INSERT INTO pages VALUES(?,?,?,?,?,?,?)",
                (task_id,cursor_key,oid,page.next_cursor,int(page.terminal),page.expected_total,len(page.jobs)))
            prior_totals = {r[0] for r in self.db.execute("SELECT expected_total FROM pages WHERE task_id=? AND expected_total IS NOT NULL", (task_id,))}
            observed_count = self.db.execute("SELECT COUNT(DISTINCT job_id) FROM job_sightings WHERE task_id=?", (task_id,)).fetchone()[0]
            reason = None
            if len(prior_totals) > 1:
                reason = "inventory_changed_during_pagination"
            declared_total=next(iter(prior_totals)) if len(prior_totals)==1 else page.expected_total
            if page.terminal and declared_total is not None and observed_count != declared_total:
                reason = "inventory_total_mismatch"
            if page.terminal and not page.inventory_complete:
                reason = "source_inventory_not_exhausted"
            if reason:
                state = "blocked"
                self.db.execute("UPDATE tasks SET status='blocked',error_code=?,error_note=?,lease_token=NULL,lease_until=NULL WHERE id=?",
                    (reason,page.scope_note,task_id))
            elif page.terminal:
                state = "done"
                self.db.execute("UPDATE tasks SET status='done',finished_at=?,lease_token=NULL,lease_until=NULL WHERE id=?", (self._now(),task_id))
                self.db.execute("UPDATE run_sources SET completed=1 WHERE run_id=? AND source_id=?", (task["run_id"],source["id"]))
                self.db.execute("UPDATE sources SET last_complete_at=?,last_attempt_at=? WHERE id=?", (at,at,source["id"]))
                # Absence creates a review task, never closes a job or erases a recommendation.
                missing = self.db.execute("""SELECT id FROM jobs WHERE source_id=? AND recruiting_status!='closed'
                    AND id NOT IN (SELECT job_id FROM job_sightings WHERE task_id=?)""", (source["id"],task_id)).fetchall()
                for m in missing:
                    self._enqueue(task["run_id"], "missing_job_recheck", m[0], source_id=source["id"],
                                  company_id=source["company_id"],payload={"job_id":m[0]},priority=20)
                    self._log("job",m[0],"not_seen_not_closed",{"task_id":task_id})
            else:
                state = "queued"
                self.db.execute("UPDATE tasks SET status='queued',cursor=?,lease_token=NULL,lease_until=NULL WHERE id=?", (page.next_cursor,task_id))
                self.db.execute("UPDATE sources SET last_attempt_at=? WHERE id=?", (at,source["id"]))
            for url in page.discovered_urls:
                self._enqueue(task["run_id"],"detail_discovery",url,source_id=source["id"],
                              company_id=source["company_id"],payload={"url":url})
            self._log("task",task_id,"page_committed",{"observation":oid,"cursor":cursor_key,"status":state})
        return {"observation_id":oid,"job_ids":inserted,"task_status":state,"gap":reason}

    def commit_detail(self,task_id: str,token: str,job: Job,*,source_url: str,payload: bytes,
                      origin='native_http',tool_ref=None,media_type='text/html',observed_at=None) -> dict:
        """Update an individual detail without disturbing the inventory cursor or total."""
        job.validate()
        with self.transaction():
            task=self._check_lease(task_id,token)
            if task['kind'] not in {'job_detail','detail_discovery','image_review'}:raise EngineError('not a detail task')
            source=self.row('sources',task['source_id']);request=json.loads(task['payload_json'])
            jid=stable_id(source['id'],job.external_id,job.round_key)
            if request.get('job_id'):
                jid=request['job_id'];previous=self.row('jobs',jid)
                if previous['external_id']!=job.external_id or previous['round_key']!=job.round_key:
                    raise EngineError('detail belongs to a different job/round')
                if task['kind']=='image_review' and request.get('expected_content_hash') and request['expected_content_hash']!=previous['content_hash']:
                    raise LeaseLost('image input changed; previous review cannot overwrite the current job')
            if task['kind']=='image_review' and not job.detail_verified:
                raise EngineError('image review needs an observed transcription; block unreadable input instead')
            oid=self._observe(task,source_url,payload,media_type=media_type,origin=origin,tool_ref=tool_ref,observed_at=observed_at)
            at=self.row('observations',oid)['observed_at'];encoded=dump(job.content());chash=digest(encoded)
            previous=self.db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
            if previous and at<previous['last_seen']:
                current_observation=self.row('observations',previous['latest_observation_id'])
                if current_observation['sha256']!=digest(payload) or current_observation['source_url']!=source_url:
                    self.db.execute("UPDATE tasks SET status='blocked',error_code='stale_detail_observation',error_note='Older capture retained without replacing newer job facts',lease_token=NULL,lease_until=NULL WHERE id=?",(task_id,))
                    self._log('task',task_id,'stale_detail_retained',{'observation':oid})
                    return {'observation_id':oid,'job_id':jid,'detail_verified':bool(previous['detail_verified']),'stale_ignored':True}
                # Reinterpreting identical bytes may enrich metadata, but cannot
                # rewind freshness or replace the newer source observation.
                self._log('task',task_id,'equivalent_old_capture_reinterpreted',{'retained_capture':oid,'newer_source':current_observation['id']})
                oid=current_observation['id'];at=previous['last_seen']
            company_id=source['company_id'] or self._catalog_employer(source,job.employer,task['run_id'],oid)
            self.db.execute('''INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET company_id=excluded.company_id,employer=excluded.employer,title=excluded.title,
                job_url=excluded.job_url,apply_url=excluded.apply_url,content_json=excluded.content_json,
                content_hash=excluded.content_hash,recruiting_status=excluded.recruiting_status,
                detail_verified=excluded.detail_verified,first_seen=MIN(jobs.first_seen,excluded.first_seen),last_seen=excluded.last_seen,latest_observation_id=excluded.latest_observation_id''',
                (jid,source['id'],job.external_id,job.round_key,company_id,job.employer,job.title,job.job_url,
                 job.apply_url,encoded,chash,job.status,int(job.detail_verified),at,at,oid))
            self.db.execute('INSERT OR IGNORE INTO job_versions VALUES(?,?,?,?,?)',(jid,chash,oid,at,encoded))
            self.db.execute('INSERT OR IGNORE INTO job_sightings VALUES(?,?,?,?)',(task['run_id'],jid,task_id,oid))
            self.db.execute('INSERT OR IGNORE INTO run_jobs VALUES(?,?,0)',(task['run_id'],jid))
            if job.status=='closed':
                # A source may remove its description after closing a campaign.
                # The explicit closure still governs its exact existing roles;
                # preserve their duties/decisions instead of requiring re-splitting.
                children=self.db.execute('''SELECT j.* FROM job_links l JOIN jobs j ON j.id=l.right_id
                    WHERE l.left_id=? AND l.relation='role_child' AND j.source_id=? AND j.round_key=?''',
                    (jid,source['id'],job.round_key)).fetchall()
                for child in children:
                    if at<child['last_seen'] or not child['external_id'].startswith(job.external_id+':role:'):continue
                    content=json.loads(child['content_json']);content.update(status='closed',apply_url=job.apply_url)
                    child_encoded=dump(content);child_hash=digest(child_encoded)
                    self.db.execute('''UPDATE jobs SET recruiting_status='closed',apply_url=?,content_json=?,
                        content_hash=?,last_seen=?,latest_observation_id=? WHERE id=?''',
                        (job.apply_url,child_encoded,child_hash,at,oid,child['id']))
                    self.db.execute('INSERT OR IGNORE INTO job_versions VALUES(?,?,?,?,?)',(child['id'],child_hash,oid,at,child_encoded))
                    self._log('job',child['id'],'official_parent_closed',{'parent':jid,'observation':oid})
            if not job.detail_verified:
                review={'job_id':jid,'media_urls':job.raw.get('media_urls',[]),
                        'embedded_image_count':job.raw.get('embedded_image_count',0),
                        'expected_content_hash':chash,'review_input_sha256':digest(payload)}
                tid=self._enqueue(task['run_id'],'image_review',jid,source_id=source['id'],company_id=source['company_id'],payload=review,priority=20)
                existing=self.row('tasks',tid);old_review=json.loads(existing['payload_json'])
                changed=old_review.get('expected_content_hash')!=chash or old_review.get('review_input_sha256')!=review['review_input_sha256']
                if existing['status']=='leased' and changed:
                    self.db.execute("UPDATE tasks SET status='queued',payload_json=?,not_before=?,finished_at=NULL,lease_token=NULL,lease_until=NULL,error_code=NULL,error_note=NULL WHERE id=?",(dump(review),at,tid))
                    self._log('task',tid,'image_input_superseded',{'new_observation':oid,'prior_content_hash':old_review.get('expected_content_hash')})
                elif existing['status']=='done' or existing['status'] in {'blocked','superseded'} and changed:
                    self.db.execute("UPDATE tasks SET status='queued',payload_json=?,not_before=?,finished_at=NULL,error_code=NULL,error_note=NULL WHERE id=?",(dump(review),at,tid))
                    self._log('task',tid,'image_review_reopened',{'new_observation':oid})
                elif existing['status']=='queued':
                    self.db.execute('UPDATE tasks SET payload_json=? WHERE id=?',(dump(review),tid))
            else:
                obsolete=self.db.execute("""SELECT id FROM tasks WHERE run_id=? AND kind='image_review'
                    AND id!=? AND status IN ('queued','blocked','deferred','leased')
                    AND json_extract(payload_json,'$.job_id')=?""",(task['run_id'],task_id,jid)).fetchall()
                for old_review in obsolete:
                    self.db.execute("UPDATE tasks SET status='superseded',lease_token=NULL,lease_until=NULL,finished_at=? WHERE id=?",(self._now(),old_review['id']))
                    self._log('task',old_review['id'],'verified_detail_superseded_image_input',{'observation':oid,'job_id':jid})
            self.db.execute("UPDATE tasks SET status='done',finished_at=?,lease_token=NULL,lease_until=NULL WHERE id=?",(self._now(),task_id))
            self._log('job',jid,'detail_committed',{'observation':oid,'origin':origin,'detail_verified':job.detail_verified})
        return {'observation_id':oid,'job_id':jid,'detail_verified':job.detail_verified}

    def split_campaign(self,run_id: str,parent_id: str,roles: list[dict],*,evidence_ref: str) -> list[str]:
        """Host-authored role extraction; no title keyword suitability rules."""
        required(evidence_ref,'actual host role-extraction observation')
        parent=self.row('jobs',parent_id);content=json.loads(parent['content_json'])
        if not parent['detail_verified'] or not self.db.execute('SELECT 1 FROM run_jobs WHERE run_id=? AND job_id=?',(run_id,parent_id)).fetchone():
            raise EngineError('campaign must have observed details in this run')
        if not roles:raise EngineError('individual role extraction required')
        result=[]
        with self.transaction():
            for role in roles:
                key=required(role.get('role_key'),'stable role key');title=required(role.get('title'),'exact role title')
                description=required(role.get('description'),'individual duties and requirements')
                quote=required(role.get('source_quote'),'verbatim role identity/section quote')
                if quote not in content['description']:raise EngineError('role extraction not grounded in observed campaign text')
                external=parent['external_id']+':role:'+key;jid=stable_id(parent['source_id'],external,parent['round_key'])
                employer=role.get('employer') or parent['employer']
                if role.get('employer') and employer not in content['description']:
                    raise EngineError('individual employer must appear in the observed campaign')
                company_id=parent['company_id']
                if employer!=parent['employer']:
                    company_id=self._catalog_employer(self.row('sources',parent['source_id']),employer,run_id,parent['latest_observation_id'])
                child={**content,'external_id':external,'title':title,'employer':employer,'description':description,
                       'campaign_title':parent['title'],'requires_role_split':False,'parent_content_hash':parent['content_hash']}
                if role.get('location'):child['location']=role['location']
                status=role.get('recruiting_status',parent['recruiting_status'])
                if status not in {'open','closed','unknown'}:raise EngineError('invalid observed role recruiting status')
                child['status']=status
                encoded=dump(child);chash=digest(encoded);at=parent['last_seen'];oid=parent['latest_observation_id']
                self.db.execute('''INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET company_id=excluded.company_id,employer=excluded.employer,
                    job_url=excluded.job_url,apply_url=excluded.apply_url,
                    content_json=excluded.content_json,content_hash=excluded.content_hash,
                    title=excluded.title,recruiting_status=excluded.recruiting_status,first_seen=MIN(jobs.first_seen,excluded.first_seen),last_seen=excluded.last_seen,
                    latest_observation_id=excluded.latest_observation_id''',
                    (jid,parent['source_id'],external,parent['round_key'],company_id,employer,title,
                     parent['job_url'],parent['apply_url'],encoded,chash,status,1,at,at,oid))
                self.db.execute('INSERT OR IGNORE INTO job_versions VALUES(?,?,?,?,?)',(jid,chash,oid,at,encoded))
                self.db.execute('INSERT OR IGNORE INTO run_jobs VALUES(?,?,0)',(run_id,jid))
                task=self.db.execute('SELECT task_id FROM observations WHERE id=?',(oid,)).fetchone()[0]
                self.db.execute('INSERT OR IGNORE INTO job_sightings VALUES(?,?,?,?)',(run_id,jid,task,oid))
                self.db.execute('INSERT OR IGNORE INTO job_links VALUES(?,?,?,?,?,?)',(stable_id(parent_id,jid,'role_child'),parent_id,jid,'role_child',evidence_ref,at))
                self._log('job',jid,'role_extracted',{'parent':parent_id,'quote':quote,'evidence':evidence_ref});result.append(jid)
        return result

    def complete_host_task(self, task_id: str, token: str, *, evidence_url: str | None,
                           evidence_text: str, tool_ref: str, outcome: dict) -> str:
        """Bridge from an authorized browser/LLM. Evidence is labelled host_export, not authenticated."""
        with self.transaction():
            task = self._check_lease(task_id,token)
            if task["kind"] == "inventory":
                raise EngineError("inventory requires parsed pages, not a completion sentence")
            origin='host_export'
            if evidence_url is None:
                if task['kind']!='legacy_recheck' or outcome.get('disposition')!='scoped_user_decline':
                    raise EngineError('only a scoped historical user decision may use private record evidence')
                legacy_id=json.loads(task['payload_json'])['legacy_id']
                legacy=self.db.execute('SELECT * FROM legacy_records WHERE id=?',(legacy_id,)).fetchone()
                quote=required(outcome.get('source_quote'),'exact imported decision provenance quote')
                record=json.loads(legacy['payload_json'])
                if quote not in str(record.get('provenance','')) and quote not in str(record.get('user_statement','')):
                    raise EngineError('private decision quote not found in preserved source record')
                evidence_url='urn:job-research:legacy:'+legacy_id;origin='private_record'
            oid = self._observe(task,evidence_url,evidence_text.encode(),media_type="text/plain",
                                origin=origin,tool_ref=tool_ref,observed_at=None)
            if task["kind"] == "source_discovery":
                src = self.row("sources",required(outcome.get("source_id"),"registered source"))
                if src["company_id"] != task["company_id"]:
                    raise EngineError("source is not associated with this company")
                self.db.execute("INSERT OR IGNORE INTO run_sources VALUES(?,?,0)", (task["run_id"],src["id"]))
                self._enqueue(task["run_id"],"inventory",src["id"],source_id=src["id"],company_id=src["company_id"])
            elif task["kind"] == "missing_job_recheck":
                jid = json.loads(task["payload_json"])["job_id"]
                job = self.row("jobs",jid)
                status = outcome.get("recruiting_status")
                if status not in {"open", "closed"}:
                    raise EngineError("unknown result must stay blocked/deferred, not done")
                content = json.loads(job["content_json"])
                content["status"] = status
                encoded = dump(content); chash = digest(encoded); at = self._now()
                self.db.execute("UPDATE jobs SET recruiting_status=?,content_json=?,content_hash=?,last_seen=?,latest_observation_id=? WHERE id=?", (status,encoded,chash,at,oid,jid))
                self.db.execute("INSERT OR IGNORE INTO job_versions VALUES(?,?,?,?,?)",(jid,chash,oid,at,encoded))
                self.db.execute("INSERT OR IGNORE INTO job_sightings VALUES(?,?,?,?)",(task["run_id"],jid,task_id,oid))
                self._log("job",jid,"explicit_status_recheck",{"status":status,"observation":oid})
            elif task["kind"] == "legacy_recheck":
                legacy_id = json.loads(task["payload_json"])["legacy_id"]
                record = self.db.execute("SELECT * FROM legacy_records WHERE id=?", (legacy_id,)).fetchone()
                if not record or record["profile_id"] != self.row("runs",task["run_id"])["profile_id"]:
                    raise EngineError("legacy profile mismatch")
                disposition = outcome.get("disposition")
                if disposition == "linked_job":
                    if not self.db.execute("SELECT 1 FROM run_jobs WHERE run_id=? AND job_id=?", (task["run_id"],outcome.get("job_id"))).fetchone():
                        raise EngineError("legacy job not observed in this run")
                elif disposition not in {"closed_round", "scoped_user_decline", "duplicate_record"}:
                    raise EngineError("legacy record needs explicit evidenced disposition")
                self.db.execute("UPDATE legacy_records SET resolution_json=? WHERE id=?", (dump({**outcome,"observation_id":oid}),legacy_id))
            elif task["kind"] == "detail_discovery":
                # Host must ingest the detail through a registered, evidence-linked source first.
                jid = required(outcome.get("job_id"),"ingested job ID")
                job = self.row("jobs",jid)
                if not self.db.execute("SELECT 1 FROM run_jobs WHERE run_id=? AND job_id=?",(task["run_id"],jid)).fetchone():
                    raise EngineError("detail job not ingested in this run")
                if not job["detail_verified"]:
                    raise EngineError("detail not yet verified")
            else:
                raise EngineError("unsupported host task")
            self.db.execute("UPDATE tasks SET status='done',lease_token=NULL,lease_until=NULL,finished_at=? WHERE id=?", (self._now(),task_id))
            self._log("task",task_id,"host_completed",{"observation":oid,"outcome":outcome})
        return oid

    def assess(self, profile_id: str, job_id: str, *, decision: str, reason: str,
               evidence_ids: list[str], expected_profile_revision: int, expected_content_hash: str,
               risk: str = "", blocking_unknowns: list[str] | None = None,
               report_tier: str = 'actionable') -> str:
        if decision not in {"recommend", "check", "exclude"}:
            raise EngineError("decision must be recommend/check/exclude")
        if report_tier not in {'actionable','source_gap','future_pool'} or decision!='check' and report_tier!='actionable':
            raise EngineError('only check decisions may retain non-actionable source gaps or future pools')
        required(reason,"assessment reason")
        if not evidence_ids:
            raise EngineError("assessment requires observed evidence")
        with self.transaction():
            profile,job = self.row("profiles",profile_id),self.row("jobs",job_id)
            if profile["revision"] != expected_profile_revision or job["content_hash"] != expected_content_hash:
                raise EngineError("facts changed; reassess rather than overwriting")
            for oid in evidence_ids:
                self.row("observations",oid)
            if job["latest_observation_id"] not in evidence_ids:
                raise EngineError("latest job evidence must be considered")
            unknowns = blocking_unknowns or []
            if decision == "recommend" and (unknowns or job["recruiting_status"] != "open" or not job["detail_verified"] or json.loads(job['content_json']).get('requires_role_split') or job['external_id'].startswith('campaign:') and ':role:' not in job['external_id']):
                raise EngineError("recommendation lacks verified details or has a blocking unknown")
            aid = uuid.uuid4().hex
            self.db.execute("INSERT INTO assessments VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (aid,profile_id,profile["revision"],job_id,job["content_hash"],decision,reason,risk,
                 dump(unknowns),dump(evidence_ids),self._now()))
            if report_tier!='actionable':self.db.execute('INSERT INTO assessment_reporting VALUES(?,?)',(aid,report_tier))
            self._log("assessment",aid,"created",{"job_id":job_id,"decision":decision})
        return aid

    def user_event(self, profile_id: str, *, event_key: str, scope_type: str,
                   target_id: str, kind: str, value: str, evidence_ref: str) -> str:
        """Natural-language user corrections must be translated without broadening scope."""
        self.row("profiles",profile_id)
        if scope_type not in {"job", "company"}:
            raise EngineError("only explicit job/company decisions are implemented; do not widen a scope")
        self.row("jobs" if scope_type=="job" else "companies",target_id)
        if kind == "decision":
            if value not in {"declined", "interested", "undecided"}:
                raise EngineError("invalid user decision")
        elif kind == "application":
            if scope_type != "job" or value not in {"not_started","draft","written","submitted","interview","offered","rejected","withdrawn"}:
                raise EngineError("invalid application event")
        else:
            raise EngineError("invalid event kind")
        required(evidence_ref,"user/original-record evidence")
        eid = stable_id(profile_id,event_key)
        with self.transaction():
            old = self.db.execute("SELECT * FROM user_events WHERE profile_id=? AND event_key=?",(profile_id,event_key)).fetchone()
            if old:
                if (old["scope_type"],old["target_id"],old["kind"],old["value"]) != (scope_type,target_id,kind,value):
                    raise EngineError("idempotency key reused for a different event")
                return old["id"]
            self.db.execute("INSERT INTO user_events VALUES(?,?,?,?,?,?,?,?,?)",
                (eid,profile_id,event_key,scope_type,target_id,kind,value,evidence_ref,self._now()))
            self._log("user_event",eid,"recorded",{"scope":scope_type,"target":target_id,"kind":kind,"value":value})
        return eid

    def latest_user_state(self, profile_id: str, job: dict) -> dict:
        result = {"decision":"undecided","application":"not_started"}
        events = self.db.execute("""SELECT * FROM user_events WHERE profile_id=? AND
            ((scope_type='job' AND target_id=?) OR (scope_type='company' AND target_id=?))
            ORDER BY created_at,rowid""",(profile_id,job["id"],job["company_id"])).fetchall()
        for event in events:
            result[event["kind"]] = event["value"]
        return result

    def list_run_jobs(self, run_id: str) -> list[dict]:
        run = self.row("runs",run_id)
        profile = self.row("profiles",run["profile_id"])
        rows = self.db.execute("""SELECT j.*,rj.carried FROM run_jobs rj JOIN jobs j ON j.id=rj.job_id
            WHERE rj.run_id=? ORDER BY j.first_seen,j.id""",(run_id,)).fetchall()
        result=[]
        for row in rows:
            job=dict(row)
            assessment=self.db.execute("""SELECT * FROM assessments WHERE profile_id=? AND job_id=?
                ORDER BY created_at DESC,rowid DESC LIMIT 1""",(run["profile_id"],job["id"])).fetchone()
            state=self.latest_user_state(run["profile_id"],job)
            seen=self.db.execute("SELECT 1 FROM job_sightings WHERE run_id=? AND job_id=?",(run_id,job["id"])).fetchone() is not None
            current=bool(assessment and assessment["profile_revision"]==profile["revision"] and assessment["content_hash"]==job["content_hash"])
            tier=self.db.execute('SELECT report_tier FROM assessment_reporting WHERE assessment_id=?',(assessment['id'],)).fetchone() if assessment else None
            content=json.loads(job['content_json'])
            parent=self.db.execute("SELECT j.content_hash FROM job_links l JOIN jobs j ON j.id=l.left_id WHERE l.right_id=? AND l.relation='role_child'",(job['id'],)).fetchone()
            if parent and content.get('parent_content_hash')!=parent[0]:current=False
            effective=assessment["decision"] if current else "pending"
            # A remembered recommendation without a new check is preserved as check-first, not lost.
            if not current and assessment and assessment["decision"] in {"recommend","check"}:
                effective="check"
            if effective=="recommend" and not seen:
                effective="check"
            job.update(content=json.loads(job["content_json"]),assessment=dict(assessment) if assessment else None,
                       report_tier=tier[0] if tier else 'actionable',
                       assessment_current=current,user_state=state,seen_this_run=seen,effective_decision=effective)
            job["fresh_application"] = state["decision"]!="declined" and state["application"] in {"not_started","draft","written"}
            job['decomposed_campaign']=bool(self.db.execute("SELECT 1 FROM job_links WHERE left_id=? AND relation='role_child' LIMIT 1",(job['id'],)).fetchone())
            job['equivalent_decomposition']=bool(self.db.execute('''SELECT 1 FROM job_links l JOIN jobs other
                ON other.id=CASE WHEN l.left_id=? THEN l.right_id ELSE l.left_id END
                WHERE l.relation='same_posting' AND (l.left_id=? OR l.right_id=?) AND other.content_hash=?
                AND EXISTS (SELECT 1 FROM job_links c JOIN jobs child ON child.id=c.right_id
                    WHERE c.left_id=other.id AND c.relation='role_child'
                    AND json_extract(child.content_json,'$.parent_content_hash')=other.content_hash) LIMIT 1''',
                (job['id'],job['id'],job['id'],job['content_hash'])).fetchone())
            from .report import past_deadline
            job['deadline_elapsed']=past_deadline(content['deadline'],self._now(),json.loads(profile['facts_json']).get('timezone','UTC'))
            if job['recruiting_status']=='closed' or job['content'].get('requires_role_split') or job['decomposed_campaign'] or job['equivalent_decomposition'] or job['deadline_elapsed']:
                job['fresh_application']=False
            result.append(job)
        return result

    def record_audit(self, run_id: str, *, kind: str, method: str, evidence_ids: list[str],
                     discovered_job_ids: list[str] | None = None,
                     followed_job_ids: list[str] | None = None) -> str:
        self.row("runs",run_id)
        if kind not in {"counter_search","exclusion_review","registry_scope"}:
            raise EngineError("unknown audit kind")
        required(method,"audit method")
        if not evidence_ids:
            raise EngineError("audit needs evidence, not just a completion statement")
        for oid in evidence_ids:
            if oid.startswith('registry:'):
                parts=oid.split(':')
                if kind!='registry_scope' or len(parts)!=3 or not parts[2].isdigit():raise EngineError('invalid registry audit reference')
                acquired=self.db.execute('''SELECT a.sync_id FROM registry_acquisitions a JOIN registry_syncs x ON x.id=a.sync_id
                    JOIN company_memberships m ON m.snapshot_id=x.snapshot_id
                    JOIN run_companies rc ON rc.company_id=m.company_id
                    WHERE a.sync_id=? AND a.page=? AND rc.run_id=? LIMIT 1''',(parts[1],int(parts[2]),run_id)).fetchone()
                if not acquired:raise EngineError('registry evidence does not support this run scope')
                continue
            obs=self.row("observations",oid)
            task=self.row("tasks",obs["task_id"])
            if task["run_id"] != run_id:
                raise EngineError("audit observation belongs to another run")
        discoveries=discovered_job_ids or [];followed=followed_job_ids or []
        for jid in discoveries+followed:
            if not self.db.execute("SELECT 1 FROM run_jobs WHERE run_id=? AND job_id=?",(run_id,jid)).fetchone():
                raise EngineError("audit job not in this run")
        aid=uuid.uuid4().hex
        self.db.execute("INSERT INTO audit_checks VALUES(?,?,?,?,?,?,?,?)",
            (aid,run_id,kind,method,dump(evidence_ids),dump(discoveries),dump(followed),self._now()))
        return aid

    def coverage(self, run_id: str) -> dict:
        run=self.row("runs",run_id)
        tasks=[dict(t) for t in self.db.execute("SELECT * FROM tasks WHERE run_id=?",(run_id,))]
        plan=[r[0] for r in self.db.execute("SELECT company_id FROM run_companies WHERE run_id=?",(run_id,))]
        sources=[dict(r) for r in self.db.execute("SELECT * FROM run_sources WHERE run_id=?",(run_id,))]
        checks=[dict(r) for r in self.db.execute("SELECT * FROM audit_checks WHERE run_id=?",(run_id,))]
        errors=[];gaps=[]
        original=self.db.execute("SELECT detail_json FROM change_log WHERE entity='run' AND entity_id=? AND action='plan_frozen' ORDER BY seq LIMIT 1",(run_id,)).fetchone()
        if not original or not set(json.loads(original[0])["company_ids"]).issubset(set(plan)):
            errors.append("original_company_scope_shrunk")
        for task in tasks:
            if task["status"] not in {"done","superseded"}:
                gaps.append({"type":task["kind"],"id":task["id"],"status":task["status"],
                             "since":task["created_at"],"reason":task["error_code"]})
        if not sources:
            gaps.append({"type":"no_registered_sources"})
        if run["scope"]=="broad":
            kinds={c["kind"] for c in checks}
            for k in {"counter_search","exclusion_review","registry_scope"}-kinds:
                gaps.append({"type":"missing_audit","kind":k})
        for check in checks:
            missing=set(json.loads(check["discovered_json"]))-set(json.loads(check["followed_json"]))
            if missing:
                gaps.append({"type":"counter_search_followthrough","ids":sorted(missing)})
        jobs=self.list_run_jobs(run_id)
        for job in jobs:
            if job['content'].get('requires_role_split') and not job['decomposed_campaign'] and not job['equivalent_decomposition']:
                gaps.append({'type':'campaign_roles_not_split','id':job['id']})
            if job["recruiting_status"]=="closed" or not job["fresh_application"]:
                continue
            if not job["assessment_current"]:
                gaps.append({"type":"unreviewed_or_stale_candidate","id":job["id"]})
            if not job["seen_this_run"]:
                gaps.append({"type":"carried_candidate_not_rechecked","id":job["id"]})
        profile=self.row("profiles",run["profile_id"])
        if profile["revision"] != run["profile_revision"]:
            gaps.append({"type":"profile_changed_mid_run"})
        inventories=sum(s["completed"] for s in sources)
        covered_company=set()
        for cid in plan:
            rows=self.db.execute("""SELECT rs.completed FROM run_sources rs JOIN sources s ON s.id=rs.source_id
                WHERE rs.run_id=? AND s.company_id=?""",(run_id,cid)).fetchall()
            if rows and all(r[0] for r in rows):covered_company.add(cid)
        production=self.db.execute("""SELECT COUNT(*) FROM observations o JOIN tasks t ON t.id=o.task_id
            WHERE t.run_id=? AND o.origin IN ('native_http','host_export')""",(run_id,)).fetchone()[0]
        return {"run_id":run_id,"scope":run["scope"],"scope_note":run["scope_note"],
                "status":"scope_checked" if not errors and not gaps else "partial",
                "companies_planned":len(plan),"companies_registered_sources_checked":len(covered_company),
                "sources_planned":len(sources),"sources_exhausted":inventories,
                "unique_source_jobs":len(jobs),"material_gaps":gaps,"errors":errors,
                "production_observations":production,"national_coverage":"unknown",
                "assurance":"record_consistency_not_independent_browsing_proof"}

    def checkpoint(self, run_id: str, *, stop_reason: str) -> dict:
        required(stop_reason,"stop reason")
        result=self.coverage(run_id)
        # Checkpoints keep the run resumable. A completed collection is not delivery success.
        self.db.execute("UPDATE runs SET stop_reason=? WHERE id=?",(stop_reason,run_id))
        self._log("run",run_id,"checkpoint",{"reason":stop_reason,"coverage":result["status"]})
        return result

    def review_packet(self, run_id: str) -> dict:
        run=self.row("runs",run_id)
        profile=self.row("profiles",run["profile_id"])
        return {"run_id":run_id,"profile_id":profile["id"],"profile_revision":profile["revision"],
                "facts":json.loads(profile["facts_json"]),"jobs":self.list_run_jobs(run_id),
                "legacy_records":[dict(r) for r in self.db.execute("SELECT * FROM legacy_records WHERE profile_id=? AND resolution_json IS NULL",(profile["id"],))],
                "host_tasks":[dict(t) for t in self.db.execute("SELECT * FROM tasks WHERE run_id=? AND kind!='inventory' AND status!='done' ORDER BY created_at",(run_id,))],
                "blocked_tasks":[dict(t) for t in self.db.execute("SELECT * FROM tasks WHERE run_id=? AND status IN ('blocked','deferred') ORDER BY created_at",(run_id,))],
                "registered_sources":[dict(s) for s in self.db.execute("SELECT s.* FROM sources s JOIN run_sources rs ON rs.source_id=s.id WHERE rs.run_id=?",(run_id,))],
                "coverage":self.coverage(run_id)}

    def save_report(self, run_id: str, body: str, mapping: list[dict], audit: dict) -> str:
        run=self.row("runs",run_id)
        rows=self.list_run_jobs(run_id)
        expected={j["id"] for j in rows if j["fresh_application"] and
                  j["recruiting_status"]!="closed" and j["effective_decision"] in {"recommend","check"} and j['report_tier']=='actionable'}
        shown={m["job_id"] for m in mapping}
        if expected != shown:
            raise EngineError("report reconciliation failed: worthwhile jobs lost or invented")
        gaps={j['id'] for j in rows if j['effective_decision']=='check' and j['report_tier']!='actionable'}
        retained={j['job_id'] for j in audit.get('retained_non_actionable_checks',[])}
        if gaps!=retained:raise EngineError('report reconciliation failed: retained source gaps or pools lost or invented')
        rid=uuid.uuid4().hex
        self.db.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?)",
            (rid,run_id,run["profile_id"],self._now(),body,dump(mapping),dump(audit)))
        return rid

    def select_report_job(self, report_id: str, number: int, *, profile_id: str) -> dict:
        report=self.row("reports",report_id)
        if report["profile_id"] != profile_id:
            raise EngineError("report belongs to another profile")
        matches=[m for m in json.loads(report["mapping_json"]) if m["number"]==number]
        if len(matches)!=1:
            raise EngineError("unknown/ambiguous report number")
        job=self.row("jobs",matches[0]["job_id"])
        job["selection_changed_since_report"]=job["content_hash"]!=matches[0]["content_hash"]
        job["requires_live_recheck"]=True
        return job
