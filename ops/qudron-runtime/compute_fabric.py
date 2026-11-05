"""Provider-neutral admission control for remote compute resources.

This is a control-plane contract, not a provider implementation. A provider is
not usable until an owner-authorized adapter performs a live probe and
provision/release operations. Free notebook sessions are never treated as
persistent machines by default.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any, Protocol, runtime_checkable
import uuid

from agent_protocol import DataClass


class ComputeFabricError(RuntimeError):
    pass


class NoEligibleCompute(ComputeFabricError):
    pass


class ComputeProviderUnavailable(ComputeFabricError):
    pass


@dataclass(frozen=True)
class ComputeProviderDescriptor:
    provider_id: str
    adapter: str
    kind: str
    price_class: str
    access_mode: str
    authorized: bool = False
    enabled: bool = False
    health: str = "unknown"
    last_verified_at: float | None = None
    quality_score: float = 0.0
    cpu_cores: float = 0.0
    ram_gb: float = 0.0
    gpu_name: str | None = None
    gpu_vram_gb: float = 0.0
    max_runtime_seconds: int = 0
    persistent: bool = False
    capabilities: tuple[str, ...] = ()
    accepted_data_classes: tuple[str, ...] = (DataClass.PUBLIC.value,)
    quota_remaining_seconds: int | None = None
    endpoint_ref: str | None = None
    terms_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider_id or not self.adapter or not self.kind:
            raise ValueError("provider_id, adapter and kind are required")
        if not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("quality_score must be between 0 and 1")
        if min(self.cpu_cores, self.ram_gb, self.gpu_vram_gb) < 0:
            raise ValueError("resource capacities cannot be negative")
        if self.max_runtime_seconds < 0:
            raise ValueError("max_runtime_seconds cannot be negative")
        if self.quota_remaining_seconds is not None and self.quota_remaining_seconds < 0:
            raise ValueError("quota_remaining_seconds cannot be negative")


@dataclass(frozen=True)
class ComputeRequest:
    request_id: str
    workload: str
    required_capabilities: tuple[str, ...] = ()
    min_cpu_cores: float = 0.0
    min_ram_gb: float = 0.0
    min_gpu_vram_gb: float = 0.0
    min_runtime_seconds: int = 1
    persistent_required: bool = False
    allowed_kinds: tuple[str, ...] = ()
    allowed_price_classes: tuple[str, ...] = ("free", "free_compute")
    allowed_access_modes: tuple[str, ...] = ()
    data_class: DataClass = DataClass.PUBLIC

    def __post_init__(self) -> None:
        if not self.request_id or not self.workload.strip():
            raise ValueError("request_id and workload are required")
        if min(self.min_cpu_cores, self.min_ram_gb, self.min_gpu_vram_gb) < 0:
            raise ValueError("minimum resource requirements cannot be negative")
        if self.min_runtime_seconds < 1:
            raise ValueError("min_runtime_seconds must be >= 1")


@dataclass(frozen=True)
class ComputeLease:
    provider_id: str
    lease_id: str
    resource_id: str
    expires_at: float
    endpoint_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider_id or not self.lease_id or not self.resource_id:
            raise ValueError("provider_id, lease_id and resource_id are required")
        if self.expires_at <= 0:
            raise ValueError("expires_at must be a positive epoch timestamp")


@runtime_checkable
class ComputeAdapter(Protocol):
    async def acquire(
        self, provider: ComputeProviderDescriptor, request: ComputeRequest
    ) -> ComputeLease: ...

    async def release(
        self, provider: ComputeProviderDescriptor, lease: ComputeLease
    ) -> None: ...


@dataclass(frozen=True)
class ComputeFabricPolicy:
    free_only: bool = True
    allowed_price_classes: tuple[str, ...] = ("free", "free_compute")
    allowed_access_modes: tuple[str, ...] = (
        "official_api", "official_account_session", "official_gradio_space",
        "owner_provisioned_host",
    )
    minimum_quality_score: float = 0.75
    maximum_probe_age_seconds: int = 86_400
    request_timeout_seconds: int = 60
    permit_confidential_data: bool = False
    permit_restricted_data: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_quality_score <= 1.0:
            raise ValueError("minimum_quality_score must be between 0 and 1")
        if self.maximum_probe_age_seconds < 1 or self.request_timeout_seconds < 1:
            raise ValueError("probe age and request timeout must be positive")


class ComputeFabric:
    """Qualify and allocate only explicitly authorized, recently probed resources."""

    def __init__(self, policy: ComputeFabricPolicy | None = None):
        self.policy = policy or ComputeFabricPolicy()
        self._providers: dict[str, ComputeProviderDescriptor] = {}
        self._adapters: dict[str, ComputeAdapter] = {}
        self._leases: dict[str, tuple[str, ComputeLease]] = {}
        self._lock = asyncio.Lock()

    def register_adapter(self, adapter_id: str, adapter: ComputeAdapter) -> None:
        if not adapter_id or adapter_id in self._adapters:
            raise ValueError("adapter_id must be non-empty and unique")
        self._adapters[adapter_id] = adapter

    def register_provider(self, provider: ComputeProviderDescriptor) -> None:
        if provider.provider_id in self._providers:
            raise ValueError(f"Duplicate compute provider: {provider.provider_id}")
        if provider.adapter not in self._adapters:
            raise ValueError(f"Compute adapter is not registered: {provider.adapter}")
        self._providers[provider.provider_id] = provider

    def _eligible(self, provider: ComputeProviderDescriptor, request: ComputeRequest) -> tuple[bool, str]:
        if not provider.enabled:
            return False, "disabled"
        if not provider.authorized:
            return False, "owner_authorization_missing"
        if provider.health != "healthy":
            return False, "health_not_verified"
        if provider.adapter not in self._adapters:
            return False, "adapter_missing"
        if provider.last_verified_at is None:
            return False, "never_probed"
        if time.time() - provider.last_verified_at > self.policy.maximum_probe_age_seconds:
            return False, "probe_stale"
        if provider.quality_score < self.policy.minimum_quality_score:
            return False, "quality_below_threshold"
        if self.policy.free_only and provider.price_class not in self.policy.allowed_price_classes:
            return False, "not_in_approved_free_price_class"
        if provider.price_class not in request.allowed_price_classes:
            return False, "request_price_policy_denied"
        if provider.access_mode not in self.policy.allowed_access_modes:
            return False, "access_mode_not_authorized"
        if request.allowed_access_modes and provider.access_mode not in request.allowed_access_modes:
            return False, "request_access_policy_denied"
        if request.allowed_kinds and provider.kind not in request.allowed_kinds:
            return False, "compute_kind_not_supported"
        if not set(request.required_capabilities).issubset(provider.capabilities):
            return False, "missing_compute_capability"
        if provider.cpu_cores < request.min_cpu_cores or provider.ram_gb < request.min_ram_gb:
            return False, "insufficient_cpu_or_ram"
        if provider.gpu_vram_gb < request.min_gpu_vram_gb:
            return False, "insufficient_gpu_vram"
        if request.persistent_required and not provider.persistent:
            return False, "persistent_resource_required"
        if provider.max_runtime_seconds < request.min_runtime_seconds:
            return False, "runtime_window_too_short"
        if provider.quota_remaining_seconds is not None and provider.quota_remaining_seconds < request.min_runtime_seconds:
            return False, "insufficient_remaining_quota"
        if request.data_class.value not in provider.accepted_data_classes:
            return False, "data_class_not_accepted"
        if request.data_class == DataClass.CONFIDENTIAL and not self.policy.permit_confidential_data:
            return False, "confidential_data_policy_denied"
        if request.data_class == DataClass.RESTRICTED and not self.policy.permit_restricted_data:
            return False, "restricted_data_policy_denied"
        return True, "eligible"

    def eligible_providers(self, request: ComputeRequest) -> list[ComputeProviderDescriptor]:
        candidates = []
        for provider in self._providers.values():
            ok, _ = self._eligible(provider, request)
            if ok:
                # Prefer quality, GPU memory and quota, then stable provider ID.
                score = (
                    provider.quality_score
                    + min(provider.gpu_vram_gb, 256) / 10_000
                    + min(provider.quota_remaining_seconds or 0, 86_400) / 10_000_000
                )
                candidates.append((score, provider))
        candidates.sort(key=lambda item: (-item[0], item[1].provider_id))
        return [provider for _, provider in candidates]

    def rejection_reasons(self, request: ComputeRequest) -> dict[str, int]:
        reasons: dict[str, int] = {}
        for provider in self._providers.values():
            _, reason = self._eligible(provider, request)
            reasons[reason] = reasons.get(reason, 0) + 1
        return reasons

    async def acquire(self, request: ComputeRequest) -> ComputeLease:
        candidates = self.eligible_providers(request)
        if not candidates:
            raise NoEligibleCompute(
                f"No compute provider passed policy gates: {self.rejection_reasons(request)}"
            )
        failures = []
        for provider in candidates:
            adapter = self._adapters[provider.adapter]
            try:
                lease = await asyncio.wait_for(
                    adapter.acquire(provider, request),
                    timeout=self.policy.request_timeout_seconds,
                )
                if lease.provider_id != provider.provider_id:
                    raise ComputeFabricError("Adapter returned a mismatched provider identity")
                if lease.expires_at <= time.time():
                    raise ComputeFabricError("Adapter returned an already-expired compute lease")
                async with self._lock:
                    if lease.lease_id in self._leases:
                        raise ComputeFabricError("Duplicate active compute lease ID")
                    self._leases[lease.lease_id] = (provider.provider_id, lease)
                return lease
            except (asyncio.TimeoutError, ComputeProviderUnavailable, ConnectionError) as exc:
                failures.append(f"{provider.provider_id}:{type(exc).__name__}")
                continue
        raise ComputeProviderUnavailable("All eligible compute providers failed: " + ", ".join(failures))

    async def release(self, lease: ComputeLease) -> None:
        async with self._lock:
            stored = self._leases.get(lease.lease_id)
            if not stored or stored[0] != lease.provider_id or stored[1] != lease:
                raise ComputeFabricError("Unknown or mismatched compute lease")
            provider = self._providers[lease.provider_id]
            adapter = self._adapters[provider.adapter]
        await asyncio.wait_for(
            adapter.release(provider, lease),
            timeout=self.policy.request_timeout_seconds,
        )
        async with self._lock:
            self._leases.pop(lease.lease_id, None)

    def snapshot(self) -> dict[str, Any]:
        return {
            "providers": [
                {
                    "provider_id": p.provider_id,
                    "kind": p.kind,
                    "enabled": p.enabled,
                    "authorized": p.authorized,
                    "health": p.health,
                    "price_class": p.price_class,
                    "gpu_name": p.gpu_name,
                    "gpu_vram_gb": p.gpu_vram_gb,
                    "ram_gb": p.ram_gb,
                    "last_verified_at": p.last_verified_at,
                }
                for p in self._providers.values()
            ],
            "active_leases": len(self._leases),
        }
