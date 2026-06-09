from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
import uuid
from typing import Any


HUMAN_EDGE_DECISION_AUTHORITY = "task_system.graph_instance.human_edge_decision"
HUMAN_ARTIFACT_SUBMISSION_AUTHORITY = "task_system.graph_instance.human_artifact_submission"

HUMAN_EDGE_DECISIONS = {"pass", "revise", "replace", "comment", "hold", "abort"}
HUMAN_EDGE_DECISION_STATUSES = {
    "draft",
    "submitted",
    "accepted",
    "applied",
    "rejected",
    "failed",
    "superseded",
}


@dataclass(frozen=True, slots=True)
class HumanArtifactSubmission:
    submission_id: str
    graph_task_instance_id: str
    path: str
    content: str = ""
    content_kind: str = ""
    repository_id: str = "instance"
    commit_policy: str = "project_file"
    memory_policy: str = "none"
    source: str = "human_edge_decision"
    artifact_ref: str = ""
    created_at: float = 0.0
    authority: str = HUMAN_ARTIFACT_SUBMISSION_AUTHORITY

    def __post_init__(self) -> None:
        if self.authority != HUMAN_ARTIFACT_SUBMISSION_AUTHORITY:
            raise ValueError("HumanArtifactSubmission authority must be task_system.graph_instance.human_artifact_submission")
        if not self.submission_id:
            raise ValueError("HumanArtifactSubmission requires submission_id")
        if not self.graph_task_instance_id:
            raise ValueError("HumanArtifactSubmission requires graph_task_instance_id")
        if not self.path:
            raise ValueError("HumanArtifactSubmission requires path")
        if not self.created_at:
            object.__setattr__(self, "created_at", time.time())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HumanEdgeDecision:
    decision_id: str
    graph_task_instance_id: str
    graph_id: str
    graph_run_id: str
    edge_id: str
    source_node_id: str
    target_node_id: str
    decision: str
    graph_harness_config_id: str = ""
    instruction: str = ""
    artifact_refs: tuple[dict[str, Any], ...] = ()
    content_submission: dict[str, Any] = field(default_factory=dict)
    operator: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    status: str = "submitted"
    apply_error: str = ""
    apply_result_ref: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = HUMAN_EDGE_DECISION_AUTHORITY

    def __post_init__(self) -> None:
        if self.authority != HUMAN_EDGE_DECISION_AUTHORITY:
            raise ValueError("HumanEdgeDecision authority must be task_system.graph_instance.human_edge_decision")
        if not self.decision_id:
            raise ValueError("HumanEdgeDecision requires decision_id")
        if not self.graph_task_instance_id:
            raise ValueError("HumanEdgeDecision requires graph_task_instance_id")
        if not self.graph_id:
            raise ValueError("HumanEdgeDecision requires graph_id")
        if not self.graph_run_id:
            raise ValueError("HumanEdgeDecision requires graph_run_id")
        if not self.edge_id:
            raise ValueError("HumanEdgeDecision requires edge_id")
        if not self.source_node_id:
            raise ValueError("HumanEdgeDecision requires source_node_id")
        if not self.target_node_id:
            raise ValueError("HumanEdgeDecision requires target_node_id")
        if self.decision not in HUMAN_EDGE_DECISIONS:
            raise ValueError(f"HumanEdgeDecision decision is not supported: {self.decision}")
        if self.status not in HUMAN_EDGE_DECISION_STATUSES:
            raise ValueError(f"HumanEdgeDecision status is not supported: {self.status}")
        if self.decision == "revise" and not self.instruction.strip():
            raise ValueError("HumanEdgeDecision revise requires instruction")
        if self.decision == "replace" and not self.content_submission and not self.artifact_refs:
            raise ValueError("HumanEdgeDecision replace requires content_submission or artifact_refs")
        now = time.time()
        if not self.created_at:
            object.__setattr__(self, "created_at", now)
        if not self.updated_at:
            object.__setattr__(self, "updated_at", self.created_at or now)
        if not self.idempotency_key:
            object.__setattr__(self, "idempotency_key", decision_idempotency_key(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        return payload


def human_edge_decision_from_dict(payload: dict[str, Any]) -> HumanEdgeDecision:
    return HumanEdgeDecision(
        decision_id=str(payload.get("decision_id") or "").strip(),
        graph_task_instance_id=str(payload.get("graph_task_instance_id") or "").strip(),
        graph_id=str(payload.get("graph_id") or "").strip(),
        graph_run_id=str(payload.get("graph_run_id") or "").strip(),
        graph_harness_config_id=str(payload.get("graph_harness_config_id") or "").strip(),
        edge_id=str(payload.get("edge_id") or "").strip(),
        source_node_id=str(payload.get("source_node_id") or "").strip(),
        target_node_id=str(payload.get("target_node_id") or "").strip(),
        decision=str(payload.get("decision") or "").strip(),
        instruction=str(payload.get("instruction") or "").strip(),
        artifact_refs=tuple(dict(item) for item in list(payload.get("artifact_refs") or []) if isinstance(item, dict)),
        content_submission=dict(payload.get("content_submission") or {}),
        operator=dict(payload.get("operator") or {}),
        idempotency_key=str(payload.get("idempotency_key") or "").strip(),
        status=str(payload.get("status") or "submitted").strip() or "submitted",
        apply_error=str(payload.get("apply_error") or "").strip(),
        apply_result_ref=str(payload.get("apply_result_ref") or "").strip(),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        metadata=dict(payload.get("metadata") or {}),
        authority=str(payload.get("authority") or HUMAN_EDGE_DECISION_AUTHORITY),
    )


def human_artifact_submission_from_dict(payload: dict[str, Any]) -> HumanArtifactSubmission:
    return HumanArtifactSubmission(
        submission_id=str(payload.get("submission_id") or "").strip(),
        graph_task_instance_id=str(payload.get("graph_task_instance_id") or "").strip(),
        repository_id=str(payload.get("repository_id") or "instance").strip() or "instance",
        path=str(payload.get("path") or "").strip(),
        content=str(payload.get("content") or ""),
        content_kind=str(payload.get("content_kind") or "").strip(),
        commit_policy=str(payload.get("commit_policy") or "project_file").strip() or "project_file",
        memory_policy=str(payload.get("memory_policy") or "none").strip() or "none",
        source=str(payload.get("source") or "human_edge_decision").strip() or "human_edge_decision",
        artifact_ref=str(payload.get("artifact_ref") or "").strip(),
        created_at=float(payload.get("created_at") or 0.0),
        authority=str(payload.get("authority") or HUMAN_ARTIFACT_SUBMISSION_AUTHORITY),
    )


def next_human_edge_decision_id(instance_id: str) -> str:
    return f"hedge.{_safe_id(instance_id)}.{uuid.uuid4().hex[:12]}"


def next_human_artifact_submission_id(instance_id: str) -> str:
    return f"hsub.{_safe_id(instance_id)}.{uuid.uuid4().hex[:12]}"


def decision_idempotency_key(payload: dict[str, Any]) -> str:
    parts = [
        str(payload.get("graph_task_instance_id") or ""),
        str(payload.get("graph_run_id") or ""),
        str(payload.get("edge_id") or ""),
        str(payload.get("decision") or ""),
        str(payload.get("instruction") or "")[:160],
        str(dict(payload.get("content_submission") or {}).get("path") or ""),
    ]
    for ref in list(payload.get("artifact_refs") or []):
        if isinstance(ref, dict):
            parts.append(str(ref.get("path") or ref.get("artifact_ref") or ""))
        else:
            parts.append(str(ref or ""))
    return ":".join(_safe_id(part, limit=80) for part in parts if part)


def _safe_id(value: str, *, limit: int = 120) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip())
    safe = safe.strip("._-")
    return (safe or "item")[:limit]

