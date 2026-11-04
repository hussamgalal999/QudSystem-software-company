"""Minimal consent-first commercial ledger for QudSystem pilot services.

Stores operational references, not CV files, message bodies, payment credentials,
or raw customer contact details. Payment verification is deliberately explicit:
a screenshot, SMS, or client assertion is never sufficient evidence.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv(
    "QUDRON_COMMERCIAL_DB_PATH",
    str(APP_DIR / "data" / "commercial.sqlite3"),
))
CURRENCIES = {"EGP", "USD"}
LEAD_STATES = {"new", "qualified", "proposal", "converted", "closed_lost"}
ORDER_STATES = {"draft", "awaiting_payment", "paid", "in_fulfilment", "delivered", "accepted", "cancelled", "refunded"}
ALLOWED_SERVICES = {"cvpen_review", "cvpen_rewrite", "content_pack", "workflow_assessment", "market_research", "software_discovery"}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=20000")
    return db


def init_db() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS leads (
          id TEXT PRIMARY KEY,
          service TEXT NOT NULL,
          source TEXT NOT NULL,
          consent_at TEXT NOT NULL,
          contact_fingerprint TEXT,
          state TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
          id TEXT PRIMARY KEY,
          lead_id TEXT NOT NULL REFERENCES leads(id),
          service TEXT NOT NULL,
          scope TEXT NOT NULL,
          amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
          currency TEXT NOT NULL,
          state TEXT NOT NULL,
          payment_provider TEXT,
          payment_reference TEXT UNIQUE,
          verified_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS commercial_events (
          id TEXT PRIMARY KEY,
          entity_type TEXT NOT NULL,
          entity_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          actor TEXT NOT NULL,
          details TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_leads_state ON leads(state, updated_at);
        CREATE INDEX IF NOT EXISTS idx_orders_state ON orders(state, updated_at);
        CREATE INDEX IF NOT EXISTS idx_events_entity ON commercial_events(entity_type, entity_id, created_at);
        """)


def _event(db: sqlite3.Connection, entity_type: str, entity_id: str,
           event_type: str, actor: str, details: str = "") -> None:
    db.execute(
        "INSERT INTO commercial_events VALUES(?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, entity_type, entity_id, event_type, actor[:80],
         details[:500], now_utc()),
    )


def _clean(value: Any, field: str, limit: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > limit:
        raise ValueError(f"{field} is required and must be <= {limit} characters")
    return result


def fingerprint_contact(contact: str) -> str:
    """Return a one-way fingerprint; raw contact values are never persisted."""
    normalized = re.sub(r"\s+", "", str(contact or "")).casefold()
    if not normalized or len(normalized) > 254:
        raise ValueError("contact must be a non-empty email/phone reference")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def create_lead(*, service: str, source: str, consent: bool,
                contact: str = "", notes: str = "", actor: str = "owner") -> dict[str, Any]:
    if consent is not True:
        raise ValueError("explicit consent is required before recording a lead")
    service = _clean(service, "service", 60)
    if service not in ALLOWED_SERVICES:
        raise ValueError("service is not in the approved pilot catalogue")
    source = _clean(source, "source", 80)
    if len(str(notes)) > 500:
        raise ValueError("notes must be <= 500 characters; do not store CV or sensitive data")
    contact_hash = fingerprint_contact(contact) if contact else None
    lead_id, stamp = uuid.uuid4().hex, now_utc()
    with connect() as db:
        db.execute(
            "INSERT INTO leads VALUES(?,?,?,?,?,?,?,?,?)",
            (lead_id, service, source, stamp, contact_hash, "new",
             str(notes).strip(), stamp, stamp),
        )
        _event(db, "lead", lead_id, "lead_created_with_consent", actor,
               f"service={service};source={source}")
    return get_lead(lead_id)


def get_lead(lead_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if row is None:
        raise KeyError("lead_not_found")
    return dict(row)


def set_lead_state(lead_id: str, state: str, *, actor: str = "owner") -> dict[str, Any]:
    if state not in LEAD_STATES:
        raise ValueError("invalid lead state")
    with connect() as db:
        row = db.execute("SELECT state FROM leads WHERE id=?", (lead_id,)).fetchone()
        if row is None:
            raise KeyError("lead_not_found")
        db.execute("UPDATE leads SET state=?,updated_at=? WHERE id=?",
                   (state, now_utc(), lead_id))
        _event(db, "lead", lead_id, "state_changed", actor, f"{row['state']}->{state}")
    return get_lead(lead_id)


def create_order(*, lead_id: str, service: str, scope: str,
                 amount_minor: int, currency: str = "EGP",
                 actor: str = "owner") -> dict[str, Any]:
    service = _clean(service, "service", 60)
    scope = _clean(scope, "scope", 1000)
    if service not in ALLOWED_SERVICES:
        raise ValueError("service is not in the approved pilot catalogue")
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
        raise ValueError("amount_minor must be a positive integer in the smallest currency unit")
    currency = str(currency).upper()
    if currency not in CURRENCIES:
        raise ValueError("unsupported currency")
    order_id, stamp = uuid.uuid4().hex, now_utc()
    with connect() as db:
        lead = db.execute("SELECT id FROM leads WHERE id=?", (lead_id,)).fetchone()
        if lead is None:
            raise KeyError("lead_not_found")
        db.execute(
            "INSERT INTO orders VALUES(?,?,?,?,?,?,?,NULL,NULL,NULL,?,?)",
            (order_id, lead_id, service, scope, amount_minor, currency,
             "awaiting_payment", stamp, stamp),
        )
        _event(db, "order", order_id, "order_created", actor,
               f"service={service};amount_minor={amount_minor};currency={currency}")
    return get_order(order_id)


def get_order(order_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if row is None:
        raise KeyError("order_not_found")
    return dict(row)


def verify_payment(order_id: str, *, provider: str, provider_reference: str,
                   verified_amount_minor: int, verified_currency: str,
                   signature_verified: bool, settlement_confirmed: bool,
                   verifier: str) -> dict[str, Any]:
    """Mark paid only after provider-authenticated amount/currency and settlement checks."""
    provider = _clean(provider, "provider", 60)
    provider_reference = _clean(provider_reference, "provider_reference", 160)
    verifier = _clean(verifier, "verifier", 80)
    if signature_verified is not True or settlement_confirmed is not True:
        raise ValueError("provider signature and settlement must both be verified")
    if isinstance(verified_amount_minor, bool) or not isinstance(verified_amount_minor, int):
        raise ValueError("verified amount must be an integer minor-unit amount")
    currency = str(verified_currency).upper()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise KeyError("order_not_found")
        if row["state"] not in {"awaiting_payment"}:
            raise ValueError("order is not awaiting payment")
        if verified_amount_minor != row["amount_minor"] or currency != row["currency"]:
            raise ValueError("verified amount/currency does not match the order")
        stamp = now_utc()
        db.execute(
            """UPDATE orders SET state='paid',payment_provider=?,payment_reference=?,
               verified_at=?,updated_at=? WHERE id=?""",
            (provider, provider_reference, stamp, stamp, order_id),
        )
        _event(db, "order", order_id, "payment_verified_and_settled", verifier,
               f"provider={provider};reference={provider_reference}")
    return get_order(order_id)


def transition_order(order_id: str, state: str, *, actor: str = "owner") -> dict[str, Any]:
    allowed = {
        "paid": {"in_fulfilment", "refunded"},
        "in_fulfilment": {"delivered", "refunded"},
        "delivered": {"accepted", "refunded"},
        "awaiting_payment": {"cancelled"},
    }
    if state not in ORDER_STATES:
        raise ValueError("invalid order state")
    with connect() as db:
        row = db.execute("SELECT state FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise KeyError("order_not_found")
        previous = row["state"]
        if state not in allowed.get(previous, set()):
            raise ValueError(f"invalid order transition: {previous}->{state}")
        db.execute("UPDATE orders SET state=?,updated_at=? WHERE id=?",
                   (state, now_utc(), order_id))
        _event(db, "order", order_id, "state_changed", actor, f"{previous}->{state}")
    return get_order(order_id)


def dashboard_snapshot() -> dict[str, Any]:
    with connect() as db:
        leads = db.execute("SELECT state,COUNT(*) count FROM leads GROUP BY state").fetchall()
        orders = db.execute("SELECT state,COUNT(*) count FROM orders GROUP BY state").fetchall()
        paid = db.execute(
            """SELECT currency,SUM(amount_minor) total_minor,COUNT(*) count
               FROM orders WHERE state IN ('paid','in_fulfilment','delivered','accepted')
               GROUP BY currency"""
        ).fetchall()
    return {
        "leads": {row["state"]: row["count"] for row in leads},
        "orders": {row["state"]: row["count"] for row in orders},
        "verified_settlements": {
            row["currency"]: {"total_minor": row["total_minor"], "orders": row["count"]}
            for row in paid
        },
        "revenue_rule": "Only provider-verified settled orders are counted; proposals and pending payments are excluded.",
    }
