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
from urllib.parse import urlsplit
from endpoint_security import is_allowed_credential_endpoint, open_credential_request
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


def _valid_internal_service_url(url: str, service: str, port: int) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            return False
        if is_allowed_credential_endpoint(url):
            return True
        return (
            parsed.scheme == "http" and parsed.hostname == service
            and parsed.port == port
        )
    except ValueError:
        return False


def _validate_bootstrap_targets() -> None:
    if not _valid_internal_service_url(OPENDOTS_URL, "opendots", 4310):
        raise BootstrapError("OPENDOTS_INTERNAL_URL must be HTTPS, loopback, or the exact opendots:4310 Compose service")
    if not _valid_internal_service_url(QUDRON_MCP_URL, "qudron", 8765):
        raise BootstrapError("QUDRON_MCP_URL must be HTTPS, loopback, or the exact qudron:8765 Compose service")


def request_json(url: str, token: str, method: str = "GET",
                 payload: dict[str, Any] | None = None) -> Any:
    if not _valid_internal_service_url(OPENDOTS_URL, "opendots", 4310):
        raise BootstrapError("OpenDots service endpoint is not approved")
    try:
        base = urlsplit(OPENDOTS_URL)
        target = urlsplit(url)
        if (
            target.scheme != base.scheme or target.netloc != base.netloc
            or target.username is not None or target.password is not None
            or target.query or target.fragment
        ):
            raise BootstrapError("OpenDots request target differs from the validated service origin")
    except ValueError:
        raise BootstrapError("OpenDots request URL is invalid") from None
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with open_credential_request(req, timeout=15, endpoint_validated=True) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise BootstrapError("OpenDots API response exceeded the bootstrap size limit")
        return json.loads(raw.decode("utf-8"))


def ensure_qudron_space(workspace: Any, owner_token: str) -> str:
    if not isinstance(workspace, dict) or not isinstance(workspace.get("spaces"), list):
        raise BootstrapError("OpenDots workspace response is missing spaces")
    space_name = "Qudron Command Room"
    space = next(
        (item for item in workspace["spaces"]
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
                "description": "Qudron's live control room: status, tasks, agents, memory, integrations and reports.",
            },
        )
    space_id = str(space.get("id", "")) if isinstance(space, dict) else ""
    if not space_id:
        raise BootstrapError("OpenDots did not return a Qudron Space ID")
    return space_id


def ensure_commander_dot(
    workspace: Any, owner_token: str, space_id: str | None = None
) -> str:
    if not isinstance(workspace, dict):
        raise BootstrapError("OpenDots workspace response is invalid")
    dots = workspace.get("dots")
    if not isinstance(dots, list):
        raise BootstrapError("OpenDots workspace response is missing dots")
    space_id = space_id or ensure_qudron_space(workspace, owner_token)

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


def ensure_qudron_pages(space_id: str, owner_token: str) -> dict[str, int]:
    """Create an idempotent, navigable control-room page tree without overwriting edits."""
    if not space_id:
        raise BootstrapError("A Qudron Space ID is required before creating pages")
    pages_url = f"{OPENDOTS_URL}/api/spaces/{space_id}/pages"
    existing = request_json(pages_url, owner_token)
    if not isinstance(existing, list):
        raise BootstrapError("OpenDots pages endpoint returned an invalid collection")
    page_ids = {
        str(item.get("title")): str(item.get("id"))
        for item in existing
        if isinstance(item, dict) and item.get("title") and item.get("id")
    }
    specs = [
        ("dashboard", "00 — Qudron Dashboard", None,
         "# Qudron Dashboard\n\nThe command centre for QudSystem. Use the Qudron MCP tools for live queue, provider, role, continuity and report data. This page is a navigation anchor; do not treat static text as live telemetry.\n\n## Operating rule\nEvery task must have an owner, status, acceptance criteria, evidence and a next action. A task is not complete because an agent started it."),
        ("tasks", "01 — Master Task Registry", None,
         "# Master Task Registry\n\nThe authoritative task inventory lives in ops/qudron-runtime/project_task_registry.json in the Qudron repository. The runtime status and MCP status snapshot report the queue and continuity state. Keep planned, blocked, implemented-unverified and CI-verified tasks distinct."),
        ("active", "Active, Blocked & Waiting", "tasks",
         "# Active, Blocked & Waiting\n\nReview queued/running/retry/failed jobs, owner actions, provider waits and external tasks. For every blocker record the exact missing permission, credential, device, deployment or decision."),
        ("evidence", "Completed Work & Evidence", "tasks",
         "# Completed Work & Evidence\n\nA completion requires an artifact, test result, workflow run, verified provider response or device trace. Record commit SHA, job ID, artifact and verification scope."),
        ("workforce", "02 — Agent Workforce", None,
         "# Agent Workforce\n\nThe registry lists specialist roles and task teams. Roles are not live processes. Use the continuity tools to inspect actual agent stage executions and persisted role memories."),
        ("roles", "44 Specialist Roles & Teams", "workforce",
         "# 44 Specialist Roles & Teams\n\nRead ops/qudron-runtime/agent_registry.json for the current registry. It is data-driven; adding a role requires an ID, responsibilities, team membership, tests and a workload profile."),
        ("memory", "Agent Memory & Resume", "workforce",
         "# Agent Memory & Resume\n\nEach internal role has project-scoped persistent memory. Each stage has a job/agent/stage checkpoint. After a restart, completed non-sensitive stages are reused. Sensitive CV, support and payment workflows keep only non-sensitive metadata and are re-executed rather than storing intermediate content."),
        ("external", "External Agents & Manus", "workforce",
         "# External Agents & Manus\n\nExternal runs must store provider, remote task ID, local job ID, agent identity, status, last event, task URL and result reference. The Manus API v2 adapter is opt-in and requires an authorized account credential. Never store cookies or scrape private session tokens."),
        ("models", "03 — Model Supply & Routing", None,
         "# Model Supply & Routing\n\nOnly quality-qualified and terms-compliant models may receive work. Free access is not unlimited. Check current model ID, modalities, free quota, data terms, latency, reliability and last successful inference before marking a route ready."),
        ("providers", "Provider Readiness & Free Capacity", "models",
         "# Provider Readiness & Free Capacity\n\nProvider candidates are not live. Record last authorized probe, actual model response, request limits, token limits, cooldowns, uptime and measured capacity. Do not use low-capability local models as general agents or paid fallback routes without explicit approval."),
        ("router", "Routing, Failover & Quality Gates", "models",
         "# Routing, Failover & Quality Gates\n\nFail over only to another eligible, authorized source. Do not bypass quotas, rotate accounts to evade limits, or silently switch to paid inference. Preserve the task if no eligible provider is available."),
        ("android", "04 — Android Mobile Worker", None,
         "# Android Mobile Worker\n\nThe owner's Android phone is a delegated execution node. Use official Android permissions and Artemis tools for approved UI workflows. Keep owner approval for state-changing actions and preserve trace evidence."),
        ("device", "Device Connection & Delegated Tasks", "android",
         "# Device Connection & Delegated Tasks\n\nTrack ADB authorization, serial, Artemis readiness, app inventory, battery/network state and task trace IDs. Never claim full control until the relevant Android permissions and workflows have been tested on this exact device."),
        ("security", "Authorized App Security Assessment", "android",
         "# Authorized App Security Assessment\n\nTest only owner-owned apps or targets with written authorization and an explicit scope. Prefer static/dynamic analysis, permission review, storage/network checks and safe proof-of-concept reproduction. Preserve evidence and prepare responsible disclosure; do not access other users' data or persist beyond the test."),
        ("portfolio", "05 — 500+ Project Portfolio", None,
         "# Project Portfolio\n\nThe repository catalog snapshot is historical metadata, not a completed review of every project. Run read-only inventory, rank projects by evidence, customer value, uniqueness, quality, cost and legal/license readiness, then open separate QA, product and commercialization tasks."),
        ("inventory", "Repository Inventory & Project State", "portfolio",
         "# Repository Inventory & Project State\n\nUse the latest GitHub inventory snapshot and commit refs. Do not assume all private repositories were discovered or all files inspected. Track access coverage, last scan, default branch, build status and missing owner permissions."),
        ("products", "Productization & Feedback Pipeline", "portfolio",
         "# Productization & Feedback Pipeline\n\nFor each selected project create a product brief, test plan, roadmap, pricing hypothesis, demo, user-feedback mechanism, issue triage and release criteria. Do not mark projects commercialized until a customer-ready release is verified."),
        ("integrations", "06 — Integrations & Work Channels", None,
         "# Integrations & Work Channels\n\nCentral index of integrations. Every connector needs authenticated access, least privilege, idempotency, audit logging, health checks and tests. A source-code adapter is not a live connection."),
        ("manus", "Manus API v2", "integrations",
         "# Manus API v2\n\nCreate tasks asynchronously, poll task.listMessages, inspect task.detail, send follow-up messages and preserve external task IDs. Pending actions must remain approval-gated. Account entitlement and API billing/free access must be verified before activation."),
        ("models_page", "Gemini, DeepSeek, Qwen & GLM", "integrations",
         "# Gemini, DeepSeek, Qwen & GLM\n\nTrack official API or product access separately. Do not assume consumer website sessions are reusable as APIs. For a free plan, record exact model quotas, data-use terms, concurrency and whether automated orchestration is permitted."),
        ("opendots", "OpenDots, MCP & Browser Computers", "integrations",
         "# OpenDots, MCP & Browser Computers\n\nOpenDots is the owner-facing command surface; Qudron owns persistent task execution. Per-Dot browser computers are a separate optional profile and each requires permissions, storage and host resources."),
        ("artemis", "Google Artemis Android MCP", "integrations",
         "# Google Artemis Android MCP\n\nArtemis remains an independently installed Android-specialist service. Track the integration PR, bridge readiness, authorized ADB device, trace-based verification and physical-device E2E separately."),
        ("operations", "07 — Operations, Finance & Governance", None,
         "# Operations, Finance & Governance\n\nCompany-wide operations: service delivery, staffing, finance, compliance, risk, customer experience, marketing, sales, project management and leadership."),
        ("commercial", "Commercial Ledger & CVPen", "operations",
         "# Commercial Ledger & CVPen\n\nThe current ledger is an internal primitive. PSP-specific signed webhooks, secure file intake, encrypted tenant storage, document rendering, reconciliation and customer acceptance remain separate release gates."),
        ("growth", "Marketing, Publishing & Customer Channels", "operations",
         "# Marketing, Publishing & Customer Channels\n\nPrepare drafts and analytics through authorized connectors. Keep publishing, direct messaging, payments, refunds and ad spend behind human approval until the full channel permissions and audit trails pass end-to-end tests."),
        ("decisions", "08 — Decisions, Incidents & Technical Debt", None,
         "# Decisions, Incidents & Technical Debt\n\nEvery unresolved risk, failed test, design compromise and blocked integration must be tracked in the repository task registry with severity, owner, mitigation and evidence of closure.")
    ]
    created = 0
    retained = 0
    title_by_key = {spec[0]: spec[1] for spec in specs}
    for key, title, parent_key, content in specs:
        if page_ids.get(title):
            retained += 1
            continue
        parent_id = page_ids.get(title_by_key[parent_key]) if parent_key else None
        if parent_key and not parent_id:
            raise BootstrapError(f"Parent page was not created for {title}")
        result = request_json(
            pages_url, owner_token, method="POST",
            payload={"title": title, "content": content, "parentId": parent_id},
        )
        page_id = str(result.get("id", "")) if isinstance(result, dict) else ""
        if not page_id:
            raise BootstrapError(f"OpenDots did not confirm page creation: {title}")
        page_ids[title] = page_id
        created += 1
    return {"created": created, "retained": retained, "total": created + retained}


def main() -> int:
    _validate_bootstrap_targets()
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
            space_id = ensure_qudron_space(workspace, owner_token)
            dot_id = ensure_commander_dot(workspace, owner_token, space_id=space_id)
            page_summary = ensure_qudron_pages(space_id, owner_token)
            print(
                f"Qudron Command Room pages verified: {page_summary['created']} created, "
                f"{page_summary['retained']} retained, {page_summary['total']} total."
            )
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
