import unittest

from mcp_gateway import handle_mcp_request


class MCPContinuityToolTests(unittest.TestCase):
    def handle(self, payload, memories=None):
        return handle_mcp_request(
            payload,
            is_authorized=lambda: True,
            enqueue_job=lambda _: {},
            get_job=lambda _: {},
            get_job_result=lambda _: "",
            get_status=lambda: {"continuity": {"saved_agent_memories": 3}},
            get_usage=lambda: {},
            get_continuity=lambda: {"agent_stage_counts": {"completed": 4}},
            get_agent_memory=lambda agent_id, project, limit: (
                memories.append((agent_id, project, limit)) or
                "Persistent role memory: prior verified result."
            ),
        )

    def test_continuity_tools_are_registered_as_read_only(self):
        result = self.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}
        })
        tools = {item["name"]: item for item in result["result"]["tools"]}
        for name in ("qudron_get_continuity", "qudron_get_agent_memory"):
            self.assertTrue(tools[name]["annotations"]["readOnlyHint"])
            self.assertFalse(tools[name]["annotations"]["destructiveHint"])

    def test_continuity_snapshot_returns_stage_and_memory_counts(self):
        result = self.handle({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "qudron_get_continuity", "arguments": {}},
        })
        text = result["result"]["content"][0]["text"]
        self.assertIn('"completed": 4', text)

    def test_agent_memory_is_scoped_to_role_and_project(self):
        calls = []
        result = self.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {
                "name": "qudron_get_agent_memory",
                "arguments": {"agent_id": "security_test_analyst", "project": "qudron", "limit": 4},
            },
        }, memories=calls)
        self.assertEqual(calls, [("security_test_analyst", "qudron", 4)])
        self.assertIn("Persistent role memory", result["result"]["content"][0]["text"])

    def test_invalid_agent_memory_limit_is_rejected(self):
        calls = []
        result = self.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {
                "name": "qudron_get_agent_memory",
                "arguments": {"agent_id": "qa_engineer", "project": "qudron", "limit": 100},
            },
        }, memories=calls)
        self.assertTrue(result["result"]["isError"])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
