"""Owner-controlled Windows UIA worker for Qudron.

Run this in the signed-in user's interactive desktop session, not as a
Session-0 Windows service. It exposes only allowlisted UI Automation actions,
binds to loopback by default, and requires a signed one-time owner approval for
state-changing operations. Arbitrary shell/PowerShell is intentionally absent.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .policy import approval_resource, verify_approval


MUTATING_ACTIONS = {
    "windows.launch_app", "windows.invoke_control", "windows.type_text"
}
READ_ACTIONS = {"windows.list_windows", "windows.inspect_window"}


class WindowsNodeError(RuntimeError):
    pass


class PywinautoAutomation:
    def _desktop(self):
        if sys.platform != "win32":
            raise WindowsNodeError("Windows UI Automation is available only on Windows")
        try:
            from pywinauto import Desktop
        except ImportError as exc:
            raise WindowsNodeError("Install the optional pywinauto dependency on Windows") from exc
        return Desktop(backend="uia")

    def list_windows(self) -> list[dict[str, Any]]:
        result = []
        for window in self._desktop().windows():
            try:
                if not window.is_visible():
                    continue
                result.append({
                    "title": str(window.window_text())[:240],
                    "process_id": int(window.process_id()),
                    "handle": int(window.handle),
                    "control_type": str(window.element_info.control_type),
                })
            except Exception:
                continue
        return result[:100]

    def inspect_window(self, process_id: int) -> dict[str, Any]:
        for window in self._desktop().windows():
            try:
                if int(window.process_id()) != process_id:
                    continue
                controls = []
                for element in window.descendants()[:200]:
                    try:
                        info = element.element_info
                        controls.append({
                            "name": str(info.name or "")[:200],
                            "automation_id": str(info.automation_id or "")[:200],
                            "control_type": str(info.control_type or "")[:80],
                            "enabled": bool(element.is_enabled()),
                            "visible": bool(element.is_visible()),
                        })
                    except Exception:
                        continue
                return {
                    "title": str(window.window_text())[:240],
                    "process_id": process_id,
                    "controls": controls,
                    "control_count": len(controls),
                }
            except Exception:
                continue
        raise WindowsNodeError("Requested process window was not found")

    def launch_app(self, path: str) -> dict[str, Any]:
        if sys.platform != "win32":
            raise WindowsNodeError("App launch is supported only on Windows")
        if not Path(path).is_absolute() or not Path(path).exists():
            raise WindowsNodeError("Configured app path does not exist")
        process = subprocess.Popen([path], shell=False, close_fds=True)
        return {"process_id": process.pid, "launched": True}

    def invoke_control(
        self, process_id: int, automation_id: str, control_type: str
    ) -> dict[str, Any]:
        if not automation_id or not control_type:
            raise WindowsNodeError("automation_id and control_type are required")
        for window in self._desktop().windows():
            try:
                if int(window.process_id()) != process_id:
                    continue
                control = window.child_window(
                    auto_id=automation_id, control_type=control_type
                )
                if not control.exists(timeout=2):
                    continue
                control.click_input()
                return {"invoked": True, "automation_id": automation_id}
            except Exception:
                continue
        raise WindowsNodeError("Allowlisted UI control could not be located or invoked")

    def type_text(
        self, process_id: int, automation_id: str,
        control_type: str, text: str,
    ) -> dict[str, Any]:
        if not isinstance(automation_id, str) or not automation_id.strip():
            raise WindowsNodeError("A non-empty automation_id is required")
        if control_type != "Edit":
            raise WindowsNodeError("Text input is restricted to explicitly identified Edit controls")
        if not isinstance(text, str) or len(text) > 4000:
            raise WindowsNodeError("Text input must contain at most 4,000 characters")
        for window in self._desktop().windows():
            try:
                if int(window.process_id()) != process_id:
                    continue
                control = window.child_window(
                    auto_id=automation_id.strip(), control_type="Edit"
                )
                if not control.exists(timeout=2):
                    continue
                # set_edit_text writes literal content; type_keys interprets
                # braces and modifier characters as keyboard commands.
                setter = getattr(control, "set_edit_text", None)
                if not callable(setter):
                    raise WindowsNodeError("Target Edit control does not support literal text assignment")
                control.set_focus()
                setter(text)
                return {"typed": True, "character_count": len(text)}
            except WindowsNodeError:
                raise
            except Exception:
                continue
        raise WindowsNodeError("Allowlisted Edit control could not be located or filled")


class WindowsNode:
    def __init__(
        self, *, token: str, approval_secret: str,
        database_path: str | Path,
        allowed_apps: dict[str, str] | None = None,
        automation: Any | None = None,
    ):
        if len(token) < 32 or len(approval_secret) < 32:
            raise ValueError("Windows node secrets must each contain at least 32 characters")
        self.token = token
        self.approval_secret = approval_secret
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.allowed_apps = dict(allowed_apps or {})
        self.automation = automation or PywinautoAutomation()
        self._schema()

    def _connect(self):
        import sqlite3
        db = sqlite3.connect(self.database_path, timeout=20, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=20000")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _schema(self) -> None:
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS task_receipts(
              idempotency_key TEXT PRIMARY KEY, task_id TEXT NOT NULL,
              action TEXT NOT NULL, status TEXT NOT NULL,
              safe_result_json TEXT, error_code TEXT,
              created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approval_nonces(
              nonce TEXT PRIMARY KEY, consumed_at REAL NOT NULL, task_id TEXT NOT NULL
            );
            """)

    def health(self) -> dict[str, Any]:
        ui_available = False
        if sys.platform == "win32":
            try:
                import pywinauto  # noqa: F401
                ui_available = True
            except Exception:
                ui_available = False
        return {
            "service": "qudron-windows-node",
            "platform": sys.platform,
            "interactive_user_session_required": True,
            "ui_automation_available": ui_available,
            "capabilities": sorted(READ_ACTIONS | MUTATING_ACTIONS),
            "allowed_application_count": len(self.allowed_apps),
        }

    def _consume_approval(
        self, *, task_id: str, action: str, params: dict[str, Any],
        approval: Any, db: Any,
    ) -> str:
        resource = approval_resource(action, params)
        ok, value = verify_approval(
            self.approval_secret, approval, action=action, resource=resource
        )
        if not ok:
            raise WindowsNodeError(value)
        nonce = str(approval["nonce"])
        try:
            db.execute(
                "INSERT INTO approval_nonces(nonce,consumed_at,task_id) VALUES(?,?,?)",
                (nonce, time.time(), task_id),
            )
        except Exception as exc:
            raise WindowsNodeError("approval_replay_blocked") from exc
        return value

    @staticmethod
    def _safe_result(action: str, raw: dict[str, Any]) -> dict[str, Any]:
        # UI contents may contain customer/private data. Persist only bounded
        # operational metadata; the caller receives the immediate owner result.
        if action == "windows.inspect_window":
            return {
                "process_id": raw.get("process_id"),
                "control_count": raw.get("control_count", 0),
                "inspected": True,
            }
        if action == "windows.list_windows":
            return {"window_count": len(raw.get("windows", [])), "inspected": True}
        if action == "windows.type_text":
            return {"typed": bool(raw.get("typed")), "character_count": raw.get("character_count", 0)}
        return {key: value for key, value in raw.items() if key in {"process_id", "launched", "invoked", "automation_id"}}

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload.get("task_id", "")).strip()
        idempotency_key = str(payload.get("idempotency_key", "")).strip()
        action = str(payload.get("action", "")).strip()
        params = payload.get("parameters", {})
        approval = payload.get("approval")
        if not task_id or not idempotency_key or len(idempotency_key) > 160:
            raise WindowsNodeError("task_id and idempotency_key are required")
        if not isinstance(params, dict):
            raise WindowsNodeError("parameters must be a JSON object")
        if action not in READ_ACTIONS | MUTATING_ACTIONS:
            raise WindowsNodeError("Action is not allowlisted")
        if action == "windows.type_text":
            process_id = params.get("process_id")
            automation_id = params.get("automation_id")
            control_type = params.get("control_type")
            text_value = params.get("text")
            if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id <= 0:
                raise WindowsNodeError("type_text requires a positive integer process_id")
            if not isinstance(automation_id, str) or not automation_id.strip():
                raise WindowsNodeError("type_text requires a non-empty automation_id")
            if control_type != "Edit":
                raise WindowsNodeError("type_text requires the exact Edit control type")
            if not isinstance(text_value, str) or len(text_value) > 4000:
                raise WindowsNodeError("type_text requires a string of at most 4,000 characters")

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT * FROM task_receipts WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if prior:
                replay_status = str(prior["status"])
                replay_error = prior["error_code"]
                if replay_status == "running":
                    # A durable running receipt means the UI action may have
                    # happened before a crash. Never replay a mutating action
                    # just because its completion receipt is missing.
                    replay_status = "unknown"
                    replay_error = "outcome_unknown_requires_reconciliation"
                    db.execute(
                        """UPDATE task_receipts
                           SET status='unknown',error_code=?,updated_at=?
                           WHERE idempotency_key=? AND status='running'""",
                        (replay_error, time.time(), idempotency_key),
                    )
                db.execute("COMMIT")
                return {
                    "task_id": prior["task_id"], "status": replay_status,
                    "error_code": replay_error,
                    "result": json.loads(prior["safe_result_json"] or "{}"),
                    "replayed": True,
                    "reconciliation_required": replay_status == "unknown",
                }

            approved_by = None
            if action in MUTATING_ACTIONS:
                approved_by = self._consume_approval(
                    task_id=task_id, action=action, params=params,
                    approval=approval, db=db,
                )
            db.execute(
                """INSERT INTO task_receipts
                   (idempotency_key,task_id,action,status,created_at,updated_at)
                   VALUES(?,?,?,'running',?,?)""",
                (idempotency_key, task_id, action, time.time(), time.time()),
            )
            db.execute("COMMIT")
        except Exception:
            db.rollback()
            db.close()
            raise

        try:
            if action == "windows.list_windows":
                raw = {"windows": self.automation.list_windows()}
            elif action == "windows.inspect_window":
                raw = self.automation.inspect_window(int(params.get("process_id", 0)))
            elif action == "windows.launch_app":
                alias = str(params.get("app_alias", ""))
                path = self.allowed_apps.get(alias)
                if not path:
                    raise WindowsNodeError("Application alias is not allowlisted")
                raw = self.automation.launch_app(path)
            elif action == "windows.invoke_control":
                raw = self.automation.invoke_control(
                    int(params.get("process_id", 0)),
                    str(params.get("automation_id", "")),
                    str(params.get("control_type", "")),
                )
            else:
                raw = self.automation.type_text(
                    params["process_id"], params["automation_id"],
                    params["control_type"], params["text"],
                )
            safe = self._safe_result(action, raw)
            response = {
                "status": "completed", "task_id": task_id, "result": raw,
                "approved_by": approved_by, "replayed": False,
            }
            db.execute(
                "UPDATE task_receipts SET status='completed',safe_result_json=?,updated_at=? WHERE idempotency_key=?",
                (json.dumps(safe), time.time(), idempotency_key),
            )
            return response
        except Exception as exc:
            code = str(exc)[:300]
            db.execute(
                "UPDATE task_receipts SET status='failed',error_code=?,updated_at=? WHERE idempotency_key=?",
                (code, time.time(), idempotency_key),
            )
            raise WindowsNodeError(code) from exc
        finally:
            db.close()


class Handler(BaseHTTPRequestHandler):
    node: WindowsNode

    def _json(self, status: int, value: dict[str, Any]) -> None:
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, self.node.health())
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/tasks":
            self._json(404, {"error": "not_found"})
            return
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.node.token}"
        import hmac
        if not hmac.compare_digest(supplied, expected):
            self._json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "invalid_content_length"})
            return
        if length < 1 or length > 65_536:
            self._json(413, {"error": "invalid_or_oversized_body"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise WindowsNodeError("JSON object required")
            result = self.node.execute(payload)
            self._json(200, result)
        except (UnicodeDecodeError, json.JSONDecodeError, WindowsNodeError, ValueError) as exc:
            self._json(400, {"error": str(exc)[:500]})

    def log_message(self, fmt: str, *args: Any) -> None:
        # Avoid logging UI text, typed text, credentials or approval payloads.
        sys.stderr.write("Windows node request handled\n")


def main() -> int:
    if sys.platform != "win32":
        print("Windows node must run on a Windows host.", file=sys.stderr)
        return 2
    token = os.getenv("QUDRON_WINDOWS_NODE_TOKEN", "").strip()
    approval_secret = os.getenv("QUDRON_WINDOWS_APPROVAL_SECRET", "").strip()
    apps = json.loads(os.getenv("QUDRON_WINDOWS_ALLOWED_APPS_JSON", "{}"))
    if not isinstance(apps, dict):
        raise ValueError("QUDRON_WINDOWS_ALLOWED_APPS_JSON must be an object")
    if not token or not approval_secret:
        print("Windows node secrets are not configured; refusing to start.", file=sys.stderr)
        return 2
    port = max(1024, min(65535, int(os.getenv("QUDRON_WINDOWS_NODE_PORT", "8787"))))
    node = WindowsNode(
        token=token,
        approval_secret=approval_secret,
        database_path=os.getenv("QUDRON_WINDOWS_NODE_DB", "data/windows-node.sqlite3"),
        allowed_apps={str(k): str(v) for k, v in apps.items()},
    )
    Handler.node = node
    # Always loopback. Use an owner-controlled SSH tunnel for remote Qudron access.
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Qudron Windows node listening on 127.0.0.1:{port} in the interactive user session.")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
