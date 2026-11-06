# Qudron Runtime — restart-safe AI swarm worker

**Hosting decision:** Before choosing a host, review [HOSTING_DECISION_2026-11-04.md](./HOSTING_DECISION_2026-11-04.md). The current Python/Docker runtime needs a Docker host; the Cloudflare zero-monthly-cost route requires a separate event-driven Worker implementation and is not deployed yet.

Qudron is a self-hosted operating layer for QudSystem. It separates ChatGPT's interactive control role from background task execution. Once deployed on an always-on host and configured with model endpoints, the worker can continue queued tasks independently of a ChatGPT conversation.

## Specialist swarm registry

The registry currently contains 48 role identities across 31 specialist teams. Eight five-role waves cover the original 40-role programme; eight additional specialists remain in dedicated Android, provider-access, external-dispatch, platform-operations and memory/continuity teams.

These are **role-specialized AI workers**, not separately hosted models or human employees. A job selects its registered team; the producer runs first, independent reviewers execute within bounded fan-out, and the finalizer receives available worker outputs and evidence.

`QUDRON_MAX_ROLE_ASSIGNMENTS_PER_TASK` is the global ceiling on planned role assignments (default 10,000; maximum 10,000). This is **not** a promise of 10,000 live model calls. Actual upstream concurrency remains bounded by `QUDRON_MAX_CONCURRENT_MODEL_CALLS` (default 16; hard maximum 32), provider RPM/TPM quotas, spend budgets and host resources. `QUDRON_MAX_PARALLEL_REVIEWS` separately bounds reviewer fan-out. For backward compatibility, setting `QUDRON_MAX_SWARM_AGENTS` or `QUDRON_MAX_CVPEN_AGENTS` applies an additional per-task cap; the smaller of that legacy cap and the global ceiling is used. Leave the legacy variables unset to use the registry's full team composition.

CVPen paid-CV creation has a dedicated ten-role team: one writer, eight independent reviews, and one final QA role. It fails closed until `QUDRON_CVPEN_JOB_BUDGET_USD` and exact input/output model prices are configured. Each specialist can be routed to a different OpenAI-compatible model profile. Queue throughput defaults to eight queue workers; these are scheduling limits, not guaranteed throughput. Keep each task's team specialist-specific rather than adding generic reviewers that do not improve the result.
## Model routing and cost control

Set the default LLM_BASE_URL / LLM_MODEL. Optional profiles:
- LLM_FAST_* for classification and routine low-cost tasks.
- LLM_BALANCED_* for drafting and analysis.
- LLM_REASONING_* for complex strategy, fact checking, and risk review.

If a profile is blank it falls back to the default endpoint. Configure price limits, request limits, provider keys, and usage alerts at the gateway/provider as well. Qudron does not assume external model calls are free and does not claim to force any model's maximum reasoning setting.

## Token and model-spend controls

**Fail-closed by default:** generic model calls require a positive daily or monthly USD budget. Anonymous FreeLLM routes may use zero provider-price estimates only when no upstream provider keys are present; the runtime also limits these routes to public, non-sensitive work and omits private Qudron memory. All keyed/custom endpoints require exact input/output prices, and zero-price keyed endpoints are blocked unless explicitly allowed after verification. `QUDRON_REQUIRE_MODEL_BUDGET=false` is an isolated-development escape hatch only. CVPen additionally requires its own per-order USD cap. Enable provider-side hard spending limits as a second independent control: local token estimates and usage reports cannot guarantee the final provider invoice ceiling.


- Every model call sets a configurable output token ceiling (`QUDRON_MAX_OUTPUT_TOKENS`, default 1,200; hard range 128–4,000).
- Task input, prior-stage context and memory are bounded before being sent to providers.
- Model usage is recorded by job, specialist, profile and model. The authenticated `GET /usage` endpoint reports daily/monthly prompt tokens, completion tokens, total tokens, calls and known USD cost.
- Configure exact input/output rates per million tokens for each keyed/custom profile. Anonymous FreeLLM routes default to zero provider-price estimates while the daily cap and provider quotas remain active; cost is reported as an estimate, not an invoice guarantee.
- Optional daily/monthly USD budgets reserve a conservative estimated amount before concurrent API requests. CVPen creation additionally requires a per-order USD cap; the sum of provider usage and outstanding reservations for that order cannot exceed it.  Budgets fail closed if profile prices are not configured or the next reservation would exceed a cap. Abandoned reservations are reclaimed after a crash/timeout using a bounded TTL. Provider dashboards should still have their own spend limits; this local estimate is not a billing guarantee.
- Fast/Balanced/Reasoning routing keeps routine work bounded to five specialists. CVPen uses ten specialists only for the CV-creation task and requires a per-order spend cap plus configured price rates before the first model request.

## Start with Docker

1. Copy this folder to an always-on server or computer.
2. Copy .env.example to .env and configure model endpoints. Do not commit secrets.
3. Run: docker compose up -d --build
4. Check: curl http://127.0.0.1:8765/health and docker compose logs -f qudron

The health port is bound to localhost by default. Put an authenticated reverse proxy or private VPN in front of any remote operational interface; do not expose the health service publicly.

Completed drafts are saved under reports/; durable task state and sanitized memory are in data/; logs are in logs/.

## Owner command channel — Telegram (optional)

An owner-only Telegram long-polling gateway is included as an optional Compose profile. It opens no inbound webhook or public port. It supports:
- /help — command guide.
- /status — queue counts and a short latest-jobs summary.
- /usage — daily/monthly calls, tokens and known model cost.
- /task <request> — enqueue an internal research task using Qudron's authenticated API.

Setup:
1. Create a bot with Telegram's official BotFather and keep its token secret.
2. Obtain your own numeric chat ID using a trusted Telegram bot/tool; add only your ID to TELEGRAM_OWNER_CHAT_IDS.
3. Set TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_CHAT_IDS in the private .env file. Keep QUDRON_API_TOKEN configured with a random 32+ character secret.
4. Start the runtime and gateway: docker compose up -d --build qudron, then docker compose --profile telegram up -d --build telegram-gateway.
5. Inspect only operational logs: docker compose logs --tail=100 telegram-gateway.

The gateway ignores messages from non-allowlisted chat IDs. It accepts text commands only. Task submissions use Telegram update IDs as idempotency keys, so replayed updates after a restart do not create duplicate jobs. It does not send customer messages, publish content, access local files, process payments or execute financial actions.

Do not paste the bot token or API token into ChatGPT, GitHub issues, screenshots or logs. Telegram is a convenient owner-control channel, not an end-to-end private vault; avoid sending customer CVs, identity documents, payment evidence or other sensitive personal data through it.

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


## Optional FreeLLM multi-provider sidecar

Qudron now includes an **opt-in** FreeLLM 0.5.2 sidecar. It exposes an OpenAI-compatible endpoint on the private Compose network and can fail over among supported free-tier providers. It is pinned in `Dockerfile.freellm`; the service has no published host port and requires `FREELM_SERVER_KEY`. It is not started by default.

### Enable the private sidecar

1. Copy `.env.example` to `.env`.
2. Generate a unique random `FREELM_SERVER_KEY` (at least 32 random bytes). Do not reuse `QUDRON_API_TOKEN`.
3. The sample `.env` sets `FREELM_KEYLESS=auto`: if no provider keys are present, FreeLLM uses its documented anonymous endpoints as a last resort. This is intended only for public, non-sensitive test prompts. For provider-key-only operation, set `FREELM_KEYLESS=0` and add official provider keys you own and are authorized to use (for example Google AI Studio, Groq, OpenRouter, Cloudflare, Mistral, NVIDIA NIM, Z.ai or Kilo; Cerebras is trial-credit based and may require a card).
4. In `.env`, explicitly route only the FAST profile to the sidecar:
   ```dotenv
   LLM_FAST_BASE_URL=http://freellm:4000/v1
   LLM_FAST_MODEL=auto
   ```
   Compose injects `FREELM_SERVER_KEY` as the FAST profile's bearer key. Balanced and Reasoning profiles remain on their separately configured endpoints.
5. From this directory, run:
   ```bash
   docker compose --profile free-ai up -d --build
   docker compose ps
   docker compose logs --tail=100 freellm
   ```
6. Check the private sidecar from the Qudron container:
   ```bash
   docker compose exec qudron python -c "import urllib.request; print(urllib.request.urlopen('http://freellm:4000/health').status)"
   ```

### Verify configured providers

After the sidecar is running, inspect provider readiness from inside its container:
```bash
docker compose exec freellm freelm health
docker compose exec freellm freelm doctor --json
docker compose exec freellm freelm models
```
`freelm doctor` sends a tiny live test request to each configured provider/key (and keyless fallback when enabled), so it consumes a small amount of quota and should be run only with harmless test prompts. The health endpoint alone proves the router process is alive; it does not prove upstream inference is available.

### Keyless mode and privacy

- With `FREELM_KEYLESS=auto`, FreeLLM uses anonymous public endpoints only when no keyed providers are configured. It documents Kilo Gateway free routes and OVHcloud anonymous endpoints as low-quota keyless fallbacks. Availability and limits can change at any time.
- Anonymous endpoints may log prompts and are not approved for CVs, personal data, customer records, payment evidence, secrets, or confidential QudSystem material. Use keyless mode only for public, non-sensitive test prompts.
- Free tiers are not unlimited, guaranteed, or necessarily suitable for commercial workloads. The provider's own terms, account quotas, region restrictions and data handling apply.
- FreeLLM quota/cooldown state is persisted in a named Docker volume so a routine sidecar restart does not immediately reset local provider pacing. This does not change or extend upstream quotas.
- Do not add multiple keys to evade a provider's quota or terms. Only use separately authorized keys within each provider's published rules.
- This sidecar is an optional provider adapter, not proof that any provider is currently reachable. Run the provider's live `freelm doctor` checks and a harmless end-to-end Qudron test before relying on it.
- Keep CVPen and other personal-data workflows on a provider approved for that data. Anonymous/keyless routing is not allowed for customer-data jobs.

### Roll back / disable

Stop the optional sidecar with:
```bash
docker compose --profile free-ai stop freellm
```
Remove `LLM_FAST_BASE_URL` and `LLM_FAST_MODEL` from `.env` to return FAST tasks to the default configured endpoint. The queue and existing jobs remain independent of the optional sidecar.


## Optional connected-service adapters

- github_inventory.py provides paginated, read-only repository metadata discovery and optional recursive tree indexing. Configure GITHUB_OWNER and a read-only GITHUB_TOKEN in the host secret manager. This indexes repo metadata and paths, not every source file. Never enable write scopes for the inventory worker.
- metricool_client.py reads the scheduled-post calendar and Facebook/Instagram published-post analytics. It can create review drafts only; it hard-sets draft=true and autoPublish=false. Configure METRICOOL_API_TOKEN, METRICOOL_USER_ID and METRICOOL_BLOG_ID. Metricool API access requires an eligible Advanced or Custom plan. The ChatGPT connector session does not transfer to this service.
- vision_adapter.py accepts local images only under QUDRON_IMAGE_ROOT and calls a configured multimodal OpenAI-compatible model. It reuses the runtime spend reservation and concurrency controls. It is a callable adapter, not a public upload route. Use only a provider whose data handling is approved for the image content.

These modules are optional and do not run until called by an authenticated orchestration workflow. No external post is published by this release.


## Owner completion reports

When the optional Telegram gateway is configured, it checks the latest 20 task records every 60 seconds. Completed tasks send their bounded Markdown report to the allowlisted owner private chat; failed tasks send a short status notice without exposing internal provider errors. A SQLite ledger in the shared persistent data volume deduplicates notifications across gateway restarts. This requires the runtime and Telegram gateway to remain running on an always-on host.


## Optional automatic live web research

Research jobs can automatically retrieve up to five live web sources from DeepSeek Search & Fetch before the swarm starts. This is disabled by default. To enable it, configure DEEPSEEK_API_KEY, set QUDRON_WEB_SEARCH_MAX_DAILY_CALLS to a small positive integer, and set QUDRON_WEB_SEARCH_ENABLED=true. Each successful Search or Fetch call is currently listed at $0.75 per 1,000 calls; the local daily call cap is a conservative guard, not a billing guarantee. Results are marked as untrusted evidence and are passed to the swarm with title, URL, date, authority tier, summary and a bounded content excerpt. Only research jobs trigger this integration; drafts and customer-data workflows do not. The system never scrapes logged-in ChatGPT pages or bypasses website access controls.


## Weekly GitHub capability mining

The `github-capability-mining` schedule runs once every seven days at 03:30 Africa/Cairo. It calls the bounded read-only miner and registers repository metadata/tree-path candidates in the SQLite capability registry. The default batch is 50 repositories; set `QUDRON_GITHUB_MINE_MAX_REPOSITORIES` to 1-200. It is internal-only and is not accepted by the generic external task intake API.

If `GITHUB_OWNER` or `GITHUB_TOKEN` is absent, the scheduled job writes a clear skipped report and makes no GitHub request. Use a fine-grained read-only token scoped to the intended repositories. This pass does not download source, verify licenses, run tests, execute repository code or promote a candidate to active.


## Multi-provider model gateway (keyless starter)

The included FreeLLM sidecar is the default OpenAI-compatible gateway when `LLM_BASE_URL` is blank. It is pinned to `freelm==0.5.2`; its own local server key is generated inside the persistent `freellm-state` volume, not committed to Git. It can discover and fail over among published free-tier endpoints. The gateway itself does not supply unlimited inference: anonymous endpoints have tight per-IP quotas, provider free tiers change, and each provider's data handling applies.

**Keyless mode is for public, non-sensitive work only.** Qudron's worker will fail closed before sending jobs involving CV customer data, support records, payments, incident/security reports, private source code or other sensitive workflows through this route. It also refuses a keyless request if its prompt contains a value that the existing PII/token redactor would mask. Add an approved provider key or private model endpoint before enabling those workflows. Do not place private customer records, credentials, private source code or payment evidence in an anonymous/free endpoint.

When no provider keys are configured, `FREELM_KEYLESS=auto` selects only documented anonymous/free routes. To force official provider keys only, set `FREELM_KEYLESS=0`. Add keys via the host secret manager (not Git) when available. The router handles provider/model discovery and failover; Qudron still records call/token usage and maintains its own budget/concurrency gates.

## Continuous model-provider access and recovery

Qudron keeps a provider access radar for owner-configured routes. The runtime probes the read-only model catalogue endpoint (GET `/models`) on a bounded interval, checks that the configured model is actually advertised, records latency/failures in the shared SQLite database, and applies a persistent circuit breaker after authentication, quota, network or server errors. A provider returning to health is re-tested and may re-enter the route chain.

The inference path can use an owner-approved ordered fallback chain through `QUDRON_PROVIDER_ROUTES_JSON`. Each route must declare its profile, exact endpoint/model, protocol, price class, accepted data classes, and an environment-variable reference to its key. The raw key is never placed in JSON, status responses or logs. The currently implemented execution chain accepts OpenAI Chat Completions routes; providers requiring Anthropic Messages, Gemini GenerateContent or OpenAI Responses need their respective adapter before they can be activated through this chain.

For DeepSeek V4.1 Flash, the official API model ID is `deepseek-flash` (currently served as V4.1-Flash-1017), using `https://api.deepseek.com`. The current official peak cache-miss input rate is $0.30 per 1M tokens and output is $1.20 per 1M tokens; off-peak and cache-hit prices differ. The example in `.env.example` is commented out and must be revalidated against the official pricing page and the owner's account before enabling it.

**No silent privilege or spend escalation:** a fallback is eligible only when explicitly enabled and owner-approved. Paid routes need exact input/output prices and the same local per-task/daily/monthly budget controls. Verified free routes require an explicit owner attestation; an endpoint is never treated as free merely because it responds. The runtime never scrapes browser cookies, borrows another user's subscription, evades rate limits, or silently changes a blocked paid route to a paid alternative.

Provider data classes default to `public,internal`. Customer CVs, support cases and payment workflows are classified as confidential and will not be sent to a route until `QUDRON_PROVIDER_DATA_CLASSES` and the route's own `accepted_data_classes` explicitly permit it. Anonymous FreeLLM remains public-only and never receives Qudron's private memory.

The health probe is deliberately read-only: it proves that the catalogue endpoint is reachable and advertises a model, not that an inference request succeeds or that quota/billing is available. A successful inference, usage record and real account entitlement remain distinct verification steps.

## Batch task intake and capacity

- `POST /jobs` remains available for one job.
- `POST /jobs/batch` atomically accepts 1-100 internal draft/research jobs, each with its own idempotency key.
- `QUDRON_MAX_PENDING_JOBS` defaults to 100,000 active/pending jobs (configurable up to 1,000,000); excess submissions fail with a capacity error rather than silently dropping work.
- `GET /status` includes active queue depth, maximum capacity and remaining slots.
- The 100,000 figure is the **durable backlog target**, not 100,000 live model calls. The current SQLite deployment is a single-host starter with bounded worker/model concurrency. Horizontal execution at high volume needs a shared Postgres job ledger and a durable broker/consumer group (Cloudflare Queues or NATS JetStream are candidates), provider-specific rate limits, idempotency leases and autoscaling. Do not increase one provider's concurrency to match queue size.

A missing `QUDRON_API_TOKEN` is now handled by generating a random owner token in the private `data/api_token` file with mode 0600. Keep the data directory private and back it up encrypted. An explicitly configured token takes precedence.

## OpenDots workspace integration

The repository pins the upstream MIT-licensed [CopilotKit/OpenDots](https://github.com/CopilotKit/OpenDots) source under `integrations/OpenDots` (see `.gitmodules`). A Streamable HTTP MCP server is exposed at `/mcp`; OpenDots can read Qudron status, usage, job status and reports, and submit only internal draft/research tasks. Submission is not marked read-only, so OpenDots defaults it to **Ask first**.

The one-time connection is configured in OpenDots under a Dot's **Edit specialist → Connections**:
- URL: `http://qudron:8765/mcp`
- Bearer token: the private Qudron API token in `data/api_token` (or the `QUDRON_API_TOKEN` host secret).

Keep the submission tool approval enabled. OpenDots conversations require a CopilotKit Intelligence project (hosted, local evaluation or licensed self-hosted) and a model. The app can start in setup mode without those credentials; it does not invent replies. Its optional computer service uses Docker/OpenBot and requires Docker Engine, enough RAM and per-Dot computer credentials. See `OPENDOTS_INTEGRATION.md`.

## Social distribution

The current Metricool adapter deliberately creates drafts only. Use it as the distribution layer for Facebook, Instagram, YouTube and other supported destinations after connecting the official Metricool API. The publication workflow should produce platform-specific variants, campaign IDs, media metadata, UTM tags, an approval record and post-publication evidence. No public post is considered complete until its provider returns a published ID and permalink. Never bypass Meta login or use personal cookies scraped from a browser to publish.
