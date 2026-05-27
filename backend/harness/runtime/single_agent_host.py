from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from capability_system import build_default_operation_registry
from capability_system.tool_authorization import ToolAuthorizationIndex, build_tool_authorization_index
from permissions import OperationGate
from project_layout import ProjectLayout
from runtime.memory.state_index import RuntimeStateIndex
from runtime.shared.event_log import RuntimeEventLog
from runtime.shared.execution_record import RuntimeExecutionStore
from runtime.shared.runtime_object_store import RuntimeObjectStore


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
        tool_authorization_index: ToolAuthorizationIndex | None = None,
        tool_definitions: list[Any] | tuple[Any, ...] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.backend_dir = Path(backend_dir) if backend_dir is not None else ProjectLayout.from_runtime_root(self.root_dir).backend_dir
        self.event_log = RuntimeEventLog(self.root_dir)
        self.execution_store = RuntimeExecutionStore(self.root_dir)
        self.state_index = RuntimeStateIndex(self.root_dir)
        self.runtime_objects = RuntimeObjectStore(self.root_dir)
        self.operation_gate = operation_gate or OperationGate(build_default_operation_registry())
        self.permission_mode_provider = permission_mode_provider
        self.tool_authorization_index = tool_authorization_index or build_tool_authorization_index(
            tuple(tool_definitions or ())
        )

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
        return {
            "session_id": session_id,
            "task_run_count": len(task_runs),
            "task_runs": [self._task_run_summary(item) for item in task_runs],
            "authority": "single_agent_runtime_host.session_traces",
        }

    def list_global_live_monitor(self, limit: int = 20) -> dict[str, Any]:
        requested_limit = max(1, min(int(limit or 20), 100))
        task_runs = sorted(
            self.state_index.list_task_runs(),
            key=lambda item: item.updated_at,
            reverse=True,
        )[:requested_limit]
        return {
            "authority": "single_agent_runtime_host.global_live_monitor",
            "summary": {
                "total": len(task_runs),
                "running": sum(1 for item in task_runs if item.status == "running"),
                "waiting": sum(1 for item in task_runs if item.status in {"waiting_executor", "waiting_approval", "blocked"}),
                "completed": sum(1 for item in task_runs if item.status == "completed"),
                "failed": sum(1 for item in task_runs if item.status in {"failed", "aborted"}),
            },
            "task_runs": [self._task_run_live_summary(item) for item in task_runs],
        }

    def get_session_live_monitor(self, session_id: str) -> dict[str, Any]:
        task_runs = sorted(
            self.state_index.list_session_task_runs(session_id),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        active = [item for item in task_runs if item.status in {"created", "running", "waiting_executor", "waiting_approval", "blocked"}]
        latest = active[0] if active else (task_runs[0] if task_runs else None)
        return {
            "session_id": session_id,
            "active_task_run_id": latest.task_run_id if latest is not None else "",
            "task_runs": [self._task_run_live_summary(item) for item in task_runs[:20]],
            "authority": "single_agent_runtime_host.session_live_monitor",
        }

    def get_task_run_live_monitor(self, task_run_id: str) -> dict[str, Any] | None:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            return None
        return self._task_run_live_summary(task_run)

    def get_trace(
        self,
        task_run_id: str,
        *,
        include_payloads: bool = False,
        include_model_messages: bool = False,
    ) -> dict[str, Any] | None:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            return None
        events = [item.to_dict() for item in self.event_log.list_events(task_run_id)]
        if not include_payloads:
            events = [
                {
                    **event,
                    "payload": _redact_payload(dict(event.get("payload") or {}), include_model_messages=include_model_messages),
                }
                for event in events
            ]
        return {
            "task_run": task_run.to_dict(),
            "events": events,
            "event_count": len(events),
            "authority": "single_agent_runtime_host.task_run_trace",
        }

    def get_task_run_artifacts(self, task_run_id: str) -> dict[str, Any]:
        return {
            "task_run_id": task_run_id,
            "artifact_refs": [],
            "created_files": [],
            "authority": "single_agent_runtime_host.task_run_artifacts",
        }

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
        return {
            "task_run_id": task_run.task_run_id,
            "session_id": task_run.session_id,
            "task_id": task_run.task_id,
            "status": task_run.status,
            "runtime_lane": task_run.runtime_lane,
            "created_at": task_run.created_at,
            "updated_at": task_run.updated_at,
            "terminal_reason": task_run.terminal_reason,
            "latest_event_offset": task_run.latest_event_offset,
        }

    def _task_run_live_summary(self, task_run: Any) -> dict[str, Any]:
        events = self.event_log.list_events(task_run.task_run_id)
        latest_event = events[-1].to_dict() if events else {}
        return {
            **self._task_run_summary(task_run),
            "is_live": task_run.status in {"created", "running", "waiting_executor", "waiting_approval", "blocked"},
            "event_count": len(events),
            "latest_event": latest_event,
            "authority": "single_agent_runtime_host.task_run_live_summary",
        }


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
