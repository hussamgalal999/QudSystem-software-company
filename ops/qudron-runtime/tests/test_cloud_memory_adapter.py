import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cloud_memory_adapter import (
    CloudMemoryClient, CloudMemoryError, flush_from_environment, flush_outbox,
)
from continuity_store import ContinuityStore


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, *_):
        return self.data


class CloudMemoryAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ContinuityStore(Path(self.temp.name) / "state.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_memory_sync_is_disabled_without_owner_provisioned_secret(self):
        with patch.dict(os.environ, {
            "QUDRON_MEMORY_URL": "", "QUDRON_MEMORY_TOKEN": "",
        }, clear=False):
            result = flush_from_environment(self.store)
        self.assertFalse(result["enabled"])

    def test_flushes_outbox_idempotently_to_allowed_event_endpoint(self):
        now = "2026-11-05T12:00:00+00:00"
        with self.store.connect() as db:
            self.store._queue_cloud(
                db, "event-1", "/v1/events",
                {
                    "event_id": "event-1", "scope": "project",
                    "scope_id": "qudron", "project_id": "qudron",
                    "event_type": "test", "actor": "tester", "summary": "test event",
                }, now,
            )
        calls = []
        def fake_urlopen(request, timeout=0):
            calls.append(request)
            return FakeResponse({"ok": True, "inserted": True, "event_id": "event-1"})
        client = CloudMemoryClient("https://memory.example.com", "t" * 40)
        with patch("cloud_memory_adapter.urlopen", side_effect=fake_urlopen):
            result = flush_outbox(self.store, client)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(calls), 1)
        payload = json.loads(calls[0].data)
        self.assertEqual(payload["event_id"], "event-1")
        self.assertEqual(self.store.cloud_outbox_snapshot()["sent"], 1)

    def test_failed_cloud_sync_keeps_record_for_retry(self):
        now = "2026-11-05T12:00:00+00:00"
        with self.store.connect() as db:
            self.store._queue_cloud(
                db, "event-2", "/v1/events",
                {"event_id": "event-2", "scope": "project", "scope_id": "qudron",
                 "event_type": "test", "actor": "tester", "summary": "retry"},
                now,
            )
        def fail(*_, **__):
            raise TimeoutError("offline")
        client = CloudMemoryClient("https://memory.example.com", "t" * 40)
        with patch("cloud_memory_adapter.urlopen", side_effect=fail):
            result = flush_outbox(self.store, client)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(self.store.cloud_outbox_snapshot()["pending"], 1)

    def test_unsupported_outbox_route_is_rejected(self):
        client = CloudMemoryClient("https://memory.example.com", "t" * 40)
        with self.assertRaises(CloudMemoryError):
            client._request("POST", "/admin/delete", {})


if __name__ == "__main__":
    unittest.main()
