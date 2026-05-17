from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TimelineResultRecord:
    """Confirmed result facts for one node execution at one timeline coordinate."""

    result_record_id: str
    request_id: str
    dispatch_event_id: str
    result_event_id: str
    clock_seq: int
    scope_path: tuple[str, ...]
    stage_id: str
    node_id: str
    status: str
    accepted: bool
    produced_artifact_refs: tuple[str, ...] = ()
    produced_trace_refs: tuple[str, ...] = ()
    source_artifact_refs: tuple[str, ...] = ()
    source_result_record_ids: tuple[str, ...] = ()
    memory_write_candidate_refs: tuple[str, ...] = ()
    memory_commit_refs: tuple[str, ...] = ()
    commit_identity: str = ""
    scope_key: str = ""
    dependency_scope_key: str = ""
    timeline_coordinate: dict[str, Any] = field(default_factory=dict)
    validation_result: dict[str, Any] = field(default_factory=dict)
    effective_from_clock_seq: int = 0
    effective_scope_path: tuple[str, ...] = ()
    created_at: float = 0.0
    authority: str = "task_graph.timeline_result_record"

    def __post_init__(self) -> None:
        if self.authority != "task_graph.timeline_result_record":
            raise ValueError("TimelineResultRecord authority must be task_graph.timeline_result_record")
        if not self.result_record_id:
            raise ValueError("TimelineResultRecord requires result_record_id")
        if not self.stage_id:
            raise ValueError("TimelineResultRecord requires stage_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scope_path"] = list(self.scope_path)
        payload["produced_artifact_refs"] = list(self.produced_artifact_refs)
        payload["produced_trace_refs"] = list(self.produced_trace_refs)
        payload["source_artifact_refs"] = list(self.source_artifact_refs)
        payload["source_result_record_ids"] = list(self.source_result_record_ids)
        payload["memory_write_candidate_refs"] = list(self.memory_write_candidate_refs)
        payload["memory_commit_refs"] = list(self.memory_commit_refs)
        payload["timeline_coordinate"] = dict(self.timeline_coordinate)
        payload["effective_scope_path"] = list(self.effective_scope_path)
        payload["validation_result"] = dict(self.validation_result)
        return payload


def build_timeline_result_record(
    *,
    request_payload: dict[str, Any],
    result_event: dict[str, Any],
    stage_id: str,
    node_id: str,
    accepted: bool,
    artifact_refs: list[str] | tuple[str, ...],
    trace_refs: list[str] | tuple[str, ...] = (),
    source_artifact_refs: list[str] | tuple[str, ...] = (),
    source_result_record_ids: list[str] | tuple[str, ...] = (),
    memory_write_candidate_refs: list[str] | tuple[str, ...] = (),
    memory_commit_refs: list[str] | tuple[str, ...] = (),
    commit_identity: str = "",
    validation_result: dict[str, Any] | None = None,
) -> TimelineResultRecord:
    dispatch_context = dict(request_payload.get("dispatch_context") or {})
    clock_seq = int(result_event.get("clock_seq") or dispatch_context.get("clock_seq") or 0)
    scope_path = tuple(
        str(item)
        for item in list(result_event.get("scope_path") or dispatch_context.get("scope_path") or ["run"])
        if str(item)
    )
    scope_key = scope_key_from_path(scope_path or ("run",))
    dependency_scope_key = str(dispatch_context.get("dependency_scope_key") or "") or scope_key
    coordinate = build_timeline_coordinate(
        request_payload=request_payload,
        result_event=result_event,
        stage_id=stage_id,
        node_id=node_id,
        scope_path=scope_path or ("run",),
    )
    record_seed = {
        "request_id": str(request_payload.get("request_id") or ""),
        "result_event_id": str(result_event.get("event_id") or ""),
        "stage_id": stage_id,
        "accepted": bool(accepted),
        "artifact_refs": list(artifact_refs or []),
        "source_artifact_refs": list(source_artifact_refs or []),
        "source_result_record_ids": list(source_result_record_ids or []),
        "memory_write_candidate_refs": list(memory_write_candidate_refs or []),
        "memory_commit_refs": list(memory_commit_refs or []),
        "commit_identity": str(commit_identity or ""),
        "scope_key": scope_key,
        "dependency_scope_key": dependency_scope_key,
    }
    return TimelineResultRecord(
        result_record_id=f"tlresult:{_short_hash(record_seed)}",
        request_id=str(request_payload.get("request_id") or ""),
        dispatch_event_id=str(dispatch_context.get("dispatch_event_id") or ""),
        result_event_id=str(result_event.get("event_id") or ""),
        clock_seq=clock_seq,
        scope_path=scope_path or ("run",),
        stage_id=stage_id,
        node_id=node_id or stage_id,
        status="accepted" if accepted else "rejected",
        accepted=bool(accepted),
        produced_artifact_refs=tuple(str(item) for item in list(artifact_refs or []) if str(item)),
        produced_trace_refs=tuple(str(item) for item in list(trace_refs or []) if str(item)),
        source_artifact_refs=tuple(str(item) for item in list(source_artifact_refs or []) if str(item)),
        source_result_record_ids=tuple(str(item) for item in list(source_result_record_ids or []) if str(item)),
        memory_write_candidate_refs=tuple(str(item) for item in list(memory_write_candidate_refs or []) if str(item)),
        memory_commit_refs=tuple(str(item) for item in list(memory_commit_refs or []) if str(item)),
        commit_identity=str(commit_identity or ""),
        scope_key=scope_key,
        dependency_scope_key=dependency_scope_key,
        timeline_coordinate=coordinate,
        validation_result=dict(validation_result or {}),
        effective_from_clock_seq=clock_seq if accepted else 0,
        effective_scope_path=scope_path if accepted else (),
        created_at=time.time(),
    )


def build_timeline_coordinate(
    *,
    request_payload: dict[str, Any],
    result_event: dict[str, Any] | None = None,
    stage_id: str = "",
    node_id: str = "",
    scope_path: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    dispatch_context = dict(request_payload.get("dispatch_context") or {})
    explicit_inputs = dict(request_payload.get("explicit_inputs") or {})
    result = dict(result_event or {})
    resolved_scope = tuple(str(item) for item in list(scope_path or dispatch_context.get("scope_path") or ["run"]) if str(item))
    return {
        "coordination_run_id": str(request_payload.get("coordination_run_id") or dispatch_context.get("coordination_run_id") or ""),
        "stage_id": str(stage_id or request_payload.get("stage_id") or dispatch_context.get("stage_id") or ""),
        "node_id": str(node_id or request_payload.get("node_id") or dispatch_context.get("node_id") or ""),
        "dispatch_event_id": str(dispatch_context.get("dispatch_event_id") or ""),
        "request_id": str(request_payload.get("request_id") or ""),
        "result_event_id": str(result.get("event_id") or ""),
        "clock_seq": _safe_int(result.get("clock_seq") or dispatch_context.get("clock_seq"), 0),
        "scope_path": list(resolved_scope),
        "scope_key": scope_key_from_path(resolved_scope),
        "dependency_scope_key": str(dispatch_context.get("dependency_scope_key") or "") or scope_key_from_path(resolved_scope),
        "phase_id": str(dispatch_context.get("phase_id") or ""),
        "loop_frame_id": str(dispatch_context.get("loop_frame_id") or explicit_inputs.get("loop_frame_id") or ""),
        "iteration_index": _safe_int(dispatch_context.get("iteration_index") or explicit_inputs.get("iteration_index"), 0),
        "volume_index": _safe_int(dispatch_context.get("volume_index") or explicit_inputs.get("volume_index"), 0),
        "batch_start_index": _safe_int(dispatch_context.get("batch_start_index") or explicit_inputs.get("batch_start_index") or explicit_inputs.get("chapter_index"), 0),
        "batch_end_index": _safe_int(dispatch_context.get("batch_end_index") or explicit_inputs.get("batch_end_index") or explicit_inputs.get("chapter_index"), 0),
        "round_index": _safe_int(
            dispatch_context.get("round_index")
            or explicit_inputs.get("round_index")
            or explicit_inputs.get("revision_round")
            or explicit_inputs.get("attempt_index"),
            0,
        ),
        "authority": "task_graph.timeline_coordinate",
    }


def scope_key_from_path(scope_path: tuple[str, ...] | list[str]) -> str:
    parts = [str(item).strip().replace("/", "_") for item in list(scope_path or ["run"]) if str(item).strip()]
    return "/".join(parts) or "run"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _short_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
