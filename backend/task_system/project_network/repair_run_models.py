from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from graph_system.models import ExecutableGraphConfig
from task_system.graphs.task_graph_models import TaskGraphDefinition

from .directory_render_models import DirectoryFrameMaterializationPackage
from .store_models import ProjectNetworkRepairWorkItemRecord


@dataclass(frozen=True, slots=True)
class ProjectNetworkRepairGraphPublishResult:
    build_id: str
    repair_batch_id: str
    folder_stable_ref: str = ""
    selected_file_refs: tuple[str, ...] = ()
    deferred_repair_item_ids: tuple[str, ...] = ()
    repair_items: tuple[ProjectNetworkRepairWorkItemRecord, ...] = ()
    package: DirectoryFrameMaterializationPackage | None = None
    task_graph: TaskGraphDefinition | None = None
    graph_config: ExecutableGraphConfig | None = None
    start_initial_inputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.project_network.repair_graph_publish_result"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "build_id": self.build_id,
                "repair_batch_id": self.repair_batch_id,
                "folder_stable_ref": self.folder_stable_ref,
                "selected_file_refs": list(self.selected_file_refs),
                "deferred_repair_item_ids": list(self.deferred_repair_item_ids),
                "repair_items": [item.to_dict() for item in self.repair_items],
                "package": self.package.to_dict() if self.package is not None else {},
                "task_graph": self.task_graph.to_dict() if self.task_graph is not None else {},
                "graph_config": self.graph_config.to_dict() if self.graph_config is not None else {},
                "start_initial_inputs": dict(self.start_initial_inputs or {}),
                "metadata": dict(self.metadata or {}),
                "authority": self.authority,
            }
        )


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
