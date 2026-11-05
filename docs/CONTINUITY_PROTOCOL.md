# Qudron continuity protocol — every agent, every task, every session

## 1. The source-of-truth chain

- **Code and decisions:** Git repository and commit SHA.
- **Project backlog and debt:** ops/qudron-runtime/project_task_registry.json.
- **Project status summary:** docs/QUDRON_PROJECT_STATE.md.
- **Runtime job state:** the persistent SQLite database in the Qudron data volume.
- **Shared project memory:** existing project-scoped memory entries in the runtime database.
- **Individual agent memory:** agent_memories keyed by project and stable agent ID.
- **Resumable internal work:** agent_runs keyed by local job ID + agent ID + execution stage.
- **External work:** external_agent_tasks keyed by provider + external task ID; keep its local job ID, status, URL and last event.
- **User-facing navigation:** Qudron Command Room pages in the OpenDots Space.

No agent may keep its only copy of progress in a chat transcript or on a provider website.

## 2. How internal agent continuity works

Before an agent stage is invoked, Qudron:
1. Identifies the task's project.
2. Retrieves shared project memory.
3. Retrieves that stable role's project-scoped memory.
4. Checks the checkpoint for (job_id, agent_id, stage).
5. Reuses a completed non-sensitive stage output instead of calling the model again.
6. Otherwise records the stage as running, invokes the role, and persists success/failure and an execution event.

On completion, the agent's recent sanitized outcome is added to its own memory. The task's full report remains in the normal Qudron report store. Agent memory is a concise continuity aid, not a customer-record database.

### Sensitive data rule

CV creation/audit, customer-support and payment-reconciliation tasks do not store intermediate model outputs in agent checkpoints or memory. Only non-sensitive execution metadata is retained; these stages are rerun after interruption. The existing customer-data release gates still apply. Redaction is best-effort and is not permission to put sensitive records into memory.

## 3. How external agents keep continuity

For each external worker, persist:
- Provider and access mode.
- Local Qudron job ID and stable Qudron agent ID.
- Provider's remote task ID and private task URL.
- Current status (submitted, running, waiting, stopped, error, etc.).
- Last event/message ID and pagination cursor when available.
- Result/artifact references, checksums and verified completion evidence.
- Follow-up and approval history.

Every new external prompt must contain the minimum necessary Qudron task context and role memory, and the remote task must receive prior task references where the provider officially supports them. Never assume that a browser tab, provider chat or external agent will remember work after session expiry.

## 4. Manus integration contract

Qudron's Manus adapter uses official API v2 methods:
- POST /v2/task.create — create asynchronous task.
- GET /v2/task.listMessages — poll progress/events and attachments.
- GET /v2/task.detail — inspect status and background work.
- POST /v2/task.sendMessage — continue or answer the agent's question.

Manus status stopped is not necessarily final when background work is still running. Qudron must inspect task.detail and keep polling when required. Action confirmations are never auto-approved; the expected schema and target event must be shown to the owner.

The adapter is disabled by default. API/OAuth access, account credit use, free-account model downgrades and the account's usage terms must be verified first. Qudron must not claim that the API path is free or that a Max/Ultra profile is available to a free personal account.

## 5. Browser and OpenDots workers

OpenDots is the human-facing workspace and approval surface. Qudron remains the durable task engine.
- A Dot is an interaction identity and workspace, not proof of a separate live model process.
- A per-Dot computer is an isolated browser/desktop execution resource with its own files and session, but it is not the same as an agent's durable memory.
- Before using an external website, Qudron must capture task ID, URL, action log, outputs/files and the point to resume.
- The user must sign in through the site's official flow. Do not export cookies or session tokens, scrape private local storage or bypass rate limits/account rules.
- Browser workers must obey site terms and stop for user approval before publishing, sending, purchasing, changing accounts or deleting data.

The bootstrap provisions one Qudron Command Room and its page hierarchy. It creates missing pages only and does not overwrite pages the owner has already edited.

## 6. New ChatGPT conversation resume checklist

At the beginning of a new conversation about Qudron:
1. Read docs/QUDRON_PROJECT_STATE.md.
2. Read ops/qudron-runtime/project_task_registry.json and count tasks by status.
3. Read docs/CONTINUITY_PROTOCOL.md and docs/DECISIONS.md.
4. Fetch current main SHA, all open Qudron PRs and their latest head SHAs.
5. Fetch the latest Actions run/jobs for each active PR; distinguish green CI from deployment/live access.
6. Inspect the most recent project state commit and any continuity branch. Do not assume a branch is merged.
7. Identify the most recent completed task and the first highest-priority open task; preserve existing constraints and continue without asking the user to repeat known requirements.

### Automatic sync limitation

A new ChatGPT chat can recover durable repository state when it reads the GitHub repository. It does not automatically inherit every prior chat transcript or the live SQLite database on an external Qudron host. Runtime-to-GitHub sanitized state synchronization still needs an authorized least-privilege GitHub connection; until that is installed, use the runtime MCP continuity tools for live state and commit periodic sanitized project snapshots to GitHub.

## 7. Completion rule

A task is complete only when:
- Its acceptance criteria pass.
- Its outcome and evidence are persisted.
- Its dependencies and follow-up work are recorded.
- Its status is updated in the task registry.
- Any new technical debt is added to the registry rather than hidden in free text.

No 100% completion claim is valid while blocked, planned, target-unmeasured, open-PR or pending-CI tasks remain.
