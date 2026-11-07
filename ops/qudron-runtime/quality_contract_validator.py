"""Fail-closed validator for Qudron's per-task quality contracts."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

VALID_MATURITY = {f"M{i}" for i in range(8)}
MINIMUM_MATURITY = {
    "Runtime": "M3", "Workforce": "M3", "Continuity": "M3",
    "Product Engineering": "M3", "External Swarm": "M4", "Manus": "M4",
    "Model Supply": "M4", "Android": "M4", "Capacity": "M6",
    "Infrastructure": "M6", "Release": "M6", "Governance": "M5",
    "Android Security": "M5", "CVPen": "M5", "Commercial": "M5",
    "Growth": "M5", "Communications": "M5", "Portfolio": "M4",
}
CRITICAL_GATE_PATTERN = re.compile(
    r"security|privacy|authoriz|approval|payment|consent|secret|"
    r"tenant_isolation|data_classification|owner_device|retention|rollback|"
    r"risk_acceptance|license_and_secret|written_scope|credential_scope|"
    r"least_privilege|audit_trail|critical_high|source_provenance|fail_closed",
    re.IGNORECASE,
)


def parse_profile_gates(framework_text: str) -> dict[str, set[str]]:
    """Read canonical gate IDs only from the specialty verification profiles."""
    section = re.search(
        r"^## Specialty-specific verification profiles\s*$([\s\S]*?)"
        r"^### Per-task acceptance contract and validation\s*$",
        framework_text,
        re.MULTILINE,
    )
    if not section:
        raise ValueError("Quality framework is missing its specialty profile section")
    profile_text = section.group(1)
    headings = list(re.finditer(r"^### (.+)$", profile_text, re.MULTILINE))
    profiles: dict[str, set[str]] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(profile_text)
        block = profile_text[heading.end():end]
        profiles[heading.group(1).strip()] = set(
            re.findall(r"^- \[ \] `([^`]+)`", block, re.MULTILINE)
        )
    return profiles


def validate_task_contract(task: dict[str, Any], profiles: dict[str, set[str]]) -> list[str]:
    task_id = str(task.get("id", "<unknown>"))
    errors: list[str] = []
    area = task.get("area")
    profile = task.get("verification_profile")
    if not isinstance(area, str) or area not in profiles:
        return [f"{task_id}: unknown verification area {area!r}"]
    if not isinstance(profile, list) or not profile or any(not isinstance(x, str) for x in profile):
        return [f"{task_id}: verification_profile must be a non-empty string list"]
    if len(profile) != len(set(profile)):
        errors.append(f"{task_id}: verification_profile contains duplicate gate IDs")
    unknown_profile = sorted(set(profile) - profiles[area])
    if unknown_profile:
        errors.append(f"{task_id}: unknown profile gate IDs: {unknown_profile}")

    mandatory = task.get("mandatory_gates")
    if not isinstance(mandatory, list) or not mandatory or any(not isinstance(x, str) for x in mandatory):
        errors.append(f"{task_id}: mandatory_gates must be a non-empty string list")
        mandatory = []
    if len(mandatory) != len(set(mandatory)):
        errors.append(f"{task_id}: mandatory_gates contains duplicates")
    if not set(mandatory).issubset(set(profile)):
        errors.append(f"{task_id}: mandatory_gates must be a subset of verification_profile")
    if not set(mandatory).issubset(profiles[area]):
        errors.append(f"{task_id}: mandatory_gates contains unknown canonical gate IDs")

    critical = task.get("critical_gates")
    if not isinstance(critical, list) or any(not isinstance(x, str) for x in critical):
        errors.append(f"{task_id}: critical_gates must be a string list")
        critical = []
    if not set(critical).issubset(set(mandatory)):
        errors.append(f"{task_id}: critical_gates must be a subset of mandatory_gates")
    required_critical = {g for g in mandatory if CRITICAL_GATE_PATTERN.search(g)}
    if not required_critical.issubset(set(critical)):
        errors.append(f"{task_id}: critical gates omitted: {sorted(required_critical - set(critical))}")

    weights = task.get("gate_weights")
    if not isinstance(weights, dict):
        errors.append(f"{task_id}: gate_weights must be an object")
        weights = {}
    if set(weights) != set(mandatory):
        errors.append(f"{task_id}: gate_weights keys must exactly match mandatory_gates")
    numeric_weights = []
    for gate, weight in weights.items():
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight <= 0:
            errors.append(f"{task_id}: gate weight for {gate!r} must be a positive finite number")
        else:
            numeric_weights.append(float(weight))
    if numeric_weights and abs(sum(numeric_weights) - 100.0) > 0.01:
        errors.append(f"{task_id}: gate weights must sum to 100")

    maturity = task.get("required_maturity")
    if maturity not in VALID_MATURITY:
        errors.append(f"{task_id}: required_maturity must be M0-M7")
    else:
        minimum = MINIMUM_MATURITY.get(area, "M3")
        if int(maturity[1:]) < int(minimum[1:]):
            errors.append(f"{task_id}: {area} requires at least {minimum}, got {maturity}")
    return errors


def validate_registry(registry: dict[str, Any], framework_text: str) -> list[str]:
    profiles = parse_profile_gates(framework_text)
    tasks = registry.get("tasks")
    if not isinstance(tasks, list):
        return ["registry.tasks must be a list"]
    errors: list[str] = []
    ids = [task.get("id") for task in tasks if isinstance(task, dict)]
    if len(ids) != len(tasks) or len(ids) != len(set(ids)):
        errors.append("registry task IDs must be present and unique")
    for task in tasks:
        if isinstance(task, dict):
            errors.extend(validate_task_contract(task, profiles))
    if registry.get("total_tasks") != len(tasks):
        errors.append("registry.total_tasks does not match tasks length")
    actual_counts: dict[str, int] = {}
    for task in tasks:
        if isinstance(task, dict) and isinstance(task.get("status"), str):
            actual_counts[task["status"]] = actual_counts.get(task["status"], 0) + 1
    if actual_counts != registry.get("computed_status_counts"):
        errors.append("registry.computed_status_counts does not match task records")
    return errors


def validate_registry_files(registry_path: Path, framework_path: Path) -> list[str]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    framework = framework_path.read_text(encoding="utf-8")
    return validate_registry(registry, framework)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    errors = validate_registry_files(
        Path(__file__).with_name("project_task_registry.json"),
        root / "docs" / "QUALITY_VERIFICATION_FRAMEWORK.md",
    )
    if errors:
        raise SystemExit("\n".join(errors))
    print("Qudron quality contracts valid.")
