from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


WorkProductConfidence = Literal["deterministic", "derived", "hypothesis", "rejected", "needs_human_review"]
WorkProductStatus = Literal["candidate", "accepted", "rejected", "superseded", "published"]
WorkProductReducerPolicy = Literal[
    "append_by_work_product_id",
    "merge_by_stable_ref",
    "replace_by_generation",
    "reject_on_anchor_mismatch",
    "merge_scope_coverage",
]


@dataclass(frozen=True, slots=True)
class WorkProductRef:
    work_product_id: str
    product_domain: str
    product_kind: str
    stable_ref: str = ""
    payload_ref: str = ""
    status: WorkProductStatus = "candidate"
    generation: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.work_product_ref"

    def __post_init__(self) -> None:
        if self.authority != "task_system.work_product_ref":
            raise ValueError("WorkProductRef authority must be task_system.work_product_ref")
        _require_text(self.work_product_id, "WorkProductRef requires work_product_id")
        _require_text(self.product_domain, "WorkProductRef requires product_domain")
        _require_text(self.product_kind, "WorkProductRef requires product_kind")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class WorkProduct:
    work_product_id: str
    task_environment_id: str
    task_instance_id: str
    source_episode_id: str
    product_domain: str
    product_kind: str
    confidence: WorkProductConfidence
    status: WorkProductStatus = "candidate"
    stable_ref: str = ""
    payload_ref: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    anchor_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    acceptance_claims: tuple[dict[str, Any], ...] = ()
    downstream_refs: dict[str, Any] = field(default_factory=dict)
    generation: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.work_product"

    def __post_init__(self) -> None:
        if self.authority != "task_system.work_product":
            raise ValueError("WorkProduct authority must be task_system.work_product")
        _require_text(self.work_product_id, "WorkProduct requires work_product_id")
        _require_text(self.task_environment_id, "WorkProduct requires task_environment_id")
        _require_text(self.task_instance_id, "WorkProduct requires task_instance_id")
        _require_text(self.source_episode_id, "WorkProduct requires source_episode_id")
        _require_text(self.product_domain, "WorkProduct requires product_domain")
        _require_text(self.product_kind, "WorkProduct requires product_kind")
        if self.status in {"accepted", "published"} and not (self.stable_ref or self.payload_ref or self.payload):
            raise ValueError("accepted/published WorkProduct requires stable_ref, payload_ref, or payload")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkProduct":
        data = dict(payload or {})
        return cls(
            work_product_id=str(data.get("work_product_id") or ""),
            task_environment_id=str(data.get("task_environment_id") or ""),
            task_instance_id=str(data.get("task_instance_id") or ""),
            source_episode_id=str(data.get("source_episode_id") or ""),
            product_domain=str(data.get("product_domain") or ""),
            product_kind=str(data.get("product_kind") or ""),
            confidence=str(data.get("confidence") or "derived"),  # type: ignore[arg-type]
            status=str(data.get("status") or "candidate"),  # type: ignore[arg-type]
            stable_ref=str(data.get("stable_ref") or ""),
            payload_ref=str(data.get("payload_ref") or ""),
            payload=dict(data.get("payload") or {}),
            evidence_refs=_tuple_of_strings(data.get("evidence_refs")),
            anchor_refs=_tuple_of_strings(data.get("anchor_refs")),
            artifact_refs=_tuple_of_strings(data.get("artifact_refs")),
            acceptance_claims=tuple(dict(item) for item in list(data.get("acceptance_claims") or []) if isinstance(item, dict)),
            downstream_refs=dict(data.get("downstream_refs") or {}),
            generation=_int(data.get("generation")),
            created_at=_float(data.get("created_at")),
            updated_at=_float(data.get("updated_at")),
            metadata=dict(data.get("metadata") or {}),
            authority=str(data.get("authority") or "task_system.work_product"),
        )

    def ref(self) -> WorkProductRef:
        return WorkProductRef(
            work_product_id=self.work_product_id,
            product_domain=self.product_domain,
            product_kind=self.product_kind,
            stable_ref=self.stable_ref,
            payload_ref=self.payload_ref,
            status=self.status,
            generation=self.generation,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        payload["anchor_refs"] = list(self.anchor_refs)
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["acceptance_claims"] = [dict(item) for item in self.acceptance_claims]
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class TaskReducerInput:
    task_environment_id: str
    episode_id: str
    episode_result_ref: str
    reduction_policy: WorkProductReducerPolicy = "append_by_work_product_id"
    work_product_candidates: tuple[WorkProduct, ...] = ()
    state_update_proposals: tuple[dict[str, Any], ...] = ()
    memory_candidates: tuple[dict[str, Any], ...] = ()
    artifact_refs: tuple[str, ...] = ()
    graph_binding_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_reducer_input"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_reducer_input":
            raise ValueError("TaskReducerInput authority must be task_system.task_reducer_input")
        _require_text(self.task_environment_id, "TaskReducerInput requires task_environment_id")
        _require_text(self.episode_id, "TaskReducerInput requires episode_id")
        _require_text(self.episode_result_ref, "TaskReducerInput requires episode_result_ref")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["work_product_candidates"] = [item.to_dict() for item in self.work_product_candidates]
        payload["state_update_proposals"] = [dict(item) for item in self.state_update_proposals]
        payload["memory_candidates"] = [dict(item) for item in self.memory_candidates]
        payload["artifact_refs"] = list(self.artifact_refs)
        return _drop_empty(payload)


def _require_text(value: str, message: str) -> None:
    if not str(value or "").strip():
        raise ValueError(message)


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace(",", "\n").splitlines() if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
