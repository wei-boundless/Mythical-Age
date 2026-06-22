from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prompt_library import (
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptAssemblyService,
    build_runtime_prompt_manifest,
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
    render_agent_prompt_instruction,
    render_environment_instruction,
    render_lifecycle_instruction,
    render_model_messages_from_projection,
    render_personality_prompt_instruction,
    render_prompt_contract_instruction,
)
from artifact_system.artifact_authority import artifact_ref_value, dedupe_artifact_refs, model_visible_artifact_refs, normalize_artifact_ref
from agent_system.identity import normalize_agent_id_sequence
from harness.current_work_receipt import current_work_operation_availability_from_receipt
from harness.recovery_receipt import recovery_operation_availability_from_receipt
from project_layout import ProjectLayout
from runtime.model_gateway.protocol_sanitizer import sanitize_messages_for_prompt
from runtime_objects.tool_result_storage import DEFAULT_PREVIEW_SIZE_BYTES, ToolResultStore
from task_system.contracts.runtime_contracts import expand_selected_skill_bodies, render_skill_candidate_cards

from .artifact_scope import runtime_artifact_scope_from_environment
from .dynamic_context import DynamicContextInput, DynamicContextManager, DynamicContextProjection, dynamic_context_storage_root
from .envelope import RuntimeEnvelope
from .invocation_packet import RuntimeInvocationPacket
from .action_schema_manifest import ActionSchemaManifest, build_action_schema_manifest
from .artifact_scope_manifest import ArtifactScopeManifest, build_artifact_scope_manifest
from .bound_task_context import build_bound_task_context
from .environment_storage import ensure_environment_storage_dirs
from .environment_prompt_controller import GENERAL_ENVIRONMENT_ID, prompt_mount_plan_for_invocation, prompt_mount_plan_from_payload
from .incremental_context_frame import (
    TASK_EXECUTION_INCREMENTAL_CONTEXT_FRAME_SOURCE_REF,
    build_task_execution_incremental_context_frame_payload,
)
from .packet_assembler import (
    build_dynamic_context_projection_policy as _dynamic_context_projection_policy,
    build_session_file_evidence_projection as _build_session_file_evidence_projection,
    build_single_agent_turn_packet_context,
    build_task_execution_packet_context,
)
from .prompt_segment_plan import build_prompt_segment_plan
from .project_instructions import ProjectInstructionBundle, collect_project_instruction_bundle
from .provider_tool_schema import stable_tool_schema_catalog_payload
from .runtime_control_signal_projection import canonical_runtime_control_signal_projection
from .sandbox_execution_scope import compile_sandbox_execution_scope, task_safety_envelope_from_assembly
from .task_contract_manifest import TaskContractManifest, build_task_contract_manifest_from_contract
from .tool_catalog_manifest import ToolCatalogManifest, build_tool_catalog_manifest


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

_PROVIDER_PROTOCOL_DEFAULT_MESSAGE_LIMIT = 12
_PROVIDER_PROTOCOL_DEFAULT_CHAR_BUDGET = 24_000
_PROVIDER_PROTOCOL_DEFAULT_MESSAGE_CHARS = 2_400
_PROVIDER_PROTOCOL_REHYDRATION_NOTE = (
    "Provider protocol replay evidence only. This preserves tool-call continuity; it is not a request to repeat the tool. "
    "Preview only. Do not rely on omitted content for exact claims, citations, line-level edits, "
    "or final factual judgments. For non-code omitted output, call read_persisted_tool_result first when exact content matters. "
    "For read_file content, rely on exact text only when it is visible in the current packet; "
    "historical file evidence is represented by refs, hashes, and line ranges, so read the current target window when exact text matters."
)


@dataclass(frozen=True, slots=True)
class RuntimeCompilationResult:
    envelope: RuntimeEnvelope
    packet: RuntimeInvocationPacket

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope": self.envelope.to_dict(),
            "packet": self.packet.to_dict(),
        }


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
            prompt_refs=_agent_prompt_refs_for_invocation(assembly_payload, invocation_kind=invocation_kind),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
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
                    source_ref=",".join(_agent_prompt_refs_for_invocation(assembly_payload, invocation_kind=invocation_kind)),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Semantic compaction stable boundary",
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
        )
        protocol_sanitizer = sanitize_messages_for_prompt(
            model_messages,
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
        prompt_manifest["prompt_slot_plan_ref"] = slot_plan.plan_id
        prompt_manifest["prompt_slot_plan"] = slot_plan.to_dict()
        prompt_manifest["runtime_context_load_plan_ref"] = context_load_plan.plan_id
        prompt_manifest["runtime_context_load_plan"] = context_load_plan.to_dict()
        prompt_manifest["protocol_sanitizer"] = dict(protocol_sanitizer.diagnostics)
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
    ) -> RuntimeCompilationResult:
        initial_assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
        initial_profile_payload = dict(initial_assembly_payload.get("profile") or {})
        prompt_pack_refs = _prompt_pack_refs_for_invocation(initial_profile_payload, invocation_kind="single_agent_turn")
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
            prompt_pack_refs=prompt_pack_refs,
            base_dir=self.base_dir,
        )
        assembly_payload = packet_context.runtime_assembly
        self._bind_assembly_base_dir(assembly_payload)
        profile_payload = packet_context.profile_payload
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
        output_contract = _single_agent_turn_output_contract(
            allowed_actions=allowed_actions,
            control_capabilities=effective_control_capabilities,
            planning_protocol=planning_protocol,
        )
        agent_visible_runtime_projection = _agent_visible_runtime_projection(
            invocation_kind="single_agent_turn",
            allowed_action_types=allowed_actions,
            profile_payload=profile_payload,
            environment_payload=environment_payload,
            operation_authorization=dict(assembly_payload.get("operation_authorization") or {}),
            available_tools=single_turn_tools,
            permission_mode=permission_mode,
            tool_plan=single_turn_tool_plan,
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
        )
        prompt_mount_plan = prompt_mount_plan_for_invocation(
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
        tool_catalog_manifest = _build_tool_catalog_manifest_for_mount_plan(
            invocation_kind="single_agent_turn",
            tool_payloads=single_turn_tools,
            source_ref="runtime_assembly.available_tools",
            prompt_mount_plan=prompt_mount_plan,
        )
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="single_agent_turn",
            prompt_refs=_agent_prompt_refs_for_invocation(assembly_payload, invocation_kind="single_agent_turn"),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        personality_prompt_assembly = self._assemble_personality_prompt_layer(
            prompt_mount_plan=prompt_mount_plan,
            invocation_kind="single_agent_turn",
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        environment_prompt_assembly, lifecycle_prompt_assembly = self._assemble_environment_prompt_layers(
            prompt_mount_plan=prompt_mount_plan,
            agent_profile_ref=agent_profile_ref,
        )
        runtime_lifecycle_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=tuple(prompt_mount_plan.runtime_lifecycle_prompt_refs or ()),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(prompt_mount_plan.selected_environment_id or ""),
        )
        project_instruction_bundle = collect_project_instruction_bundle(base_dir=self.base_dir)
        runtime_instruction = _runtime_projection_instruction(agent_visible_runtime_projection)
        environment_instruction = render_environment_instruction(
            environment_payload,
            environment_prompt_assembly=environment_prompt_assembly,
        )
        lifecycle_instruction = render_lifecycle_instruction(lifecycle_prompt_assembly)
        runtime_lifecycle_instruction = render_lifecycle_instruction(runtime_lifecycle_prompt_assembly)
        personality_instruction = render_personality_prompt_instruction(personality_prompt_assembly)
        agent_instruction = render_agent_prompt_instruction(agent_prompt_assembly, invocation_kind="single_agent_turn")
        skill_candidate_instruction = _skill_candidate_instruction(assembly_payload)
        stable_payload = {
            "control_capabilities": dict(effective_control_capabilities),
            "planning_protocol": planning_protocol,
            "task_environment": _environment_model_visible_payload(
                environment_payload,
                prompt_mount_plan=prompt_mount_plan.to_dict(),
            ),
            "capability_directory": _capability_directory_model_visible_payload(assembly_payload),
            "output_contract": output_contract,
            **_project_instruction_model_payload(project_instruction_bundle),
        }
        tool_index_payload = (
            tool_catalog_manifest.to_model_visible_payload(include_catalog_hash=True)
            if single_turn_tools
            else {}
        )
        tool_schema_catalog_payload = stable_tool_schema_catalog_payload(
            tool_payloads=single_turn_tools,
            tool_catalog_manifest=tool_catalog_manifest,
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
        dynamic_payload = dict(dynamic_context.dynamic_runtime_projection or {})
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
        recoverable_work_payload = _continuation_record_model_visible_payload(
            session_context_payload.get("recoverable_work")
        )
        if recoverable_work_payload:
            volatile_runtime_payload["recoverable_work"] = recoverable_work_payload
        interrupted_turn_payload = _interrupted_turn_work_model_visible_payload(
            session_context_payload.get("interrupted_turn_work"),
            current_user_message=user_message,
        )
        if interrupted_turn_payload:
            volatile_runtime_payload["interrupted_turn_work"] = interrupted_turn_payload
        recovery_boundary_receipt_payload = _recovery_boundary_receipt_model_visible_payload(
            session_context_payload.get("recovery_boundary_receipt")
        )
        if recovery_boundary_receipt_payload:
            volatile_runtime_payload["recovery_boundary_receipt"] = recovery_boundary_receipt_payload
        runtime_observations_payload = _runtime_observations_model_visible_payload(
            session_context_payload.get("runtime_observations")
        )
        if runtime_observations_payload:
            volatile_runtime_payload["runtime_observations"] = runtime_observations_payload
        if turn_input_facts:
            volatile_runtime_payload["turn_input_facts"] = _turn_input_facts_model_visible_payload(turn_input_facts)
        volatile_payload = dict(dynamic_context.volatile_request_projection or {})
        session_history_payload, current_request_payload = _split_volatile_request_payload(volatile_payload)
        attachment_context_payload, current_request_payload = _extract_attachment_context_payload(current_request_payload)
        task_plan_context_payload, current_request_payload = _extract_task_plan_context_payload(current_request_payload)
        editor_context_payload, current_request_payload = _extract_editor_context_payload(current_request_payload)
        model_messages, segment_plan, message_specs, source_manifest, slot_plan, context_load_plan = _model_messages_and_segment_plan(
            packet_id=packet_id,
            invocation_kind="single_agent_turn",
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
                    title="Single agent turn tool schema catalog",
                    payload=tool_schema_catalog_payload,
                    kind="tool_schema_catalog",
                    source_ref=_short_hash(tool_catalog_manifest.tool_catalog_hash),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "provider_tool_schema_catalog",
                        "content_source": "harness.runtime.compiler.stable_tool_schema_catalog",
                    },
                )
                if tool_schema_catalog_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Single agent turn tool index",
                    payload=tool_index_payload,
                    kind="tool_index_stable",
                    source_ref=_short_hash(tool_catalog_manifest.tool_catalog_hash),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                )
                if tool_index_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Single agent turn stable boundary",
                    payload=stable_payload,
                    kind="turn_stable",
                    source_ref="single_agent_turn_stable_boundary",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _runtime_payload_spec(
                    role="system",
                    title="File evidence policy",
                    payload=_file_evidence_policy_stable_payload(),
                    kind="file_evidence_policy_stable",
                    source_ref="file_evidence_policy_stable.read_window_admission",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "file_evidence_policy",
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
                    content=lifecycle_instruction,
                    kind="lifecycle_stable",
                    source_ref=",".join(prompt_mount_plan.lifecycle_prompt_refs),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "runtime_lifecycle_protocol",
                        "lifecycle_prompt_keys": list(prompt_mount_plan.lifecycle_prompt_keys),
                        "lifecycle_trigger_reasons": dict(prompt_mount_plan.lifecycle_trigger_reasons),
                    },
                )
                if lifecycle_instruction.strip()
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
                *_attachment_context_message_specs(
                    attachment_context_payload,
                    title_prefix="Single agent turn",
                    source_ref_prefix="single_agent_turn",
                    dynamic_context=dynamic_context,
                ),
                *_task_plan_context_message_specs(
                    task_plan_context_payload,
                    title_prefix="Single agent turn",
                    source_ref_prefix="single_agent_turn",
                    dynamic_context=dynamic_context,
                ),
                *_editor_context_message_specs(
                    editor_context_payload,
                    title_prefix="Single agent turn",
                    source_ref_prefix="single_agent_turn",
                    dynamic_context=dynamic_context,
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Task current exact read evidence",
                    payload=read_evidence_prompt_payload,
                    kind="read_evidence_injection",
                    source_ref=_read_evidence_prompt_source_ref(read_evidence_prompt_payload, fallback=packet_id),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "read_evidence_injection",
                        "projection_strategy": "current_exact_read_once_historical_refs",
                        "content_source": "harness.runtime.dynamic_context.read_evidence_projector",
                        "cache_impact": "task_prefix_read_evidence_snapshot",
                        "stability_rule": "exact read evidence already sent in this turn is a stable snapshot; later reads append new observations",
                    },
                )
                if read_evidence_prompt_payload
                else None,
                *_session_history_message_specs(
                    session_history_payload,
                    title="Single agent turn session history",
                    source_ref="single_agent_turn_session_history",
                    metadata=_dynamic_context_segment_metadata(dynamic_context, source="session_history") if session_history_payload else {},
                ),
                *_provider_protocol_message_specs(
                    session_context,
                    source_ref="single_agent_turn_api_transcript",
                    projection_policy=projection_policy,
                    storage_root=dynamic_context_storage_root(self.base_dir, assembly_payload) or self.base_dir,
                    storage_run_id=session_id,
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Single agent turn dynamic runtime",
                    payload=dynamic_payload,
                    preamble=runtime_instruction,
                    kind="dynamic_projection",
                    source_ref="single_agent_turn_runtime_delta",
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="summarize",
                    metadata=_dynamic_context_segment_metadata(dynamic_context, source="runtime_delta"),
                ),
                _message_spec(
                    role="system",
                    content=skill_candidate_instruction,
                    kind="skill_candidates",
                    source_ref="runtime_skill_candidates",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "active_skill_runtime",
                        "volatility_reason": "skill candidates are selected for the current request and can change between turns",
                        "cache_impact": "volatile_suffix_only",
                    },
                )
                if skill_candidate_instruction.strip()
                else None,
                _message_spec(
                    role="system",
                    content=runtime_lifecycle_instruction,
                    kind="lifecycle_runtime_guidance",
                    source_ref=",".join(prompt_mount_plan.runtime_lifecycle_prompt_refs),
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "runtime_lifecycle_guidance",
                        "lifecycle_prompt_keys": list(prompt_mount_plan.runtime_lifecycle_prompt_keys),
                        "lifecycle_trigger_reasons": dict(prompt_mount_plan.runtime_lifecycle_trigger_reasons),
                        "volatility_reason": "runtime lifecycle guidance is selected from active state such as memory, observations, steering, or recovery",
                        "cache_impact": "volatile_suffix_only",
                    },
                )
                if runtime_lifecycle_instruction.strip()
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Single agent turn volatile runtime state",
                    payload=volatile_runtime_payload,
                    kind="volatile_runtime_state",
                    source_ref="single_agent_turn_volatile_runtime_state",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata={
                        "authority_class": "single_turn_runtime_state",
                        "volatility_reason": "active work, recovery, runtime observations, and turn facts can change on every user turn",
                        "cache_impact": "volatile_suffix_only",
                        "content_source": "harness.runtime.compiler.single_turn_volatile_runtime_state",
                    },
                )
                if volatile_runtime_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Single agent turn runtime memory context",
                    payload=runtime_memory_context_payload,
                    kind="runtime_memory_context",
                    source_ref=_runtime_memory_context_source_ref(runtime_memory_context_payload),
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata={
                        "authority_class": "runtime_memory_context",
                        "content_source": "memory_system.runtime_memory_context",
                        "volatility_reason": "selected memory context can change on each invocation and belongs in the dynamic tail",
                        "cache_impact": "volatile_suffix_only",
                    },
                )
                if runtime_memory_context_payload
                else None,
                _runtime_payload_spec(
                    role="user",
                    title="Single agent turn current request",
                    payload=current_request_payload,
                    kind="volatile_user",
                    source_ref="single_agent_turn_current_request",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata=_dynamic_context_segment_metadata(dynamic_context, source="current_request"),
                ),
            ],
            enforce_dynamic_context_reports=True,
        )
        protocol_sanitizer = sanitize_messages_for_prompt(
            model_messages,
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
            "agent_visible_runtime_projection",
            "operation_authorization",
            "file_evidence_scope",
            "file_state",
            "file_evidence_decisions",
            "read_resource_state",
        )
        single_turn_volatile_refs = (
            "runtime_envelope",
            "turn_id",
            "history",
            "user_message",
            "active_work_context",
            "recent_work_outcome",
            "current_work_boundary_receipt",
            "recoverable_work",
            "interrupted_turn_work",
            "recovery_boundary_receipt",
            "runtime_observations",
            "turn_input_facts",
            "task_plan_context",
            "editor_context_index",
            "current_editor_evidence_delta",
            "lifecycle_runtime_guidance",
            "runtime_memory_context",
            "skill_candidates",
        )
        prompt_manifest = build_runtime_prompt_manifest(
            invocation_kind="single_agent_turn",
            assembly=_merge_prompt_assemblies(
                prompt_assembly,
                personality_prompt_assembly,
                environment_prompt_assembly,
                lifecycle_prompt_assembly,
                runtime_lifecycle_prompt_assembly,
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
        prompt_manifest["prompt_slot_plan_ref"] = slot_plan.plan_id
        prompt_manifest["prompt_slot_plan"] = slot_plan.to_dict()
        prompt_manifest["runtime_context_load_plan_ref"] = context_load_plan.plan_id
        prompt_manifest["runtime_context_load_plan"] = context_load_plan.to_dict()
        prompt_manifest["prompt_mount_plan"] = prompt_mount_plan.to_dict()
        prompt_manifest["dynamic_context_report"] = dynamic_context.to_report_dict()
        prompt_manifest["protocol_sanitizer"] = dict(protocol_sanitizer.diagnostics)
        prompt_manifest["context_window"] = _context_window_report(
            session_context=session_context,
            history=history,
            dynamic_context=dynamic_context,
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
            hidden_control_refs={"agent_invocation_id": agent_invocation_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
            context_refs=dynamic_context.context_refs,
            artifact_refs=dynamic_context.artifact_refs,
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
                "tool_catalog_manifest": tool_catalog_manifest_payload,
                "model_input_authority": "prompt_composition.message_projection",
                "protocol_sanitizer": dict(protocol_sanitizer.diagnostics),
                "runtime_packet_context": packet_context.to_dict(),
                "control_capabilities": dict(effective_control_capabilities),
                "active_work_context_present": bool(active_work_context),
                "current_work_boundary_receipt": dict(current_work_boundary_receipt or {}),
                "turn_input_facts_present": bool(turn_input_facts),
            },
        )
        return RuntimeCompilationResult(envelope=envelope, packet=packet)

    def compile_task_execution_packet(
        self,
        *,
        session_id: str,
        task_run: dict[str, Any],
        contract: dict[str, Any],
        observations: list[dict[str, Any]],
        execution_state: dict[str, Any] | None = None,
        work_rollout: dict[str, Any] | None = None,
        agent_profile_ref: str = "main_interactive_agent",
        model_selection: dict[str, Any] | None = None,
        available_tools: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
        runtime_assembly: Any | None = None,
        memory_context: dict[str, Any] | None = None,
        inherited_start_context: dict[str, Any] | None = None,
        invocation_index: int = 1,
    ) -> RuntimeCompilationResult:
        assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
        self._bind_assembly_base_dir(assembly_payload)
        profile_payload = dict(assembly_payload.get("profile") or {})
        environment_payload = dict(assembly_payload.get("task_environment") or {})
        _ensure_environment_storage_dirs_for_runtime(self.base_dir, environment_payload)
        permission_mode = str(assembly_payload.get("permission_mode") or "default")
        artifact_scope = runtime_artifact_scope_from_environment(environment_payload)
        sandbox_execution_scope = compile_sandbox_execution_scope(
            environment_payload=environment_payload,
            contract=contract,
            safety_envelope=task_safety_envelope_from_assembly(assembly_payload),
            artifact_root=artifact_scope.artifact_root,
        )
        contract = sandbox_execution_scope.canonical_contract
        agent_profile_ref = str(assembly_payload.get("agent_profile_ref") or agent_profile_ref or "main_interactive_agent")
        task_environment_ref = str(environment_payload.get("environment_id") or "env.general.workspace")
        task_run_id = str(task_run.get("task_run_id") or "")
        task_run_diagnostics = dict(task_run.get("diagnostics") or {})
        executor_epoch = int(task_run_diagnostics.get("executor_epoch") or 0)
        runtime_policy = {
            "planning_policy": dict(profile_payload.get("planning_policy") or {}),
            "task_lifecycle_policy": dict(profile_payload.get("task_lifecycle_policy") or {}),
            "self_review_policy": dict(profile_payload.get("self_review_policy") or {}),
        }
        permission_policy = dict(profile_payload.get("permission_policy") or {"permission_scope": "task_run_execution"})
        permission_policy.setdefault("permission_scope", str(permission_policy.get("scope") or "task_run_execution"))
        tool_payloads = tuple(dict(item) for item in list(available_tools or []) if isinstance(item, dict))
        graph_slot = _graph_slot_from_contract(contract)
        task_run_context_enabled = _task_run_context_enabled(profile_payload)
        prompt_pack_refs = _prompt_pack_refs_for_invocation(profile_payload, invocation_kind="task_execution")
        prompt_policy = _runtime_prompt_policy(
            profile_payload=profile_payload,
            assembly_payload=assembly_payload,
            contract=contract,
        )
        operation_authorization = dict(assembly_payload.get("operation_authorization") or {})
        packet_context = build_task_execution_packet_context(
            session_id=session_id,
            task_run=task_run,
            runtime_assembly=assembly_payload,
            available_tools=tool_payloads,
            agent_profile_ref=agent_profile_ref,
            model_selection=model_selection,
            prompt_pack_refs=prompt_pack_refs,
            invocation_index=invocation_index,
            base_dir=self.base_dir,
            operation_authorization=operation_authorization,
            prompt_policy=prompt_policy,
            include_task_run_context=task_run_context_enabled,
        )
        tool_payloads = packet_context.model_visible_tools
        allowed_actions = packet_context.allowed_action_types
        agent_visible_runtime_projection = _agent_visible_runtime_projection(
            invocation_kind="task_execution",
            allowed_action_types=allowed_actions,
            profile_payload=profile_payload,
            environment_payload=environment_payload,
            operation_authorization=operation_authorization,
            available_tools=tool_payloads,
            permission_mode=permission_mode,
            prompt_policy=prompt_policy,
        )
        planning_protocol = _planning_protocol_payload(
            invocation_kind="task_execution",
            profile_payload=profile_payload,
            permission_mode=permission_mode,
            contract=contract,
        )
        envelope = RuntimeEnvelope(
            envelope_id=f"rtenv:{task_run_id}:task_execution:{invocation_index}",
            scope_kind="task_run",
            session_id=session_id,
            task_run_id=task_run_id,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            runtime_policy=runtime_policy,
            sandbox_policy=dict(environment_payload.get("sandbox_policy") or {}),
            file_policy={
                "file_management": dict(environment_payload.get("file_management") or {}),
                "file_access_tables": list(environment_payload.get("file_access_tables") or []),
            },
            artifact_policy=artifact_scope.to_artifact_policy(dict(environment_payload.get("artifact_policy") or {})),
            permission_policy=permission_policy,
            prompt_policy={"invocation_kind": "task_execution", **prompt_policy},
            output_policy={"format": "model_action_request_json", "planning_protocol": planning_protocol},
            graph_slot=graph_slot,
            diagnostics={
                "task_run_id": task_run_id,
                "model_selection": dict(model_selection or {}),
                "runtime_assembly_id": str(assembly_payload.get("assembly_id") or ""),
            },
        )
        action_schema_manifest = build_action_schema_manifest(
            invocation_kind="task_execution",
            schema=task_execution_action_schema(),
            source_ref="task_execution_action_schema",
        )
        artifact_scope_manifest = build_artifact_scope_manifest(
            invocation_kind="task_execution",
            sandbox_execution_scope=sandbox_execution_scope,
            source_ref="task_execution_artifact_write_scope",
        )
        schema = dict(action_schema_manifest.schema)
        task_prompt_contract = _task_prompt_contract_from_runtime(
            task_run=task_run,
            contract=contract,
            assembly_payload=assembly_payload,
        )
        graph_node_prompt_contract = _graph_node_prompt_contract_from_runtime(
            task_run=task_run,
            contract=contract,
            assembly_payload=assembly_payload,
        )
        if graph_node_prompt_contract or not task_run_context_enabled:
            task_prompt_contract = {}
        prompt_assembly = self._assemble_prompt_pack(
            invocation_kind="task_execution",
            prompt_pack_refs=prompt_pack_refs,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        prompt_mount_plan = prompt_mount_plan_for_invocation(
            _prompt_mount_plan_payload_from_runtime_assembly(assembly_payload),
            invocation_kind="task_execution",
            allowed_actions=allowed_actions,
            memory_context=memory_context,
            observations=tuple(dict(item) for item in list(observations or []) if isinstance(item, dict)),
            visible_tools=tool_payloads,
            execution_state=dict(execution_state or {}),
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
        )
        tool_catalog_manifest = _build_tool_catalog_manifest_for_mount_plan(
            invocation_kind="task_execution",
            tool_payloads=tool_payloads,
            source_ref="task_execution.available_tools",
            prompt_mount_plan=prompt_mount_plan,
        )
        task_prompt_assembly = self._assemble_prompt_contract(
            task_prompt_contract=task_prompt_contract,
            graph_node_prompt_contract=graph_node_prompt_contract,
        )
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="task_execution",
            prompt_refs=_agent_prompt_refs_for_invocation(assembly_payload, invocation_kind="task_execution"),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        personality_prompt_assembly = (
            self._assemble_personality_prompt_layer(
                prompt_mount_plan=prompt_mount_plan,
                invocation_kind="task_execution",
                agent_profile_ref=agent_profile_ref,
                task_environment_ref=task_environment_ref,
            )
            if _prompt_policy_visible(prompt_policy, "personality_prompt_visibility", default=True)
            else _empty_prompt_assembly("personality", "promptasm:empty:task_execution_personality_policy_hidden")
        )
        if _prompt_policy_visible(prompt_policy, "environment_prompt_visibility", default=True):
            environment_prompt_assembly, lifecycle_prompt_assembly = self._assemble_environment_prompt_layers(
                prompt_mount_plan=prompt_mount_plan,
                agent_profile_ref=agent_profile_ref,
            )
            runtime_lifecycle_prompt_assembly = self._assemble_prompt_refs(
                invocation_kind="environment",
                prompt_refs=tuple(prompt_mount_plan.runtime_lifecycle_prompt_refs or ()),
                agent_profile_ref=agent_profile_ref,
                task_environment_ref=str(prompt_mount_plan.selected_environment_id or ""),
            )
        else:
            environment_prompt_assembly = _empty_prompt_assembly("environment", "promptasm:empty:environment_policy_hidden")
            lifecycle_prompt_assembly = _empty_prompt_assembly("environment", "promptasm:empty:lifecycle_policy_hidden")
            runtime_lifecycle_prompt_assembly = _empty_prompt_assembly("environment", "promptasm:empty:runtime_lifecycle_policy_hidden")
        project_instruction_bundle = (
            collect_project_instruction_bundle(
                base_dir=self.base_dir,
                target_paths=_project_instruction_target_paths(contract=contract, task_run=task_run),
                cache_scope="task_stable",
            )
            if _prompt_policy_visible(prompt_policy, "project_instruction_visibility", default=True)
            else ProjectInstructionBundle(cache_scope="task_stable")
        )
        runtime_instruction = _runtime_projection_instruction(agent_visible_runtime_projection)
        active_skill_instruction, active_skill_meta = _active_skill_instruction(
            base_dir=self.base_dir,
            assembly_payload=assembly_payload,
        )
        environment_instruction = (
            render_environment_instruction(
                environment_payload,
                environment_prompt_assembly=environment_prompt_assembly,
                include_storage_note=False,
            )
            if _prompt_policy_visible(prompt_policy, "environment_prompt_visibility", default=True)
            else ""
        )
        lifecycle_instruction = (
            render_lifecycle_instruction(lifecycle_prompt_assembly)
            if _prompt_policy_visible(prompt_policy, "environment_prompt_visibility", default=True)
            else ""
        )
        runtime_lifecycle_instruction = (
            render_lifecycle_instruction(runtime_lifecycle_prompt_assembly)
            if _prompt_policy_visible(prompt_policy, "environment_prompt_visibility", default=True)
            else ""
        )
        personality_instruction = (
            render_personality_prompt_instruction(personality_prompt_assembly)
            if _prompt_policy_visible(prompt_policy, "personality_prompt_visibility", default=True)
            else ""
        )
        agent_instruction = render_agent_prompt_instruction(agent_prompt_assembly, invocation_kind="task_execution")
        action_schema_payload = action_schema_manifest.to_model_visible_payload()
        agent_function_shared_payload = _graph_agent_function_shared_stable_payload(contract)
        graph_task_shared_payload = _graph_task_shared_stable_payload(contract)
        task_contract_manifest = build_task_contract_manifest_from_contract(
            invocation_kind="task_execution",
            contract=contract,
            planning_protocol=planning_protocol,
            source_ref=str(contract.get("contract_id") or "task_execution_contract"),
            graph_node_context=_graph_node_stable_contract_context(graph_slot) if graph_slot else {},
        )
        task_contract_payload = task_contract_manifest.to_model_visible_payload()
        graph_node_runtime_context_payload = (
            {"graph_node_runtime_context": _graph_node_model_context_projection(graph_slot)}
            if graph_slot
            else {}
        )
        graph_node_completion_prefix = _graph_node_completion_prefix(
            graph_slot,
            invocation_kind="task_execution",
            allowed_action_types=allowed_actions,
        )
        artifact_execution_scope_payload = artifact_scope_manifest.to_model_visible_payload()
        environment_stable_payload = {}
        if _prompt_policy_visible(prompt_policy, "environment_payload_visibility", default=True):
            environment_stable_payload["task_environment"] = _environment_model_visible_payload(
                environment_payload,
                prompt_mount_plan=prompt_mount_plan.to_dict(),
            )
        capability_directory_payload = _capability_directory_model_visible_payload(assembly_payload)
        if capability_directory_payload:
            environment_stable_payload["capability_directory"] = capability_directory_payload
        project_instruction_payload = _project_instruction_model_payload(project_instruction_bundle)
        tool_schema_catalog_payload = stable_tool_schema_catalog_payload(
            tool_payloads=tool_payloads,
            tool_catalog_manifest=tool_catalog_manifest,
        )
        tool_index_payload = tool_catalog_manifest.to_model_visible_payload(include_catalog_hash=True)
        packet_context = build_task_execution_packet_context(
            session_id=session_id,
            task_run=task_run,
            runtime_assembly=assembly_payload,
            available_tools=tool_payloads,
            agent_profile_ref=agent_profile_ref,
            model_selection=model_selection,
            prompt_pack_refs=prompt_pack_refs,
            invocation_index=invocation_index,
            base_dir=self.base_dir,
            agent_visible_runtime_projection=agent_visible_runtime_projection,
            operation_authorization=operation_authorization,
            prompt_policy=prompt_policy,
            include_task_run_context=task_run_context_enabled,
        )
        packet_id = packet_context.packet_id
        projection_policy = packet_context.projection_policy
        dynamic_context = self.dynamic_context_manager.project(
            DynamicContextInput(
                invocation_kind="task_execution",
                session_id=session_id,
                task_run_id=task_run_id,
                task_run=dict(task_run or {}),
                task_contract=dict(contract or {}),
                observations=tuple(dict(item) for item in list(observations or []) if isinstance(item, dict)),
                execution_state=dict(execution_state or {}),
                work_rollout=dict(work_rollout or {}),
                inherited_start_context=dict(inherited_start_context or {}),
                runtime_assembly=assembly_payload,
                runtime_envelope=envelope.to_dict(),
                editor_context=_editor_context_from_task_run(task_run),
                projection_policy=projection_policy,
            )
        )
        dynamic_payload = dict(dynamic_context.dynamic_runtime_projection or {})
        inherited_start_context_payload = dict(dynamic_context.inherited_start_context_projection or {})
        attachment_context_payload, inherited_start_context_payload = _extract_attachment_context_payload(inherited_start_context_payload)
        runtime_memory_context_payload = _memory_context_model_visible_payload(memory_context)
        recovery_packet_payload = _recovery_packet_model_visible_payload(
            task_run_diagnostics.get("recovery_packet")
        )
        if recovery_packet_payload:
            dynamic_payload["recovery_packet"] = recovery_packet_payload
        volatile_payload = dict(dynamic_context.volatile_state_projection or {})
        execution_projection = dict(dict(execution_state or {}).get("system_projection") or {})
        runtime_control_signals = canonical_runtime_control_signal_projection(
            execution_projection.get("runtime_control_signals")
        )
        if runtime_control_signals:
            volatile_payload["runtime_control_signals"] = runtime_control_signals
            volatile_payload["latest_runtime_control_signal"] = dict(runtime_control_signals[-1])
        task_plan_context_payload, volatile_payload = _extract_task_plan_context_payload(volatile_payload)
        evidence_index_cursor_payload, volatile_payload = _extract_evidence_index_cursor_payload(volatile_payload)
        editor_context_payload, volatile_payload = _extract_editor_context_payload(volatile_payload)
        bound_task_context = build_bound_task_context(
            contract=contract,
            planning_protocol=planning_protocol,
            dynamic_context=dynamic_context,
            task_state_projection=_drop_empty_payload({**volatile_payload, **evidence_index_cursor_payload}),
            task_run_id=task_run_id,
        )
        bound_task_context_payload = bound_task_context.to_stable_model_visible_payload()
        bound_task_runtime_context_payload = bound_task_context.to_runtime_model_visible_payload()
        task_state_replay_specs = _task_state_replay_message_specs(dynamic_context.task_state_replay_entries)
        task_state_payload = dict(volatile_payload.get("task_state") or {})
        packet_context = build_task_execution_packet_context(
            session_id=session_id,
            task_run=task_run,
            runtime_assembly=assembly_payload,
            available_tools=tool_payloads,
            agent_profile_ref=agent_profile_ref,
            model_selection=model_selection,
            prompt_pack_refs=prompt_pack_refs,
            invocation_index=invocation_index,
            base_dir=self.base_dir,
            agent_visible_runtime_projection=agent_visible_runtime_projection,
            operation_authorization=operation_authorization,
            prompt_policy=prompt_policy,
            include_task_run_context=task_run_context_enabled,
            task_state_payload=task_state_payload,
            evidence_index_cursor_payload=evidence_index_cursor_payload,
            current_observations=tuple(dict(item) for item in list(observations or []) if isinstance(item, dict)),
        )
        read_evidence_payload = packet_context.read_evidence_payload
        read_evidence_prompt_payload = _read_evidence_prompt_payload(read_evidence_payload)
        user_steering_payload = _user_steering_updates_payload(execution_state)
        incremental_context_frame_payload = build_task_execution_incremental_context_frame_payload(
            task_run_id=task_run_id,
            invocation_index=invocation_index,
            dynamic_context_report=dynamic_context.to_report_dict(),
            task_state_replay_entries=dynamic_context.task_state_replay_entries,
            current_observations=tuple(dict(item) for item in list(observations or []) if isinstance(item, dict)),
            execution_projection=execution_projection,
            task_plan_context_payload=task_plan_context_payload,
            evidence_index_cursor_payload=evidence_index_cursor_payload,
            editor_context_payload=editor_context_payload,
            read_evidence_payload=read_evidence_payload,
            volatile_payload=volatile_payload,
            runtime_memory_context_payload=runtime_memory_context_payload,
            user_steering_payload=user_steering_payload,
            runtime_control_signals=runtime_control_signals,
        )
        model_messages, segment_plan, message_specs, source_manifest, slot_plan, context_load_plan = _model_messages_and_segment_plan(
            packet_id=packet_id,
            invocation_kind="task_execution",
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
                    title="Task execution action schema",
                    payload=action_schema_payload,
                    kind="action_schema_static",
                    source_ref=action_schema_manifest.source_ref,
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Task execution tool schema catalog",
                    payload=tool_schema_catalog_payload,
                    kind="tool_schema_catalog",
                    source_ref=_short_hash(tool_catalog_manifest.tool_catalog_hash),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "provider_tool_schema_catalog",
                        "content_source": "harness.runtime.compiler.stable_tool_schema_catalog",
                    },
                )
                if tool_schema_catalog_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Task execution tool index",
                    payload=tool_index_payload,
                    kind="tool_index_stable",
                    source_ref=_short_hash(tool_catalog_manifest.tool_catalog_hash),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Task execution task contract",
                    payload=task_contract_payload,
                    kind="task_contract_stable",
                    source_ref=task_contract_manifest.source_ref,
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=render_prompt_contract_instruction(task_prompt_assembly),
                    kind="task_prompt_contract",
                    source_ref=",".join(task_prompt_assembly.manifest.get("stable_contract_refs") or ()),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Task execution bound task context",
                    payload=bound_task_context_payload,
                    kind="bound_task_context_stable",
                    source_ref=bound_task_context.source_ref,
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "bound_task_context",
                        "semantic_layer": "L7_bound_task_context",
                        "cache_impact": "task_prefix_stable",
                        "projection_strategy": "task_bound_context_manifest",
                        "content_source": "harness.runtime.bound_task_context",
                    },
                )
                if bound_task_context_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Task execution graph shared context",
                    payload=graph_task_shared_payload,
                    kind="graph_task_shared_stable",
                    source_ref=str(graph_task_shared_payload.get("graph_shared_context", {}).get("shared_context_hash") or ""),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                )
                if graph_task_shared_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Task execution artifact write scope",
                    payload=artifact_execution_scope_payload,
                    kind="artifact_scope_stable",
                    source_ref=artifact_scope_manifest.source_ref,
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                (
                    _runtime_payload_spec(
                        role="system",
                        title="Task execution environment boundary",
                        payload=environment_stable_payload,
                        preamble=environment_instruction,
                        kind="environment_stable",
                        source_ref=",".join(prompt_mount_plan.environment_prompt_refs),
                        cache_scope="session",
                        cache_role="session_stable",
                        compression_role="preserve",
                    )
                    if environment_instruction.strip() or environment_stable_payload
                    else None
                ),
                (
                    _message_spec(
                        role="system",
                        content=lifecycle_instruction,
                        kind="lifecycle_stable",
                        source_ref=",".join(prompt_mount_plan.lifecycle_prompt_refs),
                        cache_scope="session",
                        cache_role="session_stable",
                        compression_role="preserve",
                        metadata={
                            "authority_class": "runtime_lifecycle_protocol",
                            "lifecycle_prompt_keys": list(prompt_mount_plan.lifecycle_prompt_keys),
                            "lifecycle_trigger_reasons": dict(prompt_mount_plan.lifecycle_trigger_reasons),
                        },
                    )
                    if lifecycle_instruction.strip()
                    else None
                ),
                (
                    _message_spec(
                        role="system",
                        content=personality_instruction,
                        kind="personality_stable",
                        source_ref=",".join(personality_prompt_assembly.manifest.get("stable_prompt_refs") or ()),
                        cache_scope="session",
                        cache_role="session_stable",
                        compression_role="preserve",
                    )
                    if personality_instruction.strip()
                    else None
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
                (
                    _runtime_payload_spec(
                        role="system",
                        title="Task execution project instructions",
                        payload=project_instruction_payload,
                        kind="project_instructions_stable",
                        source_ref=project_instruction_bundle.prompt_ref,
                        cache_scope="session",
                        cache_role="session_stable",
                        compression_role="preserve",
                        metadata={
                            "authority_class": "project_instruction_boundary",
                            "cache_impact": "project_prefix_stable",
                            "projection_strategy": "scoped_project_instruction_bundle",
                            "content_source": "harness.runtime.project_instructions",
                        },
                    )
                    if project_instruction_payload
                    else None
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Task execution agent function contract",
                    payload=agent_function_shared_payload,
                    kind="agent_function_shared_stable",
                    source_ref=str(agent_function_shared_payload.get("agent_function_shared_context", {}).get("role_family") or ""),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                )
                if agent_function_shared_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Task execution file evidence policy",
                    payload=_file_evidence_policy_stable_payload(),
                    kind="file_evidence_policy_stable",
                    source_ref="file_evidence_policy_stable.read_window_admission",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "file_evidence_policy",
                        "projection_strategy": "stable_file_evidence_policy",
                    },
                ),
                _message_spec(
                    role="system",
                    content=active_skill_instruction,
                    kind="active_skills",
                    source_ref=",".join(active_skill_meta.get("source_refs") or ()),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "active_skill_runtime",
                        "cache_impact": "task_prefix_active_skill_snapshot",
                        "stability_rule": "active skill instruction is locked once sent for this task invocation; later changes append new tail context",
                    },
                )
                if active_skill_instruction.strip()
                else None,
                *_attachment_context_message_specs(
                    attachment_context_payload,
                    title_prefix="Task execution",
                    source_ref_prefix="task_execution",
                    dynamic_context=dynamic_context,
                ),
                *_task_plan_context_message_specs(
                    task_plan_context_payload,
                    title_prefix="Task execution",
                    source_ref_prefix="task_execution",
                    dynamic_context=dynamic_context,
                ),
                *_evidence_index_cursor_message_specs(
                    evidence_index_cursor_payload,
                    title_prefix="Task execution",
                    source_ref_prefix="task_execution",
                    dynamic_context=dynamic_context,
                ),
                *_editor_context_message_specs(
                    editor_context_payload,
                    title_prefix="Task execution",
                    source_ref_prefix="task_execution",
                    dynamic_context=dynamic_context,
                ),
                *task_state_replay_specs,
                _runtime_payload_spec(
                    role="system",
                    title="Task start inherited context",
                    payload=inherited_start_context_payload,
                    kind="task_start_inherited_context",
                    source_ref=str(inherited_start_context_payload.get("handoff_ref") or inherited_start_context_payload.get("handoff_id") or ""),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="ref_only",
                    metadata={
                        **_dynamic_context_segment_metadata(dynamic_context, source="turn_to_task_context_handoff"),
                        "cache_impact": "task_prefix_inherited_context_snapshot",
                        "stability_rule": "task start inherited context is immutable after handoff; later updates are appended as task deltas",
                    },
                )
                if inherited_start_context_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Task execution bound runtime context",
                    payload=bound_task_runtime_context_payload,
                    kind="bound_task_runtime_context",
                    source_ref=bound_task_context.source_ref,
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="ref_only",
                    metadata={
                        "authority_class": "bound_task_runtime_context",
                        "semantic_layer": "L7_bound_task_runtime_context",
                        "cache_impact": "task_prefix_bound_runtime_snapshot",
                        "stability_rule": "bound runtime context is a hashable snapshot; changed file/artifact/rehydration state must append a later delta",
                        "content_source": "harness.runtime.bound_task_context",
                    },
                )
                if bound_task_runtime_context_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Task current exact read evidence",
                    payload=read_evidence_prompt_payload,
                    kind="read_evidence_injection",
                    source_ref=_read_evidence_prompt_source_ref(read_evidence_prompt_payload, fallback=packet_id),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "read_evidence_injection",
                        "projection_strategy": "current_exact_read_once_historical_refs",
                        "content_source": "harness.runtime.dynamic_context.read_evidence_projector",
                        "cache_impact": "task_prefix_read_evidence_snapshot",
                        "stability_rule": "exact read evidence already selected for this invocation is a stable snapshot; newer reads append later observations",
                    },
                )
                if read_evidence_prompt_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Task execution graph node runtime context",
                    payload=graph_node_runtime_context_payload,
                    kind="graph_node_runtime_context",
                    source_ref="graph_node_runtime_context",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="ref_only",
                    metadata={
                        "volatility_reason": "graph node authorized inputs, memory snapshots, loop state, and upstream artifact payloads vary per node execution",
                        "cache_impact": "volatile",
                    },
                )
                if graph_node_runtime_context_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Task execution runtime boundary",
                    payload=dynamic_payload,
                    preamble=runtime_instruction,
                    kind="task_runtime_boundary_dynamic",
                    source_ref="agent_visible_runtime_projection",
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "runtime_boundary",
                        "cache_impact": "task_prefix_runtime_boundary_snapshot",
                        "projection_strategy": "agent_visible_runtime_boundary",
                        "content_source": "runtime.dynamic_context.runtime_delta_projection",
                        "stability_rule": "runtime boundary is a selected model-visible snapshot; actual per-invocation deltas remain in volatile_task_state and incremental_context_frame",
                    },
                ),
                _message_spec(
                    role="system",
                    content=runtime_lifecycle_instruction,
                    kind="lifecycle_runtime_guidance",
                    source_ref=",".join(prompt_mount_plan.runtime_lifecycle_prompt_refs),
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "runtime_lifecycle_guidance",
                        "lifecycle_prompt_keys": list(prompt_mount_plan.runtime_lifecycle_prompt_keys),
                        "lifecycle_trigger_reasons": dict(prompt_mount_plan.runtime_lifecycle_trigger_reasons),
                        "volatility_reason": "runtime lifecycle guidance is selected from active state such as memory, observations, steering, or recovery",
                        "cache_impact": "volatile_suffix_only",
                    },
                )
                if runtime_lifecycle_instruction.strip()
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Task execution current state",
                    payload=volatile_payload,
                    kind="volatile_task_state",
                    source_ref="task_execution_current_state",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata=_dynamic_context_segment_metadata(dynamic_context, source="task_state"),
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Task runtime memory context",
                    payload=runtime_memory_context_payload,
                    kind="runtime_memory_context",
                    source_ref=_runtime_memory_context_source_ref(runtime_memory_context_payload),
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata={
                        "authority_class": "runtime_memory_context",
                        "content_source": "memory_system.runtime_memory_context",
                        "volatility_reason": "selected memory context can change on each task invocation and belongs in the dynamic tail",
                        "cache_impact": "volatile_suffix_only",
                    },
                )
                if runtime_memory_context_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Task execution incremental context frame",
                    payload={"incremental_context_frame": incremental_context_frame_payload},
                    kind="incremental_context_frame",
                    source_ref=TASK_EXECUTION_INCREMENTAL_CONTEXT_FRAME_SOURCE_REF,
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata={
                        "authority_class": "incremental_context_frame",
                        "runtime_fragment_role": "task_execution_delta_explanation",
                        "volatility_reason": "task execution incremental frame changes each invocation and must stay in the volatile suffix",
                        "cache_impact": "volatile_suffix_only",
                        "content_source": "harness.runtime.incremental_context_frame",
                    },
                ),
                _runtime_payload_spec(
                    role="user",
                    title="User steering updates for this task",
                    payload=user_steering_payload,
                    kind="user_steering_updates",
                    source_ref=_user_steering_source_ref(user_steering_payload),
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "user_task_steer",
                        "volatility_reason": "user steer queue changes whenever the user adds or the executor consumes active task guidance",
                        "projection_strategy": "preserve_user_supplied_task_steer",
                        "cache_impact": "volatile_suffix_only",
                        "steer_refs": [
                            str(item.get("steer_id") or "")
                            for item in list(user_steering_payload.get("pending_user_steers") or [])
                            if isinstance(item, dict) and str(item.get("steer_id") or "")
                        ],
                        "pending_user_steer_count": int(user_steering_payload.get("pending_user_steer_count") or 0),
                    },
                )
                if user_steering_payload
                else None,
                _message_spec(
                    role="assistant",
                    content=graph_node_completion_prefix,
                    kind="graph_node_completion_prefix",
                    source_ref="graph_node_completion_prefix",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="preserve",
                    metadata={
                        "completion_mode": "chat_prefix",
                        "provider_protocol": "deepseek_chat_prefix_completion",
                        "volatility_reason": "graph loop cursor and current unit heading vary per node execution",
                        "cache_impact": "volatile_suffix_only",
                    },
                    prefix=True,
                )
                if graph_node_completion_prefix
                else None,
            ],
            enforce_dynamic_context_reports=True,
        )
        content_fragments = build_content_fragments_from_message_specs(
            segment_plan=segment_plan,
            message_specs=message_specs,
            fallback_model_messages=model_messages,
        )
        task_dynamic_refs = (
            "agent_visible_runtime_projection",
            "operation_authorization",
            "active_skills",
            "recovery_packet",
            "task_start_inherited_context",
            "task_plan_context",
            "evidence_index_cursor",
            "editor_context_index",
        )
        task_volatile_refs = (
            "runtime_envelope",
            "task_state",
            "turn_to_task_context_handoff",
            "user_steering_updates",
            "pending_user_steers",
            "active_contract_revisions",
            "runtime_control_signals",
            "current_editor_evidence_delta",
            "incremental_context_frame",
            "lifecycle_runtime_guidance",
            "runtime_memory_context",
        )
        prompt_manifest = build_runtime_prompt_manifest(
            invocation_kind="task_execution",
            assembly=_merge_prompt_assemblies(
                prompt_assembly,
                personality_prompt_assembly,
                environment_prompt_assembly,
                lifecycle_prompt_assembly,
                runtime_lifecycle_prompt_assembly,
                agent_prompt_assembly,
                task_prompt_assembly,
                invocation_kind="task_execution",
            ),
            packet_id=packet_id,
            dynamic_projection_refs=task_dynamic_refs,
            volatile_state_refs=task_volatile_refs,
        ).to_dict()
        prompt_manifest["segment_plan_ref"] = segment_plan.segment_plan_id
        prompt_manifest["prompt_assembly_plan_ref"] = segment_plan.provider_policy_ref
        prompt_manifest["runtime_prompt_source_manifest_ref"] = source_manifest.manifest_id
        prompt_manifest["runtime_prompt_sources"] = source_manifest.to_dict()
        prompt_manifest["prompt_slot_plan_ref"] = slot_plan.plan_id
        prompt_manifest["prompt_slot_plan"] = slot_plan.to_dict()
        prompt_manifest["runtime_context_load_plan_ref"] = context_load_plan.plan_id
        prompt_manifest["runtime_context_load_plan"] = context_load_plan.to_dict()
        prompt_manifest["prompt_mount_plan"] = _prompt_mount_plan_manifest_payload(
            prompt_mount_plan,
            prompt_policy=prompt_policy,
        )
        prompt_manifest["dynamic_context_report"] = dynamic_context.to_report_dict()
        prompt_manifest["context_window"] = _context_window_report(
            session_context={},
            history=[],
            dynamic_context=dynamic_context,
        )
        _attach_project_instruction_manifest(prompt_manifest, project_instruction_bundle)
        action_schema_manifest_payload = _attach_action_schema_manifest(prompt_manifest, action_schema_manifest)
        artifact_scope_manifest_payload = _attach_artifact_scope_manifest(prompt_manifest, artifact_scope_manifest)
        tool_catalog_manifest_payload = _attach_tool_catalog_manifest(prompt_manifest, tool_catalog_manifest)
        task_contract_manifest_payload = _attach_task_contract_manifest(prompt_manifest, task_contract_manifest)
        bound_task_context_manifest_payload = bound_task_context.to_manifest_payload()
        prompt_manifest["bound_task_context_manifest"] = bound_task_context_manifest_payload
        prompt_composition_manifest = _attach_prompt_composition_manifest(
            prompt_manifest,
            invocation_kind="task_execution",
            packet_id=packet_id,
            segment_plan=segment_plan.to_dict(),
            runtime_slot_plan=slot_plan,
            dynamic_projection_refs=task_dynamic_refs,
            volatile_state_refs=task_volatile_refs,
            diagnostics={"compiler_entrypoint": "compile_task_execution_packet"},
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
            invocation_kind="task_execution",
            invocation_index=invocation_index,
            session_id=session_id,
            task_run_id=task_run_id,
            model_messages=model_messages,
            segment_plan=segment_plan.to_dict(),
            prompt_composition_manifest=prompt_composition_manifest,
            action_schema_manifest=action_schema_manifest_payload,
            artifact_scope_manifest=artifact_scope_manifest_payload,
            tool_catalog_manifest=tool_catalog_manifest_payload,
            task_contract_manifest=task_contract_manifest_payload,
            bound_task_context_manifest=bound_task_context_manifest_payload,
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
            available_tools=tool_payloads,
            allowed_action_types=allowed_actions,
            observation_refs=dynamic_context.observation_refs,
            artifact_refs=dynamic_context.artifact_refs,
            context_refs=dynamic_context.context_refs,
            output_contract={"schema": schema, "format": "json_object", "planning_protocol": planning_protocol},
            hidden_control_refs={"task_run_id": task_run_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
                "action_schema_manifest": action_schema_manifest_payload,
                "artifact_scope_manifest": artifact_scope_manifest_payload,
                "tool_catalog_manifest": tool_catalog_manifest_payload,
                "task_contract_manifest": task_contract_manifest_payload,
                "bound_task_context_manifest": bound_task_context_manifest_payload,
                "model_input_authority": "prompt_composition.message_projection",
                "runtime_packet_context": packet_context.to_dict(),
                "artifact_scope": {
                    **sandbox_execution_scope.to_diagnostics(),
                    "artifact_root_authority": artifact_scope.authority,
                },
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
        prompt_pack_refs = _prompt_pack_refs_for_invocation(profile_payload, invocation_kind="tool_observation_followup")
        tool_payloads = tuple(dict(item) for item in list(available_tools or []) if isinstance(item, dict))
        agent_visible_runtime_projection = _agent_visible_runtime_projection(
            invocation_kind="tool_observation_followup",
            allowed_action_types=("respond", "ask_user", "tool_call", "request_task_run", "block"),
            profile_payload=profile_payload,
            environment_payload=environment_payload,
            operation_authorization=dict(assembly_payload.get("operation_authorization") or {}),
            available_tools=tool_payloads,
            permission_mode=str(assembly_payload.get("permission_mode") or "default"),
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
        )
        prompt_mount_plan = prompt_mount_plan_for_invocation(
            _prompt_mount_plan_payload_from_runtime_assembly(assembly_payload),
            invocation_kind="tool_observation_followup",
            allowed_actions=("respond", "ask_user", "tool_call", "request_task_run", "block"),
            observations=tuple(dict(item) for item in list(observations or []) if isinstance(item, dict)),
            visible_tools=tool_payloads,
            session_context=dict(session_context or {}),
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
        )
        tool_catalog_manifest = _build_tool_catalog_manifest_for_mount_plan(
            invocation_kind="tool_observation_followup",
            tool_payloads=tool_payloads,
            source_ref="tool_observation_followup.available_tools",
            prompt_mount_plan=prompt_mount_plan,
        )
        tool_schema_catalog_payload = stable_tool_schema_catalog_payload(
            tool_payloads=tool_payloads,
            tool_catalog_manifest=tool_catalog_manifest,
        )
        tool_index_payload = (
            tool_catalog_manifest.to_model_visible_payload(include_catalog_hash=True)
            if tool_payloads
            else {}
        )
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="tool_observation_followup",
            prompt_refs=_agent_prompt_refs_for_invocation(assembly_payload, invocation_kind="tool_observation_followup"),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        personality_prompt_assembly = self._assemble_personality_prompt_layer(
            prompt_mount_plan=prompt_mount_plan,
            invocation_kind="tool_observation_followup",
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        environment_prompt_assembly, lifecycle_prompt_assembly = self._assemble_environment_prompt_layers(
            prompt_mount_plan=prompt_mount_plan,
            agent_profile_ref=agent_profile_ref,
        )
        runtime_lifecycle_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=tuple(prompt_mount_plan.runtime_lifecycle_prompt_refs or ()),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(prompt_mount_plan.selected_environment_id or ""),
        )
        project_instruction_bundle = collect_project_instruction_bundle(base_dir=self.base_dir)
        runtime_instruction = _runtime_projection_instruction(agent_visible_runtime_projection)
        environment_instruction = render_environment_instruction(
            environment_payload,
            environment_prompt_assembly=environment_prompt_assembly,
        )
        lifecycle_instruction = render_lifecycle_instruction(lifecycle_prompt_assembly)
        runtime_lifecycle_instruction = render_lifecycle_instruction(runtime_lifecycle_prompt_assembly)
        personality_instruction = render_personality_prompt_instruction(personality_prompt_assembly)
        agent_instruction = render_agent_prompt_instruction(agent_prompt_assembly, invocation_kind="tool_observation_followup")
        skill_candidate_instruction = _skill_candidate_instruction(assembly_payload)
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
        dynamic_payload = dict(dynamic_context.dynamic_runtime_projection or {})
        runtime_memory_context_payload = _memory_context_model_visible_payload(
            dict(session_context or {}).get("memory_context")
        )
        volatile_payload = dict(dynamic_context.volatile_request_projection or {})
        session_history_payload, current_request_payload = _split_volatile_request_payload(volatile_payload)
        attachment_context_payload, current_request_payload = _extract_attachment_context_payload(current_request_payload)
        task_plan_context_payload, current_request_payload = _extract_task_plan_context_payload(current_request_payload)
        editor_context_payload, current_request_payload = _extract_editor_context_payload(current_request_payload)
        model_messages, segment_plan, message_specs, source_manifest, slot_plan, context_load_plan = _model_messages_and_segment_plan(
            packet_id=packet_id,
            invocation_kind="tool_observation_followup",
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
                    title="Observation followup tool schema catalog",
                    payload=tool_schema_catalog_payload,
                    kind="tool_schema_catalog",
                    source_ref=_short_hash(tool_catalog_manifest.tool_catalog_hash),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "provider_tool_schema_catalog",
                        "content_source": "harness.runtime.compiler.stable_tool_schema_catalog",
                    },
                )
                if tool_schema_catalog_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Observation followup tool index",
                    payload=tool_index_payload,
                    kind="tool_index_stable",
                    source_ref=_short_hash(tool_catalog_manifest.tool_catalog_hash),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                )
                if tool_index_payload
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Observation followup stable contract",
                    payload=stable_payload,
                    kind="task_stable",
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
                    source_ref="file_evidence_policy_stable.read_window_admission",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "file_evidence_policy",
                        "projection_strategy": "stable_file_evidence_policy",
                    },
                ),
                _message_spec(
                    role="system",
                    content=lifecycle_instruction,
                    kind="lifecycle_stable",
                    source_ref=",".join(prompt_mount_plan.lifecycle_prompt_refs),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "runtime_lifecycle_protocol",
                        "lifecycle_prompt_keys": list(prompt_mount_plan.lifecycle_prompt_keys),
                        "lifecycle_trigger_reasons": dict(prompt_mount_plan.lifecycle_trigger_reasons),
                    },
                )
                if lifecycle_instruction.strip()
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
                _message_spec(
                    role="system",
                    content=skill_candidate_instruction,
                    kind="skill_candidates",
                    source_ref="runtime_skill_candidates",
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "active_skill_runtime",
                        "cache_impact": "task_prefix_stable_within_turn",
                        "stability_rule": "selected skill candidates are stable for the current turn; if rebuilt differently prefix lock must downgrade the segment",
                    },
                ),
                _message_spec(
                    role="system",
                    content=runtime_lifecycle_instruction,
                    kind="lifecycle_runtime_guidance",
                    source_ref=",".join(prompt_mount_plan.runtime_lifecycle_prompt_refs),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "runtime_lifecycle_guidance",
                        "lifecycle_prompt_keys": list(prompt_mount_plan.runtime_lifecycle_prompt_keys),
                        "lifecycle_trigger_reasons": dict(prompt_mount_plan.runtime_lifecycle_trigger_reasons),
                        "cache_impact": "task_prefix_stable_within_turn",
                        "stability_rule": "runtime lifecycle guidance is locked once sent for this turn; later changes must append a new tail segment",
                    },
                )
                if runtime_lifecycle_instruction.strip()
                else None,
                _runtime_payload_spec(
                    role="system",
                    title="Task current exact read evidence",
                    payload=read_evidence_prompt_payload,
                    kind="read_evidence_injection",
                    source_ref=_read_evidence_prompt_source_ref(read_evidence_prompt_payload, fallback=packet_id),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "authority_class": "read_evidence_injection",
                        "projection_strategy": "current_exact_read_once_historical_refs",
                        "content_source": "harness.runtime.dynamic_context.read_evidence_projector",
                        "cache_impact": "task_prefix_read_evidence_snapshot",
                        "stability_rule": "exact read evidence already sent in this turn is a stable snapshot; later reads append new observations",
                    },
                )
                if read_evidence_prompt_payload
                else None,
                *_attachment_context_message_specs(
                    attachment_context_payload,
                    title_prefix="Observation followup",
                    source_ref_prefix="observation_followup",
                    dynamic_context=dynamic_context,
                ),
                *_task_plan_context_message_specs(
                    task_plan_context_payload,
                    title_prefix="Observation followup",
                    source_ref_prefix="observation_followup",
                    dynamic_context=dynamic_context,
                ),
                *_editor_context_message_specs(
                    editor_context_payload,
                    title_prefix="Observation followup",
                    source_ref_prefix="observation_followup",
                    dynamic_context=dynamic_context,
                ),
                *_session_history_message_specs(
                    session_history_payload,
                    title="Observation followup session history",
                    source_ref="observation_followup_session_history",
                    metadata=_dynamic_context_segment_metadata(dynamic_context, source="session_history") if session_history_payload else {},
                ),
                *_provider_protocol_message_specs(
                    session_context,
                    source_ref="observation_followup_api_transcript",
                    projection_policy=projection_policy,
                    storage_root=dynamic_context_storage_root(self.base_dir, assembly_payload) or self.base_dir,
                    storage_run_id=session_id,
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Observation followup dynamic runtime",
                    payload=dynamic_payload,
                    preamble=runtime_instruction,
                    kind="dynamic_projection",
                    source_ref="agent_visible_runtime_projection",
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="summarize",
                    metadata=_dynamic_context_segment_metadata(dynamic_context, source="runtime_delta"),
                ),
                _runtime_payload_spec(
                    role="system",
                    title="Observation followup runtime memory context",
                    payload=runtime_memory_context_payload,
                    kind="runtime_memory_context",
                    source_ref=_runtime_memory_context_source_ref(runtime_memory_context_payload),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="summarize",
                    metadata={
                        "authority_class": "runtime_memory_context",
                        "content_source": "memory_system.runtime_memory_context",
                        "cache_impact": "task_prefix_memory_snapshot",
                        "stability_rule": "selected memory context is a stable snapshot for this turn; later changes append a new tail segment",
                    },
                )
                if runtime_memory_context_payload
                else None,
                _runtime_payload_spec(
                    role="user",
                    title="Observation followup current request",
                    payload=current_request_payload,
                    kind="tool_observations",
                    source_ref="observation_followup_current_request",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="ref_only",
                    metadata=_dynamic_context_segment_metadata(dynamic_context, source="current_request"),
                ),
            ],
            enforce_dynamic_context_reports=True,
        )
        content_fragments = build_content_fragments_from_message_specs(
            segment_plan=segment_plan,
            message_specs=message_specs,
            fallback_model_messages=model_messages,
        )
        observation_dynamic_refs = (
            "agent_visible_runtime_projection",
            "operation_authorization",
            "history",
            "task_plan_context",
            "editor_context_index",
            "lifecycle_runtime_guidance",
            "runtime_memory_context",
        )
        observation_volatile_refs = (
            "runtime_envelope",
            "turn_id",
            "user_message",
            "observations",
            "current_editor_evidence_delta",
        )
        prompt_manifest = build_runtime_prompt_manifest(
            invocation_kind="tool_observation_followup",
            assembly=_merge_prompt_assemblies(
                prompt_assembly,
                personality_prompt_assembly,
                environment_prompt_assembly,
                lifecycle_prompt_assembly,
                runtime_lifecycle_prompt_assembly,
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
        prompt_manifest["prompt_slot_plan_ref"] = slot_plan.plan_id
        prompt_manifest["prompt_slot_plan"] = slot_plan.to_dict()
        prompt_manifest["runtime_context_load_plan_ref"] = context_load_plan.plan_id
        prompt_manifest["runtime_context_load_plan"] = context_load_plan.to_dict()
        prompt_manifest["prompt_mount_plan"] = prompt_mount_plan.to_dict()
        prompt_manifest["dynamic_context_report"] = dynamic_context.to_report_dict()
        prompt_manifest["context_window"] = _context_window_report(
            session_context=session_context,
            history=history,
            dynamic_context=dynamic_context,
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
            allowed_action_types=("respond", "ask_user", "tool_call", "request_task_run", "block"),
            observation_refs=dynamic_context.observation_refs,
            artifact_refs=dynamic_context.artifact_refs,
            context_refs=dynamic_context.context_refs,
            output_contract={"schema": schema, "format": "json_object"},
            hidden_control_refs={"agent_invocation_id": agent_invocation_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
                "tool_catalog_manifest": tool_catalog_manifest_payload,
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
    ) -> tuple[PromptAssemblyResult, PromptAssemblyResult]:
        base_environment_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=tuple(prompt_mount_plan.base_prompt_refs or ()),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(prompt_mount_plan.base_environment_id or ""),
        )
        overlay_environment_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=tuple(prompt_mount_plan.overlay_prompt_refs or ()),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(prompt_mount_plan.selected_environment_id or ""),
        )
        environment_prompt_assembly = _merge_prompt_assemblies(
            base_environment_prompt_assembly,
            overlay_environment_prompt_assembly,
            invocation_kind="environment",
        )
        lifecycle_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=tuple(prompt_mount_plan.lifecycle_prompt_refs or ()),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(prompt_mount_plan.selected_environment_id or ""),
        )
        return environment_prompt_assembly, lifecycle_prompt_assembly

    def _assemble_personality_prompt_layer(
        self,
        *,
        prompt_mount_plan: Any,
        invocation_kind: str,
        agent_profile_ref: str,
        task_environment_ref: str,
    ) -> PromptAssemblyResult:
        return self._assemble_prompt_refs(
            invocation_kind=invocation_kind,
            prompt_refs=tuple(getattr(prompt_mount_plan, "personality_prompt_refs", ()) or ()),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )


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
    return {
        "authority": "harness.loop.model_action_request",
        "action_type": "respond|ask_user|tool_call|request_task_run|active_work_control|resume_recoverable_work|block",
        "json_action_shape_rules": [
            "提交一个可唯一识别的结构化动作；推荐使用一个顶层 JSON 对象，Markdown 代码块或简短说明只会作为传输包装被忽略。",
            "respond 必须把用户可见最终回复写在顶层 final_answer；不要写 payload.final_answer、payload.content、action.final_answer 或 action.content。",
            "ask_user 必须把用户要回答的问题写在顶层 user_question；不要使用 provider-native ask_user 工具调用。",
            "block 必须把真实阻塞原因写在顶层 blocking_reason。",
            "tool_call 使用顶层 tool_call: {tool_name, args}；普通工具可以使用 provider-native tool_call；控制动作可以使用 JSON action 或 provider-native canonical control signal，但同一轮不要混入其它动作来源。",
        ],
        "action_selection_rules": [
            "先识别用户当前输入本身要你回应什么：提问、质疑、状态追问、纠错、继续执行、修改目标、请求交付或闲聊。任何 action 都不能绕过这个输入意图。",
            "默认优先在当前 turn 内完成用户请求；复杂、跨文件或需要审查不自动等于 Task。",
            "只有当当前 turn 的自然边界不足以承载目标、计划、状态、恢复、验收、审计、用户可追踪阶段反馈或资源隔离时，才申请 request_task_run。",
            "先判断目标是否需要持久工作生命周期：跨 turn 状态记录、暂停/恢复/停止/replan、明确完成证据、长期执行、工具/上下文预算恢复、独立验收或资源隔离。",
            "审查、评估、排查、review、audit、架构梳理或多文件链路检查可以留在普通 ReAct/tool_call，只要当前 turn 能通过有限工具调用形成可靠结论、验证并收口。",
            "当工作范围、状态、验收或恢复需求已经超过当前 turn 能稳定保存和交付的边界时，先形成足够的 task_contract_seed，再申请 request_task_run。",
            "如果用户当前输入是问题、质疑、追问、状态询问、纠错或询问为什么，必须先对这个输入给出公开回应；只有用户明确要求继续/执行/恢复当前任务时，才允许 active_work_control 只承接执行。",
            "如果需要 Task 但目标、范围、计划或验收标准不足以形成 task_contract_seed，必须选择 ask_user 补齐关键缺口。",
            "普通 tool_call 是合法路径，只要当前 turn 仍能保住目标、证据、反馈和收口；在状态控制、验收或恢复需求越过 turn 边界前升级 Task。",
        ],
        "public_response_obligation": {
            "authority": "model_semantic_response",
            "rule": "你必须回应用户当前输入本身。回应可以是直接回答、解释你的公开判断、说明需要查证哪个事实才能判断、指出当前不能回答的原因，或说明会把用户的新要求并入本轮处理范围。内部工具、长期任务和结构化 action 只能服务这个回应，不能替代这个回应。",
            "first_visible_response": [
                "如果已经足以回答，使用 respond/final_answer。",
                "如果需要查证后才能判断，使用 tool_call/tool_calls，同时在 public_progress_note 中说明要查证的公开事实和为什么它关系到用户问题；public_action_state.current_judgment 可以补充当前公开判断，但不能替代空白回应；不要写工具名、动作字段或隐藏推理。",
                "如果用户是在追问为什么、哪里卡住、是否正常、为什么没回应，必须先解释当前已知状态或你需要核对的状态对象；不要直接继续旧任务。",
                "如果用户只是明确说继续、恢复、接着执行，并且没有提出新问题，才可以用 active_work_control 或 request_task_run 承接执行。"
            ],
            "tool_observation_reporting": {
                "must_explain_when": [
                    "观察结果回答了用户问题，或改变了你对用户问题的判断。",
                    "观察结果发现错误、阻塞、权限问题、缺失信息、测试失败、运行异常或与用户预期冲突。",
                    "观察结果改变下一步计划、任务范围、验收状态、风险或是否需要用户确认。",
                    "观察结果完成了用户可见阶段，需要让用户知道结论或下一步。",
                    "观察结果推翻了你先前的公开判断或暴露出不确定性。",
                    "你已经连续跨多个文件、多个工具批次或多轮观察推进，或者刚处理过失败恢复、写入、验证、范围切换或阶段结束，继续请求工具前需要给用户一个阶段反馈。"
                ],
                "may_keep_internal_when": [
                    "观察只是短链路的低层文件读取、搜索、目录枚举或格式检查，且没有改变公开判断、风险、计划或用户问题的答案。",
                    "观察只是为后续工具调用准备上下文，单独展示不会帮助用户理解进展。",
                    "结构化工具槽已经足以表达动作状态，而没有新的语义结论。"
                ],
                "explanation_shape": "需要解释时，只说结论、依据的可见事实、影响和下一步；不要粘贴原始工具输出，不要暴露内部事件编号、动作字段、隐藏推理或无关路径。不要求每个低层工具都单独反馈，但不允许长时间任务只剩工具列表而没有你的阶段判断。"
            },
            "non_response_examples": [
                "只输出 tool_call、request_task_run 或 active_work_control，没有解释用户当前问题。",
                "只说正在处理、开始处理、稍等、我会看看，但没有说明要判断什么公开事实。",
                "把工具名、动作字段或执行步骤列表当成给用户的回答。"
            ]
        },
        "public_progress_note": "一句用户可理解的公开语义回应；用户输入触发的 tool_call、request_task_run 或 active_work_control 必须填写，用于回应用户当前输入或说明为什么需要先查证。不要写工具名、动作字段、内部事件、隐藏推理或泛化占位词；不要只说正在处理、开始处理、稍等、我会看看；不得预测工具结果，不得把尚未完成的动作说成已经完成。",
        "public_action_state": {
            "visible_status": "可选机器状态；thinking|waiting_for_tool|tool_returned|responding|blocked。不是用户可见正文；不要复制到 public_progress_note、current_judgment、next_action、final_answer 或 blocking_reason。",
            "current_judgment": "可选；你对当前公开状态的简短说明。首次工具调用前，如果你已经能向用户说明真实开局判断或处理边界，就把这句话写在这里；如果只是要表达正在思考、正在处理或等待工具，必须留空。只能写本轮已经确定的事实或边界，不写隐藏推理。",
            "next_action": "可选；你下一步准备执行的动作。必须与 action_type 对齐：respond 时是整理回复；ask_user 时是向用户确认；需要持续执行时是进入执行流程；block 时是说明阻塞。tool_call 时通常留空；只有在观察返回后形成真实阶段方向，才写给用户能理解的下一步，不要把工具调用动作或机器状态改写成公开判断文本。",
            "evidence_refs": ["可选；已经返回且可被用户理解的 observation/event/artifact ref；没有返回结果时留空"],
            "open_risks": ["可选；已经观察到的公开阻塞或风险；不要写预测性风险"],
            "completion_status": "可选机器状态；working|waiting_for_tool|verifying|ready_to_finish|blocked。不是用户可见正文；不要复制到公开反馈、阶段判断、下一步、阻塞说明或最终回答。"
        },
        "final_answer": "",
        "user_question": "",
        "blocking_reason": "",
        "tool_call": {"tool_name": "", "args": {}},
        "request_task_run_shape_rules": [
            "request_task_run 必须是单个结构化控制信号；可以使用 JSON action，也可以使用 provider-native canonical request_task_run；如果文本里带代码块或简短说明，只提取唯一 action-like 对象执行。",
            "开启 Task 前先按 request_task_run_required_skeleton 自检；缺少任一必填路径时不要申请 Task，改用 ask_user 补齐或继续当前 turn 查证。",
            "不要使用 payload 包裹任务字段；顶层只能放 action_type、authority、public_progress_note、public_action_state、task_contract_seed、completion_contract、permission_request、diagnostics 等动作控制字段。",
            "task_contract_seed 的最小必填是 user_visible_goal、task_run_goal、working_scope.target_objects 和完成证据。",
        ],
        "request_task_run_required_skeleton": {
            "instruction": "这是开启持续任务的最小必填骨架。用当前用户目标和已观察事实替换占位内容；不要删除这些键，不要把它们放到 JSON 顶层。",
            "required_top_level": ["authority", "action_type", "public_progress_note", "public_action_state", "task_contract_seed"],
            "required_task_contract_seed_paths": [
                "user_visible_goal",
                "task_run_goal",
                "working_scope.target_objects",
                "completion_criteria",
            ],
            "minimal_action": {
                "authority": "harness.loop.model_action_request",
                "action_type": "request_task_run",
                "public_progress_note": "说明为什么当前工作需要进入持续任务生命周期。",
                "public_action_state": {
                    "current_judgment": "说明当前 turn 无法稳定承载的边界。",
                    "next_action": "进入持续任务执行流程。",
                },
                "task_contract_seed": {
                    "user_visible_goal": "用户能看懂的任务目标。",
                    "task_run_goal": "执行生命周期要持续推进的具体任务目标。",
                    "working_scope": {
                        "target_objects": ["要处理的文件、模块、目录、对象或问题域"],
                        "source_refs": ["用户消息或已观察证据"],
                        "excluded_scope": [],
                        "known_constraints": ["用户明确约束、质量要求或排除项"],
                    },
                    "completion_criteria": ["可验收完成标准"],
                },
            },
        },
        "resume_recoverable_work_shape_rules": [
            "resume_recoverable_work 必须是单个结构化控制信号；可以使用 JSON action，也可以使用 provider-native canonical resume_recoverable_work；如果文本里带代码块或简短说明，只提取唯一 action-like 对象执行。",
            "task_run_id 和 continuation_id 必须放在 recovery_resume 对象内；不允许放在 JSON 顶层，也不要使用 payload 包裹。",
            "只使用 recovery_resume 候选中的可恢复句柄；不要从聊天文本、旧 assistant closeout 或文件内容里猜测 task_run_id/continuation_id。",
            "恢复动作只恢复同一个 task_run，不创建新任务；如果句柄缺失、失效或用户要求改目标，选择 respond、ask_user 或 block 说明原因。",
        ],
        "minimal_valid_resume_recoverable_work_example": {
            "authority": "harness.loop.model_action_request",
            "action_type": "resume_recoverable_work",
            "public_progress_note": "已确认存在可恢复任务，我会从已提供的断点继续原任务。",
            "public_action_state": {
                "current_judgment": "恢复句柄和任务标识已提供。",
                "next_action": "恢复原任务执行。",
            },
            "recovery_resume": {
                "task_run_id": "taskrun:可恢复任务 id",
                "continuation_id": "cont:continuation id",
            },
        },
        "minimal_valid_request_task_run_example": {
            "authority": "harness.loop.model_action_request",
            "action_type": "request_task_run",
            "public_progress_note": "这项工作需要跨 turn 保存目标、计划、证据和验收状态，我会申请进入持续任务生命周期。",
            "public_action_state": {
                "current_judgment": "当前 turn 已不足以稳定承载任务目标、恢复和验收边界。",
                "next_action": "进入持续任务执行流程。",
            },
            "task_contract_seed": {
                "user_visible_goal": "完整审查指定系统并输出可靠报告。",
                "task_run_goal": "读取指定模块、记录证据、审查架构和提示词链路，并输出可验收报告。",
                "working_scope": {
                    "target_objects": ["要审查的目录、模块、文件或子系统"],
                    "workspace_refs": ["项目或工作区引用"],
                    "source_refs": ["用户消息、已观察到的文件清单或资料引用"],
                    "excluded_scope": ["明确不处理的范围"],
                    "known_constraints": ["用户明确的质量标准和边界"],
                },
                "completion_criteria": ["读取关键证据", "形成问题清单和结论", "交付报告或修复建议"],
            },
        },
        "task_contract_seed": {
            "user_visible_goal": "用户可理解的任务目标，必填",
            "task_run_goal": "给执行生命周期使用的任务目标，必填",
            "working_scope": {
                "target_objects": ["任务要处理的文件、材料、对象或目标；可以是路径、引用或结构化对象"],
                "workspace_refs": ["可选；明确要使用的工作区或项目引用"],
                "source_refs": ["可选；用户给出的资料、链接、消息或 observation 引用"],
                "excluded_scope": ["可选；明确不处理的范围"],
                "known_constraints": ["可选；用户明确约束、质量要求、时间或输出限制"]
            },
            "completion_criteria": [
                "可验收的完成标准；至少一条，除非 required_artifacts 或 required_verifications 已提供"
            ],
            "required_artifacts": [
                {
                    "artifact_kind": "交付物类型，例如 markdown_document",
                    "user_visible_name": "用户可理解的交付物名称",
                    "description": "交付物必须包含的内容和质量要求"
                }
            ],
            "required_verifications": [
                {
                    "verification_kind": "self_review|artifact_review|test|manual_acceptance",
                    "description": "验收或验证要求"
                }
            ],
            "plan_ref": "可选；用户已批准或已有记录的计划引用。没有批准计划时不要伪造。",
            "active_work_relationship": "可选；只有 allowed_action_types 包含 request_task_run 时填写。new_work 表示用户要求开启新的持续任务；不要用 request_task_run 恢复、替换或接管旧任务。",
            "plan_requirements": {
                "requires_plan": False,
                "reason": "为什么需要先计划；仅在高影响改动、架构重构、协议变更或用户要求计划时填写。",
                "expected_plan_artifact": "可选；计划书或计划记录的目标位置或引用。"
            },
            "implementation_lock": {
                "plan_ref": "获批计划引用",
                "status": "approved|locked|implementation_locked",
                "approved": False,
                "deviation_policy": "ask_user_or_block_before_changing_approved_plan"
            },
            "acceptance_policy": {},
            "recovery_policy": {}
        },
        "completion_contract": {
            "completion_criteria": [],
            "artifact_requirements": [],
            "required_verifications": []
        },
        "permission_request": {},
        "diagnostics": {},
    }


def task_execution_action_schema() -> dict[str, Any]:
    return {
        "authority": "harness.loop.model_action_request",
        "action_type": "respond|ask_user|tool_call|block",
        "json_action_shape_rules": [
            "提交一个可唯一识别的结构化动作；推荐使用一个顶层 JSON 对象，Markdown 代码块或简短说明只会作为传输包装被忽略。",
            "respond 必须把用户可见最终回复写在顶层 final_answer；不要写 payload.final_answer、payload.content、action.final_answer 或 action.content。",
            "ask_user 必须把用户要回答的问题写在顶层 user_question；不要使用 provider-native ask_user 工具调用。",
            "block 必须把真实阻塞原因写在顶层 blocking_reason。",
            "tool_call 使用顶层 tool_calls 或 tool_call；普通工具可以使用 provider-native tool_call。控制动作必须是单个结构化控制信号，可用 JSON action 或 provider-native canonical control signal；同一轮不要混入其它动作来源。",
        ],
        "public_response_obligation": {
            "authority": "model_semantic_response",
            "rule": "你必须回应用户当前输入本身。回应可以是直接回答、解释你的公开判断、说明需要查证哪个事实才能判断、指出当前不能回答的原因，或说明会把用户的新要求并入本轮处理范围。持续任务执行时，内部工具可以不可见，但工具动作不能替代对用户输入的回应。",
            "first_visible_response": [
                "如果已经足以回答，使用 respond/final_answer。",
                "如果需要查证后才能判断，使用 tool_call/tool_calls，同时在 public_progress_note 中说明要查证的公开事实和为什么它关系到用户问题；public_action_state.current_judgment 可以补充当前公开判断，但不能替代空白回应；不要写工具名、动作字段或隐藏推理。",
                "如果用户是在追问为什么、哪里卡住、是否正常、为什么没回应，必须先解释当前已知状态或你需要核对的状态对象；不要直接继续旧任务。",
                "如果用户只是明确说继续、恢复、接着执行，并且没有提出新问题，才可以只承接执行。"
            ],
            "tool_observation_reporting": {
                "must_explain_when": [
                    "观察结果回答了用户问题，或改变了你对用户问题的判断。",
                    "观察结果发现错误、阻塞、权限问题、缺失信息、测试失败、运行异常或与用户预期冲突。",
                    "观察结果改变下一步计划、任务范围、验收状态、风险或是否需要用户确认。",
                    "观察结果完成了用户可见阶段，需要让用户知道结论或下一步。",
                    "观察结果推翻了你先前的公开判断或暴露出不确定性。",
                    "你已经连续跨多个文件、多个工具批次或多轮观察推进，或者刚处理过失败恢复、写入、验证、范围切换或阶段结束，继续请求工具前需要给用户一个阶段反馈。"
                ],
                "may_keep_internal_when": [
                    "观察只是短链路的低层文件读取、搜索、目录枚举或格式检查，且没有改变公开判断、风险、计划或用户问题的答案。",
                    "观察只是为后续工具调用准备上下文，单独展示不会帮助用户理解进展。",
                    "结构化工具槽已经足以表达动作状态，而没有新的语义结论。"
                ],
                "explanation_shape": "需要解释时，只说结论、依据的可见事实、影响和下一步；不要粘贴原始工具输出，不要暴露内部事件编号、动作字段、隐藏推理或无关路径。不要求每个低层工具都单独反馈，但不允许长时间任务只剩工具列表而没有你的阶段判断。"
            },
            "non_response_examples": [
                "只输出 tool_call 或 block，没有解释用户当前问题。",
                "只说正在处理、开始处理、稍等、我会看看，但没有说明要判断什么公开事实。",
                "把工具名、动作字段或执行步骤列表当成给用户的回答。"
            ]
        },
        "public_progress_note": "一句用户可理解的公开语义回应；用户输入或用户 steer 触发的 tool_call 必须填写，用于回应用户当前输入或说明为什么需要先查证。不要写工具名、动作字段、内部事件、隐藏推理或泛化占位词；不要只说正在处理、开始处理、稍等、我会看看；不得预测工具结果，不得把尚未完成的动作说成已经完成。",
        "public_action_state": {
            "visible_status": "机器状态；thinking|waiting_for_tool|tool_returned|responding|blocked。不是用户可见正文；不要复制到 public_progress_note、current_judgment、next_action、final_answer 或 blocking_reason。",
            "current_judgment": "可选；你对当前公开状态的简短说明。首次工具调用前，如果你已经能向用户说明真实开局判断或处理边界，就把这句话写在这里；如果只是要表达正在思考、正在处理或等待工具，必须留空。只能写本轮已经确定的事实或边界，不写隐藏推理。",
            "next_action": "可选；你下一步准备执行的动作。必须与 action_type 对齐：respond 时是整理回复；ask_user 时是向用户确认；block 时是说明阻塞。tool_call 时通常留空；只有在观察返回后形成真实阶段方向，才写给用户能理解的下一步，不要把工具调用动作或机器状态改写成公开判断文本。",
            "evidence_refs": ["已经返回且可被用户理解的 observation/event/artifact ref；没有返回结果时留空"],
            "open_risks": ["已经观察到的公开阻塞或风险；没有则留空；不要写预测性风险"],
            "completion_status": "机器状态；working|waiting_for_tool|verifying|ready_to_finish|blocked。不是用户可见正文；不要复制到公开反馈、阶段判断、下一步、阻塞说明或最终回答。"
        },
        "final_answer": "",
        "user_question": "",
        "blocking_reason": "",
        "tool_calls": [
            {"tool_name": "本轮可见工具名", "args": {"参数名": "参数值"}}
        ],
        "diagnostics": {
            "artifacts": [
                {"path": "真实交付物路径", "kind": "artifact kind", "summary": "产物说明"}
            ],
            "verification": "简短说明自审和验收结果",
            "consumed_steer_refs": [
                "如果本轮处理了 pending_user_steers 中的某条用户补充要求，填写对应 steer_id；未处理则留空"
            ],
            "contract_revision_decisions": [
                {
                    "revision_id": "active_contract_revisions 中的 revision_id",
                    "steer_ref": "对应 steer_id",
                    "status": "accepted|needs_user|rejected",
                    "reason": "简短说明为什么这样裁决",
                    "requires_user_confirmation": False,
                    "proposed_goal": "",
                    "proposed_acceptance_criteria": [],
                }
            ],
            "plan_deviation": {
                "status": "none|within_plan|needs_user|blocked",
                "plan_ref": "如果任务目标绑定了计划，填写对应 plan_ref",
                "reason": "如需偏离计划，说明具体原因；没有偏离时留空"
            },
        },
    }


def _current_work_boundary_receipt_model_visible_payload(receipt: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(receipt or {})
    if not payload:
        return {}
    decision = dict(dict(payload.get("diagnostics") or {}).get("decision") or {})
    operations = current_work_operation_availability_from_receipt(payload)
    return {
        "receipt_id": str(payload.get("receipt_id") or ""),
        "boundary_decision": str(payload.get("boundary_decision") or ""),
        "observation_state": str(payload.get("observation_state") or ""),
        "operation_availability": operations,
        "active_work_ref": dict(payload.get("active_work_ref") or {}),
        "read_only_context": not bool(operations.get("active_work_control") is True),
        "state_reason": str(payload.get("state_reason") or ""),
        "reason": str(decision.get("reason") or ""),
        "relation_to_current_work": str(decision.get("relation_to_current_work") or ""),
        "boundary_code": "runtime_state_observation_only",
        "authority": "harness.runtime.current_work_boundary_receipt_projection",
    }


def _continuation_record_model_visible_payload(record: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(record or {})
    if not payload:
        return {}
    return _drop_empty_payload(
        {
            "continuation_id": str(payload.get("continuation_id") or ""),
            "task_run_id": str(payload.get("task_run_id") or ""),
            "state": str(payload.get("state") or ""),
            "resume_allowed": bool(payload.get("resume_allowed") is True),
            "resume_strategy": str(payload.get("resume_strategy") or ""),
            "recovery_cause": str(payload.get("recovery_cause") or ""),
            "task_status": str(payload.get("task_status") or ""),
            "user_visible_goal": str(payload.get("user_visible_goal") or ""),
            "latest_progress": str(payload.get("latest_progress") or ""),
            "last_completed_step": str(payload.get("last_completed_step") or ""),
            "next_recommended_step": str(payload.get("next_recommended_step") or ""),
            "model_visible_summary": str(payload.get("model_visible_summary") or ""),
            "read_only_context": True,
            "boundary_code": "recoverable_task_record_observation_only",
            "authority": "harness.runtime.continuation_record_projection",
        }
    )


def _interrupted_turn_work_model_visible_payload(
    record: dict[str, Any] | None,
    *,
    current_user_message: str = "",
) -> dict[str, Any]:
    payload = dict(record or {})
    if not payload:
        return {}
    if str(payload.get("authority") or "") != "harness.continuation.interrupted_turn_record":
        return {}
    if str(payload.get("state") or "") != "interrupted_continuation_context":
        return {}
    visible_prefix = str(payload.get("visible_assistant_prefix") or "")
    agent_contract_feedback = _agent_contract_feedback_model_visible_payload(
        payload.get("agent_contract_feedback")
    )
    visible_prefix_payload = _drop_empty_payload(
        {
            "content": visible_prefix,
            "content_sha256": str(payload.get("visible_assistant_prefix_sha256") or ""),
            "content_utf8_bytes": _safe_int(payload.get("visible_assistant_prefix_utf8_bytes")),
            "truncated_from_start": bool(payload.get("visible_assistant_prefix_truncated") is True),
            "continuation_rule": (
                "Do not repeat this already visible assistant prefix. Continue from the next useful token, "
                "and only restate context if the user explicitly asks for a recap."
            )
            if visible_prefix
            else "",
        }
    )
    return _drop_empty_payload(
        {
            "continuation_id": str(payload.get("continuation_id") or ""),
            "turn_run_id": str(payload.get("turn_run_id") or ""),
            "turn_id": str(payload.get("turn_id") or ""),
            "state": "interrupted_continuation_context",
            "continuation_allowed": True,
            "resume_allowed": False,
            "resume_strategy": str(payload.get("resume_strategy") or "continue_next_single_agent_turn"),
            "interruption_kind": str(payload.get("interruption_kind") or ""),
            "terminal_status": str(payload.get("terminal_status") or ""),
            "terminal_reason": str(payload.get("terminal_reason") or ""),
            "latest_progress": str(payload.get("latest_progress") or ""),
            "latest_step": str(payload.get("latest_step") or ""),
            "next_recommended_step": str(payload.get("next_recommended_step") or ""),
            "model_visible_summary": str(payload.get("model_visible_summary") or ""),
            "agent_contract_feedback": agent_contract_feedback,
            "current_user_instruction": _compact_text(current_user_message, limit=4000),
            "visible_assistant_prefix": visible_prefix_payload,
            "evidence_continuity": {
                "current_packet_exact_evidence_ref": "Task current exact read evidence",
                "reuse_rule": (
                    "Treat current packet read_evidence_injection entries as inherited same-session evidence. "
                    "Reuse visible exact evidence when it is present and not stale; re-read only when missing, stale, changed, or too coarse for the requested judgment."
                ),
            },
            "followup_contract": [
                "Treat the current user request as a continuation of the interrupted ordinary conversation turn.",
                "Continue from latest_progress, exact read evidence, and visible_assistant_prefix instead of starting a new unrelated answer.",
                "If visible_assistant_prefix.content is present, do not repeat that prefix; append the missing continuation.",
            ],
            "allowed_followup_posture": "ordinary_turn_continuation",
            "forbidden_action": "resume_recoverable_work",
            "read_only_context": False,
            "boundary_code": "interrupted_single_agent_turn_continuation_context",
            "authority": "harness.runtime.interrupted_turn_work_projection",
        }
    )


def _agent_contract_feedback_model_visible_payload(value: Any) -> dict[str, Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    if not payload:
        return {}
    protocol = dict(payload.get("required_action_protocol") or {})
    failure = dict(payload.get("contract_failure") or {})
    structured_signal = dict(payload.get("structured_signal") or {})
    specific_feedback = [
        _drop_empty_payload(
            {
                "category": str(item.get("category") or ""),
                "code": str(item.get("code") or ""),
                "reason": str(item.get("reason") or ""),
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
            "signal_kind": str(payload.get("signal_kind") or ""),
            "lifecycle": str(payload.get("lifecycle") or ""),
            "contract_feedback_state": str(payload.get("contract_feedback_state") or ""),
            "phase": str(payload.get("phase") or ""),
            "reason": str(payload.get("reason") or ""),
            "triggering_signal_kind": str(payload.get("triggering_signal_kind") or ""),
            "visible_assistant_message_allowed": payload.get("visible_assistant_message_allowed"),
            "tool_calls_allowed_after_signal": payload.get("tool_calls_allowed_after_signal"),
            "agent_closeout_required": payload.get("agent_closeout_required"),
            "agent_feedback": _compact_text(payload.get("agent_feedback"), limit=3000),
            "required_action_protocol": _drop_empty_payload(
                {
                    "authority": str(protocol.get("authority") or ""),
                    "allowed_action_types": [
                        str(item)
                        for item in list(protocol.get("allowed_action_types") or [])
                        if str(item or "").strip()
                    ],
                    "tool_call_allowed": protocol.get("tool_call_allowed"),
                    "structured_action_required": protocol.get("structured_action_required"),
                    "text_transport_accepts_single_unambiguous_json_action": protocol.get("text_transport_accepts_single_unambiguous_json_action"),
                    "visible_user_body_allowed_only_from_agent_action": protocol.get("visible_user_body_allowed_only_from_agent_action"),
                }
            ),
            "contract_failure": _drop_empty_payload(
                {
                    "kind": str(failure.get("kind") or ""),
                    "closeout_attempts": failure.get("closeout_attempts"),
                    "phase": str(failure.get("phase") or ""),
                    "reason": str(failure.get("reason") or ""),
                    "facts": dict(failure.get("facts") or {}),
                    "specific_feedback": specific_feedback,
                }
            ),
            "observed_facts": dict(payload.get("observed_facts") or {}),
            "structured_signal": _drop_empty_payload(
                {
                    "code": str(structured_signal.get("code") or ""),
                    "message": _compact_text(structured_signal.get("message"), limit=3000),
                    "retryable": structured_signal.get("retryable"),
                }
            ),
            "authority": "harness.runtime.interrupted_turn_contract_feedback_projection",
        }
    )


def _recovery_boundary_receipt_model_visible_payload(receipt: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(receipt or {})
    if not payload:
        return {}
    operations = recovery_operation_availability_from_receipt(payload)
    return _drop_empty_payload(
        {
            "receipt_id": str(payload.get("receipt_id") or ""),
            "boundary_decision": str(payload.get("boundary_decision") or ""),
            "continuation_ref": str(payload.get("continuation_ref") or ""),
            "task_run_ref": str(payload.get("task_run_ref") or ""),
            "operation_availability": operations,
            "resume_execution_route": str(payload.get("resume_execution_route") or ""),
            "read_only_context": not bool(operations.get("resume_recoverable_work") is True),
            "state_reason": str(payload.get("state_reason") or ""),
            "boundary_code": "recovery_boundary_receipt",
            "authority": "harness.runtime.recovery_boundary_receipt_projection",
        }
    )


def _recovery_packet_model_visible_payload(packet: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(packet or {})
    if not payload:
        return {}
    return _drop_empty_payload(
        {
            "packet_id": str(payload.get("packet_id") or ""),
            "continuation_id": str(payload.get("continuation_id") or ""),
            "task_run_id": str(payload.get("task_run_id") or ""),
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
            "authority": "harness.runtime.recovery_packet_projection",
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
                    "authority": str(payload.get("authority") or ""),
                }
            )
        )
    if not observations:
        return {}
    return {
        "observations": observations,
        "boundary_code": "agent_addressed_runtime_observations",
        "authority": "harness.runtime.runtime_observations_projection",
    }


def _single_agent_turn_output_contract(
    *,
    allowed_actions: tuple[str, ...],
    control_capabilities: dict[str, Any],
    planning_protocol: dict[str, Any] | None = None,
) -> dict[str, Any]:
    json_action_enabled = bool(control_capabilities.get("supports_json_action_protocol") is True)
    json_action_required = bool(control_capabilities.get("requires_json_action_protocol") is True)
    forbidden: list[str] = ["delegate_subagent"]
    if not json_action_enabled:
        forbidden.append("json_action_protocol")
    if "tool_call" not in allowed_actions:
        forbidden.append("general_tool_call")
    if "request_task_run" not in allowed_actions:
        forbidden.append("task_run_request")
    if "active_work_control" not in allowed_actions:
        forbidden.append("active_work_control")
    action_selection_rules = [
        "默认优先在当前 turn 内完成用户请求；复杂、跨文件或需要审查不自动等于 Task。",
        "只有当当前 turn 的自然边界不足以承载目标、计划、状态、恢复、验收、审计、用户可追踪阶段反馈或资源隔离时，才升级到 request_task_run。",
        "先判断目标是否需要持久工作生命周期：跨 turn 状态记录、暂停/恢复/停止/replan、明确完成证据、长期执行、工具/上下文预算恢复、独立验收或资源隔离。",
        "普通 tool_call 是合法路径，只要当前 turn 能保住目标、证据、反馈和收口；审查、评估、排查或多文件链路检查也可以在 turn 内完成。",
        "当工作范围、状态、验收或恢复需求越过 turn 边界时，先确认足以形成 task_contract_seed 的目标、范围、计划和验收标准，再申请 Task。",
    ]
    if "request_task_run" in allowed_actions:
        action_selection_rules.extend(
            [
                "如果需要 Task 但目标、范围、计划或验收标准不足以形成 task_contract_seed，必须选择 ask_user 补齐关键缺口。",
                "不要把 Task 当作普通工具调用；Task 是持续工作生命周期容器，只在 turn 边界不足时申请。",
                "如果当前 turn 可以通过有限工具调用完成、验证并收口，应继续使用 respond 或普通 tool_call。",
            ]
        )
    else:
        action_selection_rules.append(
            "如果当前工作确实需要持续 Task 但本轮没有挂载 request_task_run，必须用可用动作公开说明持续任务生命周期未挂载或补齐缺口；不能假装已经进入持续任务。"
        )
    return {
        "format": "assistant_message_or_action",
        "allowed_actions": list(allowed_actions),
        "forbidden": list(dict.fromkeys(forbidden)),
        "action_selection_rules": action_selection_rules,
        "action_protocol": {
            "single_control_action_per_turn": True,
            "json_action": {
                "enabled": json_action_enabled,
                "required": json_action_required,
                "required_for": "explicit_control_phase_only" if json_action_required else "control_or_task_action_only",
                "authority": "harness.loop.model_action_request",
            },
            "assistant_messages": {
                "enabled": bool(control_capabilities.get("may_emit_assistant_message") is not False),
                "transport": "assistant_message",
                "terminal_when_no_action": True,
                "raw_text_is_not_a_control_action": True,
            },
            "ordinary_tool_calls": {
                "enabled": "tool_call" in allowed_actions,
                "transport": "provider_native_tool_call_or_json_tool_call",
                "native_tool_transport_enabled": "tool_call" in allowed_actions,
                "multi_tool_calls_allowed": True,
                "runtime_execution_policy": "tool_batch_plan_scheduled_by_safety_and_resource_locks",
                "boundary": "runtime_visible_tools_only",
                "denied_or_failed_tool_calls_return_observations": True,
            },
            "control_actions": {
                "enabled": json_action_enabled,
                "transport": "json_action",
                "allowed_action_types": [
                    item
                    for item in ("respond", "ask_user", "block", "request_task_run", "active_work_control")
                    if item in allowed_actions
                ],
                "parallel_allowed": False,
                "native_tool_transport_enabled": False,
            },
            "native_tool_calls": {
                "enabled": "tool_call" in allowed_actions,
                "provider_multi_tool_calls_allowed": "tool_call" in allowed_actions,
                "runtime_execution_policy": "tool_batch_plan_scheduled_by_safety_and_resource_locks",
                "control_actions_exposed_as_native_tools": False,
                "visible_tool_boundary": "ordinary tool calls use the RuntimeToolPlan model-visible tool surface for this invocation",
            },
            "transport_decision_table": {
                "control_actions": {
                    "transport": "json_action",
                    "native_tool_transport_enabled": False,
                    "allowed_action_types": [
                        item
                        for item in (
                            "respond",
                            "ask_user",
                            "block",
                            "request_task_run",
                            "active_work_control",
                            "resume_recoverable_work",
                        )
                        if item in allowed_actions
                    ],
                },
                "ordinary_tool_calls": {
                    "transport": "provider_native_tool_call_or_json_tool_call",
                    "native_tool_transport_enabled": "tool_call" in allowed_actions,
                    "json_tool_call_enabled": json_action_enabled and "tool_call" in allowed_actions,
                    "multi_tool_calls_allowed": "tool_call" in allowed_actions,
                },
                "assistant_body": {
                    "enabled_when": "model_has_no_tool_or_control_action_and_is_answering_user",
                    "disabled_reason_when_json_required": "explicit_control_phase_requires_structured_control_decision",
                    "raw_text_is_not_a_control_action": True,
                },
            },
            "public_feedback_contract": {
                "feedback_must_be_model_authored": True,
                "system_must_not_synthesize_user_semantic_text": True,
                "json_action_feedback_fields": [
                    "public_progress_note",
                    "public_action_state.current_judgment",
                    "final_answer",
                    "user_question",
                    "blocking_reason",
                ],
                "tool_events_are_not_user_responses": True,
            },
            "native_tool_feedback_contract": {
                "assistant_content_preamble_is_public_feedback": True,
                "projection_target": "assistant_public_feedback",
                "missing_preamble_policy": "record_contract_gap_without_synthesizing_body",
                "low_level_tool_calls_may_omit_feedback": True,
                "stage_change_or_failure_should_emit_feedback": True,
            },
        },
        "planning_protocol": dict(planning_protocol or {}),
        "native_actions": {
            "tool_call": {
                "enabled": "tool_call" in allowed_actions,
                "boundary": "runtime_visible_tools_only",
                "multi_tool_calls_allowed": True,
                "runtime_execution_policy": "tool_batch_plan_scheduled_by_safety_and_resource_locks",
                "denied_or_failed_calls_return_observations": True,
            },
        },
        "control_actions": {
            "request_task_run": {
                "enabled": "request_task_run" in allowed_actions,
                "required_fields": ["user_visible_goal", "task_run_goal", "completion_criteria"],
                "operation_boundary": "request_task_run is available only when the current action contract exposes a new task lifecycle. It does not control, resume, pause, replace, or mutate active_work_context.",
            },
            "resume_recoverable_work": {
                "enabled": "resume_recoverable_work" in allowed_actions,
                "operation_availability_gate": (
                    "Use resume_recoverable_work only when Single agent turn dynamic runtime.recoverable_work.resume_allowed "
                    "is true and the latest user message asks to resume that recoverable task. The action must include "
                    "recovery_resume.task_run_id and recovery_resume.continuation_id from recoverable_work. If a "
                    "recovery_boundary_receipt is present, its operation_availability.resume_recoverable_work must be true. "
                    "Do not use this action for interrupted_turn_work, recent_work_outcome, terminal_read_only records, "
                    "or ordinary current-work control."
                ),
                "required_fields": ["recovery_resume.task_run_id", "recovery_resume.continuation_id"],
                "runtime_revalidation": "harness.continuation.recovery_boundary revalidates the handles before scheduling execution.",
            },
            "active_work_control": {
                "enabled": "active_work_control" in allowed_actions,
                "operation_availability_gate": (
                    "Before choosing active_work_control, check "
                    "Single agent turn dynamic runtime.current_work_boundary_receipt.operation_availability.active_work_control. "
                    "Use active_work_control only when that value is true; if it is false or missing, treat active_work_context "
                    "as read-only state and choose respond, ask_user, block, request_task_run, or another legal action."
                ),
                "required_fields": ["action", "relation_to_current_work"],
                "payload_schema": {
                    "action": "one of allowed_controls; use this exact field name for the control decision",
                    "response": "本次控制动作的用户可见反馈意图；它会和执行结果组成控制回执，不是一条脱离控制动作的最终正文",
                    "appended_instruction": "required when action is append_instruction_to_active_work unless the latest user message itself is the instruction",
                    "relation_to_current_work": "current_work when the latest user message clearly points at the active work",
                    "continuation_strategy": "same_run_resume, already_running, defer, or none",
                    "turn_response_policy": "answer_only, answer_then_active_work, active_work_only, or no_user_reply",
                    "user_turn_kind": "question, complaint, command, mixed, or statement",
                    "answer_obligation": "direct_answer_required, acknowledgement_only, or none",
                    "evidence": "brief visible reason showing why the latest user message controls the current work",
                },
                "allowed_controls": [
                    "continue_active_work",
                    "pause_active_work",
                    "stop_active_work",
                    "append_instruction_to_active_work",
                    "answer_about_active_work",
                    "answer_then_continue_active_work",
                ],
            },
        },
        "capability_source": dict(control_capabilities or {}),
    }


def _active_work_model_visible_payload(
    active_work_context: dict[str, Any] | None,
    *,
    controls_enabled: bool = False,
) -> dict[str, Any]:
    context = dict(active_work_context or {})
    if not context:
        return {}
    controls = [
        "continue_active_work",
        "pause_active_work",
        "stop_active_work",
        "append_instruction_to_active_work",
        "answer_about_active_work",
        "answer_then_continue_active_work",
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
            "boundary_code": "active_turn_bound_work_fact",
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
            "session_id": str(payload.get("session_id") or ""),
            "turn_id": str(payload.get("turn_id") or ""),
            "expected_active_turn_id": str(payload.get("expected_active_turn_id") or ""),
            "active_turn_input_policy": str(payload.get("active_turn_input_policy") or ""),
            "expected_task_run_id": str(payload.get("expected_task_run_id") or ""),
            "expected_continuation_id": str(payload.get("expected_continuation_id") or ""),
            "recovery_input_policy": str(payload.get("recovery_input_policy") or ""),
            "active_turn_present": bool(active_turn),
            "active_turn_id": str(active_turn.get("turn_id") or ""),
            "active_turn_state": str(active_turn.get("state") or ""),
            "active_turn_bound_task_run_id": str(active_turn.get("bound_task_run_id") or ""),
            "active_work_candidate_present": bool(payload.get("active_work_candidate")),
            "recoverable_work_candidate_present": bool(payload.get("recoverable_work_candidate")),
            "recent_work_outcome_candidate_present": bool(payload.get("recent_work_outcome_candidate")),
            "boundary_code": "observable_request_facts_only",
            "authority": "harness.runtime.turn_input_facts.model_projection",
        }
    )


def _split_volatile_request_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    source = dict(payload or {})
    history_payload = dict(source.get("history") or {}) if isinstance(source.get("history"), dict) else {}
    current_request = dict(source)
    current_request.pop("history", None)
    session_history = dict(history_payload)
    return _drop_empty_payload(session_history), _drop_empty_payload(current_request)


def _extract_editor_context_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    current = dict(payload or {})
    editor_payload = _drop_empty_payload(
        {
            "editor_context_index": current.pop("editor_context_index", None),
            "current_editor_evidence_delta": current.pop("current_editor_evidence_delta", None),
        }
    )
    return editor_payload, _drop_empty_payload(current)


def _extract_attachment_context_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    current = dict(payload or {})
    attachment_payload = _drop_empty_payload(
        {
            "attachment_context_index": current.pop("attachment_context_index", None),
        }
    )
    return attachment_payload, _drop_empty_payload(current)


def _extract_task_plan_context_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    current = dict(payload or {})
    task_plan_payload = _drop_empty_payload(
        {
            "task_plan_context": current.pop("task_plan_context", None),
        }
    )
    return task_plan_payload, _drop_empty_payload(current)


def _extract_evidence_index_cursor_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    current = dict(payload or {})
    evidence_payload = _drop_empty_payload(
        {
            "evidence_index_cursor": current.pop("evidence_index_cursor", None),
        }
    )
    return evidence_payload, _drop_empty_payload(current)


def _attachment_context_message_specs(
    payload: dict[str, Any] | None,
    *,
    title_prefix: str,
    source_ref_prefix: str,
    dynamic_context: DynamicContextProjection,
) -> list[dict[str, Any]]:
    attachment_context_index = dict(payload or {}).get("attachment_context_index")
    if not attachment_context_index:
        return []
    return [
        _runtime_payload_spec(
            role="system",
            title=f"{title_prefix} attachment context index",
            payload={"attachment_context_index": attachment_context_index},
            kind="attachment_context_index",
            source_ref=f"{source_ref_prefix}:attachment_context_index",
            cache_scope="task",
            cache_role="session_stable",
            compression_role="ref_only",
            metadata={
                **_dynamic_context_segment_metadata(dynamic_context, source="attachment_context_index"),
                "authority_class": "attachment_context_index",
                "content_source": "harness.runtime.dynamic_context.attachment_context_index",
                "runtime_fragment_role": "attachment_context_index",
                "cache_impact": "task_prefix_attachment_index_snapshot",
            },
        )
    ]


def _evidence_index_cursor_message_specs(
    payload: dict[str, Any] | None,
    *,
    title_prefix: str,
    source_ref_prefix: str,
    dynamic_context: DynamicContextProjection,
) -> list[dict[str, Any]]:
    evidence_index_cursor = dict(payload or {}).get("evidence_index_cursor")
    if not evidence_index_cursor:
        return []
    return [
        _runtime_payload_spec(
            role="system",
            title=f"{title_prefix} evidence index cursor",
            payload={"evidence_index_cursor": evidence_index_cursor},
            kind="evidence_index_cursor",
            source_ref=f"{source_ref_prefix}:evidence_index_cursor",
            cache_scope="task",
            cache_role="session_stable",
            compression_role="ref_only",
            metadata={
                **_dynamic_context_segment_metadata(dynamic_context, source="evidence_index_cursor"),
                "authority_class": "evidence_index_cursor",
                "content_source": "harness.runtime.dynamic_context.evidence_index_cursor",
                "runtime_fragment_role": "evidence_index_cursor",
                "cache_impact": "task_prefix_evidence_cursor_snapshot",
            },
        )
    ]


def _task_plan_context_message_specs(
    payload: dict[str, Any] | None,
    *,
    title_prefix: str,
    source_ref_prefix: str,
    dynamic_context: DynamicContextProjection,
) -> list[dict[str, Any]]:
    task_plan_context = dict(payload or {}).get("task_plan_context")
    if not task_plan_context:
        return []
    return [
        _runtime_payload_spec(
            role="system",
            title=f"{title_prefix} task plan context",
            payload={"task_plan_context": task_plan_context},
            kind="task_plan_context",
            source_ref=f"{source_ref_prefix}:task_plan_context",
            cache_scope="task",
            cache_role="session_stable",
            compression_role="ref_only",
            metadata={
                **_dynamic_context_segment_metadata(dynamic_context, source="task_plan_context"),
                "authority_class": "task_plan_context",
                "content_source": "harness.runtime.dynamic_context.task_plan_context",
                "runtime_fragment_role": "task_plan_context",
                "cache_impact": "task_prefix_plan_context_snapshot",
            },
        )
    ]


def _editor_context_message_specs(
    payload: dict[str, Any] | None,
    *,
    title_prefix: str,
    source_ref_prefix: str,
    dynamic_context: DynamicContextProjection,
) -> list[dict[str, Any]]:
    editor_payload = dict(payload or {})
    specs: list[dict[str, Any]] = []
    editor_context_index = editor_payload.get("editor_context_index")
    if editor_context_index:
        specs.append(
            _runtime_payload_spec(
                role="system",
                title=f"{title_prefix} editor context index",
                payload={"editor_context_index": editor_context_index},
                kind="editor_context_index",
                source_ref=f"{source_ref_prefix}:editor_context_index",
                cache_scope="task",
                cache_role="session_stable",
                compression_role="ref_only",
                metadata={
                    **_dynamic_context_segment_metadata(dynamic_context, source="editor_context_index"),
                    "authority_class": "editor_context_index",
                    "content_source": "harness.runtime.dynamic_context.editor_context_index",
                    "runtime_fragment_role": "editor_context_index",
                    "cache_impact": "task_prefix_editor_context_index_snapshot",
                },
            )
        )
    editor_evidence_delta = editor_payload.get("current_editor_evidence_delta")
    if editor_evidence_delta:
        specs.append(
            _runtime_payload_spec(
                role="system",
                title=f"{title_prefix} current editor evidence delta",
                payload={"current_editor_evidence_delta": editor_evidence_delta},
                kind="current_editor_evidence_delta",
                source_ref=f"{source_ref_prefix}:current_editor_evidence_delta",
                cache_scope="none",
                cache_role="volatile",
                compression_role="preserve",
                metadata={
                    **_dynamic_context_segment_metadata(dynamic_context, source="editor_exact_evidence_delta"),
                    "authority_class": "editor_evidence_delta",
                    "content_source": "harness.runtime.dynamic_context.current_editor_evidence_delta",
                    "runtime_fragment_role": "current_editor_evidence_delta",
                },
            )
        )
    return specs


def _session_history_message_specs(
    payload: dict[str, Any] | None,
    *,
    title: str,
    source_ref: str,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    clean_payload = _drop_empty_payload(dict(payload or {}))
    if not clean_payload:
        return []
    return [
        _runtime_payload_spec(
            role="system",
            title=title,
            payload=clean_payload,
            kind="session_history",
            source_ref=source_ref,
            cache_scope="task",
            cache_role="session_stable",
            compression_role="summarize",
            metadata={
                **dict(metadata or {}),
                "authority_class": "natural_history",
                "cache_impact": "task_prefix_history_snapshot",
                "stability_rule": "history already selected for this turn is preserved by hash; new user input is appended separately",
            },
        )
    ]


def _task_state_replay_message_specs(entries: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(tuple(entries or ()), start=1):
        entry = _drop_empty_payload(dict(raw_entry or {}))
        if not entry:
            continue
        entry_ref = _task_state_replay_entry_ref(entry, fallback_index=index)
        specs.append(
            _runtime_payload_spec(
                role="system",
                title=f"Task execution replayed state evidence {entry_ref}",
                payload={"task_state_replay_entry": entry},
                kind="task_state_replay_entry",
                source_ref=f"task_state_replay:{entry_ref}",
                cache_scope="task",
                cache_role="session_stable",
                compression_role="preserve",
                metadata={
                    "authority_class": "runtime_state",
                    "cache_impact": "append_only_task_prefix",
                    "stability_rule": "replay entries are append-only historical evidence; current invocation deltas remain in volatile task state",
                    "dynamic_context_report_ref": "task_state_replay_entries",
                    "projection_strategy": "bounded_task_state_replay_entry",
                    "task_state_replay_entry_index": index,
                    "task_state_replay_entry_ref": entry_ref,
                    "content_source": "runtime.dynamic_context.task_state_replay_entry",
                    "runtime_fragment_role": "append_only_task_state_evidence",
                },
            )
        )
    return specs


def _task_state_replay_entry_ref(entry: dict[str, Any], *, fallback_index: int) -> str:
    explicit_ref = str(entry.get("observation_ref") or entry.get("entry_ref") or "").strip()
    if explicit_ref:
        return explicit_ref
    digest = hashlib.sha256(
        json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8", errors="ignore")
    ).hexdigest()[:12]
    return f"entry:{digest or fallback_index}"


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
        for item in list(payload.get("api_transcript") or payload.get("provider_protocol_history") or [])
        if isinstance(item, dict)
    ]
    boundary_filtered_candidates = _provider_protocol_after_compaction_boundary(
        transcript_candidates,
        boundary_created_at=compaction_boundary_created_at,
    )
    protocol_sanitizer = sanitize_messages_for_prompt(
        boundary_filtered_candidates,
        turn_id=str(payload.get("turn_id") or ""),
        source=source_ref,
    )
    raw_transcript = [dict(item) for item in protocol_sanitizer.messages]
    protocol_transcript = _provider_protocol_hot_messages(raw_transcript)
    if not protocol_transcript:
        return []
    transcript, protocol_projection = _project_provider_protocol_replay(
        protocol_transcript,
        projection_policy=projection_policy,
        storage_root=storage_root,
        storage_run_id=storage_run_id,
    )
    protocol_truncated_count = max(0, len(protocol_transcript) - len(transcript))
    protocol_projection = {
        **dict(protocol_projection or {}),
        "raw_transcript_message_count": len(raw_transcript),
        "raw_transcript_input_message_count": len(transcript_candidates),
        "compaction_boundary_created_at": compaction_boundary_created_at,
        "compaction_boundary_omitted_message_count": max(0, len(transcript_candidates) - len(boundary_filtered_candidates)),
        "hot_protocol_message_count": len(protocol_transcript),
        "non_protocol_message_count": max(0, len(raw_transcript) - len(protocol_transcript)),
    }
    result: list[dict[str, Any]] = []
    for index, message in enumerate([item for item in transcript if item is not None], start=1):
        result.append(
            {
                "role": str(message.get("role") or "user"),
                "content": str(message.get("content") or ""),
                "kind": "provider_protocol_history",
                "source_ref": f"{source_ref}:{index}",
                "cache_scope": "none",
                "cache_role": "never_cache",
                "prefix_tier": "none",
                "compression_role": "preserve",
                "metadata": {
                    "protocol_history_index": index,
                    "provider_protocol_replay": True,
                    "protocol_truncated_count": protocol_truncated_count,
                    "protocol_sanitizer": dict(protocol_sanitizer.diagnostics),
                    "protocol_projection": dict(protocol_projection),
                    "reasoning_content_present": bool(message.get("reasoning_content")),
                    "tool_calls_present": bool(message.get("tool_calls")),
                    "exact_content_required_before_final": _provider_protocol_requires_rehydration(message),
                    "content_source": "runtime.provider_protocol_replay",
                },
                "model_message": message,
            }
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
    return [message for message in list(transcript or []) if _is_provider_protocol_hot_message(message)]


def _is_provider_protocol_hot_message(message: dict[str, Any]) -> bool:
    role = str(message.get("role") or "").strip()
    if role == "tool":
        return True
    if _assistant_tool_call_ids(message):
        return True
    if str(message.get("reasoning_content") or "").strip():
        return True
    return False


def _select_provider_protocol_replay(
    transcript: list[dict[str, Any]],
    *,
    max_messages: int = _PROVIDER_PROTOCOL_DEFAULT_MESSAGE_LIMIT,
) -> list[dict[str, Any]]:
    if len(transcript) <= max_messages:
        return list(transcript)
    start = max(0, len(transcript) - max_messages)
    start = _provider_protocol_start_with_tool_pairs(transcript, start)
    return list(transcript[start:])


def _project_provider_protocol_replay(
    transcript: list[dict[str, Any]],
    *,
    projection_policy: dict[str, Any] | None,
    storage_root: Path | None,
    storage_run_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    policy = dict(projection_policy or {})
    message_limit = _provider_protocol_message_limit(policy)
    char_budget = _provider_protocol_char_budget(policy, message_limit=message_limit)
    selected = _select_provider_protocol_replay(transcript, max_messages=message_limit)
    projected, projection = _project_provider_protocol_messages(
        selected,
        projection_policy=policy,
        storage_root=storage_root,
        storage_run_id=storage_run_id,
    )
    budgeted = _select_provider_protocol_replay_by_char_budget(projected, max_chars=char_budget)
    projection.update(
        {
            "authority": "harness.runtime.compiler.provider_protocol_projection",
            "input_message_count": len(transcript),
            "selected_message_limit": message_limit,
            "char_budget": char_budget,
            "selected_message_count": len(selected),
            "replayed_message_count": len(budgeted),
            "omitted_message_count": max(0, len(transcript) - len(budgeted)),
            "input_chars": _provider_protocol_messages_chars(transcript),
            "output_chars": _provider_protocol_messages_chars(budgeted),
        }
    )
    return budgeted, _drop_empty_payload(projection)


def _project_provider_protocol_messages(
    transcript: list[dict[str, Any]],
    *,
    projection_policy: dict[str, Any],
    storage_root: Path | None,
    storage_run_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tool_preview_chars = _provider_protocol_tool_preview_chars(projection_policy)
    message_chars = _provider_protocol_message_chars_limit(projection_policy)
    store = ToolResultStore(
        storage_root or Path.cwd(),
        run_id=storage_run_id or "session",
        namespace="runtime_context",
    )
    projected: list[dict[str, Any]] = []
    projected_tool_outputs = 0
    persisted_replacements = 0
    compacted_messages = 0
    storage_errors = 0
    tool_name_by_call_id = _provider_protocol_tool_call_names(transcript)
    for message in transcript:
        item = dict(message)
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role == "tool" and content:
            tool_name = _provider_protocol_tool_name(item, content=content) or tool_name_by_call_id.get(
                str(item.get("tool_call_id") or "").strip(),
                "",
            )
            if tool_name == "read_file":
                if len(content) > tool_preview_chars:
                    item["content"] = _provider_protocol_read_file_preview(content, preview_chars=tool_preview_chars)
                    projected_tool_outputs += 1
                    compacted_messages += 1
                projected.append(item)
                continue
            try:
                budgeted, replacements = store.apply_budget(
                    {"content": content},
                    field_limit_bytes=tool_preview_chars,
                    preview_size_bytes=tool_preview_chars,
                    payload_budget_bytes=max(tool_preview_chars * 2, tool_preview_chars + 1000),
                )
            except Exception:
                item["content"] = _provider_protocol_storage_unavailable_preview(
                    content,
                    preview_chars=tool_preview_chars,
                )
                storage_errors += 1
                compacted_messages += 1
            else:
                if replacements:
                    replacement_content = str(budgeted.get("content") or "")
                    item["content"] = _with_provider_protocol_rehydration_note(replacement_content)
                    projected_tool_outputs += 1
                    persisted_replacements += len(replacements)
                    compacted_messages += 1
        elif content and len(content) > message_chars:
            item["content"] = _provider_protocol_bounded_message_preview(content, limit=message_chars)
            compacted_messages += 1
        projected.append(item)
    return projected, _drop_empty_payload(
        {
            "tool_preview_chars": tool_preview_chars,
            "message_chars": message_chars,
            "projected_tool_output_count": projected_tool_outputs,
            "persisted_tool_replacement_count": persisted_replacements,
            "compacted_message_count": compacted_messages,
            "storage_error_count": storage_errors,
        }
    )


def _select_provider_protocol_replay_by_char_budget(
    transcript: list[dict[str, Any]],
    *,
    max_chars: int,
) -> list[dict[str, Any]]:
    if not transcript or _provider_protocol_messages_chars(transcript) <= max_chars:
        return list(transcript)
    total = 0
    start = len(transcript)
    for index in range(len(transcript) - 1, -1, -1):
        size = _provider_protocol_message_chars(transcript[index])
        if start < len(transcript) and total + size > max_chars:
            break
        start = index
        total += size
    if start >= len(transcript):
        start = max(0, len(transcript) - 1)
    start = _provider_protocol_start_with_tool_pairs(transcript, start)
    return list(transcript[start:])


def _provider_protocol_start_with_tool_pairs(transcript: list[dict[str, Any]], start: int) -> int:
    selected = transcript[start:]
    required_tool_call_ids = {
        str(message.get("tool_call_id") or "").strip()
        for message in selected
        if str(message.get("role") or "") == "tool" and str(message.get("tool_call_id") or "").strip()
    }
    if required_tool_call_ids:
        for index in range(start - 1, -1, -1):
            call_ids = _assistant_tool_call_ids(transcript[index])
            matched = call_ids.intersection(required_tool_call_ids)
            if matched:
                start = index
                required_tool_call_ids.difference_update(matched)
                if not required_tool_call_ids:
                    break
    return start


def _assistant_tool_call_ids(message: dict[str, Any]) -> set[str]:
    if str(message.get("role") or "") != "assistant":
        return set()
    tool_calls = list(message.get("tool_calls") or []) if isinstance(message.get("tool_calls"), list) else []
    return {str(call.get("id") or "").strip() for call in tool_calls if isinstance(call, dict) and str(call.get("id") or "").strip()}


def _provider_protocol_message_limit(policy: dict[str, Any]) -> int:
    explicit = policy.get("provider_protocol_message_limit")
    if explicit not in (None, ""):
        return _int_in_range(explicit, default=_PROVIDER_PROTOCOL_DEFAULT_MESSAGE_LIMIT, low=4, high=32)
    recent_limit = _safe_int(policy.get("recent_history_message_limit"))
    inferred = recent_limit // 12 if recent_limit else _PROVIDER_PROTOCOL_DEFAULT_MESSAGE_LIMIT
    return _int_in_range(inferred, default=_PROVIDER_PROTOCOL_DEFAULT_MESSAGE_LIMIT, low=6, high=16)


def _provider_protocol_char_budget(policy: dict[str, Any], *, message_limit: int) -> int:
    explicit = policy.get("provider_protocol_char_budget")
    if explicit not in (None, ""):
        return _int_in_range(explicit, default=_PROVIDER_PROTOCOL_DEFAULT_CHAR_BUDGET, low=4_000, high=48_000)
    inferred = max(4_000, int(message_limit or _PROVIDER_PROTOCOL_DEFAULT_MESSAGE_LIMIT) * 1_800)
    return _int_in_range(inferred, default=_PROVIDER_PROTOCOL_DEFAULT_CHAR_BUDGET, low=6_000, high=24_000)


def _provider_protocol_tool_preview_chars(policy: dict[str, Any]) -> int:
    explicit = policy.get("provider_protocol_tool_result_preview_chars")
    if explicit not in (None, ""):
        return _int_in_range(explicit, default=DEFAULT_PREVIEW_SIZE_BYTES, low=600, high=6_000)
    base = _safe_int(policy.get("tool_result_preview_chars")) or DEFAULT_PREVIEW_SIZE_BYTES
    return _int_in_range(min(base, 3_000), default=DEFAULT_PREVIEW_SIZE_BYTES, low=800, high=3_000)


def _provider_protocol_message_chars_limit(policy: dict[str, Any]) -> int:
    explicit = policy.get("provider_protocol_message_chars")
    if explicit not in (None, ""):
        return _int_in_range(explicit, default=_PROVIDER_PROTOCOL_DEFAULT_MESSAGE_CHARS, low=600, high=8_000)
    base = _safe_int(policy.get("history_message_chars")) or _PROVIDER_PROTOCOL_DEFAULT_MESSAGE_CHARS
    return _int_in_range(min(base, _PROVIDER_PROTOCOL_DEFAULT_MESSAGE_CHARS), default=_PROVIDER_PROTOCOL_DEFAULT_MESSAGE_CHARS, low=800, high=4_000)


def _provider_protocol_messages_chars(messages: list[dict[str, Any]]) -> int:
    return sum(_provider_protocol_message_chars(message) for message in messages)


def _provider_protocol_message_chars(message: dict[str, Any]) -> int:
    return len(json.dumps(_json_stable(message), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _with_provider_protocol_rehydration_note(content: str) -> str:
    text = str(content or "").strip()
    if not text or _PROVIDER_PROTOCOL_REHYDRATION_NOTE in text:
        return text
    return f"{text}\n{_PROVIDER_PROTOCOL_REHYDRATION_NOTE}"


def _provider_protocol_tool_name(message: dict[str, Any], *, content: str = "") -> str:
    for key in ("name", "tool_name", "function_name"):
        value = str(message.get(key) or "").strip()
        if value:
            return value.removeprefix("tool:").strip()
    parsed = _json_object(content)
    for key in ("tool_name", "name"):
        value = str(parsed.get(key) or "").strip()
        if value:
            return value.removeprefix("tool:").strip()
    envelope = dict(parsed.get("result_envelope") or {})
    value = str(envelope.get("tool_name") or "").strip()
    return value.removeprefix("tool:").strip()


def _provider_protocol_tool_call_names(transcript: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for message in list(transcript or []):
        if str(message.get("role") or "") != "assistant":
            continue
        for call in list(message.get("tool_calls") or []) if isinstance(message.get("tool_calls"), list) else []:
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or "").strip()
            name = str(call.get("name") or call.get("function_name") or "").removeprefix("tool:").strip()
            if call_id and name:
                names[call_id] = name
    return names


def _provider_protocol_read_file_preview(content: str, *, preview_chars: int) -> str:
    preview = _provider_protocol_bounded_message_preview(content, limit=preview_chars)
    return (
        preview.rstrip()
        + "\nProvider protocol replay preview only for read_file. Exact code evidence must come from "
        "visible read_file content, injected read observation artifacts, or a current read_file call."
    )


def _json_object(value: Any) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text or not text.startswith("{"):
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _provider_protocol_requires_rehydration(message: dict[str, Any]) -> bool:
    content = str(message.get("content") or "")
    if str(message.get("role") or "") != "tool":
        return False
    return "<persisted-output>" in content or "Provider protocol replay preview only for read_file" in content


def _provider_protocol_storage_unavailable_preview(content: str, *, preview_chars: int) -> str:
    preview = _compact_text(content, limit=max(120, int(preview_chars or DEFAULT_PREVIEW_SIZE_BYTES)))
    return (
        f"{preview}\n"
        "[Provider protocol replay omitted the rest of this tool output; persisted storage was unavailable.]"
    )


def _provider_protocol_bounded_message_preview(content: str, *, limit: int) -> str:
    preview = _compact_text(content, limit=max(120, int(limit or _PROVIDER_PROTOCOL_DEFAULT_MESSAGE_CHARS)))
    omitted = max(0, len(str(content or "")) - len(preview))
    return f"{preview}\n[Provider protocol replay omitted {omitted} char(s) from this older message.]"


def _int_in_range(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        parsed = default
    return max(int(low), min(int(high), parsed))


def _model_messages_and_segment_plan(
    *,
    packet_id: str,
    invocation_kind: str,
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    enforce_dynamic_context_reports: bool = False,
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
    slot_plan = build_runtime_prompt_slot_plan(
        packet_id=packet_id,
        invocation_kind=invocation_kind,
        message_specs=clean_specs,
    )
    load_plan = build_runtime_context_load_plan(slot_plan)
    if enforce_dynamic_context_reports:
        _validate_dynamic_context_metadata(clean_specs)
    model_messages = [dict(spec.get("model_message") or {}) for spec in clean_specs]
    segment_plan = build_prompt_segment_plan(
        packet_id=packet_id,
        invocation_kind=invocation_kind,
        message_specs=clean_specs,
        enforce_dynamic_context_reports=enforce_dynamic_context_reports,
    )
    return model_messages, segment_plan, tuple(clean_specs), source_manifest, slot_plan, load_plan


def _model_message_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    raw_message = spec.get("model_message") if isinstance(spec.get("model_message"), dict) else spec
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


def _validate_dynamic_context_metadata(specs: list[dict[str, Any]]) -> None:
    for spec in specs:
        cache_role = str(spec.get("cache_role") or "")
        kind = str(spec.get("kind") or "")
        if cache_role != "volatile" and not kind.startswith("dynamic"):
            continue
        metadata = dict(spec.get("metadata") or {})
        if metadata.get("dynamic_context_report_ref") or metadata.get("volatility_reason"):
            continue
        raise ValueError(f"dynamic/volatile segment requires dynamic context metadata: {kind}")


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


def _attach_task_contract_manifest(
    prompt_manifest: dict[str, Any],
    task_contract_manifest: TaskContractManifest,
) -> dict[str, Any]:
    payload = task_contract_manifest.to_dict()
    prompt_manifest["task_contract_manifest"] = payload
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


def _project_instruction_target_paths(*, contract: dict[str, Any], task_run: dict[str, Any]) -> tuple[str, ...]:
    paths: list[str] = []
    for payload in (dict(contract or {}), dict(task_run or {})):
        _collect_path_like_values(payload, paths)
    return tuple(dict.fromkeys(paths))


def _collect_path_like_values(value: Any, paths: list[str], *, key_hint: str = "") -> None:
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key or "").strip().lower()
            next_hint = key or key_hint
            if _is_path_like_key(key):
                _append_path_values(item, paths)
                continue
            if isinstance(item, (dict, list, tuple)):
                _collect_path_like_values(item, paths, key_hint=next_hint)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_path_like_values(item, paths, key_hint=key_hint)


def _is_path_like_key(key: str) -> bool:
    value = str(key or "").strip().lower()
    if value in {
        "path",
        "paths",
        "file",
        "files",
        "filepath",
        "file_path",
        "file_paths",
        "target_path",
        "target_paths",
        "target_file",
        "target_files",
        "changed_file",
        "changed_files",
        "required_read_files",
        "required_write_files",
        "allowed_write_paths",
        "artifact_path",
        "artifact_paths",
    }:
        return True
    return value.endswith("_path") or value.endswith("_paths") or value.endswith("_file") or value.endswith("_files")


def _append_path_values(value: Any, paths: list[str]) -> None:
    if isinstance(value, str):
        if _looks_like_project_path(value):
            paths.append(value)
        return
    if isinstance(value, dict):
        candidate = value.get("path") or value.get("file_path") or value.get("target_path")
        if isinstance(candidate, str) and _looks_like_project_path(candidate):
            paths.append(candidate)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _append_path_values(item, paths)


def _looks_like_project_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text or "://" in text:
        return False
    return any(separator in text for separator in ("/", "\\")) or "." in Path(text).name


def _user_steering_updates_payload(execution_state: dict[str, Any] | None) -> dict[str, Any]:
    state = dict(execution_state or {})
    projection = dict(state.get("system_projection") or {})
    pending_steers = [
        _user_steer_model_payload(item)
        for item in list(projection.get("pending_user_steers") or [])
        if isinstance(item, dict) and str(item.get("steer_id") or "").strip()
    ]
    if not pending_steers:
        return {}
    return {
        "authority": "harness.runtime.task_execution.user_steering_updates",
        "source": "active_task_steer_queue",
        "policy_ref": "lifecycle_stable.user_steer_contract_revision",
        "pending_user_steer_count": len(pending_steers),
        "pending_user_steers": pending_steers,
    }


def _user_steer_model_payload(value: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "steer_id": str(value.get("steer_id") or ""),
        "task_run_id": str(value.get("task_run_id") or ""),
        "submission_ref": str(value.get("submission_ref") or ""),
        "steer_kind": str(value.get("steer_kind") or "instruction"),
        "priority": str(value.get("priority") or "normal"),
        "consumption_state": str(value.get("consumption_state") or "pending"),
        "content": str(value.get("content") or ""),
        "created_at": value.get("created_at"),
        "editor_context": dict(value.get("editor_context") or {}) if isinstance(value.get("editor_context"), dict) else {},
    }
    return {key: item for key, item in payload.items() if item not in ("", {}, [], None)}


def _file_evidence_policy_stable_payload() -> dict[str, Any]:
    return {
        "file_evidence_policy": {
            "policy_id": "file_evidence_policy_stable.read_window_admission",
            "read_file_admission": {
                "covered_non_stale_window": (
                    "如果目标行范围已经被当前未过期 read_file 窗口覆盖，应复用该窗口或对应 observation_ref；"
                    "工具控制面会把重复 read_file 转成当前证据复用观察。"
                ),
                "rehydrate_omitted_window": (
                    "当已有窗口内容被省略且确实需要精确字节时，优先使用 rehydration_ref 或 reusable_result_ref 恢复；"
                    "只有 stale、changed、missing、hash 缺失或目标范围未覆盖时才需要新的 read_file。"
                ),
                "known_path_boundary": (
                    "已知 bound/editor 文件路径，以及 task_contract.environment_contract.working_scope 中表现为路径的 target_objects、"
                    "source_refs 或 workspace_refs，不需要通过 search_files 或 search_text 重新发现；"
                    "未知位置才使用 search_files、glob_paths 或 search_text。"
                ),
            },
            "dynamic_fact_refs": [
                "evidence_index_cursor",
                "bound_task_runtime_context.rehydration_refs",
            ],
            "enforcement": "runtime.tool_runtime.file_evidence_admission",
            "authority": "harness.runtime.file_evidence_policy_stable",
        }
    }


def _user_steering_source_ref(payload: dict[str, Any]) -> str:
    steer_ids = [
        str(item.get("steer_id") or "")
        for item in list(dict(payload or {}).get("pending_user_steers") or [])
        if isinstance(item, dict) and str(item.get("steer_id") or "")
    ]
    if not steer_ids:
        return "active_task_steer_queue"
    return "active_task_steer_queue:" + _short_hash(_stable_json_hash(steer_ids))


def _join_prompt_sections(*sections: str) -> str:
    return "\n".join(str(section or "").strip() for section in sections if str(section or "").strip()) + "\n"


def _merge_prompt_assemblies(
    *assemblies: PromptAssemblyResult,
    invocation_kind: str,
) -> PromptAssemblyResult:
    sections = []
    pack_refs: list[str] = []
    rejected_refs: list[dict[str, Any]] = []
    for assembly in assemblies:
        sections.extend(assembly.sections)
        pack_refs.extend(assembly.prompt_pack_refs)
        rejected_refs.extend(dict(item) for item in assembly.rejected_refs)
    sections = list(enforce_prompt_authority_order(tuple(sections)))
    rule_diagnostics = build_rule_diagnostics(tuple(sections), invocation_kind=invocation_kind)
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
        "lifecycle": 45,
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
        layer = "lifecycle" if category == "environment" and (subtype.startswith("lifecycle_") or ".lifecycle." in prompt_ref) else category
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
        "policy": "system>override>coordinator>agent>personality>runtime>environment>lifecycle>tool>skill>project>contract",
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


def _prompt_pack_refs_for_invocation(profile_payload: dict[str, Any], *, invocation_kind: str) -> tuple[str, ...]:
    by_invocation = dict(profile_payload.get("prompt_pack_refs_by_invocation") or {})
    refs = _string_tuple(by_invocation.get(invocation_kind))
    if refs:
        return refs
    return _string_tuple(profile_payload.get("prompt_pack_refs"))


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
    hidden_lifecycle_refs = list(payload.get("lifecycle_prompt_refs") or [])
    hidden_runtime_lifecycle_refs = list(payload.get("runtime_lifecycle_prompt_refs") or [])
    hidden_lifecycle_keys = list(payload.get("lifecycle_prompt_keys") or [])
    hidden_runtime_lifecycle_keys = list(payload.get("runtime_lifecycle_prompt_keys") or [])
    hidden_lifecycle_trigger_reasons = dict(payload.get("lifecycle_trigger_reasons") or {})
    hidden_runtime_lifecycle_trigger_reasons = dict(payload.get("runtime_lifecycle_trigger_reasons") or {})
    payload["environment_prompt_refs"] = []
    payload["base_prompt_refs"] = []
    payload["overlay_prompt_refs"] = []
    payload["lifecycle_prompt_refs"] = []
    payload["runtime_lifecycle_prompt_refs"] = []
    payload["lifecycle_prompt_keys"] = []
    payload["runtime_lifecycle_prompt_keys"] = []
    payload["lifecycle_trigger_reasons"] = {}
    payload["runtime_lifecycle_trigger_reasons"] = {}
    diagnostics = dict(payload.get("diagnostics") or {})
    diagnostics.update(
        {
            "environment_prompt_visibility": "hidden",
            "hidden_environment_prompt_refs": hidden_refs,
            "hidden_base_prompt_refs": hidden_base_refs,
            "hidden_overlay_prompt_refs": hidden_overlay_refs,
            "hidden_lifecycle_prompt_refs": hidden_lifecycle_refs,
            "hidden_runtime_lifecycle_prompt_refs": hidden_runtime_lifecycle_refs,
            "hidden_lifecycle_prompt_keys": hidden_lifecycle_keys,
            "hidden_runtime_lifecycle_prompt_keys": hidden_runtime_lifecycle_keys,
            "hidden_lifecycle_trigger_reasons": hidden_lifecycle_trigger_reasons,
            "hidden_runtime_lifecycle_trigger_reasons": hidden_runtime_lifecycle_trigger_reasons,
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


def _agent_prompt_refs_for_invocation(assembly_payload: dict[str, Any], *, invocation_kind: str) -> tuple[str, ...]:
    by_invocation = dict(assembly_payload.get("agent_prompt_refs_by_invocation") or {})
    refs = _string_tuple(by_invocation.get(invocation_kind))
    if refs:
        return refs
    return _string_tuple(assembly_payload.get("agent_prompt_refs"))


def _prompt_mount_plan_payload_from_runtime_assembly(assembly_payload: dict[str, Any]) -> dict[str, Any]:
    explicit_plan = dict(assembly_payload.get("prompt_mount_plan") or {})
    if explicit_plan:
        return explicit_plan
    environment_payload = dict(assembly_payload.get("task_environment") or {})
    environment_prompt_refs = _string_tuple(assembly_payload.get("environment_prompt_refs"))
    if not environment_prompt_refs:
        boundary = dict(environment_payload.get("environment_boundary") or {})
        environment_prompt_refs = _string_tuple(boundary.get("prompt_refs"))
    if not environment_prompt_refs:
        environment_prompt_refs = tuple(
            str(item.get("prompt_id") or "").strip()
            for item in list(environment_payload.get("environment_prompts") or [])
            if isinstance(item, dict) and str(item.get("prompt_id") or "").strip()
        )
    personality_prompt_refs = _string_tuple(assembly_payload.get("personality_prompt_refs"))
    selected_environment_id = str(
        environment_payload.get("environment_id")
        or environment_payload.get("task_environment_id")
        or GENERAL_ENVIRONMENT_ID
    ).strip()
    base_prompt_refs = environment_prompt_refs
    overlay_prompt_refs: tuple[str, ...] = ()
    profile_payload = dict(assembly_payload.get("profile") or {})
    prompt_policy = dict(profile_payload.get("prompt_policy") or assembly_payload.get("prompt_policy") or {})
    boundary = dict(environment_payload.get("environment_boundary") or {})
    return {
        "base_environment_id": selected_environment_id or GENERAL_ENVIRONMENT_ID,
        "selected_environment_id": selected_environment_id or GENERAL_ENVIRONMENT_ID,
        "personality_prompt_refs": list(personality_prompt_refs),
        "base_prompt_refs": list(base_prompt_refs),
        "overlay_prompt_refs": list(overlay_prompt_refs),
        "environment_prompt_refs": _dedupe_strings([*base_prompt_refs]),
        "lifecycle_prompt_defaults": _string_dict(boundary.get("lifecycle_prompt_defaults")),
        "lifecycle_prompt_overrides": dict(boundary.get("lifecycle_prompt_overrides") or {}),
        "tool_guidance_prompt_defaults": dict(prompt_policy.get("tool_guidance_prompt_defaults") or {}),
        "tool_guidance_prompt_overrides": dict(boundary.get("tool_guidance_prompt_overrides") or {}),
        "diagnostics": {
            "source": "runtime_assembly_environment_prompt_refs_without_mount_plan",
            "normalized_by": "harness.runtime.compiler",
            "environment_prompt_count": len(environment_prompt_refs),
            "overlay_mode": "selected_environment_only",
        },
    }


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
    return {
        "contract_id": str(contract_id or payload.get("contract_id") or "").strip(),
        "version": str(payload.get("version") or "v1"),
        "role_prompt": _first_runtime_text(payload.get("role_prompt")),
        "task_instruction": _first_runtime_text(payload.get("task_instruction")),
        "output_instruction": _first_runtime_text(payload.get("output_instruction")),
        "forbidden_behavior": _string_list(payload.get("forbidden_behavior")),
        "definition_of_done": _string_list(payload.get("definition_of_done")),
    }


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
                "edit_file",
                "write_file",
                "side_effect_terminal",
                "git_write",
                "deliverable_write",
                "claim_completed",
            ],
            "deviation_policy": "ask_user_or_block_before_changing_approved_plan",
            "authority": "harness.runtime.plan_mode_protocol",
        }
    )


def _agent_visible_runtime_projection(
    *,
    invocation_kind: str,
    allowed_action_types: tuple[str, ...],
    profile_payload: dict[str, Any],
    environment_payload: dict[str, Any],
    operation_authorization: dict[str, Any],
    available_tools: tuple[dict[str, Any], ...],
    permission_mode: str = "default",
    prompt_policy: dict[str, Any] | None = None,
    tool_plan: Any | None = None,
) -> dict[str, Any]:
    prompt_policy_payload = dict(prompt_policy or {})
    task_lifecycle = dict(profile_payload.get("task_lifecycle_policy") or {})
    planning = dict(profile_payload.get("planning_policy") or {})
    planning_protocol = _planning_protocol_payload(
        invocation_kind=invocation_kind,
        profile_payload=profile_payload,
        permission_mode=permission_mode,
    )
    self_review = dict(profile_payload.get("self_review_policy") or {})
    step_summary = dict(profile_payload.get("step_summary_policy") or {})
    permission = dict(profile_payload.get("permission_policy") or {})
    subagent = dict(profile_payload.get("subagent_policy") or {})
    storage = dict(environment_payload.get("storage_space") or {})
    environment_boundary = dict(environment_payload.get("environment_boundary") or {})
    artifact_scope = runtime_artifact_scope_from_environment(environment_payload)
    allowed_operations = [
        str(item)
        for item in list(operation_authorization.get("allowed_operations") or [])
        if str(item)
    ]
    tool_names = [
        str(item.get("tool_name") or item.get("name") or "")
        for item in available_tools
        if str(item.get("tool_name") or item.get("name") or "")
    ]
    task_scoped_tool_routes = _task_scoped_tool_routes_from_tool_plan(tool_plan)
    service_surface = _service_surface_payload(
        invocation_kind=invocation_kind,
        allowed_action_types=allowed_action_types,
        available_tools=available_tools,
        tool_plan=tool_plan,
    )
    visible_tool_name_set = {name for name in tool_names if name}
    subagent_lifecycle_enabled = bool(subagent.get("enabled") is True) and bool(
        visible_tool_name_set.intersection(
            {
                "spawn_subagent",
                "send_subagent_message",
                "wait_subagent",
                "list_subagents",
                "close_subagent",
            }
        )
    )
    task_run_allowed = "request_task_run" in allowed_action_types and task_lifecycle.get("request_task_run") is not False
    model_decision_contract = _model_decision_contract_payload(
        invocation_kind=invocation_kind,
        allowed_action_types=allowed_action_types,
        task_run_allowed=task_run_allowed,
    )
    execution_boundary = _execution_boundary_payload(
        profile_payload=profile_payload,
        operation_authorization=operation_authorization,
        permission_mode=permission_mode,
    )
    payload = {
        "authority": "harness.runtime.agent_visible_runtime_projection",
        "invocation_kind": str(invocation_kind or ""),
        "model_decision_contract": model_decision_contract,
        "service_surface": service_surface,
        "execution_boundary": execution_boundary,
        "allowed_action_types": list(allowed_action_types),
        "task_lifecycle": {
            "request_task_run_allowed": task_run_allowed,
            "requires_completion_evidence": bool(task_lifecycle.get("requires_completion_evidence") is True),
            "artifact_evidence_required": bool(task_lifecycle.get("artifact_evidence_required") is True),
        },
        "planning": {
            **planning_protocol,
            "specified_plan_allowed": bool(planning.get("specified_plan_allowed") is True),
            "todo_required_when_task_run": bool(planning.get("todo_required_when_task_run") is True),
        },
        "self_review": {
            "enabled": bool(self_review.get("enabled") is True),
            "before_final": str(self_review.get("before_final") or ""),
            "checkpoints": [str(item) for item in list(self_review.get("checkpoints") or []) if str(item)],
            "failure_recovery": str(self_review.get("failure_recovery") or ""),
        },
        "step_summary": {
            "enabled": bool(step_summary.get("enabled") is True),
            "detail": str(step_summary.get("detail") or ""),
        },
        "tool_boundary": {
            "visible_tool_count": len(tool_names),
            "visible_tool_names": tool_names,
            "task_scoped_tool_routes": task_scoped_tool_routes,
            "allowed_operation_count": len(allowed_operations),
            "tools_are_limited_to_visible_context": True,
            "subagent_lifecycle_enabled": subagent_lifecycle_enabled,
            "allowed_subagent_ids": list(
                normalize_agent_id_sequence(str(item) for item in list(subagent.get("allowed_subagent_ids") or []) if str(item))
            ),
        },
        "permission_boundary": {
            "permission_scope": str(permission.get("permission_scope") or permission.get("scope") or ""),
            "permission_mode": str(permission_mode or "default"),
        },
    }
    if _prompt_policy_visible(prompt_policy_payload, "runtime_environment_boundary_visibility", default=True):
        payload["environment_boundary"] = {
            "task_environment_id": str(environment_payload.get("environment_id") or ""),
            "artifact_root": str(artifact_scope.artifact_root or storage.get("artifact_root") or ""),
            "environment_storage_root": str(storage.get("environment_storage_root") or ""),
            "boundary_authority": str(environment_boundary.get("authority") or ""),
        }
    return payload


def _model_decision_contract_payload(
    *,
    invocation_kind: str,
    allowed_action_types: tuple[str, ...],
    task_run_allowed: bool,
) -> dict[str, Any]:
    semantic_actions = [str(item) for item in tuple(allowed_action_types or ()) if str(item)]
    control_actions = [
        item
        for item in ("ask_user", "block", "request_task_run", "active_work_control")
        if item in semantic_actions
    ]
    return {
        "authority": "harness.runtime.model_decision_contract",
        "prompt_authority": "developer_prompt_contract",
        "invocation_kind": str(invocation_kind or ""),
        "semantic_actions": semantic_actions,
        "control_actions": control_actions,
        "assistant_response_transport": "assistant_message",
        "ordinary_tool_transport": "provider_native_tool_call_or_json_tool_call",
        "control_action_transport": "json_action",
        "json_action_required_for": "control_or_task_action_only",
        "assistant_text_allowed_when_no_action": True,
        "required_transport": "assistant_message_or_tool_call_or_json_action",
        "json_action_shape": {
            "authority": "harness.loop.model_action_request",
            "single_unambiguous_action_required": True,
            "markdown_fence_allowed_when_single_action": True,
            "wrapper_text_allowed_when_single_action": True,
            "respond_requires_top_level_final_answer": "action_type=respond 时，最终给用户看的自然回复必须写在顶层 final_answer；不要放入 payload.content、payload.final_answer 或 action.content。",
            "ask_user_requires_top_level_user_question": "action_type=ask_user 时，用户要回答的问题必须写在顶层 user_question；不要通过 provider-native ask_user 工具调用表达。",
            "block_requires_top_level_blocking_reason": "action_type=block 时，真实阻塞原因必须写在顶层 blocking_reason。",
        },
        "task_entry_rule": {
            "request_task_run_allowed": bool(task_run_allowed),
            "upgrade_to_task_when_turn_boundary_insufficient": bool(task_run_allowed),
            "ask_user_when_contract_gaps_exist": True,
            "turn_first_policy": (
                "默认在当前 turn 内完成、验证并收口；复杂、跨文件或需要审查不自动等于 Task。"
            ),
            "task_upgrade_conditions": [
                "当前 turn 无法稳定承载目标、计划、状态、恢复、验收、审计、用户可追踪阶段反馈或资源隔离。",
                "工作需要跨 turn 状态记录、暂停/恢复/停止/replan、明确完成证据、长期执行、独立验收或资源隔离。",
                "工具/上下文预算触发 closeout/recover，需要保存证据、未完成项和恢复点后继续。",
            ],
            "single_turn_tool_call_boundary": (
                "普通 tool_call 是有效路径，只要当前 turn 能保住目标、证据、反馈和收口；"
                "在状态控制、验收或恢复需求越过 turn 边界前升级 Task。"
            ),
        },
        "feedback_obligation": {
            "agent_must_give_user_feedback": True,
            "pure_control_feedback_is_carried_by_control_payload_and_projection": True,
            "do_not_emit_detached_assistant_body_for_pure_control": True,
        },
    }


def _service_surface_payload(
    *,
    invocation_kind: str,
    allowed_action_types: tuple[str, ...],
    available_tools: tuple[dict[str, Any], ...],
    tool_plan: Any | None,
) -> dict[str, Any]:
    mounted_tools: list[dict[str, str]] = []
    for tool in available_tools:
        payload = dict(tool or {})
        tool_name = str(payload.get("tool_name") or payload.get("name") or "").strip()
        if not tool_name:
            continue
        mounted_tools.append(
            {
                "tool_name": tool_name,
                "operation_id": str(payload.get("operation_id") or tool_name),
                "owner_scope": str(payload.get("owner_scope") or "none"),
            }
        )
    return {
        "authority": "harness.runtime.service_surface",
        "invocation_kind": str(invocation_kind or ""),
        "tool_call_transport_available": "tool_call" in set(allowed_action_types or ()),
        "mounted_tools": mounted_tools,
        "unmounted_services": [
            {
                "service": str(issue.get("tool_name") or issue.get("operation_id") or ""),
                "tool_name": str(issue.get("tool_name") or ""),
                "operation_id": str(issue.get("operation_id") or ""),
                "category": _tool_filter_issue_category(issue),
                "reason": str(issue.get("reason") or ""),
                "source": str(issue.get("source") or ""),
                "required_action": str(dict(issue.get("metadata") or {}).get("required_action") or ""),
            }
            for issue in _tool_filter_issues_from_tool_plan(tool_plan)
            if str(issue.get("tool_name") or issue.get("operation_id") or "").strip()
        ],
    }


def _execution_boundary_payload(
    *,
    profile_payload: dict[str, Any],
    operation_authorization: dict[str, Any],
    permission_mode: str,
) -> dict[str, Any]:
    permission = dict(profile_payload.get("permission_policy") or {})
    return {
        "authority": "harness.runtime.execution_boundary",
        "safety_authority": "runtime.tooling.supervisor",
        "permission_mode": str(permission_mode or "default"),
        "permission_scope": str(permission.get("permission_scope") or permission.get("scope") or ""),
        "allowed_operation_count": len(list(operation_authorization.get("allowed_operations") or [])),
        "approval_required_operation_count": len(list(operation_authorization.get("requires_approval_operations") or [])),
        "operation_gate_stage": "deferred_to_tool_supervisor_for_real_execution_risk",
    }


def _tool_filter_issues_from_tool_plan(tool_plan: Any | None) -> list[dict[str, Any]]:
    plan = tool_plan.to_dict() if hasattr(tool_plan, "to_dict") else dict(tool_plan or {})
    capability_table = dict(plan.get("capability_table") or {})
    return [dict(item or {}) for item in list(capability_table.get("filtered") or []) if isinstance(item, dict)]


def _tool_filter_issue_category(issue: dict[str, Any]) -> str:
    reason = str(dict(issue or {}).get("reason") or "")
    source = str(dict(issue or {}).get("source") or "")
    if reason == "task_scoped_tool_requires_task_run":
        return "requires_task_run"
    if "approval" in reason:
        return "approval_required"
    if "denied" in reason or source == "operation_authorization":
        return "permission_denied"
    return "service_unavailable"


def _task_scoped_tool_routes_from_tool_plan(tool_plan: Any | None) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    for item in _tool_filter_issues_from_tool_plan(tool_plan):
        issue = dict(item or {})
        if str(issue.get("reason") or "") != "task_scoped_tool_requires_task_run":
            continue
        metadata = dict(issue.get("metadata") or {})
        routes.append(
            {
                "tool_name": str(issue.get("tool_name") or ""),
                "operation_id": str(issue.get("operation_id") or ""),
                "owner_scope": str(metadata.get("owner_scope") or ""),
                "required_action": str(metadata.get("required_action") or "request_task_run"),
            }
        )
    return [item for item in routes if item["tool_name"]]


def _runtime_projection_instruction(projection: dict[str, Any]) -> str:
    if not projection:
        return ""
    allowed_actions = [
        str(item)
        for item in list(projection.get("allowed_action_types") or [])
        if str(item)
    ]
    model_contract = dict(projection.get("model_decision_contract") or {})
    control_actions = [
        str(item)
        for item in list(model_contract.get("control_actions") or [])
        if str(item)
    ]
    service_surface = dict(projection.get("service_surface") or {})
    tool_boundary = dict(projection.get("tool_boundary") or {})
    try:
        visible_tool_count = int(tool_boundary.get("visible_tool_count") or 0)
    except (TypeError, ValueError):
        visible_tool_count = 0
    native_tool_available = bool(service_surface.get("tool_call_transport_available") is True) and bool(
        visible_tool_count > 0
    )
    allowed_text = "、".join(allowed_actions) if allowed_actions else "见 payload.allowed_action_types"
    protocol_refs = ["output_contract", "action_schema_static", "runtime_prompt.system_call_boundary"]
    if control_actions:
        protocol_refs.append("runtime_prompt.control_action_json")
    if native_tool_available:
        protocol_refs.append("runtime_prompt.native_tool_preamble")
    lines = [
        "本轮动作增量：",
        f"本轮允许动作：{allowed_text}。",
        "详细规则见：" + ", ".join(protocol_refs) + "；本段只列本轮新增约束。",
    ]
    return "\n".join(lines).strip() + "\n"


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
) -> dict[str, Any]:
    payload = dict(environment_payload or {})
    storage = dict(payload.get("storage_space") or {})
    sandbox = dict(payload.get("sandbox_policy") or {})
    execution = dict(payload.get("execution_policy") or {})
    file_management = dict(payload.get("file_management") or {})
    environment_boundary = dict(payload.get("environment_boundary") or {})
    boundary_contract = dict(environment_boundary.get("boundary_contract") or {})
    mount_plan = prompt_mount_plan_from_payload(prompt_mount_plan)
    prompt_refs = mount_plan.environment_prompt_refs or _string_tuple(environment_boundary.get("prompt_refs")) or tuple(
        str(item.get("prompt_id") or "").strip()
        for item in list(payload.get("environment_prompts") or [])
        if isinstance(item, dict) and str(item.get("prompt_id") or "").strip()
    )
    model_payload = {
        "environment_id": str(payload.get("environment_id") or payload.get("task_environment_id") or ""),
        "title": str(payload.get("title") or ""),
        "environment_kind": str(payload.get("environment_kind") or ""),
        "storage": _drop_empty_payload(
            {
                "environment_storage_root": str(storage.get("environment_storage_root") or ""),
                "artifact_root": str(storage.get("artifact_root") or ""),
                "cache_root": str(storage.get("cache_root") or ""),
                "storage_namespace": str(storage.get("storage_namespace") or ""),
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
                "base_environment_id": mount_plan.base_environment_id,
                "selected_environment_id": mount_plan.selected_environment_id,
                "environment_prompt_count": len(prompt_refs),
                "base_prompt_count": len(mount_plan.base_prompt_refs),
                "overlay_prompt_count": len(mount_plan.overlay_prompt_refs),
                "lifecycle_prompt_count": len(mount_plan.lifecycle_prompt_refs),
                "personality_prompt_count": len(mount_plan.personality_prompt_refs),
            }
        ),
        "boundary_contract": _drop_empty_payload(
            {
                "tool_authority": str(boundary_contract.get("tool_authority") or ""),
                "file_boundary_authority": str(boundary_contract.get("file_boundary_authority") or ""),
                "environment_prompts_source": str(boundary_contract.get("environment_prompts_source") or ""),
                "environment_prompt_role": str(boundary_contract.get("environment_prompt_role") or ""),
            }
        ),
        "authority": "task_system.environment.model_visible_projection",
    }
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
    return _drop_empty_payload(
        {
            "model_visible_sections": visible_sections,
            "selected_sections": [
                str(item)
                for item in list(memory_context.get("selected_sections") or visible_sections.keys())
                if str(item)
            ],
            "memory_runtime_view_ref": str(memory_context.get("memory_runtime_view_ref") or ""),
            "context_package_ref": str(memory_context.get("context_package_ref") or ""),
            "memory_context_status": status,
            "read_namespaces": list(diagnostics.get("read_namespaces") or ()),
            "requested_memory_layers": list(diagnostics.get("requested_memory_layers") or ()),
            "context_candidate_count": int(diagnostics.get("context_candidate_count") or 0),
            "state_candidate_count": int(diagnostics.get("state_candidate_count") or 0),
            "long_term_candidate_count": int(diagnostics.get("long_term_candidate_count") or 0),
            "requires_verification_before_use": True,
            "authority": str(memory_context.get("authority") or "memory_system.runtime_memory_context"),
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


def _read_evidence_prompt_source_ref(payload: dict[str, Any] | None, *, fallback: str) -> str:
    data = dict(payload or {})
    if not data:
        return str(fallback or "read_evidence_injection")
    return f"read_evidence:{_stable_json_hash(data).removeprefix('sha256:')[:16]}"


def _skill_candidate_instruction(assembly_payload: dict[str, Any]) -> str:
    cards = render_skill_candidate_cards(
        [
            dict(item)
            for item in list(assembly_payload.get("skill_runtime_views") or [])
            if isinstance(item, dict)
        ]
    )
    if not cards:
        return ""
    return _join_prompt_sections(
        cards,
        (
            "能力说明：这些候选内容只帮助你理解当前工作可用的专门能力。"
            "启动持续任务时请只提交任务目标、范围和完成标准。"
            "候选卡片不是完整技能说明；进入持续任务后运行环境会提供相关能力说明。"
            "不要把内部路由或工具名暴露给用户。"
        ),
    )


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
                        "operation_id": str(tool.get("operation_id") or "").strip(),
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
                "authorized_input_content_lives_in": "Task execution graph node runtime context",
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
                "authority": "harness.graph.inbound_context.model_visible",
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
        "authority": str(item.get("authority") or "harness.graph.flow_packet.artifact_text_projection"),
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
