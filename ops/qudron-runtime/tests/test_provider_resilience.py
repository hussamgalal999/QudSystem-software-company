import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from provider_resilience import (
    ProviderHealthStore,
    eligible_routes,
    load_provider_routes,
    models_endpoint,
    probe_route,
    route_allowed_for_data,
    ProviderCatalogueStore,
    probe_catalogue_provider,
    probe_due_catalogue_providers,
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, limit=-1):
        return self.payload[:limit]


class ProviderResilienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "provider-health.sqlite3"
        self.store = ProviderHealthStore(self.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_fallback_routes_require_explicit_owner_approval_and_exact_protocol(self):
        env = {
            "QUDRON_PROVIDER_ROUTES_JSON": json.dumps([
                {
                    "route_id": "deepseek-balanced",
                    "provider_id": "deepseek",
                    "profile": "balanced",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-flash",
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "enabled": True,
                    "owner_approved": True,
                    "protocol": "openai_chat_completions",
                    "price_class": "paid",
                    "input_usd_per_1m": 0.3,
                    "output_usd_per_1m": 1.2,
                    "accepted_data_classes": ["public", "internal"],
                },
                {
                    "route_id": "unapproved-route",
                    "provider_id": "unapproved",
                    "profile": "balanced",
                    "base_url": "https://unapproved.example/v1",
                    "model": "example-model",
                    "enabled": True,
                    "owner_approved": False,
                    "price_class": "paid",
                    "input_usd_per_1m": 1,
                    "output_usd_per_1m": 2,
                },
                {
                    "route_id": "unsupported-protocol",
                    "provider_id": "other",
                    "profile": "balanced",
                    "base_url": "https://other.example/v1",
                    "model": "example-model",
                    "enabled": True,
                    "owner_approved": True,
                    "protocol": "gemini_generate_content",
                    "price_class": "paid",
                    "input_usd_per_1m": 1,
                    "output_usd_per_1m": 2,
                },
            ]),
            "DEEPSEEK_API_KEY": "secret-value-not-to-display",
        }
        routes = load_provider_routes("balanced", environ=env)
        self.assertEqual([route.route_id for route in routes], ["deepseek-balanced"])
        self.assertEqual(routes[0].provider_id, "deepseek")
        self.assertEqual(routes[0].api_key, "secret-value-not-to-display")
        self.assertNotIn("secret-value-not-to-display", json.dumps(routes[0].safe_record()))

    def test_missing_fallback_credentials_and_missing_paid_prices_fail_closed(self):
        env = {
            "QUDRON_PROVIDER_ROUTES_JSON": json.dumps([
                {
                    "route_id": "missing-key", "provider_id": "p1",
                    "profile": "balanced", "base_url": "https://p1.example/v1",
                    "model": "model-1", "api_key_env": "PROVIDER_KEY",
                    "enabled": True, "owner_approved": True,
                    "price_class": "paid", "input_usd_per_1m": 1,
                    "output_usd_per_1m": 2,
                },
                {
                    "route_id": "missing-price", "provider_id": "p2",
                    "profile": "balanced", "base_url": "https://p2.example/v1",
                    "model": "model-2", "api_key_env": "PROVIDER_KEY",
                    "enabled": True, "owner_approved": True,
                    "price_class": "paid",
                },
            ]),
        }
        self.assertEqual(load_provider_routes("balanced", environ=env), [])

    def test_free_fallback_requires_owner_verified_free_entitlement(self):
        env = {
            "QUDRON_PROVIDER_ROUTES_JSON": json.dumps([
                {
                    "route_id": "guessed-free", "provider_id": "p1",
                    "profile": "balanced", "base_url": "https://p1.example/v1",
                    "model": "model-1", "requires_api_key": False,
                    "enabled": True, "owner_approved": True, "price_class": "free",
                    "verified_free": False,
                },
                {
                    "route_id": "verified-free", "provider_id": "p2",
                    "profile": "balanced", "base_url": "https://p2.example/v1",
                    "model": "model-2", "requires_api_key": False,
                    "enabled": True, "owner_approved": True, "price_class": "free",
                    "verified_free": True,
                },
            ]),
        }
        routes = load_provider_routes("balanced", environ=env)
        self.assertEqual([route.route_id for route in routes], ["verified-free"])
        self.assertEqual(routes[0].input_usd_per_1m, 0.0)
        self.assertEqual(routes[0].output_usd_per_1m, 0.0)

    def test_primary_route_uses_configured_profile_and_owner_data_policy(self):
        env = {
            "LLM_BASE_URL": "https://api.deepseek.com",
            "LLM_MODEL": "deepseek-flash",
            "LLM_API_KEY": "private-key",
            "QUDRON_PROVIDER_DATA_CLASSES": "public,internal,confidential",
            "LLM_BALANCED_INPUT_USD_PER_1M": "0.3",
            "LLM_BALANCED_OUTPUT_USD_PER_1M": "1.2",
        }
        routes = load_provider_routes("balanced", environ=env)
        self.assertEqual(len(routes), 1)
        route = routes[0]
        self.assertEqual(route.model, "deepseek-flash")
        self.assertTrue(route.is_primary)
        self.assertTrue(route_allowed_for_data(route, "confidential"))
        self.assertEqual(route.input_usd_per_1m, 0.3)

    def test_primary_route_defaults_to_public_and_internal_only(self):
        env = {"LLM_BASE_URL": "https://api.example.com/v1", "LLM_MODEL": "model-1"}
        route = load_provider_routes("balanced", environ=env)[0]
        self.assertTrue(route_allowed_for_data(route, "public"))
        self.assertTrue(route_allowed_for_data(route, "internal"))
        self.assertFalse(route_allowed_for_data(route, "confidential"))

    def test_route_must_use_https_or_private_local_http(self):
        env = {
            "QUDRON_PROVIDER_ROUTES_JSON": json.dumps([
                {
                    "route_id": "unsafe-http", "provider_id": "p1",
                    "profile": "balanced", "base_url": "http://public.example/v1",
                    "model": "model-1", "api_key_env": "KEY",
                    "enabled": True, "owner_approved": True, "price_class": "paid",
                    "input_usd_per_1m": 1, "output_usd_per_1m": 1,
                },
            ]),
            "KEY": "secret",
        }
        with self.assertRaises(ValueError):
            load_provider_routes("balanced", environ=env)

    def test_probe_uses_read_only_models_endpoint_and_confirms_exact_model(self):
        env = {"LLM_BASE_URL": "https://api.deepseek.com", "LLM_MODEL": "deepseek-flash"}
        route = load_provider_routes("balanced", environ=env)[0]
        seen = []
        def fake_open(request, timeout=0):
            seen.append((request.full_url, request.get_header("Authorization"), request.get_method(), timeout))
            return FakeResponse({"object": "list", "data": [{"id": "deepseek-flash"}]})
        result = probe_route(route, self.store, opener=fake_open, now=1000)
        self.assertEqual(seen[0][0], "https://api.deepseek.com/models")
        self.assertEqual(seen[0][2], "GET")
        self.assertEqual(result["status"], "healthy")
        self.assertTrue(result["model_available"])
        health = self.store.get(route)
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["last_probe"], 1000)

    def test_virtual_auto_model_uses_catalogue_presence(self):
        route = load_provider_routes(
            "balanced",
            environ={
                "LLM_BASE_URL": "http://freellm:4000/v1",
                "LLM_MODEL": "auto",
                "LLM_API_KEY": "local-server-key",
            },
        )[0]
        result = probe_route(
            route, self.store,
            opener=lambda *_args, **_kwargs: FakeResponse({"data": [{"id": "deepseek-flash"}]}),
        )
        self.assertEqual(result["status"], "healthy")

    def test_unauthorized_probe_opens_circuit_and_persists_after_restart(self):
        route = load_provider_routes(
            "balanced",
            environ={"LLM_BASE_URL": "https://api.example.com/v1", "LLM_MODEL": "model-1"},
        )[0]
        def unauthorized(*_args, **_kwargs):
            raise HTTPError("https://api.example.com/v1/models", 401, "unauthorized", None, None)
        probe_route(route, self.store, opener=unauthorized, now=2000)
        self.assertTrue(self.store.circuit_open(route, now=2001))
        restarted = ProviderHealthStore(self.db_path)
        self.assertTrue(restarted.circuit_open(route, now=2001))
        self.assertFalse(restarted.circuit_open(route, now=4000))

    def test_eligible_routes_respect_data_class_and_open_circuit(self):
        env = {
            "LLM_BASE_URL": "https://api.example.com/v1",
            "LLM_MODEL": "model-1",
            "QUDRON_PROVIDER_DATA_CLASSES": "public,internal",
        }
        route = load_provider_routes("balanced", environ=env)[0]
        self.assertEqual(eligible_routes([route], self.store, data_class="internal"), [route])
        self.store.mark_call_failure(route, "http_429", now=3000)
        self.assertEqual(eligible_routes([route], self.store, data_class="internal", now=3001), [])
        self.assertEqual(eligible_routes([route], self.store, data_class="confidential", now=4000), [])


    def test_official_catalogue_discovery_uses_provider_specific_auth_header(self):
        provider = {
            "provider": "Google Gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "auth_env": "GEMINI_API_KEY",
            "discovery": {
                "enabled": True, "probe_path": "/models",
                "probe_auth_header": "x-goog-api-key",
            },
        }
        seen = []
        def fake_open(request, timeout=0):
            headers = {name.lower(): value for name, value in request.header_items()}
            seen.append((request.full_url, headers.get("x-goog-api-key"), request.get_method()))
            return FakeResponse({
                "models": [{"name": "models/gemini-3.8-flash", "displayName": "Gemini 3.8 Flash"}]
            })
        store = ProviderCatalogueStore(self.db_path)
        result = probe_catalogue_provider(
            provider, store, environ={"GEMINI_API_KEY": "catalogue-secret"},
            opener=fake_open, now=5000,
        )
        self.assertEqual(seen[0], (
            "https://generativelanguage.googleapis.com/v1beta/models",
            "catalogue-secret", "GET",
        ))
        self.assertEqual(result["status"], "healthy")
        record = store.get("Google Gemini")
        self.assertEqual(record["models"][0]["id"], "gemini-3.8-flash")
        self.assertNotIn("catalogue-secret", json.dumps(record))

    def test_catalogue_discovery_rechecks_missing_credentials_each_cycle(self):
        store = ProviderCatalogueStore(self.db_path)
        provider = {
            "provider": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "auth_env": "DEEPSEEK_API_KEY",
            "discovery": {
                "enabled": True, "probe_path": "/models",
                "probe_auth_header": "bearer",
            },
        }
        catalogue_path = Path(self.temp.name) / "models.json"
        catalogue_path.write_text(json.dumps({"providers": [provider]}), encoding="utf-8")
        first = probe_due_catalogue_providers(
            catalogue_path, store, environ={}, now=1000,
        )
        self.assertEqual(first[0]["status"], "credentials_not_configured")
        calls = []
        def fake_open(request, timeout=0):
            calls.append(request)
            return FakeResponse({"data": [{"id": "deepseek-flash"}]})
        second = probe_due_catalogue_providers(
            catalogue_path, store,
            environ={"DEEPSEEK_API_KEY": "owner-secret"},
            opener=fake_open, now=1010,
        )
        self.assertEqual(second[0]["status"], "healthy")
        self.assertEqual(len(calls), 1)

    def test_success_closes_circuit_and_clears_failure_counter(self):
        route = load_provider_routes(
            "balanced",
            environ={"LLM_BASE_URL": "https://api.example.com/v1", "LLM_MODEL": "model-1"},
        )[0]
        self.store.mark_call_failure(route, "network_unavailable", now=1000)
        self.assertTrue(self.store.circuit_open(route, now=1001))
        self.store.mark_call_success(route, now=2000)
        record = self.store.get(route)
        self.assertEqual(record["status"], "healthy")
        self.assertEqual(record["consecutive_failures"], 0)
        self.assertEqual(record["open_until"], 0)


if __name__ == "__main__":
    unittest.main()
