"""One-time Ed25519 approval tokens with owner-only signing keys.

The owner-facing process holds the private key and issues scoped tokens.
Runtime workers receive only the public key and can verify/consume tokens,
but cannot mint new approvals if a worker is compromised.
"""
from __future__ import annotations

import base64
import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)


class ApprovalError(RuntimeError):
    pass


def _read_private_key(path: str | Path, passphrase: str | None = None) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(
            Path(path).read_bytes(),
            password=passphrase.encode("utf-8") if passphrase else None,
        )
    except (OSError, ValueError, TypeError) as exc:
        raise ApprovalError("Owner approval private key could not be loaded") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ApprovalError("Owner approval signing key must be Ed25519")
    return key


def _read_public_key(path: str | Path) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(Path(path).read_bytes())
    except (OSError, ValueError, TypeError) as exc:
        raise ApprovalError("Approval verification public key could not be loaded") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise ApprovalError("Approval verification key must be Ed25519")
    return key


def issue_approval_token(
    private_key: Ed25519PrivateKey,
    *,
    action: str,
    resource_id: str,
    approved_by: str,
    ttl_seconds: int = 300,
) -> str:
    """Issue a scoped token; call only after authenticating the human approver."""
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ApprovalError("An owner-only Ed25519 private signing key is required")
    if not all(isinstance(value, str) for value in (action, resource_id, approved_by)):
        raise ApprovalError("action, resource_id and approved_by must be strings")
    if not action.strip() or not resource_id.strip() or not approved_by.strip():
        raise ApprovalError("action, resource_id and approved_by are required")
    if len(action) > 120 or len(resource_id) > 500 or len(approved_by) > 160:
        raise ApprovalError("Approval scope exceeds the supported length")
    try:
        ttl = max(30, min(3600, int(ttl_seconds)))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ApprovalError("Approval TTL must be an integer") from exc
    now = int(time.time())
    claims = {
        "v": 2,
        "action": action,
        "resource_id": resource_id,
        "approved_by": approved_by,
        "issued_at": now,
        "expires_at": now + ttl,
        "nonce": secrets.token_urlsafe(24),
    }
    raw = json.dumps(claims, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    signature = private_key.sign(encoded.encode("ascii")).hex()
    return encoded + "." + signature


class ApprovalTokenIssuer:
    """Owner-side token issuer. Never construct this class inside agent workers."""

    def __init__(self, private_key: Ed25519PrivateKey):
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ApprovalError("An Ed25519 private signing key is required")
        self._private_key = private_key

    @classmethod
    def from_environment(cls) -> "ApprovalTokenIssuer":
        import os
        path = os.getenv("QUDRON_APPROVAL_PRIVATE_KEY_FILE", "").strip()
        if not path:
            raise ApprovalError("Owner approval private-key file is not configured")
        passphrase = os.getenv("QUDRON_APPROVAL_PRIVATE_KEY_PASSPHRASE", "")
        return cls(_read_private_key(path, passphrase))

    def issue(
        self, *, action: str, resource_id: str, approved_by: str,
        ttl_seconds: int = 300,
    ) -> str:
        return issue_approval_token(
            self._private_key, action=action, resource_id=resource_id,
            approved_by=approved_by, ttl_seconds=ttl_seconds,
        )


class ApprovalService:
    """Runtime-side verifier. It deliberately has no token-issuing method."""

    def __init__(self, public_key: Ed25519PublicKey, database_path: str | Path):
        if not isinstance(public_key, Ed25519PublicKey):
            raise ApprovalError("Runtime approval service accepts only an Ed25519 public key")
        self._public_key = public_key
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @classmethod
    def from_environment(cls, database_path: str | Path) -> "ApprovalService | None":
        import os
        path = os.getenv("QUDRON_APPROVAL_PUBLIC_KEY_FILE", "").strip()
        if not path:
            return None
        return cls(_read_public_key(path), database_path)

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
        """Verify signature, scope and expiry, then atomically consume the nonce."""
        if not isinstance(token, str) or token.count(".") != 1:
            return None
        encoded, supplied_signature = token.split(".", 1)
        if not encoded or len(supplied_signature) != 128 or not supplied_signature.isascii():
            return None
        try:
            signature = bytes.fromhex(supplied_signature)
            self._public_key.verify(signature, encoded.encode("ascii"))
            padded = encoded + "=" * (-len(encoded) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        except (InvalidSignature, ValueError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(claims, dict) or claims.get("v") != 2:
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
