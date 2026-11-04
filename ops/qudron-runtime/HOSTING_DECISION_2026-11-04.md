# Qudron Hosting Decision — 4 November 2026

## Executive decision

Do **not** select a free VM as the guaranteed 24/7 production host for the current Docker worker. The closest zero-monthly-cost route for an always-reachable, event-driven service is a Cloudflare Workers + Queues + D1 + R2 implementation. That is a serverless re-platform of the worker logic, not a place to run the existing Python/Docker Compose stack unchanged.

Keep the existing Python/Docker runtime as the reference implementation and local/hosted worker option. Build the Cloudflare edge runtime as a separate, tested pilot before switching any production traffic.

No paid service has been provisioned, no billing account has been upgraded, and no API credentials have been installed.

## Options and actual constraints

| Option | What it solves | Blocking limitation | Decision |
|---|---|---|---|
| Cloudflare Workers Free + Queues + D1 + R2 | Public HTTPS intake, event-driven jobs/retries, persistent job ledger, artifacts and scheduled dispatch without an idle VM | Requires a TypeScript/JavaScript worker implementation; free quotas apply; no permanent process; Queue retention is only 24 hours on Free | **Preferred zero-monthly-cost architecture**, after code port and tests |
| Oracle Cloud Always Free Ampere A1 | Can host the existing Docker Compose stack on ARM64 Linux; up to 2 OCPU and 12 GB RAM within Always Free monthly allowances | Capacity is not guaranteed; idle Always Free VMs can be reclaimed; no SLA; account/card verification required | Development or low-volume pilot only; **not** a dependable production guarantee |
| GitHub Actions | CI, scheduled maintenance, bounded batch execution and deployment automation | GitHub-hosted job has a six-hour maximum runtime; runners are ephemeral and scheduled runs may be delayed | Keep for CI and controlled batch jobs, not the always-on worker |
| Vercel Hobby | Front-end, static assets and short request/response APIs | Not a persistent Docker worker host; current connected Vercel team has no Git-linked Qudron project | UI/API edge only, not the Qudron queue worker |
| Replit | Convenient application hosting | Connected account currently blocks app creation on subscription requirement | Not available for this pilot |
| Local desktop/laptop | Zero hosting bill and useful for development | Power, internet, device sleep/restarts and home-network exposure make it unsuitable as a production SLA | Development and backup test only |
| Paid VPS | Straightforward, compatible Docker host with persistent process | Monthly cost and explicit purchasing approval required | Fallback only; do not provision without owner approval |

### Cloudflare Free plan sizing

The current documented Free plan includes:

- Workers: 100,000 requests per day and 10 ms CPU time per invocation.
- Queues: 10,000 standard operations per day. A simple message commonly costs one write, one read and one delete (roughly three operations). Queue retention on the Free plan is fixed at 24 hours.
- D1: 5 million rows read per day, 100,000 rows written per day and 5 GB total storage.
- R2: 10 GB-month storage, 1 million Class A operations and 10 million Class B operations per month, with no egress charge.

These limits are sufficient to prototype a lightweight, event-driven internal task service, but not a promise of unlimited free usage. The worker must persist task state and retry deadlines in D1 so the 24-hour Queue retention is not the only durable record. Long-running work must be split into bounded stages. The Free CPU limit makes heavy parsing and document conversion unsuitable inside the Worker.

Cloudflare Containers are not a free substitute: the documented Containers pricing is part of the Workers Paid plan, which has a $5/month minimum.

## Recommended zero-cost architecture

1. **HTTPS control/intake:** Cloudflare Worker validates a bearer token, schema, idempotency key and allowlisted task type.
2. **Durable ledger:** D1 stores job state, idempotency, retry count, usage, schedule state and audit events.
3. **Execution queue:** Cloudflare Queues dispatches bounded jobs to a queue consumer. D1 remains the source of truth; the queue is a delivery mechanism.
4. **Artifacts:** R2 stores non-sensitive internal reports. Customer CV files remain out of scope until encrypted tenant isolation, retention and deletion controls are separately implemented.
5. **Scheduler/recovery:** Cron Trigger scans D1 for due jobs and undispatched/retryable jobs. This recovers from queue messages expiring or dispatch interruptions.
6. **AI providers:** Call only documented provider APIs with secrets entered into the provider dashboard/Worker secret store. Keep provider/model routing configurable. Anonymous public model endpoints are restricted to public, non-sensitive prompts and must never receive CVs, IDs, payment evidence, credentials or confidential business material.
7. **Human approval:** Customer messaging, live payment operations, refunds, public publishing and production settings remain approval-gated.

The first edge pilot must support only internal research, drafting and review. It must not claim to replace the 36-role registry or the ten-agent CVPen workflow until those stages are ported and independently tested.

## Oracle Always Free: important warning

Oracle documents up to 1,500 OCPU-hours and 9,000 GB-hours per month for Ampere A1, equivalent to 2 OCPU and 12 GB RAM for a full month. It also documents 200 GB of total Always Free Block Volume storage, including boot volumes.

However, Oracle can reclaim an idle Always Free compute instance when, over a seven-day period, CPU utilization at the 95th percentile is below 20%, network utilization is below 20%, and (for A1) memory utilization is below 20%. Do not generate artificial load just to evade this policy. An internal worker that mostly waits for model APIs may be considered idle. Free Tier has no SLA, capacity may be unavailable in the home region, and the account requires a valid card for identity verification; temporary authorization holds may occur. Do not upgrade to Pay As You Go for this plan.

Therefore OCI A1 is a useful free pilot host only if the instance is available and its use naturally satisfies Oracle's policy. It is not the recommended guarantee for a quiet 24/7 queue worker.

## What is solved now vs. still requires external setup

| Blocker | Solution | Status |
|---|---|---|
| Tested worker code | Keep current Docker runtime, 36-role registry, durable SQLite queue, retries, spend gates and FreeLLM sidecar | Implemented and CI-tested; not deployed |
| Free always-reachable hosting | Port bounded jobs to Workers + Queues + D1 + R2 | Architecture selected; implementation and account setup remain |
| Current Docker host | OCI A1 Always Free can host a pilot, with idle-reclamation caveat | Not provisioned; owner must create/verify tenancy and capacity |
| AI credentials | Configure official provider keys as platform secrets; set exact model prices and caps before execution | Not configured; never paste keys into chat or Git |
| QUDRON_API_TOKEN | Generate on deployment host/secret manager and store only as a secret | Not configured |
| WhatsApp/customer intake | Official WhatsApp Cloud API or an approved Chatwoot/partner integration | Not connected |
| Payments | Provider-specific signed PSP webhook and settlement reconciliation; sandbox first | Generic HMAC primitive exists; Paymob/e& merchant integration absent |
| CVPen document pipeline | Encrypted tenant storage, malware-safe parsing, DOCX/PDF output, retention/deletion and audit tests | Not implemented/connected |
| Social publishing from Qudron | Keep using the existing approved Metricool workflow; Qudron publishing stays disabled | Separate from this runtime; no blanket cross-platform automation |
| Production safety | Private access, monitoring, backups/restore, spend caps, idempotency and approval gates | Tests/design exist; host-side validation pending |

## Release gates

Do not mark Qudron pilot-live until all of the following are evidenced:

- The chosen host/runtime is deployed and reachable over authenticated HTTPS.
- D1/SQLite state and reports survive retries and restarts; backup and restore are demonstrated.
- A real provider call succeeds using an owner-configured secret, exact model price and hard daily/monthly/job budgets.
- Duplicate idempotency keys do not duplicate work.
- Queue expiration, retry, dead-letter and recovery paths are tested.
- Internal scheduled tasks run and produce retrievable reports.
- Monitoring reports health, queue age, failures, provider errors, spend and last successful schedule.
- No customer data, CV uploads, payments, WhatsApp messages or public publishing are enabled in the internal pilot.

## Official references checked 4 November 2026

- Cloudflare Workers limits: https://developers.cloudflare.com/workers/platform/limits/
- Cloudflare Workers pricing: https://developers.cloudflare.com/workers/platform/pricing/
- Cloudflare Queues pricing: https://developers.cloudflare.com/queues/platform/pricing/
- Cloudflare Queues limits: https://developers.cloudflare.com/queues/platform/limits/
- Cloudflare D1 pricing: https://developers.cloudflare.com/d1/platform/pricing/
- Oracle Always Free resources and idle compute reclamation: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- Oracle Free Tier FAQ and card verification: https://www.oracle.com/cloud/free/faq/
- GitHub Actions limits: https://docs.github.com/en/actions/reference/limits
- Cloudflare Containers pricing: https://developers.cloudflare.com/workers/platform/pricing/


## Best current route for AI inference without a separate model API key

The Cloudflare edge option can use the native **Workers AI binding** (`env.AI.run()`), so the Worker can call Cloudflare-hosted models without a separate Gemini/Groq/OpenRouter model key. The owner still needs a Cloudflare account and must configure the AI binding, but no model-provider secret is required for this route.

As of 4 November 2026, Workers AI Free includes **10,000 Neurons per day** at no charge. The Free plan blocks further inference when the free allowance is exceeded; moving beyond the allowance requires Workers Paid (starting at $5/month, plus usage above the free allowance). We must not upgrade billing automatically.

A current model candidate explicitly listed as available on the Free plan is `@cf/zai-org/glm-4.7-flash`; the pricing page lists 5,500 Neurons per million input tokens and 36,400 Neurons per million output tokens. This is a finite daily allowance, not unlimited usage. Resource-intensive models including Kimi K2.6, Kimi K2.7 Code and GLM 5.2 require a paid plan according to the official changelog. Prefer GLM-4.7-Flash for the first internal test, then compare quality and quota consumption before routing more workloads.

Cloudflare's Workers AI data-usage documentation updated 16 October 2026 states standard inference inputs/outputs are processed only as needed, are not retained after processing absent stateful features, and are not used to train AI models. If Qudron stores reports/prompts in D1, R2 or logs, those stored copies follow the configured storage/log retention settings. Each third-party model's license still applies.

This is a better first no-key model path than using anonymous third-party gateways: it offers a documented daily free allocation and current privacy commitments. It still requires the separate Worker-based edge runtime; it cannot run the current Python/Docker worker directly.

Other routes:
- Gemini API Free has selected free models and free input/output tokens, but Google states Free-tier content may be used to improve products; public/non-sensitive work only.
- Groq Free has API-key access subject to model-specific RPM/RPD/TPM/TPD limits, which vary by organization.
- Cerebras lists a $0 Free tier with lower rate limits, but its public pricing details are stale; verify account quotas before relying on it.

Sources checked 4 November 2026:
- Workers AI pricing: https://developers.cloudflare.com/workers-ai/platform/pricing/
- Workers AI direct binding: https://developers.cloudflare.com/workers-ai/configuration/bindings/
- Workers AI Free-plan model eligibility: https://developers.cloudflare.com/changelog/post/2026-07-28-models-require-workers-paid/
- Workers AI data use: https://developers.cloudflare.com/workers-ai/platform/data-usage/
- Gemini Free vs Paid data treatment: https://ai.google.dev/gemini-api/docs/pricing
- Gemini project rate limits: https://ai.google.dev/gemini-api/docs/rate-limits
- Groq rate limits: https://console.groq.com/docs/rate-limits
- Cerebras pricing: https://inference-docs.cerebras.ai/support/pricing

## Railway: useful temporary Docker validation, not permanent free hosting

Railway can run persistent container services and workers, making it technically compatible with the current Docker Compose architecture. Its official Trial provides a one-time $5 credit for up to 30 days; after the trial, the Free plan provides only $1 of usage credit per month. The Free plan allows up to 0.5 GB RAM and one shared vCPU per service. RAM is priced at $10/GB-month and CPU at $20/vCPU-month. Therefore, holding 0.5 GB RAM continuously is about $5/month for memory alone before CPU, egress or storage. The $1 monthly free credit is not enough for a reliable always-on Qudron worker at that size.

**Decision:** Railway is a reasonable short-lived staging option using the trial credit, with an explicit shutdown date and usage alert. It is not a permanent zero-cost answer. The Railway ChatGPT app is available to connect for account inspection and deployment actions, but it is not currently connected here. Do not start a paid subscription or consume any paid balance without explicit approval.

Official references:
- Railway compute and persistent services: https://docs.railway.com/build-deploy
- Railway Trial: https://docs.railway.com/pricing/free-trial
- Railway plan resources and metered resource prices: https://docs.railway.com/pricing/plans
