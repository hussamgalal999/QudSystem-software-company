import json
import unittest
from unittest.mock import patch

from agent_protocol import AgentDescriptor
from mcp_agent_adapter import MCPToolAgentAdapter


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.payload = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, _limit=-1):
        return self.payload


class MCPAgentAdapterSessionTests(unittest.TestCase):
    def setUp(self):
        self.adapter = MCPToolAgentAdapter()
        self.agent = AgentDescriptor(
            agent_id="mcp-worker",
            display_name="MCP Worker",
            provider_id="mcp-provider",
            adapter="mcp",
            endpoint_ref="https://mcp.example.test/mcp",
            metadata={},
        )

    def test_tool_calls_use_the_session_bound_to_the_task_handle(self):
        seen = []

        def fake_open(request, timeout=0, **kwargs):
            seen.append(request)
            return FakeResponse({"jsonrpc": "2.0", "result": {"content": []}})

        with patch("mcp_agent_adapter.open_credential_request", side_effect=fake_open):
            self.adapter._call_tool(
                self.agent, "status", {"job_id": "task-a"}, session_id="session-a"
            )
            self.adapter._call_tool(
                self.agent, "status", {"job_id": "task-b"}, session_id="session-b"
            )

        self.assertEqual(seen[0].get_header("Mcp-session-id"), "session-a")
        self.assertEqual(seen[1].get_header("Mcp-session-id"), "session-b")
        self.assertEqual(len(seen), 2)


    def test_initialize_uses_its_own_response_session_not_stale_endpoint_cache(self):
        endpoint = self.agent.endpoint_ref
        self.adapter._sessions[endpoint] = "stale-session"
        responses = [
            FakeResponse(
                {"jsonrpc": "2.0", "result": {"protocolVersion": "2025-06-18"}},
                headers={"Mcp-Session-Id": "fresh-session"},
            ),
            FakeResponse({"jsonrpc": "2.0", "result": {}}),
        ]
        seen = []

        def fake_open(request, timeout=0, **kwargs):
            seen.append(request)
            return responses.pop(0)

        with patch("mcp_agent_adapter.open_credential_request", side_effect=fake_open):
            session_id = self.adapter._initialize_session(self.agent)

        self.assertEqual(session_id, "fresh-session")
        self.assertIsNone(seen[0].get_header("Mcp-session-id"))
        self.assertEqual(seen[1].get_header("Mcp-session-id"), "fresh-session")

    def test_stateless_initialize_does_not_reuse_another_tasks_cached_session(self):
        endpoint = self.agent.endpoint_ref
        self.adapter._sessions[endpoint] = "stale-session"
        responses = [
            FakeResponse({"jsonrpc": "2.0", "result": {"protocolVersion": "2025-06-18"}}),
            FakeResponse({"jsonrpc": "2.0", "result": {}}),
        ]
        seen = []

        def fake_open(request, timeout=0, **kwargs):
            seen.append(request)
            return responses.pop(0)

        with patch("mcp_agent_adapter.open_credential_request", side_effect=fake_open):
            session_id = self.adapter._initialize_session(self.agent)

        self.assertIsNone(session_id)
        self.assertIsNone(seen[0].get_header("Mcp-session-id"))
        self.assertIsNone(seen[1].get_header("Mcp-session-id"))

    def test_empty_remote_id_uses_local_task_id_fallback(self):
        from agent_protocol import TaskEnvelope, TaskStatus

        task = TaskEnvelope(
            task_id="local-task-0001",
            project_id="qudron",
            idempotency_key="mcp-empty-id-0001",
            title="Test empty provider identifier",
            instruction="Return a safe receipt.",
        )
        receipt = {"content": [{
            "type": "text",
            "text": json.dumps({"job_id": "", "status": "completed"}),
        }]}
        with patch.object(self.adapter, "_initialize_session", return_value=None), \
             patch.object(self.adapter, "_call_tool", return_value=receipt):
            import asyncio
            handle = asyncio.run(self.adapter.submit(
                AgentDescriptor(
                    agent_id="mcp-submit", display_name="MCP Submit",
                    provider_id="mcp-provider", adapter="mcp",
                    endpoint_ref=self.agent.endpoint_ref,
                    metadata={"submit_tool": "submit_task", "status_tool": "get_status"},
                ),
                task,
            ))
        self.assertEqual(handle.remote_task_id, task.task_id)
        self.assertEqual(handle.status, TaskStatus.SUCCEEDED)
        self.assertIsNotNone(handle.metadata["immediate_text"])



if __name__ == "__main__":
    unittest.main()
