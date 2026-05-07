from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from capability_system.local_mcp_registry import build_local_mcp_agent_map
from evidence.models import BindingCandidate, EvidenceArtifact, EvidenceEnvelope


MCPRoute = Literal["none", "retrieval", "pdf", "structured_data", "evidence_orchestrator"]
MCPStatus = Literal["ok", "degraded", "clarify", "error"]
MCPTaskStatus = Literal["submitted", "working", "completed", "failed", "requires_input"]

OFFICIAL_A2A_PROTOCOL_VERSION = "0.3.0"

AGENT_ID_BY_MCP_ROUTE: dict[str, str] = build_local_mcp_agent_map()


@dataclass(frozen=True, slots=True)
class MCPRequest:
    request_id: str
    session_id: str = ""
    query: str = ""
    mcp_route: MCPRoute = "none"
    task_frame: dict[str, Any] = field(default_factory=dict)
    bindings: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[str] = field(default_factory=list)
    evidence_policy: dict[str, Any] = field(default_factory=dict)
    target_handle_kind: str = "none"
    target_handle_id: str = ""
    upstream_object_handle_ids: list[str] = field(default_factory=list)
    upstream_result_handle_ids: list[str] = field(default_factory=list)
    owner_task_id: str = ""
    arbitration_reason: str = ""
    agent_id: str = ""
    message_id: str = ""
    protocol_version: str = OFFICIAL_A2A_PROTOCOL_VERSION
    extensions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["agent_id"] = request_agent_id(self)
        payload["message_id"] = self.message_id or self.request_id
        payload["protocol_version"] = self.protocol_version or OFFICIAL_A2A_PROTOCOL_VERSION
        payload["extensions"] = dict(self.extensions or {})
        return payload


@dataclass(frozen=True, slots=True)
class CanonicalResult:
    result_kind: str
    ok: bool
    answer: str
    evidence_refs: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    bindings: dict[str, Any] = field(default_factory=dict)
    projection_policy: str = "do_not_persist"
    degraded_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    object_handle_ids: list[str] = field(default_factory=list)
    result_handle_ids: list[str] = field(default_factory=list)
    primary_result_handle_id: str = ""
    degraded_reason_typed: str = ""
    presentation_hints: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MCPResult:
    mcp_name: str
    status: MCPStatus = "ok"
    evidence_envelope: EvidenceEnvelope | None = None
    artifact_updates: list[EvidenceArtifact] = field(default_factory=list)
    canonical_result: CanonicalResult | None = None
    binding_candidates: list[BindingCandidate] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    emitted_object_handles: list[dict[str, Any]] = field(default_factory=list)
    emitted_result_handles: list[dict[str, Any]] = field(default_factory=list)
    binding_owner_task_id: str = ""
    agent_id: str = ""
    task_status: MCPTaskStatus | str = ""
    stream_event_type: str = ""
    extensions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mcp_name": self.mcp_name,
            "status": self.status,
            "agent_id": result_agent_id(self),
            "task_status": self.task_status or task_status_from_mcp_status(self.status),
            "stream_event_type": self.stream_event_type or stream_event_type_from_mcp_status(self.status),
            "extensions": dict(self.extensions or {}),
            "evidence_envelope": self.evidence_envelope.to_dict() if self.evidence_envelope is not None else None,
            "artifact_updates": [item.to_dict() for item in self.artifact_updates],
            "canonical_result": self.canonical_result.to_dict() if self.canonical_result is not None else None,
            "binding_candidates": [item.to_dict() for item in self.binding_candidates],
            "diagnostics": dict(self.diagnostics),
            "emitted_object_handles": [dict(item) for item in self.emitted_object_handles],
            "emitted_result_handles": [dict(item) for item in self.emitted_result_handles],
            "binding_owner_task_id": self.binding_owner_task_id,
        }


@dataclass(frozen=True, slots=True)
class MCPExecutionPlan:
    mcp_route: MCPRoute = "none"
    request: MCPRequest | None = None
    expected_result: Literal["evidence", "canonical", "clarification"] = "evidence"
    artifact_refs: list[str] = field(default_factory=list)
    candidate_refs: list[str] = field(default_factory=list)
    fallback_execution_kind: Literal["agent", "builtin_tool_lane", "none"] = "agent"
    cutover_mode: Literal["shadow", "primary", "disabled"] = "primary"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mcp_route": self.mcp_route,
            "request": self.request.to_dict() if self.request is not None else None,
            "expected_result": self.expected_result,
            "artifact_refs": list(self.artifact_refs),
            "candidate_refs": list(self.candidate_refs),
            "fallback_execution_kind": self.fallback_execution_kind,
            "cutover_mode": self.cutover_mode,
        }


def agent_id_for_mcp_route(mcp_route: str | None) -> str:
    return AGENT_ID_BY_MCP_ROUTE.get(str(mcp_route or "").strip(), "agent:local:unknown")


def request_agent_id(request: MCPRequest | None, *, fallback_mcp_route: str = "") -> str:
    if request is None:
        return agent_id_for_mcp_route(fallback_mcp_route)
    return str(request.agent_id or "").strip() or agent_id_for_mcp_route(request.mcp_route or fallback_mcp_route)


def result_agent_id(result: MCPResult | None, *, fallback_mcp_route: str = "") -> str:
    if result is None:
        return agent_id_for_mcp_route(fallback_mcp_route)
    return str(result.agent_id or "").strip() or agent_id_for_mcp_route(result.mcp_name or fallback_mcp_route)


def task_status_from_mcp_status(status: str | None) -> MCPTaskStatus:
    normalized = str(status or "").strip()
    if normalized == "ok":
        return "completed"
    if normalized == "clarify":
        return "requires_input"
    if normalized in {"degraded", "error"}:
        return "failed"
    return "working"


def stream_event_type_from_mcp_status(status: str | None) -> str:
    normalized = str(status or "").strip()
    if normalized == "ok":
        return "task.completed"
    if normalized == "clarify":
        return "task.input_required"
    if normalized in {"degraded", "error"}:
        return "task.failed"
    return "task.updated"
