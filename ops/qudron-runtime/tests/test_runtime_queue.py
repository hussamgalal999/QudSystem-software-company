import concurrent.futures
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import qudron_worker as worker

class RuntimeQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        worker.DB_PATH = root / "state.sqlite3"
        worker.REPORTS_DIR = root / "reports"
        worker.LOG_PATH = root / "worker.log"
        worker.SCHEDULE_PATH = root / "schedule.json"
        worker.init_db()

    def tearDown(self):
        self.temp.cleanup()

    def insert_job(self, job_id, status="pending", attempts=0, lock_until=None):
        now = worker.iso_now()
        with worker.connect_db() as db:
            db.execute(
                """INSERT INTO jobs(id,job_key,title,role,task_type,prompt,status,attempts,
                   run_after,locked_by,lock_until,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, None, f"Job {job_id}", "Test Agent", "research", "test prompt",
                 status, attempts, (worker.utc_now()-timedelta(minutes=1)).isoformat(),
                 "test-instance" if status == "running" else None, lock_until, now, now)
            )

    def test_concurrent_claims_are_unique(self):
        for i in range(12):
            self.insert_job(f"job-{i}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            claims = list(pool.map(lambda _: worker.claim_job(), range(12)))
        claimed_ids = [row["id"] for row in claims if row is not None]
        self.assertEqual(len(claimed_ids), 12)
        self.assertEqual(len(set(claimed_ids)), 12)

    def test_expired_running_job_is_recovered(self):
        self.insert_job("stale", status="running", attempts=1,
                        lock_until=(worker.utc_now()-timedelta(minutes=5)).isoformat())
        worker.recover_stale_jobs()
        with worker.connect_db() as db:
            row = db.execute("SELECT status,locked_by,lock_until FROM jobs WHERE id='stale'").fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertIsNone(row["locked_by"])
        self.assertIsNone(row["lock_until"])

    def test_expired_job_at_attempt_limit_becomes_failed(self):
        self.insert_job("stale-final", status="running", attempts=worker.MAX_ATTEMPTS,
                        lock_until=(worker.utc_now()-timedelta(minutes=5)).isoformat())
        worker.recover_stale_jobs()
        with worker.connect_db() as db:
            row = db.execute("SELECT status FROM jobs WHERE id='stale-final'").fetchone()
        self.assertEqual(row["status"], "failed")

    def test_schedule_enqueue_is_idempotent_within_interval(self):
        worker.SCHEDULE_PATH.write_text(json.dumps({
            "schedules":[{"id":"one","every_minutes":1440,"role":"Tester",
                          "task_type":"research","title":"Daily test","prompt":"Test"}]
        }), encoding="utf-8")
        worker.enqueue_due_schedules()
        worker.enqueue_due_schedules()
        with worker.connect_db() as db:
            count = db.execute("SELECT COUNT(*) FROM jobs WHERE job_key LIKE 'schedule:one:%'").fetchone()[0]
        self.assertEqual(count, 1)


    def test_every_configured_schedule_uses_a_supported_task_type(self):
        schedule_path = Path(__file__).resolve().parents[1] / "schedule.json"
        schedules = json.loads(schedule_path.read_text(encoding="utf-8"))["schedules"]
        unsupported = sorted({
            item.get("task_type") for item in schedules
            if item.get("task_type") not in worker.ALLOWED_TASK_TYPES
        })
        self.assertEqual(unsupported, [])



    def test_active_job_lease_can_be_renewed_only_by_its_owner(self):
        worker.LOCK_SECONDS = 60
        self.insert_job("lease-owner", status="running", attempts=1,
                        lock_until=(worker.utc_now()-timedelta(seconds=10)).isoformat())
        with worker.connect_db() as db:
            db.execute("UPDATE jobs SET locked_by=? WHERE id='lease-owner'", (worker.INSTANCE_ID,))
            before = db.execute("SELECT lock_until FROM jobs WHERE id='lease-owner'").fetchone()["lock_until"]
        self.assertTrue(worker.renew_job_lease("lease-owner"))
        with worker.connect_db() as db:
            after = db.execute("SELECT lock_until FROM jobs WHERE id='lease-owner'").fetchone()["lock_until"]
        self.assertGreater(after, before)

    def test_active_job_lease_cannot_be_stolen_or_renewed_by_another_instance(self):
        self.insert_job("lease-foreign", status="running", attempts=1,
                        lock_until=(worker.utc_now()-timedelta(seconds=10)).isoformat())
        with worker.connect_db() as db:
            db.execute("UPDATE jobs SET locked_by='another-instance' WHERE id='lease-foreign'")
        self.assertFalse(worker.renew_job_lease("lease-foreign"))

    def test_sqlite_context_manager_closes_connection(self):
        with worker.connect_db() as db:
            db.execute("SELECT 1").fetchone()
            connection = db
        with self.assertRaises(Exception):
            connection.execute("SELECT 1")

    def test_terminal_failure_queues_single_same_day_incident_triage(self):
        self.insert_job("terminal-failure", status="running", attempts=worker.MAX_ATTEMPTS,
                        lock_until=(worker.utc_now()+timedelta(minutes=5)).isoformat())
        with worker.connect_db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id='terminal-failure'").fetchone()
        worker.fail_job(row, RuntimeError("Provider temporarily unavailable"))
        worker.fail_job(row, RuntimeError("Provider temporarily unavailable"))
        with worker.connect_db() as db:
            main = db.execute("SELECT status FROM jobs WHERE id='terminal-failure'").fetchone()
            triage = db.execute(
                "SELECT id,task_type,status,job_key FROM jobs WHERE job_key='incident-triage:terminal-failure'"
            ).fetchall()
        self.assertEqual(main["status"], "failed")
        self.assertEqual(len(triage), 1)
        self.assertEqual(triage[0]["task_type"], "incident_triage")
        self.assertEqual(triage[0]["status"], "pending")

    def test_incident_triage_failure_does_not_spawn_recursive_triage(self):
        self.insert_job("failed-triage", status="running", attempts=worker.MAX_ATTEMPTS,
                        lock_until=(worker.utc_now()+timedelta(minutes=5)).isoformat())
        with worker.connect_db() as db:
            db.execute("UPDATE jobs SET task_type='incident_triage' WHERE id='failed-triage'")
            row = db.execute("SELECT * FROM jobs WHERE id='failed-triage'").fetchone()
        worker.fail_job(row, RuntimeError("reasoning endpoint offline"))
        with worker.connect_db() as db:
            triage_count = db.execute(
                "SELECT COUNT(*) FROM jobs WHERE job_key LIKE 'incident-triage:%'"
            ).fetchone()[0]
        self.assertEqual(triage_count, 0)

    def test_malformed_and_unsupported_schedules_are_skipped_safely(self):
        worker.SCHEDULE_PATH.write_text(json.dumps({
            "schedules":[
                {"id":"good","every_minutes":60,"role":"Tester","task_type":"research",
                 "title":"Valid","prompt":"Run a valid task"},
                {"id":"bad-type","every_minutes":60,"role":"Tester","task_type":"unknown",
                 "title":"Unsupported","prompt":"Should be skipped"},
                {"id":"missing-prompt","every_minutes":60,"role":"Tester","task_type":"research",
                 "title":"Missing prompt"},
                {"id":"good","every_minutes":60,"role":"Tester","task_type":"research",
                 "title":"Duplicate id","prompt":"Should be skipped"},
                None
            ]
        }), encoding="utf-8")
        loaded = worker.load_schedules()
        self.assertEqual([item["id"] for item in loaded], ["good"])

    def test_memory_is_project_scoped_and_redacted(self):
        worker.remember_event("cvpen","short","job_event",
            "Customer a@example.com called 01012345678. CVPen task complete.")
        cvpen_context = worker.retrieve_memory_context("cvpen")
        qudschool_context = worker.retrieve_memory_context("qudschool")
        self.assertIn("REDACTED_EMAIL", cvpen_context)
        self.assertIn("REDACTED_PHONE", cvpen_context)
        self.assertNotIn("a@example.com", cvpen_context)
        self.assertNotIn("CVPen task complete", qudschool_context)

    def test_expired_memory_is_not_retrieved(self):
        worker.remember_event("qudsystem","short","temporary","temporary note",ttl_days=-1)
        self.assertNotIn("temporary note", worker.retrieve_memory_context("qudsystem"))

if __name__ == "__main__":
    unittest.main()
