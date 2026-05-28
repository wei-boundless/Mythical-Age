from __future__ import annotations

from dataclasses import dataclass, field
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
    prompt_accounting_ledger: Any
    state_index: Any
    runtime_objects: Any
    execution_store: Any
    operation_gate: Any
    tool_authorization_index: Any
    current_permission_mode: Any
    get_trace_callback: Any
    execute_task_run_callback: Any | None = None
    execute_graph_agent_work_order_callback: Any | None = None
    get_graph_harness_config_callback: Any | None = None
    model_runtime: Any | None = None
    tool_runtime_executor: Any | None = None
    tool_instances: tuple[Any, ...] = ()
    agent_runtime_profile_resolver: Any | None = None
    backend_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_runtime_host(
        cls,
        host: Any,
        *,
        execute_task_run_callback: Any | None = None,
        execute_graph_agent_work_order_callback: Any | None = None,
        get_graph_harness_config_callback: Any | None = None,
        model_runtime: Any | None = None,
        tool_runtime_executor: Any | None = None,
        tool_instances: list[Any] | tuple[Any, ...] | None = None,
        agent_runtime_profile_resolver: Any | None = None,
        backend_config: dict[str, Any] | None = None,
    ) -> "AgentRuntimeServices":
        return cls(
            root_dir=Path(host.root_dir),
            backend_dir=Path(host.backend_dir),
            event_log=host.event_log,
            prompt_accounting_ledger=getattr(host, "prompt_accounting_ledger", None),
            state_index=host.state_index,
            runtime_objects=host.runtime_objects,
            execution_store=host.execution_store,
            operation_gate=host.operation_gate,
            tool_authorization_index=host.tool_authorization_index,
            current_permission_mode=host._current_permission_mode,
            get_trace_callback=host.get_trace,
            execute_task_run_callback=execute_task_run_callback,
            execute_graph_agent_work_order_callback=execute_graph_agent_work_order_callback,
            get_graph_harness_config_callback=get_graph_harness_config_callback,
            model_runtime=model_runtime,
            tool_runtime_executor=tool_runtime_executor,
            tool_instances=tuple(tool_instances or ()),
            agent_runtime_profile_resolver=agent_runtime_profile_resolver,
            backend_config=dict(backend_config or {}),
        )

    def _current_permission_mode(self) -> str:
        return str(self.current_permission_mode() or "default")

    def get_task_run(self, task_run_id: str) -> Any | None:
        return self.state_index.get_task_run(task_run_id)

    def get_trace(self, task_run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.get_trace_callback(task_run_id, **kwargs)

    def event_count(self, task_run_id: str) -> int:
        return len(self.event_log.list_events(task_run_id))


@dataclass(frozen=True, slots=True)
class TaskExecutorServices:
    """Narrow service table for a TaskRun executor invocation.

    The task executor is part of the harness, not the API adapter. It receives
    the exact runtime services it needs instead of reaching back into
    QueryRuntime.
    """

    runtime_host: Any
    backend_dir: Path
    model_runtime: Any
    tool_runtime_executor: Any | None
    tool_instances: tuple[Any, ...]
    agent_runtime_profile: Any | None
    backend_config: dict[str, Any]

    def all_tool_instances(self) -> list[Any]:
        return list(self.tool_instances)
