# Qudron Pilot Deployment Runbook

This runbook takes the tested Docker runtime to a **private internal pilot**. It does not enable public customer intake, payments, WhatsApp, or social publishing.

## 0. Release gate

Before deployment, confirm:
- The candidate PR is reviewed and merged by the repository owner.
- The exact merged commit has a green CI run.
- A dedicated always-on Docker host is available. A serverless web-function deployment alone is not a worker host.
- The host has persistent storage, automated security updates, backups, monitoring, and a rollback procedure.
- A model provider account and a low-cost model are available.

Do not deploy an unmerged draft branch to production.

## 1. Host requirements

Minimum pilot requirements:
- Linux host with Docker Engine and Docker Compose plugin.
- Always-on process supervision and restart-on-failure.
- Persistent disk for `data/`, `reports/`, and `logs/`.
- SSH access restricted to the owner/admin, firewall enabled, time synchronization enabled.
- Disk space and memory alerts.
- Encrypted off-host backups with a tested restore procedure.

Do not assume a free web hosting tier supports persistent background workers or durable local volumes. Confirm provider limits before choosing a host.

## 2. Prepare secrets and configuration

On the host, create a deployment directory and copy the runtime source from the reviewed, merged commit. Create `.env` from `.env.example` locally on the host.

Required values:
- `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` (or the selected tier profile).
- `QUDRON_API_TOKEN`: generate a cryptographically random secret of at least 32 bytes.
- Exact input and output prices for every enabled model profile.
- Conservative daily and monthly model budgets.
- `QUDRON_CVPEN_JOB_BUDGET_USD` only when CVPen generation is being tested; keep CVPen customer workflows disabled during the internal pilot.

Never commit `.env`, paste credentials into issues/chat, or place secrets in logs. Restrict the file to the service account (for example, mode 0600). Do not use a local-machine URL such as `127.0.0.1:1234` unless the model server is inside the same container/network namespace; use a reachable private service hostname instead.

## 3. Start privately

The supplied Compose file binds port 8765 to host loopback. Preserve that default for the first pilot.

From the runtime directory:
```sh
docker compose config
docker compose up -d --build
docker compose ps
docker compose logs --tail=200 qudron
```

Check health locally:
```sh
curl --fail http://127.0.0.1:8765/health
```

Do not open port 8765 to the public internet. If remote access becomes necessary, use a private VPN or an authenticated HTTPS reverse proxy with rate limits and access logs.

## 4. Pilot smoke tests

Run these tests before scheduling any business-critical work:
1. Health endpoint returns success.
2. Submit one harmless internal research/draft job with a unique idempotency key.
3. Repeat the same request with the same key; verify no duplicate job is created.
4. Poll the job until terminal state and retrieve its report using authenticated endpoints.
5. Restart the container; verify queued work and completed artifacts remain available.
6. Simulate a worker interruption in a non-production test environment; verify lease recovery and bounded retry.
7. Trigger one scheduled internal task and verify its local Cairo schedule.
8. Verify model usage is recorded and the configured budget prevents an over-budget call.
9. Verify unauthenticated API requests fail.
10. Verify the host port is not reachable from the public internet.

Record test date, commit SHA, host/provider, model/provider, token usage, estimated cost, and evidence links in the deployment log. Do not store secrets or customer data in the log.

## 5. Monitoring and backup

Monitor at minimum:
- Health check and process/container restarts.
- Queue depth and oldest queued-job age.
- Jobs by terminal state; retries and terminal failures.
- Provider latency, errors, rate limits, and token/cost totals.
- Disk capacity, memory, CPU, and backup freshness.
- Timestamp of last successful scheduled task.

Back up `data/` and required reports using a consistent, encrypted backup method. Keep retention bounded. Test restoration into an isolated environment before relying on backups.

## 6. Rollback

1. Stop intake from external callers.
2. Preserve logs and a copy of the persistent data directory for diagnosis.
3. Roll back to the last known-good image/commit.
4. Start the previous version and verify health, queue integrity, and report retrieval.
5. Reconcile any in-flight jobs before re-enabling internal scheduling.

Never delete the persistent database as a rollback shortcut.

## 7. Explicitly out of scope for this pilot

- Public customer intake and CV uploads.
- CV parsing, DOCX/PDF generation, and customer delivery.
- Live payment collection, payment webhooks, refunds, or wallet operations.
- WhatsApp or other outbound customer messaging.
- Public social publishing or paid advertising.

Each requires a separate provider integration, authorization, privacy controls, sandbox/end-to-end tests, and an explicit release gate. Payment status must come from authenticated PSP evidence reconciled to order ID, amount, currency, settlement state, and transaction ID; screenshots and SMS are not settlement proof.

## Pilot exit criteria

The pilot is successful only when the service is continuously running on an always-on host, access is private and authenticated, one real low-cost model call succeeds under a configured spend cap, a scheduled internal job completes with a retrievable artifact, restart recovery is demonstrated, and monitoring plus backup/restore have been tested.
