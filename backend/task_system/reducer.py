from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from task_system.episodes import AgentExecutionEpisode, EpisodeRepository, EpisodeResult
from task_system.work_environments.models import TaskEvent
from task_system.work_environments.repository import TaskEnvironmentRepository
from task_system.work_products import WorkProduct, WorkProductRepository


@dataclass(frozen=True, slots=True)
class TaskReductionResult:
    episode: AgentExecutionEpisode
    episode_result: EpisodeResult
    work_products: tuple[WorkProduct, ...] = ()
    event: TaskEvent | None = None
    authority: str = "task_system.task_reducer_result"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "episode": self.episode.to_dict(),
            "episode_result": self.episode_result.to_dict(),
            "work_products": [item.to_dict() for item in self.work_products],
            "event": self.event.to_dict() if self.event is not None else {},
        }


class TaskReducer:
    authority = "task_system.task_reducer"

    def __init__(self, base_dir: str | Path) -> None:
        self.task_repository = TaskEnvironmentRepository(base_dir)
        self.episode_repository = EpisodeRepository(base_dir)
        self.work_product_repository = WorkProductRepository(base_dir)

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
    ) -> TaskReductionResult:
        self._validate_episode_result_scope(
            episode=episode,
            episode_result=episode_result,
            work_product_candidates=work_product_candidates,
            event=event,
        )
        now = time.time() if ended_at is None else float(ended_at)
        stored_episode = self.episode_repository.upsert_episode(
            replace(
                episode,
                status=str(episode_status or episode.status or "interrupted"),  # type: ignore[arg-type]
                terminal_reason=str(terminal_reason or episode.terminal_reason or ""),
                ended_at=now,
                diagnostics={
                    **dict(episode.diagnostics or {}),
                    **dict(episode_diagnostics_patch or {}),
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
        return TaskReductionResult(
            episode=stored_episode,
            episode_result=stored_result,
            work_products=stored_products,
            event=stored_event,
        )

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
