#!/usr/bin/env python3
"""Qudron dual-agent coordination board (Qoder <-> GitHub Copilot).

Why this exists
---------------
Two coding agents work in *different* git worktrees of the same repository, so
they cannot see each other's uncommitted files. This module provides one shared
directory, reachable by absolute path from any worktree, that holds:

* an append-only, SHA-256 hash-chained event log (``events.jsonl``) that is the
  single source of truth,
* agent identity / branch / worktree / base-SHA registration,
* plan proposals with task splits and explicit peer acknowledgement (ACK),
* inbox-style messages between agents,
* file and symbol reservations with deterministic conflict detection,
* a pre-edit gate that refuses work until the peer has ACKed and the path is
  reserved,
* progress states and hand-off records,
* a rendered ``board/BOARD.md`` snapshot for humans and LLM agents.

Concurrency model
-----------------
Every mutation runs inside :class:`Transaction`, which takes a cross-process
advisory lock (``msvcrt.locking`` on Windows, ``fcntl.flock`` elsewhere), reads
the log tail, computes the next ``seq`` and ``prev_hash``, and appends exactly
one line with a single ``os.write`` on a file opened ``O_APPEND`` followed by
``fsync``. A torn or interleaved write therefore shows up as a broken hash
chain, which ``verify`` detects.

Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

SCHEMA_VERSION = 1
GENESIS_HASH = "sha256:" + ("0" * 64)
EVENTS_FILE = "events.jsonl"
BOARD_FILE = os.path.join("board", "BOARD.md")
HEAD_FILE = os.path.join("board", "HEAD.json")
LOCK_FILE = os.path.join("locks", "board.lock")
INFRA_DIR = ".agent-coordination"
DEFAULT_TTL_MINUTES = 120
# The bootstrap exemption is deliberately time bounded: it only covers a plan the
# caller proposed itself inside this window, so it can never become a standing
# licence to edit without a peer.
BOOTSTRAP_MAX_AGE_MINUTES = 240

AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,39}$")
# Windows-only spellings that would alias another path if they were normalised
# instead of rejected: a drive with no separator, and any colon (ADS).
DRIVE_RELATIVE_RE = re.compile(r"^[A-Za-z]:(?![\\/])")
ILLEGAL_PATH_CHAR_RE = re.compile(r'[<>:"|?*\x00-\x1f]')
VALID_STATES = (
    "idle",
    "planning",
    "waiting_ack",
    "in_progress",
    "blocked",
    "paused",
    "done",
    "handed_off",
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BLOCKED = 3
EXIT_CORRUPT = 4


class CoordinationError(Exception):
    """A deterministic, user facing failure with a stable machine code."""

    def __init__(self, code, message, exit_code=EXIT_USAGE, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = details or {}

    def as_dict(self):
        out = {"error": self.code, "message": self.message}
        if self.details:
            out["details"] = self.details
        return out


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------
def utc_now():
    return datetime.now(timezone.utc)


def to_iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def utc_now_iso():
    return to_iso(utc_now())


def parse_iso(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# normalisation and conflict rules
# ---------------------------------------------------------------------------
def _check_path_component(component, original):
    """Reject path components whose spelling Windows would silently rewrite."""
    if component != component.rstrip(" ."):
        raise CoordinationError(
            "PATH_INVALID_COMPONENT",
            "%r has the component %r, which ends with a dot or a space; Windows "
            "strips it, so the path would alias a different file"
            % (original, component),
        )
    if ":" in component:
        raise CoordinationError(
            "PATH_ADS_FORBIDDEN",
            "%r contains ':' in the component %r; alternate data streams and other "
            "colon forms are not supported" % (original, component),
        )
    if ILLEGAL_PATH_CHAR_RE.search(component):
        raise CoordinationError(
            "PATH_INVALID_COMPONENT",
            "%r contains a character that is not portable in the component %r"
            % (original, component),
        )


def norm_path(value, repo_root=None):
    """Canonicalise a repository path so both worktrees agree on identity.

    Empty and ``.`` segments are dropped, ``..`` segments are resolved, and any
    path that escapes the repository root is rejected, so aliases such as
    ``src/../file.py`` and ``file.py`` cannot slip past an overlapping
    reservation.

    Windows-only spellings are rejected rather than normalised. A component that
    ends with a dot or a space, a drive-relative path such as ``C:src/file.py``
    and every colon form (alternate data stream) have no portable meaning, so
    accepting them would let one spelling hide behind another one.
    """
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise CoordinationError("INVALID_PATH", "empty path")
    if DRIVE_RELATIVE_RE.match(raw):
        raise CoordinationError(
            "PATH_DRIVE_RELATIVE",
            "%r is drive-relative; use a path relative to the repository root, or an "
            "absolute path together with --repo-root" % (value,),
        )
    absolute = raw.startswith("/") or bool(re.match(r"^[A-Za-z]:/", raw))
    if absolute:
        if not repo_root:
            raise CoordinationError(
                "PATH_REQUIRES_REPO_ROOT",
                "absolute path %r needs --repo-root so both worktrees resolve it" % (value,),
            )
        root = os.path.abspath(repo_root).replace("\\", "/").rstrip("/")
        if raw.lower() == root.lower():
            raw = "."
        elif raw.lower().startswith(root.lower() + "/"):
            raw = raw[len(root) + 1:]
        else:
            raise CoordinationError(
                "PATH_OUTSIDE_REPO", "%r is outside the repository root %s" % (value, root)
            )
    parts = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise CoordinationError(
                    "PATH_ESCAPES_ROOT", "%r escapes the repository root" % (value,)
                )
            parts.pop()
            continue
        _check_path_component(part, value)
        parts.append(part)
    if not parts:
        return "."
    return "/".join(parts).lower()


def safe_norm_path(value, repo_root=None):
    """Tolerant variant used when reading paths written by an older board."""
    try:
        return norm_path(value, repo_root)
    except CoordinationError:
        return str(value or "").strip().replace("\\", "/").lower()



def paths_conflict(first, second):
    """Symmetric overlap: two leases, or a lease and an edit, cannot coexist.

    Used for *conflict detection* only. Permission is directional and is answered
    by :func:`path_covers`, never by this predicate.
    """
    if first == second:
        return True
    if first == "." or second == ".":
        return True
    return first.startswith(second + "/") or second.startswith(first + "/")


def path_covers(holder, requested):
    """Directional containment: does ``holder`` authorise ``requested``?

    A scope or lease on ``src`` authorises ``src/app.py``; a lease on
    ``src/app.py`` never authorises ``src``. Permission therefore propagates down
    the tree only, so a narrow reservation cannot be read as a licence for its
    parent directory.
    """
    if holder == "." or holder == requested:
        return True
    return requested.startswith(holder + "/")


def norm_symbol(value):
    return str(value or "").strip().lower()


def symbols_conflict(first, second):
    """Symmetric overlap for symbols; see :func:`paths_conflict`."""
    if first == second:
        return True
    return first.startswith(second + ".") or second.startswith(first + ".")


def symbol_covers(holder, requested):
    """Directional containment: ``Order`` authorises ``Order.total``, not vice versa."""
    if holder == requested:
        return True
    return requested.startswith(holder + ".")


def split_values(values):
    out = []
    for value in values or []:
        for chunk in str(value).replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk:
                out.append(chunk)
    return out


# ---------------------------------------------------------------------------
# cross-process lock
# ---------------------------------------------------------------------------
class BoardLock:
    """Advisory exclusive lock that works on Windows and POSIX."""

    def __init__(self, path, timeout=20.0, poll=0.01):
        self.path = path
        self.timeout = timeout
        self.poll = poll
        self._fd = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        fd = os.open(self.path, flags, 0o666)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._acquire(fd)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    self._safe_close(fd)
                    raise CoordinationError(
                        "LOCK_TIMEOUT",
                        "another agent kept the board lock for more than "
                        "%.1fs; retry the command" % self.timeout,
                        exit_code=EXIT_BLOCKED,
                    )
                time.sleep(self.poll)
        self._fd = fd
        return self

    def __exit__(self, exc_type, exc, tb):
        fd, self._fd = self._fd, None
        if fd is None:
            return False
        try:
            self._release(fd)
        except OSError:
            pass
        finally:
            self._safe_close(fd)
        return False

    @staticmethod
    def _safe_close(fd):
        try:
            os.close(fd)
        except OSError:
            pass

    @staticmethod
    def _acquire(fd):
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _release(fd):
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# git discovery
# ---------------------------------------------------------------------------
def _git(cwd, args, timeout=20):
    try:
        proc = subprocess.run(
            ["git", "-C", cwd] + list(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def git_info(cwd=None):
    cwd = cwd or os.getcwd()
    info = {
        "branch": _git(cwd, ["rev-parse", "--abbrev-ref", "HEAD"]),
        "base_sha": _git(cwd, ["rev-parse", "HEAD"]),
        "worktree": _git(cwd, ["rev-parse", "--show-toplevel"]),
        "git_common_dir": _git(cwd, ["rev-parse", "--git-common-dir"]),
    }
    info["worktree"] = (
        os.path.abspath(info["worktree"]).replace("\\", "/") if info["worktree"] else ""
    )
    return info


# ---------------------------------------------------------------------------
# event log + state replay
# ---------------------------------------------------------------------------
def _bump_counter(state, kind, identifier):
    match = re.search(r"(\d+)$", str(identifier or ""))
    if match:
        state["counters"][kind] = max(state["counters"][kind], int(match.group(1)))


def next_id(state, kind):
    return "%s-%04d" % (kind[0].upper(), state["counters"][kind] + 1)


def _ensure_agent(state, agent_id, event_type):
    agent = state["agents"].get(agent_id)
    if agent is None:
        raise CoordinationError(
            "AGENT_NOT_REGISTERED",
            "agent %r is not registered; run `register --agent %s` first"
            % (agent_id, agent_id),
        )
    return agent


def _plan_peers(state, plan):
    return {aid for aid in state["agents"] if aid != plan.get("proposed_by")}


def plan_missing_acks(state, plan):
    return sorted(_plan_peers(state, plan) - set(plan.get("acks", {})))


def plan_status(state, plan):
    if plan.get("rejections"):
        return "rejected"
    peers = _plan_peers(state, plan)
    if not peers:
        return "proposed"
    return "proposed" if plan_missing_acks(state, plan) else "acked"


def _find_task(state, task_id, agent=None, plan_id=None):
    """Locate a task while replaying the log.

    ``plan_id`` pins the plan. When a legacy record carries no plan_id the lookup
    stays tolerant (first match in insertion order) so replaying an older log
    keeps producing the same board: ambiguity is refused on the *command* line,
    never by rewriting history.
    """
    if plan_id:
        plans = [state["plans"][plan_id]] if plan_id in state["plans"] else []
    else:
        plans = list(state["plans"].values())
    for plan in plans:
        for task in plan.get("tasks", []):
            if task.get("id") != task_id:
                continue
            if agent and task.get("owner") not in (agent, "both", "any"):
                continue
            return plan["plan_id"], plan, task
    return None, None, None


def apply_event(state, event):
    kind = event.get("type")
    payload = event.get("payload") or {}
    agent_id = event.get("agent") or ""
    ts = event.get("ts")

    if kind == "board.initialized":
        state["initialized"] = True
        state["schema_version"] = payload.get("schema_version", SCHEMA_VERSION)

    elif kind == "agent.registered":
        aid = payload.get("agent_id") or agent_id
        existing = state["agents"].get(aid)
        record = dict(payload)
        record["agent_id"] = aid
        if existing:
            record["registered_at"] = existing.get("registered_at", ts)
            record["registered_seq"] = existing.get("registered_seq", event.get("seq"))
            record["revision"] = int(existing.get("revision", 1)) + 1
        else:
            record["registered_at"] = ts
            record["registered_seq"] = event.get("seq")
            record["revision"] = 1
        record["last_seen"] = ts
        for key, value in payload.items():
            if value in (None, "") and key in (existing or {}):
                record[key] = existing[key]
        state["agents"][aid] = record

    elif kind == "agent.heartbeat":
        aid = payload.get("agent_id") or agent_id
        agent = state["agents"].get(aid)
        if agent:
            agent["last_seen"] = ts
            for key in ("branch", "base_sha", "worktree", "note"):
                if payload.get(key):
                    agent[key] = payload[key]

    elif kind == "plan.proposed":
        pid = payload.get("plan_id")
        state["plans"][pid] = {
            "plan_id": pid,
            "title": payload.get("title", ""),
            "summary": payload.get("summary", ""),
            "scope": payload.get("scope", []),
            "scope_symbols": payload.get("scope_symbols", []),
            "tasks": payload.get("tasks", []),
            "base_sha": payload.get("base_sha", ""),
            "proposed_by": agent_id,
            "proposed_at": ts,
            "proposed_seq": event.get("seq"),
            "acks": {},
            "rejections": {},
        }
        _bump_counter(state, "plan", pid)

    elif kind == "plan.acknowledged":
        plan = state["plans"].get(payload.get("plan_id"))
        if plan:
            plan["acks"][agent_id] = {"at": ts, "note": payload.get("note", "")}

    elif kind == "plan.rejected":
        plan = state["plans"].get(payload.get("plan_id"))
        if plan:
            plan["rejections"][agent_id] = {
                "at": ts,
                "reason": payload.get("reason", ""),
            }

    elif kind == "message.sent":
        mid = payload.get("message_id")
        state["messages"][mid] = {
            "message_id": mid,
            "from": payload.get("from") or agent_id,
            "to": payload.get("to", ""),
            "subject": payload.get("subject", ""),
            "body": payload.get("body", ""),
            "plan_id": payload.get("plan_id", ""),
            "requires_ack": bool(payload.get("requires_ack", True)),
            "sent_at": ts,
            "sent_seq": event.get("seq"),
            "acked_by": {},
        }
        _bump_counter(state, "message", mid)

    elif kind == "message.acknowledged":
        message = state["messages"].get(payload.get("message_id"))
        if message:
            message["acked_by"][agent_id] = {"at": ts, "note": payload.get("note", "")}

    elif kind == "reservation.granted":
        rid = payload.get("reservation_id")
        state["reservations"][rid] = {
            "reservation_id": rid,
            "agent": payload.get("agent") or agent_id,
            "plan_id": payload.get("plan_id", ""),
            "paths": payload.get("paths", []),
            "symbols": payload.get("symbols", []),
            "note": payload.get("note", ""),
            "ttl_minutes": payload.get("ttl_minutes"),
            "granted_at": ts,
            "expires_at": payload.get("expires_at", ""),
            "status": "active",
            "released_at": None,
            "renewals": 0,
        }
        _bump_counter(state, "reservation", rid)

    elif kind == "reservation.denied":
        rid = payload.get("reservation_id")
        state["denials"].append(
            {
                "reservation_id": rid,
                "agent": payload.get("agent") or agent_id,
                "paths": payload.get("paths", []),
                "symbols": payload.get("symbols", []),
                "conflicts": payload.get("conflicts", []),
                "at": ts,
            }
        )
        _bump_counter(state, "reservation", rid)

    elif kind == "reservation.released":
        reservation = state["reservations"].get(payload.get("reservation_id"))
        if reservation:
            reservation["status"] = "released"
            reservation["released_at"] = ts
            reservation["release_reason"] = payload.get("reason", "")

    elif kind == "reservation.renewed":
        reservation = state["reservations"].get(payload.get("reservation_id"))
        if reservation:
            reservation["expires_at"] = payload.get("expires_at", "")
            reservation["renewals"] = int(reservation.get("renewals", 0)) + 1
            reservation["status"] = "active"

    elif kind == "status.updated":
        state["agent_status"][agent_id] = {
            "state": payload.get("state", ""),
            "task_id": payload.get("task_id", ""),
            "note": payload.get("note", ""),
            "at": ts,
        }
        if payload.get("task_id") and payload.get("state"):
            _, _, task = _find_task(
                state, payload["task_id"], agent_id, payload.get("plan_id")
            )
            if task is not None:
                task["status"] = payload["state"]

    elif kind == "handoff.submitted":
        hid = payload.get("handoff_id")
        state["handoffs"][hid] = dict(
            payload,
            handoff_id=hid,
            agent=payload.get("agent") or agent_id,
            submitted_at=ts,
            submitted_seq=event.get("seq"),
            acked_by={},
        )
        _bump_counter(state, "handoff", hid)
        if payload.get("task_id"):
            _, _, task = _find_task(
                state, payload["task_id"], agent_id, payload.get("plan_id")
            )
            if task is not None:
                task["status"] = "handed_off"

    elif kind == "handoff.acknowledged":
        handoff = state["handoffs"].get(payload.get("handoff_id"))
        if handoff:
            handoff["acked_by"][agent_id] = {"at": ts, "note": payload.get("note", "")}


def empty_state():
    return {
        "schema_version": SCHEMA_VERSION,
        "initialized": False,
        "agents": {},
        "plans": {},
        "messages": {},
        "reservations": {},
        "denials": [],
        "handoffs": {},
        "agent_status": {},
        "counters": {"plan": 0, "message": 0, "reservation": 0, "handoff": 0},
        "last_seq": 0,
        "last_hash": GENESIS_HASH,
    }


def replay(events):
    state = empty_state()
    for event in events:
        apply_event(state, event)
        state["last_seq"] = event.get("seq", state["last_seq"])
        state["last_hash"] = event.get("hash", state["last_hash"])
    return state


def active_reservations(state, now=None):
    now = now or utc_now()
    out = []
    for reservation in state["reservations"].values():
        if reservation.get("status") != "active":
            continue
        expiry = parse_iso(reservation.get("expires_at"))
        if expiry is not None and expiry <= now:
            continue
        out.append(reservation)
    return out


def find_path_conflicts(state, agent_id, paths, symbols):
    conflicts = []
    others = [r for r in active_reservations(state) if r.get("agent") != agent_id]
    for path in paths:
        for reservation in others:
            for held in reservation.get("paths", []):
                if paths_conflict(path, held):
                    conflicts.append(
                        {
                            "kind": "path",
                            "requested": path,
                            "held": held,
                            "reservation_id": reservation["reservation_id"],
                            "agent": reservation["agent"],
                            "expires_at": reservation.get("expires_at", ""),
                        }
                    )
    for symbol in symbols:
        for reservation in others:
            for held in reservation.get("symbols", []):
                if symbols_conflict(symbol, held):
                    conflicts.append(
                        {
                            "kind": "symbol",
                            "requested": symbol,
                            "held": held,
                            "reservation_id": reservation["reservation_id"],
                            "agent": reservation["agent"],
                            "expires_at": reservation.get("expires_at", ""),
                        }
                    )
    unique = {canonical(item): item for item in conflicts}
    return sorted(unique.values(), key=lambda item: (item["kind"], item["requested"]))


def own_covering_reservations(state, agent_id, value, kind, now=None):
    """Live reservations of this agent that *authorise* the value (directional)."""
    covers = path_covers if kind == "path" else symbol_covers
    key = "paths" if kind == "path" else "symbols"
    out = []
    for reservation in active_reservations(state, now):
        if reservation.get("agent") != agent_id:
            continue
        if any(covers(held, value) for held in reservation.get(key, [])):
            out.append(reservation)
    return sorted(out, key=lambda item: item["reservation_id"])


def peer_overlapping_reservations(state, agent_id, value, kind, now=None):
    """Live peer reservations that *overlap* the value (symmetric).

    A peer lease on ``src/app.py`` overlaps a request for ``src``, so this check is
    deliberately symmetric: it answers "who else could be editing this area",
    which is a different question from "am I allowed to edit it".
    """
    overlaps = paths_conflict if kind == "path" else symbols_conflict
    key = "paths" if kind == "path" else "symbols"
    out = []
    for reservation in active_reservations(state, now):
        if reservation.get("agent") == agent_id:
            continue
        if any(overlaps(value, held) for held in reservation.get(key, [])):
            out.append(reservation)
    return sorted(out, key=lambda item: item["reservation_id"])


def expired_own_matches(state, agent_id, value, kind):
    """Own reservations that would have authorised the value but lapsed."""
    covers = path_covers if kind == "path" else symbol_covers
    key = "paths" if kind == "path" else "symbols"
    now = utc_now()
    out = []
    for reservation in state["reservations"].values():
        if reservation.get("agent") != agent_id or reservation.get("status") != "active":
            continue
        if not any(covers(held, value) for held in reservation.get(key, [])):
            continue
        expiry = parse_iso(reservation.get("expires_at"))
        if expiry is not None and expiry > now:
            continue
        out.append(reservation)
    return sorted(out, key=lambda item: item["reservation_id"])


def plan_path_coverage(plan, agent_id):
    """Paths a plan authorises for this agent: plan scope plus owned task files."""
    declared = [safe_norm_path(item) for item in plan.get("scope", [])]
    for task in plan.get("tasks", []):
        if task.get("owner") in (agent_id, "both", "any"):
            declared.extend(safe_norm_path(item) for item in task.get("files", []))
    return [item for item in declared if item]


def plan_symbol_coverage(plan):
    declared = [norm_symbol(item) for item in plan.get("scope_symbols", [])]
    return [item for item in declared if item]


def valid_plan_acks(state, plan):
    """ACK records that actually count: a registered agent other than the proposer.

    An ACK whose author is unknown to the identity table (a forged or hand written
    record in an old log) is ignored rather than trusted.
    """
    acks = {}
    for agent_id, record in (plan.get("acks") or {}).items():
        if agent_id == plan.get("proposed_by"):
            continue
        if agent_id not in state["agents"]:
            continue
        acks[agent_id] = record
    return acks


def tasks_named(state, task_id, plan_id=None):
    """Every (plan_id, task) pair carrying this task id, optionally in one plan."""
    if plan_id:
        plans = [state["plans"][plan_id]] if plan_id in state["plans"] else []
    else:
        plans = list(state["plans"].values())
    out = []
    for plan in plans:
        for task in plan.get("tasks", []):
            if task.get("id") == task_id:
                out.append((plan["plan_id"], task))
    return out


def resolve_task_reference(state, task_id, plan_id=None, agent_id=None):
    """Address one task as plan_id + task_id; refuse ambiguous references.

    Task ids are only unique inside a plan (``T1`` routinely exists in several
    plans), so an unqualified id is accepted only while it is unambiguous.
    """
    if not task_id:
        return None, None
    if plan_id and plan_id not in state["plans"]:
        raise CoordinationError("PLAN_NOT_FOUND", "unknown plan %r" % (plan_id,))
    matches = tasks_named(state, task_id, plan_id)
    if not matches:
        raise CoordinationError(
            "TASK_NOT_FOUND",
            "no task %r in %s" % (task_id, plan_id or "any plan"),
            details={"task_id": task_id, "plan_id": plan_id or ""},
        )
    if len(matches) > 1:
        raise CoordinationError(
            "TASK_REFERENCE_AMBIGUOUS",
            "task id %r exists in %s; pass --plan to say which task you mean"
            % (task_id, ", ".join(pid for pid, _ in matches)),
            details={"task_id": task_id, "plans": [pid for pid, _ in matches]},
        )
    found_plan_id, task = matches[0]
    if agent_id and task.get("owner") not in (agent_id, "both", "any"):
        raise CoordinationError(
            "TASK_NOT_OWNED",
            "task %s of %s belongs to %s" % (task_id, found_plan_id, task.get("owner")),
            details={"task_id": task_id, "plan_id": found_plan_id},
        )
    return found_plan_id, task


def plan_age_minutes(plan, now=None):
    proposed = parse_iso(plan.get("proposed_at"))
    if proposed is None:
        return None
    return ((now or utc_now()) - proposed).total_seconds() / 60.0


def bootstrap_window_minutes(args):
    value = getattr(args, "bootstrap_window_minutes", None)
    if value is None:
        return BOOTSTRAP_MAX_AGE_MINUTES
    return max(0, int(value))


def bootstrap_denial(state, plan, agent_id, args):
    """Why the limited bootstrap exemption does not apply (``None`` when it does)."""
    if plan.get("proposed_by") != agent_id:
        return (
            "--allow-solo only waives the ACK for a plan the caller proposed itself; "
            "plan %s was proposed by %s" % (plan["plan_id"], plan.get("proposed_by"))
        )
    age = plan_age_minutes(plan)
    if age is None:
        return "--allow-solo needs a parseable plan timestamp"
    window = bootstrap_window_minutes(args)
    if age > window:
        return (
            "--allow-solo is limited to a plan proposed within %d minute(s); plan %s is "
            "%.1f minute(s) old" % (window, plan["plan_id"], age)
        )
    return None


def bootstrap_deadline(plan, args):
    proposed = parse_iso(plan.get("proposed_at"))
    if proposed is None:
        return "-"
    return to_iso(proposed + timedelta(minutes=bootstrap_window_minutes(args)))


# ---------------------------------------------------------------------------
# board
# ---------------------------------------------------------------------------
def atomic_write_text(path, text):
    """Write a derived file with a same-directory temp file + os.replace."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class Board:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.events_path = os.path.join(self.root, EVENTS_FILE)
        self.lock_path = os.path.join(self.root, LOCK_FILE)
        self.board_path = os.path.join(self.root, BOARD_FILE)
        self.head_path = os.path.join(self.root, HEAD_FILE)

    # -- layout ------------------------------------------------------------
    def ensure_layout(self):
        for relative in ("board", "locks", "tests"):
            os.makedirs(os.path.join(self.root, relative), exist_ok=True)

    def is_initialized(self):
        return os.path.isfile(self.events_path) and os.path.getsize(self.events_path) > 0

    # -- reading -----------------------------------------------------------
    def read_events(self):
        if not os.path.isfile(self.events_path):
            return []
        events = []
        with open(self.events_path, "r", encoding="utf-8", newline="\n") as handle:
            for lineno, line in enumerate(handle, 1):
                text = line.strip()
                if not text:
                    continue
                try:
                    events.append(json.loads(text))
                except json.JSONDecodeError as exc:
                    raise CoordinationError(
                        "LOG_CORRUPT",
                        "events.jsonl line %d is not valid JSON: %s" % (lineno, exc),
                        exit_code=EXIT_CORRUPT,
                    )
        return events

    def state(self):
        """Replay the log after verifying it; never return unverified state."""
        return self.snapshot("read")[3]

    def snapshot(self, where="read"):
        """Read log + anchor, verify both and replay, all under one lock.

        The chain and the anchor are checked against the *same* captured snapshot
        that is replayed, so a concurrent append can neither produce a false
        alarm nor let a gate verdict rest on an unverified log.
        """
        with self.lock():
            events = self.read_events()
            head, head_state = self.read_head_ex()
            problems = require_intact(events, head, head_state, where)
            state = replay(events)
        return events, head, problems, state

    # -- writing -----------------------------------------------------------
    def lock(self, timeout=20.0):
        return BoardLock(self.lock_path, timeout=timeout)

    @staticmethod
    def compute_hash(event):
        body = {key: value for key, value in event.items() if key != "hash"}
        digest = hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()
        return "sha256:" + digest

    def write_event_line(self, event):
        line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        data = (line + "\n").encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
        fd = os.open(self.events_path, flags, 0o666)
        try:
            written = os.write(fd, data)
            if written != len(data):
                raise CoordinationError(
                    "SHORT_WRITE",
                    "only %d of %d bytes were appended to events.jsonl" % (written, len(data)),
                    exit_code=EXIT_CORRUPT,
                )
            os.fsync(fd)
        finally:
            os.close(fd)

    def write_head(self, seq, hash_value):
        atomic_write_text(
            self.head_path,
            json.dumps(
                {"seq": seq, "hash": hash_value, "updated_at": utc_now_iso()},
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
        )

    def read_head(self):
        if not os.path.isfile(self.head_path):
            return None
        try:
            with open(self.head_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None

    def read_head_ex(self):
        """Return ``(head, state)`` where state is ``missing``/``invalid``/``present``.

        ``verify`` has to tell "no board here" apart from "the anchor exists but
        cannot be parsed", so it may not collapse both cases into ``None``.
        """
        if not os.path.isfile(self.head_path):
            return None, "missing"
        try:
            with open(self.head_path, "r", encoding="utf-8") as handle:
                return json.load(handle), "present"
        except (OSError, json.JSONDecodeError):
            return None, "invalid"

    def transaction(self):
        return Transaction(self)

    def require_initialized(self):
        if not self.is_initialized():
            raise CoordinationError(
                "BOARD_NOT_INITIALIZED",
                "no board found at %s; run `python coord.py init` first" % self.root,
            )


class Transaction:
    """Serialised read-modify-append unit of work."""

    def __init__(self, board):
        self.board = board
        self.events = []
        self.state = None
        self.created = []
        self._lock = None

    def __enter__(self):
        self._lock = self.board.lock()
        self._lock.__enter__()
        try:
            self.events = self.board.read_events()
            head, head_state = self.board.read_head_ex()
            # Verify first, mutate second: a corrupt or truncated log is refused
            # before a single byte is appended and before the anchor is rewritten.
            require_intact(self.events, head, head_state, "mutation")
            self.state = replay(self.events)
        except BaseException:
            self._lock.__exit__(None, None, None)
            self._lock = None
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._lock is not None:
            self._lock.__exit__(exc_type, exc, tb)
        return False

    def append(self, event_type, agent, payload, note=None):
        last = self.events[-1] if self.events else None
        seq = (last.get("seq", 0) + 1) if last else 1
        event = {
            "schema_version": SCHEMA_VERSION,
            "seq": seq,
            "event_id": "evt-%06d" % seq,
            "type": event_type,
            "agent": agent,
            "ts": utc_now_iso(),
            "payload": payload,
            "prev_hash": last.get("hash", GENESIS_HASH) if last else GENESIS_HASH,
        }
        if note:
            event["note"] = note
        event["hash"] = Board.compute_hash(event)
        self.board.write_event_line(event)
        self.board.write_head(seq, event["hash"])
        self.events.append(event)
        apply_event(self.state, event)
        self.state["last_seq"] = seq
        self.state["last_hash"] = event["hash"]
        self.created.append(event)
        return event

    def atomic_write(self, path, text):
        atomic_write_text(path, text)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def _short(sha, size=12):
    return (sha or "-")[:size]


def _fmt_epoch(value):
    parsed = parse_iso(value)
    return to_iso(parsed) if parsed else (value or "-")


def board_sections(state):
    plans = sorted(state["plans"].values(), key=lambda item: item["plan_id"])
    reservations = sorted(
        state["reservations"].values(), key=lambda item: item["reservation_id"]
    )
    messages = sorted(state["messages"].values(), key=lambda item: item["message_id"])
    handoffs = sorted(state["handoffs"].values(), key=lambda item: item["handoff_id"])
    return plans, reservations, messages, handoffs


def open_messages(state, agent_id):
    out = []
    for message in sorted(state["messages"].values(), key=lambda item: item["message_id"]):
        if message["to"] not in (agent_id, "all"):
            continue
        if message["from"] == agent_id:
            continue
        if message["requires_ack"] and agent_id in message["acked_by"]:
            continue
        out.append(message)
    return out


def render_markdown(board, state):
    plans, reservations, messages, handoffs = board_sections(state)
    active = active_reservations(state)
    lines = []
    lines.append("# Qudron Coordination Board")
    lines.append("")
    lines.append("- Board root: `%s`" % board.root)
    lines.append("- Schema version: %s" % state["schema_version"])
    lines.append("- Events: %d (last seq %d)" % (len(state.get("_events", [])), state["last_seq"]))
    lines.append("- Last hash: `%s`" % state["last_hash"])
    lines.append("- Generated: %s" % utc_now_iso())
    lines.append("- Integrity: run `python coord.py verify`")
    lines.append("")
    lines.append("## Agents")
    lines.append("")
    lines.append("| Agent | Branch | Worktree | Base SHA | Revision | Last seen |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for aid, agent in sorted(state["agents"].items()):
        lines.append(
            "| `%s` | %s | `%s` | `%s` | %s | %s |"
            % (
                aid,
                agent.get("branch") or "-",
                agent.get("worktree") or "-",
                _short(agent.get("base_sha")),
                agent.get("revision", 1),
                _fmt_epoch(agent.get("last_seen")),
            )
        )
    if not state["agents"]:
        lines.append("| _none_ | - | - | - | - | - |")
    lines.append("")

    lines.append("## Progress states")
    lines.append("")
    if state["agent_status"]:
        lines.append("| Agent | State | Task | Note | At |")
        lines.append("| --- | --- | --- | --- | --- |")
        for aid, item in sorted(state["agent_status"].items()):
            lines.append(
                "| `%s` | %s | %s | %s | %s |"
                % (
                    aid,
                    item.get("state") or "-",
                    item.get("task_id") or "-",
                    (item.get("note") or "-").replace("|", "\\|"),
                    _fmt_epoch(item.get("at")),
                )
            )
    else:
        lines.append("_no status reported yet_")
    lines.append("")

    lines.append("## Plans")
    lines.append("")
    if not plans:
        lines.append("_no plan proposed yet_")
    for plan in plans:
        status = plan_status(state, plan)
        missing = plan_missing_acks(state, plan)
        lines.append("### %s — %s" % (plan["plan_id"], plan["title"]))
        lines.append("")
        lines.append(
            "- Status: **%s** | proposed by `%s` at %s"
            % (status, plan["proposed_by"], _fmt_epoch(plan["proposed_at"]))
        )
        if plan.get("base_sha"):
            lines.append("- Base SHA: `%s`" % plan["base_sha"])
        if plan.get("scope"):
            lines.append("- Scope: %s" % ", ".join("`%s`" % item for item in plan["scope"]))
        if missing:
            lines.append("- Missing ACK: %s" % ", ".join("`%s`" % item for item in missing))
        if plan.get("rejections"):
            for who, item in plan["rejections"].items():
                lines.append("- Rejected by `%s`: %s" % (who, item.get("reason") or "-"))
        if plan.get("summary"):
            lines.append("")
            lines.append(plan["summary"])
        if plan.get("tasks"):
            lines.append("")
            lines.append("| Task | Owner | Status | Files | Title |")
            lines.append("| --- | --- | --- | --- | --- |")
            for task in plan["tasks"]:
                lines.append(
                    "| `%s` | `%s` | %s | %s | %s |"
                    % (
                        task.get("id", "-"),
                        task.get("owner", "-"),
                        task.get("status", "pending"),
                        ", ".join("`%s`" % item for item in task.get("files", [])) or "-",
                        (task.get("title") or "-").replace("|", "\\|"),
                    )
                )
        lines.append("")

    lines.append("## Reservations")
    lines.append("")
    if reservations:
        lines.append("| ID | Agent | Paths | Symbols | Expires | Status |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for reservation in reservations:
            live = reservation in active
            lines.append(
                "| `%s` | `%s` | %s | %s | %s | %s |"
                % (
                    reservation["reservation_id"],
                    reservation["agent"],
                    ", ".join("`%s`" % item for item in reservation.get("paths", [])) or "-",
                    ", ".join("`%s`" % item for item in reservation.get("symbols", [])) or "-",
                    _fmt_epoch(reservation.get("expires_at")),
                    "active" if live else reservation.get("status", "-"),
                )
            )
    else:
        lines.append("_no reservation_")
    lines.append("")

    pending = [
        message
        for message in messages
        if message["requires_ack"] and not message["acked_by"]
    ]
    lines.append("## Messages awaiting ACK")
    lines.append("")
    if pending:
        for message in pending:
            lines.append(
                "- `%s` from `%s` to `%s`: **%s** (plan %s)"
                % (
                    message["message_id"],
                    message["from"],
                    message["to"],
                    message["subject"] or "-",
                    message["plan_id"] or "-",
                )
            )
            if message["body"]:
                for line in message["body"].splitlines():
                    lines.append("  > %s" % line)
    else:
        lines.append("_none_")
    lines.append("")

    lines.append("## Hand-offs")
    lines.append("")
    if handoffs:
        for handoff in handoffs:
            lines.append(
                "- `%s` by `%s` task `%s`: %s"
                % (
                    handoff["handoff_id"],
                    handoff["agent"],
                    handoff.get("task_id") or "-",
                    (handoff.get("summary") or "-").replace("\n", " "),
                )
            )
    else:
        lines.append("_none_")
    lines.append("")

    events = state.get("_events", [])
    lines.append("## Recent events")
    lines.append("")
    lines.append("| Seq | Type | Agent | At |")
    lines.append("| --- | --- | --- | --- |")
    for event in events[-15:]:
        lines.append(
            "| %s | `%s` | `%s` | %s |"
            % (event.get("seq"), event.get("type"), event.get("agent"), event.get("ts"))
        )
    lines.append("")
    return "\n".join(lines)


def render_text(board, state):
    plans, reservations, messages, handoffs = board_sections(state)
    live = active_reservations(state)
    live_ids = {item["reservation_id"] for item in live}
    out = []
    out.append("Qudron coordination board  root=%s" % board.root)
    out.append(
        "schema=%s  events=%d  last_seq=%s  last_hash=%s"
        % (state["schema_version"], len(state.get("_events", [])), state["last_seq"], _short(state["last_hash"]))
    )
    out.append("")
    out.append("AGENTS")
    if not state["agents"]:
        out.append("  (none registered)")
    for aid, agent in sorted(state["agents"].items()):
        out.append(
            "  %-12s branch=%-40s base=%s"
            % (aid, agent.get("branch") or "-", _short(agent.get("base_sha")))
        )
        out.append("               worktree=%s" % (agent.get("worktree") or "-"))
        status = state["agent_status"].get(aid)
        if status:
            out.append(
                "               state=%s task=%s note=%s"
                % (status.get("state") or "-", status.get("task_id") or "-", status.get("note") or "-")
            )
    out.append("")
    out.append("PLANS")
    if not plans:
        out.append("  (none)")
    for plan in plans:
        missing = plan_missing_acks(state, plan)
        out.append(
            "  %s [%s] by %s :: %s"
            % (plan["plan_id"], plan_status(state, plan), plan["proposed_by"], plan["title"])
        )
        if missing:
            out.append("     missing ACK: %s" % ", ".join(missing))
        for task in plan.get("tasks", []):
            out.append(
                "     - %-6s owner=%-10s status=%-10s files=%s"
                % (
                    task.get("id", "-"),
                    task.get("owner", "-"),
                    task.get("status", "pending"),
                    ",".join(task.get("files", [])) or "-",
                )
            )
    out.append("")
    out.append("RESERVATIONS")
    if not reservations:
        out.append("  (none)")
    for reservation in reservations:
        out.append(
            "  %s %-10s %-8s paths=%s symbols=%s expires=%s"
            % (
                reservation["reservation_id"],
                reservation["agent"],
                "ACTIVE" if reservation["reservation_id"] in live_ids else reservation.get("status", "-"),
                ",".join(reservation.get("paths", [])) or "-",
                ",".join(reservation.get("symbols", [])) or "-",
                reservation.get("expires_at") or "-",
            )
        )
    out.append("")
    out.append("MESSAGES AWAITING ACK")
    pending = [m for m in messages if m["requires_ack"] and not m["acked_by"]]
    if not pending:
        out.append("  (none)")
    for message in pending:
        out.append(
            "  %s %s -> %s :: %s%s"
            % (
                message["message_id"],
                message["from"],
                message["to"],
                message["subject"] or "-",
                " (plan %s)" % message["plan_id"] if message["plan_id"] else "",
            )
        )
    out.append("")
    out.append("HAND-OFFS")
    if not handoffs:
        out.append("  (none)")
    for handoff in handoffs:
        out.append(
            "  %s %s task=%s :: %s"
            % (handoff["handoff_id"], handoff["agent"], handoff.get("task_id") or "-", handoff.get("summary") or "-")
        )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# identity helpers
# ---------------------------------------------------------------------------
def require_agent_id(value):
    candidate = str(value or "").strip().lower()
    if not AGENT_ID_RE.match(candidate):
        raise CoordinationError(
            "INVALID_AGENT_ID",
            "agent id %r must match %s" % (value, AGENT_ID_RE.pattern),
        )
    return candidate


def resolve_identity(args):
    identity = {
        "branch": args.branch or "",
        "worktree": args.worktree or "",
        "base_sha": args.base_sha or "",
        "git_common_dir": "",
    }
    if not args.no_auto_git:
        detected = git_info(os.getcwd())
        for key in ("branch", "base_sha", "worktree", "git_common_dir"):
            if not identity.get(key) and detected.get(key):
                identity[key] = detected[key]
    if identity["worktree"]:
        identity["worktree"] = os.path.abspath(identity["worktree"]).replace("\\", "/")
    if identity["git_common_dir"]:
        common = identity["git_common_dir"]
        if not os.path.isabs(common):
            base = identity["worktree"] or os.getcwd()
            common = os.path.join(base, common)
        identity["git_common_dir"] = os.path.abspath(common).replace("\\", "/")
    missing = [key for key in ("branch", "worktree", "base_sha") if not identity[key]]
    if missing:
        raise CoordinationError(
            "MISSING_IDENTITY",
            "cannot determine %s; pass them explicitly or run inside a git worktree"
            % ", ".join(missing),
            details={"missing": missing},
        )
    return identity


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_init(board, args):
    board.ensure_layout()
    with board.transaction() as tx:
        if tx.state["initialized"]:
            print("board already initialised at %s (last seq %d)" % (board.root, tx.state["last_seq"]))
            return EXIT_OK
        tx.append(
            "board.initialized",
            args.by,
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_version": 1,
                "created_by": args.by,
                "root": board.root,
            },
        )
        tx.state["_events"] = tx.events
        tx.atomic_write(board.board_path, render_markdown(board, tx.state))
        print("initialised board at %s (protocol v1, schema v%d)" % (board.root, SCHEMA_VERSION))
    return EXIT_OK


def cmd_register(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    identity = resolve_identity(args)
    payload = {
        "agent_id": agent_id,
        "display_name": args.display_name or agent_id,
        "model": args.model or "",
        "role": args.role or "",
        "branch": identity["branch"],
        "worktree": identity["worktree"],
        "base_sha": identity["base_sha"],
        "git_common_dir": identity["git_common_dir"],
        "notes": args.notes or "",
        "protocol_version": 1,
    }
    with board.transaction() as tx:
        tx.append("agent.registered", agent_id, payload)
        peers = [aid for aid in tx.state["agents"] if aid != agent_id]
        mismatched = [
            aid
            for aid in peers
            if tx.state["agents"][aid].get("base_sha")
            and tx.state["agents"][aid]["base_sha"] != identity["base_sha"]
        ]
        result = {
            "agent": tx.state["agents"][agent_id],
            "revision": tx.state["agents"][agent_id]["revision"],
            "peers": peers,
            "base_sha_mismatch": mismatched,
            "event_seq": tx.state["last_seq"],
        }
    if args.json:
        emit(result, True)
    else:
        print(
            "registered %s revision %d (branch=%s, base=%s)"
            % (agent_id, result["revision"], identity["branch"], _short(identity["base_sha"]))
        )
        if mismatched:
            print(
                "WARNING: base SHA differs from %s; re-sync your worktree or note it in a message"
                % ", ".join(mismatched)
            )
        if not peers:
            print("note: no peer registered yet; the peer must register and ACK before either side edits")
    return EXIT_OK


def cmd_heartbeat(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    with board.transaction() as tx:
        _ensure_agent(tx.state, agent_id, "agent.heartbeat")
        tx.append(
            "agent.heartbeat",
            agent_id,
            {
                "agent_id": agent_id,
                "branch": args.branch or "",
                "base_sha": args.base_sha or "",
                "note": args.note or "",
            },
        )
    print("heartbeat recorded for %s" % agent_id)
    return EXIT_OK


def _parse_tasks(args, repo_root=None):
    tasks = []
    for raw in args.task_json or []:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CoordinationError("TASK_JSON_INVALID", "invalid --task-json: %s" % exc)
        tasks.append(item)
    if args.tasks_file:
        try:
            with open(args.tasks_file, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except OSError as exc:
            raise CoordinationError("TASKS_FILE_UNREADABLE", str(exc))
        except json.JSONDecodeError as exc:
            raise CoordinationError("TASKS_FILE_INVALID", str(exc))
        if not isinstance(loaded, list):
            raise CoordinationError("TASKS_FILE_INVALID", "tasks file must contain a JSON array")
        tasks.extend(loaded)
    normalised = []
    for index, item in enumerate(tasks, 1):
        if not isinstance(item, dict):
            raise CoordinationError("TASK_INVALID", "task %d is not an object" % index)
        normalised.append(
            {
                "id": str(item.get("id") or "T%d" % index),
                "owner": str(item.get("owner") or "unassigned"),
                "title": str(item.get("title") or ""),
                "files": [
                    norm_path(value, repo_root)
                    for value in (item.get("files") or [])
                ],
                "status": str(item.get("status") or "pending"),
            }
        )
    return normalised


def cmd_plan_propose(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    repo_root = _resolve_repo_root(args)
    tasks = _parse_tasks(args, repo_root)
    scope = [norm_path(item, repo_root) for item in split_values(args.scope)]
    scope_symbols = [norm_symbol(item) for item in split_values(args.symbols)]
    with board.transaction() as tx:
        agent = _ensure_agent(tx.state, agent_id, "plan.proposed")
        plan_id = next_id(tx.state, "plan")
        tx.append(
            "plan.proposed",
            agent_id,
            {
                "plan_id": plan_id,
                "title": args.title,
                "summary": args.summary or "",
                "scope": scope,
                "scope_symbols": scope_symbols,
                "tasks": tasks,
                "base_sha": args.base_sha or agent.get("base_sha", ""),
            },
        )
    if args.json:
        emit({"plan_id": plan_id, "tasks": tasks, "scope": scope, "scope_symbols": scope_symbols}, True)
    else:
        print("proposed %s :: %s (%d task(s))" % (plan_id, args.title, len(tasks)))
        print("peer must run: python coord.py plan ack --agent <peer> --plan %s" % plan_id)
    return EXIT_OK


def cmd_plan_ack(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    with board.transaction() as tx:
        _ensure_agent(tx.state, agent_id, "plan.acknowledged")
        plan = tx.state["plans"].get(args.plan)
        if plan is None:
            raise CoordinationError("PLAN_NOT_FOUND", "unknown plan %r" % args.plan)
        if plan["proposed_by"] == agent_id:
            raise CoordinationError("SELF_ACK_FORBIDDEN", "the proposing agent cannot ACK its own plan")
        tx.append(
            "plan.acknowledged",
            agent_id,
            {"plan_id": args.plan, "note": args.note or ""},
        )
        missing = plan_missing_acks(tx.state, tx.state["plans"][args.plan])
    print(
        "ACK recorded: %s by %s%s"
        % (args.plan, agent_id, "" if missing else " (plan fully acknowledged)")
    )
    if missing:
        print("still missing: %s" % ", ".join(missing))
    return EXIT_OK


def cmd_plan_reject(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    with board.transaction() as tx:
        _ensure_agent(tx.state, agent_id, "plan.rejected")
        plan = tx.state["plans"].get(args.plan)
        if plan is None:
            raise CoordinationError("PLAN_NOT_FOUND", "unknown plan %r" % args.plan)
        tx.append(
            "plan.rejected",
            agent_id,
            {"plan_id": args.plan, "reason": args.reason},
        )
    print("rejection recorded: %s by %s" % (args.plan, agent_id))
    return EXIT_OK


def cmd_msg_send(board, args):
    board.require_initialized()
    sender = require_agent_id(args.sender)
    target = args.to.strip().lower()
    body = args.body or ""
    if args.body_file:
        try:
            with open(args.body_file, "r", encoding="utf-8") as handle:
                body = handle.read()
        except OSError as exc:
            raise CoordinationError("BODY_FILE_UNREADABLE", str(exc))
    if not body.strip():
        raise CoordinationError("EMPTY_MESSAGE", "provide --body or --body-file")
    with board.transaction() as tx:
        _ensure_agent(tx.state, sender, "message.sent")
        if target != "all":
            if target == sender:
                raise CoordinationError("SELF_MESSAGE", "cannot send a message to yourself")
            _ensure_agent(tx.state, target, "message.sent")
        if args.plan and args.plan not in tx.state["plans"]:
            raise CoordinationError("PLAN_NOT_FOUND", "unknown plan %r" % args.plan)
        message_id = next_id(tx.state, "message")
        tx.append(
            "message.sent",
            sender,
            {
                "message_id": message_id,
                "from": sender,
                "to": target,
                "subject": args.subject,
                "body": body,
                "plan_id": args.plan or "",
                "requires_ack": not args.no_ack,
            },
        )
    print(
        "sent %s -> %s :: %s%s"
        % (message_id, target, args.subject, "" if args.no_ack else " (ACK required)")
    )
    return EXIT_OK


def cmd_msg_inbox(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    state = board.state()
    if agent_id not in state["agents"]:
        raise CoordinationError("AGENT_NOT_REGISTERED", "agent %r is not registered" % agent_id)
    if args.all:
        items = [
            message
            for message in sorted(state["messages"].values(), key=lambda item: item["message_id"])
            if message["to"] in (agent_id, "all") and message["from"] != agent_id
        ]
    else:
        items = open_messages(state, agent_id)
    if args.json:
        emit(
            {
                "agent": agent_id,
                "count": len(items),
                "messages": [
                    {
                        "message_id": item["message_id"],
                        "from": item["from"],
                        "to": item["to"],
                        "subject": item["subject"],
                        "body": item["body"],
                        "plan_id": item["plan_id"],
                        "sent_at": item["sent_at"],
                        "acknowledged": bool(item["acked_by"]),
                    }
                    for item in items
                ],
            },
            True,
        )
        return EXIT_OK
    if not items:
        print("inbox empty for %s" % agent_id)
        return EXIT_OK
    for item in items:
        status = "ACKED" if item["acked_by"] else ("ACK REQUIRED" if item["requires_ack"] else "info")
        print(
            "%s [%s] %s -> %s :: %s"
            % (item["message_id"], status, item["from"], item["to"], item["subject"])
        )
        for line in (item["body"] or "").splitlines():
            print("    %s" % line)
        if item["plan_id"]:
            print("    plan: %s" % item["plan_id"])
        print("")
    return EXIT_OK


def cmd_msg_ack(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    with board.transaction() as tx:
        _ensure_agent(tx.state, agent_id, "message.acknowledged")
        message = tx.state["messages"].get(args.message)
        if message is None:
            raise CoordinationError("MESSAGE_NOT_FOUND", "unknown message %r" % args.message)
        if message["to"] not in (agent_id, "all") or message["from"] == agent_id:
            raise CoordinationError(
                "NOT_A_RECIPIENT",
                "%s is not addressed to %s" % (args.message, agent_id),
            )
        tx.append(
            "message.acknowledged",
            agent_id,
            {"message_id": args.message, "note": args.note or ""},
        )
    print("ACK recorded for %s by %s" % (args.message, agent_id))
    return EXIT_OK


def _resolve_repo_root(args):
    if getattr(args, "repo_root", None):
        return os.path.abspath(args.repo_root)
    detected = git_info(os.getcwd()).get("worktree")
    return detected or None


def cmd_reserve(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    repo_root = _resolve_repo_root(args)
    paths = [norm_path(value, repo_root) for value in split_values(args.files)]
    symbols = [norm_symbol(value) for value in split_values(args.symbols)]
    if not paths and not symbols:
        raise CoordinationError("EMPTY_RESERVATION", "reserve at least one path or symbol")
    ttl = args.ttl_minutes if args.ttl_minutes is not None else DEFAULT_TTL_MINUTES
    if ttl < 0:
        raise CoordinationError("INVALID_TTL", "ttl must be >= 0")
    with board.transaction() as tx:
        _ensure_agent(tx.state, agent_id, "reservation.granted")
        if args.plan and args.plan not in tx.state["plans"]:
            raise CoordinationError("PLAN_NOT_FOUND", "unknown plan %r" % args.plan)
        conflicts = find_path_conflicts(tx.state, agent_id, paths, symbols)
        if conflicts:
            reservation_id = next_id(tx.state, "reservation")
            tx.append(
                "reservation.denied",
                agent_id,
                {
                    "reservation_id": reservation_id,
                    "agent": agent_id,
                    "paths": paths,
                    "symbols": symbols,
                    "conflicts": conflicts,
                },
            )
            payload = {
                "decision": "denied",
                "reservation_id": reservation_id,
                "agent": agent_id,
                "paths": paths,
                "symbols": symbols,
                "conflicts": conflicts,
            }
            if args.json:
                emit(payload, True)
            else:
                print("DENIED %s for %s" % (reservation_id, agent_id))
                for conflict in conflicts:
                    print(
                        "  conflict: %s %r vs %r held by %s (%s, expires %s)"
                        % (
                            conflict["kind"],
                            conflict["requested"],
                            conflict["held"],
                            conflict["agent"],
                            conflict["reservation_id"],
                            conflict["expires_at"] or "-",
                        )
                    )
                print("  resolve by messaging the holder or waiting for expiry")
            return EXIT_BLOCKED
        same = [
            item
            for item in active_reservations(tx.state)
            if item.get("agent") == agent_id
            and sorted(item.get("paths", [])) == sorted(paths)
            and sorted(item.get("symbols", [])) == sorted(symbols)
        ]
        if same:
            expires_at = to_iso(utc_now() + timedelta(minutes=ttl))
            tx.append(
                "reservation.renewed",
                agent_id,
                {"reservation_id": same[0]["reservation_id"], "expires_at": expires_at},
            )
            print(
                "extended %s for %s until %s" % (same[0]["reservation_id"], agent_id, expires_at)
            )
            return EXIT_OK
        reservation_id = next_id(tx.state, "reservation")
        expires_at = to_iso(utc_now() + timedelta(minutes=ttl))
        tx.append(
            "reservation.granted",
            agent_id,
            {
                "reservation_id": reservation_id,
                "agent": agent_id,
                "plan_id": args.plan or "",
                "paths": paths,
                "symbols": symbols,
                "ttl_minutes": ttl,
                "expires_at": expires_at,
                "note": args.note or "",
            },
        )
    payload = {
        "decision": "granted",
        "reservation_id": reservation_id,
        "agent": agent_id,
        "paths": paths,
        "symbols": symbols,
        "expires_at": expires_at,
    }
    if getattr(args, "json", False):
        emit(payload, True)
    else:
        print(
            "granted %s to %s until %s" % (reservation_id, agent_id, expires_at)
        )
        print("  paths: %s" % (", ".join(paths) or "-"))
        print("  symbols: %s" % (", ".join(symbols) or "-"))
    return EXIT_OK


def cmd_release(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    with board.transaction() as tx:
        _ensure_agent(tx.state, agent_id, "reservation.released")
        reservation = tx.state["reservations"].get(args.reservation)
        if reservation is None:
            raise CoordinationError("RESERVATION_NOT_FOUND", "unknown reservation %r" % args.reservation)
        if reservation["agent"] != agent_id:
            raise CoordinationError(
                "NOT_RESERVATION_OWNER",
                "%s belongs to %s" % (args.reservation, reservation["agent"]),
            )
        if reservation["status"] != "active":
            print("%s is already %s" % (args.reservation, reservation["status"]))
            return EXIT_OK
        tx.append(
            "reservation.released",
            agent_id,
            {"reservation_id": args.reservation, "reason": args.reason or ""},
        )
    print("released %s" % args.reservation)
    return EXIT_OK


def cmd_renew(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    ttl = args.ttl_minutes if args.ttl_minutes is not None else DEFAULT_TTL_MINUTES
    if ttl < 0:
        raise CoordinationError("INVALID_TTL", "ttl must be >= 0")
    with board.transaction() as tx:
        _ensure_agent(tx.state, agent_id, "reservation.renewed")
        reservation = tx.state["reservations"].get(args.reservation)
        if reservation is None:
            raise CoordinationError("RESERVATION_NOT_FOUND", "unknown reservation %r" % args.reservation)
        if reservation["agent"] != agent_id:
            raise CoordinationError(
                "NOT_RESERVATION_OWNER", "%s belongs to %s" % (args.reservation, reservation["agent"])
            )
        if reservation["status"] != "active":
            raise CoordinationError(
                "RESERVATION_NOT_ACTIVE", "%s is %s" % (args.reservation, reservation["status"])
            )
        expiry = parse_iso(reservation.get("expires_at"))
        if expiry is not None and expiry <= utc_now():
            # A lapsed lease is gone. Renewing it would revive it without the
            # conflict check, which is exactly how two agents end up holding the
            # same path; re-acquisition through `reserve` runs that check again.
            raise CoordinationError(
                "RESERVATION_EXPIRED",
                "%s expired at %s and cannot be renewed; re-acquire it with `reserve` so "
                "the conflict check runs again"
                % (args.reservation, reservation.get("expires_at")),
                exit_code=EXIT_BLOCKED,
                details={
                    "reservation_id": args.reservation,
                    "expires_at": reservation.get("expires_at") or "",
                },
            )
        expires_at = to_iso(utc_now() + timedelta(minutes=ttl))
        tx.append(
            "reservation.renewed",
            agent_id,
            {"reservation_id": args.reservation, "expires_at": expires_at},
        )
    print("renewed %s until %s" % (args.reservation, expires_at))
    return EXIT_OK


def cmd_gate(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    repo_root = _resolve_repo_root(args)
    paths = [norm_path(value, repo_root) for value in split_values(args.files)]
    symbols = [norm_symbol(value) for value in split_values(args.symbols)]
    reasons = []
    # A verdict is only meaningful for a log that is itself trustworthy, so the
    # chain and the anchor are verified under the board lock before any check.
    state = board.snapshot("gate")[3]

    if agent_id not in state["agents"]:
        reasons.append(
            {
                "code": "AGENT_NOT_REGISTERED",
                "detail": "register your identity before touching repository files",
                "fix": "python coord.py register --agent %s ..." % agent_id,
            }
        )
    else:
        peers = [aid for aid in state["agents"] if aid != agent_id]
        peer_base = {
            state["agents"][aid].get("base_sha") for aid in peers if state["agents"][aid].get("base_sha")
        }
        mine = state["agents"][agent_id].get("base_sha")
        if peer_base and mine and mine not in peer_base:
            reasons.append(
                {
                    "code": "BASE_SHA_DIVERGED",
                    "detail": "your base SHA %s differs from peer base %s"
                    % (_short(mine), ", ".join(_short(item) for item in peer_base)),
                    "severity": "warning",
                }
            )

    if not paths and not symbols:
        reasons.append(
            {
                "code": "GATE_REQUEST_EMPTY",
                "severity": "block",
                "detail": "gate needs at least one --files or --symbols entry; an empty "
                "request proves nothing",
                "fix": "python coord.py gate --agent %s --plan <plan> --files <path>"
                % agent_id,
            }
        )

    plan = state["plans"].get(args.plan) if args.plan else None
    target_plan_id = args.plan or ""
    peers = sorted(aid for aid in state["agents"] if aid != agent_id)

    if args.plan and plan is None:
        reasons.append(
            {"code": "PLAN_NOT_FOUND", "detail": "unknown plan %r" % args.plan, "severity": "block"}
        )
    elif plan is None:
        reasons.append(
            {
                "code": "PLAN_REQUIRED",
                "severity": "block",
                "detail": "gate requires --plan <plan_id>; the acknowledged plan must also "
                "cover the requested paths and symbols. There is no plan-less path, not "
                "even with --allow-solo",
                "fix": "python coord.py plan propose --agent %s --title ... --scope <path> "
                "--symbols <symbol>" % agent_id,
            }
        )
    else:
        target_plan_id = plan["plan_id"]
        if plan_status(state, plan) == "rejected":
            reasons.append(
                {
                    "code": "PLAN_REJECTED",
                    "detail": "plan %s was rejected by %s"
                    % (plan["plan_id"], ", ".join(sorted(plan["rejections"]))),
                    "severity": "block",
                }
            )
        acks = valid_plan_acks(state, plan)
        if peers:
            # A registered peer exists, so only a real ACK from that peer opens the
            # gate: --allow-solo never applies, and an ACK from an unknown identity
            # does not count (see valid_plan_acks).
            missing = [aid for aid in peers if aid not in acks]
            if missing:
                reasons.append(
                    {
                        "code": "PLAN_NOT_ACKED",
                        "detail": "missing ACK from %s" % ", ".join(missing),
                        "severity": "block",
                        "fix": "wait for: %s" % " ; ".join(
                            "python coord.py plan ack --agent %s --plan %s"
                            % (aid, plan["plan_id"])
                            for aid in missing
                        ),
                    }
                )
        elif args.allow_solo:
            denial = bootstrap_denial(state, plan, agent_id, args)
            if denial:
                reasons.append(
                    {
                        "code": "BOOTSTRAP_EXEMPTION_DENIED",
                        "severity": "block",
                        "detail": denial,
                        "fix": "propose a plan of your own inside the window, or register "
                        "the peer and let it ACK",
                    }
                )
            else:
                reasons.append(
                    {
                        "code": "SOLO_BOOTSTRAP_EXEMPTION",
                        "severity": "warning",
                        "detail": "no peer is registered and --allow-solo was given; the ACK "
                        "requirement is waived for plan %s only, until %s"
                        % (plan["plan_id"], bootstrap_deadline(plan, args)),
                    }
                )
        else:
            reasons.append(
                {
                    "code": "PEER_REQUIRED",
                    "severity": "block",
                    "detail": "no peer is registered, so plan %s cannot carry a peer ACK; "
                    "the gate does not allow work without one" % plan["plan_id"],
                    "fix": "register the peer and have it run: python coord.py plan ack "
                    "--agent <peer> --plan %s (--allow-solo is the bounded bootstrap "
                    "exemption)" % plan["plan_id"],
                }
            )
        declared_paths = plan_path_coverage(plan, agent_id)
        if paths:
            if not declared_paths:
                reasons.append(
                    {
                        "code": "PLAN_SCOPE_UNDECLARED",
                        "severity": "block",
                        "detail": "plan %s declares no --scope and no task files owned by %s"
                        % (plan["plan_id"], agent_id),
                        "fix": "propose a plan with --scope <path> or assign the task files to %s"
                        % agent_id,
                    }
                )
            else:
                for path in paths:
                    # Directional: the plan must *contain* the request.
                    if not any(path_covers(item, path) for item in declared_paths):
                        reasons.append(
                            {
                                "code": "PLAN_SCOPE_MISMATCH",
                                "severity": "block",
                                "detail": "%r is outside the scope of plan %s"
                                % (path, plan["plan_id"]),
                                "fix": "declare it in a plan before editing, or shrink the edit set",
                            }
                        )
        if symbols:
            declared_symbols = plan_symbol_coverage(plan)
            if not declared_symbols:
                reasons.append(
                    {
                        "code": "PLAN_SYMBOLS_UNDECLARED",
                        "severity": "warning",
                        "detail": "plan %s declares no --symbols; symbol edits rely on "
                        "reservations only" % plan["plan_id"],
                    }
                )
            else:
                for symbol in symbols:
                    # Directional: the plan must *contain* the symbol, so a plan that
                    # names only Order.total.compute cannot authorise all of Order.total.
                    if not any(symbol_covers(item, symbol) for item in declared_symbols):
                        reasons.append(
                            {
                                "code": "PLAN_SCOPE_MISMATCH",
                                "severity": "block",
                                "detail": "symbol %r is outside the scope of plan %s"
                                % (symbol, plan["plan_id"]),
                                "fix": "declare the symbol with --symbols in a plan first",
                            }
                        )

    for path in paths:
        mine = own_covering_reservations(state, agent_id, path, "path")
        peers_live = peer_overlapping_reservations(state, agent_id, path, "path")
        if peers_live:
            # Symmetric overlap wins over any lease of our own: two agents must
            # never be authorised into the same area at the same time.
            holder = peers_live[0]
            reasons.append(
                {
                    "code": "RESERVED_BY_PEER",
                    "detail": "%r overlaps %s held by %s via %s"
                    % (path, holder.get("paths", []), holder["agent"], holder["reservation_id"]),
                    "severity": "block",
                    "fix": "message %s and wait for release or expiry" % holder["agent"],
                }
            )
        if mine:
            continue
        expired_mine = expired_own_matches(state, agent_id, path, "path")
        if expired_mine:
            reasons.append(
                {
                    "code": "RESERVATION_EXPIRED",
                    "detail": "%s no longer covers %r" % (expired_mine[0]["reservation_id"], path),
                    "severity": "block",
                    # An expired lease cannot be renewed any more: it must be re-acquired.
                    "fix": "python coord.py reserve --agent %s --plan %s --files %s"
                    % (agent_id, target_plan_id or "<plan>", path),
                }
            )
        elif not peers_live:
            reasons.append(
                {
                    "code": "NOT_RESERVED",
                    "detail": "%r has no active reservation for %s" % (path, agent_id),
                    "severity": "block",
                    "fix": "python coord.py reserve --agent %s --plan %s --files %s"
                    % (agent_id, target_plan_id or "<plan>", path),
                }
            )

    for symbol in symbols:
        mine = own_covering_reservations(state, agent_id, symbol, "symbol")
        peers_live = peer_overlapping_reservations(state, agent_id, symbol, "symbol")
        if peers_live:
            holder = peers_live[0]
            reasons.append(
                {
                    "code": "RESERVED_BY_PEER",
                    "detail": "symbol %r overlaps %s held by %s via %s"
                    % (
                        symbol,
                        holder.get("symbols", []),
                        holder["agent"],
                        holder["reservation_id"],
                    ),
                    "severity": "block",
                    "fix": "message %s and wait for release or expiry" % holder["agent"],
                }
            )
        if mine:
            continue
        expired_mine = expired_own_matches(state, agent_id, symbol, "symbol")
        if expired_mine:
            reasons.append(
                {
                    "code": "RESERVATION_EXPIRED",
                    "detail": "%s no longer covers symbol %r"
                    % (expired_mine[0]["reservation_id"], symbol),
                    "severity": "block",
                    "fix": "python coord.py reserve --agent %s --plan %s --symbols %s"
                    % (agent_id, target_plan_id or "<plan>", symbol),
                }
            )
        elif not peers_live:
            reasons.append(
                {
                    "code": "NOT_RESERVED",
                    "detail": "symbol %r has no active reservation for %s" % (symbol, agent_id),
                    "severity": "block",
                    "fix": "python coord.py reserve --agent %s --plan %s --symbols %s"
                    % (agent_id, target_plan_id or "<plan>", symbol),
                }
            )

    blocking = [item for item in reasons if item.get("severity") != "warning"]
    result = {
        "decision": "block" if blocking else "allow",
        "agent": agent_id,
        "plan_id": target_plan_id,
        "paths": paths,
        "symbols": symbols,
        "reasons": reasons,
    }
    if args.json:
        emit(result, True)
    else:
        print("%s gate for %s" % ("ALLOW" if not blocking else "BLOCK", agent_id))
        for reason in reasons:
            print("  [%s] %s" % (reason["code"], reason.get("detail", "")))
            if reason.get("fix"):
                print("      fix: %s" % reason["fix"])
        if blocking:
            print("  refusing to proceed until every blocking reason is cleared")
    return EXIT_OK if not blocking else EXIT_BLOCKED


def cmd_status_set(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    if args.state not in VALID_STATES:
        raise CoordinationError(
            "INVALID_STATE", "state must be one of: %s" % ", ".join(VALID_STATES)
        )
    with board.transaction() as tx:
        _ensure_agent(tx.state, agent_id, "status.updated")
        plan_id, _task = resolve_task_reference(tx.state, args.task_id, args.plan, agent_id)
        tx.append(
            "status.updated",
            agent_id,
            {
                "state": args.state,
                "plan_id": plan_id or "",
                "task_id": args.task_id or "",
                "note": args.note or "",
            },
        )
    print(
        "status: %s -> %s%s%s"
        % (
            agent_id,
            args.state,
            " (task %s of %s)" % (args.task_id, plan_id) if args.task_id else "",
            "\n  note: %s" % args.note if args.note else "",
        )
    )
    return EXIT_OK


def cmd_status_get(board, args):
    board.require_initialized()
    state = board.state()
    if args.agent:
        agent_id = require_agent_id(args.agent)
        item = state["agent_status"].get(agent_id)
        if item is None:
            print("%s has not reported a state" % agent_id)
            return EXIT_OK
        if args.json:
            emit({"agent": agent_id, **item}, True)
        else:
            print("%s: %s task=%s note=%s" % (agent_id, item["state"], item["task_id"] or "-", item["note"] or "-"))
        return EXIT_OK
    if args.json:
        emit({"statuses": state["agent_status"]}, True)
        return EXIT_OK
    if not state["agent_status"]:
        print("no state reported yet")
    for aid, item in sorted(state["agent_status"].items()):
        print("%s: %s task=%s note=%s" % (aid, item["state"], item["task_id"] or "-", item["note"] or "-"))
    return EXIT_OK


def cmd_handoff(board, args):
    board.require_initialized()
    agent_id = require_agent_id(args.agent)
    files = [str(item).strip().replace("\\", "/") for item in split_values(args.files)]
    with board.transaction() as tx:
        _ensure_agent(tx.state, agent_id, "handoff.submitted")
        if args.plan and args.plan not in tx.state["plans"]:
            raise CoordinationError("PLAN_NOT_FOUND", "unknown plan %r" % args.plan)
        plan_id, _task = resolve_task_reference(tx.state, args.task_id, args.plan, agent_id)
        handoff_id = next_id(tx.state, "handoff")
        tx.append(
            "handoff.submitted",
            agent_id,
            {
                "handoff_id": handoff_id,
                "agent": agent_id,
                "plan_id": plan_id or args.plan or "",
                "task_id": args.task_id or "",
                "summary": args.summary,
                "files": files,
                "tests": args.tests or "",
                "next_steps": args.next_steps or "",
                "state": "delivered",
            },
        )
    print("hand-off %s submitted by %s%s" % (handoff_id, agent_id, " for task %s" % args.task_id if args.task_id else ""))
    return EXIT_OK


def cmd_board(board, args):
    board.require_initialized()
    with board.transaction() as tx:
        tx.state["_events"] = tx.events
        if args.json:
            snapshot = {key: value for key, value in tx.state.items() if key != "_events"}
            snapshot["event_count"] = len(tx.events)
            snapshot["plans"] = {
                pid: dict(plan, status=plan_status(tx.state, plan))
                for pid, plan in tx.state["plans"].items()
            }
            snapshot["active_reservations"] = [
                item["reservation_id"] for item in active_reservations(tx.state)
            ]
            snapshot["open_messages"] = {
                aid: [item["message_id"] for item in open_messages(tx.state, aid)]
                for aid in tx.state["agents"]
            }
            emit(snapshot, True)
            return EXIT_OK
        text = render_text(board, tx.state)
        if args.write:
            tx.atomic_write(board.board_path, render_markdown(board, tx.state))
            text += "\n\nwrote %s" % board.board_path
        print(text)
    return EXIT_OK


def verify_events(events):
    problems = []
    expected_prev = GENESIS_HASH
    expected_seq = 1
    for index, event in enumerate(events):
        seq = event.get("seq")
        if seq != expected_seq:
            problems.append(
                {
                    "code": "SEQ_GAP",
                    "index": index,
                    "expected": expected_seq,
                    "found": seq,
                }
            )
        if event.get("prev_hash") != expected_prev:
            problems.append(
                {
                    "code": "LINK_BROKEN",
                    "index": index,
                    "seq": seq,
                    "expected_prev": expected_prev,
                    "found_prev": event.get("prev_hash"),
                }
            )
        recomputed = Board.compute_hash(event)
        if event.get("hash") != recomputed:
            problems.append(
                {
                    "code": "HASH_MISMATCH",
                    "index": index,
                    "seq": seq,
                    "stored": event.get("hash"),
                    "recomputed": recomputed,
                }
            )
        expected_prev = event.get("hash")
        expected_seq = (seq + 1) if isinstance(seq, int) else expected_seq + 1
    return problems


def verify_head(events, head):
    """Cross-check the anchored head against a captured, consistent snapshot."""
    problems = []
    if head is None:
        if not events:
            # Nothing was ever written: the board is simply not initialised yet.
            return []
        return [
            {
                "code": "HEAD_ANCHOR_MISSING",
                "severity": "error",
                "detail": "board/HEAD.json is missing; tail truncation cannot be detected",
            }
        ]
    anchor_seq = head.get("seq")
    anchor_hash = head.get("hash")
    if not isinstance(anchor_seq, int) or anchor_seq < 1:
        return [{"code": "HEAD_ANCHOR_INVALID", "severity": "error", "detail": repr(head)}]
    if anchor_seq > len(events):
        problems.append(
            {
                "code": "TAIL_TRUNCATED",
                "severity": "error",
                "detail": "anchor points at seq %d but only %d event(s) exist"
                % (anchor_seq, len(events)),
            }
        )
        return problems
    if events[anchor_seq - 1].get("hash") != anchor_hash:
        problems.append(
            {
                "code": "ANCHOR_MISMATCH",
                "severity": "error",
                "detail": "event %d hash does not match the anchored head" % anchor_seq,
            }
        )
    elif anchor_seq < len(events):
        problems.append(
            {
                "code": "HEAD_ANCHOR_BEHIND",
                "severity": "warning",
                "detail": "anchor at seq %d, log at %d (crash between append and anchor write)"
                % (anchor_seq, len(events)),
            }
        )
    return problems


def log_presence_problems(events, head):
    """An anchor with no log behind it means the source of truth was lost."""
    if events:
        return []
    if isinstance((head or {}).get("seq"), int) and head.get("seq") >= 1:
        return [
            {
                "code": "LOG_MISSING",
                "severity": "error",
                "detail": "board/HEAD.json anchors seq %d but events.jsonl is missing "
                "or empty" % head["seq"],
            }
        ]
    return []


def integrity_problems(events, head, head_state="present"):
    """Every integrity finding for one snapshot of log + anchor."""
    if head_state == "invalid":
        return [
            {
                "code": "HEAD_ANCHOR_INVALID",
                "severity": "error",
                "detail": "board/HEAD.json exists but cannot be parsed",
            }
        ]
    problems = log_presence_problems(events, head)
    if problems:
        return problems
    problems = verify_events(events)
    problems.extend(verify_head(events, head))
    return problems


def fatal_problems(problems):
    return [item for item in problems if item.get("severity", "error") == "error"]


def require_intact(events, head, head_state, where):
    """Refuse to read or mutate a board whose log or anchor is not trustworthy.

    The anchor is deliberately left untouched when this raises: repairing a broken
    board is a human decision, not a side effect of an ordinary command.
    """
    problems = integrity_problems(events, head, head_state)
    fatal = fatal_problems(problems)
    if fatal:
        codes = sorted({item["code"] for item in fatal})
        raise CoordinationError(
            "BOARD_CORRUPT",
            "%s refused: the event log or its anchor is not trustworthy (%s); run "
            "`python coord.py verify` and report it" % (where, ", ".join(codes)),
            exit_code=EXIT_CORRUPT,
            details={"problems": fatal},
        )
    return problems


def cmd_verify(board, args):
    """Report the integrity of the log *and* tell the three states apart.

    ``uninitialized`` (nothing written yet), ``ok`` and ``corrupt`` are different
    answers, and a missing or empty log under an existing anchor is corruption,
    not an empty board.
    """
    with board.lock():
        events = board.read_events()
        head, head_state = board.read_head_ex()
    problems = integrity_problems(events, head, head_state)
    failures = fatal_problems(problems)
    if failures:
        status = "corrupt"
    elif not events:
        status = "uninitialized"
    else:
        status = "ok"
    result = {
        "ok": not failures,
        "status": status,
        "root": board.root,
        "events": len(events),
        "last_seq": events[-1].get("seq") if events else 0,
        "last_hash": events[-1].get("hash") if events else GENESIS_HASH,
        "anchor": head,
        "problems": problems,
    }
    if args.json:
        emit(result, True)
    else:
        if status == "uninitialized":
            print(
                "UNINITIALIZED: no event log and no anchor at %s (nothing to verify yet)"
                % board.root
            )
        elif result["ok"]:
            print(
                "OK: %d event(s), hash chain intact, anchor seq %s, last seq %s"
                % (result["events"], (head or {}).get("seq", "-"), result["last_seq"])
            )
        else:
            print("BROKEN: %d problem(s) detected" % len(failures))
        for problem in problems:
            if problem.get("severity") == "warning":
                print("  warning %s: %s" % (problem["code"], problem.get("detail", "")))
            else:
                print("  %s: %s" % (problem["code"], json.dumps(problem, ensure_ascii=False)))
    return EXIT_OK if result["ok"] else EXIT_CORRUPT



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def emit(obj, as_json):
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="coord.py",
        description="Shared coordination board for Qoder and GitHub Copilot.",
        epilog="See PROTOCOL.md for the full protocol and README.md for the runbook.",
    )
    parser.add_argument(
        "--root",
        default=os.environ.get("AGENT_COORD_ROOT") or os.path.dirname(os.path.abspath(__file__)),
        help="board directory (default: directory of this script or $AGENT_COORD_ROOT)",
    )
    parser.add_argument("--json", action="store_true", help="machine readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create the board layout and genesis event")
    init.add_argument("--by", default="system", help="who initialises the board")
    init.set_defaults(func=cmd_init)

    register = sub.add_parser("register", help="register agent identity, branch, worktree, base SHA")
    register.add_argument("--agent", required=True)
    register.add_argument("--display-name", default="")
    register.add_argument("--model", default="")
    register.add_argument("--role", default="")
    register.add_argument("--branch", default=None)
    register.add_argument("--worktree", default=None)
    register.add_argument("--base-sha", default=None)
    register.add_argument("--notes", default="")
    register.add_argument("--no-auto-git", action="store_true", help="do not detect branch/SHA with git")
    register.set_defaults(func=cmd_register)

    heartbeat = sub.add_parser("heartbeat", help="refresh liveness and base SHA for an agent")
    heartbeat.add_argument("--agent", required=True)
    heartbeat.add_argument("--branch", default=None)
    heartbeat.add_argument("--base-sha", default=None)
    heartbeat.add_argument("--note", default="")
    heartbeat.set_defaults(func=cmd_heartbeat)

    plan = sub.add_parser("plan", help="propose, acknowledge or reject a plan")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    propose = plan_sub.add_parser("propose")
    propose.add_argument("--agent", required=True)
    propose.add_argument("--title", required=True)
    propose.add_argument("--summary", default="")
    propose.add_argument("--scope", nargs="*", default=[], help="paths or areas this plan covers")
    propose.add_argument("--symbols", nargs="*", default=[], help="symbols this plan covers")
    propose.add_argument("--repo-root", default=None)
    propose.add_argument("--base-sha", default="")
    propose.add_argument("--task-json", action="append", default=[], help="JSON object for one task")
    propose.add_argument("--tasks-file", default=None, help="JSON file with an array of tasks")
    propose.set_defaults(func=cmd_plan_propose, repo_root=None)
    ack = plan_sub.add_parser("ack")
    ack.add_argument("--agent", required=True)
    ack.add_argument("--plan", required=True)
    ack.add_argument("--note", default="")
    ack.set_defaults(func=cmd_plan_ack)
    reject = plan_sub.add_parser("reject")
    reject.add_argument("--agent", required=True)
    reject.add_argument("--plan", required=True)
    reject.add_argument("--reason", required=True)
    reject.set_defaults(func=cmd_plan_reject)

    msg = sub.add_parser("msg", help="exchange messages")
    msg_sub = msg.add_subparsers(dest="msg_command", required=True)
    send = msg_sub.add_parser("send")
    send.add_argument("--from", dest="sender", required=True)
    send.add_argument("--to", required=True, help="agent id or 'all'")
    send.add_argument("--subject", required=True)
    send.add_argument("--body", default="")
    send.add_argument("--body-file", default=None)
    send.add_argument("--plan", default=None)
    send.add_argument("--no-ack", action="store_true", help="informational message, no ACK expected")
    send.set_defaults(func=cmd_msg_send)
    inbox = msg_sub.add_parser("inbox")
    inbox.add_argument("--agent", required=True)
    inbox.add_argument("--all", action="store_true", help="include already acknowledged messages")
    inbox.set_defaults(func=cmd_msg_inbox)
    ack_msg = msg_sub.add_parser("ack")
    ack_msg.add_argument("--agent", required=True)
    ack_msg.add_argument("--message", required=True)
    ack_msg.add_argument("--note", default="")
    ack_msg.set_defaults(func=cmd_msg_ack)

    reserve = sub.add_parser("reserve", help="reserve files and symbols with conflict detection")
    reserve.add_argument("--agent", required=True)
    reserve.add_argument("--files", nargs="*", default=[])
    reserve.add_argument("--symbols", nargs="*", default=[])
    reserve.add_argument("--plan", default=None)
    reserve.add_argument("--ttl-minutes", type=int, default=None)
    reserve.add_argument("--repo-root", default=None)
    reserve.add_argument("--note", default="")
    reserve.set_defaults(func=cmd_reserve)

    release = sub.add_parser("release", help="release a reservation")
    release.add_argument("--agent", required=True)
    release.add_argument("--reservation", required=True)
    release.add_argument("--reason", default="")
    release.set_defaults(func=cmd_release)

    renew = sub.add_parser("renew", help="extend a reservation lease")
    renew.add_argument("--agent", required=True)
    renew.add_argument("--reservation", required=True)
    renew.add_argument("--ttl-minutes", type=int, default=None)
    renew.set_defaults(func=cmd_renew)

    gate = sub.add_parser("gate", help="pre-edit gate: ACK + reservation check")
    gate.add_argument("--agent", required=True)
    gate.add_argument("--files", nargs="*", default=[])
    gate.add_argument("--symbols", nargs="*", default=[])
    gate.add_argument("--plan", default=None)
    gate.add_argument("--strict", action="store_true", help="deprecated: a specific acknowledged plan is now always required")
    gate.add_argument(
        "--allow-solo",
        action="store_true",
        help="bounded bootstrap exemption: waive the peer ACK only while no peer is "
        "registered, the plan is yours and it is fresh",
    )
    gate.add_argument(
        "--bootstrap-window-minutes",
        type=int,
        default=None,
        help="age limit for --allow-solo (default %d)" % BOOTSTRAP_MAX_AGE_MINUTES,
    )
    gate.add_argument("--repo-root", default=None)
    gate.set_defaults(func=cmd_gate)

    status = sub.add_parser("status", help="report or read progress state")
    status_sub = status.add_subparsers(dest="status_command", required=True)
    status_set = status_sub.add_parser("set")
    status_set.add_argument("--agent", required=True)
    status_set.add_argument("--state", required=True)
    status_set.add_argument("--plan", default=None, help="plan that owns the task (required when task ids collide)")
    status_set.add_argument("--task-id", default=None)
    status_set.add_argument("--note", default="")
    status_set.set_defaults(func=cmd_status_set)
    status_get = status_sub.add_parser("get")
    status_get.add_argument("--agent", default=None)
    status_get.set_defaults(func=cmd_status_get)

    handoff = sub.add_parser("handoff", help="submit a delivery record for a task")
    handoff.add_argument("--agent", required=True)
    handoff.add_argument("--task-id", default=None)
    handoff.add_argument("--plan", default=None)
    handoff.add_argument("--summary", required=True)
    handoff.add_argument("--files", nargs="*", default=[])
    handoff.add_argument("--tests", default="")
    handoff.add_argument("--next-steps", default="")
    handoff.set_defaults(func=cmd_handoff)

    board_cmd = sub.add_parser("board", help="render the live board")
    board_cmd.add_argument("--write", action="store_true", help="also regenerate board/BOARD.md")
    board_cmd.set_defaults(func=cmd_board)

    verify = sub.add_parser("verify", help="verify the hash chain of the event log")
    verify.set_defaults(func=cmd_verify)

    return parser


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    board = Board(os.path.abspath(args.root))
    try:
        return int(args.func(board, args) or EXIT_OK)
    except CoordinationError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
