from __future__ import annotations

import json
from typing import Any

from harness.runtime.public_progress import public_runtime_progress_summary


_SUPPRESSED_VISIBLE_TEXT = {
    "",
    "已同步最新进展。",
    "已接上当前工作，正在同步最新进展。",
    "工具调用已完成，正在根据结果继续。",
    "工具返回成功，正在根据结果继续。",
    "工具返回了结构化结果，正在根据结果继续。",
}

_INTERNAL_EVENT_TYPES = {
    "runtime_invocation_packet_compiled",
    "task_execution_packet_compiled",
    "task_model_action_wait_heartbeat",
    "model_action_admission_checked",
    "task_run_executor_claimed",
    "task_run_executor_scheduled",
}

_RAW_STATUS = {
    "aborted",
    "blocked",
    "cancelled",
    "completed",
    "created",
    "failed",
    "queued",
    "ready_to_finish",
    "running",
    "success",
    "waiting",
    "working",
}


def build_progress_presentation(
    *,
    events: list[dict[str, Any]],
    task_run: Any,
    monitor: dict[str, Any] | None = None,
    max_work_units: int = 12,
    max_trace_entries: int = 48,
) -> dict[str, Any]:
    ordered_events = _ordered_events(events)
    observations_by_ref = _observations_by_ref(ordered_events)
    action_requests_by_ref = _action_requests_by_ref(ordered_events)
    technical_trace = [_technical_trace_item(event, observations_by_ref=observations_by_ref) for event in ordered_events]

    units: list[dict[str, Any]] = []
    units_by_key: dict[str, dict[str, Any]] = {}
    latest_unit: dict[str, Any] | None = None

    def resolve_unit(event: dict[str, Any], *, fallback_kind: str = "stage") -> dict[str, Any]:
        nonlocal latest_unit
        key = _event_group_key(event, observations_by_ref=observations_by_ref)
        if key and key in units_by_key:
            unit = units_by_key[key]
        elif key:
            unit = _new_work_unit(key, kind=fallback_kind)
            units.append(unit)
            units_by_key[key] = unit
        elif latest_unit is not None and fallback_kind not in {"terminal", "verification"}:
            unit = latest_unit
        else:
            unit = _new_work_unit(_event_id(event), kind=fallback_kind)
            units.append(unit)
        _alias_unit_keys(unit, event, observations_by_ref=observations_by_ref, units_by_key=units_by_key)
        latest_unit = unit
        return unit

    for event in ordered_events:
        event_type = _text(event.get("event_type"))
        if event_type in _INTERNAL_EVENT_TYPES:
            continue
        payload = _record(event.get("payload"))
        refs = _record(event.get("refs"))

        if event_type == "model_action_request_received":
            action = _record(payload.get("model_action_request"))
            if not action:
                continue
            unit = resolve_unit(event, fallback_kind="model_judgment")
            _apply_model_action(unit, action, event)
            continue

        if event_type == "step_summary_recorded":
            step = _text(payload.get("step"))
            if _is_suppressed_step(step, payload):
                continue
            if step.startswith("model_action_received"):
                unit = resolve_unit(event, fallback_kind="model_judgment")
                action_ref = _text(refs.get("action_request_ref"))
                _apply_model_action_state(unit, payload, action_requests_by_ref.get(action_ref, {}), event)
                continue
            if step.startswith("task_tool_call_started"):
                unit = resolve_unit(event, fallback_kind="tool_action")
                action_ref = _text(refs.get("action_request_ref"))
                action_request = action_requests_by_ref.get(action_ref, {})
                _apply_tool_action(unit, action_request, payload, event)
                continue
            if step.startswith(("task_tool_observation_recorded", "task_duplicate_tool_call_guarded")):
                observation_ref = _text(refs.get("observation_ref"))
                observation = observations_by_ref.get(observation_ref, {})
                if not observation:
                    continue
                unit = resolve_unit(event, fallback_kind="tool_action")
                _apply_tool_observation(unit, observation, event)
                continue
            if step.startswith(("task_completion_repair", "model_action_protocol_repair", "verification")):
                unit = resolve_unit(event, fallback_kind="verification")
                _set_if_better(unit, "kind", "verification")
                _set_if_better(unit, "title", "补齐验收证据")
                _set_if_visible(unit, "judgment", payload.get("public_progress_note") or payload.get("summary"))
                _set_if_better(unit, "state", _state_from_status(payload.get("status")))
                _append_trace_ref(unit, event)
                continue
            visible = _visible_text(payload.get("public_progress_note") or payload.get("summary"))
            if visible:
                unit = resolve_unit(event, fallback_kind="stage")
                _set_if_visible(unit, "action", visible)
                _set_if_better(unit, "title", _stage_title(step, payload.get("status")))
                _set_if_better(unit, "state", _state_from_status(payload.get("status")))
                _append_trace_ref(unit, event)
            continue

        if event_type == "task_tool_observation_recorded":
            observation = _record(payload.get("observation"))
            if not observation:
                continue
            unit = resolve_unit(event, fallback_kind="tool_action")
            _apply_tool_observation(unit, observation, event)
            continue

        if event_type == "agent_todo_initialized":
            unit = resolve_unit(event, fallback_kind="stage")
            _set_if_better(unit, "title", "建立处理清单")
            _set_if_visible(unit, "action", "已把任务目标转成可跟踪的处理清单。")
            _set_if_better(unit, "state", "completed")
            _append_trace_ref(unit, event)
            continue

        if event_type in {"task_run_lifecycle_started", "task_run_executor_started"}:
            unit = resolve_unit(event, fallback_kind="stage")
            _set_if_better(unit, "title", "开始处理")
            _set_if_visible(unit, "action", _goal_from_event(payload) or "已开始处理。")
            _set_if_better(unit, "state", "running")
            _append_trace_ref(unit, event)
            continue

        if event_type in {"user_work_instruction_recorded", "active_task_steer_recorded"}:
            unit = resolve_unit(event, fallback_kind="stage")
            _set_if_better(unit, "title", "纳入补充要求")
            _set_if_visible(unit, "action", _user_instruction_from_event(payload))
            _set_if_better(unit, "state", "completed")
            _append_trace_ref(unit, event)
            continue

        if event_type == "task_run_lifecycle_finished":
            unit = resolve_unit(event, fallback_kind="terminal")
            task_payload = _record(payload.get("task_run"))
            status = _text(task_payload.get("status") or getattr(task_run, "status", ""))
            _set_if_better(unit, "kind", "terminal")
            _set_if_better(unit, "title", "处理已完成" if status == "completed" else "处理已停止")
            _set_if_visible(unit, "judgment", task_payload.get("terminal_reason") or status)
            _set_if_better(unit, "state", "completed" if status == "completed" else "error")
            _append_trace_ref(unit, event)

    normalized_units = [_normalize_work_unit(unit) for unit in units]
    normalized_units = [unit for unit in normalized_units if _work_unit_has_visible_value(unit)]
    normalized_units = normalized_units[-max(1, int(max_work_units or 12)) :]
    _ensure_closeout_unit(task_run=task_run, monitor=dict(monitor or {}), work_units=normalized_units)
    mission = _build_mission(task_run=task_run, monitor=dict(monitor or {}), work_units=normalized_units)
    return {
        "mission": mission,
        "work_units": normalized_units,
        "technical_trace": [item for item in technical_trace if item][-max(1, int(max_trace_entries or 48)) :],
        "authority": "harness.runtime.progress_presenter",
    }


def _apply_model_action(unit: dict[str, Any], action: dict[str, Any], event: dict[str, Any]) -> None:
    action_type = _text(action.get("action_type"))
    public_state = _record(action.get("public_action_state"))
    current_judgment = action.get("current_judgment") or public_state.get("current_judgment")
    next_action = action.get("next_action") or public_state.get("next_action")
    progress_note = action.get("public_progress_note")
    if action_type == "tool_call":
        _apply_tool_action(unit, action, {}, event)
        _set_if_visible(unit, "judgment", current_judgment or progress_note)
        _set_if_visible(unit, "next_action", next_action)
    elif action_type == "respond":
        _set_if_better(unit, "kind", "terminal")
        _set_if_better(unit, "title", "整理最终回复")
        _set_if_visible(unit, "judgment", current_judgment or progress_note or action.get("final_answer"))
        _set_if_better(unit, "state", "running")
    elif action_type == "ask_user":
        _set_if_better(unit, "kind", "model_judgment")
        _set_if_better(unit, "title", "等待补充信息")
        _set_if_visible(unit, "judgment", current_judgment or progress_note)
        _set_if_visible(unit, "next_action", action.get("user_question") or next_action)
        _set_if_better(unit, "state", "waiting")
    elif action_type == "block":
        _set_if_better(unit, "kind", "model_judgment")
        _set_if_better(unit, "title", "确认阻塞边界")
        _set_if_visible(unit, "judgment", action.get("blocking_reason") or current_judgment or progress_note)
        _set_if_better(unit, "state", "error")
    else:
        _set_if_better(unit, "kind", "model_judgment")
        _set_if_better(unit, "title", "确认下一步")
        _set_if_visible(unit, "judgment", current_judgment or progress_note)
        _set_if_better(unit, "state", "running")
    _set_if_visible(unit, "next_action", next_action)
    _append_trace_ref(unit, event)


def _apply_model_action_state(unit: dict[str, Any], payload: dict[str, Any], action: dict[str, Any], event: dict[str, Any]) -> None:
    public_state = _record(payload.get("public_action_state"))
    current_judgment = payload.get("current_judgment") or public_state.get("current_judgment")
    next_action = payload.get("next_action") or public_state.get("next_action")
    completion_status = payload.get("completion_status") or public_state.get("completion_status")
    if action:
        _apply_model_action(unit, action, event)
    else:
        _set_if_better(unit, "kind", "model_judgment")
        _set_if_better(unit, "title", "确认下一步")
    _set_if_visible(unit, "judgment", current_judgment or payload.get("public_progress_note") or payload.get("summary"))
    _set_if_visible(unit, "next_action", next_action)
    if completion_status:
        _set_if_visible(unit, "risk", completion_status)
    _set_if_better(unit, "state", _state_from_status(payload.get("status")))
    _append_trace_ref(unit, event)


def _apply_tool_action(unit: dict[str, Any], action: dict[str, Any], payload: dict[str, Any], event: dict[str, Any]) -> None:
    tool_call = _record(action.get("tool_call"))
    tool_name = _tool_name(tool_call.get("tool_name") or tool_call.get("name") or payload.get("tool_name"))
    tool_args = _record(tool_call.get("args") or tool_call.get("tool_args"))
    target = _tool_target_preview(tool_args)
    if tool_name:
        _set_if_better(unit, "kind", _work_kind_from_tool(tool_name))
        _set_if_better(unit, "title", _tool_title(tool_name, target))
        _set_if_visible(unit, "action", _tool_action_sentence(tool_name, target))
    else:
        _set_if_better(unit, "title", "执行操作")
        _set_if_visible(unit, "action", payload.get("summary"))
    _set_if_better(unit, "state", _state_from_status(payload.get("status") or "running"))
    _append_trace_ref(unit, event)


def _apply_tool_observation(unit: dict[str, Any], observation: dict[str, Any], event: dict[str, Any]) -> None:
    payload = _record(observation.get("payload"))
    source = _text(observation.get("source"))
    tool_name = _tool_name(payload.get("tool_name") or source)
    tool_args = _record(payload.get("tool_args"))
    target = _tool_target_preview(tool_args)
    evidence = _tool_evidence(tool_name=tool_name, tool_args=tool_args, observation=observation)
    _set_if_better(unit, "kind", _work_kind_from_tool(tool_name))
    _set_if_better(unit, "title", _tool_title(tool_name, target))
    _set_if_visible(unit, "action", _tool_action_sentence(tool_name, target))
    if evidence:
        _append_evidence(unit, evidence)
        inferred_next = _next_action_from_evidence(tool_name, evidence, target)
        _set_if_visible(unit, "next_action", inferred_next)
    _set_if_better(unit, "state", "error" if evidence.get("status") == "error" else "completed")
    _append_trace_ref(unit, event)


def _tool_evidence(*, tool_name: str, tool_args: dict[str, Any], observation: dict[str, Any]) -> dict[str, str]:
    payload = _record(observation.get("payload"))
    raw_result = _observation_result_value(payload)
    parsed = _parse_result(raw_result)
    error = _visible_text(observation.get("error") or payload.get("error") or _result_error(parsed))
    target = _tool_target_preview(tool_args)
    observed_paths = _string_list(payload.get("observed_paths"))
    matched_paths = _string_list(payload.get("matched_paths"))
    artifact_refs = _string_list(payload.get("artifact_refs"))
    envelope = _record(payload.get("result_envelope"))
    if not observed_paths:
        observed_paths = _string_list(envelope.get("observed_paths"))
    if not matched_paths:
        matched_paths = _string_list(envelope.get("matched_paths"))
    if not artifact_refs:
        artifact_refs = _string_list(envelope.get("artifact_refs"))
    result_text = _result_text(parsed if parsed is not None else raw_result)
    normalized = tool_name.lower()

    if error:
        return {
            "label": _tool_label(tool_name),
            "summary": f"工具返回失败：{error}",
            "status": "error",
        }

    if normalized == "path_exists":
        exists = _result_bool(parsed if parsed is not None else raw_result)
        if exists is False:
            return {
                "label": "path_exists",
                "summary": "目标文件尚未存在，路径检查成功；下一步需要创建。",
                "status": "negative_evidence",
            }
        if exists is True:
            return {
                "label": "path_exists",
                "summary": "目标路径已存在，可进入读取、覆盖判断或验收。",
                "status": "positive_evidence",
            }

    if normalized in {"write_file", "edit_file", "apply_patch"}:
        path = (observed_paths or [target])[0] if (observed_paths or target) else ""
        return {
            "label": _tool_label(tool_name),
            "summary": f"文件已写入：{path}" if path else "文件写入已完成。",
            "status": "success",
        }

    if normalized in {"read_file", "read_path"}:
        path = (observed_paths or [target])[0] if (observed_paths or target) else ""
        return {
            "label": _tool_label(tool_name),
            "summary": f"已读取文件：{path}" if path else "文件内容已读取，可继续分析。",
            "status": "success",
        }

    if normalized in {"list_dir", "stat_path"}:
        return {
            "label": _tool_label(tool_name),
            "summary": "已读取路径信息，可继续判断目录结构。",
            "status": "success",
        }

    if normalized in {"search_text", "search_files", "glob_paths"}:
        if matched_paths:
            preview = "、".join(matched_paths[:3])
            return {
                "label": _tool_label(tool_name),
                "summary": f"已找到关键证据：{preview}",
                "status": "success",
            }
        if _result_bool(parsed if parsed is not None else raw_result) is False or not _visible_text(result_text):
            return {
                "label": _tool_label(tool_name),
                "summary": "未找到关键文本，需要补充实现或换关键词验证。",
                "status": "negative_evidence",
            }
        return {
            "label": _tool_label(tool_name),
            "summary": f"搜索完成：{_short(result_text, 96)}",
            "status": "success",
        }

    if normalized in {"terminal", "shell", "run_command", "powershell"}:
        if _terminal_failed(payload, parsed):
            return {
                "label": _tool_label(tool_name),
                "summary": "命令失败，需要修正命令或路径。",
                "status": "error",
            }
        return {
            "label": _tool_label(tool_name),
            "summary": "命令执行完成，结果已记录。",
            "status": "success",
        }

    if artifact_refs:
        return {
            "label": _tool_label(tool_name),
            "summary": f"工具完成并记录 {len(artifact_refs)} 个产物。",
            "status": "success",
        }
    summary = _visible_text(result_text or observation.get("summary"))
    return {
        "label": _tool_label(tool_name),
        "summary": summary or "工具执行完成，结果已写入运行上下文。",
        "status": "success",
    }


def _build_mission(*, task_run: Any, monitor: dict[str, Any], work_units: list[dict[str, Any]]) -> dict[str, str]:
    latest = work_units[-1] if work_units else {}
    state = _mission_state(task_run=task_run, monitor=monitor, latest=latest)
    phase = _mission_phase(latest, state)
    closeout_summary = _closeout_summary(task_run=task_run, monitor=monitor)
    current_action = _visible_text(
        closeout_summary if state == "completed" else ""
    ) or _visible_text(
        latest.get("judgment")
        or latest.get("action")
        or monitor.get("latest_step_summary")
        or monitor.get("summary")
    )
    next_action = _visible_text(latest.get("next_action"))
    completed = sum(1 for unit in work_units if unit.get("state") == "completed")
    progress_label = f"{completed}/{len(work_units)} {phase}" if work_units else _state_label(state)
    return {
        "goal": _goal_from_task_run(task_run, monitor),
        "phase": phase,
        "state": state,
        "current_action": current_action or _state_label(state),
        "next_action": next_action,
        "progress_label": progress_label,
        "closeout_summary": closeout_summary if state == "completed" else "",
    }


def _ensure_closeout_unit(*, task_run: Any, monitor: dict[str, Any], work_units: list[dict[str, Any]]) -> None:
    state = _mission_state(task_run=task_run, monitor=monitor, latest=work_units[-1] if work_units else {})
    if state != "completed":
        return
    closeout = _closeout_summary(task_run=task_run, monitor=monitor)
    if not closeout:
        return
    if work_units and work_units[-1].get("kind") == "terminal":
        work_units[-1]["title"] = _visible_text(work_units[-1].get("title")) or "结果收口"
        work_units[-1]["judgment"] = _visible_text(work_units[-1].get("judgment")) or closeout
        work_units[-1]["state"] = "completed"
        return
    work_units.append(
        {
            "unit_id": "workunit:closeout",
            "kind": "terminal",
            "title": "结果收口",
            "state": "completed",
            "judgment": closeout,
            "action": "",
            "evidence": [],
            "next_action": "",
            "risk": "",
            "technical_trace_refs": [],
        }
    )


def _normalize_work_unit(unit: dict[str, Any]) -> dict[str, Any]:
    evidence = []
    seen_evidence: set[tuple[str, str]] = set()
    for item in list(unit.get("evidence") or []):
        normalized = {
            "label": _visible_text(_record(item).get("label")) or "证据",
            "summary": _visible_text(_record(item).get("summary")),
            "status": _text(_record(item).get("status") or "success"),
        }
        if not normalized["summary"]:
            continue
        key = (normalized["label"], normalized["summary"])
        if key in seen_evidence:
            continue
        seen_evidence.add(key)
        evidence.append(normalized)
    refs = []
    for ref in list(unit.get("technical_trace_refs") or []):
        normalized_ref = _text(ref)
        if normalized_ref and normalized_ref not in refs:
            refs.append(normalized_ref)
    result = {
        "unit_id": _text(unit.get("unit_id")),
        "kind": _text(unit.get("kind") or "stage"),
        "title": _visible_text(unit.get("title")) or "推进任务",
        "state": _text(unit.get("state") or "running"),
        "judgment": _visible_text(unit.get("judgment")),
        "action": _visible_text(unit.get("action")),
        "evidence": evidence,
        "next_action": _visible_text(unit.get("next_action")),
        "risk": _visible_text(unit.get("risk")),
        "technical_trace_refs": refs,
    }
    return result


def _work_unit_has_visible_value(unit: dict[str, Any]) -> bool:
    for key in ("title", "judgment", "action", "next_action", "risk"):
        if _visible_text(unit.get(key)):
            return True
    return bool(unit.get("evidence"))


def _new_work_unit(key: str, *, kind: str) -> dict[str, Any]:
    return {
        "unit_id": f"workunit:{key}",
        "kind": kind,
        "title": "",
        "state": "running",
        "judgment": "",
        "action": "",
        "evidence": [],
        "next_action": "",
        "risk": "",
        "technical_trace_refs": [],
    }


def _ordered_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [dict(item or {}) for item in events],
        key=lambda item: (float(item.get("created_at") or 0.0), int(item.get("offset") or 0)),
    )


def _observations_by_ref(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = _record(event.get("payload"))
        observation = _record(payload.get("observation"))
        observation_id = _text(observation.get("observation_id"))
        if observation_id:
            result[observation_id] = observation
    return result


def _action_requests_by_ref(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        if _text(event.get("event_type")) != "model_action_request_received":
            continue
        payload = _record(event.get("payload"))
        action = _record(payload.get("model_action_request"))
        request_id = _text(action.get("request_id"))
        if request_id:
            result[request_id] = action
    return result


def _event_group_key(event: dict[str, Any], *, observations_by_ref: dict[str, dict[str, Any]]) -> str:
    refs = _record(event.get("refs"))
    payload = _record(event.get("payload"))
    for key in ("action_request_ref", "observation_ref", "runtime_invocation_packet_ref"):
        value = _text(refs.get(key) or payload.get(key))
        if value:
            if key == "observation_ref":
                observation = observations_by_ref.get(value, {})
                action_ref = _text(observation.get("action_request_ref"))
                if action_ref:
                    return f"action:{action_ref}"
            return f"{key}:{value}"
    observation = _record(payload.get("observation"))
    action_ref = _text(observation.get("action_request_ref"))
    if action_ref:
        return f"action:{action_ref}"
    observation_id = _text(observation.get("observation_id"))
    if observation_id:
        return f"observation:{observation_id}"
    action = _record(payload.get("model_action_request"))
    request_id = _text(action.get("request_id"))
    if request_id:
        return f"action:{request_id}"
    return ""


def _alias_unit_keys(
    unit: dict[str, Any],
    event: dict[str, Any],
    *,
    observations_by_ref: dict[str, dict[str, Any]],
    units_by_key: dict[str, dict[str, Any]],
) -> None:
    refs = _record(event.get("refs"))
    payload = _record(event.get("payload"))
    candidates = []
    for key in ("action_request_ref", "observation_ref", "runtime_invocation_packet_ref"):
        value = _text(refs.get(key) or payload.get(key))
        if value:
            candidates.append(f"{key}:{value}")
            if key == "observation_ref":
                observation = observations_by_ref.get(value, {})
                action_ref = _text(observation.get("action_request_ref"))
                if action_ref:
                    candidates.append(f"action:{action_ref}")
    observation = _record(payload.get("observation"))
    observation_id = _text(observation.get("observation_id"))
    action_ref = _text(observation.get("action_request_ref"))
    if observation_id:
        candidates.append(f"observation_ref:{observation_id}")
        candidates.append(f"observation:{observation_id}")
    if action_ref:
        candidates.append(f"action:{action_ref}")
    action = _record(payload.get("model_action_request"))
    request_id = _text(action.get("request_id"))
    if request_id:
        candidates.append(f"action:{request_id}")
        candidates.append(f"action_request_ref:{request_id}")
    for key in candidates:
        units_by_key.setdefault(key, unit)


def _technical_trace_item(event: dict[str, Any], *, observations_by_ref: dict[str, dict[str, Any]]) -> dict[str, Any]:
    payload = _record(event.get("payload"))
    refs = _record(event.get("refs"))
    observation = _record(payload.get("observation"))
    if not observation:
        observation_ref = _text(refs.get("observation_ref"))
        observation = observations_by_ref.get(observation_ref, {})
    observation_payload = _record(observation.get("payload"))
    action = _record(payload.get("model_action_request"))
    tool_call = _record(action.get("tool_call"))
    tool_name = _tool_name(
        observation_payload.get("tool_name")
        or observation.get("source")
        or tool_call.get("tool_name")
        or tool_call.get("name")
        or refs.get("tool_name")
    )
    raw_preview = _raw_preview(
        observation_payload.get("result")
        if observation_payload
        else payload.get("summary") or payload.get("public_progress_note") or action.get("public_progress_note") or payload
    )
    result = {
        "event_id": _event_id(event),
        "event_type": _text(event.get("event_type")),
        "created_at": float(event.get("created_at") or 0.0),
        "tool_name": tool_name,
        "target": _tool_target_preview(_record(observation_payload.get("tool_args") or tool_call.get("args") or tool_call.get("tool_args"))),
        "raw_preview": raw_preview,
    }
    return {key: value for key, value in result.items() if value not in ("", None)}


def _append_trace_ref(unit: dict[str, Any], event: dict[str, Any]) -> None:
    ref = _event_id(event)
    if ref and ref not in unit["technical_trace_refs"]:
        unit["technical_trace_refs"].append(ref)


def _append_evidence(unit: dict[str, Any], evidence: dict[str, str]) -> None:
    if not evidence.get("summary"):
        return
    key = (evidence.get("label", ""), evidence.get("summary", ""))
    for item in unit["evidence"]:
        if (item.get("label", ""), item.get("summary", "")) == key:
            return
    unit["evidence"].append(evidence)


def _set_if_visible(unit: dict[str, Any], key: str, value: Any) -> None:
    text = _visible_text(value)
    if text:
        unit[key] = text


def _set_if_better(unit: dict[str, Any], key: str, value: Any) -> None:
    text = _text(value)
    if key == "state":
        current = _text(unit.get(key) or "running")
        rank = {"": 0, "running": 1, "completed": 2, "waiting": 3, "error": 4}
        if text and rank.get(text, 1) >= rank.get(current, 1):
            unit[key] = text
        return
    if text and (not _text(unit.get(key)) or _text(unit.get(key)) in {"stage", "tool_action", "推进任务", "执行操作", "确认下一步"}):
        unit[key] = text


def _is_suppressed_step(step: str, payload: dict[str, Any]) -> bool:
    if step.startswith(("task_model_action_invocation_started", "task_model_action_waiting")):
        return True
    if step.startswith("task_execution_packet_compiled"):
        return True
    summary = _visible_text(payload.get("summary"))
    public_note = _visible_text(payload.get("public_progress_note"))
    return not summary and not public_note


def _visible_text(value: Any, *, limit: int = 220) -> str:
    text = public_runtime_progress_summary(value).strip()
    if not text:
        return ""
    text = " ".join(text.split()).strip()
    if text in _SUPPRESSED_VISIBLE_TEXT:
        return ""
    lower = text.lower()
    if lower in _RAW_STATUS:
        return ""
    if lower in {"true", "false", "null", "none"}:
        return ""
    if _looks_like_raw_json(text):
        return ""
    if _looks_like_internal_reference(text):
        return ""
    return _short(text, limit)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _short(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split()).strip()
    if limit <= 0:
        return text
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "..."


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _event_id(event: dict[str, Any]) -> str:
    return _text(event.get("event_id") or f"{event.get('run_id') or event.get('task_run_id')}:{event.get('offset')}")


def _tool_name(value: Any) -> str:
    return _text(value).removeprefix("tool:").strip()


def _tool_label(tool_name: str) -> str:
    return tool_name or "工具"


def _tool_target_preview(args: dict[str, Any]) -> str:
    for key in ("path", "file_path", "relative_path", "target_path", "artifact_path"):
        if _text(args.get(key)):
            return _short(args.get(key), 120)
    for key in ("query", "pattern", "search", "text"):
        if _text(args.get(key)):
            return _short(args.get(key), 120)
    for key in ("command", "shell_command", "cmd", "script"):
        if _text(args.get(key)):
            return _short(args.get(key), 140)
    for key in ("url", "href"):
        if _text(args.get(key)):
            return _short(args.get(key), 140)
    return ""


def _tool_title(tool_name: str, target: str) -> str:
    normalized = tool_name.lower()
    if normalized == "path_exists":
        return "确认 artifact 路径" if target else "确认路径状态"
    if normalized in {"stat_path", "list_dir"}:
        return "检查路径信息"
    if normalized in {"read_file", "read_path"}:
        return "读取文件内容"
    if normalized in {"write_file", "edit_file", "apply_patch"}:
        return "写入文件"
    if normalized in {"search_text", "search_files", "glob_paths"}:
        return "搜索证据"
    if normalized in {"terminal", "shell", "run_command", "powershell"}:
        return "运行命令"
    return f"执行 {tool_name}" if tool_name else "执行操作"


def _tool_action_sentence(tool_name: str, target: str) -> str:
    normalized = tool_name.lower()
    if normalized == "path_exists":
        return f"检查 {target} 是否已存在。" if target else "检查目标路径是否已存在。"
    if normalized in {"read_file", "read_path"}:
        return f"读取 {target}。" if target else "读取目标文件。"
    if normalized in {"write_file", "edit_file", "apply_patch"}:
        return f"写入 {target}。" if target else "写入目标文件。"
    if normalized in {"search_text", "search_files", "glob_paths"}:
        return f"搜索 {target}。" if target else "搜索可用证据。"
    if normalized in {"terminal", "shell", "run_command", "powershell"}:
        return "运行命令处理当前步骤。"
    return f"调用 {tool_name}。" if tool_name else ""


def _work_kind_from_tool(tool_name: str) -> str:
    normalized = tool_name.lower()
    if normalized in {"path_exists", "stat_path", "list_dir", "read_file", "read_path"}:
        return "inspect_path"
    if normalized in {"write_file", "edit_file", "apply_patch"}:
        return "write_file"
    if normalized in {"search_text", "search_files", "glob_paths"}:
        return "search_text"
    if normalized in {"terminal", "shell", "run_command", "powershell"}:
        return "terminal"
    return "tool_action" if normalized else "stage"


def _parse_result(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    if _looks_like_raw_json(text):
        try:
            return json.loads(text)
        except Exception:
            return value
    return value


def _observation_result_value(payload: dict[str, Any]) -> Any:
    if "result" in payload:
        return payload.get("result")
    envelope = _record(payload.get("result_envelope"))
    structured = _record(envelope.get("structured_payload"))
    for key in ("result", "summary", "output", "text", "exists", "matched", "found"):
        if key in structured:
            return structured.get(key)
    for key in ("result", "summary", "output", "text", "exists", "matched", "found", "ok"):
        if key in envelope:
            return envelope.get(key)
    return ""


def _result_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        for key in ("exists", "result", "ok", "matched", "found"):
            if isinstance(value.get(key), bool):
                return bool(value.get(key))
    text = _text(value).lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _result_error(value: Any) -> str:
    if isinstance(value, dict):
        structured = _record(value.get("structured_error"))
        return _text(value.get("error") or value.get("message") or structured.get("message") or structured.get("error"))
    return ""


def _result_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("summary", "output", "text", "result"):
            if key in value and not isinstance(value.get(key), (dict, list)):
                return _text(value.get(key))
        return ""
    if isinstance(value, list):
        return json.dumps(value[:3], ensure_ascii=False)
    if isinstance(value, bool):
        return ""
    return _text(value)


def _terminal_failed(payload: dict[str, Any], parsed: Any) -> bool:
    if payload.get("error"):
        return True
    if isinstance(parsed, dict):
        if parsed.get("ok") is False:
            return True
        for key in ("exit_code", "returncode", "code"):
            value = parsed.get(key)
            if isinstance(value, int) and value != 0:
                return True
    return False


def _next_action_from_evidence(tool_name: str, evidence: dict[str, str], target: str) -> str:
    status = evidence.get("status")
    normalized = tool_name.lower()
    if status == "error":
        return "修正失败原因后重新执行。"
    if normalized == "path_exists" and status == "negative_evidence":
        return f"创建 {target}。" if target else "创建目标文件。"
    if normalized in {"write_file", "edit_file", "apply_patch"}:
        return "继续读取或运行验证。"
    if normalized in {"search_text", "search_files", "glob_paths"} and status == "negative_evidence":
        return "补充实现后重新验证关键文本。"
    return ""


def _state_from_status(value: Any) -> str:
    status = _text(value).lower()
    if status in {"completed", "success", "done"}:
        return "completed"
    if status in {"failed", "error", "blocked", "aborted", "cancelled"}:
        return "error"
    if status.startswith("wait") or status in {"paused", "queued"}:
        return "waiting"
    return "running"


def _mission_state(*, task_run: Any, monitor: dict[str, Any], latest: dict[str, Any]) -> str:
    for value in (
        getattr(task_run, "status", ""),
        monitor.get("lifecycle"),
        monitor.get("status"),
        latest.get("state"),
    ):
        state = _state_from_status(value)
        if state == "completed":
            return "completed"
        if state == "error":
            return "failed"
        if state == "waiting":
            return "waiting"
        if _text(value):
            return "running"
    return "running"


def _mission_phase(latest: dict[str, Any], state: str) -> str:
    if state == "completed":
        return "结果收口"
    if state == "failed":
        return "受阻"
    if state == "waiting":
        return "等待确认"
    title = _visible_text(latest.get("title"))
    return title or "推进中"


def _state_label(state: str) -> str:
    return {
        "running": "正在处理",
        "waiting": "等待确认",
        "completed": "已完成",
        "blocked": "受阻",
        "failed": "失败",
    }.get(state, "正在处理")


def _closeout_summary(*, task_run: Any, monitor: dict[str, Any]) -> str:
    diagnostics = _record(getattr(task_run, "diagnostics", {}))
    for value in (
        diagnostics.get("final_answer"),
        diagnostics.get("closeout_summary"),
        monitor.get("final_answer"),
        monitor.get("summary"),
        getattr(task_run, "terminal_reason", ""),
    ):
        visible = _visible_text(value, limit=260)
        if visible:
            return visible
    return "任务已完成，结果和证据已记录。"


def _stage_title(step: str, status: Any) -> str:
    if step.startswith("task_run_completed") or _text(status) == "completed":
        return "处理已完成"
    if step.startswith("task_tool"):
        return "执行操作"
    if step.startswith("model"):
        return "确认下一步"
    return "推进任务"


def _goal_from_task_run(task_run: Any, monitor: dict[str, Any]) -> str:
    diagnostics = _record(getattr(task_run, "diagnostics", {}))
    contract = _record(diagnostics.get("contract"))
    for value in (
        contract.get("user_visible_goal"),
        contract.get("task_run_goal"),
        diagnostics.get("user_visible_goal"),
        diagnostics.get("task_run_goal"),
        getattr(task_run, "goal", ""),
        getattr(task_run, "title", ""),
        monitor.get("title"),
    ):
        visible = _visible_text(value, limit=120)
        if visible:
            return visible
    return "处理当前任务"


def _goal_from_event(payload: dict[str, Any]) -> str:
    contract = _record(payload.get("contract"))
    task_run = _record(payload.get("task_run"))
    return _visible_text(contract.get("user_visible_goal") or contract.get("task_run_goal") or task_run.get("goal") or task_run.get("title"))


def _user_instruction_from_event(payload: dict[str, Any]) -> str:
    steer = _record(payload.get("steer"))
    observation = _record(payload.get("observation"))
    observation_payload = _record(observation.get("payload"))
    structured = _record(observation_payload.get("structured_payload"))
    return _visible_text(steer.get("content") or structured.get("user_instruction") or observation_payload.get("result"))


def _raw_preview(value: Any, limit: int = 220) -> str:
    if isinstance(value, str):
        text = value.strip()
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            text = str(value)
    return _short(text, limit)


def _looks_like_raw_json(value: str) -> bool:
    text = value.strip()
    return (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))


def _looks_like_internal_reference(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    return (
        text.startswith(("taskrun:", "turnrun:", "task:", "turn:", "rtevt:", "rtobs:", "obs:"))
        or text.startswith(("harness.", "backend.", "runtime.", "query.", "agent_system.", "task_system."))
    )
