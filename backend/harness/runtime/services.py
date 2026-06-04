from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentRuntimeServices:
    """Small service table for the single-agent harness.

    The loop receives stores and gateways explicitly. It must not call back
    into external turn controllers or task routers to decide what the agent wants.
    """

    root_dir: Path
    backend_dir: Path
    event_log: Any
    prompt_accounting_ledger: Any
    state_index: Any
    monitor_projector: Any
    runtime_objects: Any
    graph_checkpoint_store: Any
    execution_store: Any
    operation_gate: Any
    tool_control_plane: Any
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
    artifact_repository_service: Any | None = None
    formal_memory_service: Any | None = None
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
        artifact_repository_service: Any | None = None,
        formal_memory_service: Any | None = None,
        backend_config: dict[str, Any] | None = None,
    ) -> "AgentRuntimeServices":
        resolved_artifact_repository_service = artifact_repository_service
        resolved_formal_memory_service = formal_memory_service
        if resolved_artifact_repository_service is None or resolved_formal_memory_service is None:
            resolved_artifact_repository_service, resolved_formal_memory_service = _default_environment_services(host)
        return cls(
            root_dir=Path(host.root_dir),
            backend_dir=Path(host.backend_dir),
            event_log=host.event_log,
            prompt_accounting_ledger=getattr(host, "prompt_accounting_ledger", None),
            state_index=host.state_index,
            monitor_projector=host.monitor_projector,
            runtime_objects=host.runtime_objects,
            graph_checkpoint_store=host.graph_checkpoint_store,
            execution_store=host.execution_store,
            operation_gate=host.operation_gate,
            tool_control_plane=getattr(host, "tool_control_plane", None),
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
            artifact_repository_service=resolved_artifact_repository_service,
            formal_memory_service=resolved_formal_memory_service,
            backend_config=dict(backend_config or {}),
        )

    def _current_permission_mode(self) -> str:
        return str(self.current_permission_mode() or "default")

    def get_task_run(self, task_run_id: str) -> Any | None:
        return self.state_index.get_task_run(task_run_id)

    def get_trace(self, task_run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.get_trace_callback(task_run_id, **kwargs)

    def event_count(self, task_run_id: str) -> int:
        estimator = getattr(self.event_log, "estimated_event_count", None)
        if callable(estimator):
            return int(estimator(task_run_id))
        counter = getattr(self.event_log, "event_count", None)
        if callable(counter):
            return int(counter(task_run_id))
        return 0


def _default_environment_services(host: Any) -> tuple[Any | None, Any | None]:
    try:
        from artifact_system import ArtifactRepositoryService
        from memory_system.runtime_services import MemoryRuntimeServices
        from project_layout import ProjectLayout
    except Exception:
        return None, None
    try:
        layout = ProjectLayout.from_backend_dir(Path(host.backend_dir))
        memory_services = MemoryRuntimeServices(layout.storage_root)
        artifact_repository = ArtifactRepositoryService(
            layout.storage_root / "artifact_repository",
            workspace_root=layout.project_root,
        )
        return artifact_repository, memory_services.formal_memory
    except Exception:
        return None, None


@dataclass(frozen=True, slots=True)
class TaskExecutorServices:
    """Narrow service table for a TaskRun executor invocation.

    The task executor is part of the harness, not the API adapter. It receives
    the exact runtime services it needs instead of reaching back into
    HarnessRuntimeFacade.
    """

    runtime_host: Any
    backend_dir: Path
    model_runtime: Any
    tool_control_plane: Any | None
    tool_runtime_executor: Any | None
    tool_instances: tuple[Any, ...]
    agent_runtime_profile: Any | None
    backend_config: dict[str, Any]
    assistant_message_committer: Any | None = None
    execute_task_run_callback: Any | None = None
    memory_context_provider: Any | None = None

    def all_tool_instances(self) -> list[Any]:
        return list(self.tool_instances)
