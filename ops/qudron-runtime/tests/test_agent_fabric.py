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
    async def test_update_agent_resizes_the_existing_slot_without_bypassing_active_work(self):
        class BlockingAdapter(FakeAdapter):
            def __init__(self):
                super().__init__()
                self.active = 0
                self.max_active = 0
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def submit(self, agent_descriptor, task_envelope):
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                self.started.set()
                try:
                    await self.release.wait()
                finally:
                    self.active -= 1
                return AgentTaskHandle(
                    agent_descriptor.provider_id,
                    f"remote-{task_envelope.task_id}",
                    TaskStatus.RUNNING,
                )

        fabric = AgentFabric()
        adapter = BlockingAdapter()
        fabric.register_adapter("fake", adapter)
        original = agent("worker", "provider", "fake", max_concurrency=1)
        fabric.register_agent(original)

        first = asyncio.create_task(fabric.dispatch(task(
            task_id="job-first", idempotency_key="idem-first",
        )))
        await adapter.started.wait()

        refreshed = agent("worker", "provider", "fake", max_concurrency=1)
        fabric.update_agent(refreshed)
        second = asyncio.create_task(fabric.dispatch(task(
            task_id="job-second", idempotency_key="idem-second",
        )))
        await asyncio.sleep(0.02)
        self.assertEqual(adapter.max_active, 1)

        adapter.release.set()
        first_receipt = await first
        await fabric.poll("worker", first_receipt.handle)
        second_receipt = await second
        await fabric.poll("worker", second_receipt.handle)
        self.assertEqual(adapter.max_active, 1)

    async def test_routes_to_eligible_agent_and_polls_result(self):
        fabric = AgentFabric()
        adapter = FakeAdapter()
        fabric.register_adapter("fake", adapter)
        fabric.register_agent(agent("gemini-research", "gemini-free", "fake"))
        receipt = await fabric.dispatch(task())
        result = await fabric.poll("gemini-research", receipt.handle)
        self.assertEqual(receipt.provider_id, "gemini-free")
        self.assertEqual(result.status, TaskStatus.SUCCEEDED)

    async def test_dispatch_holds_admission_lease_until_remote_terminal_state(self):
        fabric = AgentFabric()
        adapter = FakeAdapter()
        fabric.register_adapter("fake", adapter)
        fabric.register_agent(agent("worker", "provider", "fake", max_concurrency=1))

        first = await fabric.dispatch(task(task_id="job-one", idempotency_key="idem-one"))
        second_task = asyncio.create_task(
            fabric.dispatch(task(task_id="job-two", idempotency_key="idem-two"))
        )
        await asyncio.sleep(0.02)
        self.assertEqual(len(adapter.submitted), 1)

        first_result = await fabric.poll("worker", first.handle)
        self.assertEqual(first_result.status, TaskStatus.SUCCEEDED)
        second = await second_task
        self.assertEqual(len(adapter.submitted), 2)
        await fabric.poll("worker", second.handle)

    async def test_timed_out_submission_holds_slot_until_explicit_reconciliation(self):
        class HangingAdapter:
            async def submit(self, agent_descriptor, task_envelope):
                await asyncio.Event().wait()
            async def poll(self, agent_descriptor, handle):
                raise AssertionError("poll must not run before a handle is known")
            async def follow_up(self, agent_descriptor, handle, message):
                raise AssertionError("follow_up must not run")
            async def cancel(self, agent_descriptor, handle):
                raise AssertionError("cancel must not run")

        fabric = AgentFabric(FabricPolicy(request_timeout_seconds=0.01))
        fabric.register_adapter("hanging", HangingAdapter())
        fabric.register_agent(agent("worker", "provider", "hanging", max_concurrency=1))
        with self.assertRaises(ProviderUnavailable):
            await fabric.dispatch(task(task_id="job-timeout", idempotency_key="idem-timeout"))
        self.assertEqual(fabric._agent_slots["worker"]._active, 1)
        await fabric.reconcile_submission_timeout("worker", "job-timeout", handle=None)
        self.assertEqual(fabric._agent_slots["worker"]._active, 0)

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

    async def test_ambiguous_submit_timeout_does_not_fail_over_and_duplicate_task(self):
        class HangingAdapter:
            def __init__(self):
                self.calls = 0
            async def submit(self, agent_descriptor, task_envelope):
                self.calls += 1
                await asyncio.Event().wait()
            async def poll(self, agent_descriptor, handle):
                raise AssertionError("poll must not be called")
            async def follow_up(self, agent_descriptor, handle, message):
                raise AssertionError("follow_up must not be called")
            async def cancel(self, agent_descriptor, handle):
                raise AssertionError("cancel must not be called")

        slow = HangingAdapter()
        fallback = FakeAdapter()
        fabric = AgentFabric(FabricPolicy(request_timeout_seconds=0.01))
        fabric.register_adapter("slow", slow)
        fabric.register_adapter("fake", fallback)
        fabric.register_agent(agent(
            "a-slow", "provider-a", "slow", quality_score=0.95,
        ))
        fabric.register_agent(agent(
            "b-fallback", "provider-b", "fake", quality_score=0.90,
        ))

        with self.assertRaisesRegex(ProviderUnavailable, "outcome is unknown"):
            await fabric.dispatch(task())
        self.assertEqual(slow.calls, 1)
        self.assertEqual(fallback.submitted, [])

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
        fabric.register_agent(agent("never-verified", "provider", "fake",
                                    last_verified_at=None))
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
