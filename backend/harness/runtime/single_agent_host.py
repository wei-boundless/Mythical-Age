from __future__ import annotations

import asyncio
from dataclasses import replace
import logging
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
from harness.runtime.run_monitor import RuntimeMonitorService
from harness.graph.langgraph_checkpoint_store import LangGraphCheckpointStore
from runtime.memory.state_index import RuntimeStateIndex
from runtime.facts import RuntimeFactLedger
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime.prompt_accounting import PromptAccountingLedger
from runtime.observability import RuntimeObservabilityKernel
from runtime.shared.event_log import RuntimeEventLog
from runtime.shared.execution_record import RuntimeExecutionStore
from runtime.shared.queued_user_input_store import QueuedUserInputStore
from runtime.shared.runtime_run_registry import RuntimeRun, RuntimeRunRegistry
from runtime.shared.runtime_object_store import RuntimeObjectStore
from runtime.shared.stream_replay import RuntimeStreamReplayService
from runtime.trace import RuntimeTraceService
from runtime.cache_manager import RuntimeCacheManager
from runtime.tool_runtime.tool_control_plane import RuntimeToolControlPlane
from .active_turn import ActiveTurnRegistry
from .agent_run_supervisor import AgentRunSupervisor
from .runtime_gateway import RuntimeGateway
from langgraph.checkpoint.sqlite import SqliteSaver

logger = logging.getLogger(__name__)


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
        session_manager: Any | None = None,
        tool_authorization_index: ToolAuthorizationIndex | None = None,
        tool_definitions: list[Any] | tuple[Any, ...] | None = None,
        tool_runtime_executor: Any | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.owner_process_id = os.getpid()
        self.instance_id = f"runtime-instance:{os.getpid()}:{uuid.uuid4().hex[:12]}"
        self.backend_dir = Path(backend_dir) if backend_dir is not None else ProjectLayout.from_runtime_root(self.root_dir).backend_dir
        self.runtime_cache = RuntimeCacheManager.from_runtime_root(self.root_dir)
        self.fact_ledger = RuntimeFactLedger(self.root_dir)
        self.event_log = RuntimeEventLog(self.root_dir, fact_ledger=self.fact_ledger)
        self.runtime_gateway = RuntimeGateway(self.event_log)
        self.run_registry = RuntimeRunRegistry(self.root_dir)
        self.stream_replay = RuntimeStreamReplayService(self.event_log)
        self.session_manager = session_manager
        self.prompt_accounting_ledger = PromptAccountingLedger(self.root_dir)
        self.execution_store = RuntimeExecutionStore(self.root_dir)
        self.queued_user_inputs = QueuedUserInputStore(self.root_dir)
        self.file_state_store = FileStateAuthorityStore(self.root_dir)
        self.state_index = RuntimeStateIndex(self.root_dir)
        self.runtime_objects = RuntimeObjectStore(self.root_dir)
        self.trace_service = RuntimeTraceService(self.root_dir, fact_ledger=self.fact_ledger)
        self.observability = RuntimeObservabilityKernel(
            event_log=self.event_log,
            trace_service=self.trace_service,
            fact_ledger=self.fact_ledger,
        )
        self.active_turn_registry = ActiveTurnRegistry(self)
        self._record_unowned_active_chat_run_interruptions()
        self.graph_checkpoint_store = LangGraphCheckpointStore(_build_graph_checkpoint_saver(self.root_dir))
        self.operation_gate = operation_gate or OperationGate(build_default_operation_registry())
        self.session_scope_resolver = session_scope_resolver
        self.tool_control_plane = RuntimeToolControlPlane(
            tool_runtime_executor=tool_runtime_executor,
            operation_gate=self.operation_gate,
        )
        self.permission_mode_provider = permission_mode_provider
        self.tool_authorization_index = tool_authorization_index or build_tool_authorization_index(
            tuple(tool_definitions or ())
        )
        self.runtime_monitor_service = RuntimeMonitorService(runtime_host=self)
        self.monitor_projector = self.runtime_monitor_service.projector
        self.agent_run_supervisor = AgentRunSupervisor(
            runtime_host=self,
            runtime_gateway=self.runtime_gateway,
        )
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._background_tasks_by_name: dict[str, set[asyncio.Task[Any]]] = {}
        self._control_loop: asyncio.AbstractEventLoop | None = None

    def bind_control_loop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        try:
            candidate = loop or asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._control_loop is not None and self._control_loop.is_running() and self._control_loop is not candidate:
            return
        if candidate.is_running():
            self._control_loop = candidate

    def spawn_background_task(self, coro: Any, *, name: str = "") -> asyncio.Task[Any]:
        self.bind_control_loop()
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

    def background_task_running(self, name: str) -> bool:
        normalized = str(name or "").strip()
        if not normalized:
            return False
        tasks = self._background_tasks_by_name.get(normalized, set())
        return any(not task.done() for task in list(tasks or ()))

    def spawn_control_background_task(
        self,
        coro_factory: Callable[[], Any],
        *,
        name: str = "",
    ) -> asyncio.Task[Any] | None:
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        control_loop = self._control_loop if self._control_loop is not None and self._control_loop.is_running() else current_loop
        if control_loop is None or not control_loop.is_running():
            return None

        def _start() -> asyncio.Task[Any] | None:
            try:
                coro = coro_factory()
            except Exception:
                logger.exception("failed to create control background coroutine", extra={"task_name": name})
                return None
            try:
                return self.spawn_background_task(coro, name=name)
            except Exception:
                close = getattr(coro, "close", None)
                if callable(close):
                    close()
                logger.exception("failed to schedule control background task", extra={"task_name": name})
                return None

        if current_loop is control_loop:
            return _start()
        control_loop.call_soon_threadsafe(_start)
        return None

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

    def cancel_task_run_cells(
        self,
        *,
        task_run_sessions: dict[str, str],
        reason: str = "task_run_cancelled",
    ) -> dict[str, Any]:
        supervisor = getattr(self, "agent_run_supervisor", None)
        requested: dict[str, str] = {
            str(task_run_id or "").strip(): str(session_id or "").strip()
            for task_run_id, session_id in dict(task_run_sessions or {}).items()
            if str(task_run_id or "").strip()
        }
        cancelled: list[str] = []
        rejected: list[dict[str, str]] = []
        missing_scope: list[str] = []
        for task_run_id, session_id in requested.items():
            if not session_id:
                missing_scope.append(task_run_id)
                continue
            if supervisor is not None and supervisor.cancel_task_run(task_run_id, session_id=session_id, reason=reason):
                cancelled.append(task_run_id)
                continue
            rejected.append(
                {
                    "task_run_id": task_run_id,
                    "expected_session_id": session_id,
                    "reason": "active_cell_missing_or_session_mismatch",
                }
            )
        return {
            "authority": "single_agent_runtime_host.cancel_task_run_cells",
            "requested_task_run_ids": sorted(requested),
            "cancelled_count": len(cancelled),
            "cancelled_task_run_ids": sorted(cancelled),
            "rejected": rejected,
            "missing_scope_task_run_ids": sorted(missing_scope),
            "reason": str(reason or ""),
        }

    def cancel_runtime_run_cells(
        self,
        *,
        runtime_run_sessions: dict[str, str],
        reason: str = "runtime_run_cancelled",
    ) -> dict[str, Any]:
        supervisor = getattr(self, "agent_run_supervisor", None)
        requested: dict[str, str] = {
            str(stream_run_id or "").strip(): str(session_id or "").strip()
            for stream_run_id, session_id in dict(runtime_run_sessions or {}).items()
            if str(stream_run_id or "").strip()
        }
        cancelled: list[str] = []
        rejected: list[dict[str, str]] = []
        missing_scope: list[str] = []
        for stream_run_id, session_id in requested.items():
            if not session_id:
                missing_scope.append(stream_run_id)
                continue
            if supervisor is not None and supervisor.cancel_stream_run(stream_run_id, session_id=session_id, reason=reason):
                cancelled.append(stream_run_id)
                continue
            rejected.append(
                {
                    "stream_run_id": stream_run_id,
                    "expected_session_id": session_id,
                    "reason": "active_cell_missing_or_session_mismatch",
                }
            )
        return {
            "authority": "single_agent_runtime_host.cancel_runtime_run_cells",
            "requested_stream_run_ids": sorted(requested),
            "cancelled_count": len(cancelled),
            "cancelled_stream_run_ids": sorted(cancelled),
            "rejected": rejected,
            "missing_scope_stream_run_ids": sorted(missing_scope),
            "reason": str(reason or ""),
        }

    def _record_unowned_active_chat_run_interruptions(self) -> None:
        for run in self.run_registry.list_runs():
            if not _active_chat_run_not_owned_by_current_host(
                run,
                owner_process_id=self.owner_process_id,
                owner_instance_id=self.instance_id,
            ):
                if _orphaned_chat_run_needs_interruption_record(run):
                    diagnostics = dict(run.diagnostics or {})
                    failure_code = str(diagnostics.get("reason") or "").strip() or "runtime_process_restarted"
                    self.record_chat_turn_run_runtime_interruption_best_effort(
                        run,
                        code=failure_code,
                        reason=_orphaned_chat_run_failure_reason(failure_code),
                        orphaned_by="single_agent_runtime_host.startup_reconciliation",
                    )
                continue
            current = self.run_registry.get_run(run.stream_run_id) or run
            self.record_chat_turn_run_runtime_interruption_best_effort(
                current,
                code="runtime_process_restarted",
                reason="runtime_cell_missing_after_restart",
                orphaned_by="single_agent_runtime_host.startup_reconciliation",
            )

    def record_chat_turn_run_runtime_interruption_best_effort(
        self,
        run: RuntimeRun,
        *,
        code: str,
        reason: str = "",
        orphaned_by: str = "",
    ) -> dict[str, Any]:
        try:
            return self.record_chat_turn_run_runtime_interruption(
                run,
                code=code,
                reason=reason,
                orphaned_by=orphaned_by,
            )
        except Exception:
            logger.exception(
                "failed to record chat runtime interruption",
                extra={"stream_run_id": getattr(run, "stream_run_id", ""), "failure_code": code},
            )
            return {
                "authority": "single_agent_runtime_host.chat_turn_runtime_interruption",
                "stream_run_id": str(getattr(run, "stream_run_id", "") or ""),
                "turn_run_closed": False,
                "public_terminal_event_appended": False,
                "runtime_interruption_recorded": False,
                "reason": "reconciliation_failed",
                "failure_code": str(code or ""),
            }

    def record_chat_turn_run_runtime_interruption(
        self,
        run: RuntimeRun,
        *,
        code: str,
        reason: str = "",
        orphaned_by: str = "",
    ) -> dict[str, Any]:
        current = self.run_registry.get_run(run.stream_run_id) or run
        failure_code = str(code or "runtime_stream_interrupted").strip() or "runtime_stream_interrupted"
        failure_reason = str(reason or failure_code).strip() or failure_code
        diagnostics = _runtime_interruption_diagnostics(
            stream_run_id=current.stream_run_id,
            failure_code=failure_code,
            failure_reason=failure_reason,
            orphaned_by=orphaned_by,
        )
        turn_run = self._turn_run_for_stream_run(current)
        turn_run_recorded = False
        if turn_run is not None:
            latest = self.state_index.get_turn_run(turn_run.turn_run_id) or turn_run
            self.state_index.upsert_turn_run(
                replace(
                    latest,
                    updated_at=time.time(),
                    diagnostics={
                        **dict(latest.diagnostics or {}),
                        **diagnostics,
                    },
                )
            )
            turn_run_recorded = True
        current = self.run_registry.update_run(
            current.stream_run_id,
            status="orphaned",
            terminal_event="",
            owner_process_id=0,
            owner_instance_id="",
            diagnostics=diagnostics,
        )
        return {
            "authority": "single_agent_runtime_host.chat_turn_runtime_interruption",
            "stream_run_id": current.stream_run_id,
            "turn_run_id": str(getattr(turn_run, "turn_run_id", "") or ""),
            "turn_run_closed": False,
            "turn_run_interruption_recorded": turn_run_recorded,
            "public_terminal_event_appended": False,
            "runtime_interruption_recorded": True,
            "failure_code": failure_code,
        }

    def _turn_run_for_stream_run(self, run: RuntimeRun) -> Any | None:
        for turn_run_id in _turn_run_id_candidates_for_runtime_run(run):
            turn_run = self.state_index.get_turn_run(turn_run_id)
            if turn_run is not None:
                return turn_run
        return None

    def _current_permission_mode(self) -> str:
        provider = self.permission_mode_provider
        if callable(provider):
            try:
                mode = str(provider() or "").strip()
            except Exception:
                return "default"
            if mode:
                return mode
        return "default"

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

    def run_task_run_retention_maintenance(self, *, limit: int = 240) -> dict[str, Any]:
        return self.runtime_monitor_service.run_lifecycle_retention_maintenance(limit=limit)

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
        if run.owner_instance_id == owner_instance_id:
            return False
        if run.owner_process_id and _process_is_alive(int(run.owner_process_id)):
            return False
        return True
    if run.owner_process_id:
        run_owner_pid = int(run.owner_process_id)
        if run_owner_pid == int(owner_process_id):
            return False
        return not _process_is_alive(run_owner_pid)
    return True


def _process_is_alive(process_id: int) -> bool:
    pid = int(process_id or 0)
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
    try:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        synchronize = 0x00100000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information | synchronize,
            False,
            pid,
        )
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return bool(ok) and int(exit_code.value) == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False


def _orphaned_chat_run_needs_interruption_record(run: RuntimeRun) -> bool:
    if run.status != "orphaned":
        return False
    if not str(run.event_log_id or "").startswith("chatrun:"):
        return False
    diagnostics = dict(run.diagnostics or {})
    reason = str(diagnostics.get("reason") or "").strip()
    if diagnostics.get("semantic_terminal") is False and diagnostics.get("recoverable") is True:
        return False
    return reason in _RECOVERABLE_RUNTIME_INTERRUPTION_CODES or diagnostics.get("cancelled") is True


def _orphaned_chat_run_failure_reason(failure_code: str) -> str:
    code = str(failure_code or "").strip()
    if code == "stream_cancelled":
        return "runtime_cell_cancelled"
    return "runtime_cell_missing_after_restart"


_RECOVERABLE_RUNTIME_INTERRUPTION_CODES = frozenset(
    {
        "runtime_process_restarted",
        "runtime_cell_missing_after_restart",
        "runtime_cell_cancelled",
        "stream_cancelled",
        "stream_exception",
        "missing_terminal_event",
        "projection_stream_exception",
        "projection_stream_missing_terminal",
        "task_bridge_context_missing",
    }
)


def _runtime_interruption_diagnostics(
    *,
    stream_run_id: str,
    failure_code: str,
    failure_reason: str,
    orphaned_by: str,
) -> dict[str, Any]:
    code = str(failure_code or "runtime_stream_interrupted").strip() or "runtime_stream_interrupted"
    reason = str(failure_reason or code).strip() or code
    recovery_kind = "runtime_process_restarted" if code in {"runtime_process_restarted", "runtime_cell_missing_after_restart"} else "runtime_stream_interrupted"
    return {
        "runtime_interruption_event_type": "runtime_interruption_recorded",
        "runtime_interruption_code": code,
        "runtime_interruption_reason": reason,
        "recovery_kind": recovery_kind,
        "failure_code": code,
        "failure_reason": reason,
        "interrupted_stream_run_id": str(stream_run_id or "").strip(),
        "stream_run_id": str(stream_run_id or "").strip(),
        "orphaned_by": str(orphaned_by or "").strip(),
        "reason": code,
        "recoverable": True,
        "semantic_terminal": False,
    }


def _turn_run_id_candidates_for_runtime_run(run: RuntimeRun) -> list[str]:
    diagnostics = dict(run.diagnostics or {})
    candidates = [
        str(diagnostics.get("runtime_turn_run_id") or "").strip(),
        str(diagnostics.get("turn_run_id") or "").strip(),
    ]
    stream_run_id = str(run.stream_run_id or "").strip()
    if stream_run_id:
        candidates.append(f"turnrun:{stream_run_id}")
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result
