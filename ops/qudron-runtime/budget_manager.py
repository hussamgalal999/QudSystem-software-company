"""
Qudron Budget and Concurrency Management Module.
Handles token costs, reservations, and model-call slots.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import os
import time
import uuid
import sqlite3
from typing import Any, Optional
from urllib.parse import urlsplit

class QudronBudgetManager:
    def __init__(self, db_connector: Any, max_concurrent_calls: int, slot_timeout: int):
        self.db_connector = db_connector
        self.max_concurrent_calls = max_concurrent_calls
        self.slot_timeout = slot_timeout

    def profile_cost_rates(self, profile: str) -> tuple[float | None, float | None]:
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

    def configured_budget(self, name: str) -> float | None:
        raw = os.getenv(name, "").strip()
        if not raw:
            return None
        value = float(raw)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a finite number > 0 when configured")
        return value

    def acquire_model_call_slot(self, job_id: str, agent_id: str) -> str:
        deadline = time.monotonic() + self.slot_timeout
        slot_ttl_seconds = 600 # Default
        slot_id = uuid.uuid4().hex
        while True:
            now = dt.datetime.now(dt.timezone.utc)
            stamp = now.isoformat(timespec="seconds")
            lease_until = (now + dt.timedelta(seconds=slot_ttl_seconds)).isoformat(timespec="seconds")
            with self.db_connector() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM model_call_slots WHERE lease_until<=?", (stamp,))
                active = db.execute("SELECT COUNT(*) FROM model_call_slots").fetchone()[0]
                if int(active) < self.max_concurrent_calls:
                    db.execute(
                        """INSERT INTO model_call_slots(id,job_id,agent_id,lease_until,created_at)
                        VALUES(?,?,?,?,?)""",
                        (slot_id, job_id, agent_id, lease_until, stamp),
                    )
                    db.commit()
                    return slot_id
                db.rollback()
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Qudron model-call concurrency limit ({self.max_concurrent_calls}) full.")
            time.sleep(0.2)

    def release_model_call_slot(self, slot_id: str | None) -> None:
        if not slot_id:
            return
        with self.db_connector() as db:
            db.execute("DELETE FROM model_call_slots WHERE id=?", (slot_id,))
