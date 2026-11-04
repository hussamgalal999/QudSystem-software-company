import os
import unittest
from unittest.mock import patch

import qudron_worker


class ScheduledCapabilityMiningTests(unittest.TestCase):
    def test_skips_without_github_credentials_and_makes_no_api_call(self):
        with patch.dict(os.environ, {"GITHUB_OWNER": "", "GITHUB_TOKEN": ""}):
            with patch.object(qudron_worker, "mine_from_environment") as miner:
                result = qudron_worker.execute_job_swarm({"task_type": "capability_mining"})
        self.assertIn("skipped", result.lower())
        miner.assert_not_called()

    def test_uses_bounded_miner_when_credentials_exist(self):
        expected = {"candidates_registered": 7, "source_execution_performed": False}
        with patch.dict(os.environ, {
            "GITHUB_OWNER": "owner",
            "GITHUB_TOKEN": "read-only-token",
            "QUDRON_GITHUB_MINE_MAX_REPOSITORIES": "25",
        }):
            with patch.object(qudron_worker, "mine_from_environment", return_value=expected) as miner:
                result = qudron_worker.execute_job_swarm({"task_type": "capability_mining"})
        miner.assert_called_once_with(max_repositories=25)
        self.assertIn('"candidates_registered": 7', result)
        self.assertIn("source_execution_performed", result)

    def test_task_is_internal_not_external(self):
        self.assertIn("capability_mining", qudron_worker.ALLOWED_TASK_TYPES)
        self.assertNotIn("capability_mining", qudron_worker.EXTERNAL_API_TASK_TYPES)


if __name__ == "__main__":
    unittest.main()
