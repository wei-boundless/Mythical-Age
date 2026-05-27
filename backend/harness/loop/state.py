from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.shared.models import RuntimeTerminalReason, RuntimeTransition, TaskRunStatus


@dataclass(frozen=True, slots=True)
class HarnessLoopState:
    """Serializable state for one Harness loop lifecycle."""

    task_run_id: str
    status: TaskRunStatus = "created"
    turn_count: int = 0
    step_count: int = 0
    current_step_id: str = ""
    agent_id: str = "agent:0"
    agent_profile_id: str = "main_interactive_agent"
    runtime_lane: str = "standard_task"
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
    authority: str = "harness.loop_state"

    def __post_init__(self) -> None:
        if self.authority not in {"harness.loop_state", "runtime_state"}:
            raise ValueError("HarnessLoopState authority must be harness.loop_state")
        if self.authority == "runtime_state":
            object.__setattr__(self, "authority", "harness.loop_state")
        if not self.task_run_id:
            raise ValueError("HarnessLoopState requires task_run_id")
        if self.terminal_reason and self.status not in {"waiting_approval", "blocked", "completed", "failed", "aborted"}:
            raise ValueError("terminal_reason requires a terminal or waiting status")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pending_action_requests"] = [dict(item) for item in self.pending_action_requests]
        payload["result_refs"] = list(self.result_refs)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, task_run_id: str = "") -> "HarnessLoopState":
        state_payload = dict(payload or {})
        return cls(
            task_run_id=str(state_payload.get("task_run_id") or task_run_id),
            status=state_payload.get("status", "created"),
            turn_count=int(state_payload.get("turn_count") or 0),
            step_count=int(state_payload.get("step_count") or 0),
            current_step_id=str(state_payload.get("current_step_id") or ""),
            agent_id=str(state_payload.get("agent_id") or "agent:0"),
            agent_profile_id=str(state_payload.get("agent_profile_id") or "main_interactive_agent"),
            runtime_lane=str(state_payload.get("runtime_lane") or "standard_task"),
            task_agent_binding_ref=str(state_payload.get("task_agent_binding_ref") or ""),
            task_template_id=str(state_payload.get("task_template_id") or ""),
            task_spec_ref=str(state_payload.get("task_spec_ref") or ""),
            task_result_ref=str(state_payload.get("task_result_ref") or ""),
            skill_workflow_ref=str(state_payload.get("skill_workflow_ref") or ""),
            health_issue_ref=str(state_payload.get("health_issue_ref") or ""),
            transition=state_payload.get("transition", "start"),
            terminal_reason=state_payload.get("terminal_reason", ""),
            messages_ref=str(state_payload.get("messages_ref") or ""),
            context_snapshot_ref=str(state_payload.get("context_snapshot_ref") or ""),
            memory_state_ref=str(state_payload.get("memory_state_ref") or ""),
            projection_ref=str(state_payload.get("projection_ref") or ""),
            prompt_manifest_ref=str(state_payload.get("prompt_manifest_ref") or ""),
            pending_action_requests=tuple(state_payload.get("pending_action_requests") or ()),
            pending_approval_state=dict(state_payload.get("pending_approval_state") or {}),
            denial_tracking_state=dict(state_payload.get("denial_tracking_state") or {}),
            token_pressure=dict(state_payload.get("token_pressure") or {}),
            compaction_state=dict(state_payload.get("compaction_state") or {}),
            result_refs=tuple(state_payload.get("result_refs") or ()),
            commit_state=dict(state_payload.get("commit_state") or {}),
            diagnostics=dict(state_payload.get("diagnostics") or {}),
            authority=str(state_payload.get("authority") or "harness.loop_state"),
        )

    def with_status(
        self,
        status: TaskRunStatus,
        *,
        transition: RuntimeTransition | None = None,
        terminal_reason: RuntimeTerminalReason | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> "HarnessLoopState":
        merged_diagnostics = dict(self.diagnostics)
        if diagnostics:
            merged_diagnostics.update(diagnostics)
        return HarnessLoopState(
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


