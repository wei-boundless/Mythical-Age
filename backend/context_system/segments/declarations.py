from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STATIC_PREFIX = "static_prefix"
CONTEXT_MEMORY_PREFIX = "context_memory_prefix"
CONTEXT_APPEND = "context_append"
DYNAMIC_TAIL = "dynamic_tail"

STATIC_IDENTITY = "static_identity"
RUNTIME_CONTRACTS = "runtime_contracts"
ACTION_CONTRACTS = "action_contracts"
TASK_RUN_CONTRACTS = "task_run_contracts"
TOOL_CONTEXT = "tool_context"
CONTEXT_MEMORY = "context_memory"
TASK_STATE_CONTEXT = "task_state_context"
EVIDENCE_CONTEXT = "evidence_context"
EVIDENCE_ALIGNMENT = "evidence_alignment"
CURRENT_DYNAMIC_CONTROL = "current_dynamic_control"
TURN_STATE_CONTROL = "turn_state_control"
REPAIR_FEEDBACK = "repair_feedback"
ACTIVE_SKILL = "active_skill"
REASONING_PROJECTION = "reasoning_projection"


@dataclass(frozen=True, slots=True)
class ContextSegmentKindDeclaration:
    kind: str
    section: str = ""
    semantic_slot: str = ""
    source_kind: str = ""
    content_source: str = ""
    capability_group: str = ""
    capability_slot: str = ""
    capability_member: str = ""
    layer: str = ""
    dynamic_tier: str = ""
    append_only: bool = False
    contract_slot: str = ""
    repair_feedback_slot: str = ""

    def policy_defaults(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "semantic_slot": self.semantic_slot,
            "contract_slot": self.contract_slot,
            "repair_feedback_slot": self.repair_feedback_slot,
        }


def _decl(
    kind: str,
    *,
    section: str = "",
    semantic_slot: str = "",
    source_kind: str = "",
    content_source: str = "",
    capability: tuple[str, str, str] | None = None,
    layer: str = "",
    dynamic_tier: str = "",
    append_only: bool = False,
    contract_slot: str = "",
    repair_feedback_slot: str = "",
) -> ContextSegmentKindDeclaration:
    group, slot, member = capability or ("", "", "")
    return ContextSegmentKindDeclaration(
        kind=str(kind or "").strip(),
        section=str(section or "").strip(),
        semantic_slot=str(semantic_slot or "").strip(),
        source_kind=str(source_kind or "").strip(),
        content_source=str(content_source or "").strip(),
        capability_group=str(group or "").strip(),
        capability_slot=str(slot or "").strip(),
        capability_member=str(member or "").strip(),
        layer=str(layer or "").strip(),
        dynamic_tier=str(dynamic_tier or "").strip(),
        append_only=bool(append_only),
        contract_slot=str(contract_slot or "").strip(),
        repair_feedback_slot=str(repair_feedback_slot or "").strip(),
    )


_DECLARATIONS: tuple[ContextSegmentKindDeclaration, ...] = (
    _decl("global_static", section=STATIC_PREFIX, content_source="prompt_assembly.content"),
    _decl("semantic_compaction_role", section=STATIC_PREFIX, content_source="prompt_assembly.content"),
    _decl("agent_stable", section=STATIC_PREFIX, content_source="prompt_composition.section_renderer.agent", layer="session_stable_agent"),
    _decl("personality_stable", section=STATIC_PREFIX, content_source="prompt_composition.section_renderer.personality", layer="session_stable_personality"),
    _decl("environment_stable", section=STATIC_PREFIX, source_kind="runtime_environment_boundary", content_source="prompt_composition.section_renderer.environment", layer="session_stable_environment"),
    _decl("turn_state_stable", section=STATIC_PREFIX, source_kind="runtime_turn_state", content_source="prompt_composition.section_renderer.turn_state", layer="session_stable_turn_state"),
    _decl("file_evidence_policy_stable", section=STATIC_PREFIX, source_kind="runtime_file_evidence_policy", content_source="harness.runtime.file_evidence_policy", layer="session_stable_file_evidence"),
    _decl("project_instructions_stable", section=STATIC_PREFIX, source_kind="runtime_project_instructions", content_source="harness.runtime.project_instructions", layer="session_stable_project"),
    _decl("action_schema_static", section=STATIC_PREFIX, semantic_slot="action_schema", source_kind="runtime_action_schema", content_source="runtime.action_schema_manifest", capability=(ACTION_CONTRACTS, "action_schema", "contract"), layer="session_stable_capability"),
    _decl("artifact_scope_stable", section=STATIC_PREFIX, source_kind="runtime_artifact_scope", content_source="runtime.artifact_scope_manifest", layer="task_scope_context"),
    _decl("bound_task_context_stable", section=STATIC_PREFIX, source_kind="runtime_bound_task_context", content_source="harness.runtime.bound_task_context", layer="task_scope_context"),
    _decl("capability_catalog", section=STATIC_PREFIX, semantic_slot="capability_catalog", source_kind="runtime_capability_catalog", content_source="harness.runtime.capability_directory_catalog", capability=(TOOL_CONTEXT, "capability_catalog", "contract"), layer="session_stable_capability"),
    _decl("tool_index_stable", section=STATIC_PREFIX, semantic_slot="tool_index", source_kind="tool_catalog", content_source="runtime.tool_catalog_manifest", capability=(TOOL_CONTEXT, "tool_index", "contract"), layer="session_stable_capability"),
    _decl("task_prompt_contract", section=STATIC_PREFIX, semantic_slot="task_prompt_contract", source_kind="runtime_contract", content_source="prompt_composition.section_renderer.task_run_contract", capability=(TASK_RUN_CONTRACTS, "task_prompt_contract", "contract"), layer="task_run_contract_context"),
    _decl("task_environment_context", section=STATIC_PREFIX, semantic_slot="task_environment_context", source_kind="runtime_environment_boundary", content_source="harness.runtime.environment_model_visible_payload", capability=(STATIC_IDENTITY, "task_environment_context", "prefix"), layer="session_stable_environment"),
    _decl("runtime_stable_contract", section=STATIC_PREFIX, source_kind="runtime_contract", content_source="runtime.stable_boundary", capability=(RUNTIME_CONTRACTS, "runtime_stable_contract", "contract"), layer="task_run_contract_context"),
    _decl("task_runtime_boundary_stable", section=STATIC_PREFIX, source_kind="runtime_task_boundary", layer="task_scope_context"),
    _decl("graph_task_shared_stable", section=STATIC_PREFIX, content_source="runtime.stable_boundary", layer="task_run_contract_context"),
    _decl("agent_function_shared_stable", section=STATIC_PREFIX, content_source="runtime.stable_boundary", layer="task_scope_context"),
    _decl("semantic_compaction_stable_boundary", section=STATIC_PREFIX, source_kind="semantic_compaction_boundary", content_source="runtime.stable_boundary", layer="session_stable_turn_state"),
    _decl("environment_guidance_stable", section=STATIC_PREFIX, source_kind="runtime_environment_boundary", layer="session_stable_environment"),
    _decl("runtime_baseline_refs", section=STATIC_PREFIX, source_kind="runtime_baseline_refs", content_source="runtime.stable_boundary", layer="session_stable_protocol"),
    _decl("provider_protocol_history", section=CONTEXT_APPEND, semantic_slot="provider_protocol_history", source_kind="runtime_append_only_context", content_source="runtime.provider_protocol_append_candidate", capability=(CONTEXT_MEMORY, "provider_protocol_history", "content"), layer="append_only_runtime_evidence", dynamic_tier="append_only_runtime_evidence", append_only=True),
    _decl("current_turn_user_context", section=CONTEXT_APPEND, semantic_slot="current_user_intent", source_kind="runtime_append_only_context", content_source="runtime.dynamic_context_fragment", capability=(CONTEXT_MEMORY, "current_user_intent", "content"), layer="current_turn_user_context", dynamic_tier="user_context_append", append_only=True),
    _decl("single_agent_turn_user_steer_context", section=CONTEXT_APPEND, semantic_slot="active_user_steer_content", source_kind="runtime_append_only_context", content_source="harness.runtime.user_steering_context", capability=(CONTEXT_MEMORY, "active_user_steer_content", "content"), dynamic_tier="user_context_append", append_only=True),
    _decl("user_steering_context_append", section=CONTEXT_APPEND, semantic_slot="active_user_steer_content", source_kind="runtime_append_only_context", content_source="harness.runtime.user_steering_context", capability=(CONTEXT_MEMORY, "active_user_steer_content", "content"), dynamic_tier="user_context_append", append_only=True),
    _decl("runtime_memory_context", section=CONTEXT_APPEND, semantic_slot="selected_memory_and_task_state_facts", source_kind="runtime_memory_context", content_source="memory_system.runtime_memory_context", capability=(CONTEXT_MEMORY, "runtime_memory_context", "content"), layer="runtime_memory_context", dynamic_tier="runtime_memory_context", append_only=True),
    _decl("previous_incomplete_output_memory", section=CONTEXT_APPEND, semantic_slot="previous_incomplete_output_memory", source_kind="runtime_turn_memory_output_hot_cache", content_source="runtime.turn_memory.output_hot_cache", capability=(CONTEXT_MEMORY, "previous_incomplete_output_memory", "content"), layer="previous_incomplete_output_memory", dynamic_tier="previous_incomplete_output_memory", append_only=True),
    _decl("session_history", section=CONTEXT_APPEND, semantic_slot="semantic_history_tail", source_kind="runtime_append_only_context", content_source="runtime.dynamic_context_fragment", capability=(CONTEXT_MEMORY, "history_replay", "content"), dynamic_tier="history_replay"),
    _decl("session_emphasis", section=CONTEXT_APPEND, semantic_slot="context_memory_append", content_source="memory_system.session_emphasis", capability=(CONTEXT_MEMORY, "session_emphasis", "content"), append_only=True),
    _decl("session_pinned_facts_context", section=CONTEXT_APPEND, semantic_slot="context_memory_append", source_kind="runtime_append_only_context", content_source="harness.runtime.dynamic_context.history_projection", capability=(CONTEXT_MEMORY, "session_pinned_facts", "content"), append_only=True),
    _decl("incremental_context_frame", section=CONTEXT_APPEND, semantic_slot="context_memory_append", source_kind="runtime_incremental_context_frame", content_source="harness.runtime.incremental_context_frame", dynamic_tier="context_memory_append", append_only=True),
    _decl("task_state_replay_entry", section=CONTEXT_APPEND, semantic_slot="selected_memory_and_task_state_facts", source_kind="runtime_task_state_replay", capability=(TASK_STATE_CONTEXT, "task_state_replay", "content"), layer="append_only_runtime_evidence", dynamic_tier="append_only_runtime_evidence", append_only=True),
    _decl("task_start_inherited_context", section=CONTEXT_APPEND, semantic_slot="selected_memory_and_task_state_facts", source_kind="runtime_append_only_context", capability=(TASK_STATE_CONTEXT, "task_start_inherited_context", "content"), layer="runtime_cursor_prefix", dynamic_tier="runtime_cursor_prefix"),
    _decl("single_agent_turn_tool_call", section=CONTEXT_APPEND, semantic_slot="tool_transcript", source_kind="runtime_append_only_context", capability=(TOOL_CONTEXT, "tool_transcript", "content"), layer="append_only_runtime_evidence", dynamic_tier="append_only_runtime_evidence", append_only=True),
    _decl("tool_transcript_delta", section=CONTEXT_APPEND, semantic_slot="tool_transcript", source_kind="runtime_append_only_context", content_source="harness.runtime.tool_transcript_delta", capability=(TOOL_CONTEXT, "tool_transcript", "content"), layer="append_only_runtime_evidence", dynamic_tier="append_only_runtime_evidence", append_only=True),
    _decl("read_evidence_context", section=CONTEXT_APPEND, semantic_slot="evidence_refs_and_file_state_facts", source_kind="runtime_read_evidence_context", content_source="harness.runtime.dynamic_context.read_evidence_projector", capability=(EVIDENCE_CONTEXT, "read_evidence_context", "content"), layer="append_only_runtime_evidence", dynamic_tier="append_only_runtime_evidence", append_only=True),
    _decl("evidence_index_cursor", section=CONTEXT_APPEND, semantic_slot="evidence_refs_and_file_state_facts", source_kind="runtime_evidence_index_cursor", content_source="harness.runtime.dynamic_context.evidence_index_cursor", capability=(EVIDENCE_CONTEXT, "evidence_index_cursor", "content"), layer="evidence_index_cursor", dynamic_tier="evidence_index_cursor"),
    _decl("attachment_context_index", section=CONTEXT_APPEND, semantic_slot="evidence_refs_and_file_state_facts", source_kind="runtime_attachment_context_index", content_source="harness.runtime.dynamic_context.attachment_context_index", capability=(EVIDENCE_CONTEXT, "attachment_context_index", "content"), layer="attachment_context_index", dynamic_tier="attachment_context_index"),
    _decl("editor_context_index", section=CONTEXT_APPEND, semantic_slot="evidence_refs_and_file_state_facts", source_kind="runtime_editor_context_index", content_source="harness.runtime.dynamic_context.editor_context_index", capability=(EVIDENCE_CONTEXT, "editor_context_index", "content"), layer="editor_context_index", dynamic_tier="editor_context_index"),
    _decl("physical_prefix_frame_tool_transcript_replay", section=CONTEXT_MEMORY_PREFIX, semantic_slot="tool_transcript", source_kind="runtime_physical_prefix_frame", content_source="runtime.context_management.physical_prefix_frame.replay", capability=(TOOL_CONTEXT, "tool_transcript", "content"), dynamic_tier="history_replay"),
    _decl("physical_prefix_frame_user_context_replay", section=CONTEXT_MEMORY_PREFIX, semantic_slot="provider_protocol_history", source_kind="runtime_physical_prefix_frame", content_source="runtime.context_management.physical_prefix_frame.replay", capability=(CONTEXT_MEMORY, "provider_protocol_history", "content"), dynamic_tier="history_replay"),
    _decl("physical_prefix_frame_user_message_replay", section=CONTEXT_MEMORY_PREFIX, semantic_slot="provider_protocol_history", source_kind="runtime_physical_prefix_frame", content_source="runtime.context_management.physical_prefix_frame.replay", capability=(CONTEXT_MEMORY, "provider_protocol_history", "content"), dynamic_tier="history_replay"),
    _decl("physical_prefix_frame_assistant_message_replay", section=CONTEXT_MEMORY_PREFIX, semantic_slot="provider_protocol_history", source_kind="runtime_physical_prefix_frame", content_source="runtime.context_management.physical_prefix_frame.replay", capability=(CONTEXT_MEMORY, "provider_protocol_history", "content"), dynamic_tier="history_replay"),
    _decl("physical_prefix_frame_context_replay", section=CONTEXT_MEMORY_PREFIX, semantic_slot="provider_protocol_history", source_kind="runtime_physical_prefix_frame", content_source="runtime.context_management.physical_prefix_frame.replay", capability=(CONTEXT_MEMORY, "provider_protocol_history", "content"), dynamic_tier="history_replay"),
    _decl("bound_task_runtime_context", section=CONTEXT_APPEND, semantic_slot="bound_task_runtime_context", source_kind="runtime_bound_task_context", content_source="runtime.dynamic_context_fragment", capability=(TASK_STATE_CONTEXT, "bound_task_runtime_context", "content"), layer="current_task_state_fact", dynamic_tier="file_evidence_cursor", append_only=True),
    _decl("task_goal_context", section=CONTEXT_APPEND, semantic_slot="task_goal_context", source_kind="runtime_task_goal_context", content_source="harness.runtime.dynamic_context.task_goal_context", capability=(TASK_STATE_CONTEXT, "task_goal_context", "content"), layer="current_task_state_fact", dynamic_tier="current_task_state_fact", append_only=True),
    _decl("task_plan_context", section=CONTEXT_APPEND, semantic_slot="task_plan_context", source_kind="runtime_task_plan_context", content_source="harness.runtime.dynamic_context.task_plan_context", capability=(TASK_STATE_CONTEXT, "task_plan_context", "content"), layer="current_task_state_fact", dynamic_tier="current_task_state_fact", append_only=True),
    _decl("task_todo_context", section=CONTEXT_APPEND, semantic_slot="task_todo_context", source_kind="runtime_task_todo_context", content_source="harness.runtime.dynamic_context.task_todo_context", capability=(TASK_STATE_CONTEXT, "task_todo_context", "content"), layer="current_task_state_fact", dynamic_tier="current_task_state_fact", append_only=True),
    _decl("active_execution_lease", section=DYNAMIC_TAIL, semantic_slot="active_execution_lease", source_kind="runtime_active_execution_lease", content_source="harness.runtime.dynamic_context.active_execution_lease", capability=(TURN_STATE_CONTROL, "active_execution_lease", "control"), layer="dynamic_context_tail", dynamic_tier="active_execution_lease", contract_slot="active_execution_lease"),
    _decl("task_runtime_boundary_dynamic", section=DYNAMIC_TAIL, semantic_slot="task_runtime_boundary_dynamic", source_kind="runtime_dynamic_boundary", content_source="runtime.dynamic_context_fragment", capability=(TURN_STATE_CONTROL, "task_runtime_boundary_dynamic", "contract"), layer="runtime_cursor_prefix", dynamic_tier="runtime_cursor_prefix", contract_slot="task_runtime_boundary_dynamic"),
    _decl("graph_node_runtime_context", section=CONTEXT_APPEND, semantic_slot="graph_node_runtime_context", source_kind="dynamic_context_fragment", content_source="runtime.dynamic_context_fragment", capability=(TASK_STATE_CONTEXT, "graph_node_runtime_context", "content"), layer="current_task_state_fact", dynamic_tier="graph_node_runtime_context", append_only=True),
    _decl("graph_node_completion_prefix", section=DYNAMIC_TAIL, semantic_slot="graph_node_completion_prefix", source_kind="dynamic_context_fragment", content_source="runtime.dynamic_context_fragment", capability=(TURN_STATE_CONTROL, "graph_node_completion_prefix", "control"), layer="assistant_completion_prefix", dynamic_tier="assistant_completion_prefix"),
    _decl("evidence_acquisition_horizon", section=DYNAMIC_TAIL, semantic_slot="evidence_acquisition_horizon", source_kind="runtime_evidence_acquisition_horizon", content_source="harness.runtime.dynamic_context.evidence_acquisition_horizon", capability=(EVIDENCE_CONTEXT, "evidence_acquisition_horizon", "contract"), layer="dynamic_context_tail", dynamic_tier="evidence_acquisition_horizon"),
    _decl("current_editor_evidence_delta", section=CONTEXT_APPEND, semantic_slot="current_editor_evidence_delta", source_kind="runtime_editor_evidence_delta", content_source="harness.runtime.dynamic_context.current_editor_evidence_delta", capability=(EVIDENCE_CONTEXT, "current_editor_evidence_delta", "content"), layer="current_exact_evidence_fact", dynamic_tier="current_exact_evidence_fact", append_only=True),
    _decl("read_evidence_injection", section=CONTEXT_APPEND, semantic_slot="current_exact_evidence", source_kind="runtime_read_evidence", content_source="runtime.dynamic_context_fragment", capability=(EVIDENCE_CONTEXT, "current_exact_evidence", "content"), layer="current_exact_evidence_fact", dynamic_tier="current_exact_evidence_fact", append_only=True),
    _decl("incremental_context_cursor", section=DYNAMIC_TAIL, semantic_slot="incremental_context_cursor", source_kind="runtime_incremental_context_cursor", content_source="harness.runtime.incremental_context_cursor", capability=(TURN_STATE_CONTROL, "incremental_context_cursor", "control"), layer="dynamic_context_tail", dynamic_tier="dynamic_context_tail"),
    _decl("active_skills", section=DYNAMIC_TAIL, semantic_slot="active_skill_body", source_kind="runtime_active_skills", content_source="task_system.skill_renderer", capability=(ACTIVE_SKILL, "active_skill_body", "content"), layer="dynamic_context_tail", dynamic_tier="active_skills"),
    _decl("session_history_tail_context", section=CONTEXT_APPEND, semantic_slot="recovery_or_recent_work_facts", source_kind="runtime_session_history_tail_context", content_source="runtime.dynamic_context_fragment", capability=(CONTEXT_MEMORY, "recent_work_outcome", "content"), dynamic_tier="recent_work_fact", append_only=True),
    _decl("dynamic_projection", section=DYNAMIC_TAIL, semantic_slot="runtime_delta_tail", source_kind="dynamic_context_fragment", content_source="runtime.dynamic_context_fragment", capability=(CURRENT_DYNAMIC_CONTROL, "runtime_delta_tail", "control"), layer="runtime_delta_tail", dynamic_tier="runtime_delta_tail"),
    _decl("volatile_runtime_state", section=DYNAMIC_TAIL, semantic_slot="volatile_runtime_state", source_kind="dynamic_context_fragment", capability=(CURRENT_DYNAMIC_CONTROL, "volatile_runtime_state", "control")),
    _decl("volatile_task_state", section=CONTEXT_APPEND, semantic_slot="task_state_cursor", source_kind="dynamic_context_fragment", content_source="runtime.dynamic_context_fragment", capability=(TASK_STATE_CONTEXT, "task_state_cursor", "content"), layer="current_task_state_fact", dynamic_tier="task_state_cursor", append_only=True),
    _decl("semantic_compaction_request", section=DYNAMIC_TAIL, semantic_slot="semantic_compaction_request", source_kind="dynamic_context_fragment", content_source="runtime.dynamic_context_fragment", capability=(TURN_STATE_CONTROL, "semantic_compaction_request", "control"), dynamic_tier="user_editor_volatile"),
    _decl("accumulated_context_boundary", section=DYNAMIC_TAIL, semantic_slot="accumulated_context_boundary", source_kind="dynamic_context_fragment", capability=(TURN_STATE_CONTROL, "accumulated_context_boundary", "control")),
    _decl("turn_state_guidance", section=DYNAMIC_TAIL, semantic_slot="turn_state_guidance", source_kind="dynamic_context_fragment", capability=(TURN_STATE_CONTROL, "turn_state_guidance", "contract"), layer="dynamic_context_tail", dynamic_tier="dynamic_context_tail", contract_slot="turn_state_guidance"),
    _decl("previous_incomplete_output_guidance", section=DYNAMIC_TAIL, semantic_slot="turn_state_guidance", source_kind="runtime_previous_incomplete_output_guidance", content_source="harness.runtime.compiler.previous_incomplete_output_guidance", capability=(TURN_STATE_CONTROL, "turn_state_guidance", "contract"), layer="dynamic_context_tail", dynamic_tier="dynamic_context_tail", contract_slot="turn_state_guidance"),
    _decl("turn_attention_index", section=DYNAMIC_TAIL, semantic_slot="turn_attention_index", source_kind="dynamic_context_fragment", capability=(TURN_STATE_CONTROL, "turn_attention_index", "control"), dynamic_tier="dynamic_context_tail"),
    _decl("turn_operating_contract", section=DYNAMIC_TAIL, semantic_slot="turn_operating_contract", source_kind="dynamic_context_fragment", content_source="harness.runtime.turn_operating_contract", capability=(TURN_STATE_CONTROL, "turn_operating_contract", "contract"), layer="dynamic_context_tail", dynamic_tier="dynamic_context_tail", contract_slot="turn_operating_contract"),
    _decl("runtime_control_signal_tail", section=DYNAMIC_TAIL, semantic_slot="runtime_control_contract", source_kind="dynamic_context_fragment", content_source="harness.loop.single_agent_turn.runtime_control_boundary", capability=(TURN_STATE_CONTROL, "runtime_control_signal", "control"), dynamic_tier="dynamic_context_tail", contract_slot="runtime_control_contract", repair_feedback_slot="system_repair_feedback"),
    _decl("user_steering_consumption_tail", section=CONTEXT_APPEND, semantic_slot="active_user_steer_consumption_state", source_kind="dynamic_context_fragment", content_source="harness.runtime.user_steering_consumption_tail", capability=(CONTEXT_MEMORY, "active_user_steer_consumption_state", "content"), dynamic_tier="user_context_append", append_only=True),
    _decl("single_agent_turn_followup_action_contract", section=DYNAMIC_TAIL, semantic_slot="action_contract", source_kind="dynamic_context_fragment", dynamic_tier="dynamic_context_tail", contract_slot="action_contract"),
    _decl("single_agent_turn_followup_message", section=DYNAMIC_TAIL, semantic_slot="runtime_followup_contract", source_kind="dynamic_context_fragment", dynamic_tier="dynamic_context_tail", contract_slot="runtime_followup_contract"),
    _decl("partial_stream_recovery_instruction", section=DYNAMIC_TAIL, semantic_slot="visible_prefix_recovery_contract", source_kind="dynamic_context_fragment", capability=(REPAIR_FEEDBACK, "visible_prefix_recovery_contract", "feedback"), dynamic_tier="dynamic_context_tail", contract_slot="visible_prefix_recovery_contract", repair_feedback_slot="system_repair_feedback"),
    _decl("partial_stream_recovery_visible_prefix", section=DYNAMIC_TAIL, semantic_slot="visible_prefix_recovery_context", source_kind="dynamic_context_fragment", capability=(REPAIR_FEEDBACK, "visible_prefix_recovery_context", "feedback"), dynamic_tier="dynamic_context_tail", contract_slot="visible_prefix_recovery_context"),
    _decl("provider_visible_ledger_recovery_checkpoint", section=DYNAMIC_TAIL, semantic_slot="provider_visible_ledger_recovery", capability=(REPAIR_FEEDBACK, "provider_visible_ledger_recovery", "feedback"), repair_feedback_slot="system_repair_feedback"),
    _decl("recovery_context_package", section=CONTEXT_APPEND, semantic_slot="recovery_or_recent_work_facts", capability=(CONTEXT_MEMORY, "recovery_context_package", "content"), dynamic_tier="recent_work_fact", append_only=True),
    _decl("recent_work_outcome", section=CONTEXT_APPEND, semantic_slot="recovery_or_recent_work_facts", capability=(CONTEXT_MEMORY, "recent_work_outcome", "content"), dynamic_tier="recent_work_fact", append_only=True),
    _decl("evidence_delta_summary", section=CONTEXT_APPEND, semantic_slot="evidence_semantic_summary", capability=(EVIDENCE_ALIGNMENT, "evidence_semantic_summary", "content"), dynamic_tier="evidence_semantic_fact", append_only=True),
    _decl("evidence_semantic_summary", section=CONTEXT_APPEND, semantic_slot="evidence_semantic_summary", capability=(EVIDENCE_ALIGNMENT, "evidence_semantic_summary", "content"), dynamic_tier="evidence_semantic_fact", append_only=True),
    _decl("read_coverage_projection", section=CONTEXT_APPEND, semantic_slot="read_coverage_projection", capability=(EVIDENCE_ALIGNMENT, "read_coverage_projection", "content"), dynamic_tier="evidence_semantic_fact", append_only=True),
    _decl("execution_action_evidence", section=CONTEXT_APPEND, semantic_slot="execution_action_evidence", capability=(EVIDENCE_ALIGNMENT, "execution_action_evidence", "content"), dynamic_tier="evidence_semantic_fact", append_only=True),
    _decl("answer_evidence_alignment_contract", section=DYNAMIC_TAIL, semantic_slot="answer_evidence_alignment_contract", capability=(EVIDENCE_ALIGNMENT, "answer_evidence_alignment_contract", "contract")),
    _decl("answer_alignment_feedback", section=DYNAMIC_TAIL, semantic_slot="answer_alignment_feedback", capability=(EVIDENCE_ALIGNMENT, "answer_alignment_feedback", "feedback")),
    _decl("reasoning_trace_projection", section=DYNAMIC_TAIL, semantic_slot="reasoning_trace_projection", capability=(REASONING_PROJECTION, "reasoning_trace_projection", "content")),
    _decl("provider_reasoning_projection", section=DYNAMIC_TAIL, semantic_slot="provider_reasoning_projection", capability=(REASONING_PROJECTION, "provider_reasoning_projection", "content")),
)

_DECLARATIONS_BY_KIND: dict[str, ContextSegmentKindDeclaration] = {
    declaration.kind: declaration
    for declaration in _DECLARATIONS
    if declaration.kind
}


def context_segment_kind_declaration(kind: Any) -> ContextSegmentKindDeclaration | None:
    return _DECLARATIONS_BY_KIND.get(str(kind or "").strip())


def context_segment_kind_declarations() -> tuple[ContextSegmentKindDeclaration, ...]:
    return _DECLARATIONS


def context_segment_declared_kinds(
    *,
    section: str = "",
    append_only: bool | None = None,
) -> frozenset[str]:
    normalized_section = str(section or "").strip()
    return frozenset(
        declaration.kind
        for declaration in _DECLARATIONS
        if declaration.kind
        and (not normalized_section or declaration.section == normalized_section)
        and (append_only is None or declaration.append_only is bool(append_only))
    )


def context_segment_semantic_slot_defaults() -> dict[str, str]:
    return {
        declaration.kind: declaration.semantic_slot
        for declaration in _DECLARATIONS
        if declaration.kind and declaration.semantic_slot
    }


def context_segment_source_kind_defaults() -> dict[str, str]:
    return {
        declaration.kind: declaration.source_kind
        for declaration in _DECLARATIONS
        if declaration.kind and declaration.source_kind
    }


def context_segment_content_source_defaults() -> dict[str, str]:
    return {
        declaration.kind: declaration.content_source
        for declaration in _DECLARATIONS
        if declaration.kind and declaration.content_source
    }


def context_segment_capability_defaults() -> dict[str, tuple[str, str, str]]:
    return {
        declaration.kind: (
            declaration.capability_group,
            declaration.capability_slot,
            declaration.capability_member,
        )
        for declaration in _DECLARATIONS
        if declaration.kind and declaration.capability_group
    }


def context_segment_layer_defaults() -> dict[str, str]:
    return {
        declaration.kind: declaration.layer
        for declaration in _DECLARATIONS
        if declaration.kind and declaration.layer
    }


def context_segment_dynamic_tier_defaults() -> dict[str, str]:
    return {
        declaration.kind: declaration.dynamic_tier
        for declaration in _DECLARATIONS
        if declaration.kind and declaration.dynamic_tier
    }


def context_segment_kind_semantic_slot(kind: Any) -> str:
    declaration = context_segment_kind_declaration(kind)
    return str(declaration.semantic_slot if declaration else "")


def context_segment_kind_source_kind(kind: Any) -> str:
    declaration = context_segment_kind_declaration(kind)
    return str(declaration.source_kind if declaration else "")


def context_segment_kind_content_source(kind: Any) -> str:
    declaration = context_segment_kind_declaration(kind)
    return str(declaration.content_source if declaration else "")


def context_segment_kind_capability(kind: Any) -> tuple[str, str, str] | None:
    declaration = context_segment_kind_declaration(kind)
    if not declaration or not declaration.capability_group:
        return None
    return declaration.capability_group, declaration.capability_slot, declaration.capability_member


def context_segment_kind_layer(kind: Any) -> str:
    declaration = context_segment_kind_declaration(kind)
    return str(declaration.layer if declaration else "")


def context_segment_kind_dynamic_tier(kind: Any) -> str:
    declaration = context_segment_kind_declaration(kind)
    return str(declaration.dynamic_tier if declaration else "")
