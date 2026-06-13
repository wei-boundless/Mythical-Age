from __future__ import annotations

from typing import Any

from .authority import build_public_projection_frame
from .guards import public_text, record, stable_id, text
from .items import action_kind_for_tool
from runtime.output_stream.public_contract import (
    ASSISTANT_STREAM_REPAIR_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_CHECKED_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
    TOOL_CALL_REQUESTED_EVENT,
    TOOL_ITEM_COMPLETED_EVENT,
    TOOL_ITEM_STARTED_EVENT,
    TOOL_PERMISSION_DECIDED_EVENT,
    TURN_COMPLETED_EVENT,
)


def project_public_projection_event(
    public_event_type: str,
    data: dict[str, Any],
    *,
    session_id: str = "",
    sequence: int = 0,
    public_anchor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(data or {})
    payload.setdefault("sequence", int(sequence or payload.get("sequence") or 0))
    if public_anchor:
        payload["public_anchor"] = dict(public_anchor)
    spec = projection_spec_for_event(public_event_type, payload)
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
) -> None:
    projection = project_public_projection_event(
        public_event_type,
        data,
        session_id=session_id,
        sequence=sequence,
        public_anchor=public_anchor,
    )
    data["public_projection_frame"] = projection["public_projection_frame"]
    data.pop("public_projection_envelope", None)
    data.pop("public_timeline_delta", None)
    data.pop("task_projection", None)
    data.pop("task_projection_delta", None)


def projection_spec_for_event(public_event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    event_type = text(public_event_type)
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
    if event_type in {
        SESSION_OUTPUT_COMMIT_CHECKED_EVENT,
        SESSION_OUTPUT_COMMIT_ACK_EVENT,
        SESSION_OUTPUT_COMMIT_FAILED_EVENT,
        SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
    }:
        return _commit_spec(event_type, data)
    if event_type == TURN_COMPLETED_EVENT:
        return _turn_terminal_spec(data)
    if event_type == "runtime_status":
        return _status_spec(data)
    if event_type == "active_task_steer_accepted":
        return _status_spec(data, title="已收到补充要求")
    if event_type in {"error", "stopped"}:
        return _terminal_status_spec(event_type, data)
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


def _tool_call_requested_spec(data: dict[str, Any]) -> dict[str, Any]:
    tool_name = text(data.get("tool_name")) or "tool"
    tool_call_id = text(data.get("tool_call_id"))
    action_kind = action_kind_for_tool(tool_name, data.get("target") or data.get("arguments_preview"))
    title = _tool_request_text(data, tool_name=tool_name)
    subject = public_text(data.get("target") or data.get("arguments_preview"), limit=180)
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
    if decision in {"allow", "allowed"}:
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
    if not tool_call_id or not permission_decision_id:
        return _protocol_diagnostic_spec(
            data,
            code="tool_started_without_request_or_permission",
            detail="tool_item_started 缺少 tool_call_id 或 permission_decision_id，不能进入主视图。",
        )
    tool_name = text(data.get("tool_name")) or "tool"
    return {
        "op": "item_upsert",
        "slot": "trace",
        "source_authority": "tool",
        "main_visibility": "trace_only",
        "retention": "trace",
        "item_id": text(data.get("tool_lifecycle_id")) or tool_call_id,
        "tool_call_id": tool_call_id,
        "permission_decision_id": permission_decision_id,
        "tool_name": tool_name,
        "tool_lifecycle_id": text(data.get("tool_lifecycle_id")) or tool_call_id,
        "title": "工具开始执行",
        "text": "工具开始执行",
        "state": "running",
        "trace_refs": _trace_refs(data),
    }


def _tool_completed_spec(data: dict[str, Any]) -> dict[str, Any]:
    tool_call_id = text(data.get("tool_call_id"))
    permission_decision_id = text(data.get("permission_decision_id"))
    if not tool_call_id or not permission_decision_id:
        return _protocol_diagnostic_spec(
            data,
            code="tool_completed_without_request_or_permission",
            detail="tool_item_completed 缺少 tool_call_id 或 permission_decision_id，不能进入主视图。",
        )
    tool_name = text(data.get("tool_name")) or "tool"
    raw_state = text(data.get("state")).lower()
    failed = raw_state in {"error", "failed", "blocked"}
    detail = public_text(data.get("error") or data.get("observation"), limit=360)
    if failed:
        return {
            "op": "item_upsert",
            "slot": "pinned",
            "source_authority": "tool",
            "main_visibility": "pinned",
            "retention": "pinned_until_resolved",
            "pin_reason": "failed",
            "item_id": text(data.get("tool_lifecycle_id")) or tool_call_id,
            "tool_call_id": tool_call_id,
            "permission_decision_id": permission_decision_id,
            "tool_name": tool_name,
            "tool_lifecycle_id": text(data.get("tool_lifecycle_id")) or tool_call_id,
            "title": "工具执行失败",
            "text": "工具执行失败",
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
        "title": "工具已完成",
        "text": "工具已完成",
        "detail": detail,
        "state": "done",
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
        detail = public_text(data.get("reason") or data.get("error") or data.get("summary"), limit=260)
        return {
            "op": "commit_failed",
            "slot": "pinned",
            "source_authority": "runtime",
            "main_visibility": "pinned",
            "retention": "pinned_until_resolved",
            "pin_reason": "commit_failed",
            "item_id": stable_id("commit-failed", commit.get("message_id"), commit.get("commit_event_offset"), detail),
            "title": "结果写回失败",
            "text": "结果写回失败",
            "detail": detail,
            "state": "failed",
            "commit": commit,
            "trace_refs": _trace_refs(data),
        }
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


def _turn_terminal_spec(data: dict[str, Any]) -> dict[str, Any]:
    status = text(data.get("status")).lower() or "completed"
    failed = status == "failed"
    stopped = status == "stopped"
    detail = public_text(data.get("error_summary") or data.get("stopped_reason") or data.get("terminal_reason"), limit=260)
    return {
        "op": "turn_terminal",
        "slot": "pinned" if failed or stopped else "trace",
        "source_authority": "runtime",
        "main_visibility": "pinned" if failed or stopped else "hidden",
        "retention": "pinned_until_resolved" if failed or stopped else "trace",
        "pin_reason": "failed" if failed else ("blocked" if stopped else ""),
        "item_id": stable_id("turn-terminal", data.get("turn_run_id"), data.get("task_run_id"), status),
        "title": "运行中断" if failed else ("运行已停止" if stopped else "本轮结束"),
        "text": "运行中断" if failed else ("运行已停止" if stopped else ""),
        "detail": detail,
        "state": "failed" if failed else ("stopped" if stopped else "done"),
        "trace_refs": _trace_refs(data),
    }


def _status_spec(data: dict[str, Any], *, title: str = "") -> dict[str, Any]:
    visible_title = public_text(title or data.get("title") or data.get("summary"), limit=140)
    visible_detail = public_text(data.get("detail"), limit=260)
    state = text(data.get("state") or data.get("status")) or "running"
    return {
        "op": "item_upsert",
        "slot": "status",
        "source_authority": "runtime",
        "main_visibility": "visible_live" if visible_title or visible_detail else "hidden",
        "retention": "transient",
        "item_id": stable_id("status", data.get("runtime_event_id"), visible_title, visible_detail),
        "title": visible_title,
        "text": visible_title,
        "detail": visible_detail,
        "state": state,
        "trace_refs": _trace_refs(data),
    }


def _terminal_status_spec(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    failed = event_type == "error"
    return {
        "op": "item_upsert",
        "slot": "pinned",
        "source_authority": "runtime",
        "main_visibility": "pinned",
        "retention": "pinned_until_resolved",
        "pin_reason": "failed" if failed else "blocked",
        "item_id": stable_id("terminal", event_type, data.get("runtime_event_id")),
        "title": "运行中断" if failed else "运行已停止",
        "text": "运行中断" if failed else "运行已停止",
        "detail": public_text(data.get("error") or data.get("reason") or data.get("content"), limit=260),
        "state": "failed" if failed else "stopped",
        "trace_refs": _trace_refs(data),
    }


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


def _tool_request_text(data: dict[str, Any], *, tool_name: str) -> str:
    action_state = record(data.get("public_action_state"))
    return (
        public_text(action_state.get("next_action"), limit=180)
        or public_text(data.get("public_progress_note"), limit=180)
        or f"运行工具 {tool_name}"
    )


def _body_item_id(data: dict[str, Any]) -> str:
    return text(data.get("body_segment_id")) or text(data.get("message_ref")) or stable_id("body", data.get("stream_ref"), data.get("sequence"))


def _trace_refs(data: dict[str, Any]) -> list[str]:
    event = record(data.get("event"))
    refs = []
    for value in (
        data.get("runtime_event_id"),
        data.get("event_id"),
        event.get("event_id"),
        data.get("turn_run_id"),
        data.get("task_run_id"),
        data.get("debug_trace_ref"),
    ):
        if text(value):
            refs.append(text(value))
    return refs
