from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


WorkProductKind = Literal[
    "source_snapshot",
    "system_map",
    "folder_index",
    "module_index",
    "endpoint_index",
    "relation_candidates",
    "directory_summary",
    "coverage_report",
    "conflict_report",
    "layer_summary",
    "publish_candidate",
]
WorkProductConfidence = Literal["deterministic", "derived", "hypothesis", "rejected", "needs_human_review"]
WorkProductStatus = Literal["candidate", "accepted", "rejected", "superseded", "published"]
WorkProductReducerPolicy = Literal[
    "append_by_work_product_id",
    "merge_by_stable_ref",
    "replace_by_generation",
    "merge_scope_coverage",
    "reject_on_anchor_mismatch",
]


@dataclass(frozen=True, slots=True)
class WorkProductRef:
    work_product_id: str
    product_kind: str
    layer_id: str = ""
    payload_ref: str = ""
    status: str = "candidate"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class GraphBuildWorkProductEnvelope:
    work_product_id: str
    build_id: str
    graph_run_id: str
    node_id: str
    shard_id: str
    layer_id: str
    product_kind: WorkProductKind
    contract_id: str = ""
    payload_ref: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    anchor_refs: tuple[str, ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)
    confidence: WorkProductConfidence = "derived"
    status: WorkProductStatus = "candidate"
    stable_ref: str = ""
    generation: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.project_network.graph_build_work_product"

    def __post_init__(self) -> None:
        if self.authority != "task_system.project_network.graph_build_work_product":
            raise ValueError("GraphBuildWorkProductEnvelope authority mismatch")
        if not str(self.work_product_id or "").strip():
            raise ValueError("GraphBuildWorkProductEnvelope requires work_product_id")
        if not str(self.build_id or "").strip():
            raise ValueError("GraphBuildWorkProductEnvelope requires build_id")
        if self.product_kind not in {
            "source_snapshot",
            "system_map",
            "folder_index",
            "module_index",
            "endpoint_index",
            "relation_candidates",
            "directory_summary",
            "coverage_report",
            "conflict_report",
            "layer_summary",
            "publish_candidate",
        }:
            raise ValueError("unsupported GraphBuildWorkProductEnvelope product_kind")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphBuildWorkProductEnvelope":
        payload = dict(payload or {})
        return cls(
            work_product_id=str(payload.get("work_product_id") or payload.get("id") or ""),
            build_id=str(payload.get("build_id") or ""),
            graph_run_id=str(payload.get("graph_run_id") or ""),
            node_id=str(payload.get("node_id") or ""),
            shard_id=str(payload.get("shard_id") or ""),
            layer_id=str(payload.get("layer_id") or ""),
            product_kind=str(payload.get("product_kind") or "layer_summary"),  # type: ignore[arg-type]
            contract_id=str(payload.get("contract_id") or ""),
            payload_ref=str(payload.get("payload_ref") or ""),
            payload=dict(payload.get("payload") or {}),
            evidence_refs=_tuple_of_strings(payload.get("evidence_refs")),
            anchor_refs=_tuple_of_strings(payload.get("anchor_refs")),
            coverage=dict(payload.get("coverage") or {}),
            confidence=str(payload.get("confidence") or "derived"),  # type: ignore[arg-type]
            status=str(payload.get("status") or "candidate"),  # type: ignore[arg-type]
            stable_ref=str(payload.get("stable_ref") or ""),
            generation=_int_value(payload.get("generation"), 0),
            metadata=dict(payload.get("metadata") or {}),
        )

    def ref(self) -> WorkProductRef:
        return WorkProductRef(
            work_product_id=self.work_product_id,
            product_kind=self.product_kind,
            layer_id=self.layer_id,
            payload_ref=self.payload_ref,
            status=self.status,
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class WorkProductChannel:
    channel_id: str
    layer_id: str
    accepted_product_kinds: tuple[str, ...]
    reducer_policy: WorkProductReducerPolicy
    identity_keys: tuple[str, ...] = ()
    conflict_policy: str = "emit_conflict_product"
    visibility: str = "aggregation_nodes_only"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.project_network.work_product_channel"

    def __post_init__(self) -> None:
        if self.authority != "task_system.project_network.work_product_channel":
            raise ValueError("WorkProductChannel authority mismatch")
        if not str(self.channel_id or "").strip():
            raise ValueError("WorkProductChannel requires channel_id")
        if self.reducer_policy not in {
            "append_by_work_product_id",
            "merge_by_stable_ref",
            "replace_by_generation",
            "merge_scope_coverage",
            "reject_on_anchor_mismatch",
        }:
            raise ValueError("unsupported WorkProductChannel reducer_policy")

    def accepts(self, product: GraphBuildWorkProductEnvelope) -> bool:
        return not self.accepted_product_kinds or product.product_kind in set(self.accepted_product_kinds)

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


def reduce_work_products(
    channel: WorkProductChannel,
    existing: tuple[GraphBuildWorkProductEnvelope, ...],
    incoming: tuple[GraphBuildWorkProductEnvelope, ...],
) -> tuple[GraphBuildWorkProductEnvelope, ...]:
    accepted = tuple(item for item in incoming if channel.accepts(item))
    if channel.reducer_policy == "append_by_work_product_id":
        return _dedupe_by_key((*existing, *accepted), lambda item: item.work_product_id)
    if channel.reducer_policy == "merge_by_stable_ref":
        return _dedupe_by_key((*existing, *accepted), lambda item: item.stable_ref or item.work_product_id)
    if channel.reducer_policy == "replace_by_generation":
        items = _dedupe_by_key((*existing, *accepted), lambda item: item.stable_ref or item.layer_id or item.work_product_id)
        latest: dict[str, GraphBuildWorkProductEnvelope] = {}
        for item in items:
            key = item.stable_ref or item.layer_id or item.work_product_id
            current = latest.get(key)
            if current is None or item.generation >= current.generation:
                latest[key] = item
        return tuple(latest.values())
    if channel.reducer_policy == "merge_scope_coverage":
        return _dedupe_by_key((*existing, *accepted), lambda item: item.stable_ref or item.work_product_id)
    if channel.reducer_policy == "reject_on_anchor_mismatch":
        return tuple(item for item in _dedupe_by_key((*existing, *accepted), lambda item: item.stable_ref or item.work_product_id) if item.anchor_refs)
    return (*existing, *accepted)


def _dedupe_by_key(
    products: tuple[GraphBuildWorkProductEnvelope, ...],
    key_fn: Any,
) -> tuple[GraphBuildWorkProductEnvelope, ...]:
    ordered: dict[str, GraphBuildWorkProductEnvelope] = {}
    for item in products:
        key = str(key_fn(item) or item.work_product_id)
        ordered[key] = item
    return tuple(ordered.values())


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
