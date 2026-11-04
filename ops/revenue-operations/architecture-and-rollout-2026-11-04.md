# QudSystem Revenue Operations & Automation Architecture
## Decision brief — 4 November 2026

**Status:** Architecture and operating plan only. This document is not evidence that the proposed external services have been installed, connected, licensed, or deployed.

## Executive decision

Adopt a **hybrid operating model (Scenario 3)** now, then evolve selected workflows into the Qudron multi-agent orchestration model (Scenario 4). Keep Metricool for the currently connected Hossam Galal/brand accounts. Use Qudron for planning, work queues, specialist reviews and measurable operations. Add Activepieces as the connector/orchestration bridge and Chatwoot Community Edition as the shared inbox once the official WhatsApp Business Platform account and hosting environment are ready. Use an authorized Egyptian payment gateway such as Paymob for settlement to a business bank account.

Do not replace working integrations just to use more software. Do not automate through unofficial WhatsApp Web libraries, browser scraping, shared passwords, or wallet-limit workarounds.

## Five operating scenarios

| Scenario | Architecture | Strengths | Costs / risks | Decision |
|---|---|---|---|---|
| 1. Managed-first | Metricool + official WhatsApp Cloud API/BSP + hosted inbox/CRM + Paymob + hosted LLM | Fast onboarding, less server maintenance, managed OAuth connectors | Recurring subscription fees, external data processors, dependence on vendor approval and account limits | Useful for speed when revenue funds the subscriptions |
| 2. Self-hosted open-source | Qudron + Activepieces core + Chatwoot CE + Postiz self-hosted + PostgreSQL/Redis + own platform developer apps | More control, low software licence cost for core components, API/webhook integration | Requires a maintained server, backups, updates, monitoring, security, and separate app approvals on social networks; Postiz self-hosted is AGPL-3.0 | Not the first move with no production host or social developer apps |
| 3. Hybrid (recommended) | Keep Metricool on connected channels; Qudron + Activepieces self-hosted for internal workflows; Chatwoot CE when WhatsApp onboarding is ready; Paymob for merchant settlement | Reuses the proven connector, lower initial switching cost, open interfaces, gradual rollout | Still needs hosting, OAuth/API permissions, official WhatsApp onboarding and merchant KYC | Best balance now |
| 4. Agent-orchestrated operations | Qudron queues → role-specialist swarms → evidence/QA gates → Activepieces tools → approved systems | Separates research, drafting, review, QA and reporting; supports model routing and memory; scalable | More model/API cost, orchestration complexity, prompt and output risk, observability burden | Target architecture after the hybrid base is stable |
| 5. Multi-brand agency/SaaS | Tenant-isolated Qudron/Activepieces workflows, separate brand OAuth, separate customer data, usage metering, merchant arrangements | Can scale into a QudSystem service sold to clients | Highest legal, security, support and licensing burden; each client's channels, ownership, data and permissions must be isolated | Defer until QudSystem has proven demand and formal compliance |

### Why Scenario 3 wins

It avoids a risky full migration away from Metricool while taking advantage of open-source tools for workflow orchestration and customer support. Postiz is a credible self-hosted publishing alternative, but its AGPL-3.0 edition requires QudSystem to run and maintain its own deployment and developer applications. Its hosted platform advertises a public API, webhooks and agent integrations; the cloud product is paid. Platform integrations remain subject to the actual social network's app permissions and approvals.

## Proposed service map

- **Qudron:** central job queue, role registry, routing, memory, audit trail, operational reviews and approval policy.
- **Activepieces:** event-driven connectors and reusable workflows. Its core is MIT-licensed; enterprise/cloud components are commercially licensed. Its WhatsApp Business piece documents send-text, send-media and template-message actions, and can be self-hosted. It is an automation connector, not a substitute for WhatsApp's official network or customer inbox.
- **Chatwoot Community Edition:** shared inbox, assignment, conversation history and human handoff. Self-hosted Community Edition is listed at $0 per agent/month; Captain AI and some enterprise capabilities are not in the free edition. Official WhatsApp Cloud API setup still requires a Meta business/app configuration, a phone-number ID and a system-user token. Manual setup does not support WhatsApp Business App coexistence; confirm the correct Meta Quick Setup route before touching an existing number.
- **Metricool:** keep using the currently connected brand while channel access and publishing are verified. Current connected brand ID is 7777628 with Facebook, Instagram and YouTube. This does not establish access to LinkedIn, TikTok or Vision Guard accounts.
- **Postiz (optional replacement or secondary publisher):** test in staging first. Self-hosted edition is AGPL-3.0; cloud pricing is paid. Do not migrate until its social-app OAuth and account permissions are confirmed.
- **Paymob or another licensed Egyptian PSP:** checkout/payment links, signed payment events and reconciliation, with settlement to the verified merchant bank account. Confirm provider-specific pricing, supported methods and settlement timing in the merchant contract.
- **LLM providers:** fast/low-cost profile for routine drafts; balanced profile for content; reasoning profile for fact, privacy, CV and financial-risk review. Keep sensitive CV files outside long-lived strategic memory.

## CVPen revenue model — gross revenue is not profit

The figures below use a simple illustrative average order value (AOV), not a statement of current CVPen prices or proven demand.

| Average order value | Orders for EGP 200,000/month | Orders per day over 30 days | Orders for EGP 1,000,000/month | Orders per day over 30 days |
|---:|---:|---:|---:|---:|
| EGP 499 | 401 | 13.4 | 2,005 | 66.9 |
| EGP 799 | 251 | 8.4 | 1,252 | 41.7 |
| EGP 999 | 201 | 6.7 | 1,002 | 33.4 |

The current date is 4 November 2026. To reach EGP 200,000 by 30 November, there are approximately 26 calendar days remaining: 401 orders at EGP 499 means about 15.4 orders/day; 251 orders at EGP 799 means about 9.7/day; 201 orders at EGP 999 means about 7.7/day. These are arithmetic requirements, not forecasts.

### Funnel requirement example

At EGP 799 AOV, 251 monthly orders are required for EGP 200,000 gross revenue. At a hypothetical 5% qualified-lead-to-paid-order conversion rate, that would require about 5,020 qualified leads; at 10%, about 2,510. The actual CVPen funnel conversion is not currently verified. Track every stage before increasing content volume or spending.

### Offer architecture to test (not yet approved as final pricing)

1. Free, privacy-safe CV structure check using a limited set of user-provided text.
2. Entry-level CV formatting/structure improvement.
3. Role-tailored CV package based only on verified candidate facts.
4. Career package with cover letter and LinkedIn profile review.
5. Paid additional target-role version or revision package.

The existing CVPen source branch currently narrows the automated free checker to TXT while genuine PDF/DOCX text extraction is not implemented. Keep that limitation visible until tested extraction is added. A structure score must not be represented as a probability of passing ATS or getting hired.

## Payments and the Etisalat Cash request

### Do not plan a EGP 200k–1m business turnover around the personal Etisalat Cash wallet

The current published e& Etisalat Cash terms found in the official e& Egypt page list:
- EGP 30,000 maximum daily transactions.
- EGP 100,000 maximum monthly transactions.
- EGP 100,000 maximum wallet balance.
- EGP 50,000 maximum daily cash-in.

The CBE's general individual mobile-wallet information also publishes EGP 30,000/day and EGP 100,000/month. A separate CBE announcement in 2023 raised limits for certain financial-inclusion accounts, prepaid cards and mobile banking categories, but that does not, by itself, prove that the e& consumer wallet has adopted the higher limits or offers a merchant settlement product. Treat the official e& wallet product terms as the wallet-specific limit unless Banque du Caire/e& confirms an updated product in writing.

**Operational conclusion:** do not route a target of EGP 200,000 or EGP 1,000,000 through the one personal consumer wallet. Do not split proceeds among family or other consumer wallets to evade limits. No wallet PIN, OTP or password should ever enter Qudron or ChatGPT.

### Preferred lawful settlement route

1. Apply for merchant onboarding with a licensed PSP (for example Paymob) using the correct legal form and verified business identity.
2. Confirm merchant documents, allowed business activity, supported wallet/card methods, reserves, refund/chargeback rules and settlement schedule in writing.
3. Set up the dedicated merchant account and business bank account required by the provider.
4. Let customers pay using the officially supported checkout methods (the provider may support customer wallet payments as an acceptance method).
5. Verify every payment using provider-authenticated webhooks and reconcile order ID, exact amount, currency, transaction ID and final settlement state.
6. Settle to the approved business bank account. Any later owner draw or transfer to an e-wallet must follow applicable wallet rules and the PSP/bank's terms.

Paymob's published standard plan lists 2.75% + EGP 3 per transaction and weekly settlement to a bank account. Confirm that the quoted plan applies to the chosen method and your merchant contract; wallet and alternative payment methods can have different terms.

Illustrative fees at the published standard rate, before other charges/taxes/chargebacks:
- EGP 200,000 gross, average order EGP 500 (400 transactions): 2.75% = EGP 5,500 plus EGP 1,200 transaction fees; approximately EGP 6,700.
- EGP 1,000,000 gross, average order EGP 500 (2,000 transactions): 2.75% = EGP 27,500 plus EGP 6,000; approximately EGP 33,500.

Those amounts are not a net-profit calculation. Also subtract VAT/tax obligations where applicable, model/provider costs, hosting, customer service, human QA, refunds, chargebacks, payment failures and customer acquisition cost.

## WhatsApp: official API, not a reverse-engineered workaround

Recommended customer-support path:
1. Use an official WhatsApp Business Platform / Cloud API account.
2. Connect it to Chatwoot through the supported Meta setup flow.
3. Connect Chatwoot events to Qudron/Activepieces via authenticated webhooks.
4. Let a bot answer only approved FAQs, order status and safe service-process questions.
5. Escalate disputes, payment mismatches, sensitive CV questions, refunds, complaints and legal questions to a human.
6. Send marketing templates only to contacts with recorded opt-in and only under applicable Meta rules and Egyptian legal requirements.

Do not install Baileys, whatsapp-web.js or other unofficial WhatsApp-Web automation as a workaround. They are not a replacement for the official business API and can expose the business to session compromise, account restriction and policy violations. Open-source tooling can connect to the official API; it cannot remove the API's rules or per-message fees.

Activepieces' currently documented WhatsApp Business connector includes send text, send media and send template message actions. Its current listing reports zero triggers, so incoming messages should be received through the official Meta webhook/Chatwoot inbox, not assumed to arrive through that connector as an event source.

Meta's pricing is per delivered message and varies by category and recipient country. The research snapshot for Egypt in late 2026 identified a marketing-template rate near US$0.0644 and utility/authentication rates near US$0.0036, but obtain the current Meta rate card at onboarding; pricing changes and intermediaries may add fees.

## Cross-platform publishing policy

### Currently connected
Metricool currently exposes one brand with Facebook, Instagram and YouTube. Organic posts can be scheduled through Metricool where the provider supports the content type and media.

### Not confirmed as connected
LinkedIn, TikTok, Pinterest, Threads, Google Business Profile and Vision Guard Systems are not currently confirmed in that connected brand. Do not publish to them until the correct owner account is connected and provider permissions are verified.

### Platform constraints
- TikTok Direct Post needs Content Posting API approval and the `video.publish` scope; unaudited clients are restricted to private visibility.
- LinkedIn organic publishing uses `w_member_social` or organization permissions and appropriate Page roles.
- YouTube uploads require OAuth scopes such as `youtube.upload`, plus actual video media and metadata.
- Instagram feed posts/Reels require the media types and account/API permissions specified by Meta; text-only scheduling is not an Instagram post substitute.

Use one content source with platform-specific adaptations, not identical copies everywhere. Keep human review for legal claims, customer testimonials, financial claims and content that could materially affect reputation.

## Compliance and customer-data protection

CVs contain personal data. Before any live customer intake:
- Map controller/processor roles, lawful purpose, data categories, retention periods and deletion handling.
- Collect only fields needed for the order.
- Publish an Arabic-first privacy notice and separate, affirmative consent for service processing and any direct marketing.
- Never use customer CVs for model training or public examples without a distinct lawful basis and appropriately documented authorization.
- Use tenant-separated storage, encryption at rest/in transit, least privilege, secrets management, audit logs, backup/restore testing and a documented incident-response process.
- Review all cross-border model/storage transfers with Egyptian counsel and the relevant regulator before sending CV data to foreign-hosted providers.
- Do not treat an AI-generated answer as legal, tax or regulatory sign-off.

The PDPL (Law 151/2020) and Executive Regulations No. 816/2025 are important current compliance references. Research sources disagree on transitional dates and the precise licensing/permit scope for different activities. Do not rely on a model-generated deadline summary: obtain a written compliance assessment from the Egyptian Personal Data Protection Center or qualified Egyptian counsel before high-volume personal-data processing or direct electronic marketing.

## Operations and continuous improvement

### Daily control loop
1. Fetch new task events, Metricool results, approved order events and delivery outcomes.
2. Deduplicate webhook events and reconcile payments before starting paid fulfilment.
3. Assign a bounded swarm: producer → independent reviewer → final QA. Five stages maximum for high-risk work.
4. Store short-term operational notes with expiry; store only sanitized, low-sensitivity strategic decisions long-term.
5. Draft/schedule authorized content to verified channels only.
6. Compare planned vs completed work; log errors, retries, owner, evidence, test and rollback note.
7. Escalate payment mismatches, data breaches, privacy requests, complaints, refunds and provider-account restrictions.

### Three-day process review
Review lead quality, conversion, delivery time, quality failures, revisions, refunds, complaint themes, social performance, API errors, model cost, workflow retries and capacity. Change one major variable at a time and retain a decision log.

### Weekly strategy review
Compare 7-day and 28-day performance. Stop channels that produce low-quality leads; invest in the best verified sources; adjust packaging/pricing only after cohort evidence; review whether capacity can support the next volume tier.

### Minimum KPI dashboard
- Qualified enquiries and source.
- Free diagnostic starts/completions.
- Checkout starts and payment success.
- Paid orders and gross cash received.
- AOV and contribution margin.
- Median fulfilment time and on-time delivery rate.
- CV correction/revision rate and refund/complaint rate.
- Social reach, saves/shares, website clicks and attributed enquiries.
- Cost per qualified enquiry and cost per paid order.
- LLM spend per completed job, failed job rate, queue age and API uptime.

## Staged delivery plan

### Phase 0 — legal/payment gate
- Confirm business form and applicable registration/tax/VAT requirements with an Egyptian accountant/lawyer.
- Obtain written e&/Banque du Caire guidance if the personal wallet is still intended for any business receipts.
- Open/identify an appropriate business bank account and complete PSP merchant onboarding.
- Approve privacy notice, data retention, consent and DPO/licensing requirements.
- No live customer CV intake or marketing automation until these points have been assessed.

### Phase 1 — low-risk operating baseline
- Retain Metricool for the three currently connected accounts.
- Finish CVPen PR quality checks, review the draft, then choose whether to merge and deploy.
- Deploy Qudron to a private, always-on host after selecting a host, backup policy and model provider.
- Start Activepieces self-hosted in an isolated environment; use only core MIT components unless a commercial feature is knowingly licensed.
- Prepare Chatwoot Community Edition deployment, but connect WhatsApp only after official Meta account setup and approved access.

### Phase 2 — checkout and support automation
- Build Paymob sandbox checkout and verify signed webhook handling, idempotency, duplicate event replay, refunds/disputes as human escalations, failed-payment handling and weekly bank reconciliation.
- Connect Chatwoot to official WhatsApp Cloud API.
- Automate order confirmations and delivery notices as approved utility templates; maintain consent evidence for any marketing.
- Connect Qudron's task API to Activepieces, with a strict per-task allowlist and service credentials.

### Phase 3 — measured growth
- Run 2–3 controlled CVPen content/offer experiments each week.
- Build a consented lead funnel, referrals and partnerships with training centers/universities.
- Increase order volume only after QA capacity, delivery SLA and unit economics remain healthy.
- Expand to TikTok/LinkedIn/other brands only after account OAuth, API approvals and role permissions exist.

### Phase 4 — multi-brand and productized automation
- Introduce tenant separation and formal client data-processing agreements.
- Use separate OAuth apps and least-privilege credentials per client.
- Review software license terms before making any component part of a hosted QudSystem customer-facing automation product.
- Negotiate commercial OEM/embedding terms for tools whose licenses require them.

## Human approval boundaries that remain

Even with the best agents and browser computers, some actions cannot responsibly be zero-human:
- Meta/TikTok/LinkedIn developer-app approval and business verification.
- PSP/bank onboarding, KYC, business account opening and tax registration.
- Wallet PINs, OTPs, banking credentials, refunds, payout routing and money movement.
- Legal declarations, privacy-policy approval, sensitive data transfers and regulatory license applications.
- Complaints, disputed payments, identity or CV fact contradictions, and decisions materially affecting a customer.

Qudron should automate preparation, evidence collection, checking, routing and audit logs. It should not impersonate the business owner to satisfy identity verification or override external permission gates.

## Current implementation status as of 4 November 2026

**Verified completed in source/CI:**
- Qudron PR #2: 31 specialist roles, 14 teams, 16 scheduled workstreams, bounded three-stage swarm orchestration, model profiles, SQLite operational memory, authenticated idempotent task intake, generic payment signature guard, tests. Latest recorded Qudron CI run was green with 28 unit/API/safety tests and Docker image build.
- CVPen source PR #2: safer resume backup validation, blank default CV template, bilingual structure checklist, TXT-only checker, improved list editing and error boundary. The latest recorded GitHub Actions run #3 passed tests, lint and production build. This is still a **draft PR**, not merged or deployed.
- Metricool brand 7777628: one Facebook post was scheduled as an auto-publish post for 4 November 2026 at 12:15 Africa/Cairo. Its Metricool planner id is 416253036 and its state was PENDING when scheduled. A scheduled status is not proof that the post has published.
- QudSystem Growth Engine automation was updated with exact verified destinations and publishing quality gates.

**Not yet live/connected:**
- Qudron has no verified always-on deployment or model credentials.
- Activepieces, Chatwoot and Postiz have not been installed on a host.
- WhatsApp Cloud API is not connected.
- Paymob merchant account, bank settlement and CVPen live checkout are not connected.
- No Instagram media post, YouTube video, TikTok post or LinkedIn post has been published by this work.
- Vision Guard social accounts are not connected to the selected Metricool brand.
- No funds have been received, moved or transferred by Qudron.

This is an implementation plan with verified source/CI milestones, not a guarantee of 100% uptime or revenue. The remaining work is contingent on lawful onboarding, account authorization, hosting, model credentials, channel media and payment-provider approval.
