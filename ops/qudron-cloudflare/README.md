# Qudron Cloudflare Free Control Plane

Serverless pilot adapter, separate from the Docker/Python runtime. It does not replace the Python runtime's full specialist registry, SQLite features, CVPen safeguards or operational capabilities.

## Components
- Workers: authenticated task intake and health endpoint.
- Workflows: durable execution, checkpointed steps, retries and status retrieval.
- Workers AI binding: initial generation plus a separate QA inference.
- SQLite-backed Durable Object: idempotent admission ledger and strict five-task/day internal pilot cap.
- Telegram webhook: owner-only research/draft task submission, status checks and automatic completion delivery to allowlisted owner chats.
- No VPS, Docker daemon or always-on process is required for this pilot.

## Free-plan envelope
Published limits include 100,000 Worker requests/day and 10 ms CPU per Worker invocation. Workflows Free includes 100,000 executions/day shared with Worker requests, 3,000 steps/day, 100 concurrent instances and 1 GB-month persisted state. Workers AI has a 10,000 Neurons/day free allocation. SQLite Durable Objects have a 5 GB account storage allowance and daily request limits. The pilot caps task intake at five per UTC day. These are quotas, not guaranteed throughput; inference can fail when the free AI allowance is exhausted.

References:
- https://developers.cloudflare.com/workers/platform/limits/
- https://developers.cloudflare.com/workflows/reference/limits/
- https://developers.cloudflare.com/workflows/reference/pricing/
- https://developers.cloudflare.com/durable-objects/platform/limits/
- https://developers.cloudflare.com/workers-ai/platform/pricing/

## Security boundaries
- All /api endpoints require a long random QUDRON_API_TOKEN bearer secret.
- Telegram webhook requires Telegram secret_token header and explicit numeric owner chat-ID allowlist.
- Only research and draft task kinds are accepted.
- Intake rejects common PII/credential patterns. This is a guardrail, not complete DLP.
- Use synthetic/public prompts only. No CVs, customer records, credentials, financial data or confidential files.
- Reviewed results can be delivered automatically to explicitly allowlisted owner Telegram chats when bot credentials are configured. They are never sent to customers or published automatically; owner review is required.
- Workflow inputs and outputs are persisted by Cloudflare Workflows; do not submit sensitive content.

## Bootstrap and deployment
1. Install Node.js 20+ and run npm install in this folder.
2. Create a Cloudflare API token scoped to the account with Workers Scripts:Edit, Workflows:Edit, Durable Objects:Edit and Workers AI:Read. Store it as GitHub Actions secret CLOUDFLARE_API_TOKEN; store the account ID as CLOUDFLARE_ACCOUNT_ID.
3. Set Worker secrets in Cloudflare: QUDRON_API_TOKEN (random 32+ characters), TELEGRAM_BOT_TOKEN (optional), TELEGRAM_WEBHOOK_SECRET (optional random 32+ characters), and TELEGRAM_OWNER_CHAT_IDS (owner numeric Telegram chat ID).
4. Run npm run typecheck, npm test and npm run build.
5. Deploy with npx wrangler deploy after account secrets and token are configured.
6. Configure Telegram webhook with official setWebhook method, deployed /telegram/webhook URL and the same secret_token.
7. Test /health, unauthenticated 401, authenticated task intake, task status, Telegram allowlist and actual Workers AI inference.

## Endpoints
- GET /health — liveness.
- POST /api/tasks — authenticated JSON with kind research or draft, title and prompt.
- GET /api/tasks/{taskId} — authenticated Workflow status and result.
- POST /telegram/webhook — Telegram webhook guarded by secret header and owner allowlist. Telegram commands: /task or /research for research, /draft for content drafts, and /status <task-id>.

## Not enabled
No Cloudflare account deployment, API token, Workers AI inference, Telegram webhook or bot credentials are claimed to be configured by this commit. No customer intake, CVPen, payment verification, file uploads, WhatsApp, voice, autonomous external publishing or financial actions are enabled.