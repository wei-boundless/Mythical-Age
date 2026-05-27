from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SplitMergeIssue:
    code: str
    message: str
    severity: str = "error"
    graph_id: str = ""
    node_id: str = ""
    plan_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BatchRange:
    start: int
    end: int
    label: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BatchSpec:
    batch_id: str
    sequence_index: int
    unit_kind: str
    range: BatchRange
    input_contract_id: str = ""
    output_contract_id: str = ""
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["range"] = self.range.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class BatchLifecycleStep:
    step_id: str
    step_type: str
    title: str
    sequence_index: int
    depends_on: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    policy: dict[str, Any] = field(default_factory=dict)
    status: str = "planned"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["depends_on"] = list(self.depends_on)
        payload["consumes"] = list(self.consumes)
        payload["produces"] = list(self.produces)
        return payload


@dataclass(frozen=True, slots=True)
class BatchLifecyclePlan:
    plan_id: str
    graph_id: str
    node_id: str
    split_plan_id: str
    batch_id: str
    sequence_index: int
    unit_kind: str
    range: BatchRange
    steps: tuple[BatchLifecycleStep, ...] = ()
    status: str = "planned"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["range"] = self.range.to_dict()
        payload["steps"] = [item.to_dict() for item in self.steps]
        return payload


@dataclass(frozen=True, slots=True)
class BatchAcceptancePolicy:
    mode: str = "review_then_commit"
    review_graph_id: str = ""
    review_node_id: str = ""
    repair_policy: str = "repair_until_pass_or_manual_gate"
    max_repair_rounds: int = 3
    commit_visibility: str = "next_batch_after_acceptance"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BatchMergePolicy:
    mode: str = "wait_all_committed"
    result_order: str = "batch_sequence"
    allow_partial: bool = False
    final_review_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BatchMergeReadinessPlan:
    plan_id: str
    graph_id: str
    node_id: str
    split_plan_id: str
    merge_id: str
    mode: str
    result_order: str
    allow_partial: bool
    final_review_required: bool
    depends_on_batch_ids: tuple[str, ...] = ()
    depends_on_commit_step_ids: tuple[str, ...] = ()
    ready_condition: str = "all_batches_committed"
    status: str = "planned"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["depends_on_batch_ids"] = list(self.depends_on_batch_ids)
        payload["depends_on_commit_step_ids"] = list(self.depends_on_commit_step_ids)
        return payload


@dataclass(frozen=True, slots=True)
class StaticSplitPlan:
    plan_id: str
    graph_id: str
    node_id: str
    unit_kind: str
    requested_count: int
    batch_size: int
    range_start: int
    batches: tuple[BatchSpec, ...] = ()
    batch_lifecycle_plans: tuple[BatchLifecyclePlan, ...] = ()
    merge_readiness_plan: BatchMergeReadinessPlan | None = None
    acceptance_policy: BatchAcceptancePolicy = field(default_factory=BatchAcceptancePolicy)
    merge_policy: BatchMergePolicy = field(default_factory=BatchMergePolicy)
    issues: tuple[SplitMergeIssue, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["batches"] = [item.to_dict() for item in self.batches]
        payload["batch_lifecycle_plans"] = [item.to_dict() for item in self.batch_lifecycle_plans]
        payload["merge_readiness_plan"] = self.merge_readiness_plan.to_dict() if self.merge_readiness_plan else None
        payload["acceptance_policy"] = self.acceptance_policy.to_dict()
        payload["merge_policy"] = self.merge_policy.to_dict()
        payload["issues"] = [item.to_dict() for item in self.issues]
        payload["valid"] = self.valid
        return payload


