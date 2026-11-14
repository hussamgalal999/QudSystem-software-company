"""
Qudron Memory Management Module.
Handles local and cloud-native memory context for agents.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid
import os
from pathlib import Path
from typing import Any, Optional

from swarm_engine import redact_sensitive_text
from cloud_memory_adapter import (
    CloudMemoryClient, CloudMemoryError, context_packet_to_text,
)

class QudronMemoryManager:
    def __init__(self, db_connector: Any):
        self.db_connector = db_connector

    def remember_event(self, project: str, scope: str, category: str, content: str,
                       ttl_days: int | None = 14) -> None:
        if scope not in {"short", "long"}:
            raise ValueError("Memory scope must be short or long")
        safe_content = redact_sensitive_text(content).strip()[:4000]
        if not safe_content:
            return
        now = dt.datetime.now(dt.timezone.utc)
        expires = (now + dt.timedelta(days=ttl_days)).isoformat(timespec="seconds") if ttl_days else None
        with self.db_connector() as db:
            db.execute(
                """INSERT INTO memory_entries(id,project,scope,category,content,created_at,expires_at)
                VALUES(?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex, project, scope, category, safe_content,
                 now.isoformat(timespec="seconds"), expires),
            )

    def retrieve_memory_context(self, project: str, limit: int = 10) -> str:
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        short_limit = max(1, min(12, limit - 3))
        with self.db_connector() as db:
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
        return "\n".join(lines)[:8000]

    def retrieve_cloud_memory_context(self, project: str, limit: int = 25) -> str:
        try:
            client = CloudMemoryClient.from_environment()
        except (CloudMemoryError, ValueError) as exc:
            logging.warning("Cloud memory context unavailable during client setup (%s)", type(exc).__name__)
            return ""
        if client is None:
            return ""
        try:
            context_timeout = float(os.getenv("QUDRON_MEMORY_CONTEXT_TIMEOUT_SECONDS", "2"))
            client.timeout_seconds = max(1.0, min(5.0, context_timeout))
            packet = client.get_context(project_id=project, limit=max(1, min(100, limit)))
            rendered = context_packet_to_text(packet, max_chars=8000)
        except (CloudMemoryError, ValueError) as exc:
            logging.warning("Cloud memory context fetch failed (%s); continuing with local memory", type(exc).__name__)
            return ""
        if not rendered:
            return ""
        return redact_sensitive_text(rendered)[:8000]
