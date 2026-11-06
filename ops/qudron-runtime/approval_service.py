"""Authenticated, one-time approval tokens for high-impact Qudron actions.

The secret belongs only to the owner-facing approval service. Agent workers
receive a scoped, short-lived token and can verify/consume it; a caller-supplied
name such as approved_by='owner' is never accepted as authorization.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any


class ApprovalError(RuntimeError):
    pass


def issue_approval_token(
    secret: str,
    *,
    action: str,
    resource_id: str,
    approved_by: str,
    ttl_seconds: int = 300,
) -> str:
    """Issue a scoped token. Call only after authenticating the human approver."""
    if not isinstance(secret, str) or len(secret) < 32:
        raise ApprovalError("Approval secret must contain at least 32 characters")
    if not all(isinstance(value, str) for value in (action, resource_id, approved_by)):
        raise ApprovalError("action, resource_id and approved_by must be strings")
    if not action.strip() or not resource_id.strip() or not approved_by.strip():
        raise ApprovalError("action, resource_id and approved_by are required")
    if len(action) > 120 or len(resource_id) > 500 or len(approved_by) > 160:
        raise ApprovalError("Approval scope exceeds the supported length")
    ttl = max(30, min(3600, int(ttl_seconds)))
    now = int(time.time())
    claims = {
        "v": 1,
        "action": action,
        "resource_id": resource_id,
        "approved_by": approved_by,
        "issued_at": now,
        "expires_at": now + ttl,
        "nonce": secrets.token_urlsafe(24),
    }
    raw = json.dumps(claims, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return encoded + "." + signature


class ApprovalService:
    def __init__(self, secret: str, database_path: str | Path):
        if not isinstance(secret, str) or len(secret) < 32:
            raise ApprovalError("Approval secret must contain at least 32 characters")
        self._secret = secret
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @classmethod
    def from_environment(cls, database_path: str | Path) -> "ApprovalService | None":
        import os

        secret = os.getenv("QUDRON_APPROVAL_SECRET", "").strip()
        if not secret:
            return None
        return cls(secret, database_path)

    def issue(
        self, *, action: str, resource_id: str, approved_by: str,
        ttl_seconds: int = 300,
    ) -> str:
        """Issue a token for an already-authenticated owner-facing UI."""
        return issue_approval_token(
            self._secret, action=action, resource_id=resource_id,
            approved_by=approved_by, ttl_seconds=ttl_seconds,
        )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _ensure_schema(self) -> None:
        db = self._connect()
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS consumed_approval_nonces (
                    nonce TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    consumed_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
            """)
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_approval_expiry ON consumed_approval_nonces(expires_at)"
            )
        finally:
            db.close()

    def verify_and_consume(
        self, token: str | None, *, action: str, resource_id: str,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        """Verify scope, expiry and signature, then atomically consume the nonce."""
        if not isinstance(token, str) or token.count(".") != 1:
            return None
        encoded, supplied_signature = token.split(".", 1)
        if not encoded or len(supplied_signature) != 64 or not supplied_signature.isascii():
            return None
        expected = hmac.new(
            self._secret.encode("utf-8"), encoded.encode("ascii", "ignore"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, supplied_signature):
            return None
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(claims, dict) or claims.get("v") != 1:
            return None
        current = time.time() if now is None else float(now)
        issued = claims.get("issued_at")
        expires = claims.get("expires_at")
        nonce = claims.get("nonce")
        actor = claims.get("approved_by")
        if (
            claims.get("action") != action
            or claims.get("resource_id") != resource_id
            or not isinstance(actor, str) or not actor.strip()
            or not isinstance(nonce, str) or len(nonce) < 16
            or not isinstance(issued, int) or not isinstance(expires, int)
            or issued > current + 30 or issued < current - 3600
            or expires <= current or expires > issued + 3600
        ):
            return None

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM consumed_approval_nonces WHERE expires_at<=?",
                (current,),
            )
            try:
                db.execute(
                    """INSERT INTO consumed_approval_nonces
                       (nonce,action,resource_id,approved_by,consumed_at,expires_at)
                       VALUES(?,?,?,?,?,?)""",
                    (nonce, action, resource_id, actor, current, float(expires)),
                )
            except sqlite3.IntegrityError:
                db.rollback()
                return None
            db.commit()
            return claims
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
