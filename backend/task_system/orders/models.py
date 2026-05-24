from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ConversationInteractionKind = Literal["chat_turn", "task_order_draft", "executable_task"]
TaskIntentDecisionKind = Literal["chat_turn", "task_order_draft", "executable_task"]
TaskOrderKind = Literal[
    "ad_hoc_task",
    "specific_task",
    "graph_run",
    "graph_node_task",
    "agent_spawn_task",
    "human_work",
    "subruntime_task",
]
TaskOrderStatus = Literal["drafted", "accepted", "running", "completed", "failed", "cancelled"]
TaskOrderRunStatus = Literal[
    "created",
    "running",
    "waiting_approval",
    "paused",
    "completed",
    "failed",
    "cancelled",
]
ExecutionChannelStatus = Literal[
    "created",
    "running",
    "waiting_approval",
    "paused",
    "completed",
    "failed",
    "cancelled",
]


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """A conversation turn is not a task order."""

    turn_id: str
    session_id: str
    user_message_ref: str = ""
    assistant_message_ref: str = ""
    interaction_kind: ConversationInteractionKind = "chat_turn"
    task_intent_decision_id: str = ""
    task_order_ref: str = ""
    created_at: float = 0.0
    status: str = "created"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "conversation.turn"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "conversation.turn", "ConversationTurn")
        _require(self.turn_id, "ConversationTurn requires turn_id")
        _require(self.session_id, "ConversationTurn requires session_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskIntentDecision:
    """Auditable decision that separates chat, draft, and executable task."""

    decision_id: str
    turn_id: str
    decision: TaskIntentDecisionKind
    confidence: float = 0.0
    hard_signals: tuple[str, ...] = ()
    contract_signals: tuple[str, ...] = ()
    weak_signals: tuple[str, ...] = ()
    evidence_spans: tuple[dict[str, Any], ...] = ()
    missing_fields: tuple[str, ...] = ()
    lifecycle_needs: tuple[str, ...] = ()
    created_order_id: str = ""
    reason: str = ""
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.intent_decision"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.intent_decision", "TaskIntentDecision")
        _require(self.decision_id, "TaskIntentDecision requires decision_id")
        _require(self.turn_id, "TaskIntentDecision requires turn_id")
        if self.decision not in {"chat_turn", "task_order_draft", "executable_task"}:
            raise ValueError(f"invalid task intent decision: {self.decision}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        _tuple_fields_to_lists(
            payload,
            "hard_signals",
            "contract_signals",
            "weak_signals",
            "evidence_spans",
            "missing_fields",
            "lifecycle_needs",
        )
        return payload


@dataclass(frozen=True, slots=True)
class TaskOrderDraft:
    """A task-like intent that lacks enough evidence to run."""

    draft_id: str
    turn_id: str
    session_id: str
    decision_id: str
    objective: str = ""
    candidate_order_kind: str = ""
    missing_fields: tuple[str, ...] = ()
    candidate_inputs: dict[str, Any] = field(default_factory=dict)
    status: str = "needs_confirmation"
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_order_draft"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.task_order_draft", "TaskOrderDraft")
        _require(self.draft_id, "TaskOrderDraft requires draft_id")
        _require(self.turn_id, "TaskOrderDraft requires turn_id")
        _require(self.session_id, "TaskOrderDraft requires session_id")
        _require(self.decision_id, "TaskOrderDraft requires decision_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        _tuple_fields_to_lists(payload, "missing_fields")
        return payload


@dataclass(frozen=True, slots=True)
class TaskOrder:
    """Accepted work contract and task initiation authority."""

    order_id: str
    session_id: str
    order_kind: TaskOrderKind
    source: str
    source_ref: str
    objective: str
    task_id: str = ""
    task_definition_ref: str = ""
    parent_order_id: str = ""
    parent_run_id: str = ""
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    role_contract: dict[str, Any] = field(default_factory=dict)
    acceptance_policy: dict[str, Any] = field(default_factory=dict)
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    executor_policy: dict[str, Any] = field(default_factory=dict)
    context_policy: dict[str, Any] = field(default_factory=dict)
    status: TaskOrderStatus = "accepted"
    idempotency_key: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_order"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.task_order", "TaskOrder")
        _require(self.order_id, "TaskOrder requires order_id")
        _require(self.session_id, "TaskOrder requires session_id")
        _require(self.source, "TaskOrder requires source")
        _require(self.source_ref, "TaskOrder requires source_ref")
        _require(self.objective, "TaskOrder requires objective")
        if self.order_kind == "chat_turn":
            raise ValueError("chat_turn is not a TaskOrder kind")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskOrderRun:
    """One supervised execution attempt for a TaskOrder."""

    run_id: str
    order_id: str
    session_id: str
    primary_execution_channel_id: str = ""
    task_run_id: str = ""
    coordination_run_id: str = ""
    executor_assignment: dict[str, Any] = field(default_factory=dict)
    status: TaskOrderRunStatus = "created"
    retry_of_run_id: str = ""
    supersedes_run_id: str = ""
    created_from_checkpoint_id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    terminal_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_order_run"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.task_order_run", "TaskOrderRun")
        _require(self.run_id, "TaskOrderRun requires run_id")
        _require(self.order_id, "TaskOrderRun requires order_id")
        _require(self.session_id, "TaskOrderRun requires session_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExecutionChannel:
    """Isolated execution channel instance for a TaskOrderRun."""

    channel_id: str
    order_run_id: str
    order_id: str
    session_id: str
    channel_kind: str = "single_agent"
    task_run_id: str = ""
    stream_binding: dict[str, Any] = field(default_factory=dict)
    artifact_scope: dict[str, Any] = field(default_factory=dict)
    memory_scope: dict[str, Any] = field(default_factory=dict)
    checkpoint_scope: dict[str, Any] = field(default_factory=dict)
    approval_gate_binding: dict[str, Any] = field(default_factory=dict)
    status: ExecutionChannelStatus = "created"
    created_at: float = 0.0
    updated_at: float = 0.0
    terminal_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.execution_channel"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.execution_channel", "ExecutionChannel")
        _require(self.channel_id, "ExecutionChannel requires channel_id")
        _require(self.order_run_id, "ExecutionChannel requires order_run_id")
        _require(self.order_id, "ExecutionChannel requires order_id")
        _require(self.session_id, "ExecutionChannel requires session_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskExecutionEnvelope:
    """Task-local invocation contract consumed by runtime assembly."""

    envelope_id: str
    order_id: str
    order_run_id: str
    execution_channel_id: str
    session_id: str
    role_contract: dict[str, Any] = field(default_factory=dict)
    responsibility_boundary: dict[str, Any] = field(default_factory=dict)
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    acceptance_policy: dict[str, Any] = field(default_factory=dict)
    executor_policy: dict[str, Any] = field(default_factory=dict)
    permission_ceiling: dict[str, Any] = field(default_factory=dict)
    context_package: dict[str, Any] = field(default_factory=dict)
    source_refs: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "task_system.task_execution_envelope"

    def __post_init__(self) -> None:
        _require_authority(self.authority, "task_system.task_execution_envelope", "TaskExecutionEnvelope")
        _require(self.envelope_id, "TaskExecutionEnvelope requires envelope_id")
        _require(self.order_id, "TaskExecutionEnvelope requires order_id")
        _require(self.order_run_id, "TaskExecutionEnvelope requires order_run_id")
        _require(self.execution_channel_id, "TaskExecutionEnvelope requires execution_channel_id")
        _require(self.session_id, "TaskExecutionEnvelope requires session_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def conversation_turn_from_dict(payload: dict[str, Any]) -> ConversationTurn:
    return ConversationTurn(**_clean_payload(payload, ConversationTurn))


def task_intent_decision_from_dict(payload: dict[str, Any]) -> TaskIntentDecision:
    cleaned = _clean_payload(payload, TaskIntentDecision)
    for key in ("hard_signals", "contract_signals", "weak_signals", "missing_fields", "lifecycle_needs"):
        cleaned[key] = tuple(str(item) for item in list(cleaned.get(key) or []) if str(item))
    cleaned["evidence_spans"] = tuple(dict(item) for item in list(cleaned.get("evidence_spans") or []) if isinstance(item, dict))
    return TaskIntentDecision(**cleaned)


def task_order_draft_from_dict(payload: dict[str, Any]) -> TaskOrderDraft:
    cleaned = _clean_payload(payload, TaskOrderDraft)
    cleaned["missing_fields"] = tuple(str(item) for item in list(cleaned.get("missing_fields") or []) if str(item))
    return TaskOrderDraft(**cleaned)


def task_order_from_dict(payload: dict[str, Any]) -> TaskOrder:
    return TaskOrder(**_clean_payload(payload, TaskOrder))


def task_order_run_from_dict(payload: dict[str, Any]) -> TaskOrderRun:
    return TaskOrderRun(**_clean_payload(payload, TaskOrderRun))


def execution_channel_from_dict(payload: dict[str, Any]) -> ExecutionChannel:
    return ExecutionChannel(**_clean_payload(payload, ExecutionChannel))


def task_execution_envelope_from_dict(payload: dict[str, Any]) -> TaskExecutionEnvelope:
    return TaskExecutionEnvelope(**_clean_payload(payload, TaskExecutionEnvelope))


def _clean_payload(payload: dict[str, Any], model: type[Any]) -> dict[str, Any]:
    allowed = set(getattr(model, "__dataclass_fields__", {}).keys())
    return {key: value for key, value in dict(payload or {}).items() if key in allowed}


def _require(value: str, message: str) -> None:
    if not str(value or "").strip():
        raise ValueError(message)


def _require_authority(actual: str, expected: str, model_name: str) -> None:
    if actual != expected:
        raise ValueError(f"{model_name} authority must be {expected}")


def _tuple_fields_to_lists(payload: dict[str, Any], *keys: str) -> None:
    for key in keys:
        payload[key] = list(payload.get(key) or [])
