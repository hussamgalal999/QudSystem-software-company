import json
import unittest
from unittest.mock import patch

from agent_protocol import AgentDescriptor
from mcp_agent_adapter import MCPToolAgentAdapter


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")
        self.headers = {}

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


if __name__ == "__main__":
    unittest.main()
