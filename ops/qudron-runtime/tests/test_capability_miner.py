import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import capability_miner as miner
from capability_registry import get_capability, initialize_registry


class CapabilityMinerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.tmp.name) / "capabilities.sqlite3"
        initialize_registry(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def repo(self, **extra):
        value = {
            "full_name": "owner/repo", "description": "Useful project",
            "html_url": "https://github.com/owner/repo", "default_branch": "main",
            "updated_at": "2026-11-01T10:00:00Z", "private": False,
            "archived": False, "size": 123,
        }
        value.update(extra)
        return value

    def test_evaluator_uses_path_signals_without_claiming_verification(self):
        tree = {"truncated": False, "entries": [
            {"path": "README.md", "type": "blob"},
            {"path": "LICENSE", "type": "blob"},
            {"path": "pyproject.toml", "type": "blob"},
            {"path": "tests/test_core.py", "type": "blob"},
            {"path": ".github/workflows/ci.yml", "type": "blob"},
        ]}
        item = miner.evaluate_repository(self.repo(), tree)
        self.assertEqual(item["status"], "candidate")
        self.assertEqual(item["license"], "unknown")
        self.assertIsNone(item["verified_at"])
        self.assertTrue(item["metadata"]["signals"]["license_file_present"])
        self.assertEqual(item["metadata"]["evaluation_scope"], "metadata_and_paths_only_no_source_execution")

    def test_archived_repository_is_deprecated(self):
        item = miner.evaluate_repository(self.repo(archived=True), {"entries": [], "truncated": False})
        self.assertEqual(item["status"], "deprecated")

    def test_mining_registers_candidates_without_execution(self):
        tree = {"truncated": False, "entries": [{"path": "README.md", "type": "blob"}]}
        with patch.object(miner, "discover_repositories", return_value=[self.repo()]), \
             patch.object(miner, "repository_tree", return_value=tree):
            result = miner.mine_repositories("owner", "read-only-token", self.db, max_repositories=10)
        self.assertEqual(result["candidates_registered"], 1)
        self.assertFalse(result["source_execution_performed"])
        saved = get_capability(self.db, "github:owner/repo")
        self.assertEqual(saved["status"], "candidate")

    def test_invalid_batch_size_rejected_before_network(self):
        with self.assertRaises(ValueError):
            miner.mine_repositories("owner", "token", self.db, max_repositories=201)

    def test_missing_credentials_fail_closed(self):
        with patch.dict("os.environ", {"GITHUB_OWNER": "", "GITHUB_TOKEN": ""}):
            with self.assertRaises(Exception):
                miner.mine_from_environment(self.db)


if __name__ == "__main__":
    unittest.main()
