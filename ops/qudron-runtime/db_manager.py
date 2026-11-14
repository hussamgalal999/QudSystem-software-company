"""
Qudron Database Management Module.
Handles schema initialization, connections, and common job queries.
"""
from __future__ import annotations

import sqlite3
import os
import uuid
import logging
from pathlib import Path
from typing import Any

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()

class QudronDBManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(
            self.db_path, timeout=30, isolation_level=None, factory=ClosingConnection
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def init_db(self) -> None:
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, job_key TEXT UNIQUE, title TEXT NOT NULL,
              role TEXT NOT NULL, task_type TEXT NOT NULL, prompt TEXT NOT NULL,
              data_class TEXT NOT NULL DEFAULT 'internal',
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
            CREATE TABLE IF NOT EXISTS llm_call_attempts (
              id TEXT PRIMARY KEY, job_id TEXT NOT NULL, agent_id TEXT NOT NULL,
              profile TEXT NOT NULL, provider_id TEXT NOT NULL, model TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'in_flight',
              billing_state TEXT NOT NULL DEFAULT 'pending',
              estimated_cost_usd REAL, reported_cost_usd REAL,
              error_class TEXT, started_at TEXT NOT NULL, finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_llm_attempts_started
              ON llm_call_attempts(started_at);
            CREATE INDEX IF NOT EXISTS idx_llm_attempts_job
              ON llm_call_attempts(job_id, started_at);
            CREATE INDEX IF NOT EXISTS idx_llm_attempts_billing
              ON llm_call_attempts(billing_state, started_at);
            CREATE INDEX IF NOT EXISTS idx_llm_reservations_created
              ON llm_usage_reservations(created_at);
            CREATE TABLE IF NOT EXISTS model_call_slots (
              id TEXT PRIMARY KEY, job_id TEXT NOT NULL, agent_id TEXT NOT NULL,
              lease_until TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_model_call_slots_lease
              ON model_call_slots(lease_until);
            """)
            job_columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            if "data_class" not in job_columns:
                db.execute("ALTER TABLE jobs ADD COLUMN data_class TEXT NOT NULL DEFAULT 'internal'")
            db.execute("UPDATE jobs SET data_class='internal' WHERE data_class IS NULL OR TRIM(data_class)=''")
