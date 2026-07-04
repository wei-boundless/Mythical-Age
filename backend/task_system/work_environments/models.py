from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TaskInstanceStatus = Literal["draft", "active", "paused", "waiting_user", "waiting_external", "completed", "failed", "aborted", "archived"]
TaskEnvironmentStatus = Literal["created", "ready", "leased", "paused", "blocked", "completed", "failed", "aborted", "archived"]
TaskPlanStatus = Literal["proposed", "active", "revised", "superseded", "completed"]
TaskTodoStatus = Literal["pending", "active", "blocked", "done", "canceled"]
TaskLeaseStatus = Literal["active", "released", "expired", "revoked"]
TaskControlSignalKind = Literal[
    "pause_requested",
    "stop_requested",
    "abort_requested",
    "resume_requested",
    "replan_requested",
    "instruction_appended",
]
TaskControlSignalStatus = Literal["pending", "handled", "canceled", "failed"]


@dataclass(frozen=True, slots=True)
class TaskInstance:
    task_instance_id: str
    task_kind: str
    title: str
    goal: str
    status: TaskInstanceStatus = "draft"
    owner_agent_id: str = ""
    owner_user_id: str = ""
    project_id: str = ""
    workspace_view: str = ""
    priority: str = "normal"
    acceptance_contract_ref: str = ""
    root_task_environment_id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    archived_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_instance"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.task_instance", "TaskInstance")
        _require_text(self.task_instance_id, "TaskInstance requires task_instance_id")
        _require_text(self.task_kind, "TaskInstance requires task_kind")
        _require_text(self.title, "TaskInstance requires title")
        _require_text(self.goal, "TaskInstance requires goal")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskInstance":
        data = dict(payload or {})
        return cls(
            task_instance_id=str(data.get("task_instance_id") or ""),
            task_kind=str(data.get("task_kind") or ""),
            title=str(data.get("title") or ""),
            goal=str(data.get("goal") or ""),
            status=str(data.get("status") or "draft"),  # type: ignore[arg-type]
            owner_agent_id=str(data.get("owner_agent_id") or ""),
            owner_user_id=str(data.get("owner_user_id") or ""),
            project_id=str(data.get("project_id") or ""),
            workspace_view=str(data.get("workspace_view") or ""),
            priority=str(data.get("priority") or "normal"),
            acceptance_contract_ref=str(data.get("acceptance_contract_ref") or ""),
            root_task_environment_id=str(data.get("root_task_environment_id") or ""),
            created_at=_float(data.get("created_at")),
            updated_at=_float(data.get("updated_at")),
            archived_at=_float(data.get("archived_at")),
            metadata=dict(data.get("metadata") or {}),
            authority=str(data.get("authority") or "task_system.task_instance"),
        )


@dataclass(frozen=True, slots=True)
class TaskWorkEnvironment:
    task_environment_id: str
    task_instance_id: str
    environment_kind: str
    caller_kind: str
    status: TaskEnvironmentStatus = "created"
    revision: int = 0
    current_phase: str = ""
    current_step: str = ""
    progress_current: int = 0
    progress_total: int = 0
    progress_label: str = ""
    active_episode_id: str = ""
    active_lease_id: str = ""
    latest_event_id: str = ""
    latest_checkpoint_id: str = ""
    latest_context_package_id: str = ""
    latest_work_product_id: str = ""
    continuation_hint: str = ""
    blocked_reason: str = ""
    recovery_action: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_environment"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.task_environment", "TaskWorkEnvironment")
        _require_text(self.task_environment_id, "TaskWorkEnvironment requires task_environment_id")
        _require_text(self.task_instance_id, "TaskWorkEnvironment requires task_instance_id")
        _require_text(self.environment_kind, "TaskWorkEnvironment requires environment_kind")
        _require_text(self.caller_kind, "TaskWorkEnvironment requires caller_kind")
        if self.progress_current < 0 or self.progress_total < 0:
            raise ValueError("TaskWorkEnvironment progress values must be non-negative")
        if self.progress_total and self.progress_current > self.progress_total:
            raise ValueError("TaskWorkEnvironment progress_current cannot exceed progress_total")
        if self.status == "leased" and not self.active_lease_id:
            raise ValueError("leased TaskWorkEnvironment requires active_lease_id")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskWorkEnvironment":
        data = dict(payload or {})
        return cls(
            task_environment_id=str(data.get("task_environment_id") or ""),
            task_instance_id=str(data.get("task_instance_id") or ""),
            environment_kind=str(data.get("environment_kind") or ""),
            caller_kind=str(data.get("caller_kind") or ""),
            status=str(data.get("status") or "created"),  # type: ignore[arg-type]
            revision=_int(data.get("revision")),
            current_phase=str(data.get("current_phase") or ""),
            current_step=str(data.get("current_step") or ""),
            progress_current=_int(data.get("progress_current")),
            progress_total=_int(data.get("progress_total")),
            progress_label=str(data.get("progress_label") or ""),
            active_episode_id=str(data.get("active_episode_id") or ""),
            active_lease_id=str(data.get("active_lease_id") or ""),
            latest_event_id=str(data.get("latest_event_id") or ""),
            latest_checkpoint_id=str(data.get("latest_checkpoint_id") or ""),
            latest_context_package_id=str(data.get("latest_context_package_id") or ""),
            latest_work_product_id=str(data.get("latest_work_product_id") or ""),
            continuation_hint=str(data.get("continuation_hint") or ""),
            blocked_reason=str(data.get("blocked_reason") or ""),
            recovery_action=str(data.get("recovery_action") or ""),
            created_at=_float(data.get("created_at")),
            updated_at=_float(data.get("updated_at")),
            metadata=dict(data.get("metadata") or {}),
            authority=str(data.get("authority") or "task_system.task_environment"),
        )


@dataclass(frozen=True, slots=True)
class TaskEvent:
    event_id: str
    task_environment_id: str
    task_instance_id: str
    event_seq: int
    event_type: str
    actor_kind: str
    actor_id: str = ""
    source_episode_id: str = ""
    source_graph_run_id: str = ""
    source_work_order_id: str = ""
    idempotency_key: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "task_system.task_event"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.task_event", "TaskEvent")
        _require_text(self.event_id, "TaskEvent requires event_id")
        _require_text(self.task_environment_id, "TaskEvent requires task_environment_id")
        _require_text(self.task_instance_id, "TaskEvent requires task_instance_id")
        _require_text(self.event_type, "TaskEvent requires event_type")
        _require_text(self.actor_kind, "TaskEvent requires actor_kind")
        if self.event_seq < 0:
            raise ValueError("TaskEvent event_seq must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskEvent":
        data = dict(payload or {})
        return cls(
            event_id=str(data.get("event_id") or ""),
            task_environment_id=str(data.get("task_environment_id") or ""),
            task_instance_id=str(data.get("task_instance_id") or ""),
            event_seq=_int(data.get("event_seq")),
            event_type=str(data.get("event_type") or ""),
            actor_kind=str(data.get("actor_kind") or ""),
            actor_id=str(data.get("actor_id") or ""),
            source_episode_id=str(data.get("source_episode_id") or ""),
            source_graph_run_id=str(data.get("source_graph_run_id") or ""),
            source_work_order_id=str(data.get("source_work_order_id") or ""),
            idempotency_key=str(data.get("idempotency_key") or ""),
            payload=dict(data.get("payload") or {}),
            refs=dict(data.get("refs") or {}),
            created_at=_float(data.get("created_at")),
            authority=str(data.get("authority") or "task_system.task_event"),
        )


@dataclass(frozen=True, slots=True)
class TaskPlan:
    plan_id: str
    task_environment_id: str
    version: int
    status: TaskPlanStatus = "proposed"
    strategy_summary: str = ""
    phases: tuple[dict[str, Any], ...] = ()
    acceptance_mapping: dict[str, Any] = field(default_factory=dict)
    risk_notes: tuple[str, ...] = ()
    created_by_episode_id: str = ""
    supersedes_plan_id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_plan"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.task_plan", "TaskPlan")
        _require_text(self.plan_id, "TaskPlan requires plan_id")
        _require_text(self.task_environment_id, "TaskPlan requires task_environment_id")
        if self.version < 1:
            raise ValueError("TaskPlan version must be positive")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["phases"] = [dict(item) for item in self.phases]
        payload["risk_notes"] = list(self.risk_notes)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class TaskTodoItem:
    todo_id: str
    task_environment_id: str
    title: str
    status: TaskTodoStatus = "pending"
    plan_id: str = ""
    evidence_refs: tuple[str, ...] = ()
    blocker: str = ""
    created_by_episode_id: str = ""
    completed_by_episode_id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_todo_item"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.task_todo_item", "TaskTodoItem")
        _require_text(self.todo_id, "TaskTodoItem requires todo_id")
        _require_text(self.task_environment_id, "TaskTodoItem requires task_environment_id")
        _require_text(self.title, "TaskTodoItem requires title")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class SessionTaskBinding:
    binding_id: str
    session_id: str
    task_environment_id: str
    task_instance_id: str
    binding_kind: str = "origin"
    control_role: str = "controller"
    visibility: str = "foreground"
    created_from_turn_id: str = ""
    last_focused_at: float = 0.0
    last_user_steer_ref: str = ""
    status: str = "active"
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.session_task_binding"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.session_task_binding", "SessionTaskBinding")
        _require_text(self.binding_id, "SessionTaskBinding requires binding_id")
        _require_text(self.session_id, "SessionTaskBinding requires session_id")
        _require_text(self.task_environment_id, "SessionTaskBinding requires task_environment_id")
        _require_text(self.task_instance_id, "SessionTaskBinding requires task_instance_id")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class TaskEnvironmentLease:
    lease_id: str
    task_environment_id: str
    episode_id: str
    lease_kind: str
    holder_kind: str
    holder_id: str
    status: TaskLeaseStatus = "active"
    acquired_at: float = 0.0
    expires_at: float = 0.0
    heartbeat_at: float = 0.0
    released_at: float = 0.0
    release_reason: str = ""
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_environment_lease"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.task_environment_lease", "TaskEnvironmentLease")
        _require_text(self.lease_id, "TaskEnvironmentLease requires lease_id")
        _require_text(self.task_environment_id, "TaskEnvironmentLease requires task_environment_id")
        _require_text(self.episode_id, "TaskEnvironmentLease requires episode_id")
        _require_text(self.lease_kind, "TaskEnvironmentLease requires lease_kind")
        _require_text(self.holder_kind, "TaskEnvironmentLease requires holder_kind")
        _require_text(self.holder_id, "TaskEnvironmentLease requires holder_id")
        _require_text(self.idempotency_key, "TaskEnvironmentLease requires idempotency_key")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class TaskContextPackage:
    package_id: str
    task_environment_id: str
    episode_id: str
    package_hash: str
    role_contract: str = ""
    goal: str = ""
    scope: dict[str, Any] = field(default_factory=dict)
    acceptance: dict[str, Any] = field(default_factory=dict)
    stable_context_ref: str = ""
    current_context_ref: str = ""
    memory_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    resource_handles: dict[str, Any] = field(default_factory=dict)
    graph_context: dict[str, Any] = field(default_factory=dict)
    project_network_handles: dict[str, Any] = field(default_factory=dict)
    continuation_hint: str = ""
    output_contract: dict[str, Any] = field(default_factory=dict)
    packet_policy: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_context_package"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.task_context_package", "TaskContextPackage")
        _require_text(self.package_id, "TaskContextPackage requires package_id")
        _require_text(self.task_environment_id, "TaskContextPackage requires task_environment_id")
        _require_text(self.episode_id, "TaskContextPackage requires episode_id")
        _require_text(self.package_hash, "TaskContextPackage requires package_hash")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["memory_refs"] = list(self.memory_refs)
        payload["artifact_refs"] = list(self.artifact_refs)
        return _drop_empty(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskContextPackage":
        data = dict(payload or {})
        return cls(
            package_id=str(data.get("package_id") or ""),
            task_environment_id=str(data.get("task_environment_id") or ""),
            episode_id=str(data.get("episode_id") or ""),
            package_hash=str(data.get("package_hash") or ""),
            role_contract=str(data.get("role_contract") or ""),
            goal=str(data.get("goal") or ""),
            scope=dict(data.get("scope") or {}),
            acceptance=dict(data.get("acceptance") or {}),
            stable_context_ref=str(data.get("stable_context_ref") or ""),
            current_context_ref=str(data.get("current_context_ref") or ""),
            memory_refs=_tuple_of_strings(data.get("memory_refs")),
            artifact_refs=_tuple_of_strings(data.get("artifact_refs")),
            resource_handles=dict(data.get("resource_handles") or {}),
            graph_context=dict(data.get("graph_context") or {}),
            project_network_handles=dict(data.get("project_network_handles") or {}),
            continuation_hint=str(data.get("continuation_hint") or ""),
            output_contract=dict(data.get("output_contract") or {}),
            packet_policy=dict(data.get("packet_policy") or {}),
            created_at=_float(data.get("created_at")),
            metadata=dict(data.get("metadata") or {}),
            authority=str(data.get("authority") or "task_system.task_context_package"),
        )


@dataclass(frozen=True, slots=True)
class TaskControlSignal:
    signal_id: str
    task_environment_id: str
    signal_kind: TaskControlSignalKind
    requested_by: str
    status: TaskControlSignalStatus = "pending"
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    handled_at: float = 0.0
    handler_episode_id: str = ""
    idempotency_key: str = ""
    authority: str = "task_system.task_control_signal"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.task_control_signal", "TaskControlSignal")
        _require_text(self.signal_id, "TaskControlSignal requires signal_id")
        _require_text(self.task_environment_id, "TaskControlSignal requires task_environment_id")
        _require_text(self.signal_kind, "TaskControlSignal requires signal_kind")
        _require_text(self.requested_by, "TaskControlSignal requires requested_by")
        _require_text(self.idempotency_key, "TaskControlSignal requires idempotency_key")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


def stable_task_environment_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    return f"{str(prefix or 'taskenv').strip() or 'taskenv'}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:20]}"


def context_package_hash(payload: Any) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")


def _require_authority(value: str, expected: str, label: str) -> None:
    if value != expected:
        raise ValueError(f"{label} authority must be {expected}")


def _require_text(value: str, message: str) -> None:
    if not str(value or "").strip():
        raise ValueError(message)


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace(",", "\n").splitlines() if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
