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
            enqueue_batch=lambda args: self.calls.append(("batch", args)) or {"created_count": len(args["jobs"])},
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
        self.assertEqual(
            tools["qudron_submit_job"]["inputSchema"]["properties"]["data_class"]["default"],
            "internal",
        )
        self.assertIn(
            "restricted",
            tools["qudron_submit_batch"]["inputSchema"]["properties"]["jobs"]["items"]["properties"]["data_class"]["enum"],
        )
        self.assertFalse(tools["qudron_submit_batch"]["annotations"]["readOnlyHint"])
        self.assertEqual(tools["qudron_submit_batch"]["inputSchema"]["properties"]["jobs"]["maxItems"], 100)

    def test_submit_job_passes_arguments_to_existing_fail_closed_queue(self):
        args = {"title": "Test research", "prompt": "Research only", "task_type": "research",
                "idempotency_key": "dots-job-0001", "data_class": "public"}
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

    def test_workforce_and_model_catalogue_tools_are_read_only(self):
        result = self.handle({"jsonrpc": "2.0", "id": 11, "method": "tools/list", "params": {}})
        tools = {item["name"]: item for item in result["result"]["tools"]}
        for name in ("qudron_get_agents", "qudron_get_models", "qudron_search_capabilities"):
            self.assertTrue(tools[name]["annotations"]["readOnlyHint"])

    def test_capability_search_validates_query_and_limit(self):
        captured = []
        result = handle_mcp_request(
            {"jsonrpc": "2.0", "id": 12, "method": "tools/call",
             "params": {"name": "qudron_search_capabilities",
                        "arguments": {"query": "browser", "kind": "tool", "limit": 5}}},
            is_authorized=lambda: True,
            enqueue_job=lambda _: {},
            get_job=lambda _: {},
            get_job_result=lambda _: "",
            get_status=lambda: {},
            get_usage=lambda: {},
            search_capabilities=lambda query, kind, limit: captured.append((query, kind, limit)) or [{"name": "Browser"}],
        )
        self.assertEqual(captured, [("browser", "tool", 5)])
        self.assertIn("Browser", result["result"]["content"][0]["text"])

    def test_submit_batch_uses_atomic_batch_callback(self):
        args = {"jobs": [
            {"title": "Research one", "prompt": "Public source one", "task_type": "research", "idempotency_key": "batch-one-001"},
            {"title": "Research two", "prompt": "Public source two", "task_type": "research", "idempotency_key": "batch-two-002"},
        ]}
        result = self.handle({"jsonrpc": "2.0", "id": 11, "method": "tools/call",
                              "params": {"name": "qudron_submit_batch", "arguments": args}})
        self.assertIn('"created_count": 2', result["result"]["content"][0]["text"])
        self.assertEqual(self.calls[0], ("batch", args))

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
