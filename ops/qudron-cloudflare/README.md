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

## Cloudflare authentication and least privilege

This Worker uses the Workers AI **binding** (`env.AI.run()`), not the Workers AI REST API. The binding supplies the capability inside the Worker; do not create a separate Workers AI REST token for this runtime.

For Wrangler deployment, use an account-owned Cloudflare API token and the current Workers role model:

1. **Preferred bootstrap:** create the `qudron-control-plane` Worker once from the Cloudflare dashboard. Then create an account-owned API token with the **Workers Editor** role scoped only to that Worker. Store the token as GitHub Actions secret `CLOUDFLARE_API_TOKEN` and the account ID as `CLOUDFLARE_ACCOUNT_ID`.
2. **Alternative first deployment:** if the Worker does not exist and you create it through Wrangler, Cloudflare requires **Workers Admin** at the Workers product scope for that initial creation. After the Worker exists, replace the bootstrap token with a new **Workers Editor** token scoped only to `qudron-control-plane`.
3. Durable Objects do not have separate roles; access follows the Worker that implements them. The Worker/Workflow deployment is authorized through the Workers role. Do not look for separate `Workflows:Edit` or `Durable Objects:Edit` token permissions.
4. No Workers Routes permission is needed for the current `workers.dev` configuration. Add zone-scoped Workers Routes write access only if a future deployment explicitly creates or changes a zone route/custom domain.

The token is used only by GitHub Actions/Wrangler. It is never placed in source code, Worker variables, chat, screenshots or issue comments.

Official references:
- https://developers.cloudflare.com/workers/authorization/
- https://developers.cloudflare.com/workers/authorization/workers/
- https://developers.cloudflare.com/workers/authorization/durable-objects/
- https://developers.cloudflare.com/workers/runtime-apis/bindings/

## Bootstrap and deployment
1. Create or select the Cloudflare account and copy its Account ID.
2. Apply the least-privilege token procedure above.
3. Add GitHub Actions secret `QUDRON_API_TOKEN` (generate a random 32+ character value; never send it in chat). The deployment workflow installs it into the Worker as a secret.
4. Optional Telegram secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` (random 32+ characters), and `TELEGRAM_OWNER_CHAT_IDS` (owner numeric Telegram chat ID). If a bot token is present, the other two are required and the workflow installs all three as Worker secrets.
5. Run the GitHub Actions workflow named Deploy Qudron Cloudflare pilot. It runs typecheck, tests, Wrangler dry-run, deployment and runtime secret provisioning. If required secrets are missing, the workflow records an explicit skipped-deployment summary and does not change Cloudflare resources.
6. Configure Telegram webhook with official setWebhook method, deployed `/telegram/webhook` URL and the same `secret_token`.
7. Test `/health`, unauthenticated 401, authenticated task intake, task status, Telegram allowlist and actual Workers AI inference.

## Endpoints
- GET `/health` — liveness.
- POST `/api/tasks` — authenticated JSON with kind research or draft, title and prompt.
- GET `/api/tasks/{taskId}` — authenticated Workflow status and result.
- POST `/telegram/webhook` — Telegram webhook guarded by secret header and owner allowlist. Telegram commands: `/task` or `/research` for research, `/draft` for content drafts, and `/status <task-id>`.

## Not enabled
No Cloudflare account deployment, API token, Workers AI inference, Telegram webhook or bot credentials are claimed to be configured by this commit. No customer intake, CVPen, payment verification, file uploads, WhatsApp, voice, autonomous external publishing or financial actions are enabled.
