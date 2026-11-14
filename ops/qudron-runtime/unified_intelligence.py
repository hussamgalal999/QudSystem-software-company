"""
Unified Intelligence Layer for Qudron Swarm.

Provides:
1. Unified Context Bus: Shared memory for cross-agent coordination.
2. Token Budget Manager: Proactive failover and usage tracking.
3. Smart Surrogate Handover: Resumable state for different CLI engines.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from continuity_store import ContinuityStore

class TokenBudgetManager:
    def __init__(self, db_connector: Any):
        self.db_connector = db_connector
        self._ensure_schema()

    def _ensure_schema(self):
        with self.db_connector() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS token_budgets (
                    platform TEXT PRIMARY KEY,
                    quota_limit INTEGER NOT NULL,
                    used_tokens INTEGER DEFAULT 0,
                    reset_at TEXT,
                    status TEXT DEFAULT 'ok',
                    updated_at TEXT NOT NULL
                )
            """)
            db.commit()

    def update_usage(self, platform: str, tokens: int):
        now = datetime.now(timezone.utc).isoformat()
        with self.db_connector() as db:
            db.execute("""
                INSERT INTO token_budgets (platform, quota_limit, used_tokens, updated_at)
                VALUES (?, 100000, ?, ?)
                ON CONFLICT(platform) DO UPDATE SET
                    used_tokens = used_tokens + excluded.used_tokens,
                    updated_at = excluded.updated_at
            """, (platform, tokens, now))
            
            # Check for status change
            row = db.execute("SELECT used_tokens, quota_limit FROM token_budgets WHERE platform=?", (platform,)).fetchone()
            if row and row[0] >= row[1] * 0.9:
                status = 'low' if row[0] < row[1] else 'exhausted'
                db.execute("UPDATE token_budgets SET status=? WHERE platform=?", (status, platform))
            
            db.commit()

    def get_status(self, platform: str) -> Dict[str, Any]:
        with self.db_connector() as db:
            row = db.execute("SELECT * FROM token_budgets WHERE platform=?", (platform,)).fetchone()
            if row:
                return dict(row)
            return {"platform": platform, "status": "ok", "used_tokens": 0, "quota_limit": 100000}

    def get_best_platform(self, preferred: str) -> str:
        status = self.get_status(preferred)
        if status["status"] == "ok":
            return preferred
        
        # Fallback to platform with most tokens left
        with self.db_connector() as db:
            rows = db.execute("SELECT platform FROM token_budgets WHERE status='ok' ORDER BY (quota_limit - used_tokens) DESC").fetchall()
            if rows:
                return rows[0][0]
        return "unlimited_local" # Final fallback

from cli_adapters import CLIAdapterRegistry

class SurrogateRouter:
    def __init__(self, token_manager: TokenBudgetManager):
        self.token_manager = token_manager
        self.registry = CLIAdapterRegistry()

    def route_task(self, task_id: str, preferred_platform: str, prompt: str, worktree: Path) -> Dict[str, Any]:
        platform = self.token_manager.get_best_platform(preferred_platform)
        adapter = self.registry.get_adapter(platform)
        
        if not adapter:
            return {"success": False, "error": f"Platform {platform} unavailable"}
        
        result = adapter.run_task(prompt, worktree)
        if result["success"]:
            self.token_manager.update_usage(platform, result.get("tokens_estimate", 0))
        
        return result

class CrossAgentConsensus:
    """
    Implements a debate/consensus mechanism where agents can review each other's work.
    """
    def __init__(self, intel: UnifiedIntelligence):
        self.intel = intel

    def request_review(self, task_id: str, agent_id: str, work_result: str):
        # Store result for review
        self.intel.update_task_context(task_id, agent_id, {"result": work_result, "status": "needs_review"}, ["Review by another agent"])

    def get_consensus(self, task_id: str) -> bool:
        # Simple majority or quality-based consensus logic
        context = self.intel.get_task_context(task_id)
        if not context:
            return False
        
        # Check if we have at least 2 reviews
        reviews = [s for s in context["global_state"].values() if isinstance(s, dict) and s.get("status") == "reviewed"]
        if not reviews:
            return False
            
        success_count = sum(1 for r in reviews if r.get("review_status") == "approved")
        return success_count >= 1 # For now, one approval is enough

class UnifiedIntelligence:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.continuity = ContinuityStore(self.db_path)
        self._init_unified_db()
        self.router = SurrogateRouter(self.token_manager)
        self.consensus = CrossAgentConsensus(self)

    def _init_unified_db(self):
        with self.continuity.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS unified_context (
                    task_id TEXT PRIMARY KEY,
                    global_state_json TEXT NOT NULL,
                    last_agent_id TEXT,
                    next_steps_json TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS learned_lessons (
                    id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    vector_hash TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            db.commit()
        self.token_manager = TokenBudgetManager(self.continuity.connect)

    def update_task_context(self, task_id: str, agent_id: str, state: Dict[str, Any], next_steps: List[str]):
        now = datetime.now(timezone.utc).isoformat()
        with self.continuity.connect() as db:
            db.execute("""
                INSERT INTO unified_context (task_id, global_state_json, last_agent_id, next_steps_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    global_state_json = excluded.global_state_json,
                    last_agent_id = excluded.last_agent_id,
                    next_steps_json = excluded.next_steps_json,
                    updated_at = excluded.updated_at
            """, (task_id, json.dumps(state), agent_id, json.dumps(next_steps), now))
            db.commit()

    def get_task_context(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self.continuity.connect() as db:
            row = db.execute("SELECT * FROM unified_context WHERE task_id=?", (task_id,)).fetchone()
            if row:
                res = dict(row)
                res["global_state"] = json.loads(res["global_state_json"])
                res["next_steps"] = json.loads(res["next_steps_json"])
                return res
        return None

    def get_situation_room(self, task_id: str) -> str:
        """
        Returns a human/agent readable summary of the entire project status
        across all agents who have touched it.
        """
        context = self.get_task_context(task_id)
        if not context:
            return "No previous swarm activity found for this task."
        
        state = context["global_state"]
        summary = [f"=== SWARM SITUATION ROOM (Task: {task_id}) ==="]
        summary.append(f"Last updated: {context['updated_at']} by {context['last_agent_id']}")
        
        summary.append("\n[Agent Status Registry]")
        for agent_id, data in state.items():
            if isinstance(data, dict):
                status = data.get("status", "unknown")
                finding = data.get("finding", data.get("last_result", "N/A"))
                summary.append(f"- {agent_id}: [{status}] -> {finding}")
        
        summary.append("\n[Next Coordinated Steps]")
        for step in context["next_steps"]:
            summary.append(f"-> {step}")
            
        summary.append("\n[Project-Wide Lessons]")
        lessons = self.get_lessons_for_prompt(state.get("project", "default"), "general")
        summary.append(lessons if lessons else "No specific lessons recorded yet.")
        
        return "\n".join(summary)

    def record_lesson(self, project: str, domain: str, lesson: str):
        now = datetime.now(timezone.utc).isoformat()
        lesson_id = uuid.uuid4().hex
        with self.continuity.connect() as db:
            db.execute("""
                INSERT INTO learned_lessons (id, project, domain, lesson, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (lesson_id, project, domain, lesson, now))
            db.commit()

    def get_lessons_for_prompt(self, project: str, domain: str, limit: int = 5) -> str:
        with self.continuity.connect() as db:
            rows = db.execute("""
                SELECT lesson FROM learned_lessons 
                WHERE project=? OR domain=? 
                ORDER BY created_at DESC LIMIT ?
            """, (project, domain, limit)).fetchall()
            if not rows:
                return ""
            return "\n".join([f"- {r[0]}" for r in rows])

    def prepare_handover(self, task_id: str, current_agent: str) -> Dict[str, Any]:
        context = self.get_task_context(task_id)
        if not context:
            return {"task_id": task_id, "status": "new"}
            
        best_platform = self.token_manager.get_best_platform(current_agent)
        
        state = context["global_state"]
        project = state.get("project", "default")
        
        return {
            "task_id": task_id,
            "previous_agent": current_agent,
            "target_platform": best_platform,
            "state": state,
            "next_steps": context["next_steps"],
            "lessons": self.get_lessons_for_prompt(project, "general")
        }
