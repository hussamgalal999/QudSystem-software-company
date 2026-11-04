import unittest

from mcp_gateway import PROTOCOL_VERSION, handle_mcp_request


class MCPGatewayTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.authorized = True

    def handle(self, payload):
        return handle_mcp_request(
            payload,
            is_authorized=lambda: self.authorized,
            enqueue_job=lambda args: self.calls.append(("enqueue", args)) or {"id": "job-12345678", "status": "pending"},
            get_job=lambda job_id: self.calls.append(("get_job", job_id)) or {"id": job_id, "status": "completed"},
            get_job_result=lambda job_id: self.calls.append(("get_result", job_id)) or "# report\n\nDraft only.",
            get_status=lambda: {"service": "qudron-runtime", "counts": {"pending": 2}},
            get_usage=lambda: {"daily": {"calls": 3, "known_cost_usd": 0.01}},
        )

    def test_initialize_negotiates_streamable_http_protocol(self):
        result = self.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": PROTOCOL_VERSION}})
        self.assertEqual(result["result"]["protocolVersion"], PROTOCOL_VERSION)
        self.assertIn("tools", result["result"]["capabilities"])

    def test_notifications_return_no_json_response(self):
        self.assertIsNone(self.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_unauthorized_requests_are_rejected_without_calling_tools(self):
        self.authorized = False
        result = self.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": "qudron_get_status", "arguments": {}}})
        self.assertEqual(result["error"]["code"], -32001)
        self.assertEqual(self.calls, [])

    def test_tools_list_has_approval_gate_for_submission(self):
        result = self.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
        tools = {item["name"]: item for item in result["result"]["tools"]}
        self.assertFalse(tools["qudron_submit_job"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["qudron_get_status"]["annotations"]["readOnlyHint"])
        self.assertIn("idempotency_key", tools["qudron_submit_job"]["inputSchema"]["required"])

    def test_submit_job_passes_arguments_to_existing_fail_closed_queue(self):
        args = {"title": "Test research", "prompt": "Research only", "task_type": "research",
                "idempotency_key": "dots-job-0001"}
        result = self.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                              "params": {"name": "qudron_submit_job", "arguments": args}})
        self.assertIn("job-12345678", result["result"]["content"][0]["text"])
        self.assertEqual(self.calls[0], ("enqueue", args))

    def test_read_tools_return_safe_results(self):
        status = self.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                              "params": {"name": "qudron_get_status", "arguments": {}}})
        job = self.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                           "params": {"name": "qudron_get_job", "arguments": {"job_id": "job-12345678"}}})
        report = self.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                              "params": {"name": "qudron_get_job_result", "arguments": {"job_id": "job-12345678"}}})
        usage = self.handle({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                             "params": {"name": "qudron_get_usage", "arguments": {}}})
        self.assertIn('"pending": 2', status["result"]["content"][0]["text"])
        self.assertIn('"completed"', job["result"]["content"][0]["text"])
        self.assertIn("Draft only", report["result"]["content"][0]["text"])
        self.assertIn('"calls": 3', usage["result"]["content"][0]["text"])

    def test_unknown_tool_is_rejected(self):
        result = self.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                              "params": {"name": "unknown", "arguments": {}}})
        self.assertEqual(result["error"]["code"], -32602)

    def test_malformed_requests_are_rejected(self):
        with self.assertRaises(ValueError):
            self.handle([])
        result = self.handle({"jsonrpc": "1.0", "id": 1, "method": "ping"})
        self.assertEqual(result["error"]["code"], -32600)

    def test_tool_error_does_not_leak_exception_details(self):
        result = handle_mcp_request(
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
             "params": {"name": "qudron_get_status", "arguments": {}}},
            is_authorized=lambda: True,
            enqueue_job=lambda _: None,
            get_job=lambda _: None,
            get_job_result=lambda _: None,
            get_status=lambda: (_ for _ in ()).throw(RuntimeError("/secret/path")),
            get_usage=lambda: {},
        )
        text = result["result"]["content"][0]["text"]
        self.assertNotIn("/secret/path", text)


if __name__ == "__main__":
    unittest.main()
