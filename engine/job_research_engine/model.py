from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit, parse_qsl


class EngineError(ValueError):
    """An operation cannot truthfully or safely be completed."""


class LeaseLost(EngineError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def timestamp(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as e:
        raise EngineError("timezone-aware ISO timestamp required") from e
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise EngineError("timestamp timezone is required")
    return dt.astimezone(timezone.utc)


def canonical_time(value: str) -> str:
    return timestamp(value).isoformat(timespec="microseconds")


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def stable_id(*parts: str) -> str:
    return digest(dump(list(parts)))[:32]


def required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"{name}: nonempty text required")
    return value.strip()


SECRET_KEYS = {"token", "access_token", "refresh_token", "authkey", "crtfc_key",
               "api_key", "apikey", "session", "sessionid", "password", "signature",
               "x-amz-signature", "x-amz-credential", "authorization", "jsessionid"}


def public_url(value: str) -> str:
    """Syntax/display gate. Network clients additionally resolve and pin public IPs."""
    value = required(value, "url")
    if re.search(r"[\s\x00-\x1f\x7f<>\\]", value):
        raise EngineError("unsafe URL characters")
    try:
        p = urlsplit(value)
    except ValueError as e:
        raise EngineError('invalid public URL') from e
    try:
        port = p.port
    except ValueError as e:
        raise EngineError("invalid URL port") from e
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
        raise EngineError("public http(s) URL without credentials required")
    if port not in {None, 80, 443}:
        raise EngineError("nonstandard network port requires a separate reviewed adapter")
    host = p.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".local", ".localhost", ".internal")):
        raise EngineError("private host prohibited")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as e:
            raise EngineError("invalid IDN") from e
        if "." not in host or "%" in host or not re.fullmatch(r"[a-z0-9.-]+", host):
            raise EngineError("public DNS hostname required")
        if any(not x or x.startswith("-") or x.endswith("-") for x in host.split(".")):
            raise EngineError("invalid hostname")
    else:
        if not addr.is_global:
            raise EngineError("non-public network address prohibited")
    for key, _ in parse_qsl(p.query, keep_blank_values=True):
        k = key.lower()
        if k in SECRET_KEYS or k.endswith(("_token", "_secret", "_signature")):
            raise EngineError("credential URL cannot be persisted/displayed")
    if re.search(r"(?i)[;#&](?:token|access_token|sessionid|jsessionid|authkey|crtfc_key)=", value):
        raise EngineError("credential component prohibited")
    return value


@dataclass(frozen=True)
class Job:
    external_id: str
    title: str
    employer: str
    job_url: str
    apply_url: str | None = None
    round_key: str = "source-id"
    description: str = ""
    location: str = ""
    status: str = "open"
    deadline: dict[str, Any] = field(default_factory=lambda: {"kind": "unknown"})
    published_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    detail_verified: bool = False
    requires_role_split: bool = False
    source_context: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for label in ("external_id", "title", "employer", "round_key"):
            required(getattr(self, label), label)
        public_url(self.job_url)
        if self.apply_url:
            public_url(self.apply_url)
        if self.detail_verified and not self.description.strip():
            raise EngineError("verified details require actual job-description content")
        if self.status not in {"open", "closed", "unknown"}:
            raise EngineError("bad recruiting status")
        validate_deadline(self.deadline)
        if not isinstance(self.source_context,dict):raise EngineError('source context must be an observed metadata object')

    def content(self) -> dict[str, Any]:
        return {"external_id": self.external_id, "title": self.title,
                "employer": self.employer, "job_url": self.job_url,
                "apply_url": self.apply_url, "round_key": self.round_key,
                "description": self.description, "location": self.location,
                "status": self.status, "deadline": self.deadline,
                "published_at": self.published_at,
                "detail_verified": self.detail_verified,
                "requires_role_split": self.requires_role_split,
                **({'source_context':self.source_context} if self.source_context else {})}


@dataclass(frozen=True)
class Page:
    jobs: list[Job]
    terminal: bool
    next_cursor: str | None = None
    expected_total: int | None = None
    inventory_complete: bool = True
    scope_note: str = ""
    discovered_urls: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.terminal and self.next_cursor is not None:
            raise EngineError("terminal page cannot have next cursor")
        if not self.terminal and self.next_cursor is None:
            raise EngineError("nonterminal page requires cursor")
        if self.expected_total is not None and self.expected_total < 0:
            raise EngineError("negative total")
        keys = []
        for job in self.jobs:
            job.validate()
            keys.append((job.external_id, job.round_key))
        if len(keys) != len(set(keys)):
            raise EngineError("duplicate source identity on a page")
        for url in self.discovered_urls:
            public_url(url)


def validate_deadline(value: dict[str, Any]) -> None:
    from datetime import date
    if not isinstance(value, dict):
        raise EngineError("deadline must be an object")
    kind = value.get("kind")
    if kind == "date":
        try:
            date.fromisoformat(value["date"])
        except (KeyError, ValueError, TypeError) as e:
            raise EngineError("invalid date deadline") from e
        if value.get("at") or value.get("time"):
            raise EngineError("date deadline cannot invent time")
    elif kind == "datetime":
        timestamp(value.get("at", ""))
    elif kind not in {"unknown", "rolling"}:
        raise EngineError("invalid deadline kind")
