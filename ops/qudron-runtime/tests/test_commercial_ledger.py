import os
import tempfile
import unittest
from pathlib import Path

import commercial_ledger as ledger


class CommercialLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = ledger.DB_PATH
        self.old_key = os.environ.get("QUDRON_CONTACT_HMAC_KEY")
        os.environ["QUDRON_CONTACT_HMAC_KEY"] = "test-key-that-is-at-least-32-characters-long"
        ledger.DB_PATH = Path(self.temp.name) / "commercial.sqlite3"
        ledger.init_db()

    def tearDown(self):
        ledger.DB_PATH = self.old_path
        if self.old_key is None:
            os.environ.pop("QUDRON_CONTACT_HMAC_KEY", None)
        else:
            os.environ["QUDRON_CONTACT_HMAC_KEY"] = self.old_key
        self.temp.cleanup()

    def lead(self, **kwargs):
        values = {"service": "cvpen_review", "source": "website_form",
                  "consent": True, "contact": "Customer@example.com"}
        values.update(kwargs)
        return ledger.create_lead(**values)

    def test_consent_is_required(self):
        with self.assertRaisesRegex(ValueError, "consent"):
            self.lead(consent=False)

    def test_contact_is_not_stored_raw(self):
        lead = self.lead()
        self.assertNotIn("Customer@example.com", str(lead))
        self.assertEqual(len(lead["contact_fingerprint"]), 64)

    def test_contact_fingerprint_requires_keyed_hmac(self):
        os.environ.pop("QUDRON_CONTACT_HMAC_KEY", None)
        with self.assertRaisesRegex(RuntimeError, "HMAC_KEY"):
            ledger.fingerprint_contact("someone@example.com")

    def test_raw_free_text_notes_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "free-text notes"):
            self.lead(notes="Candidate CV details")

    def test_unapproved_service_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "approved"):
            self.lead(service="autonomous_whatsapp_bot")

    def test_order_scope_is_fixed_and_service_must_match_lead(self):
        lead = self.lead()
        with self.assertRaisesRegex(ValueError, "approved service label"):
            ledger.create_order(lead_id=lead["id"], service="cvpen_review",
                                scope="Candidate email is private", amount_minor=1000)
        with self.assertRaisesRegex(ValueError, "must match"):
            ledger.create_order(lead_id=lead["id"], service="content_pack",
                                scope="Content pack", amount_minor=1000)

    def test_payment_requires_signature_and_settlement(self):
        lead = self.lead()
        order = ledger.create_order(lead_id=lead["id"], service="cvpen_review",
                                    scope="CV review", amount_minor=24900)
        with self.assertRaisesRegex(ValueError, "signature and settlement"):
            ledger.verify_payment(order["id"], provider="PSP", provider_reference="txn-1",
                                  verified_amount_minor=24900, verified_currency="EGP",
                                  signature_verified=False, settlement_confirmed=True,
                                  verifier="owner")
        self.assertEqual(ledger.get_order(order["id"])["state"], "awaiting_payment")

    def test_amount_currency_must_match(self):
        lead = self.lead()
        order = ledger.create_order(lead_id=lead["id"], service="cvpen_review",
                                    scope="CV review", amount_minor=24900)
        with self.assertRaisesRegex(ValueError, "does not match"):
            ledger.verify_payment(order["id"], provider="PSP", provider_reference="txn-2",
                                  verified_amount_minor=100, verified_currency="EGP",
                                  signature_verified=True, settlement_confirmed=True,
                                  verifier="owner")

    def test_happy_path_only_counts_verified_settlement(self):
        lead = self.lead()
        order = ledger.create_order(lead_id=lead["id"], service="cvpen_review",
                                    scope="CV review", amount_minor=24900)
        before = ledger.dashboard_snapshot()
        self.assertEqual(before["verified_settlements"], {})
        paid = ledger.verify_payment(order["id"], provider="sandbox",
                                     provider_reference="sandbox-txn-3",
                                     verified_amount_minor=24900, verified_currency="EGP",
                                     signature_verified=True, settlement_confirmed=True,
                                     verifier="sandbox-test")
        self.assertEqual(paid["state"], "paid")
        snap = ledger.dashboard_snapshot()
        self.assertEqual(snap["verified_settlements"]["EGP"]["total_minor"], 24900)
        self.assertEqual(snap["verified_settlements"]["EGP"]["orders"], 1)

    def test_duplicate_provider_reference_is_rejected(self):
        lead = self.lead()
        one = ledger.create_order(lead_id=lead["id"], service="cvpen_review",
                                  scope="CV review", amount_minor=1000)
        two = ledger.create_order(lead_id=lead["id"], service="cvpen_review",
                                  scope="CV review", amount_minor=1000)
        for order in (one, two):
            if order is one:
                ledger.verify_payment(order["id"], provider="sandbox", provider_reference="same-ref",
                                      verified_amount_minor=1000, verified_currency="EGP",
                                      signature_verified=True, settlement_confirmed=True,
                                      verifier="test")
            else:
                with self.assertRaises(Exception):
                    ledger.verify_payment(order["id"], provider="sandbox", provider_reference="same-ref",
                                          verified_amount_minor=1000, verified_currency="EGP",
                                          signature_verified=True, settlement_confirmed=True,
                                          verifier="test")

    def test_order_state_machine_prevents_unpaid_fulfilment(self):
        lead = self.lead()
        order = ledger.create_order(lead_id=lead["id"], service="cvpen_review",
                                    scope="CV review", amount_minor=1000)
        with self.assertRaisesRegex(ValueError, "invalid order transition"):
            ledger.transition_order(order["id"], "in_fulfilment")


if __name__ == "__main__":
    unittest.main()
