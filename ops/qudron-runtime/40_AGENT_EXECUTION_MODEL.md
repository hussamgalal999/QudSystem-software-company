# Qudron 40-Specialist Execution Model

Date: 5 November 2026
Branch: `ops/qudron-40-role-agent-roster-2026-11-05`

## Important distinction

The registry defines 40 specialist **agent roles/prompts**. A role is not a separately hosted ChatGPT model instance. The runtime routes role prompts through configured model profiles. To execute these waves with OpenAI GPT models, the operator must configure a valid OpenAI API credential, an API-supported model ID, exact input/output rates, and provider-side hard limits. A ChatGPT consumer subscription is not an OpenAI API key or API credit.

This change prepares the 40-role plan and tests its integrity. It does not claim that 40 GPT instances have been provisioned or that any live model jobs have run.

## Eight execution waves

Each wave contains five distinct specialist roles. The eight wave teams assign all 40 registered roles exactly once. They are intended as eight separately queued tasks, not a 40-way fan-out inside one task.

| Wave | Team | Focus | Deliverable |
|---|---|---|---|
| 01 | `qudron_wave_01_architecture` | Architecture, priorities, evidence, product scope | Architecture decisions and acceptance criteria |
| 02 | `qudron_wave_02_runtime_models` | Queue, concurrency, model routing, reliability | Runtime changes and measured synthetic throughput |
| 03 | `qudron_wave_03_security_governance` | Threat model, privacy, authorization, compliance | Security findings and fail-closed controls |
| 04 | `qudron_wave_04_opendots_experience` | OpenDots control surface, Commander, language and support | Verified MCP capability contract and owner UX |
| 05 | `qudron_wave_05_platform_release` | Hosting, release, technical documentation and demos | Reproducible deployment package and release checklist |
| 06 | `qudron_wave_06_market_commercial` | Positioning, market, sales, finance | One evidence-backed QudSystem offer and unit economics |
| 07 | `qudron_wave_07_cvpen_product` | CVPen workflow, ATS, career facts and language QA | CVPen sandbox acceptance pack; no customer data until privacy gates pass |
| 08 | `qudron_wave_08_quality_payment` | Role matching, achievement evidence, readability, privacy and payment proof | Cross-functional QA report and payment acceptance test plan |

## Execution limits already present in the runtime

- Queue workers default to 8.
- Shared upstream model-call concurrency defaults to 16 and is hard-capped in code at 32.
- Routine per-task swarm size defaults to 5 and is currently hard-capped at 5.
- CVPen has a separate 10-role cap and up to 8 parallel reviews.
- Therefore, 40 registered roles can be scheduled as eight bounded five-role waves, but 40 simultaneous upstream model calls are not currently permitted.
- Do not raise concurrency caps merely to match a headline number. Validate provider RPM/TPM, host resources, latency, retries, and hard spend limits first.

## OpenAI/GPT activation gate

Before selecting an OpenAI GPT model profile:
1. Configure the OpenAI API key in the deployment secret manager only; never commit it or paste it into chat.
2. Select a model ID actually available to the API project.
3. Configure exact input/output token rates for every enabled profile.
4. Set provider-side hard spend caps and alerts, plus Qudron daily/monthly budgets.
5. Run a synthetic, non-sensitive smoke task and reconcile Qudron's usage ledger against provider usage.
6. Only then schedule the eight waves, starting with one wave and increasing gradually.

## Current blockers / proof required

- The connected Railway account currently exposes no projects; no always-on runtime host is verified.
- The repository's `.env.example` contains blank provider credential placeholders; it is not proof that a production OpenAI API key exists.
- No production deployment or real GPT API invocation is evidenced by this roster change.
- External actions, customer data, payments, public publishing, and paid infrastructure remain approval-gated.

## Acceptance criteria

A wave counts as executed only when its job ID, selected model ID, start/end status, provider usage, cost, final report, and QA result are retrievable. A registry entry, green CI run, or queued job alone is not execution evidence. All eight waves must complete with a final independent evidence review before Qudron is described as having completed the 40-specialist run.
