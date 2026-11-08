#!/usr/bin/env python3
"""
Qudron Smart Swarm Orchestrator
================================
Token-efficient methodology:
1. FETCH existing code from GitHub instead of generating from scratch
2. PATCH only the delta (surgical fixes)
3. VALIDATE via existing CI pipeline (zero local token cost)
4. DELEGATE to free AI APIs for code review/generation

This script automates the PR review → fix → test → commit → push pipeline.
"""

import subprocess
import json
import os
import sys
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RUNTIME_DIR = REPO_ROOT / "ops" / "qudron-runtime"
TESTS_DIR = RUNTIME_DIR / "tests"
LOG_FILE = REPO_ROOT / "ops" / "swarm-orchestrator" / "swarm_log.jsonl"

# ─── Token-Saving Strategy Registry ───────────────────────────────
STRATEGIES = {
    "github_search": {
        "desc": "Search GitHub for existing implementations instead of writing from scratch",
        "api": "https://api.github.com/search/code?q={query}+language:python",
        "auth_required": False,  # public search is free & no auth needed
        "token_savings": "70-90%",
    },
    "patch_only": {
        "desc": "Generate only git diff patches, not full file rewrites",
        "token_savings": "80%+",
    },
    "ci_delegation": {
        "desc": "Push to branch and let GitHub Actions CI run tests (free for public repos)",
        "token_savings": "100% on test execution tokens",
    },
    "template_reuse": {
        "desc": "Use existing project patterns as templates for new code",
        "token_savings": "60-80%",
    },
}


def log_event(event_type: str, details: dict):
    """Append structured event to swarm log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "type": event_type,
        "details": details,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def run_cmd(cmd: list[str], cwd: str | None = None) -> dict:
    """Run a command and return structured result."""
    result = subprocess.run(
        cmd,
        cwd=cwd or str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout.strip()[-500:],  # truncate to save tokens
        "stderr": result.stderr.strip()[-200:],
    }


def git_status() -> dict:
    """Get current git status summary."""
    branch = run_cmd(["git", "branch", "--show-current"])
    status = run_cmd(["git", "status", "--porcelain"])
    return {
        "branch": branch["stdout"],
        "changed_files": len(status["stdout"].splitlines()) if status["stdout"] else 0,
        "dirty": bool(status["stdout"]),
    }


def run_tests(test_file: str | None = None) -> dict:
    """Run pytest with minimal output to save tokens."""
    cmd = [sys.executable, "-m", "pytest", "-v", "--tb=line", "-q"]
    if test_file:
        cmd.append(test_file)
    result = run_cmd(cmd, cwd=str(RUNTIME_DIR))
    passed = result["stdout"].count(" PASSED")
    failed = result["stdout"].count(" FAILED")
    return {
        "passed": passed,
        "failed": failed,
        "total": passed + failed,
        "exit_code": result["returncode"],
        "summary": result["stdout"].splitlines()[-3:] if result["stdout"] else [],
    }


def commit_and_push(message: str, files: list[str] | None = None):
    """Stage, commit, and push with conventional commit message."""
    if files:
        for f in files:
            run_cmd(["git", "add", f])
    else:
        run_cmd(["git", "add", "-A"])

    result = run_cmd(["git", "commit", "-m", message])
    log_event("commit", {"message": message, "result": result["stdout"][:200]})

    push = run_cmd(["git", "push", "origin", "HEAD"])
    log_event("push", {"result": push["stdout"][:200], "exit": push["returncode"]})
    return push


def search_github_patterns(query: str, language: str = "python") -> list[dict]:
    """
    Search GitHub public repos for existing code patterns.
    FREE, no auth needed for basic search. Saves massive tokens
    vs generating code from scratch.
    """
    import urllib.request
    import urllib.parse

    url = f"https://api.github.com/search/code?q={urllib.parse.quote(query)}+language:{language}"
    headers = {"Accept": "application/vnd.github.v3+json"}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return [
                {
                    "repo": item["repository"]["full_name"],
                    "path": item["path"],
                    "url": item["html_url"],
                    "score": item.get("score", 0),
                }
                for item in data.get("items", [])[:5]
            ]
    except Exception as e:
        log_event("github_search_error", {"query": query, "error": str(e)})
        return []


# ─── PR #27 Fix Registry ──────────────────────────────────────────
PR27_FIXES = [
    {
        "id": "fix-job-id-validation",
        "file": "ops/qudron-runtime/qudron_worker.py",
        "desc": "Add job_id empty/None validation in MCP functions",
        "lines": "455-476",
        "strategy": "patch_only",
    },
    {
        "id": "fix-quorum-formula-format",
        "file": "ops/qudron-runtime/workflow_orchestrator.py",
        "desc": "Fix unformatted f-string in quorum validation error message",
        "lines": "54-57",
        "strategy": "patch_only",
    },
    {
        "id": "fix-quorum-default-inconsistency",
        "file": "ops/qudron-runtime/workflow_orchestrator.py",
        "desc": "Fix inconsistent quorum default (0 vs 1) between run() and status evaluation",
        "lines": "625-627,693-695",
        "strategy": "patch_only",
    },
    {
        "id": "add-missing-tests",
        "file": "ops/qudron-runtime/tests/test_mcp_gateway.py",
        "desc": "Add test cases for empty/None job_id rejection",
        "strategy": "template_reuse",
    },
]


def print_dashboard():
    """Print swarm status dashboard."""
    status = git_status()
    print("=" * 60)
    print("  QUDRON SWARM ORCHESTRATOR — STATUS DASHBOARD")
    print("=" * 60)
    print(f"  Branch:        {status['branch']}")
    print(f"  Changed files: {status['changed_files']}")
    print(f"  Pending fixes: {len(PR27_FIXES)}")
    print(f"  Strategies:    {', '.join(STRATEGIES.keys())}")
    print("=" * 60)

    if LOG_FILE.exists():
        with open(LOG_FILE) as f:
            events = [json.loads(l) for l in f if l.strip()]
        print(f"\n  Recent events ({len(events)} total):")
        for e in events[-5:]:
            print(f"    [{e['timestamp'][:19]}] {e['type']}: {json.dumps(e['details'])[:80]}")
    print()


if __name__ == "__main__":
    print_dashboard()
    log_event("orchestrator_start", {
        "fixes": len(PR27_FIXES),
        "strategies": list(STRATEGIES.keys()),
    })
