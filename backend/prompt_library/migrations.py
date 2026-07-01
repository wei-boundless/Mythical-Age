from __future__ import annotations

from typing import Any


_DIRECT_PROMPT_REFS = (
    "system.foundation.local_collaboration",
    "system.foundation.current_request_authority",
    "system.foundation.truth_and_verification",
    "system.foundation.response_and_reporting",
    "system.foundation.security_and_injection",
    "system.foundation.context_memory_cache",
    "system.foundation.user_change_protection",
    "runtime.single_agent_turn",
    "runtime.task_execution",
    "runtime.graph_node_execution",
    "runtime.observation_followup",
    "runtime.semantic_compaction",
    "runtime.rule.system_call_protocol",
    "runtime.rule.turn_decision_alignment",
    "runtime.rule.turn_state_orientation",
    "runtime.rule.tool_use",
    "runtime.rule.output_boundary",
    "runtime.rule.error_recovery",
    "runtime.rule.context_memory",
    "runtime.rule.permission_denial",
    "runtime.rule.subagent_delegation",
    "runtime.rule.subagent_invocation_protocol",
    "runtime.rule.multi_tool_scheduling",
    "runtime.rule.plan_mode_boundary",
    "runtime.rule.file_management.generic",
    "graph.rule.node_boundary",
    "graph.rule.node_output_contract",
    "coding.rule.codebase_inspection",
    "coding.rule.large_scope_exploration",
    "coding.rule.editing",
    "coding.rule.verification",
    "coding.rule.debug_discipline",
    "coding.rule.git_safety",
    "coding.rule.windows_shell",
    "coding.rule.task_progress",
    "environment.rule.coding_workspace",
    "environment.rule.office_file_search",
    "environment.rule.general_workspace",
    "environment.resource.base_workspace.orientation",
    "environment.resource.managed_project_workspace.orientation",
    "environment.resource.sandbox_overlay.orientation",
    "environment.resource.general_workspace.orientation",
    "environment.coding.vibe_workspace.orientation",
    "environment.office.file_search.orientation",
    "environment.general.workspace.orientation",
    "environment.general.guidance.context_intake",
    "environment.general.guidance.request_judgment",
    "environment.general.guidance.work_relation",
    "environment.general.guidance.environment_capability_alignment",
    "environment.general.guidance.plan_gate",
    "environment.general.guidance.action_boundary",
    "environment.general.guidance.active_work_control",
    "environment.general.guidance.task_run_handoff",
    "environment.general.guidance.user_steer_contract_revision",
    "environment.general.guidance.tool_dispatch",
    "environment.general.guidance.tool_observation_recovery",
    "environment.general.guidance.subagent_delegation",
    "environment.general.guidance.subagent_result_integration",
    "environment.general.guidance.verification_gate",
    "environment.general.guidance.memory_read_context",
    "environment.general.guidance.memory_write_handoff",
    "environment.general.guidance.compaction_handoff",
    "environment.general.guidance.finalization",
    "agent.main_interactive_agent.single_agent_turn.work_role",
    "agent.main_interactive_agent.task_execution.work_role",
    "agent.main_interactive_agent.tool_observation_followup.work_role",
    "agent.main_coding_agent.single_agent_turn.work_role",
    "agent.main_coding_agent.task_execution.work_role",
    "agent.main_coding_agent.tool_observation_followup.work_role",
    "agent.main_office_agent.single_agent_turn.work_role",
    "agent.main_office_agent.task_execution.work_role",
    "agent.main_office_agent.tool_observation_followup.work_role",
    "agent.context_compactor_agent.semantic_compaction.work_role",
    "agent.memory_system_agent.memory_maintenance.work_role",
    "personality.default.mythical_age",
    "worker.prompt.dev_prototype",
    "worker.prompt.explorer",
    "worker.prompt.web_research",
    "worker.prompt.knowledge_search",
    "worker.prompt.memory_search",
    "worker.prompt.pdf_analysis",
    "worker.prompt.structured_data_analysis",
    "worker.prompt.codebase_search",
    "worker.prompt.planner",
    "worker.prompt.verification",
    "worker.prompt.execution",
    "worker.prompt.code_executor",
    "worker.prompt.review",
    "tool.guidance.read_file",
    "tool.guidance.edit_file",
    "tool.guidance.batch_edit_file",
    "tool.guidance.write_file",
    "tool.guidance.terminal_powershell",
    "tool.guidance.git_read",
    "tool.guidance.git_write",
    "tool.guidance.todo",
    "tool.guidance.subagent",
    "tool.guidance.browser",
    "tool.guidance.web_fetch",
    "tool.guidance.read_persisted_tool_result",
    "project.instructions.scoped",
    "runtime.pack.single_agent_turn",
    "runtime.pack.task_execution",
    "runtime.pack.graph_node_execution",
    "runtime.pack.observation_followup",
    "runtime.pack.semantic_compaction",
)


PROMPT_REF_MIGRATIONS: dict[str, tuple[str, ...]] = {
    f"{prompt_ref}.v1": (prompt_ref,) for prompt_ref in _DIRECT_PROMPT_REFS
}
PROMPT_REF_MIGRATIONS.update(
    {
        "system.foundation.vibe_coding_agent.v1": ("system.foundation.local_collaboration",),
        "system.foundation.context_and_cache.v1": ("system.foundation.context_memory_cache",),
        "runtime.rule.intent_feedback": ("runtime.rule.turn_decision_alignment",),
        "runtime.rule.intent_feedback.v1": ("runtime.rule.turn_decision_alignment",),
        "runtime.rule.lifecycle_control": ("runtime.rule.turn_state_orientation",),
        "runtime.rule.lifecycle_control.v1": ("runtime.rule.turn_state_orientation",),
        "tool.guidance.git.v1": ("tool.guidance.git_read", "tool.guidance.git_write"),
    }
)
_ENVIRONMENT_GUIDANCE_PROMPT_SLOTS = (
    "context_intake",
    "request_judgment",
    "work_relation",
    "environment_capability_alignment",
    "plan_gate",
    "action_boundary",
    "active_work_control",
    "task_run_handoff",
    "user_steer_contract_revision",
    "tool_dispatch",
    "tool_observation_recovery",
    "subagent_delegation",
    "subagent_result_integration",
    "verification_gate",
    "memory_read_context",
    "memory_write_handoff",
    "compaction_handoff",
    "finalization",
)
for _environment_prefix in ("general", "coding", "office"):
    for _slot in _ENVIRONMENT_GUIDANCE_PROMPT_SLOTS:
        _old_slot = "action_selection" if _slot == "action_boundary" else _slot
        _old_ref = f"environment.{_environment_prefix}.lifecycle.{_old_slot}"
        _new_ref = f"environment.{_environment_prefix}.guidance.{_slot}"
        PROMPT_REF_MIGRATIONS[_old_ref] = (_new_ref,)
        PROMPT_REF_MIGRATIONS[f"{_old_ref}.v1"] = (_new_ref,)
        if _slot == "action_boundary":
            _old_guidance_ref = f"environment.{_environment_prefix}.guidance.action_selection"
            PROMPT_REF_MIGRATIONS[_old_guidance_ref] = (_new_ref,)
            PROMPT_REF_MIGRATIONS[f"{_old_guidance_ref}.v1"] = (_new_ref,)


def migrate_prompt_ref(value: Any) -> str:
    prompt_ref = str(value or "").strip()
    if not prompt_ref:
        return ""
    migrated = PROMPT_REF_MIGRATIONS.get(prompt_ref)
    if not migrated:
        return prompt_ref
    return migrated[0] if migrated else ""


def migrate_prompt_ref_sequence(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values: list[Any] = [value]
    else:
        raw_values = list(value or [])
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        prompt_ref = str(raw or "").strip()
        if not prompt_ref:
            continue
        replacements = PROMPT_REF_MIGRATIONS.get(prompt_ref, (prompt_ref,))
        for replacement in replacements:
            normalized = str(replacement or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)


def migrate_prompt_refs_by_invocation(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, raw_refs in value.items():
        invocation_kind = str(key or "").strip()
        refs = list(migrate_prompt_ref_sequence(raw_refs))
        if invocation_kind and refs:
            result[invocation_kind] = refs
    return result


def migrate_prompt_resource_payload(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    prompt_id = migrate_prompt_ref(next_payload.get("prompt_id") or next_payload.get("resource_id"))
    resource_id = migrate_prompt_ref(next_payload.get("resource_id") or next_payload.get("prompt_id"))
    if prompt_id:
        next_payload["prompt_id"] = prompt_id
    if resource_id:
        next_payload["resource_id"] = resource_id
    metadata = _migrate_prompt_metadata(next_payload.get("metadata"))
    if metadata:
        next_payload["metadata"] = metadata
    return next_payload


def migrate_prompt_pack_payload(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    pack_id = migrate_prompt_ref(next_payload.get("pack_id"))
    if pack_id:
        next_payload["pack_id"] = pack_id
    next_payload["ordered_prompt_refs"] = list(
        migrate_prompt_ref_sequence(next_payload.get("ordered_prompt_refs"))
    )
    metadata = _migrate_prompt_metadata(next_payload.get("metadata"))
    if metadata:
        next_payload["metadata"] = metadata
    return next_payload


def migrate_runtime_profile_prompt_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    next_metadata = dict(metadata or {})
    if "worker_prompt_ref" in next_metadata:
        next_metadata["worker_prompt_ref"] = migrate_prompt_ref(next_metadata.get("worker_prompt_ref"))
    for key in ("agent_prompt_refs", "prompt_pack_refs", "personality_prompt_refs"):
        if key in next_metadata:
            next_metadata[key] = list(migrate_prompt_ref_sequence(next_metadata.get(key)))
    for key in ("agent_prompt_refs_by_invocation", "prompt_pack_refs_by_invocation"):
        if key in next_metadata:
            next_metadata[key] = migrate_prompt_refs_by_invocation(next_metadata.get(key))
    for policy_key in ("runtime_policy", "execution_policy"):
        policy = next_metadata.get(policy_key)
        if isinstance(policy, dict):
            next_metadata[policy_key] = _migrate_runtime_policy_prompt_refs(policy)
    return next_metadata


def _migrate_runtime_policy_prompt_refs(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    if "prompt_pack_refs" in next_payload:
        next_payload["prompt_pack_refs"] = list(migrate_prompt_ref_sequence(next_payload.get("prompt_pack_refs")))
    if "prompt_pack_refs_by_invocation" in next_payload:
        next_payload["prompt_pack_refs_by_invocation"] = migrate_prompt_refs_by_invocation(
            next_payload.get("prompt_pack_refs_by_invocation")
        )
    return next_payload


def _migrate_prompt_metadata(value: Any) -> dict[str, Any]:
    metadata = dict(value or {}) if isinstance(value, dict) else {}
    if not metadata:
        return metadata
    prompt_rule = metadata.get("prompt_rule")
    if isinstance(prompt_rule, dict):
        metadata["prompt_rule"] = _migrate_prompt_rule_payload(prompt_rule)
    return migrate_runtime_profile_prompt_metadata(metadata)


def _migrate_prompt_rule_payload(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    for key in ("rule_id", "prompt_ref"):
        if key in next_payload:
            next_payload[key] = migrate_prompt_ref(next_payload.get(key))
    for key in ("requires", "conflicts_with", "supersedes"):
        if key in next_payload:
            next_payload[key] = list(migrate_prompt_ref_sequence(next_payload.get(key)))
    return next_payload
