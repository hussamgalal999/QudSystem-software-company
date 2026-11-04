import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import qudron_worker as worker


class QueueBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "qudron.sqlite3"
        self.db_patch = patch.object(worker, "DB_PATH", self.db)
        self.db_patch.start()
        worker.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def item(self, key, **extra):
        payload = {
            "title": f"Public research {key}",
            "prompt": "Research publicly available information only.",
            "role": "Research Agent",
            "task_type": "research",
            "idempotency_key": key,
        }
        payload.update(extra)
        return payload

    def count_active(self):
        with worker.connect_db() as db:
            return int(db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('pending','running')"
            ).fetchone()[0])

    def test_batch_is_atomic_and_preserves_caller_order(self):
        original, created = worker.enqueue_api_job(self.item("batch-old-0001"))
        self.assertTrue(created)
        payload = {"jobs": [self.item("batch-old-0001"), self.item("batch-new-0002")]}
        result = worker.enqueue_api_batch(payload)
        self.assertEqual(result["created_count"], 1)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertFalse(result["jobs"][0]["created"])
        self.assertEqual(result["jobs"][0]["job"]["id"], original["id"])
        self.assertTrue(result["jobs"][1]["created"])
        self.assertEqual(result["queue"]["active"], 2)

    def test_repeating_batch_is_idempotent(self):
        payload = {"jobs": [self.item("repeat-000001"), self.item("repeat-000002")]}
        first = worker.enqueue_api_batch(payload)
        second = worker.enqueue_api_batch(payload)
        self.assertEqual(first["created_count"], 2)
        self.assertEqual(second["created_count"], 0)
        self.assertEqual(second["duplicate_count"], 2)
        self.assertEqual(
            [x["job"]["id"] for x in first["jobs"]],
            [x["job"]["id"] for x in second["jobs"]],
        )
        self.assertEqual(self.count_active(), 2)

    def test_invalid_item_rejects_entire_batch_without_partial_writes(self):
        payload = {"jobs": [self.item("atomic-000001"), self.item("bad-000002", task_type="payment_reconciliation")]}
        with self.assertRaises(ValueError):
            worker.enqueue_api_batch(payload)
        self.assertEqual(self.count_active(), 0)

    def test_duplicate_idempotency_keys_inside_batch_are_rejected(self):
        payload = {"jobs": [self.item("duplicate-0001"), self.item("duplicate-0001")]}
        with self.assertRaisesRegex(ValueError, "unique"):
            worker.enqueue_api_batch(payload)
        self.assertEqual(self.count_active(), 0)

    def test_queue_capacity_rejects_whole_batch(self):
        with patch.object(worker, "MAX_PENDING_JOBS", 1):
            worker.enqueue_api_job(self.item("capacity-0001"))
            with self.assertRaisesRegex(ValueError, "queue_capacity_reached"):
                worker.enqueue_api_batch({"jobs": [self.item("capacity-0002")]})
        self.assertEqual(self.count_active(), 1)

    def test_single_intake_respects_queue_capacity(self):
        with patch.object(worker, "MAX_PENDING_JOBS", 1):
            worker.enqueue_api_job(self.item("single-cap-0001"))
            with self.assertRaisesRegex(ValueError, "queue_capacity_reached"):
                worker.enqueue_api_job(self.item("single-cap-0002"))
        self.assertEqual(self.count_active(), 1)

    def test_batch_size_is_bounded(self):
        with patch.object(worker, "MAX_API_BATCH_SIZE", 1):
            with self.assertRaisesRegex(ValueError, "between 1 and 1"):
                worker.enqueue_api_batch({"jobs": [self.item("size-000001"), self.item("size-000002")]})

    def test_status_capacity_reports_remaining_slots(self):
        with patch.object(worker, "MAX_PENDING_JOBS", 5):
            worker.enqueue_api_job(self.item("status-cap-0001"))
            snapshot = worker.queue_capacity_snapshot()
        self.assertEqual(snapshot, {"active": 1, "maximum": 5, "remaining": 4})


class PrivateTokenTests(unittest.TestCase):
    def test_api_token_is_generated_persisted_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "api_token"
            with patch.object(worker, "API_TOKEN_FILE", target), patch.dict(os.environ, {"QUDRON_API_TOKEN": ""}):
                first = worker.ensure_api_token()
                second = worker.ensure_api_token()
            self.assertEqual(first, second)
            self.assertGreaterEqual(len(first), 48)
            self.assertEqual(target.read_text().strip(), first)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)


class KeylessProviderPolicyTests(unittest.TestCase):
    def setUp(self):
        self.original = {name: os.environ.get(name) for name in worker.KEYLESS_PROVIDER_KEYS}

    def test_anonymous_freellm_allows_public_research_only(self):
        job = {"task_type": "research"}
        with patch.dict(os.environ, {"FREELM_KEYLESS": "auto"}, clear=False):
            for name in worker.KEYLESS_PROVIDER_KEYS:
                os.environ.pop(name, None)
            self.assertTrue(worker.is_anonymous_freellm_route("http://freellm:4000/v1"))
            worker.validate_keyless_payload(job, "Research official public documentation.", "http://freellm:4000/v1")

    def test_anonymous_freellm_blocks_cv_finance_code_and_private_work(self):
        with patch.dict(os.environ, {"FREELM_KEYLESS": "auto"}, clear=False):
            for name in worker.KEYLESS_PROVIDER_KEYS:
                os.environ.pop(name, None)
            for task_type in ("cvpen_cv_creation", "payment_reconciliation", "engineering_review", "customer_support_reply"):
                with self.subTest(task_type=task_type):
                    with self.assertRaisesRegex(RuntimeError, "limited to public research"):
                        worker.validate_keyless_payload({"task_type": task_type}, "Do the task.", "http://freellm:4000/v1")

    def test_anonymous_freellm_blocks_pii_marked_prompts(self):
        with patch.dict(os.environ, {"FREELM_KEYLESS": "auto"}, clear=False):
            for name in worker.KEYLESS_PROVIDER_KEYS:
                os.environ.pop(name, None)
            with self.assertRaisesRegex(RuntimeError, "sensitive-data redactor"):
                worker.validate_keyless_payload(
                    {"task_type": "research"},
                    "Research this contact: hussamgalal999@gmail.com",
                    "http://freellm:4000/v1",
                )

    def test_provider_key_or_keyless_disabled_disables_anonymous_route(self):
        with patch.dict(os.environ, {"FREELM_KEYLESS": "auto", "GROQ_API_KEY": "configured"}):
            self.assertFalse(worker.is_anonymous_freellm_route("http://freellm:4000/v1"))
        with patch.dict(os.environ, {"FREELM_KEYLESS": "0"}, clear=True):
            self.assertFalse(worker.is_anonymous_freellm_route("http://freellm:4000/v1"))


if __name__ == "__main__":
    unittest.main()
