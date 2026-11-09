import os
import sys
import tempfile
import unittest
import urllib.error
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

            create = next(call for call in calls if call[2] == "POST")
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

    def test_rotated_qudron_token_replaces_only_unauthorized_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            owner_file = Path(directory) / "owner-token"
            qudron_file = Path(directory) / "qudron-token"
            owner_file.write_text("o" * 48)
            qudron_file.write_text("n" * 48)
            workspace = {
                "spaces": [{"id": "space-1", "name": "Qudron Command Room"}],
                "dots": [{"id": "dot-1", "name": "Qudron Commander"}],
            }
            calls = []

            def fake_request(url, token, method="GET", payload=None):
                calls.append((url, token, method, payload))
                if url.endswith("/api/workspace"):
                    return workspace
                if url.endswith("/api/dots/dot-1/connections"):
                    if method == "GET":
                        return [{"id": "old-connection", "name": "Qudron"}]
                    return {"id": "new-connection", "name": "Qudron"}
                if url.endswith("/api/connections/old-connection/refresh"):
                    raise urllib.error.HTTPError(url, 401, "Unauthorized", None, None)
                if url.endswith("/api/connections/old-connection"):
                    self.assertEqual(method, "DELETE")
                    return {}
                raise AssertionError(f"Unexpected request: {url}")

            with patch.object(bootstrap, "OWNER_TOKEN_FILE", owner_file), \
                 patch.object(bootstrap, "QUDRON_TOKEN_FILE", qudron_file), \
                 patch.object(bootstrap, "request_json", side_effect=fake_request):
                self.assertEqual(bootstrap.main(), 0)

            deleted = next(call for call in calls if call[2] == "DELETE")
            created = next(call for call in calls if call[0].endswith("/api/dots/dot-1/connections") and call[2] == "POST")
            self.assertEqual(deleted[0], "http://opendots:4310/api/connections/old-connection")
            self.assertEqual(created[3]["token"], "n" * 48)
            self.assertEqual(created[3]["name"], "Qudron")

    def test_bootstrap_retries_until_private_tokens_are_created(self):
        values = {
            "OPENDOTS_OWNER_TOKEN": ["", "o" * 48],
            "QUDRON_API_TOKEN": ["", "q" * 48],
        }

        def read_secret(name, _path):
            return values[name].pop(0)

        workspace = {
            "spaces": [{"id": "space-1", "name": "Qudron Command Room"}],
            "dots": [{"id": "dot-1", "name": "Qudron Commander"}],
        }
        calls = []

        def fake_request(url, token, method="GET", payload=None):
            calls.append((url, method, payload))
            if url.endswith("/api/workspace"):
                return workspace
            if url.endswith("/api/dots/dot-1/connections"):
                if method == "GET":
                    return []
                return {"id": "connection-1", "name": "Qudron"}
            raise AssertionError(f"Unexpected request: {url}")

        with patch.object(bootstrap, "read_secret", side_effect=read_secret), \
             patch.object(bootstrap.time, "sleep"), \
             patch.object(bootstrap, "request_json", side_effect=fake_request):
            self.assertEqual(bootstrap.main(), 0)

        self.assertTrue(any(url.endswith("/api/workspace") for url, _, _ in calls))

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
