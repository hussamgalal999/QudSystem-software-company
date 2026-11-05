import unittest

from mcp_gateway import ARTEMIS_TOOLS, _validate_artemis_call, handle_mcp_request


class ArtemisMCPIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def handle(self, payload):
        return handle_mcp_request(
            payload,
            is_authorized=lambda: True,
            enqueue_job=lambda _: {},
            get_job=lambda _: {},
            get_job_result=lambda _: "",
            get_status=lambda: {},
            get_usage=lambda: {},
            call_artemis=lambda name, args: self.calls.append((name, args)) or {
                "content": [{"type": "text", "text": "Artemis task accepted"}],
                "isError": False,
            },
        )

    def test_android_tools_are_registered_with_correct_approval_hints(self):
        tools = {item["name"]: item for item in ARTEMIS_TOOLS}
        self.assertFalse(tools["qudron_android_run_task"]["annotations"]["readOnlyHint"])
        self.assertFalse(tools["qudron_android_task_control"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["qudron_android_task_status"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["qudron_android_get_device_state"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["qudron_android_inspect_trace"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["qudron_android_diagnose"]["annotations"]["readOnlyHint"])

    def test_run_task_maps_to_official_artemis_mcp_contract(self):
        result = self.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "qudron_android_run_task", "arguments": {
                "task_desc": "Open Settings and report battery percentage",
                "model": "Pro", "device_serial": "emulator-5554",
                "verification_level": "strict",
            }},
        })
        self.assertEqual(self.calls, [("mobile_run_task", {
            "task_desc": "Open Settings and report battery percentage",
            "model": "Pro", "device_serial": "emulator-5554",
            "verification_level": "strict",
        })])
        self.assertIn("Artemis task accepted", result["result"]["content"][0]["text"])

    def test_status_is_read_only_and_maps_to_manage_task(self):
        self.handle({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "qudron_android_task_status", "arguments": {"trace_id": "trace-123"}},
        })
        self.assertEqual(self.calls[0], ("mobile_manage_task", {
            "action": "status", "trace_id": "trace-123"
        }))

    def test_diagnose_cannot_enable_automatic_repairs_or_credential_probes(self):
        native, args = _validate_artemis_call("qudron_android_diagnose", {})
        self.assertEqual(native, "mobile_diagnose")
        self.assertEqual(args, {
            "attempt_fix": False, "verify_credentials": False, "probe_device": False
        })

    def test_unknown_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            _validate_artemis_call("qudron_android_run_task", {
                "task_desc": "Open Settings", "shell_command": "adb shell"
            })

    def test_stop_control_is_explicitly_mapped(self):
        native, args = _validate_artemis_call("qudron_android_task_control", {
            "action": "stop", "trace_id": "trace-123"
        })
        self.assertEqual(native, "mobile_manage_task")
        self.assertEqual(args, {"action": "stop", "trace_id": "trace-123"})


if __name__ == "__main__":
    unittest.main()
