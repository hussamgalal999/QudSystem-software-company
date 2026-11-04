import json
import unittest
from unittest.mock import patch

import qudron_worker as worker

class FakeResponse:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def read(self):
        return json.dumps({"choices":[{"message":{"content":"routed response"}}]}).encode()

class ModelRoutingTests(unittest.TestCase):
    def test_agent_profile_routes_to_external_model_endpoint(self):
        captured = {}
        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode())
            captured["authorization"] = request.get_header("Authorization")
            return FakeResponse()
        with patch.dict("os.environ", {
            "LLM_FAST_BASE_URL":"https://fast.example/v1",
            "LLM_FAST_API_KEY":"test-secret",
            "LLM_FAST_MODEL":"fast-instruct"
        }, clear=True):
            with patch("qudron_worker.urllib.request.urlopen", side_effect=fake_urlopen):
                response = worker.call_llm(
                    {"role":"Research","task_type":"research","title":"Test","prompt":"Do the work"},
                    {"id":"research_analyst","name":"Research Analyst","profile":"fast",
                     "responsibilities":"Research."},
                    "Produce the report.", "", ""
                )
        self.assertEqual(response, "routed response")
        self.assertEqual(captured["url"], "https://fast.example/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "fast-instruct")
        self.assertEqual(captured["authorization"], "Bearer test-secret")

    def test_unconfigured_model_fails_closed(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(worker, "LLM_BASE_URL", ""), patch.object(worker, "LLM_MODEL", ""):
                with self.assertRaisesRegex(RuntimeError, "not configured"):
                    worker.call_llm(
                        {"role":"Research","task_type":"research","title":"Test","prompt":"Do the work"},
                        {"id":"research_analyst","profile":"balanced"},
                        "Produce the report.", "", ""
                    )

if __name__ == "__main__":
    unittest.main()
