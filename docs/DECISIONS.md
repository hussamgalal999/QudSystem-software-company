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
