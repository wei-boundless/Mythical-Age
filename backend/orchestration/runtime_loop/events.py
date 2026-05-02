from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RuntimeEventType = Literal[
    "task_run_started",
    "loop_iteration_started",
    "loop_control_checked",
    "task_contract_built",
    "memory_runtime_view_built",
    "context_snapshot_built",
    "context_invariant_checked",
    "stage_projection_built",
    "runtime_directive_issued",
    "operation_gate_checked",
    "executor_started",
    "model_item_received",
    "executor_observation_received",
    "output_boundary_applied",
    "commit_gate_checked",
    "checkpoint_written",
    "loop_terminal",
    "loop_error",
    "tool_call_requested",
    "tool_result_received",
    "worker_requested",
    "worker_result_received",
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
