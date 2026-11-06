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
        process_id = parameters.get("process_id")
        window_title = parameters.get("window_title")
        automation_id = parameters.get("automation_id")
        control_type = parameters.get("control_type")
        if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id <= 0:
            raise ValueError("UI approval requires a positive integer process_id")
        if not isinstance(window_title, str) or not window_title.strip():
            raise ValueError("UI approval requires an exact window_title")
        if not isinstance(automation_id, str) or not automation_id.strip():
            raise ValueError("UI approval requires an automation_id")
        if not isinstance(control_type, str) or not control_type.strip():
            raise ValueError("UI approval requires a control_type")
        text_digest = ""
        if action == "windows.type_text":
            text_value = parameters.get("text")
            if not isinstance(text_value, str) or len(text_value) > 4000:
                raise ValueError("UI text approval requires bounded string content")
            text_digest = hashlib.sha256(text_value.encode("utf-8")).hexdigest()
        return ":".join((
            str(process_id), window_title, automation_id,
            control_type, text_digest,
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
