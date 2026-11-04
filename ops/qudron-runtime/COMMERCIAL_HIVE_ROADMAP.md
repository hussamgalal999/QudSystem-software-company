# Qudron Commercial Hive — Execution Roadmap
**Decision date:** 4 November 2026  
**Status:** Product and engineering plan; not a statement that the commercial system is live.

## Executive decision
Build Qudron as an AI-native operating system for QudSystem: one durable orchestration/control plane, specialist workers, approved external tools, customer-facing channels, and a measurable revenue pipeline.

Do not introduce LangGraph, CrewAI and n8n as three competing orchestration engines. The existing Qudron Python runtime already has durable task state, leases, retries, schedules, specialist roles, bounded review swarms, spend reservations and reports. Keep it as the first orchestration engine. Add integrations around it. Reconsider LangGraph only if the current state graph proves inadequate. Use n8n later as an integration/trigger layer if useful, not as a second source of truth.

The Cloudflare edge code is a separate pilot adapter and is not a deployed replacement for Python/Docker. Do not split the system across both until a real edge deployment passes its own integration tests.

## Product outcome
Qudron should:
1. Receive tasks from an authenticated dashboard/API, Telegram, WhatsApp Business or a local desktop bridge.
2. Classify tasks, select approved workflows, assign specialists and set deadlines/budgets.
3. Execute through external model providers and business tools without confusing model output with a completed external action.
4. Review results, validate facts and permissions, retry recoverable failures and escalate unresolved work.
5. Store task status, source references, usage/cost, approvals and final artifacts.
6. Report completed work and exceptions to the owner.
7. Convert approved service packages into leads, proposals, orders, fulfilment, payment reconciliation and retention.

## Architecture decisions

### 1. Orchestration and workers
- Primary: current Qudron Python runtime and durable SQLite queue for the first private pilot.
- Worker teams: Research & Market Intelligence; Content & Creative; Sales Operations; Customer Delivery; Engineering & QA; Finance & Risk; Monitoring & Recovery.
- Start with three bounded workflows:
  - Market research → source-check → opportunity brief.
  - Content draft → brand/fact review → owner approval → scheduled publishing.
  - Lead qualification → proposal draft → owner approval → CRM follow-up.
- Reuse the existing specialist registry and bounded review swarm. Invoke multiple independent reviewers only where risk/value justifies extra calls.
- Self-correction means schema validation, evidence checks, bounded retries, regression tests and escalation. It does not mean agents may rewrite production code, permissions or their own policies without review.

### 2. Model routing
- Keep FreeLLM as the optional Docker sidecar already integrated in the candidate branch. It is not live until a host, provider configuration and live inference test exist.
- Use official provider APIs/OAuth only, subject to provider terms. Never scrape session cookies, reuse private browser tokens or rotate accounts to evade quotas.
- Free tiers are capped experiments, not guaranteed capacity or a business continuity plan.
- Cloudflare Workers AI native binding is a possible no-separate-model-key route for the separate Cloudflare Worker adapter. It still requires Cloudflare resources and a deployed Worker; it does not automatically provide inference to the current Docker runtime.
- Every provider route needs an exact model ID, current tariff, quota, data-use terms, retention, rate limits, fallback policy and per-task spend cap.
- Never send CVs, identity documents, payment evidence, credentials or confidential customer content to anonymous/keyless endpoints.

### 3. Communication layer
**Stage A — Telegram:** first low-friction owner notification and command channel. Use a bot token stored as a secret; restrict allowed owner/chat IDs; support task submission, status, approval and reports.

**Stage B — WhatsApp Business Cloud API:** customer intake and service notifications only after Meta Business/phone setup, verified webhooks, opt-in, template rules and privacy/retention controls. Do not automate a personal WhatsApp Web session.

**Stage C — voice:** Twilio or another official voice provider only after pricing, Egyptian number availability, regulatory requirements, caller ID, recording consent and call cost are confirmed. Start with owner-requested status calls; do not cold-call prospects autonomously.

**Local desktop bridge:** a local agent/MCP server may access only explicitly allowlisted folders, such as a dedicated QudSystem workspace. It must not expose the whole home directory, browser profiles, wallet apps, passwords or unrelated personal files. Require confirmation before reading, uploading, deleting or modifying sensitive files.

### 4. Business systems and approvals
- CRM/lead records: source, consent, business need, budget, owner, next action, status and contact history.
- Proposals/orders: package, scope, delivery date, revisions, price, payment terms and acceptance.
- Payment reconciliation: signed PSP webhook/API plus matching internal order ID, amount, currency and provider transaction ID. SMS is not proof of settlement.
- Fulfilment: workflow tied to a paid/approved order; customer data tenant-isolated and encrypted.
- Publishing and customer messaging: drafts can be autonomous; final external send/publish requires approval until channel safeguards and quality metrics are demonstrated.
- Transfers, wallet PIN/OTP, refunds and ad spend remain outside autonomous authority.

## Revenue strategy

### Sell productized outcomes, not "AI agents"
Initial offers to validate:
1. **Social Presence Starter:** monthly content calendar, designed posts, captions and scheduled publishing for one local business.
2. **Short Video Pack:** scripts, editing/AI-assisted production, subtitles and fixed revisions.
3. **WhatsApp Lead Assistant:** FAQ, lead capture, routing and human handoff; setup plus monthly support, only after official WhatsApp integration is ready.
4. **CVPen:** ATS-focused CV review/creation with source-fact verification, customer approval and secure document handling.

Start with one target segment and one offer, prove delivery and collect testimonials with permission. Do not promise leads, sales or revenue outcomes that are not measured and contractually defined.

### Revenue math (illustrative, not a forecast)
A gross-sales target of EGP 1,000,000 requires, for example:
- 200 orders × EGP 5,000; or
- 100 orders × EGP 10,000; or
- 20 projects × EGP 50,000; or
- 10 contracts × EGP 100,000.

These examples exclude discounts, taxes, payment fees, delivery costs, refunds, churn and collection delays. Revenue is not profit and signed proposals are not collected cash. A one-month million-pound target cannot be responsibly forecast without a verified pipeline, conversion rates, delivery capacity, average collected ticket and sales-cycle data. Track cash collected separately from bookings.

### Sales funnel and KPIs
Track weekly:
- Qualified leads by source and consent status.
- First-response time and contact-to-meeting rate.
- Proposal count, proposal value and win rate.
- Orders accepted, invoices due, cash collected and overdue balances.
- Delivery time, revision rate, refund/complaint rate and gross margin.
- Recurring revenue, churn and renewal rate.
- Agent completion rate, human-review rate, factual error rate, provider failure rate and cost per deliverable.

Never fabricate customer logos, testimonials, case studies, reach or revenue metrics.

## 30-day gated implementation

### Gate 0 — make the existing runtime safe (Days 1–3)
- Keep PR #4 Draft until the candidate is reviewed and its complete test suite passes.
- Configure exact provider prices and daily/monthly caps; enable provider-side hard spend caps.
- Run local integration tests for queue recovery, concurrent claims, stale leases, idempotency, redaction and report access.
- Define secret-management and backup/restore procedures.
- No customer data or production traffic yet.

**Exit:** private internal runtime completes a synthetic task, survives restart/retry, produces a report and records usage/cost without secret leakage.

### Gate 1 — owner command and reporting (Days 4–7)
- Telegram bot or authenticated web console.
- Owner-only allowlist, task submission, status, approval and report links.
- Daily digest and incident alert.
- Explicit states: NEEDS_APPROVAL, NEEDS_REVIEW, COMPLETED, RETRYING and FAILED.

**Exit:** owner can submit and track tasks from a phone; no unapproved external messages are sent.

### Gate 2 — first commercial workflow (Days 8–14)
- Select one QudSystem offer and one local-business segment.
- Build lead research and qualification with evidence links.
- Generate proposal and content drafts.
- Use Metricool or an approved publishing connector only after owner approval.
- Manually verify every lead and commercial claim.

**Exit:** first pilot customer accepts a written scope and pays under agreed terms; otherwise revise the offer before scaling automation.

### Gate 3 — fulfilment and payment evidence (Days 15–21)
- Secure order records and tenant boundaries.
- Provider-specific payment webhook verification.
- Idempotent order-to-fulfilment transition.
- Customer deliverable QA, acceptance and support workflow.
- Keep customer CV pipeline disabled until encrypted storage, retention/deletion, file parsing/output and privacy/security tests pass.

**Exit:** one real paid order is reconciled from provider evidence through delivery and customer acceptance.

### Gate 4 — controlled scale (Days 22–30)
- Add only the next workflow with measured demand.
- Add WhatsApp Business if official account and webhook requirements are met.
- Add voice only if it has a clear owner use case and approved budget.
- Review unit economics, errors, quota pressure and customer satisfaction.
- Expand autonomy only for reversible, low-risk actions.

**Exit:** repeatable paid delivery with positive contribution margin and no unresolved critical security incidents.

## Known blockers and explicit non-claims
As of this decision:
- PR #4 is Draft/open/unmerged; Docker candidate passed CI but is not a production deployment.
- No always-on host has been provisioned.
- No live model-provider credential or Cloudflare resource is configured by this document.
- No Telegram bot, WhatsApp Business webhook, Twilio voice line, CRM, PSP webhook or local desktop bridge is claimed to be live.
- No live customer CV fulfilment or automatic payment acceptance is enabled.
- No revenue target is guaranteed.

## Immediate next actions
1. Keep work on the existing candidate branch and open a separate implementation issue for the commercial hive.
2. Run a real internal smoke test only after the owner selects/configures the runtime host and approved provider.
3. Build owner notifications before customer-facing automation.
4. Select one offer and one customer segment; measure actual conversion and collected cash.
5. Keep external send, publish, payment, refunds, spending and production changes behind explicit approval.
