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
