"""Durable per-agent memory, resumable stage checkpoints, and external-run ledger.

The store shares Qudron's SQLite database file but owns its own short-lived
connections. Agent outputs are checkpointed by job + role + stage so a worker
restart does not repeat completed stages. Sensitive workflows can disable
output checkpointing while retaining non-sensitive execution metadata.
"""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any, Iterator


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class ContinuityStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def ensure_schema(self) -> None:
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS agent_runs (
              job_id TEXT NOT NULL,
              project TEXT NOT NULL,
              agent_id TEXT NOT NULL,
              stage TEXT NOT NULL,
              status TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0,
              output TEXT,
              error TEXT,
              started_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(job_id, agent_id, stage)
            );
            CREATE INDEX IF NOT EXISTS idx_agent_runs_job
              ON agent_runs(job_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_runs_active
              ON agent_runs(status, updated_at DESC);
            CREATE TABLE IF NOT EXISTS agent_memories (
              id TEXT PRIMARY KEY,
              project TEXT NOT NULL,
              agent_id TEXT NOT NULL,
              scope TEXT NOT NULL,
              category TEXT NOT NULL,
              content TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_agent_memories_lookup
              ON agent_memories(project, agent_id, scope, created_at DESC);
            CREATE TABLE IF NOT EXISTS continuity_events (
              id TEXT PRIMARY KEY,
              job_id TEXT,
              project TEXT NOT NULL,
              agent_id TEXT,
              event_type TEXT NOT NULL,
              detail TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_continuity_events_job
              ON continuity_events(job_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS external_agent_tasks (
              id TEXT PRIMARY KEY,
              provider TEXT NOT NULL,
              external_task_id TEXT NOT NULL,
              local_job_id TEXT,
              agent_id TEXT NOT NULL,
              status TEXT NOT NULL,
              task_url TEXT,
              last_event_id TEXT,
              result_json TEXT,
              error TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(provider, external_task_id)
            );
            CREATE INDEX IF NOT EXISTS idx_external_tasks_local_job
              ON external_agent_tasks(local_job_id, updated_at DESC);
            """)

    def begin_stage(
        self, *, job_id: str, project: str, agent_id: str, stage: str
    ) -> dict[str, Any] | None:
        """Return a completed checkpoint, or mark the stage running and return None."""
        now = _now()
        with self.connect() as db:
            row = db.execute(
                "SELECT status,output,attempts FROM agent_runs "
                "WHERE job_id=? AND agent_id=? AND stage=?",
                (job_id, agent_id, stage),
            ).fetchone()
            if row and row["status"] == "completed" and row["output"] is not None:
                db.execute(
                    "INSERT INTO continuity_events VALUES(?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, job_id, project, agent_id, "stage_resumed_from_checkpoint",
                     stage, now),
                )
                return {"output": str(row["output"]), "attempts": int(row["attempts"])}
            attempts = (int(row["attempts"]) + 1) if row else 1
            db.execute(
                """INSERT INTO agent_runs
                   (job_id,project,agent_id,stage,status,attempts,output,error,started_at,updated_at)
                   VALUES(?,?,?,?,? ,?,NULL,NULL,?,?)
                   ON CONFLICT(job_id,agent_id,stage) DO UPDATE SET
                     status='running',attempts=excluded.attempts,error=NULL,updated_at=excluded.updated_at""",
                (job_id, project, agent_id, stage, "running", attempts, now, now),
            )
            db.execute(
                "INSERT INTO continuity_events VALUES(?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, job_id, project, agent_id,
                 "stage_started" if attempts == 1 else "stage_retried", stage, now),
            )
        return None

    def complete_stage(
        self, *, job_id: str, project: str, agent_id: str, stage: str,
        output: str | None, memory_note: str | None = None,
        memory_ttl_days: int = 30,
    ) -> None:
        now = _now()
        with self.connect() as db:
            db.execute(
                """UPDATE agent_runs
                   SET status='completed',output=?,error=NULL,updated_at=?
                   WHERE job_id=? AND agent_id=? AND stage=?""",
                (output[:24000] if output is not None else None, now, job_id, agent_id, stage),
            )
            db.execute(
                "INSERT INTO continuity_events VALUES(?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, job_id, project, agent_id, "stage_completed", stage, now),
            )
            if memory_note and memory_note.strip():
                expires = (
                    (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=memory_ttl_days))
                    .isoformat(timespec="seconds") if memory_ttl_days > 0 else None
                )
                db.execute(
                    """INSERT INTO agent_memories
                       (id,project,agent_id,scope,category,content,created_at,expires_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (uuid.uuid4().hex, project, agent_id, "short", "task_outcome",
                     memory_note.strip()[:2500], now, expires),
                )

    def fail_stage(
        self, *, job_id: str, project: str, agent_id: str, stage: str, error: str
    ) -> None:
        now = _now()
        with self.connect() as db:
            db.execute(
                """UPDATE agent_runs SET status='failed',error=?,updated_at=?
                   WHERE job_id=? AND agent_id=? AND stage=?""",
                (error[:1200], now, job_id, agent_id, stage),
            )
            db.execute(
                "INSERT INTO continuity_events VALUES(?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, job_id, project, agent_id, "stage_failed",
                 error[:500], now),
            )

    def remember(
        self, *, project: str, agent_id: str, content: str,
        scope: str = "short", category: str = "agent_note",
        ttl_days: int | None = 30,
    ) -> None:
        if scope not in {"short", "long"}:
            raise ValueError("scope must be short or long")
        note = content.strip()[:2500]
        if not note:
            return
        now = _now()
        expires = (
            (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=ttl_days))
            .isoformat(timespec="seconds") if ttl_days else None
        )
        with self.connect() as db:
            db.execute(
                """INSERT INTO agent_memories
                   (id,project,agent_id,scope,category,content,created_at,expires_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex, project, agent_id, scope, category, note, now, expires),
            )

    def agent_memory_context(self, *, project: str, agent_id: str, limit: int = 6) -> str:
        limit = max(1, min(12, int(limit)))
        now = _now()
        with self.connect() as db:
            db.execute(
                "DELETE FROM agent_memories WHERE expires_at IS NOT NULL AND expires_at<=?",
                (now,),
            )
            rows = db.execute(
                """SELECT scope,category,content,created_at FROM agent_memories
                   WHERE agent_id=? AND project IN (?, 'portfolio')
                     AND (expires_at IS NULL OR expires_at>?)
                   ORDER BY CASE scope WHEN 'long' THEN 0 ELSE 1 END, created_at DESC
                   LIMIT ?""",
                (agent_id, project, now, limit),
            ).fetchall()
        if not rows:
            return ""
        lines = [f"Persistent memory for agent {agent_id} in project {project}:"]
        lines.extend(
            f"- [{row['scope']}/{row['category']} @ {row['created_at']}] {row['content']}"
            for row in rows
        )
        return "\n".join(lines)[:6000]

    def save_external_task(
        self, *, provider: str, external_task_id: str, agent_id: str,
        local_job_id: str | None = None, status: str = "submitted",
        task_url: str | None = None, result: dict[str, Any] | None = None,
    ) -> None:
        now = _now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO external_agent_tasks
                   (id,provider,external_task_id,local_job_id,agent_id,status,task_url,
                    last_event_id,result_json,error,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,NULL,?,NULL,?,?)
                   ON CONFLICT(provider,external_task_id) DO UPDATE SET
                     status=excluded.status,task_url=excluded.task_url,
                     result_json=COALESCE(excluded.result_json,external_agent_tasks.result_json),
                     updated_at=excluded.updated_at""",
                (uuid.uuid4().hex, provider, external_task_id, local_job_id, agent_id,
                 status, task_url, json.dumps(result, ensure_ascii=False) if result else None,
                 now, now),
            )

    def update_external_task(
        self, *, provider: str, external_task_id: str, status: str,
        last_event_id: str | None = None, result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """UPDATE external_agent_tasks SET status=?,last_event_id=?,
                   result_json=COALESCE(?,result_json),error=?,updated_at=?
                   WHERE provider=? AND external_task_id=?""",
                (status, last_event_id,
                 json.dumps(result, ensure_ascii=False) if result else None,
                 error[:1200] if error else None, _now(), provider, external_task_id),
            )

    def external_task(self, *, provider: str, external_task_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM external_agent_tasks WHERE provider=? AND external_task_id=?",
                (provider, external_task_id),
            ).fetchone()
        return dict(row) if row else None

    def snapshot(self) -> dict[str, Any]:
        with self.connect() as db:
            stage_counts = {
                str(row["status"]): int(row["total"])
                for row in db.execute(
                    "SELECT status,COUNT(*) AS total FROM agent_runs GROUP BY status"
                )
            }
            memory_count = int(db.execute("SELECT COUNT(*) FROM agent_memories").fetchone()[0])
            external_counts = {
                str(row["status"]): int(row["total"])
                for row in db.execute(
                    "SELECT status,COUNT(*) AS total FROM external_agent_tasks GROUP BY status"
                )
            }
            latest = db.execute(
                """SELECT job_id,project,agent_id,event_type,detail,created_at
                   FROM continuity_events ORDER BY created_at DESC LIMIT 20"""
            ).fetchall()
        return {
            "agent_stage_counts": stage_counts,
            "saved_agent_memories": memory_count,
            "external_task_counts": external_counts,
            "latest_events": [dict(row) for row in latest],
        }
