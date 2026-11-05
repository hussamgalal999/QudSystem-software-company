import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "project_task_registry.json"
VALID_STATUSES = {
    "ci_verified",
    "implemented_pending_ci",
    "implemented_unverified",
    "open_pr",
    "candidate_not_enabled",
    "blocked_owner",
    "planned",
    "not_started",
    "target_unmeasured",
    "needs_owner_review",
    "pending_ci",
}


class QualityVerificationFrameworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.tasks = cls.registry["tasks"]

    def test_every_task_has_unique_id_and_specialty_verification_profile(self):
        ids = [task["id"] for task in self.tasks]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(self.registry["total_tasks"], len(self.tasks))
        for task in self.tasks:
            with self.subTest(task=task["id"]):
                self.assertTrue(task.get("area"))
                self.assertTrue(task.get("title"))
                self.assertTrue(task.get("acceptance_criteria"))
                self.assertTrue(task.get("evidence"))
                profile = task.get("verification_profile")
                self.assertIsInstance(profile, list)
                self.assertGreaterEqual(len(profile), 3)
                self.assertEqual(len(profile), len(set(profile)))

    def test_priorities_and_statuses_are_valid(self):
        for task in self.tasks:
            with self.subTest(task=task["id"]):
                self.assertRegex(task.get("priority", ""), r"^P[0-3]$")
                self.assertIn(task.get("status"), VALID_STATUSES)

    def test_status_counts_match_task_records(self):
        actual = {}
        for task in self.tasks:
            actual[task["status"]] = actual.get(task["status"], 0) + 1
        self.assertEqual(actual, self.registry["computed_status_counts"])
        self.assertEqual(sum(actual.values()), len(self.tasks))

    def test_remote_compute_fabric_is_explicit_p0_work(self):
        task = next(task for task in self.tasks if task["id"] == "remote-compute-fabric")
        self.assertEqual(task["area"], "Capacity")
        self.assertEqual(task["priority"], "P0")
        self.assertEqual(task["status"], "not_started")
        self.assertIn("Ollama", task["title"])
        self.assertIn("live evidence", task["acceptance_criteria"].lower())

    def test_remote_compute_catalog_never_enables_unprobed_providers(self):
        catalog_path = ROOT / "compute_provider_catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.assertTrue(catalog["policy"]["enable_only_after_live_probe"])
        for provider in catalog["providers"]:
            with self.subTest(provider=provider["id"]):
                self.assertFalse(provider["live_probe"]["verified"])
                self.assertIn(provider["status"], {
                    "candidate_not_enabled", "excluded_for_background_worker"
                })
                self.assertTrue(provider["source_urls"])

    def test_workforce_count_is_not_misrepresented_as_live_agents(self):
        task = next(task for task in self.tasks if task["id"] == "workforce-44")
        self.assertIn("48 role identities", task["current_state"])
        self.assertIn("not live model processes", task["current_state"])


if __name__ == "__main__":
    unittest.main()
