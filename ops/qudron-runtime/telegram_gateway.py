"""Owner-only Telegram command bridge for Qudron.

Long-polling adapter: no public webhook/port is opened. Commands are restricted
to TELEGRAM_OWNER_CHAT_IDS and all task intake goes through Qudron's authenticated
internal API. Never log bot tokens or message contents.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TELEGRAM_API = "https://api.telegram.org"
DEFAULT_QUDRON_URL = "http://qudron:8765"
MAX_MESSAGE = 3900


def parse_owner_ids(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def parse_command(text: str) -> tuple[str, str]:
    value = (text or "").strip()
    if not value:
        return "", ""
    command, _, argument = value.partition(" ")
    command = command.split("@", 1)[0].lower()
    return command, argument.strip()


def format_status(payload: dict[str, Any]) -> str:
    counts = payload.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    order = ("pending", "running", "retry_wait", "completed", "needs_review", "failed")
    lines = ["Qudron status"]
    lines.extend(f"{key}: {int(counts.get(key, 0) or 0)}" for key in order)
    latest = payload.get("latest_jobs", [])
    if isinstance(latest, list) and latest:
        lines.append("Latest:")
        for item in latest[:3]:
            if isinstance(item, dict):
                lines.append(f"- {str(item.get('title', 'Task'))[:80]} [{item.get('status', 'unknown')}]")
    return "\n".join(lines)[:MAX_MESSAGE]


def format_usage(payload: dict[str, Any]) -> str:
    lines = ["Qudron model usage"]
    for period in ("daily", "monthly"):
        row = payload.get(period, {})
        if not isinstance(row, dict):
            row = {}
        lines.append(
            f"{period}: calls={row.get('calls', 0)}, tokens={row.get('total_tokens', 0)}, "
            f"known_cost_usd={row.get('cost_usd', 0)}"
        )
    return "\n".join(lines)[:MAX_MESSAGE]


class TelegramGateway:
    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.owner_ids = parse_owner_ids(os.getenv("TELEGRAM_OWNER_CHAT_IDS", ""))
        self.api_token = os.getenv("QUDRON_API_TOKEN", "").strip()
        self.qudron_url = os.getenv("QUDRON_INTERNAL_URL", DEFAULT_QUDRON_URL).rstrip("/")
        self.timeout = max(5, min(30, int(os.getenv("TELEGRAM_HTTP_TIMEOUT", "15"))))
        self.offset = 0
        self.notification_db_path = Path(os.getenv('QUDRON_TELEGRAM_STATE_DB', '/app/data/telegram_gateway.sqlite3'))
        self.last_completion_poll = 0.0
        self._init_notification_db()

    def _request(self, url: str, payload: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None, timeout: int | None = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json", **(headers or {})},
            method="GET" if data is None else "POST",
        )
        with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        if isinstance(result, dict) and result.get("ok") is False:
            raise RuntimeError("remote_api_rejected_request")
        return result

    def telegram(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        # Telegram long polling can wait up to 50 seconds; the HTTP client
        # timeout must exceed that server-side wait or every poll will time out.
        request_timeout = 65 if method == "getUpdates" else self.timeout
        return self._request(
            f"{TELEGRAM_API}/bot{self.token}/{method}", payload, timeout=request_timeout
        )

    def qudron(self, path: str) -> Any:
        return self._request(
            f"{self.qudron_url}{path}",
            headers={"Authorization": f"Bearer {self.api_token}"},
        )

    def enqueue_research(self, update_id: int, prompt: str) -> dict[str, Any]:
        payload = {
            "task_type": "research",
            "title": "Telegram owner task",
            "role": "Qudron Owner Command Agent",
            "prompt": prompt[:8000],
            "idempotency_key": f"telegram-update-{update_id}",
        }
        return self._request(
            f"{self.qudron_url}/jobs", payload,
            headers={"Authorization": f"Bearer {self.api_token}"},
        )

    def send(self, chat_id: str, text: str) -> None:
        self.telegram("sendMessage", {
            "chat_id": chat_id,
            "text": text[:MAX_MESSAGE],
            "disable_web_page_preview": True,
        })


    def _init_notification_db(self) -> None:
        self.notification_db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.notification_db_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS notified_jobs (job_id TEXT PRIMARY KEY, notified_at TEXT NOT NULL)")

    def _already_notified(self, job_id: str) -> bool:
        with sqlite3.connect(self.notification_db_path) as db:
            return db.execute("SELECT 1 FROM notified_jobs WHERE job_id=?", (job_id,)).fetchone() is not None

    def _mark_notified(self, job_id: str) -> None:
        with sqlite3.connect(self.notification_db_path) as db:
            db.execute("INSERT OR IGNORE INTO notified_jobs(job_id,notified_at) VALUES(?,?)", (job_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))

    def qudron_result_text(self, job_id: str) -> str:
        if not job_id or len(job_id) > 100 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for ch in job_id):
            raise ValueError("invalid_job_id")
        request = urllib.request.Request(
            f"{self.qudron_url}/jobs/{urllib.parse.quote(job_id, safe='')}/result",
            headers={"Authorization": f"Bearer {self.api_token}"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def poll_completion_notifications(self) -> int:
        if not self.owner_ids:
            return 0
        payload = self.qudron("/status")
        jobs = payload.get("latest_jobs", []) if isinstance(payload, dict) else []
        sent = 0
        for job in jobs if isinstance(jobs, list) else []:
            if not isinstance(job, dict):
                continue
            job_id = str(job.get("id", ""))
            status = job.get("status")
            if not job_id or status not in {"completed", "failed"} or self._already_notified(job_id):
                continue
            title = str(job.get("title", "Qudron task"))[:100]
            if status == "completed" and job.get("result_available"):
                try:
                    result = self.qudron_result_text(job_id).strip()
                except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError):
                    logging.warning("Could not retrieve completed report for notification; job_id=%s", job_id)
                    continue
                message = f"Qudron task completed: {title}\nID: {job_id}\n\n{result[:2500]}"
            else:
                message = f"Qudron task failed: {title}\nID: {job_id}\nCheck /status for the queue summary."
            for owner_id in self.owner_ids:
                self.send(owner_id, message)
            self._mark_notified(job_id)
            sent += 1
        return sent

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", "")) if isinstance(chat, dict) else ""
        # Owner commands are accepted only in a one-to-one private chat.
        if not isinstance(chat, dict) or chat.get("type") != "private":
            return
        sender = message.get("from", {})
        sender_id = str(sender.get("id", "")) if isinstance(sender, dict) else ""
        if not chat_id or chat_id not in self.owner_ids or sender_id != chat_id:
            return
        text = message.get("text", "")
        if not isinstance(text, str):
            self.send(chat_id, "For security, send text commands only.")
            return
        command, argument = parse_command(text)
        update_id = int(update.get("update_id", 0))
        try:
            if command in {"/start", "/help"}:
                self.send(chat_id,
                    "Qudron owner console\n"
                    "/status — queue status\n"
                    "/usage — model usage and known cost\n"
                    "/task your research or drafting request — enqueue an internal task\n"
                    "Only internal research/draft tasks are enabled. External messages and publishing are not.")
            elif command == "/status":
                self.send(chat_id, format_status(self.qudron("/status")))
            elif command == "/usage":
                self.send(chat_id, format_usage(self.qudron("/usage")))
            elif command == "/task":
                if len(argument) < 8:
                    self.send(chat_id, "Add a task after /task (at least 8 characters).")
                    return
                result = self.enqueue_research(update_id, argument)
                job = result.get("job", {}) if isinstance(result, dict) else {}
                self.send(chat_id,
                    f"Task {'created' if result.get('created') else 'already received'}.\n"
                    f"ID: {job.get('id', 'unknown')}\nStatus: {job.get('status', 'unknown')}")
            else:
                self.send(chat_id, "Unknown command. Send /help.")
        except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError):
            # Do not echo provider/transport details or user prompt into logs/chat.
            logging.warning("Telegram command failed: command=%s update_id=%s", command, update_id)
            self.send(chat_id, "Qudron could not complete that request. Check the runtime and try again.")

    def run(self) -> None:
        if not self.token or len(self.token) < 20:
            raise RuntimeError("TELEGRAM_BOT_TOKEN must be configured")
        if not self.api_token or len(self.api_token) < 32:
            raise RuntimeError("QUDRON_API_TOKEN must be configured")
        if not self.owner_ids:
            raise RuntimeError("TELEGRAM_OWNER_CHAT_IDS must contain at least one owner chat ID")
        logging.info("Qudron Telegram owner gateway starting; owner allowlist entries=%d", len(self.owner_ids))
        while True:
            try:
                result = self.telegram("getUpdates", {
                    "offset": self.offset,
                    "timeout": 50,
                    "allowed_updates": ["message"],
                })
                if time.monotonic() - self.last_completion_poll >= 60:
                    try:
                        self.poll_completion_notifications()
                    except Exception:
                        logging.warning("Completion notification poll failed; will retry")
                    self.last_completion_poll = time.monotonic()
                for update in result.get("result", []):
                    if not isinstance(update, dict):
                        continue
                    self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
                    self.handle_update(update)
            except KeyboardInterrupt:
                raise
            except Exception:
                logging.warning("Telegram polling failed; retrying after bounded delay")
                time.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    TelegramGateway().run()
