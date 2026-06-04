from __future__ import annotations

import json
from hashlib import sha1
from typing import Any

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
    "工具调用已完成，正在根据结果继续。",
    "工具返回成功，正在根据结果继续。",
    "工具返回了结构化结果，正在根据结果继续。",
    "正在思考。",
    "等待模型输出。",
}


def build_public_execution_state(
    *,
    events: list[dict[str, Any]],
    progress_presentation: dict[str, Any] | None = None,
    final_answer: str = "",
    artifact_refs: list[Any] | None = None,
    status: str = "",
    assistant_text: str = "",
) -> dict[str, Any]:
    presentation = dict(progress_presentation or {})
    mission = _record(presentation.get("mission"))
    work_units = [item for item in list(presentation.get("work_units") or []) if isinstance(item, dict)]
    opening = _opening_from_units(work_units)
    todo_plan = _latest_todo_plan(events)
    observations = _observation_reports_from_units(work_units)
    final_summary = _final_summary(
        mission=mission,
        final_answer=final_answer,
        artifact_refs=list(artifact_refs or []),
        status=status,
        assistant_text=assistant_text,
        work_units=work_units,
    )
    return _compact(
        {
            "opening": opening,
            "todo_plan": todo_plan,
            "observations": observations,
            "final_summary": final_summary,
            "authority": "harness.runtime.public_execution_state",
        }
    )


def public_todo_plan_from_event(event: dict[str, Any]) -> dict[str, Any]:
    return _todo_plan_from_event(dict(event or {}))


def public_todo_plan_item(plan: dict[str, Any]) -> dict[str, Any]:
    todo_plan = _record(plan)
    if not todo_plan:
        return {}
    items = [_public_todo_item(item) for item in list(todo_plan.get("items") or []) if isinstance(item, dict)]
    items = [item for item in items if item]
    if not items:
        return {}
    completed = sum(1 for item in items if item.get("status") == "completed")
    active = str(todo_plan.get("active_item_id") or "").strip()
    state = "done" if todo_plan.get("completion_ready") else "running"
    trace_refs = _string_list(todo_plan.get("trace_refs"))
    return _compact(
        {
            "item_id": f"todo-plan:{_stable_digest(todo_plan.get('plan_id'), trace_refs, items)}",
            "kind": "todo_plan",
            "title": "处理清单",
            "detail": f"{completed}/{len(items)} 已完成",
            "state": state,
            "todo_items": items,
            "active_item_id": active,
            "completion_ready": bool(todo_plan.get("completion_ready")),
            "trace_refs": trace_refs,
        }
    )


def _opening_from_units(work_units: list[dict[str, Any]]) -> dict[str, Any]:
    for unit in work_units:
        text = _visible_text(unit.get("agent_feedback") or unit.get("judgment") or unit.get("action"))
        if not text:
            continue
        return _compact(
            {
                "text": text,
                "state": _timeline_state(unit.get("state")),
                "trace_refs": _string_list(unit.get("technical_trace_refs"))[:3],
            }
        )
    return {}


def _observation_reports_from_units(work_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unit in work_units:
        unit_id = str(unit.get("unit_id") or "").strip()
        refs = _string_list(unit.get("technical_trace_refs"))
        implication = _visible_text(unit.get("next_action") or unit.get("judgment"), limit=180)
        for evidence in list(unit.get("evidence") or []):
            item = _record(evidence)
            detail = _visible_text(item.get("summary"), limit=220)
            if not detail:
                continue
            state = "error" if item.get("status") == "error" or str(unit.get("state") or "") == "error" else "done"
            key = "|".join([unit_id, detail, state])
            if key in seen:
                continue
            seen.add(key)
            reports.append(
                _compact(
                    {
                        "item_id": f"observation:{_stable_digest(unit_id, detail, refs)}",
                        "unit_id": unit_id,
                        "title": "观察报告",
                        "detail": detail,
                        "implication": implication if implication and implication != detail else "",
                        "state": state,
                        "trace_refs": refs,
                    }
                )
            )
    return reports


def _final_summary(
    *,
    mission: dict[str, Any],
    final_answer: str,
    artifact_refs: list[Any],
    status: str,
    assistant_text: str,
    work_units: list[dict[str, Any]],
) -> dict[str, Any]:
    state = str(mission.get("state") or status or "").strip().lower()
    if state not in {"completed", "success", "done"}:
        return {}
    text = _visible_text(final_answer or mission.get("closeout_summary") or mission.get("current_action"), limit=520)
    if not text or _same_public_text(text, assistant_text):
        return {}
    verified: list[str] = []
    for unit in work_units:
        if str(unit.get("state") or "").strip() not in {"completed", "done", "success"}:
            continue
        for evidence in list(unit.get("evidence") or []):
            summary = _visible_text(_record(evidence).get("summary"), limit=140)
            if summary and summary not in verified:
                verified.append(summary)
        if len(verified) >= 4:
            break
    artifacts = [_artifact_label(item) for item in artifact_refs]
    artifacts = [item for item in artifacts if item][:6]
    return _compact(
        {
            "text": text,
            "verified": verified[:4],
            "artifacts": artifacts,
        }
    )


def _latest_todo_plan(events: list[dict[str, Any]]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for event in _ordered_events(events):
        plan = _todo_plan_from_event(event)
        if plan:
            latest = plan
    return latest


def _todo_plan_from_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("event_type") or "").strip()
    payload = _record(event.get("payload"))
    candidates: list[Any] = []

    observation = _record(payload.get("observation"))
    if observation:
        source = str(observation.get("source") or "").strip()
        observation_payload = _record(observation.get("payload"))
        tool_name = str(observation_payload.get("tool_name") or "").strip()
        if source in {"system:agent_todo", "tool:agent_todo"} or tool_name == "agent_todo":
            candidates.extend(
                [
                    observation_payload.get("result"),
                    observation_payload.get("text"),
                    observation_payload.get("structured_payload"),
                    observation.get("summary"),
                ]
            )

    tool_observation = _record(payload.get("tool_observation") or _record(payload.get("preview")).get("tool_observation"))
    if tool_observation:
        tool_name = str(tool_observation.get("tool_name") or _record(tool_observation.get("result_envelope")).get("tool_name") or "").strip()
        if tool_name == "agent_todo":
            envelope = _record(tool_observation.get("result_envelope"))
            candidates.extend(
                [
                    tool_observation.get("text"),
                    tool_observation.get("structured_payload"),
                    envelope.get("text"),
                    envelope.get("structured_payload"),
                ]
            )

    if event_type == "agent_todo_initialized":
        candidates.extend([payload, payload.get("result")])

    for candidate in candidates:
        plan = _parse_todo_plan(candidate)
        if plan:
            trace_ref = str(event.get("event_id") or "").strip()
            refs = _string_list(plan.get("trace_refs"))
            return {
                **plan,
                "trace_refs": [*refs, *([trace_ref] if trace_ref and trace_ref not in refs else [])],
            }
    return {}


def _parse_todo_plan(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        parsed = _parse_json(value)
    elif isinstance(value, dict):
        parsed = dict(value)
    else:
        parsed = {}
    if not parsed:
        return {}
    if "result" in parsed and "items" not in parsed:
        nested = _parse_todo_plan(parsed.get("result"))
        if nested:
            return nested
    if "structured_payload" in parsed and "items" not in parsed:
        nested = _parse_todo_plan(parsed.get("structured_payload"))
        if nested:
            return nested
    if "tool_result" in parsed and "items" not in parsed:
        nested = _parse_todo_plan(parsed.get("tool_result"))
        if nested:
            return nested
    items = [_normalize_todo_item(item) for item in list(parsed.get("items") or []) if isinstance(item, dict)]
    items = [item for item in items if item]
    if not items:
        return {}
    active = str(parsed.get("active_item_id") or "").strip()
    if active and not any(item.get("todo_id") == active and item.get("status") == "in_progress" for item in items):
        active = ""
    return _compact(
        {
            "plan_id": str(parsed.get("plan_id") or _stable_digest(items)).strip(),
            "active_item_id": active,
            "completion_ready": bool(parsed.get("completion_ready") or all(item.get("status") == "completed" for item in items)),
            "items": items,
        }
    )


def _normalize_todo_item(item: dict[str, Any]) -> dict[str, Any]:
    content = _visible_text(item.get("content") or item.get("title"), limit=180)
    if not content:
        return {}
    status = str(item.get("status") or "pending").strip()
    if status not in {"pending", "in_progress", "completed", "blocked"}:
        status = "pending"
    return _compact(
        {
            "todo_id": str(item.get("todo_id") or _stable_digest(content)).strip(),
            "content": content,
            "active_form": _visible_text(item.get("active_form") or content, limit=180),
            "status": status,
            "notes": _visible_text(item.get("notes"), limit=180),
            "updated_at": float(item.get("updated_at") or 0.0) or None,
        }
    )


def _public_todo_item(item: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "todo_id": str(item.get("todo_id") or "").strip(),
            "content": _visible_text(item.get("content"), limit=180),
            "active_form": _visible_text(item.get("active_form"), limit=180),
            "status": str(item.get("status") or "pending").strip(),
            "notes": _visible_text(item.get("notes"), limit=180),
        }
    )


def _ordered_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [dict(item or {}) for item in list(events or [])],
        key=lambda item: (float(item.get("created_at") or 0.0), int(item.get("offset") or 0)),
    )


def _parse_json(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _artifact_label(value: Any) -> str:
    if isinstance(value, str):
        return _visible_text(value, limit=180)
    item = _record(value)
    return _visible_text(item.get("path") or item.get("href") or item.get("url") or item.get("label") or item.get("title"), limit=180)


def _visible_text(value: Any, *, limit: int = 220) -> str:
    text = public_runtime_progress_summary(value).strip()
    if not text:
        return ""
    text = " ".join(text.split()).strip()
    if text in _SUPPRESSED_TEXT:
        return ""
    lower = text.lower()
    if lower in _SUPPRESSED_TEXT or lower in {"true", "false", "null", "none"}:
        return ""
    if _looks_like_raw_json(text):
        return ""
    if _looks_internal(text):
        return ""
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "..."


def _looks_like_raw_json(value: str) -> bool:
    text = str(value or "").strip()
    return (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))


def _looks_internal(value: str) -> bool:
    return "step_summary_recorded" in value or "agent_turn_terminal" in value or value.startswith(("rtevt:", "taskrun:", "turnrun:"))


def _timeline_state(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"completed", "done", "success"}:
        return "done"
    if text in {"failed", "error", "blocked"}:
        return "error"
    return "running"


def _same_public_text(left: Any, right: Any) -> bool:
    left_text = _visible_text(left, limit=1000)
    right_text = _visible_text(right, limit=1000)
    if not left_text or not right_text:
        return False
    return left_text == right_text or left_text in right_text or right_text in left_text


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _stable_digest(*values: Any) -> str:
    text = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str)
    return sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
