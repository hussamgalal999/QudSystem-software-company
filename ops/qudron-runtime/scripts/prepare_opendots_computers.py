#!/usr/bin/env python3
"""Prepare private OpenDots computer tokens and its external Docker network.

Only fills blank credentials in a private .env file. The token values are
never printed. A dedicated Docker bridge network is created for Dot computers;
the privileged Docker socket remains mounted only into computer-supervisor.
"""
from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

KEYS = ("COMPUTER_SUPERVISOR_TOKEN", "COMPUTER_TOKEN")


def read_env(lines: list[str], key: str, default: str = "") -> str:
    value = default
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        name, current = line.split("=", 1)
        if name.strip() == key:
            value = current.strip().strip('"').strip("'")
    return value


def prepare(path: Path) -> tuple[str, ...]:
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    values: dict[str, str] = {}
    positions: dict[str, int] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in KEYS:
            positions[key] = index
            values[key] = value.strip().strip('"').strip("'")

    generated = []
    for key in KEYS:
        current = values.get(key, "")
        if len(current) < 32:
            current = secrets.token_urlsafe(48)
            generated.append(key)
        line = f"{key}={current}"
        if key in positions:
            lines[positions[key]] = line
        else:
            lines.append(line)

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return tuple(generated)


def ensure_docker_network(namespace: str, runner=subprocess.run) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,54}", namespace):
        raise ValueError("COMPUTER_NAMESPACE must be 1-55 safe letters, digits, dots, underscores or dashes")
    name = f"{namespace}-computers"
    inspect = runner(
        ["docker", "network", "inspect", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if inspect.returncode != 0:
        runner(["docker", "network", "create", name], check=True)
    return name


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".env")
    generated = prepare(target)
    lines = target.read_text(encoding="utf-8").splitlines()
    namespace = read_env(lines, "COMPUTER_NAMESPACE", "qudron") or "qudron"
    network = ensure_docker_network(namespace)
    if generated:
        print(f"Generated private OpenBot credentials in {target}: {', '.join(generated)} (values hidden).")
    else:
        print(f"OpenBot credentials already present in {target}; no changes made.")
    print(f"Verified dedicated Docker network: {network}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
