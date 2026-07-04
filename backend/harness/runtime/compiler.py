from __future__ import annotations

import json
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prompt_library import (
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptAssemblyService,
    build_runtime_prompt_manifest,
    build_runtime_prompt_wiring_plan,
    default_pack_ref_for_invocation,
)
from prompt_library.assembly import (
    build_prompt_authority_manifest,
    build_prompt_precedence_report,
    enforce_prompt_authority_order,
)
from prompt_library.rules import build_rule_diagnostics
from prompt_composition import (
    PromptCompositionContentFragment,
    build_content_fragments_from_message_specs,
    build_model_message_spec as _message_spec,
    build_prompt_assembly_plan,
    build_prompt_source_bundle,
    build_runtime_context_load_plan,
    build_runtime_prompt_source_manifest,
    build_runtime_payload_message_spec as _runtime_payload_spec,
    build_runtime_prompt_slot_plan,
    materialize_prompt_packet,
    build_runtime_slot_prompt_composition_manifest,
    materialize_runtime_prompt_sources,
    parse_context_fragments,
    render_agent_prompt_instruction,
    render_environment_instruction,
    render_environment_guidance_instruction,
    render_model_messages_from_projection,
    render_personality_prompt_instruction,
    render_prompt_contract_instruction,
    render_text_context_fragment,
)
from artifact_system.artifact_authority import artifact_ref_value, dedupe_artifact_refs, model_visible_artifact_refs, normalize_artifact_ref
from harness.current_work_receipt import current_work_operation_availability_from_receipt
from core.project_layout import ProjectLayout
from runtime.model_gateway.lightweight_chat_model import provider_message_payloads
from runtime.model_gateway.protocol_sanitizer import ProtocolSanitizerResult, sanitize_messages_for_prompt
from context_system.segments.metadata import (
    PROVIDER_PROTOCOL_APPEND_AUTHORITY,
    PROVIDER_PROTOCOL_APPEND_POLICY,
    PROVIDER_PROTOCOL_APPEND_STATUS,
    physical_prefix_frame_replay_metadata,
    provider_message_byte_preservation_required,
    provider_message_replay_kind,
)
from context_system.segments.policy import (
    CONTEXT_APPEND,
    DYNAMIC_TAIL,
    context_segment_policy_for_spec,
)
from runtime.context_management.context_candidate_gateway import build_context_candidate_gateway
from runtime.context_management.context_pipeline import (
    build_context_pipeline,
    normalize_context_compaction_generation,
)
from runtime.prompt_accounting.provider_lane import (
    PROVIDER_LANE_AGENT_TOOL_LOOP,
    PROVIDER_LANE_COMPACTION,
)
from runtime.context_management.provider_tool_protocol import annotate_provider_tool_round_specs
from task_system.contracts.runtime_contracts import expand_selected_skill_bodies

from .artifact_scope import runtime_artifact_scope_from_environment
from .context_message_producers import build_context_message_projection
from .dynamic_context import DynamicContextInput, DynamicContextManager, DynamicContextProjection, dynamic_context_storage_root
from .envelope import RuntimeEnvelope
from .invocation_packet import RuntimeInvocationPacket
from .action_schema_manifest import ActionSchemaManifest, build_action_schema_manifest
from .agent_visible_projection.projector import build_agent_visible_runtime_projection
from .artifact_scope_manifest import ArtifactScopeManifest, build_artifact_scope_manifest
from .context_contract import build_context_contract_inspection_payload, build_context_contract_manifest
from .environment_storage import ensure_environment_storage_dirs
from .environment_prompt_controller import (
    GENERAL_ENVIRONMENT_ID,
    build_base_environment_prompt_inventory,
    environment_prompt_inventory_for_invocation,
    environment_prompt_inventory_from_payload,
)
from .packet_assembler import (
    build_dynamic_context_projection_policy as _dynamic_context_projection_policy,
    build_session_file_evidence_projection as _build_session_file_evidence_projection,
    build_single_agent_turn_packet_context,
)
from .prompt_segment_plan import build_prompt_segment_plan
from .project_instructions import ProjectInstructionBundle, collect_project_instruction_bundle
from .runtime_control_signal_projection import canonical_runtime_control_signal_projection
from .tool_catalog_manifest import ToolCatalogManifest, build_tool_catalog_manifest
from .tool_call_contract import build_tool_call_contract
from .turn_operating_contract import (
    build_turn_operating_contract,
    turn_action_request_contract_payload,
    turn_output_contract_payload,
)


_GRAPH_AUTHORIZED_INPUT_CONTENT_LIMIT = 16000
_GRAPH_AUTHORIZED_INPUT_PAYLOAD_LIMIT = 12000
_GRAPH_ARTIFACT_PAYLOAD_LIMIT = 2
_GRAPH_LOOP_ARTIFACT_PAYLOAD_LIMIT = 4
_GRAPH_MEMORY_SNAPSHOT_LIMIT = 6
_GRAPH_MEMORY_RECORD_LIMIT = 2
_GRAPH_MEMORY_RECORD_TEXT_LIMIT = 1200
_GRAPH_LOOP_FRAME_LIMIT = 2
_GRAPH_LOOP_ITERATION_LIMIT = 6
_GRAPH_LOOP_NODE_RESULT_LIMIT = 6

@dataclass(frozen=True, slots=True)
class RuntimeCompilationResult:
    envelope: RuntimeEnvelope
    packet: RuntimeInvocationPacket

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope": self.envelope.to_dict(),
            "packet": self.packet.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class _RuntimePromptProfileView:
    agent_profile_id: str
    prompt_set_refs: tuple[str, ...] = ()
    prompt_bindings: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class RuntimeCompiler:
    def __init__(self, *, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parents[2]
        self.dynamic_context_manager = DynamicContextManager(base_dir=self.base_dir)

    def compile_semantic_compaction_packet(
        self,
        *,
        semantic_request: Any,
        runtime_assembly: Any,
        agent_runtime_profile: Any | None = None,
        session_id: str = "",
        turn_id: str = "",
        task_run_id: str = "",
        model_selection: dict[str, Any] | None = None,
    ) -> RuntimeCompilationResult:
        invocation_kind = "semantic_compaction"
        request_payload = semantic_request.to_dict() if hasattr(semantic_request, "to_dict") else dict(semantic_request or {})
        request_diagnostics = dict(request_payload.get("diagnostics") or {})
        request_id = str(request_payload.get("request_id") or "context_compaction:semantic").strip()
        resolved_session_id = (
            str(session_id or "").strip()
            or str(request_diagnostics.get("session_id") or "").strip()
            or "semantic_compaction"
        )
        resolved_turn_id = str(turn_id or request_diagnostics.get("turn_id") or "").strip()
        resolved_task_run_id = str(task_run_id or request_diagnostics.get("task_run_id") or "").strip()
        assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
        self._bind_assembly_base_dir(assembly_payload)
        profile_payload = dict(assembly_payload.get("profile") or {})
        environment_payload = dict(assembly_payload.get("task_environment") or {})
        profile_metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {})
        agent_profile_ref = str(
            assembly_payload.get("agent_profile_ref")
            or profile_payload.get("profile_ref")
            or getattr(agent_runtime_profile, "agent_profile_id", "")
            or "context_compactor_agent"
        )
        task_environment_ref = str(
            environment_payload.get("environment_id")
            or request_diagnostics.get("task_environment_id")
            or "env.general.workspace"
        )
        prompt_assembly = PromptAssemblyResult(
            assembly_id="promptasm:empty:semantic_compaction_runtime_pack",
            invocation_kind=invocation_kind,
            sections=(),
            prompt_pack_refs=(),
        )
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind=invocation_kind,
            prompt_refs=_agent_work_role_refs_for_invocation(assembly_payload, invocation_kind=invocation_kind),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            assembly_payload=assembly_payload,
        )
        output_contract = {
            "required_json_object": True,
            "required_fields": ["context_recovery_package"],
            "optional_fields": ["summary_content", "diagnostics"],
            "context_recovery_package_schema": {
                "current_task": "string",
                "key_user_constraints": "string[]",
                "progress_so_far": "string[]",
                "important_findings": "string[]",
                "key_decisions": "string[]",
                "files_artifacts_refs": "string[] | object[]",
                "errors_and_corrections": "string[]",
                "environment_state": "string[]",
                "dirty_worktree": "string[]",
                "validation_state": "string[]",
                "open_questions": "string[]",
                "next_steps": "string[]",
                "do_not_touch": "string[]",
            },
            "forbidden_actions": ["tool_call", "file_write", "memory_write", "delegation"],
            **dict(profile_metadata.get("output_contract") or {}),
            "authority": "harness.runtime.semantic_compaction.output_contract",
        }
        stable_boundary = {
            "agent_id": str(getattr(agent_runtime_profile, "agent_id", "") or "agent:context_compactor"),
            "agent_profile_ref": agent_profile_ref,
            "runtime_template_id": str(profile_metadata.get("runtime_template_id") or ""),
            "runtime_config": dict(profile_metadata.get("runtime_config") or {}),
            "input_contract": dict(profile_metadata.get("input_contract") or {}),
            "output_contract": output_contract,
            "allowed_operations": list(profile_payload.get("allowed_operations") or []),
            "blocked_operations": list(getattr(agent_runtime_profile, "blocked_operations", ()) or ()),
            "subagent_policy": dict(profile_payload.get("subagent_policy") or {}),
            "task_environment_id": task_environment_ref,
            "authority": "harness.runtime.semantic_compaction.stable_boundary",
        }
        packet_id = f"rtpacket:{request_id}:semantic_compaction:1"
        model_messages, segment_plan, message_specs, source_manifest, slot_plan, context_load_plan = _model_messages_and_segment_plan(
            packet_id=packet_id,
            invocation_kind=invocation_kind,
            specs=[
                _message_spec(
                    role="system",
                    content=agent_prompt_assembly.content,
                    kind="semantic_compaction_role",
                    source_ref=",".join(_agent_work_role_refs_for_invocation(assembly_payload, invocation_kind=invocation_kind)),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Semantic compaction operating contract",
                    payload=stable_boundary,
                    kind="semantic_compaction_stable_boundary",
                    source_ref="semantic_compaction_stable_boundary",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _runtime_payload_spec(
                    role="user",
                    title="Semantic compaction request",
                    payload=request_payload,
                    kind="semantic_compaction_request",
                    source_ref=str(request_payload.get("request_id") or "semantic_compaction_request"),
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata={
                        "semantic_compaction_request_ref": str(request_payload.get("request_id") or ""),
                        "pressure_level": str(request_payload.get("pressure_level") or ""),
                        "summary_target_tokens": int(request_payload.get("summary_target_tokens") or 0),
                    },
                ),
            ],
            provider_visible_append_scope=resolved_session_id,
            storage_root=self.base_dir,
            model_selection=_model_selection_with_provider_lane(
                model_selection,
                provider_lane=PROVIDER_LANE_COMPACTION,
            ),
            context_capability_profile=_context_capability_profile_from_runtime_assembly(assembly_payload),
            system_wiring_manifest=_system_wiring_manifest_from_runtime_assembly(assembly_payload),
        )
        protocol_sanitizer = _sanitize_model_messages_for_prompt_packet(
            model_messages,
            message_specs=message_specs,
            turn_id=resolved_turn_id,
            source="harness.runtime.compiler.semantic_compaction",
        )
        model_messages = [dict(item) for item in protocol_sanitizer.messages]
        content_fragments = build_content_fragments_from_message_specs(
            segment_plan=segment_plan,
            message_specs=message_specs,
            fallback_model_messages=model_messages,
        )
        semantic_dynamic_refs = ("semantic_compaction_request",)
        semantic_volatile_refs = ("messages", "recent_messages")
        prompt_manifest = build_runtime_prompt_manifest(
            invocation_kind=invocation_kind,
            assembly=_merge_prompt_assemblies(
                prompt_assembly,
                agent_prompt_assembly,
                invocation_kind=invocation_kind,
            ),
            packet_id=packet_id,
            dynamic_projection_refs=semantic_dynamic_refs,
            volatile_state_refs=semantic_volatile_refs,
        ).to_dict()
        prompt_manifest["rendered_prompt_refs"] = [
            "general.runtime_protocol.system_call_protocol",
            "coding.cycles.session_compaction.way.route",
        ]
        prompt_manifest["prompt_text_authority"] = {
            "authority": "harness.runtime.semantic_compaction.prompt_frame",
            "runtime_text_authority": "semantic_compaction_model_only_frame",
            "replaced_prompt_pack_refs": [],
            "rendered_prompt_refs": list(prompt_manifest["rendered_prompt_refs"]),
        }
        prompt_manifest["segment_plan_ref"] = segment_plan.segment_plan_id
        prompt_manifest["prompt_assembly_plan_ref"] = segment_plan.provider_policy_ref
        prompt_manifest["runtime_prompt_source_manifest_ref"] = source_manifest.manifest_id
        prompt_manifest["runtime_prompt_sources"] = source_manifest.to_dict()
        prompt_manifest["context_physical_assembly"] = _context_physical_assembly_manifest_from_specs(message_specs)
        prompt_manifest["prompt_slot_plan_ref"] = slot_plan.plan_id
        prompt_manifest["prompt_slot_plan"] = slot_plan.to_dict()
        prompt_manifest["runtime_context_load_plan_ref"] = context_load_plan.plan_id
        prompt_manifest["runtime_context_load_plan"] = context_load_plan.to_dict()
        prompt_manifest["protocol_sanitizer"] = dict(protocol_sanitizer.diagnostics)
        context_contract_manifest_payload = _attach_context_contract_manifest(
            prompt_manifest,
            packet_id=packet_id,
            invocation_kind=invocation_kind,
            message_specs=message_specs,
            segment_plan=segment_plan.to_dict(),
        )
        prompt_composition_manifest = _attach_prompt_composition_manifest(
            prompt_manifest,
            invocation_kind=invocation_kind,
            packet_id=packet_id,
            segment_plan=segment_plan.to_dict(),
            runtime_slot_plan=slot_plan,
            dynamic_projection_refs=semantic_dynamic_refs,
            volatile_state_refs=semantic_volatile_refs,
            diagnostics={"compiler_entrypoint": "compile_semantic_compaction_packet"},
        )
        model_messages = _render_model_messages_from_prompt_composition(
            prompt_manifest=prompt_manifest,
            prompt_composition_manifest=prompt_composition_manifest,
            content_fragments=content_fragments,
            model_messages=model_messages,
        )
        _attach_model_message_metrics(prompt_manifest, model_messages=model_messages, segment_plan=segment_plan.to_dict())
        envelope = RuntimeEnvelope(
            envelope_id=f"rtenv:{request_id}:semantic_compaction",
            scope_kind="recovery",
            session_id=resolved_session_id,
            turn_id=resolved_turn_id,
            task_run_id=resolved_task_run_id,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            runtime_policy={
                "context_policy": dict(profile_payload.get("context_policy") or {}),
                "memory_policy": dict(profile_payload.get("memory_policy") or {}),
            },
            permission_policy=dict(profile_payload.get("permission_policy") or {}),
            prompt_policy={"invocation_kind": invocation_kind},
            output_policy=output_contract,
            diagnostics={
                "request_id": request_id,
                "model_selection": dict(model_selection or {}),
                "runtime_assembly_id": str(assembly_payload.get("assembly_id") or ""),
                "worker_kind": str(profile_metadata.get("worker_kind") or ""),
            },
        )
        packet = RuntimeInvocationPacket(
            packet_id=packet_id,
            envelope_ref=envelope.envelope_id,
            invocation_kind=invocation_kind,
            invocation_index=1,
            session_id=resolved_session_id,
            turn_id=resolved_turn_id,
            task_run_id=resolved_task_run_id,
            model_messages=model_messages,
            segment_plan=segment_plan.to_dict(),
            prompt_composition_manifest=prompt_composition_manifest,
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
            available_tools=(),
            allowed_action_types=("model_response",),
            output_contract=output_contract,
            hidden_control_refs={
                "request_id": request_id,
                "runtime_assembly_id": str(assembly_payload.get("assembly_id") or ""),
            },
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
                "context_contract_manifest": context_contract_manifest_payload,
                "model_input_authority": "prompt_composition.message_projection",
                "protocol_sanitizer": dict(protocol_sanitizer.diagnostics),
                "semantic_compaction_request_ref": str(request_payload.get("request_id") or ""),
            },
        )
        return RuntimeCompilationResult(envelope=envelope, packet=packet)

    def compile_single_agent_turn_packet(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent_invocation_id: str,
        user_message: str,
        history: list[dict[str, Any]],
        session_context: dict[str, Any] | None = None,
        active_work_context: dict[str, Any] | None = None,
        current_work_boundary_receipt: dict[str, Any] | None = None,
        memory_context: dict[str, Any] | None = None,
        agent_profile_ref: str = "main_interactive_agent",
        model_selection: dict[str, Any] | None = None,
        runtime_assembly: Any | None = None,
        tool_definitions_by_name: dict[str, Any] | None = None,
    ) -> RuntimeCompilationResult:
        initial_assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
        initial_profile_payload = dict(initial_assembly_payload.get("profile") or {})
        prompt_pack_refs = _prompt_pack_refs_for_invocation(
            initial_profile_payload,
            invocation_kind="single_agent_turn",
            assembly_payload=initial_assembly_payload,
        )
        packet_context = build_single_agent_turn_packet_context(
            session_id=session_id,
            turn_id=turn_id,
            agent_invocation_id=agent_invocation_id,
            user_message=user_message,
            history=history,
            session_context=session_context,
            active_work_context=active_work_context,
            current_work_boundary_receipt=current_work_boundary_receipt,
            memory_context=memory_context,
            agent_profile_ref=agent_profile_ref,
            model_selection=model_selection,
            runtime_assembly=initial_assembly_payload,
            tool_definitions_by_name=tool_definitions_by_name,
            prompt_pack_refs=prompt_pack_refs,
            base_dir=self.base_dir,
        )
        assembly_payload = packet_context.runtime_assembly
        self._bind_assembly_base_dir(assembly_payload)
        profile_payload = packet_context.profile_payload
        prompt_policy = dict(profile_payload.get("prompt_policy") or assembly_payload.get("prompt_policy") or {})
        environment_payload = packet_context.environment_payload
        _ensure_environment_storage_dirs_for_runtime(self.base_dir, environment_payload)
        control_capabilities = packet_context.control_capabilities
        effective_control_capabilities = packet_context.effective_control_capabilities
        agent_profile_ref = packet_context.agent_profile_ref
        task_environment_ref = packet_context.task_environment_ref
        permission_mode = packet_context.permission_mode
        allowed_actions = packet_context.allowed_action_types
        session_context_payload = packet_context.session_context
        active_work_context = packet_context.active_work_context
        current_work_boundary_receipt = packet_context.current_work_boundary_receipt
        operation_availability = packet_context.operation_availability
        active_work_controls_enabled = operation_availability.get("active_work_control") is True
        memory_context = packet_context.memory_context
        model_selection = packet_context.model_selection
        single_turn_tool_plan = packet_context.tool_plan
        single_turn_tools = packet_context.model_visible_tools
        planning_protocol = _planning_protocol_payload(
            invocation_kind="single_agent_turn",
            profile_payload=profile_payload,
            permission_mode=permission_mode,
        )
        tool_call_contract = build_tool_call_contract(
            invocation_kind="single_agent_turn",
            allowed_action_types=allowed_actions,
            available_tools=single_turn_tools,
            runtime_assembly=assembly_payload,
            tool_plan=single_turn_tool_plan,
        )
        output_contract = _single_agent_turn_output_contract(
            allowed_actions=allowed_actions,
            control_capabilities=effective_control_capabilities,
            planning_protocol=planning_protocol,
        )
        turn_operating_contract = build_turn_operating_contract(
            packet_context=packet_context,
            tool_call_contract=tool_call_contract,
            output_contract=output_contract,
        )
        agent_visible_runtime_projection = build_agent_visible_runtime_projection(
            invocation_kind="single_agent_turn",
            allowed_action_types=allowed_actions,
            profile_payload=profile_payload,
            environment_payload=environment_payload,
            operation_authorization=dict(assembly_payload.get("operation_authorization") or {}),
            available_tools=single_turn_tools,
            permission_mode=permission_mode,
            tool_plan=single_turn_tool_plan,
            tool_call_contract=tool_call_contract,
        )
        envelope = RuntimeEnvelope(
            envelope_id=f"rtenv:{turn_id}:single_agent_turn",
            scope_kind="turn",
            session_id=session_id,
            turn_id=turn_id,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            runtime_policy={
                "planning_policy": dict(profile_payload.get("planning_policy") or {}),
                "task_lifecycle_policy": dict(profile_payload.get("task_lifecycle_policy") or {}),
                "self_review_policy": dict(profile_payload.get("self_review_policy") or {}),
            },
            sandbox_policy=dict(environment_payload.get("sandbox_policy") or {}),
            file_policy={
                "file_management": dict(environment_payload.get("file_management") or {}),
                "file_access_tables": list(environment_payload.get("file_access_tables") or []),
            },
            artifact_policy=dict(environment_payload.get("artifact_policy") or {}),
            permission_policy=dict(profile_payload.get("permission_policy") or {}),
            prompt_policy={"invocation_kind": "single_agent_turn"},
            output_policy=output_contract,
            diagnostics={
                "agent_invocation_id": agent_invocation_id,
                "model_selection": dict(model_selection or {}),
                "runtime_assembly_id": str(assembly_payload.get("assembly_id") or ""),
                "control_capabilities": dict(effective_control_capabilities),
            },
        )
        prompt_assembly = self._assemble_prompt_pack(
            invocation_kind="single_agent_turn",
            prompt_pack_refs=prompt_pack_refs,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            assembly_payload=assembly_payload,
        )
        runtime_prompt_wiring_plan = _build_invocation_prompt_wiring_plan(
            base_dir=self.base_dir,
            assembly_payload=assembly_payload,
            invocation_kind="single_agent_turn",
            allowed_actions=allowed_actions,
            operation_availability=operation_availability,
            active_work_context=dict(active_work_context or {}),
            memory_context=memory_context or session_context_payload.get("memory_context"),
            visible_tools=single_turn_tools,
            session_context=session_context_payload,
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
        )
        prompt_mount_plan = environment_prompt_inventory_for_invocation(
            _prompt_mount_plan_payload_from_runtime_assembly(assembly_payload),
            invocation_kind="single_agent_turn",
            allowed_actions=allowed_actions,
            operation_availability=operation_availability,
            active_work_context=dict(active_work_context or {}),
            memory_context=memory_context or session_context_payload.get("memory_context"),
            visible_tools=single_turn_tools,
            session_context=session_context_payload,
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
        )
        prompt_mount_plan = _prompt_mount_plan_with_wiring_guidance(prompt_mount_plan, runtime_prompt_wiring_plan)
        tool_catalog_manifest = _build_tool_catalog_manifest_for_mount_plan(
            invocation_kind="single_agent_turn",
            tool_payloads=single_turn_tools,
            source_ref="runtime_assembly.available_tools",
            prompt_mount_plan=prompt_mount_plan,
        )
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="single_agent_turn",
            prompt_refs=_agent_work_role_refs_for_invocation(assembly_payload, invocation_kind="single_agent_turn"),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            assembly_payload=assembly_payload,
        )
        personality_prompt_assembly = self._assemble_personality_prompt_layer(
            prompt_mount_plan=prompt_mount_plan,
            invocation_kind="single_agent_turn",
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            assembly_payload=assembly_payload,
        )
        environment_prompt_assembly, environment_guidance_prompt_assembly = self._assemble_environment_prompt_layers(
            prompt_mount_plan=prompt_mount_plan,
            agent_profile_ref=agent_profile_ref,
            assembly_payload=assembly_payload,
        )
        turn_state_guidance_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=tuple(prompt_mount_plan.turn_state_guidance_prompt_refs or ()),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(prompt_mount_plan.selected_environment_id or ""),
            assembly_payload=assembly_payload,
        )
        project_instruction_bundle = collect_project_instruction_bundle(base_dir=self.base_dir)
        runtime_instruction = _runtime_projection_instruction(
            agent_visible_runtime_projection,
            validity_scope=turn_id,
        )
        environment_instruction = render_environment_instruction(
            environment_payload,
            environment_prompt_assembly=environment_prompt_assembly,
        )
        environment_guidance_instruction = render_environment_guidance_instruction(environment_guidance_prompt_assembly)
        turn_state_guidance_instruction = render_environment_guidance_instruction(turn_state_guidance_prompt_assembly)
        personality_instruction = render_personality_prompt_instruction(personality_prompt_assembly)
        agent_instruction = render_agent_prompt_instruction(agent_prompt_assembly, invocation_kind="single_agent_turn")
        task_environment_context_payload = _environment_model_visible_payload(
            environment_payload,
            prompt_mount_plan=prompt_mount_plan.to_dict(),
        )
        capability_directory_payload = _capability_directory_model_visible_payload(assembly_payload)
        capability_catalog_payload = _capability_catalog_payload(capability_directory_payload)
        current_operating_contract_payload = _single_agent_turn_current_operating_contract_payload(
            control_capabilities=effective_control_capabilities,
            turn_operating_contract=turn_operating_contract.to_agent_visible_payload(),
            output_contract=_prompt_output_contract_payload(output_contract),
            capability_directory=capability_directory_payload,
        )
        project_instruction_payload = _project_instruction_model_payload(project_instruction_bundle)
        tool_index_payload = (
            tool_catalog_manifest.to_model_visible_payload(include_catalog_hash=True)
            if single_turn_tools
            else {}
        )
        packet_id = packet_context.packet_id
        turn_input_facts = dict(session_context_payload.get("turn_input_facts") or {})
        file_evidence_scope = packet_context.file_evidence_scope
        session_file_state = packet_context.file_state
        projection_policy = {
            **dict(packet_context.projection_policy or {}),
            "agent_visible_runtime_projection": agent_visible_runtime_projection,
        }
        read_evidence_payload = packet_context.read_evidence_payload
        read_evidence_prompt_payload = _read_evidence_prompt_payload(read_evidence_payload)
        dynamic_context = self.dynamic_context_manager.project(
            DynamicContextInput(
                invocation_kind="single_agent_turn",
                session_id=session_id,
                turn_id=turn_id,
                history=tuple(dict(item) for item in list(history or []) if isinstance(item, dict)),
                file_state=session_file_state,
                file_evidence_scope=file_evidence_scope,
                session_context=session_context_payload,
                runtime_assembly=assembly_payload,
                runtime_envelope=envelope.to_dict(),
                current_user_message=str(user_message or ""),
                editor_context=_editor_context_from_session_context(session_context_payload),
                projection_policy=projection_policy,
            )
        )
        runtime_baseline_refs_payload = _runtime_baseline_refs_model_visible_payload(dynamic_context)
        dynamic_payload = dict(dynamic_context.dynamic_runtime_projection or dynamic_context.dynamic_runtime_delta or {})
        runtime_memory_context_payload = _memory_context_model_visible_payload(
            memory_context or session_context_payload.get("memory_context")
        )
        volatile_runtime_payload: dict[str, Any] = {}
        if active_work_context:
            volatile_runtime_payload["active_work_context"] = _active_work_model_visible_payload(
                active_work_context,
                controls_enabled=active_work_controls_enabled,
            )
        if current_work_boundary_receipt:
            volatile_runtime_payload["current_work_boundary_receipt"] = _current_work_boundary_receipt_model_visible_payload(
                current_work_boundary_receipt
            )
        prior_work_memory_payload = _prior_work_memory_model_visible_payload(
            session_context_payload.get("prior_work_memory_context"),
            current_user_message=user_message,
        )
        previous_incomplete_output_memory_spec = _previous_incomplete_output_memory_message_spec(
            prior_work_memory_payload,
            validity_scope=turn_id,
        )
        previous_incomplete_output_guidance_spec = _previous_incomplete_output_guidance_message_spec(
            prior_work_memory_payload,
            validity_scope=turn_id,
        )
        turn_memory_recovery_payload = _turn_memory_recovery_model_visible_payload(
            session_context_payload.get("turn_memory_recovery"),
            current_user_message=user_message,
        )
        if turn_memory_recovery_payload:
            volatile_runtime_payload["work_state_repair_context"] = turn_memory_recovery_payload
        runtime_observations_payload = _runtime_observations_model_visible_payload(
            session_context_payload.get("runtime_observations")
        )
        if runtime_observations_payload:
            volatile_runtime_payload["work_observations"] = runtime_observations_payload
        if turn_input_facts:
            volatile_runtime_payload["request_input_facts"] = _turn_input_facts_model_visible_payload(turn_input_facts)
        if volatile_runtime_payload:
            dynamic_payload = _drop_empty_payload({**dynamic_payload, **volatile_runtime_payload})
            volatile_runtime_payload = {}
        volatile_payload = dict(dynamic_context.volatile_request_projection or {})
        context_message_projection = build_context_message_projection(
            invocation_kind="single_agent_turn",
            source_ref_prefix="single_agent_turn",
            dynamic_context=dynamic_context,
            dynamic_payload=dynamic_payload,
            volatile_payload=volatile_payload,
            read_evidence_prompt_payload=read_evidence_prompt_payload,
        )
        dynamic_payload = context_message_projection.dynamic_payload
        current_request_payload = context_message_projection.current_request_payload
        context_message_specs = list(context_message_projection.message_specs)
        provider_protocol_specs = _provider_protocol_message_specs(
            session_context_payload,
            source_ref="single_agent_turn_provider_protocol_history",
            projection_policy=projection_policy,
            storage_root=self.base_dir,
            storage_run_id=turn_id,
        )
        current_turn_delta_payload = _current_turn_delta_model_payload(current_request_payload)
        model_messages, segment_plan, message_specs, source_manifest, slot_plan, context_load_plan = _model_messages_and_segment_plan(
            packet_id=packet_id,
            invocation_kind="single_agent_turn",
            provider_visible_append_scope=session_id,
            provider_visible_context_inheritance=_provider_visible_context_inheritance_from_session_context(
                session_context_payload,
                child_scope=session_id,
            ),
            compaction_generation=_context_compaction_generation_from_session_context(session_context_payload),
            storage_root=self.base_dir,
            model_selection=_model_selection_with_provider_lane(
                model_selection,
                provider_lane=PROVIDER_LANE_AGENT_TOOL_LOOP,
            ),
            context_capability_profile=_context_capability_profile_from_runtime_assembly(assembly_payload),
            system_wiring_manifest=_system_wiring_manifest_from_runtime_assembly(assembly_payload),
            specs=[
                _message_spec(
                    role="system",
                    content=prompt_assembly.content,
                    kind="global_static",
                    source_ref=",".join(prompt_assembly.prompt_pack_refs),
                    cache_scope="global",
                    cache_role="cacheable_prefix",
                    compression_role="preserve",
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Tool Capability Surface",
                    payload=tool_index_payload,
                    kind="tool_index_stable",
                    visible_kind="tool_capabilities",
                    source_ref="agent_visible_tool_contract",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                )
                if tool_index_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Task Environment Context",
                    payload=task_environment_context_payload,
                    kind="task_environment_context",
                    visible_kind="task_environment",
                    source_ref=task_environment_ref,
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "content_source": "harness.runtime.environment_model_visible_payload",
                        "cache_impact": "session_prefix_task_environment_context",
                    },
                )
                if task_environment_context_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Capability Catalog",
                    payload=capability_catalog_payload,
                    kind="capability_catalog",
                    visible_kind="capability_catalog",
                    source_ref=_capability_catalog_source_ref(capability_catalog_payload),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "content_source": "harness.runtime.capability_directory_catalog",
                        "cache_impact": "session_prefix_capability_catalog",
                        "routing_boundary": "Current requested groups and preferred namespaces stay in the turn operating contract tail.",
                    },
                )
                if capability_catalog_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Project Instructions",
                    payload=project_instruction_payload,
                    kind="project_instructions_stable",
                    source_ref=project_instruction_bundle.prompt_ref,
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "cache_impact": "project_prefix_stable",
                        "projection_strategy": "scoped_project_instruction_bundle",
                        "content_source": "harness.runtime.project_instructions",
                    },
                )
                if project_instruction_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="File evidence policy",
                    payload=_file_evidence_policy_stable_payload(),
                    kind="file_evidence_policy_stable",
                    visible_kind="file_evidence_reuse_policy",
                    source_ref="file_evidence_policy_stable.read_evidence_reuse_contract",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "projection_strategy": "stable_file_evidence_policy",
                    },
                ),
                _message_spec(
                    role="system",
                    content=personality_instruction,
                    kind="personality_stable",
                    source_ref=",".join(personality_prompt_assembly.manifest.get("stable_prompt_refs") or ()),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=environment_instruction,
                    kind="environment_stable",
                    source_ref=",".join(prompt_mount_plan.environment_prompt_refs),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=environment_guidance_instruction,
                    kind="environment_guidance_stable",
                    source_ref=",".join(prompt_mount_plan.environment_guidance_prompt_refs),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "environment_guidance_prompt_keys": list(prompt_mount_plan.environment_guidance_prompt_keys),
                        "environment_guidance_trigger_reasons": dict(prompt_mount_plan.environment_guidance_trigger_reasons),
                    },
                )
                if environment_guidance_instruction.strip()
                else None,
                _message_spec(
                    role="system",
                    content=agent_instruction,
                    kind="agent_stable",
                    source_ref=",".join(agent_prompt_assembly.manifest.get("stable_prompt_refs") or ()),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Stable Context References",
                    payload=runtime_baseline_refs_payload,
                    kind="runtime_baseline_refs",
                    visible_kind="context_continuity",
                    source_ref=_runtime_baseline_refs_source_ref(runtime_baseline_refs_payload),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="ref_only",
                    metadata={
                        "content_source": "harness.runtime.dynamic_context.runtime_baseline_refs",
                        "cache_impact": "session_prefix_runtime_baseline_refs",
                        "stability_rule": "Only immutable agent and environment refs are cacheable; current action and execution facts stay in the current request context tail.",
                    },
                )
                if runtime_baseline_refs_payload
                else None,
                *provider_protocol_specs,
                *context_message_specs,
                previous_incomplete_output_memory_spec,
                _runtime_payload_spec(
                    role="user",
                    title="Current User Request",
                    payload=current_turn_delta_payload,
                    kind="current_turn_user_context",
                    visible_kind="current_user_request",
                    source_ref="single_agent_turn_current_request",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata={
                        **_dynamic_context_segment_metadata(dynamic_context, source="current_request"),
                        **_current_user_context_append_metadata(current_turn_delta_payload, turn_id=turn_id),
                    },
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Selected memory context",
                    payload=runtime_memory_context_payload,
                    kind="runtime_memory_context",
                    visible_kind="selected_memory_context",
                    source_ref=_runtime_memory_context_source_ref(runtime_memory_context_payload),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="summarize",
                    metadata={
                        "content_source": "memory_system.runtime_memory_context",
                        "stability_rule": "selected memory context is rememberable context; changed selections append as new context and the previous provider-visible package remains sealed",
                        "cache_impact": "context_append_then_sealed_prefix",
                    },
                )
                if runtime_memory_context_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Current File Evidence",
                    payload=_read_evidence_current_prompt_payload(read_evidence_prompt_payload),
                    kind="read_evidence_injection",
                    visible_kind="current_file_evidence",
                    source_ref=_read_evidence_prompt_source_ref(read_evidence_prompt_payload, fallback=packet_id),
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="preserve",
                    metadata={
                        "projection_strategy": "current_exact_or_required_read_append",
                        "content_source": "harness.runtime.dynamic_context.read_evidence_projector",
                        "volatility_reason": "current exact text and read-required windows are current evidence facts; they are not runtime control tail instructions",
                        "stability_rule": (
                            "Read evidence exact windows use path/range as the stable fact slot and content hash as the version. "
                            "Unchanged windows are not re-appended; changed windows supersede prior content after provider success."
                        ),
                        **_read_evidence_injection_append_metadata(read_evidence_prompt_payload),
                    },
                )
                if _read_evidence_current_prompt_payload(read_evidence_prompt_payload)
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Current Request Context",
                    payload=dynamic_payload,
                    preamble=runtime_instruction,
                    kind="dynamic_projection",
                    visible_kind="current_request_context",
                    source_ref="single_agent_turn_runtime_delta",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata=_current_runtime_tail_metadata(
                        {
                            **_dynamic_context_segment_metadata(dynamic_context, source="runtime_delta"),
                            "content_source": "harness.runtime.dynamic_context.runtime_delta_projection",
                        },
                        semantic_slot="runtime_delta_tail",
                        validity_scope=turn_id,
                    ),
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Current Action Contract",
                    payload=current_operating_contract_payload,
                    preamble=_runtime_control_context_notice(validity_scope=turn_id),
                    kind="turn_operating_contract",
                    visible_kind="current_action_contract",
                    source_ref="single_agent_turn_operating_contract",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="preserve",
                    metadata=_current_runtime_tail_metadata(
                        {
                            "content_source": "harness.runtime.turn_operating_contract",
                            "volatility_reason": "current turn action surface, output protocol, and capability routing are bound to the provider request",
                        },
                        semantic_slot="turn_operating_contract",
                        validity_scope=turn_id,
                    ),
                )
                if current_operating_contract_payload
                else None,
                _message_spec(
                    role="system",
                    content=_runtime_control_context_content(
                        turn_state_guidance_instruction,
                        validity_scope=turn_id,
                        source_ref=",".join(prompt_mount_plan.turn_state_guidance_prompt_refs),
                        include_notice=False,
                    ),
                    kind="turn_state_guidance",
                    source_ref=",".join(prompt_mount_plan.turn_state_guidance_prompt_refs),
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="preserve",
                    metadata=_current_runtime_tail_metadata(
                        {
                            "environment_guidance_prompt_keys": list(prompt_mount_plan.turn_state_guidance_prompt_keys),
                            "environment_guidance_trigger_reasons": dict(prompt_mount_plan.turn_state_guidance_trigger_reasons),
                            "volatility_reason": "turn state guidance is selected from active state such as memory, observations, steering, or recovery",
                        },
                        semantic_slot="turn_state_guidance",
                        validity_scope=turn_id,
                    ),
                )
                if turn_state_guidance_instruction.strip()
                else None,
                previous_incomplete_output_guidance_spec,
                _runtime_payload_spec(
                    role="system",
                    title="Current Request Signals",
                    payload=volatile_runtime_payload,
                    kind="volatile_runtime_state",
                    visible_kind="current_request_signals",
                    source_ref="single_agent_turn_volatile_runtime_state",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata={
                        "volatility_reason": "active work, recovery, runtime observations, and turn facts can change on every user turn",
                        "cache_impact": "volatile_suffix_only",
                        "content_source": "harness.runtime.compiler.single_turn_volatile_runtime_state",
                    },
                )
                if volatile_runtime_payload
                else None,
            ],
            collect_dynamic_context_metadata_diagnostics=True,
        )
        protocol_sanitizer = _sanitize_model_messages_for_prompt_packet(
            model_messages,
            message_specs=message_specs,
            turn_id=turn_id,
            source="harness.runtime.compiler.single_agent_turn",
        )
        model_messages = [dict(item) for item in protocol_sanitizer.messages]
        content_fragments = build_content_fragments_from_message_specs(
            segment_plan=segment_plan,
            message_specs=message_specs,
            fallback_model_messages=model_messages,
        )
        single_turn_dynamic_refs = (
            "runtime_delta_projection",
            "operation_authorization",
            "active_work_context",
            "recent_work_outcome",
            "current_work_boundary_receipt",
            "previous_incomplete_output_memory",
            "work_state_repair_context",
            "work_observations",
            "request_input_facts",
        )
        single_turn_volatile_refs = (
            "runtime_envelope",
            "turn_id",
            "history",
            "user_message",
            "turn_state_guidance",
        )
        prompt_manifest = build_runtime_prompt_manifest(
            invocation_kind="single_agent_turn",
            assembly=_merge_prompt_assemblies(
                prompt_assembly,
                personality_prompt_assembly,
                environment_prompt_assembly,
                environment_guidance_prompt_assembly,
                turn_state_guidance_prompt_assembly,
                agent_prompt_assembly,
                invocation_kind="single_agent_turn",
            ),
            packet_id=packet_id,
            dynamic_projection_refs=single_turn_dynamic_refs,
            volatile_state_refs=single_turn_volatile_refs,
        ).to_dict()
        prompt_manifest["segment_plan_ref"] = segment_plan.segment_plan_id
        prompt_manifest["prompt_assembly_plan_ref"] = segment_plan.provider_policy_ref
        prompt_manifest["runtime_prompt_source_manifest_ref"] = source_manifest.manifest_id
        prompt_manifest["runtime_prompt_sources"] = source_manifest.to_dict()
        prompt_manifest["context_physical_assembly"] = _context_physical_assembly_manifest_from_specs(message_specs)
        prompt_manifest["prompt_slot_plan_ref"] = slot_plan.plan_id
        prompt_manifest["prompt_slot_plan"] = slot_plan.to_dict()
        prompt_manifest["runtime_context_load_plan_ref"] = context_load_plan.plan_id
        prompt_manifest["runtime_context_load_plan"] = context_load_plan.to_dict()
        prompt_manifest["prompt_mount_plan"] = prompt_mount_plan.to_dict()
        prompt_manifest["prompt_wiring_plan"] = _prompt_wiring_plan_manifest_payload(
            runtime_prompt_wiring_plan,
            prompt_policy=prompt_policy,
        )
        prompt_manifest["tool_call_contract"] = tool_call_contract.to_hidden_control_payload()
        prompt_manifest["turn_operating_contract"] = turn_operating_contract.to_hidden_control_payload()
        prompt_manifest["dynamic_context_report"] = dynamic_context.to_report_dict()
        prompt_manifest["protocol_sanitizer"] = dict(protocol_sanitizer.diagnostics)
        prompt_manifest["context_window"] = _context_window_report(
            session_context=session_context,
            history=history,
            dynamic_context=dynamic_context,
        )
        context_contract_manifest_payload = _attach_context_contract_manifest(
            prompt_manifest,
            packet_id=packet_id,
            invocation_kind="single_agent_turn",
            message_specs=message_specs,
            segment_plan=segment_plan.to_dict(),
        )
        _attach_project_instruction_manifest(prompt_manifest, project_instruction_bundle)
        tool_catalog_manifest_payload = _attach_tool_catalog_manifest(prompt_manifest, tool_catalog_manifest)
        prompt_composition_manifest = _attach_prompt_composition_manifest(
            prompt_manifest,
            invocation_kind="single_agent_turn",
            packet_id=packet_id,
            segment_plan=segment_plan.to_dict(),
            runtime_slot_plan=slot_plan,
            dynamic_projection_refs=single_turn_dynamic_refs,
            volatile_state_refs=single_turn_volatile_refs,
            diagnostics={"compiler_entrypoint": "compile_single_agent_turn_packet"},
        )
        model_messages = _render_model_messages_from_prompt_composition(
            prompt_manifest=prompt_manifest,
            prompt_composition_manifest=prompt_composition_manifest,
            content_fragments=content_fragments,
            model_messages=model_messages,
        )
        _attach_model_message_metrics(prompt_manifest, model_messages=model_messages, segment_plan=segment_plan.to_dict())
        packet = RuntimeInvocationPacket(
            packet_id=packet_id,
            envelope_ref=envelope.envelope_id,
            invocation_kind="single_agent_turn",
            invocation_index=1,
            session_id=session_id,
            turn_id=turn_id,
            model_messages=model_messages,
            segment_plan=segment_plan.to_dict(),
            prompt_composition_manifest=prompt_composition_manifest,
            tool_catalog_manifest=tool_catalog_manifest_payload,
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
            available_tools=single_turn_tools,
            allowed_action_types=allowed_actions,
            output_contract=output_contract,
            hidden_control_refs={
                "agent_invocation_id": agent_invocation_id,
                "runtime_assembly_id": str(assembly_payload.get("assembly_id") or ""),
                "tool_call_contract": tool_call_contract.to_hidden_control_payload(),
                "turn_operating_contract": turn_operating_contract.to_hidden_control_payload(),
            },
            context_refs=dynamic_context.context_refs,
            artifact_refs=dynamic_context.artifact_refs,
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
                "context_contract_manifest": context_contract_manifest_payload,
                "tool_catalog_manifest": tool_catalog_manifest_payload,
                "model_input_authority": "prompt_composition.message_projection",
                "protocol_sanitizer": dict(protocol_sanitizer.diagnostics),
                "runtime_packet_context": packet_context.to_dict(),
                "turn_operating_contract": turn_operating_contract.to_dict(),
                "control_capabilities": dict(effective_control_capabilities),
                "tool_call_contract": tool_call_contract.to_hidden_control_payload(),
                "active_work_context_present": bool(active_work_context),
                "current_work_boundary_receipt": dict(current_work_boundary_receipt or {}),
                "turn_input_facts_present": bool(turn_input_facts),
            },
        )
        return RuntimeCompilationResult(envelope=envelope, packet=packet)

    def compile_observation_followup_packet(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent_invocation_id: str,
        user_message: str,
        history: list[dict[str, Any]],
        session_context: dict[str, Any] | None = None,
        observations: list[dict[str, Any]],
        agent_profile_ref: str = "main_interactive_agent",
        model_selection: dict[str, Any] | None = None,
        available_tools: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
        runtime_assembly: Any | None = None,
    ) -> RuntimeCompilationResult:
        assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
        self._bind_assembly_base_dir(assembly_payload)
        profile_payload = dict(assembly_payload.get("profile") or {})
        environment_payload = dict(assembly_payload.get("task_environment") or {})
        agent_profile_ref = str(assembly_payload.get("agent_profile_ref") or agent_profile_ref or "main_interactive_agent")
        task_environment_ref = str(environment_payload.get("environment_id") or "env.general.workspace")
        runtime_policy = {
            "planning_policy": dict(profile_payload.get("planning_policy") or {}),
            "task_lifecycle_policy": dict(profile_payload.get("task_lifecycle_policy") or {}),
        }
        permission_policy = dict(profile_payload.get("permission_policy") or {"permission_scope": "bounded_read_observation"})
        permission_policy.setdefault("permission_scope", str(permission_policy.get("scope") or "bounded_read_observation"))
        prompt_pack_refs = _prompt_pack_refs_for_invocation(
            profile_payload,
            invocation_kind="tool_observation_followup",
            assembly_payload=assembly_payload,
        )
        tool_payloads = tuple(dict(item) for item in list(available_tools or []) if isinstance(item, dict))
        task_lifecycle = dict(profile_payload.get("task_lifecycle_policy") or {})
        observation_allowed_actions = (
            ("respond", "ask_user", "tool_call", "request_task_run", "block")
            if task_lifecycle.get("request_task_run") is not False
            else ("respond", "ask_user", "tool_call", "block")
        )
        tool_call_contract = build_tool_call_contract(
            invocation_kind="tool_observation_followup",
            allowed_action_types=observation_allowed_actions,
            available_tools=tool_payloads,
            runtime_assembly=assembly_payload,
        )
        agent_visible_runtime_projection = build_agent_visible_runtime_projection(
            invocation_kind="tool_observation_followup",
            allowed_action_types=observation_allowed_actions,
            profile_payload=profile_payload,
            environment_payload=environment_payload,
            operation_authorization=dict(assembly_payload.get("operation_authorization") or {}),
            available_tools=tool_payloads,
            permission_mode=str(assembly_payload.get("permission_mode") or "default"),
            tool_call_contract=tool_call_contract,
        )
        envelope = RuntimeEnvelope(
            envelope_id=f"rtenv:{turn_id}:observation_followup",
            scope_kind="turn",
            session_id=session_id,
            turn_id=turn_id,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            runtime_policy=runtime_policy,
            sandbox_policy=dict(environment_payload.get("sandbox_policy") or {}),
            file_policy={
                "file_management": dict(environment_payload.get("file_management") or {}),
                "file_access_tables": list(environment_payload.get("file_access_tables") or []),
            },
            artifact_policy=dict(environment_payload.get("artifact_policy") or {}),
            permission_policy=permission_policy,
            prompt_policy={"invocation_kind": "tool_observation_followup"},
            output_policy={"format": "model_action_request_json"},
            diagnostics={
                "agent_invocation_id": agent_invocation_id,
                "model_selection": dict(model_selection or {}),
                "runtime_assembly_id": str(assembly_payload.get("assembly_id") or ""),
            },
        )
        schema = model_action_request_schema(turn_id)
        prompt_assembly = self._assemble_prompt_pack(
            invocation_kind="tool_observation_followup",
            prompt_pack_refs=prompt_pack_refs,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            assembly_payload=assembly_payload,
        )
        runtime_prompt_wiring_plan = _build_invocation_prompt_wiring_plan(
            base_dir=self.base_dir,
            assembly_payload=assembly_payload,
            invocation_kind="tool_observation_followup",
            allowed_actions=observation_allowed_actions,
            observations=tuple(dict(item) for item in list(observations or []) if isinstance(item, dict)),
            visible_tools=tool_payloads,
            session_context=dict(session_context or {}),
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
        )
        prompt_mount_plan = environment_prompt_inventory_for_invocation(
            _prompt_mount_plan_payload_from_runtime_assembly(assembly_payload),
            invocation_kind="tool_observation_followup",
            allowed_actions=observation_allowed_actions,
            observations=tuple(dict(item) for item in list(observations or []) if isinstance(item, dict)),
            visible_tools=tool_payloads,
            session_context=dict(session_context or {}),
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
        )
        prompt_mount_plan = _prompt_mount_plan_with_wiring_guidance(prompt_mount_plan, runtime_prompt_wiring_plan)
        tool_catalog_manifest = _build_tool_catalog_manifest_for_mount_plan(
            invocation_kind="tool_observation_followup",
            tool_payloads=tool_payloads,
            source_ref="tool_observation_followup.available_tools",
            prompt_mount_plan=prompt_mount_plan,
        )
        tool_index_payload = (
            tool_catalog_manifest.to_model_visible_payload(include_catalog_hash=True)
            if tool_payloads
            else {}
        )
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="tool_observation_followup",
            prompt_refs=_agent_work_role_refs_for_invocation(assembly_payload, invocation_kind="tool_observation_followup"),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            assembly_payload=assembly_payload,
        )
        personality_prompt_assembly = self._assemble_personality_prompt_layer(
            prompt_mount_plan=prompt_mount_plan,
            invocation_kind="tool_observation_followup",
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            assembly_payload=assembly_payload,
        )
        environment_prompt_assembly, environment_guidance_prompt_assembly = self._assemble_environment_prompt_layers(
            prompt_mount_plan=prompt_mount_plan,
            agent_profile_ref=agent_profile_ref,
            assembly_payload=assembly_payload,
        )
        turn_state_guidance_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=tuple(prompt_mount_plan.turn_state_guidance_prompt_refs or ()),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(prompt_mount_plan.selected_environment_id or ""),
            assembly_payload=assembly_payload,
        )
        project_instruction_bundle = collect_project_instruction_bundle(base_dir=self.base_dir)
        runtime_instruction = _runtime_projection_instruction(
            agent_visible_runtime_projection,
            validity_scope=f"{turn_id}:observation_followup:{len(observations) + 1}",
        )
        environment_instruction = render_environment_instruction(
            environment_payload,
            environment_prompt_assembly=environment_prompt_assembly,
        )
        environment_guidance_instruction = render_environment_guidance_instruction(environment_guidance_prompt_assembly)
        turn_state_guidance_instruction = render_environment_guidance_instruction(turn_state_guidance_prompt_assembly)
        personality_instruction = render_personality_prompt_instruction(personality_prompt_assembly)
        agent_instruction = render_agent_prompt_instruction(agent_prompt_assembly, invocation_kind="tool_observation_followup")
        stable_payload = {
            "schema": schema,
            "task_environment": _environment_model_visible_payload(
                environment_payload,
                prompt_mount_plan=prompt_mount_plan.to_dict(),
            ),
            **_project_instruction_model_payload(project_instruction_bundle),
        }
        packet_id = f"rtpacket:{turn_id}:tool_observation_followup:{len(observations) + 1}"
        projection_policy = _dynamic_context_projection_policy(
            invocation_kind="tool_observation_followup",
            model_selection=model_selection,
            assembly_payload=assembly_payload,
            overrides={
                "agent_visible_runtime_projection": agent_visible_runtime_projection,
                "operation_authorization": dict(assembly_payload.get("operation_authorization") or {}),
            },
        )
        session_evidence_projection = _build_session_file_evidence_projection(
            session_id=session_id,
            base_dir=self.base_dir,
            runtime_assembly=assembly_payload,
            packet_id=packet_id,
            budget_policy=projection_policy,
            current_observations=tuple(dict(item) for item in list(observations or []) if isinstance(item, dict)),
        )
        read_evidence_payload = dict(session_evidence_projection.get("read_evidence_payload") or {})
        read_evidence_prompt_payload = _read_evidence_prompt_payload(read_evidence_payload)
        dynamic_context = self.dynamic_context_manager.project(
            DynamicContextInput(
                invocation_kind="tool_observation_followup",
                session_id=session_id,
                turn_id=turn_id,
                history=tuple(dict(item) for item in list(history or []) if isinstance(item, dict)),
                session_context=dict(session_context or {}),
                observations=tuple(dict(item) for item in list(observations or []) if isinstance(item, dict)),
                runtime_assembly=assembly_payload,
                runtime_envelope=envelope.to_dict(),
                current_user_message=str(user_message or ""),
                editor_context=_editor_context_from_session_context(dict(session_context or {})),
                projection_policy=projection_policy,
            )
        )
        runtime_baseline_refs_payload = _runtime_baseline_refs_model_visible_payload(dynamic_context)
        dynamic_payload = dict(dynamic_context.dynamic_runtime_projection or dynamic_context.dynamic_runtime_delta or {})
        runtime_memory_context_payload = _memory_context_model_visible_payload(
            dict(session_context or {}).get("memory_context")
        )
        volatile_payload = dict(dynamic_context.volatile_request_projection or {})
        context_message_projection = build_context_message_projection(
            invocation_kind="tool_observation_followup",
            source_ref_prefix="observation_followup",
            dynamic_context=dynamic_context,
            dynamic_payload=dynamic_payload,
            volatile_payload=volatile_payload,
            read_evidence_prompt_payload=read_evidence_prompt_payload,
        )
        dynamic_payload = context_message_projection.dynamic_payload
        current_request_payload = context_message_projection.current_request_payload
        context_message_specs = list(context_message_projection.message_specs)
        followup_session_context = dict(session_context or {})
        provider_protocol_specs = _provider_protocol_message_specs(
            followup_session_context,
            source_ref="observation_followup_provider_protocol_history",
            projection_policy=projection_policy,
            storage_root=self.base_dir,
            storage_run_id=turn_id,
        )
        current_turn_delta_payload = _current_turn_delta_model_payload(current_request_payload)
        model_messages, segment_plan, message_specs, source_manifest, slot_plan, context_load_plan = _model_messages_and_segment_plan(
            packet_id=packet_id,
            invocation_kind="tool_observation_followup",
            provider_visible_append_scope=session_id,
            provider_visible_context_inheritance=_provider_visible_context_inheritance_from_session_context(
                followup_session_context,
                child_scope=session_id,
            ),
            compaction_generation=_context_compaction_generation_from_session_context(followup_session_context),
            storage_root=self.base_dir,
            model_selection=_model_selection_with_provider_lane(
                model_selection,
                provider_lane=PROVIDER_LANE_AGENT_TOOL_LOOP,
            ),
            context_capability_profile=_context_capability_profile_from_runtime_assembly(assembly_payload),
            system_wiring_manifest=_system_wiring_manifest_from_runtime_assembly(assembly_payload),
            specs=[
                _message_spec(
                    role="system",
                    content=prompt_assembly.content,
                    kind="global_static",
                    source_ref=",".join(prompt_assembly.prompt_pack_refs),
                    cache_scope="global",
                    cache_role="cacheable_prefix",
                    compression_role="preserve",
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Tool Capability Surface",
                    payload=tool_index_payload,
                    kind="tool_index_stable",
                    visible_kind="tool_capabilities",
                    source_ref="agent_visible_tool_contract",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                )
                if tool_index_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Tool observation follow-up contract",
                    payload=stable_payload,
                    kind="runtime_stable_contract",
                    visible_kind="operating_contract",
                    source_ref="observation_followup_stable_contract",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=environment_instruction,
                    kind="environment_stable",
                    source_ref=",".join(prompt_mount_plan.environment_prompt_refs),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _runtime_payload_spec(
                    role="system",
                    title="File evidence policy",
                    payload=_file_evidence_policy_stable_payload(),
                    kind="file_evidence_policy_stable",
                    visible_kind="file_evidence_reuse_policy",
                    source_ref="file_evidence_policy_stable.read_evidence_reuse_contract",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "projection_strategy": "stable_file_evidence_policy",
                    },
                ),
                _message_spec(
                    role="system",
                    content=environment_guidance_instruction,
                    kind="environment_guidance_stable",
                    source_ref=",".join(prompt_mount_plan.environment_guidance_prompt_refs),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "environment_guidance_prompt_keys": list(prompt_mount_plan.environment_guidance_prompt_keys),
                        "environment_guidance_trigger_reasons": dict(prompt_mount_plan.environment_guidance_trigger_reasons),
                    },
                )
                if environment_guidance_instruction.strip()
                else None,
                _message_spec(
                    role="system",
                    content=personality_instruction,
                    kind="personality_stable",
                    source_ref=",".join(personality_prompt_assembly.manifest.get("stable_prompt_refs") or ()),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=agent_instruction,
                    kind="agent_stable",
                    source_ref=",".join(agent_prompt_assembly.manifest.get("stable_prompt_refs") or ()),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Stable Context References",
                    payload=runtime_baseline_refs_payload,
                    kind="runtime_baseline_refs",
                    visible_kind="context_continuity",
                    source_ref=_runtime_baseline_refs_source_ref(runtime_baseline_refs_payload),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="ref_only",
                    metadata={
                        "content_source": "harness.runtime.dynamic_context.runtime_baseline_refs",
                        "cache_impact": "session_prefix_runtime_baseline_refs",
                        "stability_rule": "Only immutable agent and environment refs are cacheable; current action and execution facts stay in the current request context tail.",
                    },
                )
                if runtime_baseline_refs_payload
                else None,
                *provider_protocol_specs,
                *context_message_specs,
                _runtime_payload_spec(
                    role="system",
                    title="Current Request Context",
                    payload=dynamic_payload,
                    preamble=runtime_instruction,
                    kind="dynamic_projection",
                    visible_kind="current_request_context",
                    source_ref="observation_followup_runtime_delta",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata=_current_runtime_tail_metadata(
                        {
                            **_dynamic_context_segment_metadata(dynamic_context, source="runtime_delta"),
                            "content_source": "harness.runtime.dynamic_context.runtime_delta_projection",
                        },
                        semantic_slot="runtime_delta_tail",
                        validity_scope=f"{turn_id}:observation_followup:{len(observations) + 1}",
                    ),
                ),
                _message_spec(
                    role="system",
                    content=_runtime_control_context_content(
                        turn_state_guidance_instruction,
                        validity_scope=f"{turn_id}:observation_followup:{len(observations) + 1}",
                        source_ref=",".join(prompt_mount_plan.turn_state_guidance_prompt_refs),
                        include_notice=False,
                    ),
                    kind="turn_state_guidance",
                    source_ref=",".join(prompt_mount_plan.turn_state_guidance_prompt_refs),
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="preserve",
                    metadata=_current_runtime_tail_metadata(
                        {
                            "environment_guidance_prompt_keys": list(prompt_mount_plan.turn_state_guidance_prompt_keys),
                            "environment_guidance_trigger_reasons": dict(prompt_mount_plan.turn_state_guidance_trigger_reasons),
                            "volatility_reason": "turn state guidance is selected from observation followup state and must expire after this follow-up boundary",
                        },
                        semantic_slot="turn_state_guidance",
                        validity_scope=f"{turn_id}:observation_followup:{len(observations) + 1}",
                    ),
                )
                if turn_state_guidance_instruction.strip()
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Current File Evidence",
                    payload=_read_evidence_current_prompt_payload(read_evidence_prompt_payload),
                    kind="read_evidence_injection",
                    visible_kind="current_file_evidence",
                    source_ref=_read_evidence_prompt_source_ref(read_evidence_prompt_payload, fallback=packet_id),
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="preserve",
                    metadata={
                        "projection_strategy": "current_exact_or_required_read_append",
                        "content_source": "harness.runtime.dynamic_context.read_evidence_projector",
                        "volatility_reason": "current exact text and read-required windows are current evidence facts; they are not runtime control tail instructions",
                        "stability_rule": (
                            "Read evidence exact windows use path/range as the stable fact slot and content hash as the version. "
                            "Unchanged windows are not re-appended; changed windows supersede prior content after provider success."
                        ),
                        **_read_evidence_injection_append_metadata(read_evidence_prompt_payload),
                    },
                )
                if _read_evidence_current_prompt_payload(read_evidence_prompt_payload)
                else None,
                _runtime_payload_spec(
                    role="user",
                    title="Current User Request",
                    payload=current_turn_delta_payload,
                    kind="current_turn_user_context",
                    visible_kind="current_user_request",
                    source_ref="observation_followup_current_request",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="ref_only",
                    metadata={
                        **_dynamic_context_segment_metadata(dynamic_context, source="current_request"),
                        **_current_user_context_append_metadata(current_turn_delta_payload, turn_id=turn_id),
                    },
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Tool observation selected memory context",
                    payload=runtime_memory_context_payload,
                    kind="runtime_memory_context",
                    visible_kind="selected_memory_context",
                    source_ref=_runtime_memory_context_source_ref(runtime_memory_context_payload),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="summarize",
                    metadata={
                        "content_source": "memory_system.runtime_memory_context",
                        "stability_rule": "selected memory context is rememberable context; changed selections append as new context and the previous provider-visible package remains sealed",
                        "cache_impact": "context_append_then_sealed_prefix",
                    },
                )
                if runtime_memory_context_payload
                else None,
            ],
            collect_dynamic_context_metadata_diagnostics=True,
        )
        content_fragments = build_content_fragments_from_message_specs(
            segment_plan=segment_plan,
            message_specs=message_specs,
            fallback_model_messages=model_messages,
        )
        observation_dynamic_refs = (
            "runtime_delta_projection",
            "operation_authorization",
            "history",
            "task_plan_context",
            "editor_context_index",
            "turn_state_guidance",
            "runtime_memory_context",
        )
        observation_volatile_refs = (
            "runtime_envelope",
            "turn_id",
            "user_message",
            "observations",
        )
        prompt_manifest = build_runtime_prompt_manifest(
            invocation_kind="tool_observation_followup",
            assembly=_merge_prompt_assemblies(
                prompt_assembly,
                personality_prompt_assembly,
                environment_prompt_assembly,
                environment_guidance_prompt_assembly,
                turn_state_guidance_prompt_assembly,
                agent_prompt_assembly,
                invocation_kind="tool_observation_followup",
            ),
            packet_id=packet_id,
            dynamic_projection_refs=observation_dynamic_refs,
            volatile_state_refs=observation_volatile_refs,
        ).to_dict()
        prompt_manifest["segment_plan_ref"] = segment_plan.segment_plan_id
        prompt_manifest["prompt_assembly_plan_ref"] = segment_plan.provider_policy_ref
        prompt_manifest["runtime_prompt_source_manifest_ref"] = source_manifest.manifest_id
        prompt_manifest["runtime_prompt_sources"] = source_manifest.to_dict()
        prompt_manifest["context_physical_assembly"] = _context_physical_assembly_manifest_from_specs(message_specs)
        prompt_manifest["prompt_slot_plan_ref"] = slot_plan.plan_id
        prompt_manifest["prompt_slot_plan"] = slot_plan.to_dict()
        prompt_manifest["runtime_context_load_plan_ref"] = context_load_plan.plan_id
        prompt_manifest["runtime_context_load_plan"] = context_load_plan.to_dict()
        prompt_manifest["prompt_mount_plan"] = prompt_mount_plan.to_dict()
        prompt_manifest["prompt_wiring_plan"] = _prompt_wiring_plan_manifest_payload(
            runtime_prompt_wiring_plan,
            prompt_policy={},
        )
        prompt_manifest["tool_call_contract"] = tool_call_contract.to_hidden_control_payload()
        prompt_manifest["dynamic_context_report"] = dynamic_context.to_report_dict()
        prompt_manifest["context_window"] = _context_window_report(
            session_context=session_context,
            history=history,
            dynamic_context=dynamic_context,
        )
        context_contract_manifest_payload = _attach_context_contract_manifest(
            prompt_manifest,
            packet_id=packet_id,
            invocation_kind="tool_observation_followup",
            message_specs=message_specs,
            segment_plan=segment_plan.to_dict(),
        )
        _attach_project_instruction_manifest(prompt_manifest, project_instruction_bundle)
        tool_catalog_manifest_payload = _attach_tool_catalog_manifest(prompt_manifest, tool_catalog_manifest)
        prompt_composition_manifest = _attach_prompt_composition_manifest(
            prompt_manifest,
            invocation_kind="tool_observation_followup",
            packet_id=packet_id,
            segment_plan=segment_plan.to_dict(),
            runtime_slot_plan=slot_plan,
            dynamic_projection_refs=observation_dynamic_refs,
            volatile_state_refs=observation_volatile_refs,
            diagnostics={"compiler_entrypoint": "compile_observation_followup_packet"},
        )
        model_messages = _render_model_messages_from_prompt_composition(
            prompt_manifest=prompt_manifest,
            prompt_composition_manifest=prompt_composition_manifest,
            content_fragments=content_fragments,
            model_messages=model_messages,
        )
        _attach_model_message_metrics(prompt_manifest, model_messages=model_messages, segment_plan=segment_plan.to_dict())
        packet = RuntimeInvocationPacket(
            packet_id=packet_id,
            envelope_ref=envelope.envelope_id,
            invocation_kind="tool_observation_followup",
            invocation_index=len(observations) + 1,
            session_id=session_id,
            turn_id=turn_id,
            model_messages=model_messages,
            segment_plan=segment_plan.to_dict(),
            prompt_composition_manifest=prompt_composition_manifest,
            tool_catalog_manifest=tool_catalog_manifest_payload,
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
            available_tools=tool_payloads,
            allowed_action_types=observation_allowed_actions,
            observation_refs=dynamic_context.observation_refs,
            artifact_refs=dynamic_context.artifact_refs,
            context_refs=dynamic_context.context_refs,
            output_contract={"schema": schema, "format": "json_object"},
            hidden_control_refs={
                "agent_invocation_id": agent_invocation_id,
                "runtime_assembly_id": str(assembly_payload.get("assembly_id") or ""),
                "tool_call_contract": tool_call_contract.to_hidden_control_payload(),
            },
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
                "context_contract_manifest": context_contract_manifest_payload,
                "tool_catalog_manifest": tool_catalog_manifest_payload,
                "tool_call_contract": tool_call_contract.to_hidden_control_payload(),
                "model_input_authority": "prompt_composition.message_projection",
            },
        )
        return RuntimeCompilationResult(envelope=envelope, packet=packet)

    def _assemble_prompt_pack(
        self,
        *,
        invocation_kind: str,
        prompt_pack_refs: tuple[str, ...],
        agent_profile_ref: str,
        task_environment_ref: str,
        assembly_payload: dict[str, Any] | None = None,
    ) -> PromptAssemblyResult:
        refs = tuple(prompt_pack_refs or ())
        if not refs:
            default_ref = default_pack_ref_for_invocation(invocation_kind)
            refs = (default_ref,) if default_ref else ()
        assembly = PromptAssemblyService(self.base_dir).assemble(
            PromptAssemblyRequest(
                invocation_kind=invocation_kind,
                prompt_pack_refs=refs,
                agent_profile_ref=agent_profile_ref,
                task_environment_ref=task_environment_ref,
                metadata=_prompt_assembly_metadata_from_runtime_assembly(assembly_payload),
            )
        )
        _validate_runtime_prompt_pack_assembly(
            assembly,
            invocation_kind=invocation_kind,
            requested_refs=refs,
        )
        return assembly

    def _assemble_prompt_contract(
        self,
        *,
        task_prompt_contract: dict[str, Any] | None = None,
        graph_node_prompt_contract: dict[str, Any] | None = None,
        assembly_payload: dict[str, Any] | None = None,
    ) -> PromptAssemblyResult:
        if not task_prompt_contract and not graph_node_prompt_contract:
            return PromptAssemblyResult(
                assembly_id="promptasm:empty:task_prompt_contract",
                invocation_kind="task_prompt_contract",
                sections=(),
            )
        return PromptAssemblyService(self.base_dir).assemble(
            PromptAssemblyRequest(
                invocation_kind="task_prompt_contract",
                task_prompt_contract=dict(task_prompt_contract or {}),
                graph_node_prompt_contract=dict(graph_node_prompt_contract or {}),
                metadata=_prompt_assembly_metadata_from_runtime_assembly(assembly_payload),
            )
        )

    def _bind_assembly_base_dir(self, assembly_payload: dict[str, Any]) -> None:
        backend_dir = str(assembly_payload.get("backend_dir") or "").strip()
        if backend_dir:
            next_base_dir = Path(backend_dir)
            if next_base_dir != self.base_dir:
                self.base_dir = next_base_dir
                self.dynamic_context_manager = DynamicContextManager(base_dir=self.base_dir)

    def _assemble_prompt_refs(
        self,
        *,
        invocation_kind: str,
        prompt_refs: tuple[str, ...],
        agent_profile_ref: str,
        task_environment_ref: str,
        assembly_payload: dict[str, Any] | None = None,
    ) -> PromptAssemblyResult:
        if not prompt_refs:
            return PromptAssemblyResult(
                assembly_id=f"promptasm:empty:{invocation_kind}",
                invocation_kind=invocation_kind,
                sections=(),
            )
        assembly = PromptAssemblyService(self.base_dir).assemble(
            PromptAssemblyRequest(
                invocation_kind=invocation_kind,
                prompt_pack_refs=(),
                prompt_refs=prompt_refs,
                agent_profile_ref=agent_profile_ref,
                task_environment_ref=task_environment_ref,
                metadata=_prompt_assembly_metadata_from_runtime_assembly(assembly_payload),
            )
        )
        _validate_runtime_prompt_ref_assembly(
            assembly,
            invocation_kind=invocation_kind,
            requested_refs=prompt_refs,
        )
        return assembly

    def _assemble_environment_prompt_layers(
        self,
        *,
        prompt_mount_plan: Any,
        agent_profile_ref: str,
        assembly_payload: dict[str, Any] | None = None,
    ) -> tuple[PromptAssemblyResult, PromptAssemblyResult]:
        base_environment_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=tuple(prompt_mount_plan.base_prompt_refs or ()),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(prompt_mount_plan.base_environment_id or ""),
            assembly_payload=assembly_payload,
        )
        overlay_environment_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=tuple(prompt_mount_plan.overlay_prompt_refs or ()),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(prompt_mount_plan.selected_environment_id or ""),
            assembly_payload=assembly_payload,
        )
        environment_prompt_assembly = _merge_prompt_assemblies(
            base_environment_prompt_assembly,
            overlay_environment_prompt_assembly,
            invocation_kind="environment",
        )
        environment_guidance_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=tuple(prompt_mount_plan.environment_guidance_prompt_refs or ()),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(prompt_mount_plan.selected_environment_id or ""),
            assembly_payload=assembly_payload,
        )
        return environment_prompt_assembly, environment_guidance_prompt_assembly

    def _assemble_personality_prompt_layer(
        self,
        *,
        prompt_mount_plan: Any,
        invocation_kind: str,
        agent_profile_ref: str,
        task_environment_ref: str,
        assembly_payload: dict[str, Any] | None = None,
    ) -> PromptAssemblyResult:
        return self._assemble_prompt_refs(
            invocation_kind=invocation_kind,
            prompt_refs=tuple(getattr(prompt_mount_plan, "personality_prompt_refs", ()) or ()),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            assembly_payload=assembly_payload,
        )


def _prompt_assembly_metadata_from_runtime_assembly(assembly_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(assembly_payload or {})
    system_wiring_manifest = _system_wiring_manifest_from_runtime_assembly(payload)
    context_capability_profile = _context_capability_profile_from_runtime_assembly(payload)
    if not system_wiring_manifest and not context_capability_profile:
        return {}
    return {
        "runtime_assembly_id": str(payload.get("assembly_id") or ""),
        "system_wiring_manifest": system_wiring_manifest,
        "context_capability_profile": context_capability_profile,
        "authority": "harness.runtime.compiler.prompt_assembly_metadata",
    }


def _system_wiring_manifest_from_runtime_assembly(assembly_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(assembly_payload or {})
    manifest = payload.get("system_wiring_manifest")
    if isinstance(manifest, dict) and manifest:
        return dict(manifest)
    diagnostics = dict(payload.get("diagnostics") or {})
    manifest = diagnostics.get("system_wiring_manifest")
    return dict(manifest) if isinstance(manifest, dict) else {}

def _context_capability_profile_from_runtime_assembly(assembly_payload: dict[str, Any] | None) -> dict[str, Any]:
    system_wiring_manifest = _system_wiring_manifest_from_runtime_assembly(assembly_payload)
    compiled = dict(system_wiring_manifest.get("compiled") or {})
    profile = compiled.get("context_capability_profile")
    return dict(profile) if isinstance(profile, dict) else {}


def _validate_runtime_prompt_pack_assembly(
    assembly: PromptAssemblyResult,
    *,
    invocation_kind: str,
    requested_refs: tuple[str, ...],
) -> None:
    if not tuple(requested_refs or ()):
        return
    rejected_refs = tuple(dict(item) for item in tuple(assembly.rejected_refs or ()))
    if rejected_refs:
        rejected = ", ".join(
            f"{item.get('ref', '')}:{item.get('reason', '')}" for item in rejected_refs
        )
        raise ValueError(
            "runtime prompt pack assembly rejected refs: "
            f"invocation_kind={invocation_kind} refs={rejected}"
        )
    _validate_prompt_rule_diagnostics(assembly, invocation_kind=invocation_kind)
    if not str(assembly.content or "").strip():
        raise ValueError(
            "runtime prompt pack assembly produced empty content: "
            f"invocation_kind={invocation_kind} refs={','.join(requested_refs)}"
        )


def _validate_runtime_prompt_ref_assembly(
    assembly: PromptAssemblyResult,
    *,
    invocation_kind: str,
    requested_refs: tuple[str, ...],
) -> None:
    if not tuple(requested_refs or ()):
        return
    rejected_refs = tuple(dict(item) for item in tuple(assembly.rejected_refs or ()))
    if rejected_refs:
        rejected = ", ".join(
            f"{item.get('ref', '')}:{item.get('reason', '')}" for item in rejected_refs
        )
        raise ValueError(
            "runtime prompt ref assembly rejected refs: "
            f"invocation_kind={invocation_kind} refs={rejected}"
        )
    _validate_prompt_rule_diagnostics(assembly, invocation_kind=invocation_kind)
    if not str(assembly.content or "").strip():
        raise ValueError(
            "runtime prompt ref assembly produced empty content: "
            f"invocation_kind={invocation_kind} refs={','.join(requested_refs)}"
        )


def _validate_prompt_rule_diagnostics(assembly: PromptAssemblyResult, *, invocation_kind: str) -> None:
    prompt_rules = dict(assembly.manifest.get("prompt_rules") or {})
    rejected_rules = [dict(item) for item in list(prompt_rules.get("rejected_rules") or []) if isinstance(item, dict)]
    if not rejected_rules:
        return
    rejected = ", ".join(
        f"{item.get('ref', '')}:{item.get('reason', '')}" for item in rejected_rules
    )
    raise ValueError(
        "runtime prompt rule assembly rejected refs: "
        f"invocation_kind={invocation_kind} refs={rejected}"
    )


def model_action_request_schema(turn_id: str) -> dict[str, Any]:
    del turn_id
    return turn_action_request_contract_payload()

def _current_work_boundary_receipt_model_visible_payload(receipt: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(receipt or {})
    if not payload:
        return {}
    decision = dict(dict(payload.get("diagnostics") or {}).get("decision") or {})
    operations = current_work_operation_availability_from_receipt(payload)
    boundary_decision = str(payload.get("boundary_decision") or "")
    active_work_ref = dict(payload.get("active_work_ref") or {})
    if boundary_decision in {"", "no_current_work"} and not bool(operations.get("active_work_control") is True):
        active_work_ref = {}
    return _drop_empty_payload(
        {
            "boundary_decision": boundary_decision,
            "observation_state": str(payload.get("observation_state") or ""),
            "operation_availability": operations,
            "active_work": _active_work_ref_model_visible_payload(active_work_ref),
            "read_only_context": not bool(operations.get("active_work_control") is True),
            "state_reason": str(payload.get("state_reason") or ""),
            "reason": str(decision.get("reason") or ""),
            "relation_to_current_work": str(decision.get("relation_to_current_work") or ""),
        }
    )


def _active_work_ref_model_visible_payload(value: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(value or {})
    if not payload:
        return {}
    return _drop_empty_payload(
        {
            "work_ref": str(
                payload.get("work_ref")
                or payload.get("task_ref")
                or payload.get("task_run_ref")
                or payload.get("task_run_id")
                or ""
            ),
            "state": str(payload.get("state") or payload.get("status") or ""),
            "user_visible_goal": str(payload.get("user_visible_goal") or ""),
            "latest_progress": str(payload.get("latest_progress") or ""),
            "relation_to_current_request": str(payload.get("relation_to_current_request") or ""),
        }
    )


def _turn_memory_recovery_model_visible_payload(
    context: dict[str, Any] | None,
    *,
    current_user_message: str = "",
) -> dict[str, Any]:
    payload = dict(context or {})
    if not payload:
        return {}
    if str(payload.get("authority") or "") != "runtime.turn_memory.recovery_context":
        return {}
    decision = dict(payload.get("recovery_decision") or {})
    if not bool(decision.get("recoverable") is True):
        return {}
    decision_payload = dict(decision.get("payload") or {})
    current_context = dict(payload.get("current_turn_context") or {})
    handoff_context = dict(payload.get("handoff_context") or {})
    pending_commit_summary = dict(
        payload.get("pending_commit_summary")
        or decision_payload.get("pending_commit_summary")
        or {}
    )
    pending_tool_summary = dict(
        payload.get("pending_tool_summary")
        or decision_payload.get("pending_tool_summary")
        or {}
    )
    action = str(decision.get("action") or "")
    return _drop_empty_payload(
        {
            "authority": "harness.compiler.work_state_repair_context",
            "state": "work_state_repair_context",
            "branch_id": str(payload.get("branch_id") or ""),
            "status": str(payload.get("status") or ""),
            "phase": str(payload.get("phase") or ""),
            "repair_state": str(payload.get("recovery_state") or ""),
            "repair_decision": _drop_empty_payload(
                {
                    "action": action,
                    "reason": str(decision.get("reason") or ""),
                    "commit_state": str(decision.get("commit_state") or ""),
                    "repairable": True,
                }
            ),
            "current_user_request": _compact_text(current_user_message, limit=4000),
            "work_refs": _drop_empty_payload(
                {
                    "current_user_message_ref": str(current_context.get("current_user_message_ref") or ""),
                    "physical_prefix_frame_id": str(payload.get("physical_prefix_frame_id") or handoff_context.get("physical_prefix_frame_id") or ""),
                    "provider_request_refs": list(payload.get("provider_request_refs") or [])[-8:],
                    "provider_payload_manifest_refs": list(payload.get("provider_payload_manifest_refs") or [])[-8:],
                    "closed_tool_round_refs": list(payload.get("closed_tool_round_refs") or handoff_context.get("closed_tool_round_refs") or [])[-8:],
                    "active_steer_refs": list(payload.get("active_steer_refs") or handoff_context.get("active_steer_refs") or [])[-8:],
                    "assistant_draft_ref": str(payload.get("assistant_draft_ref") or decision_payload.get("assistant_draft_ref") or ""),
                    "assistant_draft_sha256": str(payload.get("assistant_draft_sha256") or decision_payload.get("assistant_draft_sha256") or ""),
                    "assistant_final_ref": str(payload.get("assistant_final_ref") or decision_payload.get("assistant_final_ref") or ""),
                    "assistant_final_sha256": str(payload.get("assistant_final_sha256") or decision_payload.get("assistant_final_sha256") or ""),
                    "frame_promotion_ref": str(payload.get("frame_promotion_ref") or decision_payload.get("frame_promotion_ref") or ""),
                    "current_append_hash": str(payload.get("current_append_hash") or ""),
                }
            ),
            "pending_summaries": _drop_empty_payload(
                {
                    "tool": pending_tool_summary,
                    "commit": pending_commit_summary,
                }
            ),
            "followup_contract": [
                "Treat these work-state facts as a repair boundary, not as a new user goal.",
                "If repair_decision.action is retry_commit or retry_frame_promotion, do not regenerate an assistant final that already exists; preserve the recorded final refs and let the system close the missing boundary.",
                "Do not treat this payload as permission to continue an old execution; use it only to repair or explain the current state.",
            ],
            "allowed_followup_posture": "work_state_repair",
            "forbidden_action": "continue_closed_work",
            "read_only_context": False,
        }
    )


def _prior_work_memory_model_visible_payload(
    context: dict[str, Any] | None,
    *,
    current_user_message: str = "",
) -> dict[str, Any]:
    payload = dict(context or {})
    if not payload:
        return {}
    if str(payload.get("authority") or "") != "runtime.turn_memory.prior_work_context":
        return {}
    current_context = dict(payload.get("current_turn_context") or {})
    handoff_context = dict(payload.get("handoff_context") or {})
    pending_commit_summary = dict(payload.get("pending_commit_summary") or {})
    pending_tool_summary = dict(payload.get("pending_tool_summary") or {})
    closure_summary = _agent_visible_work_closure_summary(
        payload.get("interruption"),
        pending_commit_summary,
    )
    interruption = dict(payload.get("interruption") or {}) if isinstance(payload.get("interruption"), dict) else {}
    previous_work_ref = _previous_incomplete_output_work_ref(payload)
    memory_refs = _drop_empty_payload(
        {
            "current_user_message_ref": str(current_context.get("current_user_message_ref") or ""),
            "physical_prefix_frame_id": str(payload.get("physical_prefix_frame_id") or handoff_context.get("physical_prefix_frame_id") or ""),
            "provider_request_refs": list(payload.get("provider_request_refs") or [])[-8:],
            "provider_payload_manifest_refs": list(payload.get("provider_payload_manifest_refs") or [])[-8:],
            "closed_tool_round_refs": list(payload.get("closed_tool_round_refs") or handoff_context.get("closed_tool_round_refs") or [])[-8:],
            "active_steer_refs": list(payload.get("active_steer_refs") or handoff_context.get("active_steer_refs") or [])[-8:],
            "assistant_draft_ref": str(payload.get("assistant_draft_ref") or ""),
            "assistant_draft_sha256": str(payload.get("assistant_draft_sha256") or ""),
            "current_append_hash": str(payload.get("current_append_hash") or ""),
        }
    )
    state_signal_evidence = _previous_incomplete_output_state_signal_evidence(
        payload,
        previous_work_ref=previous_work_ref,
        interruption=interruption,
        closure_summary=closure_summary,
        memory_refs=memory_refs,
    )
    return _drop_empty_payload(
        {
            "authority": "harness.compiler.previous_incomplete_output_memory",
            "memory_type": "previous_incomplete_output_memory",
            "source": "previous_interrupted_work_output_hot_cache",
            "branch_id": str(payload.get("branch_id") or ""),
            "previous_work_ref": previous_work_ref,
            "work_state": _drop_empty_payload(
                {
                    "status": str(payload.get("status") or ""),
                    "phase": str(payload.get("phase") or ""),
                    "closure": closure_summary,
                }
            ),
            "state_signal_evidence": state_signal_evidence,
            "closure": closure_summary,
            "memory_refs": memory_refs,
            "memory_summaries": _drop_empty_payload(
                {
                    "tool": pending_tool_summary,
                    "closure": closure_summary,
                }
            ),
            "completion_state": "incomplete_previous_output",
        }
    )


def _previous_incomplete_output_memory_message_spec(
    payload: dict[str, Any] | None,
    *,
    validity_scope: str,
) -> dict[str, Any] | None:
    memory_payload = _drop_empty_payload(dict(payload or {}))
    if not memory_payload:
        return None
    source_ref = _previous_incomplete_output_memory_source_ref(memory_payload)
    wrapped_payload = {
        "previous_incomplete_work_context": memory_payload,
    }
    return _runtime_payload_spec(
        role="system",
        title="Previous incomplete work context",
        payload=wrapped_payload,
        kind="previous_incomplete_output_memory",
        visible_kind="previous_incomplete_output_memory",
        source_ref=source_ref,
        cache_scope="none",
        cache_role="volatile",
        compression_role="summarize",
        metadata={
            **_current_append_fact_metadata(
                kind="previous_incomplete_output_memory",
                payload=wrapped_payload,
                semantic_slot="previous_incomplete_output_memory",
                semantic_rank=12,
                origin_ref=source_ref,
                package="previous_incomplete_output_memory",
                stream="previous_incomplete_output_memory",
                semantic_commit_class="previous_incomplete_output_memory",
            ),
            "content_source": "runtime.turn_memory.output_hot_cache",
            "state_signal_evidence": dict(memory_payload.get("state_signal_evidence") or {}),
            "stability_rule": (
                "Previous incomplete output memory is a current request fact derived from output hot cache. "
                "It may be sealed only after this provider request succeeds; guidance stays in the dynamic tail."
            ),
        },
    )


def _previous_incomplete_output_guidance_message_spec(
    payload: dict[str, Any] | None,
    *,
    validity_scope: str,
) -> dict[str, Any] | None:
    memory_payload = _drop_empty_payload(dict(payload or {}))
    if not memory_payload:
        return None
    source_ref = _previous_incomplete_output_memory_source_ref(memory_payload) + ":guidance"
    guidance = _previous_incomplete_output_guidance_content(memory_payload)
    if not guidance.strip():
        return None
    return _message_spec(
        role="system",
        content=_runtime_control_context_content(
            guidance,
            validity_scope=validity_scope,
            source_ref=source_ref,
            include_notice=False,
        ),
        kind="previous_incomplete_output_guidance",
        source_ref=source_ref,
        cache_scope="none",
        cache_role="volatile",
        compression_role="preserve",
        metadata=_current_runtime_tail_metadata(
            {
                "content_source": "harness.runtime.compiler.previous_incomplete_output_guidance",
                "state_signal_ref": str(dict(memory_payload.get("state_signal_evidence") or {}).get("signal_ref") or ""),
                "volatility_reason": "guidance explains the current state signal for this request only",
            },
            semantic_slot="turn_state_guidance",
            validity_scope=validity_scope,
        ),
    )


def _previous_incomplete_output_guidance_content(payload: dict[str, Any]) -> str:
    signal = dict(dict(payload or {}).get("state_signal_evidence") or {})
    if str(signal.get("signal_type") or "") != "previous_output_interrupted":
        return ""
    return "\n".join(
        (
            "上一段工作被中断。你会收到一段上一段未完成工作的记忆，它只是一份当前请求可用的背景证据。",
            "这些内容可能包含已完成的工具观察、临时草稿、尚未收尾的判断和约束。",
            "请把它作为当前请求的背景证据继续判断，不要假设它已经是最终结论；如果当前用户指令改变方向，以当前用户指令为准。",
        )
    )


def _previous_incomplete_output_state_signal_evidence(
    payload: dict[str, Any],
    *,
    previous_work_ref: str,
    interruption: dict[str, Any],
    closure_summary: dict[str, Any],
    memory_refs: dict[str, Any],
) -> dict[str, Any]:
    reason_class = str(dict(closure_summary or {}).get("reason") or "")
    event_id = str(dict(interruption or {}).get("event_id") or "").strip()
    event_offset = dict(interruption or {}).get("event_offset")
    seed = {
        "signal_type": "previous_output_interrupted",
        "previous_work_ref": previous_work_ref,
        "event_id": event_id,
        "event_offset": event_offset,
        "current_append_hash": str(dict(memory_refs or {}).get("current_append_hash") or ""),
    }
    return _drop_empty_payload(
        {
            "signal_type": "previous_output_interrupted",
            "signal_ref": "statesignal:" + _stable_json_hash(seed).removeprefix("sha256:")[:16],
            "evidence_source": "runtime.output_hot_cache",
            "previous_work_ref": previous_work_ref,
            "interruption": _drop_empty_payload(
                {
                    "reason_class": reason_class,
                    "event_ref": event_id,
                    "event_offset": event_offset,
                }
            ),
            "memory_ref_summary": _drop_empty_payload(
                {
                    "provider_request_ref_count": len(list(dict(memory_refs or {}).get("provider_request_refs") or [])),
                    "provider_payload_manifest_ref_count": len(list(dict(memory_refs or {}).get("provider_payload_manifest_refs") or [])),
                    "closed_tool_round_ref_count": len(list(dict(memory_refs or {}).get("closed_tool_round_refs") or [])),
                    "assistant_draft_ref": str(dict(memory_refs or {}).get("assistant_draft_ref") or ""),
                    "current_append_hash": str(dict(memory_refs or {}).get("current_append_hash") or ""),
                }
            ),
            "authority": "harness.compiler.previous_incomplete_output_memory.state_signal_evidence",
        }
    )


def _previous_incomplete_output_work_ref(payload: dict[str, Any]) -> str:
    return _first_runtime_text(
        payload.get("turn_run_id"),
        payload.get("previous_turn_id"),
        payload.get("current_append_hash"),
        "previous_incomplete_output",
    )


def _previous_incomplete_output_memory_source_ref(payload: dict[str, Any]) -> str:
    signal = dict(dict(payload or {}).get("state_signal_evidence") or {})
    explicit = str(signal.get("signal_ref") or "").strip()
    if explicit:
        return f"previous_incomplete_output_memory:{explicit}"
    seed = {
        "previous_work_ref": str(dict(payload or {}).get("previous_work_ref") or ""),
        "memory_refs": dict(dict(payload or {}).get("memory_refs") or {}),
    }
    return "previous_incomplete_output_memory:" + _stable_json_hash(seed).removeprefix("sha256:")[:16]


def _agent_visible_work_closure_summary(interruption: Any, pending_commit_summary: dict[str, Any]) -> dict[str, Any]:
    interruption_payload = dict(interruption or {}) if isinstance(interruption, dict) else {}
    raw_code = _first_runtime_text(
        interruption_payload.get("code"),
        pending_commit_summary.get("runtime_interruption_code"),
    )
    raw_reason = _first_runtime_text(
        interruption_payload.get("reason"),
        pending_commit_summary.get("runtime_interruption_reason"),
    )
    return _drop_empty_payload(
        {
            "state": "interrupted_and_closed",
            "reason": _agent_visible_work_interruption_reason(raw_code, raw_reason),
        }
    )


def _agent_visible_work_interruption_reason(code: Any, reason: Any) -> str:
    normalized_code = str(code or "").strip().lower()
    if normalized_code in {
        "runtime_process_restarted",
        "runtime_cell_missing_after_restart",
        "runtime_cell_cancelled",
    }:
        return "connection_or_process_interruption"
    if normalized_code in {"stream_cancelled"}:
        return "stream_cancelled"
    if normalized_code in {"stream_exception", "projection_stream_exception"}:
        return "stream_interrupted"
    if normalized_code in {"missing_terminal_event", "projection_stream_missing_terminal"}:
        return "closed_without_normal_finish_signal"
    raw_reason = str(reason or "").strip()
    lowered = raw_reason.lower()
    if not raw_reason or "runtime" in lowered or "turn" in lowered:
        return "work_interrupted"
    return _compact_text(raw_reason, limit=240)


def _agent_contract_feedback_model_visible_payload(value: Any) -> dict[str, Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    if not payload:
        return {}
    requirements = dict(payload.get("next_action_requirements") or {})
    failure = dict(payload.get("contract_failure") or {})
    structured_signal = dict(payload.get("structured_signal") or {})
    feedback_contract = _feedback_contract_model_visible_payload(payload.get("feedback_contract"))
    specific_feedback = [
        _drop_empty_payload(
            {
                "situation_feedback": _compact_text(item.get("situation_feedback"), limit=1200),
                "repair_instruction": _compact_text(item.get("repair_instruction"), limit=1200),
                "expected_next_action": _compact_text(item.get("expected_next_action"), limit=1200),
            }
        )
        for item in list(failure.get("specific_feedback") or [])
        if isinstance(item, dict)
    ]
    return _drop_empty_payload(
        {
            "situation": "上一轮输出没有形成可执行、可发布的下一步动作。",
            "phase": str(payload.get("phase") or ""),
            "public_feedback_obligation": "respond_with_public_judgment_now",
            "system_handling_of_missing_feedback": "record_contract_gap_only",
            "tool_action_available": payload.get("tool_calls_allowed_after_signal"),
            "feedback_contract": feedback_contract,
            "agent_feedback": _compact_text(payload.get("agent_feedback"), limit=3000),
            "next_action_requirements": _drop_empty_payload(
                {
                    "allowed_action_types": [
                        str(item)
                        for item in list(requirements.get("allowed_action_types") or [])
                        if str(item or "").strip()
                    ],
                    "tool_call_allowed": requirements.get("tool_call_allowed"),
                    "one_action_only": requirements.get("one_action_only") if "one_action_only" in requirements else requirements.get("structured_action_required"),
                    "visible_response_fields": [
                        str(item)
                        for item in list(requirements.get("visible_response_fields") or ["final_answer", "user_question", "blocking_reason"])
                        if str(item or "").strip()
                    ],
                }
            ),
            "contract_failure": _drop_empty_payload(
                {
                    "closeout_attempts": failure.get("closeout_attempts"),
                    "phase": str(failure.get("phase") or ""),
                    "facts": dict(failure.get("facts") or {}),
                    "specific_feedback": specific_feedback,
                }
            ),
            "observed_facts": dict(payload.get("observed_facts") or {}),
            "structured_signal": _drop_empty_payload(
                {
                    "message": _compact_text(structured_signal.get("message"), limit=3000),
                    "retryable": structured_signal.get("retryable"),
                }
            ),
        }
    )


def _feedback_contract_model_visible_payload(value: Any) -> dict[str, Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    if not payload:
        return {}
    return _drop_empty_payload(
        {
            "source": str(payload.get("source") or ""),
            "situation": _compact_text(payload.get("situation"), limit=400),
            "your_task": _compact_text(payload.get("your_task"), limit=600),
            "public_feedback_obligation": (
                payload.get("public_feedback_obligation")
                or (
                    "respond_with_public_judgment_now"
                    if payload.get("public_feedback_recommended")
                    else ""
                )
            ),
            "system_handling_of_missing_feedback": (
                payload.get("system_handling_of_missing_feedback")
                or ("record_contract_gap_only" if payload.get("public_feedback_recommended") else "")
            ),
            "tool_action_available": payload.get("tool_action_available"),
            "available_actions": [
                str(item)
                for item in list(payload.get("available_actions") or [])
                if str(item or "").strip()
            ],
            "response_slots": [
                str(item)
                for item in list(payload.get("response_slots") or [])
                if str(item or "").strip()
            ],
            "tool_result_feedback": _compact_text(payload.get("tool_result_feedback"), limit=600),
        }
    )


def _recovery_packet_model_visible_payload(packet: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(packet or {})
    if not payload:
        return {}
    return _drop_empty_payload(
        {
            "resume_ref": str(payload.get("continuation_id") or ""),
            "work_ref": str(payload.get("task_run_id") or ""),
            "resume_intent": str(payload.get("resume_intent") or ""),
            "user_resume_instruction": _compact_text(payload.get("user_resume_instruction") or "", limit=4000),
            "user_visible_goal": str(payload.get("user_visible_goal") or ""),
            "confirmed_progress": [
                str(item)
                for item in list(payload.get("confirmed_progress") or [])
                if str(item or "").strip()
            ][:5],
            "interruption_summary": str(payload.get("interruption_summary") or ""),
            "next_step_contract": str(payload.get("next_step_contract") or ""),
            "artifact_refs": [dict(item) for item in list(payload.get("artifact_refs") or []) if isinstance(item, dict)][:8],
            "resume_constraints": [
                str(item)
                for item in list(payload.get("resume_constraints") or [])
                if str(item or "").strip()
            ][:8],
            "forbidden_actions": [
                str(item)
                for item in list(payload.get("forbidden_actions") or [])
                if str(item or "").strip()
            ][:8],
            "model_instruction": str(payload.get("model_instruction") or ""),
        }
    )


def _runtime_observations_model_visible_payload(value: Any) -> dict[str, Any]:
    raw_items = list(value or []) if isinstance(value, (list, tuple)) else ([value] if isinstance(value, dict) else [])
    observations: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        payload = dict(raw)
        payload_payload = dict(payload.get("payload") or {})
        feedback_contract = _feedback_contract_model_visible_payload(
            payload.get("feedback_contract") or payload_payload.get("feedback_contract")
        )
        envelope = dict(payload_payload.get("result_envelope") or {})
        structured = dict(payload_payload.get("structured_payload") or envelope.get("structured_payload") or {})
        structured_error = (
            dict(structured.get("structured_error") or {})
            if isinstance(structured.get("structured_error"), dict)
            else dict(payload_payload.get("structured_error") or {})
            if isinstance(payload_payload.get("structured_error"), dict)
            else {}
        )
        observations.append(
            _drop_empty_payload(
                {
                    "observation_id": str(payload.get("observation_id") or ""),
                    "observation_type": str(payload.get("observation_type") or ""),
                    "source": str(payload.get("source") or ""),
                    "status": str(payload.get("status") or ""),
                    "error_code": str(payload.get("error_code") or payload_payload.get("error_code") or structured_error.get("code") or ""),
                    "summary": str(payload.get("summary") or payload_payload.get("error") or envelope.get("text") or ""),
                    "contract_errors": list(payload_payload.get("contract_errors") or []),
                    "repair_instruction": str(payload_payload.get("repair_instruction") or structured_error.get("repair_instruction") or ""),
                    "feedback_contract": feedback_contract,
                    "structured_error": _drop_empty_payload(
                        {
                            "code": str(structured_error.get("code") or ""),
                            "message": str(structured_error.get("message") or ""),
                            "origin": str(structured_error.get("origin") or ""),
                            "repair_instruction": str(structured_error.get("repair_instruction") or ""),
                            "expected_ref_type": str(structured_error.get("expected_ref_type") or ""),
                            "expected_prefix": str(structured_error.get("expected_prefix") or ""),
                            "received_ref_type": str(structured_error.get("received_ref_type") or ""),
                        }
                    ),
                    "needs_model_followup": bool(payload.get("needs_model_followup") is True),
                }
            )
        )
    if not observations:
        return {}
    return {
        "observations": observations,
        "boundary_code": "agent_addressed_work_observations",
    }


def _prompt_output_contract_payload(output_contract: dict[str, Any]) -> dict[str, Any]:
    payload = dict(output_contract or {})
    payload.pop("planning_protocol", None)
    return _drop_empty_payload(payload)


def _single_agent_turn_current_operating_contract_payload(
    *,
    control_capabilities: dict[str, Any],
    turn_operating_contract: dict[str, Any],
    output_contract: dict[str, Any],
    capability_directory: dict[str, Any],
) -> dict[str, Any]:
    return _drop_empty_payload(
        {
            "control_capabilities": dict(control_capabilities or {}),
            "current_action_contract": dict(turn_operating_contract or {}),
            "output_contract": dict(output_contract or {}),
            "capability_routing": _capability_routing_payload(capability_directory),
        }
    )


def _single_agent_turn_output_contract(
    *,
    allowed_actions: tuple[str, ...],
    control_capabilities: dict[str, Any],
    planning_protocol: dict[str, Any] | None = None,
    phase: str = "initial_decision",
) -> dict[str, Any]:
    return turn_output_contract_payload(
        allowed_actions=allowed_actions,
        control_capabilities=control_capabilities,
        planning_protocol=planning_protocol,
        phase=phase,
    )

def _active_work_model_visible_payload(
    active_work_context: dict[str, Any] | None,
    *,
    controls_enabled: bool = False,
) -> dict[str, Any]:
    context = dict(active_work_context or {})
    if not context:
        return {}
    controls = [
        "pause_active_work",
        "stop_active_work",
        "append_instruction_to_active_work",
        "answer_about_active_work",
    ] if controls_enabled else []
    payload = _drop_empty_payload(
        {
            "status": str(context.get("status") or ""),
            "control_state": str(context.get("control_state") or ""),
            "user_visible_goal": str(context.get("user_visible_goal") or ""),
            "latest_progress": str(context.get("latest_progress") or ""),
            "latest_step_name": str(context.get("latest_step_name") or ""),
            "resumable": bool(context.get("resumable") is True),
            "running": bool(context.get("running") is True),
            "paused": bool(context.get("paused") is True),
            "queued_user_instruction_count": _safe_int(context.get("queued_user_instruction_count")),
            "continuation_kind": str(context.get("continuation_kind") or ""),
            "available_controls": controls,
            "read_only_context": not controls_enabled,
            "control_availability": (
                "current_work_boundary_receipt_active_work_control_available"
                if controls_enabled
                else "current_work_boundary_receipt_active_work_control_unavailable"
            ),
        }
    )
    if not controls_enabled:
        payload["available_controls"] = []
    return payload


def _turn_input_facts_model_visible_payload(facts: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(facts or {})
    if not payload:
        return {}
    active_turn = dict(payload.get("active_turn") or {})
    return _drop_empty_payload(
        {
            "current_work_input_policy": str(payload.get("active_turn_input_policy") or ""),
            "recovery_input_policy": str(payload.get("recovery_input_policy") or ""),
            "current_work_present": bool(active_turn),
            "current_work_state": str(active_turn.get("state") or ""),
            "active_work_candidate_present": bool(payload.get("active_work_candidate")),
            "recent_work_outcome_candidate_present": bool(payload.get("recent_work_outcome_candidate")),
        }
    )


def _current_turn_delta_model_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(payload or {})
    user_message = str(current.pop("user_message", "") or "")
    current.pop("runtime_envelope", None)
    current.pop("turn_id", None)
    allowed_context_keys = (
        "attachment_context_index",
        "editor_context_index",
        "observations",
    )
    return _drop_empty_payload(
        {
            "user_message": user_message,
            **{
                key: current.get(key)
                for key in allowed_context_keys
                if current.get(key) not in ("", None, [], {})
            },
        }
    )


def _provider_protocol_message_specs(
    session_context: dict[str, Any] | None,
    *,
    source_ref: str,
    projection_policy: dict[str, Any] | None = None,
    storage_root: Path | None = None,
    storage_run_id: str = "",
) -> list[dict[str, Any]]:
    payload = dict(session_context or {})
    context_recovery_package_present = bool(_context_recovery_package_payload(payload))
    compaction_boundary_created_at = _safe_float(payload.get("provider_protocol_compaction_created_at"))
    if context_recovery_package_present and compaction_boundary_created_at <= 0:
        return []
    transcript_candidates = [
        dict(item)
        for item in list(payload.get("provider_protocol_timeline") or [])
        if isinstance(item, dict)
    ]
    boundary_filtered_candidates = _provider_protocol_after_compaction_boundary(
        transcript_candidates,
        boundary_created_at=compaction_boundary_created_at,
    )
    raw_transcript = [
        dict(item)
        for item in provider_message_payloads(boundary_filtered_candidates)
        if isinstance(item, dict)
    ]
    protocol_transcript = _provider_protocol_hot_messages(raw_transcript)
    if not protocol_transcript:
        return []
    transcript = [dict(item) for item in protocol_transcript]
    protocol_created_ats = _provider_protocol_created_ats(transcript, boundary_filtered_candidates)
    protocol_projection = {
        "authority": "harness.runtime.compiler.provider_protocol_projection",
        "projection_strategy": "full_append_only_protocol_append_candidate",
        "input_message_count": len(protocol_transcript),
        "append_candidate_message_count": len(transcript),
        "omitted_message_count": 0,
        "input_chars": _provider_protocol_messages_chars(protocol_transcript),
        "output_chars": _provider_protocol_messages_chars(transcript),
    }
    protocol_truncated_count = 0
    protocol_projection = {
        **dict(protocol_projection or {}),
        "raw_transcript_message_count": len(raw_transcript),
        "raw_transcript_input_message_count": len(transcript_candidates),
        "protocol_projection_strategy": "provider_payload_append_candidate_byte_preservation",
        "protocol_sanitizer_boundary": "provider_protocol_append_candidate_byte_preservation",
        "compaction_boundary_created_at": compaction_boundary_created_at,
        "compaction_boundary_omitted_message_count": max(0, len(transcript_candidates) - len(boundary_filtered_candidates)),
        "hot_protocol_message_count": len(protocol_transcript),
        "non_protocol_message_count": max(0, len(raw_transcript) - len(protocol_transcript)),
    }
    result: list[dict[str, Any]] = []
    for index, message in enumerate([item for item in transcript if item is not None], start=1):
        append_only_created_at = protocol_created_ats[index - 1] if index - 1 < len(protocol_created_ats) else 0.0
        append_only_item_key = _provider_protocol_append_item_key(
            message,
            source_ref=source_ref,
            index=index,
            append_only_created_at=append_only_created_at,
            compaction_boundary_created_at=compaction_boundary_created_at,
        )
        result.append(
            {
                "role": str(message.get("role") or "user"),
                "content": str(message.get("content") or ""),
                "kind": "provider_protocol_history",
                "source_ref": f"{source_ref}:{index}",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "compression_role": "preserve",
                "metadata": {
                    "context_cache_section": CONTEXT_APPEND,
                    "context_commit_policy": "append_then_seal",
                    "context_replay_policy": PROVIDER_PROTOCOL_APPEND_POLICY,
                    "context_identity_policy": "origin_ref_stable",
                    "context_origin_authority": "harness.runtime.compiler.provider_protocol_projection",
                    "context_origin_ref": append_only_item_key,
                    "append_only_context_item_key": append_only_item_key,
                    "protocol_history_index": index,
                    "provider_protocol_append_candidate": True,
                    "provider_message_append_authority": PROVIDER_PROTOCOL_APPEND_AUTHORITY,
                    "provider_visible_history_status": PROVIDER_PROTOCOL_APPEND_STATUS,
                    "protocol_truncated_count": protocol_truncated_count,
                    "protocol_sanitizer": {
                        "status": "provider_protocol_append_candidate_byte_preserved",
                        "reason": "provider protocol history is an append candidate and must preserve provider-visible bytes",
                        "authority": "harness.runtime.compiler.provider_protocol_projection",
                    },
                    "protocol_projection": dict(protocol_projection),
                    "reasoning_content_present": bool(message.get("reasoning_content")),
                    "tool_calls_present": bool(message.get("tool_calls")),
                    "exact_content_required_before_final": _provider_protocol_requires_rehydration(message),
                    "content_source": "runtime.provider_protocol_append_candidate",
                    "cache_impact": "append_only_provider_visible_append_candidate",
                    "volatility_reason": (
                        "provider protocol append candidates are materialized in the current request; "
                        "provider success and the physical prefix frame decide their later cache placement"
                    ),
                    "stability_rule": "provider protocol transcript is historical context; new protocol messages append after old ones and provider success promotes confirmed candidates into the next physical prefix frame",
                    "append_only_context_package": "historical_context",
                    "append_only_context_stream": "provider_protocol",
                    "append_only_created_at": append_only_created_at,
                    "append_only_stream_index": index,
                },
                "model_message": message,
            }
        )
    result, _tool_round_diagnostics = annotate_provider_tool_round_specs(
        result,
        source="compiler_provider_protocol_history",
    )
    return result


def _provider_protocol_after_compaction_boundary(
    transcript: list[dict[str, Any]],
    *,
    boundary_created_at: float,
) -> list[dict[str, Any]]:
    if boundary_created_at <= 0:
        return list(transcript or [])
    return [
        dict(message)
        for message in list(transcript or [])
        if _safe_float(message.get("created_at") or message.get("updated_at") or message.get("timestamp")) >= boundary_created_at
    ]


def _provider_protocol_hot_messages(transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages = [dict(item) for item in list(transcript or []) if isinstance(item, dict)]
    result: list[dict[str, Any]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        role = str(message.get("role") or "").strip()
        if role == "user":
            if _provider_protocol_message_has_content(message):
                result.append(message)
            index += 1
            continue
        if role != "assistant":
            index += 1
            continue
        tool_call_ids = _assistant_tool_call_id_list(message)
        if not tool_call_ids:
            if _provider_protocol_message_has_content(message) or _explicit_provider_text(message.get("reasoning_content")):
                result.append(message)
            index += 1
            continue
        if _assistant_has_control_protocol_tool_call(message):
            index += 1
            continue
        expected = list(tool_call_ids)
        if len(expected) != len(set(expected)):
            index += 1
            continue
        expected_set = set(expected)
        tool_messages: list[dict[str, Any]] = []
        found: set[str] = set()
        cursor = index + 1
        while cursor < len(messages):
            candidate = messages[cursor]
            if str(candidate.get("role") or "").strip() != "tool":
                break
            tool_call_id = str(candidate.get("tool_call_id") or "").strip()
            if tool_call_id not in expected_set or tool_call_id in found:
                break
            tool_messages.append(candidate)
            found.add(tool_call_id)
            cursor += 1
        if expected_set.issubset(found):
            result.append(message)
            result.extend(tool_messages)
            index = cursor
            continue
        index += 1
    return result


def _provider_protocol_message_has_content(message: dict[str, Any]) -> bool:
    content = message.get("content")
    if content is None:
        return False
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return bool(content)
    return bool(str(content).strip())


_CONTROL_PROTOCOL_TOOL_CALL_NAMES = {
    "respond",
    "ask_user",
    "block",
    "request_task_run",
    "active_work_control",
    "resume_task_recovery",
    "pause_for_user_steer",
    "task_run_request",
}


def _provider_protocol_created_ats(
    transcript: list[dict[str, Any]],
    raw_candidates: list[dict[str, Any]],
) -> list[float]:
    created_ats: list[float] = []
    cursor = 0
    candidates = [dict(item) for item in list(raw_candidates or []) if isinstance(item, dict)]
    for message in list(transcript or []):
        created_at = 0.0
        for index in range(cursor, len(candidates)):
            candidate = candidates[index]
            if _same_provider_protocol_message(message, candidate):
                created_at = _message_created_at(candidate)
                cursor = index + 1
                break
        created_ats.append(created_at)
    return created_ats


def _same_provider_protocol_message(message: dict[str, Any], candidate: dict[str, Any]) -> bool:
    role = str(message.get("role") or "").strip()
    if role != str(candidate.get("role") or candidate.get("type") or "").strip():
        return False
    if role == "tool":
        return str(message.get("tool_call_id") or "").strip() == str(candidate.get("tool_call_id") or "").strip()
    message_tool_ids = _assistant_tool_call_ids(message)
    candidate_tool_ids = _assistant_tool_call_ids(candidate)
    if message_tool_ids or candidate_tool_ids:
        return bool(message_tool_ids) and message_tool_ids == candidate_tool_ids
    reasoning = _explicit_provider_text(message.get("reasoning_content"))
    if reasoning:
        return reasoning == _explicit_provider_text(candidate.get("reasoning_content"))
    content = str(message.get("content") or "").strip()
    return bool(content) and content == str(candidate.get("content") or candidate.get("text") or "").strip()


def _explicit_provider_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text if text != "" else ""


def _assistant_tool_call_ids(message: dict[str, Any]) -> set[str]:
    return set(_assistant_tool_call_id_list(message))


def _assistant_tool_call_id_list(message: dict[str, Any]) -> list[str]:
    if str(message.get("role") or "") != "assistant":
        return []
    tool_calls = list(message.get("tool_calls") or []) if isinstance(message.get("tool_calls"), list) else []
    return [
        str(call.get("id") or "").strip()
        for call in tool_calls
        if isinstance(call, dict) and str(call.get("id") or "").strip()
    ]


def _assistant_has_control_protocol_tool_call(message: dict[str, Any]) -> bool:
    if str(message.get("role") or "") != "assistant":
        return False
    tool_calls = list(message.get("tool_calls") or []) if isinstance(message.get("tool_calls"), list) else []
    return any(_is_control_protocol_tool_call_name(_provider_tool_call_name(call)) for call in tool_calls if isinstance(call, dict))


def _provider_tool_call_name(call: dict[str, Any]) -> str:
    payload = dict(call or {})
    function = payload.get("function") if isinstance(payload.get("function"), dict) else {}
    return str(payload.get("name") or function.get("name") or "").strip()


def _is_control_protocol_tool_call_name(name: str) -> bool:
    return str(name or "").strip().lower() in _CONTROL_PROTOCOL_TOOL_CALL_NAMES


def _provider_protocol_messages_chars(messages: list[dict[str, Any]]) -> int:
    return sum(_provider_protocol_message_chars(message) for message in messages)


def _provider_protocol_message_chars(message: dict[str, Any]) -> int:
    return len(json.dumps(_json_stable(message), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _provider_protocol_requires_rehydration(message: dict[str, Any]) -> bool:
    content = str(message.get("content") or "")
    if str(message.get("role") or "") != "tool":
        return False
    return "<persisted-output>" in content


def _provider_protocol_append_item_key(
    message: dict[str, Any],
    *,
    source_ref: str,
    index: int,
    append_only_created_at: float,
    compaction_boundary_created_at: float,
) -> str:
    return _stable_json_hash(
        {
            "schema": "provider_protocol_append_item_key",
            "source_ref": str(source_ref or ""),
            "stream": "provider_protocol",
            "index": int(index or 0),
            "created_at": float(append_only_created_at or 0.0),
            "compaction_boundary_created_at": float(compaction_boundary_created_at or 0.0),
            "provider_message_hash": _stable_json_hash(message),
        }
    )


def _model_messages_and_segment_plan(
    *,
    packet_id: str,
    invocation_kind: str,
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    collect_dynamic_context_metadata_diagnostics: bool = False,
    provider_visible_append_scope: str = "",
    provider_visible_context_inheritance: dict[str, Any] | None = None,
    compaction_generation: str = "",
    storage_root: Path | None = None,
    model_selection: dict[str, Any] | None = None,
    context_capability_profile: dict[str, Any] | None = None,
    system_wiring_manifest: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], Any, tuple[dict[str, Any], ...], Any, Any, Any]:
    source_specs: list[dict[str, Any]] = []
    for raw_spec in list(specs or []):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        model_message = _model_message_from_spec(spec)
        if not _has_model_message_payload(model_message):
            continue
        spec["role"] = str(model_message.get("role") or spec.get("role") or "user")
        spec["content"] = str(model_message.get("content") or spec.get("content") or "")
        spec["model_message"] = model_message
        source_specs.append(spec)
    context_candidate_gateway_result = build_context_candidate_gateway(
        source_specs,
        invocation_kind=invocation_kind,
        context_capability_profile=context_capability_profile,
        system_wiring_manifest=system_wiring_manifest,
    )
    source_specs = [dict(item) for item in context_candidate_gateway_result.message_specs]
    _context_candidate_gateway_diagnostics = dict(context_candidate_gateway_result.diagnostics or {})
    _context_capability_diagnostics = dict(
        _context_candidate_gateway_diagnostics.get("context_line_activation") or {}
    )
    source_bundle = build_prompt_source_bundle(
        packet_id=packet_id,
        invocation_kind=invocation_kind,
        message_specs=source_specs,
    )
    assembly_plan = build_prompt_assembly_plan(
        source_bundle=source_bundle,
        provider_profile={"provider_payload_boundary_source": "prompt_materialized_packet"},
    )
    materialized_packet = materialize_prompt_packet(assembly_plan=assembly_plan)
    clean_specs = [dict(item) for item in tuple(materialized_packet.message_specs or ())]
    source_manifest = build_runtime_prompt_source_manifest(
        packet_id=packet_id,
        invocation_kind=invocation_kind,
        message_specs=clean_specs,
    )
    clean_specs = [dict(item) for item in materialize_runtime_prompt_sources(source_manifest)]
    context_pipeline_result = build_context_pipeline(
        clean_specs,
        invocation_kind=invocation_kind,
        provider_visible_append_scope=provider_visible_append_scope,
        provider_visible_context_inheritance=provider_visible_context_inheritance,
        compaction_generation=compaction_generation,
        storage_root=storage_root,
        model_selection=model_selection,
        context_capability_profile=context_capability_profile,
        system_wiring_manifest=system_wiring_manifest,
        apply_capability_profile_stage=False,
    )
    clean_specs = [dict(item) for item in tuple(context_pipeline_result.message_specs or ())]
    context_pipeline_diagnostics = dict(context_pipeline_result.diagnostics or {})
    _provider_visible_append_stage_diagnostics = dict(context_pipeline_diagnostics.get("provider_visible_append_stage") or {})
    _context_physical_diagnostics = dict(context_pipeline_diagnostics.get("physical_context") or {})
    slot_plan = build_runtime_prompt_slot_plan(
        packet_id=packet_id,
        invocation_kind=invocation_kind,
        message_specs=clean_specs,
    )
    load_plan = build_runtime_context_load_plan(slot_plan)
    dynamic_context_validation = _dynamic_context_metadata_validation_diagnostics(
        clean_specs,
        requested=collect_dynamic_context_metadata_diagnostics,
    )
    strict_dynamic_context_validation = bool(
        collect_dynamic_context_metadata_diagnostics and _strict_dynamic_context_report_validation_enabled()
    )
    if strict_dynamic_context_validation:
        _raise_dynamic_context_metadata_violations(
            list(dynamic_context_validation.get("violations") or [])
        )
    model_messages = [dict(spec.get("model_message") or {}) for spec in clean_specs]
    segment_plan = build_prompt_segment_plan(
        packet_id=packet_id,
        invocation_kind=invocation_kind,
        message_specs=clean_specs,
        diagnostics={
            **dict(_context_physical_diagnostics or {}),
            "provider_visible_append_stage": dict(_provider_visible_append_stage_diagnostics or {}),
            "context_candidate_gateway": dict(_context_candidate_gateway_diagnostics or {}),
            "context_capability": dict(_context_capability_diagnostics or {}),
            "context_pipeline": context_pipeline_diagnostics,
            "dynamic_context_metadata_validation": dynamic_context_validation,
        },
    )
    return model_messages, segment_plan, tuple(clean_specs), source_manifest, slot_plan, load_plan


def _context_compaction_generation_from_session_context(session_context: dict[str, Any] | None) -> str:
    payload = dict(session_context or {})
    return normalize_context_compaction_generation(payload.get("compaction_generation"))


def _provider_visible_context_inheritance_from_session_context(
    session_context: dict[str, Any] | None,
    *,
    child_scope: str,
) -> dict[str, Any]:
    payload = dict(session_context or {})
    forked_from = dict(payload.get("forked_from") or {}) if isinstance(payload.get("forked_from"), dict) else {}
    parent_session_id = str(
        forked_from.get("parent_session_id")
        or payload.get("parent_session_id")
        or ""
    ).strip()
    child = str(child_scope or "").strip()
    if not parent_session_id or parent_session_id == child:
        return {}
    anchor = (
        dict(forked_from.get("fork_point_provider_visible_append_anchor") or {})
        if isinstance(forked_from.get("fork_point_provider_visible_append_anchor"), dict)
        else {}
    )
    if not anchor:
        return {}
    return {
        "inherited_scope": parent_session_id,
        "write_scope": child,
        "inherited_anchor": anchor,
        "fork_id": str(forked_from.get("fork_id") or ""),
        "fork_point_context_commit_id": str(forked_from.get("fork_point_context_commit_id") or ""),
        "fork_point_turn_id": str(forked_from.get("fork_point_turn_id") or ""),
        "fork_point_cache_spine_hash": str(forked_from.get("fork_point_cache_spine_hash") or ""),
        "fork_point_provider_request_commit_id": str(forked_from.get("fork_point_provider_request_commit_id") or ""),
        "fork_point_provider_request_cache_spine_hash": str(forked_from.get("fork_point_provider_request_cache_spine_hash") or ""),
        "fork_point_provider_payload_prefix_hash": str(forked_from.get("fork_point_provider_payload_prefix_hash") or ""),
        "fork_point_physical_cache_spine_message_subtotal_hash": str(forked_from.get("fork_point_physical_cache_spine_message_subtotal_hash") or ""),
        "fork_point_provider_payload_messages_hash": str(forked_from.get("fork_point_provider_payload_messages_hash") or ""),
        "fork_point_transport_contract_hash": str(forked_from.get("fork_point_transport_contract_hash") or ""),
        "fork_point_cache_sensitive_params_hash": str(forked_from.get("fork_point_cache_sensitive_params_hash") or ""),
        "provider_cache_scope_id": str(forked_from.get("provider_cache_scope_id") or ""),
        "fork_point_tool_context_anchor": str(forked_from.get("fork_point_tool_context_anchor") or ""),
        "fork_point_tool_context_projection": (
            dict(forked_from.get("fork_point_tool_context_projection") or {})
            if isinstance(forked_from.get("fork_point_tool_context_projection"), dict)
            else {}
        ),
        "fork_point_read_evidence_scope": (
            dict(forked_from.get("fork_point_read_evidence_scope") or {})
            if isinstance(forked_from.get("fork_point_read_evidence_scope"), dict)
            else {}
        ),
        "fork_child_read_evidence_scope": (
            dict(forked_from.get("fork_child_read_evidence_scope") or {})
            if isinstance(forked_from.get("fork_child_read_evidence_scope"), dict)
            else {}
        ),
        "fork_point_read_evidence_state_ref": str(forked_from.get("fork_point_read_evidence_state_ref") or ""),
        "fork_point_read_evidence_file_count": _safe_int(forked_from.get("fork_point_read_evidence_file_count")),
        "fork_file_state_materialization": (
            dict(forked_from.get("fork_file_state_materialization") or {})
            if isinstance(forked_from.get("fork_file_state_materialization"), dict)
            else {}
        ),
        "fork_point_content_replacement_state_ref": str(forked_from.get("fork_point_content_replacement_state_ref") or ""),
        "fork_point_content_replacement_state": (
            dict(forked_from.get("fork_point_content_replacement_state") or {})
            if isinstance(forked_from.get("fork_point_content_replacement_state"), dict)
            else {}
        ),
        "fork_point_compaction_generation": str(forked_from.get("fork_point_compaction_generation") or ""),
        "workspace_effect_policy": str(forked_from.get("workspace_effect_policy") or ""),
        "authority": "harness.runtime.compiler.provider_visible_context_inheritance_from_session_context",
    }


def _model_selection_with_provider_lane(
    model_selection: dict[str, Any] | None,
    *,
    provider_lane: str,
) -> dict[str, Any]:
    selection = dict(model_selection or {})
    selection["provider_lane"] = str(provider_lane or "").strip()
    return selection


def _sanitize_model_messages_for_prompt_packet(
    messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    message_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    turn_id: str,
    source: str,
) -> ProtocolSanitizerResult:
    byte_preservation_specs = [
        dict(item)
        for item in list(message_specs or ())
        if isinstance(item, dict) and _provider_message_byte_preservation_contract_spec(dict(item))
    ]
    if not byte_preservation_specs:
        return sanitize_messages_for_prompt(messages, turn_id=turn_id, source=source)
    return ProtocolSanitizerResult(
        messages=tuple(dict(item) for item in list(messages or []) if isinstance(item, dict)),
        diagnostics={
            "source": str(source or ""),
            "turn_id": str(turn_id or ""),
            "input_message_count": len(list(messages or [])),
            "output_message_count": len([item for item in list(messages or []) if isinstance(item, dict)]),
            "status": "byte_preserved_for_provider_message_contract",
            "provider_message_byte_preservation_contract_spec_count": len(byte_preservation_specs),
            "provider_message_byte_preservation_contract_refs": [
                str(spec.get("source_ref") or dict(spec.get("metadata") or {}).get("runtime_prompt_source_id") or "")
                for spec in byte_preservation_specs[:20]
            ],
            "provider_message_byte_preservation_contracts": [
                provider_message_replay_kind(spec) for spec in byte_preservation_specs[:20]
            ],
            "authority": "harness.runtime.compiler.provider_message_byte_preservation_sanitizer_guard",
        },
    )


def _provider_message_byte_preservation_contract_spec(spec: dict[str, Any]) -> bool:
    return provider_message_byte_preservation_required(spec)


def _context_physical_assembly_manifest_from_specs(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    section_counts: dict[str, int] = {}
    dynamic_tail_count = 0
    stable_after_tail_count = 0
    tail_seen = False
    physical_plan_ref = ""
    cache_spine_hash = ""
    cache_spine_generation = ""
    prefix_lane_counts: dict[str, int] = {}
    prefix_lane_order: list[str] = []
    for raw_spec in list(specs or ()):
        if not isinstance(raw_spec, dict):
            continue
        metadata = dict(raw_spec.get("metadata") or {})
        if not physical_plan_ref:
            physical_plan_ref = str(metadata.get("physical_context_plan_ref") or "")
        if not cache_spine_hash:
            cache_spine_hash = str(metadata.get("cache_spine_hash") or "")
        if not cache_spine_generation:
            cache_spine_generation = str(metadata.get("cache_spine_generation") or "")
        lane = str(metadata.get("physical_prefix_lane") or "").strip()
        if lane:
            prefix_lane_counts[lane] = prefix_lane_counts.get(lane, 0) + 1
            if lane not in prefix_lane_order:
                prefix_lane_order.append(lane)
        section = str(metadata.get("context_cache_section") or raw_spec.get("context_cache_section") or "").strip()
        if section:
            section_counts[section] = section_counts.get(section, 0) + 1
        if section == DYNAMIC_TAIL:
            dynamic_tail_count += 1
        lane = str(metadata.get("physical_prefix_lane") or "").strip()
        if lane in {"current_turn_tail", "never_replay_tail"}:
            tail_seen = True
        elif tail_seen and lane in {"global_static_prefix", "provider_visible_context_prefix"}:
            stable_after_tail_count += 1
    return {
        "message_spec_count": len([item for item in list(specs or ()) if isinstance(item, dict)]),
        "context_cache_section_counts": section_counts,
        "dynamic_tail_count": dynamic_tail_count,
        "stable_cache_spine_segment_after_tail_count": stable_after_tail_count,
        "physical_context_plan_ref": physical_plan_ref,
        "physical_prefix_lane_order": prefix_lane_order,
        "physical_prefix_lane_counts": prefix_lane_counts,
        "cache_spine_hash": cache_spine_hash,
        "cache_spine_generation": cache_spine_generation,
        "source_manifest_stage": "pre_physical_source_lineage",
        "final_order_source": "message_specs_after_context_physical_assembly",
        "authority": "harness.runtime.compiler.context_physical_assembly_manifest",
    }


def _model_message_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    raw_message = spec.get("model_message") if isinstance(spec.get("model_message"), dict) else spec
    if provider_message_byte_preservation_required(spec):
        return dict(raw_message)
    role = str(raw_message.get("role") or spec.get("role") or "user").strip() or "user"
    message: dict[str, Any] = {
        "role": role,
        "content": str(raw_message.get("content") if raw_message.get("content") is not None else spec.get("content") or ""),
    }
    for key in ("name", "tool_call_id"):
        value = str(raw_message.get(key) or spec.get(key) or "").strip()
        if value:
            message[key] = value
    tool_calls = raw_message.get("tool_calls") if raw_message.get("tool_calls") is not None else spec.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        message["tool_calls"] = [dict(item) for item in tool_calls if isinstance(item, dict)]
    reasoning_content = str(
        raw_message.get("reasoning_content")
        if raw_message.get("reasoning_content") is not None
        else spec.get("reasoning_content")
        or ""
    ).strip()
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    prefix = raw_message.get("prefix") if raw_message.get("prefix") is not None else spec.get("prefix")
    if prefix is True or str(prefix or "").strip().lower() == "true":
        message["prefix"] = True
    return message


def _has_model_message_payload(message: dict[str, Any]) -> bool:
    role = str(message.get("role") or "")
    if role == "assistant" and (message.get("tool_calls") or message.get("reasoning_content")):
        return True
    if role == "tool" and message.get("tool_call_id"):
        return True
    return bool(str(message.get("content") or "").strip())


def _strict_dynamic_context_report_validation_enabled() -> bool:
    raw = str(os.getenv("AGENT_STRICT_DYNAMIC_CONTEXT_REPORTS") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _dynamic_context_metadata_validation_diagnostics(
    specs: list[dict[str, Any]],
    *,
    requested: bool,
) -> dict[str, Any]:
    violations = _dynamic_context_metadata_violations(specs) if requested else []
    strict_enabled = _strict_dynamic_context_report_validation_enabled()
    return {
        "requested": bool(requested),
        "mode": "strict" if requested and strict_enabled else "diagnostic",
        "strict_env": "AGENT_STRICT_DYNAMIC_CONTEXT_REPORTS",
        "strict_enabled": bool(strict_enabled),
        "violation_count": len(violations),
        "violations": violations[:20],
        "authority": "harness.runtime.compiler.dynamic_context_metadata_validation",
    }


def _raise_dynamic_context_metadata_violations(violations: list[dict[str, Any]]) -> None:
    if not violations:
        return
    first = dict(violations[0] or {})
    kind = str(first.get("kind") or "")
    raise ValueError(f"dynamic/volatile segment requires dynamic context metadata: {kind}")


def _dynamic_context_metadata_violations(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for index, spec in enumerate(specs):
        cache_role = str(spec.get("cache_role") or "")
        kind = str(spec.get("kind") or "")
        policy = context_segment_policy_for_spec(spec, default_section=CONTEXT_APPEND)
        if cache_role != "volatile" and policy.section != DYNAMIC_TAIL:
            continue
        metadata = dict(spec.get("metadata") or {})
        if _is_sealed_provider_visible_replay_metadata(metadata):
            continue
        if metadata.get("dynamic_context_report_ref") or metadata.get("volatility_reason"):
            continue
        violations.append(
            {
                "index": index,
                "kind": kind,
                "cache_role": cache_role,
                "source_ref": str(spec.get("source_ref") or ""),
                "reason": "missing_dynamic_context_report_ref_or_volatility_reason",
            }
        )
    return violations


def _is_sealed_provider_visible_replay_metadata(metadata: dict[str, Any]) -> bool:
    return physical_prefix_frame_replay_metadata(metadata)


def _dynamic_context_segment_metadata(
    projection: DynamicContextProjection,
    *,
    source: str,
) -> dict[str, Any]:
    source_text = str(source or "")
    for report in projection.section_reports:
        if str(report.source or "") == source_text:
            return {
                "dynamic_context_report_ref": report.section_id,
                "volatility_reason": report.volatility_reason,
                "projection_strategy": report.projection_strategy,
                "cache_impact": report.cache_impact,
            }
    raise ValueError(f"dynamic context section report missing for source: {source_text}")


def _current_user_context_append_metadata(payload: dict[str, Any] | None, *, turn_id: str = "") -> dict[str, Any]:
    user_message = str(dict(payload or {}).get("user_message") or "")
    origin_ref = f"turn:{str(turn_id or '').strip()}:current_user_context" if str(turn_id or "").strip() else ""
    return {
        "content_source": "harness.runtime.compiler.current_turn_user_context",
        "context_origin_authority": "harness.runtime.compiler.current_turn_user_context",
        "context_origin_ref": origin_ref,
        "runtime_fragment_role": "current_user_request",
        "context_cache_section": CONTEXT_APPEND,
        "context_prefix_cache_scope": "none",
        "context_prefix_cache_role": "volatile",
        "context_prefix_tier": "volatile",
        "context_commit_policy": "never_commit",
        "context_replay_policy": "current_turn_present_only",
        "context_identity_policy": "current_turn_only",
        "semantic_commit_class": "current_user_context",
        "provider_visible_after_validity": "not_replayed_after_current_request",
        "cache_impact": "current_turn_tail_only",
        "stability_rule": (
            "current user input is present-turn context; after provider success it is represented by "
            "provider_protocol_timeline/provider_protocol_history instead of this current-turn fragment"
        ),
        "append_only_context_package": "current_user_context",
        "append_only_context_stream": "current_user_context",
        "append_only_stream_index": 1,
        "append_only_content_hash": _stable_json_hash({"user_message": user_message}),
    }


def _current_append_fact_metadata(
    *,
    kind: str,
    payload: dict[str, Any],
    semantic_slot: str,
    semantic_rank: int,
    origin_ref: str = "",
    package: str = "",
    stream: str = "",
    semantic_commit_class: str = "",
) -> dict[str, Any]:
    normalized_kind = str(kind or "").strip()
    normalized_slot = str(semantic_slot or normalized_kind or "context_memory_append").strip()
    content_hash = _stable_json_hash(payload)
    stable_origin_ref = str(origin_ref or "").strip() or f"{normalized_kind}:{content_hash}"
    fact_slot_key = _stable_json_hash(
        {
            "schema": "semantic_fact_slot",
            "kind": normalized_kind,
            "semantic_slot": normalized_slot,
            "origin_ref": stable_origin_ref,
        }
    )
    item_key = _stable_json_hash(
        {
            "schema": "current_append_fact_context_item",
            "kind": normalized_kind,
            "semantic_slot": normalized_slot,
            "origin_ref": stable_origin_ref,
            "content_hash": content_hash,
        }
    )
    return {
        "cache_impact": "context_append_then_sealed_prefix",
        "context_cache_section": CONTEXT_APPEND,
        "context_prefix_cache_scope": "none",
        "context_prefix_cache_role": "volatile",
        "context_prefix_tier": "volatile",
        "context_semantic_slot": normalized_slot,
        "context_semantic_slot_rank": int(semantic_rank or 0),
        "context_commit_policy": "append_then_seal",
        "context_replay_policy": "current_append_commit_on_provider_success_then_next_physical_prefix_frame",
        "context_identity_policy": "origin_ref_stable",
        "context_origin_authority": "harness.runtime.compiler.current_append_fact",
        "context_origin_ref": stable_origin_ref,
        "append_only_context_package": str(package or normalized_slot or normalized_kind),
        "append_only_context_stream": str(stream or normalized_slot or normalized_kind),
        "append_only_context_item_key": item_key,
        "append_only_content_hash": content_hash,
        "fact_slot_key": fact_slot_key,
        "fact_content_hash": content_hash,
        "fact_change_class": "content_version_candidate",
        "fact_supersession_policy": "same_fact_slot_latest_content_hash_supersedes_prior",
        "semantic_commit_class": str(semantic_commit_class or "context_memory_append"),
        "provider_visible_after_validity": "replay_after_provider_success_via_physical_prefix_frame",
    }


def _current_runtime_tail_metadata(
    metadata: dict[str, Any] | None,
    *,
    semantic_slot: str,
    validity_scope: str = "",
) -> dict[str, Any]:
    payload = dict(metadata or {})
    slot = str(semantic_slot or "runtime_delta_tail").strip() or "runtime_delta_tail"
    return {
        **payload,
        "context_cache_section": DYNAMIC_TAIL,
        "fixed_context_package": "current_turn_tail",
        "context_prefix_cache_scope": "none",
        "context_prefix_cache_role": "volatile",
        "context_prefix_tier": "volatile",
        "context_semantic_slot": slot,
        "context_commit_policy": "never_commit",
        "context_replay_policy": "current_dynamic_tail_only",
        "context_identity_policy": "turn_scope_runtime_tail",
        "semantic_commit_class": "current_runtime_control",
        "context_memory_visible": False,
        "context_memory_commit_policy": "never_commit",
        "validity_scope": str(validity_scope or ""),
        "provider_visible_after_validity": "not_replayed_after_current_request",
        "cache_impact": "current_dynamic_tail_only",
        "stability_rule": (
            "This request-control block is valid only for the current model request. "
            "It is not sealed into provider-visible history; stable conversation memory is carried by "
            "the append-only user, tool, file-evidence, and memory context lanes."
        ),
    }


def _runtime_control_context_notice(*, validity_scope: str = "") -> str:
    del validity_scope
    return (
        "这段只对当前用户请求有效；历史上下文中的同类边界只作背景记录。"
        "请以消息流最后出现的当前请求上下文为准。"
    )


def _runtime_control_context_content(
    content: str,
    *,
    validity_scope: str = "",
    source_ref: str = "",
    include_notice: bool = True,
) -> str:
    body = _context_fragment_text_body(content)
    if not body:
        return ""
    text = (
        _join_prompt_sections(
            _runtime_control_context_notice(validity_scope=validity_scope),
            body,
        )
        if include_notice
        else body
    )
    return render_text_context_fragment(
        kind="current_request_guidance",
        title="当前请求工作提示边界",
        text=text,
        role="system",
        source_ref=source_ref,
        cache_scope="none",
        cache_role="volatile",
        prefix_tier="volatile",
        compression_role="preserve",
        validity_scope=validity_scope,
    )


def _active_skill_context_content(content: str, *, source_ref: str = "") -> str:
    body = _context_fragment_text_body(content)
    if not body:
        return ""
    return render_text_context_fragment(
        kind="active_skills",
        title="当前激活技能",
        text=body,
        role="system",
        source_ref=source_ref,
        cache_scope="none",
        cache_role="volatile",
        prefix_tier="volatile",
        compression_role="preserve",
    )


def _context_fragment_text_body(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    if not text.startswith("<context_fragment"):
        return text
    fragments = parse_context_fragments(text)
    if not fragments:
        return text
    values: list[str] = []
    for fragment in fragments:
        body = fragment.get("body")
        if not isinstance(body, dict):
            continue
        if "text" in body:
            value = str(body.get("text") or "").strip()
        elif "payload" in body:
            value = json.dumps(_json_stable(body.get("payload")), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        else:
            value = ""
        if value:
            values.append(value)
    return _join_prompt_sections(*values)


def _optional_dynamic_context_segment_metadata(
    projection: DynamicContextProjection,
    *,
    source: str,
) -> dict[str, Any]:
    try:
        return _dynamic_context_segment_metadata(projection, source=source)
    except ValueError:
        return {}


def _editor_context_from_session_context(session_context: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(session_context or {})
    turn_input_facts = dict(payload.get("turn_input_facts") or {})
    editor_context = turn_input_facts.get("editor_context")
    if isinstance(editor_context, dict) and editor_context:
        return dict(editor_context)
    editor_context = payload.get("editor_context")
    return dict(editor_context) if isinstance(editor_context, dict) and editor_context else {}


def _editor_context_from_task_run(task_run: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(task_run or {})
    diagnostics = dict(payload.get("diagnostics") or {})
    editor_context = diagnostics.get("editor_context")
    return dict(editor_context) if isinstance(editor_context, dict) and editor_context else {}


def _attach_model_message_metrics(
    prompt_manifest: dict[str, Any],
    *,
    model_messages: list[dict[str, Any]],
    segment_plan: dict[str, Any],
) -> None:
    segments = [dict(item) for item in list(segment_plan.get("segments") or []) if isinstance(item, dict)]
    message_chars = [len(str(dict(item).get("content") or "")) for item in list(model_messages or []) if isinstance(item, dict)]
    token_estimate = dict(prompt_manifest.get("token_estimate") or {})
    token_estimate["assembly_prompt_chars"] = int(token_estimate.get("prompt_chars") or 0)
    token_estimate["model_visible_chars"] = sum(message_chars)
    token_estimate["model_message_count"] = len(message_chars)
    token_estimate["cacheable_prefix_chars"] = sum(
        message_chars[int(segment.get("model_message_index"))]
        for segment in segments
        if str(segment.get("cache_role") or "") in {"cacheable_prefix", "session_stable"}
        and _valid_message_index(segment.get("model_message_index"), message_chars)
    )
    token_estimate["volatile_chars"] = sum(
        message_chars[int(segment.get("model_message_index"))]
        for segment in segments
        if str(segment.get("cache_role") or "") == "volatile"
        and _valid_message_index(segment.get("model_message_index"), message_chars)
    )
    prompt_manifest["token_estimate"] = token_estimate


def _attach_context_contract_manifest(
    prompt_manifest: dict[str, Any],
    *,
    packet_id: str,
    invocation_kind: str,
    message_specs: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    segment_plan: dict[str, Any],
) -> dict[str, Any]:
    manifest = build_context_contract_manifest(
        packet_id=packet_id,
        invocation_kind=invocation_kind,
        message_specs=message_specs,
        segment_plan=segment_plan,
    )
    payload = manifest.to_dict()
    prompt_manifest["context_contract_manifest"] = payload
    prompt_manifest["context_contract_inspection"] = build_context_contract_inspection_payload(payload)
    return payload


def _attach_action_schema_manifest(
    prompt_manifest: dict[str, Any],
    action_schema_manifest: ActionSchemaManifest,
) -> dict[str, Any]:
    payload = action_schema_manifest.to_dict()
    prompt_manifest["action_schema_manifest"] = payload
    return payload


def _attach_artifact_scope_manifest(
    prompt_manifest: dict[str, Any],
    artifact_scope_manifest: ArtifactScopeManifest,
) -> dict[str, Any]:
    payload = artifact_scope_manifest.to_dict()
    prompt_manifest["artifact_scope_manifest"] = payload
    return payload


def _attach_tool_catalog_manifest(
    prompt_manifest: dict[str, Any],
    tool_catalog_manifest: ToolCatalogManifest,
) -> dict[str, Any]:
    payload = tool_catalog_manifest.to_dict()
    prompt_manifest["tool_catalog_manifest"] = payload
    return payload


def _attach_prompt_composition_manifest(
    prompt_manifest: dict[str, Any],
    *,
    invocation_kind: str,
    packet_id: str,
    segment_plan: dict[str, Any],
    runtime_slot_plan: Any | None = None,
    dynamic_projection_refs: tuple[str, ...] = (),
    volatile_state_refs: tuple[str, ...] = (),
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if runtime_slot_plan is None:
        raise ValueError("runtime_slot_plan is required for runtime prompt composition")
    try:
        composition = build_runtime_slot_prompt_composition_manifest(
            invocation_kind=invocation_kind,
            packet_id=packet_id,
            runtime_slot_plan=runtime_slot_plan,
            segment_plan=segment_plan,
            dynamic_fragment_refs=dynamic_projection_refs,
            volatile_state_refs=volatile_state_refs,
            diagnostics={
                **dict(diagnostics or {}),
                "shadow_mode": False,
                "runtime_prompt_manifest_ref": str(prompt_manifest.get("manifest_id") or ""),
            },
        )
    except Exception as exc:
        failure = {
            "shadow_mode": False,
            "status": "failed",
            "error": str(exc),
            "authority": "prompt_composition.runtime_slot_manifest_builder",
        }
        prompt_manifest["prompt_composition"] = failure
        return failure
    payload = composition.to_dict()
    prompt_manifest["prompt_composition"] = payload
    return payload


def _render_model_messages_from_prompt_composition(
    *,
    prompt_manifest: dict[str, Any],
    prompt_composition_manifest: dict[str, Any],
    content_fragments: tuple[PromptCompositionContentFragment, ...],
    model_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    render_result = render_model_messages_from_projection(
        manifest=prompt_composition_manifest,
        content_fragments=content_fragments,
        source_messages=model_messages,
    )
    render_diagnostics = dict(render_result.diagnostics)
    rendered_message_count = int(render_diagnostics.get("rendered_message_count") or 0)
    expected_message_count = len(list(model_messages or []))
    projection_message_count = int(render_diagnostics.get("projection_message_count") or 0)
    source_message_fallback_count = int(render_diagnostics.get("source_message_fallback_count") or 0)
    if rendered_message_count != expected_message_count or rendered_message_count != projection_message_count or source_message_fallback_count:
        prompt_manifest["prompt_composition_render"] = {
            **render_diagnostics,
            "renderer_fallback_to_source_messages": False,
            "status": "failed",
            "fallback_reason": (
                "content_fragment_incomplete"
                if source_message_fallback_count
                or list(render_diagnostics.get("missing_content_fragment_segment_ids") or [])
                else "message_projection_incomplete"
            ),
        }
        raise RuntimeError("prompt_composition_render_failed")
    prompt_manifest["prompt_composition_render"] = render_diagnostics
    return [dict(item) for item in render_result.messages]


def _context_window_report(
    *,
    session_context: dict[str, Any] | None,
    history: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    dynamic_context: DynamicContextProjection | None = None,
) -> dict[str, Any]:
    session_payload = dict(session_context or {})
    context_recovery_package = _context_recovery_package_payload(session_payload)
    package_coverage = (
        dict(context_recovery_package.get("coverage") or {})
        if isinstance(context_recovery_package.get("coverage"), dict)
        else {}
    )
    recent_work_outcome = dict(session_payload.get("recent_work_outcome") or {}) if isinstance(session_payload.get("recent_work_outcome"), dict) else {}
    dynamic_report = dynamic_context.to_report_dict() if dynamic_context is not None else {}
    volatile_request = dict(getattr(dynamic_context, "volatile_request_projection", {}) or {}) if dynamic_context is not None else {}
    history_projection = dict(volatile_request.get("history") or {})
    raw_history = [dict(item) for item in list(history or []) if isinstance(item, dict)]
    active_history = [dict(item) for item in list(history_projection.get("active_history") or []) if isinstance(item, dict)]
    return _drop_empty_payload(
        {
            "context_recovery_package_hash": _stable_json_hash(context_recovery_package) if context_recovery_package else "",
            "context_recovery_package_present": bool(context_recovery_package),
            "context_recovery_package_source": str(context_recovery_package.get("source") or "") if context_recovery_package else "",
            "context_recovery_package_covered_message_count": _safe_int(package_coverage.get("covered_message_count")),
            "context_recovery_package_covered_event_offset_end": _safe_int(package_coverage.get("covered_event_offset_end")),
            "recent_work_outcome_hash": _stable_json_hash(recent_work_outcome) if recent_work_outcome else "",
            "recent_work_outcome_present": bool(recent_work_outcome),
            "raw_history_message_count": len(raw_history),
            "active_history_message_count": len(active_history),
            "active_history_fingerprint": _stable_json_hash(active_history) if active_history else "",
            "budget_report": dict(dynamic_report.get("budget_report") or {}),
            "stable_runtime_baseline_refs": dict(dynamic_report.get("stable_runtime_baseline_refs") or {}),
            "dynamic_context_diagnostics": dict(dynamic_report.get("diagnostics") or {}),
            "authority": "harness.runtime.compiler.context_window_report",
        }
    )


def _context_recovery_package_payload(session_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(session_payload or {})
    package = payload.get("context_recovery_package")
    if isinstance(package, dict) and package:
        return {
            **dict(package),
            "authority": str(dict(package).get("authority") or "runtime.context_management.context_recovery_package"),
        }
    compressed_context = str(payload.get("compressed_context") or "").strip()
    if not compressed_context:
        return {}
    return {
        "content": compressed_context,
        "format": "markdown",
        "source": "session_record.compressed_context",
        "authority": "runtime.context_management.context_recovery_package",
    }


def _valid_message_index(index: Any, message_chars: list[int]) -> bool:
    try:
        value = int(index)
    except (TypeError, ValueError):
        return False
    return 0 <= value < len(message_chars)


def _attach_project_instruction_manifest(prompt_manifest: dict[str, Any], bundle: ProjectInstructionBundle) -> None:
    if not bundle.has_content:
        prompt_manifest["project_instruction_refs"] = []
        return
    prompt_manifest["project_instruction_refs"] = [bundle.prompt_ref]
    prompt_manifest["project_instructions"] = bundle.to_manifest_dict()


def _project_instruction_model_payload(bundle: ProjectInstructionBundle) -> dict[str, Any]:
    if not bundle.has_content:
        return {}
    return {
        "project_instructions": {
            "prompt_ref": bundle.prompt_ref,
            "content": bundle.content,
            "source_hash": bundle.source_hash,
            "sources": [source.to_manifest_dict() for source in bundle.sources],
            "authority": bundle.authority,
        }
    }


def _file_evidence_policy_stable_payload() -> dict[str, Any]:
    return {
        "file_evidence_policy": {
            "read_evidence_reuse_contract": {
                "covered_non_stale_window": (
                    "如果目标行范围已经被当前未过期 workspace_read(action=file) 窗口覆盖，应复用该窗口或对应 observation_ref；"
                    "当你提交的 workspace_read(action=file) 与未过期窗口完全重合时，执行层会返回当前工具观察，说明旧证据仍可使用。"
                ),
                "rehydrate_omitted_window": (
                    "当已有窗口内容被省略且确实需要精确字节时，优先使用 rehydration_ref 或 reusable_result_ref 恢复；"
                    "只有 stale、changed、missing、hash 缺失或目标范围未覆盖时才需要新的 workspace_read(action=file)。"
                ),
                "known_path_boundary": (
                    "已知 bound/editor 文件路径，以及 task_run_contract 的 GoalContext、PlanContext 或 TodoContext working_scope 中表现为路径的 target_objects、"
                    "source_refs 或 workspace_refs，不需要通过 workspace_search 重新发现；"
                    "未知位置先使用 workspace_search(action=text) 这类 rg-like 搜索收敛候选；只有文件名/路径关键词用 workspace_search(action=path)，明确通配符线索时用 workspace_search(action=glob)。"
                ),
            },
            "current_evidence_sources": [
                "当前文件证据窗口",
                "可重新读取的结果句柄",
                "已绑定的编辑器或任务工作范围",
            ],
        }
    }


def _join_prompt_sections(*sections: str) -> str:
    return "\n".join(str(section or "").strip() for section in sections if str(section or "").strip()) + "\n"


def _merge_prompt_assemblies(
    *assemblies: PromptAssemblyResult,
    invocation_kind: str,
) -> PromptAssemblyResult:
    sections = []
    pack_refs: list[str] = []
    rejected_refs: list[dict[str, Any]] = []
    omitted_refs: list[dict[str, Any]] = []
    for assembly in assemblies:
        sections.extend(assembly.sections)
        pack_refs.extend(assembly.prompt_pack_refs)
        rejected_refs.extend(dict(item) for item in assembly.rejected_refs)
        omitted_refs.extend(dict(item) for item in list(dict(assembly.manifest or {}).get("omitted_refs") or []))
    sections = list(enforce_prompt_authority_order(tuple(sections)))
    rule_diagnostics = build_rule_diagnostics(
        tuple(sections),
        invocation_kind=invocation_kind,
        omitted_rule_refs=tuple(str(item.get("ref") or "") for item in omitted_refs),
    )
    rejected_refs.extend(dict(item) for item in list(rule_diagnostics.get("rejected_rules") or []))
    if rule_diagnostics.get("rejected_rules"):
        rejected = ", ".join(
            f"{item.get('ref', '')}:{item.get('reason', '')}"
            for item in list(rule_diagnostics.get("rejected_rules") or [])
            if isinstance(item, dict)
        )
        raise ValueError(
            "runtime prompt rule assembly rejected refs: "
            f"invocation_kind={invocation_kind} refs={rejected}"
        )
    return PromptAssemblyResult(
        assembly_id=f"promptasm:runtime_packet:{invocation_kind}",
        invocation_kind=invocation_kind,
        sections=tuple(sections),
        prompt_pack_refs=tuple(dict.fromkeys(pack_refs)),
        rejected_refs=tuple(rejected_refs),
        manifest={
            "stable_prompt_refs": [item.prompt_ref for item in sections if item.prompt_ref],
            "stable_contract_refs": [item.source_ref for item in sections if not item.prompt_ref],
            "prompt_pack_refs": list(dict.fromkeys(pack_refs)),
            "rejected_refs": rejected_refs,
            "omitted_refs": omitted_refs,
            "prompt_rules": rule_diagnostics,
            "prompt_precedence": build_prompt_precedence_report(tuple(sections)),
            "prompt_authority": build_prompt_authority_manifest(tuple(sections)),
            "authority": "prompt_library.prompt_assembly_manifest",
        },
    )


def _runtime_prompt_precedence_report(sections: tuple[Any, ...]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    precedence = {
        "system": 0,
        "agent": 20,
        "personality": 25,
        "runtime": 30,
        "environment": 40,
        "tool": 50,
        "skill": 60,
        "project": 70,
        "contract": 80,
        "unknown": 100,
    }
    for section in sections:
        category = str(getattr(section, "category", "") or "")
        subtype = str(getattr(section, "subtype", "") or "")
        prompt_ref = str(getattr(section, "prompt_ref", "") or "")
        layer = "environment" if category == "environment" and (subtype.startswith("guidance_") or ".guidance." in prompt_ref) else category
        if layer not in precedence:
            layer = "unknown"
        entries.append(
            {
                "prompt_ref": prompt_ref,
                "category": category,
                "subtype": subtype,
                "assembly_layer": layer,
                "precedence": precedence[layer],
                "order": int(getattr(section, "order", 0) or 0),
            }
        )
    return {
        "policy": "system>override>coordinator>agent>personality>runtime>environment>tool>skill>project>contract",
        "behavior": "enforced_precedence_order",
        "entries": entries,
        "authority": "harness.runtime.prompt_precedence_report",
    }


def _string_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip(): str(item).strip()
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }


def _prompt_pack_refs_for_invocation(
    profile_payload: dict[str, Any],
    *,
    invocation_kind: str,
    assembly_payload: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    return _prompt_wiring_pack_refs_for_slot(
        dict(assembly_payload or {}),
        invocation_kind=invocation_kind,
        slot_name="runtime_prompt_pack",
    )


def _build_invocation_prompt_wiring_plan(
    *,
    base_dir: Path,
    assembly_payload: dict[str, Any],
    invocation_kind: str,
    allowed_actions: tuple[str, ...] = (),
    operation_availability: dict[str, Any] | None = None,
    active_work_context: dict[str, Any] | None = None,
    memory_context: dict[str, Any] | None = None,
    observations: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    visible_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    execution_state: dict[str, Any] | None = None,
    session_context: dict[str, Any] | None = None,
    prompt_pack_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    environment_payload = dict(assembly_payload.get("task_environment") or {})
    environment_id = str(environment_payload.get("environment_id") or environment_payload.get("requested_environment_id") or "").strip()
    profile_view = _runtime_prompt_profile_view_from_assembly(assembly_payload, environment_id=environment_id)
    wiring_plan = build_runtime_prompt_wiring_plan(
        base_dir=base_dir,
        agent_profile=profile_view,
        invocation_kind=invocation_kind,
        environment_id=environment_id,
        allowed_actions=allowed_actions,
        operation_availability=operation_availability,
        active_work_context=active_work_context,
        memory_context=memory_context,
        observations=observations,
        visible_tools=visible_tools,
        execution_state=execution_state,
        session_context=session_context,
        prompt_pack_refs=prompt_pack_refs,
    ).to_dict()
    _attach_invocation_prompt_wiring_plan(assembly_payload, invocation_kind=invocation_kind, wiring_plan=wiring_plan)
    return wiring_plan


def _runtime_prompt_profile_view_from_assembly(
    assembly_payload: dict[str, Any],
    *,
    environment_id: str,
) -> _RuntimePromptProfileView:
    profile_payload = dict(assembly_payload.get("profile") or {})
    agent_profile_id = str(
        assembly_payload.get("agent_profile_ref")
        or profile_payload.get("profile_ref")
        or "main_interactive_agent"
    ).strip()
    metadata = dict(profile_payload.get("metadata") or {})
    metadata.setdefault("default_task_environment_id", environment_id)
    return _RuntimePromptProfileView(
        agent_profile_id=agent_profile_id,
        prompt_set_refs=_string_tuple(profile_payload.get("prompt_set_refs")),
        prompt_bindings=dict(profile_payload.get("prompt_bindings") or {}),
        metadata=metadata,
    )


def _attach_invocation_prompt_wiring_plan(
    assembly_payload: dict[str, Any],
    *,
    invocation_kind: str,
    wiring_plan: dict[str, Any],
) -> None:
    invocation = str(invocation_kind or "").strip()
    if not invocation:
        return
    plans = dict(assembly_payload.get("prompt_wiring_plans_by_invocation") or {})
    plans[invocation] = dict(wiring_plan or {})
    assembly_payload["prompt_wiring_plans_by_invocation"] = plans
    if invocation == "single_agent_turn" or not dict(assembly_payload.get("prompt_wiring_plan") or {}):
        assembly_payload["prompt_wiring_plan"] = dict(wiring_plan or {})


def _prompt_wiring_refs_for_slot(
    assembly_payload: dict[str, Any],
    *,
    invocation_kind: str,
    slot_name: str,
) -> tuple[str, ...]:
    slot = _prompt_wiring_slot(assembly_payload, invocation_kind=invocation_kind, slot_name=slot_name)
    return _string_tuple(slot.get("refs"))


def _prompt_wiring_pack_refs_for_slot(
    assembly_payload: dict[str, Any],
    *,
    invocation_kind: str,
    slot_name: str,
) -> tuple[str, ...]:
    slot = _prompt_wiring_slot(assembly_payload, invocation_kind=invocation_kind, slot_name=slot_name)
    return _string_tuple(slot.get("pack_refs"))


def _prompt_wiring_slot_from_plan(wiring_plan: dict[str, Any], *, slot_name: str) -> dict[str, Any]:
    target = str(slot_name or "").strip()
    for raw_slot in list(dict(wiring_plan or {}).get("slots") or []):
        if not isinstance(raw_slot, dict):
            continue
        if str(raw_slot.get("slot") or "").strip() == target:
            return dict(raw_slot)
    return {}


def _prompt_wiring_slot(
    assembly_payload: dict[str, Any],
    *,
    invocation_kind: str,
    slot_name: str,
) -> dict[str, Any]:
    plans_by_invocation = dict(assembly_payload.get("prompt_wiring_plans_by_invocation") or {})
    plan = dict(plans_by_invocation.get(str(invocation_kind or "").strip()) or {})
    if not plan:
        plan = dict(assembly_payload.get("prompt_wiring_plan") or {})
    if str(plan.get("invocation_kind") or "").strip() != str(invocation_kind or "").strip():
        return {}
    target = str(slot_name or "").strip()
    for raw_slot in list(plan.get("slots") or []):
        if not isinstance(raw_slot, dict):
            continue
        if str(raw_slot.get("slot") or "").strip() == target:
            return dict(raw_slot)
    return {}


def _runtime_prompt_policy(
    *,
    profile_payload: dict[str, Any],
    assembly_payload: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    runtime_profile = dict(contract.get("runtime_profile") or {})
    runtime_policy = dict(runtime_profile.get("runtime_policy") or runtime_profile.get("execution_policy") or {})
    candidates = (
        profile_payload.get("prompt_policy"),
        dict(assembly_payload.get("runtime_contract") or {}).get("prompt_policy"),
        dict(assembly_payload.get("runtime_contract") or {}).get("runtime_prompt_policy"),
        assembly_payload.get("prompt_policy"),
        runtime_profile.get("prompt_policy"),
        runtime_policy.get("prompt_policy"),
        contract.get("prompt_policy"),
    )
    result: dict[str, Any] = {}
    for candidate in candidates:
        if isinstance(candidate, dict):
            result.update(candidate)
    return result


def _prompt_policy_visible(policy: dict[str, Any], key: str, *, default: bool) -> bool:
    if key not in dict(policy or {}):
        return default
    value = dict(policy or {}).get(key)
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"", "default", "inherit"}:
        return default
    if normalized in {"hidden", "hide", "off", "false", "0", "none", "disabled", "omit", "omitted"}:
        return False
    if normalized in {"visible", "show", "on", "true", "1", "full", "enabled"}:
        return True
    return default


def _empty_prompt_assembly(invocation_kind: str, assembly_id: str) -> PromptAssemblyResult:
    return PromptAssemblyResult(
        assembly_id=assembly_id,
        invocation_kind=invocation_kind,
        sections=(),
    )


def _prompt_mount_plan_manifest_payload(prompt_mount_plan: Any, *, prompt_policy: dict[str, Any]) -> dict[str, Any]:
    payload = dict(prompt_mount_plan.to_dict() if hasattr(prompt_mount_plan, "to_dict") else dict(prompt_mount_plan or {}))
    if _prompt_policy_visible(prompt_policy, "environment_prompt_visibility", default=True):
        return payload
    hidden_refs = list(payload.get("environment_prompt_refs") or [])
    hidden_base_refs = list(payload.get("base_prompt_refs") or [])
    hidden_overlay_refs = list(payload.get("overlay_prompt_refs") or [])
    hidden_environment_guidance_refs = list(payload.get("environment_guidance_prompt_refs") or [])
    hidden_turn_state_guidance_refs = list(payload.get("turn_state_guidance_prompt_refs") or [])
    hidden_guidance_keys = list(payload.get("environment_guidance_prompt_keys") or [])
    hidden_runtime_guidance_keys = list(payload.get("turn_state_guidance_prompt_keys") or [])
    hidden_environment_guidance_trigger_reasons = dict(payload.get("environment_guidance_trigger_reasons") or {})
    hidden_turn_state_guidance_trigger_reasons = dict(payload.get("turn_state_guidance_trigger_reasons") or {})
    payload["environment_prompt_refs"] = []
    payload["base_prompt_refs"] = []
    payload["overlay_prompt_refs"] = []
    payload["environment_guidance_prompt_refs"] = []
    payload["turn_state_guidance_prompt_refs"] = []
    payload["environment_guidance_prompt_keys"] = []
    payload["turn_state_guidance_prompt_keys"] = []
    payload["environment_guidance_trigger_reasons"] = {}
    payload["turn_state_guidance_trigger_reasons"] = {}
    diagnostics = dict(payload.get("diagnostics") or {})
    diagnostics.update(
        {
            "environment_prompt_visibility": "hidden",
            "hidden_environment_prompt_refs": hidden_refs,
            "hidden_base_prompt_refs": hidden_base_refs,
            "hidden_overlay_prompt_refs": hidden_overlay_refs,
            "hidden_environment_guidance_prompt_refs": hidden_environment_guidance_refs,
            "hidden_turn_state_guidance_prompt_refs": hidden_turn_state_guidance_refs,
            "hidden_environment_guidance_prompt_keys": hidden_guidance_keys,
            "hidden_turn_state_guidance_prompt_keys": hidden_runtime_guidance_keys,
            "hidden_environment_guidance_trigger_reasons": hidden_environment_guidance_trigger_reasons,
            "hidden_turn_state_guidance_trigger_reasons": hidden_turn_state_guidance_trigger_reasons,
            "authority": "runtime.prompt_policy",
        }
    )
    payload["diagnostics"] = diagnostics
    return payload


def _prompt_mount_plan_with_wiring_guidance(prompt_mount_plan: Any, wiring_plan: dict[str, Any]) -> Any:
    payload = dict(prompt_mount_plan.to_dict() if hasattr(prompt_mount_plan, "to_dict") else dict(prompt_mount_plan or {}))
    stable_slot = _prompt_wiring_slot_from_plan(wiring_plan, slot_name="environment_guidance_stable")
    runtime_slot = _prompt_wiring_slot_from_plan(wiring_plan, slot_name="environment_guidance_runtime")
    if stable_slot:
        stable_metadata = dict(stable_slot.get("metadata") or {})
        payload["environment_guidance_prompt_refs"] = list(_string_tuple(stable_slot.get("refs")))
        payload["environment_guidance_prompt_keys"] = list(_string_tuple(stable_metadata.get("environment_guidance_prompt_keys")))
        payload["environment_guidance_trigger_reasons"] = dict(stable_metadata.get("environment_guidance_trigger_reasons") or {})
    if runtime_slot:
        runtime_metadata = dict(runtime_slot.get("metadata") or {})
        payload["turn_state_guidance_prompt_refs"] = list(_string_tuple(runtime_slot.get("refs")))
        payload["turn_state_guidance_prompt_keys"] = list(_string_tuple(runtime_metadata.get("environment_guidance_prompt_keys")))
        payload["turn_state_guidance_trigger_reasons"] = dict(runtime_metadata.get("environment_guidance_trigger_reasons") or {})
    diagnostics = dict(payload.get("diagnostics") or {})
    diagnostics.update(
        {
            "environment_guidance_selector_authority": "prompt_library.wiring.build_runtime_prompt_wiring_plan",
            "prompt_wiring_plan_ref": str(dict(wiring_plan or {}).get("wiring_id") or ""),
            "environment_prompt_inventory_role": "environment_prompt_fact_adapter",
        }
    )
    payload["diagnostics"] = diagnostics
    return environment_prompt_inventory_from_payload(payload)


def _prompt_wiring_plan_manifest_payload(wiring_plan: dict[str, Any], *, prompt_policy: dict[str, Any]) -> dict[str, Any]:
    payload = dict(wiring_plan or {})
    if _prompt_policy_visible(prompt_policy, "environment_prompt_visibility", default=True):
        return payload
    hidden_slots: list[dict[str, Any]] = []
    visible_slots: list[dict[str, Any]] = []
    for raw_slot in list(payload.get("slots") or []):
        if not isinstance(raw_slot, dict):
            continue
        slot = dict(raw_slot)
        if str(slot.get("owner_layer") or "") == "environment":
            hidden_slots.append(slot)
            slot["refs"] = []
            metadata = dict(slot.get("metadata") or {})
            metadata["hidden_by_prompt_policy"] = "environment_prompt_visibility"
            slot["metadata"] = metadata
        visible_slots.append(slot)
    payload["slots"] = visible_slots
    diagnostics = dict(payload.get("diagnostics") or {})
    diagnostics.update(
        {
            "environment_prompt_visibility": "hidden",
            "hidden_environment_wiring_slots": hidden_slots,
            "authority": "runtime.prompt_policy",
        }
    )
    payload["diagnostics"] = diagnostics
    return payload


def _build_tool_catalog_manifest_for_mount_plan(
    *,
    invocation_kind: str,
    tool_payloads: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    source_ref: str,
    prompt_mount_plan: Any,
) -> ToolCatalogManifest:
    plan = (
        prompt_mount_plan.to_dict()
        if hasattr(prompt_mount_plan, "to_dict")
        else dict(prompt_mount_plan or {})
        if isinstance(prompt_mount_plan, dict)
        else {}
    )
    return build_tool_catalog_manifest(
        invocation_kind=invocation_kind,
        tool_payloads=tool_payloads,
        source_ref=source_ref,
        tool_guidance_prompt_defaults=_string_dict(plan.get("tool_guidance_prompt_defaults")),
        tool_guidance_prompt_overrides=_string_dict(plan.get("tool_guidance_prompt_overrides")),
    )


def _agent_work_role_refs_for_invocation(assembly_payload: dict[str, Any], *, invocation_kind: str) -> tuple[str, ...]:
    return _prompt_wiring_refs_for_slot(
        assembly_payload,
        invocation_kind=invocation_kind,
        slot_name="agent_work_role",
    )


def _prompt_mount_plan_payload_from_runtime_assembly(assembly_payload: dict[str, Any]) -> dict[str, Any]:
    explicit_plan = dict(assembly_payload.get("prompt_mount_plan") or {})
    if explicit_plan:
        return explicit_plan
    environment_payload = dict(assembly_payload.get("task_environment") or {})
    personality_prompt_refs = _string_tuple(assembly_payload.get("personality_prompt_refs"))
    profile_payload = dict(assembly_payload.get("profile") or {})
    prompt_policy = dict(profile_payload.get("prompt_policy") or assembly_payload.get("prompt_policy") or {})
    plan = build_base_environment_prompt_inventory(
        selected_environment=environment_payload,
        personality_prompt_refs=personality_prompt_refs,
        prompt_policy=prompt_policy,
    ).to_dict()
    diagnostics = dict(plan.get("diagnostics") or {})
    diagnostics.update(
        {
            "source": "runtime_assembly_without_prompt_mount_plan",
            "normalized_by": "harness.runtime.compiler",
        }
    )
    plan["diagnostics"] = diagnostics
    return plan


def _task_run_context_enabled(profile_payload: dict[str, Any]) -> bool:
    context_policy = dict(profile_payload.get("context_policy") or {})
    raw = context_policy.get("task_run_context", context_policy.get("task_context", True))
    if isinstance(raw, bool):
        return raw
    value = str(raw or "").strip().lower()
    return value not in {"disabled", "none", "off", "false", "0", "omitted"}


def _task_prompt_contract_from_runtime(
    *,
    task_run: dict[str, Any],
    contract: dict[str, Any],
    assembly_payload: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(contract.get("prompt_contract") or {})
    if not payload:
        return {}
    result = _normalize_prompt_contract(
        payload,
        contract_id=str(
            payload.get("contract_id")
            or contract.get("contract_id")
            or task_run.get("task_run_id")
            or "task_prompt_contract"
        ),
    )
    return result


def _graph_node_prompt_contract_from_runtime(
    *,
    task_run: dict[str, Any],
    contract: dict[str, Any],
    assembly_payload: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(
        _graph_slot_node_prompt_contract(contract)
        or dict(contract.get("graph_node_prompt_contract") or {})
    )
    if not payload:
        return {}
    return _normalize_prompt_contract(
        payload,
        contract_id=str(
            payload.get("contract_id")
            or payload.get("node_id")
            or contract.get("source_contract_ref")
            or task_run.get("task_id")
            or "graph_node_prompt_contract"
        ),
    )


def _normalize_prompt_contract(payload: dict[str, Any], *, contract_id: str) -> dict[str, Any]:
    normalized = {
        "contract_id": str(contract_id or payload.get("contract_id") or "").strip(),
        "contract_identity": str(payload.get("contract_identity") or contract_id or "prompt_contract"),
        "role_prompt": _first_runtime_text(payload.get("role_prompt")),
        "task_instruction": _first_runtime_text(payload.get("task_instruction")),
        "output_instruction": _first_runtime_text(payload.get("output_instruction")),
        "language_policy": payload.get("language_policy") if isinstance(payload.get("language_policy"), dict) else {},
        "forbidden_behavior": _string_list(payload.get("forbidden_behavior")),
        "definition_of_done": _string_list(payload.get("definition_of_done")),
    }
    for key in (
        "input_boundary_contract",
        "language_policy",
        "typed_submission_contract",
        "review_judgment_contract",
        "semantic_network_contract",
        "work_product_contract",
        "quality_gate_contract",
        "failure_handling_contract",
    ):
        value = payload.get(key)
        if _has_structured_prompt_contract_value(value):
            normalized[key] = value
    return normalized


def _has_structured_prompt_contract_value(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, (list, tuple)):
        return any(_has_structured_prompt_contract_value(item) if isinstance(item, (dict, list, tuple)) else bool(str(item or "").strip()) for item in value)
    return bool(str(value or "").strip())


def _first_runtime_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _planning_protocol_payload(
    *,
    invocation_kind: str,
    profile_payload: dict[str, Any],
    permission_mode: str,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    planning = dict(profile_payload.get("planning_policy") or {})
    contract_payload = dict(contract or {})
    raw_lock = contract_payload.get("implementation_lock")
    implementation_lock = dict(raw_lock) if isinstance(raw_lock, dict) else {}
    plan_ref = str(
        contract_payload.get("plan_ref")
        or contract_payload.get("approved_plan_ref")
        or implementation_lock.get("plan_ref")
        or ""
    ).strip()
    plan_mode = str(planning.get("plan_mode") or "").strip().lower()
    normalized_permission_mode = str(permission_mode or "default").strip().lower()
    plan_mode_active = normalized_permission_mode == "plan" or plan_mode in {
        "plan",
        "active",
        "required",
        "plan_only",
    }
    plan_required = bool(
        planning.get("requires_plan") is True
        or plan_mode_active
        or implementation_lock
        or str(contract_payload.get("plan_required") or "").strip().lower() in {"1", "true", "yes", "required"}
    )
    lock_status = str(implementation_lock.get("status") or "").strip().lower()
    plan_approved = bool(
        implementation_lock.get("approved") is True
        or lock_status in {"approved", "locked", "implementation_locked"}
        or contract_payload.get("plan_approved") is True
    )
    implementation_allowed = not plan_mode_active and (not plan_required or plan_approved or bool(plan_ref))
    mode = "plan_only" if plan_mode_active else ("implementation_locked" if plan_ref or implementation_lock else str(planning.get("plan_mode") or "available"))
    return _drop_empty_payload(
        {
            "mode": mode,
            "invocation_kind": str(invocation_kind or ""),
            "permission_mode": str(permission_mode or "default"),
            "plan_required": plan_required,
            "plan_mode_active": plan_mode_active,
            "plan_ref": plan_ref,
            "implementation_lock": implementation_lock,
            "implementation_allowed": implementation_allowed,
            "allowed_during_plan": [
                "respond_with_plan",
                "ask_user",
                "read_only_observation",
                "search",
                "request_task_run_with_plan_requirement",
            ],
            "forbidden_during_plan": [
                "workspace_edit(action=edit)",
                "workspace_edit(action=write)",
                "local_execution",
                "git_write",
                "deliverable_write",
                "claim_completed",
            ],
            "deviation_policy": "ask_user_or_block_before_changing_approved_plan",
            "authority": "harness.runtime.plan_mode_protocol",
        }
    )


def _runtime_projection_instruction(projection: dict[str, Any], *, validity_scope: str = "") -> str:
    if not projection:
        return ""
    allowed_actions = [
        str(item)
        for item in list(projection.get("allowed_action_types") or [])
        if str(item)
    ]
    tool_call_contract = dict(projection.get("tool_call_contract") or {})
    tool_action = dict(tool_call_contract.get("tool_action") or {})
    tool_boundary = dict(projection.get("tool_boundary") or {})
    try:
        visible_tool_count = int(tool_boundary.get("visible_tool_count") or 0)
    except (TypeError, ValueError):
        visible_tool_count = 0
    tool_action_available = bool(tool_action.get("available") is True) and bool(visible_tool_count > 0)
    allowed_text = "、".join(allowed_actions) if allowed_actions else "见 payload.allowed_action_types"
    action_ref = "tool_action" if tool_action_available else "assistant_or_control_action"
    notice = _runtime_control_context_notice(validity_scope=validity_scope)
    return _join_prompt_sections(
        notice,
        f"当前请求动作契约：动作={allowed_text}；工具行动={action_ref}；本段只列当前请求边界。\n",
    )


def _environment_stable_payload(environment_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(environment_payload or {})
    environment_boundary = dict(payload.get("environment_boundary") or {})
    prompt_refs = [
        str(item.get("prompt_id") or "").strip()
        for item in list(payload.get("environment_prompts") or [])
        if isinstance(item, dict) and str(item.get("prompt_id") or "").strip()
    ] or _string_tuple(environment_boundary.get("prompt_refs"))
    if "environment_prompts" in payload:
        payload["environment_prompts"] = [
            {
                "prompt_id": prompt_ref,
                "content_omitted": True,
                "content_source": "prompt_library",
            }
            for prompt_ref in prompt_refs
        ]
    return payload


def _environment_model_visible_payload(
    environment_payload: dict[str, Any],
    *,
    prompt_mount_plan: dict[str, Any] | None = None,
    include_runtime_storage_roots: bool = False,
) -> dict[str, Any]:
    payload = dict(environment_payload or {})
    storage = dict(payload.get("storage_space") or {})
    sandbox = dict(payload.get("sandbox_policy") or {})
    execution = dict(payload.get("execution_policy") or {})
    file_management = dict(payload.get("file_management") or {})
    environment_boundary = dict(payload.get("environment_boundary") or {})
    boundary_contract = dict(environment_boundary.get("boundary_contract") or {})
    mount_plan = environment_prompt_inventory_from_payload(prompt_mount_plan)
    prompt_refs = mount_plan.environment_prompt_refs or _string_tuple(environment_boundary.get("prompt_refs")) or tuple(
        str(item.get("prompt_id") or "").strip()
        for item in list(payload.get("environment_prompts") or [])
        if isinstance(item, dict) and str(item.get("prompt_id") or "").strip()
    )
    model_payload = {
        "title": str(payload.get("title") or ""),
        "environment_kind": str(payload.get("environment_kind") or ""),
        "storage": _drop_empty_payload(
            {
                "artifact_workspace_available": bool(storage.get("artifact_root")),
                "persistent_storage_available": bool(storage.get("environment_storage_root")),
                "cache_available": bool(storage.get("cache_root")),
            }
        ),
        "resource_boundary": _drop_empty_payload(
            {
                "workspace_access": str(sandbox.get("workspace_access") or execution.get("real_workspace_access") or ""),
                "write_policy": str(sandbox.get("write_policy") or execution.get("write_scope_policy") or ""),
                "shell_policy": str(sandbox.get("shell_policy") or execution.get("shell_execution_policy") or ""),
                "browser_policy": str(sandbox.get("browser_policy") or execution.get("browser_execution_policy") or ""),
                "network_policy": str(sandbox.get("network_policy") or execution.get("network_execution_policy") or ""),
                "canonical_write_policy": str(file_management.get("canonical_write_policy") or ""),
            }
        ),
        "prompt_mount_summary": _drop_empty_payload(
            {
                "environment_prompt_count": len(prompt_refs),
                "base_prompt_count": len(mount_plan.base_prompt_refs),
                "overlay_prompt_count": len(mount_plan.overlay_prompt_refs),
                "environment_guidance_prompt_count": len(mount_plan.environment_guidance_prompt_refs),
                "personality_prompt_count": len(mount_plan.personality_prompt_refs),
            }
        ),
        "boundary_contract": _drop_empty_payload(
            {
                "environment_prompts_source": str(boundary_contract.get("environment_prompts_source") or ""),
                "environment_prompt_role": str(boundary_contract.get("environment_prompt_role") or ""),
            }
        ),
    }
    _ = include_runtime_storage_roots
    return _drop_empty_payload(model_payload)


def _memory_context_model_visible_payload(memory_context: Any) -> dict[str, Any]:
    if not isinstance(memory_context, dict):
        return {}
    sections = memory_context.get("model_visible_sections")
    if not isinstance(sections, dict):
        sections = {}
    allowed_sections = (
        "active_process_context",
        "hot_truth_window",
        "retrieval_evidence",
        "warm_snapshots",
        "exact_durable_context",
        "relevant_durable_context",
    )
    visible_sections = {
        section: [
            str(item).strip()
            for item in list(sections.get(section) or [])
            if str(item).strip()
        ]
        for section in allowed_sections
    }
    visible_sections = {section: items for section, items in visible_sections.items() if items}
    status = dict(memory_context.get("memory_context_status") or {}) if isinstance(memory_context.get("memory_context_status"), dict) else {}
    diagnostics = dict(memory_context.get("diagnostics") or {}) if isinstance(memory_context.get("diagnostics"), dict) else {}
    if not visible_sections and not status and not diagnostics:
        return {}
    has_visible_records = bool(visible_sections) or bool(status.get("has_model_visible_records") is True)
    return _drop_empty_payload(
        {
            "model_visible_sections": visible_sections,
            "selected_sections": [
                str(item)
                for item in list(memory_context.get("selected_sections") or visible_sections.keys())
                if str(item)
            ],
            "memory_context_status": _drop_empty_payload(
                {
                    "status": "available" if has_visible_records else str(status.get("status") or "empty"),
                    "has_visible_records": has_visible_records,
                    "visible_section_count": len(visible_sections),
                    "agent_use_contract": str(
                        status.get("agent_use_contract")
                        or "Use listed memory records when present; if none are listed, do not infer facts from memory."
                    ),
                }
            ),
            "requires_verification_before_use": True,
        }
    )


def _runtime_memory_context_source_ref(payload: dict[str, Any] | None) -> str:
    data = dict(payload or {})
    for key in ("memory_runtime_view_ref", "context_package_ref"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    selected = ",".join(str(item) for item in list(data.get("selected_sections") or []) if str(item).strip())
    if selected:
        return f"runtime_memory_context:{_short_hash(selected)}"
    return "runtime_memory_context"


_RUNTIME_BASELINE_REF_KEYS = (
    "agent_profile_ref",
    "task_environment_ref",
)


def _runtime_baseline_refs_model_visible_payload(dynamic_context: DynamicContextProjection) -> dict[str, Any]:
    refs = dict(getattr(dynamic_context, "stable_runtime_baseline_refs", {}) or {})
    baseline_refs = {
        key: refs.get(key)
        for key in _RUNTIME_BASELINE_REF_KEYS
        if refs.get(key) not in ("", None, [], {})
    }
    if not baseline_refs:
        return {}
    return {
        "context_continuity": {
            "stable_agent_role_present": bool(baseline_refs.get("agent_profile_ref")),
            "stable_environment_contract_present": bool(baseline_refs.get("task_environment_ref")),
            "current_request_context": "Current action and execution facts are provided later in the current request context.",
        }
    }


def _runtime_baseline_refs_source_ref(payload: dict[str, Any] | None) -> str:
    refs = dict(dict(payload or {}).get("runtime_baseline_refs") or {})
    value = "|".join(
        str(refs.get(key) or "").strip()
        for key in ("agent_profile_ref", "task_environment_ref")
        if str(refs.get(key) or "").strip()
    )
    if value:
        return "runtime_baseline_refs:" + _short_hash(value)
    return "runtime_baseline_refs"


def _read_evidence_prompt_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    if not data:
        return {}
    meaningful = (
        bool(data.get("read_evidence_refs"))
        or bool(data.get("read_required_windows"))
        or bool(data.get("read_evidence_injections"))
        or bool(data.get("visible_exact_in_packet") is True)
    )
    if not meaningful:
        return {}
    data.pop("packet_id", None)
    return _drop_empty_payload(data)


def _read_evidence_current_prompt_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    if not data:
        return {}
    injections = [
        _drop_empty_payload(dict(item))
        for item in list(data.get("read_evidence_injections") or [])
        if isinstance(item, dict)
    ]
    read_required = [
        _drop_empty_payload(dict(item))
        for item in list(data.get("read_required_windows") or [])
        if isinstance(item, dict)
    ]
    injections = [item for item in injections if item]
    read_required = [item for item in read_required if item]
    if not injections and not read_required:
        return {}
    current_payload = {
        "visible_exact_in_packet": bool(injections),
        "read_evidence_injections": injections,
        "read_required_windows": read_required,
        "projection_policy": dict(data.get("projection_policy") or {}),
    }
    if injections:
        refs = [
            _drop_empty_payload(dict(item))
            for item in list(data.get("read_evidence_refs") or [])
            if isinstance(item, dict)
        ]
        current_payload["read_evidence_refs"] = [item for item in refs if item]
    return _drop_empty_payload(current_payload)


def _read_evidence_prompt_source_ref(payload: dict[str, Any] | None, *, fallback: str) -> str:
    data = dict(payload or {})
    if not data:
        return str(fallback or "read_evidence_injection")
    return f"read_evidence:{_stable_json_hash(data).removeprefix('sha256:')[:16]}"


def _read_evidence_injection_append_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    current_payload = _read_evidence_current_prompt_payload(payload)
    return _current_append_fact_metadata(
        kind="read_evidence_injection",
        payload=current_payload,
        semantic_slot="current_exact_evidence",
        semantic_rank=41,
        origin_ref=_read_evidence_injection_origin_ref(current_payload),
        package="evidence_context",
        stream="current_exact_evidence",
        semantic_commit_class="current_exact_evidence_fact",
    )


def _read_evidence_injection_origin_ref(payload: dict[str, Any] | None) -> str:
    data = dict(payload or {})
    anchors: list[dict[str, Any]] = []
    for collection, window_type in (
        ("read_evidence_injections", "exact"),
        ("read_required_windows", "read_required"),
    ):
        for item in list(data.get(collection) or [])[:8]:
            if not isinstance(item, dict):
                continue
            anchors.append(
                _drop_empty_payload(
                    {
                        "window_type": window_type,
                        "path": str(item.get("path") or "").replace("\\", "/"),
                        "start_line": item.get("start_line"),
                        "end_line": item.get("end_line"),
                    }
                )
            )
    anchors = [item for item in anchors if item]
    if not anchors:
        return ""
    return "read_evidence_window:" + _stable_json_hash({"anchors": anchors}).removeprefix("sha256:")[:16]


def _active_skill_instruction(*, base_dir: Path, assembly_payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    skill_activation = dict(assembly_payload.get("skill_activation") or {})
    selected_skill_ids = [
        str(item).strip()
        for item in list(skill_activation.get("selected_skill_ids") or [])
        if str(item).strip()
    ]
    if not selected_skill_ids:
        return "", {"accepted_skill_ids": [], "rejected_skill_ids": [], "source_refs": []}
    try:
        return expand_selected_skill_bodies(
            base_dir=base_dir,
            skill_runtime_views=[
                dict(item)
                for item in list(assembly_payload.get("skill_runtime_views") or [])
                if isinstance(item, dict)
            ],
            selected_skill_ids=selected_skill_ids,
        )
    except Exception:
        return "", {
            "accepted_skill_ids": [],
            "rejected_skill_ids": selected_skill_ids,
            "source_refs": [],
            "error": "skill_expansion_failed",
        }


def _capability_directory_model_visible_payload(assembly_payload: dict[str, Any]) -> dict[str, Any]:
    directory = dict(assembly_payload.get("capability_directory") or {})
    groups = [
        _drop_empty_payload(
            {
                "group_id": str(item.get("group_id") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "use_when": str(item.get("use_when") or "").strip(),
                "tool_namespaces": [
                    str(value).strip()
                    for value in list(item.get("tool_namespaces") or [])
                    if str(value).strip()
                ],
                "candidate_tools": [
                    {
                        "tool_name": str(tool.get("tool_name") or "").strip(),
                        "read_only": bool(tool.get("read_only") is True),
                    }
                    for tool in list(item.get("candidate_tools") or [])
                    if isinstance(tool, dict) and str(tool.get("tool_name") or "").strip()
                ],
                "candidate_skills": [
                    {
                        "skill_id": str(skill.get("skill_id") or "").strip(),
                        "title": str(skill.get("title") or "").strip(),
                    }
                    for skill in list(item.get("candidate_skills") or [])
                    if isinstance(skill, dict) and str(skill.get("skill_id") or "").strip()
                ],
                "loading_mode": str(item.get("loading_mode") or "").strip(),
                "contract_requested": bool(item.get("contract_requested") is True),
            }
        )
        for item in list(directory.get("capability_groups") or [])
        if isinstance(item, dict) and str(item.get("group_id") or "").strip()
    ]
    if not groups:
        return {}
    return _drop_empty_payload(
        {
            "capability_groups": groups,
            "requested_capability_groups": [
                str(item).strip()
                for item in list(directory.get("requested_capability_groups") or [])
                if str(item).strip()
            ],
            "preferred_tool_namespaces": [
                str(item).strip()
                for item in list(directory.get("preferred_tool_namespaces") or [])
                if str(item).strip()
            ],
            "tool_search_available": bool(directory.get("tool_search_available") is True),
            "skill_selection_available": bool(directory.get("skill_selection_available") is True),
            "authority": str(directory.get("authority") or "harness.runtime.capability_directory"),
        }
    )


def _capability_catalog_payload(value: Any) -> dict[str, Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    groups: list[dict[str, Any]] = []
    for item in list(payload.get("capability_groups") or []):
        if not isinstance(item, dict):
            continue
        group_id = str(item.get("group_id") or "").strip()
        if not group_id:
            continue
        candidate_tools = [
            dict(tool)
            for tool in list(item.get("candidate_tools") or [])
            if isinstance(tool, dict) and str(tool.get("tool_name") or "").strip()
        ]
        candidate_skills = [
            dict(skill)
            for skill in list(item.get("candidate_skills") or [])
            if isinstance(skill, dict) and str(skill.get("skill_id") or "").strip()
        ]
        if group_id != "general_task" and not candidate_tools and not candidate_skills:
            continue
        groups.append(
            _drop_empty_payload(
                {
                    "group_id": group_id,
                    "title": str(item.get("title") or "").strip(),
                    "use_when": str(item.get("use_when") or "").strip(),
                    "tool_namespaces": [
                        str(value).strip()
                        for value in list(item.get("tool_namespaces") or [])
                        if str(value).strip()
                    ],
                    "candidate_tools": candidate_tools,
                    "candidate_skills": candidate_skills,
                    "loading_mode": str(item.get("loading_mode") or "").strip(),
                }
            )
        )
    return _drop_empty_payload(
        {
            "capability_groups": groups,
            "skill_selection_available": bool(payload.get("skill_selection_available") is True),
            "authority": str(payload.get("authority") or "harness.runtime.capability_directory"),
        }
    )


def _capability_routing_payload(value: Any) -> dict[str, Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    return _drop_empty_payload(
        {
            "requested_capability_groups": [
                str(item).strip()
                for item in list(payload.get("requested_capability_groups") or [])
                if str(item).strip()
            ],
            "preferred_tool_namespaces": [
                str(item).strip()
                for item in list(payload.get("preferred_tool_namespaces") or [])
                if str(item).strip()
            ],
            "tool_search_available": bool(payload.get("tool_search_available") is True),
            "authority": str(payload.get("authority") or "harness.runtime.capability_directory"),
        }
    )


def _capability_catalog_source_ref(payload: dict[str, Any]) -> str:
    return "capability_catalog:" + _stable_json_hash(payload).removeprefix("sha256:")[:20]


def _compact_text(value: Any, *, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _short_hash(value: str, *, prefix_chars: int = 10) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("sha256:"):
        return "sha256:" + text.removeprefix("sha256:")[:prefix_chars]
    return text[:prefix_chars]


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _graph_slot_from_contract(contract: dict[str, Any]) -> dict[str, Any]:
    graph_slot = dict(dict(contract or {}).get("graph_slot") or {})
    if graph_slot:
        return graph_slot
    diagnostics = dict(dict(contract or {}).get("diagnostics") or {})
    return dict(diagnostics.get("graph_slot") or {})


def _graph_slot_node_prompt_contract(contract: dict[str, Any]) -> dict[str, Any]:
    graph_slot = _graph_slot_from_contract(contract)
    node_contract = dict(graph_slot.get("node_contract") or {})
    return dict(node_contract.get("prompt_contract") or {})


def _graph_node_model_context_projection(graph_slot: dict[str, Any]) -> dict[str, Any]:
    slot = dict(graph_slot or {})
    if not slot:
        return {}
    node_contract = dict(slot.get("node_contract") or {})
    edge_contracts = dict(slot.get("edge_contracts") or {})
    memory_contract = dict(slot.get("memory_contract") or {})
    loop_contract = dict(slot.get("loop_contract") or {})
    output_contract = dict(slot.get("output_contract") or {})
    node_identity = dict(node_contract.get("node_identity") or {})
    return _drop_empty_payload(
        {
            "node": _graph_node_prompt_context(node_contract=node_contract, node_identity=node_identity),
            "authorized_inputs": _graph_authorized_inputs(edge_contracts.get("inbound_edge_contexts")),
            "memory": _graph_visible_memory_snapshots(memory_contract),
            "loop": _graph_visible_loop_context(loop_contract),
            "output": _graph_visible_output_requirements(output_contract),
            "constraints": _graph_visible_constraints(node_contract=node_contract, output_contract=output_contract),
            "visibility": {
                "runtime_contract_details_omitted": True,
                "system_control_fields_omitted": True,
                "authority": "harness.runtime.graph_node_context.visibility",
            },
            "authority": "harness.runtime.graph_node_model_context",
        }
    )


def _graph_node_completion_prefix(
    graph_slot: dict[str, Any],
    *,
    invocation_kind: str = "",
    allowed_action_types: tuple[str, ...] = (),
) -> str:
    slot = dict(graph_slot or {})
    if not slot:
        return ""
    node_contract = dict(slot.get("node_contract") or {})
    completion_profile = dict(node_contract.get("completion_profile") or {})
    if str(completion_profile.get("mode") or "").strip() != "chat_prefix":
        return ""
    allowed = {str(item or "").strip() for item in tuple(allowed_action_types or ()) if str(item or "").strip()}
    if "model_response" not in allowed:
        return ""
    profile_invocation_kind = str(completion_profile.get("invocation_kind") or "").strip()
    if profile_invocation_kind and profile_invocation_kind != str(invocation_kind or "").strip():
        return ""
    template = str(completion_profile.get("assistant_prefix_template") or "").strip()
    if not template:
        return ""
    loop_contract = dict(slot.get("loop_contract") or {})
    variables = dict(loop_contract.get("variables") or {})
    try:
        return template.format_map(_SafeFormatMap(variables))
    except (KeyError, IndexError, ValueError):
        return template


class _SafeFormatMap(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _graph_node_stable_contract_context(graph_slot: dict[str, Any]) -> dict[str, Any]:
    slot = dict(graph_slot or {})
    if not slot:
        return {}
    node_contract = dict(slot.get("node_contract") or {})
    edge_contracts = dict(slot.get("edge_contracts") or {})
    output_contract = dict(slot.get("output_contract") or {})
    node_identity = dict(node_contract.get("node_identity") or {})
    return _drop_empty_payload(
        {
            "node": _drop_empty_payload(
                {
                    "title": str(node_identity.get("title") or ""),
                    "node_type": str(node_identity.get("node_type") or ""),
                    "node_id": str(node_identity.get("node_id") or ""),
                    "authority": "harness.runtime.graph_node_context.node_identity",
                }
            ),
            "authorized_input_slots": _graph_authorized_input_stable_refs(edge_contracts.get("inbound_edge_contexts")),
            "output": _graph_visible_output_requirements(output_contract),
            "constraints": _graph_visible_constraints(node_contract=node_contract, output_contract=output_contract),
            "visibility": {
                "authorized_input_content_lives_in": "Task execution graph node current context",
                "stable_contract_is_cache_prefix_safe": True,
                "authority": "harness.runtime.graph_node_context.stable_visibility",
            },
            "authority": "harness.runtime.graph_node_stable_contract_context",
        }
    )


def _graph_agent_function_shared_stable_payload(contract: dict[str, Any]) -> dict[str, Any]:
    graph_slot = _graph_slot_from_contract(dict(contract or {}))
    if not graph_slot:
        return {}
    node_contract = dict(dict(graph_slot or {}).get("node_contract") or {})
    node_identity = dict(node_contract.get("node_identity") or {})
    family = _graph_agent_role_family(node_identity=node_identity)
    if not family:
        return {}
    payload = _drop_empty_payload(
        {
            "role_family": family,
            "function_contract": _graph_agent_function_contract(family),
            "handoff_boundary": {
                "read_authorized_inputs_only": True,
                "do_not_invent_missing_upstream_content": True,
                "do_not_request_tools_for_hidden_graph_state": True,
                "write_complete_final_answer_for_runtime_materialization": True,
                "authority": "harness.runtime.agent_function_shared.handoff_boundary",
            },
            "authority": "harness.runtime.agent_function_shared_context.model_visible",
        }
    )
    if not payload:
        return {}
    payload["shared_context_hash"] = _short_hash(_stable_json_hash(payload))
    return {"agent_function_shared_context": payload}


def _graph_agent_role_family(*, node_identity: dict[str, Any]) -> str:
    node_type = str(node_identity.get("node_type") or "").strip().lower()
    node_id = str(node_identity.get("node_id") or "").strip().lower()
    haystack = f"{node_type} {node_id}"
    if "memory_commit" in haystack or "memory_finalize" in haystack or "memory_steward" in haystack:
        return "memory_steward"
    if "review" in haystack or "review_gate" in haystack or "monitor" in haystack:
        return "reviewer"
    if "self_repair" in haystack or "repair" in haystack:
        return "self_repair_writer"
    return "creator"


def _graph_agent_function_contract(role_family: str) -> dict[str, Any]:
    contracts = {
        "creator": {
            "identity": "你是一名创作型写作节点执行者。",
            "primary_duty": "根据上游交接、项目约束和当前节点目标产出新的设计、大纲或正文候选。",
            "boundaries": [
                "不得替审核节点下通过、返修或拒绝裁决。",
                "不得把未审核候选写成最终 canon。",
                "不得越过当前节点目标扩写其它阶段内容。",
            ],
            "quality_bar": "商业长篇网文标准：设定清晰、冲突明确、可连续扩展、避免空泛说明。",
        },
        "self_repair_writer": {
            "identity": "你是一名单节点自修写手。",
            "primary_duty": "只基于候选稿、审核意见和授权参照完成一次自修，交付可继续流转的修订稿。",
            "boundaries": [
                "不得推翻上游大纲层级和已审核事实。",
                "不得新增与审核意见无关的大范围重构。",
                "不得替审核节点做最终通过裁决。",
            ],
            "quality_bar": "优先修复明确问题，保持原任务目标、语义连续性和交付格式稳定。",
        },
        "reviewer": {
            "identity": "你是一名质量审核员。",
            "primary_duty": "评审当前候选是否满足合同、上游设定和连贯性要求，并给出明确裁决。",
            "boundaries": [
                "不得替创作者扩写正文或重写候选稿。",
                "不得越过当前审核对象审查无关节点。",
                "发现明显矛盾、缺漏或层级越权时必须指出并要求返修。",
            ],
            "quality_bar": "以商业可读性、设定一致性、层级服从、语义连续性和可执行返修意见为标准。",
        },
        "memory_steward": {
            "identity": "你是一名写作记忆管家。",
            "primary_duty": "只把已审核通过或明确允许提交的内容整理成稳定记忆、索引和可追踪引用。",
            "boundaries": [
                "不得把候选稿、未通过裁决或推测内容写成 canon。",
                "不得创作新剧情、新设定或替审核节点裁决。",
                "必须保留来源、适用范围和不可覆盖边界。",
            ],
            "quality_bar": "记忆条目要准确、可检索、可追溯、避免重复和互相矛盾。",
        },
    }
    return {
        **dict(contracts.get(role_family) or contracts["creator"]),
        "authority": "harness.runtime.agent_function_shared.contract",
    }


def _graph_task_shared_stable_payload(contract: dict[str, Any]) -> dict[str, Any]:
    payload = dict(contract or {})
    graph_slot = _graph_slot_from_contract(payload)
    if not graph_slot:
        return {}
    slot = dict(graph_slot or {})
    shared_context = _drop_empty_payload(
        {
            "contract_id": "graph_node_shared_context",
            "contract_source": str(payload.get("contract_source") or "graph_node_work_order"),
            "task_environment_id": str(payload.get("task_environment_id") or ""),
            "graph_task": _graph_task_shared_identity(slot),
            "execution_contract_boundary": {
                "node_local_contract_follows": True,
                "authorized_inputs_are_node_local": True,
                "memory_snapshots_are_node_local": True,
                "loop_variables_are_node_local": True,
                "output_targets_are_node_local": True,
                "authority": "harness.runtime.graph_task_shared.boundary",
            },
            "authority": "harness.runtime.graph_task_shared_context.model_visible",
        }
    )
    if not shared_context:
        return {}
    shared_context["shared_context_hash"] = _short_hash(_stable_json_hash(shared_context))
    return {"graph_shared_context": shared_context}


def _graph_task_shared_identity(graph_slot: dict[str, Any]) -> dict[str, Any]:
    identity = dict(graph_slot.get("graph_identity") or {})
    return _drop_empty_payload(
        {
            "graph_id": str(identity.get("graph_id") or ""),
            "config_id": str(identity.get("config_id") or ""),
            "authority": "harness.runtime.graph_task_shared.identity",
        }
    )


def _graph_node_prompt_context(*, node_contract: dict[str, Any], node_identity: dict[str, Any]) -> dict[str, Any]:
    prompt = dict(node_contract.get("prompt_contract") or {})
    normalized = _normalize_prompt_contract(
        prompt,
        contract_id=str(node_identity.get("node_id") or prompt.get("contract_id") or "graph_node_prompt"),
    )
    return _drop_empty_payload(
        {
            "title": str(node_identity.get("title") or ""),
            "node_type": str(node_identity.get("node_type") or ""),
            "role_prompt": normalized.get("role_prompt") or "",
            "task_instruction": normalized.get("task_instruction") or "",
            "output_instruction": normalized.get("output_instruction") or "",
            "forbidden_behavior": list(normalized.get("forbidden_behavior") or []),
            "definition_of_done": list(normalized.get("definition_of_done") or []),
            "authority": "harness.runtime.graph_node_context.node",
        }
    )


def _graph_authorized_inputs(value: Any) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    for item in _inbound_context_stable_payload(value):
        slot = str(item.get("target_input_slot") or item.get("target_context_key") or "").strip()
        label = slot or str(item.get("target_context_key") or "").strip()
        payload = dict(item.get("payload") or {})
        primary_content = _authorized_input_content(payload)
        artifact_refs = _model_visible_artifact_refs(item.get("artifact_refs"))
        memory_refs = _model_visible_ref_summaries(item.get("memory_refs"), limit=8)
        inputs.append(
            _drop_empty_payload(
                {
                    "slot": slot,
                    "label": label,
                    "packet_type": str(item.get("packet_type") or ""),
                    "content": primary_content,
                    "payload": _authorized_input_payload(payload, primary_content=primary_content),
                    "artifact_refs": artifact_refs,
                    "memory_refs": memory_refs,
                    "authority": "harness.runtime.graph_node_context.authorized_input",
                }
            )
        )
    return inputs


def _graph_authorized_input_stable_refs(value: Any) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    for item in _inbound_context_stable_payload(value):
        slot = str(item.get("target_input_slot") or item.get("target_context_key") or "").strip()
        label = slot or str(item.get("target_context_key") or "").strip()
        inputs.append(
            _drop_empty_payload(
                {
                    "slot": slot,
                    "label": label,
                    "packet_type": str(item.get("packet_type") or ""),
                    "artifact_refs": _model_visible_artifact_refs(item.get("artifact_refs")),
                    "memory_refs": _model_visible_ref_summaries(item.get("memory_refs"), limit=8),
                    "content_omitted_reason": "available_in_graph_node_runtime_context",
                    "authority": "harness.runtime.graph_node_context.authorized_input_stable_ref",
                }
            )
        )
    return inputs


def _authorized_input_payload(payload: dict[str, Any], *, primary_content: str = "") -> dict[str, Any]:
    allowed: dict[str, Any] = {}
    for key in (
        "initial_inputs",
        "title",
        "project_id",
        "graph_id",
        "loop_iteration_results",
        "batch_chapter_ledger",
        "source_error",
        "quality_acceptance",
        "quality_issue_summary",
        "issues",
    ):
        if key in payload:
            allowed[key] = payload.get(key)
    if isinstance(payload.get("artifact_payloads"), list):
        artifact_payload_limit = _GRAPH_LOOP_ARTIFACT_PAYLOAD_LIMIT if isinstance(payload.get("loop_iteration_results"), list) else _GRAPH_ARTIFACT_PAYLOAD_LIMIT
        allowed["artifact_payloads"] = [
            _bounded_artifact_payload_for_authorized_input(dict(item), primary_content=primary_content)
            for item in list(payload.get("artifact_payloads") or [])[:artifact_payload_limit]
            if isinstance(item, dict)
        ]
    return _truncate_value(allowed, max_chars=_GRAPH_AUTHORIZED_INPUT_PAYLOAD_LIMIT) if allowed else {}


def _bounded_artifact_payload_for_authorized_input(item: dict[str, Any], *, primary_content: str) -> dict[str, Any]:
    bounded = _bounded_artifact_payload(item)
    content = str(bounded.get("content") or "").strip()
    visible = str(primary_content or "").strip()
    if content and visible and (content == visible or content in visible):
        bounded.pop("content", None)
        bounded["content_omitted_reason"] = "duplicate_of_authorized_input_content"
    return bounded


def _authorized_input_content(payload: dict[str, Any]) -> str:
    for key in ("content", "text", "handoff_summary", "summary"):
        text = str(payload.get(key) or "").strip()
        if text:
            return text[:_GRAPH_AUTHORIZED_INPUT_CONTENT_LIMIT]
    artifact_payloads = [dict(item) for item in list(payload.get("artifact_payloads") or []) if isinstance(item, dict)]
    parts = [str(item.get("content") or item.get("text") or "").strip() for item in artifact_payloads]
    joined = "\n\n".join(part for part in parts if part)
    return joined[:_GRAPH_AUTHORIZED_INPUT_CONTENT_LIMIT]


def _model_visible_artifact_refs(value: Any) -> list[dict[str, Any]]:
    return model_visible_artifact_refs(value, limit=8, summary_limit=1000)


def _model_visible_ref_summaries(value: Any, *, limit: int) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in _bounded_dict_list(value, limit=limit):
        refs.append(
            _drop_empty_payload(
                {
                    "label": str(item.get("label") or item.get("title") or item.get("collection_id") or ""),
                    "summary": str(item.get("summary") or item.get("payload_summary") or "")[:1000],
                }
            )
        )
    return refs


def _graph_visible_memory_snapshots(memory_contract: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for item in list(memory_contract.get("resolved_snapshots") or [])[:_GRAPH_MEMORY_SNAPSHOT_LIMIT]:
        if isinstance(item, dict):
            snapshots.append(_graph_visible_memory_snapshot(dict(item)))
    return snapshots


def _graph_visible_memory_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    records = snapshot.get("records") or snapshot.get("items") or snapshot.get("memories") or []
    visible_records: list[dict[str, Any]] = []
    for item in list(records)[:_GRAPH_MEMORY_RECORD_LIMIT]:
        if not isinstance(item, dict):
            continue
        visible_records.append(
            _drop_empty_payload(
                {
                    "title": str(item.get("title") or item.get("label") or ""),
                    "summary": str(item.get("summary") or "")[:1000],
                    "content": str(item.get("canonical_text") or item.get("content") or item.get("text") or "")[:_GRAPH_MEMORY_RECORD_TEXT_LIMIT],
                }
            )
        )
    return _drop_empty_payload(
        {
            "label": str(snapshot.get("label") or snapshot.get("title") or snapshot.get("collection_id") or snapshot.get("collection") or ""),
            "collection": str(snapshot.get("collection_id") or snapshot.get("collection") or ""),
            "summary": str(snapshot.get("summary") or "")[:2000],
            "records": visible_records,
            "visibility": str(snapshot.get("visibility") or snapshot.get("state") or ""),
            "authority": "harness.runtime.graph_node_context.memory_snapshot",
        }
    )


def _graph_visible_loop_context(loop_contract: dict[str, Any]) -> dict[str, Any]:
    variables = dict(loop_contract.get("variables") or {})
    allowed = {
        key: variables.get(key)
        for key in (
            "volume_index",
            "chapter_index",
            "unit_index",
            "batch_index",
            "batch_start_index",
            "batch_end_index",
            "batch_chapter_range",
            "target_measure_units",
            "unit_target_measure",
            "units_per_batch",
            "completed_groups",
            "group_current_measure",
            "total_current_measure",
            "metric_label",
        )
        if key in variables
    }
    active_frame = dict(dict(loop_contract.get("loop_context") or {}).get("active_frame") or {})
    if active_frame:
        allowed["active_frame"] = _truncate_value(active_frame, max_chars=4000)
    loop_context = dict(loop_contract.get("loop_context") or {})
    return _drop_empty_payload(
        {
            "variables": _truncate_value(allowed, max_chars=8000),
            "iteration_results": _graph_visible_loop_iteration_results(loop_context.get("iteration_results")),
            "authority": "harness.runtime.graph_node_context.loop",
        }
    )


def _graph_visible_loop_iteration_results(value: Any) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for frame_id, raw_frame_results in list(dict(value or {}).items())[-_GRAPH_LOOP_FRAME_LIMIT:]:
        if not isinstance(raw_frame_results, dict):
            continue
        iterations: list[dict[str, Any]] = []
        for iteration_id, raw_node_results in list(raw_frame_results.items())[-_GRAPH_LOOP_ITERATION_LIMIT:]:
            if not isinstance(raw_node_results, dict):
                continue
            node_results: list[dict[str, Any]] = []
            for node_id, raw_summary in list(raw_node_results.items())[:_GRAPH_LOOP_NODE_RESULT_LIMIT]:
                if not isinstance(raw_summary, dict):
                    continue
                summary = dict(raw_summary)
                node_results.append(
                    _drop_empty_payload(
                        {
                            "node_id": str(node_id or summary.get("node_id") or ""),
                            "status": str(summary.get("status") or ""),
                            "result_ref": str(summary.get("result_ref") or ""),
                            "artifact_refs": _model_visible_artifact_refs(summary.get("artifact_refs")),
                            "handoff_summary": str(summary.get("handoff_summary") or "")[:800],
                        }
                    )
                )
            if node_results:
                iterations.append(
                    {
                        "iteration_id": str(iteration_id or ""),
                        "node_results": node_results,
                    }
                )
        if iterations:
            frames.append(
                {
                    "frame_id": str(frame_id or ""),
                    "iterations": iterations,
                }
            )
    return frames


def _graph_visible_output_requirements(output_contract: dict[str, Any]) -> dict[str, Any]:
    output_policy = dict(output_contract.get("output_policy") or {})
    expected = dict(output_contract.get("expected_result_contract") or {})
    targets = _visible_output_targets(output_policy=output_policy, expected=expected)
    required_sections = _string_list(output_policy.get("required_sections") or expected.get("required_sections"))
    return _drop_empty_payload(
        {
            "output_contract_id": str(output_policy.get("output_contract_id") or expected.get("output_contract_id") or ""),
            "artifact_paths": targets,
            "required_sections": required_sections,
            "candidate_state": str(dict(output_policy.get("state_boundary") or {}).get("candidate_state") or ""),
            "primary_content_key": str(output_policy.get("primary_content_key") or ""),
            "authority": "harness.runtime.graph_node_context.output",
        }
    )


def _visible_output_targets(*, output_policy: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    candidates: list[Any] = []
    candidates.extend(list(output_policy.get("artifact_targets") or []))
    candidates.extend(list(output_policy.get("artifacts") or []))
    candidates.extend(list(expected.get("artifact_targets") or []))
    candidates.extend(list(expected.get("artifact_refs") or []))
    result: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if isinstance(item, dict):
            path = str(item.get("path") or item.get("artifact_path") or item.get("target_path") or "").strip()
        else:
            path = str(item or "").strip()
        if path and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _graph_visible_constraints(*, node_contract: dict[str, Any], output_contract: dict[str, Any]) -> list[str]:
    constraints: list[str] = []
    prompt = dict(node_contract.get("prompt_contract") or {})
    constraints.extend(_string_list(prompt.get("forbidden_behavior")))
    expected = dict(output_contract.get("expected_result_contract") or {})
    constraints.extend(_string_list(expected.get("constraints")))
    output_policy = dict(output_contract.get("output_policy") or {})
    constraints.extend(_string_list(output_policy.get("constraints")))
    return _dedupe_strings(constraints)


def _dedupe_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in list(values or []):
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _inbound_context_stable_payload(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in list(value or []):
        if not isinstance(item, dict):
            continue
        payload = dict(item.get("payload") or {})
        items.append(
            {
                "packet_type": str(item.get("packet_type") or ""),
                "source_node_id": str(item.get("source_node_id") or ""),
                "target_node_id": str(item.get("target_node_id") or ""),
                "edge_id": str(item.get("edge_id") or item.get("source_edge_id") or ""),
                "payload_contract_id": str(item.get("payload_contract_id") or ""),
                "packet_contract_id": str(item.get("packet_contract_id") or item.get("payload_contract_id") or ""),
                "target_context_key": str(item.get("target_context_key") or ""),
                "target_input_slot": str(item.get("target_input_slot") or ""),
                "delivery_policy": str(item.get("delivery_policy") or ""),
                "payload": _bounded_graph_payload(payload),
                "artifact_refs": _bounded_dict_list(item.get("artifact_refs"), limit=12),
                "memory_refs": _bounded_dict_list(item.get("memory_refs"), limit=12),
                "result_refs": _bounded_dict_list(item.get("result_refs"), limit=8),
                "receipt_refs": _bounded_dict_list(item.get("receipt_refs"), limit=12),
                "visibility": dict(item.get("visibility") or {}),
                "authority": "graph_system.inbound_context.model_visible",
            }
        )
    return items


def _bounded_graph_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(payload.get("initial_inputs"), dict):
        result["initial_inputs"] = _truncate_value(dict(payload.get("initial_inputs") or {}), max_chars=4000)
    if payload.get("graph_id"):
        result["graph_id"] = str(payload.get("graph_id") or "")
    if payload.get("project_id"):
        result["project_id"] = str(payload.get("project_id") or "")
    if "handoff_summary" in payload:
        result["handoff_summary"] = str(payload.get("handoff_summary") or "")[:1200]
    if isinstance(payload.get("source_error"), dict):
        result["source_error"] = _truncate_value(dict(payload.get("source_error") or {}), max_chars=4000)
    if isinstance(payload.get("quality_acceptance"), dict):
        result["quality_acceptance"] = _truncate_value(dict(payload.get("quality_acceptance") or {}), max_chars=4000)
    if payload.get("quality_issue_summary"):
        result["quality_issue_summary"] = str(payload.get("quality_issue_summary") or "")[:4000]
    if isinstance(payload.get("issues"), list):
        result["issues"] = [str(item) for item in list(payload.get("issues") or [])[:32] if str(item)]
    if isinstance(payload.get("artifact_refs"), list):
        result["artifact_refs"] = [
            artifact_ref_value(item)
            for item in dedupe_artifact_refs([normalize_artifact_ref(ref) for ref in list(payload.get("artifact_refs") or [])])
            if artifact_ref_value(item)
        ][:12]
    if isinstance(payload.get("receipt_refs"), list):
        result["receipt_refs"] = _bounded_dict_list(payload.get("receipt_refs"), limit=12)
    if isinstance(payload.get("bounded_outputs"), dict):
        result["bounded_outputs"] = _truncate_value(dict(payload.get("bounded_outputs") or {}), max_chars=8000)
    if isinstance(payload.get("loop_iteration_results"), list):
        result["loop_iteration_results"] = _truncate_value(list(payload.get("loop_iteration_results") or [])[:10], max_chars=6000)
    if isinstance(payload.get("batch_chapter_ledger"), dict):
        result["batch_chapter_ledger"] = _truncate_value(dict(payload.get("batch_chapter_ledger") or {}), max_chars=6000)
    if isinstance(payload.get("artifact_payloads"), list):
        artifact_payload_limit = _GRAPH_LOOP_ARTIFACT_PAYLOAD_LIMIT if isinstance(payload.get("loop_iteration_results"), list) else _GRAPH_ARTIFACT_PAYLOAD_LIMIT
        result["artifact_payloads"] = [
            _bounded_artifact_payload(dict(item))
            for item in list(payload.get("artifact_payloads") or [])[:artifact_payload_limit]
            if isinstance(item, dict)
        ]
    return result


def _bounded_artifact_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_ref": str(item.get("artifact_ref") or ""),
        "content": str(item.get("content") or "")[:_GRAPH_AUTHORIZED_INPUT_CONTENT_LIMIT],
        "truncated": bool(item.get("truncated") is True),
        "max_chars": min(_safe_int(item.get("max_chars")) or _GRAPH_AUTHORIZED_INPUT_CONTENT_LIMIT, _GRAPH_AUTHORIZED_INPUT_CONTENT_LIMIT),
        "authority": str(item.get("authority") or "graph_system.flow_packet.artifact_text_projection"),
    }


def _truncate_value(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, str):
        return value[:max_chars]
    if isinstance(value, dict):
        return {str(key): _truncate_value(item, max_chars=max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_value(item, max_chars=max_chars) for item in value]
    return value


def _bounded_view_payload(view: dict[str, Any]) -> dict[str, Any]:
    payload = dict(view or {})
    if isinstance(payload.get("graph_memory_policy"), dict):
        policy = dict(payload.get("graph_memory_policy") or {})
        policy["read_rules"] = _bounded_dict_list(policy.get("read_rules"), limit=16)
        payload["graph_memory_policy"] = policy
    if isinstance(payload.get("graph_artifact_policy"), dict):
        policy = dict(payload.get("graph_artifact_policy") or {})
        policy["context_edges"] = _bounded_dict_list(policy.get("context_edges"), limit=16)
        payload["graph_artifact_policy"] = policy
    if isinstance(payload.get("graph_resource_policy"), dict):
        policy = dict(payload.get("graph_resource_policy") or {})
        policy["resource_nodes"] = _bounded_dict_list(policy.get("resource_nodes"), limit=24)
        payload["graph_resource_policy"] = policy
    return payload


def _bounded_dict_list(value: Any, *, limit: int) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or [])[:limit] if isinstance(item, dict)]


def _drop_empty_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {})
    }


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _message_created_at(message: dict[str, Any]) -> float:
    payload = dict(message or {})
    return _safe_float(payload.get("created_at") or payload.get("updated_at") or payload.get("timestamp"))


def _artifact_root(environment_payload: dict[str, Any]) -> str:
    storage = dict(environment_payload.get("storage_space") or {})
    artifact_root = str(storage.get("artifact_root") or "").strip()
    if artifact_root:
        return artifact_root
    artifact_policy = dict(environment_payload.get("artifact_policy") or {})
    return str(artifact_policy.get("artifact_root") or "").strip()


def _ensure_environment_storage_dirs_for_runtime(base_dir: Path, environment_payload: dict[str, Any]) -> None:
    storage = dict(environment_payload.get("storage_space") or {})
    if not storage:
        return
    project_root = ProjectLayout.from_backend_dir(base_dir).project_root.resolve()
    ensure_environment_storage_dirs(project_root=project_root, storage_space=storage)
