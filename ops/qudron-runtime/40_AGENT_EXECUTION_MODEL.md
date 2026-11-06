# Qudron Specialist Catalogue & Dynamic Execution Model

Date: 6 November 2026
Branch: `feat/qudron-continuity-memory-registry-2026-11-05`

## Roles, instances, tasks, processes and model calls are different

The current candidate registry contains **48 specialist role identities across 31 teams**. The owner requirement is 40+ specialties as a minimum, not a product-wide agent limit. A role definition is a reusable capability and prompt. A task-scoped agent instance is one assignment of that capability to one project/task. A task run is the durable execution record. A worker process is an operating-system process consuming queued work. A provider/model call is an individual inference request. None of these counts should be reported as another.

The registry and the provider-neutral fabric are foundations; they do not provision one hosted model session per role. A configured free/authorized provider may serve many role assignments subject to its verified concurrency, quota and terms. When no qualified provider is available, tasks remain queued or fail with a visible provider-required state.

## Dynamic task planning

- The planner now selects **every role listed in the selected team by default**. It no longer silently truncates routine teams to five or CVPen teams to ten.
- An explicit task-scoped role-assignment guard is configured by `QUDRON_MAX_ROLE_ASSIGNMENTS_PER_TASK` (default 10,000; hard safety ceiling 10,000). This caps planned role assignments only; it does not provision or count 10,000 persisted agent instances.
- A task can still request an intentional subset through an explicit `max_agents` argument for bounded testing or specialist workflows.
- Independent review stages fan out up to `QUDRON_MAX_PARALLEL_REVIEWS` (default 16; hard ceiling 32). Actual upstream calls remain governed by the shared SQLite-backed global model-call slot limit.
- Queue workers default to eight and remain capped at eight in this runtime. Provider RPM/TPM, quota, latency, network health and host resources remain binding. Queue capacity is not a guarantee of throughput.
- Eight five-role waves are registered to cover the original 40-specialist programme. They are separate task/workflow units, not a claim that 40 model requests run simultaneously.
- The workflow DAG engine supports up to 128 concurrent ready nodes per workflow. This is a scheduler admission ceiling, not a provider or hardware capacity claim.

## Free and authorized provider gate

The default provider policy must remain free-only and explicitly authorized. A route is eligible only when its access method is permitted, its price class is `free` or `free_compute`, a recent health probe exists, its quality score meets the configured threshold, its capabilities match the task, and the task's data classification is allowed.

Do not scrape browser cookies, reuse consumer sessions as undocumented APIs, bypass quotas, rotate accounts to evade limits, or silently fall back to paid inference. Never send customer CVs, payment records, secrets, or confidential content to anonymous free endpoints. If all eligible providers are unavailable, preserve the task and report `NEEDS_PROVIDER`; do not silently substitute a weak local model.

## Provider and compute resource controls

- The shared model-call gate defaults to 16 and has a code ceiling of 32. Increase it only after provider quotas and host capacity have been measured.
- Remote compute is a separate, ephemeral/persistent resource decision. Kaggle notebooks, Hugging Face ZeroGPU and Colab are candidates with distinct terms and session limits; none is a connected always-on worker by virtue of appearing in the catalog.
- Owner authorization, recent health, CPU/RAM/VRAM, runtime window, quota, data class and per-provider lease caps are checked before a compute lease is admitted.
- Provider adapters and real account probes are still required before any remote compute resource can be marked enabled.

## Verification boundary

The tests validate role-registry integrity, complete team planning, resource admission contracts and deterministic mock routing. They do not prove 48 active agents, 10,000 simultaneous model calls, a live free GPU, or a production deployment. A task counts as executed only when its task/run ID, selected role/provider/model, timestamps, usage (when available), output artifact and independent verification result are retrievable.

## Next acceptance gates

1. Persist explicit task-scoped agent-instance IDs separately from stable role IDs and record instance lifecycle transitions.
2. Wire the new agent fabric into the worker and MCP submission path, preserving provider-specific concurrency and fail-closed approval.
3. Connect optional cloud memory retrieval to the runtime context packet, while retaining local SQLite as the execution source of truth.
4. Add a load test that proves 40+ role assignments can be planned and admitted without hidden role truncation, with global provider-call limits enforced.
5. Run owner-authorized live probes for each candidate provider and a physical Android Artemis E2E test before claiming those integrations are live.

No merge or production activation is implied by this document.
