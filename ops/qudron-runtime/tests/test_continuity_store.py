import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from datetime import datetime, timedelta, timezone

from continuity_store import ContinuityStore


class ContinuityStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "qudron.sqlite3"
        self.store = ContinuityStore(self.db_path)

    def tearDown(self):
        self.temp.cleanup()


    def test_connection_context_rolls_back_all_statements_after_failure(self):
        with self.store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS transaction_probe (value TEXT NOT NULL)"
            )
        with self.assertRaisesRegex(RuntimeError, "forced transaction failure"):
            with self.store.connect() as db:
                db.execute("INSERT INTO transaction_probe(value) VALUES(?)", ("first",))
                db.execute("INSERT INTO transaction_probe(value) VALUES(?)", ("second",))
                raise RuntimeError("forced transaction failure")
        with self.store.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM transaction_probe").fetchone()[0]
        self.assertEqual(count, 0)


    def test_legacy_running_stage_without_claim_token_is_immediately_reclaimable(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute("""
                CREATE TABLE agent_runs (
                    job_id TEXT NOT NULL, project TEXT NOT NULL,
                    agent_id TEXT NOT NULL, stage TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    output TEXT, error TEXT, started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, agent_id, stage)
                )
            """)
            db.execute(
                """INSERT INTO agent_runs
                   (job_id,project,agent_id,stage,status,started_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                ("legacy-job", "qudron", "worker", "research", "running", "2026-11-01", "2026-11-01"),
            )
        recovered_store = ContinuityStore(legacy_path)
        with recovered_store.connect() as db:
            row = db.execute(
                "SELECT claim_token,lease_until FROM agent_runs WHERE job_id='legacy-job'"
            ).fetchone()
        self.assertIsNone(row["claim_token"])
        self.assertEqual(row["lease_until"], 0)
        recovered = recovered_store.begin_stage(
            job_id="legacy-job", project="qudron", agent_id="worker", stage="research"
        )
        self.assertTrue(recovered["claimed"])

    def test_concurrent_stage_claim_is_exclusive_and_stale_claim_cannot_complete(self):
        first = self.store.begin_stage(
            job_id="job-claim", project="qudron", agent_id="worker", stage="analyze"
        )
        second_store = ContinuityStore(self.db_path)
        second = second_store.begin_stage(
            job_id="job-claim", project="qudron", agent_id="worker", stage="analyze"
        )
        self.assertTrue(first["claimed"])
        self.assertFalse(second["claimed"])
        with self.store.connect() as db:
            db.execute(
                "UPDATE agent_runs SET lease_until=0 WHERE job_id=? AND agent_id=? AND stage=?",
                ("job-claim", "worker", "analyze"),
            )
        recovered = second_store.begin_stage(
            job_id="job-claim", project="qudron", agent_id="worker", stage="analyze"
        )
        self.assertTrue(recovered["claimed"])
        self.assertNotEqual(first["claim_token"], recovered["claim_token"])
        with self.assertRaisesRegex(RuntimeError, "claim is stale"):
            self.store.complete_stage(
                job_id="job-claim", project="qudron", agent_id="worker",
                stage="analyze", claim_token=first["claim_token"], output="stale",
            )
        second_store.complete_stage(
            job_id="job-claim", project="qudron", agent_id="worker",
            stage="analyze", claim_token=recovered["claim_token"], output="current",
        )

    def test_lost_parent_job_lease_blocks_stale_stage_completion(self):
        future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(timespec="seconds")
        with self.store.connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, status TEXT, locked_by TEXT, lock_until TEXT
                )"""
            )
            db.execute(
                "INSERT OR REPLACE INTO jobs(id,status,locked_by,lock_until) VALUES(?,?,?,?)",
                ("job-lease-owner", "running", "worker-one", future),
            )
        claim = self.store.begin_stage(
            job_id="job-lease-owner", project="qudron", agent_id="worker",
            stage="research", job_lease_owner="worker-one",
        )
        with self.store.connect() as db:
            db.execute(
                "UPDATE jobs SET locked_by=? WHERE id=?",
                ("worker-two", "job-lease-owner"),
            )
        with self.assertRaisesRegex(RuntimeError, "Job lease lost"):
            self.store.complete_stage(
                job_id="job-lease-owner", project="qudron", agent_id="worker",
                stage="research", claim_token=claim["claim_token"],
                output="stale worker output", job_lease_owner="worker-one",
            )
        with self.store.connect() as db:
            row = db.execute(
                "SELECT status,output FROM agent_runs WHERE job_id=? AND agent_id=? AND stage=?",
                ("job-lease-owner", "worker", "research"),
            ).fetchone()
        self.assertEqual(row["status"], "running")
        self.assertIsNone(row["output"])
        self.assertTrue(self.store.abandon_stage_claim(
            job_id="job-lease-owner", project="qudron", agent_id="worker",
            stage="research", claim_token=claim["claim_token"],
        ))
        next_claim = self.store.begin_stage(
            job_id="job-lease-owner", project="qudron", agent_id="worker",
            stage="research", job_lease_owner="worker-two",
        )
        self.assertTrue(next_claim["claimed"])

    def test_stage_completion_rolls_back_run_event_and_memory_as_one_transaction(self):
        claim = self.store.begin_stage(
            job_id="job-atomic", project="qudron", agent_id="worker", stage="produce"
        )
        with patch.object(self.store, "_queue_event", side_effect=RuntimeError("event store unavailable")):
            with self.assertRaisesRegex(RuntimeError, "event store unavailable"):
                self.store.complete_stage(
                    job_id="job-atomic", project="qudron", agent_id="worker",
                    stage="produce", claim_token=claim["claim_token"],
                    output="private output", memory_note="memory must not be committed",
                )
        with self.store.connect() as db:
            row = db.execute(
                "SELECT status,output FROM agent_runs WHERE job_id=? AND agent_id=? AND stage=?",
                ("job-atomic", "worker", "produce"),
            ).fetchone()
            memories = db.execute(
                "SELECT COUNT(*) FROM agent_memories WHERE project=? AND agent_id=?",
                ("qudron", "worker"),
            ).fetchone()[0]
        self.assertEqual(row["status"], "running")
        self.assertIsNone(row["output"])
        self.assertEqual(memories, 0)
        self.store.complete_stage(
            job_id="job-atomic", project="qudron", agent_id="worker",
            stage="produce", claim_token=claim["claim_token"], output="committed output",
        )

    def test_snapshot_exposes_all_recent_stage_checkpoints_without_raw_output(self):
        first = self.store.begin_stage(
            job_id="job-snapshot", project="qudron", agent_id="worker", stage="research"
        )
        self.store.complete_stage(
            job_id="job-snapshot", project="qudron", agent_id="worker",
            stage="research", claim_token=first["claim_token"], output="private output one",
        )
        second = self.store.begin_stage(
            job_id="job-snapshot", project="qudron", agent_id="worker", stage="review"
        )
        self.store.complete_stage(
            job_id="job-snapshot", project="qudron", agent_id="worker",
            stage="review", claim_token=second["claim_token"], output="private output two",
        )
        snapshot = self.store.snapshot()
        stages = [row for row in snapshot["recent_agent_stages"] if row["job_id"] == "job-snapshot"]
        self.assertEqual({row["stage"] for row in stages}, {"research", "review"})
        self.assertTrue(all(row["has_output"] for row in stages))
        self.assertNotIn("output", stages[0])
        self.assertNotIn("claim_token", stages[0])

    def test_stage_events_are_queued_for_cloud_sync(self):
        self.store.begin_stage(
            job_id="job-outbox", project="qudron", agent_id="qa_engineer", stage="verify"
        )
        rows = self.store.pending_cloud_outbox()
        self.assertTrue(rows)
        self.assertTrue(any(row["endpoint"] == "/v1/events" for row in rows))
        self.assertTrue(all(row["status"] == "pending" for row in rows))

    def test_agent_memories_are_durable_and_isolated_by_agent_and_project(self):
        self.store.remember(
            project="qudron", agent_id="security_analyst",
            content="Review only owner-authorized Android test builds.",
        )
        self.store.remember(
            project="vision_guard", agent_id="brand_strategist",
            content="Keep security messaging calm and evidence-led.",
        )
        restarted = ContinuityStore(self.db_path)
        memory = restarted.agent_memory_context(project="qudron", agent_id="security_analyst")
        self.assertIn("owner-authorized Android", memory)
        self.assertNotIn("evidence-led", memory)

    def test_expired_agent_memory_is_excluded_and_purged(self):
        self.store.remember(
            project="qudron", agent_id="research_analyst",
            content="This note should expire.", ttl_days=1,
        )
        with self.store.connect() as db:
            row = db.execute(
                "SELECT id, expires_at FROM agent_memories WHERE project=? AND agent_id=?",
                ("qudron", "research_analyst"),
            ).fetchone()
            self.assertIsNotNone(row["expires_at"])
            db.execute(
                "UPDATE agent_memories SET expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00+00:00", row["id"]),
            )
        memory = self.store.agent_memory_context(
            project="qudron", agent_id="research_analyst"
        )
        self.assertNotIn("This note should expire", memory)
        with self.store.connect() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM agent_memories WHERE id=?", (row["id"],)
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_zero_ttl_creates_non_expiring_agent_memory(self):
        self.store.remember(
            project="qudron", agent_id="research_analyst",
            content="Retain this long-lived note.", scope="long", ttl_days=0,
        )
        with self.store.connect() as db:
            row = db.execute(
                "SELECT expires_at FROM agent_memories WHERE project=? AND agent_id=?",
                ("qudron", "research_analyst"),
            ).fetchone()
        self.assertIsNone(row["expires_at"])
        memory = self.store.agent_memory_context(
            project="qudron", agent_id="research_analyst"
        )
        self.assertIn("Retain this long-lived note", memory)

    def test_completed_agent_stage_is_reused_after_restart(self):
        claim = self.store.begin_stage(
            job_id="job-001", project="qudron", agent_id="software_engineer", stage="produce"
        )
        self.assertTrue(claim["claimed"])
        self.store.complete_stage(
            job_id="job-001", project="qudron", agent_id="software_engineer",
            stage="produce", claim_token=claim["claim_token"], output="completed implementation draft",
            memory_note="Completed implementation draft for task job-001.",
        )
        restarted = ContinuityStore(self.db_path)
        checkpoint = restarted.begin_stage(
            job_id="job-001", project="qudron", agent_id="software_engineer", stage="produce"
        )
        self.assertTrue(checkpoint["completed"])
        self.assertEqual(checkpoint["output"], "completed implementation draft")
        self.assertEqual(checkpoint["attempts"], 1)

    def test_failed_stage_is_retried_and_attempt_count_increases(self):
        first = self.store.begin_stage(
            job_id="job-002", project="qudron", agent_id="qa_engineer", stage="review"
        )
        self.store.fail_stage(
            job_id="job-002", project="qudron", agent_id="qa_engineer",
            stage="review", claim_token=first["claim_token"], error="mock failure",
        )
        retry = self.store.begin_stage(
            job_id="job-002", project="qudron", agent_id="qa_engineer", stage="review"
        )
        self.assertTrue(retry["claimed"])
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot["agent_stage_counts"]["running"], 1)

    def test_sensitive_stage_can_be_completed_without_persisting_the_output(self):
        claim = self.store.begin_stage(
            job_id="job-003", project="cvpen", agent_id="cv_writer", stage="produce"
        )
        self.store.complete_stage(
            job_id="job-003", project="cvpen", agent_id="cv_writer",
            stage="produce", claim_token=claim["claim_token"], output=None,
            memory_note="Completed CV draft stage; source content not retained in agent memory.",
        )
        retry = self.store.begin_stage(
            job_id="job-003", project="cvpen", agent_id="cv_writer", stage="produce"
        )
        self.assertTrue(retry["claimed"])
        self.assertIn("source content not retained", self.store.agent_memory_context(
            project="cvpen", agent_id="cv_writer"
        ))


    def test_agent_instance_id_is_distinct_from_role_and_creation_is_idempotent(self):
        first = self.store.create_agent_instance(
            job_id="job-instance", project="qudron", role_id="software_engineer",
            stage="produce", model_profile="balanced",
            provider_id="freellm", model_name="auto",
        )
        again = self.store.create_agent_instance(
            job_id="job-instance", project="qudron", role_id="software_engineer",
            stage="produce", model_profile="balanced",
        )
        different_task = self.store.create_agent_instance(
            job_id="job-instance-2", project="qudron", role_id="software_engineer",
            stage="produce",
        )
        self.assertNotEqual(first["instance_id"], first["role_id"])
        self.assertEqual(first["instance_id"], again["instance_id"])
        self.assertNotEqual(first["instance_id"], different_task["instance_id"])
        self.assertEqual(first["status"], "queued")
        self.assertEqual(first["provider_id"], "freellm")

    def test_agent_instance_lifecycle_persists_and_counts_retries(self):
        instance = self.store.create_agent_instance(
            job_id="job-lifecycle", project="qudron", role_id="qa_engineer",
            stage="review",
        )
        running = self.store.transition_agent_instance(
            instance["instance_id"], "running", model_profile="reasoning",
            provider_id="gemini.google.com", model_name="free-tier-model",
        )
        self.assertEqual(running["attempts"], 1)
        failed = self.store.transition_agent_instance(
            instance["instance_id"], "failed", error="mock provider timeout",
        )
        self.assertEqual(failed["status"], "failed")
        retried = self.store.transition_agent_instance(
            instance["instance_id"], "running",
        )
        self.assertEqual(retried["attempts"], 2)
        completed = self.store.transition_agent_instance(
            instance["instance_id"], "succeeded",
        )
        self.assertEqual(completed["status"], "succeeded")

        restarted = ContinuityStore(self.db_path)
        recovered = restarted.get_agent_instance(instance["instance_id"])
        self.assertEqual(recovered["status"], "succeeded")
        self.assertEqual(recovered["attempts"], 2)
        self.assertEqual(recovered["provider_id"], "gemini.google.com")
        snapshot = restarted.snapshot()
        self.assertEqual(snapshot["agent_instance_counts"]["succeeded"], 1)
        self.assertEqual(snapshot["active_agent_instances"], 0)

    def test_sensitive_succeeded_stage_retries_only_with_explicit_fenced_transition(self):
        instance = self.store.create_agent_instance(
            job_id="job-sensitive-retry", project="cvpen", role_id="cv_writer",
            stage="produce",
        )
        first = self.store.begin_stage(
            job_id="job-sensitive-retry", project="cvpen",
            agent_id="cv_writer", stage="produce",
        )
        self.assertTrue(first["claimed"])
        self.store.transition_agent_instance(instance["instance_id"], "running")
        self.store.complete_stage(
            job_id="job-sensitive-retry", project="cvpen", agent_id="cv_writer",
            stage="produce", claim_token=first["claim_token"], output=None,
        )
        self.store.transition_agent_instance(instance["instance_id"], "succeeded")

        retry = self.store.begin_stage(
            job_id="job-sensitive-retry", project="cvpen",
            agent_id="cv_writer", stage="produce",
        )
        self.assertTrue(retry["claimed"])
        with self.assertRaisesRegex(ValueError, "succeeded -> running"):
            self.store.transition_agent_instance(instance["instance_id"], "running")
        retried = self.store.transition_agent_instance(
            instance["instance_id"], "running",
            allow_retry_from_succeeded=True,
        )
        self.assertEqual(retried["status"], "running")
        self.assertEqual(retried["attempts"], 2)

        with self.assertRaisesRegex(RuntimeError, "stale or no longer owned"):
            self.store.complete_stage(
                job_id="job-sensitive-retry", project="cvpen", agent_id="cv_writer",
                stage="produce", claim_token=first["claim_token"], output=None,
            )
        self.store.complete_stage(
            job_id="job-sensitive-retry", project="cvpen", agent_id="cv_writer",
            stage="produce", claim_token=retry["claim_token"], output=None,
        )

    def test_project_role_snapshot_remains_active_until_all_instances_finish(self):
        first = self.store.create_agent_instance(
            job_id="job-parallel-1", project="qudron", role_id="qa_engineer",
            stage="review",
        )
        second = self.store.create_agent_instance(
            job_id="job-parallel-2", project="qudron", role_id="qa_engineer",
            stage="review",
        )
        self.store.transition_agent_instance(first["instance_id"], "running")
        self.store.transition_agent_instance(second["instance_id"], "running")
        self.store.transition_agent_instance(first["instance_id"], "succeeded")

        def latest_role_snapshot():
            # Multiple state writes can share the same timestamp precision;
            # rowid gives the true insertion order for this transactional test.
            with self.store.connect() as db:
                rows = db.execute(
                    "SELECT payload_json FROM cloud_outbox WHERE endpoint='/v1/agents' ORDER BY rowid DESC"
                ).fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"])
                if payload.get("agent_id") == "qudron/qa_engineer":
                    return payload
            self.fail("No cloud agent snapshot was queued")

        active = latest_role_snapshot()
        self.assertEqual(active["status"], "running")
        self.assertIsNone(active["current_task_id"])
        self.assertIn("1 active task-scoped instance", active["next_action"])

        self.store.transition_agent_instance(second["instance_id"], "succeeded")
        idle = latest_role_snapshot()
        self.assertEqual(idle["status"], "idle")
        self.assertIsNone(idle["current_task_id"])

    def test_agent_instance_rejects_invalid_lifecycle_transition(self):
        instance = self.store.create_agent_instance(
            job_id="job-invalid", project="qudron", role_id="qa_engineer",
            stage="review",
        )
        self.store.transition_agent_instance(instance["instance_id"], "running")
        self.store.transition_agent_instance(instance["instance_id"], "succeeded")
        with self.assertRaises(ValueError):
            self.store.transition_agent_instance(instance["instance_id"], "running")


    def test_external_agent_task_can_be_recovered_from_local_ledger(self):
        self.store.save_external_task(
            provider="manus", external_task_id="task-123",
            local_job_id="job-004", agent_id="manus_operator",
            status="running", task_url="https://manus.im/app/task-123",
        )
        self.store.update_external_task(
            provider="manus", external_task_id="task-123",
            status="running", last_event_id="evt-123",
        )
        restarted = ContinuityStore(self.db_path)
        task = restarted.external_task(provider="manus", external_task_id="task-123")
        self.assertEqual(task["local_job_id"], "job-004")
        self.assertEqual(task["status"], "running")
        restarted.update_external_task(
            provider="manus", external_task_id="task-123",
            status="stopped", result={"summary": "verified"},
        )
        recovered = restarted.external_task(provider="manus", external_task_id="task-123")
        self.assertEqual(recovered["status"], "stopped")
        self.assertEqual(recovered["last_event_id"], "evt-123")


if __name__ == "__main__":
    unittest.main()
