import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import qudron_worker as worker

class FakeResponse:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def read(self, size=-1):
        payload = json.dumps({
            "choices":[{"message":{"content":"routed response"}}],
            "usage":{"prompt_tokens":100,"completion_tokens":50,"total_tokens":150}
        }).encode()
        return payload if size is None or size < 0 else payload[:size]

class ModelRoutingTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = worker.DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        worker.DB_PATH = Path(self.temp.name) / "usage.sqlite3"
        worker.init_db()

    def tearDown(self):
        worker.DB_PATH = self.original_db_path
        self.temp.cleanup()

    def test_agent_profile_routes_to_external_model_endpoint(self):
        captured = {}
        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode())
            captured["authorization"] = request.get_header("Authorization")
            return FakeResponse()
        with patch.dict("os.environ", {
            "LLM_FAST_BASE_URL":"https://fast.example/v1",
            "LLM_FAST_API_KEY":"test-secret",
            "LLM_FAST_MODEL":"fast-instruct",
            "LLM_FAST_INPUT_USD_PER_1M":"1",
            "LLM_FAST_OUTPUT_USD_PER_1M":"1",
            "QUDRON_MONTHLY_MODEL_BUDGET_USD":"1"
        }, clear=True):
            with patch("qudron_worker.open_credential_request", side_effect=fake_urlopen):
                response = worker.call_llm(
                    {"id":"job-model-test","role":"Research","task_type":"research","title":"Test","prompt":"Do the work"},
                    {"id":"research_analyst","name":"Research Analyst","profile":"fast",
                     "responsibilities":"Research."},
                    "Produce the report.", "", ""
                )
        self.assertEqual(response, "routed response")
        self.assertEqual(captured["url"], "https://fast.example/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "fast-instruct")
        self.assertEqual(captured["payload"]["max_tokens"], worker.MAX_OUTPUT_TOKENS)
        self.assertEqual(captured["authorization"], "Bearer test-secret")
        usage = worker.model_usage_snapshot()
        self.assertEqual(usage["daily"]["calls"], 1)
        self.assertEqual(usage["daily"]["total_tokens"], 150)
        self.assertAlmostEqual(usage["daily"]["cost_usd"], 0.00015, places=8)




    def test_cvpen_creation_fails_closed_without_per_order_budget(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "QUDRON_CVPEN_JOB_BUDGET_USD"):
                worker.reserve_model_budget(
                    "cv-order-1","cv_writer","balanced","cv-model",1000,
                    task_type="cvpen_cv_creation"
                )

    def test_cvpen_per_order_budget_caps_parallel_agent_reservations(self):
        with patch.dict("os.environ", {
            "LLM_BALANCED_INPUT_USD_PER_1M":"1",
            "LLM_BALANCED_OUTPUT_USD_PER_1M":"1",
            "QUDRON_CVPEN_JOB_BUDGET_USD":"0.003"
        }, clear=True):
            first = worker.reserve_model_budget(
                "cv-order-2","cv_writer","balanced","cv-model",1000,
                task_type="cvpen_cv_creation"
            )
            self.assertIsNotNone(first)
            with self.assertRaisesRegex(RuntimeError, "CVPen per-order model budget reached"):
                worker.reserve_model_budget(
                    "cv-order-2","cv_grammar_editor","balanced","cv-model",1000,
                    task_type="cvpen_cv_creation"
                )
            worker.release_model_budget_reservation(first)
        with worker.connect_db() as db:
            remaining = db.execute(
                "SELECT COUNT(*) FROM llm_usage_reservations WHERE job_id='cv-order-2'"
            ).fetchone()[0]
        self.assertEqual(remaining, 0)

    def test_generic_model_calls_fail_closed_without_a_daily_or_monthly_budget(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "fail-closed until QUDRON_DAILY_MODEL_BUDGET_USD"):
                worker.reserve_model_budget(
                    "research-job","research_analyst","balanced","research-model",500,
                    task_type="research"
                )

    def test_non_cvpen_work_can_skip_local_budget_only_in_explicit_dev_mode(self):
        with patch.dict("os.environ", {"QUDRON_REQUIRE_MODEL_BUDGET":"false"}, clear=True):
            reservation = worker.reserve_model_budget(
                "research-job","research_analyst","balanced","research-model",500,
                task_type="research"
            )
        self.assertIsNone(reservation)

    def test_budget_fails_closed_when_profile_pricing_is_missing(self):
        with patch.dict("os.environ", {
            "QUDRON_MONTHLY_MODEL_BUDGET_USD":"5"
        }, clear=True):
            with self.assertRaisesRegex(RuntimeError, "price rates are missing"):
                worker.reserve_model_budget("job-1","research_analyst","balanced","model-x",1000)

    def test_model_budget_reservations_prevent_concurrent_overspend(self):
        with patch.dict("os.environ", {
            "LLM_BALANCED_INPUT_USD_PER_1M":"1",
            "LLM_BALANCED_OUTPUT_USD_PER_1M":"1",
            "QUDRON_MONTHLY_MODEL_BUDGET_USD":"0.0025"
        }, clear=True):
            first = worker.reserve_model_budget("job-1","writer","balanced","model-x",1000)
            self.assertIsNotNone(first)
            with self.assertRaisesRegex(RuntimeError, "monthly model budget reached"):
                worker.reserve_model_budget("job-2","reviewer","balanced","model-x",1000)
            worker.release_model_budget_reservation(first)
            with worker.connect_db() as db:
                count = db.execute("SELECT COUNT(*) FROM llm_usage_reservations").fetchone()[0]
            self.assertEqual(count, 0)


    def test_stale_model_budget_reservations_are_reclaimed(self):
        stale_time = (worker.utc_now() - worker.dt.timedelta(hours=2)).isoformat(timespec="seconds")
        with worker.connect_db() as db:
            db.execute(
                """INSERT INTO llm_usage_reservations
                (id,job_id,agent_id,profile,reserved_cost_usd,created_at)
                VALUES(?,?,?,?,?,?)""",
                ("stale-reservation","old-job","writer","balanced",0.5,stale_time)
            )
        with patch.dict("os.environ", {
            "LLM_BALANCED_INPUT_USD_PER_1M":"1",
            "LLM_BALANCED_OUTPUT_USD_PER_1M":"1",
            "QUDRON_MONTHLY_MODEL_BUDGET_USD":"1"
        }, clear=True):
            new_id = worker.reserve_model_budget("new-job","reviewer","balanced","model-x",1000)
        self.assertIsNotNone(new_id)
        with worker.connect_db() as db:
            rows = db.execute(
                "SELECT id FROM llm_usage_reservations ORDER BY created_at"
            ).fetchall()
        self.assertEqual([row["id"] for row in rows], [new_id])

    def test_usage_cost_is_calculated_from_configured_per_million_rates(self):
        with patch.dict("os.environ", {
            "LLM_BALANCED_INPUT_USD_PER_1M":"2",
            "LLM_BALANCED_OUTPUT_USD_PER_1M":"4"
        }, clear=True):
            worker.record_model_usage(
                "job-usage","cv_writer","balanced","balanced-model",
                {"usage":{"prompt_tokens":1000,"completion_tokens":500,"total_tokens":1500}},
                None
            )
            snapshot = worker.model_usage_snapshot()
            self.assertEqual(snapshot["daily"]["calls"], 1)
            self.assertAlmostEqual(snapshot["daily"]["cost_usd"], 0.004, places=8)


    def test_non_finite_prices_and_budgets_are_rejected(self):
        with patch.dict("os.environ", {
            "LLM_BALANCED_INPUT_USD_PER_1M":"nan",
            "LLM_BALANCED_OUTPUT_USD_PER_1M":"1"
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "finite number"):
                worker.profile_cost_rates("balanced")
        with patch.dict("os.environ", {
            "QUDRON_MONTHLY_MODEL_BUDGET_USD":"inf"
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "finite number"):
                worker.configured_budget("QUDRON_MONTHLY_MODEL_BUDGET_USD")

    def test_malformed_usage_metadata_is_stored_without_crashing(self):
        worker.record_model_usage(
            "job-bad-usage","reviewer","balanced","test-model",
            {"usage":"provider returned a malformed usage object"},
            None
        )
        snapshot = worker.model_usage_snapshot()
        self.assertEqual(snapshot["daily"]["calls"], 1)
        self.assertIsNone(snapshot["recent"][0]["prompt_tokens"])
        self.assertIsNone(snapshot["recent"][0]["cost_usd"])

    def test_profile_only_configuration_counts_as_model_ready(self):
        with patch.dict("os.environ", {
            "LLM_REASONING_BASE_URL":"https://reasoning.example/v1",
            "LLM_REASONING_MODEL":"deep-review"
        }, clear=True):
            with patch.object(worker, "LLM_BASE_URL", ""), patch.object(worker, "LLM_MODEL", ""):
                self.assertTrue(worker.any_model_profile_configured())

    def test_no_default_or_specialized_profile_is_not_ready(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(worker, "LLM_BASE_URL", ""), patch.object(worker, "LLM_MODEL", ""):
                self.assertFalse(worker.any_model_profile_configured())

    def test_unconfigured_model_fails_closed(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(worker, "LLM_BASE_URL", ""), patch.object(worker, "LLM_MODEL", ""):
                with self.assertRaisesRegex(RuntimeError, "not configured"):
                    worker.call_llm(
                        {"role":"Research","task_type":"research","title":"Test","prompt":"Do the work"},
                        {"id":"research_analyst","profile":"balanced"},
                        "Produce the report.", "", ""
                    )

if __name__ == "__main__":
    unittest.main()
