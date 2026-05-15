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
    "artifact_validation_failed",
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


@dataclass(frozen=True, slots=True)
class AgentDispatchRecord:
    """Scheduling record for a graph node before concrete model execution."""

    dispatch_id: str
    task_run_id: str
    coordination_run_id: str
    node_id: str
    node_run_id: str = ""
    agent_id: str = ""
    agent_run_id: str = ""
    execution_mode: str = "sync"
    dispatch_group: str = ""
    wait_policy: str = "wait_all_upstream_completed"
    join_policy: str = "all_success"
    status: str = "pending"
    blocks_downstream: bool = True
    background_policy: dict[str, Any] = field(default_factory=dict)
    notification_policy: dict[str, Any] = field(default_factory=dict)
    resource_lifecycle_policy: dict[str, Any] = field(default_factory=dict)
    upstream_node_ids: tuple[str, ...] = ()
    downstream_node_ids: tuple[str, ...] = ()
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.agent_dispatch_record"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.agent_dispatch_record":
            raise ValueError("AgentDispatchRecord authority must be orchestration.agent_dispatch_record")
        if not self.dispatch_id:
            raise ValueError("AgentDispatchRecord requires dispatch_id")
        if not self.task_run_id:
            raise ValueError("AgentDispatchRecord requires task_run_id")
        if not self.coordination_run_id:
            raise ValueError("AgentDispatchRecord requires coordination_run_id")
        if not self.node_id:
            raise ValueError("AgentDispatchRecord requires node_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["upstream_node_ids"] = list(self.upstream_node_ids)
        payload["downstream_node_ids"] = list(self.downstream_node_ids)
        return payload


@dataclass(frozen=True, slots=True)
class CoordinationBarrierState:
    """Join state for a barrier or grouped dispatch."""

    barrier_id: str
    task_run_id: str
    coordination_run_id: str
    node_id: str
    join_policy: str = "all_success"
    waiting_for_node_ids: tuple[str, ...] = ()
    completed_node_ids: tuple[str, ...] = ()
    failed_node_ids: tuple[str, ...] = ()
    status: str = "waiting"
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.coordination_barrier_state"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.coordination_barrier_state":
            raise ValueError("CoordinationBarrierState authority must be orchestration.coordination_barrier_state")
        if not self.barrier_id:
            raise ValueError("CoordinationBarrierState requires barrier_id")
        if not self.task_run_id:
            raise ValueError("CoordinationBarrierState requires task_run_id")
        if not self.coordination_run_id:
            raise ValueError("CoordinationBarrierState requires coordination_run_id")
        if not self.node_id:
            raise ValueError("CoordinationBarrierState requires node_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["waiting_for_node_ids"] = list(self.waiting_for_node_ids)
        payload["completed_node_ids"] = list(self.completed_node_ids)
        payload["failed_node_ids"] = list(self.failed_node_ids)
        return payload


@dataclass(frozen=True, slots=True)
class QueuedAgentNotification:
    """Control-plane notification queued after runtime state is updated."""

    notification_id: str
    task_run_id: str
    coordination_run_id: str = ""
    node_id: str = ""
    agent_run_id: str = ""
    event: str = "completed"
    priority: str = "later"
    include_result: str = "summary_and_refs"
    status: str = "queued"
    payload_ref: str = ""
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.queued_agent_notification"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.queued_agent_notification":
            raise ValueError("QueuedAgentNotification authority must be orchestration.queued_agent_notification")
        if not self.notification_id:
            raise ValueError("QueuedAgentNotification requires notification_id")
        if not self.task_run_id:
            raise ValueError("QueuedAgentNotification requires task_run_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentDispatchPlan:
    """Compiled scheduling plan consumed by RunLoop and checkpoint diagnostics."""

    dispatch_plan_id: str
    task_run_id: str
    coordination_run_id: str
    records: tuple[AgentDispatchRecord, ...] = ()
    barrier_states: tuple[CoordinationBarrierState, ...] = ()
    queued_notifications: tuple[QueuedAgentNotification, ...] = ()
    ready_node_ids: tuple[str, ...] = ()
    blocked_node_ids: tuple[str, ...] = ()
    background_node_ids: tuple[str, ...] = ()
    dispatch_groups: dict[str, list[str]] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.agent_dispatch_plan"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.agent_dispatch_plan":
            raise ValueError("AgentDispatchPlan authority must be orchestration.agent_dispatch_plan")
        if not self.dispatch_plan_id:
            raise ValueError("AgentDispatchPlan requires dispatch_plan_id")
        if not self.task_run_id:
            raise ValueError("AgentDispatchPlan requires task_run_id")
        if not self.coordination_run_id:
            raise ValueError("AgentDispatchPlan requires coordination_run_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["records"] = [item.to_dict() for item in self.records]
        payload["barrier_states"] = [item.to_dict() for item in self.barrier_states]
        payload["queued_notifications"] = [item.to_dict() for item in self.queued_notifications]
        payload["ready_node_ids"] = list(self.ready_node_ids)
        payload["blocked_node_ids"] = list(self.blocked_node_ids)
        payload["background_node_ids"] = list(self.background_node_ids)
        payload["dispatch_groups"] = {str(key): list(value) for key, value in self.dispatch_groups.items()}
        return payload


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
    runtime_lane: str = "full_interactive"
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
    spawn_mode: str = "adopt_existing"
    context_scope: str = "task_default"
    runtime_lane: str = "full_interactive"
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
class RuntimeLoopState:
    """Serializable state for the current while-loop iteration."""

    task_run_id: str
    status: TaskRunStatus = "created"
    turn_count: int = 0
    step_count: int = 0
    current_step_id: str = ""
    agent_id: str = "agent:0"
    agent_profile_id: str = "main_interactive_agent"
    runtime_lane: str = "full_interactive"
    task_agent_binding_ref: str = ""
    task_template_id: str = ""
    task_spec_ref: str = ""
    task_result_ref: str = ""
    skill_workflow_ref: str = ""
    health_issue_ref: str = ""
    transition: RuntimeTransition = "start"
    terminal_reason: RuntimeTerminalReason = ""
    messages_ref: str = ""
    context_snapshot_ref: str = ""
    memory_state_ref: str = ""
    projection_ref: str = ""
    prompt_manifest_ref: str = ""
    pending_action_requests: tuple[dict[str, Any], ...] = ()
    pending_approval_state: dict[str, Any] = field(default_factory=dict)
    denial_tracking_state: dict[str, Any] = field(default_factory=dict)
    token_pressure: dict[str, Any] = field(default_factory=dict)
    compaction_state: dict[str, Any] = field(default_factory=dict)
    result_refs: tuple[str, ...] = ()
    commit_state: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.runtime_loop_state"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.runtime_loop_state":
            raise ValueError("RuntimeLoopState authority must be orchestration.runtime_loop_state")
        if not self.task_run_id:
            raise ValueError("RuntimeLoopState requires task_run_id")
        if self.terminal_reason and self.status not in {"waiting_approval", "blocked", "completed", "failed", "aborted"}:
            raise ValueError("terminal_reason requires a terminal or waiting status")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pending_action_requests"] = [dict(item) for item in self.pending_action_requests]
        payload["result_refs"] = list(self.result_refs)
        return payload

    def with_status(
        self,
        status: TaskRunStatus,
        *,
        transition: RuntimeTransition | None = None,
        terminal_reason: RuntimeTerminalReason | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> "RuntimeLoopState":
        merged_diagnostics = dict(self.diagnostics)
        if diagnostics:
            merged_diagnostics.update(diagnostics)
        return RuntimeLoopState(
            task_run_id=self.task_run_id,
            status=status,
            turn_count=self.turn_count,
            step_count=self.step_count,
            current_step_id=self.current_step_id,
            agent_id=self.agent_id,
            agent_profile_id=self.agent_profile_id,
            runtime_lane=self.runtime_lane,
            task_agent_binding_ref=self.task_agent_binding_ref,
            task_template_id=self.task_template_id,
            task_spec_ref=self.task_spec_ref,
            task_result_ref=self.task_result_ref,
            skill_workflow_ref=self.skill_workflow_ref,
            health_issue_ref=self.health_issue_ref,
            transition=transition or self.transition,
            terminal_reason=terminal_reason if terminal_reason is not None else self.terminal_reason,
            messages_ref=self.messages_ref,
            context_snapshot_ref=self.context_snapshot_ref,
            memory_state_ref=self.memory_state_ref,
            projection_ref=self.projection_ref,
            prompt_manifest_ref=self.prompt_manifest_ref,
            pending_action_requests=self.pending_action_requests,
            pending_approval_state=self.pending_approval_state,
            denial_tracking_state=self.denial_tracking_state,
            token_pressure=self.token_pressure,
            compaction_state=self.compaction_state,
            result_refs=self.result_refs,
            commit_state=self.commit_state,
            diagnostics=merged_diagnostics,
        )
