from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .common import clean_payload, require, require_authority, tuple_of_dicts, tuple_of_strings


TaskSourceKind = Literal["explicit_requirement", "agent_derived"]
TaskDispatchKind = Literal[
    "order_dispatch",
    "agent_dispatch",
    "graph_node_dispatch",
    "human_dispatch",
    "system_dispatch",
]
TaskActivationStatus = Literal["requested", "accepted", "needs_confirmation", "rejected"]


@dataclass(frozen=True, slots=True)
class AgentWorkLifecycleIntent:
    """Agent semantic intent to open an independent work lifecycle."""

    intent_id: str
    parent_task_id: str
    objective: str
    reason: str
    environment_hint: str = ""
    working_objects: tuple[dict[str, Any], ...] = ()
    input_refs: tuple[dict[str, Any], ...] = ()
    expected_output: dict[str, Any] = field(default_factory=dict)
    acceptance_hint: dict[str, Any] = field(default_factory=dict)
    capability_needs: dict[str, Any] = field(default_factory=dict)
    lifecycle_need: tuple[str, ...] = ()
    risk_or_side_effects: dict[str, Any] = field(default_factory=dict)
    relation_to_parent: str = "within_scope"
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.agent_work_lifecycle_intent"

    def __post_init__(self) -> None:
        require_authority(self.authority, "task_system.agent_work_lifecycle_intent", "AgentWorkLifecycleIntent")
        require(self.intent_id, "AgentWorkLifecycleIntent requires intent_id")
        require(self.objective, "AgentWorkLifecycleIntent requires objective")
        require(self.reason, "AgentWorkLifecycleIntent requires reason")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["working_objects"] = [dict(item) for item in self.working_objects]
        payload["input_refs"] = [dict(item) for item in self.input_refs]
        payload["lifecycle_need"] = list(self.lifecycle_need)
        return payload


@dataclass(frozen=True, slots=True)
class TaskActivationRequest:
    """Request to open a task lifecycle inside a TaskEnvironment."""

    activation_id: str
    session_id: str
    source: TaskSourceKind
    dispatch: TaskDispatchKind
    objective: str
    environment_id: str = ""
    environment_hint: str = ""
    parent_task_id: str = ""
    source_ref: str = ""
    dispatch_ref: str = ""
    working_objects: tuple[dict[str, Any], ...] = ()
    input_refs: tuple[dict[str, Any], ...] = ()
    resource_needs: dict[str, Any] = field(default_factory=dict)
    capability_needs: dict[str, Any] = field(default_factory=dict)
    expected_output: dict[str, Any] = field(default_factory=dict)
    acceptance_hint: dict[str, Any] = field(default_factory=dict)
    lifecycle_need: tuple[str, ...] = ()
    risk_or_side_effects: dict[str, Any] = field(default_factory=dict)
    relation_to_parent: str = "within_scope"
    status: TaskActivationStatus = "requested"
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_activation_request"

    def __post_init__(self) -> None:
        require_authority(self.authority, "task_system.task_activation_request", "TaskActivationRequest")
        require(self.activation_id, "TaskActivationRequest requires activation_id")
        require(self.session_id, "TaskActivationRequest requires session_id")
        require(self.objective, "TaskActivationRequest requires objective")
        if self.source not in {"explicit_requirement", "agent_derived"}:
            raise ValueError(f"invalid task activation source: {self.source}")
        if self.dispatch not in {
            "order_dispatch",
            "agent_dispatch",
            "graph_node_dispatch",
            "human_dispatch",
            "system_dispatch",
        }:
            raise ValueError(f"invalid task activation dispatch: {self.dispatch}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["working_objects"] = [dict(item) for item in self.working_objects]
        payload["input_refs"] = [dict(item) for item in self.input_refs]
        payload["lifecycle_need"] = list(self.lifecycle_need)
        return payload


def agent_work_lifecycle_intent_from_dict(payload: dict[str, Any]) -> AgentWorkLifecycleIntent:
    cleaned = clean_payload(payload, AgentWorkLifecycleIntent)
    cleaned["working_objects"] = tuple_of_dicts(cleaned.get("working_objects"))
    cleaned["input_refs"] = tuple_of_dicts(cleaned.get("input_refs"))
    cleaned["lifecycle_need"] = tuple_of_strings(cleaned.get("lifecycle_need"))
    return AgentWorkLifecycleIntent(**cleaned)


def task_activation_request_from_dict(payload: dict[str, Any]) -> TaskActivationRequest:
    cleaned = clean_payload(payload, TaskActivationRequest)
    cleaned["working_objects"] = tuple_of_dicts(cleaned.get("working_objects"))
    cleaned["input_refs"] = tuple_of_dicts(cleaned.get("input_refs"))
    cleaned["lifecycle_need"] = tuple_of_strings(cleaned.get("lifecycle_need"))
    return TaskActivationRequest(**cleaned)
