"""Qudron's provider-neutral agent registry, routing and lifecycle fabric.

Adapters may speak A2A, MCP, Manus API, a trusted local worker, or a device
bridge. The fabric enforces a common policy before a provider receives work.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Any, Protocol, runtime_checkable

from agent_protocol import (
    AgentDescriptor, AgentTaskHandle, AgentTaskResult, DataClass, TaskEnvelope,
    TaskStatus,
)
from approval_service import ApprovalService


class AgentFabricError(RuntimeError):
    pass


class NoEligibleAgent(AgentFabricError):
    pass


class ProviderUnavailable(AgentFabricError):
    pass


@runtime_checkable
class AgentAdapter(Protocol):
    async def submit(self, agent: AgentDescriptor, task: TaskEnvelope) -> AgentTaskHandle: ...
    async def poll(self, agent: AgentDescriptor, handle: AgentTaskHandle) -> AgentTaskResult: ...
    async def follow_up(
        self, agent: AgentDescriptor, handle: AgentTaskHandle, message: str
    ) -> AgentTaskHandle: ...
    async def cancel(self, agent: AgentDescriptor, handle: AgentTaskHandle) -> AgentTaskHandle: ...


@dataclass(frozen=True)
class FabricPolicy:
    """Default to genuinely free, explicitly authorized, quality-qualified routes."""
    free_only: bool = True
    allowed_price_classes: tuple[str, ...] = ("free", "free_compute")
    allowed_access_modes: tuple[str, ...] = (
        "official_free_tier", "official_web_session", "a2a_authorized_free",
        "mcp_authorized_free", "owner_device", "free_compute",
    )
    minimum_quality_score: float = 0.75
    maximum_probe_age_seconds: int = 86_400
    maximum_parallel_per_provider: int = 4
    request_timeout_seconds: int = 60
    permit_confidential_data: bool = False
    permit_restricted_data: bool = False
    allow_unverified_fallback: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_quality_score <= 1.0:
            raise ValueError("minimum_quality_score must be between 0 and 1")
        if self.maximum_parallel_per_provider < 1:
            raise ValueError("maximum_parallel_per_provider must be >= 1")


@dataclass(frozen=True)
class DispatchReceipt:
    agent_id: str
    provider_id: str
    handle: AgentTaskHandle
    fallback_count: int = 0
    route_reason: str = ""


class _ResizableSemaphore:
    """Stable per-agent concurrency gate whose capacity can change in place."""

    def __init__(self, value: int):
        self._limit = max(1, int(value))
        self._active = 0
        self._condition = asyncio.Condition()

    async def acquire(self):
        async with self._condition:
            await self._condition.wait_for(lambda: self._active < self._limit)
            self._active += 1

    async def release(self):
        async with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        await self.release()

    def resize(self, value: int) -> None:
        self._limit = max(1, int(value))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._notify_waiters())

    async def _notify_waiters(self) -> None:
        async with self._condition:
            self._condition.notify_all()


class AgentFabric:
    def __init__(
        self,
        policy: FabricPolicy | None = None,
        *,
        approval_service: ApprovalService | None = None,
    ):
        self.policy = policy or FabricPolicy()
        self.approval_service = approval_service
        self._agents: dict[str, AgentDescriptor] = {}
        self._adapters: dict[str, AgentAdapter] = {}
        self._agent_slots: dict[str, _ResizableSemaphore] = {}
        self._provider_slots: dict[str, asyncio.Semaphore] = {}
        self._in_flight: dict[str, int] = {}
        self._active_task_leases: dict[tuple[str, str], tuple[asyncio.Semaphore, _ResizableSemaphore]] = {}
        self._unknown_submission_leases: dict[tuple[str, str], tuple[asyncio.Semaphore, _ResizableSemaphore]] = {}
        self._lock = asyncio.Lock()

    def register_adapter(self, adapter_id: str, adapter: AgentAdapter) -> None:
        if not adapter_id or adapter_id in self._adapters:
            raise ValueError("adapter_id must be non-empty and unique")
        self._adapters[adapter_id] = adapter

    def register_agent(self, descriptor: AgentDescriptor) -> None:
        if descriptor.agent_id in self._agents:
            raise ValueError(f"Duplicate agent identity: {descriptor.agent_id}")
        if descriptor.adapter not in self._adapters:
            raise ValueError(f"Adapter is not registered: {descriptor.adapter}")
        self._agents[descriptor.agent_id] = descriptor
        self._agent_slots[descriptor.agent_id] = _ResizableSemaphore(descriptor.max_concurrency)
        self._provider_slots.setdefault(
            descriptor.provider_id,
            asyncio.Semaphore(self.policy.maximum_parallel_per_provider),
        )
        self._in_flight.setdefault(descriptor.provider_id, 0)

    def update_agent(self, descriptor: AgentDescriptor) -> None:
        if descriptor.agent_id not in self._agents:
            raise KeyError(descriptor.agent_id)
        if descriptor.adapter not in self._adapters:
            raise ValueError(f"Adapter is not registered: {descriptor.adapter}")
        current = self._agents[descriptor.agent_id]
        has_active_remote_work = (
            any(key[0] == descriptor.agent_id for key in self._active_task_leases)
            or any(key[0] == descriptor.agent_id for key in self._unknown_submission_leases)
        )
        if has_active_remote_work and (
            descriptor.provider_id != current.provider_id
            or descriptor.adapter != current.adapter
        ):
            raise AgentFabricError(
                "Cannot change an agent provider or adapter while remote tasks are active"
            )
        self._agents[descriptor.agent_id] = descriptor
        # Keep the same gate object: replacing it while callers are waiting or
        # running creates two independent semaphore pools and bypasses the cap.
        slot = self._agent_slots.get(descriptor.agent_id)
        if slot is None:
            self._agent_slots[descriptor.agent_id] = _ResizableSemaphore(descriptor.max_concurrency)
        else:
            slot.resize(descriptor.max_concurrency)
        self._provider_slots.setdefault(
            descriptor.provider_id,
            asyncio.Semaphore(self.policy.maximum_parallel_per_provider),
        )

    def agent_snapshot(self) -> list[dict[str, Any]]:
        now = time.time()
        result = []
        for agent in self._agents.values():
            verified_age = (
                max(0.0, now - agent.last_verified_at)
                if agent.last_verified_at is not None else None
            )
            result.append({
                "agent_id": agent.agent_id,
                "provider_id": agent.provider_id,
                "adapter": agent.adapter,
                "enabled": agent.enabled,
                "health": agent.health,
                "quality_score": agent.quality_score,
                "verified_age_seconds": verified_age,
                "in_flight_provider": self._in_flight.get(agent.provider_id, 0),
                "active_remote_tasks": sum(1 for key in self._active_task_leases if key[0] == agent.agent_id)
                + sum(1 for key in self._unknown_submission_leases if key[0] == agent.agent_id),
            })
        return result

    def _eligible(self, agent: AgentDescriptor, task: TaskEnvelope) -> tuple[bool, str]:
        if not agent.enabled:
            return False, "disabled"
        if agent.health != "healthy":
            return False, "health_not_verified"
        if agent.adapter not in self._adapters:
            return False, "adapter_missing"
        if agent.quality_score < self.policy.minimum_quality_score:
            return False, "quality_below_threshold"
        if agent.last_verified_at is None:
            return False, "never_probed"
        if time.time() - agent.last_verified_at > self.policy.maximum_probe_age_seconds:
            return False, "probe_stale"
        if self.policy.free_only and agent.price_class not in self.policy.allowed_price_classes:
            return False, "not_in_approved_free_price_class"
        if agent.access_mode not in self.policy.allowed_access_modes:
            return False, "access_mode_not_authorized"
        if not set(task.required_skills).issubset(set(agent.skills)):
            return False, "missing_required_skill"
        if not set(task.required_modalities).issubset(set(agent.modalities_in)):
            return False, "missing_input_modality"
        if task.execution_mode.value not in agent.supported_modes:
            return False, "execution_mode_not_supported"
        if task.data_class.value not in agent.accepted_data_classes:
            return False, "data_class_not_accepted"
        if task.data_class == DataClass.CONFIDENTIAL and not self.policy.permit_confidential_data:
            return False, "confidential_data_policy_denied"
        if task.data_class == DataClass.RESTRICTED and not self.policy.permit_restricted_data:
            return False, "restricted_data_policy_denied"
        return True, "eligible"

    def eligible_agents(self, task: TaskEnvelope) -> list[AgentDescriptor]:
        ranked: list[tuple[float, AgentDescriptor]] = []
        for agent in self._agents.values():
            eligible, _ = self._eligible(agent, task)
            if not eligible:
                continue
            skill_match = len(set(task.required_skills) & set(agent.skills))
            utilization = self._in_flight.get(agent.provider_id, 0)
            score = agent.quality_score + min(skill_match, 5) * 0.03 - utilization * 0.01
            ranked.append((score, agent))
        ranked.sort(key=lambda item: (-item[0], item[1].agent_id))
        return [agent for _, agent in ranked]

    async def dispatch(self, task: TaskEnvelope) -> DispatchReceipt:
        candidates = self.eligible_agents(task)
        if not candidates:
            reasons: dict[str, int] = {}
            for agent in self._agents.values():
                _, reason = self._eligible(agent, task)
                reasons[reason] = reasons.get(reason, 0) + 1
            raise NoEligibleAgent(f"No provider passed policy gates: {reasons}")

        if task.requires_approval:
            if self.approval_service is None or not task.approval_token:
                raise AgentFabricError("Task is waiting for authenticated owner approval")
            approval = self.approval_service.verify_and_consume(
                task.approval_token,
                action="agent.dispatch",
                resource_id=f"{task.project_id}/{task.task_id}",
            )
            if not approval:
                raise AgentFabricError("Owner approval token is invalid, expired, out of scope, or already used")

        failures: list[str] = []
        for index, agent in enumerate(candidates):
            adapter = self._adapters[agent.adapter]
            provider_slot = self._provider_slots[agent.provider_id]
            agent_slot = self._agent_slots[agent.agent_id]
            await provider_slot.acquire()
            try:
                await agent_slot.acquire()
            except Exception:
                provider_slot.release()
                raise
            acquired = True
            try:
                async with self._lock:
                    self._in_flight[agent.provider_id] = self._in_flight.get(agent.provider_id, 0) + 1
                try:
                    handle = await asyncio.wait_for(
                        adapter.submit(agent, task),
                        timeout=self.policy.request_timeout_seconds,
                    )
                finally:
                    async with self._lock:
                        self._in_flight[agent.provider_id] -= 1
                if handle.provider_id != agent.provider_id:
                    raise AgentFabricError("Adapter returned a mismatched provider identity")

                terminal = {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}
                if handle.status in terminal:
                    provider_slot.release()
                    await agent_slot.release()
                    acquired = False
                else:
                    key = (agent.agent_id, handle.remote_task_id)
                    async with self._lock:
                        if key in self._active_task_leases:
                            raise AgentFabricError("Remote task already owns an admission lease")
                        self._active_task_leases[key] = (provider_slot, agent_slot)
                    acquired = False
                return DispatchReceipt(
                    agent_id=agent.agent_id,
                    provider_id=agent.provider_id,
                    handle=handle,
                    fallback_count=index,
                    route_reason="; ".join(failures) if failures else "highest eligible capability score",
                )
            except asyncio.TimeoutError as exc:
                # A timed-out submit may still be executing in a worker thread
                # or may already exist remotely. Keep the admission slot until
                # an explicit reconciliation identifies the remote outcome.
                async with self._lock:
                    self._unknown_submission_leases[(agent.agent_id, task.task_id)] = (
                        provider_slot, agent_slot,
                    )
                acquired = False
                raise ProviderUnavailable(
                    f"Submission outcome is unknown after timeout for {agent.agent_id}; "
                    "reconcile the remote task before retrying or failing over"
                ) from exc
            except (ProviderUnavailable, ConnectionError) as exc:
                if acquired:
                    provider_slot.release()
                    await agent_slot.release()
                    acquired = False
                failures.append(f"{agent.agent_id}:{type(exc).__name__}")
                continue
            except Exception:
                if acquired:
                    provider_slot.release()
                    await agent_slot.release()
                raise
        raise ProviderUnavailable("All eligible providers failed: " + ", ".join(failures))

    async def _release_task_lease(self, agent_id: str, remote_task_id: str) -> None:
        async with self._lock:
            lease = self._active_task_leases.pop((agent_id, remote_task_id), None)
        if lease:
            provider_slot, agent_slot = lease
            provider_slot.release()
            await agent_slot.release()

    async def reconcile_submission_timeout(
        self, agent_id: str, task_id: str, handle: AgentTaskHandle | None = None
    ) -> None:
        """Owner/operator reconciliation for a timed-out, ambiguous submission.

        Pass a discovered handle if the provider accepted the task. Pass None
        only after confirming that no remote task was created.
        """
        key = (agent_id, task_id)
        async with self._lock:
            lease = self._unknown_submission_leases.pop(key, None)
            if lease is None:
                raise AgentFabricError("No unknown submission lease exists for this task")
            if handle is not None:
                agent = self._agents.get(agent_id)
                if not agent or handle.provider_id != agent.provider_id:
                    self._unknown_submission_leases[key] = lease
                    raise AgentFabricError("Reconciled handle does not match the agent provider")
                self._active_task_leases[(agent_id, handle.remote_task_id)] = lease
        if handle is None or handle.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            provider_slot, agent_slot = lease
            provider_slot.release()
            await agent_slot.release()

    async def poll(
        self, agent_id: str, handle: AgentTaskHandle
    ) -> AgentTaskResult:
        agent = self._agents.get(agent_id)
        if not agent:
            raise KeyError(agent_id)
        if handle.provider_id != agent.provider_id:
            raise AgentFabricError("Remote task handle belongs to a different provider")
        adapter = self._adapters[agent.adapter]
        result = await asyncio.wait_for(
            adapter.poll(agent, handle), timeout=self.policy.request_timeout_seconds
        )
        if result.provider_id != agent.provider_id or result.remote_task_id != handle.remote_task_id:
            raise AgentFabricError("Adapter returned a mismatched remote task result")
        if result.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            await self._release_task_lease(agent_id, handle.remote_task_id)
        return result

    async def follow_up(
        self, agent_id: str, handle: AgentTaskHandle, message: str
    ) -> AgentTaskHandle:
        agent = self._agents.get(agent_id)
        if not agent:
            raise KeyError(agent_id)
        if handle.provider_id != agent.provider_id:
            raise AgentFabricError("Remote task handle belongs to a different provider")
        updated = await asyncio.wait_for(
            self._adapters[agent.adapter].follow_up(agent, handle, message),
            timeout=self.policy.request_timeout_seconds,
        )
        if updated.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            await self._release_task_lease(agent_id, handle.remote_task_id)
        elif updated.remote_task_id != handle.remote_task_id:
            async with self._lock:
                lease = self._active_task_leases.pop((agent_id, handle.remote_task_id), None)
                if lease:
                    self._active_task_leases[(agent_id, updated.remote_task_id)] = lease
        return updated
    async def cancel(
        self, agent_id: str, handle: AgentTaskHandle
    ) -> AgentTaskHandle:
        agent = self._agents.get(agent_id)
        if not agent:
            raise KeyError(agent_id)
        if handle.provider_id != agent.provider_id:
            raise AgentFabricError("Remote task handle belongs to a different provider")
        updated = await asyncio.wait_for(
            self._adapters[agent.adapter].cancel(agent, handle),
            timeout=self.policy.request_timeout_seconds,
        )
        if updated.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            await self._release_task_lease(agent_id, handle.remote_task_id)
        return updated
