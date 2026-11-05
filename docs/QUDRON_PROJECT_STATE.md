# Qudron — authoritative project state

**Snapshot:** 5 November 2026 (Africa/Cairo)  
**Repository:** hussamgalal999/QudSystem-software-company  
**Default branch:** main  
**Continuity branch:** feat/qudron-continuity-memory-registry-2026-11-05  
**Task registry:** ops/qudron-runtime/project_task_registry.json

## What is authoritative

1. The Git repository is the source of truth for code, architecture decisions, documented task status and release evidence.
2. The runtime SQLite database is the source of truth for queued jobs, agent-stage checkpoints, per-agent memories and external task references while the runtime host is running.
3. The task registry records all known work and technical debt. It must never be silently truncated. New work is appended; completed work is closed only with evidence.
4. OpenDots is the owner-facing control surface. Qudron is the execution engine. Artemis is the Android specialist. External providers remain separate workers whose task IDs and results must be recorded by Qudron.
5. A new ChatGPT conversation must read this file, the JSON task registry, relevant open pull requests, the latest workflow run and the last commit before making claims about project state. See CONTINUITY_PROTOCOL.md.

## Current measured inventory

The registry contains **63 tracked tasks** in this snapshot. Status is explicit and evidence-based:

| Status | Count |
|---|---:|
| CI-verified implementation | 3 |
| Implemented, CI pending | 6 |
| Implemented, live/unverified | 9 |
| Open pull request | 1 |
| Candidate provider, not enabled | 3 |
| Blocked by owner/external setup | 10 |
| Planned | 11 |
| Not started | 16 |
| Strategic target, not measured | 2 |
| Needs owner review | 1 |
| Pending CI gate | 1 |
| **Total** | **63** |

These counts are the status distribution, not a weighted percentage and not a claim that the 63 tasks are all production-ready. Each task now has a specialty-specific verification profile in `ops/qudron-runtime/project_task_registry.json`. See `docs/QUALITY_VERIFICATION_FRAMEWORK.md` for maturity levels, evidence records, scoring, and release gates.

## Verification and quality scoring

- Each backlog item has a specialty-specific verification profile; CI, integration, live, operational and independent acceptance are separate maturity levels.
- Blocked and not-run checks are never counted as passes. A missing credential cannot block unrelated code work, but it also cannot be reported as a live integration.
- The remote-compute fabric is now an explicit P0 task covering authorized remote GPU/CPU providers, remote Ollama, cloud computers, notebooks and browser workers. No free high-performance GPU is claimed until measured.

## Workforce and concurrency

- The branch registry now contains **48 specialist role identities across 31 teams**. These are configured identities, not active workers or model sessions.
- Routine swarm execution is intentionally bounded; the existing runtime defaults to five specialist stages for routine work and a separate ten-role CVPen workflow. Existing shared model-call slots impose a global concurrency ceiling.
- The 10,000-worker goal is a **logical capacity target**. A measured scheduler, admission controller, provider quota plan and load test are still required before claiming that scale.
- 100 billion tokens is a **capacity objective**, not a current free entitlement. Only verified provider quotas and successful inference measurements count toward it.

## Continuity implementation on the current branch

New branch work adds:
- SQLite-backed memory scoped to agent ID + project.
- Job + agent + stage checkpoints for resumable non-sensitive work.
- Execution events for started, retried, resumed, completed and failed agent stages.
- A persistent external-agent ledger for provider name, remote task ID, local job ID, status, task URL and result reference.
- MCP read-only tools for continuity snapshots and one agent's project-scoped memory.
- A Manus API v2 adapter with asynchronous task creation, message polling, task detail and follow-up messages; disabled unless an authorized credential and owner opt-in are configured.
- An OpenDots bootstrap page tree for dashboard, tasks, specialist workforce, memory/resume, external agents, model supply, Android operations, portfolio, integrations and governance.

**Important:** these code additions are not yet CI-verified, deployed or connected to live accounts on this snapshot. The current branch must pass CI and be reviewed before merge. The OpenDots pages are created only when the optional OpenDots stack/bootstrap is actually run.

## Latest engineering corrections on the active branch

- The runtime Docker image now copies all root-level Python modules and JSON registries, including the continuity and agent-fabric modules; CI now checks that key modules import from inside the built image.
- The continuity store now imports the time module required by its cloud outbox and has an outbox-persistence regression test.
- The runtime now runs a bounded cloud-memory outbox sync loop when both owner-provisioned URL and token are present. Without those secrets, cloud sync remains disabled; no live cloud deployment is claimed.
- PR #24 adds the evidence framework, the explicit remote-compute fabric backlog item and the provider qualification catalog. Its latest Actions run has not yet been observed; do not mark it CI-verified until a run completes on the exact head SHA.

## External integrations — honest current state

| Integration | Code / design | Live state |
|---|---|---|
| Artemis Android MCP | Host bridge and Qudron MCP integration on PR #22 | PR #22 is Draft/open; physical phone E2E not run |
| OpenDots Commander | Bootstrap and private MCP connection code | No deployed OpenDots/Intelligence project is verified |
| OpenDots subpages | Idempotent bootstrap page tree on this branch | Not created in a live workspace yet |
| OpenDots per-Dot computers | Optional supervisor/computer Compose overlays | Not enabled on a live host |
| Manus API v2 | Opt-in adapter on this branch | No API/OAuth credential or live task test |
| Gemini / DeepSeek / Qwen / GLM | Provider candidates and gateway groundwork | No complete per-provider live qualification; paid-only paths are ineligible by default |
| FreeLLM | Optional private sidecar and CI smoke tests | CI health/auth is not proof of successful upstream model inference |
| Metricool | Read/analytics and draft-only adapter | Qudron host API token is not connected |
| Telegram | Owner-only polling gateway code | Bot token and owner chat allowlist not configured |
| WhatsApp / PSTN | Architecture and roadmap | Not connected |
| Cloudflare Worker | Separate edge adapter code | No deployment or live Workers AI proof |
| GitHub inventory | Historical snapshot of 503 repositories | Dynamic runtime scan not verified; coverage of private repos is incomplete/unknown |

## Next execution order

1. Pass CI for the continuity branch; repair all failures; verify 48 role identities across 31 teams, agent memory, checkpoint-resume, MCP and OpenDots page provisioning tests.
2. Open and review a dedicated PR for the continuity branch. Do not merge automatically.
3. Complete Artemis PR #22 review separately; then authorize the phone and run physical-device E2E.
4. Provision OpenDots only on an owner-approved host; connect its Intelligence service; run the bootstrap and verify that the subpages exist.
5. Verify free/authorized provider access one source at a time, with exact model IDs, data terms, quota, quality, latency and measured inference. No silent paid fallback.
6. Enable Manus only after account entitlement/credits and permitted API/OAuth access are confirmed; then test one harmless task and a follow-up.
7. Deploy Qudron privately with persistence, backup/restore, monitoring and owner-only access.
8. Start the read-only GitHub portfolio scan and convert the historical 503-repository snapshot into an evidence-backed review; then prioritize the 500+ project pipeline.
9. Close security, customer-data, payment, channel and approval gates before activating customer-facing or financial operations.

## Non-claims

No claim is made that all work is running, that all providers are connected, that 10,000 or 100 agents are active, that 100B tokens are available, that Android has been controlled, that the 500+ projects have been reviewed, or that Qudron is deployed in production. These states require fresh evidence.
