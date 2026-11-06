"""MCP adapter for tools that expose bounded agent-like tasks.

MCP servers are tool providers, not automatically autonomous agents. This
adapter wraps an explicitly selected tool and optional status/result tools in
the same Qudron task lifecycle. It never discovers or calls arbitrary tools.
"""
from __future__ import annotations

import asyncio
import json
import os

from endpoint_security import is_allowed_credential_endpoint
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

from agent_protocol import AgentDescriptor, AgentTaskHandle, AgentTaskResult, TaskEnvelope, TaskStatus
from agent_fabric import ProviderUnavailable


class MCPAdapterError(ProviderUnavailable):
    pass


class MCPToolAgentAdapter:
    def __init__(self, *, protocol_version: str = "2025-06-18", timeout_seconds: int = 45):
        self.protocol_version = protocol_version
        self.timeout_seconds = max(5, min(180, timeout_seconds))

    def _request_sync(
        self, agent: AgentDescriptor, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        endpoint = (agent.endpoint_ref or "").strip()
        if not is_allowed_credential_endpoint(endpoint):
            raise MCPAdapterError("MCP endpoint must use HTTPS or an exact loopback HTTP endpoint")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        token_env = str(agent.metadata.get("token_env", "")).strip()
        if token_env:
            token = os.getenv(token_env, "").strip()
            if not token:
                raise MCPAdapterError(f"Authorized credential is missing: {token_env}")
            headers["Authorization"] = f"Bearer {token}"
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params or {},
        }
        request = Request(
            endpoint, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise MCPAdapterError("MCP response exceeded 1 MB safety limit")
                result = json.loads(raw.decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise MCPAdapterError(f"MCP request failed: {type(exc).__name__}") from exc
        if not isinstance(result, dict):
            raise MCPAdapterError("MCP returned an invalid JSON-RPC response")
        if "error" in result:
            error = result["error"]
            raise MCPAdapterError(str(error.get("message", "MCP JSON-RPC error"))[:500])
        return result.get("result", {})

    @staticmethod
    def _text_content(result: dict[str, Any]) -> str:
        content = result.get("content", [])
        if not isinstance(content, list):
            return ""
        return "\n".join(
            str(item.get("text", "")) for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )[:80_000]

    def _call_tool(self, agent: AgentDescriptor, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._request_sync(
            agent, "tools/call", {"name": name, "arguments": arguments}
        )
        if not isinstance(result, dict) or result.get("isError"):
            raise MCPAdapterError(self._text_content(result if isinstance(result, dict) else {})[:500])
        return result

    async def submit(self, agent: AgentDescriptor, task: TaskEnvelope) -> AgentTaskHandle:
        tool_name = str(agent.metadata.get("submit_tool", "")).strip()
        if not tool_name:
            raise MCPAdapterError("MCP agent descriptor is missing its explicit submit_tool")
        await asyncio.to_thread(
            self._request_sync, agent, "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "qudron-agent-fabric", "version": "0.1.0"},
            },
        )
        args = {
            "title": task.title,
            "prompt": task.instruction,
            "task_type": str(agent.metadata.get("task_type", "research")),
            "idempotency_key": task.idempotency_key,
            "role": agent.display_name,
        }
        args.update(agent.metadata.get("fixed_arguments", {}))
        result = await asyncio.to_thread(self._call_tool, agent, tool_name, args)
        text = self._text_content(result)
        parsed: dict[str, Any] = {}
        try:
            parsed = json.loads(text) if text else {}
        except json.JSONDecodeError:
            parsed = {}
        remote_id = parsed.get("job_id") or parsed.get("id") or task.task_id
        status = TaskStatus.QUEUED if parsed.get("job_id") else TaskStatus.SUCCEEDED
        return AgentTaskHandle(
            provider_id=agent.provider_id,
            remote_task_id=str(remote_id),
            status=status,
            task_url=parsed.get("task_url"),
            metadata={
                "protocol": "mcp",
                "submit_tool": tool_name,
                "status_tool": agent.metadata.get("status_tool"),
                "result_tool": agent.metadata.get("result_tool"),
                "immediate_text": text if status == TaskStatus.SUCCEEDED else None,
            },
        )

    async def poll(self, agent: AgentDescriptor, handle: AgentTaskHandle) -> AgentTaskResult:
        if handle.metadata.get("immediate_text") is not None:
            return AgentTaskResult(
                agent.provider_id, handle.remote_task_id, TaskStatus.SUCCEEDED,
                summary=str(handle.metadata["immediate_text"]),
            )
        status_tool = handle.metadata.get("status_tool")
        if not status_tool:
            return AgentTaskResult(
                agent.provider_id, handle.remote_task_id, TaskStatus.RUNNING,
                summary="MCP task submitted; no status_tool was configured.",
            )
        result = await asyncio.to_thread(
            self._call_tool, agent, str(status_tool), {"job_id": handle.remote_task_id}
        )
        raw = self._text_content(result)
        data: dict[str, Any] = {}
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}
        status_value = str(data.get("status", "running")).lower()
        status = {
            "pending": TaskStatus.QUEUED, "queued": TaskStatus.QUEUED,
            "running": TaskStatus.RUNNING, "waiting_for_input": TaskStatus.WAITING_FOR_INPUT,
            "waiting_for_approval": TaskStatus.WAITING_FOR_APPROVAL,
            "completed": TaskStatus.SUCCEEDED, "succeeded": TaskStatus.SUCCEEDED,
            "failed": TaskStatus.FAILED, "cancelled": TaskStatus.CANCELLED,
        }.get(status_value, TaskStatus.RUNNING)
        summary = str(data.get("summary", data.get("result", "")))[:20_000]
        artifacts = ()
        if status == TaskStatus.SUCCEEDED and handle.metadata.get("result_tool"):
            final = await asyncio.to_thread(
                self._call_tool, agent, str(handle.metadata["result_tool"]),
                {"job_id": handle.remote_task_id},
            )
            summary = self._text_content(final)[:80_000]
        return AgentTaskResult(
            agent.provider_id, handle.remote_task_id, status, summary=summary,
            error_message=str(data.get("error", ""))[:1000] or None,
            raw_metadata={"mcp_status": data},
        )

    async def follow_up(self, agent: AgentDescriptor, handle: AgentTaskHandle, message: str) -> AgentTaskHandle:
        follow_tool = agent.metadata.get("follow_up_tool")
        if not follow_tool:
            raise MCPAdapterError("This MCP agent does not expose an explicit follow_up_tool")
        result = await asyncio.to_thread(
            self._call_tool, agent, str(follow_tool),
            {"job_id": handle.remote_task_id, "message": message},
        )
        return AgentTaskHandle(
            agent.provider_id, handle.remote_task_id, TaskStatus.RUNNING,
            metadata={**handle.metadata, "last_follow_up": time.time()},
        )

    async def cancel(self, agent: AgentDescriptor, handle: AgentTaskHandle) -> AgentTaskHandle:
        cancel_tool = agent.metadata.get("cancel_tool")
        if not cancel_tool:
            raise MCPAdapterError("This MCP agent does not expose an explicit cancel_tool")
        await asyncio.to_thread(
            self._call_tool, agent, str(cancel_tool), {"job_id": handle.remote_task_id}
        )
        return AgentTaskHandle(
            agent.provider_id, handle.remote_task_id, TaskStatus.CANCELLED,
            metadata=handle.metadata,
        )
