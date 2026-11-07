# Agent task contract

Every worker task must declare:

| Field | Meaning |
|---|---|
| id | Stable unique lowercase slug used in branch and artifact names |
| title | One independent, observable outcome |
| agent | Supported CLI adapter |
| mode | implement or review |
| base_ref | Explicit Git ref; resolved to an immutable commit SHA |
| allowed_paths | Narrow relative paths/globs; required for implementation |
| prompt | Objective, context, interfaces, acceptance criteria, non-goals and tests |

## Required prompt structure

1. Objective: one independently deliverable change.
2. Context: relevant modules, contracts and trusted references.
3. Interfaces: exact functions, APIs, events or schemas that must remain compatible.
4. Allowed scope: only files listed in the manifest.
5. Acceptance criteria: observable behaviour, edge cases and regression tests.
6. Non-goals: work reserved for other workers or explicitly excluded.
7. Evidence: commands/tests actually run, their exit codes, failures and remaining uncertainty.

## Review artifact contract

The integration owner must require:

- exact base SHA and worker branch;
- full diff and changed-file list (no patch is exported for a task with any path violation);
- raw stdout/stderr are absent by default and may only be retained through explicit `--capture-logs` opt-in for scope-valid tasks;
- allowed-path validation result, with no patch artifact exported if any changed path violates the allowlist;
- test commands and actual exit codes;
- known limitations and unverified assumptions;
- independent reviewer findings;
- CI run linked to the exact proposed commit.

A reviewer should use a different provider from the implementer when feasible and receive a read-only worktree. Reviewers report findings; they do not resolve GitHub review threads or merge code for the owner.

A generated patch is an untrusted proposal until it has passed scope checks, relevant tests, independent review and repository CI.
