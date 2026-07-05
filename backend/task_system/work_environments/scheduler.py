from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .graph_control_command_handlers import (
    apply_task_environment_graph_control_command,
    apply_task_environment_graph_recovery_command,
    normalized_task_environment_recovery_action,
    recovery_action_signal_kind,
)
from .models import TaskCommand, TaskDispatchRecord, TaskEvent, stable_task_environment_id
from .repository import TaskEnvironmentRepository
from .service import TaskWorkEnvironmentService


class TaskScheduler:
    authority = "task_system.task_scheduler"

    def __init__(
        self,
        base_dir: str | Path,
        *,
        harness_runtime: Any | None = None,
        graph_system: Any | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.repository = TaskEnvironmentRepository(base_dir)
        self.service = TaskWorkEnvironmentService(base_dir)
        self.harness_runtime = harness_runtime
        self.graph_system = graph_system

    def submit_command(
        self,
        *,
        command_kind: str,
        task_environment_id: str = "",
        requested_by: str = "user",
        payload: dict[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        kind = _normalize_command_kind(command_kind)
        if not kind:
            raise ValueError("submit_command requires command_kind")
        environment_id = str(task_environment_id or "").strip()
        command_payload = dict(payload or {})
        if kind == "run_graph_node_work_order":
            environment_id = self._ensure_graph_node_command_environment_id(
                task_environment_id=environment_id,
                payload=command_payload,
            )
        if kind != "recover_stale_lease" and self.repository.get_task_environment(environment_id) is None:
            raise KeyError(f"task environment not found: {environment_id}")
        key = str(idempotency_key or command_payload.get("idempotency_key") or "").strip()
        if not key:
            key = stable_task_environment_id("taskcmdkey", environment_id, kind, requested_by, command_payload)
        existing = self.repository.get_task_command_by_idempotency(
            task_environment_id=environment_id,
            command_kind=kind,
            idempotency_key=key,
        )
        if existing is not None:
            return {
                "authority": f"{self.authority}.submit_command",
                "created": False,
                "command": existing.to_dict(),
            }
        now = time.time()
        command = self.repository.upsert_task_command(
            TaskCommand(
                command_id=stable_task_environment_id("taskcmd", environment_id, kind, key),
                task_environment_id=environment_id,
                command_kind=kind,  # type: ignore[arg-type]
                status="queued",
                requested_by=str(requested_by or "user"),
                idempotency_key=key,
                payload=command_payload,
                created_at=now,
                updated_at=now,
            )
        )
        self._append_command_event(command, "task_command_queued")
        return {
            "authority": f"{self.authority}.submit_command",
            "created": True,
            "command": command.to_dict(),
        }

    async def dispatch_command(self, command_id: str) -> dict[str, Any]:
        command = self.repository.get_task_command(command_id)
        if command is None:
            raise KeyError(f"task command not found: {command_id}")
        if command.status in {"succeeded", "failed", "canceled", "dead_letter"}:
            latest_dispatch = self._latest_dispatch_for_command(command.command_id)
            return {
                "authority": f"{self.authority}.dispatch_command",
                "dispatched": False,
                "ok": command.status == "succeeded",
                "reason": "command_terminal",
                "command": command.to_dict(),
                "dispatch": latest_dispatch,
                "result": dict(command.result or latest_dispatch.get("result") or {}),
            }
        dispatch_id = stable_task_environment_id("taskdispatch", command.command_id, command.attempt_count + 1)
        started_at = time.time()
        running_command = self.repository.upsert_task_command(
            replace(
                command,
                status="running",
                attempt_count=command.attempt_count + 1,
                dispatch_ref=dispatch_id,
                updated_at=started_at,
            )
        )
        dispatch = self.repository.upsert_task_dispatch_record(
            TaskDispatchRecord(
                dispatch_id=dispatch_id,
                command_id=command.command_id,
                task_environment_id=command.task_environment_id,
                status="running",
                started_at=started_at,
            )
        )
        self._append_command_event(running_command, "task_command_started", dispatch_id=dispatch.dispatch_id)
        try:
            result = await self._execute_command(running_command)
        except Exception as exc:
            error = {
                "message": str(exc) or exc.__class__.__name__,
                "error_type": exc.__class__.__name__,
                "authority": f"{self.authority}.dispatch_error",
            }
            finished_at = time.time()
            failed_dispatch = self.repository.upsert_task_dispatch_record(
                replace(dispatch, status="failed", error=error, finished_at=finished_at)
            )
            failed_command = self.repository.upsert_task_command(
                replace(running_command, status="failed", error=error, updated_at=finished_at)
            )
            self._append_command_event(failed_command, "task_command_failed", dispatch_id=failed_dispatch.dispatch_id, payload=error)
            return {
                "authority": f"{self.authority}.dispatch_command",
                "dispatched": True,
                "ok": False,
                "command": failed_command.to_dict(),
                "dispatch": failed_dispatch.to_dict(),
            }
        finished_at = time.time()
        dispatch_status = "failed" if _result_failed(result) else "succeeded"
        command_status = "failed" if dispatch_status == "failed" else "succeeded"
        dispatch_refs = _dispatch_record_refs(result)
        final_dispatch = self.repository.upsert_task_dispatch_record(
            replace(
                dispatch,
                status=dispatch_status,
                episode_id=str(dispatch_refs.get("episode_id") or dispatch.episode_id),
                runtime_anchor_id=str(dispatch_refs.get("runtime_anchor_id") or dispatch.runtime_anchor_id),
                graph_run_id=str(dispatch_refs.get("graph_run_id") or dispatch.graph_run_id),
                work_order_id=str(dispatch_refs.get("work_order_id") or dispatch.work_order_id),
                result=dict(result or {}),
                finished_at=finished_at,
            )
        )
        final_command = self.repository.upsert_task_command(
            replace(
                running_command,
                status=command_status,
                result=dict(result or {}),
                updated_at=finished_at,
                lease_ref=str(_nested_get(result, "lease", "lease_id") or _nested_get(result, "lease", "lease", "lease_id") or ""),
            )
        )
        self._append_command_event(
            final_command,
            "task_command_failed" if command_status == "failed" else "task_command_succeeded",
            dispatch_id=final_dispatch.dispatch_id,
            payload=dict(result or {}),
        )
        return {
            "authority": f"{self.authority}.dispatch_command",
            "dispatched": True,
            "ok": command_status == "succeeded",
            "command": final_command.to_dict(),
            "dispatch": final_dispatch.to_dict(),
            "result": dict(result or {}),
        }

    async def dispatch_next(self, *, limit: int = 1) -> dict[str, Any]:
        commands = self.repository.list_task_commands(status="queued", limit=limit)
        results = []
        for command in commands:
            results.append(await self.dispatch_command(command.command_id))
        return {
            "authority": f"{self.authority}.dispatch_next",
            "dispatch_results": results,
            "summary": {"dispatched_count": len(results), "limit": limit},
        }

    async def _execute_command(self, command: TaskCommand) -> dict[str, Any]:
        payload = dict(command.payload or {})
        if command.command_kind == "prepare_episode":
            preparation = self.service.prepare_task_episode(
                task_environment_id=command.task_environment_id,
                agent_id=str(payload.get("agent_id") or ""),
                agent_profile_id=str(payload.get("agent_profile_id") or ""),
                invocation_kind=str(payload.get("invocation_kind") or "task_episode"),
                caller_kind=str(payload.get("caller_kind") or "task_system"),
                role_contract=str(payload.get("role_contract") or ""),
                scope=dict(payload.get("scope") or {}),
                acceptance=dict(payload.get("acceptance") or {}),
                resource_handles=dict(payload.get("resource_handles") or {}),
                graph_context=dict(payload.get("graph_context") or {}),
                project_network_handles=dict(payload.get("project_network_handles") or {}),
                output_contract=dict(payload.get("output_contract") or {}),
                packet_policy=dict(payload.get("packet_policy") or {}),
                continuation_hint=str(payload.get("continuation_hint") or ""),
                idempotency_key=str(payload.get("episode_idempotency_key") or command.idempotency_key),
            )
            return {
                "authority": f"{self.authority}.prepare_episode",
                "preparation": preparation.to_dict(),
            }
        if command.command_kind == "run_episode":
            if self.harness_runtime is None:
                raise RuntimeError("TaskScheduler run_episode requires harness_runtime")
            episode_id = str(payload.get("episode_id") or "").strip()
            result = await self.harness_runtime.execute_task_environment_episode(
                task_environment_id=command.task_environment_id,
                episode_id=episode_id,
                max_steps=int(payload.get("max_steps") or 12),
            )
            return {
                "authority": f"{self.authority}.run_episode",
                "episode_execution": dict(result or {}),
            }
        if command.command_kind == "run_graph_node_work_order":
            return await self._execute_graph_node_work_order_command(command, payload)
        if command.command_kind == "materialize_project_network_generation":
            return self._execute_project_network_materialize_command(command, payload)
        if command.command_kind == "publish_project_network_generation":
            return self._execute_project_network_publish_command(command, payload)
        if command.command_kind == "repair_project_network_refs":
            return self._execute_project_network_repair_command(command, payload)
        if command.command_kind in {"request_control_signal", "request_pause", "request_resume", "request_stop"}:
            return self._execute_control_signal_command(command, payload)
        if command.command_kind in {"resume_graph_run", "requeue_graph_node", "dispatch_ready_graph_nodes"}:
            return self._execute_recovery_command(command, payload)
        if command.command_kind == "recover_stale_lease":
            return {
                "authority": f"{self.authority}.recover_stale_lease",
                "recovery": self.service.recover_stale_leases(
                    limit=int(payload.get("limit") or 200),
                    reason=str(payload.get("reason") or "task_environment_lease_expired"),
                ),
            }
        raise ValueError(f"unsupported task command kind: {command.command_kind}")

    async def _execute_graph_node_work_order_command(self, command: TaskCommand, payload: dict[str, Any]) -> dict[str, Any]:
        if self.graph_system is None:
            raise RuntimeError("TaskScheduler run_graph_node_work_order requires graph_system")
        from graph_system.models import GraphNodeWorkOrder, graph_config_from_dict

        graph_config_payload = dict(payload.get("graph_config") or {})
        if not graph_config_payload:
            raise ValueError("run_graph_node_work_order requires graph_config payload")
        work_order_payload = _graph_node_work_order_payload(payload)
        graph_config = graph_config_from_dict(graph_config_payload)
        work_order = GraphNodeWorkOrder.from_dict(work_order_payload)
        binding_service = self._graph_node_binding_service()
        lease_projection_payload: dict[str, Any] = {}
        lease_release_payload: dict[str, Any] = {}
        result_projection_payload: dict[str, Any] = {}
        execution: Any | None = None
        try:
            lease_projection_payload = _payload_dict(binding_service.begin_work_order_execution(work_order))
            execution = await self.graph_system.execute_work_order_executor(
                graph_config=graph_config,
                work_order=work_order,
                max_steps=int(payload.get("max_steps") or 12),
                runtime_overrides=dict(payload.get("runtime_overrides") or {}),
            )
            result_projection_payload = _payload_dict(
                binding_service.record_work_order_result(
                    work_order=execution.work_order,
                    node_result=execution.node_result,
                    executor_result=dict(execution.executor_result or {}),
                )
            )
            lease_release_payload = dict(result_projection_payload.get("lease_release") or {})
        finally:
            if not lease_release_payload:
                lease_release_payload = _payload_dict(
                    binding_service.release_work_order_execution_lease(
                        work_order if execution is None else execution.work_order,
                        release_reason="graph_node_work_order_finished" if execution is not None else "graph_node_work_order_interrupted",
                    )
                )
        accept_result = bool(payload.get("accept_result", True))
        advance = self.graph_system.accept_work_order_execution_result(
            graph_config=graph_config,
            execution=execution,
            accept_result=accept_result,
        )
        graph_work_order_execution = self.graph_system.project_work_order_execution(
            graph_config=graph_config,
            execution=execution,
            advance=advance,
            graph_node_task_lease=lease_projection_payload,
            graph_node_task_lease_release=lease_release_payload,
            graph_node_task_result_projection=result_projection_payload,
        )
        ok = bool(graph_work_order_execution.get("accepted_result") or (not accept_result and graph_work_order_execution.get("node_result")))
        return {
            "authority": f"{self.authority}.run_graph_node_work_order",
            "ok": ok,
            "graph_work_order_execution": graph_work_order_execution,
            "graph_run_id": str(work_order.graph_run_id or ""),
            "work_order_id": str(work_order.work_order_id or ""),
            "episode_id": _graph_node_episode_id(result_projection_payload, lease_projection_payload),
            "task_environment_id": command.task_environment_id,
        }

    def _execute_project_network_materialize_command(self, command: TaskCommand, payload: dict[str, Any]) -> dict[str, Any]:
        from project_network_system import ProjectNetworkBuildService

        build_id = str(payload.get("build_id") or "").strip()
        if not build_id:
            raise ValueError("materialize_project_network_generation requires build_id")
        service = ProjectNetworkBuildService.from_backend_dir(_project_network_target_base_dir(payload, default_base_dir=self.base_dir))
        result = service.materialize_generation_candidate(
            build_id,
            graph_run_id=str(payload.get("graph_run_id") or ""),
            actor_kind=str(payload.get("actor_kind") or "system"),
            actor_ref=str(payload.get("actor_ref") or command.command_id),
            metadata={
                **dict(payload.get("metadata") or {}),
                "task_command_id": command.command_id,
                "task_environment_id": command.task_environment_id,
            },
        )
        return {
            "authority": f"{self.authority}.materialize_project_network_generation",
            "ok": True,
            "project_network_generation": result.to_dict(),
        }

    def _execute_project_network_publish_command(self, command: TaskCommand, payload: dict[str, Any]) -> dict[str, Any]:
        from project_network_system import ProjectNetworkBuildService

        generation_id = str(payload.get("generation_id") or "").strip()
        if not generation_id:
            raise ValueError("publish_project_network_generation requires generation_id")
        service = ProjectNetworkBuildService.from_backend_dir(_project_network_target_base_dir(payload, default_base_dir=self.base_dir))
        result = service.publish_materialized_generation(
            generation_id,
            graph_run_id=str(payload.get("graph_run_id") or ""),
            actor_kind=str(payload.get("actor_kind") or "system_publish_gate"),
            actor_ref=str(payload.get("actor_ref") or command.command_id),
            metadata={
                **dict(payload.get("metadata") or {}),
                "task_command_id": command.command_id,
                "task_environment_id": command.task_environment_id,
            },
        )
        return {
            "authority": f"{self.authority}.publish_project_network_generation",
            "ok": True,
            "project_network_generation": result.to_dict(),
        }

    def _execute_project_network_repair_command(self, command: TaskCommand, payload: dict[str, Any]) -> dict[str, Any]:
        from project_network_system import ProjectNetworkBuildService
        from project_network_tasks import ProjectNetworkRepairRuntimeService

        build_id = str(payload.get("build_id") or "").strip()
        signal_code = str(payload.get("signal_code") or "").strip()
        if not build_id:
            raise ValueError("repair_project_network_refs requires build_id")
        if not signal_code:
            raise ValueError("repair_project_network_refs requires signal_code")
        service = ProjectNetworkBuildService.from_backend_dir(_project_network_target_base_dir(payload, default_base_dir=self.base_dir))
        result = service.queue_repair(
            build_id=build_id,
            signal_source=str(payload.get("signal_source") or "task_system.task_scheduler"),
            signal_code=signal_code,
            severity=str(payload.get("severity") or "info"),
            subject_ref=str(payload.get("subject_ref") or payload.get("stable_ref") or ""),
            stable_ref=str(payload.get("stable_ref") or payload.get("subject_ref") or ""),
            edge_id=str(payload.get("edge_id") or ""),
            anchor_ref=str(payload.get("anchor_ref") or ""),
            scope_refs=tuple(str(item).strip() for item in list(payload.get("scope_refs") or []) if str(item).strip()),
            evidence_refs=tuple(str(item).strip() for item in list(payload.get("evidence_refs") or []) if str(item).strip()),
            requested_layers=tuple(str(item).strip() for item in list(payload.get("requested_layers") or []) if str(item).strip()),
            payload={
                **dict(payload.get("repair_payload") or {}),
                "task_command_id": command.command_id,
                "task_environment_id": command.task_environment_id,
            },
            metadata=dict(payload.get("metadata") or {}),
        )
        repair_item_ids = [
            str(item.get("repair_item_id") or "")
            for item in result.to_dict().get("repair_items", [])
            if str(item.get("repair_item_id") or "").strip()
        ]
        publish_repair_graph = bool(payload.get("publish_repair_graph", True))
        repair_graph_publish: dict[str, Any] = {}
        repair_graph_publish_error: dict[str, Any] = {}
        if publish_repair_graph:
            try:
                repair_graph_publish = ProjectNetworkRepairRuntimeService.from_backend_dir(
                    _project_network_target_base_dir(payload, default_base_dir=self.base_dir),
                    flow_registry_base_dir=self.base_dir,
                ).publish_repair_graph(
                    build_id=build_id,
                    repair_item_ids=tuple(repair_item_ids),
                    limit=int(payload.get("repair_batch_limit") or payload.get("limit") or 4),
                    publish_version=str(payload.get("publish_version") or "runtime"),
                    runtime_scope=dict(payload.get("runtime_scope") or {}),
                    max_active_nodes=int(payload.get("max_active_nodes") or 0),
                ).to_dict()
            except Exception as exc:
                repair_graph_publish_error = {
                    "message": str(exc) or exc.__class__.__name__,
                    "error_type": exc.__class__.__name__,
                    "authority": f"{self.authority}.repair_project_network_refs.publish_error",
                }
        return {
            "authority": f"{self.authority}.repair_project_network_refs",
            "ok": not repair_graph_publish_error,
            "project_network_repair": result.to_dict(),
            "repair_graph_publish": repair_graph_publish,
            "repair_graph_publish_error": repair_graph_publish_error,
            "repair_graph_published": bool(repair_graph_publish),
        }

    def _ensure_graph_node_command_environment_id(
        self,
        *,
        task_environment_id: str,
        payload: dict[str, Any],
    ) -> str:
        environment_id = str(
            task_environment_id
            or payload.get("task_environment_id")
            or payload.get("graph_node_task_environment_id")
            or ""
        ).strip()
        if environment_id and self.repository.get_task_environment(environment_id) is not None:
            payload["task_environment_id"] = environment_id
            return environment_id
        preparation = _payload_dict(self._graph_node_binding_service().prepare_work_order(_graph_node_work_order_payload(payload)))
        environment = dict(preparation.get("task_environment") or {})
        binding = dict(preparation.get("binding") or {})
        episode = dict(preparation.get("episode") or {})
        context_package = dict(preparation.get("context_package") or {})
        environment_id = str(environment.get("task_environment_id") or binding.get("node_task_environment_id") or environment_id).strip()
        if not environment_id:
            raise ValueError("run_graph_node_work_order could not resolve task_environment_id")
        payload["task_environment_id"] = environment_id
        payload["graph_node_task_environment_id"] = environment_id
        payload["graph_node_preparation_ref"] = {
            "binding_id": str(binding.get("binding_id") or ""),
            "episode_id": str(episode.get("episode_id") or ""),
            "context_package_id": str(context_package.get("package_id") or ""),
            "authority": "task_system.task_scheduler.graph_node_preparation_ref",
        }
        return environment_id

    def _graph_node_binding_service(self) -> Any:
        from task_system.graph_bindings import GraphNodeTaskBindingService

        return GraphNodeTaskBindingService(self.base_dir)

    def _execute_control_signal_command(self, command: TaskCommand, payload: dict[str, Any]) -> dict[str, Any]:
        signal_kind = _control_signal_kind_for_command(command.command_kind, payload)
        request_result = self.service.request_control_signal(
            task_environment_id=command.task_environment_id,
            signal_kind=signal_kind,
            requested_by=str(payload.get("requested_by") or command.requested_by or "user"),
            reason=str(payload.get("reason") or ""),
            payload=dict(payload.get("signal_payload") or payload.get("payload") or {}),
            idempotency_key=str(payload.get("signal_idempotency_key") or command.idempotency_key),
        )
        signal = dict(request_result.get("control_signal") or {})
        graph_control = apply_task_environment_graph_control_command(
            base_dir=self.base_dir,
            graph_system=self.graph_system,
            environment_id=command.task_environment_id,
            signal=signal,
            graph_control_enabled=bool(payload.get("graph_control_enabled", True)),
        )
        handling_result: dict[str, Any] = {}
        graph_control_status = str(graph_control.get("signal_status") or "")
        if graph_control_status in {"handled", "failed"}:
            handling_result = self.service.record_control_signal_handling(
                signal_id=str(signal.get("signal_id") or ""),
                status=graph_control_status,
                handling_result=graph_control,
            )
        return {
            "authority": f"{self.authority}.control_signal",
            "request": request_result,
            "graph_control": graph_control,
            "handling": handling_result,
        }

    def _execute_recovery_command(self, command: TaskCommand, payload: dict[str, Any]) -> dict[str, Any]:
        action = normalized_task_environment_recovery_action(str(payload.get("recovery_action") or command.command_kind))
        if not action:
            raise ValueError("unsupported task environment recovery action")
        request_result = self.service.request_control_signal(
            task_environment_id=command.task_environment_id,
            signal_kind=recovery_action_signal_kind(action),
            requested_by=str(payload.get("requested_by") or command.requested_by or "user"),
            reason=str(payload.get("reason") or action),
            payload={
                "recovery_action": action,
                "start_node_ids": list(payload.get("start_node_ids") or []),
                "reset_downstream": bool(payload.get("reset_downstream", False)),
                "dispatch_ready": bool(payload.get("dispatch_ready", True)),
                "max_dispatch_requests": int(payload.get("max_dispatch_requests") or 4),
                "runtime_settings_patch": dict(payload.get("runtime_settings_patch") or {}),
            },
            idempotency_key=str(payload.get("signal_idempotency_key") or f"{command.idempotency_key}:signal"),
        )
        signal = dict(request_result.get("control_signal") or {})
        graph_recovery = apply_task_environment_graph_recovery_command(
            base_dir=self.base_dir,
            graph_system=self.graph_system,
            environment_id=command.task_environment_id,
            action=action,
            command_id=command.command_id,
            start_node_ids=tuple(str(item).strip() for item in list(payload.get("start_node_ids") or []) if str(item).strip()),
            reset_downstream=bool(payload.get("reset_downstream", False)),
            dispatch_ready=bool(payload.get("dispatch_ready", True)),
            max_dispatch_requests=int(payload.get("max_dispatch_requests") or 4),
            runtime_settings_patch=dict(payload.get("runtime_settings_patch") or {}),
        )
        handling_result: dict[str, Any] = {}
        graph_recovery_status = str(graph_recovery.get("signal_status") or "")
        if graph_recovery_status in {"handled", "failed"}:
            handling_result = self.service.record_control_signal_handling(
                signal_id=str(signal.get("signal_id") or ""),
                status=graph_recovery_status,
                handling_result=graph_recovery,
            )
        return {
            "authority": f"{self.authority}.recovery_command",
            "request": request_result,
            "graph_recovery": graph_recovery,
            "handling": handling_result,
        }

    def _append_command_event(
        self,
        command: TaskCommand,
        event_type: str,
        *,
        dispatch_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not command.task_environment_id:
            return
        environment = self.repository.get_task_environment(command.task_environment_id)
        if environment is None:
            return
        event_payload = {
            "command_id": command.command_id,
            "command_kind": command.command_kind,
            "command_status": command.status,
            "dispatch_id": dispatch_id,
            **dict(payload or {}),
        }
        self.repository.append_event(
            TaskEvent(
                event_id=stable_task_environment_id("taskevent", command.task_environment_id, event_type, command.command_id, dispatch_id),
                task_environment_id=environment.task_environment_id,
                task_instance_id=environment.task_instance_id,
                event_seq=0,
                event_type=event_type,
                actor_kind="system" if command.requested_by == "system" else "user",
                actor_id=command.requested_by,
                idempotency_key=f"{event_type}:{command.command_id}:{dispatch_id}",
                payload=event_payload,
                refs={
                    "task_command_ref": command.command_id,
                    **({"task_dispatch_ref": dispatch_id} if dispatch_id else {}),
                },
                created_at=time.time(),
            )
        )

    def _latest_dispatch_for_command(self, command_id: str) -> dict[str, Any]:
        records = self.repository.list_task_dispatch_records(command_id=command_id, limit=1)
        return records[0].to_dict() if records else {}


def _normalize_command_kind(value: str) -> str:
    kind = str(value or "").strip()
    aliases = {
        "pause_requested": "request_pause",
        "resume_requested": "request_resume",
        "stop_requested": "request_stop",
        "abort_requested": "request_stop",
        "resume": "resume_graph_run",
        "resume_graph": "resume_graph_run",
        "requeue": "requeue_graph_node",
        "requeue_node": "requeue_graph_node",
        "dispatch": "dispatch_ready_graph_nodes",
        "dispatch_ready": "dispatch_ready_graph_nodes",
        "graph_node_run": "run_graph_node_work_order",
        "run_graph_node": "run_graph_node_work_order",
        "execute_graph_node": "run_graph_node_work_order",
        "materialize_project_network": "materialize_project_network_generation",
        "materialize_network_generation": "materialize_project_network_generation",
        "publish_project_network": "publish_project_network_generation",
        "publish_network_generation": "publish_project_network_generation",
        "repair_project_network": "repair_project_network_refs",
    }
    return aliases.get(kind, kind)


def _control_signal_kind_for_command(command_kind: str, payload: dict[str, Any]) -> str:
    if command_kind == "request_pause":
        return "pause_requested"
    if command_kind == "request_resume":
        return "resume_requested"
    if command_kind == "request_stop":
        return "abort_requested" if str(payload.get("signal_kind") or "") == "abort_requested" else "stop_requested"
    signal_kind = str(payload.get("signal_kind") or "").strip()
    if not signal_kind:
        raise ValueError("request_control_signal requires signal_kind")
    return signal_kind


def _result_failed(result: dict[str, Any]) -> bool:
    graph_control = dict(result.get("graph_control") or {})
    graph_recovery = dict(result.get("graph_recovery") or {})
    if str(graph_control.get("signal_status") or "") == "failed":
        return True
    if str(graph_recovery.get("signal_status") or "") == "failed":
        return True
    if str(result.get("authority") or "").endswith(".recovery_command") and str(graph_recovery.get("signal_status") or "") != "handled":
        return True
    episode_execution = dict(result.get("episode_execution") or {})
    if episode_execution.get("ok") is False:
        return True
    if str(result.get("authority") or "").endswith(".run_graph_node_work_order") and result.get("ok") is not True:
        return True
    return bool(result.get("ok") is False)


def _nested_get(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _graph_node_work_order_payload(payload: dict[str, Any]) -> dict[str, Any]:
    work_order = dict(payload.get("work_order") or payload.get("graph_node_work_order") or {})
    if not work_order:
        raise ValueError("run_graph_node_work_order requires work_order payload")
    return work_order


def _payload_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return dict(value.to_dict() or {})
    return dict(value or {}) if isinstance(value, dict) else {}


def _graph_node_episode_id(*payloads: dict[str, Any]) -> str:
    for payload in payloads:
        episode = dict(payload.get("episode") or {})
        value = str(episode.get("episode_id") or payload.get("episode_id") or "").strip()
        if value:
            return value
    return ""


def _dispatch_record_refs(result: dict[str, Any]) -> dict[str, str]:
    graph_execution = dict(result.get("graph_work_order_execution") or {})
    work_order = dict(graph_execution.get("work_order") or {})
    node_task_result = dict(graph_execution.get("graph_node_task_result_projection") or {})
    node_task_lease = dict(graph_execution.get("graph_node_task_lease") or {})
    return {
        "episode_id": _graph_node_episode_id(node_task_result, node_task_lease, result),
        "runtime_anchor_id": str(graph_execution.get("runtime_anchor_id") or ""),
        "graph_run_id": str(result.get("graph_run_id") or graph_execution.get("graph_run_id") or work_order.get("graph_run_id") or ""),
        "work_order_id": str(result.get("work_order_id") or work_order.get("work_order_id") or ""),
    }


def _project_network_target_base_dir(payload: dict[str, Any], *, default_base_dir: Path) -> Path:
    for key in ("project_network_target_backend_dir", "project_network_target_project_root"):
        raw = str(payload.get(key) or "").strip()
        if not raw:
            continue
        try:
            return Path(raw).expanduser().resolve()
        except OSError:
            continue
    return Path(default_base_dir).resolve()
