from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal


ToolInvocationStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
ToolInvocationCallerKind = Literal["agent_turn", "task_run", "graph_node", "direct_route"]
ToolInvocationSignalKind = Literal["pause", "stop", "replan", "cancel"]

_THREAD_LOCAL = threading.local()


@dataclass(frozen=True, slots=True)
class ToolInvocationSignal:
    kind: ToolInvocationSignalKind
    tool_invocation_id: str
    reason: str
    requested_by: str
    requested_at: float
    agent_run_id: str = ""
    run_cell_id: str = ""
    caller_kind: str = ""
    caller_ref: str = ""
    task_run_id: str = ""
    turn_id: str = ""
    steer_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolInvocationContext:
    tool_invocation_id: str
    caller_kind: str
    caller_ref: str
    agent_run_id: str = ""
    run_cell_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    task_run_id: str = ""
    tool_call_id: str = ""
    idempotency_key: str = ""
    file_evidence_scope: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolInvocationRecord:
    tool_invocation_id: str
    caller_kind: str
    caller_ref: str
    agent_run_id: str = ""
    run_cell_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    task_run_id: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_call_id: str = ""
    status: ToolInvocationStatus = "queued"
    idempotency_key: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    structured_error: dict[str, Any] = field(default_factory=dict)
    result_ref: str = ""
    error: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.tool_invocation_record"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class _InvocationEntry:
    record: ToolInvocationRecord
    task: asyncio.Task[Any] | None = None
    loop: asyncio.AbstractEventLoop | None = None
    signal: ToolInvocationSignal | None = None


class ToolInvocationControlRegistry:
    def __init__(self, *, agent_run_id: str = "", run_cell_id: str = "") -> None:
        self._entries: dict[str, _InvocationEntry] = {}
        self._lock = threading.RLock()
        self.agent_run_id = str(agent_run_id or "").strip()
        self.run_cell_id = str(run_cell_id or "").strip()

    def start(
        self,
        *,
        tool_invocation_id: str,
        caller_kind: str,
        caller_ref: str,
        session_id: str = "",
        agent_run_id: str = "",
        run_cell_id: str = "",
        turn_id: str = "",
        task_run_id: str = "",
        tool_name: str = "",
        tool_args: dict[str, Any] | None = None,
        tool_call_id: str = "",
        idempotency_key: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> ToolInvocationRecord:
        now = time.time()
        record = ToolInvocationRecord(
            tool_invocation_id=str(tool_invocation_id or "").strip(),
            caller_kind=str(caller_kind or "").strip() or "agent_turn",
            caller_ref=str(caller_ref or "").strip(),
            agent_run_id=str(agent_run_id or self.agent_run_id or "").strip(),
            run_cell_id=str(run_cell_id or self.run_cell_id or "").strip(),
            session_id=str(session_id or "").strip(),
            turn_id=str(turn_id or "").strip(),
            task_run_id=str(task_run_id or "").strip(),
            tool_name=str(tool_name or "").strip(),
            tool_args=dict(tool_args or {}),
            tool_call_id=str(tool_call_id or "").strip(),
            status="running",
            idempotency_key=str(idempotency_key or "").strip(),
            started_at=now,
            diagnostics=dict(diagnostics or {}),
        )
        with self._lock:
            self._entries[record.tool_invocation_id] = _InvocationEntry(record=record)
        return record

    def attach_task(self, tool_invocation_id: str, task: asyncio.Task[Any]) -> None:
        with self._lock:
            entry = self._entries.get(str(tool_invocation_id or ""))
            if entry is None:
                return
            entry.task = task
            try:
                entry.loop = asyncio.get_running_loop()
            except RuntimeError:
                entry.loop = None
            signal = entry.signal
            loop = entry.loop
        if signal is not None and not task.done():
            _cancel_task(task, loop)

    def clear_task(self, tool_invocation_id: str, task: asyncio.Task[Any]) -> None:
        with self._lock:
            entry = self._entries.get(str(tool_invocation_id or ""))
            if entry is not None and entry.task is task:
                entry.task = None
                entry.loop = None

    def request_cancel(
        self,
        *,
        tool_invocation_id: str,
        kind: str = "cancel",
        reason: str = "",
        requested_by: str = "user",
        steer_ref: str = "",
    ) -> bool:
        task: asyncio.Task[Any] | None = None
        loop: asyncio.AbstractEventLoop | None = None
        with self._lock:
            entry = self._entries.get(str(tool_invocation_id or ""))
            if entry is None:
                return False
            record = entry.record
            signal = ToolInvocationSignal(
                kind=_signal_kind(kind),
                tool_invocation_id=record.tool_invocation_id,
                reason=str(reason or "").strip() or "tool_invocation_cancelled",
                requested_by=str(requested_by or "").strip() or "user",
                requested_at=time.time(),
                agent_run_id=record.agent_run_id,
                run_cell_id=record.run_cell_id,
                caller_kind=record.caller_kind,
                caller_ref=record.caller_ref,
                task_run_id=record.task_run_id,
                turn_id=record.turn_id,
                steer_ref=str(steer_ref or "").strip(),
            )
            entry.signal = signal
            task = entry.task
            loop = entry.loop
            entry.record = replace(
                record,
                status="cancelled",
                completed_at=record.completed_at or time.time(),
                error=signal.reason,
                diagnostics={**dict(record.diagnostics), "runtime_control": signal.to_dict()},
            )
        if task is not None and not task.done():
            _cancel_task(task, loop)
        return True

    def cancel_by_caller(
        self,
        *,
        caller_kind: str = "",
        caller_ref: str = "",
        task_run_id: str = "",
        turn_id: str = "",
        agent_run_id: str = "",
        run_cell_id: str = "",
        kind: str = "cancel",
        reason: str = "",
        requested_by: str = "user",
        steer_ref: str = "",
    ) -> int:
        scoped_agent_run_id = str(agent_run_id or self.agent_run_id or "").strip()
        scoped_run_cell_id = str(run_cell_id or self.run_cell_id or "").strip()
        count = 0
        for record in list(self.records()):
            if record.status not in {"queued", "running"}:
                continue
            if caller_kind and record.caller_kind != caller_kind:
                continue
            if caller_ref and record.caller_ref != caller_ref:
                continue
            if task_run_id and record.task_run_id != task_run_id:
                continue
            if turn_id and record.turn_id != turn_id:
                continue
            if scoped_agent_run_id and record.agent_run_id != scoped_agent_run_id:
                continue
            if scoped_run_cell_id and record.run_cell_id != scoped_run_cell_id:
                continue
            if self.request_cancel(
                tool_invocation_id=record.tool_invocation_id,
                kind=kind,
                reason=reason,
                requested_by=requested_by,
                steer_ref=steer_ref,
            ):
                count += 1
        return count

    def signal(self, tool_invocation_id: str) -> ToolInvocationSignal | None:
        with self._lock:
            entry = self._entries.get(str(tool_invocation_id or ""))
            return entry.signal if entry is not None else None

    def complete(
        self,
        tool_invocation_id: str,
        *,
        result_ref: str = "",
        artifact_refs: list[dict[str, Any]] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> ToolInvocationRecord | None:
        with self._lock:
            entry = self._entries.get(str(tool_invocation_id or ""))
            if entry is None:
                return None
            if entry.record.status == "cancelled":
                return entry.record
            entry.record = replace(
                entry.record,
                status="completed",
                completed_at=time.time(),
                result_ref=str(result_ref or ""),
                artifact_refs=[dict(item) for item in list(artifact_refs or []) if isinstance(item, dict)],
                diagnostics={**dict(entry.record.diagnostics), **dict(diagnostics or {})},
            )
            return entry.record

    def fail(
        self,
        tool_invocation_id: str,
        *,
        error: str = "",
        structured_error: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> ToolInvocationRecord | None:
        with self._lock:
            entry = self._entries.get(str(tool_invocation_id or ""))
            if entry is None:
                return None
            if entry.record.status == "cancelled":
                return entry.record
            entry.record = replace(
                entry.record,
                status="failed",
                completed_at=time.time(),
                error=str(error or ""),
                structured_error=dict(structured_error or {}),
                diagnostics={**dict(entry.record.diagnostics), **dict(diagnostics or {})},
            )
            return entry.record

    def record(self, tool_invocation_id: str) -> ToolInvocationRecord | None:
        with self._lock:
            entry = self._entries.get(str(tool_invocation_id or ""))
            return entry.record if entry is not None else None

    def records(self) -> list[ToolInvocationRecord]:
        with self._lock:
            return [entry.record for entry in self._entries.values()]


def registry_for(runtime_host: Any | None) -> ToolInvocationControlRegistry | None:
    current = getattr(_THREAD_LOCAL, "tool_invocation_registry", None)
    if isinstance(current, ToolInvocationControlRegistry):
        return current
    if runtime_host is None:
        return None
    registry = getattr(runtime_host, "_tool_invocation_control", None)
    if isinstance(registry, ToolInvocationControlRegistry):
        return registry
    scope = getattr(runtime_host, "_active_agent_run_scope", None)
    registry = ToolInvocationControlRegistry(
        agent_run_id=str(getattr(scope, "agent_run_id", "") or ""),
        run_cell_id=str(getattr(scope, "run_cell_id", "") or ""),
    )
    setattr(runtime_host, "_tool_invocation_control", registry)
    return registry


def bind_thread_tool_invocation_registry(registry: ToolInvocationControlRegistry | None) -> None:
    if registry is None:
        clear_thread_tool_invocation_registry()
        return
    setattr(_THREAD_LOCAL, "tool_invocation_registry", registry)


def clear_thread_tool_invocation_registry() -> None:
    if hasattr(_THREAD_LOCAL, "tool_invocation_registry"):
        delattr(_THREAD_LOCAL, "tool_invocation_registry")


def _cancel_task(task: asyncio.Task[Any], loop: asyncio.AbstractEventLoop | None) -> None:
    if task.done():
        return
    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(task.cancel)
        return
    task.cancel()


def build_tool_invocation_id(
    *,
    caller_ref: str,
    action_request_ref: str,
    tool_name: str,
    tool_call_id: str = "",
    agent_run_id: str = "",
    run_cell_id: str = "",
) -> str:
    raw = "::".join([
        str(agent_run_id or ""),
        str(run_cell_id or ""),
        str(caller_ref or ""),
        str(action_request_ref or ""),
        str(tool_name or ""),
        str(tool_call_id or ""),
    ])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"toolinv:{digest}"


def build_tool_invocation_idempotency_key(
    *,
    caller_ref: str = "",
    action_request_ref: str = "",
    tool_call_id: str = "",
    tool_name: str = "",
    tool_args: dict[str, Any] | None = None,
    tool_invocation_id: str = "",
    agent_run_id: str = "",
    run_cell_id: str = "",
) -> str:
    raw = json.dumps(
        {
            "caller_ref": str(caller_ref or ""),
            "agent_run_id": str(agent_run_id or ""),
            "run_cell_id": str(run_cell_id or ""),
            "action_request_ref": str(action_request_ref or ""),
            "tool_call_id": str(tool_call_id or ""),
            "tool_invocation_id": str(tool_invocation_id or ""),
            "tool_name": str(tool_name or ""),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _signal_kind(value: str) -> ToolInvocationSignalKind:
    kind = str(value or "").strip()
    if kind in {"pause", "stop", "replan", "cancel"}:
        return kind  # type: ignore[return-value]
    return "cancel"
