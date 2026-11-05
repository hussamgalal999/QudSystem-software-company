"""Optional Cloudflare D1 memory adapter with a durable local outbox.

Local SQLite remains authoritative for execution and never waits on network
memory. When QUDRON_MEMORY_URL/TOKEN are configured, an idempotent outbox
replicates sanitized project/agent/task events to the separate D1 service.
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from continuity_store import ContinuityStore


class CloudMemoryError(RuntimeError):
    pass


class CloudMemoryClient:
    ALLOWED_ENDPOINTS = {
        "/v1/events", "/v1/agents", "/v1/tasks", "/v1/conversations"
    }

    def __init__(self, base_url: str, token: str, timeout_seconds: int = 8):
        if not base_url.startswith("https://") and not base_url.startswith("http://127.0.0.1"):
            raise ValueError("Cloud memory must use HTTPS or local loopback HTTP")
        if not token or len(token) < 32:
            raise ValueError("Cloud memory token must contain at least 32 characters")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = max(2, min(30, int(timeout_seconds)))

    @classmethod
    def from_environment(cls) -> "CloudMemoryClient | None":
        url = os.getenv("QUDRON_MEMORY_URL", "").strip()
        token = os.getenv("QUDRON_MEMORY_TOKEN", "").strip()
        if not url and not token:
            return None
        if not url or not token:
            raise CloudMemoryError(
                "Both QUDRON_MEMORY_URL and QUDRON_MEMORY_TOKEN are required"
            )
        return cls(
            url, token,
            int(os.getenv("QUDRON_MEMORY_TIMEOUT_SECONDS", "8")),
        )

    def _request(
        self, method: str, endpoint: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if endpoint not in self.ALLOWED_ENDPOINTS and endpoint != "/health":
            raise CloudMemoryError("Cloud-memory endpoint is not allowlisted")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        request = Request(
            self.base_url + endpoint, data=data, headers=headers, method=method
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise CloudMemoryError("Cloud-memory response exceeded 1 MB")
                result = json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            # Do not store response bodies; they may contain private service data.
            raise CloudMemoryError(f"Cloud-memory HTTP {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise CloudMemoryError(f"Cloud-memory request failed: {type(exc).__name__}") from exc
        if not isinstance(result, dict) or result.get("error"):
            raise CloudMemoryError("Cloud-memory service returned an invalid/error response")
        return result

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def append_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/events", payload)

    def upsert_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/agents", payload)

    def upsert_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/tasks", payload)

    def save_conversation_note(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/conversations", payload)

    def get_context(
        self, *, project_id: str | None = None,
        agent_id: str | None = None, limit: int = 30,
    ) -> dict[str, Any]:
        if not project_id and not agent_id:
            raise ValueError("project_id or agent_id is required")
        query = {"limit": max(1, min(100, int(limit)))}
        if project_id:
            query["project_id"] = project_id
        if agent_id:
            query["agent_id"] = agent_id
        request = Request(
            self.base_url + "/v1/context?" + urlencode(query),
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise CloudMemoryError("Cloud-memory context exceeded 1 MB")
                result = json.loads(raw.decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise CloudMemoryError(f"Cloud-memory context failed: {type(exc).__name__}") from exc
        if not isinstance(result, dict) or result.get("error"):
            raise CloudMemoryError("Cloud-memory context response is invalid")
        return result


def flush_outbox(
    store: ContinuityStore, client: CloudMemoryClient, *, limit: int = 50
) -> dict[str, int]:
    sent = 0
    failed = 0
    for record in store.pending_cloud_outbox(limit):
        outbox_id = str(record["outbox_id"])
        endpoint = str(record["endpoint"])
        try:
            payload = json.loads(str(record["payload_json"]))
            if not isinstance(payload, dict):
                raise CloudMemoryError("Outbox payload is not a JSON object")
            client._request("POST", endpoint, payload)
            store.mark_cloud_outbox_sent(outbox_id)
            sent += 1
        except Exception as exc:
            store.mark_cloud_outbox_failed(
                outbox_id, f"{type(exc).__name__}: {exc}"
            )
            failed += 1
    return {"sent": sent, "failed": failed, "pending": sum(
        store.cloud_outbox_snapshot().values()
    )}


def flush_from_environment(store: ContinuityStore) -> dict[str, Any]:
    client = CloudMemoryClient.from_environment()
    if client is None:
        return {"enabled": False, "sent": 0, "failed": 0}
    result = flush_outbox(
        store, client,
        limit=int(os.getenv("QUDRON_MEMORY_OUTBOX_BATCH", "50")),
    )
    return {"enabled": True, **result}
