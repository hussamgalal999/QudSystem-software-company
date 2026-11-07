#!/usr/bin/env python3
"""Prepare per-task Git worktrees and collect validated, human-reviewable patches.

This tool does not launch model CLIs, execute task shell commands, push, open PRs,
merge, or deploy. Operators launch any approved agent in its own restricted VM.
"""
from __future__ import annotations
import argparse, datetime as dt, fnmatch, hashlib, json, re, shutil, subprocess, sys
from pathlib import Path

ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
RESULT_DIR = ".qudron-worker"
DENY = (".git/**", ".env", ".env.*", "**/.env", "**/.env.*", "**/secrets/**", "**/*private_key*", "**/*credentials*")
CLIS = ("codex", "claude", "gemini", "opencode", "aider", "goose")

class WorktreeError(RuntimeError):
    pass

def git(cwd: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True)
    if check and p.returncode:
        raise WorktreeError(p.stderr.strip() or p.stdout.strip() or f"git {args[0]} failed")
    return p.stdout.strip()

def repo_root(path: Path) -> Path:
    return Path(git(path, "rev-parse", "--show-toplevel")).resolve()

def safe_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorktreeError("allowed_paths must contain non-empty relative paths")
    p = value.strip().replace("\\", "/")
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p) or any(x in {"", ".", ".."} for x in p.split("/")):
        raise WorktreeError(f"unsafe path: {value}")
    if ("**" in p and not p.endswith("/**")) or any(x in p for x in "?[]") or ("*" in p and not p.endswith("/**")):
        raise WorktreeError(f"unsupported wildcard path: {value}")
    return p

def load_manifest(path: Path) -> dict:
    try: m = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e: raise WorktreeError(f"cannot read manifest: {e}") from e
    if not isinstance(m, dict) or type(m.get("version")) is not int or m["version"] != 1 or not isinstance(m.get("base_ref"), str) or not m["base_ref"].strip():
        raise WorktreeError("manifest requires version: 1 and a non-empty base_ref")
    tasks = m.get("tasks")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 8: raise WorktreeError("manifest must contain 1–8 tasks")
    ids, out = set(), []
    for t in tasks:
        if not isinstance(t, dict) or not isinstance(t.get("task_id"), str) or not ID.fullmatch(t["task_id"]): raise WorktreeError("invalid task_id")
        tid = t["task_id"]
        if tid in ids: raise WorktreeError(f"duplicate task_id: {tid}")
        ids.add(tid)
        if any(not isinstance(t.get(k), str) or not t[k].strip() for k in ("title", "objective")): raise WorktreeError(f"{tid}: title/objective required")
        paths = t.get("allowed_paths")
        criteria = t.get("acceptance_criteria")
        if not isinstance(paths, list) or not paths or not isinstance(criteria, list) or not all(isinstance(x, str) and x.strip() for x in criteria): raise WorktreeError(f"{tid}: allowed_paths and acceptance_criteria required")
        allow = [safe_path(x) for x in paths]
        extra_deny = t.get("deny_paths", [])
        if not isinstance(extra_deny, list): raise WorktreeError(f"{tid}: deny_paths must be a list")
        deny = list(DENY) + [safe_path(x) for x in extra_deny]
        out.append({"task_id": tid, "title": t["title"].strip(), "objective": t["objective"].strip(), "allowed_paths": allow, "deny_paths": deny, "acceptance_criteria": [x.strip() for x in criteria], "tests": t.get("tests", []) if isinstance(t.get("tests"), list) else [], "risks": t.get("risks", []) if isinstance(t.get("risks"), list) else [], "requires_human_review": True})
    for i, a in enumerate(out):
        for b in out[i+1:]:
            for x in a["allowed_paths"]:
                for y in b["allowed_paths"]:
                    xr, xt = (x[:-3].rstrip("/"), True) if x.endswith("/**") else (x, False)
                    yr, yt = (y[:-3].rstrip("/"), True) if y.endswith("/**") else (y, False)
                    if xr == yr or (xt and yr.startswith(xr + "/")) or (yt and xr.startswith(yr + "/")):
                        raise WorktreeError(f"Overlapping write scopes: {a['task_id']}:{x} and {b['task_id']}:{y}")
    return {"version": 1, "base_ref": m["base_ref"].strip(), "tasks": out}

def prepare(repo: Path, manifest_path: Path, worktree_root: Path) -> dict:
    repo = repo_root(repo); m = load_manifest(manifest_path)
    root = worktree_root.expanduser().absolute().resolve()
    if root == repo or root.is_relative_to(repo) or repo.is_relative_to(root): raise WorktreeError("worktree_root must be outside and not contain the repository")
    base = git(repo, "rev-parse", "--verify", "--end-of-options", m["base_ref"] + "^{commit}")
    if not re.fullmatch(r"[0-9a-f]{40}", base): raise WorktreeError("Git did not return a full commit SHA")
    control = root / ".qudron-control"
    if control.exists(): raise WorktreeError(f"control directory already exists: {control}")
    if root.exists() and any(root.iterdir()): raise WorktreeError("worktree_root must be a new or empty directory")
    (control / "tasks").mkdir(parents=True); (control / "prompts").mkdir()
    made = []
    try:
        records = []
        for t in m["tasks"]:
            tid = t["task_id"]; branch = f"qudron/worker/{tid}"; path = root / tid
            check = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo)
            if path.exists() or check.returncode == 0: raise WorktreeError(f"worktree or branch already exists for {tid}")
            git(repo, "worktree", "add", "-b", branch, str(path), base); made.append((path, branch))
            rec = {**t, "base_sha": base, "branch": branch, "worktree": str(path), "created_at": dt.datetime.now(dt.timezone.utc).isoformat()}
            (control / "tasks" / f"{tid}.json").write_text(json.dumps(rec, indent=2) + "\n")
            prompt = [f"# {rec['title']}", "", f"Task ID: `{tid}`", f"Base: `{base}`", f"Branch: `{branch}`", "", "## Objective", rec["objective"], "", "## Writable files", *[f"- `{x}`" for x in rec["allowed_paths"]], "", "## Acceptance criteria", *[f"- [ ] {x}" for x in rec["acceptance_criteria"]], "", "## Handoff", f"Write `{RESULT_DIR}/result.json` using `worker-result.schema.json`.", "Stage all source files before collection. Do not push, open PRs, merge, deploy, read secrets, or edit outside the allowlist. Human review is mandatory."]
            pp = control / "prompts" / f"{tid}.md"; pp.write_text("\n".join(prompt) + "\n")
            records.append({"task_id": tid, "branch": branch, "worktree": str(path), "prompt": str(pp), "base_sha": base})
        result = {"version": 1, "repo": str(repo), "base_ref": m["base_ref"], "base_sha": base, "tasks": records}
        (control / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
    except Exception:
        for path, branch in reversed(made):
            git(repo, "worktree", "remove", "--force", str(path), check=False); git(repo, "branch", "-D", branch, check=False)
        shutil.rmtree(control, ignore_errors=True); raise

def status(root: Path) -> dict:
    root = root.expanduser().resolve(); m = json.loads((root / ".qudron-control/manifest.json").read_text())
    rows = []
    for r in m["tasks"]:
        p = Path(r["worktree"])
        if not p.is_dir(): rows.append({"task_id": r["task_id"], "state": "missing"}); continue
        rows.append({"task_id": r["task_id"], "branch": git(p, "branch", "--show-current"), "head_sha": git(p, "rev-parse", "HEAD"), "dirty_entries": len(git(p, "status", "--porcelain", "--untracked-files=all").splitlines()))})
    return {"base_sha": m["base_sha"], "tasks": rows}

def matches(path: str, patterns: list[str]) -> bool:
    return any((path == p[:-3].rstrip("/") or path.startswith(p[:-3].rstrip("/") + "/")) if p.endswith("/**") else fnmatch.fnmatchcase(path, p) for p in patterns)

def collect(root: Path, task_id: str, artifact_root: Path) -> dict:
    if not isinstance(task_id, str) or not ID.fullmatch(task_id): raise WorktreeError(f"task_id must match {ID.pattern}")
    root = root.expanduser().resolve(); rec = json.loads((root / ".qudron-control/tasks" / f"{task_id}.json").read_text())
    path = Path(rec["worktree"]).resolve()
    if path != (root / task_id).resolve() or not path.is_dir() or git(path, "branch", "--show-current") != rec["branch"]: raise WorktreeError("worker worktree/branch does not match its control record")
    try: result = json.loads((path / RESULT_DIR / "result.json").read_text())
    except (OSError, json.JSONDecodeError) as e: raise WorktreeError(f"missing or invalid worker result: {e}") from e
    head = git(path, "rev-parse", "HEAD")
    untracked = [x for x in git(path, "ls-files", "--others", "--exclude-standard").splitlines() if x != RESULT_DIR and not x.startswith(RESULT_DIR + "/")]
    if untracked: raise WorktreeError("Untracked source files are not included in Git patches; stage them before collection: " + ", ".join(untracked))
    changed = sorted(set(git(path, "diff", "--name-only", rec["base_sha"]).splitlines()))
    required = ("task_id", "status", "summary", "base_sha", "head_sha", "changed_files", "tests", "risks", "requires_human_review")
    if not isinstance(result, dict) or result.get("schema_version") != 1 or any(k not in result for k in required): raise WorktreeError("worker result is missing required schema fields")
    if result["task_id"] != task_id or not isinstance(result["status"], str) or result["status"] not in {"completed", "blocked", "failed"} or not isinstance(result["summary"], str) or not result["summary"].strip(): raise WorktreeError("worker result identity/status/summary is invalid")
    if not isinstance(result["changed_files"], list) or not all(isinstance(x, str) for x in result["changed_files"]): raise WorktreeError("changed_files must be a list of path strings")
    if result["base_sha"] != rec["base_sha"] or result["head_sha"] != head or sorted(set(result["changed_files"])) != changed: raise WorktreeError("reported commit SHAs or changed_files do not match Git")
    if result["requires_human_review"] is not True or not isinstance(result["tests"], list) or not isinstance(result["risks"], list): raise WorktreeError("human review is required; tests/risks must be lists")
    for t in result["tests"]:
        if not isinstance(t, dict) or not isinstance(t.get("name"), str) or not isinstance(t.get("status"), str) or t["status"] not in {"passed", "failed", "blocked", "not_run"}: raise WorktreeError("invalid test evidence entry")
    if not all(isinstance(x, str) for x in result["risks"]): raise WorktreeError("risks must be strings")
    outside = [x for x in changed if not matches(x, rec["allowed_paths"]) or matches(x, rec["deny_paths"])]
    if outside: raise WorktreeError("worker changed disallowed paths: " + ", ".join(outside))
    if subprocess.run(["git", "diff", "--check", rec["base_sha"]], cwd=path).returncode: raise WorktreeError("git diff --check failed")
    destroot = artifact_root.expanduser().resolve()
    if destroot == path or destroot.is_relative_to(path): raise WorktreeError("artifact_root must be outside the worker worktree")
    dest = destroot / task_id; dest.mkdir(parents=True, exist_ok=True)
    patch = git(path, "diff", "--binary", rec["base_sha"])
    patch_path = dest / "diff.patch"
    patch_path.write_text(patch)
    (dest / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    (dest / "task.json").write_text(json.dumps(rec, indent=2) + "\n")
    log = path / RESULT_DIR / "test.log"
    if log.is_file(): shutil.copyfile(log, dest / "test.log")
    digest = hashlib.sha256(patch.encode()).hexdigest()
    (dest / "summary.md").write_text(f"# {task_id}\n\n- Status: {result['status']}\n- Branch: `{rec['branch']}`\n- Base: `{rec['base_sha']}`\n- Head: `{head}`\n- Patch SHA-256: `{digest}`\n- Human review required: yes\n\n## Summary\n{result['summary']}\n\n## Changed files\n" + "".join(f"- `{x}`\n" for x in changed))
    return {"task_id": task_id, "artifact_dir": str(dest), "patch": str(patch_path), "changed_files": changed, "patch_sha256": digest, "human_review_required": True}

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor"); d.set_defaults(fn=lambda a: {"git": shutil.which("git"), "agent_clis_detected_only": {x: shutil.which(x) for x in CLIS}, "agent_launch": False})
    a = sub.add_parser("prepare"); a.add_argument("--repo", type=Path, default=Path.cwd()); a.add_argument("--manifest", type=Path, required=True); a.add_argument("--worktree-root", type=Path, required=True); a.set_defaults(fn=lambda x: prepare(x.repo, x.manifest, x.worktree_root))
    s = sub.add_parser("status"); s.add_argument("--worktree-root", type=Path, required=True); s.set_defaults(fn=lambda x: status(x.worktree_root))
    c = sub.add_parser("collect"); c.add_argument("--worktree-root", type=Path, required=True); c.add_argument("--task-id", required=True); c.add_argument("--artifact-root", type=Path, required=True); c.set_defaults(fn=lambda x: collect(x.worktree_root, x.task_id, x.artifact_root))
    args = p.parse_args()
    try: print(json.dumps({"ok": True, "result": args.fn(args)}, indent=2)); return 0
    except (WorktreeError, OSError, ValueError, KeyError) as e: print(json.dumps({"ok": False, "error": str(e)}, indent=2), file=sys.stderr); return 2

if __name__ == "__main__": raise SystemExit(main())
