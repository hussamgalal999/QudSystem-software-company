"""Metered read-only live web search and fetch through DeepSeek's official API.

Search results are cached by a one-way query digest so repeated specialist
roles can reuse the same public evidence without persisting the original query.
This is a cost/latency optimization, not a quota bypass: only owner-authorized
API calls are made and every cache miss remains subject to the daily call cap.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import sqlite3
import urllib.error
import urllib.parse
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request

from endpoint_security import is_allowed_credential_endpoint, open_credential_request

BASE = "https://api.deepseek.com/v1/tools"
if not is_allowed_credential_endpoint(BASE):
    raise RuntimeError("DeepSeek API endpoint is not allowed")
COST_PER_SUCCESS_USD = 0.00075
DEFAULT_SEARCH_CACHE_TTL_SECONDS = 21_600
MAX_CACHED_SEARCH_BYTES = 100_000


class WebResearchError(RuntimeError):
    """A bounded web-research request could not be completed safely."""


def _db_path() -> Path:
    return Path(os.getenv("QUDRON_WEB_SEARCH_DB", "/app/data/web_search_usage.sqlite3"))


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=20)
    db.execute("PRAGMA busy_timeout=20000")
    return db


def _reserve_call(kind: str) -> dict[str, object]:
    limit = max(0, int(os.getenv("QUDRON_WEB_SEARCH_MAX_DAILY_CALLS", "0")))
    if limit < 1:
        raise WebResearchError(
            "Web search is disabled; configure QUDRON_WEB_SEARCH_MAX_DAILY_CALLS after setting a spend cap"
        )
    import datetime

    day = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    with _connect() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS web_calls("
            "day TEXT NOT NULL,kind TEXT NOT NULL,calls INTEGER NOT NULL,"
            "PRIMARY KEY(day,kind))"
        )
        db.execute("BEGIN IMMEDIATE")
        total = db.execute(
            "SELECT COALESCE(SUM(calls),0) FROM web_calls WHERE day=?", (day,)
        ).fetchone()[0]
        if total >= limit:
            db.rollback()
            raise WebResearchError("Daily web search/fetch call limit reached")
        db.execute(
            "INSERT INTO web_calls(day,kind,calls) VALUES(?,?,1) "
            "ON CONFLICT(day,kind) DO UPDATE SET calls=calls+1",
            (day, kind),
        )
        db.commit()
    return {
        "day_utc": day,
        "daily_calls": int(total) + 1,
        "max_daily_calls": limit,
        "reserved_cost_usd": COST_PER_SUCCESS_USD,
    }


def _request(path: str, payload: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise WebResearchError("DEEPSEEK_API_KEY is not configured in the host secret manager")
    reservation = _reserve_call(path.rsplit("/", 1)[-1])
    request = Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with open_credential_request(request, timeout=60, endpoint_validated=True) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise WebResearchError(f"DeepSeek web API returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise WebResearchError("DeepSeek web API request failed") from None
    if not isinstance(data, dict):
        raise WebResearchError("DeepSeek web API returned an invalid response")
    return data, reservation


def _normalized_query(query: str) -> str:
    return " ".join(query.split()).casefold()


def _cache_key(query: str, count: int, need_content: bool) -> str:
    material = f"{_normalized_query(query)}\0{count}\0{int(need_content)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cache_ttl() -> int:
    try:
        configured = int(os.getenv("QUDRON_WEB_SEARCH_CACHE_TTL_SECONDS", str(DEFAULT_SEARCH_CACHE_TTL_SECONDS)))
    except (TypeError, ValueError):
        configured = DEFAULT_SEARCH_CACHE_TTL_SECONDS
    return max(0, min(604_800, configured))


def _read_search_cache(key: str) -> list[dict[str, object]] | None:
    ttl = _cache_ttl()
    if ttl == 0:
        return None
    import time

    with _connect() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS web_search_cache("
            "cache_key TEXT PRIMARY KEY,results_json TEXT NOT NULL,created_at REAL NOT NULL)"
        )
        db.execute("DELETE FROM web_search_cache WHERE created_at<?", (time.time() - ttl,))
        row = db.execute(
            "SELECT results_json FROM web_search_cache WHERE cache_key=? AND created_at>=?",
            (key, time.time() - ttl),
        ).fetchone()
    if not row:
        return None
    try:
        results = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return None
    return results if isinstance(results, list) else None


def _write_search_cache(key: str, results: list[dict[str, object]]) -> None:
    ttl = _cache_ttl()
    if ttl == 0:
        return
    encoded = json.dumps(results, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_CACHED_SEARCH_BYTES:
        return
    import time

    with _connect() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS web_search_cache("
            "cache_key TEXT PRIMARY KEY,results_json TEXT NOT NULL,created_at REAL NOT NULL)"
        )
        db.execute(
            "INSERT INTO web_search_cache(cache_key,results_json,created_at) VALUES(?,?,?) "
            "ON CONFLICT(cache_key) DO UPDATE SET "
            "results_json=excluded.results_json,created_at=excluded.created_at",
            (key, encoded, time.time()),
        )


def _bounded_results(results: object, count: int) -> list[dict[str, object]]:
    """Keep only the evidence fields used by the research pipeline, with hard bounds."""
    if not isinstance(results, list):
        return []
    bounded: list[dict[str, object]] = []
    for item in results[:count]:
        if not isinstance(item, dict):
            continue
        record: dict[str, object] = {}
        for field, limit in (
            ("title", 240), ("url", 1000), ("date", 80),
            ("authority", 80), ("summary", 1000), ("content", 2200),
        ):
            value = item.get(field)
            if isinstance(value, (str, int, float)):
                record[field] = str(value)[:limit]
        bounded.append(record)
    return bounded


def search_web(query: str, count: int = 5, need_content: bool = True) -> dict[str, object]:
    query = str(query).strip()
    if not 1 <= len(query) <= 128:
        raise ValueError("Query must contain 1–128 characters")
    if not 1 <= count <= 10:
        raise ValueError("count must be between 1 and 10 for the bounded pilot")

    key = _cache_key(query, count, need_content)
    cached = _read_search_cache(key)
    if cached is not None:
        return {
            "query": query,
            "results": cached,
            "usage": {"cached": True, "provider_calls": 0},
            "cost_usd": 0.0,
            "cached": True,
        }

    data, usage = _request(
        "/search", {"query": query, "count": count, "need_content": bool(need_content)}
    )
    results = _bounded_results(data.get("results", []), count)
    _write_search_cache(key, results)
    usage["cached"] = False
    usage["provider_calls"] = 1
    return {
        "query": query,
        "results": results,
        "usage": usage,
        "cost_usd": COST_PER_SUCCESS_USD if results else 0.0,
        "cached": False,
    }


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or len(value) > 8192:
        raise ValueError("Only public HTTPS URLs without embedded credentials are allowed")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("Local/private hosts are not allowed")
    try:
        address = ipaddress.ip_address(host)
        if not address.is_global:
            raise ValueError("Private or non-public IP targets are not allowed")
    except ValueError as exc:
        if str(exc).startswith("Private or"):
            raise
    return value


def fetch_page(url: str) -> dict[str, object]:
    target = _safe_url(url)
    data, usage = _request("/fetch", {"url": target})
    title = str(data.get("title", ""))[:240]
    content = str(data.get("content", ""))[:12_000]
    return {
        "url": target,
        "title": title,
        "content": content,
        "usage": usage,
        "cost_usd": COST_PER_SUCCESS_USD if content else 0.0,
    }
