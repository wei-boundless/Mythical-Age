from __future__ import annotations

import asyncio
from contextlib import contextmanager
import contextvars
import os
from pathlib import Path
import sqlite3
import time
import uuid
from typing import Any, Callable

from artifact_system import ArtifactAuthority, ArtifactRepositoryService
from permissions.operations import build_default_operation_registry
from capability_system.tools.authorization import ToolAuthorizationIndex, build_tool_authorization_index
from permissions import OperationGate
from project_layout import ProjectLayout
from harness.runtime.monitoring import RuntimeMonitorService
from harness.graph.langgraph_checkpoint_store import LangGraphCheckpointStore
from runtime.memory.state_index import RuntimeStateIndex
from runtime.prompt_accounting import PromptAccountingLedger
from runtime.shared.event_log import RuntimeEventLog
from runtime.shared.execution_record import RuntimeExecutionStore
from runtime.shared.runtime_run_registry import RuntimeRun, RuntimeRunRegistry
from runtime.shared.runtime_object_store import RuntimeObjectStore
from runtime.shared.stream_replay import RuntimeStreamReplayService
from runtime.tool_runtime.tool_control_plane import RuntimeToolControlPlane
from .active_turn import ActiveTurnRegistry
from langgraph.checkpoint.sqlite import SqliteSaver

class SingleAgentRuntimeHost:
    """Minimal service host for the rebuilt single-agent mainline.

    It owns only the stores and gates needed by the generic agent loop.
    """

    def __init__(
        self,
        root_dir: Path,
        *,
        backend_dir: Path | None = None,
        operation_gate: OperationGate | None = None,
        permission_mode_provider: Callable[[], str] | None = None,
        session_scope_resolver: Callable[[str], dict[str, Any] | None] | None = None,
        tool_authorization_index: ToolAuthorizationIndex | None = None,
        tool_definitions: list[Any] | tuple[Any, ...] | None = None,
        tool_runtime_executor: Any | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.owner_process_id = os.getpid()
        self.instance_id = f"runtime-instance:{os.getpid()}:{uuid.uuid4().hex[:12]}"
        self.backend_dir = Path(backend_dir) if backend_dir is not None else ProjectLayout.from_runtime_root(self.root_dir).backend_dir
        self.event_log = RuntimeEventLog(self.root_dir)
        self.run_registry = RuntimeRunRegistry(self.root_dir)
        self.stream_replay = RuntimeStreamReplayService(self.event_log)
        self._close_unowned_active_chat_runs()
        self.prompt_accounting_ledger = PromptAccountingLedger(self.root_dir)
        self.execution_store = RuntimeExecutionStore(self.root_dir)
        self.state_index = RuntimeStateIndex(self.root_dir)
        self.runtime_objects = RuntimeObjectStore(self.root_dir)
        self.active_turn_registry = ActiveTurnRegistry(self)
        self.graph_checkpoint_store = LangGraphCheckpointStore(_build_graph_checkpoint_saver(self.root_dir))
        self.operation_gate = operation_gate or OperationGate(build_default_operation_registry())
        self.session_scope_resolver = session_scope_resolver
        self.tool_control_plane = RuntimeToolControlPlane(
            tool_runtime_executor=tool_runtime_executor,
            operation_gate=self.operation_gate,
        )
        self.permission_mode_provider = permission_mode_provider
        self._permission_mode_override: contextvars.ContextVar[str] = contextvars.ContextVar(
            "single_agent_runtime_permission_mode_override",
            default="",
        )
        self.tool_authorization_index = tool_authorization_index or build_tool_authorization_index(
            tuple(tool_definitions or ())
        )
        self.runtime_monitor_service = RuntimeMonitorService(runtime_host=self)
        self.monitor_projector = self.runtime_monitor_service.projector
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._background_tasks_by_name: dict[str, set[asyncio.Task[Any]]] = {}

    def spawn_background_task(self, coro: Any, *, name: str = "") -> asyncio.Task[Any]:
        kwargs = {"name": name} if name else {}
        task = asyncio.create_task(coro, **kwargs)
        self._background_tasks.add(task)
        if name:
            self._background_tasks_by_name.setdefault(name, set()).add(task)

        def _discard(done: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(done)
            if name:
                named = self._background_tasks_by_name.get(name)
                if named is not None:
                    named.discard(done)
                    if not named:
                        self._background_tasks_by_name.pop(name, None)

        task.add_done_callback(_discard)
        return task

    async def cancel_background_tasks(
        self,
        *,
        names: set[str] | list[str] | tuple[str, ...],
        reason: str = "session_deleted",
        timeout_seconds: float = 5.0,
    ) -> dict[str, Any]:
        target_names = {str(item).strip() for item in names if str(item).strip()}
        current = asyncio.current_task()
        tasks: set[asyncio.Task[Any]] = set()
        for name in target_names:
            tasks.update(self._background_tasks_by_name.get(name, set()))
        tasks = {task for task in tasks if task is not current and not task.done()}
        for task in tasks:
            task.cancel(msg=reason)
        timed_out = False
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=max(0.1, float(timeout_seconds or 5.0)))
            except asyncio.TimeoutError:
                timed_out = True
        return {
            "authority": "single_agent_runtime_host.cancel_background_tasks",
            "requested_names": sorted(target_names),
            "cancelled_count": len(tasks),
            "timed_out": timed_out,
        }

    def _close_unowned_active_chat_runs(self) -> None:
        for run in self.run_registry.list_runs():
            if not _active_chat_run_not_owned_by_current_host(
                run,
                owner_process_id=self.owner_process_id,
                owner_instance_id=self.instance_id,
            ):
                continue
            current = self.run_registry.get_run(run.stream_run_id) or run
            event = self.stream_replay.append_public_event(
                current,
                public_event_type="error",
                data={
                    "error": "运行进程已重启，原执行流已经终止，agent 没有收到新的模型轮次。请发送新的消息；这条消息会作为新的用户输入交给 agent，由 agent 基于可见上下文和当前任务状态决定下一步。",
                    "code": "runtime_process_restarted",
                    "reason": "background_executor_missing_after_restart",
                },
            )
            self.run_registry.mark_event(
                current,
                latest_event_offset=event.offset,
                status="orphaned",
                terminal_event="error",
                diagnostics={
                    "orphaned_by": "single_agent_runtime_host.startup_reconciliation",
                    "reason": "runtime_process_restarted",
                },
            )

    def _current_permission_mode(self) -> str:
        override = str(self._permission_mode_override.get() or "").strip()
        if override:
            return override
        provider = self.permission_mode_provider
        if callable(provider):
            try:
                mode = str(provider() or "").strip()
            except Exception:
                return "default"
            if mode:
                return mode
        return "default"

    @contextmanager
    def permission_mode_scope(self, permission_mode: str):
        token = self._permission_mode_override.set(str(permission_mode or "").strip())
        try:
            yield
        finally:
            self._permission_mode_override.reset(token)

    def list_session_traces(self, session_id: str) -> dict[str, Any]:
        task_runs = sorted(
            self.state_index.list_session_task_runs(session_id),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        turn_runs = sorted(
            self.state_index.list_session_turn_runs(session_id),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        return {
            "session_id": session_id,
            "task_run_count": len(task_runs),
            "task_runs": [self._task_run_summary(item) for item in task_runs],
            "turn_run_count": len(turn_runs),
            "turn_runs": [item.to_dict() for item in turn_runs],
            "authority": "single_agent_runtime_host.session_traces",
        }

    def list_global_live_monitor(self, limit: int = 20) -> dict[str, Any]:
        return self.runtime_monitor_service.list_global_live_monitor(limit=limit)

    def get_session_live_monitor(self, session_id: str) -> dict[str, Any]:
        return self.runtime_monitor_service.get_session_live_monitor(session_id)

    def get_task_run_live_monitor(self, task_run_id: str) -> dict[str, Any] | None:
        return self.runtime_monitor_service.get_task_run_live_monitor(task_run_id)

    def get_trace(
        self,
        task_run_id: str,
        *,
        include_payloads: bool = False,
        include_model_messages: bool = False,
        event_limit: int | None = None,
    ) -> dict[str, Any] | None:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            return None
        requested_limit = max(1, min(int(event_limit or 240), 1000))
        if include_payloads:
            if event_limit is None:
                events = [item.to_dict() for item in self.event_log.list_events(task_run_id)]
            else:
                events = [
                    item.to_dict()
                    for item in self.event_log.list_event_window(
                        task_run_id,
                        limit=requested_limit,
                        include_payloads=True,
                    )
                ]
        else:
            events = [item.to_dict() for item in self.event_log.list_recent_events(task_run_id, limit=requested_limit)]
        graph_runs = self._graph_runs_for_task_run(task_run)
        if not include_payloads:
            events = [
                {
                    **event,
                    "payload": _redact_payload(dict(event.get("payload") or {}), include_model_messages=include_model_messages),
                }
                for event in events
            ]
        event_count = _event_count(self.event_log, task_run_id, fallback=len(events))
        return {
            "task_run": task_run.to_dict(),
            "graph_runs": graph_runs,
            "graph_run_count": len(graph_runs),
            "events": events,
            "event_count": event_count,
            "event_window": {
                "kind": "full_payload" if include_payloads and event_limit is None else ("bounded_full_payload_tail" if include_payloads else "tail"),
                "limit": requested_limit,
                "returned": len(events),
                "include_payloads": include_payloads,
            },
            "authority": "single_agent_runtime_host.task_run_trace",
        }

    def get_turn_trace(
        self,
        turn_run_id: str,
        *,
        include_payloads: bool = False,
        include_model_messages: bool = False,
        event_limit: int | None = None,
    ) -> dict[str, Any] | None:
        turn_run = self.state_index.get_turn_run(turn_run_id)
        if turn_run is None:
            return None
        return self._turn_run_trace(
            turn_run,
            include_payloads=include_payloads,
            include_model_messages=include_model_messages,
            event_limit=event_limit,
        )

    def _turn_run_trace(
        self,
        turn_run: Any,
        *,
        include_payloads: bool = False,
        include_model_messages: bool = False,
        event_limit: int | None = None,
    ) -> dict[str, Any]:
        turn_run_id = str(getattr(turn_run, "turn_run_id", "") or "")
        requested_limit = max(1, min(int(event_limit or 240), 1000))
        if include_payloads:
            if event_limit is None:
                events = [item.to_dict() for item in self.event_log.list_events(turn_run_id)]
            else:
                events = [
                    item.to_dict()
                    for item in self.event_log.list_event_window(
                        turn_run_id,
                        limit=requested_limit,
                        include_payloads=True,
                    )
                ]
        else:
            events = [item.to_dict() for item in self.event_log.list_recent_events(turn_run_id, limit=requested_limit)]
            events = [
                {
                    **event,
                    "payload": _redact_payload(dict(event.get("payload") or {}), include_model_messages=include_model_messages),
                }
                for event in events
            ]
        return {
            "turn_run": turn_run.to_dict(),
            "events": events,
            "event_count": _event_count(self.event_log, turn_run_id, fallback=len(events)),
            "event_window": {
                "kind": "full_payload" if include_payloads and event_limit is None else ("bounded_full_payload_tail" if include_payloads else "tail"),
                "limit": requested_limit,
                "returned": len(events),
                "include_payloads": include_payloads,
            },
            "authority": "single_agent_runtime_host.turn_run_trace",
        }

    def get_task_run_artifacts(self, task_run_id: str) -> dict[str, Any]:
        task_run = self.state_index.get_task_run(task_run_id)
        raw_refs: list[Any] = []
        if task_run is not None:
            raw_refs.extend(list(dict(task_run.diagnostics or {}).get("artifact_refs") or []))
        raw_refs.extend(self._artifact_refs_from_task_events(task_run_id))
        for result in self.state_index.list_task_agent_run_results(task_run_id):
            raw_refs.extend(list(result.artifact_refs or ()))
            raw_refs.extend(list(dict(result.diagnostics or {}).get("artifact_refs") or []))
        return self._artifact_authority().task_artifact_view(
            task_run_id=task_run_id,
            candidate_refs=raw_refs,
        )

    def _artifact_authority(self) -> ArtifactAuthority:
        layout = ProjectLayout.from_backend_dir(self.backend_dir)
        return ArtifactAuthority(
            workspace_root=layout.project_root,
            artifact_repository=ArtifactRepositoryService(
                layout.storage_root / "artifact_repository",
                workspace_root=layout.project_root,
            ),
        )

    def _artifact_refs_from_task_events(self, task_run_id: str) -> list[dict[str, Any]]:
        from artifact_system.artifact_authority import artifact_refs_from_events

        reader = getattr(self.event_log, "list_events", None)
        if not callable(reader):
            return []
        try:
            events = list(reader(task_run_id))
        except Exception:
            return []
        return artifact_refs_from_events(events)

    def get_task_run_memory_receipts(self, task_run_id: str) -> dict[str, Any]:
        return {
            "task_run_id": task_run_id,
            "memory_operations": [],
            "stage_results": [],
            "authority": "single_agent_runtime_host.task_run_memory_receipts",
        }

    def get_project_runtime_status(self, project_id: str) -> dict[str, Any] | None:
        status = self.state_index.get_project_runtime_status(project_id)
        if status is None:
            return None
        ledger = self.state_index.get_project_progress_ledger(project_id)
        return {
            "project_runtime_status": status.to_dict(),
            "project_progress_ledger": ledger.to_dict() if ledger is not None else None,
            "authority": "single_agent_runtime_host.project_runtime_status_view",
        }

    def _task_run_summary(self, task_run: Any) -> dict[str, Any]:
        graph_runs = self._graph_runs_for_task_run(task_run)
        return {
            "task_run_id": task_run.task_run_id,
            "session_id": task_run.session_id,
            "task_id": task_run.task_id,
            "status": task_run.status,
            "execution_runtime_kind": task_run.execution_runtime_kind,
            "created_at": task_run.created_at,
            "updated_at": task_run.updated_at,
            "terminal_reason": task_run.terminal_reason,
            "latest_event_offset": task_run.latest_event_offset,
            "graph_run_count": len(graph_runs),
            "graph_runs": graph_runs,
        }

    def _graph_runs_for_task_run(self, task_run: Any) -> list[dict[str, Any]]:
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        graph_run_id = str(diagnostics.get("graph_run_id") or "").strip()
        if not graph_run_id:
            return []
        payload = self.runtime_objects.get_object(f"rtobj:graph_run:{_safe_runtime_object_id(graph_run_id)}")
        if not payload:
            return []
        return [payload]

def _redact_payload(payload: dict[str, Any], *, include_model_messages: bool) -> dict[str, Any]:
    if include_model_messages:
        return payload
    redacted = dict(payload)
    for key in ("model_messages", "messages", "history"):
        if key in redacted:
            redacted[key] = "[redacted]"
    packet = redacted.get("packet")
    if isinstance(packet, dict) and "model_messages" in packet:
        redacted["packet"] = {**packet, "model_messages": "[redacted]"}
    return redacted


def _event_count(event_log: Any, task_run_id: str, *, fallback: int) -> int:
    estimator = getattr(event_log, "estimated_event_count", None)
    if callable(estimator):
        try:
            return int(estimator(task_run_id))
        except Exception:
            return int(fallback)
    counter = getattr(event_log, "event_count", None)
    if callable(counter):
        try:
            return int(counter(task_run_id))
        except Exception:
            return int(fallback)
    return int(fallback)


def _safe_runtime_object_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:180]


def _build_graph_checkpoint_saver(root_dir: Path) -> SqliteSaver:
    path = Path(root_dir) / "graph_checkpoints.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(connection)
    saver.setup()
    return saver


def _active_chat_run_not_owned_by_current_host(
    run: RuntimeRun,
    *,
    owner_process_id: int,
    owner_instance_id: str,
) -> bool:
    if run.status in {"completed", "failed", "stopped", "orphaned"}:
        return False
    if not str(run.event_log_id or "").startswith("chatrun:"):
        return False
    if run.owner_instance_id:
        return run.owner_instance_id != owner_instance_id
    if run.owner_process_id:
        return int(run.owner_process_id) != int(owner_process_id)
    return True
