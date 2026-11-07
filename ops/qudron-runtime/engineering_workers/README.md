# Qudron Engineering Worktree Pipeline

This repository-side developer orchestration layer complements the existing Qudron runtime (agent fabric, workflow orchestrator, swarm engine and background worker). It does not replace or duplicate those runtime components.

## Capabilities
- Validates versioned wave manifests containing 1–8 tasks.
- Rejects unsafe paths, denied paths and overlapping parallel write scopes.
- Pins every wave to one resolved base commit SHA.
- Creates one dedicated Git branch and worktree for each task.
- Generates per-worker prompts and control records outside the main repository.
- Reports branch, HEAD and dirty state.
- Collects a worker handoff only after validating task identity, branch, base/head SHAs, exact changed-file list, allowed paths, denied paths, diff whitespace and the human-review gate.
- Writes diff.patch, result.json, task.json, optional test.log and a SHA-256 patch digest.

## What it deliberately does not do
It does not launch Codex, Claude Code, Gemini CLI, OpenCode, Aider, Goose or any other model/agent process. The doctor command only detects executable paths. It does not run task-supplied shell commands, install tools, provide credentials, call model APIs, push, open PRs, merge or deploy. An operator must explicitly launch any approved CLI in a separate restricted VM/container.

Git worktrees isolate working directories and branches, but they share the Git object store and are not an OS security boundary. Never run an untrusted agent in a worktree with access to the main clone, host home directory, Docker socket, secrets or customer data. Use a separately restricted VM/container and mount only the assigned worktree.

## Start a synthetic 3-task wave
From the repository root:

    python ops/qudron-runtime/scripts/dev_worktree_orchestrator.py doctor
    python ops/qudron-runtime/scripts/dev_worktree_orchestrator.py prepare --manifest ops/qudron-runtime/engineering_workers/examples/wave-001.json --worktree-root ../Qudron-workers/wave-001
    python ops/qudron-runtime/scripts/dev_worktree_orchestrator.py status --worktree-root ../Qudron-workers/wave-001

The example manifest uses HEAD. Inspect and fetch the intended base branch first. The prepare command records the exact base SHA and refuses to overwrite an existing control directory, branch or worktree.

After an operator launches one approved agent per isolated worktree, each worker must write .qudron-worker/result.json using worker-result.schema.json. Stage all source changes before collection; untracked source files are rejected because a normal Git patch would silently omit them.

    python ops/qudron-runtime/scripts/dev_worktree_orchestrator.py collect --worktree-root ../Qudron-workers/wave-001 --task-id agent-fabric-contracts --artifact-root ../Qudron-artifacts/wave-001

Review each artifact and patch independently, apply only accepted changes to an integration branch, run the full Qudron CI against the exact integration commit, request independent review and require human approval to merge.

## Pilot policy
Start with the three disjoint review/fix scopes in examples/wave-001.json. They are task definitions, not evidence that three agents are active. Do not expand fan-out until patch integrity, sandbox isolation, resource use, provider quotas and CI duration are measured. If a task needs another writable path, stop and amend the manifest with owner approval; workers must not expand their own allowlist.
