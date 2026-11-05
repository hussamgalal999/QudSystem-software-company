"""Opt-in end-to-end test; requires a configured Artemis host and real Android device."""
import json
import os
import time
import unittest
import urllib.request


@unittest.skipUnless(os.getenv("QUDRON_ARTEMIS_E2E") == "1", "requires an explicitly enabled Android device")
class ArtemisAndroidBatteryE2ETests(unittest.TestCase):
    def bridge_call(self, name, arguments):
        url = os.environ["ARTEMIS_BRIDGE_URL"].rstrip("/") + "/tools/call"
        body = json.dumps({"name": name, "arguments": arguments}).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Authorization": "Bearer " + os.environ["ARTEMIS_BRIDGE_TOKEN"],
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_open_settings_and_verify_battery_percentage(self):
        device_serial = os.getenv("ARTEMIS_DEVICE_SERIAL", "").strip()
        self.assertTrue(
            device_serial,
            "Set ARTEMIS_DEVICE_SERIAL to the explicitly authorized Android device serial",
        )
        started = self.bridge_call("mobile_run_task", {
            "device_serial": device_serial,
            "task_desc": (
                "Open Android System Settings, navigate to Battery, read the displayed "
                "battery percentage, and report the exact percentage. Do not change any setting."
            ),
            "model": "Pro",
            "expected_output_desc": (
                "Return the observed battery percentage and the UI evidence used to verify it. "
                "If the percentage is not visible, report that honestly."
            ),
            "verification_level": "strict",
        })
        trace_id = (started.get("structuredContent") or {}).get("trace_id")
        if not trace_id:
            for block in started.get("content", []):
                if block.get("type") != "text":
                    continue
                try:
                    decoded = json.loads(block.get("text", ""))
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(decoded, dict) and decoded.get("trace_id"):
                    trace_id = decoded["trace_id"]
                    break
        self.assertTrue(trace_id, "Artemis did not return a trace_id in structured or text content")
        deadline = time.monotonic() + 900
        status = {}
        while time.monotonic() < deadline:
            status = self.bridge_call("mobile_manage_task", {
                "action": "status", "trace_id": trace_id
            })
            status_text = json.dumps(status).lower()
            if any(word in status_text for word in ('"completed"', '"failed"', '"cancelled"')):
                break
            time.sleep(5)
        self.assertIn('"completed"', json.dumps(status).lower(), "Android battery task did not complete")
        summary = self.bridge_call("mobile_inspect_trace", {
            "action": "view_summary", "trace_id": trace_id
        })
        self.assertIn("battery", json.dumps(summary).lower())
