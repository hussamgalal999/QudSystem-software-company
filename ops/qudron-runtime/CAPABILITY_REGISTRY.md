# Qudron capability registry — first implementation slice

## Purpose
A durable, searchable catalogue for discovered agents, tools, MCP servers, models, workflows, repositories, papers and information sources. It is metadata storage, not an execution engine.

## Safety contract
- Discovery and registration never execute repository code or invoke a tool.
- New records default to `discovered`; default searches show only `verified`, `active`, and `limited`.
- A model/tool is not marked active merely because a README or provider catalogue mentions it.
- Store source, license, version, verification time, expiry, trust score, tags and bounded metadata.
- Explicit alternative relationships are preferred; same-kind verified records are fallback alternatives.
- Credentials, cookies, API keys, private customer data and raw CVs must never be stored in this registry.
- Registry status is not permission. Execution must separately pass runtime policy, budgets, tenant scope and human approval gates.

## Implemented API
`capability_registry.py` exposes:
- `initialize_registry(path)`
- `register_capability(path, item)` — idempotent upsert with validation.
- `get_capability(path, id)`
- `search_capabilities(path, query, kind, statuses, limit)`
- `add_relation(path, id, related_id, relation)`
- `find_alternatives(path, id, limit=4)`
- `list_stale_capabilities(path, before_iso)`

SQLite is used for a small zero-dependency start. The schema is designed so a future Postgres/managed database migration can preserve the same record contract. A million entries should be paginated/indexed and partitioned by kind/provider; never loaded into agent prompts or process memory at once.

## Next integration gates
1. Wire the registry into runtime health/maintenance jobs and authenticated admin read APIs.
2. Add GitHub repository discovery adapters and source collectors for official model/provider catalogues, MCP registries, papers and release feeds.
3. Add evidence-based evaluators: license, maintenance, security advisories, dependency health, tests, compatibility, benchmark, cost and data policy.
4. Add sandbox execution only after static checks, with network disabled by default and no production secrets.
5. Promote a candidate to verified/active only after reproducible probes and policy review.
6. Add a provider/model probe runner and routing health state; never infer endpoint availability from metadata alone.

## Scale path
Use queue-backed stateless workers and per-provider concurrency/rate limits. Keep agent definitions separate from agent instances, task executions and worker processes. Scale worker pools from 4 to 8/16/32 and then load-test 100/200 before considering 2,000+ ephemeral task workers. The 10,000 figure is a capacity target, not an assertion of current operation.
