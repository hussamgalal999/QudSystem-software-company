# Qudron Architecture Decisions

## ADR-2026-11-05-ARTEMIS-001 — Keep Artemis independent and integrate over MCP

**Status:** Accepted for implementation.

**Context:** Qudron needs real Android device perception and interaction without becoming an Android automation framework itself.

**Decision:**
- Treat upstream google/artemis as an independently installed specialist service.
- Use its native MCP server over stdio as the primary tool protocol.
- Run a small authenticated Qudron bridge on the Android host; the bridge starts the upstream MCP process and does not vendor Artemis code.
- Expose a narrow Android tool surface through Qudron's existing MCP gateway.
- Keep Qudron as executive orchestrator; Artemis owns Android perception, device execution, traces and diagnostics.

**Consequences:** Artemis dependencies and ADB remain on the device host. Qudron's existing container only needs outbound HTTP access to the bridge. The bridge must be protected by a bearer token, private network and firewall. The upstream Artemis daemon HTTP API is not exposed directly.

## ADR-2026-11-05-ARTEMIS-002 — Route Flash and Pro by risk

**Status:** Accepted for implementation.

Use Flash for deterministic, low-risk navigation and short operations. Use Pro for branching exploration, system diagnostics, checkpoint verification and tasks requiring a report. Never describe Flash as providing Pro's safety net or Checker verification.

## ADR-2026-11-05-ARTEMIS-003 — Approval boundaries

**Status:** Accepted for implementation.

- Starting a device task and stopping/steering a running task are state-changing and must remain approval-gated.
- Status, device observation, trace inspection and read-only diagnosis may be marked read-only.
- Automatic repair, emulator launch, credential verification and arbitrary host shell access are not exposed in the initial integration.
- Never place device credentials, API keys, ADB private keys or session cookies in Qudron prompts or Git.

## ADR-2026-11-05-ARTEMIS-004 — Evidence before success

**Status:** Accepted for implementation.

A submitted task is not a completed task. Qudron must retain the Artemis trace ID, poll for a terminal status, inspect the trace, and verify the requested UI state. A natural-language success sentence without trace evidence is insufficient.

## ADR-2026-11-05-ARTEMIS-005 — No upstream code copy

**Status:** Accepted for implementation.

Qudron stores only its own bridge, adapter, configuration examples, tests and documentation. Artemis remains an external dependency pinned and upgraded independently.

## ADR-2026-11-05-ARTEMIS-006 — Verify the full path through Qudron MCP

**Status:** Accepted for implementation.

The physical Android end-to-end test must invoke `qudron_android_run_task`, `qudron_android_task_status` and `qudron_android_inspect_trace` through Qudron's authenticated `/mcp` endpoint. It must not bypass Qudron by calling the host bridge directly. The test requires explicit opt-in, an owner-authorized device serial, a completed terminal state and a battery percentage in the inspected trace. The bridge resolves artifact paths from the same configured Artemis checkout used to launch MCP; artifacts outside that checkout or outside the bounded trace/screenshot allowlist are rejected.


## ADR-2026-11-05-ARTEMIS-007 — Mark device-changing tools destructive

**Status:** Accepted for implementation.

Android task execution and task steering can change the state of a real device. Their Qudron MCP tool annotations must therefore set both `readOnlyHint=false` and `destructiveHint=true`, in addition to requiring owner approval. Status, observation, trace inspection and read-only diagnosis remain read-only. Tool annotations are advisory metadata; authorization and approval policy must still be enforced by the connected MCP client and Qudron runtime.


## ADR-2026-11-05-ARTEMIS-008 — Keep Qudron secrets out of Artemis child environment

**Status:** Accepted for implementation.

The host bridge authenticates Qudron requests with its own bearer token. The spawned Artemis MCP process does not need that token or Qudron runtime credentials. The bridge removes `ARTEMIS_BRIDGE_TOKEN` and all `QUDRON_*` variables from the child environment while preserving Artemis provider configuration and the pinned checkout's `PYTHONPATH`. This reduces accidental secret exposure without preventing Artemis from using its own configured providers.

## ADR-2026-11-05-MODEL-ACCESS-001 — Quality-gated, authorized model access

**Status:** Accepted product constraint; implementation pending.

**Context:** Qudron needs a durable supply of capable model inference without making paid API credentials the default dependency and without filling the system with weak local models merely because they are free.

**Decision:**
- Admit a model/provider only when it meets the capability threshold for its assigned workload and offers a documented, authorized access path that is free to use or backed by genuinely free compute.
- Prefer official web/app access, official free inference tiers, research/education grants, and provider-published free compute programs where their terms permit the intended automation. Do not bypass authentication, rate limits, quotas, paywalls, account restrictions, or provider safeguards.
- Do not scrape private session state, export browser cookies/tokens, or store raw session credentials in repository files. If an official browser workflow is used, the account owner signs in interactively and the session remains in the user's protected browser profile; automation must respect provider terms and access controls.
- Do not make paid API keys, paid subscriptions, or paid inference a required path for the core product. Optional paid adapters may exist only as disabled, separately approved extensions and must never silently take over.
- Reject low-capability local models as general-purpose workers. A local model may be admitted only for a bounded task where measured quality, latency and resource use meet that task's acceptance criteria.
- Maintain a live provider registry with access method, model/version, capability evidence, free quota/compute conditions, concurrency, latency, uptime, last successful probe, and failure/cooldown state. Never label a provider "available" merely because its landing page or model catalogue responds.
- Route only to providers that pass a workload-specific quality check and a current authorized-access probe. Use fair quota-aware scheduling and failover only to another eligible source; do not manufacture extra quota by account rotation or evasion.
- Treat the 100-billion-token objective as a capacity target, not an existing entitlement. Report measured usable capacity separately from theoretical provider limits and estimates.

**Consequences:** Qudron's model router must be capability- and policy-aware rather than a generic API-key round-robin. Provider adapters need explicit access modes and health evidence. No model is promoted to production solely because it is free or easy to connect.
