import time
import unittest
import tempfile
from pathlib import Path

from agent_protocol import DataClass
from compute_fabric import (
    ComputeFabric, ComputeLease, ComputeProviderDescriptor, ComputeRequest,
    NoEligibleCompute, SQLiteComputeLeaseStore,
)


class FakeComputeAdapter:
    def __init__(self):
        self.acquired = []
        self.released = []

    async def acquire(self, provider, request):
        self.acquired.append((provider.provider_id, request.request_id))
        return ComputeLease(
            provider_id=provider.provider_id,
            lease_id="lease-" + provider.provider_id,
            resource_id="gpu-instance-1",
            expires_at=time.time() + 300,
            endpoint_ref="https://compute.example.test/job/1",
        )

    async def release(self, provider, lease):
        self.released.append((provider.provider_id, lease.lease_id))


def provider(provider_id="kaggle", **kwargs):
    values = dict(
        provider_id=provider_id, adapter="fake", kind="ephemeral_notebook_gpu",
        price_class="free_compute", access_mode="official_account_session",
        authorized=True, enabled=True, health="healthy",
        last_verified_at=time.time(), quality_score=0.9,
        cpu_cores=4, ram_gb=29, gpu_name="NVIDIA Tesla P100",
        gpu_vram_gb=16, max_runtime_seconds=12 * 60 * 60,
        persistent=False, capabilities=("notebook", "gpu", "pytorch"),
        accepted_data_classes=("public", "internal"),
        quota_remaining_seconds=3600,
        terms_url="https://www.kaggle.com/docs/notebooks",
    )
    values.update(kwargs)
    return ComputeProviderDescriptor(**values)


def request(**kwargs):
    values = dict(
        request_id="compute-1", workload="short-model-inference",
        required_capabilities=("gpu", "pytorch"), min_cpu_cores=2,
        min_ram_gb=16, min_gpu_vram_gb=12, min_runtime_seconds=600,
        allowed_kinds=("ephemeral_notebook_gpu",),
        allowed_access_modes=("official_account_session",),
        data_class=DataClass.PUBLIC,
    )
    values.update(kwargs)
    return ComputeRequest(**values)


class ComputeFabricTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fabric = ComputeFabric()
        self.adapter = FakeComputeAdapter()
        self.fabric.register_adapter("fake", self.adapter)

    async def test_authorized_recent_free_gpu_is_selected_and_released(self):
        self.fabric.register_provider(provider())
        lease = await self.fabric.acquire(request())
        self.assertEqual(lease.provider_id, "kaggle")
        self.assertEqual(self.fabric.snapshot()["active_leases"], 1)
        await self.fabric.release(lease)
        self.assertEqual(self.fabric.snapshot()["active_leases"], 0)
        self.assertEqual(self.adapter.released, [("kaggle", "lease-kaggle")])

    async def test_provider_concurrency_cap_blocks_second_active_lease(self):
        self.fabric.register_provider(provider(max_concurrent_leases=1))
        first = await self.fabric.acquire(request())
        with self.assertRaises(NoEligibleCompute):
            await self.fabric.acquire(request(request_id="compute-2"))
        await self.fabric.release(first)
        second = await self.fabric.acquire(request(request_id="compute-3"))
        self.assertEqual(second.provider_id, "kaggle")
        await self.fabric.release(second)

    async def test_unverified_or_unauthorized_provider_is_never_eligible(self):
        self.fabric.register_provider(provider("unverified", last_verified_at=None))
        self.fabric.register_provider(provider("unauthorized", authorized=False))
        with self.assertRaises(NoEligibleCompute):
            await self.fabric.acquire(request())

    async def test_paid_and_stale_providers_are_rejected_by_default(self):
        self.fabric.register_provider(provider("paid", price_class="paid"))
        self.fabric.register_provider(provider("stale", last_verified_at=time.time() - 100_000))
        with self.assertRaises(NoEligibleCompute):
            await self.fabric.acquire(request())

    async def test_ephemeral_notebook_cannot_satisfy_persistent_ollama_request(self):
        self.fabric.register_provider(provider())
        with self.assertRaises(NoEligibleCompute):
            await self.fabric.acquire(request(
                persistent_required=True,
                allowed_kinds=("ephemeral_notebook_gpu",),
            ))

    async def test_confidential_data_is_denied_by_default(self):
        self.fabric.register_provider(provider(
            accepted_data_classes=("public", "internal", "confidential"),
        ))
        with self.assertRaises(NoEligibleCompute):
            await self.fabric.acquire(request(data_class=DataClass.CONFIDENTIAL))

    async def test_insufficient_vram_or_quota_is_rejected(self):
        self.fabric.register_provider(provider("small", gpu_vram_gb=8, quota_remaining_seconds=30))
        with self.assertRaises(NoEligibleCompute):
            await self.fabric.acquire(request(min_gpu_vram_gb=24, min_runtime_seconds=600))

    async def test_unknown_lease_release_is_rejected(self):
        self.fabric.register_provider(provider())
        lease = await self.fabric.acquire(request())
        with self.assertRaises(Exception):
            await self.fabric.release(ComputeLease(
                provider_id=lease.provider_id, lease_id="unknown",
                resource_id=lease.resource_id, expires_at=lease.expires_at,
            ))
        await self.fabric.release(lease)


    async def test_sqlite_lease_survives_restart_and_blocks_provider_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "compute-leases.sqlite3"
            fabric_one = ComputeFabric(lease_store=SQLiteComputeLeaseStore(database))
            adapter_one = FakeComputeAdapter()
            fabric_one.register_adapter("fake", adapter_one)
            fabric_one.register_provider(provider(max_concurrent_leases=1))
            lease = await fabric_one.acquire(request())

            fabric_two = ComputeFabric(lease_store=SQLiteComputeLeaseStore(database))
            adapter_two = FakeComputeAdapter()
            fabric_two.register_adapter("fake", adapter_two)
            fabric_two.register_provider(provider(max_concurrent_leases=1))
            with self.assertRaises(NoEligibleCompute):
                await fabric_two.acquire(request(request_id="compute-after-restart"))

            self.assertEqual(fabric_two.snapshot()["active_leases"], 1)
            await fabric_two.release(lease)
            self.assertEqual(fabric_two.snapshot()["active_leases"], 0)
            next_lease = await fabric_two.acquire(
                request(request_id="compute-after-release")
            )
            self.assertEqual(next_lease.provider_id, "kaggle")
            await fabric_two.release(next_lease)

    async def test_same_request_id_reuses_persisted_lease_without_second_allocation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "compute-leases.sqlite3"
            first = ComputeFabric(lease_store=SQLiteComputeLeaseStore(database))
            first_adapter = FakeComputeAdapter()
            first.register_adapter("fake", first_adapter)
            first.register_provider(provider())
            lease_one = await first.acquire(request())

            second = ComputeFabric(lease_store=SQLiteComputeLeaseStore(database))
            second_adapter = FakeComputeAdapter()
            second.register_adapter("fake", second_adapter)
            second.register_provider(provider())
            lease_two = await second.acquire(request())

            self.assertEqual(lease_one, lease_two)
            self.assertEqual(second_adapter.acquired, [])
            await second.release(lease_two)

    async def test_failed_release_is_persisted_and_keeps_provider_capacity_reserved(self):
        class FailingReleaseAdapter(FakeComputeAdapter):
            async def release(self, provider_descriptor, lease):
                raise RuntimeError("remote release confirmation unavailable")

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "compute-leases.sqlite3"
            first = ComputeFabric(lease_store=SQLiteComputeLeaseStore(database))
            failing = FailingReleaseAdapter()
            first.register_adapter("fake", failing)
            first.register_provider(provider(max_concurrent_leases=1))
            lease = await first.acquire(request())
            with self.assertRaises(RuntimeError):
                await first.release(lease)

            self.assertEqual(first.snapshot()["release_pending"], 1)
            second = ComputeFabric(lease_store=SQLiteComputeLeaseStore(database))
            adapter = FakeComputeAdapter()
            second.register_adapter("fake", adapter)
            second.register_provider(provider(max_concurrent_leases=1))
            with self.assertRaises(NoEligibleCompute):
                await second.acquire(request(request_id="blocked-by-pending-release"))

            await second.release(lease)
            self.assertEqual(second.snapshot()["release_pending"], 0)
            next_lease = await second.acquire(
                request(request_id="after-release-reconciled")
            )
            await second.release(next_lease)

    async def test_two_fabric_instances_share_atomic_provider_lease_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "compute-leases.sqlite3"
            first = ComputeFabric(lease_store=SQLiteComputeLeaseStore(database))
            first_adapter = FakeComputeAdapter()
            first.register_adapter("fake", first_adapter)
            first.register_provider(provider(max_concurrent_leases=1))

            second = ComputeFabric(lease_store=SQLiteComputeLeaseStore(database))
            second_adapter = FakeComputeAdapter()
            second.register_adapter("fake", second_adapter)
            second.register_provider(provider(max_concurrent_leases=1))

            results = await asyncio.gather(
                first.acquire(request(request_id="parallel-one")),
                second.acquire(request(request_id="parallel-two")),
                return_exceptions=True,
            )
            leases = [item for item in results if isinstance(item, ComputeLease)]
            errors = [item for item in results if isinstance(item, Exception)]
            self.assertEqual(len(leases), 1)
            self.assertEqual(len(errors), 1)
            self.assertEqual(
                SQLiteComputeLeaseStore(database).active_count("kaggle"), 1
            )
            owner = first if first_adapter.acquired else second
            await owner.release(leases[0])


if __name__ == "__main__":
    unittest.main()
