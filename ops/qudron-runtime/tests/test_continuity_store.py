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

    def test_completed_agent_stage_is_reused_after_restart(self):
        self.assertIsNone(self.store.begin_stage(
            job_id="job-001", project="qudron", agent_id="software_engineer", stage="produce"
        ))
        self.store.complete_stage(
            job_id="job-001", project="qudron", agent_id="software_engineer",
            stage="produce", output="completed implementation draft",
            memory_note="Completed implementation draft for task job-001.",
        )
        restarted = ContinuityStore(self.db_path)
        checkpoint = restarted.begin_stage(
            job_id="job-001", project="qudron", agent_id="software_engineer", stage="produce"
        )
        self.assertEqual(checkpoint["output"], "completed implementation draft")
        self.assertEqual(checkpoint["attempts"], 1)

    def test_failed_stage_is_retried_and_attempt_count_increases(self):
        self.store.begin_stage(
            job_id="job-002", project="qudron", agent_id="qa_engineer", stage="review"
        )
        self.store.fail_stage(
            job_id="job-002", project="qudron", agent_id="qa_engineer",
            stage="review", error="mock failure",
        )
        self.assertIsNone(self.store.begin_stage(
            job_id="job-002", project="qudron", agent_id="qa_engineer", stage="review"
        ))
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot["agent_stage_counts"]["running"], 1)

    def test_sensitive_stage_can_be_completed_without_persisting_the_output(self):
        self.store.begin_stage(
            job_id="job-003", project="cvpen", agent_id="cv_writer", stage="produce"
        )
        self.store.complete_stage(
            job_id="job-003", project="cvpen", agent_id="cv_writer",
            stage="produce", output=None,
            memory_note="Completed CV draft stage; source content not retained in agent memory.",
        )
        self.assertIsNone(self.store.begin_stage(
            job_id="job-003", project="cvpen", agent_id="cv_writer", stage="produce"
        ))
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
