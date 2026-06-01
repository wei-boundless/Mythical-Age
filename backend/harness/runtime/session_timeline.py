from __future__ import annotations

import json
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
        "run_id": task_run_id,
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
    all_events_reader = getattr(runtime_host.event_log, "list_events", None)
    if callable(all_events_reader):
        try:
            return list(all_events_reader(task_run_id))[-max(1, int(limit or 160)) :]
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
    observations_by_ref = _observations_by_ref(events)
    for event in events:
        event_type = str(event.get("event_type") or "")
        payload = dict(event.get("payload") or {})
        if event_type == "step_summary_recorded":
            summary = public_runtime_progress_summary(payload.get("summary") or "").strip()
            public_note = public_runtime_progress_summary(payload.get("public_progress_note") or summary).strip()
            agent_brief = public_runtime_progress_summary(payload.get("agent_brief_output") or "").strip()
            public_action_state = dict(payload.get("public_action_state") or {})
            current_judgment = public_runtime_progress_summary(
                payload.get("current_judgment") or public_action_state.get("current_judgment") or ""
            ).strip()
            next_action = public_runtime_progress_summary(payload.get("next_action") or public_action_state.get("next_action") or "").strip()
            completion_status = public_runtime_progress_summary(
                payload.get("completion_status") or public_action_state.get("completion_status") or ""
            ).strip()
            action_brief = _public_action_state_brief(
                current_judgment=current_judgment,
                next_action=next_action,
                completion_status=completion_status,
            )
            meta = _public_action_state_meta(
                current_judgment=current_judgment,
                next_action=next_action,
                completion_status=completion_status,
            )
            step = str(payload.get("step") or "").strip()
            status = str(payload.get("status") or "").strip()
            if step.startswith("task_tool_observation_recorded"):
                refs = dict(event.get("refs") or {})
                observation = observations_by_ref.get(str(refs.get("observation_ref") or "").strip(), {})
                source = str(observation.get("source") or "").strip()
                ref_tool_name = str(refs.get("tool_name") or "").strip()
                if _is_internal_tool_observation(source=source, text=agent_brief):
                    continue
                tool_name = source.removeprefix("tool:") or ref_tool_name
                observation_body = _tool_observation_body(agent_brief or _observation_payload_result(observation) or public_note or summary)
                failed = _observation_text_is_failure(agent_brief or observation_body)
                entries.append(
                    _entry(
                        event,
                        title=_observation_title(source or (f"tool:{tool_name}" if tool_name else ""), observation=observation),
                        body=observation_body or public_note or summary,
                        kind="observation",
                        level="error" if failed else _level_from_status(status),
                        status="failed" if failed else (status or "completed"),
                        tool_name=tool_name,
                        public_note=observation_body or public_note or summary,
                        agent_brief=observation_body or agent_brief,
                        evidence_type="tool_observation",
                        meta=meta,
                    )
                )
                continue
            if _is_internal_step_only(step, summary=summary, public_note=public_note, action_brief=action_brief):
                continue
            if public_note or action_brief or summary or step:
                body = action_brief if step.startswith("model_action_received") and action_brief else public_note or next_action or current_judgment or summary
                entries.append(
                    _entry(
                        event,
                        title="Agent 判断" if step.startswith("model_action_received") else _step_title(step, status),
                        body=body,
                        kind=_step_kind(step),
                        level=_level_from_status(status),
                        status=status,
                        public_note=public_note or body,
                        agent_brief=agent_brief or action_brief,
                        evidence_type=_evidence_type(event_type, step),
                        meta=meta,
                    )
                )
            continue
        if event_type == "agent_todo_initialized":
            entries.append(
                _entry(
                    event,
                    title="待办已建立",
                    body="已把任务目标转成可跟踪的待办清单。",
                    kind="stage",
                    level="success",
                    status="completed",
                    public_note="已把任务目标转成可跟踪的待办清单。",
                    evidence_type="todo",
                )
            )
            continue
        if event_type in {"task_run_lifecycle_started", "task_run_executor_started"}:
            entries.append(
                _entry(
                    event,
                    title="处理已开始",
                    body="已开始处理。",
                    kind="stage",
                    level="running",
                    status="running",
                    public_note="已开始处理。",
                    evidence_type="runtime_step",
                )
            )
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
        if event_type in {"executor_observation_recorded", "bounded_observation_recorded", "task_run_lifecycle_event", "task_tool_observation_recorded"}:
            observation = dict(payload.get("observation") or {})
            source = str(observation.get("source") or "").strip()
            summary = public_runtime_progress_summary(observation.get("summary") or "").strip()
            if _is_internal_tool_observation(source=source, text=summary or _observation_payload_result(observation)):
                continue
            if event_type == "task_tool_observation_recorded" and source.startswith("tool:"):
                observation_body = _tool_observation_body(summary or _observation_payload_result(observation))
                if not observation_body:
                    continue
                failed = _observation_text_is_failure(observation_body)
                entries.append(
                    _entry(
                        event,
                        title=_observation_title(source, observation=observation),
                        body=observation_body,
                        kind="observation",
                        level="error" if failed else "success",
                        status="failed" if failed else "completed",
                        tool_name=source.removeprefix("tool:"),
                        public_note=observation_body,
                        agent_brief=observation_body,
                        evidence_type="tool_observation",
                    )
                )
                continue
            if source == "system:agent_todo" or _looks_like_raw_json(summary):
                continue
            if source or summary:
                entries.append(
                    _entry(
                        event,
                        title=_observation_title(source, observation=observation),
                        body=summary,
                        kind="tool" if source.startswith("tool:") else "system",
                        level="error" if observation.get("error") else "success",
                        status="failed" if observation.get("error") else "completed",
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
    meta: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    item = {
        "id": str(event.get("event_id") or f"{event.get('run_id') or event.get('task_run_id')}:{event.get('offset')}"),
        "eventType": str(event.get("event_type") or ""),
        "runId": str(event.get("run_id") or event.get("task_run_id") or ""),
        "taskRunId": _formal_task_run_id(event.get("run_id") or event.get("task_run_id")),
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
    if meta:
        item["meta"] = list(meta)
    return item


def _formal_task_run_id(value: Any) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate.startswith("taskrun:") else ""


def _observations_by_ref(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        if str(event.get("event_type") or "") != "task_tool_observation_recorded":
            continue
        observation = dict(dict(event.get("payload") or {}).get("observation") or {})
        observation_id = str(observation.get("observation_id") or "").strip()
        if observation_id:
            result[observation_id] = observation
    return result


def _observation_payload_result(observation: dict[str, Any]) -> str:
    return str(dict(observation.get("payload") or {}).get("result") or "").strip()


def _is_internal_tool_observation(*, source: str, text: str) -> bool:
    tool_name = str(source or "").strip().removeprefix("tool:")
    if tool_name == "agent_todo":
        return True
    stripped = str(text or "").strip()
    return stripped.startswith("{") and '"plan_id"' in stripped and '"items"' in stripped


def _public_action_state_brief(
    *,
    current_judgment: str = "",
    next_action: str = "",
    completion_status: str = "",
) -> str:
    parts = []
    if current_judgment:
        parts.append(f"判断：{current_judgment}")
    if next_action:
        parts.append(f"下一步：{next_action}")
    if completion_status:
        parts.append(f"状态：{completion_status}")
    return public_runtime_progress_summary("；".join(parts))


def _public_action_state_meta(
    *,
    current_judgment: str = "",
    next_action: str = "",
    completion_status: str = "",
) -> list[dict[str, str]]:
    labels = (
        ("判断", current_judgment),
        ("下一步", next_action),
        ("状态", completion_status),
    )
    return [{"label": label, "value": value} for label, value in labels if value]


def _is_internal_step_only(step: str, *, summary: str, public_note: str, action_brief: str) -> bool:
    if action_brief:
        return False
    if step.startswith(("task_model_action_invocation_started", "task_model_action_waiting")):
        return True
    if step.startswith("task_execution_packet_compiled") and (summary == "已同步最新进展。" or public_note == "已同步最新进展。"):
        return True
    return False


def _looks_like_raw_json(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))


def _tool_observation_body(value: str) -> str:
    text = public_runtime_progress_summary(value).strip()
    if not text:
        return ""
    if not _looks_like_raw_json(text):
        return text
    try:
        data = json.loads(text)
    except Exception:
        return "工具返回了结构化结果，正在根据结果继续。"
    if isinstance(data, dict):
        ok = data.get("ok")
        error = data.get("error") or data.get("message")
        structured_error = data.get("structured_error")
        if isinstance(structured_error, dict):
            error = error or structured_error.get("message") or structured_error.get("error")
        if ok is False or error:
            message = public_runtime_progress_summary(error or "工具调用失败").strip()
            return f"工具返回失败：{message}"
        result = data.get("result") or data.get("summary") or data.get("output")
        if result:
            return public_runtime_progress_summary(result)
        artifact_refs = data.get("artifact_refs")
        if isinstance(artifact_refs, list) and artifact_refs:
            return f"工具返回成功，产生 {len(artifact_refs)} 个产物引用。"
        return "工具返回成功，正在根据结果继续。"
    return "工具返回了结构化结果，正在根据结果继续。"


def _observation_text_is_failure(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if "工具返回失败" in text:
        return True
    if _looks_like_raw_json(text):
        try:
            data = json.loads(text)
        except Exception:
            return False
        if isinstance(data, dict):
            return data.get("ok") is False or bool(data.get("error") or data.get("structured_error"))
    return False


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
    if "observation" in step:
        return "observation"
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


def _observation_title(source: str, *, observation: dict[str, Any] | None = None) -> str:
    if source.startswith("tool:"):
        tool_name = source.removeprefix("tool:").strip()
        return f"工具观察：{tool_name}" if tool_name else "工具观察"
    if dict(observation or {}).get("error"):
        return "观察到失败"
    if source:
        return "观察结果"
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
