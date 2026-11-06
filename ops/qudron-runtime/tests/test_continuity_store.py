import tempfile
import unittest
from pathlib import Path

from continuity_store import ContinuityStore


class ContinuityStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "qudron.sqlite3"
        self.store = ContinuityStore(self.db_path)

    def tearDown(self):
        self.temp.cleanup()

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

    def test_agent_instance_rejects_invalid_lifecycle_transition(self):
        instance = self.store.create_agent_instance(
            job_id="job-invalid", project="qudron", role_id="qa_engineer",
            stage="review",
        )
        self.store.transition_agent_instance(instance["instance_id"], "running")
        self.store.transition_agent_instance(instance["instance_id"], "succeeded")
        with self.assertRaises(ValueError):
            self.store.transition_agent_instance(instance["instance_id"], "running")


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
