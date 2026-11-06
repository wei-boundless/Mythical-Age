from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from task_system.episodes import AgentExecutionEpisode, EpisodeRepository, EpisodeResult
from task_system.reducer import TaskReducer
from task_system.work_environments.models import (
    TaskContextPackage,
    TaskEnvironmentLease,
    TaskEvent,
    TaskInstance,
    TaskWorkEnvironment,
    context_package_hash,
    stable_task_environment_id,
)
from task_system.work_environments.repository import TaskEnvironmentRepository
from task_system.work_environments.service import TaskWorkEnvironmentService, build_task_state_context_for_episode
from task_system.work_products import WorkProduct

from .models import GraphNodeTaskBinding, binding_from_work_order_payload
from .repository import GraphNodeTaskBindingRepository


@dataclass(frozen=True, slots=True)
class GraphNodeTaskPreparation:
    binding: GraphNodeTaskBinding
    task_instance: TaskInstance
    task_environment: TaskWorkEnvironment
    episode: AgentExecutionEpisode
    context_package: TaskContextPackage
    event: TaskEvent
    authority: str = "task_system.graph_node_task_preparation"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "binding": self.binding.to_dict(),
            "task_instance": self.task_instance.to_dict(),
            "task_environment": self.task_environment.to_dict(),
            "episode": self.episode.to_dict(),
            "context_package": self.context_package.to_dict(),
            "event": self.event.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class GraphNodeTaskState:
    binding: GraphNodeTaskBinding
    task_instance: TaskInstance
    task_environment: TaskWorkEnvironment
    episode: AgentExecutionEpisode
    context_package: TaskContextPackage
    authority: str = "task_system.graph_node_task_state"


@dataclass(frozen=True, slots=True)
class GraphNodeTaskResultProjection:
    binding: GraphNodeTaskBinding
    episode: AgentExecutionEpisode
    episode_result: EpisodeResult
    work_products: tuple[WorkProduct, ...] = ()
    event: TaskEvent | None = None
    checkpoint: Any | None = None
    lease_release: Any | None = None
    authority: str = "task_system.graph_node_task_result_projection"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "binding": self.binding.to_dict(),
            "episode": self.episode.to_dict(),
            "episode_result": self.episode_result.to_dict(),
            "work_products": [item.to_dict() for item in self.work_products],
            "event": self.event.to_dict() if self.event is not None else {},
            "checkpoint": self.checkpoint.to_dict() if hasattr(self.checkpoint, "to_dict") else dict(self.checkpoint or {}),
            "lease_release": self.lease_release.to_dict() if hasattr(self.lease_release, "to_dict") else dict(self.lease_release or {}),
        }


@dataclass(frozen=True, slots=True)
class GraphNodeTaskLeaseProjection:
    binding: GraphNodeTaskBinding
    task_environment: TaskWorkEnvironment
    episode: AgentExecutionEpisode
    lease: TaskEnvironmentLease
    event: TaskEvent
    authority: str = "task_system.graph_node_task_lease_projection"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "binding": self.binding.to_dict(),
            "task_environment": self.task_environment.to_dict(),
            "episode": self.episode.to_dict(),
            "lease": self.lease.to_dict(),
            "event": self.event.to_dict(),
        }


class GraphNodeTaskBindingService:
    authority = "task_system.graph_node_task_binding_service"

    def __init__(self, base_dir: str | Path) -> None:
        self.repository = GraphNodeTaskBindingRepository(base_dir)
        self.task_repository = TaskEnvironmentRepository(base_dir)
        self.episode_repository = EpisodeRepository(base_dir)
        self.reducer = TaskReducer(base_dir)
        self.task_service = TaskWorkEnvironmentService(base_dir)

    def bind_work_order(self, work_order: Any) -> GraphNodeTaskBinding:
        payload = _work_order_payload(work_order)
        binding = binding_from_work_order_payload(payload, status="bound")
        existing = self.repository.get_by_work_order(binding.graph_run_id, binding.work_order_id)
        if existing is not None:
            binding = replace(
                binding,
                status=_binding_status_without_regression(
                    current=existing.status,
                    requested=binding.status,
                ),
                metadata={**dict(existing.metadata or {}), **dict(binding.metadata or {})},
            )
        return self.repository.upsert_binding(binding)

    def prepare_work_order(self, work_order: Any) -> GraphNodeTaskPreparation:
        payload = _work_order_payload(work_order)
        state = self._ensure_work_order_state(payload)
        event = self._append_prepared_event(
            binding=state.binding,
            work_order=payload,
            task_environment=state.task_environment,
            episode=state.episode,
            context_package=state.context_package,
        )
        latest_environment = self.task_repository.get_task_environment(state.binding.node_task_environment_id) or state.task_environment
        return GraphNodeTaskPreparation(
            binding=state.binding,
            task_instance=state.task_instance,
            task_environment=latest_environment,
            episode=state.episode,
            context_package=state.context_package,
            event=event,
        )

    def record_work_order_result(
        self,
        *,
        work_order: Any,
        node_result: Any,
        executor_result: dict[str, Any] | None = None,
    ) -> GraphNodeTaskResultProjection:
        work_order_payload = _work_order_payload(work_order)
        result_payload = _node_result_payload(node_result)
        state = self._ensure_work_order_state(work_order_payload)
        binding_status = "completed" if str(result_payload.get("status") or "") == "completed" else "completed_with_failure"
        binding = replace(state.binding, status=binding_status)
        now = time.time()
        work_products = _work_products_from_result(
            binding=binding,
            episode=state.episode,
            node_result=result_payload,
            executor_result=dict(executor_result or {}),
        )
        episode_result = EpisodeResult(
            result_id=stable_task_environment_id("epresult", state.episode.episode_id, str(result_payload.get("result_id") or "")),
            episode_id=state.episode.episode_id,
            task_environment_id=binding.node_task_environment_id,
            status=_episode_result_status(result_payload),
            summary=_result_summary(result_payload),
            work_product_candidates=tuple(item.ref().to_dict() for item in work_products),
            memory_candidates=tuple(dict(item) for item in list(result_payload.get("memory_candidates") or []) if isinstance(item, dict)),
            artifact_refs=tuple(str(item) for item in list(result_payload.get("artifact_refs") or []) if str(item)),
            blocker=_blocker(result_payload),
            continuation_hint=_continuation_hint(result_payload),
            output_contract_version=str(dict(work_order_payload.get("expected_result_contract") or {}).get("output_contract_id") or ""),
            diagnostics={
                "graph_run_id": binding.graph_run_id,
                "node_id": binding.node_id,
                "work_order_id": binding.work_order_id,
                "node_result_id": str(result_payload.get("result_id") or ""),
                "executor_result_status": str(dict(executor_result or {}).get("status") or ""),
                "source_authority": self.authority,
            },
        )
        event = self._result_recorded_event(
            binding=binding,
            episode=state.episode,
            episode_result=episode_result,
            node_result=result_payload,
            work_products=work_products,
        )
        reduction = self.reducer.reduce_episode_result(
            episode=state.episode,
            episode_status=_episode_status(result_payload),
            terminal_reason=_terminal_reason(result_payload),
            episode_result=episode_result,
            work_product_candidates=work_products,
            event=event,
            snapshot_patch=_result_snapshot_patch(result_payload),
            episode_diagnostics_patch={
                "node_result_id": str(result_payload.get("result_id") or ""),
                "node_result_status": str(result_payload.get("status") or ""),
                "source_authority": "task_system.graph_node_task_binding_service.record_work_order_result",
            },
            ended_at=now,
            release_reason="graph_node_work_order_finished",
            release_event_type="graph_node_execution_lease_released",
            release_current_phase="graph_node_work_order",
            release_current_step="lease_released",
            release_progress_label="graph node execution lease released",
            release_source_graph_run_id=binding.graph_run_id,
            release_source_work_order_id=binding.work_order_id,
            release_event_payload={
                "graph_binding_id": binding.binding_id,
                "node_id": binding.node_id,
                "work_order_id": binding.work_order_id,
            },
            release_event_refs={
                "graph_run_ref": binding.graph_run_id,
                "work_order_ref": binding.work_order_id,
                "graph_binding_ref": binding.binding_id,
            },
        )
        stored_binding = self.repository.upsert_binding(binding)
        return GraphNodeTaskResultProjection(
            binding=stored_binding,
            episode=reduction.episode,
            episode_result=reduction.episode_result,
            work_products=reduction.work_products,
            event=reduction.event,
            checkpoint=reduction.checkpoint,
            lease_release=reduction.lease_release,
        )

    def begin_work_order_execution(self, work_order: Any) -> GraphNodeTaskLeaseProjection:
        work_order_payload = _work_order_payload(work_order)
        preparation = self.prepare_work_order(work_order_payload)
        projection = self.task_service.acquire_episode_lease(
            task_environment_id=preparation.binding.node_task_environment_id,
            episode_id=preparation.episode.episode_id,
            lease_kind="graph_node_execution",
            holder_kind="graph_system_work_order",
            holder_id=preparation.binding.work_order_id,
            ttl_seconds=_lease_ttl_seconds(preparation.binding.lease_policy or work_order_payload),
            idempotency_key=f"graph-node-execution:{preparation.binding.idempotency_key}",
            event_type="graph_node_execution_lease_acquired",
            current_phase="graph_node_work_order",
            current_step="running",
            progress_label="graph node execution lease active",
            source_graph_run_id=preparation.binding.graph_run_id,
            source_work_order_id=preparation.binding.work_order_id,
            event_payload={
                "graph_binding_id": preparation.binding.binding_id,
                "node_id": preparation.binding.node_id,
                "work_order_id": preparation.binding.work_order_id,
            },
            event_refs={
                "graph_run_ref": preparation.binding.graph_run_id,
                "work_order_ref": preparation.binding.work_order_id,
                "graph_binding_ref": preparation.binding.binding_id,
            },
        )
        binding = self.repository.upsert_binding(
            replace(
                preparation.binding,
                status=_binding_status_for_lease_acquired(preparation.binding.status),
                metadata={
                    **dict(preparation.binding.metadata or {}),
                    "active_lease_id": projection.lease.lease_id,
                    "lease_acquired_event_id": projection.event.event_id,
                },
            )
        )
        return GraphNodeTaskLeaseProjection(
            binding=binding,
            task_environment=projection.task_environment,
            episode=projection.episode,
            lease=projection.lease,
            event=projection.event,
        )

    def release_work_order_execution_lease(
        self,
        work_order: Any,
        *,
        release_reason: str = "graph_node_work_order_finished",
    ) -> GraphNodeTaskLeaseProjection:
        work_order_payload = _work_order_payload(work_order)
        state = self._ensure_work_order_state(work_order_payload)
        lease_id = _lease_id(state.binding, episode_id=state.episode.episode_id)
        projection = self.task_service.release_episode_lease(
            task_environment_id=state.binding.node_task_environment_id,
            lease_id=lease_id,
            release_reason=str(release_reason or "graph_node_work_order_finished"),
            event_type="graph_node_execution_lease_released",
            current_phase="graph_node_work_order",
            current_step="lease_released",
            progress_label=str(release_reason or "graph node execution lease released"),
            source_graph_run_id=state.binding.graph_run_id,
            source_work_order_id=state.binding.work_order_id,
            event_payload={
                "graph_binding_id": state.binding.binding_id,
                "node_id": state.binding.node_id,
                "work_order_id": state.binding.work_order_id,
            },
            event_refs={
                "graph_run_ref": state.binding.graph_run_id,
                "work_order_ref": state.binding.work_order_id,
                "graph_binding_ref": state.binding.binding_id,
            },
        )
        binding = self.repository.upsert_binding(
            replace(
                state.binding,
                status=_binding_status_for_lease_release(
                    current=state.binding.status,
                    release_reason=release_reason,
                ),
                metadata={
                    **dict(state.binding.metadata or {}),
                    "released_lease_id": projection.lease.lease_id,
                    "lease_release_event_id": projection.event.event_id,
                    "lease_release_reason": str(release_reason or "graph_node_work_order_finished"),
                },
            )
        )
        return GraphNodeTaskLeaseProjection(
            binding=binding,
            task_environment=projection.task_environment,
            episode=projection.episode,
            lease=projection.lease,
            event=projection.event,
        )

    def _ensure_work_order_state(self, work_order: dict[str, Any]) -> GraphNodeTaskState:
        binding = self.bind_work_order(work_order)
        task_instance = self._ensure_task_instance(binding=binding, work_order=work_order)
        task_environment = self._ensure_task_environment(binding=binding, work_order=work_order)
        episode = self._ensure_episode(binding=binding, work_order=work_order)
        context_package = self._upsert_context_package(binding=binding, work_order=work_order, episode=episode)
        return GraphNodeTaskState(
            binding=binding,
            task_instance=task_instance,
            task_environment=task_environment,
            episode=episode,
            context_package=context_package,
        )

    def _ensure_task_instance(self, *, binding: GraphNodeTaskBinding, work_order: dict[str, Any]) -> TaskInstance:
        existing = self.task_repository.get_task_instance(binding.task_instance_id)
        if existing is not None:
            return existing
        node_identity = _node_identity(work_order)
        runtime_scope = _runtime_scope(work_order)
        instance = TaskInstance(
            task_instance_id=binding.task_instance_id,
            task_kind="graph_node",
            title=_task_title(binding=binding, node_identity=node_identity),
            goal=_task_goal(work_order=work_order, node_identity=node_identity),
            status="active",
            owner_agent_id=_agent_id(work_order),
            project_id=str(runtime_scope.get("project_id") or ""),
            workspace_view=str(runtime_scope.get("workspace_view") or ""),
            root_task_environment_id=binding.node_task_environment_id,
            metadata={
                "graph_run_id": binding.graph_run_id,
                "graph_id": binding.graph_id,
                "config_id": binding.config_id,
                "node_id": binding.node_id,
                "work_order_id": binding.work_order_id,
                "task_ref": binding.task_ref,
                "source_authority": self.authority,
            },
        )
        return self.task_repository.upsert_task_instance(instance)

    def _ensure_task_environment(self, *, binding: GraphNodeTaskBinding, work_order: dict[str, Any]) -> TaskWorkEnvironment:
        existing = self.task_repository.get_task_environment(binding.node_task_environment_id)
        if existing is not None:
            return existing
        environment = TaskWorkEnvironment(
            task_environment_id=binding.node_task_environment_id,
            task_instance_id=binding.task_instance_id,
            environment_kind="graph_node",
            caller_kind="graph_system",
            status="ready",
            current_phase="graph_node_work_order",
            current_step="scheduled",
            progress_label="graph node prepared",
            metadata={
                "graph_binding_id": binding.binding_id,
                "graph_run_id": binding.graph_run_id,
                "graph_id": binding.graph_id,
                "config_id": binding.config_id,
                "node_id": binding.node_id,
                "work_order_id": binding.work_order_id,
                "task_ref": binding.task_ref,
                "source_authority": self.authority,
            },
        )
        return self.task_repository.upsert_task_environment(environment)

    def _ensure_episode(self, *, binding: GraphNodeTaskBinding, work_order: dict[str, Any]) -> AgentExecutionEpisode:
        episode_id = stable_task_environment_id("episode", binding.node_task_environment_id, binding.binding_id, binding.idempotency_key)
        existing = self.episode_repository.get_episode(episode_id)
        if existing is not None:
            return existing
        episode = AgentExecutionEpisode(
            episode_id=episode_id,
            task_environment_id=binding.node_task_environment_id,
            task_instance_id=binding.task_instance_id,
            agent_id=_agent_id(work_order),
            agent_profile_id=_agent_profile_id(work_order, binding=binding),
            invocation_kind="graph_node_work_order",
            caller_kind="graph_system",
            status="scheduled",
            graph_binding_id=binding.binding_id,
            diagnostics={
                "graph_run_id": binding.graph_run_id,
                "node_id": binding.node_id,
                "work_order_id": binding.work_order_id,
                "idempotency_key": binding.idempotency_key,
                "source_authority": self.authority,
            },
        )
        return self.episode_repository.upsert_episode(episode)

    def _upsert_context_package(
        self,
        *,
        binding: GraphNodeTaskBinding,
        work_order: dict[str, Any],
        episode: AgentExecutionEpisode,
    ) -> TaskContextPackage:
        task_instance = self.task_repository.get_task_instance(binding.task_instance_id)
        task_environment = self.task_repository.get_task_environment(binding.node_task_environment_id)
        task_state_context = (
            build_task_state_context_for_episode(
                repository=self.task_repository,
                task_instance=task_instance,
                environment=task_environment,
            )
            if task_instance is not None and task_environment is not None
            else {}
        )
        context_payload = _context_payload(
            binding=binding,
            work_order=work_order,
            task_state_context=task_state_context,
        )
        package = TaskContextPackage(
            package_id=stable_task_environment_id("taskctx", binding.node_task_environment_id, episode.episode_id, binding.idempotency_key),
            task_environment_id=binding.node_task_environment_id,
            episode_id=episode.episode_id,
            package_hash=context_package_hash(context_payload),
            role_contract=str(work_order.get("message") or "")[:4000],
            goal=_task_goal(work_order=work_order, node_identity=_node_identity(work_order)),
            scope=dict(context_payload.get("scope") or {}),
            acceptance=dict(work_order.get("expected_result_contract") or {}),
            stable_context_ref=str(dict(work_order.get("input_package") or {}).get("package_id") or ""),
            current_context_ref=str(dict(work_order.get("input_package") or {}).get("package_id") or ""),
            memory_refs=tuple(_memory_refs(work_order)),
            artifact_refs=tuple(_artifact_refs(work_order)),
            resource_handles=dict(context_payload.get("resource_handles") or {}),
            graph_context=dict(context_payload.get("graph_context") or {}),
            task_state_context=task_state_context,
            continuation_hint="graph node work order is prepared; execute through GraphSystem work order executor",
            output_contract=dict(work_order.get("expected_result_contract") or {}),
            packet_policy=dict(context_payload.get("packet_policy") or {}),
            metadata={
                "graph_binding_id": binding.binding_id,
                "work_order_id": binding.work_order_id,
                "source_authority": self.authority,
            },
        )
        return self.task_repository.upsert_context_package(package)

    def _append_prepared_event(
        self,
        *,
        binding: GraphNodeTaskBinding,
        work_order: dict[str, Any],
        task_environment: TaskWorkEnvironment,
        episode: AgentExecutionEpisode,
        context_package: TaskContextPackage,
    ) -> TaskEvent:
        event = TaskEvent(
            event_id=stable_task_environment_id(
                "taskevent",
                binding.node_task_environment_id,
                "graph_node_task_prepared",
                binding.idempotency_key,
            ),
            task_environment_id=binding.node_task_environment_id,
            task_instance_id=binding.task_instance_id,
            event_seq=0,
            event_type="graph_node_task_prepared",
            actor_kind="system",
            source_episode_id=episode.episode_id,
            source_graph_run_id=binding.graph_run_id,
            source_work_order_id=binding.work_order_id,
            idempotency_key=f"graph-node-prepared:{binding.idempotency_key}",
            payload={
                "graph_binding_id": binding.binding_id,
                "node_id": binding.node_id,
                "task_ref": binding.task_ref,
                "agent_profile_id": _agent_profile_id(work_order, binding=binding),
                "context_package_id": context_package.package_id,
            },
            refs={
                "graph_run_ref": binding.graph_run_id,
                "work_order_ref": binding.work_order_id,
                "task_environment_ref": task_environment.task_environment_id,
                "episode_ref": episode.episode_id,
                "context_package_ref": context_package.package_id,
            },
        )
        return self.task_repository.append_event(
            event,
            snapshot_patch={
                "status": "ready",
                "current_phase": "graph_node_work_order",
                "current_step": "scheduled",
                "progress_label": "graph node prepared",
                "latest_context_package_id": context_package.package_id,
            },
        )

    def _result_recorded_event(
        self,
        *,
        binding: GraphNodeTaskBinding,
        episode: AgentExecutionEpisode,
        episode_result: EpisodeResult,
        node_result: dict[str, Any],
        work_products: tuple[WorkProduct, ...],
    ) -> TaskEvent:
        event = TaskEvent(
            event_id=stable_task_environment_id(
                "taskevent",
                binding.node_task_environment_id,
                "graph_node_task_result_recorded",
                str(node_result.get("result_id") or ""),
            ),
            task_environment_id=binding.node_task_environment_id,
            task_instance_id=binding.task_instance_id,
            event_seq=0,
            event_type="graph_node_task_result_recorded",
            actor_kind="system",
            source_episode_id=episode.episode_id,
            source_graph_run_id=binding.graph_run_id,
            source_work_order_id=binding.work_order_id,
            idempotency_key=f"graph-node-result:{node_result.get('result_id') or binding.work_order_id}",
            payload={
                "graph_binding_id": binding.binding_id,
                "node_result_id": str(node_result.get("result_id") or ""),
                "node_result_status": str(node_result.get("status") or ""),
                "episode_result_id": episode_result.result_id,
                "work_product_ids": [item.work_product_id for item in work_products],
            },
            refs={
                "graph_run_ref": binding.graph_run_id,
                "work_order_ref": binding.work_order_id,
                "episode_ref": episode.episode_id,
                "episode_result_ref": episode_result.result_id,
            },
        )
        return event

def _work_order_payload(work_order: Any) -> dict[str, Any]:
    if hasattr(work_order, "to_dict"):
        payload = work_order.to_dict()
    elif isinstance(work_order, dict):
        payload = dict(work_order)
    else:
        payload = {}
    if not isinstance(payload, dict) or not payload:
        raise ValueError("GraphNodeTaskBindingService requires GraphNodeWorkOrder payload")
    return dict(payload)


def _node_result_payload(node_result: Any) -> dict[str, Any]:
    if hasattr(node_result, "to_dict"):
        payload = node_result.to_dict()
    elif isinstance(node_result, dict):
        payload = dict(node_result)
    else:
        payload = {}
    if not isinstance(payload, dict) or not payload:
        raise ValueError("GraphNodeTaskBindingService requires graph node result payload")
    return dict(payload)


def _binding_status_without_regression(*, current: str, requested: str) -> str:
    normalized_current = str(current or "").strip() or "created"
    normalized_requested = str(requested or "").strip() or "created"
    if _binding_status_rank(normalized_current) > _binding_status_rank(normalized_requested):
        return normalized_current
    return normalized_requested


def _binding_status_rank(status: str) -> int:
    return {
        "created": 0,
        "bound": 1,
        "leased": 2,
        "waiting_resume": 3,
        "completed": 4,
        "completed_with_failure": 4,
        "aborted": 4,
    }.get(str(status or "").strip(), 0)


def _binding_status_for_lease_acquired(current: str) -> str:
    normalized = str(current or "").strip()
    if normalized in {"completed", "completed_with_failure", "aborted"}:
        return normalized
    return "leased"


def _binding_status_for_lease_release(*, current: str, release_reason: str) -> str:
    normalized = str(current or "").strip()
    if normalized in {"completed", "completed_with_failure", "aborted"}:
        return normalized
    reason = str(release_reason or "").strip().lower()
    if "abort" in reason or "stop" in reason:
        return "aborted"
    return "waiting_resume"


def _episode_status(node_result: dict[str, Any]) -> str:
    status = str(node_result.get("status") or "")
    if status == "completed":
        return "completed"
    if status == "waiting_human_gate":
        return "waiting_user"
    if status == "failed":
        return "failed"
    return "interrupted"


def _episode_result_status(node_result: dict[str, Any]) -> str:
    status = str(node_result.get("status") or "")
    if status == "completed":
        return "completed"
    if status == "failed":
        return "failed"
    return "blocked"


def _task_environment_status(node_result: dict[str, Any]) -> str:
    return "completed" if str(node_result.get("status") or "") == "completed" else "blocked"


def _result_snapshot_patch(node_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": _task_environment_status(node_result),
        "current_phase": "graph_node_work_order",
        "current_step": str(node_result.get("status") or "completed"),
        "progress_current": 1,
        "progress_total": 1,
        "progress_label": _result_summary(node_result)[:240],
        "blocked_reason": _blocker(node_result),
        "continuation_hint": _continuation_hint(node_result),
    }


def _lease_id(binding: GraphNodeTaskBinding, *, episode_id: str) -> str:
    return stable_task_environment_id(
        "lease",
        binding.node_task_environment_id,
        episode_id,
        f"graph-node-execution:{binding.idempotency_key}",
    )


def _lease_ttl_seconds(value: dict[str, Any]) -> float:
    policy = dict(value.get("lease_policy") or value.get("async_policy") or value)
    for key in ("ttl_seconds", "lease_ttl_seconds", "timeout_seconds", "max_runtime_seconds"):
        try:
            value = float(policy.get(key) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return max(1.0, value)
    return 2 * 60 * 60


def _terminal_reason(node_result: dict[str, Any]) -> str:
    status = str(node_result.get("status") or "")
    if status == "completed":
        return "node_result_completed"
    return _blocker(node_result) or f"node_result_{status or 'unknown'}"


def _blocker(node_result: dict[str, Any]) -> str:
    status = str(node_result.get("status") or "")
    if status == "completed":
        return ""
    error = dict(node_result.get("error") or {})
    return str(error.get("reason") or error.get("message") or node_result.get("handoff_summary") or status or "node_result_blocked")[:1200]


def _continuation_hint(node_result: dict[str, Any]) -> str:
    status = str(node_result.get("status") or "")
    if status == "completed":
        return ""
    if status == "waiting_human_gate":
        return "waiting for graph human gate decision"
    if status == "blocked":
        return "graph node result is blocked; inspect episode result and graph node error"
    if status == "failed":
        return "graph node result failed; inspect episode result before requeue or repair"
    return ""


def _result_summary(node_result: dict[str, Any]) -> str:
    summary = str(node_result.get("handoff_summary") or "").strip()
    if summary:
        return summary[:1200]
    error = dict(node_result.get("error") or {})
    reason = str(error.get("reason") or error.get("message") or "").strip()
    if reason:
        return reason[:1200]
    status = str(node_result.get("status") or "").strip() or "completed"
    return f"graph node result {status}"


def _work_products_from_result(
    *,
    binding: GraphNodeTaskBinding,
    episode: AgentExecutionEpisode,
    node_result: dict[str, Any],
    executor_result: dict[str, Any],
) -> tuple[WorkProduct, ...]:
    if not _result_has_product_payload(node_result):
        return ()
    status = str(node_result.get("status") or "")
    product = WorkProduct(
        work_product_id=stable_task_environment_id("workproduct", binding.node_task_environment_id, str(node_result.get("result_id") or "")),
        task_environment_id=binding.node_task_environment_id,
        task_instance_id=binding.task_instance_id,
        source_episode_id=episode.episode_id,
        product_domain="graph_node",
        product_kind="node_result",
        confidence="derived" if status == "completed" else "needs_human_review",
        status="candidate",
        stable_ref=f"{binding.graph_run_id}:{binding.node_id}:{binding.work_order_id}",
        payload={
            "node_result": _public_node_result_payload(node_result),
            "executor_result": _public_executor_projection(executor_result),
        },
        artifact_refs=tuple(str(item) for item in list(node_result.get("artifact_refs") or []) if str(item)),
        acceptance_claims=tuple(_acceptance_claims(node_result)),
        downstream_refs={
            "graph_run_id": binding.graph_run_id,
            "node_id": binding.node_id,
            "work_order_id": binding.work_order_id,
            "graph_binding_id": binding.binding_id,
        },
        metadata={
            "source_authority": "task_system.graph_node_task_binding_service",
            "node_result_id": str(node_result.get("result_id") or ""),
            "node_result_status": status,
        },
    )
    return (product,)


def _result_has_product_payload(node_result: dict[str, Any]) -> bool:
    return bool(
        dict(node_result.get("outputs") or {})
        or dict(node_result.get("decisions") or {})
        or list(node_result.get("artifact_refs") or [])
        or list(node_result.get("progress_receipts") or [])
        or list(node_result.get("artifact_materialization_receipts") or [])
        or list(node_result.get("memory_commit_receipts") or [])
    )


def _public_node_result_payload(node_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_id": str(node_result.get("result_id") or ""),
        "status": str(node_result.get("status") or ""),
        "outputs": dict(node_result.get("outputs") or {}),
        "decisions": dict(node_result.get("decisions") or {}),
        "artifact_refs": list(node_result.get("artifact_refs") or []),
        "progress_receipts": [dict(item) for item in list(node_result.get("progress_receipts") or []) if isinstance(item, dict)],
        "artifact_materialization_receipts": [
            dict(item)
            for item in list(node_result.get("artifact_materialization_receipts") or [])
            if isinstance(item, dict)
        ],
        "memory_commit_receipts": [dict(item) for item in list(node_result.get("memory_commit_receipts") or []) if isinstance(item, dict)],
        "handoff_summary": str(node_result.get("handoff_summary") or "")[:1200],
        "error": dict(node_result.get("error") or {}),
        "diagnostics": dict(node_result.get("diagnostics") or {}),
    }


def _public_executor_projection(executor_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(executor_result.get("ok") is True),
        "status": str(executor_result.get("status") or ""),
        "authority": str(executor_result.get("authority") or ""),
        "diagnostics": dict(executor_result.get("diagnostics") or {}),
    }


def _acceptance_claims(node_result: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics = dict(node_result.get("diagnostics") or {})
    quality_acceptance = dict(diagnostics.get("quality_acceptance") or {})
    if not quality_acceptance:
        return []
    return [
        {
            "claim_kind": "quality_acceptance",
            "accepted": bool(quality_acceptance.get("accepted") is True),
            "payload": quality_acceptance,
        }
    ]


def _context_payload(
    *,
    binding: GraphNodeTaskBinding,
    work_order: dict[str, Any],
    task_state_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_package = dict(work_order.get("input_package") or {})
    graph_slot = dict(work_order.get("graph_slot") or {})
    return {
        "scope": {
            "graph_run_id": binding.graph_run_id,
            "graph_id": binding.graph_id,
            "config_id": binding.config_id,
            "node_id": binding.node_id,
            "work_order_id": binding.work_order_id,
            "task_ref": binding.task_ref,
            "runtime_scope": _runtime_scope(work_order),
        },
        "resource_handles": {
            "artifact_space_ref": str(work_order.get("artifact_space_ref") or ""),
            "memory_space_ref": str(work_order.get("memory_space_ref") or ""),
            "file_access_table_refs": list(work_order.get("file_access_table_refs") or []),
            "artifact_repository_targets": list(work_order.get("artifact_repository_targets") or []),
            "memory_repository_targets": list(work_order.get("memory_repository_targets") or []),
        },
        "graph_context": {
            "graph_identity": dict(graph_slot.get("graph_identity") or {}),
            "task_contract": dict(graph_slot.get("task_contract") or {}),
            "agent_binding": dict(graph_slot.get("agent_binding") or {}),
            "edge_contracts": dict(graph_slot.get("edge_contracts") or {}),
            "memory_contract": dict(graph_slot.get("memory_contract") or {}),
            "loop_contract": dict(graph_slot.get("loop_contract") or {}),
            "output_contract": dict(graph_slot.get("output_contract") or {}),
            "runtime_controls": dict(graph_slot.get("runtime_controls") or {}),
            "node_identity": dict(input_package.get("node_identity") or {}),
            "initial_inputs": dict(input_package.get("initial_inputs") or {}),
            "loop_context": dict(input_package.get("loop_context") or {}),
            "inbound_context": [dict(item) for item in list(input_package.get("inbound_context") or []) if isinstance(item, dict)],
        },
        "task_state_context": dict(task_state_context or {}),
        "packet_policy": {
            "execution_boundary": dict(input_package.get("execution_boundary") or {}),
            "result_projection_policy": dict(binding.result_projection_policy or {}),
            "lease_policy": dict(binding.lease_policy or {}),
        },
    }


def _node_identity(work_order: dict[str, Any]) -> dict[str, Any]:
    return dict(dict(work_order.get("input_package") or {}).get("node_identity") or {})


def _runtime_scope(work_order: dict[str, Any]) -> dict[str, Any]:
    return dict(dict(work_order.get("input_package") or {}).get("runtime_scope") or {})


def _task_title(*, binding: GraphNodeTaskBinding, node_identity: dict[str, Any]) -> str:
    title = str(node_identity.get("title") or "").strip()
    return title or f"Graph node {binding.node_id}"


def _task_goal(*, work_order: dict[str, Any], node_identity: dict[str, Any]) -> str:
    instruction = str(work_order.get("message") or "").strip()
    if instruction:
        return instruction[:1200]
    title = str(node_identity.get("title") or node_identity.get("node_id") or work_order.get("node_id") or "").strip()
    return f"Execute graph node work order: {title or 'graph node'}"


def _agent_id(work_order: dict[str, Any]) -> str:
    graph_slot = dict(work_order.get("graph_slot") or {})
    agent_binding = dict(graph_slot.get("agent_binding") or {})
    return str(
        work_order.get("agent_id")
        or agent_binding.get("agent_id")
        or ""
    ).strip()


def _agent_profile_id(work_order: dict[str, Any], *, binding: GraphNodeTaskBinding) -> str:
    graph_slot = dict(work_order.get("graph_slot") or {})
    agent_binding = dict(graph_slot.get("agent_binding") or {})
    return str(
        work_order.get("agent_profile_id")
        or binding.agent_profile_id
        or agent_binding.get("agent_profile_id")
        or ""
    ).strip()


def _memory_refs(work_order: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    memory_space_ref = str(work_order.get("memory_space_ref") or "").strip()
    if memory_space_ref:
        refs.append(memory_space_ref)
    memory_contract = dict(dict(work_order.get("graph_slot") or {}).get("memory_contract") or {})
    refs.extend(str(item).strip() for item in list(memory_contract.get("memory_receipt_refs") or []) if str(item).strip())
    return list(dict.fromkeys(refs))


def _artifact_refs(work_order: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    artifact_space_ref = str(work_order.get("artifact_space_ref") or "").strip()
    if artifact_space_ref:
        refs.append(artifact_space_ref)
    for item in list(dict(work_order.get("artifact_view_request") or {}).get("artifact_refs") or []):
        if str(item).strip():
            refs.append(str(item).strip())
    return list(dict.fromkeys(refs))
