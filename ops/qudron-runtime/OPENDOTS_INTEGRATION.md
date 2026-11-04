# OpenDots as the Qudron control surface

OpenDots remains a separate upstream application. Qudron remains the autonomous execution engine. The integration keeps their application databases, runtimes, and deployment lifecycles separate; OpenDots controls Qudron through a private Streamable HTTP MCP connection.

## Start the private stack

From `ops/qudron-runtime`:

```sh
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.opendots.yml --profile opendots up -d --build qudron freellm opendots opendots-bootstrap
```

OpenDots listens on `http://127.0.0.1:4310`. Qudron's authenticated API/MCP is bound to `127.0.0.1:8765`; OpenDots reaches it over the private Compose network, not through the public host port. Keep both ports private. For remote access, use a VPN or an authenticated HTTPS reverse proxy and set `OPENDOTS_APP_ORIGIN` to the exact public origin.

## What is provisioned automatically

The one-shot `opendots-bootstrap` service uses the official OpenDots owner API. It creates a `Qudron Command Room` Space and a dedicated `Qudron Commander` Dot, then registers or refreshes the Qudron MCP connection on that Dot.

The connected Dot is the visible command surface for Qudron, not a second execution engine. OpenDots handles conversation, voice UI, approvals, pages, and the optional computer surface; Qudron owns the agent workforce, durable jobs, model routing, tool policy, execution, retries, and reports. The Dot should delegate substantive work to Qudron rather than create a competing agent swarm inside OpenDots.

The connected Dot exposes:
- Qudron service state, registered agents/teams, queue counts and queue capacity.
- Model call/token usage and known-cost totals.
- Job status and completed Markdown report retrieval.
- An approval-gated tool to submit one supported internal research, analysis, or draft job.
- An approval-gated batch tool for up to 100 independently keyed jobs, atomically admitted into Qudron’s durable queue.

The submit tool is explicitly non-read-only. OpenDots therefore marks it Ask first and presents the exact request to the owner before it is queued. It cannot use this MCP connection to publish to Facebook, send customer messages, process payments, access CV customer data, change provider accounts, or execute arbitrary shell commands. Those capabilities require their own narrowly scoped integrations and approval policies.

The Qudron API token is generated into the dedicated `qudron-auth` Docker volume and is mounted read-only into the one-shot bootstrap container. OpenDots does not receive Qudron's task database, reports, GitHub token, Telegram bot token, or model-provider keys. The bootstrap reads the OpenDots owner token from the persistent `qudron-opendots-data` volume. No token is printed or committed to Git.

If the Qudron token is rotated or the existing MCP connection becomes unauthorized, bootstrap replaces only the named Qudron connection and refreshes its tool catalogue. Existing OpenDots user data and unrelated connections are preserved.

## Models and privacy

OpenDots uses the private FreeLLM OpenAI-compatible sidecar only when `OPENDOTS_ENABLE_KEYLESS_MODEL=true` and no custom API key/base URL is supplied. This provides a no-provider-key path through documented anonymous/free endpoints, but those endpoints have small and changing quotas and may log prompts. **Use this mode only for public, non-sensitive conversations.** Do not send CVs, customer records, credentials, private source code, payment evidence, legal/financial records, or confidential QudSystem material through anonymous endpoints.

For private/commercial work, configure a provider key and model endpoint you are authorized to use:
- `OPENDOTS_OPENAI_API_KEY`
- `OPENDOTS_OPENAI_BASE_URL`
- `OPENDOTS_OPENAI_MODEL`

The FreeLLM router is a failover adapter, not an unlimited model source. Provider routing, supported tools, models, rates, and data terms must be checked live. A model name alone does not guarantee that a particular reasoning mode, computer-use feature, or Responses/Messages-specific API is supported by this OpenDots release.

## CopilotKit conversation service is separate

OpenDots does not keep full conversation history in its local SQLite file. It requires a CopilotKit Intelligence project key or a licensed self-hosted Intelligence service, separately from its model provider. Without that, the application and Commander Dot can be provisioned, but the UI remains in setup mode and cannot create live conversations.

Configure `OPENDOTS_CPK_INTELLIGENCE_API_KEY` (hosted project) or the supported `OPENDOTS_INTELLIGENCE_API_KEY` and endpoint settings for your licensed deployment. Do not paste account passwords into chat. The official login/project-selection flow creates a project-scoped credential; store that value only in the private host `.env`/secret manager.

The local Intelligence evaluation also requires a CopilotKit sign-in and a Docker host meeting the upstream resource requirements. It is not equivalent to the Qudron FreeLLM model sidecar and should not be assumed to fit on a small 10 GB desktop.

## Voice and phone calls

OpenDots includes browser-based WebRTC voice calls. They require a supported Realtime speech provider key and model; set `OPENDOTS_VOICE_API_KEY` and `OPENDOTS_VOICE_MODEL`. The default model label in the sample is `gpt-realtime-2.1`, but it must be available for the account. These are calls within the OpenDots app, not international telephone calls. PSTN/SMS requires a separate approved telephony provider and verified number/account.

## Computers and browser access

OpenDots supports per-Dot computers through the upstream OpenBot supervisor and computer service. The standard OpenDots profile does not create those computers automatically. The optional computer stack requires Docker Engine, persistent storage, CPU/RAM headroom, and a supervisor that alone owns Docker-socket access. Do not mount the host Docker socket into OpenDots or into an agent's own computer. Standard containers share the host kernel; gVisor is available only if the host already supports it.

Qudron can continue running background jobs if OpenDots is closed. Stopping OpenDots does not stop Qudron workers. Likewise, the OpenDots UI cannot make a provider or cloud VM persistent if the underlying host is unavailable.

## Verification and current boundaries

- Source: upstream OpenDots is pinned as a Git submodule under `integrations/OpenDots` with its MIT license preserved.
- MCP: Qudron endpoint is private, token-protected, and exposes only the listed safe read tools plus the approval-gated submit tool.
- Bootstrap: creates a dedicated Commander Dot and idempotently attaches the MCP server using official OpenDots API routes; no direct SQLite writes.
- CI: checks Python compilation, bootstrap tests, shell syntax, Compose configuration, Qudron/FreeLLM/OpenDots image builds, and sidecar bearer authentication.
- Not yet a production deployment: no remote always-on VM or reverse proxy is provisioned here, no CopilotKit Intelligence project key is available in the host, and no Realtime voice key or PSTN/SMS service is connected.


## Provider capability tiers

OpenDots and Qudron use separate model-routing decisions. The visible Dot can use a fast conversational model for short UI turns, while Qudron chooses a task-specific provider/model for each delegated job. Keep the provider catalogue dynamic: refresh official model lists and capabilities (reasoning, tools, vision, audio, context, output limits, region/account access, and API compatibility) rather than pinning "latest" names forever.

The top-tier Anthropic, OpenAI and Google models are **not keyless services**. Use their official APIs or an authorized cloud marketplace route (such as Bedrock or Vertex) when credentials and entitlements are configured. A free anonymous gateway may supply lightweight public research/draft models, not an Opus-/frontier-GPT-/Gemini-Pro-equivalent guarantee. Never disguise one model as another or route sensitive data to anonymous endpoints.

Voice calls inside OpenDots use its configured Realtime speech provider. They are browser/WebRTC calls, not PSTN. Qudron can continue the long-running delegated job while the Dot stays on the call. International phone calls and SMS require a separate verified telephony account/number and explicit regional compliance; do not simulate them with browser voice.
