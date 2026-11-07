# Qudron CLI Worker Fleet

This adds a local engineering-worker launcher for independent coding-agent CLIs. Each task receives its own Git worktree and branch, a bounded file scope, and a handoff artifact set for an independent reviewer.

This is a development tool, not the production Qudron queue. It does not create cloud workers, instantiate the 48 specialist roles, or claim persistent background execution.

## Flow

    JSON task manifest
          |
          v
    Validate agent, base ref and allowed paths
          |
          +---- worker A --> worktree A --> branch A --> patch + logs
          |
          +---- worker B --> worktree B --> branch B --> patch + logs
          |
          v
    Independent read-only reviewer
          |
          v
    GitHub PR + exact-head CI + human merge approval

## What the runner does

- Requires a clean source checkout before starting.
- Resolves each task's base ref to an exact commit SHA.
- Creates one worktree and branch per task.
- Runs up to eight tasks concurrently; default is two.
- Uses argument arrays and subprocess execution; it does not invoke a shell to assemble commands.
- Captures per-task stdout/stderr and a run.json summary; a patch artifact is written only after every changed path passes the declared allowlist.
- Rejects changed files outside the declared allowed_paths scope and exports no patch at all for a scope-violating task.
- Never commits, pushes, opens a PR, or merges.

## Supported CLI adapters

| CLI | Implement | Review | Permission profile |
|---|---:|---:|---|
| Codex CLI | Yes | Yes | workspace-write or read-only sandbox |
| Gemini CLI | Yes | Yes | auto_edit or plan approval mode |
| Claude Code | Yes | Yes | acceptEdits or plan permission mode |
| Aider | Yes | No | single-shot edit, automatic commits disabled |

The runner does not install tools. Authenticate each CLI using its official account/provider flow. The doctor command checks local binary presence and version only; it does not make model calls or confirm quota.

## Not enabled in this first version

OpenCode, Cline, Qwen Code, Continue CLI and Kilo Code have non-interactive modes, but their unattended permission and shell-tool policies need a separately reviewed adapter before they can be enabled here. OpenHands' legacy CLI is marked as no longer actively maintained upstream. Goose, Augment ACP, acoder and Hubble are also not enabled pending exact package/version, command, license and permission validation.

Browse Code and CodexFlow are bridges rather than isolated coding CLIs. A bridge can expose local files, terminal commands, browser sessions or credentials to a remote chat agent; audit its authentication, tunnel and tool allowlist before connecting it to a repository. MCP is a protocol, not a security boundary by itself.

## Quick start

Run from the ops/qudron-runtime directory:

    python scripts/agent_fleet.py doctor
    python scripts/agent_fleet.py doctor --json
    python scripts/agent_fleet.py run --manifest agent-workers/tasks.example.json --max-parallel 2

The source checkout must be clean. Default artifacts are placed next to the checkout, not inside it:

    ../.qudron-agent-worktrees/<run-id>/<task-id>/
    ../.qudron-agent-artifacts/<run-id>/

Inspect the run.json summary, task patches, stdout and stderr before sharing anything. Artifacts may contain proprietary source code or prompt text; sanitize them before external sharing.

## Manifest

Copy tasks.example.json and replace the examples with independent tasks. Every implementer must have a narrow, non-overlapping allowed_paths list. Review tasks must use an empty allowed_paths list and run against the implementation branch or commit in read-only mode.

Allowed agent values: codex, gemini, claude, aider.
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

- Git worktrees isolate Git state and files, not OS processes, network access, credentials or CPU/RAM. Run this tool in a disposable devcontainer/VM, as a non-admin user, without the host Docker socket.
- Codex workspace-write is still a code-execution environment inside its workspace. Do not use danger-full-access or YOLO for routine fleet tasks.
- Gemini auto_edit and Claude acceptEdits do not blanket-approve shell commands; a worker may pause or fail if a command requires approval.
- Aider automatic commits are disabled.
- allowed_paths is a post-run diff check, not an OS-level access-control boundary. Use separate OS users or containers for hostile/untrusted agent code.
- Missing local CLIs are reported as unavailable; no agent is silently substituted.
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
