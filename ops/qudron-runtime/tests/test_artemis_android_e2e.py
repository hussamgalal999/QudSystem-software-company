"""Opt-in E2E test through Qudron MCP; requires an authorized Android device."""
import json
import os
from pathlib import Path
import re
import time
import unittest
import urllib.request


@unittest.skipUnless(os.getenv("QUDRON_ARTEMIS_E2E") == "1", "requires explicit owner approval and an authorized Android device")
class ArtemisAndroidBatteryE2ETests(unittest.TestCase):
    mcp_url = os.getenv("QUDRON_MCP_URL", "http://127.0.0.1:8765/mcp").rstrip("/")

    def _token(self):
        token = os.getenv("QUDRON_API_TOKEN", "").strip()
        token_file = os.getenv("QUDRON_API_TOKEN_FILE", "").strip()
        if not token and token_file:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        self.assertTrue(token, "Set QUDRON_API_TOKEN or QUDRON_API_TOKEN_FILE for the Qudron MCP gateway")
        return token

    def mcp(self, method, params=None, request_id=1):
        body = json.dumps({
            "jsonrpc": "2.0", "id": request_id, "method": method,
            "params": params or {},
        }).encode("utf-8")
        request = urllib.request.Request(
            self.mcp_url, data=body, method="POST",
            headers={
                "Authorization": "Bearer " + self._token(),
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _text(result):
        parts = [
            str(block.get("text", ""))
            for block in result.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        structured = result.get("structuredContent")
        if structured is not None:
            parts.append(json.dumps(structured, ensure_ascii=False))
        return "\n".join(parts)

    @staticmethod
    def _trace_id(result):
        structured = result.get("structuredContent") or {}
        if isinstance(structured, dict) and structured.get("trace_id"):
            return structured["trace_id"]
        text = ArtemisAndroidBatteryE2ETests._text(result)
        try:
            decoded = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            decoded = {}
        return decoded.get("trace_id") if isinstance(decoded, dict) else None

    def test_open_settings_and_verify_battery_percentage_via_qudron(self):
        device_serial = os.getenv("ARTEMIS_DEVICE_SERIAL", "").strip()
        self.assertTrue(
            device_serial,
            "Set ARTEMIS_DEVICE_SERIAL to the explicitly authorized Android device serial",
        )
        self.assertTrue(
            os.getenv("ARTEMIS_BRIDGE_URL") and os.getenv("ARTEMIS_BRIDGE_TOKEN"),
            "Configure the authenticated Artemis host bridge before running this test",
        )

        initialized = self.mcp("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "qudron-artemis-e2e", "version": "1.0"},
        }, request_id=1)
        self.assertIn("result", initialized, "Qudron MCP initialization failed")

        started = self.mcp("tools/call", {
            "name": "qudron_android_run_task",
            "arguments": {
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
            },
        }, request_id=2)
        start_result = started.get("result", {})
        self.assertFalse(start_result.get("isError", False), self._text(start_result))
        trace_id = self._trace_id(start_result)
        self.assertTrue(trace_id, "Qudron did not return an Artemis trace_id")

        deadline = time.monotonic() + 900
        status_text = ""
        while time.monotonic() < deadline:
            status = self.mcp("tools/call", {
                "name": "qudron_android_task_status",
                "arguments": {"trace_id": trace_id},
            }, request_id=3)
            status_result = status.get("result", {})
            self.assertFalse(status_result.get("isError", False), self._text(status_result))
            status_text = self._text(status_result).lower()
            if re.search(r'"(?:status|state)"\s*:\s*"completed"', status_text):
                break
            if re.search(r'"(?:status|state)"\s*:\s*"(?:failed|cancelled|error)"', status_text):
                self.fail("Artemis task reached a failure state: " + status_text[:2000])
            time.sleep(5)
        self.assertRegex(status_text, r'"(?:status|state)"\s*:\s*"completed"')

        summary = self.mcp("tools/call", {
            "name": "qudron_android_inspect_trace",
            "arguments": {"action": "view_summary", "trace_id": trace_id},
        }, request_id=4)
        summary_result = summary.get("result", {})
        self.assertFalse(summary_result.get("isError", False), self._text(summary_result))
        summary_text = self._text(summary_result)
        self.assertRegex(summary_text.lower(), r"battery")
        percentages = re.findall(r"(?<!\d)(100|[1-9]?\d)\s*%", summary_text)
        self.assertTrue(
            percentages,
            "Trace summary did not contain a verifiable battery percentage: " + summary_text[:2000],
        )


if __name__ == "__main__":
    unittest.main()
