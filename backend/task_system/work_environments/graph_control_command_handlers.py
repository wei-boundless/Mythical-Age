from __future__ import annotations

from pathlib import Path
from typing import Any

from task_system.registry.flow_registry import TaskFlowRegistry

from .view_service import TaskEnvironmentViewService


def apply_task_environment_graph_control_command(
    *,
    base_dir: str | Path,
    graph_system: Any | None,
    environment_id: str,
    signal: dict[str, Any],
    graph_control_enabled: bool = True,
) -> dict[str, Any]:
    signal_kind = str(signal.get("signal_kind") or "").strip()
    if not graph_control_enabled:
        return {
            "authority": "task_system.task_environment_graph_control_command",
            "applied": False,
            "signal_status": "pending",
            "reason": "graph_control_disabled",
        }
    detail = TaskEnvironmentViewService(base_dir).task_environment_detail(
        environment_id,
        event_limit=1,
        episode_limit=1,
        context_package_limit=1,
        work_product_limit=1,
    )
    binding = dict(detail.get("graph_node_binding") or {})
    graph_run_id = str(binding.get("graph_run_id") or "").strip()
    if not graph_run_id:
        return {
            "authority": "task_system.task_environment_graph_control_command",
            "applied": False,
            "signal_status": "pending",
            "reason": "no_graph_node_binding",
        }
    if graph_system is None:
        return {
            "authority": "task_system.task_environment_graph_control_command",
            "applied": False,
            "signal_status": "failed",
            "reason": "graph_system_unavailable",
            "graph_run_id": graph_run_id,
        }
    try:
        if signal_kind == "pause_requested":
            result = graph_system.request_graph_run_pause(
                graph_run_id,
                reason=str(signal.get("reason") or ""),
                requested_by=str(signal.get("requested_by") or "user"),
            )
            action = "graph_run_pause"
        elif signal_kind == "resume_requested":
            result = graph_system.request_graph_run_resume(
                graph_run_id,
                reason=str(signal.get("reason") or ""),
                requested_by=str(signal.get("requested_by") or "user"),
            )
            action = "graph_run_resume"
        elif signal_kind in {"stop_requested", "abort_requested"}:
            result = graph_system.request_graph_run_stop(
                graph_run_id,
                reason=str(signal.get("reason") or signal_kind),
                requested_by=str(signal.get("requested_by") or "user"),
            )
            action = "graph_run_stop"
        else:
            return {
                "authority": "task_system.task_environment_graph_control_command",
                "applied": False,
                "signal_status": "pending",
                "reason": "unsupported_graph_control_signal",
                "signal_kind": signal_kind,
                "graph_run_id": graph_run_id,
            }
    except ValueError as exc:
        return {
            "authority": "task_system.task_environment_graph_control_command",
            "applied": False,
            "signal_status": "failed",
            "reason": str(exc),
            "signal_kind": signal_kind,
            "graph_run_id": graph_run_id,
        }
    accepted = bool(dict(result or {}).get("accepted", False))
    return {
        "authority": "task_system.task_environment_graph_control_command",
        "applied": accepted,
        "signal_status": "handled" if accepted else "failed",
        "action": action,
        "signal_kind": signal_kind,
        "graph_run_id": graph_run_id,
        "graph_control": dict(result or {}),
    }


def apply_task_environment_graph_recovery_command(
    *,
    base_dir: str | Path,
    graph_system: Any | None,
    environment_id: str,
    action: str,
    command_id: str = "",
    start_node_ids: tuple[str, ...] = (),
    checkpoint_id: str = "",
    reset_downstream: bool = False,
    dispatch_ready: bool = True,
    max_dispatch_requests: int = 4,
    runtime_settings_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_action = normalized_task_environment_recovery_action(action)
    if not normalized_action:
        return {
            "authority": "task_system.task_environment_graph_recovery_command",
            "applied": False,
            "signal_status": "failed",
            "reason": "unsupported_recovery_action",
            "action": str(action or ""),
            "command_id": command_id,
        }
    detail = TaskEnvironmentViewService(base_dir).task_environment_detail(
        environment_id,
        event_limit=1,
        episode_limit=1,
        context_package_limit=1,
        work_product_limit=1,
    )
    binding = dict(detail.get("graph_node_binding") or {})
    graph_run_id = str(binding.get("graph_run_id") or "").strip()
    node_id = str(binding.get("node_id") or "").strip()
    config_id = str(binding.get("config_id") or "").strip()
    if not graph_run_id or not node_id or not config_id:
        return {
            "authority": "task_system.task_environment_graph_recovery_command",
            "applied": False,
            "signal_status": "pending",
            "reason": "graph_node_binding_incomplete",
            "graph_run_id": graph_run_id,
            "node_id": node_id,
            "config_id": config_id,
            "command_id": command_id,
        }
    if graph_system is None:
        return {
            "authority": "task_system.task_environment_graph_recovery_command",
            "applied": False,
            "signal_status": "failed",
            "reason": "graph_system_unavailable",
            "graph_run_id": graph_run_id,
            "command_id": command_id,
        }
    graph_config = TaskFlowRegistry(base_dir).get_graph_config(config_id)
    if graph_config is None:
        return {
            "authority": "task_system.task_environment_graph_recovery_command",
            "applied": False,
            "signal_status": "failed",
            "reason": "graph_config_not_found",
            "graph_run_id": graph_run_id,
            "config_id": config_id,
            "command_id": command_id,
        }
    try:
        if normalized_action == "resume_graph_run":
            result = graph_system.resume_run(
                graph_config=graph_config,
                graph_run_id=graph_run_id,
                dispatch_ready=dispatch_ready,
                max_requests=max_dispatch_requests,
            )
            return {
                "authority": "task_system.task_environment_graph_recovery_command",
                "applied": True,
                "signal_status": "handled",
                "action": normalized_action,
                "command_id": command_id,
                "graph_run_id": graph_run_id,
                "graph_result": _compact_graph_action_result(
                    result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
                ),
            }
        if normalized_action == "dispatch_ready_graph_nodes":
            dispatch = graph_system.graph_loop.dispatch_ready_and_checkpoint(
                graph_config=graph_config,
                graph_run_id=graph_run_id,
                max_requests=max_dispatch_requests,
            )
            return {
                "authority": "task_system.task_environment_graph_recovery_command",
                "applied": True,
                "signal_status": "handled",
                "action": normalized_action,
                "command_id": command_id,
                "graph_run_id": graph_run_id,
                "dispatch": _compact_graph_loop_start(dispatch),
            }
        if normalized_action == "requeue_graph_node":
            targets = start_node_ids or (node_id,)
            requeue = graph_system.graph_loop.requeue_nodes_and_checkpoint(
                graph_config=graph_config,
                graph_run_id=graph_run_id,
                start_node_ids=targets,
                checkpoint_id=checkpoint_id,
                runtime_settings_patch=dict(runtime_settings_patch or {}),
                reset_downstream=reset_downstream,
            )
            dispatch_payload: dict[str, Any] = {}
            if dispatch_ready:
                dispatch = graph_system.graph_loop.dispatch_ready_and_checkpoint(
                    graph_config=graph_config,
                    graph_run_id=graph_run_id,
                    max_requests=max_dispatch_requests,
                )
                dispatch_payload = _compact_graph_loop_start(dispatch)
            return {
                "authority": "task_system.task_environment_graph_recovery_command",
                "applied": True,
                "signal_status": "handled",
                "action": normalized_action,
                "command_id": command_id,
                "graph_run_id": graph_run_id,
                "node_ids": list(targets),
                "checkpoint_id": str(checkpoint_id or ""),
                "requeue": _compact_graph_loop_start(requeue),
                "dispatch": dispatch_payload,
            }
    except ValueError as exc:
        return {
            "authority": "task_system.task_environment_graph_recovery_command",
            "applied": False,
            "signal_status": "failed",
            "reason": str(exc),
            "action": normalized_action,
            "graph_run_id": graph_run_id,
            "node_id": node_id,
            "command_id": command_id,
        }
    return {
        "authority": "task_system.task_environment_graph_recovery_command",
        "applied": False,
        "signal_status": "failed",
        "reason": "unsupported_recovery_action",
        "action": normalized_action,
        "graph_run_id": graph_run_id,
        "command_id": command_id,
    }


def normalized_task_environment_recovery_action(value: str) -> str:
    action = str(value or "").strip()
    aliases = {
        "resume": "resume_graph_run",
        "resume_graph": "resume_graph_run",
        "requeue": "requeue_graph_node",
        "requeue_node": "requeue_graph_node",
        "dispatch": "dispatch_ready_graph_nodes",
        "dispatch_ready": "dispatch_ready_graph_nodes",
    }
    action = aliases.get(action, action)
    if action in {"resume_graph_run", "requeue_graph_node", "dispatch_ready_graph_nodes"}:
        return action
    return ""


def recovery_action_signal_kind(action: str) -> str:
    if action == "requeue_graph_node":
        return "replan_requested"
    return "resume_requested"


def _compact_graph_loop_start(value: object) -> dict[str, Any]:
    payload = value.to_dict() if hasattr(value, "to_dict") else dict(value or {}) if isinstance(value, dict) else {}
    loop_state = dict(payload.get("graph_loop_state") or {})
    if not loop_state and hasattr(value, "loop_state"):
        state = getattr(value, "loop_state")
        loop_state = state.to_dict() if hasattr(state, "to_dict") else {}
    node_work_orders = list(payload.get("node_work_orders") or [])
    if not node_work_orders and hasattr(value, "node_work_orders"):
        node_work_orders = [
            item.to_dict() if hasattr(item, "to_dict") else dict(item or {})
            for item in list(getattr(value, "node_work_orders") or [])
        ]
    checkpoint = dict(payload.get("checkpoint") or getattr(value, "checkpoint", {}) or {})
    events = list(payload.get("events") or getattr(value, "events", ()) or ())
    return {
        "authority": "task_system.task_environment_graph_recovery_command.graph_loop_start_summary",
        "graph_loop_state": _compact_graph_loop_state(loop_state),
        "checkpoint_id": str(checkpoint.get("checkpoint_id") or checkpoint.get("id") or ""),
        "node_work_orders": [_compact_work_order(item) for item in node_work_orders],
        "work_order_count": len(node_work_orders),
        "event_count": len(events),
    }


def _compact_graph_action_result(payload: dict[str, Any]) -> dict[str, Any]:
    loop_state = dict(payload.get("graph_loop_state") or {})
    return {
        "authority": str(payload.get("authority") or "task_system.task_environment_graph_recovery_command.graph_result_summary"),
        "graph_run_id": str(payload.get("graph_run_id") or ""),
        "resumed": bool(payload.get("resumed") is True),
        "reason": str(payload.get("reason") or ""),
        "graph_loop_state": _compact_graph_loop_state(loop_state),
        "active_work_order_count": len(list(payload.get("active_work_orders") or [])),
        "node_work_order_count": len(list(payload.get("node_work_orders") or [])),
        "event_count": len(list(payload.get("events") or [])),
    }


def _compact_graph_loop_state(loop_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(loop_state.get("status") or ""),
        "terminal_reason": str(loop_state.get("terminal_reason") or ""),
        "ready_node_ids": [str(item) for item in list(loop_state.get("ready_node_ids") or []) if str(item)],
        "running_node_ids": [str(item) for item in list(loop_state.get("running_node_ids") or []) if str(item)],
        "blocked_node_ids": [str(item) for item in list(loop_state.get("blocked_node_ids") or []) if str(item)],
        "failed_node_ids": [str(item) for item in list(loop_state.get("failed_node_ids") or []) if str(item)],
    }


def _compact_work_order(value: object) -> dict[str, Any]:
    row = value if isinstance(value, dict) else value.to_dict() if hasattr(value, "to_dict") else {}
    payload = dict(row or {})
    return {
        key: payload.get(key)
        for key in ("work_order_id", "node_id", "graph_run_id", "task_run_id", "executor_type", "agent_profile_id")
        if payload.get(key) not in (None, "", [], {})
    }
