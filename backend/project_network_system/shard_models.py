from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SemanticShardWorkUnitKind = Literal[
    "system",
    "folder",
    "file_batch",
    "file_module",
    "ast_endpoint",
    "relation_route",
    "aggregation",
    "validation",
    "publish",
]
ShardPlanMode = Literal["static_pre_materialized", "rolling_one_hop", "runtime_requested_expansion"]


@dataclass(frozen=True, slots=True)
class ShardComplexity:
    score: int = 0
    estimated_files: int = 0
    estimated_symbols: int = 0
    estimated_relations: int = 0
    risk_flags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ShardComplexity":
        payload = dict(payload or {})
        return cls(
            score=_int_value(payload.get("score"), 0),
            estimated_files=_int_value(payload.get("estimated_files"), 0),
            estimated_symbols=_int_value(payload.get("estimated_symbols"), 0),
            estimated_relations=_int_value(payload.get("estimated_relations"), 0),
            risk_flags=_tuple_of_strings(payload.get("risk_flags")),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class ShardAssignment:
    assigned_scope: dict[str, Any] = field(default_factory=dict)
    input_refs: tuple[str, ...] = ()
    required_anchor_refs: tuple[str, ...] = ()
    source_snapshot_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ShardAssignment":
        payload = dict(payload or {})
        return cls(
            assigned_scope=dict(payload.get("assigned_scope") or {}),
            input_refs=_tuple_of_strings(payload.get("input_refs")),
            required_anchor_refs=_tuple_of_strings(payload.get("required_anchor_refs")),
            source_snapshot_refs=_tuple_of_strings(payload.get("source_snapshot_refs")),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class SemanticShardSpec:
    shard_id: str
    layer_id: str
    work_unit_kind: SemanticShardWorkUnitKind
    node_template_id: str
    assignment: ShardAssignment = field(default_factory=ShardAssignment)
    expected_work_product_contract_id: str = ""
    output_contract_id: str = ""
    payload_contract_id: str = ""
    complexity: ShardComplexity = field(default_factory=ShardComplexity)
    dependencies: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.semantic_shard_spec"

    def __post_init__(self) -> None:
        if self.authority != "project_network_system.semantic_shard_spec":
            raise ValueError("SemanticShardSpec authority mismatch")
        if not str(self.shard_id or "").strip():
            raise ValueError("SemanticShardSpec requires shard_id")
        if not str(self.layer_id or "").strip():
            raise ValueError("SemanticShardSpec requires layer_id")
        if not str(self.node_template_id or "").strip():
            raise ValueError("SemanticShardSpec requires node_template_id")
        if self.work_unit_kind not in {
            "system",
            "folder",
            "file_batch",
            "file_module",
            "ast_endpoint",
            "relation_route",
            "aggregation",
            "validation",
            "publish",
        }:
            raise ValueError("unsupported SemanticShardSpec work_unit_kind")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SemanticShardSpec":
        payload = dict(payload or {})
        assignment_payload = payload.get("assignment")
        if not isinstance(assignment_payload, dict):
            assignment_payload = {
                "assigned_scope": dict(payload.get("assigned_scope") or {}),
                "input_refs": payload.get("input_refs"),
                "required_anchor_refs": payload.get("required_anchor_refs"),
                "source_snapshot_refs": payload.get("source_snapshot_refs"),
            }
        return cls(
            shard_id=str(payload.get("shard_id") or ""),
            layer_id=str(payload.get("layer_id") or ""),
            work_unit_kind=str(payload.get("work_unit_kind") or "file_module"),  # type: ignore[arg-type]
            node_template_id=str(payload.get("node_template_id") or ""),
            assignment=ShardAssignment.from_dict(assignment_payload),
            expected_work_product_contract_id=str(payload.get("expected_work_product_contract_id") or ""),
            output_contract_id=str(payload.get("output_contract_id") or ""),
            payload_contract_id=str(payload.get("payload_contract_id") or ""),
            complexity=ShardComplexity.from_dict(payload.get("complexity")),
            dependencies=_tuple_of_strings(payload.get("dependencies")),
            metadata=dict(payload.get("metadata") or {}),
        )

    @property
    def assigned_scope(self) -> dict[str, Any]:
        return dict(self.assignment.assigned_scope)

    @property
    def input_refs(self) -> tuple[str, ...]:
        return self.assignment.input_refs

    @property
    def required_anchor_refs(self) -> tuple[str, ...]:
        return self.assignment.required_anchor_refs

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["assignment"] = self.assignment.to_dict()
        payload["complexity"] = self.complexity.to_dict()
        payload["assigned_scope"] = self.assigned_scope
        payload["input_refs"] = list(self.input_refs)
        payload["required_anchor_refs"] = list(self.required_anchor_refs)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ShardPlan:
    plan_id: str
    build_id: str
    mode: ShardPlanMode
    target_layer_id: str = ""
    shards: tuple[SemanticShardSpec, ...] = ()
    source_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.shard_plan"

    def __post_init__(self) -> None:
        if self.authority != "project_network_system.shard_plan":
            raise ValueError("ShardPlan authority mismatch")
        if not str(self.plan_id or "").strip():
            raise ValueError("ShardPlan requires plan_id")
        if not str(self.build_id or "").strip():
            raise ValueError("ShardPlan requires build_id")
        if self.mode not in {"static_pre_materialized", "rolling_one_hop", "runtime_requested_expansion"}:
            raise ValueError("unsupported ShardPlan mode")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ShardPlan":
        payload = dict(payload or {})
        return cls(
            plan_id=str(payload.get("plan_id") or ""),
            build_id=str(payload.get("build_id") or ""),
            mode=str(payload.get("mode") or "static_pre_materialized"),  # type: ignore[arg-type]
            target_layer_id=str(payload.get("target_layer_id") or ""),
            shards=tuple(SemanticShardSpec.from_dict(item) for item in list(payload.get("shards") or []) if isinstance(item, dict)),
            source_refs=_tuple_of_strings(payload.get("source_refs")),
            metadata=dict(payload.get("metadata") or {}),
        )

    def shards_for_layer(self, layer_id: str) -> tuple[SemanticShardSpec, ...]:
        return tuple(item for item in self.shards if item.layer_id == layer_id)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["shards"] = [item.to_dict() for item in self.shards]
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ShardComplexityPolicy:
    max_scope_refs_per_shard: int = 8
    max_files_per_shard: int = 12
    max_symbols_per_shard: int = 80
    large_file_symbol_threshold: int = 120
    force_single_file_modules: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ShardComplexityPolicy":
        payload = dict(payload or {})
        return cls(
            max_scope_refs_per_shard=max(1, _int_value(payload.get("max_scope_refs_per_shard"), 8)),
            max_files_per_shard=max(1, _int_value(payload.get("max_files_per_shard"), 12)),
            max_symbols_per_shard=max(1, _int_value(payload.get("max_symbols_per_shard"), 80)),
            large_file_symbol_threshold=max(1, _int_value(payload.get("large_file_symbol_threshold"), 120)),
            force_single_file_modules=bool(payload.get("force_single_file_modules", True)),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


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

