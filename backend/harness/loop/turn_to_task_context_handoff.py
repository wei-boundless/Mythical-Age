from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.memory.file_evidence_scope import session_file_evidence_scope, task_run_file_evidence_scope
from runtime.memory.file_state_store import FileStateAuthorityStore


HANDOFF_KIND = "turn_to_task_context_handoff"
HANDOFF_AUTHORITY = "harness.loop.turn_to_task_context_handoff"
_MAX_OBSERVATIONS = 24
_MAX_OBSERVATION_TEXT_CHARS = 12000
_MAX_MEMORY_SECTION_ITEMS = 12
_MAX_MEMORY_ITEM_CHARS = 2000
_MAX_FILE_STATE_ITEMS = 20


@dataclass(frozen=True, slots=True)
class RecordedTurnToTaskContextHandoff:
    handoff_id: str
    handoff_ref: str
    payload: dict[str, Any]
    materialization: dict[str, Any]
    event: Any | None = None


def build_turn_to_task_context_handoff_seed(
    *,
    runtime_host: Any,
    session_id: str,
    turn_id: str,
    source_packet_ref: str,
    tool_observation_payloads: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    session_context: dict[str, Any] | None = None,
    current_work_boundary_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_payload = dict(session_context or {})
    memory_context = _memory_context_for_handoff(session_payload.get("memory_context"))
    observations = _inherited_observations(tool_observation_payloads)
    file_evidence_scope = session_file_evidence_scope(session_id)
    file_state_snapshot = _session_file_state_snapshot(
        runtime_host,
        file_evidence_scope=file_evidence_scope,
    )
    turn_input_facts = _bounded_mapping(
        session_payload.get("turn_input_facts"),
        allowed_keys=(
            "user_intent",
            "environment_binding",
            "expected_active_turn_id",
            "expected_task_run_id",
            "active_turn_input_policy",
            "recovery_input_policy",
            "editor_context",
        ),
        max_chars=30000,
    )
    editor_context = {}
    if isinstance(turn_input_facts.get("editor_context"), dict):
        editor_context = _bounded_mapping(turn_input_facts.get("editor_context"), max_chars=20000)
    elif isinstance(session_payload.get("editor_context"), dict):
        editor_context = _bounded_mapping(session_payload.get("editor_context"), max_chars=20000)
    attachments = [
        _bounded_mapping(item, max_chars=4000)
        for item in list(session_payload.get("turn_input_attachments") or [])[:12]
        if isinstance(item, dict)
    ]
    return _drop_empty(
        {
            "session_id": str(session_id or ""),
            "turn_id": str(turn_id or ""),
            "source_packet_ref": str(source_packet_ref or ""),
            "inherited_observations": observations,
            "inherited_observation_refs": [
                str(item.get("observation_id") or item.get("observation_ref") or "")
                for item in observations
                if str(item.get("observation_id") or item.get("observation_ref") or "")
            ],
            "inherited_file_evidence_scope": file_evidence_scope,
            "inherited_file_state_snapshot": file_state_snapshot,
            "inherited_memory_context": memory_context,
            "inherited_memory_context_refs": _memory_context_refs(memory_context),
            "inherited_turn_input_facts": turn_input_facts,
            "inherited_editor_context": editor_context,
            "inherited_attachments": attachments,
            "inherited_current_work_boundary_receipt": _bounded_mapping(
                current_work_boundary_receipt or session_payload.get("current_work_boundary_receipt"),
                max_chars=12000,
            ),
            "artifact_refs": _artifact_refs_from_observations(observations),
            "authority": HANDOFF_AUTHORITY,
        }
    )


def record_turn_to_task_context_handoff(
    runtime_host: Any,
    *,
    session_id: str,
    turn_id: str,
    task_run_id: str,
    task_id: str = "",
    start_context_handoff: dict[str, Any] | None = None,
) -> RecordedTurnToTaskContextHandoff:
    seed = dict(start_context_handoff or {})
    handoff_id = str(seed.get("handoff_id") or f"turn-task-handoff:{turn_id}:{uuid.uuid4().hex[:10]}").strip()
    payload = _drop_empty(
        {
            **seed,
            "handoff_id": handoff_id,
            "session_id": str(session_id or seed.get("session_id") or ""),
            "turn_id": str(turn_id or seed.get("turn_id") or ""),
            "task_run_id": str(task_run_id or ""),
            "task_id": str(task_id or ""),
            "created_at": time.time(),
            "empty_reason": _empty_handoff_reason(seed),
            "authority": HANDOFF_AUTHORITY,
        }
    )
    materialization = materialize_handoff_file_state_to_task_scope(
        runtime_host,
        task_run_id=task_run_id,
        session_id=session_id,
        handoff=payload,
    )
    payload = {
        **payload,
        "file_state_materialization": dict(materialization),
    }
    handoff_ref = runtime_host.runtime_objects.put_object(HANDOFF_KIND, handoff_id, payload)
    payload = {
        **payload,
        "handoff_ref": handoff_ref,
    }
    handoff_ref = runtime_host.runtime_objects.put_object(HANDOFF_KIND, handoff_id, payload)
    event = runtime_host.event_log.append(
        task_run_id,
        "turn_to_task_context_handoff_recorded",
        payload={
            "handoff": handoff_summary(payload),
            "file_state_materialization": dict(materialization),
        },
        refs={
            "turn_ref": str(payload.get("turn_id") or turn_id or ""),
            "task_run_ref": str(task_run_id or ""),
            "turn_to_task_context_handoff_ref": handoff_ref,
            "source_packet_ref": str(payload.get("source_packet_ref") or ""),
        },
    )
    return RecordedTurnToTaskContextHandoff(
        handoff_id=handoff_id,
        handoff_ref=handoff_ref,
        payload=payload,
        materialization=materialization,
        event=event,
    )


def load_turn_to_task_context_handoff(runtime_host: Any, task_run: Any) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    if not diagnostics and isinstance(task_run, dict):
        diagnostics = dict(task_run.get("diagnostics") or {})
    handoff_ref = str(diagnostics.get("turn_to_task_context_handoff_ref") or "").strip()
    if not handoff_ref:
        return {}
    store = getattr(runtime_host, "runtime_objects", None)
    getter = getattr(store, "get_object", None)
    if not callable(getter):
        return {}
    try:
        payload = getter(handoff_ref)
    except Exception:
        return {}
    return dict(payload or {}) if isinstance(payload, dict) else {}


def handoff_summary(handoff: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(handoff or {})
    memory_context = dict(payload.get("inherited_memory_context") or {})
    file_state = [dict(item) for item in list(payload.get("inherited_file_state_snapshot") or []) if isinstance(item, dict)]
    observations = [dict(item) for item in list(payload.get("inherited_observations") or []) if isinstance(item, dict)]
    attachments = [dict(item) for item in list(payload.get("inherited_attachments") or []) if isinstance(item, dict)]
    return _drop_empty(
        {
            "handoff_id": str(payload.get("handoff_id") or ""),
            "session_id": str(payload.get("session_id") or ""),
            "turn_id": str(payload.get("turn_id") or ""),
            "task_run_id": str(payload.get("task_run_id") or ""),
            "source_packet_ref": str(payload.get("source_packet_ref") or ""),
            "inherited_observation_refs": list(payload.get("inherited_observation_refs") or [])[:_MAX_OBSERVATIONS],
            "inherited_observation_count": len(observations),
            "inherited_file_state_count": len(file_state),
            "inherited_attachment_count": len(attachments),
            "inherited_memory_context_refs": _memory_context_refs(memory_context),
            "selected_memory_sections": list(memory_context.get("selected_sections") or []),
            "empty_reason": str(payload.get("empty_reason") or ""),
            "authority": HANDOFF_AUTHORITY,
        }
    )


def inherited_observations_for_packet(handoff: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(dict(handoff or {}).get("inherited_observations") or [])[:_MAX_OBSERVATIONS]
        if isinstance(item, dict)
    ]


def inherited_start_context_for_model(handoff: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(handoff or {})
    if not payload:
        return {}
    return _drop_empty(
        {
            "handoff_id": str(payload.get("handoff_id") or ""),
            "handoff_ref": str(payload.get("handoff_ref") or ""),
            "source": HANDOFF_AUTHORITY,
            "session_id": str(payload.get("session_id") or ""),
            "turn_id": str(payload.get("turn_id") or ""),
            "task_run_id": str(payload.get("task_run_id") or ""),
            "source_packet_ref": str(payload.get("source_packet_ref") or ""),
            "memory_context": dict(payload.get("inherited_memory_context") or {}),
            "memory_context_refs": dict(payload.get("inherited_memory_context_refs") or {}),
            "observation_refs": list(payload.get("inherited_observation_refs") or [])[:_MAX_OBSERVATIONS],
            "observations": inherited_observations_for_packet(payload),
            "file_evidence_scope": dict(payload.get("inherited_file_evidence_scope") or {}),
            "file_state": [
                dict(item)
                for item in list(payload.get("inherited_file_state_snapshot") or [])[:_MAX_FILE_STATE_ITEMS]
                if isinstance(item, dict)
            ],
            "turn_input_facts": dict(payload.get("inherited_turn_input_facts") or {}),
            "editor_context": dict(payload.get("inherited_editor_context") or {}),
            "attachments": [
                dict(item)
                for item in list(payload.get("inherited_attachments") or [])[:12]
                if isinstance(item, dict)
            ],
            "current_work_boundary_receipt": dict(payload.get("inherited_current_work_boundary_receipt") or {}),
            "artifact_refs": [
                dict(item)
                for item in list(payload.get("artifact_refs") or [])
                if isinstance(item, dict)
            ],
            "authority": HANDOFF_AUTHORITY,
        }
    )


def materialize_handoff_file_state_to_task_scope(
    runtime_host: Any,
    *,
    task_run_id: str,
    session_id: str,
    handoff: dict[str, Any],
) -> dict[str, Any]:
    task_ref = str(task_run_id or "").strip()
    if not task_ref:
        return {"status": "skipped", "reason": "missing_task_run_id", "authority": f"{HANDOFF_AUTHORITY}.file_state_materialization"}
    store = _file_state_store(runtime_host)
    if store is None:
        return {"status": "skipped", "reason": "file_state_store_unavailable", "authority": f"{HANDOFF_AUTHORITY}.file_state_materialization"}
    target_scope = task_run_file_evidence_scope(task_ref, session_id=session_id)
    inherited_observations = inherited_observations_for_packet(handoff)
    applied_observation_count = 0
    for observation in inherited_observations:
        try:
            store.apply_observation_scope(target_scope, observation)
            applied_observation_count += 1
        except Exception:
            continue
    snapshot_events = _file_state_snapshot_events(
        handoff.get("inherited_file_state_snapshot"),
        handoff_id=str(handoff.get("handoff_id") or ""),
    )
    applied_snapshot_event_count = 0
    if snapshot_events:
        try:
            store.apply_events_scope(
                target_scope,
                snapshot_events,
                observation_ref=f"handoff:{handoff.get('handoff_id') or task_ref}:file_state_snapshot",
                tool_call_id="turn_to_task_context_handoff",
            )
            applied_snapshot_event_count = len(snapshot_events)
        except Exception:
            applied_snapshot_event_count = 0
    return {
        "status": "recorded" if applied_observation_count or applied_snapshot_event_count else "empty",
        "task_file_evidence_scope": target_scope,
        "source_file_evidence_scope": dict(handoff.get("inherited_file_evidence_scope") or {}),
        "applied_observation_count": applied_observation_count,
        "applied_snapshot_event_count": applied_snapshot_event_count,
        "authority": f"{HANDOFF_AUTHORITY}.file_state_materialization",
    }


def _session_file_state_snapshot(runtime_host: Any, *, file_evidence_scope: dict[str, Any]) -> list[dict[str, Any]]:
    store = _file_state_store(runtime_host)
    snapshot = getattr(store, "snapshot_scope", None) if store is not None else None
    if not callable(snapshot):
        return []
    try:
        return [dict(item) for item in list(snapshot(file_evidence_scope, limit=_MAX_FILE_STATE_ITEMS) or []) if isinstance(item, dict)]
    except Exception:
        return []


def _file_state_store(runtime_host: Any) -> Any | None:
    store = getattr(runtime_host, "file_state_store", None)
    if store is not None:
        return store
    root_dir = getattr(runtime_host, "root_dir", None)
    if root_dir is None:
        return None
    try:
        return FileStateAuthorityStore(Path(root_dir))
    except Exception:
        return None


def _memory_context_for_handoff(value: Any) -> dict[str, Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    visible = payload.get("model_visible_sections")
    if not isinstance(visible, dict):
        visible = {}
    filtered_sections: dict[str, list[str]] = {}
    for section, items in visible.items():
        clean_items = [
            _compact_text(item, limit=_MAX_MEMORY_ITEM_CHARS)
            for item in list(items or [])[:_MAX_MEMORY_SECTION_ITEMS]
            if str(item).strip()
        ]
        if clean_items:
            filtered_sections[str(section)] = clean_items
    selected_sections = [
        str(item)
        for item in list(payload.get("selected_sections") or filtered_sections.keys())
        if str(item) in filtered_sections
    ]
    diagnostics = dict(payload.get("diagnostics") or {}) if isinstance(payload.get("diagnostics"), dict) else {}
    return _drop_empty(
        {
            "authority": str(payload.get("authority") or "memory_system.runtime_memory_context"),
            "memory_runtime_view_ref": str(payload.get("memory_runtime_view_ref") or ""),
            "context_package_ref": str(payload.get("context_package_ref") or ""),
            "selected_sections": selected_sections,
            "model_visible_sections": filtered_sections,
            "diagnostics": _bounded_mapping(
                diagnostics,
                allowed_keys=(
                    "read_namespaces",
                    "requested_memory_layers",
                    "long_term_candidate_count",
                    "state_candidate_count",
                    "context_candidate_count",
                ),
                max_chars=8000,
            ),
        }
    )


def _inherited_observations(values: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in list(values or [])[-_MAX_OBSERVATIONS:]:
        if not isinstance(raw, dict):
            continue
        observation = _inherited_observation(raw)
        key = str(observation.get("observation_id") or observation.get("observation_ref") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        observations.append(observation)
    return observations


def _inherited_observation(raw: dict[str, Any]) -> dict[str, Any]:
    payload = _sanitized_tool_observation(raw)
    tool_name = str(payload.get("tool_name") or dict(payload.get("result_envelope") or {}).get("tool_name") or "system").strip()
    status = str(payload.get("status") or dict(payload.get("result_envelope") or {}).get("status") or "ok").strip()
    observation_type = "tool_result" if status == "ok" else "executor_error"
    observation_id = str(payload.get("observation_id") or raw.get("observation_ref") or f"handoff-observation:{uuid.uuid4().hex[:10]}")
    return _drop_empty(
        {
            "observation_id": observation_id,
            "observation_ref": observation_id,
            "observation_type": observation_type,
            "source": f"tool:{tool_name}" if tool_name else "tool",
            "content_chars": len(str(payload.get("text") or "")),
            "payload": payload,
            "needs_model_followup": status not in {"ok", "needs_approval"},
            "inherited_from_turn": True,
            "authority": f"{HANDOFF_AUTHORITY}.inherited_observation",
        }
    )


def _sanitized_tool_observation(raw: dict[str, Any]) -> dict[str, Any]:
    result_envelope = raw.get("result_envelope")
    diagnostics = raw.get("diagnostics")
    clean_diagnostics = {}
    if isinstance(diagnostics, dict):
        clean_diagnostics = _bounded_mapping(
            diagnostics,
            allowed_keys=(
                "file_state_commit",
                "sandbox_artifact_publish",
                "stage",
                "approval_fingerprint",
                "approval_risk_fingerprint",
            ),
            max_chars=8000,
        )
    return _drop_empty(
        {
            "observation_id": str(raw.get("observation_id") or ""),
            "invocation_id": str(raw.get("invocation_id") or ""),
            "caller_kind": str(raw.get("caller_kind") or ""),
            "caller_ref": str(raw.get("caller_ref") or ""),
            "tool_name": str(raw.get("tool_name") or ""),
            "operation_id": str(raw.get("operation_id") or ""),
            "status": str(raw.get("status") or ""),
            "text": _compact_text(raw.get("text") or "", limit=_MAX_OBSERVATION_TEXT_CHARS),
            "result_ref": str(raw.get("result_ref") or ""),
            "result_envelope": _bounded_mapping(result_envelope, max_chars=_MAX_OBSERVATION_TEXT_CHARS)
            if isinstance(result_envelope, dict)
            else {},
            "operation_gate": _bounded_mapping(raw.get("operation_gate"), max_chars=4000),
            "execution_receipt": _bounded_mapping(raw.get("execution_receipt"), max_chars=4000),
            "artifact_refs": [
                _bounded_mapping(item, max_chars=4000)
                for item in list(raw.get("artifact_refs") or [])
                if isinstance(item, dict)
            ][:12],
            "diagnostics": clean_diagnostics,
            "tool_call_id": str(raw.get("tool_call_id") or ""),
            "authority": "runtime.tool_runtime.tool_observation",
        }
    )


def _file_state_snapshot_events(value: Any, *, handoff_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for file_state in [dict(item) for item in list(value or []) if isinstance(item, dict)]:
        path = str(file_state.get("path") or "").replace("\\", "/").strip().strip("/")
        if not path:
            continue
        for read_range in [dict(item) for item in list(file_state.get("read_ranges") or []) if isinstance(item, dict)]:
            events.append(
                _drop_empty(
                    {
                        "event_type": "read",
                        "path": path,
                        "start_line": read_range.get("start_line"),
                        "end_line": read_range.get("end_line"),
                        "total_lines": file_state.get("total_lines"),
                        "content_sha256": read_range.get("content_sha256") or file_state.get("content_sha256"),
                        "mtime_ns": read_range.get("mtime_ns") or file_state.get("mtime_ns"),
                        "read_intent": read_range.get("read_intent"),
                        "reusable_result_ref": read_range.get("reusable_result_ref"),
                        "exact_artifact_ref": read_range.get("exact_artifact_ref"),
                        "artifact_ref_status": read_range.get("artifact_ref_status"),
                        "visible_exact": read_range.get("visible_exact"),
                        "text_sha256": read_range.get("text_sha256"),
                        "next_start_line": read_range.get("next_start_line"),
                        "has_more": read_range.get("has_more"),
                        "source_scope": "session",
                        "handoff_id": handoff_id,
                    }
                )
            )
        search_hits_by_query: dict[str, list[dict[str, Any]]] = {}
        for hit in [dict(item) for item in list(file_state.get("search_hits") or []) if isinstance(item, dict)]:
            query = str(hit.get("query") or "")
            search_hits_by_query.setdefault(query, []).append(
                _drop_empty({"line": hit.get("line"), "preview": hit.get("preview")})
            )
        for query, matches in search_hits_by_query.items():
            events.append(
                _drop_empty(
                    {
                        "event_type": "search",
                        "path": path,
                        "query": query,
                        "matches": matches,
                        "source_scope": "session",
                        "handoff_id": handoff_id,
                    }
                )
            )
        for write in [dict(item) for item in list(file_state.get("write_events") or []) if isinstance(item, dict)]:
            operation = str(write.get("operation") or "").strip()
            if operation not in {"write", "edit"}:
                continue
            events.append(
                _drop_empty(
                    {
                        "event_type": operation,
                        "path": path,
                        "content_sha256": write.get("content_sha256_after") or file_state.get("content_sha256"),
                        "source_scope": "session",
                        "handoff_id": handoff_id,
                    }
                )
            )
        if file_state.get("exists") is False:
            events.append(
                {
                    "event_type": "exists",
                    "path": path,
                    "exists": False,
                    "source_scope": "session",
                    "handoff_id": handoff_id,
                }
            )
    return events


def _memory_context_refs(memory_context: dict[str, Any]) -> dict[str, Any]:
    payload = dict(memory_context or {})
    return _drop_empty(
        {
            "memory_runtime_view_ref": str(payload.get("memory_runtime_view_ref") or ""),
            "context_package_ref": str(payload.get("context_package_ref") or ""),
        }
    )


def _artifact_refs_from_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in observations:
        payload = dict(observation.get("payload") or {})
        for ref in list(payload.get("artifact_refs") or []):
            if not isinstance(ref, dict):
                continue
            key = str(ref.get("artifact_ref") or ref.get("ref") or ref.get("path") or ref)
            if key in seen:
                continue
            seen.add(key)
            result.append(dict(ref))
    return result[:24]


def _empty_handoff_reason(seed: dict[str, Any]) -> str:
    if (
        seed.get("inherited_observations")
        or seed.get("inherited_memory_context")
        or seed.get("inherited_file_state_snapshot")
        or seed.get("inherited_turn_input_facts")
        or seed.get("inherited_editor_context")
        or seed.get("inherited_attachments")
        or seed.get("inherited_current_work_boundary_receipt")
    ):
        return ""
    return "no_model_visible_turn_context_to_inherit"


def _bounded_mapping(
    value: Any,
    *,
    allowed_keys: tuple[str, ...] | None = None,
    max_chars: int = 12000,
) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    allowed = set(allowed_keys or ())
    remaining = max(0, int(max_chars or 0))
    result: dict[str, Any] = {}
    for key, item in value.items():
        name = str(key)
        if allowed and name not in allowed:
            continue
        if remaining <= 0:
            break
        bounded = _bounded_value(item, max_chars=remaining)
        if bounded in ("", None, [], {}, ()):
            continue
        result[name] = bounded
        remaining -= len(str(bounded))
    return result


def _bounded_value(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, str):
        return _compact_text(value, limit=max_chars)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return _bounded_mapping(value, max_chars=max_chars)
    if isinstance(value, (list, tuple)):
        result: list[Any] = []
        remaining = max(0, int(max_chars or 0))
        for item in list(value):
            if remaining <= 0:
                break
            bounded = _bounded_value(item, max_chars=remaining)
            if bounded in ("", None, [], {}, ()):
                continue
            result.append(bounded)
            remaining -= len(str(bounded))
        return result
    return _compact_text(value, limit=max_chars)


def _compact_text(value: Any, *, limit: int) -> str:
    text = str(value or "")
    if len(text) <= max(0, int(limit or 0)):
        return text
    return text[: max(0, int(limit or 0) - 1)].rstrip() + "..."


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
