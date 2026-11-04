"""Qudron's searchable, auditable capability registry.

Stores discovered agents, tools, MCP servers, models and workflows as data.
Registration never executes a capability. Execution permissions belong to a
separate policy-enforced runtime.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KINDS = {"agent", "tool", "mcp_server", "model", "workflow", "repository", "paper", "source"}
STATUSES = {"discovered", "candidate", "verified", "active", "limited", "deprecated", "blocked"}
ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{1,159}$")


class CapabilityRegistryError(ValueError):
    """Invalid or unsafe capability registry operation."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(path: str | Path) -> sqlite3.Connection:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(target), timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=20000")
    db.execute("PRAGMA foreign_keys=ON")
    return db


@contextmanager
def _database(path: str | Path):
    db = _connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize_registry(path: str | Path) -> None:
    with _database(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS capabilities (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          version TEXT NOT NULL DEFAULT '',
          source_url TEXT NOT NULL DEFAULT '',
          license TEXT NOT NULL DEFAULT 'unknown',
          status TEXT NOT NULL,
          trust_score INTEGER NOT NULL DEFAULT 0,
          verified_at TEXT,
          expires_at TEXT,
          tags_json TEXT NOT NULL DEFAULT '[]',
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cap_kind_status ON capabilities(kind,status);
        CREATE INDEX IF NOT EXISTS idx_cap_updated ON capabilities(updated_at DESC);
        CREATE TABLE IF NOT EXISTS capability_relations (
          capability_id TEXT NOT NULL,
          related_id TEXT NOT NULL,
          relation TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY(capability_id, related_id, relation),
          FOREIGN KEY(capability_id) REFERENCES capabilities(id) ON DELETE CASCADE,
          FOREIGN KEY(related_id) REFERENCES capabilities(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_cap_rel_related ON capability_relations(related_id,relation);
        """)


def register_capability(path: str | Path, item: dict[str, Any]) -> dict[str, Any]:
    """Insert/update metadata. This function intentionally does not execute code."""
    if not isinstance(item, dict):
        raise CapabilityRegistryError("Capability must be an object")
    cid, kind, name = item.get("id"), item.get("kind"), item.get("name")
    if not isinstance(cid, str) or not ID_RE.fullmatch(cid):
        raise CapabilityRegistryError("id must be 2-160 safe identifier characters")
    if kind not in KINDS:
        raise CapabilityRegistryError(f"kind must be one of: {', '.join(sorted(KINDS))}")
    if not isinstance(name, str) or not name.strip() or len(name) > 240:
        raise CapabilityRegistryError("name is required and must be <= 240 characters")
    status = item.get("status", "discovered")
    if status not in STATUSES:
        raise CapabilityRegistryError("unsupported capability status")
    trust = item.get("trust_score", 0)
    if type(trust) is not int or not 0 <= trust <= 100:
        raise CapabilityRegistryError("trust_score must be an integer from 0 to 100")
    tags = item.get("tags", [])
    metadata = item.get("metadata", {})
    if not isinstance(tags, list) or len(tags) > 100 or any(not isinstance(t, str) or len(t) > 80 for t in tags):
        raise CapabilityRegistryError("tags must be up to 100 short strings")
    if not isinstance(metadata, dict) or len(json.dumps(metadata, ensure_ascii=False)) > 65536:
        raise CapabilityRegistryError("metadata must be an object no larger than 64 KiB")
    for field, limit in (("description", 8000), ("version", 120), ("source_url", 2048), ("license", 120)):
        value = item.get(field, "")
        if not isinstance(value, str) or len(value) > limit:
            raise CapabilityRegistryError(f"{field} must be a string <= {limit} characters")
    verified_at = item.get("verified_at")
    expires_at = item.get("expires_at")
    for field, value in (("verified_at", verified_at), ("expires_at", expires_at)):
        if value is not None:
            if not isinstance(value, str):
                raise CapabilityRegistryError(f"{field} must be an ISO timestamp")
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise CapabilityRegistryError(f"{field} must be an ISO timestamp") from exc

    now = _now()
    with _database(path) as db:
        db.execute("""
        INSERT INTO capabilities
        (id,kind,name,description,version,source_url,license,status,trust_score,
         verified_at,expires_at,tags_json,metadata_json,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          kind=excluded.kind,name=excluded.name,description=excluded.description,
          version=excluded.version,source_url=excluded.source_url,license=excluded.license,
          status=excluded.status,trust_score=excluded.trust_score,
          verified_at=excluded.verified_at,expires_at=excluded.expires_at,
          tags_json=excluded.tags_json,metadata_json=excluded.metadata_json,
          updated_at=excluded.updated_at
        """, (cid,kind,name.strip(),item.get("description",""),item.get("version",""),
              item.get("source_url",""),item.get("license","unknown"),status,trust,
              verified_at,expires_at,json.dumps(sorted(set(tags)),ensure_ascii=False),
              json.dumps(metadata,ensure_ascii=False),now,now))
        row = db.execute("SELECT * FROM capabilities WHERE id=?", (cid,)).fetchone()
    return _decode(row)


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["tags"] = json.loads(item.pop("tags_json"))
    item["metadata"] = json.loads(item.pop("metadata_json"))
    return item


def get_capability(path: str | Path, capability_id: str) -> dict[str, Any] | None:
    initialize_registry(path)
    with _database(path) as db:
        row = db.execute("SELECT * FROM capabilities WHERE id=?", (capability_id,)).fetchone()
    return _decode(row) if row else None


def search_capabilities(path: str | Path, query: str = "", kind: str | None = None,
                        statuses: tuple[str, ...] = ("verified", "active", "limited"),
                        limit: int = 50) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500:
        raise CapabilityRegistryError("limit must be between 1 and 500")
    if kind is not None and kind not in KINDS:
        raise CapabilityRegistryError("unsupported capability kind")
    if any(status not in STATUSES for status in statuses):
        raise CapabilityRegistryError("unsupported capability status filter")
    initialize_registry(path)
    clauses, params = [], []
    if kind:
        clauses.append("kind=?"); params.append(kind)
    if statuses:
        clauses.append("status IN (" + ",".join("?" for _ in statuses) + ")")
        params.extend(statuses)
    if query.strip():
        clauses.append("(name LIKE ? OR description LIKE ? OR tags_json LIKE ?)")
        needle = "%" + query.strip().replace("%", "\\%").replace("_", "\\_") + "%"
        params.extend([needle, needle, needle])
    sql = "SELECT * FROM capabilities"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY trust_score DESC, updated_at DESC LIMIT ?"
    params.append(limit)
    with _database(path) as db:
        rows = db.execute(sql, params).fetchall()
    return [_decode(row) for row in rows]


def add_relation(path: str | Path, capability_id: str, related_id: str,
                 relation: str = "alternative") -> None:
    if relation not in {"alternative", "depends_on", "implements", "supersedes"}:
        raise CapabilityRegistryError("unsupported relation type")
    initialize_registry(path)
    with _database(path) as db:
        db.execute("INSERT OR IGNORE INTO capability_relations VALUES (?,?,?,?)",
                   (capability_id, related_id, relation, _now()))


def find_alternatives(path: str | Path, capability_id: str, limit: int = 4) -> list[dict[str, Any]]:
    """Return explicit alternatives first, then same-kind verified/active candidates."""
    if not 1 <= limit <= 20:
        raise CapabilityRegistryError("limit must be between 1 and 20")
    initialize_registry(path)
    with _database(path) as db:
        target = db.execute("SELECT * FROM capabilities WHERE id=?", (capability_id,)).fetchone()
        if not target:
            return []
        linked = db.execute("""
          SELECT c.* FROM capability_relations r JOIN capabilities c ON c.id=r.related_id
          WHERE r.capability_id=? AND r.relation='alternative'
          AND c.status IN ('verified','active','limited')
          ORDER BY c.trust_score DESC LIMIT ?
        """, (capability_id, limit)).fetchall()
        found = {row["id"] for row in linked}
        remaining = limit - len(linked)
        fallback = []
        if remaining:
            fallback = db.execute("""
              SELECT * FROM capabilities WHERE kind=? AND id<>?
              AND status IN ('verified','active','limited')
              ORDER BY trust_score DESC,updated_at DESC LIMIT ?
            """, (target["kind"], capability_id, remaining + len(found))).fetchall()
    results = [_decode(row) for row in linked]
    results.extend(_decode(row) for row in fallback if row["id"] not in found)
    return results[:limit]


def list_stale_capabilities(path: str | Path, before_iso: str) -> list[dict[str, Any]]:
    """Return verified/active records with missing or old verification timestamps."""
    initialize_registry(path)
    with _database(path) as db:
        rows = db.execute("""
          SELECT * FROM capabilities
          WHERE status IN ('verified','active','limited')
          AND (verified_at IS NULL OR verified_at < ? OR (expires_at IS NOT NULL AND expires_at < ?))
          ORDER BY updated_at
        """, (before_iso, _now())).fetchall()
    return [_decode(row) for row in rows]
