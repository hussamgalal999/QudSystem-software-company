import asyncio
import json
import unittest
from unittest.mock import patch

from a2a_adapter import A2AHttpAdapter
from mcp_agent_adapter import MCPToolAgentAdapter
from agent_protocol import (
    AgentDescriptor, DataClass, ExecutionMode, TaskEnvelope, TaskStatus,
)


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, *_):
        return self.data


class AgentAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.task = TaskEnvelope(
            task_id="local-task-1", project_id="qudron",
            idempotency_key="idempotency-1", title="Research",
            instruction="Research public model docs.",
            required_skills=("research",), data_class=DataClass.PUBLIC,
            execution_mode=ExecutionMode.SEQUENTIAL,
        )

    async def test_a2a_submit_and_poll(self):
        agent = AgentDescriptor(
            agent_id="a2a-research", display_name="Research Agent",
            provider_id="remote-a2a", adapter="a2a",
            skills=("research",), enabled=True, health="healthy",
            quality_score=0.9, access_mode="a2a_authorized_free",
            price_class="free", last_verified_at=1.0,
            endpoint_ref="https://agent.example.com",
        )
        responses = [
            {"task": {"id": "remote-123", "status": {"state": "working"}, "contextId": "ctx-1"}},
            {"id": "remote-123", "status": {"state": "completed"}, "artifacts": []},
        ]
        def fake_urlopen(request, timeout=0):
            return FakeResponse(responses.pop(0))
        with patch("a2a_adapter.urlopen", side_effect=fake_urlopen):
            adapter = A2AHttpAdapter()
            handle = await adapter.submit(agent, self.task)
            result = await adapter.poll(agent, handle)
        self.assertEqual(handle.remote_task_id, "remote-123")
        self.assertEqual(handle.status, TaskStatus.RUNNING)
        self.assertEqual(result.status, TaskStatus.SUCCEEDED)

    def test_a2a_refuses_plain_remote_http(self):
        agent = AgentDescriptor(
            "bad", "Bad", "bad", "a2a", endpoint_ref="http://external.example.com"
        )
        adapter = A2AHttpAdapter()
        with self.assertRaises(Exception):
            adapter._base(agent)

    async def test_mcp_id_with_status_tool_remains_queued(self):
        agent = AgentDescriptor(
            agent_id="qudron-mcp-async", display_name="Qudron MCP Async Worker",
            provider_id="qudron-local", adapter="mcp",
            skills=("research",), enabled=True, health="healthy",
            quality_score=0.9, access_mode="mcp_authorized_free",
            price_class="free", last_verified_at=1.0,
            endpoint_ref="http://127.0.0.1:8765/mcp",
            metadata={"submit_tool": "submit", "status_tool": "status"},
        )
        def fake_urlopen(request, timeout=0):
            payload = json.loads(request.data)
            result = {} if payload["method"] == "initialize" else {
                "content": [{"type": "text", "text": '{"id":"remote-async-1"}'}],
                "isError": False,
            }
            return FakeResponse({"jsonrpc": "2.0", "id": payload["id"], "result": result})
        with patch("mcp_agent_adapter.urlopen", side_effect=fake_urlopen):
            handle = await MCPToolAgentAdapter().submit(agent, self.task)
        self.assertEqual(handle.remote_task_id, "remote-async-1")
        self.assertEqual(handle.status, TaskStatus.QUEUED)
        self.assertIsNone(handle.metadata["immediate_text"])
        self.assertEqual(handle.metadata["status_tool"], "status")

    async def test_mcp_tool_adapter_uses_explicit_tool_name(self):
        agent = AgentDescriptor(
            agent_id="qudron-mcp", display_name="Qudron MCP Worker",
            provider_id="qudron-local", adapter="mcp",
            skills=("research",), enabled=True, health="healthy",
            quality_score=0.9, access_mode="mcp_authorized_free",
            price_class="free", last_verified_at=1.0,
            endpoint_ref="http://127.0.0.1:8765/mcp",
            metadata={"submit_tool": "qudron_submit_job", "task_type": "research"},
        )
        calls = []
        def fake_urlopen(request, timeout=0):
            payload = json.loads(request.data)
            calls.append(payload)
            if payload["method"] == "initialize":
                return FakeResponse({"jsonrpc": "2.0", "id": payload["id"], "result": {}})
            return FakeResponse({"jsonrpc": "2.0", "id": payload["id"], "result": {
                "content": [{"type": "text", "text": '{"job_id":"remote-job-1"}'}],
                "isError": False,
            }})
        with patch("mcp_agent_adapter.urlopen", side_effect=fake_urlopen):
            handle = await MCPToolAgentAdapter().submit(agent, self.task)
        self.assertEqual(handle.remote_task_id, "remote-job-1")
        self.assertEqual([c["method"] for c in calls], ["initialize", "tools/call"])
        self.assertEqual(calls[1]["params"]["name"], "qudron_submit_job")


if __name__ == "__main__":
    unittest.main()
