from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import time


@dataclass(slots=True)
class TaskBindings:
    active_pdf: str = ""
    active_dataset: str = ""
    active_binding_identity: str = ""
    active_entity: str = ""
    active_location: str = ""
    source_kind: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class TaskConstraints:
    top_n: int | None = None
    group_by: str = ""
    page: int | None = None
    response_style: str = ""
    pdf_mode: str = ""
    pdf_section: str = ""
    pdf_focus_pages: list[int] = field(default_factory=list)
    total_pages: int | None = None
    readable_pages: int | None = None
    usable_pages: int | None = None
    must_exclude: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class TaskSummary:
    headline: str = ""
    response: str = ""
    key_points: list[str] = field(default_factory=list)
    response_style: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class TaskResultRef:
    result_id: str
    task_id: str
    storage_path: str = ""
    content_preview: str = ""
    content_type: str = "text/plain"
    created_at: float = field(default_factory=time)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class TaskContextRef:
    task_id: str
    parent_query_id: str
    task_kind: str = ""
    bindings: TaskBindings = field(default_factory=TaskBindings)
    constraints: TaskConstraints = field(default_factory=TaskConstraints)
    status: str = "pending"
    summary: str = ""
    result_ref_id: str = ""
    owner_scope: str = "task"

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "parent_query_id": self.parent_query_id,
            "task_kind": self.task_kind,
            "bindings": self.bindings.to_dict(),
            "constraints": self.constraints.to_dict(),
            "status": self.status,
            "summary": self.summary,
            "result_ref_id": self.result_ref_id,
            "owner_scope": self.owner_scope,
        }
