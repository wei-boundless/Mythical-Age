from __future__ import annotations

import hashlib
import json
from typing import Any

from harness.runtime.prompt_segment_plan import stable_model_message_hash, stable_text_hash


_FRAME_SOURCE_REF = "single_agent_turn_incremental_context_frame"
TASK_EXECUTION_INCREMENTAL_CONTEXT_FRAME_SOURCE_REF = "task_execution_incremental_context_frame"
TASK_EXECUTION_INCREMENTAL_CONTEXT_CURSOR_SOURCE_REF = "task_execution_incremental_context_cursor"
_FRAME_TITLE = "Single agent turn incremental context frame"
_UNCHANGED_REF_LIMIT = 4
_TASK_EVENT_LIMIT = 8


def build_prefix_lock_report(
    *,
    base_segment_plan: dict[str, Any],
    model_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    base_segments = _base_segments_by_message_index(base_segment_plan)
    checked = 0
    violations: list[dict[str, Any]] = []
    for index, message in enumerate(list(model_messages or [])):
        base = base_segments.get(index)
        if not base:
            continue
        checked += 1
        expected_role = str(base.get("model_message_role") or "").strip()
        actual_role = str(message.get("role") or "user")
        if expected_role and expected_role != actual_role:
            violations.append(
                {
                    "model_message_index": index,
                    "kind": str(base.get("kind") or ""),
                    "reason": "role_changed",
                    "expected_role": expected_role,
                    "actual_role": actual_role,
                }
            )
            continue
        expected_message_hash = str(base.get("model_message_hash") or "").strip()
        if expected_message_hash:
            actual_message_hash = _stable_model_message_hash(message)
            if expected_message_hash != actual_message_hash:
                violations.append(
                    {
                        "model_message_index": index,
                        "kind": str(base.get("kind") or ""),
                        "reason": "model_message_hash_changed",
                        "expected_model_message_hash": expected_message_hash,
                        "actual_model_message_hash": actual_message_hash,
                    }
                )
                continue
        expected_content_hash = str(base.get("content_hash") or "").strip()
        if expected_content_hash:
            actual_content_hash = stable_text_hash(str(message.get("content") or ""))
            if expected_content_hash != actual_content_hash:
                violations.append(
                    {
                        "model_message_index": index,
                        "kind": str(base.get("kind") or ""),
                        "reason": "content_hash_changed",
                        "expected_content_hash": expected_content_hash,
                        "actual_content_hash": actual_content_hash,
                    }
                )
    return {
        "status": "violated" if violations else "preserved",
        "checked_message_count": checked,
        "violation_count": len(violations),
        "violations": violations[:20],
        "authority": "harness.runtime.incremental_context_frame.prefix_lock",
    }


def prefix_lock_violation_for_index(report: dict[str, Any], index: int) -> dict[str, Any] | None:
    for violation in list(dict(report or {}).get("violations") or []):
        if not isinstance(violation, dict):
            continue
        try:
            violation_index = int(violation.get("model_message_index"))
        except (TypeError, ValueError):
            continue
        if violation_index == index:
            return dict(violation)
    return None


def build_tool_followup_incremental_context_frame_message(
    *,
    base_segment_plan: dict[str, Any],
    model_messages: list[dict[str, Any]],
    tool_iteration: int,
    prefix_lock_report: dict[str, Any] | None = None,
    current_tool_round_indexed_messages: list[tuple[int, dict[str, Any]]] | tuple[tuple[int, dict[str, Any]], ...] = (),
    unchanged_refs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    tool_context_delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    indexed_current = [
        (int(index), dict(message))
        for index, message in list(current_tool_round_indexed_messages or [])
        if isinstance(message, dict)
    ]
    needs_full_messages = not indexed_current or prefix_lock_report is None or unchanged_refs is None
    messages = [dict(item) for item in list(model_messages or []) if isinstance(item, dict)] if needs_full_messages else []
    current_indexes = {index for index, _message in indexed_current}
    if not indexed_current:
        current_indexes = _current_tool_round_indexes(messages)
        indexed_current = [(index, dict(messages[index])) for index in sorted(current_indexes)]
    current_start = min(current_indexes) if current_indexes else len(messages)
    prefix_lock = (
        dict(prefix_lock_report)
        if prefix_lock_report is not None
        else build_prefix_lock_report(
            base_segment_plan=dict(base_segment_plan or {}),
            model_messages=messages,
        )
    )
    historical_tool_refs = (
        [dict(item) for item in list(unchanged_refs or []) if isinstance(item, dict)]
        if unchanged_refs is not None
        else _historical_tool_refs(messages, current_indexes=current_indexes)
    )
    current_events = _current_tool_events_from_indexed_messages(indexed_current)
    delta_payload = dict(tool_context_delta or {})
    payload = {
        "frame_type": "incremental_context_frame",
        "tool_followup_iteration": max(1, int(tool_iteration or 1)),
        "base_prefix": {
            "status": "preserved" if str(prefix_lock.get("status") or "") == "preserved" else "changed",
            "prefix_lock_status": str(prefix_lock.get("status") or ""),
            "checked_message_count": int(prefix_lock.get("checked_message_count") or 0),
            "violation_count": int(prefix_lock.get("violation_count") or 0),
            "last_preserved_model_message_index": max(-1, current_start - 1),
            "rule": "before current_tool_round = preserved history",
        },
        "current_tool_round": {
            "status": "present" if current_events else "none",
            "model_message_indexes": sorted(current_indexes),
            "events": current_events,
        },
        "unchanged_refs": historical_tool_refs,
        "tool_context_delta": delta_payload,
        "changed_state": [
            *_changed_state(prefix_lock),
            *_tool_context_changed_state(delta_payload),
        ],
        "rules": [
            "history remains valid",
            "current_tool_round is new",
            "refs/hash index exact transcript content",
        ],
        "authority": "harness.runtime.incremental_context_frame",
    }
    return {
        "role": "system",
        "source_ref": _FRAME_SOURCE_REF,
        "content": (
            "你正在继续同一个工具执行回合。\n"
            "前面的 transcript 是已经发送过的历史上下文，仍然有效，不要把它当作本轮新观察。\n"
            "本轮新增观察、环境变化和当前关注事项如下：\n"
            f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        ),
        "incremental_context_frame": payload,
    }


def is_incremental_context_frame_message(message: dict[str, Any]) -> bool:
    payload = dict(message or {})
    if str(payload.get("source_ref") or "").strip() == _FRAME_SOURCE_REF:
        return True
    content = str(payload.get("content") or "")
    return (
        content.startswith("你正在继续同一个工具执行回合。")
        and '"frame_type": "incremental_context_frame"' in content
    )


def incremental_context_frame_segment_spec(message: dict[str, Any], *, tool_iteration: int) -> dict[str, Any]:
    return {
        "role": "system",
        "content": str(message.get("content") or ""),
        "kind": "incremental_context_frame",
        "source_ref": _FRAME_SOURCE_REF,
        "cache_scope": "task",
        "cache_role": "session_stable",
        "prefix_tier": "task",
        "compression_role": "summarize",
        "metadata": {
            "followup_iteration": max(1, int(tool_iteration or 1)),
            "authority_class": "incremental_context_frame",
            "runtime_fragment_role": "current_delta_explanation",
            "stability_rule": "tool follow-up incremental frames are append-only context; each new frame is added before the dynamic tail and is reused unchanged by later follow-ups",
            "cache_impact": "append_only_task_prefix",
        },
        "model_message": dict(message),
    }


def build_task_execution_incremental_context_frame_payload(
    *,
    task_run_id: str,
    invocation_index: int,
    dynamic_context_report: dict[str, Any] | None = None,
    task_state_replay_entries: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    current_observations: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    execution_projection: dict[str, Any] | None = None,
    task_plan_context_payload: dict[str, Any] | None = None,
    evidence_index_cursor_payload: dict[str, Any] | None = None,
    editor_context_payload: dict[str, Any] | None = None,
    read_evidence_payload: dict[str, Any] | None = None,
    volatile_payload: dict[str, Any] | None = None,
    runtime_memory_context_payload: dict[str, Any] | None = None,
    user_steering_payload: dict[str, Any] | None = None,
    runtime_control_signals: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
) -> dict[str, Any]:
    replay_entries = [dict(item) for item in list(task_state_replay_entries or []) if isinstance(item, dict)]
    current_events = _task_current_events(
        current_observations=current_observations,
        execution_projection=execution_projection,
        user_steering_payload=user_steering_payload,
        runtime_control_signals=runtime_control_signals,
        read_evidence_payload=read_evidence_payload,
    )
    return _drop_empty(
        {
            "frame_type": "dynamic_execution_tail",
            "frame_scope": "task_execution",
            "task_run_id": str(task_run_id or ""),
            "invocation_index": max(1, int(invocation_index or 1)),
            "sealed_context_cursor": _drop_empty(
                {
                    "status": "preserved",
                    "append_context_status": "facts_before_tail",
                    "task_state_replay_entry_count": len(replay_entries),
                    "latest_task_state_replay_ref": _latest_task_replay_ref(replay_entries),
                }
            ),
            "current_invocation": _drop_empty(
                {
                    "new_event_refs": current_events,
                    "runtime_control_refs": _runtime_control_signal_refs(runtime_control_signals),
                    "read_evidence_packet_id": str(dict(read_evidence_payload or {}).get("packet_id") or ""),
                }
            ),
            "execution_contract": {
                "memory_source": "sealed_context_prefix+context_append",
                "action_contract_ref": "action_schema_static",
                "tail_scope": "current_invocation_control_only",
            },
            "authority": "harness.runtime.incremental_context_frame.task_execution",
        }
    )


def _base_segments_by_message_index(base_segment_plan: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for segment in list(dict(base_segment_plan or {}).get("segments") or []):
        if not isinstance(segment, dict):
            continue
        try:
            index = int(segment.get("model_message_index"))
        except (TypeError, ValueError):
            continue
        if index >= 0:
            result[index] = dict(segment)
    return result


def _stable_model_message_hash(message: dict[str, Any]) -> str:
    return stable_model_message_hash(dict(message or {}))


def _canonical_json(value: Any) -> str:
    return json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _current_tool_round_indexes(messages: list[dict[str, Any]]) -> set[int]:
    groups: list[list[int]] = []
    active: list[int] | None = None
    for index, message in enumerate(messages):
        role = str(message.get("role") or "")
        if role == "assistant" and message.get("tool_calls"):
            active = [index]
            groups.append(active)
            continue
        if role == "tool" and active is not None:
            active.append(index)
            continue
        active = None
    return set(groups[-1]) if groups else set()


def _current_tool_events(messages: list[dict[str, Any]], *, current_indexes: set[int]) -> list[dict[str, Any]]:
    return _current_tool_events_from_indexed_messages(
        [(index, dict(messages[index])) for index in sorted(current_indexes)]
    )


def _current_tool_events_from_indexed_messages(indexed_messages: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, message in list(indexed_messages or []):
        role = str(message.get("role") or "")
        if role == "assistant":
            for call in _tool_calls(message):
                events.append(
                    {
                        "event_kind": "tool_call",
                        "model_message_index": index,
                        "tool_call_id": str(call.get("id") or ""),
                        "tool_name": str(call.get("name") or _tool_call_function(call).get("name") or ""),
                        "args_hash": _payload_hash(call.get("args") or _tool_call_function(call).get("arguments") or {}),
                    }
                )
        elif role == "tool":
            content = str(message.get("content") or "")
            events.append(
                {
                    "event_kind": "tool_observation",
                    "model_message_index": index,
                    "tool_call_id": str(message.get("tool_call_id") or ""),
                    "tool_name": str(message.get("name") or ""),
                    "payload_hash": stable_text_hash(content),
                    "exact_content_visible": True,
                }
            )
    return events


def _historical_tool_refs(messages: list[dict[str, Any]], *, current_indexes: set[int]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if index in current_indexes:
            continue
        role = str(message.get("role") or "")
        if role == "assistant" and message.get("tool_calls"):
            refs.append(
                {
                    "model_message_index": index,
                    "role": "assistant",
                    "event_kind": "tool_call",
                    "content_hash": _payload_hash(message.get("tool_calls") or []),
                    "meaning": "already visible in preserved transcript",
                }
            )
        elif role == "tool":
            refs.append(
                {
                    "model_message_index": index,
                    "role": "tool",
                    "event_kind": "tool_observation",
                    "tool_call_id": str(message.get("tool_call_id") or ""),
                    "content_hash": stable_text_hash(str(message.get("content") or "")),
                    "meaning": "already visible in preserved transcript",
                }
            )
    return refs[-_UNCHANGED_REF_LIMIT:]


def _changed_state(prefix_lock: dict[str, Any]) -> list[dict[str, Any]]:
    if str(prefix_lock.get("status") or "") == "preserved":
        return []
    return [
        {
            "subject": "prompt_prefix",
            "change": "prefix_lock_violation",
            "required_action": "treat mismatched old messages as cache break diagnostics; do not silently assume preserved prefix",
            "violations": list(prefix_lock.get("violations") or [])[:5],
        }
    ]


def _tool_context_changed_state(delta_payload: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for item in _bounded_dicts(delta_payload.get("changed_refs"), limit=8):
        changes.append(
            _drop_empty(
                {
                    "subject": str(item.get("tool_name") or item.get("signature") or "tool_context"),
                    "change": str(item.get("change") or "tool_result_changed"),
                    "current_ref": str(item.get("ref") or ""),
                    "previous_ref": str(item.get("changed_from") or ""),
                    "required_action": "prefer the current ref for this tool signature; treat the previous ref as stale for exact facts",
                }
            )
        )
    return changes


def _latest_task_replay_ref(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""
    return _task_replay_ref(dict(entries[-1]), fallback_index=len(entries))


def _task_replay_ref(entry: dict[str, Any], *, fallback_index: int) -> str:
    for key in ("observation_ref", "entry_ref", "summary_ref", "tool_call_id"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    return f"entry:{_payload_hash(entry).removeprefix('sha256:')[:12] or fallback_index}"


def _task_current_events(
    *,
    current_observations: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    execution_projection: dict[str, Any] | None,
    user_steering_payload: dict[str, Any] | None,
    runtime_control_signals: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    read_evidence_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for observation in [dict(item) for item in list(current_observations or []) if isinstance(item, dict)]:
        source = _observation_source(observation)
        ref = _first_text(
            source.get("observation_ref"),
            source.get("observation_id"),
            observation.get("observation_ref"),
            observation.get("observation_id"),
        )
        events.append(
            _drop_empty(
                {
                    "event_kind": "current_observation",
                    "event_ref": ref,
                    "tool_name": _first_text(source.get("tool_name"), source.get("name"), source.get("source")),
                    "status": str(source.get("status") or ""),
                    "exact_content_visible_elsewhere": bool(_read_evidence_has_current_exact(read_evidence_payload)),
                }
            )
        )
    execution_payload = dict(execution_projection or {})
    for receipt in _bounded_dicts(execution_payload.get("last_action_receipts"), limit=2):
        ref = _first_text(receipt.get("observation_ref"), receipt.get("observation_id"), receipt.get("tool_call_id"))
        events.append(
            _drop_empty(
                {
                    "event_kind": "latest_action_receipt",
                    "event_ref": ref,
                    "tool_name": str(receipt.get("tool_name") or receipt.get("source") or ""),
                    "status": str(receipt.get("status") or ""),
                    "visibility": "latest_runtime_cursor",
                }
            )
        )
    for steer in _bounded_dicts(dict(user_steering_payload or {}).get("pending_user_steers"), limit=3):
        events.append(
            _drop_empty(
                {
                    "event_kind": "pending_user_steer",
                    "event_ref": str(steer.get("steer_id") or ""),
                    "content_visible_in": "user_steering_context_append",
                }
            )
        )
    return _dedupe_events(events)[-_TASK_EVENT_LIMIT:]


def _runtime_control_signal_refs(
    runtime_control_signals: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for signal in _bounded_dicts(runtime_control_signals, limit=3):
        refs.append(
            _drop_empty(
                {
                    "event_ref": _first_text(signal.get("runtime_control_signal_ref"), signal.get("signal_ref")),
                    "signal_kind": str(signal.get("signal_kind") or signal.get("kind") or ""),
                }
            )
        )
    return [item for item in refs if item]


def _observation_source(observation: dict[str, Any]) -> dict[str, Any]:
    wrapped = observation.get("observation")
    if isinstance(wrapped, dict) and wrapped:
        return dict(wrapped)
    payload = observation.get("payload")
    if isinstance(payload, dict) and payload:
        return {**dict(observation), **payload}
    return dict(observation)


def _read_evidence_has_current_exact(payload: dict[str, Any] | None) -> bool:
    return bool(dict(payload or {}).get("visible_exact_in_packet"))


def _bounded_dicts(value: Any, *, limit: int) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or [])[: max(0, int(limit or 0))] if isinstance(item, dict)]


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        key = "|".join(
            [
                str(event.get("event_kind") or ""),
                str(event.get("event_ref") or ""),
                str(event.get("payload_hash") or ""),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in list(message.get("tool_calls") or []) if isinstance(item, dict)]


def _tool_call_function(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function")
    return dict(function) if isinstance(function, dict) else {}


def _payload_hash(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8", errors="ignore")).hexdigest()
