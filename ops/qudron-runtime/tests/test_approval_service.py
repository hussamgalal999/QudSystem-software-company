import tempfile
import time
import unittest
from pathlib import Path

from approval_service import ApprovalService, issue_approval_token


class ApprovalServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "approvals.sqlite3"
        self.service = ApprovalService("approval-secret-" + "x" * 40, self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_token_is_scoped_and_consumed_once(self):
        token = self.service.issue(
            action="agent.dispatch",
            resource_id="qudron/job-1",
            approved_by="owner",
        )
        claims = self.service.verify_and_consume(
            token, action="agent.dispatch", resource_id="qudron/job-1"
        )
        self.assertEqual(claims["approved_by"], "owner")
        self.assertIsNone(self.service.verify_and_consume(
            token, action="agent.dispatch", resource_id="qudron/job-1"
        ))

    def test_token_cannot_be_replayed_for_a_different_action_or_resource(self):
        token = self.service.issue(
            action="agent.dispatch",
            resource_id="qudron/job-1",
            approved_by="owner",
        )
        self.assertIsNone(self.service.verify_and_consume(
            token, action="workflow.node.approve", resource_id="qudron/job-1"
        ))
        self.assertIsNone(self.service.verify_and_consume(
            token, action="agent.dispatch", resource_id="qudron/job-2"
        ))
        self.assertIsNotNone(self.service.verify_and_consume(
            token, action="agent.dispatch", resource_id="qudron/job-1"
        ))

    def test_tampered_and_expired_tokens_are_rejected(self):
        token = self.service.issue(
            action="agent.dispatch", resource_id="qudron/job-1", approved_by="owner"
        )
        encoded, signature = token.split(".")
        tampered = encoded + "." + ("0" * len(signature))
        self.assertIsNone(self.service.verify_and_consume(
            tampered, action="agent.dispatch", resource_id="qudron/job-1"
        ))

        expired = issue_approval_token(
            "approval-secret-" + "x" * 40,
            action="agent.dispatch", resource_id="qudron/job-expired",
            approved_by="owner", ttl_seconds=30,
        )
        self.assertIsNone(self.service.verify_and_consume(
            expired, action="agent.dispatch", resource_id="qudron/job-expired",
            now=time.time() + 60,
        ))

    def test_missing_or_weak_secret_is_rejected(self):
        with self.assertRaises(Exception):
            ApprovalService("weak", self.database)


if __name__ == "__main__":
    unittest.main()
