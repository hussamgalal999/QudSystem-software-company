#!/usr/bin/env python3
"""Qudron: restart-safe background task runner for QudSystem.

This does not keep ChatGPT alive. It runs independently on infrastructure
controlled by QudSystem and creates reviewable drafts/research artifacts only.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import logging
import hmac
import math
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from swarm_engine import execute_swarm, load_agent_registry, redact_sensitive_text

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("QUDRON_DB_PATH", str(APP_DIR / "data" / "qudron.sqlite3")))
REPORTS_DIR = Path(os.getenv("QUDRON_REPORTS_DIR", str(APP_DIR / "reports")))
SCHEDULE_PATH = Path(os.getenv("QUDRON_SCHEDULE_PATH", str(APP_DIR / "schedule.json")))
AGENT_REGISTRY_PATH = Path(os.getenv("QUDRON_AGENT_REGISTRY_PATH", str(APP_DIR / "agent_registry.json")))
LOG_PATH = Path(os.getenv("QUDRON_LOG_PATH", str(APP_DIR / "logs" / "worker.log")))
POLL_SECONDS = max(1, int(os.getenv("QUDRON_POLL_SECONDS", "5")))
WORKERS = max(1, min(8, int(os.getenv("QUDRON_WORKERS", "4"))))
MAX_ATTEMPTS = max(1, int(os.getenv("QUDRON_MAX_ATTEMPTS", "5")))
LOCK_SECONDS = max(60, int(os.getenv("QUDRON_LOCK_SECONDS", "900")))
HEALTH_PORT = int(os.getenv("QUDRON_HEALTH_PORT", "8765"))
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_TIMEOUT = max(10, int(os.getenv("LLM_TIMEOUT_SECONDS", "180")))
API_TOKEN = os.getenv("QUDRON_API_TOKEN", "")
MAX_API_BODY_BYTES = 65536
MAX_OUTPUT_TOKENS = max(128, min(4000, int(os.getenv("QUDRON_MAX_OUTPUT_TOKENS", "1200"))))
MAX_INPUT_CHARS = max(4000, min(60000, int(os.getenv("QUDRON_MAX_INPUT_CHARS", "24000"))))
SWARM_ENABLED = os.getenv("QUDRON_SWARM_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
MAX_SWARM_AGENTS = max(1, min(5, int(os.getenv("QUDRON_MAX_SWARM_AGENTS", "5"))))
MAX_CVPEN_AGENTS = max(1, min(10, int(os.getenv("QUDRON_MAX_CVPEN_AGENTS", "10"))))
MAX_PARALLEL_REVIEWS = max(1, min(8, int(os.getenv("QUDRON_MAX_PARALLEL_REVIEWS", "8"))))
MAX_CONCURRENT_MODEL_CALLS = max(1, min(32, int(os.getenv("QUDRON_MAX_CONCURRENT_MODEL_CALLS", "8"))))
MODEL_CALL_SLOT_TIMEOUT_SECONDS = max(5, min(900, int(os.getenv("QUDRON_MODEL_CALL_SLOT_TIMEOUT_SECONDS", "120"))))
AGENT_REGISTRY: dict[str, Any] = {}
EXTERNAL_API_TASK_TYPES = {
    "research", "social_post_draft", "video_script", "translation",
    "seo_plan", "lead_research", "product_review", "engineering_review",
    "strategy_review", "risk_review",
}

ALLOWED_TASK_TYPES = {
    "research", "social_post_draft", "video_script",
    "translation", "seo_plan", "lead_research", "cvpen_cv_creation",
    "cvpen_ats_audit", "customer_support_reply", "payment_reconciliation",
    "product_review", "engineering_review", "strategy_review", "risk_review",
    "incident_triage",
}
STOP = threading.Event()
INSTANCE_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"

def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")

def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(os.getenv("QUDRON_LOG_LEVEL", "INFO").upper())
    handler = RotatingFileHandler(LOG_PATH, maxBytes=5_000_000, backupCount=4, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler())

class ClosingConnection(sqlite3.Connection):
    """Connection context manager that also closes the file handle on exit."""
    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(
        DB_PATH, timeout=30, isolation_level=None, factory=ClosingConnection
    )
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=30000")
    return db

def init_db() -> None:
    with connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, job_key TEXT UNIQUE, title TEXT NOT NULL,
          role TEXT NOT NULL, task_type TEXT NOT NULL, prompt TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
          run_after TEXT NOT NULL, locked_by TEXT, lock_until TEXT,
          result_path TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(status, run_after);
        CREATE TABLE IF NOT EXISTS schedule_state (
          schedule_id TEXT PRIMARY KEY, next_run_at TEXT NOT NULL, last_enqueued_at TEXT
        );
        CREATE TABLE IF NOT EXISTS heartbeats (
          instance_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, worker_count INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memory_entries (
          id TEXT PRIMARY KEY, project TEXT NOT NULL, scope TEXT NOT NULL,
          category TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
          expires_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_memory_lookup
          ON memory_entries(project, scope, created_at DESC);
        CREATE TABLE IF NOT EXISTS llm_usage (
          id TEXT PRIMARY KEY, job_id TEXT NOT NULL, agent_id TEXT NOT NULL,
          profile TEXT NOT NULL, model TEXT NOT NULL, prompt_tokens INTEGER,
          completion_tokens INTEGER, total_tokens INTEGER, cost_usd REAL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at);
        CREATE INDEX IF NOT EXISTS idx_llm_usage_job ON llm_usage(job_id);
        CREATE TABLE IF NOT EXISTS llm_usage_reservations (
          id TEXT PRIMARY KEY, job_id TEXT NOT NULL, agent_id TEXT NOT NULL,
          profile TEXT NOT NULL, reserved_cost_usd REAL NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_llm_reservations_created
          ON llm_usage_reservations(created_at);
        CREATE TABLE IF NOT EXISTS model_call_slots (
          id TEXT PRIMARY KEY, job_id TEXT NOT NULL, agent_id TEXT NOT NULL,
          lease_until TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_model_call_slots_lease
          ON model_call_slots(lease_until);
        """)

def next_local_occurrence(item: dict[str, Any], after_utc: dt.datetime) -> dt.datetime:
    """Return the next scheduled local wall-clock occurrence strictly after after_utc."""
    zone = ZoneInfo(str(item.get("timezone", "UTC")))
    hour, minute = (int(part) for part in str(item["at_local"]).split(":"))
    local_after = after_utc.astimezone(zone)
    weekdays = item.get("weekdays")
    every_days = int(item.get("every_days", 1))
    anchor_date = dt.date.fromisoformat(item["anchor_date"]) if every_days > 1 else None

    for offset in range(0, 3701):
        candidate_date = local_after.date() + dt.timedelta(days=offset)
        if weekdays is not None and candidate_date.weekday() not in weekdays:
            continue
        if anchor_date is not None and (candidate_date - anchor_date).days % every_days != 0:
            continue
        candidate_local = dt.datetime.combine(
            candidate_date, dt.time(hour=hour, minute=minute), tzinfo=zone
        )
        candidate_utc = candidate_local.astimezone(dt.timezone.utc)
        if candidate_utc > after_utc:
            return candidate_utc
    raise RuntimeError(f"Could not calculate next local schedule occurrence for {item.get('id')}")


def load_schedules() -> list[dict[str, Any]]:
    if not SCHEDULE_PATH.exists():
        logging.warning("No schedule file found: %s", SCHEDULE_PATH)
        return []
    try:
        root = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
        if not isinstance(root, dict) or not isinstance(root.get("schedules", []), list):
            raise ValueError("Schedule file must contain a schedules[] list")
        default_timezone = str(root.get("timezone", "UTC"))
        valid: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(root.get("schedules", [])):
            if not isinstance(item, dict):
                logging.error("Skipping malformed schedule at index %s: expected an object", index)
                continue
            sid = str(item.get("id", "")).strip()
            title = item.get("title")
            prompt = item.get("prompt")
            role = item.get("role", "Operations")
            task_type = item.get("task_type")
            item["timezone"] = str(item.get("timezone", default_timezone))
            has_local_clock = isinstance(item.get("at_local"), str)
            try:
                interval = int(item.get("every_minutes", 0))
            except (TypeError, ValueError):
                interval = 0
            valid_schedule = interval >= 1 and not has_local_clock
            if has_local_clock:
                try:
                    dt.time.fromisoformat(item["at_local"])
                    if len(item["at_local"]) != 5:
                        raise ValueError("at_local must use HH:MM")
                    ZoneInfo(item["timezone"])
                    weekdays = item.get("weekdays")
                    if weekdays is not None:
                        if (not isinstance(weekdays, list) or not weekdays
                                or any(type(day) is not int or day < 0 or day > 6 for day in weekdays)
                                or len(set(weekdays)) != len(weekdays)):
                            raise ValueError("weekdays must be unique ISO weekday numbers 0-6")
                        item["weekdays"] = sorted(weekdays)
                    else:
                        every_days = int(item.get("every_days", 1))
                        if every_days < 1:
                            raise ValueError("every_days must be >= 1")
                        if every_days > 1:
                            dt.date.fromisoformat(str(item.get("anchor_date", "")))
                        item["every_days"] = every_days
                    valid_schedule = True
                except (ValueError, TypeError, ZoneInfoNotFoundError):
                    valid_schedule = False
            if (not sid or sid in seen or not isinstance(title, str) or not title.strip()
                    or not isinstance(prompt, str) or not prompt.strip()
                    or not isinstance(role, str) or not role.strip()
                    or task_type not in ALLOWED_TASK_TYPES or not valid_schedule):
                logging.error("Skipping invalid or unsupported schedule at index %s (id=%r, task_type=%r)",
                              index, sid, task_type)
                continue
            item["id"] = sid
            item["role"] = role.strip()
            if interval >= 1 and not has_local_clock:
                item["every_minutes"] = interval
            seen.add(sid)
            valid.append(item)
        return valid
    except Exception:
        logging.exception("Could not parse schedule file")
        return []


def enqueue_due_schedules() -> None:
    now = utc_now()
    for item in load_schedules():
        sid = str(item["id"])
        with connect_db() as db:
            state = db.execute(
                "SELECT next_run_at FROM schedule_state WHERE schedule_id=?", (sid,)
            ).fetchone()

            if "at_local" in item:
                if state is None:
                    first_due = next_local_occurrence(item, now)
                    with connect_db() as db2:
                        db2.execute(
                            """INSERT OR IGNORE INTO schedule_state
                            (schedule_id,next_run_at,last_enqueued_at) VALUES(?,?,NULL)""",
                            (sid, first_due.isoformat(timespec="seconds")),
                        )
                    logging.info("Initialized local schedule %s; next run %s", sid, first_due.isoformat())
                    continue

                due_at = dt.datetime.fromisoformat(state["next_run_at"]).astimezone(dt.timezone.utc)
                if due_at > now:
                    continue

                # Catch up only the latest missed slot after downtime. Never dump
                # a multi-day backlog into the queue after a server restart.
                next_due = next_local_occurrence(item, due_at)
                latest_due = due_at
                skipped_slots = 0
                while next_due <= now:
                    latest_due = next_due
                    next_due = next_local_occurrence(item, latest_due)
                    skipped_slots += 1

                zone = ZoneInfo(str(item.get("timezone", "UTC")))
                local_slot = latest_due.astimezone(zone).strftime("%Y%m%dT%H%M")
                key = f"schedule:{sid}:{local_slot}"
                db.execute("BEGIN IMMEDIATE")
                try:
                    stamp = iso_now()
                    db.execute(
                        """INSERT OR IGNORE INTO jobs
                        (id, job_key, title, role, task_type, prompt, status, attempts,
                         run_after, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)""",
                        (uuid.uuid4().hex, key, item["title"], item.get("role", "Operations"),
                         item["task_type"], item["prompt"], stamp, stamp, stamp),
                    )
                    db.execute(
                        """UPDATE schedule_state SET next_run_at=?,last_enqueued_at=?
                        WHERE schedule_id=?""",
                        (next_due.isoformat(timespec="seconds"), stamp, sid),
                    )
                    db.commit()
                    logging.info(
                        "Enqueued local schedule %s for %s (skipped missed slots=%s)",
                        sid, latest_due.isoformat(), skipped_slots
                    )
                except Exception:
                    db.rollback()
                    logging.exception("Local schedule enqueue failed: %s", sid)
                continue

            interval = dt.timedelta(minutes=int(item["every_minutes"]))
            if state and dt.datetime.fromisoformat(state["next_run_at"]) > now:
                continue
            slot = int(now.timestamp() // interval.total_seconds())
            key = f"schedule:{sid}:{slot}"
            db.execute("BEGIN IMMEDIATE")
            try:
                stamp = iso_now()
                db.execute(
                    """INSERT OR IGNORE INTO jobs
                    (id, job_key, title, role, task_type, prompt, status, attempts,
                     run_after, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)""",
                    (uuid.uuid4().hex, key, item["title"], item.get("role", "Operations"),
                     item["task_type"], item["prompt"], stamp, stamp, stamp),
                )
                next_run = (now + interval).isoformat(timespec="seconds")
                db.execute(
                    """INSERT INTO schedule_state(schedule_id,next_run_at,last_enqueued_at)
                    VALUES(?,?,?) ON CONFLICT(schedule_id) DO UPDATE SET
                    next_run_at=excluded.next_run_at,last_enqueued_at=excluded.last_enqueued_at""",
                    (sid, next_run, stamp),
                )
                db.commit()
                logging.info("Enqueued schedule %s", sid)
            except Exception:
                db.rollback()
                logging.exception("Schedule enqueue failed: %s", sid)


def renew_job_lease(job_id: str) -> bool:
    """Extend the current worker's lease while a long model call is active."""
    now = utc_now()
    lease_until = (now + dt.timedelta(seconds=LOCK_SECONDS)).isoformat(timespec="seconds")
    with connect_db() as db:
        changed = db.execute(
            """UPDATE jobs SET lock_until=?,updated_at=?
            WHERE id=? AND status='running' AND locked_by=?""",
            (lease_until, now.isoformat(timespec="seconds"), job_id, INSTANCE_ID),
        ).rowcount
    return changed == 1


def lease_heartbeat_loop(job_id: str, stop_event: threading.Event,
                         lease_lost_event: threading.Event) -> None:
    """Keep active jobs leased; signal if this worker no longer owns the job."""
    interval = max(5, min(60, LOCK_SECONDS // 3))
    while not stop_event.wait(interval):
        try:
            if not renew_job_lease(job_id):
                logging.error("Lost job lease for %s; worker will not claim ownership again.", job_id)
                lease_lost_event.set()
                return
        except Exception:
            # Treat a transient database error as an observability event and retry.
            # finish_job/fail_job still enforce ownership atomically.
            logging.exception("Could not renew active job lease for %s", job_id)


def recover_stale_jobs() -> None:
    stamp = iso_now()
    with connect_db() as db:
        db.execute(
            """UPDATE jobs SET status=CASE WHEN attempts >= ? THEN 'failed' ELSE 'pending' END,
            locked_by=NULL, lock_until=NULL, error=COALESCE(error,'Worker lease expired'),
            updated_at=? WHERE status='running' AND lock_until < ?""",
            (MAX_ATTEMPTS, stamp, stamp),
        )

def claim_job() -> sqlite3.Row | None:
    now = utc_now()
    stamp = now.isoformat(timespec="seconds")
    lease = (now + dt.timedelta(seconds=LOCK_SECONDS)).isoformat(timespec="seconds")
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM jobs WHERE status='pending' AND run_after<=? ORDER BY run_after,created_at LIMIT 1",
            (stamp,),
        ).fetchone()
        if row is None:
            db.commit()
            return None
        changed = db.execute(
            """UPDATE jobs SET status='running', attempts=attempts+1, locked_by=?,
            lock_until=?, updated_at=? WHERE id=? AND status='pending'""",
            (INSTANCE_ID, lease, stamp, row["id"]),
        ).rowcount
        db.commit()
        if not changed:
            return None
        return db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()

def is_api_authorized(authorization: str, token: str | None = None) -> bool:
    expected = API_TOKEN if token is None else token
    if not expected:
        return False
    return hmac.compare_digest(str(authorization), f"Bearer {expected}")


def enqueue_api_job(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    task_type = str(payload.get("task_type", "")).strip()
    if task_type not in EXTERNAL_API_TASK_TYPES:
        raise ValueError("task_type is not enabled for external intake")
    title = str(payload.get("title", "")).strip()
    prompt = str(payload.get("prompt", "")).strip()
    role = str(payload.get("role", "Qudron Task Agent")).strip()
    key = str(payload.get("idempotency_key", "")).strip()
    if not title or len(title) > 160:
        raise ValueError("title is required and must be <= 160 characters")
    if not prompt or len(prompt) > 8000:
        raise ValueError("prompt is required and must be <= 8000 characters")
    if not role or len(role) > 100:
        raise ValueError("role is required and must be <= 100 characters")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,120}", key):
        raise ValueError("idempotency_key must be 8-120 safe ASCII characters")
    job_key = f"api:{key}"
    now = iso_now()
    job_id = uuid.uuid4().hex
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT id,status,title FROM jobs WHERE job_key=?", (job_key,)
        ).fetchone()
        if existing:
            db.commit()
            return dict(existing), False
        db.execute(
            """INSERT INTO jobs
            (id,job_key,title,role,task_type,prompt,status,attempts,run_after,created_at,updated_at)
            VALUES(?,?,?,?,?,?,'pending',0,?,?,?)""",
            (job_id, job_key, title, role, task_type, prompt, now, now, now),
        )
        db.commit()
    return {"id": job_id, "status": "pending", "title": title}, True


def infer_project(job: sqlite3.Row) -> str:
    haystack = f"{job['title']} {job['role']} {job['prompt']}".lower()
    for token, project in (
        ("cvpen", "cvpen"), ("vision guard", "vision_guard"),
        ("qudschool", "qudschool"), ("qudcopy", "qudcopy"),
        ("qudemy", "qudemy"), ("qudron", "qudron"),
    ):
        if token in haystack:
            return project
    return "qudsystem"


def remember_event(project: str, scope: str, category: str, content: str,
                   ttl_days: int | None = 14) -> None:
    if scope not in {"short", "long"}:
        raise ValueError("Memory scope must be short or long")
    safe_content = redact_sensitive_text(content).strip()[:4000]
    if not safe_content:
        return
    created = utc_now()
    expires = (created + dt.timedelta(days=ttl_days)).isoformat(timespec="seconds") if ttl_days else None
    with connect_db() as db:
        db.execute(
            """INSERT INTO memory_entries(id,project,scope,category,content,created_at,expires_at)
            VALUES(?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex, project, scope, category, safe_content,
             created.isoformat(timespec="seconds"), expires),
        )


def retrieve_memory_context(project: str, limit: int = 10) -> str:
    now = iso_now()
    short_limit = max(1, min(12, limit - 3))
    with connect_db() as db:
        db.execute("DELETE FROM memory_entries WHERE expires_at IS NOT NULL AND expires_at<=?", (now,))
        long_rows = db.execute(
            """SELECT scope,category,content,created_at FROM memory_entries
            WHERE project IN (?, 'portfolio') AND scope='long'
              AND (expires_at IS NULL OR expires_at>?)
            ORDER BY created_at DESC LIMIT 3""",
            (project, now),
        ).fetchall()
        short_rows = db.execute(
            """SELECT scope,category,content,created_at FROM memory_entries
            WHERE project IN (?, 'portfolio') AND scope='short'
              AND (expires_at IS NULL OR expires_at>?)
            ORDER BY created_at DESC LIMIT ?""",
            (project, now, short_limit),
        ).fetchall()
    rows = list(long_rows) + list(short_rows)
    if not rows:
        return ""
    lines = ["Relevant Qudron memory (sanitized operational notes; verify before relying):"]
    for row in rows:
        lines.append(f"- [{row['scope']}/{row['category']} @ {row['created_at']}] {row['content']}")
    return "\\n".join(lines)[:8000]


def any_model_profile_configured() -> bool:
    for prefix in ("LLM_FAST", "LLM_BALANCED", "LLM_REASONING"):
        base_url = (os.getenv(f"{prefix}_BASE_URL") or LLM_BASE_URL).strip()
        model = (os.getenv(f"{prefix}_MODEL") or LLM_MODEL).strip()
        if base_url and model:
            return True
    return False


def profile_cost_rates(profile: str) -> tuple[float | None, float | None]:
    prefix = {"fast": "LLM_FAST", "balanced": "LLM_BALANCED",
              "reasoning": "LLM_REASONING"}.get(profile, "LLM_BALANCED")
    def read_rate(name: str) -> float | None:
        raw = os.getenv(f"{prefix}_{name}") or os.getenv(f"LLM_{name}")
        if raw is None or not raw.strip():
            return None
        value = float(raw)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite number >= 0")
        return value
    return read_rate("INPUT_USD_PER_1M"), read_rate("OUTPUT_USD_PER_1M")


def configured_budget(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    value = float(raw)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite number > 0 when configured")
    return value


def acquire_model_call_slot(job_id: str, agent_id: str) -> str:
    """Acquire a cross-worker bounded provider-call slot from the shared SQLite DB."""
    deadline = time.monotonic() + MODEL_CALL_SLOT_TIMEOUT_SECONDS
    slot_ttl_seconds = max(300, LLM_TIMEOUT * 3)
    slot_id = uuid.uuid4().hex
    while True:
        now = utc_now()
        stamp = now.isoformat(timespec="seconds")
        lease_until = (now + dt.timedelta(seconds=slot_ttl_seconds)).isoformat(timespec="seconds")
        with connect_db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM model_call_slots WHERE lease_until<=?", (stamp,))
            active = db.execute("SELECT COUNT(*) FROM model_call_slots").fetchone()[0]
            if int(active) < MAX_CONCURRENT_MODEL_CALLS:
                db.execute(
                    """INSERT INTO model_call_slots(id,job_id,agent_id,lease_until,created_at)
                    VALUES(?,?,?,?,?)""",
                    (slot_id, job_id, agent_id, lease_until, stamp),
                )
                db.commit()
                return slot_id
            db.rollback()
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Qudron model-call concurrency limit ({MAX_CONCURRENT_MODEL_CALLS}) "
                f"remained full for {MODEL_CALL_SLOT_TIMEOUT_SECONDS}s."
            )
        time.sleep(0.2)


def release_model_call_slot(slot_id: str | None) -> None:
    if not slot_id:
        return
    with connect_db() as db:
        db.execute("DELETE FROM model_call_slots WHERE id=?", (slot_id,))


def reserve_model_budget(job_id: str, agent_id: str, profile: str, model: str,
                         payload_bytes: int, task_type: str | None = None) -> str | None:
    daily_budget = configured_budget("QUDRON_DAILY_MODEL_BUDGET_USD")
    monthly_budget = configured_budget("QUDRON_MONTHLY_MODEL_BUDGET_USD")
    cvpen_job_budget = (
        configured_budget("QUDRON_CVPEN_JOB_BUDGET_USD")
        if task_type == "cvpen_cv_creation" else None
    )
    if task_type == "cvpen_cv_creation" and cvpen_job_budget is None:
        raise RuntimeError(
            "CVPen creation is fail-closed until QUDRON_CVPEN_JOB_BUDGET_USD is configured. "
            "Set the per-order USD cap and exact model input/output rates before enabling 10-agent CV fulfilment."
        )
    require_model_budget = os.getenv("QUDRON_REQUIRE_MODEL_BUDGET", "true").strip().lower() not in {
        "0", "false", "no", "off"
    }
    if daily_budget is None and monthly_budget is None and cvpen_job_budget is None:
        if require_model_budget:
            raise RuntimeError(
                "Model calls are fail-closed until QUDRON_DAILY_MODEL_BUDGET_USD or "
                "QUDRON_MONTHLY_MODEL_BUDGET_USD is configured with exact input/output model prices. "
                "Set QUDRON_REQUIRE_MODEL_BUDGET=false only for isolated development."
            )
        return None
    input_rate, output_rate = profile_cost_rates(profile)
    profile_prefix = {"fast": "LLM_FAST", "balanced": "LLM_BALANCED",
                      "reasoning": "LLM_REASONING"}.get(profile, "LLM_BALANCED")
    if input_rate is None or output_rate is None:
        raise RuntimeError(
            "Qudron model budget is enabled, but exact input/output price rates are missing "
            f"for profile '{profile}'. Configure {profile_prefix}_INPUT_USD_PER_1M / "
            f"{profile_prefix}_OUTPUT_USD_PER_1M or default LLM_INPUT_USD_PER_1M / "
            "LLM_OUTPUT_USD_PER_1M before making billable requests."
        )
    # Use a deliberately conservative UTF-8 byte-based input estimate plus overhead.
    # Provider tokenization and billing differ; provider-side hard spend limits remain mandatory.
    estimated_input_tokens = max(0, payload_bytes) + 256
    estimated_cost = (
        estimated_input_tokens * input_rate + MAX_OUTPUT_TOKENS * output_rate
    ) / 1_000_000
    now = utc_now()
    stamp = now.isoformat(timespec="seconds")
    reservation_id = uuid.uuid4().hex
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        # Release abandoned reservations after process crashes or provider timeouts.
        # The TTL is at least 10 minutes and at least 3x the configured HTTP timeout.
        reservation_cutoff = (
            now - dt.timedelta(seconds=max(600, LLM_TIMEOUT * 3))
        ).isoformat(timespec="seconds")
        db.execute(
            "DELETE FROM llm_usage_reservations WHERE created_at<?",
            (reservation_cutoff,),
        )
        if cvpen_job_budget is not None:
            job_spent = db.execute(
                "SELECT COALESCE(SUM(cost_usd),0) FROM llm_usage WHERE job_id=?",
                (job_id,),
            ).fetchone()[0]
            job_reserved = db.execute(
                "SELECT COALESCE(SUM(reserved_cost_usd),0) FROM llm_usage_reservations WHERE job_id=?",
                (job_id,),
            ).fetchone()[0]
            if float(job_spent or 0) + float(job_reserved or 0) + estimated_cost > cvpen_job_budget:
                db.rollback()
                raise RuntimeError(
                    f"CVPen per-order model budget reached for job {job_id}; "
                    f"the next estimated call would exceed {cvpen_job_budget:.2f} USD."
                )
        if daily_budget is not None:
            day = now.date().isoformat() + "%"
            spent = db.execute(
                "SELECT COALESCE(SUM(cost_usd),0) FROM llm_usage WHERE created_at LIKE ?",
                (day,),
            ).fetchone()[0]
            reserved = db.execute(
                "SELECT COALESCE(SUM(reserved_cost_usd),0) FROM llm_usage_reservations WHERE created_at LIKE ?",
                (day,),
            ).fetchone()[0]
            if float(spent or 0) + float(reserved or 0) + estimated_cost > daily_budget:
                db.rollback()
                raise RuntimeError(
                    f"Qudron daily model budget reached; estimated call cost {estimated_cost:.6f} USD "
                    f"would exceed configured cap {daily_budget:.2f} USD."
                )
        if monthly_budget is not None:
            month = now.strftime("%Y-%m") + "%"
            spent = db.execute(
                "SELECT COALESCE(SUM(cost_usd),0) FROM llm_usage WHERE created_at LIKE ?",
                (month,),
            ).fetchone()[0]
            reserved = db.execute(
                "SELECT COALESCE(SUM(reserved_cost_usd),0) FROM llm_usage_reservations WHERE created_at LIKE ?",
                (month,),
            ).fetchone()[0]
            if float(spent or 0) + float(reserved or 0) + estimated_cost > monthly_budget:
                db.rollback()
                raise RuntimeError(
                    f"Qudron monthly model budget reached; estimated call cost {estimated_cost:.6f} USD "
                    f"would exceed configured cap {monthly_budget:.2f} USD."
                )
        db.execute(
            """INSERT INTO llm_usage_reservations
            (id,job_id,agent_id,profile,reserved_cost_usd,created_at)
            VALUES(?,?,?,?,?,?)""",
            (reservation_id, job_id, agent_id, profile, estimated_cost, stamp),
        )
        db.commit()
    return reservation_id


def record_model_usage(job_id: str, agent_id: str, profile: str, model: str,
                       response_data: dict[str, Any], reservation_id: str | None) -> None:
    usage = response_data.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    def safe_count(value: Any) -> int | None:
        try:
            number = int(value)
            return number if number >= 0 else None
        except (TypeError, ValueError):
            return None
    prompt_tokens = safe_count(prompt_tokens)
    completion_tokens = safe_count(completion_tokens)
    total_tokens = safe_count(total_tokens)
    input_rate, output_rate = profile_cost_rates(profile)
    provider_cost = usage.get("cost", usage.get("total_cost"))
    cost_usd: float | None = None
    try:
        candidate = float(provider_cost)
        if math.isfinite(candidate) and candidate >= 0:
            cost_usd = candidate
    except (TypeError, ValueError):
        if prompt_tokens is not None and completion_tokens is not None and input_rate is not None and output_rate is not None:
            cost_usd = (
                prompt_tokens * input_rate + completion_tokens * output_rate
            ) / 1_000_000
    stamp = iso_now()
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        if cost_usd is None and reservation_id:
            reserved = db.execute(
                "SELECT reserved_cost_usd FROM llm_usage_reservations WHERE id=?",
                (reservation_id,),
            ).fetchone()
            if reserved is not None:
                cost_usd = float(reserved["reserved_cost_usd"])
        db.execute(
            """INSERT INTO llm_usage
            (id,job_id,agent_id,profile,model,prompt_tokens,completion_tokens,total_tokens,cost_usd,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex, job_id, agent_id, profile, model, prompt_tokens,
             completion_tokens, total_tokens, cost_usd, stamp),
        )
        if reservation_id:
            db.execute("DELETE FROM llm_usage_reservations WHERE id=?", (reservation_id,))
        db.commit()


def release_model_budget_reservation(reservation_id: str | None) -> None:
    if not reservation_id:
        return
    with connect_db() as db:
        db.execute("DELETE FROM llm_usage_reservations WHERE id=?", (reservation_id,))


def model_usage_snapshot(recent_limit: int = 20) -> dict[str, Any]:
    now = utc_now()
    day = now.date().isoformat() + "%"
    month = now.strftime("%Y-%m") + "%"
    with connect_db() as db:
        totals = db.execute(
            """SELECT COUNT(*) calls,
               COALESCE(SUM(prompt_tokens),0) prompt_tokens,
               COALESCE(SUM(completion_tokens),0) completion_tokens,
               COALESCE(SUM(total_tokens),0) total_tokens,
               SUM(cost_usd) cost_usd
            FROM llm_usage WHERE created_at LIKE ?""", (day,)
        ).fetchone()
        month_totals = db.execute(
            """SELECT COUNT(*) calls,
               COALESCE(SUM(prompt_tokens),0) prompt_tokens,
               COALESCE(SUM(completion_tokens),0) completion_tokens,
               COALESCE(SUM(total_tokens),0) total_tokens,
               SUM(cost_usd) cost_usd
            FROM llm_usage WHERE created_at LIKE ?""", (month,)
        ).fetchone()
        pending_reserved = db.execute(
            "SELECT COALESCE(SUM(reserved_cost_usd),0) FROM llm_usage_reservations"
        ).fetchone()[0]
        recent = db.execute(
            """SELECT job_id,agent_id,profile,model,prompt_tokens,completion_tokens,
               total_tokens,cost_usd,created_at FROM llm_usage
               ORDER BY created_at DESC LIMIT ?""",
            (max(1, min(100, recent_limit)),),
        ).fetchall()
    return {
        "day_utc": now.date().isoformat(),
        "month_utc": now.strftime("%Y-%m"),
        "daily": dict(totals),
        "monthly": dict(month_totals),
        "reserved_in_flight_usd": float(pending_reserved or 0),
        "daily_budget_usd": configured_budget("QUDRON_DAILY_MODEL_BUDGET_USD"),
        "monthly_budget_usd": configured_budget("QUDRON_MONTHLY_MODEL_BUDGET_USD"),
        "cost_note": "Costs are provider-reported or calculated from configured per-million-token rates; null means the provider usage or rate was unavailable.",
        "recent": [dict(row) for row in recent],
    }


def call_llm(job: sqlite3.Row, agent: dict[str, Any], instruction: str,
             prior_context: str, memory_context: str) -> str:
    profile = str(agent.get("profile", "balanced")).lower()
    prefix = {"fast": "LLM_FAST", "balanced": "LLM_BALANCED",
              "reasoning": "LLM_REASONING"}.get(profile, "LLM_BALANCED")
    base_url = (os.getenv(f"{prefix}_BASE_URL") or LLM_BASE_URL).rstrip("/")
    api_key = os.getenv(f"{prefix}_API_KEY") or LLM_API_KEY
    model = os.getenv(f"{prefix}_MODEL") or LLM_MODEL
    if not base_url or not model:
        raise RuntimeError(
            f"LLM profile '{profile}' is not configured: set {prefix}_BASE_URL and "
            f"{prefix}_MODEL or the default LLM_BASE_URL and LLM_MODEL."
        )
    system = (
        "You are a specialist AI worker inside Qudron, the operating system for QudSystem. "
        "Brand values: trust, quality, speed, commitment; Made in Egypt. "
        "Never invent evidence, testimonials, prices, metrics, citations, or completed work. "
        "Mark assumptions and facts requiring verification. Create drafts and analysis only. "
        "Never claim content was published, a prospect was contacted, or money was moved. "
        f"Your specialist identity is {agent.get('name', agent.get('id', 'Specialist'))}. "
        f"Responsibilities: {agent.get('responsibilities', 'Complete the assigned specialist stage.')}"
    )
    user = (
        f"Role: {job['role']}\nTask type: {job['task_type']}\nTitle: {job['title']}\n\n"
        f"Original task and instructions:\n{str(job['prompt'])[:MAX_INPUT_CHARS]}\n\n"
        f"Current stage instructions:\n{instruction}\n\n"
        f"Prior stage context:\n{str(prior_context or '[none]')[-MAX_INPUT_CHARS // 2:]}\n\n"
        f"Relevant memory:\n{str(memory_context or '[none]')[-4000:]}\n\n"
        "Return a practical deliverable. Use Egyptian Arabic by default for Arabic social/video "
        "copy unless instructed otherwise. Do not expose hidden reasoning."
    )
    payload = json.dumps({
        "model": model,
        "temperature": 0.3 if profile == "reasoning" else 0.4,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode("utf-8")
    reservation_id = reserve_model_budget(
        str(job["id"]), str(agent.get("id", "unknown")), profile, model, len(payload),
        str(job["task_type"])
    )
    slot_id = None
    try:
        slot_id = acquire_model_call_slot(
            str(job["id"]), str(agent.get("id", "unknown"))
        )
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            f"{base_url}/chat/completions", data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=LLM_TIMEOUT) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1500]
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        record_model_usage(
            str(job["id"]), str(agent.get("id", "unknown")), profile, model, data, reservation_id
        )
        reservation_id = None
    finally:
        release_model_call_slot(slot_id)
        release_model_budget_reservation(reservation_id)
    choices = data.get("choices") or []
    answer = choices[0].get("message", {}).get("content") if choices else None
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("LLM returned an empty response")
    return answer.strip()


def execute_job_swarm(job: sqlite3.Row) -> str:
    project = infer_project(job)
    memory_context = retrieve_memory_context(project)
    registry = AGENT_REGISTRY or load_agent_registry(AGENT_REGISTRY_PATH)
    if SWARM_ENABLED and str(job["task_type"]) == "cvpen_cv_creation":
        max_agents = MAX_CVPEN_AGENTS
    else:
        max_agents = MAX_SWARM_AGENTS if SWARM_ENABLED else 1

    def invoke(agent: dict[str, Any], instruction: str, prior: str) -> str:
        return call_llm(job, agent, instruction, prior, memory_context)

    return execute_swarm(
        {"task_type": job["task_type"], "title": job["title"], "prompt": job["prompt"]},
        invoke, registry=registry, memory_context=memory_context, max_agents=max_agents,
        max_parallel_reviews=MAX_PARALLEL_REVIEWS if SWARM_ENABLED else 1,
    )


def safe_slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9\u0600-\u06FF_-]+", "-", value).strip("-_")
    return value[:60] or "task"

def save_result(job: sqlite3.Row, result: str) -> str:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().strftime("%Y%m%d-%H%M%S")
    path = REPORTS_DIR / f"{stamp}-{safe_slug(job['title'])}-{job['id'][:8]}.md"
    header = (
        "---\n"
        f"title: {json.dumps(job['title'], ensure_ascii=False)}\n"
        f"role: {json.dumps(job['role'], ensure_ascii=False)}\n"
        f"task_type: {job['task_type']}\n"
        f"created_at_utc: {iso_now()}\n"
        "status: draft_for_review\n---\n\n"
    )
    path.write_text(header + result + "\n", encoding="utf-8")
    return str(path)

def finish_job(job_id: str, result_path: str) -> bool:
    with connect_db() as db:
        changed = db.execute(
            """UPDATE jobs SET status='completed',result_path=?,error=NULL,
            locked_by=NULL,lock_until=NULL,updated_at=?
            WHERE id=? AND status='running' AND locked_by=?""",
            (result_path, iso_now(), job_id, INSTANCE_ID),
        ).rowcount
    return changed == 1

def fail_job(job: sqlite3.Row, exc: Exception) -> None:
    message = redact_sensitive_text(f"{type(exc).__name__}: {exc}")[:3000]
    terminal = int(job["attempts"]) >= MAX_ATTEMPTS
    delay = min(3600, 15 * (2 ** max(0, int(job["attempts"]) - 1)))
    run_after = (utc_now() + dt.timedelta(seconds=delay)).isoformat(timespec="seconds")
    with connect_db() as db:
        changed = db.execute(
            """UPDATE jobs SET status=?,run_after=?,error=?,locked_by=NULL,
            lock_until=NULL,updated_at=? WHERE id=? AND status='running' AND locked_by=?""",
            ("failed" if terminal else "pending", run_after, message, iso_now(),
             job["id"], INSTANCE_ID),
        ).rowcount
    if changed != 1:
        logging.warning("Ignoring failure from a worker that no longer owns job %s", job["id"])
        return

    try:
        remember_event(infer_project(job), "short", "job_failure",
                       f"Task {job['title']} failed on attempt {job['attempts']}/{MAX_ATTEMPTS}: {message}")
    except Exception:
        logging.exception("Could not save failure event to memory")

    # Create exactly one internal same-day triage task after a terminal failure.
    # Triage failures never recursively create more triage tasks.
    if terminal and str(job["task_type"]) != "incident_triage":
        incident_key = f"incident-triage:{job['id']}"
        incident_prompt = (
            "A Qudron task exhausted its configured retry attempts. Perform same-day, read-only "
            "incident triage. Identify likely root causes from the supplied error, distinguish "
            "evidence from hypotheses, propose a safe correction, a regression test, and a rollback "
            "plan. Do not change production systems, credentials, payment state, customer records, "
            "or external accounts. Do not contact users or publish content.\n\n"
            f"Failed task title: {str(job['title'])[:160]}\n"
            f"Original role: {str(job['role'])[:100]}\n"
            f"Task type: {str(job['task_type'])[:80]}\n"
            f"Attempts: {job['attempts']}/{MAX_ATTEMPTS}\n"
            f"Error: {message}"
        )[:8000]
        try:
            with connect_db() as db:
                db.execute(
                    """INSERT OR IGNORE INTO jobs
                    (id,job_key,title,role,task_type,prompt,status,attempts,run_after,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,'pending',0,?,?,?)""",
                    (uuid.uuid4().hex, incident_key,
                     f"Same-day incident triage: {str(job['title'])[:100]}",
                     "Reliability, QA & Evidence Review Team", "incident_triage",
                     incident_prompt, iso_now(), iso_now(), iso_now()),
                )
            remember_event(infer_project(job), "short", "incident_queued",
                           f"Terminal failure queued for same-day incident triage: {job['title']}")
        except Exception:
            logging.exception("Could not enqueue incident triage for job %s", job["id"])

    logging.error("Job %s failed on attempt %s/%s: %s",
                  job["id"], job["attempts"], MAX_ATTEMPTS, message)

def worker_loop() -> None:
    while not STOP.is_set():
        job = claim_job()
        if job is None:
            STOP.wait(POLL_SECONDS)
            continue
        logging.info("Started %s | %s | %s", job["id"], job["role"], job["title"])
        lease_stop = threading.Event()
        lease_lost = threading.Event()
        lease_thread = threading.Thread(
            target=lease_heartbeat_loop, args=(job["id"], lease_stop, lease_lost),
            name=f"lease-{job['id'][:8]}", daemon=True
        )
        lease_thread.start()
        try:
            result = execute_job_swarm(job)
            if lease_lost.is_set():
                raise RuntimeError("Worker lost job ownership during agent execution")
            path = save_result(job, result)
            if not finish_job(job["id"], path):
                raise RuntimeError("Worker no longer owns job; completion was not committed")
            project = infer_project(job)
            remember_event(project, "short", "job_completed",
                           f"Completed {job['task_type']} task: {job['title']}. Artifact stored at {path}.")
            if "weekly-deep-strategy" in str(job["job_key"] or ""):
                remember_event("portfolio", "long", "weekly_strategy", result[:3500], ttl_days=None)
            logging.info("Completed %s -> %s", job["id"], path)
        except Exception as exc:
            fail_job(job, exc)
        finally:
            lease_stop.set()
            lease_thread.join(timeout=5)

def status_snapshot() -> dict[str, Any]:
    with connect_db() as db:
        counts = {r["status"]: r["n"] for r in db.execute(
            "SELECT status,COUNT(*) n FROM jobs GROUP BY status"
        )}
        latest = db.execute(
            "SELECT title,status,updated_at,error FROM jobs ORDER BY updated_at DESC LIMIT 5"
        ).fetchall()
    return {
        "service": "qudron-runtime", "instance": INSTANCE_ID, "time_utc": iso_now(),
        "counts": counts, "latest_jobs": [dict(r) for r in latest],
        "llm_configured": any_model_profile_configured(),
        "swarm_enabled": SWARM_ENABLED,
        "max_agents_per_task": MAX_SWARM_AGENTS if SWARM_ENABLED else 1,
        "max_agents_per_cvpen_job": MAX_CVPEN_AGENTS if SWARM_ENABLED else 1,
        "max_parallel_reviews": MAX_PARALLEL_REVIEWS if SWARM_ENABLED else 1,
        "max_concurrent_model_calls": MAX_CONCURRENT_MODEL_CALLS,
        "registered_agents": len(AGENT_REGISTRY.get("agents", [])),
        "registered_teams": len(AGENT_REGISTRY.get("teams", {})),
        "teams": sorted((AGENT_REGISTRY.get("teams") or {}).keys()),
    }

class HealthHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: int, content: str, content_type: str = "text/markdown; charset=utf-8") -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            # Keep the unauthenticated container probe deliberately non-sensitive.
            self._send_json(200, {"ok": True, "service": "qudron-runtime"})
            return
        if self.path == "/status":
            if not is_api_authorized(self.headers.get("Authorization", "")):
                self._send_json(503 if not API_TOKEN else 401, {"error": "unauthorized_or_api_token_not_configured"})
                return
            self._send_json(200, status_snapshot())
            return
        if self.path == "/usage":
            if not is_api_authorized(self.headers.get("Authorization", "")):
                self._send_json(503 if not API_TOKEN else 401, {"error": "unauthorized_or_api_token_not_configured"})
                return
            self._send_json(200, model_usage_snapshot())
            return
        if self.path.startswith("/jobs/"):
            if not is_api_authorized(self.headers.get("Authorization", "")):
                self._send_json(503 if not API_TOKEN else 401, {"error": "unauthorized_or_api_token_not_configured"})
                return
            parts = self.path.strip("/").split("/")
            if len(parts) not in {2, 3} or parts[0] != "jobs" or not parts[1]:
                self._send_json(400, {"error": "invalid_job_route"})
                return
            job_id = parts[1]
            wants_result = len(parts) == 3 and parts[2] == "result"
            if len(parts) == 3 and not wants_result:
                self._send_json(404, {"error": "route_not_found"})
                return
            with connect_db() as db:
                row = db.execute(
                    """SELECT id,title,status,attempts,run_after,result_path,error,updated_at
                    FROM jobs WHERE id=?""", (job_id,)
                ).fetchone()
            if row is None:
                self._send_json(404, {"error": "job_not_found"})
                return
            if wants_result:
                if row["status"] != "completed" or not row["result_path"]:
                    self._send_json(409, {"error": "job_result_not_ready", "status": row["status"]})
                    return
                try:
                    root = REPORTS_DIR.resolve()
                    report_path = Path(row["result_path"]).resolve()
                    if not report_path.is_relative_to(root) or not report_path.is_file():
                        self._send_json(404, {"error": "job_result_not_found"})
                        return
                    if report_path.stat().st_size > 1_000_000:
                        self._send_json(413, {"error": "job_result_too_large"})
                        return
                    result = report_path.read_text(encoding="utf-8")
                except OSError:
                    self._send_json(404, {"error": "job_result_not_found"})
                    return
                self._send_text(200, result)
                return
            status_payload = {
                "id": row["id"], "title": row["title"], "status": row["status"],
                "attempts": row["attempts"], "run_after": row["run_after"],
                "error": row["error"], "updated_at": row["updated_at"],
                "result_available": bool(row["status"] == "completed" and row["result_path"]),
                "result_endpoint": f"/jobs/{job_id}/result" if row["status"] == "completed" and row["result_path"] else None,
            }
            self._send_json(200, status_payload)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/jobs":
            self.send_error(404)
            return
        if not is_api_authorized(self.headers.get("Authorization", "")):
            self._send_json(503 if not API_TOKEN else 401, {"error": "unauthorized_or_api_token_not_configured"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "invalid_content_length"})
            return
        if length < 1 or length > MAX_API_BODY_BYTES:
            self._send_json(413, {"error": "invalid_or_oversized_body"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            item, created = enqueue_api_job(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid_json"})
            return
        except ValueError as exc:
            self._send_json(422, {"error": str(exc)})
            return
        self._send_json(202 if created else 200, {
            "created": created, "job": item,
            "note": "External intake is for internal drafts/research only; CV customer data and payment events are not enabled."
        })

    def log_message(self, *_: Any) -> None:
        return


def run() -> None:
    setup_logging()
    init_db()
    global AGENT_REGISTRY
    AGENT_REGISTRY = load_agent_registry(AGENT_REGISTRY_PATH)
    logging.info("Loaded %s specialist agents across %s teams.",
                 len(AGENT_REGISTRY.get("agents", [])), len(AGENT_REGISTRY.get("teams", {})))
    logging.info("Starting Qudron runtime: %s", INSTANCE_ID)
    logging.info("DB=%s reports=%s workers=%s", DB_PATH, REPORTS_DIR, WORKERS)
    if not any_model_profile_configured():
        logging.warning("No LLM model profile is configured. Jobs will retry; no fake outputs are generated.")

    def handle_signal(signum: int, _frame: Any) -> None:
        logging.warning("Signal %s received; stopping gracefully.", signum)
        STOP.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    health = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
    threading.Thread(target=health.serve_forever, name="health", daemon=True).start()

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="agent") as pool:
        futures = [pool.submit(worker_loop) for _ in range(WORKERS)]
        try:
            while not STOP.is_set():
                recover_stale_jobs()
                enqueue_due_schedules()
                with connect_db() as db:
                    db.execute(
                        """INSERT INTO heartbeats(instance_id,updated_at,worker_count)
                        VALUES(?,?,?) ON CONFLICT(instance_id) DO UPDATE SET
                        updated_at=excluded.updated_at,worker_count=excluded.worker_count""",
                        (INSTANCE_ID, iso_now(), WORKERS),
                    )
                STOP.wait(20)
        finally:
            STOP.set()
            health.shutdown()
            for future in futures:
                try:
                    future.result(timeout=LOCK_SECONDS + 10)
                except Exception:
                    logging.exception("Worker shutdown issue")
    logging.info("Qudron runtime stopped.")

if __name__ == "__main__":
    run()
