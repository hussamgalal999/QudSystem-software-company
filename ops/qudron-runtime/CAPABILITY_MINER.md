# Qudron read-only GitHub mining engine — first pass

## What it does
- Uses the connected account's authorized GitHub token to discover repositories.
- Orders repositories by last update and caps each run at 200 repositories (default 50).
- Reads recursive Git tree metadata and indexes paths only.
- Scores transparent signals: recent updates, README presence, license-file presence, tests paths, build manifests, CI configuration, description and archived state.
- Registers each repository in the capability registry as `candidate`; archived projects are `deprecated`.
- Continues past a small number of repository-specific errors and returns sanitized failure summaries.

## What it deliberately does not claim
- A LICENSE filename is not proof of a license grant; the license remains `unknown`.
- Test paths do not prove tests pass; no tests are executed.
- A high metadata score is not a security, maintenance or quality certification.
- It does not clone repositories, download source files, execute code, access secrets or modify repositories.
- Private repositories are included only when the configured GitHub token already has read access.

## Usage
Configure `GITHUB_OWNER`, `GITHUB_TOKEN` (read-only Metadata permission for intended repositories), and a registry database path in the host secret manager. Then call `mine_from_environment(max_repositories=50)` from a controlled maintenance task.

The miner is currently a callable module, not yet a scheduled background job. The next integration adds a bounded scheduler task, persistent run history, README/LICENSE source review, dependency/license checks, security-advisory checks, sandboxed test execution and promotion approvals.

## Safety and scaling
- Metadata-only first pass; no source execution.
- Max 200 repositories per run; default 50.
- No tokens or source content are written to the capability registry.
- A later source-inspection stage must have file-size caps, allowlisted file types, rate limits, secret redaction and explicit repository scope.
- Run multiple independent mining workers only after introducing queue leases and per-token rate limits; never parallelize API calls without respecting GitHub rate limits.
