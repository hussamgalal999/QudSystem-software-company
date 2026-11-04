#!/usr/bin/env python3
"""Create persistent random OpenBot supervisor/client tokens in a private .env.

Only fills blank values. Existing non-empty values are preserved. The file is
atomically replaced with mode 0600; generated token values are never printed.
"""
from __future__ import annotations

import os
import secrets
import sys
import tempfile
from pathlib import Path

KEYS = ("COMPUTER_SUPERVISOR_TOKEN", "COMPUTER_TOKEN")


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


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".env")
    generated = prepare(target)
    if generated:
        print(f"Generated private OpenBot credentials in {target}: {', '.join(generated)} (values hidden).")
    else:
        print(f"OpenBot credentials already present in {target}; no changes made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
