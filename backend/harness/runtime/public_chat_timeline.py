from __future__ import annotations

from hashlib import sha1
from typing import Any

from harness.runtime.public_execution_state import public_todo_plan_item
from harness.runtime.public_progress import public_runtime_progress_summary


_SUPPRESSED_TEXT = {
    "",
    "completed",
    "done",
    "running",
    "working",
    "ready_to_finish",
    "回答已生成并写回会话",
    "会话输出完成",
    "处理已完成",
    "工具调用已完成，正在根据结果继续。",
    "工具返回成功，正在根据结果继续。",
    "工具返回了结构化结果，正在根据结果继续。",
    "正在思考。",
    "等待模型输出。",
}

_SUPPRESSED_EVENT_TOKENS = {
    "agent_turn_terminal",
    "runtime_invocation_packet_compiled",
    "task_execution_packet_compiled",
    "task_model_action_wait_heartbeat",
    "task_run_executor_scheduled",
    "task_run_executor_claimed",
    "step_summary_recorded",
}


def build_public_chat_timeline(
    *,
    progress_presentation: dict[str, Any] | None,
    public_execution_state: dict[str, Any] | None = None,
    final_answer: str = "",
    artifact_refs: list[Any] | None = None,
    status: str = "",
    terminal_reason: str = "",
    assistant_text: str = "",
) -> list[dict[str, Any]]:
    presentation = dict(progress_presentation or {})
    mission = _record(presentation.get("mission"))
    units = [item for item in presentation.get("work_units") or [] if isinstance(item, dict)]
    execution = _record(public_execution_state)
    observations_by_unit_id = _execution_observations_by_unit(execution)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    opening = _execution_opening_item(execution)
    if opening:
        _append_item(items, seen, opening)
    todo = _execution_todo_item(execution)
    if todo:
        _append_item(items, seen, todo)

    for unit in units:
        feedback = {} if opening else _agent_feedback_item_from_work_unit(unit)
        if feedback:
            _append_item(items, seen, feedback)
        item = _item_from_work_unit(unit)
        if item:
            _append_item(items, seen, item)
        for report in observations_by_unit_id.get(_text(unit.get("unit_id")), []):
            _append_item(items, seen, report)

    for artifact in list(artifact_refs or []):
        item = _item_from_artifact(artifact)
        if item:
            _append_item(items, seen, item)

    blocked = _blocked_item(
        mission=mission,
        status=status,
        terminal_reason=terminal_reason,
        has_error_item=any(item.get("state") == "error" or item.get("kind") == "blocked" for item in items),
    )
    if blocked:
        _append_item(items, seen, blocked)

    closeout = _final_summary_item(
        mission=mission,
        execution=execution,
        final_answer=final_answer,
        assistant_text=assistant_text,
        status=status,
    )
    if closeout:
        _append_item(items, seen, closeout)

    return items


def _execution_opening_item(execution: dict[str, Any]) -> dict[str, Any]:
    opening = _record(execution.get("opening"))
    text = _visible_text(opening.get("text"), limit=220)
    if not text:
        return {}
    refs = _trace_refs(opening)
    return _compact(
        {
            "item_id": _stable_id("opening", refs, text, ""),
            "kind": "opening_judgment",
            "title": "开局判断",
            "text": text,
            "state": _public_state(opening.get("state")),
            "trace_refs": refs,
        }
    )


def _execution_todo_item(execution: dict[str, Any]) -> dict[str, Any]:
    return public_todo_plan_item(_record(execution.get("todo_plan")))


def _execution_observations_by_unit(execution: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for raw in list(execution.get("observations") or []):
        item = _record(raw)
        unit_id = _text(item.get("unit_id"))
        detail = _visible_text(item.get("detail"), limit=220)
        if not unit_id or not detail:
            continue
        refs = _trace_refs(item)
        public_item = _compact(
            {
                "item_id": _text(item.get("item_id")) or _stable_id("observation", refs, unit_id, detail),
                "kind": "observation_report",
                "title": _visible_text(item.get("title"), limit=80) or "观察报告",
                "detail": detail,
                "implication": _visible_text(item.get("implication"), limit=180),
                "state": _public_state(item.get("state")),
                "trace_refs": refs,
            }
        )
        result.setdefault(unit_id, []).append(public_item)
    return result


def _item_from_work_unit(unit: dict[str, Any]) -> dict[str, Any]:
    title = _visible_text(unit.get("title"), limit=80)
    evidence_detail = _visible_text(_first_evidence_summary(unit), limit=180)
    action_detail = _visible_text(unit.get("action"), limit=180)
    detail = (action_detail or evidence_detail) if _is_tool_like(unit) else evidence_detail
    if not title and not detail:
        return {}
    if _looks_internal(title) or _looks_internal(detail):
        return {}

    state = _public_state(unit.get("state"))
    refs = _trace_refs(unit)
    unit_id = _visible_id(unit.get("unit_id")) or _stable_id("unit", refs, title, detail)
    if state == "error":
        return _compact(
            {
                "item_id": unit_id,
                "kind": "blocked",
                "text": detail or title,
                "state": "error",
                "trace_refs": refs,
            }
        )
    return _compact(
        {
            "item_id": unit_id,
            "kind": _public_item_kind(unit),
            "title": title or detail,
            "detail": detail if title and detail != title else "",
            "state": state,
            "trace_refs": refs,
        }
    )


def _item_from_artifact(artifact: Any) -> dict[str, Any]:
    data = _record(artifact)
    path = _visible_text(data.get("path") or data.get("href") or data.get("url"), limit=180)
    title = _visible_text(data.get("title") or data.get("label") or data.get("name") or "产物已生成", limit=80)
    if not title and not path:
        return {}
    return _compact(
        {
            "item_id": _stable_id("artifact", [], title, path),
            "kind": "artifact",
            "title": title or "产物已生成",
            "path": path,
            "href": _visible_text(data.get("href") or data.get("url"), limit=220),
            "state": "ready",
        }
    )


def _agent_feedback_item_from_work_unit(unit: dict[str, Any]) -> dict[str, Any]:
    text = _visible_text(unit.get("agent_feedback"), limit=220)
    if not text or _looks_internal(text):
        return {}
    if text in _SUPPRESSED_TEXT:
        return {}
    refs = _trace_refs(unit)
    return _compact(
        {
            "item_id": _stable_id("agent-feedback", refs, text, _text(unit.get("unit_id"))),
            "kind": "opening_judgment",
            "title": "开局判断",
            "text": text,
            "state": _public_state(unit.get("state")),
            "trace_refs": refs,
        }
    )


def _blocked_item(
    *,
    mission: dict[str, Any],
    status: str,
    terminal_reason: str,
    has_error_item: bool,
) -> dict[str, Any]:
    if has_error_item:
        return {}
    state = _text(mission.get("state") or status).lower()
    failed = state in {"failed", "blocked", "error"} or _terminal_reason_indicates_failure(terminal_reason)
    if not failed:
        return {}
    text = _visible_text(mission.get("current_action") or terminal_reason or mission.get("phase"), limit=220)
    if not text:
        return {}
    return _compact(
        {
            "item_id": _stable_id("blocked", [], text, terminal_reason),
            "kind": "blocked",
            "text": text,
            "state": "error",
        }
    )


def _final_summary_item(
    *,
    mission: dict[str, Any],
    execution: dict[str, Any],
    final_answer: str,
    assistant_text: str,
    status: str,
) -> dict[str, Any]:
    state = _text(mission.get("state") or status).lower()
    if state not in {"completed", "success", "done"}:
        return {}
    execution_final = _record(execution.get("final_summary"))
    text = _visible_text(execution_final.get("text") or final_answer or mission.get("closeout_summary") or mission.get("current_action"), limit=420)
    if not text or _same_public_text(text, assistant_text):
        return {}
    verified = [_visible_text(item, limit=140) for item in list(execution_final.get("verified") or [])]
    artifacts = [_visible_text(item, limit=180) for item in list(execution_final.get("artifacts") or [])]
    return _compact(
        {
            "item_id": _stable_id("final", [], text, ""),
            "kind": "final_summary",
            "text": text,
            "state": "done",
            "verified": [item for item in verified if item][:4],
            "artifacts": [{"label": "产物", "path": item} for item in artifacts if item][:6],
        }
    )


def _append_item(items: list[dict[str, Any]], seen: set[str], item: dict[str, Any]) -> None:
    key = _dedupe_key(item)
    if not key or key in seen:
        return
    seen.add(key)
    items.append(item)


def _dedupe_key(item: dict[str, Any]) -> str:
    item_id = _text(item.get("item_id"))
    if item_id:
        return item_id
    refs = ",".join(_trace_refs(item))
    if refs:
        return f"refs:{refs}"
    return "|".join(_text(item.get(key)) for key in ("kind", "title", "detail", "text", "path"))


def _first_evidence_summary(unit: dict[str, Any]) -> str:
    for evidence in unit.get("evidence") or []:
        if isinstance(evidence, dict):
            summary = _visible_text(evidence.get("summary"), limit=180)
            if summary:
                return summary
    return ""


def _is_tool_like(unit: dict[str, Any]) -> bool:
    kind = _text(unit.get("kind"))
    return kind in {
        "inspect_path",
        "write_file",
        "search_text",
        "terminal",
        "tool_action",
    }


def _public_item_kind(unit: dict[str, Any]) -> str:
    kind = _text(unit.get("kind"))
    if _is_tool_like(unit):
        return "tool_activity"
    if kind == "verification":
        return "verification"
    if kind in {"stage", "task_order", "model_judgment"}:
        return "status_update"
    return "assistant_text"


def _public_state(value: Any) -> str:
    text = _text(value).lower()
    if text in {"completed", "success", "done"}:
        return "done"
    if text in {"failed", "error", "blocked", "aborted", "cancelled"}:
        return "error"
    if text.startswith("wait") or text in {"waiting", "queued", "paused"}:
        return "running"
    return "running"


def _trace_refs(value: dict[str, Any]) -> list[str]:
    refs = value.get("trace_refs") or value.get("technical_trace_refs") or []
    if not isinstance(refs, list):
        return []
    return [_text(item) for item in refs if _text(item)]


def _visible_text(value: Any, *, limit: int = 220) -> str:
    text = public_runtime_progress_summary(value).strip()
    if not text:
        return ""
    text = " ".join(text.split()).strip()
    if text in _SUPPRESSED_TEXT or text.lower() in _SUPPRESSED_TEXT:
        return ""
    if text.lower() in {"true", "false", "null", "none"}:
        return ""
    if _looks_internal(text):
        return ""
    if len(text) > limit:
        return text[: max(1, limit - 1)] + "..."
    return text


def _looks_internal(text: str) -> bool:
    normalized = _text(text)
    if any(token in normalized for token in _SUPPRESSED_EVENT_TOKENS):
        return True
    return normalized.startswith(("rtevt:", "taskrun:", "turnrun:", "task:", "harness.", "runtime."))


def _same_public_text(left: str, right: str) -> bool:
    left_text = _visible_text(left, limit=1000)
    right_text = _visible_text(right, limit=1000)
    if not left_text or not right_text:
        return False
    return left_text == right_text or left_text in right_text or right_text in left_text


def _terminal_reason_indicates_failure(value: Any) -> bool:
    reason = _text(value).lower()
    if not reason or reason in {"completed", "task_executor_scheduled", "waiting_executor"}:
        return False
    return any(marker in reason for marker in ("failed", "error", "blocked", "limit", "exhausted", "repair_required", "user_aborted"))


def _stable_id(prefix: str, refs: list[str], title: str, detail: str) -> str:
    if refs:
        return f"{prefix}:{refs[0]}"
    seed = "|".join([prefix, _text(title), _text(detail)])
    digest = sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _visible_id(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    return text[:160]


def _compact(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value not in ("", None, [], {})}


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()
