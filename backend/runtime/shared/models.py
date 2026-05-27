from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TaskRunStatus = Literal[
    "created",
    "running",
    "waiting_approval",
    "blocked",
    "completed",
    "failed",
    "aborted",
]

RuntimeTransition = Literal[
    "start",
    "next_turn",
    "continue_after_model_result",
    "continue_after_tool_result",
    "continue_after_mcp_result",
    "continue_after_context_compaction",
    "continue_after_approval",
    "continue_after_recovery",
    "stop_after_final_output",
]

RuntimeTerminalReason = Literal[
    "",
    "completed",
    "waiting_approval",
    "blocked_by_gate",
    "budget_exhausted",
    "max_turns",
    "context_unrecoverable",
    "executor_failed",
    "model_response_timeout_after_partial_output",
    "artifact_validation_failed",
    "partially_completed",
    "partial_contract_failed",
    "tool_loop_budget_exceeded",
    "commit_failed",
    "user_aborted",
    "internal_error",
]

AgentRunStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "killed",
]

CoordinationRunStatus = Literal[
    "pending",
    "running",
    "waiting",
    "completed",
    "failed",
    "aborted",
    "killed",
]

ProjectRuntimeHealth = Literal[
    "healthy",
    "watching",
    "blocked",
    "failed",
    "repairing",
    "completed",
]


@dataclass(frozen=True, slots=True)
class TaskRun:
    """A durable single-agent task run owned by OrchestrationSystem."""

    task_run_id: str
    session_id: str
    task_id: str
    task_contract_ref: str = ""
    owner_agent_seat_id: str = "main"
    agent_id: str = "agent:0"
    agent_profile_id: str = "main_interactive_agent"
    runtime_lane: str = "standard_task"
    status: TaskRunStatus = "created"
    created_at: float = 0.0
    updated_at: float = 0.0
    latest_event_offset: int = -1
    latest_checkpoint_ref: str = ""
    terminal_reason: RuntimeTerminalReason = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.task_run"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.task_run":
            raise ValueError("TaskRun authority must be orchestration.task_run")
        if not self.task_run_id:
            raise ValueError("TaskRun requires task_run_id")
        if not self.session_id:
            raise ValueError("TaskRun requires session_id")
        if not self.task_id:
            raise ValueError("TaskRun requires task_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentRun:
    """Durable runtime object for a concrete agent execution instance."""

    agent_run_id: str
    task_run_id: str
    agent_id: str
    agent_profile_id: str
    role: str = "main_executor"
    spawn_mode: str = "single_agent"
    context_scope: str = "task_default"
    runtime_lane: str = "standard_task"
    parent_agent_run_ref: str = ""
    coordination_run_ref: str = ""
    status: AgentRunStatus = "pending"
    latest_checkpoint_ref: str = ""
    result_ref: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.agent_run"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.agent_run":
            raise ValueError("AgentRun authority must be orchestration.agent_run")
        if not self.agent_run_id:
            raise ValueError("AgentRun requires agent_run_id")
        if not self.task_run_id:
            raise ValueError("AgentRun requires task_run_id")
        if not self.agent_id:
            raise ValueError("AgentRun requires agent_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """Formal result object for an AgentRun."""

    agent_run_result_id: str
    agent_run_id: str
    task_run_id: str
    agent_id: str
    status: AgentRunStatus
    output_ref: str = ""
    summary: str = ""
    artifact_refs: tuple[str, ...] = ()
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.agent_run_result"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.agent_run_result":
            raise ValueError("AgentRunResult authority must be orchestration.agent_run_result")
        if not self.agent_run_result_id:
            raise ValueError("AgentRunResult requires agent_run_result_id")
        if not self.agent_run_id:
            raise ValueError("AgentRunResult requires agent_run_id")
        if not self.task_run_id:
            raise ValueError("AgentRunResult requires task_run_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_refs"] = list(self.artifact_refs)
        return payload


@dataclass(frozen=True, slots=True)
class CoordinationRun:
    """Formal runtime object for a multi-agent coordination session."""

    coordination_run_id: str
    task_run_id: str
    coordinator_agent_id: str
    graph_ref: str = ""
    topology_template_id: str = ""
    communication_protocol_id: str = ""
    handoff_policy: str = ""
    failure_policy: str = ""
    merge_policy: str = ""
    status: CoordinationRunStatus = "pending"
    latest_checkpoint_ref: str = ""
    latest_merge_result_ref: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.coordination_run"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.coordination_run":
            raise ValueError("CoordinationRun authority must be orchestration.coordination_run")
        if not self.coordination_run_id:
            raise ValueError("CoordinationRun requires coordination_run_id")
        if not self.task_run_id:
            raise ValueError("CoordinationRun requires task_run_id")
        graph_ref = str(self.graph_ref or "").strip()
        if not graph_ref:
            raise ValueError("CoordinationRun requires graph_ref")
        object.__setattr__(self, "graph_ref", graph_ref)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["graph_ref"] = self.graph_ref
        return payload


@dataclass(frozen=True, slots=True)
class CoordinationNodeRun:
    """Runtime node execution inside a CoordinationRun."""

    node_run_id: str
    coordination_run_id: str
    task_run_id: str
    node_id: str
    role: str
    assigned_agent_id: str = ""
    assigned_agent_run_ref: str = ""
    status: CoordinationRunStatus = "pending"
    handoff_count: int = 0
    latest_handoff_ref: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.coordination_node_run"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.coordination_node_run":
            raise ValueError("CoordinationNodeRun authority must be orchestration.coordination_node_run")
        if not self.node_run_id:
            raise ValueError("CoordinationNodeRun requires node_run_id")
        if not self.coordination_run_id:
            raise ValueError("CoordinationNodeRun requires coordination_run_id")
        if not self.task_run_id:
            raise ValueError("CoordinationNodeRun requires task_run_id")
        if not self.node_id:
            raise ValueError("CoordinationNodeRun requires node_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentHandoffEnvelope:
    """Formal handoff payload exchanged between agent runs."""

    handoff_id: str
    task_run_id: str
    coordination_run_id: str
    source_agent_run_ref: str
    target_agent_run_ref: str
    protocol_id: str = ""
    message_type: str = ""
    payload_ref: str = ""
    ack_state: str = "pending"
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.agent_handoff_envelope"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.agent_handoff_envelope":
            raise ValueError("AgentHandoffEnvelope authority must be orchestration.agent_handoff_envelope")
        if not self.handoff_id:
            raise ValueError("AgentHandoffEnvelope requires handoff_id")
        if not self.task_run_id:
            raise ValueError("AgentHandoffEnvelope requires task_run_id")
        if not self.coordination_run_id:
            raise ValueError("AgentHandoffEnvelope requires coordination_run_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CoordinationMergeResult:
    """Formal final merge result for a CoordinationRun."""

    merge_result_id: str
    coordination_run_id: str
    task_run_id: str
    merge_policy: str
    final_result_ref: str = ""
    accepted: bool = False
    unresolved_issue_refs: tuple[str, ...] = ()
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.coordination_merge_result"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.coordination_merge_result":
            raise ValueError("CoordinationMergeResult authority must be orchestration.coordination_merge_result")
        if not self.merge_result_id:
            raise ValueError("CoordinationMergeResult requires merge_result_id")
        if not self.coordination_run_id:
            raise ValueError("CoordinationMergeResult requires coordination_run_id")
        if not self.task_run_id:
            raise ValueError("CoordinationMergeResult requires task_run_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["unresolved_issue_refs"] = list(self.unresolved_issue_refs)
        return payload


@dataclass(frozen=True, slots=True)
class ProjectProgressLedger:
    """Project-level progress truth source for long-running task campaigns."""

    ledger_id: str
    project_id: str
    session_id: str
    graph_id: str
    project_title: str = ""
    metric_label: str = "units"
    target_metric_total: int = 0
    committed_metric_total: int = 0
    committed_unit_count: int = 0
    last_committed_unit_index: int = 0
    committed_unit_refs: tuple[str, ...] = ()
    metric_receipts: tuple[dict[str, Any], ...] = ()
    run_chain: tuple[str, ...] = ()
    latest_delivery_state: str = ""
    last_failure: dict[str, Any] = field(default_factory=dict)
    last_repair_action: dict[str, Any] = field(default_factory=dict)
    updated_at: float = 0.0
    created_at: float = 0.0
    authority: str = "orchestration.project_progress_ledger"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.project_progress_ledger":
            raise ValueError("ProjectProgressLedger authority must be orchestration.project_progress_ledger")
        if not self.ledger_id:
            raise ValueError("ProjectProgressLedger requires ledger_id")
        if not self.project_id:
            raise ValueError("ProjectProgressLedger requires project_id")
        if not self.session_id:
            raise ValueError("ProjectProgressLedger requires session_id")
        if not self.graph_id:
            raise ValueError("ProjectProgressLedger requires graph_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["committed_unit_refs"] = list(self.committed_unit_refs)
        payload["metric_receipts"] = [dict(item) for item in self.metric_receipts]
        payload["run_chain"] = list(self.run_chain)
        return payload


@dataclass(frozen=True, slots=True)
class SupervisionRecord:
    """Structured supervision log for observed issues and repairs."""

    supervision_record_id: str
    supervision_session_id: str
    project_id: str
    observed_task_run_id: str = ""
    observed_coordination_run_id: str = ""
    issue_type: str = ""
    issue_summary: str = ""
    root_cause: str = ""
    repair_action: str = ""
    repair_result: str = ""
    followup_status: str = "recorded"
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.supervision_record"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.supervision_record":
            raise ValueError("SupervisionRecord authority must be orchestration.supervision_record")
        if not self.supervision_record_id:
            raise ValueError("SupervisionRecord requires supervision_record_id")
        if not self.supervision_session_id:
            raise ValueError("SupervisionRecord requires supervision_session_id")
        if not self.project_id:
            raise ValueError("SupervisionRecord requires project_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProjectRuntimeStatus:
    """Current runtime status view for a long-running project."""

    project_id: str
    session_id: str
    graph_id: str
    project_title: str = ""
    active_task_run_id: str = ""
    active_coordination_run_id: str = ""
    active_run_status: str = ""
    project_runtime_status: ProjectRuntimeHealth = "watching"
    metric_label: str = "units"
    completed_metric_total: int = 0
    target_metric_total: int = 0
    committed_unit_count: int = 0
    last_committed_unit_index: int = 0
    active_blocker: dict[str, Any] = field(default_factory=dict)
    recovery_state: dict[str, Any] = field(default_factory=dict)
    delivery_state: str = ""
    latest_artifact_root: str = ""
    latest_event_offset: int = 0
    latest_event_at: float = 0.0
    last_effective_output_at: float = 0.0
    updated_at: float = 0.0
    authority: str = "orchestration.project_runtime_status"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.project_runtime_status":
            raise ValueError("ProjectRuntimeStatus authority must be orchestration.project_runtime_status")
        if not self.project_id:
            raise ValueError("ProjectRuntimeStatus requires project_id")
        if not self.session_id:
            raise ValueError("ProjectRuntimeStatus requires session_id")
        if not self.graph_id:
            raise ValueError("ProjectRuntimeStatus requires graph_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
