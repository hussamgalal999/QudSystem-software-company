# Qudron CLI Worker Fleet

This adds a local engineering-worker launcher for independent coding-agent CLIs. Each task receives its own Git worktree and branch, a bounded file scope, and a handoff artifact set for an independent reviewer.

This is a development tool, not the production Qudron queue. It does not create cloud workers, instantiate the 48 specialist roles, or claim persistent background execution.

## Flow

    JSON task manifest
          |
          v
    Validate agent, base ref and allowed paths
          |
          +---- worker A --> worktree A --> branch A --> validated patch + run.json (logs opt-in)
          |
          +---- worker B --> worktree B --> branch B --> validated patch + run.json (logs opt-in)
          |
          v
    Independent read-only reviewer
          |
          v
    GitHub PR + exact-head CI + human merge approval

## What the runner does

- Requires a clean source checkout before starting.
- Resolves each task's base ref to an exact commit SHA.
- Revalidates the original worktree root, branch, and unchanged base `HEAD` at handoff; a branch switch or worker-created commit blocks patch and log export.
- Creates one worktree and branch per task.
- Runs up to eight tasks concurrently; default is two.
- Uses argument arrays and subprocess execution; it does not invoke a shell to assemble commands. Each CLI receives only basic runtime variables plus that provider's explicitly allowlisted API-key variables; GitHub, generic cloud, SSH-agent, and other providers' credentials are not inherited. Host XDG/Windows profile paths are not inherited: CLI configuration roots are derived under the operator-provided `HOME`. Set `HOME` to the dedicated sandbox user's home before launching workers. Codex runs ephemerally and Claude Code session persistence is disabled for worker tasks.
- Writes a run.json summary and exports a patch only for a successful, non-timeout task with at least one change and after every changed path passes the declared allowlist and denylist. Each exported patch includes a SHA-256 digest. Every task result records its exact allowed_paths and deny_paths used for the run. Raw stdout/stderr are not saved by default.
- Rejects changed files outside the declared allowed_paths scope, blocks sensitive paths by default, and exports no patch at all for a scope-violating task.
- Rejects overlapping write scopes between concurrent implementation tasks before any worker is launched.
- Never commits, pushes, opens a PR, or merges.

## Supported CLI adapters

| CLI | Implement | Review | Permission profile |
|---|---:|---:|---|
| Codex CLI | Yes | Yes | workspace-write or read-only sandbox |
| Gemini CLI | Yes | Yes | auto_edit or plan (experimental plan mode must be enabled for read-only reviews) |
| Claude Code | Yes | Yes | acceptEdits or plan permission mode |

The runner does not install tools. Authenticate each CLI using its official account/provider flow. Gemini `auto_edit` approves edit tools only and can still wait for approval on other tools; its read-only `plan` mode requires the experimental planning feature to be enabled. The doctor command checks local binary presence and version only; it does not make model calls or confirm quota.

## Not enabled in this first version

Aider, OpenCode, Cline, Qwen Code, Continue CLI and Kilo Code have non-interactive modes, but their unattended permission and shell-tool policies need a separately reviewed adapter before they can be enabled here. In particular, Aider's `--yes` option accepts every confirmation, so this launcher does not enable it. OpenHands' legacy CLI is marked as no longer actively maintained upstream. Goose, Augment ACP, acoder and Hubble are also not enabled pending exact package/version, command, license and permission validation.

Browse Code and CodexFlow are bridges rather than isolated coding CLIs. A bridge can expose local files, terminal commands, browser sessions or credentials to a remote chat agent; audit its authentication, tunnel and tool allowlist before connecting it to a repository. MCP is a protocol, not a security boundary by itself.

## Quick start

Run from the ops/qudron-runtime directory:

```bash
python scripts/agent_fleet.py doctor
python scripts/agent_fleet.py doctor --json
python scripts/agent_fleet.py run --manifest agent-workers/tasks.example.json --max-parallel 2

# Opt in to raw CLI stdout/stderr for successful in-scope tasks only:
python scripts/agent_fleet.py run --manifest agent-workers/tasks.example.json --max-parallel 2 --capture-logs
```

The source checkout must be clean. The example manifest is illustrative; launching it invokes the selected providers and may consume account quota. Confirm installed CLIs, authentication, spending limits and the isolated host before running any real task. Default artifacts are placed next to the checkout, not inside it:

    ../.qudron-agent-worktrees/<run-id>/<task-id>/
    ../.qudron-agent-artifacts/<run-id>/

Inspect the run.json summary and task patches before sharing anything. Raw CLI logs are omitted by default; use `--capture-logs` only in an approved environment and only when the output is safe to retain. Even with opt-in, logs are withheld for failed, timed-out, or scope-violating tasks. Artifacts may contain proprietary source code or prompt text; sanitize them before external sharing.

## Manifest

Validate manifests against `manifest.schema.json` before launch. Consumers should validate every `run.json` handoff against `run.schema.json` and reject reports that do not set `requires_human_review: true`. Runtime validation remains authoritative for safe path normalization, default deny paths, and non-overlapping concurrent write scopes.

Copy tasks.example.json and replace the examples with independent tasks. Every implementer must have a narrow, non-overlapping `allowed_paths` list. Scopes accept exact relative paths or directory prefixes ending in `/**`; arbitrary glob syntax is rejected. Review tasks must use an empty allowed_paths list and run against the implementation branch or commit in read-only mode. Manifests may also declare `acceptance_criteria`, `expected_checks`, and `known_risks`; these are validated, included in the worker prompt, and echoed in the run report. `expected_checks` entries are descriptive metadata only: the launcher never executes shell commands copied from a manifest and never treats a declared check as passed evidence.

Allowed agent values: codex, gemini, claude.
Allowed modes: implement, review.
Maximum manifest size: 20 tasks.
Maximum parallel workers: 8.

## Review and PR handoff

A completed status means only that the CLI exited successfully, changed at least one file and stayed inside its declared path scope. It does not mean tests passed or code is correct.

After implementation:
1. Inspect run.json and the task patch.
2. Run the relevant unit, integration, security and compatibility tests.
3. Commit the reviewed worker branch manually.
4. Run an independent reviewer with a different provider and mode review, setting base_ref to the implementation branch.
5. Open a PR only after review findings are resolved and exact-head CI is green.

Manual owner commands:

    git push -u origin <worker-branch>
    gh pr create --base <approved-base-branch> --head <worker-branch>

No automatic PR creation or merge is implemented. Keep human merge approval and repository branch protections enabled.

## Safety model and limitations

- Git worktrees isolate Git state and files, not OS processes, network access, credentials or CPU/RAM. Run this tool in a disposable devcontainer/VM with a dedicated isolated HOME and provider login, as a non-admin user, without host home mounts, the host Docker socket, SSH agent or production access. The environment allowlist does not make an unsafe host a safe sandbox.
- Codex workspace-write is still a code-execution environment inside its workspace. Do not use danger-full-access or YOLO for routine fleet tasks.
- Gemini auto_edit and Claude acceptEdits do not blanket-approve shell commands; a worker may pause or fail if a command requires approval.
- allowed_paths and deny_paths are post-run diff checks, not OS-level access-control boundaries. Raw stdout/stderr are withheld by default and remain suppressed for any scope-violating task, even when `--capture-logs` is enabled. Sensitive paths are denied by default, but an untrusted process can still read or alter files inside its VM; use a disposable restricted VM/container with no host credentials or Docker socket.
- Missing local CLIs are reported as unavailable; no agent is silently substituted. An execution task may still incur provider usage; fake-CLI CI tests do not.
- The runner never installs packages, provisions credentials, bypasses quotas, accesses browser cookies, or calls production services.
- Keep customer CVs, payment records, secrets and confidential data out of prompts unless the selected provider and environment are explicitly approved for that data class.

## Validation

The unit tests use fake CLI executables. They do not need model credentials and do not consume inference quota.

    python -m py_compile scripts/agent_fleet.py
    python -m unittest discover -s tests -p 'test_agent_fleet.py' -v

## Official CLI references

- Codex CLI: https://learn.chatgpt.com/docs/cli/reference
- Gemini CLI headless mode: https://geminicli.com/docs/cli/headless/
- Claude Code CLI usage: https://docs.anthropic.com/en/docs/claude-code/cli-usage
- Aider scripting: https://aider.chat/docs/scripting.html
- OpenCode CLI: https://dev.opencode.ai/v2/docs/cli/commands/
- Cline CLI: https://github.com/cline/cline/blob/main/docs/usage/cli-overview.mdx
- Qwen Code settings: https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/
- Continue CLI: https://docs.continue.dev/cli/quickstart
- Kilo Code CLI: https://kilo.ai/docs/code-with-ai/platforms/cli
- OpenHands CLI: https://github.com/OpenHands/docs/blob/main/openhands/usage/cli/command-reference.mdx
