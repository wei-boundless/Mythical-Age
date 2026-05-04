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
    "commit_failed",
    "user_aborted",
    "internal_error",
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
