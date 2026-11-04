import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import qudron_worker as worker

class AuthenticatedIntakeApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        worker.DB_PATH = Path(self.temp.name) / "api.sqlite3"
        worker.init_db()
        self.old_token = worker.API_TOKEN
        worker.API_TOKEN = "unit-test-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), worker.HealthHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        worker.API_TOKEN = self.old_token
        self.temp.cleanup()

    def post(self, payload, token=None):
        body = json.dumps(payload).encode()
        headers = {"Content-Type":"application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(self.base + "/jobs", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def payload(self, **overrides):
        result = {
            "task_type":"research", "title":"Public market scan",
            "role":"Research Analyst", "prompt":"Research publicly available product information.",
            "idempotency_key":"request-2026-001"
        }
        result.update(overrides)
        return result

    def test_unauthenticated_requests_are_rejected(self):
        status, body = self.post(self.payload())
        self.assertEqual(status, 401)
        self.assertIn("unauthorized", body["error"])

    def test_authenticated_job_is_created_and_idempotent(self):
        status1, body1 = self.post(self.payload(), "unit-test-token")
        status2, body2 = self.post(self.payload(title="Different duplicate"), "unit-test-token")
        self.assertEqual(status1, 202)
        self.assertEqual(status2, 200)
        self.assertTrue(body1["created"])
        self.assertFalse(body2["created"])
        self.assertEqual(body1["job"]["id"], body2["job"]["id"])
        with worker.connect_db() as db:
            count = db.execute("SELECT COUNT(*) FROM jobs WHERE job_key='api:request-2026-001'").fetchone()[0]
        self.assertEqual(count, 1)

    def test_customer_cv_and_payment_tasks_are_not_opened_through_generic_api(self):
        for task_type in ("cvpen_cv_creation", "payment_reconciliation", "customer_support_reply"):
            status, body = self.post(self.payload(task_type=task_type), "unit-test-token")
            self.assertEqual(status, 422)
            self.assertIn("not enabled", body["error"])

    def test_invalid_idempotency_key_rejected(self):
        status, body = self.post(self.payload(idempotency_key="x"), "unit-test-token")
        self.assertEqual(status, 422)
        self.assertIn("idempotency_key", body["error"])

    def test_job_status_requires_authentication(self):
        status, body = self.post(self.payload(), "unit-test-token")
        job_id = body["job"]["id"]
        req = urllib.request.Request(self.base + "/jobs/" + job_id)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(ctx.exception.code, 401)
        req = urllib.request.Request(self.base + "/jobs/" + job_id, headers={"Authorization":"Bearer unit-test-token"})
        with urllib.request.urlopen(req, timeout=3) as response:
            status_body = json.loads(response.read().decode())
        self.assertEqual(status_body["status"], "pending")

if __name__ == "__main__":
    unittest.main()
