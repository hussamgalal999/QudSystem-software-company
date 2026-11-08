"""Qudron Central Brain & Autonomous Swarm Engine.

Unifies:
1. Multi-Persona Meta-Agent (Architect, Security, Quality, Token-Frugal, Learner).
2. Code Memory Bank (GitHub Intelligence & Zero-Waste Reusable Patterns).
3. Failure Learning System (Self-healing knowledge ledger).
4. Keyless Cloud Inference (Zero-key, zero-local-RAM, 100% cloud-native).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# 100% Free & Keyless Cloud Endpoint
CLOUD_INFERENCE_URL = "https://text.pollinations.ai/openai/chat/completions"
DEFAULT_MODEL = "openai"

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MEMORY_DB = DATA_DIR / "brain_memory.sqlite3"


def init_memory_db() -> None:
    """Initialize persistent memory tables for code patterns and failure lessons."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(MEMORY_DB) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS failure_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_hash TEXT UNIQUE,
                error_context TEXT NOT NULL,
                error_message TEXT NOT NULL,
                preventive_rule TEXT NOT NULL,
                occurrences INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS pattern_cache (
                pattern_key TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                template_code TEXT NOT NULL,
                token_savings_pct REAL DEFAULT 90.0,
                updated_at TEXT NOT NULL
            )
        """)
        db.commit()


# ==========================================
# 1. Failure Learning System (Self-Healing)
# ==========================================
class FailureLearningSystem:
    """Learns from every syntax/logic/runtime error so the swarm never repeats it."""

    @staticmethod
    def record_failure(context: str, error_msg: str, preventive_rule: str) -> None:
        init_memory_db()
        err_hash = str(hash(f"{context}:{error_msg}"))
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(MEMORY_DB) as db:
            db.execute("""
                INSERT INTO failure_lessons (error_hash, error_context, error_message, preventive_rule, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(error_hash) DO UPDATE SET
                    occurrences = occurrences + 1,
                    preventive_rule = excluded.preventive_rule,
                    updated_at = excluded.updated_at
            """, (err_hash, context, str(error_msg)[:500], preventive_rule, now, now))
            db.commit()

    @staticmethod
    def get_learned_rules(limit: int = 5) -> list[str]:
        init_memory_db()
        with sqlite3.connect(MEMORY_DB) as db:
            rows = db.execute("""
                SELECT preventive_rule FROM failure_lessons
                ORDER BY occurrences DESC, updated_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [r[0] for r in rows]


# ==========================================
# 2. Code Memory Bank (GitHub Intelligence)
# ==========================================
class CodeMemoryBank:
    """Provides tested, zero-token architectural patterns to avoid writing from scratch."""

    CORE_PATTERNS = {
        "graphql_bounded_resume": """query GetAIContextForResume {
  project(id: "{{project_id}}") {
    id name status
    lastActivity: activities(limit: 1, order: DESC) { type description completedAt }
    currentMilestone { title progressPercentage }
    nextPendingTask: tasks(filter: { status: PENDING }, limit: 1) { id title priority }
  }
}""",
        "sqlite_idempotent_store": """with connect_db() as db:
    db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT, updated_at TEXT)")
    db.execute("INSERT INTO jobs (id, status, updated_at) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET status=excluded.status", (jid, status, now))
    db.commit()""",
        "cloudflare_workers_ai": """const result = await env.AI.run('@cf/meta/llama-3.3-70b-instruct-fp8-fast', {
    messages: [{ role: 'system', content: sysPrompt }, { role: 'user', content: taskPrompt }],
    max_tokens: 1200
});""",
    }

    @classmethod
    def get_pattern(cls, pattern_name: str) -> str | None:
        init_memory_db()
        with sqlite3.connect(MEMORY_DB) as db:
            row = db.execute("SELECT template_code FROM pattern_cache WHERE pattern_key=?", (pattern_name,)).fetchone()
            if row:
                return row[0]
        return cls.CORE_PATTERNS.get(pattern_name)

    @classmethod
    def search_github_patterns(cls, query: str) -> list[dict[str, Any]]:
        """Search public GitHub repositories for patterns with zero local load."""
        encoded_query = urllib.parse.quote(query)
        url = f"https://api.github.com/search/repositories?q={encoded_query}&sort=stars&order=desc&per_page=3"
        req = urllib.request.Request(url, headers={"User-Agent": "Qudron-CodeMiner/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [
                    {
                        "name": r.get("full_name"),
                        "description": r.get("description"),
                        "stars": r.get("stargazers_count"),
                        "url": r.get("html_url"),
                    }
                    for r in data.get("items", [])
                ]
        except Exception:
            return []


# ==========================================
# 3. Multi-Persona Meta-Agent
# ==========================================
@dataclass
class SwarmPersona:
    name: str
    directive: str
    focus: str


PERSONAS = {
    "architect": SwarmPersona(
        name="معماري الأنظمة (System Architect)",
        directive="صمم حلولاً معيارية، نظيفة، وقابلة للتوسع بأعلى كفاءة تدفق DAG.",
        focus="Modular architecture, separation of concerns, scalability"
    ),
    "security": SwarmPersona(
        name="الخبير الأمني (Security Officer)",
        directive="امنع تسريب الأسرار، تحقق من المدخلات، امنع استدعاءات الـ Endpoints غير الآمنة.",
        focus="Zero trust, OWASP Top 10, sanitization, least privilege"
    ),
    "cost_optimizer": SwarmPersona(
        name="مهندس التكاليف والتوفير (Token & Cost Frugality)",
        directive="قلص السياق للحد الأدنى (Bounded Context)، امنع over-fetching، وفر 90%+ من التوكنز.",
        focus="Token conservation, micro-prompts, zero-waste hydration"
    ),
    "quality_engineer": SwarmPersona(
        name="مهندس الجودة والتحقق (Quality Assurance)",
        directive="اكتب اختبارات تغطي كافة الحالات المتطرفة، وتحقق من تطابق العقود البرمجية.",
        focus="Edge-case tests, regression safety, deterministic output"
    ),
}


# ==========================================
# 4. Central Brain Execution Pipeline
# ==========================================
class QudronBrain:
    """The central intelligence engine that coordinates personas, memories, and cloud models."""

    @classmethod
    def build_system_prompt(cls, persona_key: str = "architect") -> str:
        persona = PERSONAS.get(persona_key, PERSONAS["architect"])
        learned_rules = FailureLearningSystem.get_learned_rules(limit=4)
        rules_text = "\n".join(f"- {rule}" for rule in learned_rules) if learned_rules else "- التزم بالكود النظيف وتجنب التخمين غير المدعوم بأدلة."

        return f"""أنت "Qudron Swarm Brain" في منظومة QudSystem.Ltd بقيادة المهندس حسام جلال.
الشخصية الحالية: {persona.name}
التوجيه الأساسي: {persona.directive}
التركيز التقني: {persona.focus}

القواعد المستفادة من التجارب السابقة (تجنب تكرار هذه الأخطاء نهائياً):
{rules_text}

مبادئ صارمة:
1. صفر استهلاك لموارد جهاز المستخدم (Cloud-Native 100%).
2. أقصى توفير للتوكنز: لا تكتب كوداً من الصفر إذا كان بالإمكان استدعاء نمط جاهز.
3. قدم مخرجات دقيقة، قابلة للتنفيذ الفوري، مدعومة بالأدلة."""

    @classmethod
    def dispatch_cloud_inference(cls, prompt: str, persona_key: str = "architect") -> dict[str, Any]:
        """Call the free cloud-native inference router without requiring keys."""
        system_prompt = cls.build_system_prompt(persona_key)
        payload = {
            "model": DEFAULT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }

        req = urllib.request.Request(
            CLOUD_INFERENCE_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Qudron-CentralBrain/1.0"
            },
            method="POST"
        )

        start_time = time.time()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency = round(time.time() - start_time, 2)
                content = data["choices"][0]["message"]["content"]
                return {
                    "success": True,
                    "content": content,
                    "persona": persona_key,
                    "latency_sec": latency,
                    "cost_usd": 0.0,
                    "source": "Free Cloud Inference"
                }
        except Exception as e:
            FailureLearningSystem.record_failure(
                context=f"cloud_inference:{persona_key}",
                error_msg=str(e),
                preventive_rule=f"إضافة آلية إعادة محاولة مع Exponential Backoff عند انقطاع {CLOUD_INFERENCE_URL}"
            )
            return {
                "success": False,
                "error": str(e),
                "persona": persona_key,
                "latency_sec": round(time.time() - start_time, 2)
            }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("🧠 Qudron Central Brain (Initializing...)")
    init_memory_db()

    # Pre-populate a proven lesson
    FailureLearningSystem.record_failure(
        context="windows_sqlite_cleanup",
        error_msg="PermissionError: [WinError 32] state.sqlite3 being used by another process",
        preventive_rule="دائماً تأكد من إغلاق اتصال SQLite قبل محاولة حذف مجلد TemporaryDirectory على Windows."
    )

    query = sys.argv[1] if len(sys.argv) > 1 else "كيف نصمم معمارية تخزين ذاكرة السرب دون أن تفقد أي مهمة؟"
    print(f"\n[مهمة التحليل]: {query}\n")

    res = QudronBrain.dispatch_cloud_inference(query, persona_key="architect")
    if res["success"]:
        print(f"[{PERSONAS['architect'].name} - زمن الرد: {res['latency_sec']}s - التكلفة: $0.00]:\n")
        print(res["content"])
    else:
        print(f"فشل الاستدعاء: {res['error']}")
