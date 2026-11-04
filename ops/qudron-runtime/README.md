# Qudron Runtime — restart-safe AI swarm worker

Qudron is a self-hosted operating layer for QudSystem. It separates ChatGPT's interactive control role from background task execution. Once deployed on an always-on host and configured with model endpoints, the worker can continue queued tasks independently of a ChatGPT conversation.

## Specialist swarm registry

The registry contains 30+ specialist roles covering research, evidence review, brand, copy, video, localization, SEO, sales, privacy, customer success, CV strategy/writing/ATS/fact review/QA, finance operations, payment evidence review, compliance, product, engineering, reliability, QA, data, and strategy.

These are **role-specialized AI workers**, not 30 separately hosted models or human employees. A job selects a team and runs a bounded sequential swarm. Configure QUDRON_MAX_SWARM_AGENTS (default 3, maximum 5) to cap calls, cost, and latency. Each specialist can be routed to a different OpenAI-compatible model profile.

## Model routing and cost control

Set the default LLM_BASE_URL / LLM_MODEL. Optional profiles:
- LLM_FAST_* for classification and routine low-cost tasks.
- LLM_BALANCED_* for drafting and analysis.
- LLM_REASONING_* for complex strategy, fact checking, and risk review.

If a profile is blank it falls back to the default endpoint. Configure price limits, request limits, provider keys, and usage alerts at the gateway/provider as well. Qudron does not assume external model calls are free and does not claim to force any model's maximum reasoning setting.

## Start with Docker

1. Copy this folder to an always-on server or computer.
2. Copy .env.example to .env and configure model endpoints. Do not commit secrets.
3. Run: docker compose up -d --build
4. Check: curl http://127.0.0.1:8765/health and docker compose logs -f qudron

The health port is bound to localhost by default. Put an authenticated reverse proxy or private VPN in front of any remote operational interface; do not expose the health service publicly.

Completed drafts are saved under reports/; durable task state and sanitized memory are in data/; logs are in logs/.

## Memory

SQLite memory now has:
- Short-term, project-scoped operational events with a 14-day default expiry.
- Long-term portfolio memory from weekly strategy reports.
- Retrieval of relevant project memory plus portfolio-wide strategy notes before the next swarm.
- Best-effort redaction of common email, Egyptian mobile, 14-digit national ID, payment-number, and API-token patterns before memory persistence.

Memory is deliberately not a customer-record database. Do not put CV source documents, identity documents, payment credentials, full card data, or sensitive personal information into strategic memory. Redaction is best-effort, not a substitute for minimization and access controls. A production customer workflow needs a separate encrypted customer-data store with strict tenant isolation and retention/deletion controls.

## Authenticated task intake API

After deployment, external orchestrators can enqueue approved internal draft/research jobs:
- `POST /jobs` with `Authorization: Bearer <QUDRON_API_TOKEN>`.
- `GET /jobs/{job_id}` with the same header to read a task status.
- Requests require a caller-supplied idempotency key; duplicate submissions return the existing job instead of creating duplicate work.
- Intake is allowlisted to internal research/draft/review task types. CV customer-data tasks, payment reconciliation, customer support with customer records, and financial actions are intentionally blocked from this generic endpoint.
- The default Docker mapping binds the port to localhost. Remote integrations must use HTTPS, a private network or authenticated reverse proxy, request logging, and secret rotation. Never expose this endpoint directly to the public internet.

## CVPen workflow design and payment safety

service_workflows.json defines a 12-stage CVPen order path from intake to aftercare. It is marked DESIGNED_NOT_CONNECTED. No real customer intake, WhatsApp channel, CV document generator, or payment provider is wired up by this configuration alone.

payment_guard.py provides a fail-closed HMAC callback verification primitive and unit tests for signature, order, amount, currency, settlement status, and transaction ID. It is not a provider-specific Paymob or Etisalat Cash adapter. Implement provider-specific signature rules only from current official documentation, then test against sandbox events before accepting live payment callbacks. SMS, screenshots, and user claims are not sufficient proof of settlement.

## Recurring jobs and operational boundaries

schedule.json has recurring research and draft jobs. The current scheduler uses UTC interval timing; the timezone field documents the business timezone but does not implement local wall-clock scheduling.

This runtime currently creates research, drafts, operational memory notes, and health information. It does not publish posts, send sales messages, accept customer payments, transfer money, issue refunds, or modify production customer accounts. Those actions require connected provider credentials, idempotency, audit logs, authorization checks, and end-to-end tests.

## Reliability and verification

- SQLite WAL queue with atomic job claiming.
- Bounded worker concurrency and capped exponential retry.
- Stale lease recovery after crashes/restarts.
- Idempotent recurring schedule enqueueing within an interval.
- Health/status endpoint, logs, durable artifact paths.
- Unit tests for concurrent claims, stale recovery, recurring idempotency, memory scoping/redaction, swarm planning, and payment callback verification.

Run tests locally:
```bash
python -m py_compile *.py
python -m unittest discover -s tests -v
docker compose build
```

A passing CI run proves the tested code/configuration passed those checks. It does not prove the runtime is deployed, external model keys work, connected channels receive real customer orders, or payments are settled. A production readiness gate must also include provider sandbox tests, end-to-end customer journeys, load tests, failure injection, restore tests, and live observability.
