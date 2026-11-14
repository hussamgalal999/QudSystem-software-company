# Qudron Ultra-Precision Agentic & Service-Control Roles

This charter defines the **frontier agentic engineering**, **universal service integration**, and **ultra-precision review** roles added to [agent_registry.json](file:///c:/Users/Hossam%20Galal/Desktop/Qudron/ops/qudron-runtime/agent_registry.json) to realize Qudron's core vision:

1. **Universal Service & System Control:** Connect Qudron safely to any external or local service, API, MCP server, CLI, browser CDP, or OS/device surface to fulfill user requests end-to-end.
2. **Research-Lab Agentic Developer:** Operate at OpenAI/Anthropic research-lab engineering rigor — deterministic harnesses, self-healing multi-step loops, adversarial verification, and zero unverified claims.

---

## Added Specialist & Ultra-Precision Review Roles (6 Roles)

| Role ID | Profile | Purpose |
|---|---|---|
| `frontier_agentic_developer` | `reasoning` | Designs and implements lab-grade autonomous coding/reasoning loops, deterministic harnesses, bounded context, and verifiable patches. |
| `universal_service_integrator` | `reasoning` | Connects Qudron to any API, MCP server, CLI, browser CDP, or OS/device tool with strict schemas, idempotency, and least-privilege auth. |
| `tool_execution_reviewer` | `reasoning` | Audits tool contracts, parameter schemas, sandbox boundaries, dry-run/rollback paths, and side effects before execution. |
| `agentic_code_reviewer` | `reasoning` | Performs adversarial lab-grade code review on orchestration, state machines, concurrency, race conditions, and edge-case invariants. |
| `adversarial_eval_reviewer` | `reasoning` | Builds deterministic benchmarks, regression suites, failure-injection checks, and claim-vs-evidence audits. |
| `cross_service_security_reviewer` | `reasoning` | Enforces credential isolation, permission boundaries, spend/rate caps, data-classification rules, and human-approval gates. |

---

## Added Teams (3 Teams)

- **`frontier_agentic_engineering`**: `frontier_agentic_developer` (producer) + 5+ independent reviewers (`agentic_code_reviewer`, `adversarial_eval_reviewer`, `tool_execution_reviewer`, `cross_service_security_reviewer`, `reliability_engineer`, `evidence_checker`) — auto-expanded to 10 roles by `build_swarm_plan` when uncapped.
- **`universal_service_control`**: `universal_service_integrator` (producer) + `tool_execution_reviewer`, `cross_service_security_reviewer`, `agentic_code_reviewer`, `adversarial_eval_reviewer`, `reliability_engineer`, `privacy_qa`.
- **`ultra_precision_review_council`**: 10-member full council (`operations_commander`, `agentic_code_reviewer`, `tool_execution_reviewer`, `adversarial_eval_reviewer`, `cross_service_security_reviewer`, `evidence_checker`, `fact_checker`, `privacy_qa`, `policy_checker`, `qa_engineer`) for high-risk changes and release gates.

---

## Non-Negotiable Review Gates

1. **No Unverified Claims:** Every claimed capability, integration, or fix must cite exact commands, tests, and observed outputs (`adversarial_eval_reviewer` + `evidence_checker`).
2. **Fail-Closed Side Effects:** External writes, payments, publishing, device mutations, and credentialed actions require explicit allowlists and human-approval gates (`tool_execution_reviewer` + `cross_service_security_reviewer`).
3. **Lab-Grade Code Rigor:** Concurrency, timeouts, retries, idempotency, and state transitions must be explicitly tested (`agentic_code_reviewer`).
