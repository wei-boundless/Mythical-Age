from __future__ import annotations

from typing import Any


def build_model_message_spec(
    *,
    role: str,
    content: str,
    kind: str,
    source_ref: str,
    cache_scope: str,
    cache_role: str,
    compression_role: str,
    metadata: dict[str, Any] | None = None,
    prefix: bool = False,
) -> dict[str, Any]:
    normalized_kind = str(kind or "unknown_unplanned")
    normalized_cache_role = str(cache_role or "volatile")
    payload_metadata = dict(metadata or {})
    payload_metadata.setdefault(
        "content_source",
        message_spec_content_source(
            kind=normalized_kind,
            cache_role=normalized_cache_role,
            source_ref=str(source_ref or ""),
        ),
    )
    payload = {
        "role": str(role or "user"),
        "content": str(content or ""),
        "kind": normalized_kind,
        "source_ref": str(source_ref or ""),
        "cache_scope": str(cache_scope or "none"),
        "cache_role": normalized_cache_role,
        "compression_role": str(compression_role or "summarize"),
        "metadata": payload_metadata,
    }
    if prefix:
        payload["prefix"] = True
    return payload


def message_spec_content_source(*, kind: str, cache_role: str, source_ref: str) -> str:
    normalized_kind = str(kind or "").strip()
    if normalized_kind in {
        "global_static",
        "semantic_compaction_role",
    }:
        return "prompt_assembly.content"
    if normalized_kind == "personality_stable":
        return "prompt_composition.section_renderer.personality"
    if normalized_kind == "agent_stable":
        return "prompt_composition.section_renderer.agent"
    if normalized_kind in {"environment_stable"}:
        return "prompt_composition.section_renderer.environment"
    if normalized_kind == "lifecycle_stable":
        return "prompt_composition.section_renderer.lifecycle"
    if normalized_kind == "file_evidence_policy_stable":
        return "harness.runtime.file_evidence_policy"
    if normalized_kind == "project_instructions_stable":
        return "harness.runtime.project_instructions"
    if normalized_kind == "task_prompt_contract":
        return "prompt_composition.section_renderer.task_contract"
    if normalized_kind in {"active_skills", "skill_candidates"}:
        return "task_system.skill_renderer"
    if normalized_kind in {"action_schema_static"}:
        return "runtime.action_schema_manifest"
    if normalized_kind in {"artifact_scope_stable"}:
        return "runtime.artifact_scope_manifest"
    if normalized_kind in {"bound_task_context_stable"}:
        return "harness.runtime.bound_task_context"
    if normalized_kind in {"bound_task_runtime_context"}:
        return "runtime.dynamic_context_fragment"
    if normalized_kind in {"task_contract_stable"}:
        return "runtime.task_contract_manifest"
    if normalized_kind in {"tool_index_stable"}:
        return "runtime.tool_catalog_manifest"
    if normalized_kind in {
        "agent_function_shared_stable",
        "graph_task_shared_stable",
        "semantic_compaction_stable_boundary",
        "task_stable",
        "turn_stable",
    }:
        return "runtime.stable_boundary"
    if normalized_kind in {"provider_protocol_history"}:
        return "runtime.provider_protocol_replay"
    if normalized_kind in {
        "dynamic_projection",
        "graph_node_completion_prefix",
        "graph_node_runtime_context",
        "semantic_compaction_request",
        "session_history",
        "tool_observations",
        "user_steering_updates",
        "volatile_task_state",
        "volatile_user",
    }:
        return "runtime.dynamic_context_fragment"
    if str(cache_role or "") in {"volatile", "never_cache"}:
        return "runtime.dynamic_context_fragment"
    if str(source_ref or "").strip():
        return "runtime.stable_boundary"
    return "runtime_sanitized_model_message"
