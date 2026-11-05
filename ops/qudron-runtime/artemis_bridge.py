"""Authenticated host-side bridge from Qudron HTTP to the upstream Artemis MCP server.

Run this process on the computer that owns the Android device and the Artemis
installation. It starts the official Artemis MCP server over stdio per request;
Artemis remains an independent upstream process and is never vendored here.
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

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
import uvicorn
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

LOG = logging.getLogger("qudron.artemis_bridge")
ALLOWED_TOOLS = {
    "mobile_run_task",
    "mobile_manage_task",
    "mobile_get_device_state",
    "mobile_inspect_trace",
    "mobile_diagnose",
}
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is not configured: {name}")
    return value


def _server_parameters() -> StdioServerParameters:
    command = _required_env("ARTEMIS_MCP_COMMAND")
    raw_args = os.getenv("ARTEMIS_MCP_ARGS_JSON", '["-m","mcp_server"]')
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ARTEMIS_MCP_ARGS_JSON must be a JSON array") from exc
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise RuntimeError("ARTEMIS_MCP_ARGS_JSON must contain only strings")
    cwd = _required_env("ARTEMIS_MCP_CWD")
    project_root = Path(cwd).resolve()
    if not project_root.is_dir():
        raise RuntimeError("ARTEMIS_MCP_CWD must point to an existing Artemis checkout")
    expected_commit = os.getenv("ARTEMIS_EXPECTED_COMMIT", "").strip()
    if expected_commit:
        try:
            actual_commit = subprocess.run(
                ["git", "-C", str(project_root), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("Could not verify the pinned Artemis checkout") from exc
        if actual_commit != expected_commit:
            raise RuntimeError("Artemis checkout does not match ARTEMIS_EXPECTED_COMMIT")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    return StdioServerParameters(command=command, args=args, cwd=str(project_root), env=env)


def _safe_artifact(path_text: str) -> dict[str, Any] | None:
    """Convert only known Artemis screenshot artifacts into bounded MCP image blocks."""
    if not path_text.startswith("file://"):
        return None
    from urllib.parse import unquote, urlparse

    parsed = urlparse(path_text)
    candidate = Path(unquote(parsed.path)).resolve()
    project_root = Path(_required_env("ARTEMIS_MCP_CWD")).resolve()
    traces_root = (project_root / "traces").resolve()
    in_project = candidate.is_relative_to(project_root)
    in_traces = candidate.is_relative_to(traces_root)
    known_live_capture = candidate.name.startswith("live_screenshot_") and candidate.suffix.lower() in {".jpg", ".jpeg", ".png"}
    if not (in_traces or (in_project and known_live_capture)) or not candidate.is_file():
        return None
    size = candidate.stat().st_size
    if size < 1 or size > MAX_ARTIFACT_BYTES:
        return None
    mime_type = mimetypes.guess_type(candidate.name)[0] or "image/jpeg"
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        return None
    return {
        "type": "image",
        "mimeType": mime_type,
        "data": base64.b64encode(candidate.read_bytes()).decode("ascii"),
    }


def _serialize_result(result: Any) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for item in getattr(result, "content", []) or []:
        if hasattr(item, "model_dump"):
            block = item.model_dump(mode="json", by_alias=True)
        elif hasattr(item, "dict"):
            block = item.dict(by_alias=True)
        else:
            block = {"type": "text", "text": str(item)}
        if block.get("type") == "text":
            artifact = _safe_artifact(str(block.get("text", "")))
            content.append(artifact or {"type": "text", "text": str(block.get("text", ""))[:20000]})
        elif block.get("type") == "image":
            content.append({
                "type": "image",
                "mimeType": block.get("mimeType", "image/png"),
                "data": str(block.get("data", ""))[:MAX_ARTIFACT_BYTES * 2],
            })
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
    """Enforce the same least-privilege contract even when the bridge is called directly."""
    allowed_fields = {
        "mobile_run_task": {
            "task_desc", "model", "device_serial", "expected_output_desc",
            "verification_level", "explorer_mode",
        },
        "mobile_manage_task": {"action", "trace_id", "instruction", "release_loop"},
        "mobile_get_device_state": {"view_type", "device_serial"},
        "mobile_inspect_trace": {
            "action", "trace_id", "step_number", "query", "step_range", "max_results",
        },
        "mobile_diagnose": {"device_serial"},
    }
    if name not in allowed_fields or set(arguments) - allowed_fields[name]:
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
                result = await asyncio.wait_for(
                    session.call_tool(name, arguments=arguments),
                    timeout=timeout,
                )
                return _serialize_result(result)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Artemis MCP call timed out") from exc
    except HTTPException:
        raise
    except Exception as exc:
        LOG.exception("Artemis MCP call failed")
        raise HTTPException(status_code=502, detail="Artemis MCP call failed; inspect host-side bridge logs") from exc


app = FastAPI(title="Qudron Artemis MCP Bridge", version="0.1.0")


def _authorize(authorization: str | None) -> None:
    expected = os.getenv("ARTEMIS_BRIDGE_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Bridge token is not configured")
    supplied = authorization or ""
    if not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:], expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"service": "qudron-artemis-mcp-bridge", "status": "ready"}


@app.post("/tools/call")
async def tools_call(payload: ToolCall, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _authorize(authorization)
    return await call_artemis_tool(payload.name, payload.arguments)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("ARTEMIS_BRIDGE_LOG_LEVEL", "INFO"))
    uvicorn.run(
        app,
        host=os.getenv("ARTEMIS_BRIDGE_BIND_HOST", "0.0.0.0"),
        port=int(os.getenv("ARTEMIS_BRIDGE_PORT", "8766")),
        log_level=os.getenv("ARTEMIS_BRIDGE_LOG_LEVEL", "info").lower(),
    )
