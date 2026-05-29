from __future__ import annotations

from typing import Any


def build_session_runtime_timeline(
    *,
    session_id: str,
    history: dict[str, Any],
    runtime_host: Any,
    max_progress_entries: int = 24,
) -> dict[str, Any]:
    attachments = [
        _runtime_attachment(runtime_host, task_run, max_progress_entries=max_progress_entries)
        for task_run in sorted(
            runtime_host.state_index.list_session_task_runs(session_id),
            key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0),
        )
        if _is_formal_chat_task_run(task_run)
    ]
    return {
        **dict(history or {}),
        "session_id": session_id,
        "runtime_attachments": [item for item in attachments if item],
        "authority": "session_runtime_timeline",
    }


def _is_formal_chat_task_run(task_run: Any) -> bool:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    task_id = str(getattr(task_run, "task_id", "") or "")
    return task_run_id.startswith("taskrun:turn:") or task_id.startswith("task:turn:")


def _runtime_attachment(runtime_host: Any, task_run: Any, *, max_progress_entries: int) -> dict[str, Any]:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    if not task_run_id:
        return {}
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    events = [item.to_dict() for item in runtime_host.event_log.list_events(task_run_id)]
    monitor = runtime_host.monitor_projector.project_task_run(task_run, now=_latest_now(events, task_run))
    final_answer = str(diagnostics.get("final_answer") or "")
    artifact_refs = list(diagnostics.get("artifact_refs") or [])
    progress_entries = _progress_entries(events)[-max(1, int(max_progress_entries or 24)) :]
    return {
        "attachment_id": f"runtime-attachment:{task_run_id}",
        "anchor_turn_id": str(diagnostics.get("turn_id") or _turn_id_from_task_run(task_run_id) or ""),
        "task_run_id": task_run_id,
        "task_id": str(getattr(task_run, "task_id", "") or ""),
        "status": str(getattr(task_run, "status", "") or ""),
        "terminal_reason": str(getattr(task_run, "terminal_reason", "") or ""),
        "lifecycle": str(monitor.get("lifecycle") or ""),
        "bucket": str(monitor.get("bucket") or ""),
        "title": str(monitor.get("title") or ""),
        "summary": str(monitor.get("summary") or ""),
        "latest_step": dict(monitor.get("latest_step") or {}),
        "latest_step_summary": str(monitor.get("latest_step_summary") or ""),
        "latest_event_type": str(monitor.get("latest_event_type") or ""),
        "event_count": len(events),
        "progress_entries": progress_entries,
        "artifact_refs": artifact_refs,
        "final_answer": final_answer,
        "trace_available": True,
        "created_at": float(getattr(task_run, "created_at", 0.0) or 0.0),
        "updated_at": float(getattr(task_run, "updated_at", 0.0) or 0.0),
        "authority": "session_runtime_timeline.attachment",
    }


def _latest_now(events: list[dict[str, Any]], task_run: Any) -> float:
    event_time = max((float(item.get("created_at") or 0.0) for item in events), default=0.0)
    return max(event_time, float(getattr(task_run, "updated_at", 0.0) or 0.0))


def _turn_id_from_task_run(task_run_id: str) -> str:
    prefix = "taskrun:turn:"
    if not task_run_id.startswith(prefix):
        return ""
    parts = task_run_id.split(":")
    if len(parts) < 5:
        return ""
    return ":".join(parts[1:4])


def _progress_entries(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        payload = dict(event.get("payload") or {})
        if event_type == "step_summary_recorded":
            summary = str(payload.get("summary") or "").strip()
            step = str(payload.get("step") or "").strip()
            status = str(payload.get("status") or "").strip()
            if summary or step:
                entries.append(
                    _entry(
                        event,
                        title=_step_title(step, status),
                        body=summary,
                        kind=_step_kind(step),
                        level=_level_from_status(status),
                        status=status,
                    )
                )
            continue
        if event_type in {"task_run_lifecycle_started", "task_run_executor_started"}:
            entries.append(_entry(event, title="任务已启动", body="正式任务生命周期已建立。", kind="task_order"))
            continue
        if event_type in {"executor_observation_recorded", "bounded_observation_recorded", "task_run_lifecycle_event"}:
            observation = dict(payload.get("observation") or {})
            source = str(observation.get("source") or "").strip()
            summary = str(observation.get("summary") or "").strip()
            if source or summary:
                entries.append(
                    _entry(
                        event,
                        title=_observation_title(source),
                        body=summary,
                        kind="tool" if source.startswith("tool:") else "system",
                        status="completed",
                        tool_name=source.removeprefix("tool:"),
                    )
                )
            continue
        if event_type == "task_run_lifecycle_finished":
            task_run = dict(payload.get("task_run") or {})
            status = str(task_run.get("status") or "completed")
            entries.append(
                _entry(
                    event,
                    title="任务已完成" if status == "completed" else "任务已停止",
                    body=str(task_run.get("terminal_reason") or status),
                    kind="terminal",
                    level="success" if status == "completed" else "error",
                    status=status,
                )
            )
    return entries


def _entry(
    event: dict[str, Any],
    *,
    title: str,
    body: str = "",
    kind: str = "stage",
    level: str = "running",
    status: str = "",
    tool_name: str = "",
) -> dict[str, Any]:
    return {
        "id": str(event.get("event_id") or f"{event.get('task_run_id')}:{event.get('offset')}"),
        "eventType": str(event.get("event_type") or ""),
        "taskRunId": str(event.get("task_run_id") or ""),
        "title": title,
        "body": body,
        "kind": kind,
        "level": level,
        "statusText": status,
        "toolName": tool_name,
        "createdAt": float(event.get("created_at") or 0.0),
    }


def _step_title(step: str, status: str) -> str:
    if step.startswith("task_model_action_invocation_started"):
        return "等待 agent 决策"
    if step.startswith("task_model_action_waiting"):
        return "agent 正在处理"
    if step.startswith("task_execution_packet_compiled"):
        return "装配任务运行时"
    if step.startswith("task_tool_executed"):
        return "工具调用完成"
    if step.startswith("task_completion_repair_required"):
        return "补充验收证据"
    if step == "task_run_completed":
        return "任务已完成"
    if status == "completed":
        return "步骤已完成"
    return "任务推进中"


def _step_kind(step: str) -> str:
    if "tool" in step:
        return "tool"
    if "completed" in step:
        return "terminal"
    if "repair" in step or "verification" in step:
        return "verification"
    if "model" in step:
        return "model"
    return "stage"


def _level_from_status(status: str) -> str:
    if status in {"completed", "success"}:
        return "success"
    if status in {"failed", "error", "blocked"}:
        return "error"
    if status.startswith("wait"):
        return "waiting"
    return "running"


def _observation_title(source: str) -> str:
    if source.startswith("tool:"):
        return "工具观察"
    if source:
        return "运行观察"
    return "观察记录"
