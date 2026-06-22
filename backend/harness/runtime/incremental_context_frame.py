from __future__ import annotations

import hashlib
import json
from typing import Any

from harness.runtime.prompt_segment_plan import stable_model_message_hash, stable_text_hash


_FRAME_SOURCE_REF = "single_agent_turn_incremental_context_frame"
TASK_EXECUTION_INCREMENTAL_CONTEXT_FRAME_SOURCE_REF = "task_execution_incremental_context_frame"
_FRAME_TITLE = "Single agent turn incremental context frame"
_PREVIEW_LIMIT = 240
_UNCHANGED_REF_LIMIT = 4
_TASK_REPLAY_REF_LIMIT = 12
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
    replay_refs = _task_replay_refs(replay_entries)
    current_events = _task_current_events(
        current_observations=current_observations,
        execution_projection=execution_projection,
        user_steering_payload=user_steering_payload,
        runtime_control_signals=runtime_control_signals,
        read_evidence_payload=read_evidence_payload,
    )
    changed_state = _task_changed_state(
        task_plan_context_payload=task_plan_context_payload,
        evidence_index_cursor_payload=evidence_index_cursor_payload,
        editor_context_payload=editor_context_payload,
        read_evidence_payload=read_evidence_payload,
        volatile_payload=volatile_payload,
        runtime_memory_context_payload=runtime_memory_context_payload,
        user_steering_payload=user_steering_payload,
        runtime_control_signals=runtime_control_signals,
    )
    section_refs = _dynamic_section_refs(dynamic_context_report)
    return _drop_empty(
        {
            "frame_type": "incremental_context_frame",
            "frame_scope": "task_execution",
            "task_run_id": str(task_run_id or ""),
            "invocation_index": max(1, int(invocation_index or 1)),
            "base_prefix": {
                "status": "preserved_by_segment_plan",
                "rule": "Task/session stable prompt segments stay before the volatile suffix and must not be rebuilt or moved by incremental context.",
            },
            "append_only_replay": _drop_empty(
                {
                    "entry_count": len(replay_entries),
                    "entry_refs": replay_refs[-_TASK_REPLAY_REF_LIMIT:],
                    "latest_entry_ref": str(replay_refs[-1].get("ref") or "") if replay_refs else "",
                    "rule": "These replay entries are historical task evidence already visible in this packet; older entries are not new observations.",
                }
            ),
            "new_events": current_events,
            "changed_state": changed_state,
            "unchanged_refs": _task_unchanged_refs(replay_refs),
            "dynamic_context_refs": section_refs,
            "attention": [
                "前面的 stable prefix 和 append_only_replay 是既有上下文，仍然有效。",
                "只把 new_events 视为本次 invocation 新增或刚到达的观察、控制信号或用户 steer。",
                "read_evidence_injection 才可能包含当前 exact 文件内容；本帧只给 ref/hash/range，不复制历史正文。",
                "如果 changed_state 指出 stale、missing 或 read_required，先重新读取或恢复证据再依赖精确文本。",
                "不要把旧 replay 条目当作本轮新工具结果；使用 refs/hash 判断因果和复用关系。",
            ],
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


def _task_replay_refs(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        ref = _task_replay_ref(entry, fallback_index=index)
        if not ref:
            continue
        refs.append(
            _drop_empty(
                {
                    "ref": ref,
                    "entry_kind": str(entry.get("entry_kind") or ""),
                    "tool_name": str(entry.get("tool_name") or ""),
                    "status": str(entry.get("status") or ""),
                    "path": str(entry.get("path") or ""),
                    "payload_hash": _payload_hash(_task_replay_ref_payload(entry)),
                    "meaning": "already visible in append_only_replay",
                }
            )
        )
    return refs


def _task_replay_ref(entry: dict[str, Any], *, fallback_index: int) -> str:
    for key in ("observation_ref", "entry_ref", "summary_ref", "tool_call_id"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    return f"entry:{_payload_hash(entry).removeprefix('sha256:')[:12] or fallback_index}"


def _task_replay_ref_payload(entry: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "entry_kind": entry.get("entry_kind"),
            "observation_ref": entry.get("observation_ref"),
            "entry_ref": entry.get("entry_ref"),
            "summary_ref": entry.get("summary_ref"),
            "tool_name": entry.get("tool_name"),
            "status": entry.get("status"),
            "path": entry.get("path"),
            "content_range": entry.get("content_range"),
            "artifact_refs": entry.get("artifact_refs"),
            "error": entry.get("error"),
        }
    )


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
                    "payload_hash": _payload_hash(_observation_event_payload(source)),
                    "summary": _compact_preview(source.get("summary") or source.get("content") or ""),
                    "exact_content_visible_elsewhere": bool(_read_evidence_has_current_exact(read_evidence_payload)),
                }
            )
        )
    execution_payload = dict(execution_projection or {})
    for receipt in _bounded_dicts(execution_payload.get("last_action_receipts"), limit=4):
        ref = _first_text(receipt.get("observation_ref"), receipt.get("observation_id"), receipt.get("tool_call_id"))
        events.append(
            _drop_empty(
                {
                    "event_kind": "latest_action_receipt",
                    "event_ref": ref,
                    "tool_name": str(receipt.get("tool_name") or receipt.get("source") or ""),
                    "status": str(receipt.get("status") or ""),
                    "payload_hash": _payload_hash(_observation_event_payload(receipt)),
                    "summary": _compact_preview(receipt.get("summary") or ""),
                    "visibility": "latest_runtime_cursor",
                }
            )
        )
    for steer in _bounded_dicts(dict(user_steering_payload or {}).get("pending_user_steers"), limit=4):
        events.append(
            _drop_empty(
                {
                    "event_kind": "pending_user_steer",
                    "event_ref": str(steer.get("steer_id") or ""),
                    "payload_hash": _payload_hash(_drop_empty({"steer_id": steer.get("steer_id"), "content": steer.get("content")})),
                    "content_visible_in": "user_steering_updates",
                }
            )
        )
    for signal in _bounded_dicts(runtime_control_signals, limit=3):
        events.append(
            _drop_empty(
                {
                    "event_kind": "runtime_control_signal",
                    "event_ref": _first_text(signal.get("runtime_control_signal_ref"), signal.get("signal_ref")),
                    "signal_kind": str(signal.get("signal_kind") or signal.get("kind") or ""),
                    "payload_hash": _payload_hash(signal),
                }
            )
        )
    return _dedupe_events(events)[-_TASK_EVENT_LIMIT:]


def _task_changed_state(
    *,
    task_plan_context_payload: dict[str, Any] | None,
    evidence_index_cursor_payload: dict[str, Any] | None,
    editor_context_payload: dict[str, Any] | None,
    read_evidence_payload: dict[str, Any] | None,
    volatile_payload: dict[str, Any] | None,
    runtime_memory_context_payload: dict[str, Any] | None,
    user_steering_payload: dict[str, Any] | None,
    runtime_control_signals: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    task_plan = dict(dict(task_plan_context_payload or {}).get("task_plan_context") or {})
    if task_plan:
        baseline = dict(task_plan.get("task_plan_baseline") or {})
        cursor = dict(task_plan.get("todo_cursor") or task_plan.get("task_plan_cursor") or {})
        delta = dict(task_plan.get("task_plan_delta") or {})
        changes.append(
            _drop_empty(
                {
                    "subject": "task_plan_context",
                    "change": "plan_cursor_visible",
                    "plan_id": str(baseline.get("plan_id") or ""),
                    "active_item_id": str(cursor.get("active_item_id") or ""),
                    "delta_hash": _payload_hash(delta) if delta else "",
                    "details_visible_in": "task_plan_context",
                }
            )
        )
    evidence_cursor = dict(dict(evidence_index_cursor_payload or {}).get("evidence_index_cursor") or {})
    if evidence_cursor:
        changes.append(
            _drop_empty(
                {
                    "subject": "evidence_index_cursor",
                    "change": "evidence_cursor_visible",
                    "cursor_hash": _payload_hash(_bounded_evidence_cursor(evidence_cursor)),
                    "read_required_count": _count_nested_key(evidence_cursor, "required_read_windows"),
                    "stale_window_count": _count_value(evidence_cursor, "caution_kind", "stale_read_window"),
                    "details_visible_in": "evidence_index_cursor",
                }
            )
        )
    read_evidence = dict(read_evidence_payload or {})
    if read_evidence:
        changes.append(
            _drop_empty(
                {
                    "subject": "read_evidence_injection",
                    "change": "current_exact_or_required_read_state",
                    "packet_id": str(read_evidence.get("packet_id") or ""),
                    "visible_exact_in_packet": bool(read_evidence.get("visible_exact_in_packet")),
                    "exact_ref_count": len(_bounded_dicts(read_evidence.get("read_evidence_refs"), limit=100)),
                    "read_required_count": len(_bounded_dicts(read_evidence.get("read_required_windows"), limit=100)),
                    "refs": _read_evidence_refs(read_evidence),
                    "details_visible_in": "read_evidence_injection",
                }
            )
        )
    editor_payload = dict(editor_context_payload or {})
    if editor_payload:
        changes.append(
            _drop_empty(
                {
                    "subject": "editor_context",
                    "change": "editor_context_delta_visible",
                    "payload_keys": sorted(str(key) for key in editor_payload),
                    "payload_hash": _payload_hash(_bounded_value(editor_payload, limit=1200)),
                    "details_visible_in": "editor_context_index/current_editor_evidence_delta",
                }
            )
        )
    runtime_controls = _bounded_dicts(runtime_control_signals, limit=6)
    if runtime_controls:
        latest = runtime_controls[-1]
        changes.append(
            _drop_empty(
                {
                    "subject": "runtime_control_signals",
                    "change": "control_signal_visible",
                    "signal_count": len(runtime_controls),
                    "latest_signal_ref": _first_text(latest.get("runtime_control_signal_ref"), latest.get("signal_ref")),
                    "latest_signal_kind": str(latest.get("signal_kind") or latest.get("kind") or ""),
                    "details_visible_in": "volatile_task_state",
                }
            )
        )
    steer_payload = dict(user_steering_payload or {})
    if steer_payload:
        changes.append(
            _drop_empty(
                {
                    "subject": "user_steering_updates",
                    "change": "pending_user_steer_visible",
                    "pending_user_steer_count": int(steer_payload.get("pending_user_steer_count") or 0),
                    "steer_refs": [
                        str(item.get("steer_id") or "")
                        for item in _bounded_dicts(steer_payload.get("pending_user_steers"), limit=8)
                        if str(item.get("steer_id") or "")
                    ],
                    "details_visible_in": "user_steering_updates",
                }
            )
        )
    memory_payload = dict(runtime_memory_context_payload or {})
    if memory_payload:
        changes.append(
            _drop_empty(
                {
                    "subject": "runtime_memory_context",
                    "change": "selected_memory_visible",
                    "memory_context_ref": _first_text(
                        memory_payload.get("memory_runtime_view_ref"),
                        memory_payload.get("memory_context_ref"),
                    ),
                    "selected_sections": [
                        str(item)
                        for item in list(memory_payload.get("selected_sections") or [])[:8]
                        if str(item)
                    ],
                    "details_visible_in": "runtime_memory_context",
                }
            )
        )
    volatile = dict(volatile_payload or {})
    if volatile:
        changes.append(
            _drop_empty(
                {
                    "subject": "volatile_task_state",
                    "change": "runtime_cursor_visible",
                    "payload_keys": sorted(str(key) for key in volatile),
                    "payload_hash": _payload_hash(_bounded_value(volatile, limit=1200)),
                    "details_visible_in": "volatile_task_state",
                }
            )
        )
    return [item for item in changes if item]


def _task_unchanged_refs(replay_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unchanged: list[dict[str, Any]] = []
    for ref in replay_refs[:-1][-_UNCHANGED_REF_LIMIT:]:
        unchanged.append(
            _drop_empty(
                {
                    "ref": str(ref.get("ref") or ""),
                    "meaning": "older append-only replay entry remains visible and valid",
                    "reuse_rule": "use as historical evidence; do not treat as current new event",
                }
            )
        )
    return unchanged


def _dynamic_section_refs(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    payload = dict(report or {})
    for section in _bounded_dicts(payload.get("section_reports"), limit=12):
        refs.append(
            _drop_empty(
                {
                    "source": str(section.get("source") or ""),
                    "section_id": str(section.get("section_id") or ""),
                    "cache_impact": str(section.get("cache_impact") or ""),
                    "projection_strategy": str(section.get("projection_strategy") or ""),
                    "refs": [str(item) for item in list(section.get("refs") or [])[:8] if str(item)],
                }
            )
        )
    return refs


def _observation_source(observation: dict[str, Any]) -> dict[str, Any]:
    wrapped = observation.get("observation")
    if isinstance(wrapped, dict) and wrapped:
        return dict(wrapped)
    payload = observation.get("payload")
    if isinstance(payload, dict) and payload:
        return {**dict(observation), **payload}
    return dict(observation)


def _observation_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "observation_ref": payload.get("observation_ref") or payload.get("observation_id"),
            "tool_name": payload.get("tool_name") or payload.get("name") or payload.get("source"),
            "tool_call_id": payload.get("tool_call_id"),
            "status": payload.get("status"),
            "summary": payload.get("summary"),
            "error": payload.get("error") or payload.get("structured_error"),
            "artifact_refs": payload.get("artifact_refs"),
            "content_range": payload.get("content_range"),
        }
    )


def _read_evidence_refs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in _bounded_dicts(payload.get("read_evidence_refs"), limit=6):
        refs.append(
            _drop_empty(
                {
                    "path": str(item.get("path") or ""),
                    "start_line": item.get("start_line"),
                    "end_line": item.get("end_line"),
                    "artifact_ref": str(item.get("artifact_ref") or ""),
                    "observation_ref": str(item.get("observation_ref") or ""),
                    "model_visible_exact_in_current_packet": item.get("model_visible_exact_in_current_packet")
                    if isinstance(item.get("model_visible_exact_in_current_packet"), bool)
                    else None,
                }
            )
        )
    return refs


def _read_evidence_has_current_exact(payload: dict[str, Any] | None) -> bool:
    return bool(dict(payload or {}).get("visible_exact_in_packet"))


def _bounded_evidence_cursor(payload: dict[str, Any]) -> dict[str, Any]:
    return _bounded_value(payload, limit=1600) if isinstance(payload, dict) else {}


def _bounded_value(value: Any, *, limit: int) -> Any:
    if isinstance(value, str):
        return _compact_preview(value[:limit])
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        consumed = 0
        for key in sorted(value):
            if consumed >= limit:
                break
            item = _bounded_value(value[key], limit=max(80, limit - consumed))
            result[str(key)] = item
            consumed += len(_canonical_json(item))
        return result
    if isinstance(value, list):
        result_list = []
        consumed = 0
        for item in value[:12]:
            if consumed >= limit:
                break
            bounded = _bounded_value(item, limit=max(80, limit - consumed))
            result_list.append(bounded)
            consumed += len(_canonical_json(bounded))
        return result_list
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return repr(value)[:limit]


def _count_nested_key(value: Any, key: str) -> int:
    if isinstance(value, dict):
        count = 1 if key in value and value.get(key) not in (None, [], {}) else 0
        return count + sum(_count_nested_key(item, key) for item in value.values())
    if isinstance(value, list):
        return sum(_count_nested_key(item, key) for item in value)
    return 0


def _count_value(value: Any, key: str, expected: str) -> int:
    if isinstance(value, dict):
        count = 1 if str(value.get(key) or "") == expected else 0
        return count + sum(_count_value(item, key, expected) for item in value.values())
    if isinstance(value, list):
        return sum(_count_value(item, key, expected) for item in value)
    return 0


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


def _compact_preview(value: str) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= _PREVIEW_LIMIT:
        return text
    return text[: _PREVIEW_LIMIT - 1] + "…"
