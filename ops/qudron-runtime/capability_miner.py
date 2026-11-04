"""Bounded, read-only GitHub repository miner for Qudron.

This first pass ranks repository metadata and tree paths. It never downloads
or executes source code. Every result is a candidate until a later evaluator
reads source evidence, checks the license and runs isolated tests.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from capability_registry import register_capability
from github_inventory import discover_repositories, repository_tree, GitHubInventoryError


README_NAMES = {"readme", "readme.md", "readme.rst", "readme.txt"}
LICENSE_NAMES = {"license", "license.md", "license.txt", "copying", "copying.md"}
MANIFEST_NAMES = {
    "pyproject.toml", "requirements.txt", "package.json", "pnpm-lock.yaml",
    "go.mod", "cargo.toml", "pom.xml", "build.gradle", "dockerfile",
}
CI_PREFIXES = (".github/workflows/", ".gitlab-ci", ".circleci/")


def _parse_updated(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def evaluate_repository(repo: dict[str, Any], tree: dict[str, Any]) -> dict[str, Any]:
    """Score metadata/path evidence only; never infer license or code quality."""
    entries = tree.get("entries", [])
    paths = [str(entry.get("path", "")) for entry in entries if isinstance(entry, dict)]
    lower = [path.lower() for path in paths]
    basenames = {path.rsplit("/", 1)[-1] for path in lower}
    has_readme = any(name in README_NAMES for name in basenames)
    has_license_file = any(name in LICENSE_NAMES for name in basenames)
    has_tests = any(
        path.startswith(("tests/", "test/", "__tests__/"))
        or "/tests/" in path or "/__tests__/" in path
        or path.rsplit("/", 1)[-1].startswith(("test_", "spec."))
        for path in lower
    )
    has_manifest = bool(basenames & MANIFEST_NAMES)
    has_ci = any(path.startswith(CI_PREFIXES) for path in lower)

    score, reasons = 0, []
    if repo.get("description"):
        score += 5; reasons.append("has_description")
    if has_readme:
        score += 10; reasons.append("readme_present")
    if has_license_file:
        score += 10; reasons.append("license_file_present_not_legal_verification")
    if has_tests:
        score += 10; reasons.append("test_paths_present_not_tested")
    if has_manifest:
        score += 10; reasons.append("build_or_dependency_manifest_present")
    if has_ci:
        score += 5; reasons.append("ci_configuration_present")
    updated = _parse_updated(repo.get("updated_at"))
    if updated:
        age_days = max(0, (datetime.now(timezone.utc) - updated).days)
        if age_days <= 90:
            score += 20; reasons.append("updated_within_90_days")
        elif age_days <= 365:
            score += 10; reasons.append("updated_within_1_year")
    if not repo.get("archived", False):
        score += 5; reasons.append("not_archived")
    else:
        reasons.append("archived_repository")
    score = min(100, score)

    full_name = str(repo.get("full_name", "")).strip()
    if not full_name or "/" not in full_name:
        raise ValueError("Repository metadata is missing a valid full_name")
    archived = bool(repo.get("archived", False))
    return {
        "id": "github:" + full_name.lower(),
        "kind": "repository",
        "name": full_name,
        "description": str(repo.get("description") or ""),
        "version": str(repo.get("default_branch") or ""),
        "source_url": str(repo.get("html_url") or ""),
        "license": "unknown",
        "status": "deprecated" if archived else "candidate",
        "trust_score": score,
        "verified_at": None,
        "tags": ["github", "repository", "private" if repo.get("private") else "public"],
        "metadata": {
            "visibility": repo.get("visibility"),
            "private": bool(repo.get("private")),
            "archived": archived,
            "updated_at": repo.get("updated_at"),
            "size_kb": repo.get("size"),
            "default_branch": repo.get("default_branch"),
            "tree_entry_count": len(paths),
            "tree_truncated": bool(tree.get("truncated")),
            "signals": {
                "readme_present": has_readme,
                "license_file_present": has_license_file,
                "tests_paths_present": has_tests,
                "manifest_present": has_manifest,
                "ci_configuration_present": has_ci,
            },
            "score_reasons": reasons,
            "evaluation_scope": "metadata_and_paths_only_no_source_execution",
        },
    }


def mine_repositories(owner: str, token: str, registry_db: str | Path,
                      max_repositories: int = 50) -> dict[str, Any]:
    """Discover authorized repositories and register bounded candidate records."""
    if not 1 <= max_repositories <= 200:
        raise ValueError("max_repositories must be between 1 and 200")
    repositories = discover_repositories(owner, token, per_page=100, max_pages=20)
    repositories.sort(
        key=lambda item: _parse_updated(item.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    selected = repositories[:max_repositories]
    registered, failures, scanned_paths = 0, [], 0
    for repo in selected:
        full_name = str(repo.get("full_name") or "")
        branch = str(repo.get("default_branch") or "")
        if not full_name or not branch:
            failures.append({"repository": full_name or "unknown", "reason": "missing_repository_or_default_branch"})
            continue
        try:
            tree = repository_tree(full_name, branch, token)
            candidate = evaluate_repository(repo, tree)
            register_capability(registry_db, candidate)
            registered += 1
            scanned_paths += int(candidate["metadata"]["tree_entry_count"])
        except (GitHubInventoryError, ValueError) as exc:
            # Keep logs/results sanitized; never return exception strings that might contain URLs or secrets.
            failures.append({"repository": full_name, "reason": type(exc).__name__})
            if len(failures) >= 5:
                break
    return {
        "repositories_discovered": len(repositories),
        "repositories_selected": len(selected),
        "candidates_registered": registered,
        "paths_indexed": scanned_paths,
        "failures": failures,
        "registry_db": str(registry_db),
        "source_execution_performed": False,
        "license_verified": False,
        "candidate_promotion_performed": False,
    }


def mine_from_environment(registry_db: str | Path | None = None,
                          max_repositories: int = 50) -> dict[str, Any]:
    owner = os.getenv("GITHUB_OWNER", "").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not owner or not token:
        raise GitHubInventoryError("Set GITHUB_OWNER and GITHUB_TOKEN in the host secret manager")
    return mine_repositories(
        owner, token,
        registry_db or os.getenv("QUDRON_CAPABILITY_DB", "/app/data/capabilities.sqlite3"),
        max_repositories=max_repositories,
    )
