from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RuntimeEventType = Literal[
    "task_run_started",
    "agent_run_created",
    "agent_run_updated",
    "agent_run_result_created",
    "worker_agent_spawn_requested",
    "worker_agent_spawn_completed",
    "loop_iteration_started",
    "loop_control_checked",
    "task_contract_built",
    "task_run_ledger_updated",
    "agent_turn_received",
    "runtime_invocation_packet_compiled",
    "model_action_request_received",
    "model_action_admission_checked",
    "bounded_observation_recorded",
    "task_run_lifecycle_started",
    "task_run_lifecycle_waiting_executor",
    "task_run_lifecycle_finished",
    "task_run_lifecycle_retention_stopped",
    "agent_todo_initialized",
    "turn_signals_built",
    "runtime_context_built",
    "agent_turn_action_request_started",
    "agent_turn_action_request_completed",
    "agent_turn_action_request_failed",
    "execution_decision_completed",
    "runtime_admission_checked",
    "runtime_admission_blocked",
    "direct_response_started",
    "direct_response_completed",
    "task_run_launch_requested",
    "task_run_launched",
    "task_run_terminal_observed",
    "agent_turn_closing",
    "agent_turn_completed",
    "agent_turn_clarification_required",
    "agent_turn_failed",
    "agent_turn_blocked",
    "step_added",
    "step_entered",
    "step_completed",
    "step_failed",
    "step_skipped",
    "step_summary_recorded",
    "memory_runtime_view_built",
    "working_memory_candidates_submitted",
    "working_memory_finalized",
    "current_turn_context_resolved",
    "continuation_binding_checked",
    "continuation_binding_selected",
    "continuation_binding_rejected",
    "context_snapshot_built",
    "context_invariant_checked",
    "stage_projection_built",
    "model_profile_resolved",
    "runtime_directive_issued",
    "operation_gate_checked",
    "executor_started",
    "assistant_text_delta",
    "assistant_text_final",
    "assistant_stream_repair",
    "model_stream_recovery",
    "model_item_received",
    "task_model_action_wait_heartbeat",
    "task_tool_observation_recorded",
    "turn_tool_observation_recorded",
    "executor_observation_received",
    "output_boundary_applied",
    "commit_gate_checked",
    "task_artifact_validation_checked",
    "checkpoint_written",
    "loop_terminal",
    "loop_error",
    "tool_call_requested",
    "tool_batch_planned",
    "tool_batch_group_started",
    "tool_batch_group_completed",
    "mcp_requested",
    "mcp_result_received",
    "context_compaction_requested",
    "context_compacted",
    "approval_waiting",
    "approval_resumed",
    "recovery_attempted",
    "execution_record_created",
    "execution_dispatch_started",
    "execution_result_recorded",
    "execution_result_reused",
    "replay_guard_triggered",
    "recovery_replay_decided",
    "runtime_state_index_degraded",
    "runtime_sandbox_prepared",
    "runtime_file_management_prepared",
    "agent_runtime_planning_phase_checked",
    "agent_runtime_closeout_phase_checked",
    "user_submission_recorded",
    "active_task_steer_recorded",
    "active_task_steer_included",
    "active_task_steer_consumed",
    "active_task_steer_rejected",
    "active_task_steer_superseded",
    "task_contract_revision_recorded",
    "task_contract_revision_decided",
    "task_run_executor_claimed",
    "task_run_executor_scheduled",
    "task_run_executor_rescheduled",
    "task_run_executor_recovered_after_runtime_start",
    "task_run_executor_schedule_failed",
    "task_run_executor_failed",
    "runtime_control_signal_published",
    "runtime_control_signal_observed",
    "runtime_control_signal_consumed",
    "runtime_evidence_projection_published",
    "agent_runtime_cell_created",
    "agent_runtime_cell_started",
    "agent_runtime_cell_start_failed",
    "agent_runtime_cell_completed",
    "agent_runtime_cell_failed",
    "agent_runtime_cell_cancel_requested",
    "agent_runtime_cell_cancelled",
    "agent_runtime_cell_supervision_cancel_requested",
    "agent_runtime_cell_backpressure",
    "agent_runtime_cell_mailbox_overloaded",
    "agent_runtime_cell_late_event_rejected",
    "session_output_commit_checked",
    "session_output_commit_ack",
    "session_output_commit_failed",
    "session_output_commit_skipped",
    "chat_stream_event",
]


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """Append-only event emitted by Harness loops."""

    event_id: str
    run_id: str
    event_type: RuntimeEventType
    offset: int
    created_at: float
    payload: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.runtime_event"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.runtime_event":
            raise ValueError("RuntimeEvent authority must be orchestration.runtime_event")
        if not self.event_id:
            raise ValueError("RuntimeEvent requires event_id")
        if not self.run_id:
            raise ValueError("RuntimeEvent requires run_id")
        if self.offset < 0:
            raise ValueError("RuntimeEvent offset must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
