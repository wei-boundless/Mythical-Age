from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RuntimeEventType = Literal[
    "task_run_started",
    "agent_run_created",
    "agent_run_updated",
    "coordination_run_created",
    "coordination_run_updated",
    "worker_agent_spawn_requested",
    "worker_agent_spawn_completed",
    "coordination_node_run_created",
    "coordination_node_run_updated",
    "handoff_envelope_created",
    "coordination_merge_result_created",
    "agent_dispatch_plan_compiled",
    "agent_notification_queued",
    "coordination_flow_registered",
    "coordination_flow_finalized",
    "coordination_stage_updated",
    "search_policy_resolved",
    "loop_iteration_started",
    "loop_control_checked",
    "task_contract_built",
    "task_run_ledger_updated",
    "step_added",
    "step_entered",
    "step_completed",
    "step_failed",
    "step_skipped",
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
    "model_stream_recovery",
    "model_item_received",
    "executor_observation_received",
    "recipe_mcp_blocked_by_search_policy",
    "output_boundary_applied",
    "commit_gate_checked",
    "task_artifact_validation_checked",
    "required_artifact_write_repair_started",
    "required_artifact_write_repair_finished",
    "artifact_success_fallback_finalized",
    "checkpoint_written",
    "loop_terminal",
    "loop_error",
    "tool_call_requested",
    "tool_result_received",
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
    "tool_call_blocked_by_search_policy",
    "runtime_state_index_degraded",
    "autonomous_task_started",
    "autonomous_task_state_changed",
    "autonomous_task_plan_drafted",
    "autonomous_task_verification_checked",
]


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """Append-only event emitted by TaskRunLoop."""

    event_id: str
    task_run_id: str
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
        if not self.task_run_id:
            raise ValueError("RuntimeEvent requires task_run_id")
        if self.offset < 0:
            raise ValueError("RuntimeEvent offset must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
