"""Fail-closed payment callback verification primitives.

This module validates an HMAC-authenticated JSON callback against a locally
created order. It is not a Paymob/Etisalat Cash adapter; provider-specific
signature construction must be implemented from the provider's current docs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

def verify_payment_callback(raw_body: bytes, signature: str, secret: str,
                            expected_order_id: str, expected_amount_minor: int,
                            expected_currency: str = "EGP") -> tuple[bool, str, dict[str, Any] | None]:
    if not secret or not signature:
        return False, "missing_signature_or_secret", None
    if not raw_body or len(raw_body) > 256_000:
        return False, "invalid_payload_size", None
    expected_signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    supplied = signature.strip()
    if supplied.lower().startswith("sha256="):
        supplied = supplied[7:]
    if not hmac.compare_digest(expected_signature.lower(), supplied.lower()):
        return False, "invalid_signature", None
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, "invalid_json", None
    if not isinstance(payload, dict):
        return False, "invalid_payload_shape", None
    if str(payload.get("order_id", "")) != str(expected_order_id):
        return False, "order_id_mismatch", payload
    try:
        amount = int(payload.get("amount_minor"))
    except (TypeError, ValueError):
        return False, "invalid_amount", payload
    if amount != int(expected_amount_minor):
        return False, "amount_mismatch", payload
    if str(payload.get("currency", "")).upper() != expected_currency.upper():
        return False, "currency_mismatch", payload
    if str(payload.get("status", "")).lower() not in {"success", "succeeded", "paid", "captured"}:
        return False, "payment_not_settled", payload
    transaction_id = str(payload.get("transaction_id", "")).strip()
    if not transaction_id:
        return False, "missing_transaction_id", payload
    return True, "verified_callback", payload
