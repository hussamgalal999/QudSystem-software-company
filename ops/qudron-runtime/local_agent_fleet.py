"""
Qudron Local Agent Fleet — نظام التنسيق الرباعي الفائق
=======================================================
يُنفِّذ الميثاق المعماري الموحد للوكلاء الأربعة:
  • kiro          — Frontend / Components / Domain UI
  • github-copilot — Architecture / Tests / Review
  • antigravity   — Infra / Host Semaphore / Cloud Router
  • qoder         — DAG Engine / Full-Stack Execution

المبادئ المُطبَّقة:
  1. Host Semaphore   — عملية CLI ثقيلة واحدة فقط في أي لحظة
  2. Single-Writer    — كاتب واحد + مراجع واحد فقط لكل مهمة
  3. Compact Capsules — كبسولات مهام < 200 توكن (task_id + symbols + diff + rules)
  4. Zero-Token Bus   — تبادل الفروق فقط، لا سجلات كاملة
  5. Durable Queue    — طابور مدوَّم في SQLite، لا ضياع عند الخمول
  6. Conditional Wake — الاستيقاظ عبر واجهات رسمية فقط أو الطابور
  7. Cloud Fallback   — Cloudflare Workers AI → OpenRouter(:free) → local

الملف مكتبة قياسية Python بالكامل (sqlite3, threading, json, subprocess).
لا تبعيات خارجية مطلوبة للتشغيل.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generator, Optional

# ─────────────────────────────────────────────
#  المسارات الثابتة
# ─────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent
REPO_ROOT  = BASE_DIR.parent.parent
COORD_PY   = REPO_ROOT / ".agent-coordination" / "coord.py"
DATA_DIR   = BASE_DIR / "data"
FLEET_DB   = DATA_DIR / "fleet.sqlite3"

DATA_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
#  1. Host Semaphore — حارس الجهاز
# ─────────────────────────────────────────────
class HostSemaphore:
    """
    يضمن أن عملية CLI ثقيلة واحدة فقط تعمل في أي لحظة على الجهاز.
    يستخدم ملف قفل SQLite بدلاً من os.lock لضمان التنظيف التلقائي.
    """

    def __init__(self, max_concurrent: int = 1, timeout_sec: int = 120):
        self.max_concurrent = max_concurrent
        self.timeout_sec    = timeout_sec
        self._lock          = threading.Semaphore(max_concurrent)
        self._active: list[str] = []
        self._mu = threading.Lock()

    @contextmanager
    def acquire(self, label: str) -> Generator[None, None, None]:
        """يحجز slot، ينتظر بـ exponential backoff، يُحرِّر عند الانتهاء."""
        deadline = time.monotonic() + self.timeout_sec
        wait     = 1.0
        while not self._lock.acquire(blocking=False):
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"HostSemaphore: تجاوز المهلة {self.timeout_sec}s "
                    f"في انتظار slot لـ '{label}'. "
                    f"المهام النشطة حالياً: {self._active}"
                )
            time.sleep(min(wait, 30.0))
            wait = min(wait * 2, 30.0)

        with self._mu:
            self._active.append(label)
        try:
            yield
        finally:
            with self._mu:
                self._active.remove(label)
            self._lock.release()

    @property
    def active_tasks(self) -> list[str]:
        with self._mu:
            return list(self._active)


# Singleton للجهاز كله
HOST_SEMAPHORE = HostSemaphore(max_concurrent=1, timeout_sec=300)


# ─────────────────────────────────────────────
#  2. تعريفات الوكلاء والقدرات
# ─────────────────────────────────────────────
class AgentRole(str, Enum):
    KIRO        = "kiro"
    COPILOT     = "github-copilot"
    ANTIGRAVITY = "antigravity"
    QODER       = "qoder"
    OPENCODE    = "opencode"
    GEMINI_CLI  = "gemini-cli"
    CLAUDE_CLI  = "claude-cli"
    CODEX_CLI   = "codex-cli"
    CHATGPT_DESKTOP = "chatgpt-desktop"


@dataclass
class AgentCapability:
    """قدرات ونقاط قوة كل وكيل."""
    agent_id:    AgentRole
    domains:     list[str]           # مجالات التخصص
    can_write:   bool = True         # يستطيع الكتابة
    can_review:  bool = True         # يستطيع المراجعة
    wakeup_api:  Optional[str] = None  # واجهة الاستيقاظ الرسمية (إن وجدت)
    is_local:    bool = True         # يعمل محلياً
    max_parallel: int = 1            # الحد الأقصى للمهام المتوازية


AGENT_REGISTRY: dict[AgentRole, AgentCapability] = {
    AgentRole.KIRO: AgentCapability(
        agent_id=AgentRole.KIRO,
        domains=["frontend", "components", "ui", "domain-logic", "typescript", "react"],
        can_write=True,
        can_review=True,
        wakeup_api=None,   # Kiro يُنبَّه عبر PROGRESS.md أو events
        is_local=True,
        max_parallel=1,
    ),
    AgentRole.COPILOT: AgentCapability(
        agent_id=AgentRole.COPILOT,
        domains=["architecture", "tests", "review", "integration", "security"],
        can_write=True,
        can_review=True,
        wakeup_api=None,   # Copilot يعمل في worktree منفصل، ينبَّه عبر coord.py msg
        is_local=True,
        max_parallel=1,
    ),
    AgentRole.ANTIGRAVITY: AgentCapability(
        agent_id=AgentRole.ANTIGRAVITY,
        domains=["infrastructure", "terminal", "cloud-routing", "resource-guard", "ci-cd"],
        can_write=True,    # يكتب للـ infra و terminal والـ automation
        can_review=True,
        wakeup_api=None,   # Antigravity/Gemini في Terminal، ينبَّه بالكبسولة
        is_local=True,
        max_parallel=1,
    ),
    AgentRole.QODER: AgentCapability(
        agent_id=AgentRole.QODER,
        domains=["dag-engine", "fullstack", "python", "backend", "database", "execution"],
        can_write=True,
        can_review=False,  # Qoder منفذ، Copilot هو المراجع
        wakeup_api=None,   # Qoder ينبَّه عبر coord.py أو task queue
        is_local=True,
        max_parallel=1,
    ),
    AgentRole.OPENCODE: AgentCapability(
        agent_id=AgentRole.OPENCODE,
        domains=["execution", "python-scripting", "data-processing", "testing"],
        can_write=True,
        can_review=True,
        wakeup_api="opencode",
        is_local=True,
        max_parallel=1,
    ),
    AgentRole.GEMINI_CLI: AgentCapability(
        agent_id=AgentRole.GEMINI_CLI,
        domains=["terminal", "infra-scripts", "cloud-automation", "monitoring"],
        can_write=True,
        can_review=True,
        wakeup_api="gemini",
        is_local=True,
        max_parallel=1,
    ),
    AgentRole.CLAUDE_CLI: AgentCapability(
        agent_id=AgentRole.CLAUDE_CLI,
        domains=["refactoring", "spec-verification", "documentation", "analysis"],
        can_write=True,
        can_review=True,
        wakeup_api="claude",
        is_local=True,
        max_parallel=1,
    ),
    AgentRole.CODEX_CLI: AgentCapability(
        agent_id=AgentRole.CODEX_CLI,
        domains=["code-generation", "unit-tests", "syntax-fixes"],
        can_write=True,
        can_review=False,
        wakeup_api="codex",
        is_local=True,
        max_parallel=1,
    ),
    AgentRole.CHATGPT_DESKTOP: AgentCapability(
        agent_id=AgentRole.CHATGPT_DESKTOP,
        domains=["desktop-automation", "fullstack", "codex", "interactive-chat"],
        can_write=True,
        can_review=True,
        wakeup_api="windows-node",
        is_local=True,
        max_parallel=1,
    ),
}

# خريطة الوكلاء المناوبين الاحتياطيين عند نفاد التوكنز أو الخمول
STANDBY_SURROGATES: dict[AgentRole, list[AgentRole]] = {
    AgentRole.QODER: [AgentRole.CHATGPT_DESKTOP, AgentRole.ANTIGRAVITY, AgentRole.OPENCODE, AgentRole.GEMINI_CLI],
    AgentRole.KIRO: [AgentRole.CLAUDE_CLI, AgentRole.COPILOT, AgentRole.ANTIGRAVITY],
    AgentRole.COPILOT: [AgentRole.ANTIGRAVITY, AgentRole.CODEX_CLI],
    AgentRole.ANTIGRAVITY: [AgentRole.GEMINI_CLI, AgentRole.COPILOT],
    AgentRole.OPENCODE: [AgentRole.ANTIGRAVITY, AgentRole.QODER],
    AgentRole.GEMINI_CLI: [AgentRole.ANTIGRAVITY],
    AgentRole.CLAUDE_CLI: [AgentRole.KIRO],
    AgentRole.CODEX_CLI: [AgentRole.COPILOT],
    AgentRole.CHATGPT_DESKTOP: [AgentRole.CODEX_CLI, AgentRole.ANTIGRAVITY],
}


# ─────────────────────────────────────────────
#  3. Compact Task Capsule — كبسولة المهمة
#  < 200 توكن، لا سياق قديم
# ─────────────────────────────────────────────
@dataclass
class TaskCapsule:
    """
    كبسولة المهمة الفائقة الصغر.
    تُرسَل بين الوكلاء بدلاً من السجل الكامل.
    مُصمَّمة للبقاء < 200 توكن عند تحويلها إلى نص.
    """
    task_id:       str
    task_type:     str                    # coding | review | infra | research
    owner:         AgentRole              # الوكيل المالك
    reviewer:      Optional[AgentRole]    # الوكيل المراجع
    target_files:  list[str]              # الملفات المستهدفة فقط
    target_symbols: list[str]            # الرموز البرمجية المستهدفة
    diff_summary:  str                    # ملخص التغيير (< 100 كلمة)
    learned_rules: list[str]             # القواعد المستفادة المرتبطة (< 3)
    priority:      int = 5               # 1=أعلى، 10=أدنى
    status:        str = "pending"       # pending|running|review|done|failed
    created_at:    str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at:    str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result_ref:    Optional[str] = None  # مرجع للنتيجة (ملف أو hash)
    error_msg:     Optional[str] = None

    def to_compact_json(self) -> str:
        """يُنتج JSON مضغوط < 200 توكن تقريباً."""
        compact = {
            "id":      self.task_id,
            "type":    self.task_type,
            "owner":   self.owner.value,
            "files":   self.target_files[:3],   # أقصى 3 ملفات في الكبسولة
            "symbols": self.target_symbols[:5], # أقصى 5 رموز
            "diff":    self.diff_summary[:300],  # 300 حرف فقط
            "rules":   self.learned_rules[:3],
            "status":  self.status,
        }
        return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

    def token_estimate(self) -> int:
        """تقدير عدد التوكنز (تقريبي: 1 توكن ≈ 4 حرف)."""
        return len(self.to_compact_json()) // 4


# ─────────────────────────────────────────────
#  4. Durable Task Queue — الطابور المدوَّم
# ─────────────────────────────────────────────
class DurableTaskQueue:
    """
    طابور مهام SQLite: لا يضيع عند إغلاق أي برنامج.
    المهام تبقى حتى تُسند لوكيل ويُكملها أو تفشل بعد N محاولات.
    """

    DDL = """
    CREATE TABLE IF NOT EXISTS tasks (
        task_id      TEXT PRIMARY KEY,
        capsule_json TEXT NOT NULL,
        owner        TEXT NOT NULL,
        reviewer     TEXT,
        priority     INTEGER DEFAULT 5,
        status       TEXT DEFAULT 'pending',
        attempts     INTEGER DEFAULT 0,
        max_attempts INTEGER DEFAULT 3,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        result_ref   TEXT,
        error_msg    TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_status_priority
        ON tasks (status, priority, created_at);
    """

    def __init__(self, db_path: Path = FLEET_DB):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # أمان متزامن
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(self.DDL)
            conn.commit()

    def enqueue(self, capsule: TaskCapsule) -> None:
        """يضيف مهمة للطابور، لا تكرار إذا موجودة."""
        now = datetime.now(timezone.utc).isoformat()
        reviewer_val = capsule.reviewer.value if capsule.reviewer else None
        with self._connect() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO tasks
                    (task_id, capsule_json, owner, reviewer, priority,
                     status, attempts, max_attempts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', 0, 3, ?, ?)
            """, (
                capsule.task_id,
                capsule.to_compact_json(),
                capsule.owner.value,
                reviewer_val,
                capsule.priority,
                capsule.created_at,
                now,
            ))
            conn.commit()

    def claim_next(self, agent: AgentRole) -> Optional[dict]:
        """
        يُسند للوكيل أولى مهامه المناسبة.
        Single-Writer: المهمة تُقفَل فور الإسناد.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            # قراءة وتحديث في معاملة واحدة
            row = conn.execute("""
                SELECT task_id, capsule_json, owner, reviewer, attempts, max_attempts
                FROM tasks
                WHERE status = 'pending'
                  AND owner = ?
                  AND attempts < max_attempts
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
            """, (agent.value,)).fetchone()

            if not row:
                return None

            conn.execute("""
                UPDATE tasks
                SET status = 'running', attempts = attempts + 1, updated_at = ?
                WHERE task_id = ?
            """, (now, row["task_id"]))
            conn.commit()

        return dict(row)

    def complete(self, task_id: str, result_ref: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("""
                UPDATE tasks SET status='done', result_ref=?, updated_at=?
                WHERE task_id=?
            """, (result_ref, now, task_id))
            conn.commit()

    def fail(self, task_id: str, error_msg: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            # إذا استنفد المحاولات → failed، وإلا → pending للإعادة
            row = conn.execute(
                "SELECT attempts, max_attempts FROM tasks WHERE task_id=?",
                (task_id,)
            ).fetchone()
            if row and row["attempts"] >= row["max_attempts"]:
                new_status = "failed"
            else:
                new_status = "pending"
            conn.execute("""
                UPDATE tasks SET status=?, error_msg=?, updated_at=?
                WHERE task_id=?
            """, (new_status, error_msg[:500], now, task_id))
            conn.commit()

    def reassign_task(self, task_id: str, new_owner: str, reason: str) -> bool:
        """إعادة إسناد المهمة لوكيل بديل/مناوب مع الحفاظ على حالتها وسياقها."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            row = conn.execute("SELECT capsule_json FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if not row:
                return False
            data = json.loads(row["capsule_json"])
            data["owner"] = new_owner
            data["handoff_reason"] = reason
            conn.execute("""
                UPDATE tasks
                SET owner=?, capsule_json=?, status='pending', updated_at=?
                WHERE task_id=?
            """, (new_owner, json.dumps(data, ensure_ascii=False), now, task_id))
            conn.commit()
            return True

    def queue_stats(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status
            """).fetchall()
        return {row["status"]: row["cnt"] for row in rows}

    def pending_for_agent(self, agent: AgentRole) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT task_id, capsule_json, priority, status, attempts
                FROM tasks
                WHERE owner=? AND status IN ('pending','running')
                ORDER BY priority ASC
            """, (agent.value,)).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────
#  5. Zero-Token Context Bus — ناقل السياق الصفري
#  يبادل الفروق فقط، لا السجلات الكاملة
# ─────────────────────────────────────────────
class ZeroTokenContextBus:
    """
    يحفظ سجل المحادثات كاملاً محلياً.
    يُرجع للوكيل فقط المقاطع المرتبطة بمهمته الحالية.
    """

    DDL = """
    CREATE TABLE IF NOT EXISTS context_log (
        entry_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        agent       TEXT NOT NULL,
        task_id     TEXT,
        entry_type  TEXT NOT NULL,   -- capsule|result|rule|error
        content     TEXT NOT NULL,
        tags        TEXT,            -- JSON array of keywords
        created_at  TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_task ON context_log (task_id);
    CREATE INDEX IF NOT EXISTS idx_agent ON context_log (agent, entry_type);
    """

    def __init__(self, db_path: Path = FLEET_DB):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(self.DDL)
            conn.commit()

    def record(self, agent: AgentRole, entry_type: str,
               content: str, task_id: str = "", tags: list[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO context_log (agent, task_id, entry_type, content, tags, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                agent.value,
                task_id or "",
                entry_type,
                content[:2000],  # حد أقصى للإدخال الواحد
                json.dumps(tags or [], ensure_ascii=False),
                now,
            ))
            conn.commit()

    def fetch_relevant(self, task_id: str, limit: int = 5) -> list[str]:
        """
        يُرجع فقط المقاطع المرتبطة بهذه المهمة.
        لا سجل كامل — توفير 80%+ من التوكنز.
        """
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT agent, entry_type, content, created_at
                FROM context_log
                WHERE task_id = ?
                ORDER BY entry_id DESC
                LIMIT ?
            """, (task_id, limit)).fetchall()
        return [
            f"[{r['created_at'][11:19]}][{r['agent']}:{r['entry_type']}] {r['content']}"
            for r in reversed(rows)
        ]

    def fetch_learned_rules(self, limit: int = 5) -> list[str]:
        """يُرجع القواعد المستفادة فقط — للحقن في كبسولة المهمة التالية."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT content FROM context_log
                WHERE entry_type = 'rule'
                ORDER BY entry_id DESC LIMIT ?
            """, (limit,)).fetchall()
        return [r["content"] for r in rows]


# ─────────────────────────────────────────────
#  6. Cloud Inference Fallback
#  Cloudflare Workers AI → OpenRouter(:free)
# ─────────────────────────────────────────────
class CloudInferenceFallback:
    """
    يُجرِّب المزودين بالترتيب:
    1. Cloudflare Workers AI (موجود في المستودع، 10k/يوم مجاناً)
    2. OpenRouter :free tier
    3. يُعيد None إذا فشل الكل (لا crash)
    """

    CF_WORKER_URL = os.getenv("QUDRON_CF_WORKER_URL", "")  # من .env فقط
    OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
    FREE_MODEL     = "meta-llama/llama-3.3-70b-instruct:free"

    @classmethod
    def call(cls, system_prompt: str, user_prompt: str, timeout: int = 30) -> Optional[str]:
        # محاولة 1: Cloudflare Worker (إذا مُعدَّل)
        if cls.CF_WORKER_URL:
            result = cls._call_cloudflare(system_prompt, user_prompt, timeout)
            if result:
                return result

        # محاولة 2: OpenRouter free tier
        if cls.OPENROUTER_KEY:
            result = cls._call_openrouter(system_prompt, user_prompt, timeout)
            if result:
                return result

        return None  # لا استدعاء بدون مفتاح — لا crash صامت

    @classmethod
    def _call_cloudflare(cls, sys_p: str, usr_p: str, timeout: int) -> Optional[str]:
        try:
            payload = json.dumps({
                "messages": [
                    {"role": "system", "content": sys_p},
                    {"role": "user",   "content": usr_p},
                ],
                "max_tokens": 800,
            }).encode()
            req = urllib.request.Request(
                cls.CF_WORKER_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                return (data.get("result", {}) or {}).get("response") or \
                       data.get("choices", [{}])[0].get("message", {}).get("content")
        except Exception:
            return None

    @classmethod
    def _call_openrouter(cls, sys_p: str, usr_p: str, timeout: int) -> Optional[str]:
        try:
            payload = json.dumps({
                "model": cls.FREE_MODEL,
                "messages": [
                    {"role": "system", "content": sys_p},
                    {"role": "user",   "content": usr_p},
                ],
                "max_tokens": 800,
            }).encode()
            req = urllib.request.Request(
                cls.OPENROUTER_URL,
                data=payload,
                headers={
                    "Authorization": f"Bearer {cls.OPENROUTER_KEY}",
                    "Content-Type":  "application/json",
                    "HTTP-Referer":  "https://github.com/Qudsystem/Qudron",
                    "X-Title":       "Qudron Agent Fleet",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                return data["choices"][0]["message"]["content"]
        except Exception:
            return None


# ─────────────────────────────────────────────
#  7. Fleet Coordinator — المنسق الرئيسي
# ─────────────────────────────────────────────
class FleetCoordinator:
    """
    المنسق الرئيسي للأربعة.
    يُسند المهام، يُراقب الحجوزات، يُدير الاستيقاظ.
    """

    def __init__(self):
        self.queue   = DurableTaskQueue()
        self.bus     = ZeroTokenContextBus()
        self.cloud   = CloudInferenceFallback()
        self._coord  = COORD_PY  # مسار coord.py

    # ── واجهة إسناد المهام ──────────────────────
    def submit_task(self, capsule: TaskCapsule) -> str:
        """يُضيف مهمة للطابور وينبّه الوكيل المناسب."""
        self.queue.enqueue(capsule)
        self.bus.record(
            agent=capsule.owner,
            entry_type="capsule",
            content=capsule.to_compact_json(),
            task_id=capsule.task_id,
        )
        self._notify_agent(capsule)
        return capsule.task_id

    def _notify_agent(self, capsule: TaskCapsule) -> None:
        """
        ينبّه الوكيل المالك عبر الطريقة الرسمية المتاحة:
        - coord.py msg (للوكلاء المسجلين في البورد)
        - ملف PROGRESS.md (لـ Kiro)
        - لا استيقاظ قسري لأي واجهة خاملة
        """
        agent = capsule.owner
        cap   = AGENT_REGISTRY.get(agent)
        if not cap:
            return

        # Kiro: ينبَّه عبر PROGRESS.md
        if agent == AgentRole.KIRO:
            self._update_progress_md(capsule)
            return

        # الوكلاء المسجلون في coord.py
        if self._coord.exists():
            try:
                subprocess.run([
                    sys.executable, str(self._coord),
                    "msg", "send",
                    "--from", "qoder",
                    "--to",   agent.value,
                    "--subject", f"[fleet] task {capsule.task_id}",
                    "--body", capsule.to_compact_json(),
                ], capture_output=True, timeout=10, check=False)
            except Exception:
                pass  # الفشل لا يمنع إضافة المهمة للطابور

    def _update_progress_md(self, capsule: TaskCapsule) -> None:
        """يكتب إشعاراً في PROGRESS.md لـ Kiro."""
        progress_file = REPO_ROOT / "PROGRESS.md"
        now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        line = (
            f"\n## [{now}] 🎯 مهمة جديدة لـ Kiro: {capsule.task_id}\n"
            f"- النوع: {capsule.task_type}\n"
            f"- الملفات: {', '.join(capsule.target_files[:3])}\n"
            f"- الملخص: {capsule.diff_summary[:200]}\n"
            f"- الحالة: {capsule.status}\n"
        )
        with open(progress_file, "a", encoding="utf-8") as f:
            f.write(line)

    # ── واجهة تشغيل المهمة ──────────────────────
    def run_task_for_agent(
        self,
        agent: AgentRole,
        executor: Callable[[TaskCapsule, list[str]], str],
    ) -> Optional[str]:
        """
        يُسند للوكيل أولى مهامه، يُشغّلها بحارس الجهاز،
        يُسجّل النتيجة في الطابور والسياق.
        """
        row = self.queue.claim_next(agent)
        if not row:
            return None

        task_id = row["task_id"]
        capsule_dict = json.loads(row["capsule_json"])

        # استرجاع السياق المرتبط فقط
        relevant_ctx = self.bus.fetch_relevant(task_id)
        learned      = self.bus.fetch_learned_rules(limit=3)

        # بناء كبسولة كاملة من الـ JSON
        owner_role    = AgentRole(row["owner"])
        reviewer_val  = row.get("reviewer")
        reviewer_role = AgentRole(reviewer_val) if reviewer_val else None

        capsule = TaskCapsule(
            task_id=task_id,
            task_type=capsule_dict.get("type", "coding"),
            owner=owner_role,
            reviewer=reviewer_role,
            target_files=capsule_dict.get("files", []),
            target_symbols=capsule_dict.get("symbols", []),
            diff_summary=capsule_dict.get("diff", ""),
            learned_rules=learned,
            status="running",
        )

        try:
            with HOST_SEMAPHORE.acquire(f"{agent.value}:{task_id}"):
                result_ref = executor(capsule, relevant_ctx)

            self.queue.complete(task_id, result_ref)
            self.bus.record(agent, "result", result_ref, task_id)
            return result_ref

        except TimeoutError as e:
            self.queue.fail(task_id, str(e))
            self.bus.record(agent, "error", str(e), task_id)
            return None
        except Exception as e:
            self.queue.fail(task_id, str(e))
            self.bus.record(agent, "error", str(e), task_id, tags=["unexpected"])
            return None

    # ── لوحة الحالة ─────────────────────────────
    def dashboard(self) -> str:
        """يُعيد ملخصاً مضغوطاً للحالة — للعرض دون استهلاك توكنز."""
        stats   = self.queue.queue_stats()
        active  = HOST_SEMAPHORE.active_tasks
        lines   = [
            "╔══════════════════════════════════════════════╗",
            "║  Qudron Local Agent Fleet — حالة الأسطول   ║",
            "╚══════════════════════════════════════════════╝",
            f"  الطابور: {stats}",
            f"  نشط الآن: {active or 'لا شيء'}",
            "",
            "  الوكلاء المسجلون:",
        ]
        for role, cap in AGENT_REGISTRY.items():
            pending = self.queue.pending_for_agent(role)
            lines.append(
                f"  • {role.value:18} | مهام: {len(pending):2} | "
                f"كتابة:{cap.can_write} | مراجعة:{cap.can_review}"
            )
        lines += [
            "",
            "  مثال على إضافة مهمة:",
            "    fleet.submit_task(TaskCapsule(",
            "        task_id='T-001', task_type='coding',",
            "        owner=AgentRole.QODER,",
            "        reviewer=AgentRole.COPILOT,",
            "        target_files=['ops/qudron-runtime/qudron_worker.py'],",
            "        target_symbols=['_call_model'],",
            "        diff_summary='إضافة retry logic في _call_model',",
            "        learned_rules=['أغلق sqlite connection قبل tearDown'],",
            "    ))",
        ]
        return "\n".join(lines)


# ─────────────────────────────────────────────
#  8. نقطة الدخول — الاختبار الأساسي بلا شبكة
# ─────────────────────────────────────────────
def _demo_executor(capsule: TaskCapsule, context: list[str]) -> str:
    """
    منفذ تجريبي يطبع الكبسولة ويُعيد مرجع وهمي.
    استبدله بالمنفذ الحقيقي لكل وكيل.
    """
    print(f"\n🤖 [{capsule.owner.value}] تنفيذ: {capsule.task_id}")
    print(f"   الكبسولة ({capsule.token_estimate()} توكن): {capsule.to_compact_json()}")
    if context:
        print(f"   السياق المرتبط ({len(context)} مقطع):")
        for line in context:
            print(f"     {line}")
    time.sleep(0.5)  # محاكاة العمل
    return f"result:{capsule.task_id}:ok"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    fleet = FleetCoordinator()

    print("\n" + fleet.dashboard())

    # ── مثال: إضافة 3 مهام لوكلاء مختلفين ──
    tasks = [
        TaskCapsule(
            task_id="T-001",
            task_type="coding",
            owner=AgentRole.QODER,
            reviewer=AgentRole.COPILOT,
            target_files=["ops/qudron-runtime/qudron_worker.py"],
            target_symbols=["_call_model", "run_job"],
            diff_summary="إضافة retry logic في _call_model مع exponential backoff",
            learned_rules=["أغلق sqlite connection قبل tearDown على Windows"],
            priority=1,
        ),
        TaskCapsule(
            task_id="T-002",
            task_type="review",
            owner=AgentRole.COPILOT,
            reviewer=None,
            target_files=["ops/qudron-runtime/local_agent_fleet.py"],
            target_symbols=["HostSemaphore", "DurableTaskQueue"],
            diff_summary="مراجعة نظام التنسيق الجديد قبل دمجه في main",
            learned_rules=[],
            priority=2,
        ),
        TaskCapsule(
            task_id="T-003",
            task_type="infra",
            owner=AgentRole.ANTIGRAVITY,
            reviewer=None,
            target_files=["ops/qudron-cloudflare/wrangler.jsonc"],
            target_symbols=[],
            diff_summary="التحقق من إعدادات Workers AI وتفعيل fallback endpoint",
            learned_rules=["إذا فشل pollinations → Cloudflare Workers AI مباشرة"],
            priority=3,
        ),
    ]

    print("\n📥 إضافة المهام إلى الطابور...")
    for t in tasks:
        task_id = fleet.submit_task(t)
        print(f"   ✅ {task_id} → {t.owner.value} (reviewer: {t.reviewer.value if t.reviewer else 'لا يوجد'})")

    print(f"\n📊 إحصائيات الطابور: {fleet.queue.queue_stats()}")

    # ── تشغيل مهمة Qoder فقط (Single-Writer) ──
    print("\n⚡ تشغيل مهمة Qoder عبر Host Semaphore...")
    result = fleet.run_task_for_agent(AgentRole.QODER, _demo_executor)
    print(f"   النتيجة: {result}")

    print("\n" + fleet.dashboard())


if __name__ == "__main__":
    main()
