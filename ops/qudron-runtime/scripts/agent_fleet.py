#!/usr/bin/env python3
"""Run independent coding-agent tasks in isolated Git worktrees.

This is an engineering-worker launcher, not Qudron's production task runtime.
It never installs CLIs, pushes branches, opens PRs, or merges code.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath
from typing import Any

VERSION = "0.1.0"
MAX_TASKS = 20
MAX_PARALLEL = 8
DEFAULT_TIMEOUT_SECONDS = 3600
DEFAULT_DENY_PATHS = (
    ".git/**", ".env", ".env.*", "**/.env", "**/.env.*",
    "secrets/**", "**/secrets/**", "*private_key*", "*credentials*", "**/*private_key*", "**/*credentials*",
    ".ssh/**", "**/.ssh/**", "id_rsa*", "id_ed25519*", "**/id_rsa*", "**/id_ed25519*",
    "*.pem", "*.key", "*.p12", "*.pfx",
    "**/*.pem", "**/*.key", "**/*.p12", "**/*.pfx",
    ".aws/**", "**/.aws/**", ".kube/**", "**/.kube/**",
    ".npmrc", "**/.npmrc", ".netrc", "**/.netrc", ".pypirc", "**/.pypirc",
    "service-account*.json", "**/service-account*.json", "credentials.json", "**/credentials.json",
    ".docker/**", "**/.docker/**", ".azure/**", "**/.azure/**",
    ".config/gh/**", "**/.config/gh/**", ".config/gcloud/**", "**/.config/gcloud/**",
    ".direnv/**", "**/.direnv/**", ".git-credentials*", "**/.git-credentials*",
    ".gitconfig", "**/.gitconfig", ".terraform/**", "**/.terraform/**",
    "*.tfstate", "*.tfstate.*", "**/*.tfstate", "**/*.tfstate.*",
)

# Only adapters whose non-interactive invocation and permission behaviour are
# documented are implemented. Add more adapters only after validating the
# installed version and its permission model.
AGENTS: dict[str, dict[str, str]] = {
    "codex": {"binary": "codex", "purpose": "workspace-write or read-only sandbox"},
    "gemini": {"binary": "gemini", "purpose": "auto_edit for implement; plan for review"},
    "claude": {"binary": "claude", "purpose": "acceptEdits for implement; plan for review"},
}

BASE_ENV_KEYS = {
    "PATH", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "LC_MESSAGES",
    "TERM", "NO_COLOR", "SYSTEMROOT", "WINDIR", "PATHEXT",
}
AGENT_ENV_KEYS = {
    "codex": {"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"},
    "gemini": {"GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"},
    "claude": {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"},
}

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$")


class FleetError(RuntimeError):
    """Expected configuration or Git error."""


def git(args: list[str], cwd: Path, *, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=timeout, check=False,
    )
    if check and proc.returncode != 0:
        raise FleetError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def repo_root(candidate: Path) -> Path:
    path = candidate.expanduser().resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=str(path), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0:
        raise FleetError(f"Not inside a Git repository: {path}")
    return Path(result.stdout.strip()).resolve()


def ensure_clean_repo(root: Path) -> None:
    status = git(["status", "--porcelain", "--untracked-files=all"], root).stdout
    if status.strip():
        raise FleetError(
            "The source checkout is not clean. Commit, stash, or move local changes "
            "before launching workers; the fleet will not guess which changes belong to a task."
        )


def resolve_ref(root: Path, ref: str) -> str:
    if not isinstance(ref, str) or not REF_RE.fullmatch(ref):
        raise FleetError(f"Invalid base_ref: {ref!r}")
    resolved = git(["rev-parse", "--verify", f"{ref}^{{commit}}"], root, check=False)
    if resolved.returncode != 0:
        raise FleetError(f"Unknown commit/ref: {ref}")
    return resolved.stdout.strip()


def validate_relative_pattern(pattern: Any, task_id: str, field: str = "path") -> str:
    if not isinstance(pattern, str) or not pattern.strip():
        raise FleetError(f"Task {task_id}: {field} entries must be non-empty strings")
    value = pattern.strip()
    p = PurePosixPath(value)
    segments = value.split("/")
    if (
        p.is_absolute()
        or re.match(r"^[A-Za-z]:", value)
        or any(segment in {"", ".", ".."} for segment in segments)
        or "\\" in value
        or "\x00" in value
    ):
        raise FleetError(f"Task {task_id}: unsafe {field} pattern: {pattern!r}")
    # Exact relative file paths and directory-prefix globs are intentionally
    # the only writable-scope language. Arbitrary globs are hard to intersect
    # correctly and can create hidden overlap between parallel workers.
    has_glob = any(char in value for char in "*?[]")
    if has_glob and not value.endswith("/**"):
        raise FleetError(f"Task {task_id}: {field} supports only exact paths or a trailing '/**' directory pattern")
    if value.endswith("/**") and any(char in value[:-3] for char in "*?[]"):
        raise FleetError(f"Task {task_id}: directory-prefix paths cannot contain wildcards")
    if value.count("**") and not value.endswith("/**"):
        raise FleetError(f"Task {task_id}: '**' is supported only as a trailing directory pattern")
    return value


def patterns_overlap(left: str, right: str) -> bool:
    left_tree = left.endswith("/**")
    right_tree = right.endswith("/**")
    left_root = left[:-3] if left_tree else left
    right_root = right[:-3] if right_tree else right
    if left_root == right_root:
        return True
    if left_tree and right_root.startswith(left_root + "/"):
        return True
    if right_tree and left_root.startswith(right_root + "/"):
        return True
    return False


def validate_manifest_notes(raw: Any, task_id: str, field: str) -> list[str]:
    """Validate declarative acceptance/check/risk notes; never execute them as commands."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 32:
        raise FleetError(f"Task {task_id}: {field} must be a list of up to 32 descriptive strings")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip() or len(item) > 1000:
            raise FleetError(f"Task {task_id}: every {field} entry must contain 1-1,000 characters")
        values.append(item.strip())
    if len(values) != len(set(values)):
        raise FleetError(f"Task {task_id}: {field} cannot contain duplicates")
    return values


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FleetError(f"Manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FleetError(f"Manifest JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload.get("version") != 1:
        raise FleetError("Manifest must be a JSON object with integer version: 1")
    unknown_top_level = set(payload) - {"version", "max_parallel", "tasks"}
    if unknown_top_level:
        raise FleetError("Manifest contains unsupported fields: " + ", ".join(sorted(unknown_top_level)))
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_TASKS:
        raise FleetError(f"Manifest tasks must contain between 1 and {MAX_TASKS} items")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(tasks, start=1):
        if not isinstance(raw, dict):
            raise FleetError(f"Task #{index} must be an object")
        unknown_task_fields = set(raw) - {
            "id", "title", "agent", "mode", "prompt", "base_ref", "allowed_paths", "deny_paths",
            "acceptance_criteria", "expected_checks", "known_risks"
        }
        if unknown_task_fields:
            raise FleetError(
                f"Task #{index}: unsupported fields: " + ", ".join(sorted(unknown_task_fields))
            )
        task_id = raw.get("id")
        if not isinstance(task_id, str) or not ID_RE.fullmatch(task_id):
            raise FleetError(f"Task #{index}: id must match {ID_RE.pattern}")
        if task_id in seen:
            raise FleetError(f"Duplicate task id: {task_id}")
        seen.add(task_id)
        agent = raw.get("agent")
        if not isinstance(agent, str) or agent not in AGENTS:
            raise FleetError(f"Task {task_id}: unsupported agent {agent!r}; supported: {', '.join(AGENTS)}")
        mode = raw.get("mode", "implement")
        if not isinstance(mode, str) or mode not in {"implement", "review"}:
            raise FleetError(f"Task {task_id}: mode must be implement or review")
        prompt = raw.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
            raise FleetError(f"Task {task_id}: prompt must contain 1-16,000 characters")
        allowed = raw.get("allowed_paths", [])
        if not isinstance(allowed, list):
            raise FleetError(f"Task {task_id}: allowed_paths must be a list")
        allowed = [validate_relative_pattern(p, task_id, "allowed_paths") for p in allowed]
        if len(set(allowed)) != len(allowed):
            raise FleetError(f"Task {task_id}: allowed_paths cannot contain duplicates")
        if mode == "implement" and not allowed:
            raise FleetError(f"Task {task_id}: implement tasks require a non-empty allowed_paths list")
        if mode == "review" and allowed:
            raise FleetError(f"Task {task_id}: review tasks must use allowed_paths: [] (read-only)")
        deny = raw.get("deny_paths", [])
        if not isinstance(deny, list):
            raise FleetError(f"Task {task_id}: deny_paths must be a list")
        normalized_deny = [validate_relative_pattern(p, task_id, "deny_paths") for p in deny]
        if len(set(normalized_deny)) != len(normalized_deny):
            raise FleetError(f"Task {task_id}: deny_paths cannot contain duplicates")
        deny = list(dict.fromkeys([*DEFAULT_DENY_PATHS, *normalized_deny]))
        base_ref = raw.get("base_ref", "HEAD")
        if not isinstance(base_ref, str) or not REF_RE.fullmatch(base_ref):
            raise FleetError(f"Task {task_id}: invalid base_ref")
        title = raw.get("title", task_id)
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise FleetError(f"Task {task_id}: title must be 1-200 characters")
        acceptance_criteria = validate_manifest_notes(
            raw.get("acceptance_criteria"), task_id, "acceptance_criteria"
        )
        expected_checks = validate_manifest_notes(
            raw.get("expected_checks"), task_id, "expected_checks"
        )
        known_risks = validate_manifest_notes(
            raw.get("known_risks"), task_id, "known_risks"
        )
        normalized.append({
            "id": task_id,
            "title": title.strip(),
            "agent": agent,
            "mode": mode,
            "prompt": prompt.strip(),
            "base_ref": base_ref,
            "allowed_paths": allowed,
            "deny_paths": deny,
            "acceptance_criteria": acceptance_criteria,
            "expected_checks": expected_checks,
            "known_risks": known_risks,
        })
    implementers = [task for task in normalized if task["mode"] == "implement"]
    for index, first in enumerate(implementers):
        for second in implementers[index + 1:]:
            for left in first["allowed_paths"]:
                for right in second["allowed_paths"]:
                    if patterns_overlap(left, right):
                        raise FleetError(
                            f"Overlapping write scopes: {first['id']}:{left} and {second['id']}:{right}"
                        )
    payload["tasks"] = normalized
    max_parallel = payload.get("max_parallel", 2)
    if not isinstance(max_parallel, int) or isinstance(max_parallel, bool) or not 1 <= max_parallel <= MAX_PARALLEL:
        raise FleetError(f"max_parallel must be an integer between 1 and {MAX_PARALLEL}")
    payload["max_parallel"] = max_parallel
    return payload


def build_agent_env(agent: str) -> dict[str, str]:
    """Give each CLI provider a private HOME below an operator-owned root."""
    if agent not in AGENT_ENV_KEYS:
        raise FleetError(f"Unsupported provider environment: {agent}")
    raw_home_root = os.environ.get("QUDRON_FLEET_HOME_ROOT", "").strip()
    if not raw_home_root:
        raise FleetError(
            "QUDRON_FLEET_HOME_ROOT must point to a private directory outside the repository"
        )
    home_root = Path(raw_home_root).expanduser()
    if not home_root.is_absolute():
        raise FleetError("QUDRON_FLEET_HOME_ROOT must be an absolute path")
    if home_root.is_symlink():
        raise FleetError("QUDRON_FLEET_HOME_ROOT cannot be a symbolic link")
    try:
        home_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            os.chmod(home_root, 0o700)
        home_root = home_root.resolve(strict=True)
    except OSError as exc:
        raise FleetError("Cannot create or secure QUDRON_FLEET_HOME_ROOT") from exc
    try:
        checkout = repo_root(Path.cwd()).resolve()
    except FleetError:
        checkout = None
    if checkout and (home_root == checkout or checkout in home_root.parents):
        raise FleetError("QUDRON_FLEET_HOME_ROOT must be outside the repository checkout")

    # Separate provider homes prevent one CLI from inheriting another provider's
    # OAuth/device-login files. The root itself is never passed to the subprocess.
    home_path = home_root / agent
    if home_path.is_symlink():
        raise FleetError(f"Provider HOME cannot be a symbolic link: {agent}")
    try:
        home_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            os.chmod(home_path, 0o700)
        home_path = home_path.resolve(strict=True)
    except OSError as exc:
        raise FleetError(f"Cannot create or secure provider HOME: {agent}") from exc

    allowed = BASE_ENV_KEYS | AGENT_ENV_KEYS[agent]
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env["HOME"] = str(home_path)
    env["XDG_CONFIG_HOME"] = str(home_path / ".config")
    env["XDG_CACHE_HOME"] = str(home_path / ".cache")
    env["XDG_DATA_HOME"] = str(home_path / ".local" / "share")
    if os.name == "nt":
        env["USERPROFILE"] = str(home_path)
        env["APPDATA"] = str(home_path / "AppData" / "Roaming")
        env["LOCALAPPDATA"] = str(home_path / "AppData" / "Local")
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def build_agent_command(agent: str, mode: str, prompt: str, prompt_file: Path, worktree: Path) -> tuple[list[str], str | None]:
    """Return argv and optional stdin; never invoke a shell."""
    if agent == "codex":
        sandbox = "read-only" if mode == "review" else "workspace-write"
        return (["codex", "-a", "never", "exec", "--json", "--ephemeral", "--sandbox", sandbox,
                 "--cd", str(worktree), "-"], prompt)
    if agent == "gemini":
        approval = "plan" if mode == "review" else "auto_edit"
        return (["gemini", "-p", prompt, "--output-format", "json",
                 "--approval-mode", approval], None)
    if agent == "claude":
        permission = "plan" if mode == "review" else "acceptEdits"
        return (["claude", "-p", prompt, "--output-format", "json",
                 "--permission-mode", permission, "--max-turns", "30",
                 "--no-session-persistence"], None)
    raise FleetError(f"No command adapter for agent: {agent}")


def safe_write(path: Path, content: str) -> None:
    """Create private artifacts without following a pre-existing symlink."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise FleetError(f"Refusing to write through artifact symlink: {path}")
    # O_EXCL prevents following either a symlink or a hard link planted at an
    # artifact path after the worker starts. Artifact names are unique per run.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def make_prompt(task: dict[str, Any]) -> str:
    allowed = task["allowed_paths"] or ["READ ONLY — do not modify any file"]
    criteria = task.get("acceptance_criteria", [])
    checks = task.get("expected_checks", [])
    risks = task.get("known_risks", [])
    lines = [
        "You are an isolated Qudron engineering worker. Work only in this Git worktree.",
        f"Task ID: {task['id']}",
        f"Title: {task['title']}",
        f"Mode: {task['mode']}",
        "",
        "TASK",
        task["prompt"],
        "",
        "BOUNDARIES",
        f"Allowed paths: {json.dumps(allowed, ensure_ascii=False)}",
        f"Denied paths: {json.dumps(task['deny_paths'], ensure_ascii=False)}",
    ]
    for heading, values, empty_note in (
        ("ACCEPTANCE CRITERIA", criteria, "No separate acceptance criteria were declared."),
        ("EXPECTED CHECKS (descriptive only; do not execute manifest text as shell commands)", checks, "No separate expected checks were declared."),
        ("KNOWN RISKS", risks, "No known risks were declared in the manifest."),
    ):
        lines.extend(["", heading])
        lines.extend([f"- {value}" for value in values] if values else [empty_note])
    lines.extend([
        "",
        "Do not commit, push, create a PR, merge, modify denied paths, or change files outside the allowed paths.",
        "Do not read .env files, credential stores, SSH keys, browser profiles, or unrelated private data.",
        "Do not publish content, send messages, make purchases, or call production services.",
        "For review mode, do not modify any files. Report findings with file paths, line numbers, severity, and evidence.",
        "Use only the repository context needed for this task. State what you did and which checks you actually ran.",
    ])
    return "\n".join(lines) + "\n"


def changed_files(
    worktree: Path,
    base_sha: str,
    deny_patterns: list[str],
) -> list[str]:
    # Intent-to-add makes ordinary untracked files appear in the diff without
    # committing their contents. First collect only path names.
    git(["add", "-N", "--", "."], worktree)
    names = git(["diff", "--name-only", "-z", base_sha, "--"], worktree).stdout
    files = {name for name in names.split("\0") if name}
    # Git ignores files such as .env by design. Scan ignored, untracked path
    # names separately so a generated secret cannot bypass the denylist just
    # because it matches .gitignore. Never read the ignored file contents.
    ignored = git(
        ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
        worktree,
    ).stdout
    files.update(
        name for name in ignored.split("\0")
        if name and path_is_denied(name, deny_patterns)
    )
    return sorted(files)


def verify_worker_binding(prepared: dict[str, Any]) -> dict[str, Any]:
    """Bind the handoff to the original worktree, branch, and immutable base HEAD."""
    worktree = Path(prepared["worktree"]).expanduser().resolve()
    violations: list[str] = []
    if not worktree.is_dir():
        return {"head_sha": None, "violations": ["worktree_missing"]}
    try:
        actual_root = repo_root(worktree)
    except FleetError:
        return {"head_sha": None, "violations": ["worktree_not_a_git_repository"]}
    if actual_root != worktree:
        violations.append("worktree_root_mismatch")
    branch = git(["branch", "--show-current"], worktree, check=False)
    actual_branch = branch.stdout.strip() if branch.returncode == 0 else ""
    if actual_branch != prepared["branch"]:
        violations.append("worker_branch_mismatch")
    head = git(["rev-parse", "--verify", "HEAD"], worktree, check=False)
    actual_head = head.stdout.strip() if head.returncode == 0 else None
    if actual_head != prepared["base_sha"]:
        violations.append("worker_head_moved")
    return {"head_sha": actual_head, "violations": violations}


def write_patch(worktree: Path, base_sha: str, patch_path: Path, files: list[str]) -> None:
    # This function must only be called after every changed path has passed the
    # task's allowlist check. Passing the validated paths also limits the diff.
    diff = git(
        ["--literal-pathspecs", "diff", "--binary", "--no-ext-diff", base_sha, "--", *files],
        worktree,
    ).stdout if files else ""
    safe_write(patch_path, diff)


def path_is_allowed(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) or PurePosixPath(path).match(pattern) for pattern in patterns)


def path_is_denied(path: str, patterns: list[str]) -> bool:
    return path_is_allowed(path, patterns)


def prepare_task(root: Path, task: dict[str, Any], run_id: str, worktree_root: Path, artifact_dir: Path) -> dict[str, Any]:
    base_sha = resolve_ref(root, task["base_ref"])
    worktree = worktree_root / task["id"]
    if worktree.exists():
        raise FleetError(f"Worktree path already exists: {worktree}")
    branch = f"agent-fleet/{run_id}/{task['id']}"
    git(["worktree", "add", "-b", branch, str(worktree), base_sha], root)
    prompt = make_prompt(task)
    prompt_file = artifact_dir / f"{task['id']}.prompt.md"
    safe_write(prompt_file, prompt)
    return {
        "task": task,
        "base_sha": base_sha,
        "worktree": worktree,
        "branch": branch,
        "prompt": prompt,
        "prompt_file": prompt_file,
    }


def execute_task(
    prepared: dict[str, Any],
    artifact_dir: Path,
    timeout: int,
    *,
    capture_logs: bool = False,
) -> dict[str, Any]:
    task = prepared["task"]
    agent = task["agent"]
    binary = AGENTS[agent]["binary"]
    executable = shutil.which(binary)
    base_result: dict[str, Any] = {
        "task_id": task["id"], "title": task["title"], "agent": agent,
        "mode": task["mode"], "branch": prepared["branch"],
        "base_sha": prepared["base_sha"], "head_sha": prepared["base_sha"],
        "binding_violations": [], "worktree": str(prepared["worktree"]),
        "acceptance_criteria": list(task.get("acceptance_criteria", [])),
        "expected_checks": list(task.get("expected_checks", [])),
        "known_risks": list(task.get("known_risks", [])),
        "allowed_paths": list(task["allowed_paths"]),
        "deny_paths": list(task["deny_paths"]),
        "status": "pending", "changed_files": [], "scope_violations": [],
        "exit_code": None,
    }
    if not executable:
        base_result["status"] = "unavailable"
        base_result["error"] = f"CLI not found on PATH: {binary}"
        return base_result
    try:
        argv, stdin_text = build_agent_command(agent, task["mode"], prepared["prompt"], prepared["prompt_file"], prepared["worktree"])
    except FleetError as exc:
        base_result["status"] = "unsupported_mode"
        base_result["error"] = str(exc)
        return base_result
    stdout_path = artifact_dir / f"{task['id']}.stdout.txt"
    stderr_path = artifact_dir / f"{task['id']}.stderr.txt"
    patch_path = artifact_dir / f"{task['id']}.patch"
    started = time.time()
    proc: subprocess.Popen[str] | None = None
    try:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        launch_argv = list(argv)
        if os.name == "nt" and executable and executable.lower().endswith((".cmd", ".bat")):
            launch_argv = ["cmd.exe", "/c", executable] + launch_argv[1:]
        proc = subprocess.Popen(
            launch_argv,
            cwd=str(prepared["worktree"]),
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=build_agent_env(agent),
            start_new_session=(os.name != "nt"),
            creationflags=creationflags,
        )
        stdout, stderr = proc.communicate(input=stdin_text, timeout=timeout)
        exit_code, timed_out = proc.returncode, False
    except subprocess.TimeoutExpired:
        timed_out = True
        if proc is not None and proc.poll() is None:
            if os.name == "nt":
                # taskkill /T terminates the CLI and its descendants on Windows.
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                )
                if proc.poll() is None:
                    proc.kill()
            else:
                # A separate session gives the worker a process group of its own.
                # Kill the group, not only the top-level CLI, to prevent orphan agents.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        stdout, stderr = proc.communicate() if proc is not None else ("", "")
        exit_code = 124
    # First collect path names, then validate scope. Never construct a patch
    # artifact from an untrusted worker diff before this validation succeeds.
    binding = verify_worker_binding(prepared)
    binding_violations = binding["violations"]
    base_result["head_sha"] = binding["head_sha"]
    base_result["binding_violations"] = binding_violations
    try:
        files = changed_files(prepared["worktree"], prepared["base_sha"], task["deny_paths"])
    except (FleetError, OSError) as exc:
        files = []
        binding_violations.append("worktree_inspection_failed")
    violations = [] if task["mode"] == "review" else [
        p for p in files
        if not path_is_allowed(p, task["allowed_paths"]) or path_is_denied(p, task["deny_paths"])
    ]
    if task["mode"] == "review" and files:
        violations = files[:]
    execution_succeeded = exit_code == 0 and not timed_out
    diff_check = git(
        ["--literal-pathspecs", "diff", "--check", prepared["base_sha"], "--", *files],
        prepared["worktree"],
        check=False,
    )
    diff_check_passed = diff_check.returncode == 0
    patch_exported = bool(execution_succeeded and not violations and not binding_violations and diff_check_passed and files)
    logs_exported = bool(capture_logs and not violations and not binding_violations and execution_succeeded)
    if logs_exported:
        safe_write(stdout_path, stdout)
        safe_write(stderr_path, stderr)
    if patch_exported:
        write_patch(prepared["worktree"], prepared["base_sha"], patch_path, files)
        patch_sha256 = hashlib.sha256(patch_path.read_bytes()).hexdigest()
    else:
        patch_sha256 = None
        # All-or-nothing handoff: do not export even the allowlisted subset when
        # a task has any out-of-scope change. This avoids leaking rejected file
        # contents through a mixed patch artifact.
        patch_path.unlink(missing_ok=True)
    if timed_out:
        status = "timed_out"
    elif exit_code != 0:
        status = "failed"
    elif violations or binding_violations:
        status = "scope_violation" if task["mode"] == "implement" else "review_mutated_files"
    elif not diff_check_passed:
        status = "diff_check_failed"
    elif task["mode"] == "review":
        status = "review_completed"
    elif not files:
        status = "no_changes"
    else:
        status = "completed"
    base_result.update({
        "status": status,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": round(time.time() - started, 2),
        "changed_files": files,
        "scope_violations": violations,
        "diff_check_passed": diff_check_passed,
        "patch_exported": patch_exported,
        "patch_path": str(patch_path) if patch_exported else None,
        "patch_sha256": patch_sha256,
        "patch_block_reason": (
            "scope_validation_failed" if violations or binding_violations
            else "worker_execution_failed" if not execution_succeeded
            else "diff_check_failed" if not diff_check_passed
            else None
        ),
        "logs_exported": logs_exported,
        "log_block_reason": (
            "scope_validation_failed" if (violations or binding_violations) and capture_logs
            else "worker_execution_failed" if capture_logs and not execution_succeeded
            else None
        ),
        "stdout_path": str(stdout_path) if logs_exported else None,
        "stderr_path": str(stderr_path) if logs_exported else None,
    })
    return base_result


def run_fleet(args: argparse.Namespace) -> int:
    root = repo_root(Path(args.repo))
    ensure_clean_repo(root)
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = load_manifest(manifest_path)
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    parent = root.parent
    worktrees_base = Path(args.worktree_root).expanduser().resolve() if args.worktree_root else parent / ".qudron-agent-worktrees"
    artifacts_base = Path(args.artifacts_root).expanduser().resolve() if args.artifacts_root else parent / ".qudron-agent-artifacts"
    for external_path, label in ((worktrees_base, "worktree"), (artifacts_base, "artifact")):
        if external_path == root or root in external_path.parents:
            raise FleetError(f"{label} directory must be outside the Git checkout: {external_path}")
    worktree_root = worktrees_base / run_id
    artifact_dir = artifacts_base / run_id
    worktree_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    artifact_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        os.chmod(worktree_root, 0o700)
        os.chmod(artifact_dir, 0o700)
    except OSError:
        pass
    prepared: list[dict[str, Any]] = []
    setup_errors: list[dict[str, str]] = []
    for task in manifest["tasks"]:
        try:
            prepared.append(prepare_task(root, task, run_id, worktree_root, artifact_dir))
        except Exception as exc:
            setup_errors.append({"task_id": task["id"], "error": str(exc)})
            break
    if setup_errors:
        # Remove only worktrees created during this invocation.
        for item in reversed(prepared):
            git(["worktree", "remove", "--force", str(item["worktree"])], root, check=False)
        report = {"version": 1, "run_id": run_id, "status": "setup_failed",
                  "setup_errors": setup_errors, "tasks": [],
                  "requires_human_review": True}
        safe_write(artifact_dir / "run.json", json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        return 2
    max_parallel = min(args.max_parallel or manifest["max_parallel"], MAX_PARALLEL)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = [
            pool.submit(execute_task, item, artifact_dir, args.timeout, capture_logs=args.capture_logs)
            for item in prepared
        ]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"status": "runner_error", "error": str(exc)})
    results.sort(key=lambda r: r.get("task_id", ""))
    statuses_ok = {"completed", "review_completed"}
    overall = "completed" if results and all(r.get("status") in statuses_ok for r in results) else "partial_or_failed"
    report = {
        "version": 1, "run_id": run_id, "status": overall,
        "repository": str(root), "max_parallel": max_parallel,
        "worktree_root": str(worktree_root), "artifact_dir": str(artifact_dir),
        "tasks": results,
        "requires_human_review": True,
        "merge_policy": "manual_only — no push, PR creation, or merge performed",
    }
    safe_write(artifact_dir / "run.json", json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if overall == "completed" else 1


def doctor(as_json: bool = False) -> int:
    rows = []
    for name, info in AGENTS.items():
        path = shutil.which(info["binary"])
        version = None
        if path:
            proc = subprocess.run([path, "--version"], text=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=10, check=False,
                                  env=build_agent_env(name))
            version = (proc.stdout.strip().splitlines() or [""])[0][:240]
        rows.append({"agent": name, "binary": info["binary"], "installed": bool(path),
                     "path": path, "version": version, "permission_profile": info["purpose"]})
    result = {"version": VERSION, "agents": rows}
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Qudron Agent Fleet {VERSION}\n")
        for row in rows:
            state = "FOUND" if row["installed"] else "missing"
            print(f"{row['agent']:<9} {state:<8} {row['version'] or ''}")
        print("\nDoctor checks CLI presence and version only; it does not make model calls or verify billing/quota.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Qudron engineering agents in isolated Git worktrees")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("doctor", help="Detect supported local CLIs without making model calls")
    d.add_argument("--json", action="store_true", dest="as_json")
    r = sub.add_parser("run", help="Run independent tasks from a JSON manifest")
    r.add_argument("--manifest", required=True)
    r.add_argument("--repo", default=".")
    r.add_argument("--max-parallel", type=int, default=None)
    r.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    r.add_argument(
        "--capture-logs",
        action="store_true",
        help="Save raw CLI stdout/stderr for in-scope tasks only; may contain proprietary or sensitive text",
    )
    r.add_argument("--worktree-root", default=None)
    r.add_argument("--artifacts-root", default=None)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor(args.as_json)
        if args.timeout < 60 or args.timeout > 24 * 60 * 60:
            raise FleetError("timeout must be between 60 seconds and 24 hours")
        if args.max_parallel is not None and not 1 <= args.max_parallel <= MAX_PARALLEL:
            raise FleetError(f"max-parallel must be between 1 and {MAX_PARALLEL}")
        return run_fleet(args)
    except (FleetError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"agent-fleet: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
