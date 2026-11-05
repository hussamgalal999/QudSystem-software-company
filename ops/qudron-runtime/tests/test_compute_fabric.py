import time
import unittest

from agent_protocol import DataClass
from compute_fabric import (
    ComputeFabric, ComputeFabricPolicy, ComputeLease, ComputeProviderDescriptor,
    ComputeRequest, NoEligibleCompute,
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
                allowed_kinds=("remote_ollama", "persistent_gpu_vm"),
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

    async def test_duplicate_and_unknown_lease_release_are_rejected(self):
        self.fabric.register_provider(provider())
        lease = await self.fabric.acquire(request())
        with self.assertRaises(Exception):
            await self.fabric.release(ComputeLease(
                provider_id=lease.provider_id, lease_id="unknown",
                resource_id=lease.resource_id, expires_at=lease.expires_at,
            ))
        await self.fabric.release(lease)


if __name__ == "__main__":
    unittest.main()
