import hashlib
import hmac
import json
import unittest

from payment_guard import verify_payment_callback

SECRET = "test-webhook-secret"

def signed(payload):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, signature

class PaymentGuardTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "order_id":"CVP-1001", "amount_minor":50000, "currency":"EGP",
            "status":"paid", "transaction_id":"TX-9001"
        }

    def verify(self, payload=None, signature_override=None, secret=SECRET, body_override=None):
        raw, signature = signed(payload or self.payload)
        return verify_payment_callback(
            body_override if body_override is not None else raw,
            signature_override if signature_override is not None else signature,
            secret, "CVP-1001", 50000, "EGP"
        )

    def test_valid_signed_payment(self):
        ok, reason, parsed = self.verify()
        self.assertTrue(ok)
        self.assertEqual(reason, "verified_callback")
        self.assertEqual(parsed["transaction_id"], "TX-9001")

    def test_bad_signature_rejected(self):
        ok, reason, _ = self.verify(signature_override="bad")
        self.assertFalse(ok)
        self.assertEqual(reason, "invalid_signature")

    def test_order_amount_currency_status_and_transaction_are_required(self):
        cases = [
            ({"order_id":"OTHER"}, "order_id_mismatch"),
            ({"amount_minor":49900}, "amount_mismatch"),
            ({"currency":"USD"}, "currency_mismatch"),
            ({"status":"pending"}, "payment_not_settled"),
            ({"transaction_id":""}, "missing_transaction_id"),
        ]
        for change, expected in cases:
            payload = dict(self.payload)
            payload.update(change)
            ok, reason, _ = self.verify(payload=payload)
            self.assertFalse(ok)
            self.assertEqual(reason, expected)

    def test_sms_text_or_screenshot_is_not_a_callback(self):
        ok, reason, _ = self.verify(body_override=b"Your wallet received 500 EGP")
        self.assertFalse(ok)
        self.assertEqual(reason, "invalid_signature")

    def test_missing_secret_fails_closed(self):
        ok, reason, _ = self.verify(secret="")
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_signature_or_secret")

    def test_oversized_callback_rejected(self):
        ok, reason, _ = self.verify(body_override=b"x" * 256001)
        self.assertFalse(ok)
        self.assertEqual(reason, "invalid_payload_size")

if __name__ == "__main__":
    unittest.main()
