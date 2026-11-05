"""Vendor-neutral contracts for Qudron's multi-agent fabric.

MCP is the tool protocol; A2A is the agent-to-agent task protocol; provider
adapters translate external lifecycle semantics into these stable contracts.
No provider is considered enabled merely because its adapter exists.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import re
import time
from typing import Any


class ExecutionMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    PIPELINE = "pipeline"
    SWARM = "swarm"
    MAP_REDUCE = "map_reduce"
    CONSENSUS = "consensus"
    HYBRID = "hybrid"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    BLOCKED = "blocked"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DataClass(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ResourceMode(str, Enum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class ResourceClaim:
    """A named resource that a task reads or mutates.

    Two readers may share a resource. A writer is exclusive. Use different
    branch/artifact namespaces for parallel speculative work.
    """
    resource: str
    mode: ResourceMode = ResourceMode.READ

    def __post_init__(self) -> None:
        if not self.resource or len(self.resource) > 240:
            raise ValueError("resource must contain 1-240 characters")


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    uri: str
    media_type: str = "application/octet-stream"
    sha256: str | None = None
    size_bytes: int | None = None
    revision: str | None = None
    created_by: str | None = None
    verified: bool = False

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.uri:
            raise ValueError("artifact_id and uri are required")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("size_bytes cannot be negative")
        if self.sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", self.sha256):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")


@dataclass(frozen=True)
class AgentDescriptor:
    """Stable role identity, independently of the model or machine running it."""
    agent_id: str
    display_name: str
    provider_id: str
    adapter: str
    skills: tuple[str, ...] = ()
    modalities_in: tuple[str, ...] = ("text",)
    modalities_out: tuple[str, ...] = ("text",)
    supported_modes: tuple[str, ...] = tuple(m.value for m in ExecutionMode)
    accepted_data_classes: tuple[str, ...] = (DataClass.PUBLIC.value, DataClass.INTERNAL.value)
    max_concurrency: int = 1
    quality_score: float = 0.0
    access_mode: str = "unverified"
    price_class: str = "unknown"
    enabled: bool = False
    last_verified_at: float | None = None
    health: str = "unknown"
    endpoint_ref: str | None = None
    remote_agent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.agent_id or not self.provider_id or not self.adapter:
            raise ValueError("agent_id, provider_id, and adapter are required")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("quality_score must be between 0 and 1")


@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    project_id: str
    idempotency_key: str
    title: str
    instruction: str
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    parent_task_id: str | None = None
    correlation_id: str | None = None
    dependencies: tuple[str, ...] = ()
    required_skills: tuple[str, ...] = ()
    required_modalities: tuple[str, ...] = ("text",)
    data_class: DataClass = DataClass.PUBLIC
    resource_claims: tuple[ResourceClaim, ...] = ()
    input_artifacts: tuple[ArtifactRef, ...] = ()
    risk_level: str = "low"
    requires_approval: bool = False
    approved_by: str | None = None
    retry_safe: bool = True
    max_attempts: int = 3
    deadline_epoch: float | None = None
    context: dict[str, Any] = field(default_factory=dict)
    created_at_epoch: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.task_id or not self.project_id or not self.idempotency_key:
            raise ValueError("task_id, project_id and idempotency_key are required")
        if not self.title.strip() or not self.instruction.strip():
            raise ValueError("title and instruction cannot be empty")
        if len(self.instruction) > 50_000:
            raise ValueError("instruction exceeds the 50,000-character limit")
        if self.max_attempts < 1 or self.max_attempts > 10:
            raise ValueError("max_attempts must be between 1 and 10")
        if self.requires_approval and self.approved_by:
            # Approval is explicit metadata; callers should set this only after
            # the approval record has been persisted by the approval service.
            if len(self.approved_by) > 160:
                raise ValueError("approved_by is too long")

    @property
    def approved(self) -> bool:
        return not self.requires_approval or bool(self.approved_by)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["execution_mode"] = self.execution_mode.value
        data["data_class"] = self.data_class.value
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TaskEnvelope":
        data = dict(raw)
        data["execution_mode"] = ExecutionMode(data.get("execution_mode", "sequential"))
        data["data_class"] = DataClass(data.get("data_class", "public"))
        data["dependencies"] = tuple(data.get("dependencies", ()))
        data["required_skills"] = tuple(data.get("required_skills", ()))
        data["required_modalities"] = tuple(data.get("required_modalities", ("text",)))
        data["resource_claims"] = tuple(
            ResourceClaim(
                resource=item["resource"],
                mode=ResourceMode(item.get("mode", "read")),
            )
            for item in data.get("resource_claims", ())
        )
        data["input_artifacts"] = tuple(
            ArtifactRef(**item) for item in data.get("input_artifacts", ())
        )
        return cls(**data)


@dataclass(frozen=True)
class AgentTaskHandle:
    provider_id: str
    remote_task_id: str
    status: TaskStatus
    task_url: str | None = None
    submitted_at_epoch: float = field(default_factory=time.time)
    last_event_id: str | None = None
    cursor: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentTaskResult:
    provider_id: str
    remote_task_id: str
    status: TaskStatus
    summary: str = ""
    artifacts: tuple[ArtifactRef, ...] = ()
    progress: float | None = None
    needs_input: bool = False
    input_prompt: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.progress is not None and not 0.0 <= self.progress <= 1.0:
            raise ValueError("progress must be between 0 and 1")


def stable_idempotency_key(project_id: str, task_id: str, stage: str) -> str:
    """Stable key for retries and duplicate submissions of the same stage."""
    raw = "\x1f".join((project_id, task_id, stage))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
