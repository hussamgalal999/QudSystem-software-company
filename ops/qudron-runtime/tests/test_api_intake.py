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


    def test_completed_result_is_available_only_through_authenticated_safe_endpoint(self):
        status, body = self.post(self.payload(), "unit-test-token")
        job_id = body["job"]["id"]
        report_dir = Path(worker.REPORTS_DIR)
        report_dir.mkdir(parents=True, exist_ok=True)
        report = report_dir / "safe-result.md"
        report.write_text("# Verified draft\\nNo private data.\\n", encoding="utf-8")
        with worker.connect_db() as db:
            db.execute(
                "UPDATE jobs SET status='completed',result_path=?,updated_at=? WHERE id=?",
                (str(report), worker.iso_now(), job_id)
            )

        request = urllib.request.Request(
            self.base + f"/jobs/{job_id}/result",
            headers={"Authorization":"Bearer unit-test-token"}
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/markdown", response.headers.get("Content-Type", ""))
            self.assertIn("Verified draft", response.read().decode())

        unauthenticated = urllib.request.Request(self.base + f"/jobs/{job_id}/result")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(unauthenticated, timeout=3)
        self.assertEqual(ctx.exception.code, 401)

    def test_result_endpoint_rejects_paths_outside_reports_directory(self):
        status, body = self.post(self.payload(), "unit-test-token")
        job_id = body["job"]["id"]
        outside = Path(self.temp.name) / "outside.md"
        outside.write_text("not a report", encoding="utf-8")
        with worker.connect_db() as db:
            db.execute(
                "UPDATE jobs SET status='completed',result_path=? WHERE id=?",
                (str(outside), job_id)
            )
        request = urllib.request.Request(
            self.base + f"/jobs/{job_id}/result",
            headers={"Authorization":"Bearer unit-test-token"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(ctx.exception.code, 404)

    def test_pending_result_endpoint_returns_conflict_not_file_path(self):
        status, body = self.post(self.payload(), "unit-test-token")
        job_id = body["job"]["id"]
        request = urllib.request.Request(
            self.base + f"/jobs/{job_id}/result",
            headers={"Authorization":"Bearer unit-test-token"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(ctx.exception.code, 409)

        status_request = urllib.request.Request(
            self.base + f"/jobs/{job_id}",
            headers={"Authorization":"Bearer unit-test-token"}
        )
        with urllib.request.urlopen(status_request, timeout=3) as response:
            payload = json.loads(response.read().decode())
        self.assertNotIn("result_path", payload)


    def test_usage_dashboard_requires_authentication_and_returns_aggregate_costs(self):
        worker.record_model_usage(
            "job-usage","copywriter","balanced","test-model",
            {"usage":{"prompt_tokens":200,"completion_tokens":100,"total_tokens":300,"cost":0.0005}},
            None
        )
        request = urllib.request.Request(self.base + "/usage")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(ctx.exception.code, 401)

        request = urllib.request.Request(
            self.base + "/usage", headers={"Authorization":"Bearer unit-test-token"}
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            body = json.loads(response.read().decode())
        self.assertEqual(response.status, 200)
        self.assertEqual(body["daily"]["calls"], 1)
        self.assertEqual(body["daily"]["total_tokens"], 300)
        self.assertAlmostEqual(body["daily"]["cost_usd"], 0.0005, places=8)
        self.assertNotIn("authorization", json.dumps(body).lower())

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
