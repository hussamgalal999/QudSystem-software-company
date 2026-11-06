"""Provider-neutral admission control for remote compute resources.

This is a control-plane contract, not a provider implementation. A provider is
not usable until an owner-authorized adapter performs a live probe and
provision/release operations. Free notebook sessions are never treated as
persistent machines by default.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import sqlite3
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
    max_concurrent_leases: int = 1
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
        if self.max_concurrent_leases < 1:
            raise ValueError("max_concurrent_leases must be >= 1")


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


class SQLiteComputeLeaseStore:
    """Durable, cross-process lease ledger for compute resources.

    Active and release-pending leases continue consuming provider capacity
    after a Qudron restart. Reservations expire only after a bounded timeout;
    a timed-out provider call therefore cannot immediately free capacity when
    its remote allocation outcome is unknown.
    """

    ACTIVE_STATES = ("active", "release_pending")

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _ensure_schema(self) -> None:
        db = self._connect()
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS compute_leases (
                    lease_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    provider_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    endpoint_ref TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    state TEXT NOT NULL CHECK(state IN ('active','release_pending')),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_compute_leases_provider_state
                    ON compute_leases(provider_id, state, expires_at);
                CREATE TABLE IF NOT EXISTS compute_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    provider_id TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_compute_reservations_provider_expiry
                    ON compute_reservations(provider_id, expires_at);
            """)
            reservation_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(compute_reservations)")
            }
            if "runtime_seconds" not in reservation_columns:
                db.execute(
                    "ALTER TABLE compute_reservations ADD COLUMN runtime_seconds INTEGER NOT NULL DEFAULT 0"
                )
        finally:
            db.close()

    @staticmethod
    def _to_lease(row: sqlite3.Row) -> ComputeLease:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, ValueError):
            metadata = {}
        return ComputeLease(
            provider_id=row["provider_id"],
            lease_id=row["lease_id"],
            resource_id=row["resource_id"],
            expires_at=float(row["expires_at"]),
            endpoint_ref=row["endpoint_ref"],
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    def find_request(self, request_id: str) -> tuple[str, ComputeLease] | None:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT * FROM compute_leases WHERE request_id=?",
                (request_id,),
            ).fetchone()
            return (row["state"], self._to_lease(row)) if row else None
        finally:
            db.close()

    def get_lease(self, lease_id: str) -> tuple[str, ComputeLease] | None:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT * FROM compute_leases WHERE lease_id=?",
                (lease_id,),
            ).fetchone()
            return (row["state"], self._to_lease(row)) if row else None
        finally:
            db.close()

    def leases(self) -> list[tuple[str, ComputeLease]]:
        db = self._connect()
        try:
            rows = db.execute(
                "SELECT * FROM compute_leases ORDER BY created_at, lease_id"
            ).fetchall()
            return [(row["state"], self._to_lease(row)) for row in rows]
        finally:
            db.close()

    def active_count(self, provider_id: str, now: float | None = None) -> int:
        current = time.time() if now is None else now
        db = self._connect()
        try:
            lease_count = db.execute(
                "SELECT COUNT(*) FROM compute_leases WHERE provider_id=? AND state IN (?,?) AND expires_at>?",
                (provider_id, *self.ACTIVE_STATES, current),
            ).fetchone()[0]
            reservation_count = db.execute(
                "SELECT COUNT(*) FROM compute_reservations WHERE provider_id=? AND expires_at>?",
                (provider_id, current),
            ).fetchone()[0]
            return int(lease_count) + int(reservation_count)
        finally:
            db.close()

    def reserve(
        self,
        provider_id: str,
        request_id: str,
        max_concurrent_leases: int,
        ttl_seconds: int,
        quota_remaining_seconds: int | None = None,
        requested_runtime_seconds: int = 0,
    ) -> str | None:
        """Atomically reserve one provider slot across multiple Qudron processes."""
        now = time.time()
        reservation_id = uuid.uuid4().hex
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM compute_reservations WHERE expires_at<=?",
                (now,),
            )
            existing_lease = db.execute(
                "SELECT 1 FROM compute_leases WHERE request_id=?",
                (request_id,),
            ).fetchone()
            existing_reservation = db.execute(
                "SELECT 1 FROM compute_reservations WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if existing_lease or existing_reservation:
                db.commit()
                return None
            active = db.execute(
                "SELECT COUNT(*) FROM compute_leases WHERE provider_id=? AND state IN (?,?) AND expires_at>?",
                (provider_id, *self.ACTIVE_STATES, now),
            ).fetchone()[0]
            reserved = db.execute(
                "SELECT COUNT(*) FROM compute_reservations WHERE provider_id=? AND expires_at>?",
                (provider_id, now),
            ).fetchone()[0]
            if int(active) + int(reserved) >= max_concurrent_leases:
                db.commit()
                return None
            if quota_remaining_seconds is not None:
                active_rows = db.execute(
                    """SELECT metadata_json,expires_at,created_at FROM compute_leases
                       WHERE provider_id=? AND state IN (?,?) AND expires_at>?""",
                    (provider_id, *self.ACTIVE_STATES, now),
                ).fetchall()
                active_runtime = 0
                for row in active_rows:
                    try:
                        metadata = json.loads(row["metadata_json"] or "{}")
                    except (TypeError, ValueError):
                        metadata = {}
                    reserved_runtime = metadata.get("reserved_runtime_seconds")
                    if not isinstance(reserved_runtime, int) or reserved_runtime < 0:
                        reserved_runtime = max(0, int(float(row["expires_at"]) - now))
                    active_runtime += reserved_runtime
                reserved_runtime = int(db.execute(
                    """SELECT COALESCE(SUM(runtime_seconds),0) FROM compute_reservations
                       WHERE provider_id=? AND expires_at>?""",
                    (provider_id, now),
                ).fetchone()[0])
                if (
                    active_runtime + reserved_runtime + max(0, int(requested_runtime_seconds))
                    > max(0, int(quota_remaining_seconds))
                ):
                    db.commit()
                    return None
            db.execute(
                """INSERT INTO compute_reservations
                   (reservation_id,request_id,provider_id,expires_at,created_at,runtime_seconds)
                   VALUES(?,?,?,?,?,?)""",
                (
                    reservation_id, request_id, provider_id, now + ttl_seconds, now,
                    max(0, int(requested_runtime_seconds)),
                ),
            )
            db.commit()
            return reservation_id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def save_lease(
        self,
        reservation_id: str | None,
        request_id: str,
        lease: ComputeLease,
        state: str = "active",
    ) -> None:
        if state not in self.ACTIVE_STATES:
            raise ValueError("Unsupported compute lease state")
        now = time.time()
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT lease_id FROM compute_leases WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row and row["lease_id"] != lease.lease_id:
                raise ComputeFabricError("Request already owns a different compute lease")
            by_id = db.execute(
                "SELECT request_id FROM compute_leases WHERE lease_id=?",
                (lease.lease_id,),
            ).fetchone()
            if by_id and by_id["request_id"] != request_id:
                raise ComputeFabricError("Compute lease ID is already owned by another request")
            db.execute(
                """INSERT INTO compute_leases
                   (lease_id,request_id,provider_id,resource_id,expires_at,endpoint_ref,
                    metadata_json,state,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(lease_id) DO UPDATE SET
                     state=excluded.state, updated_at=excluded.updated_at""",
                (
                    lease.lease_id, request_id, lease.provider_id, lease.resource_id,
                    lease.expires_at, lease.endpoint_ref,
                    json.dumps(lease.metadata, ensure_ascii=False, default=str),
                    state, now, now,
                ),
            )
            if reservation_id:
                db.execute(
                    "DELETE FROM compute_reservations WHERE reservation_id=?",
                    (reservation_id,),
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def cancel_reservation(self, reservation_id: str | None) -> None:
        if not reservation_id:
            return
        db = self._connect()
        try:
            db.execute(
                "DELETE FROM compute_reservations WHERE reservation_id=?",
                (reservation_id,),
            )
        finally:
            db.close()

    def mark_release_pending(self, lease_id: str) -> None:
        db = self._connect()
        try:
            db.execute(
                "UPDATE compute_leases SET state='release_pending',updated_at=? WHERE lease_id=?",
                (time.time(), lease_id),
            )
        finally:
            db.close()

    def delete_lease(self, lease_id: str) -> None:
        db = self._connect()
        try:
            db.execute("DELETE FROM compute_leases WHERE lease_id=?", (lease_id,))
        finally:
            db.close()

    def snapshot(self) -> dict[str, int]:
        now = time.time()
        db = self._connect()
        try:
            active = db.execute(
                "SELECT COUNT(*) FROM compute_leases WHERE state='active' AND expires_at>?",
                (now,),
            ).fetchone()[0]
            release_pending = db.execute(
                "SELECT COUNT(*) FROM compute_leases WHERE state='release_pending'",
            ).fetchone()[0]
            reservations = db.execute(
                "SELECT COUNT(*) FROM compute_reservations WHERE expires_at>?",
                (now,),
            ).fetchone()[0]
            return {
                "active_leases": int(active),
                "release_pending": int(release_pending),
                "reservations": int(reservations),
            }
        finally:
            db.close()


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

    def __init__(
        self,
        policy: ComputeFabricPolicy | None = None,
        lease_store: SQLiteComputeLeaseStore | None = None,
    ):
        self.policy = policy or ComputeFabricPolicy()
        self.lease_store = lease_store
        self._providers: dict[str, ComputeProviderDescriptor] = {}
        self._adapters: dict[str, ComputeAdapter] = {}
        self._leases: dict[str, tuple[str, ComputeLease]] = {}
        self._reservations: dict[str, int] = {}
        self._reservations_runtime: dict[str, int] = {}
        self._release_lock = asyncio.Lock()
        self._releasing_leases: set[str] = set()
        if self.lease_store:
            for _, lease in self.lease_store.leases():
                self._leases[lease.lease_id] = (lease.provider_id, lease)
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
        # Store-backed admission is rechecked atomically by reserve() below.
        # Keep this synchronous candidate-ranking pass memory-only so it never
        # blocks the asyncio event loop on SQLite I/O.
        now = time.time()
        active = sum(
            1 for provider_id, lease in self._leases.values()
            if provider_id == provider.provider_id and lease.expires_at > now
        )
        reserved = self._reservations.get(provider.provider_id, 0)
        if active + reserved >= provider.max_concurrent_leases:
            return False, "provider_concurrency_limit"
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
        if provider.quota_remaining_seconds is not None:
            active_runtime = sum(
                max(0, int(lease.metadata.get(
                    "reserved_runtime_seconds",
                    max(0, lease.expires_at - time.time()),
                )))
                for provider_id, lease in self._leases.values()
                if provider_id == provider.provider_id and lease.expires_at > time.time()
            )
            reserved_runtime = self._reservations_runtime.get(provider.provider_id, 0)
            if active_runtime + reserved_runtime + request.min_runtime_seconds > provider.quota_remaining_seconds:
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
        # The same logical request is idempotent across process restarts when
        # a durable lease store is configured.
        if self.lease_store:
            prior = await asyncio.to_thread(self.lease_store.find_request, request.request_id)
            if prior:
                state, existing_lease = prior
                if state == "active" and existing_lease.expires_at > time.time():
                    self._leases[existing_lease.lease_id] = (
                        existing_lease.provider_id, existing_lease
                    )
                    return existing_lease
                raise ComputeProviderUnavailable(
                    f"Request {request.request_id} already has a {state} or expired lease; "
                    "reconcile it before retrying"
                )

        candidates = self.eligible_providers(request)
        if not candidates:
            raise NoEligibleCompute(
                f"No compute provider passed policy gates: {self.rejection_reasons(request)}"
            )
        failures = []
        for provider in candidates:
            adapter = self._adapters[provider.adapter]
            reservation_id = None
            locally_reserved = False
            if self.lease_store:
                reservation_id = await asyncio.to_thread(
                    self.lease_store.reserve,
                    provider.provider_id,
                    request.request_id,
                    provider.max_concurrent_leases,
                    max(300, self.policy.request_timeout_seconds * 2),
                    provider.quota_remaining_seconds,
                    request.min_runtime_seconds,
                )
                if not reservation_id:
                    failures.append(f"{provider.provider_id}:capacity_or_duplicate_request")
                    continue
            else:
                async with self._lock:
                    eligible, reason = self._eligible(provider, request)
                    if not eligible:
                        failures.append(f"{provider.provider_id}:{reason}")
                        continue
                    self._reservations[provider.provider_id] = (
                        self._reservations.get(provider.provider_id, 0) + 1
                    )
                    self._reservations_runtime[provider.provider_id] = (
                        self._reservations_runtime.get(provider.provider_id, 0)
                        + request.min_runtime_seconds
                    )
                    locally_reserved = True

            lease: ComputeLease | None = None
            reservation_resolved = False
            try:
                lease = await asyncio.wait_for(
                    adapter.acquire(provider, request),
                    timeout=self.policy.request_timeout_seconds,
                )
                # A provider allocation is a real resource. Persist its
                # quota reservation before exposing it to callers.
                lease = replace(
                    lease,
                    metadata={
                        **lease.metadata,
                        "reserved_runtime_seconds": request.min_runtime_seconds,
                    },
                )
                if lease.provider_id != provider.provider_id:
                    raise ComputeFabricError("Adapter returned a mismatched provider identity")
                if lease.expires_at - time.time() < request.min_runtime_seconds:
                    raise ComputeFabricError(
                        "Adapter returned a compute lease shorter than the requested minimum runtime"
                    )
                if lease.lease_id in self._leases:
                    raise ComputeFabricError("Duplicate active compute lease ID")
                if self.lease_store:
                    await asyncio.to_thread(
                        self.lease_store.save_lease,
                        reservation_id, request.request_id, lease, state="active"
                    )
                    reservation_resolved = True
                async with self._lock:
                    self._leases[lease.lease_id] = (provider.provider_id, lease)
                return lease
            except Exception as exc:
                failures.append(f"{provider.provider_id}:{type(exc).__name__}")
                if lease is not None:
                    # Never silently forget a resource that may have been
                    # allocated. Keep it occupying capacity until release is
                    # confirmed, even when the adapter returned bad metadata.
                    cleanup_lease = (
                        lease if lease.provider_id == provider.provider_id
                        else replace(lease, provider_id=provider.provider_id)
                    )
                    persisted = False
                    if self.lease_store:
                        try:
                            await asyncio.to_thread(
                                self.lease_store.save_lease,
                                reservation_id, request.request_id,
                                cleanup_lease, state="release_pending",
                            )
                            self._leases[cleanup_lease.lease_id] = (
                                provider.provider_id, cleanup_lease
                            )
                            persisted = True
                            reservation_resolved = True
                        except Exception:
                            # If persistence itself failed, still attempt
                            # immediate cleanup; do not report success.
                            pass
                    try:
                        await asyncio.wait_for(
                            adapter.release(provider, cleanup_lease),
                            timeout=self.policy.request_timeout_seconds,
                        )
                        if persisted and self.lease_store:
                            await asyncio.to_thread(self.lease_store.delete_lease, cleanup_lease.lease_id)
                        self._leases.pop(cleanup_lease.lease_id, None)
                        reservation_resolved = True
                    except Exception:
                        # Preserve an in-process blocker even if the durable
                        # write failed; a durable reservation remains until
                        # expiry and protects other Qudron processes.
                        self._leases[cleanup_lease.lease_id] = (
                            provider.provider_id, cleanup_lease
                        )
                elif self.lease_store:
                    # On timeout, the remote side may have allocated a
                    # resource before the response was lost. Keep the bounded
                    # reservation until expiry to avoid immediate overbooking.
                    if not isinstance(exc, asyncio.TimeoutError):
                        await asyncio.to_thread(self.lease_store.cancel_reservation, reservation_id)
                        reservation_resolved = True
                continue
            finally:
                if self.lease_store and reservation_id and reservation_resolved:
                    # No-op after commit; removes a reservation after clean
                    # failure or successful compensating release.
                    await asyncio.to_thread(self.lease_store.cancel_reservation, reservation_id)
                elif locally_reserved:
                    async with self._lock:
                        remaining = self._reservations.get(provider.provider_id, 1) - 1
                        if remaining > 0:
                            self._reservations[provider.provider_id] = remaining
                        else:
                            self._reservations.pop(provider.provider_id, None)
                        remaining_runtime = (
                            self._reservations_runtime.get(provider.provider_id, 0)
                            - request.min_runtime_seconds
                        )
                        if remaining_runtime > 0:
                            self._reservations_runtime[provider.provider_id] = remaining_runtime
                        else:
                            self._reservations_runtime.pop(provider.provider_id, None)
        raise ComputeProviderUnavailable(
            "All eligible compute providers failed: " + ", ".join(failures)
        )

    async def release(self, lease: ComputeLease) -> None:
        async with self._release_lock:
            if lease.lease_id in self._releasing_leases:
                raise ComputeFabricError("Compute lease release is already in progress")
            stored = self._leases.get(lease.lease_id)
            if not stored and self.lease_store:
                persisted = await asyncio.to_thread(self.lease_store.get_lease, lease.lease_id)
                if persisted:
                    state, persisted_lease = persisted
                    stored = (persisted_lease.provider_id, persisted_lease)
                    self._leases[lease.lease_id] = stored
            if not stored or stored[0] != lease.provider_id or stored[1] != lease:
                raise ComputeFabricError("Unknown or mismatched compute lease")
            provider = self._providers.get(lease.provider_id)
            if not provider:
                raise ComputeProviderUnavailable(
                    f"Provider {lease.provider_id} is not registered for lease recovery"
                )
            self._releasing_leases.add(lease.lease_id)
        try:
            adapter = self._adapters[provider.adapter]
            if self.lease_store:
                await asyncio.to_thread(self.lease_store.mark_release_pending, lease.lease_id)
            # Keep the lease in both stores until provider release is confirmed.
            await asyncio.wait_for(
                adapter.release(provider, lease),
                timeout=self.policy.request_timeout_seconds,
            )
            if self.lease_store:
                await asyncio.to_thread(self.lease_store.delete_lease, lease.lease_id)
            self._leases.pop(lease.lease_id, None)
        finally:
            async with self._release_lock:
                self._releasing_leases.discard(lease.lease_id)

    def snapshot(self) -> dict[str, Any]:
        persisted = self.lease_store.snapshot() if self.lease_store else {
            "active_leases": sum(1 for _, lease in self._leases.values() if lease.expires_at > time.time()),
            "release_pending": 0,
            "reservations": sum(self._reservations.values()),
        }
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
            **persisted,
        }
