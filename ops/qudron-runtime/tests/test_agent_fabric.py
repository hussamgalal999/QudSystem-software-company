import asyncio
import time
import unittest
import tempfile
from pathlib import Path

from agent_fabric import (
    AgentFabric, FabricPolicy, NoEligibleAgent, ProviderUnavailable,
)
from agent_protocol import (
    AgentDescriptor, AgentTaskHandle, AgentTaskResult, DataClass,
    TaskEnvelope, TaskStatus,
)
from approval_service import ApprovalService


class FakeAdapter:
    def __init__(self, fail=False):
        self.fail = fail
        self.submitted = []

    async def submit(self, agent, task):
        self.submitted.append((agent.agent_id, task.task_id))
        if self.fail:
            raise ConnectionError("mock offline")
        return AgentTaskHandle(agent.provider_id, "remote-1", TaskStatus.RUNNING)

    async def poll(self, agent, handle):
        return AgentTaskResult(agent.provider_id, handle.remote_task_id, TaskStatus.SUCCEEDED)

    async def follow_up(self, agent, handle, message):
        return AgentTaskHandle(agent.provider_id, handle.remote_task_id, TaskStatus.RUNNING)

    async def cancel(self, agent, handle):
        return AgentTaskHandle(agent.provider_id, handle.remote_task_id, TaskStatus.CANCELLED)


def task(**kwargs):
    base = dict(
        task_id="job-1", project_id="qudron", idempotency_key="idem-job-1",
        title="Research task", instruction="Research public information.",
        required_skills=("research",), data_class=DataClass.PUBLIC,
    )
    base.update(kwargs)
    return TaskEnvelope(**base)


def agent(agent_id, provider, adapter, **kwargs):
    base = dict(
        agent_id=agent_id, display_name=agent_id, provider_id=provider,
        adapter=adapter, skills=("research",), enabled=True, health="healthy",
        quality_score=0.9, access_mode="official_free_tier",
        price_class="free", last_verified_at=time.time(),
    )
    base.update(kwargs)
    return AgentDescriptor(**base)


class AgentFabricTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_to_eligible_agent_and_polls_result(self):
        fabric = AgentFabric()
        adapter = FakeAdapter()
        fabric.register_adapter("fake", adapter)
        fabric.register_agent(agent("gemini-research", "gemini-free", "fake"))
        receipt = await fabric.dispatch(task())
        result = await fabric.poll("gemini-research", receipt.handle)
        self.assertEqual(receipt.provider_id, "gemini-free")
        self.assertEqual(result.status, TaskStatus.SUCCEEDED)

    async def test_free_policy_rejects_paid_route(self):
        fabric = AgentFabric()
        fabric.register_adapter("fake", FakeAdapter())
        fabric.register_agent(agent("paid", "paid", "fake", price_class="paid"))
        with self.assertRaises(NoEligibleAgent):
            await fabric.dispatch(task())

    async def test_privacy_policy_rejects_confidential_data_on_free_hosted_models(self):
        fabric = AgentFabric()
        fabric.register_adapter("fake", FakeAdapter())
        fabric.register_agent(agent("gemini", "gemini", "fake",
                                    accepted_data_classes=("public", "internal", "confidential")))
        with self.assertRaises(NoEligibleAgent):
            await fabric.dispatch(task(data_class=DataClass.CONFIDENTIAL))

    async def test_failover_uses_next_eligible_provider(self):
        fabric = AgentFabric()
        fabric.register_adapter("broken", FakeAdapter(fail=True))
        fabric.register_adapter("healthy", FakeAdapter())
        fabric.register_agent(agent("a-broken", "provider-a", "broken", quality_score=0.95))
        fabric.register_agent(agent("b-healthy", "provider-b", "healthy", quality_score=0.90))
        receipt = await fabric.dispatch(task())
        self.assertEqual(receipt.agent_id, "b-healthy")
        self.assertEqual(receipt.fallback_count, 1)

    async def test_stale_probe_and_unverified_route_are_not_eligible(self):
        fabric = AgentFabric()
        fabric.register_adapter("fake", FakeAdapter())
        fabric.register_agent(agent("stale", "provider", "fake",
                                    last_verified_at=time.time() - 90_000))
        with self.assertRaises(NoEligibleAgent):
            await fabric.dispatch(task())

    async def test_approval_required_before_external_dispatch(self):
        fabric = AgentFabric()
        adapter = FakeAdapter()
        fabric.register_adapter("fake", adapter)
        fabric.register_agent(agent("agent", "provider", "fake"))
        with self.assertRaises(Exception):
            await fabric.dispatch(task(requires_approval=True))
        self.assertEqual(adapter.submitted, [])


    async def test_owner_approval_requires_scoped_one_time_token(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ApprovalService("a" * 40, Path(directory) / "approvals.sqlite3")
            fabric = AgentFabric(approval_service=service)
            adapter = FakeAdapter()
            fabric.register_adapter("fake", adapter)
            fabric.register_agent(agent("agent", "provider", "fake"))

            with self.assertRaises(Exception):
                await fabric.dispatch(task(requires_approval=True, approved_by="owner"))
            self.assertEqual(adapter.submitted, [])

            token = service.issue(
                action="agent.dispatch", resource_id="qudron/job-1", approved_by="owner"
            )
            approved_task = task(requires_approval=True, approved_by="owner", approval_token=token)
            receipt = await fabric.dispatch(approved_task)
            self.assertEqual(receipt.agent_id, "agent")
            with self.assertRaises(Exception):
                await fabric.dispatch(approved_task)
            self.assertEqual(len(adapter.submitted), 1)

    async def test_mismatched_provider_handle_is_rejected(self):
        fabric = AgentFabric()
        fabric.register_adapter("fake", FakeAdapter())
        fabric.register_agent(agent("agent", "provider", "fake"))
        receipt = await fabric.dispatch(task())
        wrong = AgentTaskHandle("other-provider", receipt.handle.remote_task_id, TaskStatus.RUNNING)
        with self.assertRaises(Exception):
            await fabric.poll("agent", wrong)


if __name__ == "__main__":
    unittest.main()
