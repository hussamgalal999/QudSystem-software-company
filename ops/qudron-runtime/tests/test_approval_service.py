import tempfile
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from approval_service import (
    ApprovalError, ApprovalService, ApprovalTokenIssuer, issue_approval_token,
)


class ApprovalServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.database = Path(self.temp.name) / "approvals.sqlite3"
        self.private_key = Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()
        self.issuer = ApprovalTokenIssuer(self.private_key)
        self.service = ApprovalService(self.public_key, self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_token_is_scoped_and_consumed_once(self):
        token = self.issuer.issue(
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
        token = self.issuer.issue(
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
        token = self.issuer.issue(
            action="agent.dispatch", resource_id="qudron/job-1", approved_by="owner"
        )
        encoded, signature = token.split(".")
        tampered = encoded + "." + ("0" * len(signature))
        self.assertIsNone(self.service.verify_and_consume(
            tampered, action="agent.dispatch", resource_id="qudron/job-1"
        ))

        expired = issue_approval_token(
            self.private_key,
            action="agent.dispatch", resource_id="qudron/job-expired",
            approved_by="owner", ttl_seconds=30,
        )
        self.assertIsNone(self.service.verify_and_consume(
            expired, action="agent.dispatch", resource_id="qudron/job-expired",
            now=time.time() + 60,
        ))

    def test_non_ascii_signature_is_rejected_without_raising(self):
        token = self.issuer.issue(
            action="agent.dispatch", resource_id="qudron/job-1", approved_by="owner"
        )
        encoded, _ = token.split(".", 1)
        malformed = encoded + "." + ("é" * 128)
        self.assertIsNone(self.service.verify_and_consume(
            malformed, action="agent.dispatch", resource_id="qudron/job-1"
        ))

    def test_overlong_approval_scope_is_rejected_not_truncated(self):
        with self.assertRaisesRegex(ApprovalError, "supported length"):
            issue_approval_token(
                self.private_key,
                action="agent.dispatch", resource_id="x" * 501, approved_by="owner",
            )

    def test_runtime_verifier_cannot_mint_or_load_a_private_key(self):
        self.assertFalse(hasattr(self.service, "issue"))
        with self.assertRaises(ApprovalError):
            ApprovalService(self.private_key, self.database)
        with self.assertRaises(ApprovalError):
            ApprovalTokenIssuer(self.public_key)



    def test_owner_issuer_loads_private_key_and_runtime_verifies_public_key_from_files(self):
        import os
        from unittest.mock import patch
        from cryptography.hazmat.primitives import serialization

        private_path = Path(self.temp.name) / "owner-private.pem"
        public_path = Path(self.temp.name) / "runtime-public.pem"
        private_path.write_bytes(self.private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        public_path.write_bytes(self.public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        with patch.dict(os.environ, {
            "QUDRON_APPROVAL_PRIVATE_KEY_FILE": str(private_path),
            "QUDRON_APPROVAL_PRIVATE_KEY_PASSPHRASE": "",
            "QUDRON_APPROVAL_PUBLIC_KEY_FILE": str(public_path),
        }):
            issuer = ApprovalTokenIssuer.from_environment()
            runtime = ApprovalService.from_environment(self.database)
            token = issuer.issue(
                action="agent.dispatch", resource_id="job-owner-key",
                approved_by="os-user:test-owner",
            )
            self.assertIsNotNone(runtime.verify_and_consume(
                token, action="agent.dispatch", resource_id="job-owner-key"
            ))

    def test_runtime_from_environment_fails_closed_without_public_key(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"QUDRON_APPROVAL_PUBLIC_KEY_FILE": ""}):
            self.assertIsNone(ApprovalService.from_environment(self.database))

if __name__ == "__main__":
    unittest.main()
