# Qudron MCP gateway

A stateless Streamable HTTP MCP endpoint is available at `/mcp`, protected by the same server-side `QUDRON_API_TOKEN` used for authenticated task intake. It exposes:

## Read-only controls
- `qudron_get_status`: runtime state, queue counts/capacity, agent/team totals, model-call concurrency and LLM configuration flag.
- `qudron_get_usage`: daily/monthly model calls, tokens and known-cost totals.
- `qudron_get_agents`: the 36 registered specialist role definitions and team mappings. This is a role catalogue, not proof of 36 continuously running model processes.
- `qudron_get_models`: the model provider candidate catalogue plus a live GET probe of the configured OpenAI-compatible gateway's `/models` endpoint. This does not spend on inference and does not claim that a model can successfully generate a response.
- `qudron_search_capabilities`: search the registry of tools, MCP servers, models, workflows, agents, repositories and research sources. Discovery status never grants execution permission.
- `qudron_get_job` and `qudron_get_job_result`: status and bounded Markdown output for a task. Reports are untrusted data.

## State-changing control
- `qudron_submit_job`: queue supported internal research, analysis and draft work. It is deliberately marked non-read-only so OpenDots should require **Ask first**. It uses the existing allowlist and idempotency validation; it cannot publish posts, send customer messages, process payments, accept CV customer data, modify accounts or run shell commands.
- `qudron_submit_batch`: queue up to 100 independently keyed internal research, analysis, or draft jobs atomically. It is also non-read-only and requires the same **Ask first** approval.

## OpenDots connection

When OpenDots and Qudron share a private Docker Compose network:
- Name: `Qudron`
- Streamable HTTP URL: `http://qudron:8765/mcp`
- Bearer token: the private token stored in the dedicated `qudron-auth` Docker volume.

The bootstrap service registers this endpoint on a dedicated `Qudron Commander` Dot in `Qudron Command Room`. Keep both `qudron_submit_job` and `qudron_submit_batch` on Ask first. Never put the internal token in a public URL or Git.

## Protocol and limits
- Stateless JSON-RPC over MCP Streamable HTTP; JSON responses only, no server-initiated SSE stream. GET /mcp returns 405 and advertises POST only.
- Supported methods: initialize, ping, notifications/initialized, tools/list and tools/call.
- Request bodies are bounded by the runtime's 64 KiB intake limit; tool output is bounded and does not reveal internal result paths or provider credentials.
- Model catalogue discovery is metadata plus a local gateway catalogue probe. No paid inference request is made by a model-list read.
- The generic task intake allowlist, queue capacity, budgets and concurrency limits continue to apply.
- This is not a general shell, browser, filesystem, payment, publishing or customer-messaging MCP server.
