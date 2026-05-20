from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


DelegationStatus = Literal["pending", "running", "completed", "failed", "blocked", "invalid_output", "killed"]


@dataclass(frozen=True, slots=True)
class DelegationContextPolicy:
    parent_context: str = "minimal_task_brief"
    child_context: str = "delegation_scoped"
    return_policy: str = "summary_and_refs_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DelegationTimeoutPolicy:
    timeout_seconds: float = 90.0
    max_turns: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentDelegationRequest:
    request_id: str
    task_run_id: str
    session_id: str
    parent_agent_run_ref: str
    source_agent_id: str
    target_agent_id: str
    delegation_kind: str
    instruction: str
    input_payload: dict[str, Any]
    context_policy: dict[str, Any] = field(default_factory=dict)
    expected_output_contract: dict[str, Any] = field(default_factory=dict)
    timeout_policy: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.agent_delegation_request"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.agent_delegation_request":
            raise ValueError("AgentDelegationRequest authority must be orchestration.agent_delegation_request")
        if not self.request_id:
            raise ValueError("AgentDelegationRequest requires request_id")
        if not self.task_run_id:
            raise ValueError("AgentDelegationRequest requires task_run_id")
        if not self.parent_agent_run_ref:
            raise ValueError("AgentDelegationRequest requires parent_agent_run_ref")
        if not self.source_agent_id:
            raise ValueError("AgentDelegationRequest requires source_agent_id")
        if not self.target_agent_id and not self.delegation_kind:
            raise ValueError("AgentDelegationRequest requires target_agent_id or delegation_kind")
        if not self.instruction:
            raise ValueError("AgentDelegationRequest requires instruction")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentDelegationResult:
    result_id: str
    request_id: str
    task_run_id: str
    parent_agent_run_ref: str
    child_agent_run_ref: str
    target_agent_id: str
    status: DelegationStatus
    summary: str
    answer_candidate: str = ""
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    confidence: str = "unknown"
    limitations: tuple[str, ...] = ()
    followup_questions: tuple[str, ...] = ()
    consumed_handles: tuple[str, ...] = ()
    produced_handles: tuple[str, ...] = ()
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.agent_delegation_result"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.agent_delegation_result":
            raise ValueError("AgentDelegationResult authority must be orchestration.agent_delegation_result")
        if not self.result_id:
            raise ValueError("AgentDelegationResult requires result_id")
        if not self.request_id:
            raise ValueError("AgentDelegationResult requires request_id")
        if not self.task_run_id:
            raise ValueError("AgentDelegationResult requires task_run_id")
        if not self.summary:
            raise ValueError("AgentDelegationResult requires summary")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("evidence_refs", "artifact_refs", "limitations", "followup_questions", "consumed_handles", "produced_handles"):
            payload[key] = list(payload[key])
        return payload


def delegation_request_from_dict(payload: dict[str, Any]) -> AgentDelegationRequest:
    return AgentDelegationRequest(
        request_id=str(payload.get("request_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        parent_agent_run_ref=str(payload.get("parent_agent_run_ref") or ""),
        source_agent_id=str(payload.get("source_agent_id") or ""),
        target_agent_id=str(payload.get("target_agent_id") or ""),
        delegation_kind=str(payload.get("delegation_kind") or ""),
        instruction=str(payload.get("instruction") or ""),
        input_payload=dict(payload.get("input_payload") or {}),
        context_policy=dict(payload.get("context_policy") or {}),
        expected_output_contract=dict(payload.get("expected_output_contract") or {}),
        timeout_policy=dict(payload.get("timeout_policy") or {}),
        created_at=float(payload.get("created_at") or 0.0),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def delegation_result_from_dict(payload: dict[str, Any]) -> AgentDelegationResult:
    return AgentDelegationResult(
        result_id=str(payload.get("result_id") or ""),
        request_id=str(payload.get("request_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        parent_agent_run_ref=str(payload.get("parent_agent_run_ref") or ""),
        child_agent_run_ref=str(payload.get("child_agent_run_ref") or ""),
        target_agent_id=str(payload.get("target_agent_id") or ""),
        status=payload.get("status", "failed"),
        summary=str(payload.get("summary") or ""),
        answer_candidate=str(payload.get("answer_candidate") or ""),
        evidence_refs=tuple(str(item) for item in list(payload.get("evidence_refs") or []) if str(item)),
        artifact_refs=tuple(str(item) for item in list(payload.get("artifact_refs") or []) if str(item)),
        confidence=str(payload.get("confidence") or "unknown"),
        limitations=tuple(str(item) for item in list(payload.get("limitations") or []) if str(item)),
        followup_questions=tuple(str(item) for item in list(payload.get("followup_questions") or []) if str(item)),
        consumed_handles=tuple(str(item) for item in list(payload.get("consumed_handles") or []) if str(item)),
        produced_handles=tuple(str(item) for item in list(payload.get("produced_handles") or []) if str(item)),
        created_at=float(payload.get("created_at") or 0.0),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )
