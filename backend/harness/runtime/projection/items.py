from __future__ import annotations

from typing import Any

from .guards import compact, public_state, public_text, record, stable_id, text


def model_body_item(
    *,
    item_id: str,
    kind: str,
    text_value: Any,
    title: str = "",
    state: str = "done",
    trace_refs: list[str] | None = None,
    implication: Any = "",
) -> dict[str, Any]:
    visible = public_text(text_value, limit=1200 if kind in {"final_answer", "model_body_final"} else 260)
    if not visible:
        return {}
    return compact(
        {
            "item_id": item_id or stable_id(kind, visible, ",".join(trace_refs or [])),
            "kind": kind,
            "slot": "body",
            "surface": "assistant_body",
            "source_authority": "model",
            "title": public_text(title, limit=80),
            "text": visible,
            "detail": "" if kind in {"opening_judgment", "final_answer", "model_body_final"} else visible,
            "implication": public_text(implication, limit=220),
            "state": public_state(state),
            "trace_refs": trace_refs or [],
        }
    )


def opening_judgment_item(*, item_id: str, text_value: Any, state: str = "running", trace_refs: list[str] | None = None) -> dict[str, Any]:
    return model_body_item(
        item_id=item_id,
        kind="opening_judgment",
        title="开局判断",
        text_value=text_value,
        state=state,
        trace_refs=trace_refs,
    )


def observation_report_item(
    *,
    item_id: str,
    detail: Any,
    implication: Any = "",
    state: str = "done",
    trace_refs: list[str] | None = None,
) -> dict[str, Any]:
    return model_body_item(
        item_id=item_id,
        kind="observation_report",
        title="处理反馈",
        text_value=detail,
        implication=implication,
        state=state,
        trace_refs=trace_refs,
    )


def stage_summary_item(
    *,
    item_id: str,
    summary: Any,
    next_step: Any = "",
    state: str = "done",
    trace_refs: list[str] | None = None,
    covers_tool_refs: list[str] | None = None,
) -> dict[str, Any]:
    item = model_body_item(
        item_id=item_id,
        kind="stage_summary",
        title="阶段总结",
        text_value=summary,
        implication=next_step,
        state=state,
        trace_refs=trace_refs,
    )
    if item and covers_tool_refs:
        item["covers_tool_refs"] = [text(ref) for ref in covers_tool_refs if text(ref)]
        item["collapse_after_body_feedback"] = True
    return item


def work_action_item(
    *,
    item_id: str,
    tool_name: str = "",
    raw_target: Any = "",
    summary: Any = "",
    observation: Any = "",
    state: str = "running",
    trace_refs: list[str] | None = None,
    recovery_hint: Any = "",
) -> dict[str, Any]:
    action_kind = action_kind_for_tool(tool_name, raw_target)
    normalized_state = public_state(state)
    subject = subject_label(tool_name=tool_name, raw_target=raw_target, action_kind=action_kind)
    title = action_title(action_kind=action_kind, state=normalized_state)
    summary_text = public_text(summary, limit=220) or (f"{title}：{subject}" if subject else title)
    observation_text = observation_text_for_tool(
        tool_name=tool_name,
        action_kind=action_kind,
        state=normalized_state,
        subject_label=subject,
        value=observation,
    )
    if not subject and not summary_text and not observation_text:
        return {}
    return compact(
        {
            "item_id": item_id or stable_id("tool", tool_name, subject, ",".join(trace_refs or [])),
            "kind": "work_action",
            "slot": "tool",
            "surface": "tool_window",
            "source_authority": "tool",
            "tool_name": text(tool_name),
            "action_kind": action_kind,
            "title": title,
            "subject_label": subject,
            "public_summary": summary_text,
            "observation": observation_text,
            "recovery_hint": public_text(recovery_hint, limit=180),
            "state": normalized_state,
            "stream_state": "streaming" if normalized_state == "running" else "done",
            "trace_refs": trace_refs or [],
        }
    )


def control_item(
    *,
    item_id: str,
    kind: str,
    title: Any,
    detail: Any = "",
    state: str = "running",
    trace_refs: list[str] | None = None,
) -> dict[str, Any]:
    visible_title = public_text(title, limit=120)
    visible_detail = public_text(detail, limit=220)
    if not visible_title and not visible_detail:
        return {}
    return compact(
        {
            "item_id": item_id or stable_id("control", kind, visible_title, visible_detail),
            "kind": kind or "control_state",
            "slot": "control",
            "surface": "control",
            "source_authority": "runtime",
            "title": visible_title or "运行状态",
            "detail": visible_detail,
            "state": public_state(state),
            "trace_refs": trace_refs or [],
        }
    )


def status_item(
    *,
    item_id: str,
    title: Any,
    detail: Any = "",
    state: str = "running",
    trace_refs: list[str] | None = None,
) -> dict[str, Any]:
    visible_title = public_text(title, limit=120)
    visible_detail = public_text(detail, limit=220)
    if not visible_title and not visible_detail:
        return {}
    return compact(
        {
            "item_id": item_id or stable_id("status", visible_title, visible_detail),
            "kind": "status_update",
            "slot": "status",
            "surface": "timeline",
            "source_authority": "runtime",
            "title": visible_title,
            "detail": visible_detail,
            "state": public_state(state),
            "trace_refs": trace_refs or [],
        }
    )


def todo_plan_item(plan: dict[str, Any]) -> dict[str, Any]:
    todo_plan = record(plan)
    items = [_todo_item(item) for item in list(todo_plan.get("items") or []) if isinstance(item, dict)]
    items = [item for item in items if item]
    if not items:
        return {}
    completed = sum(1 for item in items if item.get("status") == "completed")
    refs = _trace_refs(todo_plan)
    return compact(
        {
            "item_id": stable_id("todo-plan", ",".join(refs), text(todo_plan.get("plan_id")), str(items)),
            "kind": "todo_plan",
            "slot": "timeline",
            "surface": "timeline",
            "source_authority": "runtime",
            "title": "处理清单",
            "detail": f"{completed}/{len(items)} 已完成",
            "state": "done" if todo_plan.get("completion_ready") else "running",
            "todo_items": items,
            "active_item_id": text(todo_plan.get("active_item_id")),
            "completion_ready": bool(todo_plan.get("completion_ready")),
            "trace_refs": refs,
        }
    )


def action_kind_for_tool(tool_name: str, raw_target: Any = "") -> str:
    normalized = text(tool_name).lower()
    target = text(raw_target).lower()
    if normalized == "memory_search":
        return "memory"
    if normalized in {"path_exists", "stat_path", "list_dir"}:
        return "inspect"
    if normalized in {"read_file", "read_path"} or "read" in normalized:
        return "read"
    if normalized in {"search_text", "search_files", "glob_paths"} or any(token in normalized for token in ("search", "grep", "glob")):
        return "search"
    if normalized in {"write_file", "edit_file", "apply_patch"} or any(token in normalized for token in ("write", "edit", "patch")):
        return "edit"
    if any(token in normalized for token in ("terminal", "shell", "command", "powershell")):
        return "verify" if any(token in target for token in ("test", "pytest", "npm", "vitest", "pnpm")) else "run"
    if "agent" in normalized:
        return "subagent"
    return "work"


def subject_label(*, tool_name: str, raw_target: Any, action_kind: str) -> str:
    structured = record(raw_target)
    if structured:
        for key in ("path", "file_path", "relative_path", "target_path", "query", "pattern", "command", "url"):
            value = public_text(structured.get(key), limit=160)
            if value:
                return value
    raw = public_text(raw_target, limit=160)
    if raw:
        return raw
    if action_kind == "memory":
        return "相关记忆"
    if action_kind == "verify":
        return "验证结果"
    if action_kind == "subagent":
        return "子任务"
    return text(tool_name)


def action_title(*, action_kind: str, state: str) -> str:
    labels = {
        "inspect": ("正在确认目标", "已确认目标", "确认目标未完成"),
        "read": ("正在读取上下文", "已读取上下文", "读取上下文未完成"),
        "search": ("正在搜索引用", "已搜索引用", "搜索未完成"),
        "edit": ("正在更新文件", "已更新文件", "更新未完成"),
        "run": ("正在运行命令", "命令已返回", "命令未完成"),
        "verify": ("正在运行验证", "验证已返回", "验证未完成"),
        "memory": ("正在检索相关记忆", "记忆检索已返回", "记忆检索未完成"),
        "subagent": ("正在等待子任务", "子任务已返回", "子任务未完成"),
        "work": ("正在调用工具", "工具结果已返回", "步骤未完成"),
    }
    running, done, failed = labels.get(action_kind, labels["work"])
    if state == "done":
        return done
    if state == "error":
        return failed
    if state == "waiting":
        return running
    return running


def observation_text_for_tool(*, tool_name: str, action_kind: str, state: str, subject_label: str, value: Any) -> str:
    structured = record(value)
    if not structured and isinstance(value, str):
        try:
            import json

            parsed = json.loads(value)
            structured = record(parsed)
        except Exception:
            structured = {}
    if text(tool_name).lower() == "path_exists":
        flag = _bool_from_any(structured.get("exists") if structured else value)
        if flag is True:
            return "目标路径存在"
        if flag is False:
            return "目标路径不存在"
    visible = public_text(value, limit=220)
    if visible:
        return visible
    if state == "done" and subject_label:
        return f"已返回：{subject_label}"
    if state == "error":
        return "工具返回失败，需要根据结果调整。"
    return ""


def _todo_item(item: dict[str, Any]) -> dict[str, Any]:
    content = public_text(item.get("content"), limit=180)
    return compact(
        {
            "todo_id": text(item.get("todo_id")),
            "content": content,
            "active_form": public_text(item.get("active_form"), limit=180) or content,
            "status": text(item.get("status") or "pending"),
            "notes": public_text(item.get("notes"), limit=180),
        }
    )


def _trace_refs(value: dict[str, Any]) -> list[str]:
    refs = value.get("trace_refs") or value.get("technical_trace_refs") or []
    return [text(item) for item in refs if text(item)] if isinstance(refs, list) else []


def _bool_from_any(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return None
