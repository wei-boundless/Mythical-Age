from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from task_system.episodes import EpisodeRepository
from task_system.graph_bindings.repository import GraphNodeTaskBindingRepository
from task_system.work_products import WorkProductRepository

from .repository import TaskEnvironmentRepository


class TaskEnvironmentViewService:
    authority = "task_system.task_environment_view_service"

    def __init__(self, base_dir: str | Path) -> None:
        self.task_repository = TaskEnvironmentRepository(base_dir)
        self.episode_repository = EpisodeRepository(base_dir)
        self.work_product_repository = WorkProductRepository(base_dir)
        self.graph_binding_repository = GraphNodeTaskBindingRepository(base_dir)

    def list_task_environments(
        self,
        *,
        status: str = "",
        task_kind: str = "",
        project_id: str = "",
        caller_kind: str = "",
        limit: int = 200,
    ) -> dict[str, Any]:
        environments = self.task_repository.list_task_environments(
            status=status,
            task_kind=task_kind,
            project_id=project_id,
            caller_kind=caller_kind,
            limit=limit,
        )
        items = [self._environment_list_item(item) for item in environments]
        return {
            "authority": "task_system.task_environment_view.list",
            "task_environments": items,
            "summary": {
                "task_environment_count": len(items),
                "status": status,
                "task_kind": task_kind,
                "project_id": project_id,
                "caller_kind": caller_kind,
            },
        }

    def list_resumable_task_environments(self, *, limit: int = 200) -> dict[str, Any]:
        environments = self.task_repository.list_resumable(limit=limit)
        items: list[dict[str, Any]] = []
        for environment in environments:
            item = self._environment_list_item(environment)
            binding = dict(item.get("graph_node_binding") or {})
            pending_signals = self.task_repository.list_control_signals(
                environment.task_environment_id,
                status="pending",
                limit=10,
            )
            leases = self.task_repository.list_leases(environment.task_environment_id, limit=5)
            item["pending_control_signals"] = [signal.to_dict() for signal in pending_signals]
            item["latest_leases"] = [lease.to_dict() for lease in leases]
            item["recovery_hint"] = _recovery_hint(environment.to_dict(), binding)
            item["activity_state"] = _activity_state(environment.to_dict(), [lease.to_dict() for lease in leases])
            item["control_capabilities"] = _control_capabilities(
                environment.to_dict(),
                binding,
                [lease.to_dict() for lease in leases],
                [signal.to_dict() for signal in pending_signals],
            )
            items.append(item)
        return {
            "authority": "task_system.task_environment_view.resumable",
            "task_environments": items,
            "summary": {
                "task_environment_count": len(items),
                "limit": limit,
            },
        }

    def task_environment_detail(
        self,
        task_environment_id: str,
        *,
        event_limit: int = 80,
        episode_limit: int = 40,
        context_package_limit: int = 10,
        work_product_limit: int = 40,
    ) -> dict[str, Any]:
        environment = self.task_repository.get_task_environment(task_environment_id)
        if environment is None:
            return {}
        task_instance = self.task_repository.get_task_instance(environment.task_instance_id)
        graph_binding = self.graph_binding_repository.get_by_task_environment(environment.task_environment_id)
        episodes = self.episode_repository.list_episodes(environment.task_environment_id, limit=episode_limit)
        episode_results = self.episode_repository.list_episode_results(
            task_environment_id=environment.task_environment_id,
            limit=episode_limit,
        )
        context_packages = self.task_repository.list_context_packages(
            environment.task_environment_id,
            limit=context_package_limit,
        )
        latest_context_package = (
            self.task_repository.get_context_package(environment.latest_context_package_id)
            if environment.latest_context_package_id
            else None
        )
        work_products = self.work_product_repository.list_work_products(
            task_environment_id=environment.task_environment_id,
            limit=work_product_limit,
        )
        task_plans = self.task_repository.list_task_plans(environment.task_environment_id, limit=20)
        todo_items = self.task_repository.list_todo_items(environment.task_environment_id, limit=80)
        state_proposals = self.task_repository.list_state_proposals(environment.task_environment_id, limit=80)
        checkpoints = self.task_repository.list_checkpoints(environment.task_environment_id, limit=20)
        control_signals = self.task_repository.list_control_signals(environment.task_environment_id, limit=40)
        task_commands = self.task_repository.list_task_commands(environment.task_environment_id, limit=60)
        dispatch_records = self.task_repository.list_task_dispatch_records(task_environment_id=environment.task_environment_id, limit=60)
        leases = self.task_repository.list_leases(environment.task_environment_id, limit=20)
        events = self.task_repository.list_events(environment.task_environment_id, limit=event_limit)
        environment_payload = environment.to_dict()
        graph_binding_payload = graph_binding.to_dict() if graph_binding is not None else {}
        control_signal_payloads = [item.to_dict() for item in control_signals]
        task_command_payloads = [item.to_dict() for item in task_commands]
        dispatch_record_payloads = [item.to_dict() for item in dispatch_records]
        lease_payloads = [item.to_dict() for item in leases]
        return {
            "authority": "task_system.task_environment_view.detail",
            "task_environment": environment_payload,
            "task_instance": task_instance.to_dict() if task_instance is not None else {},
            "graph_node_binding": graph_binding_payload,
            "episodes": [item.to_dict() for item in episodes],
            "episode_results": [item.to_dict() for item in episode_results],
            "latest_context_package": latest_context_package.to_dict() if latest_context_package is not None else {},
            "context_packages": [item.to_dict() for item in context_packages],
            "work_products": [item.to_dict() for item in work_products],
            "task_plans": [item.to_dict() for item in task_plans],
            "todo_items": [item.to_dict() for item in todo_items],
            "state_proposals": [item.to_dict() for item in state_proposals],
            "checkpoints": [item.to_dict() for item in checkpoints],
            "control_signals": control_signal_payloads,
            "task_commands": task_command_payloads,
            "task_dispatch_records": dispatch_record_payloads,
            "leases": lease_payloads,
            "events": [item.to_dict() for item in events],
            "activity_state": _activity_state(environment_payload, lease_payloads),
            "recovery_hint": _recovery_hint(environment_payload, _compact_binding(graph_binding_payload)),
            "control_capabilities": _control_capabilities(
                environment_payload,
                _compact_binding(graph_binding_payload),
                lease_payloads,
                control_signal_payloads,
            ),
            "summary": {
                "episode_count": len(episodes),
                "episode_result_count": len(episode_results),
                "context_package_count": len(context_packages),
                "work_product_count": len(work_products),
                "task_plan_count": len(task_plans),
                "todo_item_count": len(todo_items),
                "state_proposal_count": len(state_proposals),
                "checkpoint_count": len(checkpoints),
                "control_signal_count": len(control_signals),
                "task_command_count": len(task_commands),
                "task_dispatch_record_count": len(dispatch_records),
                "active_lease_count": len([item for item in lease_payloads if _lease_is_active(item)]),
                "event_count": len(events),
                "has_graph_node_binding": graph_binding is not None,
            },
        }

    def task_environment_recovery_projection(self, task_environment_id: str) -> dict[str, Any]:
        environment = self.task_repository.get_task_environment(task_environment_id)
        if environment is None:
            return {}
        task_instance = self.task_repository.get_task_instance(environment.task_instance_id)
        graph_binding = self.graph_binding_repository.get_by_task_environment(environment.task_environment_id)
        latest_context_package = (
            self.task_repository.get_context_package(environment.latest_context_package_id)
            if environment.latest_context_package_id
            else None
        )
        control_signals = self.task_repository.list_control_signals(environment.task_environment_id, limit=12)
        leases = self.task_repository.list_leases(environment.task_environment_id, limit=8)
        environment_payload = environment.to_dict()
        graph_binding_payload = _compact_binding(graph_binding.to_dict() if graph_binding is not None else {})
        control_signal_payloads = [item.to_dict() for item in control_signals]
        lease_payloads = [item.to_dict() for item in leases]
        control_capabilities = _control_capabilities(
            environment_payload,
            graph_binding_payload,
            lease_payloads,
            control_signal_payloads,
        )
        return {
            "authority": "task_system.task_environment_view.recovery_projection",
            "task_environment": environment_payload,
            "task_instance": _compact_task_instance(task_instance.to_dict() if task_instance is not None else {}),
            "graph_node_binding": graph_binding_payload,
            "activity_state": _activity_state(environment_payload, lease_payloads),
            "recovery_hint": _recovery_hint(environment_payload, graph_binding_payload),
            "control_capabilities": control_capabilities,
            "recommended_api": str(control_capabilities.get("recommended_api") or ""),
            "latest_context_package": _compact_context_package(
                latest_context_package.to_dict() if latest_context_package is not None else {}
            ),
            "latest_lease": lease_payloads[0] if lease_payloads else {},
            "pending_control_signals": [
                item for item in control_signal_payloads if str(item.get("status") or "") == "pending"
            ],
            "summary": {
                "has_graph_node_binding": graph_binding is not None,
                "lease_count": len(lease_payloads),
                "pending_control_signal_count": len(
                    [item for item in control_signal_payloads if str(item.get("status") or "") == "pending"]
                ),
                "latest_event_id": str(environment.latest_event_id or ""),
                "latest_work_product_id": str(environment.latest_work_product_id or ""),
            },
        }

    def _environment_list_item(self, environment: Any) -> dict[str, Any]:
        task_instance = self.task_repository.get_task_instance(environment.task_instance_id)
        graph_binding = self.graph_binding_repository.get_by_task_environment(environment.task_environment_id)
        return {
            "task_environment": environment.to_dict(),
            "task_instance": task_instance.to_dict() if task_instance is not None else {},
            "graph_node_binding": _compact_binding(graph_binding.to_dict() if graph_binding is not None else {}),
            "task_fact_summary": self._task_fact_summary(environment),
        }

    def _task_fact_summary(self, environment: Any) -> dict[str, Any]:
        active_plans = self.task_repository.list_task_plans(environment.task_environment_id, status="active", limit=1)
        latest_plan = active_plans[0] if active_plans else None
        active_todos = self.task_repository.list_todo_items(environment.task_environment_id, status="active", limit=5)
        blocked_todos = self.task_repository.list_todo_items(environment.task_environment_id, status="blocked", limit=5)
        pending_todos = self.task_repository.list_todo_items(environment.task_environment_id, status="pending", limit=5)
        recorded_state_proposals = self.task_repository.list_state_proposals(
            environment.task_environment_id,
            status="recorded",
            limit=20,
        )
        reducer_checkpoints = self.task_repository.list_checkpoints(
            environment.task_environment_id,
            checkpoint_kind="reducer_commit",
            limit=1,
        )
        focus_todos = [*active_todos, *blocked_todos, *pending_todos][:5]
        return _drop_empty(
            {
                "authority": "task_system.task_environment_view.fact_summary",
                "active_plan": _compact_plan(latest_plan.to_dict() if latest_plan is not None else {}),
                "focus_todos": [_compact_todo(item.to_dict()) for item in focus_todos],
                "counts": {
                    "active_todo": len(active_todos),
                    "blocked_todo": len(blocked_todos),
                    "pending_todo_sample": len(pending_todos),
                    "recorded_state_proposal_sample": len(recorded_state_proposals),
                },
                "latest_reducer_checkpoint": _compact_checkpoint(
                    reducer_checkpoints[0].to_dict() if reducer_checkpoints else {}
                ),
            }
        )


def _compact_binding(binding: dict[str, Any]) -> dict[str, Any]:
    if not binding:
        return {}
    return {
        "binding_id": str(binding.get("binding_id") or ""),
        "status": str(binding.get("status") or ""),
        "graph_run_id": str(binding.get("graph_run_id") or ""),
        "graph_id": str(binding.get("graph_id") or ""),
        "config_id": str(binding.get("config_id") or ""),
        "node_id": str(binding.get("node_id") or ""),
        "work_order_id": str(binding.get("work_order_id") or ""),
        "task_ref": str(binding.get("task_ref") or ""),
        "authority": "task_system.task_environment_view.graph_node_binding_summary",
    }


def _compact_task_instance(task_instance: dict[str, Any]) -> dict[str, Any]:
    if not task_instance:
        return {}
    return {
        key: task_instance.get(key)
        for key in (
            "task_instance_id",
            "task_kind",
            "title",
            "goal",
            "status",
            "project_id",
            "workspace_view",
            "root_task_environment_id",
        )
        if task_instance.get(key) not in (None, "", [], {})
    }


def _compact_context_package(context_package: dict[str, Any]) -> dict[str, Any]:
    if not context_package:
        return {}
    return {
        key: context_package.get(key)
        for key in (
            "package_id",
            "episode_id",
            "package_hash",
            "goal",
            "stable_context_ref",
            "current_context_ref",
            "continuation_hint",
            "created_at",
        )
        if context_package.get(key) not in (None, "", [], {})
    }


def _compact_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not plan:
        return {}
    return _drop_empty(
        {
            "plan_id": str(plan.get("plan_id") or ""),
            "version": plan.get("version"),
            "status": str(plan.get("status") or ""),
            "strategy_summary": str(plan.get("strategy_summary") or ""),
        }
    )


def _compact_todo(todo: dict[str, Any]) -> dict[str, Any]:
    if not todo:
        return {}
    return _drop_empty(
        {
            "todo_id": str(todo.get("todo_id") or ""),
            "title": str(todo.get("title") or ""),
            "status": str(todo.get("status") or ""),
            "blocker": str(todo.get("blocker") or ""),
        }
    )


def _compact_checkpoint(checkpoint: dict[str, Any]) -> dict[str, Any]:
    if not checkpoint:
        return {}
    return _drop_empty(
        {
            "checkpoint_id": str(checkpoint.get("checkpoint_id") or ""),
            "checkpoint_kind": str(checkpoint.get("checkpoint_kind") or ""),
            "event_id": str(checkpoint.get("event_id") or ""),
            "event_seq": checkpoint.get("event_seq"),
            "summary": str(checkpoint.get("summary") or ""),
        }
    )


def _recovery_hint(environment: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    status = str(environment.get("status") or "")
    graph_run_id = str(binding.get("graph_run_id") or "").strip()
    if graph_run_id and status == "paused":
        return {
            "authority": "task_system.task_environment_view.recovery_hint",
            "recovery_owner": "graph_system",
            "recommended_control": "graph_run_resume",
            "graph_run_id": graph_run_id,
            "reason": "graph_node_task_environment_paused",
        }
    if graph_run_id and status == "blocked":
        return {
            "authority": "task_system.task_environment_view.recovery_hint",
            "recovery_owner": "graph_system",
            "recommended_control": "inspect_node_result_then_requeue_or_repair",
            "graph_run_id": graph_run_id,
            "reason": "graph_node_task_environment_blocked",
        }
    return {
        "authority": "task_system.task_environment_view.recovery_hint",
        "recovery_owner": "task_system",
        "recommended_control": "resume_task_environment_from_latest_context_package",
        "reason": f"task_environment_{status or 'ready'}",
    }


def _activity_state(environment: dict[str, Any], leases: list[dict[str, Any]]) -> dict[str, Any]:
    active_leases = [lease for lease in leases if _lease_is_active(lease)]
    expired_active_leases = [lease for lease in leases if _lease_is_expired_active(lease)]
    status = str(environment.get("status") or "")
    if active_leases:
        state = "running"
    elif expired_active_leases:
        state = "stale_lease"
    elif status == "paused":
        state = "paused"
    elif status == "blocked":
        state = "blocked"
    elif status == "completed":
        state = "completed"
    elif status in {"archived", "aborted", "failed"}:
        state = status
    else:
        state = "idle"
    return {
        "authority": "task_system.task_environment_view.activity_state",
        "state": state,
        "environment_status": status,
        "active_lease_count": len(active_leases),
        "expired_active_lease_count": len(expired_active_leases),
        "active_lease_ids": [str(item.get("lease_id") or "") for item in active_leases if str(item.get("lease_id") or "")],
        "expired_active_lease_ids": [
            str(item.get("lease_id") or "")
            for item in expired_active_leases
            if str(item.get("lease_id") or "")
        ],
    }


def _control_capabilities(
    environment: dict[str, Any],
    binding: dict[str, Any],
    leases: list[dict[str, Any]],
    control_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    status = str(environment.get("status") or "")
    graph_run_id = str(binding.get("graph_run_id") or "").strip()
    active_leases = [lease for lease in leases if _lease_is_active(lease)]
    expired_active_leases = [lease for lease in leases if _lease_is_expired_active(lease)]
    pending_kinds = {
        str(signal.get("signal_kind") or "")
        for signal in control_signals
        if str(signal.get("status") or "") == "pending"
    }
    terminal = status in {"completed", "archived", "aborted", "failed"}
    return {
        "authority": "task_system.task_environment_view.control_capabilities",
        "can_request_pause": bool(active_leases) and not terminal and "pause_requested" not in pending_kinds,
        "can_request_resume": status in {"ready", "paused", "blocked"} and not active_leases and "resume_requested" not in pending_kinds,
        "can_request_replan": status in {"ready", "paused", "blocked"} and not active_leases and "replan_requested" not in pending_kinds,
        "can_request_abort": not terminal and "abort_requested" not in pending_kinds,
        "can_recover_stale_lease": bool(expired_active_leases),
        "graph_recovery_supported": bool(graph_run_id),
        "pending_control_signal_kinds": sorted(item for item in pending_kinds if item),
        "recommended_api": _recommended_control_api(
            status=status,
            graph_run_id=graph_run_id,
            has_active_lease=bool(active_leases),
            has_expired_active_lease=bool(expired_active_leases),
        ),
    }


def _recommended_control_api(
    *,
    status: str,
    graph_run_id: str,
    has_active_lease: bool,
    has_expired_active_lease: bool,
) -> str:
    if has_expired_active_lease:
        return "POST /api/task-environments/{environment_id}/commands command_kind=recover_stale_lease"
    if has_active_lease:
        return "POST /api/task-environments/{environment_id}/commands command_kind=request_pause|request_stop"
    if graph_run_id and status in {"ready", "paused", "blocked"}:
        return "POST /api/task-environments/{environment_id}/commands command_kind=resume_graph_run|requeue_graph_node|dispatch_ready_graph_nodes"
    if status in {"ready", "paused", "blocked"}:
        return "POST /api/task-environments/{environment_id}/commands command_kind=request_resume"
    return ""


def _lease_is_active(lease: dict[str, Any]) -> bool:
    if str(lease.get("status") or "") != "active":
        return False
    try:
        expires_at = float(lease.get("expires_at") or 0.0)
    except (TypeError, ValueError):
        expires_at = 0.0
    return expires_at > time.time()


def _lease_is_expired_active(lease: dict[str, Any]) -> bool:
    if str(lease.get("status") or "") != "active":
        return False
    try:
        expires_at = float(lease.get("expires_at") or 0.0)
    except (TypeError, ValueError):
        expires_at = 0.0
    return expires_at <= time.time()


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(payload or {}).items() if value not in (None, "", [], {})}
