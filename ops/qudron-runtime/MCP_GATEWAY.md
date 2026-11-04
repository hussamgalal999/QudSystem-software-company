# Qudron MCP gateway

A stateless Streamable HTTP MCP endpoint is available at `/mcp`, protected by the same server-side `QUDRON_API_TOKEN` used for authenticated task intake. It exposes only:
- Read-only service status and model usage.
- Read-only job status and bounded Markdown report retrieval.
- An internal draft/research job submission tool.

The submission tool is **not read-only**. MCP clients such as OpenDots should leave its default **Ask first** approval enabled. It uses the existing `enqueue_api_job` validation and idempotency rules, so unsupported job types (including CV customer-data, customer support with private records, payments, incident triage, publishing and external messages) are rejected.

## OpenDots connection

When OpenDots and Qudron share a private Docker Compose network, create a connection on the selected Dot:
- Name: `Qudron`
- Streamable HTTP URL: `http://qudron:8765/mcp`
- Bearer token: the value of `QUDRON_API_TOKEN` stored in the private host `.env`

Only connect the Qudron tools to Dots that need them. Keep `qudron_submit_job` on Ask first. This token is an internal service credential, not a model-provider API key. Never place it in a public URL or Git.

## Protocol and limits

- Stateless JSON-RPC over MCP Streamable HTTP; JSON responses only, no server-initiated SSE stream.
- Supported methods: initialize, ping, notifications/initialized, tools/list and tools/call.
- Request bodies are bounded by the runtime's 64 KiB intake limit.
- Tool output is bounded and does not reveal internal result paths or provider credentials.
- The generic external intake allowlist and queue idempotency continue to apply.
- This is not a general shell, browser, filesystem, payment, publishing or customer-messaging MCP server.
