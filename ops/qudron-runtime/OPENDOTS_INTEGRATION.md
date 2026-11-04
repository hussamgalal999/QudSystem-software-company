# OpenDots integration and operating boundary

Qudron pins the upstream MIT-licensed CopilotKit/OpenDots source in `integrations/OpenDots` as a Git submodule. This preserves upstream history and license notices rather than copying or rewriting the project.

## Start the combined local/private stack

From `ops/qudron-runtime`:

```sh
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.opendots.yml --profile opendots up -d --build qudron freellm opendots opendots-bootstrap
```

OpenDots listens on `http://127.0.0.1:4310`. Qudron API/MCP listens on `127.0.0.1:8765`. Both are bound to host loopback; place an authenticated reverse proxy or private VPN in front before remote access.

The runtime generates the Qudron API bearer token under `data/api_token` and OpenDots generates its owner token under the `qudron-opendots-data` volume at `.owner-token`. Tokens are not printed. A bootstrap container calls OpenDots' authenticated workspace API, finds the initial Dot, registers the `http://qudron:8765/mcp` Streamable HTTP endpoint, and refreshes the exposed tool catalogue. The submission tool is non-read-only and should remain Ask first in OpenDots.

## Model and conversation requirements

Qudron's default model route uses its FreeLLM sidecar in keyless/auto mode only for public, non-sensitive research and draft tasks. It is a free-tier router with provider-specific quotas, not a free source of unlimited inference. The worker blocks keyless inference for customer records, CVs, support, payments, engineering/security reviews and prompts matching its PII/secret redactor. Do not send confidential code or customer data to anonymous upstream endpoints.

OpenDots conversations require a CopilotKit Intelligence project key or a licensed self-hosted Intelligence service. The stack starts in setup mode if the key is absent; it does not fabricate model replies. After connecting Intelligence, configure an approved model provider. You may set `OPENDOTS_ENABLE_KEYLESS_MODEL=true` to route its OpenAI-compatible compute model through the internal FreeLLM sidecar, but this is suitable only for public/non-sensitive conversations. It does not remove the separate Intelligence requirement, and it should stay false where users may enter private data.

## Computer and browser capabilities

The standard OpenDots app and Qudron MCP connection do not install a privileged Docker host socket inside Qudron. To give each Dot a persistent computer, use the upstream OpenDots/OpenBot computer overlay only on a Docker host where the supervisor can safely own the Docker socket. Do not mount the host Docker socket into the app or a Dot container. The supervisor creates isolated per-Dot containers and persistent browser/workspace volumes, but standard Docker containers share the host kernel. gVisor can be configured only where the host already supports it.

For a cloud browser requiring a saved login, use an isolated browser profile and the site's official sign-in. Do not put passwords in this repository or chat, and do not bypass MFA, bot checks, paywalls, or provider restrictions.

## Current status

- Source pin and MCP integration are committed on the Qudron feature branch; they are not in `main` until CI passes and the PR merges.
- The compose overlay is a deployable recipe, not a live deployment.
- No CopilotKit Intelligence project key, OpenDots account login, long-running VM, or remote host is provisioned by this change.
- No social account is connected for auto-publishing. Metricool remains draft-only until its API access is configured and a publication flow has explicit account-side authorization.
