from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryEnvironmentContext:
    task_environment_id: str = ""
    environment_kind: str = ""
    project_id: str = ""
    turn_id: str = ""
    task_run_id: str = ""
    source: str = ""
    authority: str = "memory_system.environment_context"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def resolve_memory_environment_context(
    *,
    explicit: dict[str, Any] | None = None,
    main_context: dict[str, Any] | None = None,
    runtime_assembly: Any | None = None,
    session_record: dict[str, Any] | None = None,
    turn_id: str = "",
    task_run_id: str = "",
    task_selection: dict[str, Any] | None = None,
    active_work_context: dict[str, Any] | None = None,
    recent_work_outcome: dict[str, Any] | None = None,
) -> MemoryEnvironmentContext:
    resolved: dict[str, str] = {
        "task_environment_id": "",
        "environment_kind": "",
        "project_id": "",
        "turn_id": _text(turn_id),
        "task_run_id": _text(task_run_id),
        "source": "",
    }

    for source, payload in _candidate_sources(
        explicit=explicit,
        main_context=main_context,
        runtime_assembly=runtime_assembly,
        session_record=session_record,
        turn_id=turn_id,
        task_run_id=task_run_id,
        task_selection=task_selection,
        active_work_context=active_work_context,
        recent_work_outcome=recent_work_outcome,
    ):
        candidate = _environment_payload(payload)
        if not candidate:
            continue
        _fill(resolved, "task_environment_id", candidate.get("task_environment_id"))
        _fill(resolved, "environment_kind", candidate.get("environment_kind"))
        _fill(resolved, "project_id", candidate.get("project_id"))
        _fill(resolved, "turn_id", candidate.get("turn_id"))
        _fill(resolved, "task_run_id", candidate.get("task_run_id"))
        if not resolved["source"] and any(candidate.get(key) for key in ("task_environment_id", "environment_kind", "project_id")):
            resolved["source"] = source

    return MemoryEnvironmentContext(**resolved)


def _candidate_sources(
    *,
    explicit: dict[str, Any] | None,
    main_context: dict[str, Any] | None,
    runtime_assembly: Any | None,
    session_record: dict[str, Any] | None,
    turn_id: str,
    task_run_id: str,
    task_selection: dict[str, Any] | None,
    active_work_context: dict[str, Any] | None,
    recent_work_outcome: dict[str, Any] | None,
) -> list[tuple[str, Any]]:
    main = dict(main_context or {})
    assembly = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    record = dict(session_record or {})
    state = dict(record.get("conversation_state") or {})
    sources: list[tuple[str, Any]] = [
        ("explicit", explicit or {}),
        ("main_context.task_environment", main.get("task_environment") if isinstance(main.get("task_environment"), dict) else {}),
        ("main_context", main),
        ("runtime_assembly.task_environment", assembly.get("task_environment") if isinstance(assembly.get("task_environment"), dict) else {}),
        ("task_selection", task_selection or {}),
        ("active_work_context", _dict_payload(active_work_context)),
        ("recent_work_outcome", _dict_payload(recent_work_outcome)),
        (
            "session_record.turn_environment_snapshot",
            latest_turn_environment_snapshot(record, turn_id=turn_id, task_run_id=task_run_id),
        ),
        (
            "session_record.active_task_environment",
            state.get("active_task_environment") if isinstance(state.get("active_task_environment"), dict) else {},
        ),
        ("session_record.scope", record.get("scope") if isinstance(record.get("scope"), dict) else {}),
        ("session_record.task_binding", record.get("task_binding") if isinstance(record.get("task_binding"), dict) else {}),
    ]
    return sources


def latest_turn_environment_snapshot(
    session_record: dict[str, Any] | None,
    *,
    turn_id: str = "",
    task_run_id: str = "",
) -> dict[str, Any]:
    messages = [item for item in list(dict(session_record or {}).get("messages") or []) if isinstance(item, dict)]
    normalized_turn = _text(turn_id)
    normalized_task_run = _text(task_run_id)
    if normalized_turn:
        for item in reversed(messages):
            snapshot = item.get("turn_environment_snapshot")
            if str(item.get("turn_id") or "").strip() == normalized_turn and isinstance(snapshot, dict):
                return dict(snapshot)
    if normalized_task_run:
        for item in reversed(messages):
            snapshot = item.get("turn_environment_snapshot")
            if isinstance(snapshot, dict) and _text(snapshot.get("task_run_id")) == normalized_task_run:
                return dict(snapshot)
    for item in reversed(messages):
        snapshot = item.get("turn_environment_snapshot")
        if isinstance(snapshot, dict) and _text(snapshot.get("task_environment_id") or snapshot.get("environment_id")):
            return dict(snapshot)
    return {}


def _environment_payload(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("task_environment")
    if isinstance(nested, dict):
        payload = {**nested, **payload}
    return {
        "task_environment_id": _text(
            payload.get("task_environment_id")
            or payload.get("environment_id")
            or payload.get("requested_environment_id")
        ),
        "environment_kind": _text(payload.get("environment_kind") or payload.get("kind")),
        "project_id": _text(payload.get("project_id")),
        "turn_id": _text(payload.get("turn_id")),
        "task_run_id": _text(payload.get("task_run_id")),
    }


def _dict_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return dict(value or {}) if isinstance(value, dict) else {}


def _fill(target: dict[str, str], key: str, value: Any) -> None:
    if not target.get(key):
        target[key] = _text(value)


def _text(value: Any) -> str:
    return str(value or "").strip()
