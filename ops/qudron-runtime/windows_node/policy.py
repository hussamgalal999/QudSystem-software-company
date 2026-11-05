"""Approval-signing helpers for the owner-controlled Windows worker."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any


def approval_resource(action: str, parameters: dict[str, Any]) -> str:
    if action == "windows.launch_app":
        return str(parameters.get("app_alias", ""))
    if action in {"windows.invoke_control", "windows.type_text"}:
        text_digest = ""
        if action == "windows.type_text":
            text_digest = hashlib.sha256(
                str(parameters.get("text", "")).encode("utf-8")
            ).hexdigest()
        return ":".join((
            str(parameters.get("process_id", "")),
            str(parameters.get("automation_id", "")),
            str(parameters.get("control_type", "")),
            text_digest,
        ))
    raise ValueError("This action does not require a write approval")


def sign_approval(
    secret: str, *, approver: str, action: str,
    resource: str, expires_at: int, nonce: str,
) -> dict[str, Any]:
    body = {
        "approver": approver,
        "action": action,
        "resource": resource,
        "expires_at": int(expires_at),
        "nonce": nonce,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    body["signature"] = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    return body


def verify_approval(
    secret: str, approval: Any, *, action: str, resource: str,
    now: int | None = None,
) -> tuple[bool, str]:
    if not isinstance(approval, dict):
        return False, "approval_required"
    approver = approval.get("approver")
    nonce = approval.get("nonce")
    signature = approval.get("signature")
    expiry = approval.get("expires_at")
    if not isinstance(approver, str) or not approver.strip():
        return False, "approver_missing"
    if not isinstance(nonce, str) or not 16 <= len(nonce) <= 160:
        return False, "approval_nonce_invalid"
    if type(expiry) is not int:
        return False, "approval_expiry_invalid"
    current = int(time.time()) if now is None else int(now)
    if expiry <= current or expiry > current + 600:
        return False, "approval_expired_or_too_long"
    body = {
        "approver": approver,
        "action": action,
        "resource": resource,
        "expires_at": expiry,
        "nonce": nonce,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    expected = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
        return False, "approval_signature_invalid"
    return True, approver
