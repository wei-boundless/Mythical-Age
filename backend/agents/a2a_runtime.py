from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agents.a2a_cards import get_agent_card
from agents.a2a_extensions import build_handle_extensions, merge_extensions
from capability_system.local_mcp_registry import build_local_mcp_agent_map


A2A_COMPATIBLE_PROTOCOL_VERSION = "a2a-compatible.v1"
AGENT_ID_BY_MCP_ROUTE: dict[str, str] = build_local_mcp_agent_map()


@dataclass(frozen=True, slots=True)
class A2ATaskEnvelope:
    task_id: str
    context_id: str
    agent_id: str
    status: str
    stream_event_type: str
    protocol_version: str = A2A_COMPATIBLE_PROTOCOL_VERSION
    message_id: str = ""
    parts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def task_envelope_from_request(request: Any) -> A2ATaskEnvelope:
    agent_id = _request_agent_id(request)
    card = get_agent_card(agent_id)
    return A2ATaskEnvelope(
        task_id=str(request.request_id or request.message_id or ""),
        context_id=str(request.session_id or ""),
        agent_id=agent_id,
        status="submitted",
        stream_event_type="task.started",
        protocol_version=str(request.protocol_version or A2A_COMPATIBLE_PROTOCOL_VERSION),
        message_id=str(request.message_id or request.request_id or ""),
        parts=[{"kind": "text", "text": str(request.query or "")}] if str(request.query or "").strip() else [],
        metadata={
            "mcp_route": str(getattr(request, "mcp_route", "") or ""),
            "target_handle_kind": str(request.target_handle_kind or "none"),
            "agent_card": card.to_dict() if card is not None else None,
        },
        extensions=dict(request.extensions or {}),
    )


def task_envelope_from_result(
    *,
    request: Any | None,
    result: Any,
    canonical: Any | None = None,
) -> A2ATaskEnvelope:
    canonical_result = canonical or result.canonical_result
    agent_id = _result_agent_id(result, fallback_mcp_route=getattr(request, "mcp_route", ""))
    handle_extensions = build_handle_extensions(
        object_handle_ids=list(getattr(canonical_result, "object_handle_ids", []) or []),
        result_handle_ids=list(getattr(canonical_result, "result_handle_ids", []) or []),
        evidence_refs=list(getattr(canonical_result, "evidence_refs", []) or []),
        artifact_refs=list(getattr(canonical_result, "artifact_refs", []) or []),
        binding_owner_task_id=str(getattr(result, "binding_owner_task_id", "") or ""),
    )
    request_extensions = dict(getattr(request, "extensions", {}) or {})
    result_extensions = dict(getattr(result, "extensions", {}) or {})
    return A2ATaskEnvelope(
        task_id=str(getattr(request, "request_id", "") or getattr(request, "message_id", "") or ""),
        context_id=str(getattr(request, "session_id", "") or ""),
        agent_id=agent_id,
        status=_task_status_from_mcp_status(result.status),
        stream_event_type=_stream_event_type_from_mcp_status(result.status),
        protocol_version=str(getattr(request, "protocol_version", "") or A2A_COMPATIBLE_PROTOCOL_VERSION),
        message_id=str(getattr(request, "message_id", "") or getattr(request, "request_id", "") or ""),
        parts=_result_parts(canonical_result),
        metadata={
            "mcp_name": str(getattr(result, "mcp_name", "") or ""),
            "mcp_status": str(result.status or ""),
            "result_kind": str(getattr(canonical_result, "result_kind", "") or ""),
        },
        extensions=merge_extensions(request_extensions, result_extensions, handle_extensions),
    )


def _result_parts(canonical: Any | None) -> list[dict[str, Any]]:
    if canonical is None:
        return []
    answer = str(canonical.answer or "").strip()
    if not answer:
        return []
    return [{"kind": "text", "text": answer}]


def _agent_id_for_mcp_route(mcp_route: str | None) -> str:
    return AGENT_ID_BY_MCP_ROUTE.get(str(mcp_route or "").strip(), "agent:local:unknown")


def _request_agent_id(request: Any | None, *, fallback_mcp_route: str = "") -> str:
    if request is None:
        return _agent_id_for_mcp_route(fallback_mcp_route)
    return str(getattr(request, "agent_id", "") or "").strip() or _agent_id_for_mcp_route(
        getattr(request, "mcp_route", fallback_mcp_route)
    )


def _result_agent_id(result: Any | None, *, fallback_mcp_route: str = "") -> str:
    if result is None:
        return _agent_id_for_mcp_route(fallback_mcp_route)
    return str(getattr(result, "agent_id", "") or "").strip() or _agent_id_for_mcp_route(
        getattr(result, "mcp_name", fallback_mcp_route)
    )


def _task_status_from_mcp_status(status: str | None) -> str:
    normalized = str(status or "").strip()
    if normalized == "ok":
        return "completed"
    if normalized == "clarify":
        return "requires_input"
    if normalized in {"degraded", "error"}:
        return "failed"
    return "working"


def _stream_event_type_from_mcp_status(status: str | None) -> str:
    normalized = str(status or "").strip()
    if normalized == "ok":
        return "task.completed"
    if normalized == "clarify":
        return "task.input_required"
    if normalized in {"degraded", "error"}:
        return "task.failed"
    return "task.updated"
