import unittest

from agent_protocol import (
    AgentDescriptor, ArtifactRef, DataClass, ExecutionMode,
    ResourceClaim, ResourceMode, TaskEnvelope, TaskStatus,
    stable_idempotency_key,
)


class AgentProtocolTests(unittest.TestCase):
    def test_task_round_trip_preserves_mode_privacy_dependencies_and_resources(self):
        task = TaskEnvelope(
            task_id="task-001", project_id="qudron",
            idempotency_key="idem-001", title="Review architecture",
            instruction="Review the task graph.",
            execution_mode=ExecutionMode.HYBRID,
            dependencies=("task-parent",),
            required_skills=("architecture", "security"),
            data_class=DataClass.INTERNAL,
            resource_claims=(
                ResourceClaim("repo:qudsystem/main", ResourceMode.READ),
                ResourceClaim("artifact:review-001", ResourceMode.WRITE),
            ),
            input_artifacts=(ArtifactRef("a1", "reports/review.md", "text/markdown"),),
        )
        restored = TaskEnvelope.from_dict(task.to_dict())
        self.assertEqual(restored.execution_mode, ExecutionMode.HYBRID)
        self.assertEqual(restored.data_class, DataClass.INTERNAL)
        self.assertEqual(restored.dependencies, ("task-parent",))
        self.assertEqual(restored.resource_claims[1].mode, ResourceMode.WRITE)
        self.assertEqual(restored.input_artifacts[0].artifact_id, "a1")

    def test_approval_gate_is_not_satisfied_by_a_missing_approver(self):
        task = TaskEnvelope(
            task_id="task-002", project_id="qudron",
            idempotency_key="idem-002", title="Publish post",
            instruction="Publish only after approval.",
            requires_approval=True,
        )
        self.assertFalse(task.approved)
        # Arbitrary caller-supplied text is not an authenticated approval.
        approved = TaskEnvelope.from_dict({
            **task.to_dict(), "approved_by": "owner"
        })
        self.assertFalse(approved.approved)

    def test_agent_descriptor_rejects_invalid_quality_and_concurrency(self):
        with self.assertRaises(ValueError):
            AgentDescriptor("a", "Agent", "provider", "a2a", max_concurrency=0)
        with self.assertRaises(ValueError):
            AgentDescriptor("a", "Agent", "provider", "a2a", quality_score=1.2)

    def test_artifact_digest_is_validated(self):
        with self.assertRaises(ValueError):
            ArtifactRef("artifact", "file.txt", sha256="not-a-hash")

    def test_idempotency_key_is_stable(self):
        self.assertEqual(
            stable_idempotency_key("qudron", "job-1", "review"),
            stable_idempotency_key("qudron", "job-1", "review"),
        )
        self.assertNotEqual(
            stable_idempotency_key("qudron", "job-1", "review"),
            stable_idempotency_key("qudron", "job-2", "review"),
        )

    def test_idempotency_key_is_unambiguous_when_identifiers_contain_delimiters(self):
        first = stable_idempotency_key("a\\x1fb", "c", "d")
        second = stable_idempotency_key("a", "b\\x1fc", "d")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
