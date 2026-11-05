import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from continuity_store import ContinuityStore
from manus_adapter import ManusAdapter, ManusAPIError


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, _limit=-1):
        return self.payload


class ManusAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ContinuityStore(Path(self.temp.name) / "state.sqlite3")
        self.adapter = ManusAdapter("test-secret", store=self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_create_task_uses_v2_private_task_contract_and_persists_reference(self):
        response = {
            "ok": True, "task_id": "task-abc", "task_title": "Qudron research",
            "task_url": "https://manus.im/app/task-abc", "share_visibility": "private",
        }
        with patch("manus_adapter.urlopen", return_value=FakeResponse(response)) as request:
            result = self.adapter.create_task(
                prompt="Research public model-provider docs.",
                title="Qudron research", local_job_id="job-0001",
            )
        self.assertEqual(result["task_id"], "task-abc")
        args, kwargs = request.call_args
        self.assertIn("/v2/task.create", args[0].full_url)
        payload = json.loads(args[0].data)
        self.assertEqual(payload["share_visibility"], "private")
        self.assertEqual(payload["message"]["content"][0]["text"], "Research public model-provider docs.")
        saved = self.store.external_task(provider="manus", external_task_id="task-abc")
        self.assertEqual(saved["local_job_id"], "job-0001")

    def test_list_messages_persists_external_status_and_checkpoint(self):
        response = {
            "ok": True,
            "messages": [
                {"id": "evt-1", "type": "status_update",
                 "status_update": {"agent_status": "running"}}
            ],
        }
        with patch("manus_adapter.urlopen", return_value=FakeResponse(response)):
            result = self.adapter.list_messages("task-abc")
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["last_event_id"], "evt-1")

    def test_adapter_is_opt_in_and_fails_closed_without_secret(self):
        with patch.dict(os.environ, {"QUDRON_MANUS_ENABLED": "false"}, clear=False):
            with self.assertRaises(ManusAPIError):
                ManusAdapter.from_environment(self.store)
        with patch.dict(os.environ, {"QUDRON_MANUS_ENABLED": "true", "MANUS_API_KEY": ""}, clear=False):
            with self.assertRaises(ManusAPIError):
                ManusAdapter.from_environment(self.store)

    def test_sensitive_share_visibility_cannot_be_made_public_by_default(self):
        with patch("manus_adapter.urlopen", return_value=FakeResponse({
            "ok": True, "task_id": "task-private", "task_url": "https://manus.im/app/task-private"
        })) as request:
            self.adapter.create_task(prompt="Private internal task", title="Private")
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload["share_visibility"], "private")


if __name__ == "__main__":
    unittest.main()
