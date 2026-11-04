# Qudron Runtime — persistent background worker

A self-hosted, restartable task runner for QudSystem. It provides recurring task scheduling, a durable SQLite queue, concurrent workers, retry/backoff, stale-job recovery, logs, report files, and a health endpoint.

IMPORTANT: this does not keep ChatGPT alive. It runs independently on infrastructure controlled by QudSystem and calls an OpenAI-compatible LLM endpoint only after one is configured.

## Included recurring roles
- CVPen growth research and experiments
- QudSystem social content drafts
- Short-form video scripts and bilingual subtitle drafts
- Sales segments and outreach templates
- SEO planning

These are role-specific jobs processed by a shared model endpoint, not separately hosted AI models or human employees.

## Start with Docker
1. Copy this folder to an always-on computer or server.
2. Copy .env.example to .env.
3. Configure LLM_BASE_URL and LLM_MODEL for a reachable OpenAI-compatible model endpoint. If a model server is on another machine, use its LAN address, not 127.0.0.1.
4. Run: docker compose up -d --build
5. Check: curl http://localhost:8765/health and docker compose logs -f qudron

Completed drafts are saved under reports/; durable task state is in data/; logs are in logs/.

## Run without Docker
Requires Python 3.10+. Copy .env.example to .env, export the values with your shell or secrets manager, then run python qudron_worker.py.

## Add scheduled tasks
Edit schedule.json. Each item needs a unique id, every_minutes >= 1, role, supported task_type, title, and prompt. Supported types: research, social_post_draft, video_script, translation, seo_plan, lead_research.

The scheduler currently uses UTC interval timing; the timezone field documents the intended business timezone but does not implement local wall-clock scheduling.

## Reliability
- SQLite WAL durable queue
- Atomic job claiming across worker threads
- Capped exponential retry backoff
- Stale lease recovery after worker crash/restart
- Docker restart policy and health check
- JSON status at /health and /status

## Safety boundaries
The runtime only creates drafts/research artifacts. It does not publish, message leads, send email, buy ads, spend money, transfer funds, or modify production services. Add those only with verified provider credentials, explicit destination checks, audit logs, and approval controls.

Never commit API keys. Keep .env private, restrict health endpoint network access, and back up the database and reports.

## Production checklist
1. Configure and test a model endpoint.
2. Deploy to an always-on host with backups and monitoring.
3. Add approved integrations with explicit account identity and human approval gates.
4. Validate output quality and factual claims before using leads or publishing.
5. Add a managed queue/database and secret manager before scaling beyond this starter.

If the host, power, network, or model endpoint fails, tasks pause. The process resumes pending work after it restarts; this is restart-safe, not literally uninterrupted.
## Review cadence now configured
- Daily: CVPen growth opportunities, QudSystem content draft, target-customer research, and an operations/error-prevention review.
- Every 3 days: process optimization and QA review.
- Weekly: deep portfolio strategy review, including CVPen revenue funnel assumptions and prioritization.

These are recurring queued prompts, not proof that live project logs or external platform activity are automatically visible to the model. The current starter does not yet implement a true long-term/short-term memory retrieval layer or automatic remediation against production systems. Those require an explicit memory store, verified data connectors, and policy-controlled action tools. Until then, review outputs are recommendations/drafts only.

## Reasoning quality
The runtime can route different roles and task prompts to an OpenAI-compatible model, but it cannot force a model to have ChatGPT's highest reasoning tier or guarantee deep reasoning. Use a capable hosted reasoning endpoint for weekly strategy and a smaller local model for routine drafting, with separate budgets and evaluations, if the provider supports those options.