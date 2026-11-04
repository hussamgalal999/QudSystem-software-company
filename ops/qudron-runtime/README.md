# Qudron Runtime — restart-safe AI swarm worker

Qudron is a self-hosted operating layer for QudSystem. It separates ChatGPT's interactive control role from background task execution. Once deployed on an always-on host and configured with model endpoints, the worker can continue queued tasks independently of a ChatGPT conversation.

## Specialist swarm registry

The registry contains 36 specialist roles covering research, evidence review, brand, copy, video, localization, SEO, sales, privacy, customer success, CV strategy/writing/ATS/fact review/QA, finance operations, payment evidence review, compliance, product, engineering, reliability, QA, data, and strategy.

These are **role-specialized AI workers**, not separately hosted models or human employees. A job selects a team; the producer runs first, independent reviewers execute concurrently within a bounded fan-out, then a finalizer receives the accumulated review notes. Routine jobs remain capped at five stages by default. CVPen paid-CV creation has a dedicated ten-agent team: one writer, eight independent reviews, and a final QA agent. Configure QUDRON_MAX_SWARM_AGENTS (default 5, maximum 5) to cap routine calls. CVPen uses QUDRON_MAX_CVPEN_AGENTS (default 10, maximum 10) and QUDRON_MAX_PARALLEL_REVIEWS (default 8). This increases per-order model cost, so CVPen creation fails closed until QUDRON_CVPEN_JOB_BUDGET_USD and exact input/output model prices are configured. Each specialist can be routed to a different OpenAI-compatible model profile.

## Model routing and cost control

Set the default LLM_BASE_URL / LLM_MODEL. Optional profiles:
- LLM_FAST_* for classification and routine low-cost tasks.
- LLM_BALANCED_* for drafting and analysis.
- LLM_REASONING_* for complex strategy, fact checking, and risk review.

If a profile is blank it falls back to the default endpoint. Configure price limits, request limits, provider keys, and usage alerts at the gateway/provider as well. Qudron does not assume external model calls are free and does not claim to force any model's maximum reasoning setting.

## Token and model-spend controls

- Every model call sets a configurable output token ceiling (`QUDRON_MAX_OUTPUT_TOKENS`, default 1,200; hard range 128–4,000).
- Task input, prior-stage context and memory are bounded before being sent to providers.
- Model usage is recorded by job, specialist, profile and model. The authenticated `GET /usage` endpoint reports daily/monthly prompt tokens, completion tokens, total tokens, calls and known USD cost.
- Configure exact input/output rates per million tokens for each profile. When rates are absent, token counts can still be recorded, but cost is reported as unknown.
- Optional daily/monthly USD budgets reserve a conservative estimated amount before concurrent API requests. CVPen creation additionally requires a per-order USD cap; the sum of provider usage and outstanding reservations for that order cannot exceed it.  Budgets fail closed if profile prices are not configured or the next reservation would exceed a cap. Abandoned reservations are reclaimed after a crash/timeout using a bounded TTL. Provider dashboards should still have their own spend limits; this local estimate is not a billing guarantee.
- Fast/Balanced/Reasoning routing keeps routine work bounded to five specialists. CVPen uses ten specialists only for the CV-creation task and requires a per-order spend cap plus configured price rates before the first model request.

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
- `GET /jobs/{job_id}` with the same header to read a task status without disclosing internal filesystem paths.
- `GET /jobs/{job_id}/result` with the same header to fetch a completed, size-limited Markdown artifact from inside the configured reports directory; path traversal and outside paths are rejected.
- Requests require a caller-supplied idempotency key; duplicate submissions return the existing job instead of creating duplicate work.
- Intake is allowlisted to internal research/draft/review task types. CV customer-data tasks, payment reconciliation, customer support with customer records, and financial actions are intentionally blocked from this generic endpoint.
- The default Docker mapping binds the port to localhost. Remote integrations must use HTTPS, a private network or authenticated reverse proxy, request logging, and secret rotation. Never expose this endpoint directly to the public internet.

## Failure triage and queue validation

- Malformed schedules, duplicate schedule IDs, unsupported task types, missing titles/prompts, and invalid intervals are skipped safely and logged rather than crashing the scheduler.
- SQLite connections are closed when their context exits.
- After a job reaches its terminal retry limit, Qudron creates one idempotent `incident_triage` task for the reliability/QA/evidence swarm. The triage job is read-only: it produces a root-cause hypothesis, a proposed correction, a regression test, and a rollback note. It does not repair production systems automatically.
- Incident-triage failures do not create recursive incident jobs.

## CVPen workflow design and payment safety

service_workflows.json defines a 12-stage CVPen order path from intake to aftercare. It is marked DESIGNED_NOT_CONNECTED. No real customer intake, WhatsApp channel, CV document generator, or payment provider is wired up by this configuration alone.

payment_guard.py provides a fail-closed HMAC callback verification primitive and unit tests for signature, order, amount, currency, settlement status, and transaction ID. It is not a provider-specific Paymob or Etisalat Cash adapter. Implement provider-specific signature rules only from current official documentation, then test against sandbox events before accepting live payment callbacks. SMS, screenshots, and user claims are not sufficient proof of settlement.

## Recurring jobs and operational boundaries

schedule.json has recurring research and draft jobs. Local schedules now support IANA timezones, wall-clock `at_local` times, fixed weekdays, and anchored every-N-day intervals. The QudSystem schedule is configured for `Africa/Cairo`. After downtime, the scheduler enqueues only the latest missed local slot rather than flooding the queue with every missed run. Legacy `every_minutes` schedules remain supported. Validate local schedules with the included tests before changing their cadence.

This runtime currently creates research, drafts, operational memory notes, and health information. It does not publish posts, send sales messages, accept customer payments, transfer money, issue refunds, or modify production customer accounts. Those actions require connected provider credentials, idempotency, audit logs, authorization checks, and end-to-end tests.

## Reliability and verification

- SQLite WAL queue with atomic job claiming.
- Bounded worker concurrency and capped exponential retry.
- Stale lease recovery after crashes/restarts, plus heartbeat renewal while long model calls are active.
- Completion and failure writes are guarded by current lease ownership, preventing a stale worker from overwriting a job reclaimed by another worker.
- SQLite connection context managers close handles after transactions.
- Idempotent recurring schedule enqueueing for interval-based and local wall-clock schedules.
- IANA timezone, local time, weekday, anchored every-N-day, and bounded catch-up scheduling tests.
- Health/status endpoint, logs, durable artifact paths.
- Unit tests for concurrent claims, stale recovery, recurring idempotency, memory scoping/redaction, swarm planning, and payment callback verification.

### CVPen swarm test coverage

The CVPen creation team is deliberately separate from the routine swarm cap:
- One producer creates the evidence-based draft.
- Eight independent reviewer calls run concurrently (bounded by `QUDRON_MAX_PARALLEL_REVIEWS`).
- One final QA agent receives all eight review notes before producing the final result.
- The test suite checks the exact ten-agent team composition, verifies reviewers reach a synchronization barrier concurrently, and verifies all eight notes reach the finalizer.
- Per-order model reservations are tested to fail closed if the cap is absent and to stop concurrent agents when the order budget would be exceeded.

These checks validate orchestration logic only. They do not validate resume quality for every real customer, render a DOCX/PDF, connect a live checkout, or prove the service is deployed.

Run tests locally:
```bash
python -m py_compile *.py
python -m unittest discover -s tests -v
docker compose build
```

A passing CI run proves the tested code/configuration passed those checks. It does not prove the runtime is deployed, external model keys work, connected channels receive real customer orders, or payments are settled. A production readiness gate must also include provider sandbox tests, end-to-end customer journeys, load tests, failure injection, restore tests, and live observability.


### Release gate for CVPen's ten-agent swarm

A CVPen creation task is intentionally blocked until `QUDRON_CVPEN_JOB_BUDGET_USD` and the exact token price rates for every model profile used by its agents are configured. The eight reviewer calls are parallel, so the shared SQLite reservation transaction accounts for all in-flight calls against the same order cap. Keep the PR in draft until the complete CI workflow passes on the latest head SHA; a prior green run does not validate later commits.
