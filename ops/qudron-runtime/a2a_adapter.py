"""A2A v1 HTTP/JSON adapter for independent agent systems.

A2A agents can be built with different frameworks and vendors. Qudron treats
their tasks as external jobs and persists the returned task IDs/checkpoints.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import uuid

from agent_protocol import (
    AgentDescriptor, AgentTaskHandle, AgentTaskResult, ArtifactRef,
    TaskEnvelope, TaskStatus,
)
from agent_fabric import ProviderUnavailable


class A2AAdapterError(ProviderUnavailable):
    pass


class A2AHttpAdapter:
    def __init__(self, *, timeout_seconds: int = 45, retries: int = 2):
        self.timeout_seconds = max(5, min(180, timeout_seconds))
        self.retries = max(0, min(4, retries))

    def _base(self, agent: AgentDescriptor) -> str:
        base = (agent.endpoint_ref or "").strip()
        parsed = urlparse(base)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise A2AAdapterError("A2A agent endpoint must be an absolute HTTP(S) URL")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise A2AAdapterError("Remote A2A endpoints must use HTTPS")
        return base.rstrip("/") + "/"

    def _headers(self, agent: AgentDescriptor) -> dict[str, str]:
        headers = {
            "Content-Type": "application/a2a+json",
            "Accept": "application/a2a+json, application/json",
            "A2A-Version": "1.0",
        }
        token_env = str(agent.metadata.get("token_env", "")).strip()
        if token_env:
            token = os.getenv(token_env, "").strip()
            if not token:
                raise A2AAdapterError(f"Authorized credential is missing: {token_env}")
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request_sync(
        self, agent: AgentDescriptor, method: str, path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = urljoin(self._base(agent), path.lstrip("/"))
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = Request(url, data=body, headers=self._headers(agent), method=method)
        last = "unknown"
        for attempt in range(self.retries + 1):
            try:
                with urlopen(req, timeout=self.timeout_seconds) as response:
                    raw = response.read(2_000_001)
                    if len(raw) > 2_000_000:
                        raise A2AAdapterError("A2A response exceeded 2 MB safety limit")
                    result = json.loads(raw.decode("utf-8"))
                if not isinstance(result, dict):
                    raise A2AAdapterError("A2A response is not a JSON object")
                return result
            except HTTPError as exc:
                last = f"HTTP {exc.code}"
                if exc.code not in {408, 429, 500, 502, 503, 504} or attempt >= self.retries:
                    raise A2AAdapterError(f"A2A request failed: {last}") from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = type(exc).__name__
                if attempt >= self.retries:
                    raise A2AAdapterError(f"A2A request failed: {last}") from exc
            time.sleep(min(5, 2 ** attempt))
        raise A2AAdapterError(f"A2A request failed: {last}")

    async def discover(self, agent: AgentDescriptor) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request_sync, agent, "GET", "/.well-known/agent-card.json"
        )

    @staticmethod
    def _state(task: dict[str, Any]) -> TaskStatus:
        status = task.get("status")
        raw = status.get("state") if isinstance(status, dict) else status
        mapping = {
            "submitted": TaskStatus.QUEUED,
            "working": TaskStatus.RUNNING,
            "input-required": TaskStatus.WAITING_FOR_INPUT,
            "auth-required": TaskStatus.WAITING_FOR_APPROVAL,
            "completed": TaskStatus.SUCCEEDED,
            "failed": TaskStatus.FAILED,
            "canceled": TaskStatus.CANCELLED,
            "rejected": TaskStatus.FAILED,
        }
        return mapping.get(str(raw).lower(), TaskStatus.RUNNING)

    @staticmethod
    def _message(task: TaskEnvelope, task_id: str | None = None) -> dict[str, Any]:
        message_id = str(uuid.UUID(task.idempotency_key[:32])) if re.fullmatch(
            r"[0-9a-fA-F]{32}", task.idempotency_key
        ) else str(uuid.uuid5(uuid.NAMESPACE_URL, task.idempotency_key))
        message: dict[str, Any] = {
            "messageId": message_id,
            "role": "user",
            "parts": [{"kind": "text", "text": task.instruction}],
            "contextId": task.correlation_id or task.project_id,
            "metadata": {
                "qudron.task_id": task.task_id,
                "qudron.project_id": task.project_id,
                "qudron.execution_mode": task.execution_mode.value,
                "qudron.data_class": task.data_class.value,
                "qudron.idempotency_key": task.idempotency_key,
                "qudron.resource_claims": [
                    {"resource": c.resource, "mode": c.mode.value}
                    for c in task.resource_claims
                ],
            },
        }
        if task_id:
            message["taskId"] = task_id
        return message

    @staticmethod
    def _artifacts(task: dict[str, Any], agent_id: str) -> tuple[ArtifactRef, ...]:
        found: list[ArtifactRef] = []
        for artifact in task.get("artifacts", []) if isinstance(task.get("artifacts"), list) else []:
            if not isinstance(artifact, dict):
                continue
            parts = artifact.get("parts", [])
            for part in parts if isinstance(parts, list) else []:
                if not isinstance(part, dict) or not isinstance(part.get("file"), dict):
                    continue
                file = part["file"]
                uri = file.get("uri")
                if not isinstance(uri, str) or not uri:
                    continue
                found.append(ArtifactRef(
                    artifact_id=str(artifact.get("artifactId") or uuid.uuid4().hex),
                    uri=uri,
                    media_type=str(file.get("mimeType") or "application/octet-stream"),
                    created_by=agent_id,
                    verified=False,
                ))
        return tuple(found)

    async def submit(self, agent: AgentDescriptor, task: TaskEnvelope) -> AgentTaskHandle:
        payload = {"message": self._message(task)}
        result = await asyncio.to_thread(
            self._request_sync, agent, "POST", "/message:send", payload
        )
        remote_task = result.get("task") if isinstance(result.get("task"), dict) else None
        if remote_task:
            remote_id = remote_task.get("id")
            if not isinstance(remote_id, str) or not remote_id:
                raise A2AAdapterError("A2A accepted the message without a task ID")
            return AgentTaskHandle(
                provider_id=agent.provider_id, remote_task_id=remote_id,
                status=self._state(remote_task),
                task_url=agent.endpoint_ref.rstrip("/") + "/tasks/" + remote_id,
                metadata={"protocol": "a2a", "context_id": remote_task.get("contextId")},
            )
        direct = result.get("message")
        if isinstance(direct, dict):
            direct_text = " ".join(
                str(part.get("text", "")) for part in direct.get("parts", [])
                if isinstance(part, dict)
            )
            synthetic_id = str(direct.get("messageId") or task.task_id)
            return AgentTaskHandle(
                provider_id=agent.provider_id, remote_task_id=synthetic_id,
                status=TaskStatus.SUCCEEDED,
                metadata={"protocol": "a2a", "direct_message": direct_text},
            )
        raise A2AAdapterError("A2A response contained neither task nor message")

    async def poll(self, agent: AgentDescriptor, handle: AgentTaskHandle) -> AgentTaskResult:
        if handle.provider_id != agent.provider_id:
            raise A2AAdapterError("Task belongs to a different provider")
        if handle.metadata.get("direct_message") is not None:
            return AgentTaskResult(
                provider_id=agent.provider_id, remote_task_id=handle.remote_task_id,
                status=TaskStatus.SUCCEEDED, summary=str(handle.metadata["direct_message"]),
            )
        task = await asyncio.to_thread(
            self._request_sync, agent, "GET",
            "/tasks/" + handle.remote_task_id + "?historyLength=20",
        )
        return AgentTaskResult(
            provider_id=agent.provider_id,
            remote_task_id=handle.remote_task_id,
            status=self._state(task),
            summary=str(task.get("status", {}).get("message", "") if isinstance(task.get("status"), dict) else ""),
            artifacts=self._artifacts(task, agent.agent_id),
            raw_metadata={"context_id": task.get("contextId")},
        )

    async def follow_up(
        self, agent: AgentDescriptor, handle: AgentTaskHandle, message: str
    ) -> AgentTaskHandle:
        if not message.strip():
            raise ValueError("follow-up message cannot be empty")
        payload = {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "user",
                "taskId": handle.remote_task_id,
                "contextId": handle.metadata.get("context_id"),
                "parts": [{"kind": "text", "text": message.strip()}],
            }
        }
        result = await asyncio.to_thread(
            self._request_sync, agent, "POST", "/message:send", payload
        )
        task = result.get("task") if isinstance(result.get("task"), dict) else None
        if not task:
            return AgentTaskHandle(
                provider_id=agent.provider_id, remote_task_id=handle.remote_task_id,
                status=TaskStatus.RUNNING, metadata=handle.metadata,
            )
        return AgentTaskHandle(
            provider_id=agent.provider_id, remote_task_id=str(task.get("id", handle.remote_task_id)),
            status=self._state(task), task_url=handle.task_url, metadata=handle.metadata,
        )

    async def cancel(self, agent: AgentDescriptor, handle: AgentTaskHandle) -> AgentTaskHandle:
        if handle.provider_id != agent.provider_id:
            raise A2AAdapterError("Task belongs to a different provider")
        await asyncio.to_thread(
            self._request_sync, agent, "POST",
            "/tasks/" + handle.remote_task_id + ":cancel", {"id": handle.remote_task_id},
        )
        return AgentTaskHandle(
            provider_id=agent.provider_id, remote_task_id=handle.remote_task_id,
            status=TaskStatus.CANCELLED, task_url=handle.task_url, metadata=handle.metadata,
        )
