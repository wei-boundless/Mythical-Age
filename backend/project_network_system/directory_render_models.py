from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


DirectoryRenderStatus = Literal[
    "planned",
    "manifest_ready",
    "child_frames_created",
    "direct_file_reviews_running",
    "waiting_child_returns",
    "ready_to_aggregate",
    "graph_published",
    "aggregating",
    "summarized",
    "returned_to_parent",
    "blocked_missing_skeleton",
    "blocked_child_failed",
    "blocked_unresolved_conflict",
    "needs_human_review",
    "cancelled",
]


DEFAULT_SKIPPED_DIRECTORY_NAMES = (
    ".git",
    ".hg",
    ".svn",
    ".next",
    ".nuxt",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "generated",
    "vendor",
)

DEFAULT_CODE_FILE_EXTENSIONS = (
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".java",
    ".go",
    ".rs",
    ".cs",
    ".cpp",
    ".cxx",
    ".cc",
    ".c",
    ".h",
    ".hpp",
    ".php",
    ".rb",
    ".kt",
    ".swift",
    ".scala",
    ".sql",
)


@dataclass(frozen=True, slots=True)
class DirectoryRenderBudget:
    max_depth: int = 12
    max_child_folders_per_frame: int = 64
    max_direct_files_per_frame: int = 96
    max_total_frames: int = 2000
    max_graph_nodes_per_frame: int = 128
    include_non_code_files: bool = False
    skipped_directory_names: tuple[str, ...] = DEFAULT_SKIPPED_DIRECTORY_NAMES
    code_file_extensions: tuple[str, ...] = DEFAULT_CODE_FILE_EXTENSIONS
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.directory_render_budget"

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "DirectoryRenderBudget":
        payload = dict(payload or {})
        return cls(
            max_depth=max(1, _int_value(payload.get("max_depth"), 12)),
            max_child_folders_per_frame=max(1, _int_value(payload.get("max_child_folders_per_frame"), 64)),
            max_direct_files_per_frame=max(1, _int_value(payload.get("max_direct_files_per_frame"), 96)),
            max_total_frames=max(1, _int_value(payload.get("max_total_frames"), 2000)),
            max_graph_nodes_per_frame=max(1, _int_value(payload.get("max_graph_nodes_per_frame"), 128)),
            include_non_code_files=bool(payload.get("include_non_code_files", False)),
            skipped_directory_names=_tuple_of_strings(payload.get("skipped_directory_names")) or DEFAULT_SKIPPED_DIRECTORY_NAMES,
            code_file_extensions=tuple(item.lower() for item in (_tuple_of_strings(payload.get("code_file_extensions")) or DEFAULT_CODE_FILE_EXTENSIONS)),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["skipped_directory_names"] = list(self.skipped_directory_names)
        payload["code_file_extensions"] = list(self.code_file_extensions)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class DirectoryManifestProduct:
    manifest_id: str
    build_id: str
    frame_id: str
    skeleton_build_id: str
    skeleton_generation: int
    folder_node_id: str
    folder_stable_ref: str
    folder_path: str = ""
    child_folder_node_ids: tuple[str, ...] = ()
    child_folder_refs: tuple[str, ...] = ()
    direct_file_node_ids: tuple[str, ...] = ()
    direct_file_refs: tuple[str, ...] = ()
    skipped_refs: tuple[str, ...] = ()
    child_folder_nodes: tuple[dict[str, Any], ...] = ()
    direct_file_nodes: tuple[dict[str, Any], ...] = ()
    content_hash: str = ""
    status: str = "manifest_ready"
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.directory_manifest_product"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["child_folder_node_ids"] = list(self.child_folder_node_ids)
        payload["child_folder_refs"] = list(self.child_folder_refs)
        payload["direct_file_node_ids"] = list(self.direct_file_node_ids)
        payload["direct_file_refs"] = list(self.direct_file_refs)
        payload["skipped_refs"] = list(self.skipped_refs)
        payload["child_folder_nodes"] = [dict(item) for item in self.child_folder_nodes]
        payload["direct_file_nodes"] = [dict(item) for item in self.direct_file_nodes]
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class DirectoryChildReturnEnvelope:
    return_id: str
    build_id: str
    parent_frame_id: str
    child_frame_id: str
    child_folder_ref: str
    child_folder_node_id: str = ""
    child_summary_product_ref: str = ""
    status: str = "candidate"
    payload_ref: str = ""
    coverage: dict[str, Any] = field(default_factory=dict)
    blockers: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.directory_child_return"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class DirectoryRenderFrame:
    frame_id: str
    build_id: str
    root_frame_id: str
    parent_frame_id: str
    depth: int
    skeleton_build_id: str
    skeleton_generation: int
    folder_node_id: str
    folder_stable_ref: str
    folder_path: str = ""
    manifest_ref: str = ""
    child_frame_ids: tuple[str, ...] = ()
    direct_file_refs: tuple[str, ...] = ()
    child_return_refs: tuple[str, ...] = ()
    aggregate_work_product_ref: str = ""
    graph_id: str = ""
    graph_run_id: str = ""
    status: DirectoryRenderStatus = "planned"
    budget: DirectoryRenderBudget = field(default_factory=DirectoryRenderBudget)
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.directory_render_frame"

    def __post_init__(self) -> None:
        if self.authority != "project_network_system.directory_render_frame":
            raise ValueError("DirectoryRenderFrame authority mismatch")
        if not str(self.frame_id or "").strip():
            raise ValueError("DirectoryRenderFrame requires frame_id")
        if not str(self.build_id or "").strip():
            raise ValueError("DirectoryRenderFrame requires build_id")
        if self.depth < 0:
            raise ValueError("DirectoryRenderFrame depth must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["child_frame_ids"] = list(self.child_frame_ids)
        payload["direct_file_refs"] = list(self.direct_file_refs)
        payload["child_return_refs"] = list(self.child_return_refs)
        payload["budget"] = self.budget.to_dict()
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class DirectoryFrameMaterializationPackage:
    package_id: str
    build_id: str
    frame: DirectoryRenderFrame
    manifest: DirectoryManifestProduct
    child_returns: tuple[DirectoryChildReturnEnvelope, ...] = ()
    graph_id: str = ""
    source_work_product_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.directory_frame_materialization_package"

    def __post_init__(self) -> None:
        if self.authority != "project_network_system.directory_frame_materialization_package":
            raise ValueError("DirectoryFrameMaterializationPackage authority mismatch")
        if not str(self.package_id or "").strip():
            raise ValueError("DirectoryFrameMaterializationPackage requires package_id")
        if self.frame.build_id != self.build_id or self.manifest.build_id != self.build_id:
            raise ValueError("DirectoryFrameMaterializationPackage build_id mismatch")
        if self.manifest.frame_id != self.frame.frame_id:
            raise ValueError("DirectoryFrameMaterializationPackage frame/manifest mismatch")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "package_id": self.package_id,
                "build_id": self.build_id,
                "frame": self.frame.to_dict(),
                "manifest": self.manifest.to_dict(),
                "child_returns": [item.to_dict() for item in self.child_returns],
                "graph_id": self.graph_id,
                "source_work_product_refs": list(self.source_work_product_refs),
                "metadata": dict(self.metadata or {}),
                "authority": self.authority,
            }
        )


@dataclass(frozen=True, slots=True)
class DirectoryRenderProjection:
    build_id: str
    frame: DirectoryRenderFrame
    manifest: DirectoryManifestProduct | None = None
    child_frames: tuple[DirectoryRenderFrame, ...] = ()
    child_returns: tuple[DirectoryChildReturnEnvelope, ...] = ()
    next_action: str = ""
    ready_to_materialize: bool = False
    blockers: tuple[str, ...] = ()
    authority: str = "project_network_system.directory_render_projection"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "build_id": self.build_id,
                "frame": self.frame.to_dict(),
                "manifest": self.manifest.to_dict() if self.manifest is not None else {},
                "child_frames": [item.to_dict() for item in self.child_frames],
                "child_returns": [item.to_dict() for item in self.child_returns],
                "next_action": self.next_action,
                "ready_to_materialize": self.ready_to_materialize,
                "blockers": list(self.blockers),
                "authority": self.authority,
            }
        )


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace(",", "\n").splitlines() if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}

