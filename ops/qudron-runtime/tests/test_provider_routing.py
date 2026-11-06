import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import qudron_worker as worker
from provider_resilience import ProviderRoute, ProviderHealthStore


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, limit=-1):
        return self.payload[:limit]


def route(route_id, provider_id, model, base_url, *, primary=False, accepted=("public",), priority=10):
    return ProviderRoute(
        route_id=route_id,
        provider_id=provider_id,
        profile="balanced",
        base_url=base_url,
        model=model,
        api_key="private-test-key",
        price_class="paid",
        input_usd_per_1m=0.30,
        output_usd_per_1m=1.20,
        accepted_data_classes=accepted,
        priority=priority,
        is_primary=primary,
    )


class ProviderRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = worker.DB_PATH
        worker.DB_PATH = Path(self.temp.name) / "qudron.sqlite3"

    def tearDown(self):
        worker.DB_PATH = self.old_db
        self.temp.cleanup()

    def job(self, task_type="research"):
        return {
            "id": "job-provider-001",
            "role": "Research Analyst",
            "task_type": task_type,
            "title": "Provider failover test",
            "prompt": "Use only public, non-sensitive test content.",
        }

    def test_transient_primary_failure_fails_over_to_approved_route(self):
        primary = route(
            "primary:balanced:one", "primary.example", "model-primary",
            "https://primary.example/v1", primary=True,
        )
        backup = route(
            "deepseek-balanced", "deepseek", "deepseek-flash",
            "https://api.deepseek.com", priority=20,
        )
        seen = []
        def fake_open(request, timeout=0):
            seen.append(request.full_url)
            if len(seen) == 1:
                raise HTTPError(request.full_url, 429, "rate limit", None, None)
            return FakeResponse({
                "choices": [{"message": {"content": "Recovered via authorized backup."}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            })
        selected = []
        with (
            patch.object(worker, "load_provider_routes", return_value=[primary, backup]),
            patch.object(worker, "reserve_model_budget", side_effect=["reservation-1", "reservation-2"]) as reserve,
            patch.object(worker, "release_model_budget_reservation") as release_budget,
            patch.object(worker, "acquire_model_call_slot", return_value="slot") as acquire_slot,
            patch.object(worker, "release_model_call_slot") as release_slot,
            patch.object(worker, "record_model_usage") as record_usage,
            patch("urllib.request.urlopen", side_effect=fake_open),
        ):
            answer = worker.call_llm(
                self.job(), {"id": "research_analyst", "profile": "balanced"},
                "Research the topic.", "", "",
                on_route_selected=lambda provider, model, profile: selected.append((provider, model, profile)),
            )
        self.assertEqual(answer, "Recovered via authorized backup.")
        self.assertEqual(seen, [
            "https://primary.example/v1/chat/completions",
            "https://api.deepseek.com/chat/completions",
        ])
        self.assertEqual(selected[-1], ("deepseek", "deepseek-flash", "balanced"))
        self.assertEqual(reserve.call_count, 2)
        self.assertEqual(record_usage.call_count, 1)
        self.assertEqual(acquire_slot.call_count, 2)
        self.assertEqual(release_slot.call_count, 2)
        self.assertEqual(release_budget.call_count, 1)

        health = ProviderHealthStore(worker.DB_PATH)
        self.assertTrue(health.circuit_open(primary))
        self.assertEqual(health.get(backup)["status"], "healthy")

    def test_confidential_job_never_uses_public_internal_only_routes(self):
        public_route = route(
            "public-only", "public.example", "public-model",
            "https://public.example/v1", accepted=("public", "internal"),
        )
        with (
            patch.object(worker, "load_provider_routes", return_value=[public_route]),
            patch("urllib.request.urlopen") as network,
        ):
            with self.assertRaisesRegex(RuntimeError, "data class 'confidential'"):
                worker.call_llm(
                    self.job("cvpen_cv_creation"),
                    {"id": "cv_writer", "profile": "balanced"},
                    "Create a draft.", "", "",
                )
        network.assert_not_called()

    def test_budget_exhaustion_stops_all_routes_without_fallback(self):
        first = route("primary", "one", "model-one", "https://one.example/v1", primary=True)
        second = route("backup", "two", "model-two", "https://two.example/v1")
        with (
            patch.object(worker, "load_provider_routes", return_value=[first, second]),
            patch.object(worker, "reserve_model_budget", side_effect=RuntimeError(
                "Qudron daily model budget reached"
            )),
            patch("urllib.request.urlopen") as network,
        ):
            with self.assertRaisesRegex(RuntimeError, "daily model budget reached"):
                worker.call_llm(
                    self.job(), {"id": "research_analyst", "profile": "balanced"},
                    "Research.", "", "",
                )
        network.assert_not_called()

    def test_http_request_does_not_include_unconfigured_credentials(self):
        route_without_key = ProviderRoute(
            route_id="local", provider_id="local", profile="balanced",
            base_url="http://freellm:4000/v1", model="auto",
            accepted_data_classes=("public",), anonymous=True, verified_free=True,
            price_class="free", input_usd_per_1m=0, output_usd_per_1m=0,
        )
        seen = []
        def fake_open(request, timeout=0):
            seen.append(request)
            return FakeResponse({
                "choices": [{"message": {"content": "Public test result."}}],
                "usage": {},
            })
        with (
            patch.object(worker, "load_provider_routes", return_value=[route_without_key]),
            patch.object(worker, "reserve_model_budget", return_value="reservation"),
            patch.object(worker, "release_model_budget_reservation"),
            patch.object(worker, "acquire_model_call_slot", return_value="slot"),
            patch.object(worker, "release_model_call_slot"),
            patch.object(worker, "record_model_usage"),
            patch("urllib.request.urlopen", side_effect=fake_open),
        ):
            answer = worker.call_llm(
                self.job(), {"id": "research_analyst", "profile": "balanced"},
                "Summarize public facts.", "", "",
            )
        self.assertEqual(answer, "Public test result.")
        self.assertIsNone(seen[0].get_header("Authorization"))


if __name__ == "__main__":
    unittest.main()
