from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentRuntimeServices:
    """Small service table for the single-agent harness.

    The loop receives stores and gateways explicitly. It must not call back
    into legacy turn controllers or task routers to decide what the agent wants.
    """

    root_dir: Path
    backend_dir: Path
    event_log: Any
    state_index: Any
    runtime_objects: Any
    execution_store: Any
    operation_gate: Any
    tool_authorization_index: Any
    current_permission_mode: Any
    get_trace_callback: Any

    @classmethod
    def from_runtime_host(cls, host: Any) -> "AgentRuntimeServices":
        return cls(
            root_dir=Path(host.root_dir),
            backend_dir=Path(host.backend_dir),
            event_log=host.event_log,
            state_index=host.state_index,
            runtime_objects=host.runtime_objects,
            execution_store=host.execution_store,
            operation_gate=host.operation_gate,
            tool_authorization_index=host.tool_authorization_index,
            current_permission_mode=host._current_permission_mode,
            get_trace_callback=host.get_trace,
        )

    def _current_permission_mode(self) -> str:
        return str(self.current_permission_mode() or "default")

    def get_task_run(self, task_run_id: str) -> Any | None:
        return self.state_index.get_task_run(task_run_id)

    def get_trace(self, task_run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.get_trace_callback(task_run_id, **kwargs)

    def event_count(self, task_run_id: str) -> int:
        return len(self.event_log.list_events(task_run_id))
