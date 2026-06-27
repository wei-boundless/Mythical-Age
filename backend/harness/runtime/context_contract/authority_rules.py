from __future__ import annotations

from typing import Any


def classify_context_spec(spec: dict[str, Any], *, index: int) -> dict[str, str]:
    kind = _normalized(spec.get("kind") or spec.get("visible_kind") or spec.get("title") or "context_fragment")
    source_ref = str(spec.get("source_ref") or spec.get("id") or f"context_spec:{index}")
    cache_role = _normalized(spec.get("cache_role") or spec.get("cache_scope") or "volatile")
    metadata = dict(spec.get("metadata") or {})
    authority = str(metadata.get("authority") or metadata.get("content_source") or spec.get("authority") or "harness.runtime.compiler")
    layer, semantic_time, semantic_kind, agent_use_contract = _semantic_contract(kind, cache_role, metadata)
    visibility = _visibility(kind, metadata)
    ttl = _ttl(cache_role=cache_role, semantic_time=semantic_time, visibility=visibility)
    return {
        "node_id": _node_id(kind=kind, source_ref=source_ref, index=index),
        "semantic_kind": semantic_kind,
        "semantic_layer": layer,
        "semantic_time": semantic_time,
        "authority": authority,
        "source_ref": source_ref,
        "scope": _scope(spec),
        "ttl": ttl,
        "visibility": visibility,
        "agent_use_contract": agent_use_contract,
        "commit_policy": _commit_policy(ttl=ttl, visibility=visibility),
        "replay_policy": _replay_policy(ttl=ttl, visibility=visibility),
        "cache_tier": _cache_tier(cache_role=cache_role, ttl=ttl, visibility=visibility),
        "content_mode": _content_mode(spec),
    }


def hidden_transport_node(packet_id: str, *, source_ref: str = "provider_transport_binding") -> dict[str, str]:
    return {
        "node_id": f"{packet_id}:l8_provider_transport",
        "semantic_kind": "provider_transport",
        "semantic_layer": "L8",
        "semantic_time": "HiddenTransport",
        "authority": "runtime.model_gateway.provider_payload",
        "source_ref": source_ref,
        "scope": "provider_request",
        "ttl": "current_provider_request",
        "visibility": "provider_transport",
        "agent_use_contract": "Hidden provider transport binding. Do not project to agent prompt, memory, or sealed history.",
        "commit_policy": "never_commit",
        "replay_policy": "never_replay",
        "cache_tier": "hidden",
        "content_mode": "ref_only",
    }


def _semantic_contract(kind: str, cache_role: str, metadata: dict[str, Any]) -> tuple[str, str, str, str]:
    if "tool_call_contract" in kind or "tool_catalog" in kind or "action_schema" in kind or "capability" in kind:
        return "L3", "Future", "capability_surface", "Use this to understand currently available actions and tool-selection rules."
    if "memory" in kind:
        return "L4", "Past", "memory_hint", "Treat this as a hint that must be verified against current evidence before use."
    if "evidence" in kind or "transcript" in kind or "observation" in kind or "history" in kind:
        return "L5", "Past", "evidence", "Use as replayed or observed evidence; do not treat old runtime boundaries as current permission."
    if "runtime" in kind or "permission" in kind or "boundary" in kind or "authorization" in kind:
        return "L6", "Present", "runtime_boundary", "Use as the current-turn execution boundary and budget signal."
    if "feedback" in kind or "repair" in kind or "denial" in kind or "tool_result" in kind:
        return "L7", "Present", "feedback", "Use as actionable feedback for the next model decision."
    if "task" in kind or "contract" in kind or "goal" in kind:
        return "L2", "Present", "task_contract", "Use to understand the current task goal, scope, and acceptance criteria."
    if cache_role in {"session_stable", "stable", "prefix_stable"} or "identity" in kind or "operating" in kind or "instruction" in kind:
        return "L1", "Self", "operating_contract", "Use as stable operating identity and long-lived behavior contract."
    if str(metadata.get("authority_class") or ""):
        return "L6", "Present", "runtime_boundary", "Use as current runtime state, not stable identity or sealed evidence."
    return "L2", "Present", "task_contract", "Use as current turn context."


def _visibility(kind: str, metadata: dict[str, Any]) -> str:
    raw = _normalized(metadata.get("visibility") or metadata.get("transport_visibility") or "")
    if raw in {"provider_transport", "runtime_hidden", "agent_visible"}:
        return raw
    if "provider_tool" in kind or "sidecar" in kind or "transport" in kind:
        return "provider_transport"
    return "agent_visible"


def _ttl(*, cache_role: str, semantic_time: str, visibility: str) -> str:
    if visibility == "provider_transport":
        return "current_provider_request"
    if semantic_time == "Self":
        return "stable"
    if semantic_time == "Past":
        return "append_only"
    if cache_role in {"none", "volatile", "dynamic_tail"}:
        return "current_turn"
    return "current_turn"


def _scope(spec: dict[str, Any]) -> str:
    cache_scope = _normalized(spec.get("cache_scope") or "")
    if cache_scope in {"session", "task", "turn", "global"}:
        return cache_scope
    if cache_scope == "none":
        return "turn"
    return "turn"


def _commit_policy(*, ttl: str, visibility: str) -> str:
    if visibility == "provider_transport" or ttl == "current_provider_request":
        return "never_commit"
    if ttl == "append_only":
        return "seal_on_provider_success"
    if ttl == "stable":
        return "append_once"
    return "never_commit"


def _replay_policy(*, ttl: str, visibility: str) -> str:
    if visibility == "provider_transport":
        return "never_replay"
    if ttl in {"stable", "append_only"}:
        return "replay_as_history"
    return "current_only"


def _cache_tier(*, cache_role: str, ttl: str, visibility: str) -> str:
    if visibility == "provider_transport":
        return "hidden"
    if ttl == "stable":
        return "session"
    if ttl == "append_only":
        return "append-only"
    if cache_role in {"session", "session_stable"}:
        return "session"
    if cache_role in {"task", "task_stable"}:
        return "task"
    return "volatile"


def _content_mode(spec: dict[str, Any]) -> str:
    if spec.get("payload") is not None:
        return "full"
    if spec.get("content"):
        return "full"
    return "ref_only"


def _node_id(*, kind: str, source_ref: str, index: int) -> str:
    safe_kind = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in kind)[:80]
    safe_ref = "".join(ch if ch.isalnum() or ch in {"_", "-", ".", ":"} else "_" for ch in source_ref)[:80]
    return f"ctx:{index}:{safe_kind}:{safe_ref}"


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()
