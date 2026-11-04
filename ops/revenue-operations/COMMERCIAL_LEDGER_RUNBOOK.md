# Commercial Ledger — Internal Pilot Runbook

## Status
The consent-first SQLite ledger is an internal operational primitive, not a public customer API, payment gateway, CRM SaaS, or proof of a received payment.

Module: `commercial_ledger.py`
Tests: `tests/test_commercial_ledger.py`
Default database: `data/commercial.sqlite3`
Override: `QUDRON_COMMERCIAL_DB_PATH`

Required when storing a contact fingerprint: `QUDRON_CONTACT_HMAC_KEY` (32+ random characters). Generate securely and keep it in the private environment; never commit it. If the key is absent, contact fingerprinting fails closed.

## Safety properties
- A lead cannot be recorded unless explicit consent is true.
- Only approved supervised pilot service IDs are accepted.
- Contact information is converted to a keyed HMAC-SHA-256 fingerprint; raw email/phone is not stored. An unkeyed hash is not used because email/phone values are guessable.
- Free-text notes are rejected. Order scope must be one of the fixed service labels, preventing CV text or customer details from entering the ledger.
- An order's service must match the consented lead service. Pilot order amounts have a hard ceiling.
- Do not put CV contents, national IDs, payment credentials, full addresses, or sensitive notes in this ledger.
- Orders use integer minor currency units (e.g. EGP 249.00 = 24900 piastres).
- A pending order is not revenue.
- verify_payment is an internal trusted-call boundary. Its boolean flags must only be set after a PSP adapter independently verifies provider signature, order ID, amount, currency, transaction status and settlement. Never rely on SMS, screenshot or customer statement.
- The module intentionally has no HTTP route and cannot receive external payment callbacks.
- Order fulfilment is blocked until the order has moved to paid.

## Local synthetic smoke test
From this directory:
```bash
python -m unittest discover -s tests -p 'test_commercial_ledger.py' -v
```

Optional isolated manual exercise:
```bash
python - <<'PY'
import commercial_ledger as ledger
ledger.init_db()
lead = ledger.create_lead(service='content_pack', source='internal_test', consent=True, contact='test@example.invalid')
order = ledger.create_order(lead_id=lead['id'], service='content_pack', scope='Content pack', amount_minor=10000, currency='EGP')
print({'lead_id': lead['id'], 'order_id': order['id'], 'state': order['state']})
print(ledger.dashboard_snapshot())
PY
```

This creates a local test record only. It does not charge a customer or verify settlement.

## Required before production
1. Wrap trusted payment verification in a provider-specific adapter using current official PSP documentation.
2. Authenticate and authorize every future API caller; do not expose this module directly.
3. Encrypt and back up the database; define retention/deletion and access audit procedures.
4. Add tenant isolation before multi-client operation.
5. Add transactional outbox/idempotency for provider webhooks.
6. Reconcile settlement against provider API/report, not just callback signature.
7. Add independent security review and recovery test.

## Pilot policy
Use this ledger for internal tracking and synthetic dry-runs until the PSP adapter, security controls and owner-approved deployment are complete.