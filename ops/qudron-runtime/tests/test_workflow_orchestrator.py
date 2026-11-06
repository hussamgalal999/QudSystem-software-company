import asyncio
import tempfile
import unittest
from pathlib import Path

from workflow_orchestrator import (
    NodeExecutionResult, ResourceBusy, WorkflowDefinition, WorkflowNode,
    WorkflowOrchestrator, WorkflowStore, expand_execution_mode, validate_dag,
)
from agent_protocol import ExecutionMode, ResourceClaim, ResourceMode
from approval_service import ApprovalService


class WorkflowOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.approvals = ApprovalService("a" * 40, Path(self.temp.name) / "approvals.sqlite3")
        self.store = WorkflowStore(
            Path(self.temp.name) / "state.sqlite3",
            approval_service=self.approvals,
        )
        self.orchestrator = WorkflowOrchestrator(
            self.store, max_global_parallel=8, retry_base_seconds=0
        )

    def tearDown(self):
        self.temp.cleanup()

    async def test_parallel_nodes_run_concurrently_and_reduce_after_barrier(self):
        nodes = expand_execution_mode(
            ExecutionMode.SWARM,
            [("a", "A", "Do A"), ("b", "B", "Do B"), ("c", "C", "Do C")],
        )
        definition = WorkflowDefinition(
            "wf-1", "qudron", "idem-wf-1", ExecutionMode.SWARM, nodes, max_parallel=3
        )
        active = 0
        peak = 0
        reducer_saw = {"count": 0}
        lock = asyncio.Lock()

        async def executor(row):
            nonlocal active, peak
            if row["node_id"] == "qudron_reduce":
                self.assertEqual(reducer_saw["count"], 3)
                return NodeExecutionResult("succeeded", "reduced")
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.03)
            async with lock:
                active -= 1
                reducer_saw["count"] += 1
            return NodeExecutionResult("succeeded", row["node_id"])

        result = await self.orchestrator.run(definition, executor)
        self.assertEqual(result["status"], "succeeded")
        self.assertGreaterEqual(peak, 2)
        self.assertEqual(result["counts"]["succeeded"], 4)

    async def test_sequential_mode_creates_dependency_chain(self):
        nodes = expand_execution_mode(
            ExecutionMode.SEQUENTIAL,
            [("a", "A", "First"), ("b", "B", "Second"), ("c", "C", "Third")],
        )
        self.assertEqual(nodes[0].dependencies, ())
        self.assertEqual(nodes[1].dependencies, ("a",))
        self.assertEqual(nodes[2].dependencies, ("b",))

    async def test_dag_cycle_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_dag((
                WorkflowNode("a", "A", "Do A", ("b",)),
                WorkflowNode("b", "B", "Do B", ("a",)),
            ))

    async def test_idempotency_returns_existing_workflow(self):
        node = WorkflowNode("a", "A", "Do A")
        one = WorkflowDefinition("wf-unique", "qudron", "same-key", ExecutionMode.SEQUENTIAL, (node,))
        two = WorkflowDefinition("wf-different", "qudron", "same-key", ExecutionMode.SEQUENTIAL, (node,))
        self.assertEqual(self.store.create(one), "wf-unique")
        self.assertEqual(self.store.create(two), "wf-unique")

    async def test_resource_write_lock_blocks_other_writer_but_allows_readers(self):
        one = (ResourceClaim("repo:main", ResourceMode.WRITE),)
        reader = (ResourceClaim("repo:main", ResourceMode.READ),)
        self.assertTrue(self.store.acquire_resources("writer-1", one, 60))
        self.assertFalse(self.store.acquire_resources("writer-2", reader, 60))
        self.assertFalse(self.store.acquire_resources("writer-3", one, 60))
        self.store.release_resources("writer-1")
        self.assertTrue(self.store.acquire_resources("reader-1", reader, 60))
        self.assertTrue(self.store.acquire_resources("reader-2", reader, 60))

    async def test_expired_resource_lease_is_reclaimed(self):
        claims = (ResourceClaim("file:report.md", ResourceMode.WRITE),)
        self.assertTrue(self.store.acquire_resources("old", claims, 30))
        with self.store.connect() as db:
            db.execute(
                "UPDATE workflow_resource_locks SET lease_until=0 WHERE owner_key='old'"
            )
        self.assertTrue(self.store.acquire_resources("new", claims, 30))

    async def test_approval_gated_node_is_not_executed(self):
        node = WorkflowNode(
            "publish", "Publish", "Publish to a public page.",
            requires_approval=True,
            resource_claims=(ResourceClaim("channel:facebook", ResourceMode.WRITE),),
        )
        definition = WorkflowDefinition(
            "wf-approval", "qudron", "idem-approval",
            ExecutionMode.SEQUENTIAL, (node,),
        )
        invoked = []
        async def executor(row):
            invoked.append(row["node_id"])
            return NodeExecutionResult("succeeded", "done")
        result = await self.orchestrator.run(definition, executor)
        self.assertEqual(result["status"], "waiting_for_approval")
        self.assertEqual(invoked, [])

        token = self.approvals.issue(
            action="workflow.node.approve",
            resource_id="wf-approval/publish",
            approved_by="owner",
        )
        self.store.approve_node("wf-approval", "publish", token)
        result = await self.orchestrator.run(definition, executor)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(invoked, ["publish"])

    async def test_non_idempotent_node_does_not_retry(self):
        node = WorkflowNode(
            "send", "Send", "Send one email.", retry_safe=False, max_attempts=5
        )
        definition = WorkflowDefinition(
            "wf-send", "qudron", "idem-send", ExecutionMode.SEQUENTIAL, (node,)
        )
        calls = []
        async def executor(row):
            calls.append(row["node_id"])
            raise RuntimeError("ambiguous delivery")
        result = await self.orchestrator.run(definition, executor)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(calls, ["send"])


if __name__ == "__main__":
    unittest.main()
