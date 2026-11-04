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


def ensure_commander_dot(workspace: Any, owner_token: str) -> str:
    if not isinstance(workspace, dict):
        raise BootstrapError("OpenDots workspace response is invalid")
    spaces = workspace.get("spaces")
    dots = workspace.get("dots")
    if not isinstance(spaces, list) or not isinstance(dots, list):
        raise BootstrapError("OpenDots workspace response is missing spaces or dots")

    space_name = "Qudron Command Room"
    space = next(
        (item for item in spaces
         if isinstance(item, dict) and item.get("name") == space_name and item.get("id")),
        None,
    )
    if space is None:
        space = request_json(
            f"{OPENDOTS_URL}/api/spaces",
            owner_token,
            method="POST",
            payload={
                "name": space_name,
                "description": "The control room for Qudron: tasks, reports, model operations, and capability status.",
            },
        )
    space_id = str(space.get("id", "")) if isinstance(space, dict) else ""
    if not space_id:
        raise BootstrapError("OpenDots did not return a Qudron Space ID")

    dot_name = "Qudron Commander"
    dot = next(
        (item for item in dots
         if isinstance(item, dict) and item.get("name") == dot_name and item.get("id")),
        None,
    )
    if dot is None:
        dot = request_json(
            f"{OPENDOTS_URL}/api/dots",
            owner_token,
            method="POST",
            payload={
                "spaceId": space_id,
                "spaceIds": [space_id],
                "name": dot_name,
                "instructions": (
                    "You are the OpenDots control interface for Qudron, a separate autonomous execution platform. "
                    "OpenDots is the conversation and control surface; Qudron is the system that executes tasks. "
                    "Use the Qudron MCP connection as the source of truth for status, usage, queued work, and completed reports. "
                    "Submit only supported research, analysis, or draft jobs. Wait for a job to complete and retrieve its report before claiming it is done. "
                    "The Qudron submission tool changes state and must remain Ask first. Never claim publishing, payments, account changes, private customer-data processing, or shell access are available through this connection. "
                    "Prefer small, idempotent tasks and report evidence and limitations clearly."
                ),
                "researchAllowed": True,
                "memoryAllowed": True,
                "appsAllowed": False,
                "composioToolkits": [],
            },
        )
    dot_id = str(dot.get("id", "")) if isinstance(dot, dict) else ""
    if not dot_id:
        raise BootstrapError("OpenDots did not return a Qudron Commander Dot ID")
    return dot_id


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
            dot_id = ensure_commander_dot(workspace, owner_token)
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
                refreshed = request_json(
                    f"{OPENDOTS_URL}/api/connections/{connection_id}/refresh",
                    owner_token,
                    method="POST",
                    payload={},
                )
                if isinstance(refreshed, dict) and refreshed.get("error"):
                    request_json(
                        f"{OPENDOTS_URL}/api/connections/{connection_id}",
                        owner_token,
                        method="DELETE",
                    )
                else:
                    print("Qudron Commander is connected; the MCP tool catalogue was refreshed.")
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
            print("Qudron MCP connection created for the dedicated Qudron Commander Dot.")
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
