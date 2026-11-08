import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import deepseek_web as dw


class Resp:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class WebTests(unittest.TestCase):
    def test_search_requires_key_and_explicit_daily_cap(self):
        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "",
            "QUDRON_WEB_SEARCH_MAX_DAILY_CALLS": "5",
        }, clear=True), self.assertRaisesRegex(dw.WebResearchError, "DEEPSEEK_API_KEY"):
            dw.search_web("official model docs")

    def test_zero_daily_cap_rejects_even_when_cached(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test",
            "QUDRON_WEB_SEARCH_MAX_DAILY_CALLS": "1",
            "QUDRON_WEB_SEARCH_DB": str(Path(tmp) / "usage.sqlite3"),
        }, clear=True):
            with patch.object(dw, "open_credential_request", return_value=Resp({
                "results": [{"title": "Cached", "content": "result"}]
            })):
                dw.search_web("daily cap check")
            with patch.dict(os.environ, {"QUDRON_WEB_SEARCH_MAX_DAILY_CALLS": "0"}):
                with self.assertRaisesRegex(dw.WebResearchError, "disabled"):
                    dw.search_web("daily cap check")

    def test_search_is_metered_and_returns_structured_sources(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test",
            "QUDRON_WEB_SEARCH_MAX_DAILY_CALLS": "2",
            "QUDRON_WEB_SEARCH_DB": str(Path(tmp) / "usage.sqlite3"),
            "QUDRON_WEB_SEARCH_CACHE_TTL_SECONDS": "0",
        }, clear=True):
            with patch.object(dw, "open_credential_request", return_value=Resp({
                "results": [{"title": "Official docs", "url": "https://example.com", "content": "evidence"}]
            })):
                result = dw.search_web("official model release", count=3)
            self.assertEqual(result["usage"]["daily_calls"], 1)
            self.assertEqual(result["usage"]["provider_calls"], 1)
            self.assertEqual(result["cost_usd"], dw.COST_PER_SUCCESS_USD)
            self.assertEqual(result["results"][0]["content"], "evidence")

    def test_identical_search_reuses_cache_without_spending_another_call(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test",
            "QUDRON_WEB_SEARCH_MAX_DAILY_CALLS": "2",
            "QUDRON_WEB_SEARCH_DB": str(Path(tmp) / "usage.sqlite3"),
        }, clear=True):
            response = Resp({"results": [{"title": "Official", "url": "https://example.com", "content": "source"}]})
            with patch.object(dw, "open_credential_request", return_value=response) as request:
                first = dw.search_web("  Official   model docs ")
                second = dw.search_web("official model docs")
            self.assertEqual(request.call_count, 1)
            self.assertFalse(first["cached"])
            self.assertTrue(second["cached"])
            self.assertEqual(second["usage"]["provider_calls"], 0)
            self.assertEqual(second["cost_usd"], 0.0)
            self.assertEqual(first["results"], second["results"])

    def test_cache_key_does_not_store_raw_query(self):
        self.assertNotIn("secret-looking-query", dw._cache_key("secret-looking-query", 5, True))
        self.assertEqual(dw._cache_key("Same query", 5, True), dw._cache_key(" same   QUERY ", 5, True))

    def test_cache_write_failure_keeps_live_results(self):
        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test",
            "QUDRON_WEB_SEARCH_MAX_DAILY_CALLS": "1",
        }, clear=True):
            with patch.object(dw, "_read_search_cache", return_value=None):
                with patch.object(dw, "_request", return_value=({
                    "results": [{"title": "Live result", "content": "kept"}]
                }, {"daily_calls": 1})):
                    with patch.object(dw, "_write_search_cache", side_effect=sqlite3.OperationalError("disk full")):
                        result = dw.search_web("cache write should be best effort")
            self.assertEqual(result["results"][0]["title"], "Live result")

    def test_empty_search_result_is_not_cached(self):
        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test",
            "QUDRON_WEB_SEARCH_MAX_DAILY_CALLS": "1",
        }, clear=True):
            with patch.object(dw, "_read_search_cache", return_value=None):
                with patch.object(dw, "_request", return_value=({"results": []}, {"daily_calls": 1})):
                    with patch.object(dw, "_write_search_cache") as write:
                        result = dw.search_web("empty result")
            write.assert_not_called()
            self.assertEqual(result["results"], [])

    def test_fetch_null_fields_are_empty_and_not_charged(self):
        with patch.object(dw, "_request", return_value=({"title": None, "content": None}, {})):
            result = dw.fetch_page("https://example.com")
        self.assertEqual(result["title"], "")
        self.assertEqual(result["content"], "")
        self.assertEqual(result["cost_usd"], 0.0)

    def test_cache_is_bounded_by_row_count_and_total_bytes(self):
        self.assertGreater(dw.MAX_SEARCH_CACHE_TOTAL_BYTES, dw.MAX_CACHED_SEARCH_BYTES)
        self.assertGreater(dw.MAX_SEARCH_CACHE_ROWS, 0)

    def test_daily_call_cap_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test",
            "QUDRON_WEB_SEARCH_MAX_DAILY_CALLS": "1",
            "QUDRON_WEB_SEARCH_DB": str(Path(tmp) / "usage.sqlite3"),
            "QUDRON_WEB_SEARCH_CACHE_TTL_SECONDS": "0",
        }, clear=True):
            with patch.object(dw, "open_credential_request", return_value=Resp({"results": []})):
                dw.search_web("query one")
                with self.assertRaisesRegex(dw.WebResearchError, "Daily"):
                    dw.search_web("query two")

    def test_fetch_rejects_local_and_non_https_targets(self):
        for url in (
            "http://example.com", "https://localhost/path", "https://127.0.0.1/path",
            "https://user:pass@example.com",
        ):
            with self.assertRaises(ValueError):
                dw._safe_url(url)

    def test_query_and_count_are_bounded(self):
        with self.assertRaises(ValueError):
            dw.search_web("")
        with self.assertRaises(ValueError):
            dw.search_web("valid query", count=11)

    def test_source_fields_are_bounded_before_entering_agent_context(self):
        result = dw._bounded_results([{
            "title": "t" * 1000,
            "url": "https://example.com/" + "x" * 2000,
            "content": "c" * 5000,
            "untrusted_extra": "discarded",
        }], 1)
        self.assertEqual(len(result[0]["title"]), 240)
        self.assertEqual(len(result[0]["url"]), 1000)
        self.assertEqual(len(result[0]["content"]), 2200)
        self.assertNotIn("untrusted_extra", result[0])


if __name__ == "__main__":
    unittest.main()
