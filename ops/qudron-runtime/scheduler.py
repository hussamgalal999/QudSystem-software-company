"""
Qudron Scheduler Module.
Handles loading schedules, calculating next occurrences, and enqueuing jobs.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
import sqlite3
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

def next_local_occurrence(item: dict[str, Any], after_utc: dt.datetime) -> dt.datetime:
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

class QudronScheduler:
    def __init__(self, schedule_path: Path, db_connector: Any, allowed_task_types: set[str]):
        self.schedule_path = schedule_path
        self.db_connector = db_connector
        self.allowed_task_types = allowed_task_types

    def load_schedules(self) -> list[dict[str, Any]]:
        if not self.schedule_path.exists():
            logging.warning("No schedule file found: %s", self.schedule_path)
            return []
        try:
            root = json.loads(self.schedule_path.read_text(encoding="utf-8"))
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
                        or task_type not in self.allowed_task_types or not valid_schedule):
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

    def enqueue_due_schedules(self, now: dt.datetime, iso_now_fn: Any) -> None:
        for item in self.load_schedules():
            sid = str(item["id"])
            with self.db_connector() as db:
                state = db.execute(
                    "SELECT next_run_at FROM schedule_state WHERE schedule_id=?", (sid,)
                ).fetchone()

                if "at_local" in item:
                    if state is None:
                        first_due = next_local_occurrence(item, now)
                        db.execute(
                            """INSERT OR IGNORE INTO schedule_state
                            (schedule_id,next_run_at,last_enqueued_at) VALUES(?,?,NULL)""",
                            (sid, first_due.isoformat(timespec="seconds")),
                        )
                        logging.info("Initialized local schedule %s; next run %s", sid, first_due.isoformat())
                        continue

                    due_at = dt.datetime.fromisoformat(state["next_run_at"]).astimezone(dt.timezone.utc)
                    if due_at > now:
                        continue

                    next_due = next_local_occurrence(item, due_at)
                    latest_due = due_at
                    while next_due <= now:
                        latest_due = next_due
                        next_due = next_local_occurrence(item, latest_due)

                    zone = ZoneInfo(str(item.get("timezone", "UTC")))
                    local_slot = latest_due.astimezone(zone).strftime("%Y%m%dT%H%M")
                    key = f"schedule:{sid}:{local_slot}"
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        stamp = iso_now_fn()
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
                    except Exception:
                        db.rollback()
                        logging.exception("Failed to enqueue local schedule %s", sid)
                
                elif "every_minutes" in item:
                    interval = int(item["every_minutes"])
                    if state is None:
                        next_run = now + dt.timedelta(minutes=interval)
                        db.execute(
                            """INSERT OR IGNORE INTO schedule_state
                            (schedule_id,next_run_at,last_enqueued_at) VALUES(?,?,NULL)""",
                            (sid, next_run.isoformat(timespec="seconds")),
                        )
                        continue

                    due_at = dt.datetime.fromisoformat(state["next_run_at"]).astimezone(dt.timezone.utc)
                    if due_at > now:
                        continue

                    next_run = now + dt.timedelta(minutes=interval)
                    key = f"schedule:{sid}:{due_at.strftime('%Y%m%dT%H%M')}"
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        stamp = iso_now_fn()
                        db.execute(
                            """INSERT OR IGNORE INTO jobs
                            (id, job_key, title, role, task_type, prompt, status, attempts,
                             run_after, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)""",
                            (uuid.uuid4().hex, key, item["title"], item.get("role", "Operations"),
                             item["task_type"], item["prompt"], due_at.isoformat(timespec="seconds"), stamp, stamp),
                        )
                        db.execute(
                            """UPDATE schedule_state SET next_run_at=?,last_enqueued_at=?
                            WHERE schedule_id=?""",
                            (next_run.isoformat(timespec="seconds"), stamp, sid),
                        )
                    except Exception:
                        db.rollback()
                        logging.exception("Failed to enqueue interval schedule %s", sid)
