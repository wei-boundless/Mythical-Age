from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ProjectNetworkBuildKind = Literal[
    "project_semantic_network",
    "code_control_network",
    "prompt_runtime_network",
    "tool_capability_network",
]
ProjectNetworkBuildMode = Literal["bootstrap", "incremental", "repair", "audit"]
ProjectNetworkTargetLayer = Literal[
    "source_snapshot",
    "system",
    "folder",
    "semantic_file_module",
    "ast_endpoint",
    "relation_route",
    "generation",
]


@dataclass(frozen=True, slots=True)
class ProjectNetworkScope:
    project_id: str = ""
    root_paths: tuple[str, ...] = ()
    system_refs: tuple[str, ...] = ()
    folder_refs: tuple[str, ...] = ()
    module_refs: tuple[str, ...] = ()
    anchor_refs: tuple[str, ...] = ()
    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ProjectNetworkScope":
        payload = dict(payload or {})
        return cls(
            project_id=str(payload.get("project_id") or ""),
            root_paths=_tuple_of_strings(payload.get("root_paths")),
            system_refs=_tuple_of_strings(payload.get("system_refs")),
            folder_refs=_tuple_of_strings(payload.get("folder_refs")),
            module_refs=_tuple_of_strings(payload.get("module_refs")),
            anchor_refs=_tuple_of_strings(payload.get("anchor_refs")),
            include_globs=_tuple_of_strings(payload.get("include_globs")),
            exclude_globs=_tuple_of_strings(payload.get("exclude_globs")),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class ProjectNetworkSourceSnapshots:
    file_tree_snapshot: str = ""
    deep_ast_generation: str = ""
    registry_snapshot: str = ""
    tool_catalog_snapshot: str = ""
    prompt_registry_snapshot: str = ""
    source_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ProjectNetworkSourceSnapshots":
        payload = dict(payload or {})
        return cls(
            file_tree_snapshot=str(payload.get("file_tree_snapshot") or ""),
            deep_ast_generation=str(payload.get("deep_ast_generation") or ""),
            registry_snapshot=str(payload.get("registry_snapshot") or ""),
            tool_catalog_snapshot=str(payload.get("tool_catalog_snapshot") or ""),
            prompt_registry_snapshot=str(payload.get("prompt_registry_snapshot") or ""),
            source_hash=str(payload.get("source_hash") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class ProjectNetworkPublicationPolicy:
    requires_curator: bool = True
    requires_anchor_validation: bool = True
    requires_schema_validation: bool = True
    requires_human_gate: bool = False
    publish_store: str = "project_semantic_space_store"
    allowed_generation_statuses: tuple[str, ...] = ("candidate", "published", "superseded", "rolled_back")
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ProjectNetworkPublicationPolicy":
        payload = dict(payload or {})
        return cls(
            requires_curator=bool(payload.get("requires_curator", True)),
            requires_anchor_validation=bool(payload.get("requires_anchor_validation", True)),
            requires_schema_validation=bool(payload.get("requires_schema_validation", True)),
            requires_human_gate=bool(payload.get("requires_human_gate", False)),
            publish_store=str(payload.get("publish_store") or "project_semantic_space_store"),
            allowed_generation_statuses=_tuple_of_strings(payload.get("allowed_generation_statuses"))
            or ("candidate", "published", "superseded", "rolled_back"),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class ProjectNetworkBuildContract:
    build_id: str
    build_kind: ProjectNetworkBuildKind = "project_semantic_network"
    build_mode: ProjectNetworkBuildMode = "bootstrap"
    scope: ProjectNetworkScope = field(default_factory=ProjectNetworkScope)
    source_snapshots: ProjectNetworkSourceSnapshots = field(default_factory=ProjectNetworkSourceSnapshots)
    target_layers: tuple[ProjectNetworkTargetLayer, ...] = (
        "source_snapshot",
        "system",
        "folder",
        "semantic_file_module",
        "ast_endpoint",
        "relation_route",
        "generation",
    )
    publication_policy: ProjectNetworkPublicationPolicy = field(default_factory=ProjectNetworkPublicationPolicy)
    deterministic_layers: tuple[str, ...] = ("source_snapshot",)
    model_judged_layers: tuple[str, ...] = ("system", "folder", "semantic_file_module", "relation_route")
    validation_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.build_contract"

    def __post_init__(self) -> None:
        if self.authority != "project_network_system.build_contract":
            raise ValueError("ProjectNetworkBuildContract authority mismatch")
        if not str(self.build_id or "").strip():
            raise ValueError("ProjectNetworkBuildContract requires build_id")
        if self.build_kind not in {
            "project_semantic_network",
            "code_control_network",
            "prompt_runtime_network",
            "tool_capability_network",
        }:
            raise ValueError("unsupported project network build_kind")
        if self.build_mode not in {"bootstrap", "incremental", "repair", "audit"}:
            raise ValueError("unsupported project network build_mode")
        if not self.target_layers:
            raise ValueError("ProjectNetworkBuildContract requires target_layers")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectNetworkBuildContract":
        payload = dict(payload or {})
        return cls(
            build_id=str(payload.get("build_id") or ""),
            build_kind=str(payload.get("build_kind") or "project_semantic_network"),  # type: ignore[arg-type]
            build_mode=str(payload.get("build_mode") or "bootstrap"),  # type: ignore[arg-type]
            scope=ProjectNetworkScope.from_dict(payload.get("scope")),
            source_snapshots=ProjectNetworkSourceSnapshots.from_dict(payload.get("source_snapshots")),
            target_layers=_tuple_of_strings(payload.get("target_layers")) or (
                "source_snapshot",
                "system",
                "folder",
                "semantic_file_module",
                "ast_endpoint",
                "relation_route",
                "generation",
            ),
            publication_policy=ProjectNetworkPublicationPolicy.from_dict(payload.get("publication_policy")),
            deterministic_layers=_tuple_of_strings(payload.get("deterministic_layers")) or ("source_snapshot",),
            model_judged_layers=_tuple_of_strings(payload.get("model_judged_layers"))
            or ("system", "folder", "semantic_file_module", "relation_route"),
            validation_policy=dict(payload.get("validation_policy") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scope"] = self.scope.to_dict()
        payload["source_snapshots"] = self.source_snapshots.to_dict()
        payload["publication_policy"] = self.publication_policy.to_dict()
        return _drop_empty(payload)


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace(",", "\n").splitlines() if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}

