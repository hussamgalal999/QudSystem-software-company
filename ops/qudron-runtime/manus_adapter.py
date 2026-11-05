"""Opt-in Manus API v2 adapter.

Uses the documented REST API and persists external task references through
ContinuityStore. It does not scrape browser sessions, export cookies, bypass
account limits, or assume Manus API access is free. The adapter is disabled
until an owner configures an authorized Manus API/OAuth credential.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from continuity_store import ContinuityStore


class ManusAPIError(RuntimeError):
    pass


class ManusAdapter:
    BASE_URL = "https://api.manus.ai"

    def __init__(
        self, credential: str, *, credential_type: str = "api_key",
        base_url: str | None = None, timeout: int = 30, retries: int = 2,
        store: ContinuityStore | None = None,
    ):
        if not credential or not credential.strip():
            raise ManusAPIError("Manus credential is not configured")
        if credential_type not in {"api_key", "oauth"}:
            raise ValueError("credential_type must be api_key or oauth")
        self.credential = credential.strip()
        self.credential_type = credential_type
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = max(5, min(120, int(timeout)))
        self.retries = max(0, min(4, int(retries)))
        self.store = store

    @classmethod
    def from_environment(cls, store: ContinuityStore | None = None) -> "ManusAdapter":
        enabled = os.getenv("QUDRON_MANUS_ENABLED", "false").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            raise ManusAPIError("Manus adapter is disabled; owner opt-in is required")
        credential_type = os.getenv("QUDRON_MANUS_CREDENTIAL_TYPE", "api_key").strip().lower()
        if credential_type == "oauth":
            credential = os.getenv("MANUS_ACCESS_TOKEN", "")
        else:
            credential = os.getenv("MANUS_API_KEY", "")
        return cls(
            credential,
            credential_type=credential_type,
            timeout=int(os.getenv("QUDRON_MANUS_TIMEOUT_SECONDS", "30")),
            retries=int(os.getenv("QUDRON_MANUS_RETRIES", "2")),
            store=store,
        )

    def _headers(self) -> dict[str, str]:
        if self.credential_type == "oauth":
            return {"Authorization": f"Bearer {self.credential}", "Content-Type": "application/json"}
        return {"x-manus-api-key": self.credential, "Content-Type": "application/json"}

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url + path
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = self._headers()
        request = Request(url, data=data, headers=headers, method=method)
        last_error = "unknown error"
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read(2_000_001)
                    if len(raw) > 2_000_000:
                        raise ManusAPIError("Manus response exceeded the 2 MB safety limit")
                    result = json.loads(raw.decode("utf-8"))
                if not isinstance(result, dict) or result.get("ok") is False:
                    detail = result.get("error", {}) if isinstance(result, dict) else {}
                    raise ManusAPIError(str(detail.get("message", "Manus returned an invalid response"))[:1000])
                return result
            except HTTPError as exc:
                last_error = f"HTTP {exc.code}"
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= self.retries:
                    raise ManusAPIError(f"Manus request failed: {last_error}") from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = type(exc).__name__
                if attempt >= self.retries:
                    raise ManusAPIError(f"Manus request failed: {last_error}") from exc
            time.sleep(min(8, 2 ** attempt))
        raise ManusAPIError(f"Manus request failed: {last_error}")

    def create_task(
        self, *, prompt: str, title: str, agent_id: str = "manus_operator",
        local_job_id: str | None = None, project_id: str | None = None,
        agent_profile: str = "standard", locale: str = "en-US",
        connectors: list[str] | None = None, enable_skills: list[str] | None = None,
        task_references: list[str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 24000:
            raise ValueError("prompt must contain 1-24000 characters")
        allowed_profiles = {
            "standard", "lite", "max", "max-medium", "max-high", "max-extra", "max-ultra"
        }
        if agent_profile not in allowed_profiles:
            raise ValueError("Unsupported Manus agent_profile")
        message: dict[str, Any] = {
            "content": [{"type": "text", "text": prompt.strip(), "visibility": "visible"}]
        }
        if connectors:
            message["connectors"] = connectors
        if enable_skills:
            message["enable_skills"] = enable_skills
        if task_references:
            message["task_references"] = task_references
        payload: dict[str, Any] = {
            "message": message,
            "title": title[:160],
            "locale": locale,
            "agent_profile": agent_profile,
            "share_visibility": "private",
            "interactive_mode": False,
        }
        if project_id:
            payload["project_id"] = project_id
        result = self._request("POST", "/v2/task.create", payload)
        task_id = result.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ManusAPIError("Manus did not return a task_id")
        normalized = {
            "provider": "manus",
            "task_id": task_id,
            "task_title": result.get("task_title", title),
            "task_url": result.get("task_url"),
            "status": "submitted",
            "share_visibility": result.get("share_visibility", "private"),
        }
        if self.store:
            self.store.save_external_task(
                provider="manus", external_task_id=task_id, local_job_id=local_job_id,
                agent_id=agent_id, status="submitted", task_url=normalized["task_url"],
                result=normalized,
            )
        return normalized

    def list_messages(
        self, task_id: str, *, order: str = "desc", limit: int = 20,
        verbose: bool = False, start_event_id: str | None = None,
    ) -> dict[str, Any]:
        if not task_id:
            raise ValueError("task_id is required")
        if order not in {"asc", "desc"}:
            raise ValueError("order must be asc or desc")
        limit = max(1, min(100, int(limit)))
        params: dict[str, Any] = {"task_id": task_id, "order": order, "limit": limit}
        if verbose:
            params["verbose"] = "true"
        if start_event_id:
            params["start_event_id"] = start_event_id
        result = self._request("GET", "/v2/task.listMessages?" + urlencode(params))
        events = result.get("events", [])
        status = "unknown"
        last_event_id = None
        for event in events if isinstance(events, list) else []:
            if not isinstance(event, dict):
                continue
            event_id = event.get("id")
            if isinstance(event_id, str):
                last_event_id = event_id
            status_update = event.get("status_update")
            if event.get("type") == "status_update" and isinstance(status_update, dict):
                candidate = status_update.get("agent_status")
                if candidate in {"running", "stopped", "waiting", "error"}:
                    status = candidate
        normalized = {"task_id": task_id, "status": status, "events": events, "last_event_id": last_event_id}
        if self.store:
            self.store.update_external_task(
                provider="manus", external_task_id=task_id, status=status,
                last_event_id=last_event_id, result=normalized,
            )
        return normalized

    def send_message(self, task_id: str, message: str) -> dict[str, Any]:
        if not task_id or not isinstance(message, str) or not message.strip():
            raise ValueError("task_id and a non-empty message are required")
        return self._request("POST", "/v2/task.sendMessage", {
            "task_id": task_id, "message": {"content": message.strip()}
        })

    def task_detail(self, task_id: str) -> dict[str, Any]:
        if not task_id:
            raise ValueError("task_id is required")
        return self._request("GET", "/v2/task.detail?" + urlencode({"task_id": task_id}))
