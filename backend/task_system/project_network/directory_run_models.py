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


@dataclass(frozen=True, slots=True)
class DirectoryFrameTreeMaterializationResult:
    build_id: str
    root_frame_id: str
    root_folder_path: str = ""
    max_total_frames: int = 0
    frame_count: int = 0
    prepared_frame_count: int = 0
    created_frame_count: int = 0
    ready_frame_count: int = 0
    waiting_frame_count: int = 0
    blocked_frame_count: int = 0
    ready_frames: tuple[dict[str, Any], ...] = ()
    waiting_frames: tuple[dict[str, Any], ...] = ()
    blocked_frames: tuple[dict[str, Any], ...] = ()
    budget_stop_frames: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.project_network.directory_frame_tree_materialization_result"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "build_id": self.build_id,
                "root_frame_id": self.root_frame_id,
                "root_folder_path": self.root_folder_path,
                "max_total_frames": self.max_total_frames,
                "frame_count": self.frame_count,
                "prepared_frame_count": self.prepared_frame_count,
                "created_frame_count": self.created_frame_count,
                "ready_frame_count": self.ready_frame_count,
                "waiting_frame_count": self.waiting_frame_count,
                "blocked_frame_count": self.blocked_frame_count,
                "ready_frames": [dict(item) for item in self.ready_frames],
                "waiting_frames": [dict(item) for item in self.waiting_frames],
                "blocked_frames": [dict(item) for item in self.blocked_frames],
                "budget_stop_frames": [dict(item) for item in self.budget_stop_frames],
                "metadata": dict(self.metadata or {}),
                "authority": self.authority,
            }
        )


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
