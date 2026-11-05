# Per-agent memory and resumable execution

## SQLite entities

The runtime adds four continuity tables in the same Qudron database file:

| Table | Purpose | Key |
|---|---|---|
| agent_memories | Sanitized project-scoped memory for one stable role ID | project + agent_id + timestamp |
| agent_runs | Durable status and optional output checkpoint per role/stage | job_id + agent_id + stage |
| continuity_events | Audit trail of stage started/retried/resumed/completed/failed | event ID |
| external_agent_tasks | Remote task identity and status for Manus or other approved providers | provider + external_task_id |

The original project memory table remains the shared project-level memory. Each agent receives both shared project context and its own role-specific memory.

## Resume behavior

- A non-sensitive stage is checkpointed when it completes.
- If the Qudron worker restarts or a job retries, the same job/agent/stage returns the completed checkpoint rather than re-running the model.
- If a stage was interrupted while running, its next attempt is recorded as a retry.
- Failed stages are recorded with a redacted error; they are not silently marked completed.
- The final report still comes from the regular job result pipeline and is saved under the reports directory.

## Sensitive workflows

CV creation/audit, support and payment reconciliation set output checkpointing off. Their agent stage result is not copied into the extra continuity checkpoint or agent memory. The stage metadata remains auditable, and the work is re-executed on retry. Do not place CVs, identity documents, payment credentials or full customer records into strategic memory.

## External agents

The external_agent_tasks table preserves provider, remote task ID, local job ID, stable role identity, task URL, status, last event ID, result JSON and error metadata. This makes the local reference durable; a provider connection and a poll/dispatch scheduler are still required to run an actual external task.

## Operations

- The database belongs in the persistent Qudron data volume.
- Back up the DB consistently with reports; test restore before production.
- Do not mount the SQLite data volume into OpenDots or external agent computers.
- Query live continuity using the owner-authenticated Qudron MCP tools qudron_get_continuity and qudron_get_agent_memory.
- The task registry remains a tracked Git file. Automatic sanitized runtime-to-GitHub syncing is not yet connected.
