# Qudron Parallel Execution Board
Decision date: 4 November 2026
Branch: feature/qudron-cvpen-swarm-release-candidate
Current PR: #4 (Draft, open, unmerged)

## Operating rule
Run independent engineering and commercial preparation tracks in parallel. External account setup, secrets, billing, customer data and public actions remain blocked until owner configuration/approval. Green CI is not deployment.

## Track A — Runtime / Swarm
Evidence: 36 specialist roles, 15 teams, bounded producer-reviewer-finalizer workflow, CVPen 10-role plan with 8 parallel reviewers, SQLite queue, retries/leases, usage ledger, memory and spend gates. Runtime Checks #135 passed on candidate SHA 4a20d1a8f6096dc5515584be603afe07f420750c.
- [ ] Review PR #4 and merge only after owner review.
- [ ] Run full local synthetic integration suite against exact merged SHA.
- [ ] Verify restart/recovery, backup/restore and queue-age monitoring on a real host.
- [ ] Configure one official model provider with exact tariffs and provider-side hard caps.
- [ ] Run harmless live inference and reconcile provider usage with Qudron ledger.
- [ ] Verify CVPen spend reservations with concurrent provider calls before customer data is enabled.

## Track B — Infrastructure
Evidence: Docker image/Compose and Cloudflare Worker adapter; Cloudflare Pilot CI #28 passed. Deploy #16 skipped actual deployment because secrets were absent.
- [ ] Owner creates Cloudflare Worker or supplies scoped token via GitHub Secrets.
- [ ] Configure CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID and QUDRON_API_TOKEN in GitHub Actions Secrets, never source/chat.
- [ ] Deploy and verify /health, unauthenticated 401, authenticated task creation/status, idempotency and daily cap.
- [ ] Verify real Workers AI inference and Neurons usage.
- [ ] Decide whether Python/Docker remains local/private or receives owner-approved host.
- [ ] Configure persistent storage, monitoring, backups and restore before internal live pilot.

## Track C — Owner communications
Evidence: Python Telegram long-polling gateway supports /help, /status, /usage and /task; Cloudflare adapter has optional webhook. No live bot is confirmed.
- [ ] Owner creates Telegram bot and configures TELEGRAM_BOT_TOKEN and numeric TELEGRAM_OWNER_CHAT_IDS in private secrets.
- [ ] Test owner allowlist with unauthorized test chat.
- [ ] Test task submission/idempotency, status and usage from phone.
- [ ] Add explicit approval workflow before customer messaging or publishing.
- [ ] Add daily digest and failure alerts after delivery/retry tests.

## Track D — Commercial operations
Evidence: service workflow design, generic payment HMAC primitive and roadmap; no CRM, PSP-specific adapter or verified merchant settlement.
- [ ] Launch one human-led offer from SERVICE_READINESS_AND_LAUNCH_CATALOGUE.md.
- [ ] Use minimal lead/order ledger with consent/source, scope, price, owner, next action and state.
- [ ] Track proposal/order acceptance separately from collected payment.
- [ ] Select licensed PSP and complete merchant onboarding; implement provider signature rules from official docs.
- [ ] Sandbox-test duplicate, wrong amount/currency/order, unsigned and unsettled callbacks.
- [ ] Implement idempotent order-to-fulfilment and human acceptance.
- [ ] Keep customer CV/PII disabled until tenant isolation, encryption, retention/deletion and file security are tested.

## Track E — Customer channels / Local bridge
- [ ] WhatsApp Business: official Meta account, number setup, opt-in, templates, signed webhooks, inbox/human handoff and privacy review.
- [ ] Social publishing: verify account/brand permissions and assets; require human approval and duplicate checks.
- [ ] Local desktop bridge: separate least-privilege account, explicit QudSystem folder allowlist, read-only default, audit log and confirmation for writes/uploads/deletes.
- [ ] Voice deferred until Egyptian number availability, pricing, consent/recording and regulatory requirements are verified.

## Immediate commercially usable offers
1. CVPen supervised review / role-tailored rewrite using minimized information and human QA.
2. QudSystem content starter pack (drafts/assets; owner/client approves publication).
3. AI/workflow opportunity assessment and public-source research report.
These are human-led service pilots, not a live Qudron subscription product.

## Acceptance gates
- Internal runtime pilot: synthetic task, real provider call, cost recorded, retry/restart demonstrated, artifact retrieved, backup restore tested.
- Owner console: authorized owner submits/checks task and receives report; unauthorized chat ignored.
- First paid service: written scope, verified payment evidence, human-reviewed delivery, customer acceptance and measured contribution margin.
- CVPen automation: secure upload/extraction, isolated storage, deletion, rendered DOCX/PDF QA, per-order cap and no anonymous providers.
- Customer automation: official channel, opt-in, audit log, human handoff and end-to-end tests.
- Production: monitored hosting, backup/restore, incident/rollback, security review, tenant boundaries and owner-approved budget.

## Non-claims
No Cloudflare deployment, Docker host, provider inference, Telegram bot, WhatsApp integration, PSP webhook, customer CV pipeline, public publishing, revenue or production uptime is claimed by this plan.