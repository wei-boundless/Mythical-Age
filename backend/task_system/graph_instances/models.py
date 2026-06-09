from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


GRAPH_TASK_INSTANCE_AUTHORITY = "task_system.graph_task_instance"


@dataclass(frozen=True, slots=True)
class GraphTaskInstance:
    graph_task_instance_id: str
    graph_id: str
    title: str
    description: str = ""
    status: str = "idle"
    root_session_id: str = ""
    active_graph_run_id: str = ""
    graph_run_ids: tuple[str, ...] = ()
    file_space_id: str = ""
    artifact_index_id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = GRAPH_TASK_INSTANCE_AUTHORITY

    def __post_init__(self) -> None:
        if self.authority != GRAPH_TASK_INSTANCE_AUTHORITY:
            raise ValueError("GraphTaskInstance authority must be task_system.graph_task_instance")
        if not self.graph_task_instance_id:
            raise ValueError("GraphTaskInstance requires graph_task_instance_id")
        if not self.graph_id:
            raise ValueError("GraphTaskInstance requires graph_id")
        if not self.title:
            raise ValueError("GraphTaskInstance requires title")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["graph_run_ids"] = list(self.graph_run_ids)
        return payload


def graph_task_instance_from_dict(payload: dict[str, Any]) -> GraphTaskInstance:
    instance_id = str(payload.get("graph_task_instance_id") or payload.get("instance_id") or "").strip()
    graph_run_ids = tuple(
        str(item or "").strip()
        for item in list(payload.get("graph_run_ids") or [])
        if str(item or "").strip()
    )
    return GraphTaskInstance(
        graph_task_instance_id=instance_id,
        graph_id=str(payload.get("graph_id") or "").strip(),
        title=str(payload.get("title") or instance_id).strip(),
        description=str(payload.get("description") or "").strip(),
        status=str(payload.get("status") or "idle").strip() or "idle",
        root_session_id=str(payload.get("root_session_id") or "").strip(),
        active_graph_run_id=str(payload.get("active_graph_run_id") or "").strip(),
        graph_run_ids=graph_run_ids,
        file_space_id=str(payload.get("file_space_id") or instance_id).strip() or instance_id,
        artifact_index_id=str(payload.get("artifact_index_id") or f"artifact_index.{instance_id}").strip(),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        metadata=dict(payload.get("metadata") or {}),
        authority=str(payload.get("authority") or GRAPH_TASK_INSTANCE_AUTHORITY),
    )

