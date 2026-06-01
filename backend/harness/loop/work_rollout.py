from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from harness.runtime.public_progress import public_runtime_progress_summary


WorkRolloutItemType = Literal[
    "progress",
    "user_instruction",
    "pause_boundary",
    "interrupted_boundary",
    "final_response",
]


@dataclass(frozen=True, slots=True)
class WorkRolloutItem:
    item_id: str
    item_type: WorkRolloutItemType
    title: str
    status: str
    summary: str
    agent_brief_output: str = ""
    event_offset: int = -1
    refs: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "runtime.work_rollout_item"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkRolloutRecord:
    rollout_id: str
    session_id: str
    logical_work_id: str
    root_task_run_id: str
    current_task_run_id: str
    status: str = "running"
    lineage: dict[str, Any] = field(default_factory=dict)
    model_visible_history: tuple[dict[str, Any], ...] = ()
    progress_timeline: tuple[dict[str, Any], ...] = ()
    latest_progress: str = ""
    latest_step_title: str = ""
    agent_brief_output: str = ""
    latest_event_offset: int = -1
    latest_checkpoint_ref: str = ""
    artifact_refs: tuple[dict[str, Any], ...] = ()
    runtime_fingerprint: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0
    authority: str = "runtime.work_rollout"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["model_visible_history"] = [dict(item) for item in self.model_visible_history]
        payload["progress_timeline"] = [dict(item) for item in self.progress_timeline]
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        return payload


def work_rollout_ref(task_run_id: str) -> str:
    return f"rtobj:work_rollout:{_safe_object_id(task_run_id)}"


def load_work_rollout(runtime_host: Any, task_run_id: str) -> WorkRolloutRecord | None:
    ref = work_rollout_ref(task_run_id)
    try:
        payload = dict(runtime_host.runtime_objects.get_object(ref) or {})
    except Exception:
        payload = {}
    if not payload:
        return None
    return _record_from_payload(payload)


def ensure_work_rollout(
    runtime_host: Any,
    task_run: Any,
    *,
    lineage: dict[str, Any] | None = None,
    status: str | None = None,
) -> WorkRolloutRecord:
    existing = load_work_rollout(runtime_host, str(getattr(task_run, "task_run_id", "") or ""))
    if existing is not None:
        return _sync_rollout_record(runtime_host, existing, task_run, lineage=lineage, status=status)
    now = time.time()
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    root_task_run_id = str(diagnostics.get("root_task_run_id") or getattr(task_run, "task_run_id", "") or "")
    logical_work_id = str(diagnostics.get("logical_work_id") or root_task_run_id or getattr(task_run, "task_id", "") or "")
    record = WorkRolloutRecord(
        rollout_id=f"workrollout:{getattr(task_run, 'task_run_id', '')}",
        session_id=str(getattr(task_run, "session_id", "") or ""),
        logical_work_id=logical_work_id,
        root_task_run_id=root_task_run_id,
        current_task_run_id=str(getattr(task_run, "task_run_id", "") or ""),
        status=status or str(getattr(task_run, "status", "") or "running"),
        lineage=dict(lineage or diagnostics.get("lineage") or {}),
        latest_event_offset=_int_value(getattr(task_run, "latest_event_offset", -1), -1),
        latest_checkpoint_ref=str(getattr(task_run, "latest_checkpoint_ref", "") or ""),
        created_at=now,
        updated_at=now,
    )
    _put_work_rollout(runtime_host, record)
    return record


def append_work_rollout_item(
    runtime_host: Any,
    *,
    task_run: Any,
    item_type: WorkRolloutItemType = "progress",
    title: str,
    status: str,
    summary: str,
    agent_brief_output: str = "",
    event_offset: int = -1,
    refs: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> WorkRolloutRecord:
    record = ensure_work_rollout(runtime_host, task_run, status=str(getattr(task_run, "status", "") or status or "running"))
    visible_summary = public_runtime_progress_summary(summary) or str(summary or "").strip()
    brief = public_runtime_progress_summary(agent_brief_output) or str(agent_brief_output or "").strip()
    item_refs = dict(refs or {})
    item_payload = dict(payload or {})
    checkpoint_ref = _first_text(
        item_payload.get("checkpoint_ref"),
        item_payload.get("latest_checkpoint_ref"),
        item_refs.get("checkpoint_ref"),
        getattr(task_run, "latest_checkpoint_ref", ""),
        record.latest_checkpoint_ref,
    )
    if checkpoint_ref:
        item_refs.setdefault("checkpoint_ref", checkpoint_ref)
    resolved_event_offset = _resolved_event_offset(
        explicit_offset=event_offset,
        task_run=task_run,
        fallback=record.latest_event_offset,
    )
    item = WorkRolloutItem(
        item_id=f"writem:{_safe_object_id(str(getattr(task_run, 'task_run_id', '') or 'work'))}:{uuid.uuid4().hex[:8]}",
        item_type=item_type,
        title=str(title or "").strip() or _title_for_item(item_type, status),
        status=str(status or "").strip() or str(getattr(task_run, "status", "") or "running"),
        summary=visible_summary,
        agent_brief_output=brief,
        event_offset=resolved_event_offset,
        refs=item_refs,
        payload=item_payload,
        created_at=time.time(),
    )
    timeline = [*record.progress_timeline, item.to_dict()][-80:]
    model_history = [*record.model_visible_history, _model_history_item(item)][-80:]
    artifact_refs = _dedupe_artifacts(
        [
            *list(record.artifact_refs or ()),
            *[dict(ref) for ref in list(item_payload.get("artifact_refs") or []) if isinstance(ref, dict)],
        ]
    )
    updated = replace(
        record,
        status=item.status,
        progress_timeline=tuple(timeline),
        model_visible_history=tuple(model_history),
        latest_progress=visible_summary or record.latest_progress,
        latest_step_title=item.title or record.latest_step_title,
        agent_brief_output=brief or record.agent_brief_output,
        latest_event_offset=max(record.latest_event_offset, resolved_event_offset),
        latest_checkpoint_ref=checkpoint_ref or record.latest_checkpoint_ref,
        artifact_refs=tuple(artifact_refs),
        updated_at=item.created_at,
    )
    _put_work_rollout(runtime_host, updated)
    return updated


def work_rollout_summary(runtime_host: Any, task_run: Any | str) -> dict[str, Any]:
    task_run_id = str(task_run if isinstance(task_run, str) else getattr(task_run, "task_run_id", "") or "")
    record = load_work_rollout(runtime_host, task_run_id)
    if record is None:
        if isinstance(task_run, str):
            return {}
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        return {
            "rollout_id": "",
            "latest_progress": public_runtime_progress_summary(diagnostics.get("latest_step_summary") or ""),
            "latest_step_title": str(diagnostics.get("latest_step") or ""),
            "agent_brief_output": "",
            "progress_timeline": [],
            "model_visible_history": [],
            "latest_event_offset": _int_value(getattr(task_run, "latest_event_offset", -1), -1),
            "latest_checkpoint_ref": str(getattr(task_run, "latest_checkpoint_ref", "") or ""),
            "breakpoint": _breakpoint_payload(
                latest_event_offset=_int_value(getattr(task_run, "latest_event_offset", -1), -1),
                latest_checkpoint_ref=str(getattr(task_run, "latest_checkpoint_ref", "") or ""),
                status=str(getattr(task_run, "status", "") or ""),
                latest_step_title=str(diagnostics.get("latest_step") or ""),
                latest_progress=public_runtime_progress_summary(diagnostics.get("latest_step_summary") or ""),
            ),
            "artifact_refs": list(diagnostics.get("artifact_refs") or []),
            "authority": "runtime.work_rollout_summary.fallback",
        }
    return {
        "rollout_id": record.rollout_id,
        "logical_work_id": record.logical_work_id,
        "root_task_run_id": record.root_task_run_id,
        "current_task_run_id": record.current_task_run_id,
        "status": record.status,
        "lineage": dict(record.lineage or {}),
        "latest_progress": record.latest_progress,
        "latest_step_title": record.latest_step_title,
        "agent_brief_output": record.agent_brief_output,
        "progress_timeline": [dict(item) for item in record.progress_timeline[-12:]],
        "model_visible_history": [dict(item) for item in record.model_visible_history[-18:]],
        "latest_event_offset": record.latest_event_offset,
        "latest_checkpoint_ref": record.latest_checkpoint_ref,
        "breakpoint": _breakpoint_payload(
            latest_event_offset=record.latest_event_offset,
            latest_checkpoint_ref=record.latest_checkpoint_ref,
            status=record.status,
            latest_step_title=record.latest_step_title,
            latest_progress=record.latest_progress,
        ),
        "artifact_refs": [dict(item) for item in record.artifact_refs],
        "authority": "runtime.work_rollout_summary",
    }


def _put_work_rollout(runtime_host: Any, record: WorkRolloutRecord) -> str:
    return runtime_host.runtime_objects.put_object(
        "work_rollout",
        record.current_task_run_id,
        record.to_dict(),
    )


def _record_from_payload(payload: dict[str, Any]) -> WorkRolloutRecord:
    return WorkRolloutRecord(
        rollout_id=str(payload.get("rollout_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        logical_work_id=str(payload.get("logical_work_id") or ""),
        root_task_run_id=str(payload.get("root_task_run_id") or ""),
        current_task_run_id=str(payload.get("current_task_run_id") or ""),
        status=str(payload.get("status") or ""),
        lineage=dict(payload.get("lineage") or {}),
        model_visible_history=tuple(dict(item) for item in list(payload.get("model_visible_history") or []) if isinstance(item, dict)),
        progress_timeline=tuple(dict(item) for item in list(payload.get("progress_timeline") or []) if isinstance(item, dict)),
        latest_progress=str(payload.get("latest_progress") or ""),
        latest_step_title=str(payload.get("latest_step_title") or ""),
        agent_brief_output=str(payload.get("agent_brief_output") or ""),
        latest_event_offset=_int_value(payload.get("latest_event_offset"), -1),
        latest_checkpoint_ref=str(payload.get("latest_checkpoint_ref") or ""),
        artifact_refs=tuple(dict(item) for item in list(payload.get("artifact_refs") or []) if isinstance(item, dict)),
        runtime_fingerprint=dict(payload.get("runtime_fingerprint") or {}),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
    )


def _model_history_item(item: WorkRolloutItem) -> dict[str, Any]:
    return {
        "type": item.item_type,
        "title": item.title,
        "status": item.status,
        "summary": item.summary,
        "agent_brief_output": item.agent_brief_output,
        "event_offset": item.event_offset,
        "refs": dict(item.refs or {}),
        "created_at": item.created_at,
        "authority": "runtime.work_rollout.model_visible_history",
    }


def _title_for_item(item_type: str, status: str) -> str:
    if item_type == "user_instruction":
        return "收到补充要求"
    if item_type == "pause_boundary":
        return "已暂停"
    if item_type == "interrupted_boundary":
        return "已中断"
    if item_type == "final_response":
        return "已完成"
    if status in {"waiting_executor", "blocked"}:
        return "等待继续"
    return "处理进展"


def _dedupe_artifacts(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        key = str(ref.get("absolute_path") or ref.get("path") or ref.get("src") or ref)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(dict(ref))
    return result


def _sync_rollout_record(
    runtime_host: Any,
    record: WorkRolloutRecord,
    task_run: Any,
    *,
    lineage: dict[str, Any] | None,
    status: str | None,
) -> WorkRolloutRecord:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    merged_lineage = {
        **dict(record.lineage or {}),
        **(dict(diagnostics.get("lineage") or {}) if isinstance(diagnostics.get("lineage"), dict) else {}),
        **dict(lineage or {}),
    }
    latest_checkpoint_ref = _first_text(getattr(task_run, "latest_checkpoint_ref", ""), record.latest_checkpoint_ref)
    task_run_event_offset = _int_value(getattr(task_run, "latest_event_offset", -1), -1)
    latest_event_offset = record.latest_event_offset
    if not record.progress_timeline or latest_event_offset < 0:
        latest_event_offset = max(record.latest_event_offset, task_run_event_offset)
    next_status = str(status or getattr(task_run, "status", "") or record.status or "running")
    root_task_run_id = record.root_task_run_id or str(diagnostics.get("root_task_run_id") or getattr(task_run, "task_run_id", "") or "")
    logical_work_id = record.logical_work_id or str(diagnostics.get("logical_work_id") or root_task_run_id or getattr(task_run, "task_id", "") or "")
    if (
        next_status == record.status
        and merged_lineage == dict(record.lineage or {})
        and latest_checkpoint_ref == record.latest_checkpoint_ref
        and latest_event_offset == record.latest_event_offset
        and root_task_run_id == record.root_task_run_id
        and logical_work_id == record.logical_work_id
    ):
        return record
    updated = replace(
        record,
        status=next_status,
        lineage=merged_lineage,
        logical_work_id=logical_work_id,
        root_task_run_id=root_task_run_id,
        latest_checkpoint_ref=latest_checkpoint_ref,
        latest_event_offset=latest_event_offset,
        updated_at=time.time(),
    )
    _put_work_rollout(runtime_host, updated)
    return updated


def _breakpoint_payload(
    *,
    latest_event_offset: int,
    latest_checkpoint_ref: str,
    status: str,
    latest_step_title: str,
    latest_progress: str,
) -> dict[str, Any]:
    return {
        "event_offset": _int_value(latest_event_offset, -1),
        "checkpoint_ref": str(latest_checkpoint_ref or ""),
        "status": str(status or ""),
        "latest_step_title": str(latest_step_title or ""),
        "latest_progress": str(latest_progress or ""),
        "authority": "runtime.work_rollout.breakpoint",
    }


def _resolved_event_offset(*, explicit_offset: int, task_run: Any, fallback: int) -> int:
    try:
        value = int(explicit_offset)
    except (TypeError, ValueError):
        value = -1
    if value >= 0:
        return value
    try:
        value = _int_value(getattr(task_run, "latest_event_offset", -1), -1)
    except (TypeError, ValueError):
        value = -1
    if value >= 0:
        return value
    return _int_value(fallback, -1)


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_object_id(value: str) -> str:
    raw = str(value or "")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw).strip("_")
    return safe[:180] or "work_rollout"
