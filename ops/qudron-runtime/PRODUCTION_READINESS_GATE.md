# Qudron Production Readiness Gate — Operator Checklist
Status: pre-production gate. Passing CI is not production deployment approval.

## A. Credentials and ownership
- [ ] Create a dedicated least-privilege runtime identity.
- [ ] Store model, API, Telegram and contact-HMAC secrets in the host secret manager.
- [ ] Enable MFA on GitHub, hosting, model provider and Telegram owner accounts.
- [ ] Set provider-side hard spend caps and usage alerts.
- [ ] Rotate any credential ever pasted into chat, logs, screenshots or source control.

## B. Runtime deployment
- [ ] Choose and document an always-on Docker host with persistent encrypted storage.
- [ ] Configure health checks, restart policy, resource limits and disk alerts.
- [ ] Bind admin/health endpoints to localhost or private network; use VPN/authenticated reverse proxy for remote access.
- [ ] Confirm database volume persistence and backup/restore procedure.
- [ ] Run migrations and verify clean startup from an empty database.
- [ ] Test restart during pending, running and retry_wait jobs.

## C. Model and cost safety
- [ ] Configure only approved provider endpoints and model IDs.
- [ ] Disable anonymous/keyless providers for all customer data.
- [ ] Configure exact input/output prices for each enabled profile.
- [ ] Configure daily, monthly and per-CVPen-order budgets.
- [ ] Test concurrent reservation limits and crash/timeout reservation recovery.
- [ ] Confirm provider-side caps independently.
- [ ] Test that missing budget/prices fail closed.

## D. Customer-data boundary
- [ ] No customer file upload until a private authenticated intake and tenant-isolated encrypted storage exist.
- [ ] Malware scanning, content-type/size checks and safe document parsing tested.
- [ ] Retention and deletion workflow tested including backups.
- [ ] Logs, traces, agent memory and analytics contain no raw CVs or contact details.
- [ ] Provider data retention/training terms reviewed before transmitting personal data.
- [ ] Human reviewer and incident response contact assigned.

## E. External actions
- [ ] Telegram allowlist contains only the owner's numeric chat ID; test unauthorized chat rejection.
- [ ] Telegram commands cannot send customer messages, publish posts, spend money or alter production.
- [ ] Social publishing remains disabled until account scopes and approval records are tested.
- [ ] Payment remains manual until a provider-specific signed webhook adapter, idempotency, amount/currency/order checks and settlement reconciliation pass sandbox tests.
- [ ] No public endpoint without authentication, authorization, rate limits and audit logs.

## F. Release and rollback
- [ ] All CI workflows pass on the exact release commit.
- [ ] Independent code/security review completed.
- [ ] Threat model and abuse cases reviewed.
- [ ] Synthetic end-to-end test passes without real customer data.
- [ ] Backup restore and rollback rehearsed.
- [ ] Owner explicitly approves deployment and customer pilot.

## Current decision
Do not deploy this branch as a public multi-tenant service yet. Current CI validates code and configuration checks; it does not prove that secrets, host, backups, provider billing, privacy processes, secure file storage, or production integrations are configured. Start with a private, synthetic-data runtime pilot after the owner completes sections A–C and the runtime deployment gates.