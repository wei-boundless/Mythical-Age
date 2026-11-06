from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from task_system.episodes import AgentExecutionEpisode, EpisodeRepository, EpisodeResult
from task_system.work_environments.models import (
    TaskCheckpoint,
    TaskEnvironmentLease,
    TaskEvent,
    TaskWorkEnvironment,
    TaskPlan,
    TaskStateProposal,
    TaskTodoItem,
    context_package_hash,
    stable_task_environment_id,
)
from task_system.work_environments.repository import TaskEnvironmentRepository
from task_system.work_environments.service import TaskWorkEnvironmentService
from task_system.work_products import WorkProduct, WorkProductRepository


@dataclass(frozen=True, slots=True)
class TaskReductionResult:
    episode: AgentExecutionEpisode
    episode_result: EpisodeResult
    work_products: tuple[WorkProduct, ...] = ()
    event: TaskEvent | None = None
    checkpoint: TaskCheckpoint | None = None
    lease_release: Any | None = None
    task_plans: tuple[TaskPlan, ...] = ()
    todo_items: tuple[TaskTodoItem, ...] = ()
    state_proposals: tuple[TaskStateProposal, ...] = ()
    events: tuple[TaskEvent, ...] = ()
    authority: str = "task_system.task_reducer_result"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "episode": self.episode.to_dict(),
            "episode_result": self.episode_result.to_dict(),
            "work_products": [item.to_dict() for item in self.work_products],
            "event": self.event.to_dict() if self.event is not None else {},
            "checkpoint": self.checkpoint.to_dict() if self.checkpoint is not None else {},
            "lease_release": self.lease_release.to_dict() if hasattr(self.lease_release, "to_dict") else dict(self.lease_release or {}),
            "task_plans": [item.to_dict() for item in self.task_plans],
            "todo_items": [item.to_dict() for item in self.todo_items],
            "state_proposals": [item.to_dict() for item in self.state_proposals],
            "events": [item.to_dict() for item in self.events],
        }


class TaskReducer:
    authority = "task_system.task_reducer"

    def __init__(self, base_dir: str | Path) -> None:
        self.task_repository = TaskEnvironmentRepository(base_dir)
        self.episode_repository = EpisodeRepository(base_dir)
        self.work_product_repository = WorkProductRepository(base_dir)
        self.task_service = TaskWorkEnvironmentService(base_dir)

    def reduce_episode_result(
        self,
        *,
        episode: AgentExecutionEpisode,
        episode_status: str,
        terminal_reason: str,
        episode_result: EpisodeResult,
        work_product_candidates: tuple[WorkProduct, ...] = (),
        event: TaskEvent | None = None,
        snapshot_patch: dict[str, Any] | None = None,
        episode_diagnostics_patch: dict[str, Any] | None = None,
        ended_at: float | None = None,
        release_reason: str = "",
        release_event_type: str = "task_episode_lease_released",
        release_current_phase: str = "task_episode",
        release_current_step: str = "lease_released",
        release_progress_label: str = "",
        release_source_graph_run_id: str = "",
        release_source_work_order_id: str = "",
        release_event_payload: dict[str, Any] | None = None,
        release_event_refs: dict[str, Any] | None = None,
    ) -> TaskReductionResult:
        now = time.time() if ended_at is None else float(ended_at)
        environment, leased_episode, active_lease = self._validate_episode_owns_active_lease(
            episode=episode,
            now=now,
        )
        self._validate_episode_result_scope(
            episode=leased_episode,
            episode_result=episode_result,
            work_product_candidates=work_product_candidates,
            event=event,
        )
        stored_episode = self.episode_repository.upsert_episode(
            replace(
                leased_episode,
                status=str(episode_status or episode.status or "interrupted"),  # type: ignore[arg-type]
                terminal_reason=str(terminal_reason or leased_episode.terminal_reason or ""),
                ended_at=now,
                diagnostics={
                    **dict(leased_episode.diagnostics or {}),
                    **dict(episode_diagnostics_patch or {}),
                    "task_environment_active_lease_id": active_lease.lease_id,
                    "reduced_by": self.authority,
                },
            )
        )
        stored_products = tuple(
            self.work_product_repository.upsert_work_product(product)
            for product in work_product_candidates
        )
        result_with_product_refs = self._episode_result_with_product_refs(
            episode_result,
            work_products=stored_products,
        )
        stored_result = self.episode_repository.upsert_episode_result(result_with_product_refs)
        stored_event = (
            self.task_repository.append_event(event, snapshot_patch=dict(snapshot_patch or {}))
            if event is not None
            else None
        )
        stored_state_proposals, state_events = self._apply_state_update_proposals(
            episode=stored_episode,
            episode_result=stored_result,
        )
        stored_plans, plan_events = self._apply_plan_patch(
            episode=stored_episode,
            episode_result=stored_result,
        )
        stored_todos, todo_events = self._apply_todo_patch(
            episode=stored_episode,
            episode_result=stored_result,
            active_plan_id=stored_plans[0].plan_id if stored_plans else self._active_plan_id(stored_episode.task_environment_id),
        )
        reducer_events = tuple(item for item in (stored_event, *state_events, *plan_events, *todo_events) if item is not None)
        stored_checkpoint = self._write_reducer_commit_checkpoint(
            episode=stored_episode,
            episode_result=stored_result,
            work_products=stored_products,
            event=reducer_events[-1] if reducer_events else None,
        )
        lease_release = self.task_service.release_episode_lease(
            task_environment_id=environment.task_environment_id,
            lease_id=active_lease.lease_id,
            release_reason=str(release_reason or terminal_reason or "task_episode_reduced"),
            event_type=str(release_event_type or "task_episode_lease_released"),
            current_phase=str(release_current_phase or "task_episode"),
            current_step=str(release_current_step or "lease_released"),
            progress_label=str(release_progress_label or release_reason or terminal_reason or "task episode reduced"),
            source_graph_run_id=str(release_source_graph_run_id or ""),
            source_work_order_id=str(release_source_work_order_id or ""),
            event_payload=dict(release_event_payload or {}),
            event_refs=dict(release_event_refs or {}),
        )
        return TaskReductionResult(
            episode=stored_episode,
            episode_result=stored_result,
            work_products=stored_products,
            event=stored_event,
            checkpoint=stored_checkpoint,
            lease_release=lease_release,
            task_plans=stored_plans,
            todo_items=stored_todos,
            state_proposals=stored_state_proposals,
            events=reducer_events,
        )

    def _validate_episode_owns_active_lease(
        self,
        *,
        episode: AgentExecutionEpisode,
        now: float,
    ) -> tuple[TaskWorkEnvironment, AgentExecutionEpisode, TaskEnvironmentLease]:
        environment = self.task_repository.get_task_environment(episode.task_environment_id)
        if environment is None:
            raise KeyError(f"task environment not found: {episode.task_environment_id}")
        if environment.task_instance_id != episode.task_instance_id:
            raise ValueError("AgentExecutionEpisode task_instance_id does not match TaskWorkEnvironment")
        stored_episode = self.episode_repository.get_episode(episode.episode_id)
        if stored_episode is None:
            raise KeyError(f"episode not found: {episode.episode_id}")
        if stored_episode.task_environment_id != environment.task_environment_id:
            raise ValueError("stored AgentExecutionEpisode does not belong to TaskWorkEnvironment")
        if stored_episode.task_instance_id != environment.task_instance_id:
            raise ValueError("stored AgentExecutionEpisode task_instance_id does not match TaskWorkEnvironment")
        active_lease_id = str(environment.active_lease_id or "").strip()
        if not active_lease_id:
            raise ValueError("TaskReducer requires TaskWorkEnvironment active_lease_id")
        if str(environment.active_episode_id or "").strip() != stored_episode.episode_id:
            raise ValueError("TaskReducer requires active_episode_id to match AgentExecutionEpisode")
        if str(stored_episode.lease_id or "").strip() != active_lease_id:
            raise ValueError("TaskReducer requires AgentExecutionEpisode lease_id to match active_lease_id")
        active_lease = self.task_repository.get_lease(active_lease_id)
        if active_lease is None:
            raise KeyError(f"task environment active lease not found: {active_lease_id}")
        if active_lease.task_environment_id != environment.task_environment_id:
            raise ValueError("active lease does not belong to TaskWorkEnvironment")
        if active_lease.episode_id != stored_episode.episode_id:
            raise ValueError("active lease episode_id does not match AgentExecutionEpisode")
        if active_lease.status != "active":
            raise ValueError(f"TaskReducer requires active lease, got {active_lease.status}")
        if float(active_lease.expires_at or 0.0) <= float(now):
            raise ValueError("TaskReducer cannot reduce an expired task environment lease")
        return environment, stored_episode, active_lease

    def _validate_episode_result_scope(
        self,
        *,
        episode: AgentExecutionEpisode,
        episode_result: EpisodeResult,
        work_product_candidates: tuple[WorkProduct, ...],
        event: TaskEvent | None,
    ) -> None:
        if episode_result.episode_id != episode.episode_id:
            raise ValueError("EpisodeResult episode_id does not match AgentExecutionEpisode")
        if episode_result.task_environment_id != episode.task_environment_id:
            raise ValueError("EpisodeResult task_environment_id does not match AgentExecutionEpisode")
        for product in work_product_candidates:
            if product.task_environment_id != episode.task_environment_id:
                raise ValueError("WorkProduct task_environment_id does not match AgentExecutionEpisode")
            if product.task_instance_id != episode.task_instance_id:
                raise ValueError("WorkProduct task_instance_id does not match AgentExecutionEpisode")
            if product.source_episode_id != episode.episode_id:
                raise ValueError("WorkProduct source_episode_id does not match AgentExecutionEpisode")
        if event is not None:
            if event.task_environment_id != episode.task_environment_id:
                raise ValueError("TaskEvent task_environment_id does not match AgentExecutionEpisode")
            if event.task_instance_id != episode.task_instance_id:
                raise ValueError("TaskEvent task_instance_id does not match AgentExecutionEpisode")

    def _episode_result_with_product_refs(
        self,
        episode_result: EpisodeResult,
        *,
        work_products: tuple[WorkProduct, ...],
    ) -> EpisodeResult:
        if episode_result.work_product_candidates or not work_products:
            return episode_result
        return replace(
            episode_result,
            work_product_candidates=tuple(item.ref().to_dict() for item in work_products),
        )

    def _write_reducer_commit_checkpoint(
        self,
        *,
        episode: AgentExecutionEpisode,
        episode_result: EpisodeResult,
        work_products: tuple[WorkProduct, ...],
        event: TaskEvent | None,
    ) -> TaskCheckpoint:
        product_ids = tuple(item.work_product_id for item in work_products if str(item.work_product_id or "").strip())
        artifact_refs = tuple(
            dict.fromkeys(
                [
                    *[str(item).strip() for item in episode_result.artifact_refs if str(item).strip()],
                    *[
                        str(ref).strip()
                        for product in work_products
                        for ref in product.artifact_refs
                        if str(ref).strip()
                    ],
                ]
            )
        )
        event_id = event.event_id if event is not None else ""
        checkpoint = TaskCheckpoint(
            checkpoint_id=stable_task_environment_id(
                "taskcheckpoint",
                episode.task_environment_id,
                episode.episode_id,
                episode_result.result_id,
                event_id,
            ),
            task_environment_id=episode.task_environment_id,
            task_instance_id=episode.task_instance_id,
            checkpoint_kind="reducer_commit",
            episode_id=episode.episode_id,
            event_id=event_id,
            event_seq=event.event_seq if event is not None else -1,
            context_package_id=episode.input_context_package_id,
            latest_work_product_ids=product_ids,
            latest_artifact_refs=artifact_refs,
            continuation_hint=episode_result.continuation_hint,
            summary=episode_result.summary or episode_result.blocker or episode.terminal_reason,
            hashes={
                "episode_result_hash": context_package_hash(episode_result.to_dict()),
                "work_product_ids_hash": context_package_hash(list(product_ids)),
                "artifact_refs_hash": context_package_hash(list(artifact_refs)),
            },
            metadata={
                "source_authority": f"{self.authority}.reducer_commit_checkpoint",
                "episode_result_id": episode_result.result_id,
                "episode_result_status": episode_result.status,
            },
        )
        return self.task_repository.upsert_checkpoint(checkpoint)

    def _apply_state_update_proposals(
        self,
        *,
        episode: AgentExecutionEpisode,
        episode_result: EpisodeResult,
    ) -> tuple[tuple[TaskStateProposal, ...], tuple[TaskEvent, ...]]:
        items = _state_update_proposal_items(episode_result.state_update_proposals)
        if not items:
            return (), ()
        stored_proposals: list[TaskStateProposal] = []
        events: list[TaskEvent] = []
        for index, item in enumerate(items):
            proposal_kind = _state_proposal_kind(item)
            state_path = _state_proposal_path(item)
            operation = _state_proposal_operation(item)
            proposal_id = str(item.get("proposal_id") or item.get("id") or "").strip() or stable_task_environment_id(
                "taskstateproposal",
                episode.task_environment_id,
                episode.episode_id,
                episode_result.result_id,
                index,
                proposal_kind,
                state_path,
                operation,
            )
            evidence_refs = tuple(
                dict.fromkeys(
                    [
                        *[str(ref).strip() for ref in list(item.get("evidence_refs") or []) if str(ref).strip()],
                        *[str(ref).strip() for ref in episode_result.evidence_refs if str(ref).strip()],
                    ]
                )
            )
            proposal = TaskStateProposal(
                proposal_id=proposal_id,
                task_environment_id=episode.task_environment_id,
                task_instance_id=episode.task_instance_id,
                source_episode_id=episode.episode_id,
                source_result_id=episode_result.result_id,
                proposal_kind=proposal_kind,
                state_path=state_path,
                operation=operation,
                value=_state_proposal_value(item),
                evidence_refs=evidence_refs,
                confidence=str(item.get("confidence") or item.get("certainty") or "agent_proposed"),
                status="recorded",
                metadata={
                    "source_authority": f"{self.authority}.state_update_proposal_reducer",
                    "proposal_index": index,
                    "raw_keys": sorted(str(key) for key in item.keys()),
                },
            )
            stored = self.task_repository.upsert_state_proposal(proposal)
            stored_proposals.append(stored)
            events.append(
                self.task_repository.append_event(
                    TaskEvent(
                        event_id=stable_task_environment_id(
                            "taskevent",
                            episode.task_environment_id,
                            "state_update_proposed",
                            stored.proposal_id,
                            episode_result.result_id,
                        ),
                        task_environment_id=episode.task_environment_id,
                        task_instance_id=episode.task_instance_id,
                        event_seq=0,
                        event_type="state_update_proposed",
                        actor_kind="system",
                        source_episode_id=episode.episode_id,
                        idempotency_key=f"state-update-proposed:{stored.proposal_id}:{episode_result.result_id}",
                        payload={
                            "proposal_id": stored.proposal_id,
                            "proposal_kind": stored.proposal_kind,
                            "state_path": stored.state_path,
                            "operation": stored.operation,
                            "status": stored.status,
                            "confidence": stored.confidence,
                        },
                        refs={
                            "episode_ref": episode.episode_id,
                            "episode_result_ref": episode_result.result_id,
                            "state_proposal_ref": stored.proposal_id,
                        },
                    ),
                    snapshot_patch={
                        "current_phase": "task_state",
                        "current_step": "state_update_proposed",
                        "progress_label": _state_proposal_label(stored),
                    },
                )
            )
        return tuple(stored_proposals), tuple(events)

    def _apply_plan_patch(
        self,
        *,
        episode: AgentExecutionEpisode,
        episode_result: EpisodeResult,
    ) -> tuple[tuple[TaskPlan, ...], tuple[TaskEvent, ...]]:
        patch = dict(episode_result.plan_patch or {})
        if not _meaningful_plan_patch(patch):
            return (), ()
        existing_plans = self.task_repository.list_task_plans(episode.task_environment_id, limit=200)
        latest_version = max((item.version for item in existing_plans), default=0)
        active_plans = [item for item in existing_plans if item.status == "active"]
        superseded: list[TaskPlan] = []
        for active in active_plans:
            superseded.append(
                self.task_repository.upsert_task_plan(
                    replace(
                        active,
                        status="superseded",
                        metadata={
                            **dict(active.metadata or {}),
                            "superseded_by_episode_id": episode.episode_id,
                            "superseded_by_result_id": episode_result.result_id,
                        },
                    )
                )
            )
        version = latest_version + 1
        plan_id = str(patch.get("plan_id") or "").strip() or stable_task_environment_id(
            "taskplan",
            episode.task_environment_id,
            episode.episode_id,
            episode_result.result_id,
            version,
        )
        plan = TaskPlan(
            plan_id=plan_id,
            task_environment_id=episode.task_environment_id,
            version=version,
            status="active",
            strategy_summary=str(patch.get("strategy_summary") or patch.get("summary") or "").strip(),
            phases=tuple(dict(item) for item in list(patch.get("phases") or []) if isinstance(item, dict)),
            acceptance_mapping=dict(patch.get("acceptance_mapping") or {}),
            risk_notes=tuple(str(item).strip() for item in list(patch.get("risk_notes") or []) if str(item).strip()),
            created_by_episode_id=episode.episode_id,
            supersedes_plan_id=active_plans[0].plan_id if active_plans else str(patch.get("supersedes_plan_id") or ""),
            metadata={
                "source_authority": f"{self.authority}.plan_patch_reducer",
                "episode_result_id": episode_result.result_id,
                "superseded_plan_ids": [item.plan_id for item in active_plans],
            },
        )
        stored_plan = self.task_repository.upsert_task_plan(plan)
        event_type = "plan_revised" if active_plans else "plan_proposed"
        event = self.task_repository.append_event(
            TaskEvent(
                event_id=stable_task_environment_id(
                    "taskevent",
                    episode.task_environment_id,
                    event_type,
                    stored_plan.plan_id,
                    episode_result.result_id,
                ),
                task_environment_id=episode.task_environment_id,
                task_instance_id=episode.task_instance_id,
                event_seq=0,
                event_type=event_type,
                actor_kind="system",
                source_episode_id=episode.episode_id,
                idempotency_key=f"{event_type}:{stored_plan.plan_id}:{episode_result.result_id}",
                payload={
                    "plan_id": stored_plan.plan_id,
                    "version": stored_plan.version,
                    "status": stored_plan.status,
                    "superseded_plan_ids": [item.plan_id for item in active_plans],
                },
                refs={
                    "episode_ref": episode.episode_id,
                    "episode_result_ref": episode_result.result_id,
                    "plan_ref": stored_plan.plan_id,
                },
            ),
            snapshot_patch={
                "current_phase": "task_planning",
                "current_step": event_type,
                "progress_label": stored_plan.strategy_summary[:240] or event_type,
            },
        )
        return (stored_plan, *superseded), (event,)

    def _apply_todo_patch(
        self,
        *,
        episode: AgentExecutionEpisode,
        episode_result: EpisodeResult,
        active_plan_id: str,
    ) -> tuple[tuple[TaskTodoItem, ...], tuple[TaskEvent, ...]]:
        items = _todo_patch_items(dict(episode_result.todo_patch or {}))
        if not items:
            return (), ()
        stored_items: list[TaskTodoItem] = []
        events: list[TaskEvent] = []
        for index, item in enumerate(items):
            title = str(item.get("title") or item.get("summary") or "").strip()
            todo_id = str(item.get("todo_id") or item.get("id") or "").strip()
            existing = self.task_repository.get_todo_item(todo_id) if todo_id else None
            if existing is None and not title:
                continue
            if existing is not None and not title:
                title = existing.title
            status = _todo_status(item.get("status"), fallback=existing.status if existing is not None else "pending")
            resolved_todo_id = todo_id or stable_task_environment_id(
                "tasktodo",
                episode.task_environment_id,
                episode.episode_id,
                episode_result.result_id,
                index,
                title,
            )
            completed_by_episode_id = (
                episode.episode_id
                if status in {"done", "canceled"} and not (existing.completed_by_episode_id if existing else "")
                else (existing.completed_by_episode_id if existing else "")
            )
            todo = TaskTodoItem(
                todo_id=resolved_todo_id,
                task_environment_id=episode.task_environment_id,
                title=title,
                status=status,  # type: ignore[arg-type]
                plan_id=str(item.get("plan_id") or (existing.plan_id if existing is not None else active_plan_id) or ""),
                evidence_refs=tuple(str(ref).strip() for ref in list(item.get("evidence_refs") or []) if str(ref).strip()),
                blocker=str(item.get("blocker") or (existing.blocker if existing is not None and status == "blocked" else "") or ""),
                created_by_episode_id=existing.created_by_episode_id if existing is not None else episode.episode_id,
                completed_by_episode_id=completed_by_episode_id,
                created_at=existing.created_at if existing is not None else 0.0,
                metadata={
                    **(dict(existing.metadata or {}) if existing is not None else {}),
                    "source_authority": f"{self.authority}.todo_patch_reducer",
                    "episode_result_id": episode_result.result_id,
                },
            )
            stored = self.task_repository.upsert_todo_item(todo)
            stored_items.append(stored)
            event_type = "todo_updated" if existing is not None else "todo_created"
            events.append(
                self.task_repository.append_event(
                    TaskEvent(
                        event_id=stable_task_environment_id(
                            "taskevent",
                            episode.task_environment_id,
                            event_type,
                            stored.todo_id,
                            episode_result.result_id,
                        ),
                        task_environment_id=episode.task_environment_id,
                        task_instance_id=episode.task_instance_id,
                        event_seq=0,
                        event_type=event_type,
                        actor_kind="system",
                        source_episode_id=episode.episode_id,
                        idempotency_key=f"{event_type}:{stored.todo_id}:{episode_result.result_id}",
                        payload={
                            "todo_id": stored.todo_id,
                            "title": stored.title,
                            "status": stored.status,
                            "plan_id": stored.plan_id,
                        },
                        refs={
                            "episode_ref": episode.episode_id,
                            "episode_result_ref": episode_result.result_id,
                            "todo_ref": stored.todo_id,
                            **({"plan_ref": stored.plan_id} if stored.plan_id else {}),
                        },
                    ),
                    snapshot_patch=_todo_snapshot_patch(stored),
                )
            )
        return tuple(stored_items), tuple(events)

    def _active_plan_id(self, task_environment_id: str) -> str:
        active = self.task_repository.list_task_plans(task_environment_id, status="active", limit=1)
        return active[0].plan_id if active else ""


def _meaningful_plan_patch(patch: dict[str, Any]) -> bool:
    if not patch:
        return False
    return bool(
        str(patch.get("strategy_summary") or patch.get("summary") or "").strip()
        or list(patch.get("phases") or [])
        or dict(patch.get("acceptance_mapping") or {})
        or list(patch.get("risk_notes") or [])
    )


def _todo_patch_items(patch: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    if not patch:
        return ()
    raw_items = patch.get("items")
    if raw_items is None:
        raw_items = patch.get("todos")
    if raw_items is None and any(key in patch for key in ("title", "summary", "todo_id", "id", "status")):
        raw_items = [patch]
    return tuple(dict(item) for item in list(raw_items or []) if isinstance(item, dict))


def _todo_status(value: Any, *, fallback: str) -> str:
    status = str(value or fallback or "pending").strip()
    if status in {"pending", "active", "blocked", "done", "canceled"}:
        return status
    return "pending"


def _todo_snapshot_patch(todo: TaskTodoItem) -> dict[str, Any]:
    if todo.status == "active":
        return {
            "current_phase": "task_todo",
            "current_step": "active",
            "progress_label": todo.title[:240],
            "blocked_reason": "",
        }
    if todo.status == "blocked":
        return {
            "status": "blocked",
            "current_phase": "task_todo",
            "current_step": "blocked",
            "progress_label": todo.title[:240],
            "blocked_reason": todo.blocker or todo.title,
            "recovery_action": "resume_task_environment",
        }
    if todo.status == "done":
        return {
            "current_phase": "task_todo",
            "current_step": "done",
            "progress_label": todo.title[:240],
        }
    return {
        "current_phase": "task_todo",
        "current_step": todo.status,
        "progress_label": todo.title[:240],
    }


def _state_update_proposal_items(proposals: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in list(proposals or ()) if isinstance(item, dict) and _meaningful_state_proposal(item))


def _meaningful_state_proposal(item: dict[str, Any]) -> bool:
    if not item:
        return False
    return bool(
        str(item.get("proposal_kind") or item.get("kind") or item.get("type") or item.get("state_path") or item.get("path") or item.get("key") or "").strip()
        or "value" in item
        or "payload" in item
        or "state" in item
    )


def _state_proposal_kind(item: dict[str, Any]) -> str:
    value = str(item.get("proposal_kind") or item.get("kind") or item.get("type") or "").strip()
    return value or "task_state_update"


def _state_proposal_path(item: dict[str, Any]) -> str:
    return str(item.get("state_path") or item.get("path") or item.get("key") or item.get("target") or item.get("field") or "").strip()


def _state_proposal_operation(item: dict[str, Any]) -> str:
    operation = str(item.get("operation") or item.get("op") or "").strip()
    return operation or "set"


def _state_proposal_value(item: dict[str, Any]) -> Any:
    for key in ("value", "payload", "state"):
        if key in item:
            return item.get(key)
    excluded = {
        "proposal_id",
        "id",
        "proposal_kind",
        "kind",
        "type",
        "state_path",
        "path",
        "key",
        "target",
        "field",
        "operation",
        "op",
        "evidence_refs",
        "confidence",
        "certainty",
    }
    return {key: value for key, value in item.items() if key not in excluded}


def _state_proposal_label(proposal: TaskStateProposal) -> str:
    target = proposal.state_path or proposal.proposal_kind
    return f"{proposal.operation}:{target}"[:240]
