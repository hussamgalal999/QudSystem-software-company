import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap_opendots_mcp as bootstrap


class OpenDotsBootstrapTests(unittest.TestCase):
    def test_creates_dedicated_space_and_commander_dot(self):
        workspace = {"spaces": [], "dots": []}
        calls = []

        def fake_request(url, token, method="GET", payload=None):
            calls.append((url, token, method, payload))
            if url.endswith("/api/spaces"):
                return {"id": "space-qudron"}
            if url.endswith("/api/dots"):
                return {"id": "dot-qudron"}
            raise AssertionError(f"Unexpected request: {url}")

        with patch.object(bootstrap, "request_json", side_effect=fake_request):
            dot_id = bootstrap.ensure_commander_dot(workspace, "owner-token")

        self.assertEqual(dot_id, "dot-qudron")
        self.assertEqual([call[2] for call in calls], ["POST", "POST"])
        self.assertEqual(calls[0][3]["name"], "Qudron Command Room")
        dot_payload = calls[1][3]
        self.assertEqual(dot_payload["name"], "Qudron Commander")
        self.assertEqual(dot_payload["spaceId"], "space-qudron")
        self.assertFalse(dot_payload["appsAllowed"])
        self.assertIn("Qudron is the system that executes tasks", dot_payload["instructions"])

    def test_reuses_existing_qudron_space_and_commander(self):
        workspace = {
            "spaces": [{"id": "space-1", "name": "Qudron Command Room"}],
            "dots": [{"id": "dot-1", "name": "Qudron Commander"}],
        }
        with patch.object(bootstrap, "request_json") as request:
            dot_id = bootstrap.ensure_commander_dot(workspace, "owner-token")
        self.assertEqual(dot_id, "dot-1")
        request.assert_not_called()

    def test_control_room_pages_are_nested_and_created_idempotently(self):
        pages = []
        calls = []

        def fake_request(url, token, method="GET", payload=None):
            calls.append((method, payload))
            if method == "GET":
                return list(pages)
            page = {"id": f"page-{len(pages)+1}", **payload}
            pages.append(page)
            return page

        with patch.object(bootstrap, "OPENDOTS_URL", "http://opendots:4310"), \
             patch.object(bootstrap, "request_json", side_effect=fake_request):
            first = bootstrap.ensure_qudron_pages("space-1", "owner-token")
            second = bootstrap.ensure_qudron_pages("space-1", "owner-token")

        self.assertGreaterEqual(first["total"], 20)
        self.assertEqual(first["created"], first["total"])
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["retained"], first["total"])
        by_title = {page["title"]: page for page in pages}
        self.assertIsNone(by_title["01 — Master Task Registry"]["parentId"])
        self.assertEqual(
            by_title["Active, Blocked & Waiting"]["parentId"],
            by_title["01 — Master Task Registry"]["id"],
        )
        self.assertEqual(
            by_title["Agent Memory & Resume"]["parentId"],
            by_title["02 — Agent Workforce"]["id"],
        )

    def test_main_creates_connection_to_qudron_commander(self):
        with tempfile.TemporaryDirectory() as directory:
            owner_file = Path(directory) / "owner-token"
            qudron_file = Path(directory) / "qudron-token"
            owner_file.write_text("o" * 48)
            qudron_file.write_text("q" * 48)
            workspace = {
                "spaces": [{"id": "space-1", "name": "Qudron Command Room"}],
                "dots": [{"id": "dot-1", "name": "Qudron Commander"}],
            }
            calls = []

            def fake_request(url, token, method="GET", payload=None):
                calls.append((url, token, method, payload))
                if url.endswith("/api/workspace"):
                    return workspace
                if url.endswith("/api/spaces/space-1/pages"):
                    if method == "GET":
                        return []
                    return {"id": f"page-{sum(1 for item in calls if item[0].endswith('/pages') and item[1] == 'POST')}"}
                if url.endswith("/api/dots/dot-1/connections"):
                    if method == "GET":
                        return []
                    return {"id": "connection-1", "name": "Qudron"}
                raise AssertionError(f"Unexpected request: {url}")

            with patch.object(bootstrap, "OWNER_TOKEN_FILE", owner_file), \
                 patch.object(bootstrap, "QUDRON_TOKEN_FILE", qudron_file), \
                 patch.object(bootstrap, "OPENDOTS_URL", "http://opendots:4310"), \
                 patch.object(bootstrap, "QUDRON_MCP_URL", "http://qudron:8765/mcp"), \
                 patch.object(bootstrap, "request_json", side_effect=fake_request):
                self.assertEqual(bootstrap.main(), 0)

            create = next(
                call for call in calls
                if call[0] == "http://opendots:4310/api/dots/dot-1/connections" and call[2] == "POST"
            )
            self.assertTrue(any(call[0].endswith("/api/spaces/space-1/pages") and call[2] == "POST" for call in calls))
            self.assertEqual(create[0], "http://opendots:4310/api/dots/dot-1/connections")
            self.assertEqual(create[3]["name"], "Qudron")
            self.assertEqual(create[3]["url"], "http://qudron:8765/mcp")
            self.assertEqual(create[3]["token"], "q" * 48)

    def test_existing_connection_is_refreshed_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            owner_file = Path(directory) / "owner-token"
            qudron_file = Path(directory) / "qudron-token"
            owner_file.write_text("o" * 48)
            qudron_file.write_text("q" * 48)
            workspace = {
                "spaces": [{"id": "space-1", "name": "Qudron Command Room"}],
                "dots": [{"id": "dot-1", "name": "Qudron Commander"}],
            }
            calls = []

            def fake_request(url, token, method="GET", payload=None):
                calls.append((url, method))
                if url.endswith("/api/workspace"):
                    return workspace
                if url.endswith("/api/spaces/space-1/pages"):
                    if method == "GET":
                        return []
                    return {"id": "page-created"}
                if url.endswith("/api/dots/dot-1/connections"):
                    return [{"id": "connection-1", "name": "Qudron"}]
                if url.endswith("/api/connections/connection-1/refresh"):
                    return {"id": "connection-1", "error": None, "tools": []}
                raise AssertionError(f"Unexpected request: {url}")

            with patch.object(bootstrap, "OWNER_TOKEN_FILE", owner_file), \
                 patch.object(bootstrap, "QUDRON_TOKEN_FILE", qudron_file), \
                 patch.object(bootstrap, "request_json", side_effect=fake_request):
                self.assertEqual(bootstrap.main(), 0)

            self.assertIn(
                ("http://opendots:4310/api/connections/connection-1/refresh", "POST"),
                calls,
            )
            self.assertFalse(any(method == "DELETE" for _, method in calls))

    def test_invalid_owner_token_fails_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            owner_file = Path(directory) / "owner-token"
            qudron_file = Path(directory) / "qudron-token"
            owner_file.write_text("short")
            qudron_file.write_text("q" * 48)
            with patch.object(bootstrap, "OWNER_TOKEN_FILE", owner_file), \
                 patch.object(bootstrap, "QUDRON_TOKEN_FILE", qudron_file), \
                 patch.object(bootstrap, "request_json") as request:
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.main()
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
