#!/usr/bin/env python3
"""Create or refresh a per-Dot Qudron MCP connection in an OpenDots workspace.

The script never prints either owner token. It uses the supported OpenDots API
and the protected Qudron MCP endpoint; it does not edit OpenDots SQLite tables.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

OPENDOTS_URL = os.getenv("OPENDOTS_INTERNAL_URL", "http://opendots:4310").rstrip("/")
QUDRON_MCP_URL = os.getenv("QUDRON_MCP_URL", "http://qudron:8765/mcp")
OWNER_TOKEN_FILE = Path(os.getenv("OPENDOTS_OWNER_TOKEN_FILE", "/opendots-data/.owner-token"))
QUDRON_TOKEN_FILE = Path(os.getenv("QUDRON_TOKEN_FILE", "/qudron-data/api_token"))
CONNECTION_NAME = "Qudron"


class BootstrapError(RuntimeError):
    pass


def read_secret(env_name: str, path: Path) -> str:
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def request_json(url: str, token: str, method: str = "GET",
                 payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise BootstrapError("OpenDots API response exceeded the bootstrap size limit")
        return json.loads(raw.decode("utf-8"))


def find_dot_id(workspace: Any) -> str:
    if not isinstance(workspace, dict) or not isinstance(workspace.get("dots"), list):
        raise BootstrapError("OpenDots workspace response has no dots list")
    dots = workspace["dots"]
    for dot in dots:
        if isinstance(dot, dict) and dot.get("id") and str(dot.get("name", "")).lower() in {"dot", "qudron"}:
            return str(dot["id"])
    for dot in dots:
        if isinstance(dot, dict) and dot.get("id"):
            return str(dot["id"])
    raise BootstrapError("OpenDots has no initial Dot to attach the Qudron connection to")


def main() -> int:
    owner_token = read_secret("OPENDOTS_OWNER_TOKEN", OWNER_TOKEN_FILE)
    qudron_token = read_secret("QUDRON_API_TOKEN", QUDRON_TOKEN_FILE)
    if len(owner_token) < 24:
        raise BootstrapError("OpenDots owner token is not available in its private data volume")
    if len(qudron_token) < 32:
        raise BootstrapError("Qudron owner token is not available in its private data volume")

    last_error = "OpenDots did not become ready"
    for attempt in range(1, 31):
        try:
            workspace = request_json(f"{OPENDOTS_URL}/api/workspace", owner_token)
            dot_id = find_dot_id(workspace)
            connections = request_json(
                f"{OPENDOTS_URL}/api/dots/{dot_id}/connections", owner_token
            )
            if isinstance(connections, list):
                existing = next(
                    (item for item in connections
                     if isinstance(item, dict) and item.get("name") == CONNECTION_NAME),
                    None,
                )
            else:
                existing = None

            if existing:
                connection_id = existing.get("id")
                if not connection_id:
                    raise BootstrapError("Existing Qudron connection has no ID")
                request_json(
                    f"{OPENDOTS_URL}/api/connections/{connection_id}/refresh",
                    owner_token,
                    method="POST",
                    payload={},
                )
                print("Qudron MCP connection already exists; tool catalogue refreshed.")
                return 0

            result = request_json(
                f"{OPENDOTS_URL}/api/dots/{dot_id}/connections",
                owner_token,
                method="POST",
                payload={
                    "name": CONNECTION_NAME,
                    "url": QUDRON_MCP_URL,
                    "token": qudron_token,
                },
            )
            if not isinstance(result, dict) or not result.get("id"):
                raise BootstrapError("OpenDots did not confirm creation of the Qudron MCP connection")
            print("Qudron MCP connection created for the initial OpenDots Dot.")
            return 0
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, BootstrapError) as exc:
            last_error = type(exc).__name__
            time.sleep(min(10, 1 + attempt // 3))
    raise BootstrapError(f"OpenDots MCP bootstrap did not complete after 30 attempts ({last_error})")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BootstrapError as exc:
        print(f"OpenDots MCP bootstrap failed safely: {exc}", file=sys.stderr)
        raise SystemExit(1)
