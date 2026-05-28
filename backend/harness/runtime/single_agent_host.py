from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Callable

from capability_system import build_default_operation_registry
from capability_system.tool_authorization import ToolAuthorizationIndex, build_tool_authorization_index
from permissions import OperationGate
from project_layout import ProjectLayout
from harness.runtime.monitor_projection import TaskRunMonitorProjector
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
        self.monitor_projector = TaskRunMonitorProjector(self.event_log)

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
        now = time.time()
        return self.monitor_projector.build_global_monitor(self.state_index.list_task_runs(), now=now, limit=limit)

    def get_session_live_monitor(self, session_id: str) -> dict[str, Any]:
        task_runs = sorted(
            self.state_index.list_session_task_runs(session_id),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        now = time.time()
        return self.monitor_projector.build_session_monitor(session_id, task_runs, now=now)

    def get_task_run_live_monitor(self, task_run_id: str) -> dict[str, Any] | None:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            return None
        return self.monitor_projector.project_task_run(task_run, now=time.time())

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
        task_run = self.state_index.get_task_run(task_run_id)
        raw_refs: list[Any] = []
        if task_run is not None:
            raw_refs.extend(list(dict(task_run.diagnostics or {}).get("artifact_refs") or []))
        for result in self.state_index.list_task_agent_run_results(task_run_id):
            raw_refs.extend(list(result.artifact_refs or ()))
            raw_refs.extend(list(dict(result.diagnostics or {}).get("artifact_refs") or []))
        artifacts = _existing_artifact_refs(raw_refs, project_root=ProjectLayout.from_backend_dir(self.backend_dir).project_root)
        return {
            "task_run_id": task_run_id,
            "artifact_refs": artifacts,
            "created_files": [item["path"] for item in artifacts],
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


def _existing_artifact_refs(values: list[Any], *, project_root: Path) -> list[dict[str, Any]]:
    root = Path(project_root).resolve()
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        ref = dict(value) if isinstance(value, dict) else {"path": str(value or "")}
        path_text = str(ref.get("absolute_path") or ref.get("path") or ref.get("src") or "").strip()
        if not path_text:
            continue
        candidate = Path(path_text)
        resolved = candidate.resolve() if candidate.is_absolute() else (root / path_text).resolve()
        if not _inside(resolved, root) or not resolved.exists() or not resolved.is_file():
            continue
        rel = resolved.relative_to(root).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        result.append({**ref, "path": rel, "absolute_path": str(resolved), "exists": True, "size_bytes": resolved.stat().st_size})
    return result

def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
