from __future__ import annotations

import re
from typing import Any

from .authority import build_public_projection_frame
from .guards import compact, public_text, record, stable_id, text
from .items import action_kind_for_tool
from harness.runtime.runtime_private_text import looks_like_runtime_private_artifact_text
from runtime.output_stream.public_contract import (
    ASSISTANT_BODY_EVENT_FAMILY,
    ASSISTANT_STREAM_REPAIR_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
    BODY_PUBLIC_CHANNEL,
    CHAT_TURN_BOUND_EVENT,
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_CHECKED_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
    STATUS_PUBLIC_CHANNEL,
    STATUS_TRACE_EVENT_FAMILY,
    TASK_BRIDGE_STARTED_EVENT,
    TASK_BRIDGE_TERMINAL_EVENT,
    TOOL_CALL_REQUESTED_EVENT,
    TOOL_ITEM_COMPLETED_EVENT,
    TOOL_ITEM_STARTED_EVENT,
    TOOL_PERMISSION_DECIDED_EVENT,
    TURN_COMPLETED_EVENT,
)


_TRACE_ONLY_TOOL_NAMES = {"read_persisted_tool_result"}
_TRACE_ONLY_RUNTIME_STEP_SOURCES = {
    "model_action.assistant_content_preamble",
    "runtime.protocol_repair",
    "system.tool_call_status",
    "tool_observation.summary",
}
_TOOL_FAILURE_FEEDBACK_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9 _./-]{0,80}\s+failed|tool_policy_rejection):",
    flags=re.IGNORECASE,
)
_LINE_NUMBERED_TOOL_OUTPUT_RE = re.compile(r"(?m)^\s*\d{1,6}\s*\|")


class ProjectionLifecycleState:
    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}

    def should_emit_public_event(self, public_event_type: str, data: dict[str, Any]) -> bool:
        return True

    def spec_for_event(self, public_event_type: str, data: dict[str, Any], *, sequence: int = 0) -> dict[str, Any]:
        event_type = text(public_event_type)
        offset = _event_offset(sequence=sequence)
        if event_type in {
            TOOL_CALL_REQUESTED_EVENT,
            TOOL_PERMISSION_DECIDED_EVENT,
            TOOL_ITEM_STARTED_EVENT,
            TOOL_ITEM_COMPLETED_EVENT,
        } and _is_agent_todo_tool(data.get("tool_name")):
            if event_type == TOOL_ITEM_COMPLETED_EVENT:
                return _agent_todo_completed_status_spec(data)
            return _agent_todo_hidden_trace_spec(data, state="running")
        if event_type == TOOL_CALL_REQUESTED_EVENT:
            spec = _tool_call_requested_spec(data)
            tool_call_id = text(spec.get("tool_call_id"))
            if not tool_call_id:
                return _protocol_diagnostic_spec(
                    data,
                    code="tool_call_requested_without_tool_call_id",
                    detail="tool_call_requested 缺少 tool_call_id，不能进入公开工具生命周期。",
                )
            tool_key = _tool_lifecycle_key(data, tool_call_id=tool_call_id)
            self._tools[tool_key] = {
                **dict(self._tools.get(tool_key) or {}),
                "tool_call_id": tool_call_id,
                "scope": _tool_lifecycle_scope(data),
                "requested_offset": offset,
                "item_id": text(spec.get("item_id")) or tool_call_id,
            }
            return spec
        if event_type == TOOL_PERMISSION_DECIDED_EVENT:
            tool_call_id = text(data.get("tool_call_id"))
            record = self._tool_record(data, tool_call_id=tool_call_id)
            if not tool_call_id or not record:
                return _protocol_diagnostic_spec(
                    data,
                    code="tool_permission_without_model_request",
                    detail="tool_permission_decided 没有绑定已存在的 ToolCallRequest，不能进入公开工具生命周期。",
                )
            if offset <= int(record.get("requested_offset") or -1):
                return _protocol_diagnostic_spec(
                    data,
                    code="tool_permission_before_model_request",
                    detail="tool_permission_decided 的 event_offset 不晚于 tool_call_requested，不能进入公开工具生命周期。",
                )
            spec = _tool_permission_decided_spec(data)
            decision = text(data.get("permission_decision") or data.get("decision")).lower()
            if decision in {"allow", "allowed", "auto_allow"}:
                record.update(
                    {
                        "permission_offset": offset,
                        "permission_decision_id": text(data.get("permission_decision_id")) or text(spec.get("permission_decision_id")),
                        "permission_allowed": True,
                    }
                )
            return spec
        if event_type == TOOL_ITEM_STARTED_EVENT:
            tool_call_id = text(data.get("tool_call_id"))
            record = self._tool_record(data, tool_call_id=tool_call_id)
            if (
                not tool_call_id
                or not record
                or record.get("permission_allowed") is not True
            ):
                return _protocol_diagnostic_spec(
                    data,
                    code="tool_started_without_allowed_permission",
                    detail="tool_item_started 没有绑定已允许的 PermissionDecision，不能进入公开工具生命周期。",
                )
            permission_offset = int(record.get("permission_offset") or -1)
            if offset <= permission_offset:
                return _protocol_diagnostic_spec(
                    data,
                    code="tool_started_before_permission",
                    detail="tool_item_started 的 event_offset 不晚于 tool_permission_decided，不能进入公开工具生命周期。",
                )
            started_data = {
                **data,
                "permission_decision_id": text(record.get("permission_decision_id")) or text(data.get("permission_decision_id")),
            }
            spec = _tool_started_spec(started_data)
            record.update(
                {
                    "started_offset": offset,
                    "started": True,
                    "tool_lifecycle_id": text(data.get("tool_lifecycle_id")),
                }
            )
            return spec
        if event_type == TOOL_ITEM_COMPLETED_EVENT:
            tool_call_id = text(data.get("tool_call_id"))
            record = self._tool_record(data, tool_call_id=tool_call_id)
            if (
                not tool_call_id
                or not record
                or record.get("started") is not True
            ):
                return _protocol_diagnostic_spec(
                    data,
                    code="tool_completed_without_started_lifecycle",
                    detail="tool_item_completed 没有绑定已开始的 ToolExecution，不能进入公开工具生命周期。",
                )
            started_offset = int(record.get("started_offset") or -1)
            if offset <= started_offset:
                return _protocol_diagnostic_spec(
                    data,
                    code="tool_completed_before_started",
                    detail="tool_item_completed 的 event_offset 不晚于 tool_item_started，不能进入公开工具生命周期。",
                )
            completed_data = {
                **data,
                "permission_decision_id": text(record.get("permission_decision_id")) or text(data.get("permission_decision_id")),
            }
            spec = _tool_completed_spec(completed_data)
            record.update({"completed_offset": offset, "completed": True})
            return spec
        return projection_spec_for_event(public_event_type, data)

    def _tool_record(self, data: dict[str, Any], *, tool_call_id: str) -> dict[str, Any] | None:
        if not tool_call_id:
            return None
        exact = self._tools.get(_tool_lifecycle_key(data, tool_call_id=tool_call_id))
        if exact:
            return exact
        matches = [
            record
            for record in self._tools.values()
            if text(record.get("tool_call_id")) == tool_call_id
        ]
        return matches[0] if len(matches) == 1 else None


def project_public_projection_event(
    public_event_type: str,
    data: dict[str, Any],
    *,
    session_id: str = "",
    sequence: int = 0,
    public_anchor: dict[str, Any] | None = None,
    lifecycle_state: ProjectionLifecycleState | None = None,
) -> dict[str, Any]:
    payload = dict(data or {})
    payload.setdefault("sequence", int(sequence or payload.get("sequence") or 0))
    if public_anchor:
        payload["public_anchor"] = dict(public_anchor)
    spec = (
        lifecycle_state.spec_for_event(public_event_type, payload, sequence=sequence)
        if lifecycle_state is not None
        else projection_spec_for_event(public_event_type, payload)
    )
    frame = build_public_projection_frame(
        public_event_type,
        payload,
        session_id=session_id,
        sequence=sequence,
        spec=spec,
        public_anchor=public_anchor,
    )
    return {"public_projection_frame": frame}


def attach_public_projection_event(
    public_event_type: str,
    data: dict[str, Any],
    *,
    session_id: str = "",
    sequence: int = 0,
    public_anchor: dict[str, Any] | None = None,
    lifecycle_state: ProjectionLifecycleState | None = None,
) -> None:
    projection = project_public_projection_event(
        public_event_type,
        data,
        session_id=session_id,
        sequence=sequence,
        public_anchor=public_anchor,
        lifecycle_state=lifecycle_state,
    )
    data["public_projection_frame"] = projection["public_projection_frame"]
    data.pop("public_projection_envelope", None)
    data.pop("public_timeline_delta", None)
    data.pop("task_projection", None)
    data.pop("task_projection_delta", None)


def projection_spec_for_event(public_event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    event_type = text(public_event_type)
    if event_type in {
        TOOL_CALL_REQUESTED_EVENT,
        TOOL_PERMISSION_DECIDED_EVENT,
        TOOL_ITEM_STARTED_EVENT,
        TOOL_ITEM_COMPLETED_EVENT,
    } and _is_agent_todo_tool(data.get("tool_name")):
        if event_type == TOOL_ITEM_COMPLETED_EVENT:
            return _agent_todo_completed_status_spec(data)
        return _agent_todo_hidden_trace_spec(data, state="running")
    if event_type == ASSISTANT_TEXT_DELTA_EVENT:
        return _assistant_body_spec(data, op="body_append", state="running", retention="transient")
    if event_type == ASSISTANT_TEXT_FINAL_EVENT:
        return _assistant_body_spec(data, op="body_finalize", state="done", retention="final")
    if event_type == ASSISTANT_STREAM_REPAIR_EVENT:
        return _assistant_repair_spec(data)
    if event_type == TOOL_CALL_REQUESTED_EVENT:
        return _tool_call_requested_spec(data)
    if event_type == TOOL_PERMISSION_DECIDED_EVENT:
        return _tool_permission_decided_spec(data)
    if event_type == TOOL_ITEM_STARTED_EVENT:
        return _tool_started_spec(data)
    if event_type == TOOL_ITEM_COMPLETED_EVENT:
        return _tool_completed_spec(data)
    if event_type == "tool_batch_group_started":
        return _tool_batch_group_started_spec(data)
    if event_type in {
        SESSION_OUTPUT_COMMIT_CHECKED_EVENT,
        SESSION_OUTPUT_COMMIT_ACK_EVENT,
        SESSION_OUTPUT_COMMIT_FAILED_EVENT,
        SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
    }:
        return _commit_spec(event_type, data)
    if event_type == TURN_COMPLETED_EVENT:
        return _turn_terminal_spec(data)
    if event_type in {CHAT_TURN_BOUND_EVENT, TASK_BRIDGE_STARTED_EVENT, TASK_BRIDGE_TERMINAL_EVENT}:
        return _hidden_trace_spec(event_type, data)
    if event_type == "runtime_status":
        return _hidden_trace_spec(event_type, data)
    if event_type == "agent_contract_feedback_required":
        return _hidden_trace_spec(event_type, data)
    if event_type == "runtime_step_summary":
        return _runtime_step_summary_spec(data)
    if event_type == "active_task_steer_accepted":
        return _active_task_steer_status_spec(data)
    if event_type in {"error", "stopped"}:
        return _stream_terminal_status_spec(event_type, data)
    return _hidden_trace_spec(event_type, data)


def _assistant_body_spec(data: dict[str, Any], *, op: str, state: str, retention: str) -> dict[str, Any]:
    content = str(data.get("content") or "")
    return {
        "op": op,
        "slot": "body",
        "source_authority": "model",
        "main_visibility": "visible_live" if op == "body_append" else "visible_final",
        "retention": retention,
        "item_id": _body_item_id(data),
        "text": content,
        "state": state,
        "trace_refs": _trace_refs(data),
    }


def _assistant_repair_spec(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "op": "body_finalize",
        "slot": "body",
        "source_authority": "model",
        "main_visibility": "visible_live",
        "retention": "transient",
        "item_id": _body_item_id(data),
        "text": str(data.get("replacement_content") or ""),
        "state": "running",
        "trace_refs": _trace_refs(data),
    }


def _is_trace_only_tool(tool_name: str) -> bool:
    return text(tool_name).lower() in _TRACE_ONLY_TOOL_NAMES


def _is_agent_todo_tool(tool_name: Any) -> bool:
    return text(tool_name).lower() == "agent_todo"


def _trace_only_tool_request_spec(
    data: dict[str, Any],
    *,
    tool_name: str,
    tool_call_id: str,
    action_kind: str,
) -> dict[str, Any]:
    return {
        "op": "item_upsert",
        "slot": "trace",
        "source_authority": "model",
        "main_visibility": "trace_only",
        "retention": "trace",
        "item_id": tool_call_id,
        "source_item_id": text(data.get("request_id")) or tool_call_id,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "tool_lifecycle_id": text(data.get("tool_lifecycle_id")) or tool_call_id,
        "action_kind": action_kind,
        "title": _trace_only_tool_title(tool_name, failed=False),
        "text": _trace_only_tool_title(tool_name, failed=False),
        "state": "running",
        "trace_refs": _trace_refs(data),
    }


def _trace_only_tool_completed_spec(
    data: dict[str, Any],
    *,
    tool_name: str,
    tool_call_id: str,
    permission_decision_id: str,
    failed: bool,
) -> dict[str, Any]:
    tool_lifecycle_id = text(data.get("tool_lifecycle_id")) or tool_call_id
    if failed:
        return {
            "op": "item_retire",
            "slot": "trace",
            "source_authority": "tool",
            "main_visibility": "hidden",
            "retention": "trace",
            "item_id": tool_call_id,
            "tool_call_id": tool_call_id,
            "permission_decision_id": permission_decision_id,
            "tool_name": tool_name,
            "tool_lifecycle_id": tool_lifecycle_id,
            "state": "failed",
            "trace_refs": _trace_refs(data),
            "collapsed": True,
        }
    return {
        "op": "item_retire",
        "slot": "trace",
        "source_authority": "tool",
        "main_visibility": "trace_only",
        "retention": "trace",
        "item_id": tool_call_id,
        "tool_call_id": tool_call_id,
        "permission_decision_id": permission_decision_id,
        "tool_name": tool_name,
        "tool_lifecycle_id": tool_lifecycle_id,
        "title": _trace_only_tool_title(tool_name, failed=False),
        "text": _trace_only_tool_title(tool_name, failed=False),
        "state": "done",
        "trace_refs": _trace_refs(data),
        "collapsed": True,
    }


def _trace_only_tool_title(tool_name: str, *, failed: bool) -> str:
    if text(tool_name).lower() == "read_persisted_tool_result":
        return "上下文缓存补读失败" if failed else "补读上下文缓存"
    return "内部工具执行失败" if failed else "内部工具执行"


def _agent_todo_hidden_trace_spec(data: dict[str, Any], *, state: str) -> dict[str, Any]:
    return {
        "op": "item_upsert",
        "slot": "trace",
        "source_authority": "runtime",
        "main_visibility": "hidden",
        "retention": "trace",
        "event_family": STATUS_TRACE_EVENT_FAMILY,
        "channel": STATUS_PUBLIC_CHANNEL,
        "lossless": False,
        "item_id": stable_id(
            "agent-todo-trace",
            data.get("runtime_event_id"),
            data.get("source_task_event_id"),
            data.get("tool_call_id"),
            state,
        ),
        "state": text(state) or "running",
        "status_kind": "todo_plan_trace",
        "trace_refs": _trace_refs(data),
    }


def _agent_todo_completed_status_spec(data: dict[str, Any], *, detail: str = "", failed: bool | None = None) -> dict[str, Any]:
    anchor = record(data.get("public_anchor"))
    task_run_id = text(data.get("task_run_id")) or text(anchor.get("task_run_id")) or text(data.get("runtime_task_run_id"))
    raw_state = text(data.get("state")).lower()
    resolved_failed = raw_state in {"error", "failed", "blocked"} if failed is None else bool(failed)
    todo_plan = _agent_todo_plan_projection(data.get("todo_plan"))
    if todo_plan and not resolved_failed:
        return {
            "op": "item_upsert",
            "slot": "status",
            "source_authority": "runtime",
            "main_visibility": "visible_live",
            "retention": "transient",
            "event_family": STATUS_TRACE_EVENT_FAMILY,
            "channel": STATUS_PUBLIC_CHANNEL,
            "lossless": False,
            "item_id": stable_id("agent-todo-plan", task_run_id, todo_plan.get("plan_id") or "current"),
            "title": "任务清单",
            "text": "任务清单",
            "detail": _agent_todo_plan_detail(todo_plan),
            "state": "done",
            "status_kind": "todo_plan",
            "plan_id": text(todo_plan.get("plan_id")),
            "active_item_id": text(todo_plan.get("active_item_id")),
            "completion_ready": todo_plan.get("completion_ready") if isinstance(todo_plan.get("completion_ready"), bool) else None,
            "todo_items": list(todo_plan.get("items") or []),
            "trace_refs": _trace_refs(data),
        }
    visible_detail = public_text(detail or data.get("error") or data.get("observation"), limit=360)
    if not visible_detail and not resolved_failed:
        return _agent_todo_hidden_trace_spec(data, state="done")
    return _agent_todo_hidden_trace_spec(data, state="failed" if resolved_failed else "done")


def _agent_todo_plan_projection(value: Any) -> dict[str, Any]:
    source = record(value)
    if not source:
        return {}
    items: list[dict[str, Any]] = []
    for item in list(source.get("items") or [])[:40]:
        if not isinstance(item, dict):
            continue
        todo_id = text(item.get("todo_id"))
        content = public_text(item.get("content") or item.get("title"), limit=180)
        if not todo_id or not content:
            continue
        items.append(
            compact(
                {
                    "todo_id": todo_id,
                    "content": content,
                    "active_form": public_text(item.get("active_form"), limit=120),
                    "status": text(item.get("status")),
                    "notes": public_text(item.get("notes"), limit=180),
                }
            )
        )
    if not items:
        return {}
    return compact(
        {
            "plan_id": text(source.get("plan_id")),
            "active_item_id": text(source.get("active_item_id")),
            "completion_ready": source.get("completion_ready") if isinstance(source.get("completion_ready"), bool) else None,
            "items": items,
            "authority": text(source.get("authority")) or "agent.todo_plan",
        }
    )


def _agent_todo_plan_detail(plan: dict[str, Any]) -> str:
    items = [dict(item) for item in list(plan.get("items") or []) if isinstance(item, dict)]
    total = len(items)
    completed = sum(1 for item in items if text(item.get("status")).lower() == "completed")
    active_id = text(plan.get("active_item_id"))
    active = next((item for item in items if text(item.get("todo_id")) == active_id), {})
    active_text = public_text(active.get("active_form") or active.get("content"), limit=120) if active else ""
    if active_text:
        return f"{completed}/{total} 已完成，正在：{active_text}。"
    return f"{completed}/{total} 已完成。"


def _tool_call_requested_spec(data: dict[str, Any]) -> dict[str, Any]:
    tool_name = text(data.get("tool_name")) or "tool"
    tool_call_id = text(data.get("tool_call_id"))
    action_kind = action_kind_for_tool(tool_name, data.get("target") or data.get("arguments_preview"))
    if _is_agent_todo_tool(tool_name):
        return _agent_todo_hidden_trace_spec(data, state="running")
    if _is_trace_only_tool(tool_name):
        return _trace_only_tool_request_spec(
            data,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            action_kind=action_kind,
        )
    subject = public_text(data.get("target") or data.get("arguments_preview"), limit=180)
    title = _tool_request_text(data, tool_name=tool_name, subject=subject)
    return {
        "op": "item_upsert",
        "slot": "current_action",
        "source_authority": "model",
        "main_visibility": "visible_live",
        "retention": "transient",
        "item_id": tool_call_id,
        "source_item_id": text(data.get("request_id")) or tool_call_id,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "tool_lifecycle_id": text(data.get("tool_lifecycle_id")) or tool_call_id,
        "action_kind": action_kind,
        "title": title,
        "text": title,
        "detail": subject,
        "subject_label": subject,
        "arguments_preview": text(data.get("arguments_preview")),
        "target": text(data.get("target")),
        "state": "running",
        "trace_refs": _trace_refs(data),
    }


def _tool_permission_decided_spec(data: dict[str, Any]) -> dict[str, Any]:
    decision = text(data.get("permission_decision") or data.get("decision")).lower()
    tool_call_id = text(data.get("tool_call_id"))
    permission_decision_id = text(data.get("permission_decision_id"))
    if decision in {"allow", "allowed", "auto_allow"}:
        slot = "trace"
        main_visibility = "trace_only"
        retention = "trace"
        state = "done"
        pin_reason = ""
    elif decision in {"ask_approval", "needs_approval", "approval_required"}:
        slot = "pinned"
        main_visibility = "pinned"
        retention = "pinned_until_resolved"
        state = "waiting"
        pin_reason = "waiting_approval"
    else:
        slot = "pinned"
        main_visibility = "pinned"
        retention = "pinned_until_resolved"
        state = "blocked"
        pin_reason = "permission"
    detail = public_text(data.get("permission_reason") or data.get("system_reason"), limit=260)
    title = "工具权限已确认" if state == "done" else ("等待工具权限确认" if state == "waiting" else "工具请求未获准")
    return {
        "op": "item_upsert",
        "slot": slot,
        "source_authority": "runtime",
        "main_visibility": main_visibility,
        "retention": retention,
        "pin_reason": pin_reason,
        "item_id": permission_decision_id or stable_id("permission", tool_call_id, decision),
        "tool_call_id": tool_call_id,
        "permission_decision_id": permission_decision_id,
        "title": title,
        "text": title,
        "detail": detail,
        "state": state,
        "trace_refs": _trace_refs(data),
    }


def _tool_started_spec(data: dict[str, Any]) -> dict[str, Any]:
    tool_call_id = text(data.get("tool_call_id"))
    permission_decision_id = text(data.get("permission_decision_id"))
    tool_name = text(data.get("tool_name")) or "tool"
    if _is_agent_todo_tool(tool_name):
        return _agent_todo_hidden_trace_spec(data, state="running")
    if not tool_call_id or not permission_decision_id:
        return _protocol_diagnostic_spec(
            data,
            code="tool_started_without_request_or_permission",
            detail="tool_item_started 缺少 tool_call_id 或 permission_decision_id，不能进入主视图。",
        )
    return {
        "op": "item_upsert",
        "slot": "trace",
        "source_authority": "tool",
        "main_visibility": "trace_only",
        "retention": "trace",
        "item_id": tool_call_id,
        "tool_call_id": tool_call_id,
        "permission_decision_id": permission_decision_id,
        "tool_name": tool_name,
        "tool_lifecycle_id": text(data.get("tool_lifecycle_id")) or tool_call_id,
        "state": "running",
        "trace_refs": _trace_refs(data),
    }


def _tool_completed_spec(data: dict[str, Any]) -> dict[str, Any]:
    tool_call_id = text(data.get("tool_call_id"))
    permission_decision_id = text(data.get("permission_decision_id"))
    tool_name = text(data.get("tool_name")) or "tool"
    raw_state = text(data.get("state")).lower()
    failed = raw_state in {"error", "failed", "blocked"}
    detail = _tool_completion_detail(data.get("error") or data.get("observation"), limit=360)
    if _is_agent_todo_tool(tool_name):
        return _agent_todo_completed_status_spec(data, detail=detail, failed=failed)
    if not tool_call_id or not permission_decision_id:
        return _protocol_diagnostic_spec(
            data,
            code="tool_completed_without_request_or_permission",
            detail="tool_item_completed 缺少 tool_call_id 或 permission_decision_id，不能进入主视图。",
        )
    title = _tool_completed_text(data, tool_name=tool_name, failed=failed)
    if _is_trace_only_tool(tool_name):
        return _trace_only_tool_completed_spec(
            data,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            permission_decision_id=permission_decision_id,
            failed=failed,
        )
    if failed:
        return {
            "op": "item_upsert",
            "slot": "pinned",
            "source_authority": "tool",
            "main_visibility": "pinned",
            "retention": "pinned_until_resolved",
            "pin_reason": "failed",
            "item_id": tool_call_id,
            "tool_call_id": tool_call_id,
            "permission_decision_id": permission_decision_id,
            "tool_name": tool_name,
            "tool_lifecycle_id": text(data.get("tool_lifecycle_id")) or tool_call_id,
            "title": title,
            "text": title,
            "detail": detail,
            "state": "failed",
            "trace_refs": _trace_refs(data),
        }
    return {
        "op": "item_retire",
        "slot": "trace",
        "source_authority": "tool",
        "main_visibility": "trace_only",
        "retention": "trace",
        "item_id": tool_call_id,
        "tool_call_id": tool_call_id,
        "permission_decision_id": permission_decision_id,
        "tool_name": tool_name,
        "tool_lifecycle_id": text(data.get("tool_lifecycle_id")) or tool_call_id,
        "detail": detail,
        "state": "done",
        "trace_refs": _trace_refs(data),
        "collapsed": True,
    }


def _tool_batch_group_started_spec(data: dict[str, Any]) -> dict[str, Any]:
    group = record(data.get("tool_batch_group"))
    item_indexes = list(group.get("item_indexes") or [])
    count = len(item_indexes)
    execution_class = text(group.get("execution_class"))
    title = f"正在执行 {count} 个工具" if count > 1 else "正在执行工具"
    detail_parts = []
    if execution_class:
        detail_parts.append(execution_class)
    if count > 0:
        detail_parts.append(f"items={count}")
    return {
        "op": "item_upsert",
        "slot": "trace",
        "source_authority": "runtime",
        "main_visibility": "hidden",
        "retention": "trace",
        "item_id": text(data.get("tool_batch_ref")) or stable_id("tool-batch", data.get("runtime_event_id"), data.get("event_id")),
        "title": title,
        "text": title,
        "detail": " / ".join(detail_parts),
        "state": "running",
        "trace_refs": _trace_refs(data),
    }


def _commit_spec(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    state_by_event = {
        SESSION_OUTPUT_COMMIT_CHECKED_EVENT: "checked",
        SESSION_OUTPUT_COMMIT_ACK_EVENT: "committed",
        SESSION_OUTPUT_COMMIT_FAILED_EVENT: "failed",
        SESSION_OUTPUT_COMMIT_SKIPPED_EVENT: "skipped",
    }
    state = state_by_event.get(event_type, text(data.get("state") or data.get("status")) or "checked")
    commit = {
        "state": state,
        "commit_event_offset": data.get("commit_event_offset") or data.get("event_offset"),
        "message_id": text(data.get("message_id") or data.get("message_ref")),
        "content_sha256": text(data.get("content_sha256")),
    }
    if event_type == SESSION_OUTPUT_COMMIT_ACK_EVENT:
        return {
            "op": "commit_ack",
            "slot": "status",
            "source_authority": "runtime",
            "main_visibility": "hidden",
            "retention": "trace",
            "item_id": stable_id("commit", commit.get("message_id"), commit.get("commit_event_offset"), commit.get("content_sha256")),
            "state": "done",
            "commit": commit,
            "trace_refs": _trace_refs(data),
        }
    if event_type == SESSION_OUTPUT_COMMIT_FAILED_EVENT:
        detail = public_text(
            data.get("reason")
            or data.get("error")
            or data.get("summary")
            or "最终输出未写入会话记录。",
            limit=240,
        )
        return _typed_status_spec(
            data,
            kind="recovery_event",
            state="failed",
            title="输出未写入会话记录",
            detail=detail,
            item_id=stable_id("commit-failed", commit.get("message_id"), commit.get("commit_event_offset")),
            retention="final",
            commit=commit,
        )
    return {
        "op": "item_upsert",
        "slot": "trace",
        "source_authority": "runtime",
        "main_visibility": "trace_only",
        "retention": "trace",
        "item_id": stable_id("commit", state, commit.get("commit_event_offset")),
        "state": "done" if state in {"checked", "committed", "skipped"} else "failed",
        "commit": commit,
        "trace_refs": _trace_refs(data),
    }


def _runtime_step_summary_spec(data: dict[str, Any]) -> dict[str, Any]:
    progress_note = public_text(data.get("public_progress_note"), limit=180)
    current_judgment = public_text(data.get("current_judgment"), limit=180)
    next_action = public_text(data.get("next_action"), limit=220)
    agent_brief = public_text(data.get("agent_brief_output"), limit=220)
    summary = public_text(data.get("summary"), limit=180)
    title = progress_note or current_judgment or summary
    title = _public_runtime_step_title(data, title)
    detail = next(
        (
            value
            for value in (current_judgment, next_action, agent_brief)
            if value and value != title
        ),
        "",
    )
    presentation_source = text(data.get("presentation_source"))
    if presentation_source in _TRACE_ONLY_RUNTIME_STEP_SOURCES:
        trace_title = "" if presentation_source == "runtime.protocol_repair" else title
        trace_detail = "" if presentation_source == "runtime.protocol_repair" else detail
        return {
            "op": "item_upsert",
            "slot": "trace",
            "source_authority": "runtime",
            "main_visibility": "hidden",
            "retention": "trace",
            "frame_id": _runtime_stage_status_frame_id(data, title=trace_title, detail=trace_detail),
            "item_id": stable_id(
                "runtime-step",
                data.get("runtime_event_id"),
                data.get("source_task_event_id"),
                data.get("source_task_event_offset"),
                data.get("step"),
            ),
            "title": trace_title,
            "text": trace_title,
            "detail": trace_detail,
            "state": text(data.get("status")) or "running",
            "trace_refs": _trace_refs(data),
        }
    if presentation_source.startswith("model_action.") and (title or detail):
        body_text = _runtime_step_summary_body_text(title=title, detail=detail)
        return {
            "op": "body_append",
            "slot": "body",
            "source_authority": "model",
            "event_family": ASSISTANT_BODY_EVENT_FAMILY,
            "channel": BODY_PUBLIC_CHANNEL,
            "lossless": True,
            "main_visibility": "visible_live",
            "retention": "transient",
            "frame_id": _runtime_stage_status_frame_id(data, title=title, detail=detail),
            "item_id": _runtime_step_summary_body_item_id(data, title=title, detail=detail),
            "title": title,
            "text": body_text,
            "detail": detail,
            "state": text(data.get("status")) or "running",
            "trace_refs": _trace_refs(data),
        }
    return _hidden_trace_spec("runtime_step_summary", data)


def _active_task_steer_status_spec(data: dict[str, Any]) -> dict[str, Any]:
    detail = public_text(data.get("summary") or data.get("message") or data.get("content"), limit=180)
    return _typed_status_spec(
        data,
        kind="status_event",
        state="done",
        title="补充要求已接入当前任务",
        detail=detail,
        item_id=stable_id(
            "active-task-steer",
            data.get("runtime_event_id"),
            data.get("task_run_id"),
            data.get("turn_run_id"),
            data.get("turn_id"),
        ),
        retention="transient",
    )


def _turn_terminal_spec(data: dict[str, Any]) -> dict[str, Any]:
    state = text(data.get("status") or data.get("state")).lower()
    if state not in {"failed", "error", "stopped", "aborted", "cancelled", "canceled", "blocked"}:
        return _hidden_trace_spec(TURN_COMPLETED_EVENT, data)
    if _is_agent_closeout_recovery_terminal(data):
        return _hidden_trace_spec(TURN_COMPLETED_EVENT, data)
    terminal_kind = "terminal_event" if state in {"stopped", "aborted", "cancelled", "canceled"} else "recovery_event"
    detail = public_text(
        data.get("error_summary")
        or data.get("stopped_reason")
        or data.get("terminal_reason")
        or data.get("reason")
        or data.get("error"),
        limit=260,
    )
    title = "运行已停止" if terminal_kind == "terminal_event" else _runtime_recovery_title(detail)
    return _typed_status_spec(
        data,
        kind=terminal_kind,
        state="stopped" if terminal_kind == "terminal_event" else "failed",
        title=title,
        detail=detail,
        item_id=stable_id(
            "turn-terminal",
            data.get("runtime_event_id"),
            data.get("turn_run_id"),
            data.get("task_run_id"),
            data.get("terminal_reason"),
            state,
        ),
        retention="final",
    )


def _is_agent_closeout_recovery_terminal(data: dict[str, Any]) -> bool:
    completion_state = text(data.get("completion_state"))
    terminal_reason = text(data.get("terminal_reason"))
    signal = record(data.get("runtime_control_signal"))
    contract_feedback = record(data.get("agent_contract_feedback"))
    return (
        completion_state == "agent_closeout_recovery_required"
        or completion_state == "agent_contract_feedback_required"
        or terminal_reason == "agent_closeout_recovery_required"
        or terminal_reason == "agent_contract_feedback_required"
        or text(signal.get("signal_kind")) == "agent_closeout_recovery_required"
        or text(contract_feedback.get("signal_kind")) == "agent_contract_feedback_required"
    )


def _stream_terminal_status_spec(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    terminal_kind = "terminal_event" if event_type == "stopped" else "recovery_event"
    detail = public_text(data.get("error") or data.get("reason") or data.get("terminal_reason") or data.get("message"), limit=260)
    title = "运行已停止" if terminal_kind == "terminal_event" else _runtime_recovery_title(detail)
    return _typed_status_spec(
        data,
        kind=terminal_kind,
        state="stopped" if terminal_kind == "terminal_event" else "failed",
        title=title,
        detail=detail,
        item_id=stable_id(
            "stream-terminal",
            event_type,
            data.get("runtime_event_id"),
            data.get("turn_run_id"),
            data.get("task_run_id"),
            data.get("terminal_reason"),
        ),
        retention="final",
    )


def _typed_status_spec(
    data: dict[str, Any],
    *,
    kind: str,
    state: str,
    title: str,
    detail: str = "",
    item_id: str = "",
    retention: str = "transient",
    commit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "op": "item_upsert",
        "slot": "status",
        "source_authority": "runtime",
        "main_visibility": "visible_live",
        "retention": retention,
        "item_id": item_id or stable_id("status-event", kind, data.get("runtime_event_id"), data.get("event_id")),
        "title": title,
        "text": title,
        "detail": detail,
        "state": state,
        "status_kind": kind,
        "trace_refs": _trace_refs(data),
    }
    if commit:
        result["commit"] = commit
    return result


def _runtime_recovery_title(detail: str) -> str:
    value = public_text(detail, limit=120)
    if not value or value in {"运行中断", "已中断"}:
        return "处理需要恢复"
    return value


def _runtime_step_summary_body_text(*, title: str, detail: str) -> str:
    if title and detail and _normalized_body_text(title) != _normalized_body_text(detail):
        return f"{title}\n\n{detail}"
    return title or detail


def _public_runtime_step_title(data: dict[str, Any], title: str) -> str:
    status = text(data.get("status")).lower()
    step = text(data.get("step")).lower()
    normalized_title = text(title)
    if status == "waiting_executor" or step.startswith("task_run_waiting_executor"):
        if "user_input_required" in normalized_title or not normalized_title:
            return "当前步骤正在等待你的确认。"
        if _looks_like_runtime_reason_code(normalized_title):
            return "当前步骤正在等待继续。"
    return normalized_title


def _looks_like_runtime_reason_code(value: str) -> bool:
    normalized = text(value)
    if not normalized or any(ord(ch) > 127 for ch in normalized):
        return False
    return "_" in normalized or normalized.startswith(("task-", "task:", "stream-", "stream:", "runtime-", "runtime:", "background-"))


def _normalized_body_text(value: str) -> str:
    return " ".join(text(value).split()).strip()


def _runtime_step_summary_body_item_id(data: dict[str, Any], *, title: str, detail: str) -> str:
    feedback_identity = text(data.get("feedback_identity"))
    if feedback_identity:
        return stable_id("model-action-feedback-body", feedback_identity)
    return stable_id(
        "model-action-feedback-body",
        data.get("runtime_event_id"),
        data.get("source_task_event_id"),
        data.get("source_task_event_offset"),
        data.get("step"),
        title,
        detail,
    )


def _runtime_stage_status_frame_id(data: dict[str, Any], *, title: str, detail: str) -> str:
    presentation_source = text(data.get("presentation_source"))
    feedback_identity = text(data.get("feedback_identity"))
    if presentation_source.startswith("model_action.") and feedback_identity:
        return stable_id("runtime-step-frame", "model-action-feedback", feedback_identity)
    return stable_id("runtime-step-frame", _runtime_stage_status_item_id(data), title, detail)


def _runtime_stage_status_item_id(data: dict[str, Any]) -> str:
    presentation_source = text(data.get("presentation_source"))
    feedback_identity = text(data.get("feedback_identity"))
    if presentation_source.startswith("model_action.") and feedback_identity:
        return stable_id("model-action-feedback", feedback_identity)
    anchor = record(data.get("public_anchor"))
    task_run_id = text(data.get("task_run_id")) or text(anchor.get("task_run_id")) or text(data.get("runtime_task_run_id"))
    if task_run_id:
        return stable_id("task-stage-status", task_run_id, "public")
    return stable_id("turn-stage-status", data.get("turn_run_id"), data.get("turn_id"), "public")


def _hidden_trace_spec(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "op": "item_upsert",
        "slot": "trace",
        "source_authority": "runtime",
        "main_visibility": "hidden",
        "retention": "trace",
        "item_id": stable_id("trace", event_type, data.get("runtime_event_id"), data.get("event_id")),
        "state": text(data.get("state") or data.get("status")) or "running",
        "trace_refs": _trace_refs(data),
    }


def _protocol_diagnostic_spec(data: dict[str, Any], *, code: str, detail: str) -> dict[str, Any]:
    return {
        "op": "item_upsert",
        "slot": "trace",
        "source_authority": "system",
        "main_visibility": "hidden",
        "retention": "trace",
        "item_id": stable_id("projection-diagnostic", code, data.get("runtime_event_id"), data.get("tool_call_id")),
        "title": "公开投影协议诊断",
        "text": "公开投影协议诊断",
        "detail": detail,
        "state": "failed",
        "diagnostics": {"code": code},
        "trace_refs": _trace_refs(data),
    }


def _tool_request_text(data: dict[str, Any], *, tool_name: str, subject: str = "") -> str:
    visible_subject = subject or public_text(data.get("target") or data.get("arguments_preview"), limit=180)
    structured = _structured_tool_action_text(tool_name=tool_name, subject=visible_subject)
    return structured or visible_subject or text(tool_name)


def _structured_tool_action_text(*, tool_name: str, subject: str) -> str:
    visible_subject = public_text(subject, limit=140)
    normalized_tool = text(tool_name).lower()
    if normalized_tool in {"path_exists", "stat_path"}:
        return f"检查路径：{visible_subject}" if visible_subject else "检查路径"
    if normalized_tool == "list_dir":
        return f"列出目录：{visible_subject}" if visible_subject else "列出目录"
    if normalized_tool in {"search_files", "search_text", "glob_paths"}:
        verb = {
            "search_files": "搜索文件",
            "search_text": "搜索文本",
            "glob_paths": "匹配路径",
        }.get(normalized_tool, "搜索")
        return f"{verb}：{visible_subject}" if visible_subject else verb
    if normalized_tool in {"read_file", "read_files", "read_path"}:
        return f"读取文件：{visible_subject}" if visible_subject else "读取文件"
    if normalized_tool in {"write_file", "edit_file", "batch_edit_file", "apply_patch"}:
        return f"更新文件：{visible_subject}" if visible_subject else "更新文件"
    if visible_subject:
        return f"{tool_name}：{visible_subject}"
    return text(tool_name)


def _tool_completed_text(data: dict[str, Any], *, tool_name: str, failed: bool) -> str:
    explicit = public_text(data.get("title") or data.get("summary"), limit=120)
    if explicit:
        return explicit
    tool_label = _tool_display_label(tool_name)
    normalized_tool = text(tool_name).lower()
    if failed:
        return f"{tool_label}失败" if tool_label else "工具执行失败"
    if normalized_tool in {"search_files", "search_text", "glob_paths"}:
        return "搜索完成"
    if normalized_tool in {"read_file", "read_files", "read_path"}:
        return "文件读取完成"
    if normalized_tool in {"write_file", "edit_file", "batch_edit_file", "apply_patch"}:
        return "文件更新完成"
    if tool_label:
        return f"{tool_label}完成"
    return "工具执行完成"


def _tool_completion_detail(value: Any, *, limit: int) -> str:
    visible = public_text(value, limit=limit)
    if visible:
        return visible
    raw_text = text(value)
    if _LINE_NUMBERED_TOOL_OUTPUT_RE.search(raw_text):
        return ""
    raw = " ".join(raw_text.split()).strip()
    if not _TOOL_FAILURE_FEEDBACK_RE.match(raw):
        return ""
    if looks_like_runtime_private_artifact_text(raw):
        return ""
    if limit > 0 and len(raw) > limit:
        return raw[: max(1, limit - 1)] + "..."
    return raw


def _tool_display_label(tool_name: str) -> str:
    normalized = text(tool_name).lower()
    return {
        "apply_patch": "更新文件",
        "batch_edit_file": "更新文件",
        "edit_file": "更新文件",
        "glob_paths": "匹配路径",
        "list_dir": "列出目录",
        "path_exists": "检查路径",
        "read_file": "读取文件",
        "read_files": "读取文件",
        "read_path": "读取文件",
        "search_files": "搜索文件",
        "search_text": "搜索文本",
        "stat_path": "检查路径",
        "write_file": "写入文件",
    }.get(normalized, "")


def _body_item_id(data: dict[str, Any]) -> str:
    return text(data.get("body_segment_id")) or text(data.get("message_ref")) or stable_id("body", data.get("stream_ref"), data.get("sequence"))


def _trace_refs(data: dict[str, Any]) -> list[str]:
    event = record(data.get("event"))
    refs = []
    for value in (
        data.get("runtime_event_id"),
        data.get("event_id"),
        event.get("event_id"),
        data.get("source_turn_event_id"),
        data.get("source_handoff_event_id"),
        data.get("source_task_event_id"),
        data.get("source_task_event_offset"),
        data.get("turn_run_id"),
        data.get("task_run_id"),
        data.get("debug_trace_ref"),
    ):
        if text(value):
            refs.append(text(value))
    return refs


def _event_offset(*, sequence: int = 0) -> int:
    try:
        return int(sequence)
    except (TypeError, ValueError):
        return 0


def _tool_lifecycle_key(data: dict[str, Any], *, tool_call_id: str) -> str:
    scope = _tool_lifecycle_scope(data)
    return stable_id("tool-lifecycle", scope, tool_call_id) if scope else text(tool_call_id)


def _tool_lifecycle_scope(data: dict[str, Any]) -> str:
    anchor = record(data.get("public_anchor"))
    return (
        text(data.get("turn_run_id"))
        or text(anchor.get("turn_run_id"))
        or text(data.get("task_run_id"))
        or text(data.get("runtime_task_run_id"))
        or text(anchor.get("task_run_id"))
        or text(data.get("turn_id"))
        or text(data.get("active_turn_id"))
        or text(anchor.get("turn_id"))
    )
