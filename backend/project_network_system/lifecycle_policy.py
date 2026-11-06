from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .build_contract_models import ProjectNetworkBuildContract


GENERATION_STATUS_TRANSITIONS = {
    "draft": {"candidate", "rejected"},
    "candidate": {"validating", "published", "rejected", "superseded"},
    "validating": {"published", "rejected", "candidate"},
    "published": {"superseded", "rolled_back"},
    "superseded": {"rolled_back"},
    "rejected": set(),
    "rolled_back": set(),
}


@dataclass(frozen=True, slots=True)
class GraphMaterializationBudget:
    max_materialized_nodes: int = 120
    max_parallel_shards_per_layer: int = 40
    max_layers: int = 6
    max_files_in_scope: int = 80
    max_relation_complexity: int = 120
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "GraphMaterializationBudget":
        payload = dict(payload or {})
        return cls(
            max_materialized_nodes=max(1, _int_value(payload.get("max_materialized_nodes"), 120)),
            max_parallel_shards_per_layer=max(1, _int_value(payload.get("max_parallel_shards_per_layer"), 40)),
            max_layers=max(1, _int_value(payload.get("max_layers"), 6)),
            max_files_in_scope=max(1, _int_value(payload.get("max_files_in_scope"), 80)),
            max_relation_complexity=max(1, _int_value(payload.get("max_relation_complexity"), 120)),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class GraphMaterializationModeDecision:
    mode: str
    reason: str
    budget: GraphMaterializationBudget
    observed: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.materialization_mode_decision"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["budget"] = self.budget.to_dict()
        return _drop_empty(payload)


def choose_materialization_mode(
    contract: ProjectNetworkBuildContract,
    observed: dict[str, Any],
    *,
    budget: GraphMaterializationBudget | None = None,
) -> GraphMaterializationModeDecision:
    active_budget = budget or GraphMaterializationBudget()
    estimated_nodes = _int_value(observed.get("estimated_nodes"), 0)
    estimated_parallel_shards = _int_value(observed.get("estimated_parallel_shards"), 0)
    estimated_layers = _int_value(observed.get("estimated_layers"), len(contract.target_layers))
    files_in_scope = _int_value(observed.get("files_in_scope"), len(contract.scope.module_refs) or len(contract.scope.root_paths))
    relation_complexity = _int_value(observed.get("relation_complexity"), 0)
    if contract.build_mode in {"incremental", "repair"}:
        return GraphMaterializationModeDecision(
            mode="rolling_one_hop",
            reason=f"build_mode {contract.build_mode} favors localized graph materialization",
            budget=active_budget,
            observed=dict(observed or {}),
        )
    if (
        estimated_nodes > active_budget.max_materialized_nodes
        or estimated_parallel_shards > active_budget.max_parallel_shards_per_layer
        or estimated_layers > active_budget.max_layers
        or files_in_scope > active_budget.max_files_in_scope
        or relation_complexity > active_budget.max_relation_complexity
    ):
        return GraphMaterializationModeDecision(
            mode="rolling_one_hop",
            reason="estimated graph exceeds static materialization budget",
            budget=active_budget,
            observed=dict(observed or {}),
        )
    return GraphMaterializationModeDecision(
        mode="static_pre_materialized",
        reason="estimated graph is within static materialization budget",
        budget=active_budget,
        observed=dict(observed or {}),
    )


def validate_generation_status_transition(current_status: str, next_status: str) -> bool:
    return str(next_status or "") in GENERATION_STATUS_TRANSITIONS.get(str(current_status or ""), set())


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}

