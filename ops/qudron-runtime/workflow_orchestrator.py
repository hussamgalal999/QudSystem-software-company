"""Unified sequential, parallel, pipeline, swarm and consensus scheduler.

Every execution mode is represented as a dependency graph (DAG). SQLite
idempotency, approval gates, expiring resource leases and artifact checkpoints
prevent duplicate work and concurrent writers from silently overwriting each
other. The scheduler executes only the nodes and adapters explicitly supplied.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
import time
import uuid
from typing import Any, Awaitable, Callable, Iterable

from agent_protocol import ExecutionMode, ResourceClaim, ResourceMode


class WorkflowError(RuntimeError):
    pass


class ResourceBusy(WorkflowError):
    pass


@dataclass(frozen=True)
class WorkflowNode:
    node_id: str
    title: str
    instruction: str
    dependencies: tuple[str, ...] = ()
    assigned_agent_id: str | None = None
    resource_claims: tuple[ResourceClaim, ...] = ()
    requires_approval: bool = False
    approved_by: str | None = None
    retry_safe: bool = True
    max_attempts: int = 2
    persist_output: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_id or not self.title or not self.instruction.strip():
            raise ValueError("node_id, title and instruction are required")
        if self.max_attempts < 1 or self.max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if self.requires_approval and self.approved_by and len(self.approved_by) > 160:
            raise ValueError("approved_by is too long")


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    project_id: str
    idempotency_key: str
    execution_mode: ExecutionMode
    nodes: tuple[WorkflowNode, ...]
    max_parallel: int = 8

    def __post_init__(self) -> None:
        if not self.workflow_id or not self.project_id or not self.idempotency_key:
            raise ValueError("workflow_id, project_id and idempotency_key are required")
        if not 1 <= self.max_parallel <= 128:
            raise ValueError("max_parallel must be between 1 and 128")
        validate_dag(self.nodes)


@dataclass(frozen=True)
class NodeExecutionResult:
    status: str
    summary: str = ""
    artifacts: tuple[dict[str, Any], ...] = ()
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def validate_dag(nodes: Iterable[WorkflowNode]) -> None:
    items = list(nodes)
    ids = [node.node_id for node in items]
    if len(ids) != len(set(ids)):
        raise ValueError("workflow node IDs must be unique")
    id_set = set(ids)
    for node in items:
        missing = set(node.dependencies) - id_set
        if missing:
            raise ValueError(f"{node.node_id} has missing dependencies: {sorted(missing)}")
        if node.node_id in node.dependencies:
            raise ValueError(f"{node.node_id} cannot depend on itself")
    visiting: set[str] = set()
    visited: set[str] = set()
    by_id = {node.node_id: node for node in items}

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("workflow dependency graph contains a cycle")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency in by_id[node_id].dependencies:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in ids:
        visit(node_id)


def expand_execution_mode(
    mode: ExecutionMode, workers: list[tuple[str, str, str]],
    *, finalizer: tuple[str, str, str] | None = None,
) -> tuple[WorkflowNode, ...]:
    """Compile simple role lists into common safe graph patterns.

    workers are (node_id, title, instruction). Swarm/map-reduce/consensus modes
    intentionally isolate each worker's artifact namespace; only the reducer
    or finalizer may write the shared result resource.
    """
    if not workers:
        raise ValueError("at least one worker is required")
    if mode in {ExecutionMode.SEQUENTIAL, ExecutionMode.PIPELINE}:
        result: list[WorkflowNode] = []
        previous: tuple[str, ...] = ()
        for node_id, title, instruction in workers:
            result.append(WorkflowNode(node_id, title, instruction, previous))
            previous = (node_id,)
        return tuple(result)
    if mode == ExecutionMode.PARALLEL:
        return tuple(
            WorkflowNode(node_id, title, instruction)
            for node_id, title, instruction in workers
        )
    if mode in {ExecutionMode.SWARM, ExecutionMode.MAP_REDUCE, ExecutionMode.CONSENSUS}:
        fanout = tuple(
            WorkflowNode(
                node_id, title, instruction,
                resource_claims=(ResourceClaim(f"artifact:{node_id}", ResourceMode.WRITE),),
                metadata={"swarm_member": True, "result_kind": mode.value},
            )
            for node_id, title, instruction in workers
        )
        reducer = finalizer or (
            "qudron_reduce", "Qudron final synthesis",
            "Synthesize the worker results, identify disagreements, and preserve unresolved findings.",
        )
        return fanout + (
            WorkflowNode(
                reducer[0], reducer[1], reducer[2],
                dependencies=tuple(node[0] for node in workers),
                resource_claims=(ResourceClaim("artifact:workflow-final", ResourceMode.WRITE),),
                metadata={"reducer": True, "quorum_required": len(workers) // 2 + 1 if mode == ExecutionMode.CONSENSUS else None},
            ),
        )
    if mode == ExecutionMode.HYBRID:
        raise ValueError("HYBRID requires an explicit dependency graph; pass WorkflowNode dependencies")
    raise ValueError(f"Unsupported execution mode: {mode}")


class WorkflowStore:
    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._schema()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    @contextmanager
    def connection(self):
        db = self.connect()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _schema(self) -> None:
        with self.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS workflow_runs(
              workflow_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
              idempotency_key TEXT NOT NULL UNIQUE, execution_mode TEXT NOT NULL,
              status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_nodes(
              workflow_id TEXT NOT NULL, node_id TEXT NOT NULL, title TEXT NOT NULL,
              instruction TEXT NOT NULL, dependencies_json TEXT NOT NULL,
              agent_id TEXT, resource_claims_json TEXT NOT NULL,
              requires_approval INTEGER NOT NULL, approved_by TEXT,
              retry_safe INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0, persist_output INTEGER NOT NULL,
              status TEXT NOT NULL, output_json TEXT, artifacts_json TEXT NOT NULL DEFAULT '[]',
              evidence_json TEXT NOT NULL DEFAULT '[]', error TEXT, metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at REAL NOT NULL, updated_at REAL NOT NULL,
              PRIMARY KEY(workflow_id,node_id),
              FOREIGN KEY(workflow_id) REFERENCES workflow_runs(workflow_id)
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_nodes_status ON workflow_nodes(workflow_id,status);
            CREATE TABLE IF NOT EXISTS workflow_resource_locks(
              resource_key TEXT NOT NULL, owner_key TEXT NOT NULL, lock_mode TEXT NOT NULL,
              lease_until REAL NOT NULL, updated_at REAL NOT NULL,
              PRIMARY KEY(resource_key,owner_key)
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_resource_lease
              ON workflow_resource_locks(resource_key,lease_until);
            """)

    def create(self, definition: WorkflowDefinition) -> str:
        now = time.time()
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT workflow_id FROM workflow_runs WHERE idempotency_key=?",
                (definition.idempotency_key,),
            ).fetchone()
            if existing:
                db.execute("COMMIT")
                return str(existing["workflow_id"])
            db.execute(
                """INSERT INTO workflow_runs
                   (workflow_id,project_id,idempotency_key,execution_mode,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (definition.workflow_id, definition.project_id, definition.idempotency_key,
                 definition.execution_mode.value, "queued", now, now),
            )
            for node in definition.nodes:
                claims = [
                    {"resource": c.resource, "mode": c.mode.value}
                    for c in node.resource_claims
                ]
                db.execute(
                    """INSERT INTO workflow_nodes
                    (workflow_id,node_id,title,instruction,dependencies_json,agent_id,
                     resource_claims_json,requires_approval,approved_by,retry_safe,max_attempts,
                     attempts,persist_output,status,metadata_json,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?,'queued',?,?,?)""",
                    (definition.workflow_id, node.node_id, node.title, node.instruction,
                     json.dumps(node.dependencies), node.assigned_agent_id, json.dumps(claims),
                     int(node.requires_approval), node.approved_by, int(node.retry_safe),
                     node.max_attempts, int(node.persist_output),
                     json.dumps(node.metadata, ensure_ascii=False), now, now),
                )
            db.execute("COMMIT")
            return definition.workflow_id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, workflow_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM workflow_nodes WHERE workflow_id=? ORDER BY created_at,node_id",
                (workflow_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def acquire_resources(
        self, owner_key: str, claims: tuple[ResourceClaim, ...], lease_seconds: int = 120
    ) -> bool:
        now = time.time()
        ordered = sorted(claims, key=lambda item: item.resource)
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM workflow_resource_locks WHERE lease_until<=?", (now,))
            for claim in ordered:
                conflicts = db.execute(
                    """SELECT 1 FROM workflow_resource_locks
                       WHERE resource_key=? AND owner_key<>? AND lease_until>?
                         AND (?='write' OR lock_mode='write')
                       LIMIT 1""",
                    (claim.resource, owner_key, now, claim.mode.value),
                ).fetchone()
                if conflicts:
                    db.execute("ROLLBACK")
                    return False
            for claim in ordered:
                db.execute(
                    """INSERT INTO workflow_resource_locks
                       (resource_key,owner_key,lock_mode,lease_until,updated_at)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(resource_key,owner_key) DO UPDATE SET
                       lock_mode=excluded.lock_mode,lease_until=excluded.lease_until,updated_at=excluded.updated_at""",
                    (claim.resource, owner_key, claim.mode.value, now + lease_seconds, now),
                )
            db.execute("COMMIT")
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def renew_resources(self, owner_key: str, lease_seconds: int = 120) -> bool:
        now = time.time()
        with self.connect() as db:
            changed = db.execute(
                "UPDATE workflow_resource_locks SET lease_until=?,updated_at=? WHERE owner_key=? AND lease_until>?",
                (now + lease_seconds, now, owner_key, now),
            ).rowcount
        return changed > 0

    def release_resources(self, owner_key: str) -> None:
        with self.connect() as db:
            db.execute(
                "DELETE FROM workflow_resource_locks WHERE owner_key=?",
                (owner_key,),
            )

    def approve_node(self, workflow_id: str, node_id: str, approver: str) -> None:
        if not approver.strip():
            raise ValueError("approver is required")
        with self.connect() as db:
            changed = db.execute(
                """UPDATE workflow_nodes SET approved_by=?,status='queued',updated_at=?
                   WHERE workflow_id=? AND node_id=? AND requires_approval=1""",
                (approver[:160], time.time(), workflow_id, node_id),
            ).rowcount
        if changed != 1:
            raise WorkflowError("Approval target was not found or does not require approval")

    def start_node(self, workflow_id: str, node_id: str) -> int:
        now = time.time()
        with self.connect() as db:
            row = db.execute(
                "SELECT attempts,status FROM workflow_nodes WHERE workflow_id=? AND node_id=?",
                (workflow_id, node_id),
            ).fetchone()
            if not row:
                raise WorkflowError("Workflow node not found")
            if row["status"] in {"succeeded", "failed", "cancelled"}:
                raise WorkflowError("Terminal workflow node cannot be restarted implicitly")
            attempts = int(row["attempts"]) + 1
            db.execute(
                """UPDATE workflow_nodes SET status='running',attempts=?,error=NULL,updated_at=?
                   WHERE workflow_id=? AND node_id=?""",
                (attempts, now, workflow_id, node_id),
            )
        return attempts

    def finish_node(
        self, workflow_id: str, node_id: str, result: NodeExecutionResult
    ) -> None:
        now = time.time()
        status = "succeeded" if result.status == "succeeded" else "failed"
        with self.connect() as db:
            db.execute(
                """UPDATE workflow_nodes SET status=?,output_json=?,artifacts_json=?,
                   evidence_json=?,metadata_json=?,error=?,updated_at=?
                   WHERE workflow_id=? AND node_id=?""",
                (
                    status,
                    json.dumps({"summary": result.summary, "metadata": result.metadata}, ensure_ascii=False)
                    if result.status == "succeeded" and self._persist_output(db, workflow_id, node_id) else None,
                    json.dumps(result.artifacts, ensure_ascii=False),
                    json.dumps(result.evidence, ensure_ascii=False),
                    json.dumps(result.metadata, ensure_ascii=False),
                    None if status == "succeeded" else result.summary[:1200],
                    now, workflow_id, node_id,
                ),
            )

    @staticmethod
    def _persist_output(db: sqlite3.Connection, workflow_id: str, node_id: str) -> bool:
        row = db.execute(
            "SELECT persist_output FROM workflow_nodes WHERE workflow_id=? AND node_id=?",
            (workflow_id, node_id),
        ).fetchone()
        return bool(row and row["persist_output"])

    def retry_node(self, workflow_id: str, node_id: str, error: str) -> bool:
        with self.connect() as db:
            row = db.execute(
                """SELECT attempts,max_attempts,retry_safe FROM workflow_nodes
                   WHERE workflow_id=? AND node_id=?""", (workflow_id, node_id)
            ).fetchone()
            if not row:
                raise WorkflowError("Workflow node not found")
            retry = bool(row["retry_safe"]) and int(row["attempts"]) < int(row["max_attempts"])
            db.execute(
                """UPDATE workflow_nodes SET status=?,error=?,updated_at=?
                   WHERE workflow_id=? AND node_id=?""",
                ("queued" if retry else "failed", error[:1200], time.time(), workflow_id, node_id),
            )
        return retry

    def set_workflow_status(self, workflow_id: str, status: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE workflow_runs SET status=?,updated_at=? WHERE workflow_id=?",
                (status, time.time(), workflow_id),
            )

    def snapshot(self, workflow_id: str) -> dict[str, Any]:
        with self.connect() as db:
            run = db.execute(
                "SELECT * FROM workflow_runs WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
        if not run:
            raise WorkflowError("Workflow not found")
        rows = self.rows(workflow_id)
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {
            "workflow_id": workflow_id, "project_id": run["project_id"],
            "mode": run["execution_mode"], "status": run["status"],
            "counts": counts, "nodes": rows,
        }


class WorkflowOrchestrator:
    def __init__(
        self, store: WorkflowStore, *,
        max_global_parallel: int = 16, lease_seconds: int = 120,
        retry_base_seconds: float = 0.2,
    ):
        self.store = store
        self.max_global_parallel = max(1, min(128, max_global_parallel))
        self.lease_seconds = max(30, lease_seconds)
        self.retry_base_seconds = max(0.0, retry_base_seconds)

    async def _keep_lease(self, owner: str, stop: asyncio.Event) -> None:
        interval = max(5.0, self.lease_seconds / 3)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                if not self.store.renew_resources(owner, self.lease_seconds):
                    return

    async def _execute_node(
        self, workflow_id: str, row: dict[str, Any],
        executor: Callable[[dict[str, Any]], Awaitable[NodeExecutionResult]],
        semaphore: asyncio.Semaphore,
    ) -> None:
        node_id = str(row["node_id"])
        owner = f"{workflow_id}:{node_id}"
        claims = tuple(
            ResourceClaim(item["resource"], ResourceMode(item.get("mode", "read")))
            for item in json.loads(row["resource_claims_json"])
        )
        for attempt in range(1, int(row["max_attempts"]) + 1):
            self.store.start_node(workflow_id, node_id)
            stop = asyncio.Event()
            heartbeat = asyncio.create_task(self._keep_lease(owner, stop))
            try:
                async with semaphore:
                    result = await executor(row)
                if not isinstance(result, NodeExecutionResult):
                    raise TypeError("workflow executor must return NodeExecutionResult")
                if result.status != "succeeded":
                    raise WorkflowError(result.summary or "Agent did not return success")
                self.store.finish_node(workflow_id, node_id, result)
                return
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"[:1200]
                retry = self.store.retry_node(workflow_id, node_id, message)
                if not retry:
                    return
                if self.retry_base_seconds:
                    await asyncio.sleep(min(5.0, self.retry_base_seconds * (2 ** (attempt - 1))))
            finally:
                stop.set()
                await heartbeat
                self.store.release_resources(owner)

    async def run(
        self, definition: WorkflowDefinition,
        executor: Callable[[dict[str, Any]], Awaitable[NodeExecutionResult]],
    ) -> dict[str, Any]:
        workflow_id = self.store.create(definition)
        semaphore = asyncio.Semaphore(min(definition.max_parallel, self.max_global_parallel))
        running: dict[str, asyncio.Task[None]] = {}
        self.store.set_workflow_status(workflow_id, "running")

        while True:
            rows = self.store.rows(workflow_id)
            by_id = {row["node_id"]: row for row in rows}
            active_ids = set(running)
            completed_ids = {
                row["node_id"] for row in rows if row["status"] == "succeeded"
            }
            made_progress = False

            for row in rows:
                if len(running) >= min(definition.max_parallel, self.max_global_parallel):
                    break
                node_id = row["node_id"]
                if node_id in active_ids or row["status"] != "queued":
                    continue
                if row["requires_approval"] and not row["approved_by"]:
                    continue
                dependencies = set(json.loads(row["dependencies_json"]))
                if not dependencies.issubset(completed_ids):
                    continue
                owner = f"{workflow_id}:{node_id}"
                claims = tuple(
                    ResourceClaim(item["resource"], ResourceMode(item.get("mode", "read")))
                    for item in json.loads(row["resource_claims_json"])
                )
                if not self.store.acquire_resources(owner, claims, self.lease_seconds):
                    continue
                running[node_id] = asyncio.create_task(
                    self._execute_node(workflow_id, row, executor, semaphore)
                )
                made_progress = True
                active_ids.add(node_id)

            if running:
                done, _ = await asyncio.wait(
                    tuple(running.values()), return_when=asyncio.FIRST_COMPLETED
                )
                for node_id, task in list(running.items()):
                    if task in done:
                        await task
                        running.pop(node_id, None)
                continue

            rows = self.store.rows(workflow_id)
            statuses = {row["node_id"]: row["status"] for row in rows}
            if all(status == "succeeded" for status in statuses.values()):
                final_status = "succeeded"
            elif any(status == "failed" for status in statuses.values()):
                final_status = "failed"
            elif any(
                row["requires_approval"] and not row["approved_by"] and row["status"] == "queued"
                for row in rows
            ):
                final_status = "waiting_for_approval"
            elif any(
                row["status"] == "queued" and not set(json.loads(row["dependencies_json"])).issubset(
                    {key for key, value in statuses.items() if value == "succeeded"}
                ) for row in rows
            ):
                final_status = "blocked"
            else:
                final_status = "queued"
            self.store.set_workflow_status(workflow_id, final_status)
            return self.store.snapshot(workflow_id)
