from __future__ import annotations

from hashlib import sha1
from typing import Any

from harness.runtime.progress_presenter import public_todo_plan_from_event
from harness.runtime.public_chat_timeline import public_todo_plan_item
from harness.runtime.public_projection_filters import should_hide_public_tool_observation
from harness.runtime.public_progress import public_runtime_progress_summary


_INTERNAL_STEP_SUMMARIES = {
    "turn_started",
    "runtime_packet_compiled",
    "model_action_received",
    "action_admission_checked",
    "bounded_observation_recorded",
}

_SUPPRESSED_TEXT = {
    "",
    "done",
    "completed",
    "running",
    "working",
    "回答已生成并写回会话",
    "会话输出完成",
}

_GENERIC_TOOL_WAIT_PREFIXES = (
    "已发起工具调用，正在等待工具返回",
    "已经过工具调用，正在等待工具返回",
)


def project_public_timeline_delta(
    public_event_type: str,
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    event_type = str(public_event_type or "").strip()
    if not event_type:
        return []
    item = _item_for_event(event_type, data)
    return [item] if item else []


def _item_for_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    if event_type == "runtime_step_summary":
        return _runtime_step_summary_item(data)
    if event_type == "model_action_admission":
        return _model_action_admission_item(data)
    if event_type == "turn_tool_observation_recorded":
        return _turn_tool_observation_item(data)
    if event_type == "task_run_lifecycle_event":
        return _task_run_lifecycle_item(data)
    if event_type == "active_task_steer_accepted":
        return _status_item(
            item_id=_stable_id("steer", str(data.get("runtime_task_run_id") or ""), str(data.get("summary") or "")),
            title="已收到补充要求",
            detail=_visible_text(data.get("summary")),
            state="running",
        )
    if event_type == "done":
        return _done_item(data)
    if event_type == "error":
        return _blocked_item(
            item_id=_stable_id("error", str(data.get("runtime_task_run_id") or ""), str(data.get("error") or "")),
            text=_visible_text(data.get("error") or data.get("content") or "处理失败"),
            state="error",
        )
    if event_type == "stopped":
        return _status_item(
            item_id=_stable_id("stopped", str(data.get("runtime_task_run_id") or ""), str(data.get("reason") or "")),
            title="已停止当前处理",
            detail=_visible_text(data.get("reason") or data.get("content")),
            state="error",
        )
    return {}


def _task_run_lifecycle_item(data: dict[str, Any]) -> dict[str, Any]:
    event = _record(data.get("event"))
    if str(event.get("event_type") or "").strip() != "agent_todo_initialized":
        return {}
    return public_todo_plan_item(public_todo_plan_from_event(event))


def _model_action_admission_item(data: dict[str, Any]) -> dict[str, Any]:
    event = _record(data.get("event"))
    payload = _record(event.get("payload"))
    request = _record(payload.get("model_action_request"))
    action_type = str(request.get("action_type") or "").strip().lower()
    if action_type != "tool_call":
        return {}
    tool_name, target = _tool_details_from_event(request)
    title = _tool_title(step="model_action_admission", tool_name=tool_name, target=target, state="running")
    detail = _tool_detail(
        summary=_visible_text(request.get("public_progress_note")),
        agent_brief="",
        target=target,
    )
    trace_ref = str(event.get("event_id") or "") or _stable_id("tool-admission", tool_name, target)
    item_id = _tool_activity_id(data=data, event=event, tool_name=tool_name, target=target, fallback=trace_ref)
    return _compact(
        {
            "item_id": item_id,
            "kind": "tool_activity",
            "title": title,
            "detail": detail if detail and detail != title else "",
            "state": "running",
            "trace_refs": [trace_ref],
        }
    )


def _turn_tool_observation_item(data: dict[str, Any]) -> dict[str, Any]:
    event = _record(data.get("event"))
    payload = _record(event.get("payload"))
    observation = _record(payload.get("tool_observation"))
    if not observation:
        return {}
    tool_name = str(observation.get("tool_name") or "").strip()
    if tool_name == "agent_todo":
        return public_todo_plan_item(public_todo_plan_from_event(event))
    target = _tool_target_from_observation(observation)
    status = str(observation.get("status") or "").strip().lower()
    state = "done" if status in {"ok", "success", "done", "completed"} else "error"
    title = _tool_title(step="turn_tool_observation_recorded", tool_name=tool_name, target=target, state=state)
    detail = _tool_observation_detail(observation, target=target)
    envelope = _record(observation.get("result_envelope"))
    if state == "error" and should_hide_public_tool_observation(
        tool_name,
        target,
        detail,
        observation.get("error"),
        observation.get("text"),
        envelope.get("error"),
        envelope.get("text"),
        _record(observation.get("structured_error")).get("message"),
        _record(envelope.get("structured_error")).get("message"),
    ):
        return {}
    trace_ref = str(event.get("event_id") or "") or _stable_id("tool-observation", tool_name, target or detail)
    item_id = _tool_activity_id(data=data, event=event, tool_name=tool_name, target=target or detail, fallback=trace_ref)
    if state == "error":
        return _compact(
            {
                "item_id": item_id,
                "kind": "blocked",
                "text": detail or title,
                "state": state,
                "trace_refs": [trace_ref],
            }
        )
    return _compact(
        {
            "item_id": item_id,
            "kind": "tool_activity",
            "title": title,
            "detail": detail if detail and detail != title else "",
            "state": state,
            "trace_refs": [trace_ref],
        }
    )


def _runtime_step_summary_item(data: dict[str, Any]) -> dict[str, Any]:
    step = str(data.get("step") or "").strip()
    if not step or step in _INTERNAL_STEP_SUMMARIES:
        return {}
    event = _record(data.get("event"))
    todo = public_todo_plan_item(public_todo_plan_from_event(event))
    if todo:
        return todo
    status = str(data.get("status") or "").strip().lower()
    payload = _record(event.get("payload"))
    summary = _visible_text(data.get("public_progress_note") or data.get("summary"))
    agent_brief = _visible_text(data.get("agent_brief_output") or data.get("current_judgment"))
    state = _timeline_state(status)
    trace_ref = str(event.get("event_id") or "") or _stable_id("step", step, summary or agent_brief)

    if _looks_like_tool_step(step, payload):
        tool_name, target = _tool_details_from_event(payload)
        title = _tool_title(step=step, tool_name=tool_name, target=target, state=state)
        detail = _tool_detail(summary=summary, agent_brief=agent_brief, target=target)
        item_id = _tool_activity_id(data=data, event=event, tool_name=tool_name, target=target or detail, fallback=trace_ref)
        return _compact(
            {
                "item_id": item_id,
                "kind": "tool_activity",
                "title": title,
                "detail": detail if detail and detail != title else "",
                "state": state,
                "trace_refs": [trace_ref],
            }
        )

    prose = _visible_text(agent_brief or summary)
    if not prose:
        return {}
    return _compact(
        {
            "item_id": trace_ref,
            "kind": "opening_judgment" if not _is_status_only_step(step) else "status_update",
            "title": "开局判断" if not _is_status_only_step(step) else prose,
            "text": prose,
            "state": state,
            "trace_refs": [trace_ref],
        }
    )


def _done_item(data: dict[str, Any]) -> dict[str, Any]:
    task_run_id = str(data.get("runtime_task_run_id") or "").strip()
    terminal_reason = str(data.get("terminal_reason") or "").strip()
    answer_channel = str(data.get("answer_channel") or "").strip()
    summary = _visible_text(data.get("receipt_summary") or data.get("summary") or data.get("message"))
    content = _visible_text(data.get("content"))
    if terminal_reason == "task_executor_scheduled" or answer_channel == "task_control":
        return _status_item(
            item_id=_stable_id("handoff", task_run_id, terminal_reason),
            title="后台任务已接管",
            detail="后续执行会继续投影到当前会话。",
            state="running",
        )
    if str(data.get("completion_state") or "").strip() == "task_steer_accepted":
        return _status_item(
            item_id=_stable_id("steer-done", task_run_id, summary),
            title="已收到补充要求",
            detail=summary,
            state="running",
        )
    if summary and summary != content:
        return _compact(
            {
                "item_id": _stable_id("final", task_run_id, summary),
                "kind": "final_summary",
                "text": summary,
                "state": "done",
            }
        )
    return {}


def _status_item(*, item_id: str, title: str, detail: str = "", state: str) -> dict[str, Any]:
    return _compact(
        {
            "item_id": item_id,
            "kind": "status_update",
            "title": title,
            "detail": detail,
            "state": state,
        }
    )


def _blocked_item(*, item_id: str, text: str, state: str) -> dict[str, Any]:
    if not text:
        return {}
    return _compact(
        {
            "item_id": item_id,
            "kind": "blocked",
            "text": text,
            "state": state,
        }
    )


def _looks_like_tool_step(step: str, payload: dict[str, Any]) -> bool:
    normalized = step.lower()
    if "tool" in normalized or "observation" in normalized:
        return True
    action_type = str(payload.get("action_type") or _record(payload.get("public_action_state")).get("action_type") or "").strip().lower()
    return action_type == "tool_call"


def _is_status_only_step(step: str) -> bool:
    normalized = step.lower()
    return normalized.startswith("task_executor_scheduled") or "resume" in normalized or "handoff" in normalized


def _tool_details_from_event(payload: dict[str, Any]) -> tuple[str, str]:
    public_action_state = _record(payload.get("public_action_state"))
    direct_tool_call = _record(payload.get("tool_call"))
    action_request = _record(payload.get("action_request"))
    nested_tool_call = _record(action_request.get("tool_call"))
    tool_name = str(
        payload.get("tool_name")
        or public_action_state.get("tool_name")
        or action_request.get("tool_name")
        or direct_tool_call.get("name")
        or nested_tool_call.get("name")
        or "",
    ).strip()
    raw_target = (
        payload.get("tool_target")
        or public_action_state.get("tool_target")
        or ""
    )
    target = _visible_text(raw_target, limit=240) if not isinstance(raw_target, dict) else ""
    if not target:
        tool_call = direct_tool_call or nested_tool_call
        args = _record(tool_call.get("args"))
        for key in ("path", "file_path", "target_path", "query", "pattern", "command", "url"):
            target = _visible_text(args.get(key), limit=240)
            if target:
                break
    return tool_name, target


def _tool_target_from_observation(observation: dict[str, Any]) -> str:
    envelope = _record(observation.get("result_envelope"))
    args = _record(envelope.get("tool_args"))
    for key in ("path", "file_path", "target_path", "query", "pattern", "command", "url"):
        target = _visible_text(args.get(key), limit=240)
        if target:
            return target
    structured = _record(envelope.get("structured_payload"))
    tool_result = _record(structured.get("tool_result"))
    for key in ("path", "file_path", "target_path", "query", "pattern", "command", "url"):
        target = _visible_text(tool_result.get(key), limit=240)
        if target:
            return target
    observed_paths = structured.get("observed_paths")
    if isinstance(observed_paths, list):
        for item in observed_paths:
            target = _visible_text(item, limit=240)
            if target:
                return target
    return ""


def _tool_title(*, step: str, tool_name: str, target: str, state: str) -> str:
    family = _tool_family(tool_name)
    started = state == "running"
    if family == "check":
        action = "正在检查" if started else "检查完成" if state == "done" else "检查失败"
    elif family == "write":
        action = "正在写入" if started else "写入完成" if state == "done" else "写入失败"
    elif family == "read":
        action = "正在读取" if started else "读取完成" if state == "done" else "读取失败"
    elif family == "search":
        action = "正在搜索" if started else "搜索完成" if state == "done" else "搜索失败"
    elif family == "run":
        action = "正在运行" if started else "命令已完成" if state == "done" else "命令失败"
    else:
        action = "正在调用工具" if started else "工具已完成" if state == "done" else "工具失败"
    candidate = f"{action} {target or tool_name}".strip()
    if candidate != action:
        return candidate
    return _visible_text(step, limit=120) or action


def _tool_family(tool_name: str) -> str:
    normalized = str(tool_name or "").strip().lower()
    if normalized in {"path_exists", "stat_path", "list_dir"}:
        return "check"
    if any(item in normalized for item in ("write", "edit", "patch")):
        return "write"
    if "read" in normalized:
        return "read"
    if any(item in normalized for item in ("search", "grep", "glob")):
        return "search"
    if any(item in normalized for item in ("terminal", "shell", "command", "powershell")):
        return "run"
    return "tool"


def _tool_activity_id(*, data: dict[str, Any], event: dict[str, Any], tool_name: str, target: str, fallback: str) -> str:
    scope = _runtime_scope_key(data=data, event=event)
    family = _tool_family(tool_name)
    subject = target or tool_name or fallback
    return _stable_id("tool-activity", scope or family, f"{family}|{subject}")


def _runtime_scope_key(*, data: dict[str, Any], event: dict[str, Any]) -> str:
    active_turn = _record(data.get("active_turn"))
    return str(
        data.get("runtime_task_run_id")
        or data.get("task_run_id")
        or data.get("turn_run_id")
        or active_turn.get("turn_run_id")
        or active_turn.get("turn_id")
        or event.get("run_id")
        or event.get("task_run_id")
        or event.get("turn_id")
        or "",
    ).strip()


def _tool_detail(*, summary: str, agent_brief: str, target: str) -> str:
    for candidate in (summary, agent_brief):
        text = _visible_text(candidate)
        if not text:
            continue
        lowered = text.lower()
        if any(lowered.startswith(prefix) for prefix in _GENERIC_TOOL_WAIT_PREFIXES):
            continue
        if text == target:
            continue
        return text
    return target


def _tool_observation_detail(observation: dict[str, Any], *, target: str) -> str:
    envelope = _record(observation.get("result_envelope"))
    structured = _record(envelope.get("structured_payload"))
    tool_result = _record(structured.get("tool_result"))
    if str(tool_result.get("kind") or "").strip() == "path_exists":
        exists = tool_result.get("exists")
        if exists is True:
            return "目标路径存在"
        if exists is False:
            return "目标路径不存在"
    text = _visible_text(observation.get("text") or envelope.get("text"))
    if text and text != target:
        return text
    return target


def _timeline_state(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"completed", "success", "done"}:
        return "done"
    if normalized in {"failed", "error", "blocked", "aborted", "cancelled", "canceled"}:
        return "error"
    if normalized.startswith("wait"):
        return "running"
    return "running"


def _visible_text(value: Any, *, limit: int = 220) -> str:
    text = public_runtime_progress_summary(value).strip()
    if not text:
        return ""
    text = " ".join(text.split()).strip()
    if text.lower() in _SUPPRESSED_TEXT:
        return ""
    if len(text) > limit:
        return text[: max(1, limit - 1)] + "..."
    return text


def _stable_id(prefix: str, left: str, right: str) -> str:
    digest = sha1(f"{prefix}|{left}|{right}".encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compact(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value not in ("", None, [], {})}
