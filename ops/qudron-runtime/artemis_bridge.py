"""Authenticated host-side bridge from Qudron HTTP to upstream Artemis MCP.

Run on the Android host. Artemis remains independently installed and is invoked
through its official stdio MCP server; no Artemis source is copied into Qudron.
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import mimetypes
import os
from pathlib import Path
import subprocess
from typing import Any
from urllib.parse import unquote, urlparse

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
import uvicorn
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

LOG = logging.getLogger("qudron.artemis_bridge")
ALLOWED_TOOLS = {
    "mobile_run_task", "mobile_manage_task", "mobile_get_device_state",
    "mobile_inspect_trace", "mobile_diagnose",
}
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


def _bridge_config() -> dict[str, Any]:
    config_path = os.getenv("ARTEMIS_BRIDGE_CONFIG", "").strip()
    if not config_path:
        return {}
    try:
        value = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("ARTEMIS_BRIDGE_CONFIG could not be read as JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("ARTEMIS_BRIDGE_CONFIG must contain a JSON object")
    return value


def _artemis_project_root() -> Path:
    """Resolve cwd consistently from environment overrides or the JSON config."""
    mcp_config = _bridge_config().get("mcp", {})
    if not isinstance(mcp_config, dict):
        raise RuntimeError("The mcp section in Artemis bridge config must be an object")
    cwd = os.getenv("ARTEMIS_MCP_CWD", "").strip() or str(mcp_config.get("cwd", "")).strip()
    if not cwd:
        raise RuntimeError("Set ARTEMIS_MCP_CWD or mcp.cwd in ARTEMIS_BRIDGE_CONFIG")
    root = Path(cwd).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError("The configured Artemis working directory must exist")
    return root


def _server_parameters() -> StdioServerParameters:
    config = _bridge_config()
    mcp_config = config.get("mcp", {})
    if not isinstance(mcp_config, dict):
        raise RuntimeError("The mcp section in Artemis bridge config must be an object")
    command = os.getenv("ARTEMIS_MCP_COMMAND", "").strip() or str(mcp_config.get("command", "")).strip()
    if not command:
        raise RuntimeError("Set ARTEMIS_MCP_COMMAND or mcp.command in ARTEMIS_BRIDGE_CONFIG")
    raw_args = os.getenv("ARTEMIS_MCP_ARGS_JSON", "").strip()
    if raw_args:
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            raise RuntimeError("ARTEMIS_MCP_ARGS_JSON must be a JSON array") from exc
    else:
        args = mcp_config.get("args", ["-m", "mcp_server"])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise RuntimeError("Artemis MCP args must be an array of strings")
    project_root = _artemis_project_root()
    expected_commit = os.getenv("ARTEMIS_EXPECTED_COMMIT", "").strip() or str(mcp_config.get("expected_commit", "")).strip()
    if expected_commit:
        try:
            actual = subprocess.run(
                ["git", "-C", str(project_root), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("Could not verify the pinned Artemis checkout") from exc
        if actual != expected_commit:
            raise RuntimeError("Artemis checkout does not match ARTEMIS_EXPECTED_COMMIT")
    env = os.environ.copy()
    # The MCP child needs Artemis provider settings, not Qudron bridge credentials.
    env.pop("ARTEMIS_BRIDGE_TOKEN", None)
    for key in tuple(env):
        if key.startswith("QUDRON_"):
            env.pop(key, None)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    return StdioServerParameters(command=command, args=args, cwd=str(project_root), env=env)


def _safe_artifact(path_text: str) -> dict[str, Any] | None:
    """Return only bounded image artifacts located inside the configured Artemis tree."""
    parsed = urlparse(path_text)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        return None
    try:
        project_root = _artemis_project_root()
        candidate = Path(unquote(parsed.path)).resolve()
    except (RuntimeError, OSError, ValueError):
        return None
    traces_root = (project_root / "traces").resolve()
    in_traces = candidate.is_relative_to(traces_root)
    live_capture = (
        candidate.is_relative_to(project_root)
        and candidate.name.startswith("live_screenshot_")
        and candidate.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not (in_traces or live_capture) or not candidate.is_file():
        return None
    try:
        size = candidate.stat().st_size
        if size < 1 or size > MAX_ARTIFACT_BYTES:
            return None
        mime = mimetypes.guess_type(candidate.name)[0] or "image/jpeg"
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            return None
        return {"type": "image", "mimeType": mime,
                "data": base64.b64encode(candidate.read_bytes()).decode("ascii")}
    except OSError:
        return None


def _serialize_result(result: Any) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for item in getattr(result, "content", []) or []:
        if hasattr(item, "model_dump"):
            block = item.model_dump(mode="json", by_alias=True)
        elif hasattr(item, "dict"):
            block = item.dict(by_alias=True)
        else:
            block = {"type": "text", "text": str(item)}
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = str(block.get("text", ""))
            artifact = _safe_artifact(text)
            content.append(artifact or {"type": "text", "text": text[:20000]})
        elif block.get("type") == "image":
            mime = block.get("mimeType", "image/png")
            data = str(block.get("data", ""))
            if mime in {"image/jpeg", "image/png", "image/webp"} and len(data) <= 7_000_000:
                content.append({"type": "image", "mimeType": mime, "data": data})
        else:
            content.append({"type": "text", "text": json.dumps(block, ensure_ascii=False)[:20000]})
    payload: dict[str, Any] = {
        "content": content or [{"type": "text", "text": "Artemis returned no content."}],
        "isError": bool(getattr(result, "isError", False)),
    }
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        try:
            payload["structuredContent"] = structured.model_dump(mode="json") if hasattr(structured, "model_dump") else structured
        except Exception:
            payload["structuredContent"] = str(structured)[:20000]
    return payload


def _validate_tool_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "mobile_run_task": {"task_desc", "model", "device_serial", "expected_output_desc", "verification_level", "explorer_mode"},
        "mobile_manage_task": {"action", "trace_id", "instruction", "release_loop"},
        "mobile_get_device_state": {"view_type", "device_serial"},
        "mobile_inspect_trace": {"action", "trace_id", "step_number", "query", "step_range", "max_results"},
        "mobile_diagnose": {"device_serial"},
    }
    if name not in allowed or set(arguments) - allowed[name]:
        raise HTTPException(status_code=400, detail="Invalid Artemis tool arguments")
    args = dict(arguments)
    if name == "mobile_run_task":
        if not isinstance(args.get("task_desc"), str) or not args["task_desc"].strip() or len(args["task_desc"]) > 4000:
            raise HTTPException(status_code=400, detail="task_desc is required and limited to 4000 characters")
        if args.get("model", "Flash") not in {"Flash", "Pro"}:
            raise HTTPException(status_code=400, detail="model must be Flash or Pro")
        if args.get("verification_level") not in {None, "off", "final", "checkpoints", "strict"}:
            raise HTTPException(status_code=400, detail="Invalid verification_level")
        if args.get("explorer_mode") not in {None, "flash", "pro", "ultra"}:
            raise HTTPException(status_code=400, detail="Invalid explorer_mode")
    elif name == "mobile_manage_task":
        if args.get("action") not in {"status", "stop", "inject_instruction"}:
            raise HTTPException(status_code=400, detail="Unsupported task control action")
        if not isinstance(args.get("trace_id"), str) or not args["trace_id"].strip():
            raise HTTPException(status_code=400, detail="trace_id is required")
        if args["action"] == "inject_instruction" and not args.get("instruction") and not args.get("release_loop", False):
            raise HTTPException(status_code=400, detail="instruction is required")
    elif name == "mobile_get_device_state":
        if args.get("view_type") not in {"screenshot", "hierarchy"}:
            raise HTTPException(status_code=400, detail="view_type must be screenshot or hierarchy")
    elif name == "mobile_inspect_trace":
        if args.get("action") not in {"view_summary", "search", "view_step_screenshots", "view_step_details"}:
            raise HTTPException(status_code=400, detail="Unsupported trace inspection action")
        if not isinstance(args.get("trace_id"), str) or not args["trace_id"].strip():
            raise HTTPException(status_code=400, detail="trace_id is required")
    elif name == "mobile_diagnose":
        args = {"attempt_fix": False, "verify_credentials": False, "probe_device": False}
        if arguments.get("device_serial"):
            args["device_serial"] = arguments["device_serial"]
    return args


async def call_artemis_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in ALLOWED_TOOLS:
        raise HTTPException(status_code=400, detail="Artemis tool is not allowlisted")
    arguments = _validate_tool_arguments(name, arguments)
    params = _server_parameters()
    timeout = max(5, min(900, int(os.getenv("ARTEMIS_MCP_CALL_TIMEOUT_SECONDS", "120"))))
    try:
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), timeout=timeout)
                result = await asyncio.wait_for(session.call_tool(name, arguments=arguments), timeout=timeout)
                return _serialize_result(result)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Artemis MCP call timed out") from exc
    except HTTPException:
        raise
    except Exception as exc:
        LOG.exception("Artemis MCP call failed")
        raise HTTPException(status_code=502, detail="Artemis MCP call failed; inspect host-side bridge logs") from exc


app = FastAPI(title="Qudron Artemis MCP Bridge", version="0.1.1")


def _authorize(authorization: str | None) -> None:
    expected = os.getenv("ARTEMIS_BRIDGE_TOKEN", "")
    supplied = authorization or ""
    if not expected:
        raise HTTPException(status_code=503, detail="Bridge token is not configured")
    if not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:], expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
async def health() -> dict[str, str]:
    # Liveness only; Artemis/device readiness is checked via mobile_diagnose.
    return {"service": "qudron-artemis-mcp-bridge", "status": "alive"}


@app.post("/tools/call")
async def tools_call(payload: ToolCall, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _authorize(authorization)
    return await call_artemis_tool(payload.name, payload.arguments)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("ARTEMIS_BRIDGE_LOG_LEVEL", "INFO"))
    config = _bridge_config()
    uvicorn.run(
        app,
        host=os.getenv("ARTEMIS_BRIDGE_BIND_HOST", str(config.get("bind_host", "0.0.0.0"))),
        port=int(os.getenv("ARTEMIS_BRIDGE_PORT", str(config.get("port", 8766)))),
        log_level=os.getenv("ARTEMIS_BRIDGE_LOG_LEVEL", "info").lower(),
    )
