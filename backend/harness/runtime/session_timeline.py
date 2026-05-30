from __future__ import annotations

from typing import Any

from harness.runtime.public_progress import public_runtime_progress_summary, public_runtime_progress_title


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
    events = [item.to_dict() for item in _recent_events(runtime_host, task_run_id, limit=max_progress_entries * 8)]
    monitor = runtime_host.monitor_projector.project_task_run(task_run, now=_latest_now(events, task_run))
    final_answer = str(diagnostics.get("final_answer") or "")
    artifact_refs = list(diagnostics.get("artifact_refs") or [])
    progress_entries = _progress_entries(events)[-max(1, int(max_progress_entries or 24)) :]
    return {
        "attachment_id": f"runtime-attachment:{task_run_id}",
        "anchor_turn_id": _anchor_turn_id(task_run_id=task_run_id, diagnostics=diagnostics, events=events),
        "task_run_id": task_run_id,
        "task_id": str(getattr(task_run, "task_id", "") or ""),
        "status": str(getattr(task_run, "status", "") or ""),
        "terminal_reason": str(getattr(task_run, "terminal_reason", "") or ""),
        "lifecycle": str(monitor.get("lifecycle") or ""),
        "bucket": str(monitor.get("bucket") or ""),
        "title": str(monitor.get("title") or ""),
        "summary": public_runtime_progress_summary(monitor.get("summary") or ""),
        "latest_step": dict(monitor.get("latest_step") or {}),
        "latest_step_summary": public_runtime_progress_summary(monitor.get("latest_step_summary") or ""),
        "latest_event_type": str(monitor.get("latest_event_type") or ""),
        "event_count": _event_count(runtime_host, task_run_id, fallback=len(events)),
        "progress_entries": progress_entries,
        "artifact_refs": artifact_refs,
        "final_answer": final_answer,
        "trace_available": True,
        "created_at": float(getattr(task_run, "created_at", 0.0) or 0.0),
        "updated_at": float(getattr(task_run, "updated_at", 0.0) or 0.0),
        "authority": "session_runtime_timeline.attachment",
    }


def _recent_events(runtime_host: Any, task_run_id: str, *, limit: int) -> list[Any]:
    reader = getattr(runtime_host.event_log, "list_recent_events", None)
    if callable(reader):
        try:
            return list(reader(task_run_id, limit=max(1, int(limit or 160))))
        except TypeError:
            return list(reader(task_run_id))
        except Exception:
            return []
    legacy_reader = getattr(runtime_host.event_log, "list_events", None)
    if callable(legacy_reader):
        try:
            return list(legacy_reader(task_run_id))[-max(1, int(limit or 160)) :]
        except Exception:
            return []
    return []


def _event_count(runtime_host: Any, task_run_id: str, *, fallback: int) -> int:
    estimator = getattr(runtime_host.event_log, "estimated_event_count", None)
    if callable(estimator):
        try:
            return int(estimator(task_run_id))
        except Exception:
            return int(fallback)
    counter = getattr(runtime_host.event_log, "event_count", None)
    if callable(counter):
        try:
            return int(counter(task_run_id))
        except Exception:
            return int(fallback)
    return int(fallback)


def _latest_now(events: list[dict[str, Any]], task_run: Any) -> float:
    event_time = max((float(item.get("created_at") or 0.0) for item in events), default=0.0)
    return max(event_time, float(getattr(task_run, "updated_at", 0.0) or 0.0))


def _anchor_turn_id(*, task_run_id: str, diagnostics: dict[str, Any], events: list[dict[str, Any]]) -> str:
    return (
        _latest_interaction_turn_id(events)
        or _valid_turn_ref(diagnostics.get("latest_interaction_turn_id"))
        or _lineage_turn_id(diagnostics)
        or _valid_turn_ref(diagnostics.get("turn_id"))
        or _turn_id_from_task_run(task_run_id)
        or ""
    )


def _latest_interaction_turn_id(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        event_type = str(event.get("event_type") or "")
        payload = dict(event.get("payload") or {})
        refs = dict(event.get("refs") or {})
        if event_type in {
            "user_work_instruction_recorded",
            "active_task_steer_recorded",
            "task_run_resume_requested",
            "task_run_executor_scheduled",
            "step_summary_recorded",
        }:
            steer = dict(payload.get("steer") or {})
            observation = dict(payload.get("observation") or {})
            observation_payload = dict(observation.get("payload") or {})
            structured_payload = dict(observation_payload.get("structured_payload") or {})
            for candidate in (
                refs.get("turn_ref"),
                payload.get("turn_id"),
                dict(payload.get("submission") or {}).get("turn_id"),
                observation.get("request_ref"),
                structured_payload.get("turn_id"),
                steer.get("turn_id"),
            ):
                turn_id = _valid_turn_ref(candidate)
                if turn_id:
                    return turn_id
        if event_type == "task_run_checkout_created":
            lineage = dict(payload.get("lineage") or {})
            task_run = dict(payload.get("task_run") or {})
            task_diagnostics = dict(task_run.get("diagnostics") or {})
            for candidate in (
                refs.get("turn_ref"),
                lineage.get("turn_id"),
                _lineage_turn_id(task_diagnostics),
            ):
                turn_id = _valid_turn_ref(candidate)
                if turn_id:
                    return turn_id
    return ""


def _lineage_turn_id(diagnostics: dict[str, Any]) -> str:
    lineage = diagnostics.get("lineage")
    if isinstance(lineage, dict):
        turn_id = _valid_turn_ref(lineage.get("turn_id"))
        if turn_id:
            return turn_id
    return ""


def _valid_turn_ref(value: Any) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate.startswith("turn:") else ""


def _turn_id_from_task_run(task_run_id: str) -> str:
    prefix = "taskrun:turn:"
    if not task_run_id.startswith(prefix):
        return ""
    parts = task_run_id.split(":")
    if len(parts) < 5:
        return ""
    for index in range(2, len(parts)):
        if parts[index].isdigit():
            return ":".join(parts[1 : index + 1])
    return ""


def _progress_entries(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        payload = dict(event.get("payload") or {})
        if event_type == "step_summary_recorded":
            summary = public_runtime_progress_summary(payload.get("summary") or "").strip()
            public_note = public_runtime_progress_summary(payload.get("public_progress_note") or summary).strip()
            agent_brief = public_runtime_progress_summary(payload.get("agent_brief_output") or "").strip()
            step = str(payload.get("step") or "").strip()
            status = str(payload.get("status") or "").strip()
            if public_note or summary or step:
                entries.append(
                    _entry(
                        event,
                        title=_step_title(step, status),
                        body=public_note or summary,
                        kind=_step_kind(step),
                        level=_level_from_status(status),
                        status=status,
                        public_note=public_note,
                        agent_brief=agent_brief,
                        evidence_type=_evidence_type(event_type, step),
                    )
                )
            continue
        if event_type in {"task_run_lifecycle_started", "task_run_executor_started"}:
            entries.append(_entry(event, title="处理已开始", body="后续进展会继续汇总。", kind="task_order"))
            continue
        if event_type in {"user_work_instruction_recorded", "active_task_steer_recorded"}:
            steer = dict(payload.get("steer") or {})
            observation = dict(payload.get("observation") or {})
            observation_payload = dict(observation.get("payload") or {})
            structured_payload = dict(observation_payload.get("structured_payload") or {})
            instruction = str(
                steer.get("content")
                or structured_payload.get("user_instruction")
                or observation_payload.get("result")
                or ""
            ).strip()
            entries.append(
                _entry(
                    event,
                    title="收到补充要求",
                    body=public_runtime_progress_summary(instruction),
                    kind="stage",
                    level="success",
                    status="completed",
                    tool_name="",
                    public_note=public_runtime_progress_summary(instruction),
                    evidence_type="user_instruction",
                )
            )
            continue
        if event_type in {"executor_observation_recorded", "bounded_observation_recorded", "task_run_lifecycle_event"}:
            observation = dict(payload.get("observation") or {})
            source = str(observation.get("source") or "").strip()
            summary = public_runtime_progress_summary(observation.get("summary") or "").strip()
            if source or summary:
                entries.append(
                    _entry(
                        event,
                        title=_observation_title(source),
                        body=summary,
                        kind="tool" if source.startswith("tool:") else "system",
                        status="completed",
                        tool_name=source.removeprefix("tool:"),
                        public_note=summary,
                        agent_brief=summary,
                        evidence_type="tool_observation" if source.startswith("tool:") else "observation",
                    )
                )
            continue
        if event_type == "task_run_lifecycle_finished":
            task_run = dict(payload.get("task_run") or {})
            status = str(task_run.get("status") or "completed")
            entries.append(
                _entry(
                    event,
                    title="处理已完成" if status == "completed" else "处理已停止",
                    body=public_runtime_progress_summary(task_run.get("terminal_reason") or status),
                    kind="terminal",
                    level="success" if status == "completed" else "error",
                    status=status,
                    public_note=public_runtime_progress_summary(task_run.get("terminal_reason") or status),
                    evidence_type="terminal",
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
    public_note: str = "",
    agent_brief: str = "",
    evidence_type: str = "",
) -> dict[str, Any]:
    item = {
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
    if public_note:
        item["publicNote"] = public_note
    if agent_brief:
        item["agentBrief"] = agent_brief
    if evidence_type:
        item["evidenceType"] = evidence_type
    return item


def _step_title(step: str, status: str) -> str:
    if step.startswith("task_model_action_invocation_started"):
        return "思考下一步"
    if step.startswith("task_model_action_waiting"):
        return "等待结果"
    if step.startswith("task_execution_packet_compiled"):
        return "整理上下文"
    if step.startswith("task_tool_executed"):
        return "执行操作"
    if step.startswith("task_completion_repair_required"):
        return "补充验收证据"
    if step == "task_run_completed":
        return "处理已完成"
    if status == "completed":
        return "步骤已完成"
    return public_runtime_progress_title(step=step, status=status)


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
        return "执行操作"
    if source:
        return "处理观察"
    return "观察结果"


def _evidence_type(event_type: str, step: str) -> str:
    if "tool" in step:
        return "tool_observation"
    if "model_action" in step:
        return "model_action"
    if "repair" in step or "verification" in step:
        return "verification"
    if "completed" in step or event_type.endswith("finished"):
        return "terminal"
    return "runtime_step"
