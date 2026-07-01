from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from graph_system.models import ExecutableGraphConfig
from task_system.graphs.task_graph_models import TaskGraphDefinition

from .directory_render_models import DirectoryFrameMaterializationPackage, DirectoryRenderProjection


@dataclass(frozen=True, slots=True)
class DirectoryFrameGraphPublishResult:
    build_id: str
    frame_id: str
    package: DirectoryFrameMaterializationPackage
    task_graph: TaskGraphDefinition
    graph_config: ExecutableGraphConfig
    projection: DirectoryRenderProjection | None = None
    start_initial_inputs: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.project_network.directory_frame_graph_publish_result"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "build_id": self.build_id,
                "frame_id": self.frame_id,
                "package": self.package.to_dict(),
                "task_graph": self.task_graph.to_dict() if hasattr(self.task_graph, "to_dict") else {},
                "graph_config": self.graph_config.to_dict(),
                "projection": self.projection.to_dict() if self.projection is not None else {},
                "start_initial_inputs": dict(self.start_initial_inputs or {}),
                "authority": self.authority,
            }
        )


@dataclass(frozen=True, slots=True)
class DirectoryFrameSchedulerDecision:
    build_id: str
    frame_id: str
    next_action: str
    ready_to_publish_graph: bool = False
    ready_to_aggregate: bool = False
    child_frame_ids: tuple[str, ...] = ()
    child_frame_start_queue: tuple[str, ...] = ()
    missing_child_frame_ids: tuple[str, ...] = ()
    child_return_refs: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    projection: DirectoryRenderProjection | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.project_network.directory_frame_scheduler_decision"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "build_id": self.build_id,
                "frame_id": self.frame_id,
                "next_action": self.next_action,
                "ready_to_publish_graph": self.ready_to_publish_graph,
                "ready_to_aggregate": self.ready_to_aggregate,
                "child_frame_ids": list(self.child_frame_ids),
                "child_frame_start_queue": list(self.child_frame_start_queue),
                "missing_child_frame_ids": list(self.missing_child_frame_ids),
                "child_return_refs": list(self.child_return_refs),
                "blockers": list(self.blockers),
                "projection": self.projection.to_dict() if self.projection is not None else {},
                "metadata": dict(self.metadata or {}),
                "authority": self.authority,
            }
        )


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
