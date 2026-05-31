from __future__ import annotations

from typing import Any

from harness.runtime.public_progress import public_runtime_progress_summary

from .contract import build_envelope, build_navigation_target, build_task_detail_envelope, monitor_revision
from .lifecycle import (
    BLOCKED_TASK_RUN_STATUSES,
    COMPLETED_TASK_RUN_STATUSES,
    FAILED_TASK_RUN_STATUSES,
    GLOBAL_MONITOR_BUCKETS,
    KNOWN_TASK_RUN_STATUSES,
    RUNNING_TASK_RUN_STATUSES,
    TERMINAL_TASK_RUN_STATUSES,
    WAITING_TASK_RUN_STATUSES,
    ended_at,
    is_terminal_status,
    monitor_bucket,
    runtime_control,
    task_lifecycle,
)


class RuntimeMonitorProjector:
    def __init__(self, event_log: Any, *, freshness_seconds: float = 5 * 60.0, resource_resolver: Any | None = None) -> None:
        self.event_log = event_log
        self.freshness_seconds = float(freshness_seconds)
        self.resource_resolver = resource_resolver

    def project_task_run(self, task_run: Any, *, now: float, include_runtime_details: bool = True) -> dict[str, Any]:
        current_time = float(now)
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        events = self._recent_events(task_run_id, limit=240) if include_runtime_details else []
        latest_event = events[-1].to_dict() if events else {}
        latest_step = self._latest_step_summary(events) if include_runtime_details else self._latest_step_from_diagnostics(diagnostics)
        latest_interaction_turn_id = _latest_interaction_turn_id(events, diagnostics=diagnostics) if include_runtime_details else str(diagnostics.get("latest_interaction_turn_id") or diagnostics.get("turn_id") or "")
        event_count = self._event_count(task_run_id, events=events) if include_runtime_details else int(diagnostics.get("event_count") or 0)
        created_at = float(getattr(task_run, "created_at", 0.0) or 0.0)
        updated_at = float(getattr(task_run, "updated_at", 0.0) or 0.0)
        latest_event_at = float(latest_event.get("created_at") or updated_at or 0.0)
        last_activity_at = max(created_at, updated_at, latest_event_at)
        last_activity_age_seconds = max(0.0, current_time - last_activity_at) if last_activity_at else 0.0
        status = str(getattr(task_run, "status", "") or "")
        control = runtime_control(diagnostics)
        control_state = str(control.get("state") or "")
        terminal = is_terminal_status(status)
        stale = control_state != "paused" and status in RUNNING_TASK_RUN_STATUSES | {"waiting_executor"} and (
            not last_activity_at or last_activity_age_seconds > self.freshness_seconds
        )
        action_required = status in {"waiting_approval"} | BLOCKED_TASK_RUN_STATUSES or control_state == "paused"
        route = self._route(task_run, diagnostics)
        diagnostic_reasons = self._diagnostic_reasons(
            task_run=task_run,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            latest_event=latest_event,
            last_activity_at=last_activity_at,
            route=route,
            stale=stale,
            control_state=control_state,
        )
        lifecycle = "stale" if diagnostic_reasons else task_lifecycle(status, stale=stale, action_required=action_required, control_state=control_state)
        bucket = "diagnostics" if diagnostic_reasons else monitor_bucket(lifecycle)
        resource_class = "dynamic" if bucket == "running" and not terminal else "static"
        ended = ended_at(status=status, updated_at=updated_at, last_activity_at=last_activity_at, resource_class=resource_class)
        duration_end_at = current_time if resource_class == "dynamic" else ended
        duration_seconds = max(0.0, duration_end_at - created_at) if created_at and duration_end_at else 0.0
        title = self._display_title(task_run, diagnostics, lifecycle=lifecycle)
        summary = public_runtime_progress_summary(
            latest_step.get("public_progress_note")
            or latest_step.get("summary")
            or latest_step.get("next_action")
            or latest_step.get("current_judgment")
            or diagnostics.get("public_progress_note")
            or diagnostics.get("latest_public_progress_note")
            or diagnostics.get("latest_step_summary")
            or diagnostics.get("summary")
            or ""
        )
        diagnostic_summary = self._diagnostic_summary(
            diagnostic_reasons=diagnostic_reasons,
            latest_step=latest_step,
            last_activity_age_seconds=last_activity_age_seconds,
        )
        if diagnostic_summary:
            summary = diagnostic_summary
        latest_public_progress_note = summary if diagnostic_summary else public_runtime_progress_summary(latest_step.get("public_progress_note") or summary)
        agent_brief = public_runtime_progress_summary(latest_step.get("agent_brief_output") or diagnostics.get("agent_brief_output") or "")
        artifact_refs = _dedupe_artifact_refs(
            [
                *[dict(item) for item in list(diagnostics.get("artifact_refs") or []) if isinstance(item, dict)],
                *(_artifact_refs_from_event_log(self.event_log, task_run_id) if include_runtime_details else []),
            ]
        )
        graph_id = str(route.get("graph_id") or "")
        graph_run_id = str(diagnostics.get("graph_run_id") or "")
        graph_harness_config_id = str(diagnostics.get("graph_harness_config_id") or "")
        kind = self._kind_from_route(route)
        task_instance_id = graph_run_id if kind == "task_graph" and graph_run_id else task_run_id
        resource_refs = self._resource_refs(
            task_run_id=task_run_id,
            session_id=str(getattr(task_run, "session_id", "") or ""),
            graph_run_id=graph_run_id,
            graph_harness_config_id=graph_harness_config_id,
            artifact_refs=artifact_refs,
        )
        graph_monitor = self._graph_monitor(graph_run_id, graph_harness_config_id) if include_runtime_details and kind == "task_graph" else None
        graph_status = self._graph_status(graph_monitor, graph_id=graph_id, graph_run_id=graph_run_id) if kind == "task_graph" else None
        child_runtime_refs = self._child_runtime_refs(graph_monitor) if include_runtime_details and kind == "task_graph" else []
        latest_progress = {
            "tool_status": str(latest_step.get("tool_status") or diagnostics.get("latest_tool_status") or ""),
            "observation": public_runtime_progress_summary(latest_step.get("observation") or diagnostics.get("latest_observation") or ""),
            "current_judgment": public_runtime_progress_summary(latest_step.get("current_judgment") or diagnostics.get("latest_current_judgment") or ""),
            "next_action": public_runtime_progress_summary(latest_step.get("next_action") or diagnostics.get("latest_next_action") or ""),
            "completion_status": public_runtime_progress_summary(latest_step.get("completion_status") or diagnostics.get("latest_completion_status") or ""),
            "open_risks": list(latest_step.get("open_risks") or dict(diagnostics.get("latest_public_action_state") or {}).get("open_risks") or []),
            "evidence_refs": list(latest_step.get("evidence_refs") or dict(diagnostics.get("latest_public_action_state") or {}).get("evidence_refs") or []),
            "summary": summary,
            "agent_brief": agent_brief,
        }
        navigation_target = build_navigation_target(
            kind=kind,
            task_instance_id=task_instance_id,
            task_run_id=task_run_id,
            session_id=str(getattr(task_run, "session_id", "") or ""),
            graph_run_id=graph_run_id,
            graph_id=graph_id,
            focus_node_id=str((graph_status or {}).get("active_node_id") or diagnostics.get("active_node_id") or diagnostics.get("node_id") or ""),
        )
        has_graph_run = bool(graph_run_id or graph_harness_config_id)
        item = {
            "task_run_id": task_run_id,
            "session_id": str(getattr(task_run, "session_id", "") or ""),
            "task_id": str(getattr(task_run, "task_id", "") or ""),
            "execution_runtime_kind": str(getattr(task_run, "execution_runtime_kind", "") or ""),
            "task_instance_id": task_instance_id,
            "root_task_run_id": task_run_id,
            "kind": kind,
            "title": title,
            "status": status,
            "terminal_reason": str(getattr(task_run, "terminal_reason", "") or ""),
            "lifecycle": lifecycle,
            "bucket": bucket,
            "resource_class": resource_class,
            "started_at": created_at,
            "created_at": created_at,
            "updated_at": updated_at,
            "ended_at": ended,
            "duration_seconds": duration_seconds,
            "elapsed_seconds": duration_seconds,
            "runtime_seconds": duration_seconds,
            "runtime_end_at": ended,
            "last_activity_at": last_activity_at,
            "last_activity_age_seconds": last_activity_age_seconds,
            "action_required": action_required,
            "terminal": terminal,
            "stale": bool(stale or diagnostic_reasons),
            "diagnostic_reasons": diagnostic_reasons,
            "runtime_control": control,
            "control_state": control_state,
            "is_live": resource_class == "dynamic",
            "summary": summary,
            "latest_progress": latest_progress,
            "latest_event_type": str(latest_event.get("event_type") or ""),
            "latest_event_at": latest_event_at,
            "latest_event": latest_event,
            "latest_step": latest_step,
            "latest_step_summary": summary,
            "latest_public_progress_note": latest_public_progress_note,
            "latest_interaction_turn_id": latest_interaction_turn_id,
            "agent_brief_output": agent_brief,
            "latest_step_name": str(latest_step.get("step") or diagnostics.get("latest_step") or ""),
            "latest_step_status": str(latest_step.get("status") or diagnostics.get("latest_step_status") or ""),
            "artifact_count": len(artifact_refs),
            "artifact_refs": artifact_refs[:10],
            "resource_refs": resource_refs,
            "primary_resource_ref": resource_refs[0] if resource_refs else None,
            "graph_status": graph_status,
            "child_runtime_refs": child_runtime_refs,
            "navigation_target": navigation_target,
            "pending_user_steer_count": int(diagnostics.get("pending_user_steer_count") or 0),
            "latest_user_steer_ref": str(diagnostics.get("latest_user_steer_ref") or ""),
            "active_contract_revision_count": int(diagnostics.get("active_contract_revision_count") or 0),
            "latest_contract_revision_ref": str(diagnostics.get("latest_contract_revision_ref") or ""),
            "executor_epoch": int(diagnostics.get("executor_epoch") or 0),
            "next_invocation_index": int(diagnostics.get("next_invocation_index") or 0),
            "route": route,
            "graph_run_id": graph_run_id,
            "graph_harness_config_id": graph_harness_config_id,
            "graph_id": graph_id,
            "active_node_id": str((graph_status or {}).get("active_node_id") or diagnostics.get("active_node_id") or diagnostics.get("node_id") or ""),
            "project_id": str(diagnostics.get("project_id") or ""),
            "project_title": self._public_text(diagnostics.get("project_title")),
            "project_runtime_status": None,
            "has_graph_run": has_graph_run,
            "event_count": event_count,
            "authority": "runtime_monitor.v1.item",
        }
        return item

    def build_global_monitor(self, task_runs: list[Any], *, now: float, limit: int) -> dict[str, Any]:
        items = [
            self.project_task_run(task_run, now=now, include_runtime_details=False)
            for task_run in sorted(task_runs, key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0), reverse=True)
            if not self._is_internal_child_run(task_run)
        ]
        return build_envelope(scope="global", items=items, now=now, limit=limit)

    def build_session_monitor(self, session_id: str, task_runs: list[Any], *, now: float, limit: int = 20) -> dict[str, Any]:
        items = [
            self.project_task_run(item, now=now, include_runtime_details=False)
            for item in sorted(task_runs, key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0), reverse=True)
            if not self._is_internal_child_run(item)
        ]
        active_items = [item for item in items if item.get("bucket") in {"running", "diagnostics"}]
        visible = active_items[: max(1, min(int(limit or 20), 100))]
        latest = items[0] if items else None
        active = visible[0] if visible else None
        return build_envelope(
            scope="session",
            items=visible,
            now=now,
            limit=limit,
            selected=active,
            extra={
                "session_id": session_id,
                "active_task_run_id": str(active.get("task_run_id") or "") if active else "",
                "latest_task_run_id": str(latest.get("task_run_id") or "") if latest else "",
                "task_run_count": len(items),
                "monitor": active,
            },
        )

    def build_task_monitor(self, task_run: Any, *, now: float) -> dict[str, Any]:
        return build_task_detail_envelope(item=self.project_task_run(task_run, now=now), now=now)

    def _recent_events(self, task_run_id: str, *, limit: int) -> list[Any]:
        reader = getattr(self.event_log, "list_recent_events", None)
        if callable(reader):
            try:
                return list(reader(task_run_id, limit=limit))
            except TypeError:
                return list(reader(task_run_id))
            except Exception:
                return []
        return []

    def _event_count(self, task_run_id: str, *, events: list[Any]) -> int:
        estimator = getattr(self.event_log, "estimated_event_count", None)
        if callable(estimator):
            try:
                return int(estimator(task_run_id))
            except Exception:
                return len(events)
        counter = getattr(self.event_log, "event_count", None)
        if callable(counter):
            try:
                return int(counter(task_run_id))
            except Exception:
                return len(events)
        return len(events)

    def _route(self, task_run: Any, diagnostics: dict[str, Any]) -> dict[str, str]:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        session_id = str(getattr(task_run, "session_id", "") or "")
        task_id = str(getattr(task_run, "task_id", "") or "")
        execution_runtime_kind = str(getattr(task_run, "execution_runtime_kind", "") or "")
        graph_id = str(diagnostics.get("graph_id") or diagnostics.get("task_graph_id") or "")
        graph_run_id = str(diagnostics.get("graph_run_id") or "")
        graph_harness_config_id = str(diagnostics.get("graph_harness_config_id") or "")
        if graph_run_id or graph_harness_config_id:
            kind = "task_graph_run"
        elif _is_chat_scoped(task_run_id=task_run_id, task_id=task_id):
            kind = "chat_turn_runtime"
        elif execution_runtime_kind in {"single_agent_task", "subagent_task"}:
            kind = "agent_runtime_run"
        else:
            kind = "chat_turn_runtime"
        return {
            "kind": kind,
            "session_id": session_id,
            "task_run_id": task_run_id,
            "graph_id": graph_id,
            "graph_run_id": graph_run_id,
            "graph_harness_config_id": graph_harness_config_id,
        }

    def _kind_from_route(self, route: dict[str, str]) -> str:
        route_kind = str(route.get("kind") or "")
        if route_kind == "task_graph_run":
            return "task_graph"
        if route_kind == "agent_runtime_run":
            return "agent_run"
        return "chat_turn"

    def _diagnostic_reasons(
        self,
        *,
        task_run: Any,
        status: str,
        created_at: float,
        updated_at: float,
        latest_event: dict[str, Any],
        last_activity_at: float,
        route: dict[str, str],
        stale: bool,
        control_state: str = "",
    ) -> list[str]:
        reasons: list[str] = []
        if stale:
            reasons.append("stale_runtime_activity")
        if not created_at or not updated_at or not last_activity_at:
            reasons.append("missing_runtime_time")
        if status not in KNOWN_TASK_RUN_STATUSES:
            reasons.append("unknown_task_status")
        kind = str(route.get("kind") or "")
        if not route.get("task_run_id"):
            reasons.append("missing_route_task_run_id")
        if kind in {"chat_turn_runtime", "agent_runtime_run"} and not route.get("session_id"):
            reasons.append("missing_route_session_id")
        if kind == "task_graph_run" and not route.get("graph_id"):
            reasons.append("missing_route_graph_id")
        event_type = str(latest_event.get("event_type") or "")
        if status in TERMINAL_TASK_RUN_STATUSES and event_type.startswith("task_run_lifecycle_waiting"):
            reasons.append("terminal_status_with_waiting_event")
        if status in RUNNING_TASK_RUN_STATUSES and str(getattr(task_run, "terminal_reason", "") or "") in TERMINAL_TASK_RUN_STATUSES:
            reasons.append("running_status_with_terminal_reason")
        if control_state and control_state not in {"running", "pause_requested", "paused", "resume_requested", "stop_requested", "stopped", "replan_requested", "interrupted_for_replan"}:
            reasons.append("unknown_runtime_control_state")
        return reasons

    def _is_internal_child_run(self, task_run: Any) -> bool:
        task_id = str(getattr(task_run, "task_id", "") or "")
        contract_ref = str(getattr(task_run, "task_contract_ref", "") or "")
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        if task_id.startswith("task_graph.graph_module.") or contract_ref.startswith("task_graph.graph_module."):
            return True
        return bool(
            diagnostics.get("coordination_stage_id")
            or diagnostics.get("stage_request_id")
            or diagnostics.get("stage_idempotency_key")
            or diagnostics.get("graph_node_id")
            or diagnostics.get("graph_work_order_id")
        )

    def _display_title(self, task_run: Any, diagnostics: dict[str, Any], *, lifecycle: str) -> str:
        for key in ("title", "task_graph_title", "project_title", "goal", "task_goal"):
            value = self._public_text(diagnostics.get(key))
            if value:
                return value
        if str(getattr(task_run, "execution_runtime_kind", "") or "") == "single_agent_task":
            return "Agent 运行"
        if lifecycle == "completed":
            return "会话运行已完成"
        if lifecycle == "failed":
            return "会话运行失败"
        if lifecycle == "action_required":
            return "会话运行等待处理"
        if lifecycle == "paused":
            return "会话运行已暂停"
        if lifecycle == "stale":
            return "运行状态需诊断"
        return "会话运行中"

    def _public_text(self, value: Any) -> str:
        candidate = str(value or "").strip()
        if not candidate or _looks_internal_identifier(candidate):
            return ""
        return candidate

    def _latest_step_summary(self, events: list[Any]) -> dict[str, Any]:
        for event in reversed(events):
            if str(getattr(event, "event_type", "") or "") != "step_summary_recorded":
                continue
            payload = dict(getattr(event, "payload", {}) or {})
            public_action_state = dict(payload.get("public_action_state") or {})
            return {
                "step": str(payload.get("step") or ""),
                "status": str(payload.get("status") or ""),
                "summary": public_runtime_progress_summary(payload.get("summary") or ""),
                "public_progress_note": public_runtime_progress_summary(payload.get("public_progress_note") or payload.get("summary") or ""),
                "agent_brief_output": public_runtime_progress_summary(payload.get("agent_brief_output") or ""),
                "tool_status": public_runtime_progress_summary(payload.get("tool_status") or ""),
                "observation": public_runtime_progress_summary(payload.get("observation") or ""),
                "current_judgment": public_runtime_progress_summary(
                    payload.get("current_judgment")
                    or public_action_state.get("current_judgment")
                    or ""
                ),
                "next_action": public_runtime_progress_summary(payload.get("next_action") or public_action_state.get("next_action") or ""),
                "completion_status": public_runtime_progress_summary(
                    payload.get("completion_status")
                    or public_action_state.get("completion_status")
                    or ""
                ),
                "open_risks": list(public_action_state.get("open_risks") or []),
                "evidence_refs": list(public_action_state.get("evidence_refs") or []),
                "presentation_source": str(payload.get("presentation_source") or ""),
                "event_id": str(getattr(event, "event_id", "") or ""),
                "offset": int(getattr(event, "offset", -1) or -1),
                "created_at": float(getattr(event, "created_at", 0.0) or 0.0),
            }
        return {}

    def _latest_step_from_diagnostics(self, diagnostics: dict[str, Any]) -> dict[str, Any]:
        return {
            "step": str(diagnostics.get("latest_step") or ""),
            "status": str(diagnostics.get("latest_step_status") or ""),
            "summary": public_runtime_progress_summary(diagnostics.get("latest_step_summary") or diagnostics.get("summary") or ""),
            "public_progress_note": public_runtime_progress_summary(
                diagnostics.get("latest_public_progress_note")
                or diagnostics.get("public_progress_note")
                or diagnostics.get("latest_step_summary")
                or diagnostics.get("summary")
                or ""
            ),
            "agent_brief_output": public_runtime_progress_summary(diagnostics.get("agent_brief_output") or ""),
            "tool_status": public_runtime_progress_summary(diagnostics.get("latest_tool_status") or ""),
            "observation": public_runtime_progress_summary(diagnostics.get("latest_observation") or ""),
            "current_judgment": public_runtime_progress_summary(diagnostics.get("latest_current_judgment") or ""),
            "next_action": public_runtime_progress_summary(diagnostics.get("latest_next_action") or ""),
            "completion_status": public_runtime_progress_summary(diagnostics.get("latest_completion_status") or ""),
            "presentation_source": "diagnostics",
            "event_id": "",
            "offset": -1,
            "created_at": float(diagnostics.get("latest_step_at") or diagnostics.get("latest_event_at") or 0.0),
        }

    def _diagnostic_summary(
        self,
        *,
        diagnostic_reasons: list[str],
        latest_step: dict[str, Any],
        last_activity_age_seconds: float,
    ) -> str:
        if "stale_runtime_activity" not in diagnostic_reasons:
            return ""
        elapsed = _human_duration(last_activity_age_seconds)
        step = str(latest_step.get("step") or "")
        if step.startswith("model_action_waiting") or step.startswith("task_model_action_waiting"):
            return f"模型响应已超过{elapsed}没有更新，可能是模型服务或网络异常；当前处理已进入诊断状态。"
        return f"处理已超过{elapsed}没有新的运行事件；当前处理已进入诊断状态。"

    def _resource_refs(
        self,
        *,
        task_run_id: str,
        session_id: str,
        graph_run_id: str,
        graph_harness_config_id: str,
        artifact_refs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        resolver = self.resource_resolver
        if resolver is None:
            return []
        refs = [resolver.task_run_ref(task_run_id)]
        if session_id:
            refs.append(resolver.session_ref(session_id))
        if graph_run_id:
            refs.append(resolver.graph_run_ref(graph_run_id))
        if graph_harness_config_id:
            refs.append(resolver.graph_config_ref(graph_harness_config_id))
        refs.extend(resolver.artifact_refs(artifact_refs))
        return refs

    def _graph_monitor(self, graph_run_id: str, graph_harness_config_id: str) -> dict[str, Any] | None:
        resolver = self.resource_resolver
        if resolver is None or not graph_run_id:
            return None
        return resolver.graph_monitor(graph_run_id, graph_harness_config_id)

    def _graph_status(self, monitor: dict[str, Any] | None, *, graph_id: str, graph_run_id: str) -> dict[str, Any]:
        payload = dict(monitor or {})
        graph_config = dict(payload.get("graph_harness_config") or {})
        loop_state = dict(payload.get("graph_loop_state") or {})
        node_statuses = _node_statuses_from_monitor(payload)
        active_node_id = _active_node_id(loop_state, node_statuses)
        active_node = next((item for item in node_statuses if item.get("node_id") == active_node_id), {})
        status = str(loop_state.get("status") or dict(payload.get("task_run") or {}).get("status") or "").strip()
        running_count = sum(1 for item in node_statuses if item.get("status") == "running")
        completed_count = sum(1 for item in node_statuses if item.get("status") in {"completed", "success", "succeeded"})
        failed_count = sum(1 for item in node_statuses if item.get("status") in {"failed", "error"})
        blocked_count = sum(1 for item in node_statuses if item.get("status") in {"blocked", "waiting_human_gate", "waiting_approval"})
        ready_ids = [str(item) for item in list(loop_state.get("ready_node_ids") or [])]
        return {
            "graph_id": graph_id or str(graph_config.get("graph_id") or ""),
            "graph_run_id": graph_run_id,
            "graph_title": self._public_text(graph_config.get("graph_title")) or "任务图",
            "graph_lifecycle": _graph_lifecycle(status, failed_count=failed_count, blocked_count=blocked_count),
            "active_node_id": active_node_id,
            "active_node_label": str(active_node.get("node_label") or active_node.get("node_id") or ""),
            "active_node_status": str(active_node.get("status") or ""),
            "ready_node_count": len(ready_ids),
            "running_node_count": running_count,
            "completed_node_count": completed_count,
            "failed_node_count": failed_count,
            "blocked_node_count": blocked_count,
            "current_stage_summary": _graph_stage_summary(active_node=active_node, status=status, ready_count=len(ready_ids), running_count=running_count),
            "next_action_label": _graph_next_action(status=status, ready_count=len(ready_ids), failed_count=failed_count, blocked_count=blocked_count),
            "node_statuses": node_statuses,
        }

    def _child_runtime_refs(self, monitor: dict[str, Any] | None) -> list[dict[str, Any]]:
        payload = dict(monitor or {})
        refs: list[dict[str, Any]] = []
        for item in list(payload.get("node_runtime_views") or []):
            view = dict(item or {})
            task_run_id = str(view.get("node_executor_task_run_id") or "")
            if not task_run_id:
                continue
            task_monitor = dict(view.get("node_executor_task_run_monitor") or {})
            refs.append(
                {
                    "task_run_id": task_run_id,
                    "node_id": str(view.get("node_id") or ""),
                    "node_label": str(view.get("node_label") or view.get("node_id") or ""),
                    "runtime_kind": "agent_runtime",
                    "lifecycle": str(task_monitor.get("lifecycle") or view.get("status") or ""),
                    "latest_progress": dict(task_monitor.get("latest_progress") or {}),
                    "artifact_refs": list(view.get("artifact_refs") or task_monitor.get("artifact_refs") or []),
                }
            )
        return refs

def _is_chat_scoped(*, task_run_id: str, task_id: str) -> bool:
    return task_run_id.startswith("turnrun:") or task_run_id.startswith("taskrun:turn:") or task_id.startswith("turn:") or task_id.startswith("task:turn:")


def _latest_interaction_turn_id(events: list[Any], *, diagnostics: dict[str, Any]) -> str:
    for event in reversed(events):
        event_type = str(getattr(event, "event_type", "") or "")
        payload = dict(getattr(event, "payload", {}) or {})
        refs = dict(getattr(event, "refs", {}) or {})
        if event_type in {
            "user_work_instruction_recorded",
            "active_task_steer_recorded",
            "task_run_resume_requested",
            "task_run_executor_scheduled",
            "step_summary_recorded",
            "task_run_checkout_created",
        }:
            steer = dict(payload.get("steer") or {})
            submission = dict(payload.get("submission") or {})
            for candidate in (
                refs.get("turn_ref"),
                payload.get("turn_id"),
                submission.get("turn_id"),
                steer.get("turn_id"),
            ):
                turn_id = _valid_turn_ref(candidate)
                if turn_id:
                    return turn_id
    return _valid_turn_ref(diagnostics.get("latest_interaction_turn_id"))


def _valid_turn_ref(value: Any) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate.startswith("turn:") else ""


def _human_duration(seconds: float) -> str:
    safe = max(0, int(float(seconds or 0.0)))
    if safe >= 3600:
        hours = safe // 3600
        minutes = (safe % 3600) // 60
        return f"{hours}小时{minutes}分钟" if minutes else f"{hours}小时"
    if safe >= 60:
        minutes = safe // 60
        remain = safe % 60
        return f"{minutes}分钟{remain}秒" if remain else f"{minutes}分钟"
    return f"{safe}秒"


def _looks_internal_identifier(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("task:", "taskrun:", "turn:", "turnrun:", "session:", "taskinst:", "coordrun:", "grun:"))


def _artifact_refs_from_events(events: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for event in events:
        payload = _event_payload(event)
        observation = dict(payload.get("observation") or {})
        refs.extend(_artifact_refs_from_payload(dict(observation.get("payload") or {})))
    return _dedupe_artifact_refs(refs)


def _artifact_refs_from_event_log(event_log: Any, task_run_id: str) -> list[dict[str, Any]]:
    reader = getattr(event_log, "list_event_window", None)
    if callable(reader):
        try:
            return _artifact_refs_from_events(list(reader(task_run_id, limit=240, include_payloads=True)))
        except Exception:
            pass
    reader = getattr(event_log, "list_events", None)
    if callable(reader):
        try:
            return _artifact_refs_from_events(list(reader(task_run_id))[-240:])
        except Exception:
            pass
    return []


def _event_payload(event: Any) -> dict[str, Any]:
    if hasattr(event, "payload"):
        payload = getattr(event, "payload", None)
    elif isinstance(event, dict):
        payload = event.get("payload")
    else:
        payload = None
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _artifact_refs_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    envelope = dict(payload.get("result_envelope") or {})
    structured = dict(payload.get("structured_payload") or envelope.get("structured_payload") or {})
    return [
        dict(item)
        for item in list(payload.get("artifact_refs") or envelope.get("artifact_refs") or structured.get("artifact_refs") or [])
        if isinstance(item, dict)
    ]


def _dedupe_artifact_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        key = str(ref.get("path") or ref.get("src") or ref.get("absolute_path") or ref)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(dict(ref))
    return result


def _node_statuses_from_monitor(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    config_nodes = {
        str(dict(node).get("node_id") or ""): dict(node)
        for node in list(dict(monitor.get("graph_harness_config") or {}).get("nodes") or [])
        if isinstance(node, dict)
    }
    result: list[dict[str, Any]] = []
    for view in list(monitor.get("node_runtime_views") or []):
        payload = dict(view or {})
        node_id = str(payload.get("node_id") or "")
        node_config = config_nodes.get(node_id, {})
        result.append(
            {
                "node_id": node_id,
                "node_label": str(node_config.get("title") or node_config.get("label") or payload.get("node_label") or node_id),
                "status": str(payload.get("status") or ""),
                "executor_type": str(payload.get("executor_type") or ""),
                "task_run_id": str(payload.get("node_executor_task_run_id") or ""),
            }
        )
    if result:
        return result
    loop_state = dict(monitor.get("graph_loop_state") or {})
    node_states = dict(loop_state.get("node_states") or {})
    for node_id, node_state in node_states.items():
        payload = dict(node_state or {})
        node_config = config_nodes.get(str(node_id), {})
        result.append(
            {
                "node_id": str(node_id),
                "node_label": str(node_config.get("title") or node_config.get("label") or node_id),
                "status": str(payload.get("status") or ""),
                "executor_type": str(payload.get("executor_type") or ""),
                "task_run_id": "",
            }
        )
    return result


def _active_node_id(loop_state: dict[str, Any], node_statuses: list[dict[str, Any]]) -> str:
    for key in ("active_node_id", "current_node_id"):
        value = str(loop_state.get(key) or "").strip()
        if value:
            return value
    for status in ("running", "waiting_approval", "blocked"):
        for item in node_statuses:
            if str(item.get("status") or "") == status:
                return str(item.get("node_id") or "")
    ready = list(loop_state.get("ready_node_ids") or [])
    return str(ready[0]) if ready else ""


def _graph_lifecycle(status: str, *, failed_count: int, blocked_count: int) -> str:
    normalized = status.lower()
    if normalized in {"completed", "success", "succeeded"}:
        return "completed"
    if normalized in {"failed", "error"} or failed_count:
        return "failed"
    if blocked_count:
        return "action_required"
    if normalized in {"waiting", "waiting_executor", "waiting_approval"}:
        return "waiting"
    if normalized in {"created", "running"}:
        return "running"
    return normalized or "stale"


def _graph_stage_summary(*, active_node: dict[str, Any], status: str, ready_count: int, running_count: int) -> str:
    node_label = str(active_node.get("node_label") or active_node.get("node_id") or "").strip()
    if node_label and running_count:
        return f"正在执行节点：{node_label}"
    if ready_count:
        return f"有 {ready_count} 个节点等待执行"
    if status in {"completed", "success", "succeeded"}:
        return "任务图已完成"
    if status in {"failed", "error"}:
        return "任务图执行失败"
    return "任务图状态已同步"


def _graph_next_action(*, status: str, ready_count: int, failed_count: int, blocked_count: int) -> str:
    if failed_count:
        return "查看问题"
    if blocked_count:
        return "等待审批"
    if ready_count:
        return "继续执行"
    if status in {"completed", "success", "succeeded"}:
        return "已完成"
    return "等待进展"
