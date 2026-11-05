# Qudron Cloud Memory — durable shared project and agent state

Status: **implementation foundation; not deployed or connected to production yet.**

This package adds a small Cloudflare Worker + D1 memory service alongside the existing Python runtime. It is deliberately separate from OpenDots' conversation storage and from Qudron's local SQLite queue. The service is the shared, durable record that lets a new worker, a different model, OpenDots, or a future ChatGPT-controlled session recover the current state of a project or agent.

## Why this design

- GitHub remains the versioned source of truth for code, architecture, specifications, runbooks, and approved decisions.
- D1 is the queryable operational memory for project/agent/task snapshots and append-only events.
- Existing local SQLite remains the execution queue and local short-term runtime store; do not replace it or create a competing scheduler.
- Large artifacts stay in GitHub releases/object storage or the existing reports store. Memory records keep references, hashes, summaries, and provenance, not full binaries.
- The API is REST first. GraphQL is an optional query facade, not a database or memory engine; introducing it before there is a real multi-client query need adds complexity and tokens without improving persistence. Context retrieval is bounded (maximum 100 task/event rows and 20 conversation notes) to control prompt size and avoid wasting tokens.

## Memory scopes

1. **Company** — durable company policies, goals, portfolio-wide decisions.
2. **Portfolio** — one product/project and its lifecycle.
3. **Department** — shared context for a functional team.
4. **Project** — goals, current phase, decisions, architecture, risks, next actions.
5. **Agent** — role, current assignment, checkpoint, last verified output, blockers, handoff.
6. **Task** — status, dependencies, attempts, lease, provider/model, usage, artifacts and verification.
7. **Event** — append-only status/decision/observation trail.

Every event write includes an event ID, actor, timestamp, scope, and source. Repeated event IDs are idempotent. Conversation notes are distilled records, not raw chat transcripts. Snapshots are replaceable projections; events preserve history.

## Agent handoff contract

Before an agent starts, it receives a compact context packet containing:
- Project purpose, success criteria, current status and current milestone.
- Its own role, task, dependencies, allowed tools and permission boundary.
- Latest relevant decisions and constraints with provenance.
- Recent task events and verified artifacts only.
- Open blockers, unresolved questions and the exact next action.
- Token/context budget and a pointer to deeper documents.

Before an agent pauses, completes, fails, or hands off, it must write:
- What it attempted and what changed.
- Exact status: queued, running, blocked, succeeded, failed, cancelled.
- Evidence/artifact references and hashes where available.
- Verification performed and results.
- Remaining work, risks, and recommended next action.
- Provider/model and usage metadata when available.

A summary is not proof of completion. A task becomes succeeded only after its required checks pass and evidence references are recorded. If a provider does not return token usage, store it as unknown rather than inventing a value.

## API

All routes except `GET /health` require `Authorization: Bearer <QUDRON_MEMORY_TOKEN>`.

- `GET /health` — health and schema version only.
- `POST /v1/events` — append an idempotent event.
- `POST /v1/projects` — upsert a project snapshot.
- `POST /v1/agents` — upsert an agent snapshot.
- `POST /v1/tasks` — upsert a task snapshot.
- `POST /v1/decisions` — persist an approved project decision and its rationale.
- `POST /v1/conversations` — persist a compact conversation summary, key facts, decisions, and open loops with a source reference; never assume ChatGPT history is automatically accessible.
- `GET /v1/context?project_id=...&agent_id=...&limit=...` — compact recovery packet.

Payloads are size-limited, JSON-only, and stored as structured JSON. The Worker does not execute tools, models, code, shell commands, or arbitrary GraphQL. It is a memory service, not an execution engine.

## Deploy on Cloudflare (free-tier pilot)

Cloudflare Workers Free currently documents 100,000 requests/day, 10 ms CPU/request, and 5 cron triggers/account. D1 Free currently documents 5 million rows read/day, 100,000 rows written/day, and 5 GB total storage. Limits can change; confirm current account usage and terms before deployment.

1. Create a D1 database in the owner's Cloudflare account.
2. Set its database ID in `wrangler.toml`.
3. Run `wrangler d1 migrations apply qudron-memory --remote`.
4. Set a high-entropy secret: `wrangler secret put QUDRON_MEMORY_TOKEN`.
5. Deploy: `wrangler deploy`.
6. Configure the private runtime secret `QUDRON_MEMORY_URL` and `QUDRON_MEMORY_TOKEN` in the Qudron host's secret manager.
7. Run the smoke tests below; do not put the token in GitHub, chat, browser source, or logs.

This requires the owner to authenticate Cloudflare CLI or dashboard. No Cloudflare account was accessed and no database or deployment was created by this change.

## Smoke test

```sh
curl -fsS https://<worker-host>/health

curl -fsS -X POST https://<worker-host>/v1/projects \
  -H "Authorization: Bearer $QUDRON_MEMORY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"qudron","name":"Qudron","status":"active","summary":"Executive orchestration runtime","updated_by":"owner"}'

curl -fsS -X POST https://<worker-host>/v1/events \
  -H "Authorization: Bearer $QUDRON_MEMORY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event_id":"smoke-qudron-001","scope":"project","scope_id":"qudron","event_type":"smoke_test","actor":"owner","summary":"Memory API smoke test","status":"verified"}'

curl -fsS "https://<worker-host>/v1/context?project_id=qudron" \
  -H "Authorization: Bearer $QUDRON_MEMORY_TOKEN"
```

## Security and retention

- Never store provider keys, passwords, OAuth tokens, browser cookies, raw CVs, identity documents, payment data, or sensitive customer records in strategic memory.
- Store only the minimum necessary summaries and references. Customer data belongs in a separate encrypted, tenant-isolated product database with retention/deletion controls.
- Use a private token with at least 32 random bytes; rotate it on compromise. The Worker compares the bearer token without early-exit string comparison.
- Keep Cloudflare D1 backups/export procedures and test restoration before production reliance.
- D1 free-tier limits are ceilings, not uptime guarantees. Add alerting, export/backup, and a second restore copy before business-critical use.
- The existing runtime must call this service through a small adapter with timeout, retries, idempotency and local outbox. If cloud memory is unavailable, keep local queue state and retry sync; never silently claim cloud persistence succeeded.

## Next integration work

1. Add `QUDRON_MEMORY_URL` and `QUDRON_MEMORY_TOKEN` secret-backed configuration to the Python runtime.
2. Add an outbox table to local SQLite so memory writes survive network failures and replay idempotently.
3. Persist task/agent/project events at lifecycle transitions and checkpoint/handoff boundaries.
4. Add a bounded context builder that retrieves relevant records by scope, recency, and importance; summarize only when context exceeds budget.
5. Add GitHub repository/project inventory sync and product portfolio lifecycle records for the 500+ project estate.
6. Add automated integration tests and a verified deployment runbook.

Do not describe the memory service as live until deployment, authenticated smoke tests, restart recovery, and a restore test have all passed.
