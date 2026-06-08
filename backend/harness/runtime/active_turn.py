from __future__ import annotations

import time
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal


_TERMINAL_TASK_RUN_STATUSES = {"completed", "success", "failed", "aborted", "cancelled", "error"}


ActiveTurnState = Literal[
    "starting",
    "model_turn",
    "running_task",
    "waiting_executor",
    "waiting_user",
    "interrupting",
    "terminal",
]


@dataclass(frozen=True, slots=True)
class ActiveTurnRecord:
    session_id: str
    turn_id: str
    turn_run_id: str
    state: ActiveTurnState = "starting"
    bound_task_run_id: str = ""
    stream_run_id: str = ""
    started_at: float = 0.0
    updated_at: float = 0.0
    owner_instance_id: str = ""
    steerable: bool = True
    terminal_reason: str = ""
    authority: str = "harness.runtime.active_turn"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.active_turn":
            raise ValueError("ActiveTurnRecord authority must be harness.runtime.active_turn")
        if not self.session_id:
            raise ValueError("ActiveTurnRecord requires session_id")
        if not self.turn_id:
            raise ValueError("ActiveTurnRecord requires turn_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActiveTurnRegistry:
    """Owns the current active turn handle for a session.

    This registry is intentionally separate from TaskRun and RuntimeRun. TaskRun
    records task lifecycle, RuntimeRun records transport/SSE, and this object is
    the only current-turn authority.
    """

    object_kind = "active_turn"

    def __init__(self, runtime_host: Any) -> None:
        self.runtime_host = runtime_host

    def snapshot(self, session_id: str) -> ActiveTurnRecord | None:
        payload = self._read_session_payload(session_id)
        if not payload:
            return None
        record = _record_from_payload(payload)
        if record is None or record.state == "terminal":
            return None
        if not self._owned_by_current_runtime_instance(record):
            self._update(
                record,
                state="terminal",
                steerable=False,
                terminal_reason="runtime_instance_restarted",
            )
            return None
        return record

    def resolve_current(self, session_id: str) -> ActiveTurnRecord | None:
        record = self.snapshot(session_id)
        if record is None or not record.bound_task_run_id:
            return record
        task_run = getattr(getattr(self.runtime_host, "state_index", None), "get_task_run", lambda _task_run_id: None)(
            record.bound_task_run_id
        )
        if task_run is None:
            self._update(record, state="terminal", steerable=False, terminal_reason="bound_task_run_missing")
            return None
        status = str(getattr(task_run, "status", "") or "").strip()
        if status in _TERMINAL_TASK_RUN_STATUSES:
            self._update(
                record,
                state="terminal",
                steerable=False,
                terminal_reason=f"bound_task_run_terminal:{status}",
            )
            return None
        return record

    def start(
        self,
        *,
        session_id: str,
        turn_id: str,
        turn_run_id: str = "",
        stream_run_id: str = "",
        state: ActiveTurnState = "starting",
        steerable: bool = True,
    ) -> ActiveTurnRecord:
        current = self.resolve_current(session_id)
        if current is not None and current.turn_id != turn_id:
            raise ActiveTurnConflict(current)
        now = time.time()
        record = ActiveTurnRecord(
            session_id=str(session_id or "").strip(),
            turn_id=str(turn_id or "").strip(),
            turn_run_id=str(turn_run_id or "").strip(),
            state=state,
            stream_run_id=str(stream_run_id or "").strip(),
            started_at=current.started_at if current is not None else now,
            updated_at=now,
            owner_instance_id=str(getattr(self.runtime_host, "instance_id", "") or ""),
            steerable=bool(steerable),
            bound_task_run_id=current.bound_task_run_id if current is not None else "",
        )
        self._write(record)
        return record

    def bind_turn_run(self, *, session_id: str, turn_id: str, turn_run_id: str) -> ActiveTurnRecord | None:
        record = self.resolve_current(session_id)
        if record is None or record.turn_id != turn_id:
            return record
        return self._update(record, turn_run_id=str(turn_run_id or "").strip(), state="model_turn")

    def bind_stream_run(self, *, session_id: str, turn_id: str, stream_run_id: str) -> ActiveTurnRecord | None:
        record = self.resolve_current(session_id)
        if record is None or record.turn_id != turn_id:
            return record
        return self._update(record, stream_run_id=str(stream_run_id or "").strip())

    def bind_task_run(
        self,
        *,
        session_id: str,
        turn_id: str,
        task_run_id: str,
        state: ActiveTurnState = "waiting_executor",
    ) -> ActiveTurnRecord | None:
        record = self.resolve_current(session_id)
        if record is None or record.turn_id != turn_id:
            return record
        return self._update(record, bound_task_run_id=str(task_run_id or "").strip(), state=state)

    def complete(self, *, session_id: str, expected_turn_id: str, terminal_reason: str) -> ActiveTurnRecord | None:
        record = self.resolve_current(session_id)
        if record is None:
            return None
        if expected_turn_id and record.turn_id != expected_turn_id:
            raise ActiveTurnMismatch(expected=expected_turn_id, actual=record.turn_id)
        return self._update(record, state="terminal", steerable=False, terminal_reason=str(terminal_reason or "completed"))

    def complete_bound_task(self, *, session_id: str, task_run_id: str, terminal_reason: str) -> ActiveTurnRecord | None:
        record = self.snapshot(session_id)
        if record is None:
            return None
        expected_task_run_id = str(task_run_id or "").strip()
        if not expected_task_run_id or record.bound_task_run_id != expected_task_run_id:
            return record
        return self._update(record, state="terminal", steerable=False, terminal_reason=str(terminal_reason or "completed"))

    def clear_session(self, session_id: str, *, reason: str = "session_deleted") -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        if not normalized:
            return {
                "authority": "harness.runtime.active_turn.clear_session",
                "session_id": "",
                "deleted": False,
            }
        payload = self._read_session_payload(normalized)
        ref = f"rtobj:{self.object_kind}:{self._session_object_id(normalized)}"
        deleted = False
        if payload:
            try:
                terminal = _record_from_payload(payload)
                if terminal is not None:
                    self._update(terminal, state="terminal", steerable=False, terminal_reason=str(reason or "session_deleted"))
            except Exception:
                pass
            try:
                deleted = self.runtime_host.runtime_objects.delete_ref(ref)
            except Exception:
                deleted = False
        return {
            "authority": "harness.runtime.active_turn.clear_session",
            "session_id": normalized,
            "deleted": deleted,
        }

    def _update(self, record: ActiveTurnRecord, **changes: Any) -> ActiveTurnRecord:
        updated = replace(record, updated_at=time.time(), **changes)
        self._write(updated)
        return updated

    def _write(self, record: ActiveTurnRecord) -> None:
        self.runtime_host.runtime_objects.put_object(self.object_kind, self._session_object_id(record.session_id), record.to_dict())

    def _read_session_payload(self, session_id: str) -> dict[str, Any]:
        ref = f"rtobj:{self.object_kind}:{self._session_object_id(session_id)}"
        try:
            return dict(self.runtime_host.runtime_objects.get_object(ref) or {})
        except Exception:
            return {}

    def _owned_by_current_runtime_instance(self, record: ActiveTurnRecord) -> bool:
        current_instance_id = str(getattr(self.runtime_host, "instance_id", "") or "").strip()
        if not current_instance_id:
            return True
        return str(record.owner_instance_id or "").strip() == current_instance_id

    @staticmethod
    def _session_object_id(session_id: str) -> str:
        return "session_" + "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(session_id or ""))[:160]


class ActiveTurnConflict(RuntimeError):
    def __init__(self, active_turn: ActiveTurnRecord) -> None:
        super().__init__(f"active turn already exists: {active_turn.turn_id}")
        self.active_turn = active_turn


class ActiveTurnMismatch(RuntimeError):
    def __init__(self, *, expected: str, actual: str) -> None:
        super().__init__(f"expected active turn {expected}, actual {actual}")
        self.expected = expected
        self.actual = actual


def _record_from_payload(payload: dict[str, Any]) -> ActiveTurnRecord | None:
    try:
        return ActiveTurnRecord(
            session_id=str(payload.get("session_id") or ""),
            turn_id=str(payload.get("turn_id") or ""),
            turn_run_id=str(payload.get("turn_run_id") or ""),
            state=_state(payload.get("state")),
            bound_task_run_id=str(payload.get("bound_task_run_id") or ""),
            stream_run_id=str(payload.get("stream_run_id") or ""),
            started_at=float(payload.get("started_at") or 0.0),
            updated_at=float(payload.get("updated_at") or 0.0),
            owner_instance_id=str(payload.get("owner_instance_id") or ""),
            steerable=bool(payload.get("steerable", True)),
            terminal_reason=str(payload.get("terminal_reason") or ""),
        )
    except Exception:
        return None


def _state(value: Any) -> ActiveTurnState:
    raw = str(value or "").strip()
    if raw in {"starting", "model_turn", "running_task", "waiting_executor", "waiting_user", "interrupting", "terminal"}:
        return raw  # type: ignore[return-value]
    return "starting"
