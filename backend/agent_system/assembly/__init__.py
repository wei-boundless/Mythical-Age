from __future__ import annotations

from typing import Any

from a2a import types as a2a_types

OFFICIAL_A2A_PROTOCOL_VERSION = "0.3.0"
OFFICIAL_A2A_TRANSPORT = a2a_types.TransportProtocol.jsonrpc.value
DEFAULT_A2A_MESSAGE_TYPES = ("message/send", "message/stream", "task/status", "task/artifact")
DEFAULT_A2A_PART_TYPES = ("text", "data", "file")

EXT_OBJECT_HANDLES = "x-langchain-agent.object_handles"
EXT_RESULT_HANDLES = "x-langchain-agent.result_handles"
EXT_SUBSET_HANDLES = "x-langchain-agent.subset_handles"
EXT_EVIDENCE_REFS = "x-langchain-agent.evidence_refs"
EXT_ARTIFACT_REFS = "x-langchain-agent.artifact_refs"
EXT_BINDING_OWNER_TASK_ID = "x-langchain-agent.binding_owner_task_id"


def build_official_agent_card_catalog(*, base_url: str = "http://localhost/a2a") -> list[dict[str, Any]]:
    _ = base_url
    return []


def build_official_agent_card_index(*, base_url: str = "http://localhost/a2a") -> dict[str, dict[str, Any]]:
    _ = base_url
    return {}


def build_official_task_from_request(request: Any) -> dict[str, Any]:
    message_id = _message_id_from_request(request)
    task_id = str(getattr(request, "request_id", "") or message_id)
    context_id = str(getattr(request, "session_id", "") or "")
    message = a2a_types.Message(
        message_id=message_id,
        context_id=context_id,
        task_id=task_id,
        role=a2a_types.Role.agent.value,
        metadata={
            "agent_id": _request_agent_id(request),
            "mcp_route": str(getattr(request, "mcp_route", "") or ""),
            "protocol_version": _protocol_version_from_request(request),
            "target_handle_kind": str(getattr(request, "target_handle_kind", "") or "none"),
            "extensions": dict(getattr(request, "extensions", {}) or {}),
        },
        parts=_request_parts(request),
    )
    task = a2a_types.Task(
        id=task_id,
        context_id=context_id,
        status=a2a_types.TaskStatus(state=a2a_types.TaskState.submitted, message=message),
        metadata={
            "agent_id": _request_agent_id(request),
            "protocol_version": _protocol_version_from_request(request),
            "transport": OFFICIAL_A2A_TRANSPORT,
        },
    )
    return task.model_dump(by_alias=True, exclude_none=True)


def build_official_task_from_result(
    *,
    request: Any | None,
    result: Any,
    canonical: Any | None = None,
) -> dict[str, Any]:
    canonical_result = canonical or getattr(result, "canonical_result", None)
    message_id = _message_id_from_request(request)
    task_id = str(getattr(request, "request_id", "") or message_id)
    context_id = str(getattr(request, "session_id", "") or "")
    status = _task_state_from_status(str(getattr(result, "status", "") or "working"))
    extensions = _result_extensions(request=request, result=result, canonical=canonical_result)
    message = a2a_types.Message(
        message_id=message_id,
        context_id=context_id,
        task_id=task_id,
        role=a2a_types.Role.agent.value,
        metadata={
            "agent_id": _result_agent_id(request=request, result=result),
            "mcp_name": str(getattr(result, "mcp_name", "") or ""),
            "mcp_status": str(getattr(result, "status", "") or ""),
            "result_kind": str(getattr(canonical_result, "result_kind", "") or ""),
            "protocol_version": _protocol_version_from_request(request),
            "extensions": extensions,
        },
        parts=_result_parts(canonical_result),
    )
    task = a2a_types.Task(
        id=task_id,
        context_id=context_id,
        status=a2a_types.TaskStatus(state=status, message=message),
        artifacts=_artifact_parts(extensions) or None,
        metadata={
            "agent_id": _result_agent_id(request=request, result=result),
            "stream_event_type": _stream_event_type_from_status(str(getattr(result, "status", "") or "")),
            "protocol_version": _protocol_version_from_request(request),
            "transport": OFFICIAL_A2A_TRANSPORT,
            "extensions": extensions,
        },
    )
    return task.model_dump(by_alias=True, exclude_none=True)


def build_a2a_preview_for_coordination(
    *,
    graph_id: str,
    protocol_id: str,
    source_agent_id: str,
    target_agent_id: str,
    message_type: str,
    payload_contracts: list[str] | tuple[str, ...] = (),
    ack_policy: str = "explicit_ack",
    handoff_policy: str = "",
) -> dict[str, Any]:
    text_part = a2a_types.Part(
        root=a2a_types.TextPart(
            text=f"[{message_type}] graph {graph_id}",
            metadata={"protocol_id": protocol_id},
        )
    )
    data_part = a2a_types.Part(
        root=a2a_types.DataPart(
            data={
                "graph_id": graph_id,
                "source_agent_id": source_agent_id,
                "target_agent_id": target_agent_id,
                "message_type": message_type,
                "payload_contracts": list(payload_contracts),
                "ack_policy": ack_policy,
                "handoff_policy": handoff_policy,
            }
        )
    )
    message = a2a_types.Message(
        message_id=f"preview:{graph_id}:{source_agent_id}:{target_agent_id}:{message_type}",
        context_id=f"graph:{graph_id}",
        task_id=f"graph:{graph_id}",
        role=a2a_types.Role.agent.value,
        parts=[text_part, data_part],
        metadata={
            "protocol_id": protocol_id,
            "a2a_transport": OFFICIAL_A2A_TRANSPORT,
        },
    )
    task = a2a_types.Task(
        id=f"graph:{graph_id}",
        context_id=f"graph:{graph_id}",
        status=a2a_types.TaskStatus(
            state=a2a_types.TaskState.submitted,
            message=message,
        ),
        metadata={
            "protocol_id": protocol_id,
            "ack_policy": ack_policy,
            "handoff_policy": handoff_policy,
        },
    )
    return {
        "protocol_version": OFFICIAL_A2A_PROTOCOL_VERSION,
        "transport": OFFICIAL_A2A_TRANSPORT,
        "message": message.model_dump(by_alias=True, exclude_none=True),
        "task": task.model_dump(by_alias=True, exclude_none=True),
    }


def _request_parts(request: Any | None) -> list[a2a_types.Part]:
    query = str(getattr(request, "query", "") or "").strip()
    if not query:
        return []
    return [a2a_types.Part(root=a2a_types.TextPart(text=query))]


def _result_parts(canonical: Any | None) -> list[a2a_types.Part]:
    answer = str(getattr(canonical, "answer", "") or "").strip()
    if not answer:
        return []
    return [a2a_types.Part(root=a2a_types.TextPart(text=answer))]


def _artifact_parts(extensions: dict[str, Any]) -> list[a2a_types.Artifact]:
    artifact_refs = [str(item) for item in list(extensions.get(EXT_ARTIFACT_REFS) or []) if str(item).strip()]
    artifacts: list[a2a_types.Artifact] = []
    for index, ref in enumerate(artifact_refs, start=1):
        artifacts.append(
            a2a_types.Artifact(
                artifact_id=f"artifact:{index}",
                name=ref,
                parts=[a2a_types.Part(root=a2a_types.TextPart(text=ref))],
                metadata={"ref": ref},
            )
        )
    return artifacts


def _result_extensions(*, request: Any | None, result: Any, canonical: Any | None) -> dict[str, Any]:
    extensions = {
        **dict(getattr(request, "extensions", {}) or {}),
        **dict(getattr(result, "extensions", {}) or {}),
        **dict(getattr(canonical, "extensions", {}) or {}),
    }
    object_handle_ids = [str(item) for item in list(getattr(canonical, "object_handle_ids", []) or []) if str(item).strip()]
    result_handle_ids = [str(item) for item in list(getattr(canonical, "result_handle_ids", []) or []) if str(item).strip()]
    evidence_refs = [str(item) for item in list(getattr(canonical, "evidence_refs", []) or []) if str(item).strip()]
    artifact_refs = [str(item) for item in list(getattr(canonical, "artifact_refs", []) or []) if str(item).strip()]
    binding_owner_task_id = str(getattr(result, "binding_owner_task_id", "") or "").strip()
    if object_handle_ids:
        extensions[EXT_OBJECT_HANDLES] = object_handle_ids
    if result_handle_ids:
        extensions[EXT_RESULT_HANDLES] = result_handle_ids
    if evidence_refs:
        extensions[EXT_EVIDENCE_REFS] = evidence_refs
    if artifact_refs:
        extensions[EXT_ARTIFACT_REFS] = artifact_refs
    if binding_owner_task_id:
        extensions[EXT_BINDING_OWNER_TASK_ID] = binding_owner_task_id
    return extensions


def _task_state_from_status(status: str) -> a2a_types.TaskState:
    normalized = status.strip().lower()
    mapping = {
        "submitted": a2a_types.TaskState.submitted,
        "working": a2a_types.TaskState.working,
        "ok": a2a_types.TaskState.completed,
        "completed": a2a_types.TaskState.completed,
        "clarify": a2a_types.TaskState.input_required,
        "requires_input": a2a_types.TaskState.input_required,
        "degraded": a2a_types.TaskState.failed,
        "error": a2a_types.TaskState.failed,
        "failed": a2a_types.TaskState.failed,
        "rejected": a2a_types.TaskState.rejected,
    }
    return mapping.get(normalized, a2a_types.TaskState.unknown)


def _stream_event_type_from_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized in {"ok", "completed"}:
        return "task.completed"
    if normalized in {"clarify", "requires_input"}:
        return "task.input_required"
    if normalized in {"degraded", "error", "failed"}:
        return "task.failed"
    return "task.updated"


def _request_agent_id(request: Any | None) -> str:
    agent_id = str(getattr(request, "agent_id", "") or "").strip()
    if agent_id:
        return agent_id
    route = str(getattr(request, "mcp_route", "") or "").strip()
    return f"capability_unit:{route}" if route else "capability_unit:unknown"


def _result_agent_id(*, request: Any | None, result: Any | None) -> str:
    agent_id = str(getattr(result, "agent_id", "") or "").strip()
    if agent_id:
        return agent_id
    return _request_agent_id(request)


def _protocol_version_from_request(request: Any | None) -> str:
    return str(getattr(request, "protocol_version", "") or "").strip() or OFFICIAL_A2A_PROTOCOL_VERSION


def _message_id_from_request(request: Any | None) -> str:
    return str(getattr(request, "message_id", "") or getattr(request, "request_id", "") or "")
