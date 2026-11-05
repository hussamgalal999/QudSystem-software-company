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

    def test_external_agent_task_can_be_recovered_from_local_ledger(self):
        self.store.save_external_task(
            provider="manus", external_task_id="task-123",
            local_job_id="job-004", agent_id="manus_operator",
            status="running", task_url="https://manus.im/app/task-123",
        )
        restarted = ContinuityStore(self.db_path)
        task = restarted.external_task(provider="manus", external_task_id="task-123")
        self.assertEqual(task["local_job_id"], "job-004")
        self.assertEqual(task["status"], "running")
        restarted.update_external_task(
            provider="manus", external_task_id="task-123",
            status="stopped", result={"summary": "verified"},
        )
        self.assertEqual(
            restarted.external_task(provider="manus", external_task_id="task-123")["status"],
            "stopped",
        )


if __name__ == "__main__":
    unittest.main()
