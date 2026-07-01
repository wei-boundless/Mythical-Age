from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .semantic_models import SemanticRepairWorkItemRecord


@dataclass(frozen=True, slots=True)
class GitChangeSetRecord:
    change_set_id: str
    build_id: str
    base_ref: str = ""
    head_ref: str = ""
    change_mode: str = "working_tree"
    changed_files: tuple[str, ...] = ()
    renamed_files: tuple[dict[str, str], ...] = ()
    deleted_files: tuple[str, ...] = ()
    added_files: tuple[str, ...] = ()
    diff_stats: dict[str, Any] = field(default_factory=dict)
    touched_skeleton_node_ids: tuple[str, ...] = ()
    touched_skeleton_edge_ids: tuple[str, ...] = ()
    semantic_refs_to_mark_stale: tuple[str, ...] = ()
    status: str = "candidate"
    created_at: str = ""
    updated_at: str = ""
    authority: str = "file_management.project_structure.git_change_set"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changed_files"] = list(self.changed_files)
        payload["renamed_files"] = [dict(item) for item in self.renamed_files]
        payload["deleted_files"] = list(self.deleted_files)
        payload["added_files"] = list(self.added_files)
        payload["touched_skeleton_node_ids"] = list(self.touched_skeleton_node_ids)
        payload["touched_skeleton_edge_ids"] = list(self.touched_skeleton_edge_ids)
        payload["semantic_refs_to_mark_stale"] = list(self.semantic_refs_to_mark_stale)
        return _drop_empty(payload)


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}


@dataclass(frozen=True, slots=True)
class NetworkMaintenanceProjection:
    build_id: str
    change_set: GitChangeSetRecord
    work_items: tuple[SemanticRepairWorkItemRecord, ...] = ()
    shared_memory: tuple[dict[str, Any], ...] = ()
    authority: str = "file_management.project_structure.maintenance_projection"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "build_id": self.build_id,
                "change_set": self.change_set.to_dict(),
                "work_items": [item.to_dict() for item in self.work_items],
                "shared_memory": [dict(item) for item in self.shared_memory],
                "authority": self.authority,
            }
        )
