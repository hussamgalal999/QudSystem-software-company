import concurrent.futures
import json
import tempfile
import unittest
from unittest.mock import patch
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
                 worker.INSTANCE_ID if status == "running" else None, lock_until, now, now)
            )

    def test_mcp_job_status_redacts_persisted_provider_error(self):
        self.insert_job("mcp-error", status="failed")
        with worker.connect_db() as db:
            db.execute(
                "UPDATE jobs SET error=? WHERE id=?",
                ("HTTP 500: provider response contained secret material", "mcp-error")
            )
        snapshot = worker.mcp_get_job("mcp-error")
        self.assertEqual(snapshot["error"], "job_failed")
        self.assertNotIn("provider response", snapshot["error"])
        self.assertNotIn("secret material", snapshot["error"])

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



    def test_next_local_occurrence_respects_cairo_wall_clock_time(self):
        item = {
            "id":"local-daily", "timezone":"Africa/Cairo",
            "at_local":"09:00", "every_days":1
        }
        after = worker.dt.datetime.fromisoformat("2026-11-04T06:30:00+00:00")
        next_run = worker.next_local_occurrence(item, after)
        self.assertEqual(next_run.isoformat(), "2026-11-04T07:00:00+00:00")

    def test_weekday_schedule_skips_to_next_configured_local_weekday(self):
        item = {
            "id":"monday-review", "timezone":"Africa/Cairo",
            "at_local":"09:00", "weekdays":[0]
        }
        after = worker.dt.datetime.fromisoformat("2026-11-08T08:00:00+00:00")
        next_run = worker.next_local_occurrence(item, after)
        self.assertEqual(next_run.isoformat(), "2026-11-09T07:00:00+00:00")

    def test_every_three_days_uses_explicit_local_anchor_date(self):
        item = {
            "id":"three-day", "timezone":"Africa/Cairo",
            "at_local":"16:00", "every_days":3, "anchor_date":"2026-11-04"
        }
        after = worker.dt.datetime.fromisoformat("2026-11-06T15:00:00+00:00")
        next_run = worker.next_local_occurrence(item, after)
        self.assertEqual(next_run.isoformat(), "2026-11-07T14:00:00+00:00")

    def test_local_schedule_initializes_next_slot_and_enqueues_once_when_due(self):
        worker.SCHEDULE_PATH.write_text(json.dumps({
            "timezone":"Africa/Cairo",
            "schedules":[{
                "id":"local-daily","at_local":"09:00","every_days":1,
                "role":"Tester","task_type":"research","title":"Local daily",
                "prompt":"Run the local daily task"
            }]
        }), encoding="utf-8")
        with patch.object(worker, "utc_now", return_value=worker.dt.datetime.fromisoformat("2026-11-04T06:00:00+00:00")):
            worker.enqueue_due_schedules()
        with worker.connect_db() as db:
            state = db.execute("SELECT next_run_at FROM schedule_state WHERE schedule_id='local-daily'").fetchone()
            count_before = db.execute("SELECT COUNT(*) FROM jobs WHERE job_key LIKE 'schedule:local-daily:%'").fetchone()[0]
        self.assertEqual(state["next_run_at"], "2026-11-04T07:00:00+00:00")
        self.assertEqual(count_before, 0)

        due_now = worker.dt.datetime.fromisoformat("2026-11-04T07:15:00+00:00")
        with patch.object(worker, "utc_now", return_value=due_now):
            worker.enqueue_due_schedules()
            worker.enqueue_due_schedules()
        with worker.connect_db() as db:
            rows = db.execute(
                "SELECT job_key FROM jobs WHERE job_key LIKE 'schedule:local-daily:%'"
            ).fetchall()
            state = db.execute("SELECT next_run_at FROM schedule_state WHERE schedule_id='local-daily'").fetchone()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["job_key"], "schedule:local-daily:20261104T0900")
        self.assertEqual(state["next_run_at"], "2026-11-05T07:00:00+00:00")

    def test_local_schedule_catches_up_only_latest_missed_slot_after_downtime(self):
        worker.SCHEDULE_PATH.write_text(json.dumps({
            "timezone":"Africa/Cairo",
            "schedules":[{
                "id":"local-catchup","at_local":"09:00","every_days":1,
                "role":"Tester","task_type":"research","title":"Catch-up task",
                "prompt":"Recover latest missed daily task"
            }]
        }), encoding="utf-8")
        with worker.connect_db() as db:
            db.execute(
                "INSERT INTO schedule_state(schedule_id,next_run_at,last_enqueued_at) VALUES(?,?,NULL)",
                ("local-catchup","2026-11-01T07:00:00+00:00")
            )
        now = worker.dt.datetime.fromisoformat("2026-11-04T08:30:00+00:00")
        with patch.object(worker, "utc_now", return_value=now):
            worker.enqueue_due_schedules()
            worker.enqueue_due_schedules()
        with worker.connect_db() as db:
            rows = db.execute(
                "SELECT job_key FROM jobs WHERE job_key LIKE 'schedule:local-catchup:%'"
            ).fetchall()
            state = db.execute("SELECT next_run_at FROM schedule_state WHERE schedule_id='local-catchup'").fetchone()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["job_key"], "schedule:local-catchup:20261104T0900")
        self.assertEqual(state["next_run_at"], "2026-11-05T07:00:00+00:00")

    def test_invalid_local_time_and_timezone_are_rejected(self):
        worker.SCHEDULE_PATH.write_text(json.dumps({
            "timezone":"No/Such_Zone",
            "schedules":[{
                "id":"invalid","at_local":"25:99",
                "role":"Tester","task_type":"research","title":"Invalid",
                "prompt":"Should not load"
            }]
        }), encoding="utf-8")
        self.assertEqual(worker.load_schedules(), [])

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


    def test_stale_worker_cannot_finish_or_fail_a_reclaimed_job(self):
        self.insert_job("reclaimed", status="running", attempts=worker.MAX_ATTEMPTS,
                        lock_until=(worker.utc_now()+timedelta(minutes=5)).isoformat())
        with worker.connect_db() as db:
            db.execute("UPDATE jobs SET locked_by='new-owner' WHERE id='reclaimed'")
            stale_row = db.execute("SELECT * FROM jobs WHERE id='reclaimed'").fetchone()

        self.assertFalse(worker.finish_job("reclaimed", "/tmp/should-not-commit.md"))
        worker.fail_job(stale_row, RuntimeError("old worker failed late"))

        with worker.connect_db() as db:
            row = db.execute("SELECT status,locked_by FROM jobs WHERE id='reclaimed'").fetchone()
            incident_count = db.execute(
                "SELECT COUNT(*) FROM jobs WHERE job_key='incident-triage:reclaimed'"
            ).fetchone()[0]
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["locked_by"], "new-owner")
        self.assertEqual(incident_count, 0)

    def test_completion_commits_only_for_current_lease_owner(self):
        self.insert_job("owned", status="running", attempts=1,
                        lock_until=(worker.utc_now()+timedelta(minutes=5)).isoformat())
        self.assertTrue(worker.finish_job("owned", "/tmp/owned-result.md"))
        with worker.connect_db() as db:
            row = db.execute("SELECT status,result_path FROM jobs WHERE id='owned'").fetchone()
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["result_path"], "/tmp/owned-result.md")


    def test_runtime_status_reports_routine_and_cvpen_swarm_caps(self):
        with patch.object(worker, "SWARM_ENABLED", True), \
             patch.object(worker, "MAX_SWARM_AGENTS", 5), \
             patch.object(worker, "MAX_CVPEN_AGENTS", 10), \
             patch.object(worker, "MAX_PARALLEL_REVIEWS", 8):
            snapshot = worker.status_snapshot()
        self.assertEqual(snapshot["max_agents_per_task"], 5)
        self.assertEqual(snapshot["max_agents_per_cvpen_job"], 10)
        self.assertEqual(snapshot["max_parallel_reviews"], 8)


    def test_global_model_call_slots_enforce_shared_concurrency_cap(self):
        with patch.object(worker, "MAX_CONCURRENT_MODEL_CALLS", 2), \
             patch.object(worker, "MODEL_CALL_SLOT_TIMEOUT_SECONDS", 1):
            first = worker.acquire_model_call_slot("job-a","agent-a")
            second = worker.acquire_model_call_slot("job-b","agent-b")
            with self.assertRaises(TimeoutError):
                worker.acquire_model_call_slot("job-c","agent-c")
            worker.release_model_call_slot(first)
            third = worker.acquire_model_call_slot("job-c","agent-c")
            with worker.connect_db() as db:
                active = db.execute("SELECT COUNT(*) FROM model_call_slots").fetchone()[0]
            self.assertEqual(active, 2)
            worker.release_model_call_slot(second)
            worker.release_model_call_slot(third)
        with worker.connect_db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM model_call_slots").fetchone()[0], 0)

    def test_stale_global_model_call_slots_are_reclaimed(self):
        stale = (worker.utc_now()-timedelta(minutes=30)).isoformat(timespec="seconds")
        with worker.connect_db() as db:
            db.execute(
                "INSERT INTO model_call_slots(id,job_id,agent_id,lease_until,created_at) VALUES(?,?,?,?,?)",
                ("expired-slot","old-job","old-agent",stale,stale)
            )
        with patch.object(worker, "MAX_CONCURRENT_MODEL_CALLS", 1):
            slot = worker.acquire_model_call_slot("new-job","new-agent")
            with worker.connect_db() as db:
                rows = db.execute("SELECT id FROM model_call_slots").fetchall()
            self.assertEqual([row["id"] for row in rows], [slot])
            worker.release_model_call_slot(slot)


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
