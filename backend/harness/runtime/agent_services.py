from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentRuntimeServices:
    """Explicit system service table consumed by the single-agent runtime.

    HarnessServiceHost constructs this table, but AgentLoop receives stores,
    capabilities, and callbacks directly. It must not treat the service host as
    the loop owner.
    """

    root_dir: Path
    backend_dir: Path
    event_log: Any
    checkpoints: Any
    execution_store: Any
    state_index: Any
    runtime_objects: Any
    evidence_orchestrator: Any
    operation_gate: Any
    limits: Any
    tool_authorization_index: Any
    execution_engine: Any
    task_run_finalizer: Any
    agent_runtime_registry: Any
    memory_runtime_services: Any
    start_run: Any
    sync_runtime_objects_after_task_contract: Any
    record_task_run_step_event: Any
    record_task_run_ledger_updated: Any
    state_with_task_run_ledger: Any
    write_checkpoint_event: Any
    apply_tool_call_step_transition: Any
    apply_tool_result_step_transition: Any
    apply_failed_step_transition: Any
    enter_waiting_approval: Any
    current_permission_mode: Any
    finalize_working_memory_callback: Any
    get_trace_callback: Any

    @classmethod
    def from_runtime_host(cls, host: Any) -> "AgentRuntimeServices":
        return cls(
            root_dir=Path(host.root_dir),
            backend_dir=Path(host.backend_dir),
            event_log=host.event_log,
            checkpoints=host.checkpoints,
            execution_store=host.execution_store,
            state_index=host.state_index,
            runtime_objects=host.runtime_objects,
            evidence_orchestrator=host.evidence_orchestrator,
            operation_gate=host.operation_gate,
            limits=host.limits,
            tool_authorization_index=host.tool_authorization_index,
            execution_engine=host.execution_engine,
            task_run_finalizer=host.task_run_finalizer,
            agent_runtime_registry=host.agent_runtime_registry,
            memory_runtime_services=getattr(host, "memory_runtime_services", None),
            start_run=host.start,
            sync_runtime_objects_after_task_contract=host._sync_runtime_objects_after_task_contract,
            record_task_run_step_event=host._record_task_run_step_event,
            record_task_run_ledger_updated=host._record_task_run_ledger_updated,
            state_with_task_run_ledger=host._state_with_task_run_ledger,
            write_checkpoint_event=host._write_checkpoint_event,
            apply_tool_call_step_transition=host._apply_tool_call_step_transition,
            apply_tool_result_step_transition=host._apply_tool_result_step_transition,
            apply_failed_step_transition=host._apply_failed_step_transition,
            enter_waiting_approval=host._enter_waiting_approval,
            current_permission_mode=host._current_permission_mode,
            finalize_working_memory_callback=host.finalize_working_memory,
            get_trace_callback=host.get_trace,
        )

    def start(self, **kwargs: Any) -> Any:
        return self.start_run(**kwargs)

    def _sync_runtime_objects_after_task_contract(self, **kwargs: Any) -> list[Any]:
        return list(self.sync_runtime_objects_after_task_contract(**kwargs))

    def _record_task_run_step_event(self, *args: Any, **kwargs: Any) -> Any:
        return self.record_task_run_step_event(*args, **kwargs)

    def _record_task_run_ledger_updated(self, *args: Any, **kwargs: Any) -> Any:
        return self.record_task_run_ledger_updated(*args, **kwargs)

    def _state_with_task_run_ledger(self, *args: Any, **kwargs: Any) -> Any:
        return self.state_with_task_run_ledger(*args, **kwargs)

    def _write_checkpoint_event(self, *args: Any, **kwargs: Any) -> Any:
        return self.write_checkpoint_event(*args, **kwargs)

    def _apply_tool_call_step_transition(self, *args: Any, **kwargs: Any) -> Any:
        return self.apply_tool_call_step_transition(*args, **kwargs)

    def _apply_tool_result_step_transition(self, *args: Any, **kwargs: Any) -> Any:
        return self.apply_tool_result_step_transition(*args, **kwargs)

    def _apply_failed_step_transition(self, *args: Any, **kwargs: Any) -> Any:
        return self.apply_failed_step_transition(*args, **kwargs)

    def _enter_waiting_approval(self, *args: Any, **kwargs: Any) -> Any:
        return self.enter_waiting_approval(*args, **kwargs)

    def _current_permission_mode(self) -> str:
        return str(self.current_permission_mode() or "default")

    def finalize_working_memory(self, *args: Any, **kwargs: Any) -> Any:
        return self.finalize_working_memory_callback(*args, **kwargs)

    def get_task_run(self, task_run_id: str) -> Any | None:
        return self.state_index.get_task_run(task_run_id)

    def get_trace(self, task_run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.get_trace_callback(task_run_id, **kwargs)

    def event_count(self, task_run_id: str) -> int:
        return len(self.event_log.list_events(task_run_id))
