from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from task_system.episodes import AgentExecutionEpisode, EpisodeRepository

from .models import (
    TaskContextPackage,
    TaskControlSignal,
    TaskEnvironmentLease,
    TaskEvent,
    TaskInstance,
    TaskWorkEnvironment,
    context_package_hash,
    stable_task_environment_id,
)
from .repository import TaskEnvironmentRepository


@dataclass(frozen=True, slots=True)
class TaskEpisodePreparation:
    task_instance: TaskInstance
    task_environment: TaskWorkEnvironment
    episode: AgentExecutionEpisode
    context_package: TaskContextPackage
    event: TaskEvent
    authority: str = "task_system.task_episode_preparation"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "task_instance": self.task_instance.to_dict(),
            "task_environment": self.task_environment.to_dict(),
            "episode": self.episode.to_dict(),
            "context_package": self.context_package.to_dict(),
            "event": self.event.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class TaskEpisodeLeaseProjection:
    task_environment: TaskWorkEnvironment
    episode: AgentExecutionEpisode
    lease: TaskEnvironmentLease
    event: TaskEvent
    authority: str = "task_system.task_episode_lease_projection"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "task_environment": self.task_environment.to_dict(),
            "episode": self.episode.to_dict(),
            "lease": self.lease.to_dict(),
            "event": self.event.to_dict(),
        }


class TaskWorkEnvironmentService:
    authority = "task_system.task_work_environment_service"

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.repository = TaskEnvironmentRepository(base_dir)
        self.episode_repository = EpisodeRepository(base_dir)

    def create_task_environment(
        self,
        *,
        task_kind: str,
        title: str,
        goal: str,
        environment_kind: str,
        caller_kind: str,
        idempotency_key: str,
        owner_agent_id: str = "",
        owner_user_id: str = "",
        project_id: str = "",
        workspace_view: str = "",
        acceptance_contract_ref: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskWorkEnvironment:
        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("create_task_environment requires idempotency_key")
        now = time.time()
        task_instance_id = stable_task_environment_id("taskinst", task_kind, title, goal, key)
        task_environment_id = stable_task_environment_id("taskenv", task_instance_id, environment_kind, caller_kind, key)
        existing = self.repository.get_task_environment(task_environment_id)
        if existing is not None:
            return existing
        instance = TaskInstance(
            task_instance_id=task_instance_id,
            task_kind=task_kind,
            title=title,
            goal=goal,
            status="active",
            owner_agent_id=owner_agent_id,
            owner_user_id=owner_user_id,
            project_id=project_id,
            workspace_view=workspace_view,
            acceptance_contract_ref=acceptance_contract_ref,
            root_task_environment_id=task_environment_id,
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        environment = TaskWorkEnvironment(
            task_environment_id=task_environment_id,
            task_instance_id=task_instance_id,
            environment_kind=environment_kind,
            caller_kind=caller_kind,
            status="ready",
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        self.repository.upsert_task_instance(instance)
        self.repository.upsert_task_environment(environment)
        created_event = TaskEvent(
            event_id=stable_task_environment_id("taskevent", task_environment_id, "created", key),
            task_environment_id=task_environment_id,
            task_instance_id=task_instance_id,
            event_seq=0,
            event_type="task_environment_created",
            actor_kind="system",
            idempotency_key=f"create:{key}",
            payload={
                "task_kind": task_kind,
                "environment_kind": environment_kind,
                "caller_kind": caller_kind,
            },
            created_at=now,
        )
        self.repository.append_event(created_event, expected_revision=0, snapshot_patch={"status": "ready"})
        return self.repository.get_task_environment(task_environment_id) or environment

    def request_control_signal(
        self,
        *,
        task_environment_id: str,
        signal_kind: str,
        requested_by: str,
        reason: str = "",
        payload: dict[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        environment = self._require_environment(task_environment_id)
        key = str(idempotency_key or "").strip() or stable_task_environment_id(
            "controlkey",
            environment.task_environment_id,
            signal_kind,
            requested_by,
            reason,
        )
        now = time.time()
        signal_id = stable_task_environment_id("tasksignal", environment.task_environment_id, signal_kind, key)
        existing = self.repository.get_control_signal(signal_id)
        signal = TaskControlSignal(
            signal_id=signal_id,
            task_environment_id=environment.task_environment_id,
            signal_kind=signal_kind,  # type: ignore[arg-type]
            requested_by=str(requested_by or "user"),
            reason=str(reason or ""),
            payload=dict(payload or {}),
            created_at=now,
            idempotency_key=key,
        )
        stored = existing if existing is not None else self.repository.upsert_control_signal(signal)
        event = self.repository.append_event(
            TaskEvent(
                event_id=stable_task_environment_id(
                    "taskevent",
                    environment.task_environment_id,
                    "task_control_signal_requested",
                    key,
                ),
                task_environment_id=environment.task_environment_id,
                task_instance_id=environment.task_instance_id,
                event_seq=0,
                event_type="task_control_signal_requested",
                actor_kind="user" if str(requested_by or "").strip() == "user" else "system",
                actor_id=str(requested_by or ""),
                idempotency_key=f"control-signal-requested:{key}",
                payload={
                    "signal_id": stored.signal_id,
                    "signal_kind": stored.signal_kind,
                    "reason": stored.reason,
                    "requested_by": stored.requested_by,
                    "status": stored.status,
                },
                refs={"control_signal_ref": stored.signal_id},
                created_at=now,
            )
        )
        return {
            "authority": "task_system.task_work_environment_service.control_signal_requested",
            "task_environment": (self.repository.get_task_environment(environment.task_environment_id) or environment).to_dict(),
            "control_signal": stored.to_dict(),
            "event": event.to_dict(),
        }

    def record_control_signal_handling(
        self,
        *,
        signal_id: str,
        status: str,
        handling_result: dict[str, Any] | None = None,
        handler_episode_id: str = "",
    ) -> dict[str, Any]:
        existing = self.repository.get_control_signal(signal_id)
        if existing is None:
            raise KeyError(f"task control signal not found: {signal_id}")
        environment = self._require_environment(existing.task_environment_id)
        normalized_status = str(status or "").strip() or "handled"
        if normalized_status not in {"handled", "failed", "canceled"}:
            raise ValueError("control signal handling status must be handled, failed, or canceled")
        now = time.time()
        payload = dict(existing.payload or {})
        payload["handling_result"] = dict(handling_result or {})
        stored = self.repository.upsert_control_signal(
            replace(
                existing,
                status=normalized_status,  # type: ignore[arg-type]
                handled_at=now,
                handler_episode_id=str(handler_episode_id or existing.handler_episode_id or ""),
                payload=payload,
            )
        )
        event = self.repository.append_event(
            TaskEvent(
                event_id=stable_task_environment_id(
                    "taskevent",
                    environment.task_environment_id,
                    "task_control_signal_handled",
                    stored.signal_id,
                    normalized_status,
                ),
                task_environment_id=environment.task_environment_id,
                task_instance_id=environment.task_instance_id,
                event_seq=0,
                event_type="task_control_signal_handled",
                actor_kind="system",
                source_episode_id=stored.handler_episode_id,
                idempotency_key=f"control-signal-handled:{stored.signal_id}:{normalized_status}",
                payload={
                    "signal_id": stored.signal_id,
                    "signal_kind": stored.signal_kind,
                    "status": stored.status,
                    "handling_result": dict(handling_result or {}),
                },
                refs={"control_signal_ref": stored.signal_id},
                created_at=now,
            ),
            snapshot_patch=_control_signal_snapshot_patch(stored.signal_kind, normalized_status),
        )
        return {
            "authority": "task_system.task_work_environment_service.control_signal_handled",
            "task_environment": (self.repository.get_task_environment(environment.task_environment_id) or environment).to_dict(),
            "control_signal": stored.to_dict(),
            "event": event.to_dict(),
        }

    def prepare_task_episode(
        self,
        *,
        task_environment_id: str,
        agent_id: str = "",
        agent_profile_id: str = "",
        invocation_kind: str = "task_episode",
        caller_kind: str = "task_system",
        role_contract: str = "",
        scope: dict[str, Any] | None = None,
        acceptance: dict[str, Any] | None = None,
        resource_handles: dict[str, Any] | None = None,
        graph_context: dict[str, Any] | None = None,
        project_network_handles: dict[str, Any] | None = None,
        output_contract: dict[str, Any] | None = None,
        packet_policy: dict[str, Any] | None = None,
        continuation_hint: str = "",
        idempotency_key: str = "",
    ) -> TaskEpisodePreparation:
        environment = self._require_environment(task_environment_id)
        if environment.status in {"completed", "archived", "aborted", "failed"}:
            raise ValueError(f"terminal task environment cannot prepare episode: {environment.status}")
        now = time.time()
        active_lease = self._active_lease(environment.task_environment_id, now=now)
        if active_lease is not None:
            raise ValueError("task environment already has an active lease")
        task_instance = self.repository.get_task_instance(environment.task_instance_id)
        if task_instance is None:
            raise KeyError(f"task instance not found: {environment.task_instance_id}")
        key = str(idempotency_key or "").strip() or stable_task_environment_id(
            "episodekey",
            environment.task_environment_id,
            environment.revision,
            environment.latest_context_package_id,
            invocation_kind,
            agent_profile_id or task_instance.owner_agent_id,
        )
        episode_id = stable_task_environment_id("episode", environment.task_environment_id, key)
        resolved_agent_id = str(agent_id or task_instance.owner_agent_id or "task_environment_worker")
        resolved_agent_profile_id = str(agent_profile_id or task_instance.owner_agent_id or "task_environment_worker")
        episode = self.episode_repository.upsert_episode(
            AgentExecutionEpisode(
                episode_id=episode_id,
                task_environment_id=environment.task_environment_id,
                task_instance_id=environment.task_instance_id,
                agent_id=resolved_agent_id,
                agent_profile_id=resolved_agent_profile_id,
                invocation_kind=str(invocation_kind or "task_episode"),
                caller_kind=str(caller_kind or environment.caller_kind or "task_system"),
                status="scheduled",
                continuation_hint=str(continuation_hint or environment.continuation_hint or ""),
                diagnostics={
                    "task_environment_id": environment.task_environment_id,
                    "task_instance_id": environment.task_instance_id,
                    "source_authority": f"{self.authority}.prepare_task_episode",
                    "idempotency_key": key,
                },
            )
        )
        context_payload = _context_payload_for_episode(
            task_instance=task_instance,
            environment=environment,
            role_contract=role_contract,
            scope=scope,
            acceptance=acceptance,
            resource_handles=resource_handles,
            graph_context=graph_context,
            project_network_handles=project_network_handles,
            output_contract=output_contract,
            packet_policy=packet_policy,
            continuation_hint=continuation_hint,
        )
        context_package = self.repository.upsert_context_package(
            TaskContextPackage(
                package_id=stable_task_environment_id("taskctx", environment.task_environment_id, episode.episode_id, key),
                task_environment_id=environment.task_environment_id,
                episode_id=episode.episode_id,
                package_hash=context_package_hash(context_payload),
                role_contract=str(context_payload.get("role_contract") or ""),
                goal=str(context_payload.get("goal") or ""),
                scope=dict(context_payload.get("scope") or {}),
                acceptance=dict(context_payload.get("acceptance") or {}),
                stable_context_ref=str(context_payload.get("stable_context_ref") or ""),
                current_context_ref=str(context_payload.get("current_context_ref") or ""),
                memory_refs=tuple(str(item) for item in list(context_payload.get("memory_refs") or []) if str(item)),
                artifact_refs=tuple(str(item) for item in list(context_payload.get("artifact_refs") or []) if str(item)),
                resource_handles=dict(context_payload.get("resource_handles") or {}),
                graph_context=dict(context_payload.get("graph_context") or {}),
                project_network_handles=dict(context_payload.get("project_network_handles") or {}),
                continuation_hint=str(context_payload.get("continuation_hint") or ""),
                output_contract=dict(context_payload.get("output_contract") or {}),
                packet_policy=dict(context_payload.get("packet_policy") or {}),
                metadata={
                    "source_authority": f"{self.authority}.prepare_task_episode",
                    "idempotency_key": key,
                },
            )
        )
        episode = self.episode_repository.upsert_episode(
            replace(
                episode,
                input_context_package_id=context_package.package_id,
                diagnostics={
                    **dict(episode.diagnostics or {}),
                    "context_package_id": context_package.package_id,
                },
            )
        )
        event = self.repository.append_event(
            TaskEvent(
                event_id=stable_task_environment_id(
                    "taskevent",
                    environment.task_environment_id,
                    "task_episode_prepared",
                    key,
                ),
                task_environment_id=environment.task_environment_id,
                task_instance_id=environment.task_instance_id,
                event_seq=0,
                event_type="task_episode_prepared",
                actor_kind="system",
                source_episode_id=episode.episode_id,
                idempotency_key=f"task-episode-prepared:{key}",
                payload={
                    "episode_id": episode.episode_id,
                    "context_package_id": context_package.package_id,
                    "agent_id": resolved_agent_id,
                    "agent_profile_id": resolved_agent_profile_id,
                    "invocation_kind": episode.invocation_kind,
                },
                refs={
                    "task_environment_ref": environment.task_environment_id,
                    "episode_ref": episode.episode_id,
                    "context_package_ref": context_package.package_id,
                },
                created_at=now,
            ),
            snapshot_patch={
                **({"status": "ready"} if environment.status == "created" else {}),
                "current_phase": "task_episode",
                "current_step": "prepared",
                "progress_label": "task episode context package prepared",
                "latest_context_package_id": context_package.package_id,
                "continuation_hint": context_package.continuation_hint,
            },
        )
        latest_environment = self.repository.get_task_environment(environment.task_environment_id) or environment
        return TaskEpisodePreparation(
            task_instance=task_instance,
            task_environment=latest_environment,
            episode=episode,
            context_package=context_package,
            event=event,
        )

    def acquire_episode_lease(
        self,
        *,
        task_environment_id: str,
        episode_id: str,
        lease_kind: str = "task_episode_execution",
        holder_kind: str = "task_system",
        holder_id: str = "",
        ttl_seconds: float = 2 * 60 * 60,
        idempotency_key: str = "",
        event_type: str = "task_episode_lease_acquired",
        current_phase: str = "task_episode",
        current_step: str = "running",
        progress_label: str = "task episode lease active",
        source_graph_run_id: str = "",
        source_work_order_id: str = "",
        event_payload: dict[str, Any] | None = None,
        event_refs: dict[str, Any] | None = None,
    ) -> TaskEpisodeLeaseProjection:
        environment = self._require_environment(task_environment_id)
        if environment.status in {"completed", "archived", "aborted", "failed"}:
            raise ValueError(f"terminal task environment cannot acquire lease: {environment.status}")
        episode = self.episode_repository.get_episode(episode_id)
        if episode is None:
            raise KeyError(f"episode not found: {episode_id}")
        if episode.task_environment_id != environment.task_environment_id:
            raise ValueError("episode does not belong to task environment")
        now = time.time()
        key = str(idempotency_key or "").strip() or stable_task_environment_id(
            "leasekey",
            environment.task_environment_id,
            episode.episode_id,
            lease_kind,
            holder_kind,
            holder_id,
        )
        lease_id = stable_task_environment_id("lease", environment.task_environment_id, episode.episode_id, key)
        active_lease = self._active_lease(environment.task_environment_id, now=now)
        if active_lease is not None and active_lease.lease_id != lease_id:
            raise ValueError("task environment already has an active lease")
        existing = self.repository.get_lease(lease_id)
        lease = self.repository.upsert_lease(
            replace(
                existing,
                status="active",
                released_at=0,
                release_reason="",
                expires_at=now + max(1.0, float(ttl_seconds or 1.0)),
                heartbeat_at=now,
            )
            if existing is not None
            else TaskEnvironmentLease(
                lease_id=lease_id,
                task_environment_id=environment.task_environment_id,
                episode_id=episode.episode_id,
                lease_kind=str(lease_kind or "task_episode_execution"),
                holder_kind=str(holder_kind or "task_system"),
                holder_id=str(holder_id or episode.episode_id),
                status="active",
                acquired_at=now,
                expires_at=now + max(1.0, float(ttl_seconds or 1.0)),
                heartbeat_at=now,
                idempotency_key=key,
                metadata={
                    "source_authority": f"{self.authority}.acquire_episode_lease",
                    **({"source_graph_run_id": source_graph_run_id} if source_graph_run_id else {}),
                    **({"source_work_order_id": source_work_order_id} if source_work_order_id else {}),
                },
            )
        )
        episode = self.episode_repository.upsert_episode(
            replace(
                episode,
                status="running",
                lease_id=lease.lease_id,
                started_at=episode.started_at or now,
                diagnostics={
                    **dict(episode.diagnostics or {}),
                    "lease_id": lease.lease_id,
                    "source_authority": f"{self.authority}.acquire_episode_lease",
                },
            )
        )
        event = self.repository.append_event(
            TaskEvent(
                event_id=stable_task_environment_id("taskevent", environment.task_environment_id, event_type, lease.lease_id),
                task_environment_id=environment.task_environment_id,
                task_instance_id=environment.task_instance_id,
                event_seq=0,
                event_type=str(event_type or "task_episode_lease_acquired"),
                actor_kind="system",
                source_episode_id=episode.episode_id,
                source_graph_run_id=str(source_graph_run_id or ""),
                source_work_order_id=str(source_work_order_id or ""),
                idempotency_key=f"{event_type or 'task_episode_lease_acquired'}:{lease.lease_id}",
                payload={
                    "lease_id": lease.lease_id,
                    "episode_id": episode.episode_id,
                    "lease_kind": lease.lease_kind,
                    "holder_kind": lease.holder_kind,
                    "holder_id": lease.holder_id,
                    **dict(event_payload or {}),
                },
                refs={
                    "task_environment_ref": environment.task_environment_id,
                    "episode_ref": episode.episode_id,
                    "lease_ref": lease.lease_id,
                    **dict(event_refs or {}),
                },
                created_at=now,
            ),
            snapshot_patch={
                "status": "leased",
                "active_episode_id": episode.episode_id,
                "active_lease_id": lease.lease_id,
                "current_phase": str(current_phase or "task_episode"),
                "current_step": str(current_step or "running"),
                "progress_label": str(progress_label or "task episode lease active"),
            },
        )
        latest_environment = self.repository.get_task_environment(environment.task_environment_id) or environment
        return TaskEpisodeLeaseProjection(
            task_environment=latest_environment,
            episode=episode,
            lease=lease,
            event=event,
        )

    def release_episode_lease(
        self,
        *,
        task_environment_id: str,
        lease_id: str,
        release_reason: str = "task_episode_finished",
        event_type: str = "task_episode_lease_released",
        current_phase: str = "task_episode",
        current_step: str = "lease_released",
        progress_label: str = "",
        source_graph_run_id: str = "",
        source_work_order_id: str = "",
        event_payload: dict[str, Any] | None = None,
        event_refs: dict[str, Any] | None = None,
    ) -> TaskEpisodeLeaseProjection:
        environment = self._require_environment(task_environment_id)
        lease = self.repository.get_lease(lease_id)
        if lease is None:
            raise KeyError(f"task environment lease not found: {lease_id}")
        if lease.task_environment_id != environment.task_environment_id:
            raise ValueError("lease does not belong to task environment")
        now = time.time()
        released = self.repository.upsert_lease(
            replace(
                lease,
                status="released",
                released_at=now,
                release_reason=str(release_reason or "task_episode_finished"),
            )
        )
        episode = self.episode_repository.get_episode(lease.episode_id)
        if episode is None:
            raise KeyError(f"episode not found: {lease.episode_id}")
        if episode.status == "running":
            episode = self.episode_repository.upsert_episode(
                replace(
                    episode,
                    status="interrupted",
                    terminal_reason=str(release_reason or "task_episode_finished"),
                    ended_at=now,
                    diagnostics={
                        **dict(episode.diagnostics or {}),
                        "lease_released_at": now,
                        "release_reason": str(release_reason or "task_episode_finished"),
                        "source_authority": f"{self.authority}.release_episode_lease",
                    },
                )
            )
        snapshot_patch = {"active_lease_id": ""}
        if environment.status == "leased" and environment.active_lease_id == lease.lease_id:
            snapshot_patch.update(
                {
                    "status": "ready",
                    "current_phase": str(current_phase or "task_episode"),
                    "current_step": str(current_step or "lease_released"),
                    "progress_label": str(progress_label or release_reason or "task episode lease released"),
                }
            )
        event = self.repository.append_event(
            TaskEvent(
                event_id=stable_task_environment_id("taskevent", environment.task_environment_id, event_type, lease.lease_id),
                task_environment_id=environment.task_environment_id,
                task_instance_id=environment.task_instance_id,
                event_seq=0,
                event_type=str(event_type or "task_episode_lease_released"),
                actor_kind="system",
                source_episode_id=episode.episode_id,
                source_graph_run_id=str(source_graph_run_id or ""),
                source_work_order_id=str(source_work_order_id or ""),
                idempotency_key=f"{event_type or 'task_episode_lease_released'}:{lease.lease_id}",
                payload={
                    "lease_id": released.lease_id,
                    "episode_id": episode.episode_id,
                    "release_reason": str(release_reason or "task_episode_finished"),
                    **dict(event_payload or {}),
                },
                refs={
                    "task_environment_ref": environment.task_environment_id,
                    "episode_ref": episode.episode_id,
                    "lease_ref": released.lease_id,
                    **dict(event_refs or {}),
                },
                created_at=now,
            ),
            snapshot_patch=snapshot_patch,
        )
        latest_environment = self.repository.get_task_environment(environment.task_environment_id) or environment
        return TaskEpisodeLeaseProjection(
            task_environment=latest_environment,
            episode=episode,
            lease=released,
            event=event,
        )

    def recover_stale_leases(
        self,
        *,
        now: float | None = None,
        limit: int = 200,
        reason: str = "task_environment_lease_expired",
    ) -> dict[str, Any]:
        from .view_service import TaskEnvironmentViewService

        cutoff = time.time() if now is None else float(now)
        recovered: list[dict[str, Any]] = []
        view_service = TaskEnvironmentViewService(self.base_dir)
        for lease in self.repository.list_expired_active_leases(now=cutoff, limit=limit):
            environment = self.repository.get_task_environment(lease.task_environment_id)
            if environment is None:
                continue
            expired = self.repository.upsert_lease(
                replace(
                    lease,
                    status="expired",
                    released_at=cutoff,
                    release_reason=str(reason or "task_environment_lease_expired"),
                    metadata={
                        **dict(lease.metadata or {}),
                        "expired_by": self.authority,
                        "expired_at": cutoff,
                    },
                )
            )
            episode = self.episode_repository.get_episode(lease.episode_id)
            episode_payload: dict[str, Any] = {}
            if episode is not None and episode.status in {"scheduled", "running", "waiting_tool", "waiting_user"}:
                episode = self.episode_repository.upsert_episode(
                    replace(
                        episode,
                        status="interrupted",
                        terminal_reason=str(reason or "task_environment_lease_expired"),
                        ended_at=cutoff,
                        diagnostics={
                            **dict(episode.diagnostics or {}),
                            "lease_id": lease.lease_id,
                            "lease_expired_at": cutoff,
                            "source_authority": f"{self.authority}.recover_stale_leases",
                        },
                    )
                )
                episode_payload = episode.to_dict()
            snapshot_patch = {"active_lease_id": ""}
            if environment.status == "leased" and environment.active_lease_id == lease.lease_id:
                snapshot_patch.update(
                    {
                        "status": "paused",
                        "current_step": "lease_expired",
                        "progress_label": "task environment lease expired; explicit recovery is required",
                        "recovery_action": "resume_task_environment",
                        "continuation_hint": environment.continuation_hint
                        or "The previous episode lease expired; rebuild a fresh context package before resuming.",
                    }
                )
            event = self.repository.append_event(
                TaskEvent(
                    event_id=stable_task_environment_id(
                        "taskevent",
                        environment.task_environment_id,
                        "task_environment_lease_expired",
                        lease.lease_id,
                    ),
                    task_environment_id=environment.task_environment_id,
                    task_instance_id=environment.task_instance_id,
                    event_seq=0,
                    event_type="task_environment_lease_expired",
                    actor_kind="system",
                    source_episode_id=lease.episode_id,
                    source_work_order_id=lease.holder_id if lease.holder_kind == "graph_system_work_order" else "",
                    idempotency_key=f"lease-expired:{lease.lease_id}",
                    payload={
                        "lease_id": lease.lease_id,
                        "lease_kind": lease.lease_kind,
                        "holder_kind": lease.holder_kind,
                        "holder_id": lease.holder_id,
                        "expires_at": lease.expires_at,
                        "recovered_at": cutoff,
                        "reason": str(reason or "task_environment_lease_expired"),
                    },
                    refs={
                        "lease_ref": lease.lease_id,
                        "episode_ref": lease.episode_id,
                        "task_environment_ref": environment.task_environment_id,
                    },
                    created_at=cutoff,
                ),
                snapshot_patch=snapshot_patch,
            )
            recovery_projection = view_service.task_environment_recovery_projection(environment.task_environment_id)
            recovered.append(
                {
                    "task_environment_id": environment.task_environment_id,
                    "lease": expired.to_dict(),
                    "episode": episode_payload,
                    "event": event.to_dict(),
                    "recovery_projection": recovery_projection,
                }
            )
        return {
            "authority": "task_system.task_work_environment_service.stale_lease_recovery",
            "recovered_leases": recovered,
            "summary": {
                "recovered_count": len(recovered),
                "limit": limit,
                "recovered_at": cutoff,
            },
        }

    def _require_environment(self, task_environment_id: str) -> TaskWorkEnvironment:
        target = str(task_environment_id or "").strip()
        if not target:
            raise ValueError("task_environment_id is required")
        environment = self.repository.get_task_environment(target)
        if environment is None:
            raise KeyError(f"task environment not found: {target}")
        return environment

    def _active_lease(self, task_environment_id: str, *, now: float) -> Any | None:
        for lease in self.repository.list_leases(task_environment_id, limit=20):
            if lease.status != "active":
                continue
            if float(lease.expires_at or 0.0) > now:
                return lease
        return None


def _control_signal_snapshot_patch(signal_kind: str, status: str) -> dict[str, Any]:
    if status != "handled":
        return {}
    if signal_kind == "pause_requested":
        return {
            "status": "paused",
            "current_step": "paused",
            "progress_label": "task environment paused by control signal",
        }
    if signal_kind == "resume_requested":
        return {
            "status": "ready",
            "current_step": "ready",
            "blocked_reason": "",
            "progress_label": "task environment resumed by control signal",
        }
    if signal_kind in {"stop_requested", "abort_requested"}:
        return {
            "status": "archived",
            "current_step": signal_kind,
            "progress_label": "task environment closed by control signal",
        }
    return {}


def _context_payload_for_episode(
    *,
    task_instance: TaskInstance,
    environment: TaskWorkEnvironment,
    role_contract: str,
    scope: dict[str, Any] | None,
    acceptance: dict[str, Any] | None,
    resource_handles: dict[str, Any] | None,
    graph_context: dict[str, Any] | None,
    project_network_handles: dict[str, Any] | None,
    output_contract: dict[str, Any] | None,
    packet_policy: dict[str, Any] | None,
    continuation_hint: str,
) -> dict[str, Any]:
    metadata = dict(environment.metadata or {})
    contract = dict(metadata.get("contract") or {})
    working_scope = dict(contract.get("working_scope") or {})
    acceptance_contract = dict(contract.get("acceptance_contract") or {})
    resolved_scope = {
        "task_environment_id": environment.task_environment_id,
        "task_instance_id": environment.task_instance_id,
        "task_kind": task_instance.task_kind,
        "environment_kind": environment.environment_kind,
        "caller_kind": environment.caller_kind,
        "project_id": task_instance.project_id,
        "workspace_view": task_instance.workspace_view,
        **working_scope,
        **dict(scope or {}),
    }
    resolved_acceptance = {
        **({"acceptance_contract_ref": task_instance.acceptance_contract_ref} if task_instance.acceptance_contract_ref else {}),
        **acceptance_contract,
        **dict(acceptance or {}),
    }
    return {
        "role_contract": str(role_contract or _default_role_contract(task_instance, environment)),
        "goal": str(task_instance.goal or environment.continuation_hint or ""),
        "scope": _drop_empty_context(resolved_scope),
        "acceptance": _drop_empty_context(resolved_acceptance),
        "stable_context_ref": str(metadata.get("stable_context_ref") or ""),
        "current_context_ref": str(environment.latest_context_package_id or metadata.get("current_context_ref") or ""),
        "memory_refs": _string_refs(metadata.get("memory_refs")),
        "artifact_refs": _string_refs(metadata.get("artifact_refs")),
        "resource_handles": {
            **dict(metadata.get("resource_handles") or {}),
            **dict(resource_handles or {}),
        },
        "graph_context": {
            **dict(metadata.get("graph_context") or {}),
            **dict(graph_context or {}),
        },
        "project_network_handles": {
            **dict(metadata.get("project_network_handles") or {}),
            **dict(project_network_handles or {}),
        },
        "continuation_hint": str(continuation_hint or environment.continuation_hint or ""),
        "output_contract": {
            **dict(contract.get("output_contract") or {}),
            **dict(output_contract or {}),
        },
        "packet_policy": {
            "context_scope": "task_episode",
            "source": "task_work_environment",
            **dict(packet_policy or {}),
        },
        "authority": "task_system.task_context_package_payload",
    }


def _default_role_contract(task_instance: TaskInstance, environment: TaskWorkEnvironment) -> str:
    title = str(task_instance.title or "当前任务").strip()
    return "\n".join(
        [
            f"你是一名任务执行者，正在推进任务：{title}。",
            "你只负责依据当前任务环境中的目标、范围、上下文包和验收要求推进本次 episode。",
            "你不负责改写任务目标、绕过控制信号、伪造证据，或把未验证的自然语言总结当作结构化产物。",
            "你必须输出清晰的进度、阻塞项、证据引用和可归并的结果；如果无法继续，说明缺失的资源或需要的用户决策。",
            f"当前任务环境：{environment.task_environment_id}。",
        ]
    )


def _string_refs(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace(",", "\n").splitlines() if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _drop_empty_context(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(payload or {}).items() if value not in ("", None, [], {}, ())}
