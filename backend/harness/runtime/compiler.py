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
from task_system.contracts.runtime_contracts import expand_selected_skill_bodies, render_skill_candidate_cards

from .dynamic_context import DynamicContextInput, DynamicContextManager, DynamicContextProjection
from .envelope import RuntimeEnvelope
from .invocation_packet import RuntimeInvocationPacket
from .prompt_segment_plan import build_prompt_segment_plan


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

    def compile_plain_conversation_packet(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent_invocation_id: str,
        user_message: str,
        history: list[dict[str, Any]],
        agent_profile_ref: str = "main_interactive_agent",
        model_selection: dict[str, Any] | None = None,
        runtime_assembly: Any | None = None,
    ) -> RuntimeCompilationResult:
        assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
        self._bind_assembly_base_dir(assembly_payload)
        profile_payload = dict(assembly_payload.get("profile") or {})
        environment_payload = dict(assembly_payload.get("task_environment") or {})
        control_capabilities = dict(assembly_payload.get("control_capabilities") or {})
        agent_profile_ref = str(agent_profile_ref or assembly_payload.get("agent_profile_ref") or "main_interactive_agent")
        task_environment_ref = str(environment_payload.get("environment_id") or "env.general.workspace")
        prompt_pack_refs = _prompt_pack_refs_for_invocation(profile_payload, invocation_kind="plain_conversation")
        soul_role_prompt = dict(assembly_payload.get("soul_role_prompt") or {})
        envelope = RuntimeEnvelope(
            envelope_id=f"rtenv:{turn_id}:plain_conversation",
            scope_kind="turn",
            session_id=session_id,
            turn_id=turn_id,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            sandbox_policy=dict(environment_payload.get("sandbox_policy") or {}),
            file_policy={
                "file_management": dict(environment_payload.get("file_management") or {}),
                "file_access_tables": list(environment_payload.get("file_access_tables") or []),
            },
            artifact_policy=dict(environment_payload.get("artifact_policy") or {}),
            permission_policy=dict(profile_payload.get("permission_policy") or {}),
            prompt_policy={"invocation_kind": "plain_conversation"},
            output_policy={"format": "assistant_message"},
            diagnostics={
                "agent_invocation_id": agent_invocation_id,
                "model_selection": dict(model_selection or {}),
                "runtime_assembly_id": str(assembly_payload.get("assembly_id") or ""),
                "control_capabilities": dict(control_capabilities),
            },
        )
        prompt_assembly = self._assemble_prompt_pack(
            invocation_kind="plain_conversation",
            prompt_pack_refs=prompt_pack_refs,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="agent_profile",
            prompt_refs=_string_tuple(assembly_payload.get("agent_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        environment_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=_string_tuple(assembly_payload.get("environment_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        environment_instruction = _environment_instruction(
            environment_payload,
            environment_prompt_assembly=environment_prompt_assembly,
        )
        agent_instruction = _agent_prompt_instruction(agent_prompt_assembly)
        soul_instruction = _soul_instruction(soul_role_prompt)
        stable_payload = {
            "control_capabilities": dict(control_capabilities),
            "task_environment": _environment_model_visible_payload(environment_payload),
            "output_contract": {
                "format": "assistant_message",
                "forbidden": ["json_action_protocol", "tool_call_request", "task_run_request", "runtime_ids"],
            },
        }
        packet_id = f"rtpacket:{turn_id}:plain_conversation:1"
        history_specs = [
            _message_spec(
                role=str(item.get("role") or "user"),
                content=str(item.get("content") or ""),
                kind="conversation_history",
                source_ref="conversation_history",
                cache_scope="none",
                cache_role="volatile",
                compression_role="summarize",
            )
            for item in list(history or [])
            if isinstance(item, dict) and str(item.get("role") or "") in {"user", "assistant", "system"} and str(item.get("content") or "").strip()
        ]
        model_messages, segment_plan = _model_messages_and_segment_plan(
            packet_id=packet_id,
            invocation_kind="plain_conversation",
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
                _message_spec(
                    role="system",
                    content=_packet_payload_content("Plain conversation stable boundary", stable_payload),
                    kind="conversation_stable",
                    source_ref="plain_conversation_stable_boundary",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=_join_prompt_sections(soul_instruction, agent_instruction, environment_instruction),
                    kind="conversation_context",
                    source_ref="plain_conversation_context",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                *history_specs,
                _message_spec(
                    role="user",
                    content=str(user_message or ""),
                    kind="current_user_message",
                    source_ref="plain_conversation_current_user_message",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="preserve",
                ),
            ],
        )
        prompt_manifest = build_runtime_prompt_manifest(
            invocation_kind="plain_conversation",
            assembly=_merge_prompt_assemblies(
                prompt_assembly,
                agent_prompt_assembly,
                environment_prompt_assembly,
                invocation_kind="plain_conversation",
            ),
            packet_id=packet_id,
            volatile_state_refs=("history", "user_message"),
        ).to_dict()
        prompt_manifest["segment_plan_ref"] = segment_plan.segment_plan_id
        _attach_model_message_metrics(prompt_manifest, model_messages=model_messages, segment_plan=segment_plan.to_dict())
        packet = RuntimeInvocationPacket(
            packet_id=packet_id,
            envelope_ref=envelope.envelope_id,
            invocation_kind="plain_conversation",
            invocation_index=1,
            session_id=session_id,
            turn_id=turn_id,
            model_messages=model_messages,
            segment_plan=segment_plan.to_dict(),
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
            available_tools=(),
            allowed_action_types=("respond", "ask_user"),
            output_contract={"format": "assistant_message"},
            hidden_control_refs={"agent_invocation_id": agent_invocation_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
                "model_input_authority": "runtime_invocation_packet.model_messages",
                "control_capabilities": dict(control_capabilities),
            },
        )
        return RuntimeCompilationResult(envelope=envelope, packet=packet)

    def compile_turn_action_packet(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent_invocation_id: str,
        user_message: str,
        history: list[dict[str, Any]],
        task_selection: dict[str, Any] | None = None,
        agent_profile_ref: str = "main_interactive_agent",
        model_selection: dict[str, Any] | None = None,
        available_tools: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
        runtime_assembly: Any | None = None,
    ) -> RuntimeCompilationResult:
        assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
        self._bind_assembly_base_dir(assembly_payload)
        profile_payload = dict(assembly_payload.get("profile") or {})
        environment_payload = dict(assembly_payload.get("task_environment") or {})
        agent_profile_ref = str(agent_profile_ref or assembly_payload.get("agent_profile_ref") or "main_interactive_agent")
        task_environment_ref = str(environment_payload.get("environment_id") or "env.general.workspace")
        runtime_policy = {
            "planning_policy": dict(profile_payload.get("planning_policy") or {}),
            "task_lifecycle_policy": dict(profile_payload.get("task_lifecycle_policy") or {}),
            "soul_prompt_policy": dict(profile_payload.get("soul_prompt_policy") or {}),
        }
        permission_policy = dict(profile_payload.get("permission_policy") or {"permission_scope": "action_request_only"})
        permission_policy.setdefault("permission_scope", str(permission_policy.get("scope") or "action_request_only"))
        prompt_pack_refs = _prompt_pack_refs_for_invocation(profile_payload, invocation_kind="turn_action")
        soul_role_prompt = dict(assembly_payload.get("soul_role_prompt") or {})
        tool_payloads = tuple(dict(item) for item in list(available_tools or []) if isinstance(item, dict))
        agent_visible_runtime_projection = _agent_visible_runtime_projection(
            invocation_kind="turn_action",
            allowed_action_types=("respond", "ask_user", "tool_call", "request_task_run", "request_registered_engagement", "block"),
            profile_payload=profile_payload,
            environment_payload=environment_payload,
            operation_authorization=dict(assembly_payload.get("operation_authorization") or {}),
            available_tools=tool_payloads,
        )
        envelope = RuntimeEnvelope(
            envelope_id=f"rtenv:{turn_id}:turn",
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
            prompt_policy={"invocation_kind": "turn_action"},
            output_policy={"format": "model_action_request_json"},
            diagnostics={
                "agent_invocation_id": agent_invocation_id,
                "model_selection": dict(model_selection or {}),
                "runtime_assembly_id": str(assembly_payload.get("assembly_id") or ""),
            },
        )
        schema = model_action_request_schema(turn_id)
        prompt_assembly = self._assemble_prompt_pack(
            invocation_kind="turn_action",
            prompt_pack_refs=prompt_pack_refs,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="agent_profile",
            prompt_refs=_string_tuple(assembly_payload.get("agent_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        environment_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=_string_tuple(assembly_payload.get("environment_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        runtime_instruction = _runtime_projection_instruction(agent_visible_runtime_projection)
        environment_instruction = _environment_instruction(
            environment_payload,
            environment_prompt_assembly=environment_prompt_assembly,
        )
        agent_instruction = _agent_prompt_instruction(agent_prompt_assembly)
        soul_instruction = _soul_instruction(soul_role_prompt)
        skill_candidate_instruction = _skill_candidate_instruction(assembly_payload)
        stable_payload = {
            "schema": schema,
            "task_environment": _environment_model_visible_payload(environment_payload),
            "available_tools": _stable_tool_catalog_payload(tool_payloads),
            "tool_catalog_hash": _stable_json_hash([dict(item) for item in tool_payloads]),
        }
        packet_id = f"rtpacket:{turn_id}:turn_action:1"
        dynamic_context = self.dynamic_context_manager.project(
            DynamicContextInput(
                invocation_kind="turn_action",
                session_id=session_id,
                turn_id=turn_id,
                history=tuple(dict(item) for item in list(history or []) if isinstance(item, dict)),
                runtime_assembly=assembly_payload,
                runtime_envelope=envelope.to_dict(),
                current_user_message=str(user_message or ""),
                projection_policy={
                    "agent_visible_runtime_projection": agent_visible_runtime_projection,
                    "operation_authorization": dict(assembly_payload.get("operation_authorization") or {}),
                },
            )
        )
        dynamic_payload = dynamic_context.dynamic_runtime_projection
        volatile_payload = dynamic_context.volatile_request_projection
        model_messages, segment_plan = _model_messages_and_segment_plan(
            packet_id=packet_id,
            invocation_kind="turn_action",
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
                _message_spec(
                    role="system",
                    content=_packet_payload_content("Turn action stable contract", stable_payload),
                    kind="task_stable",
                    source_ref="turn_action_stable_contract",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=skill_candidate_instruction,
                    kind="skill_candidates",
                    source_ref="runtime_skill_candidates",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=_join_prompt_sections(soul_instruction, agent_instruction),
                    kind="agent_stable",
                    source_ref=",".join(_string_tuple(assembly_payload.get("agent_prompt_refs"))),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=environment_instruction,
                    kind="environment_stable",
                    source_ref=",".join(_string_tuple(assembly_payload.get("environment_prompt_refs"))),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=_join_prompt_sections(
                        runtime_instruction,
                        _packet_payload_content("Turn action dynamic runtime", dynamic_payload),
                    ),
                    kind="dynamic_projection",
                    source_ref="agent_visible_runtime_projection",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata=_dynamic_context_segment_metadata(dynamic_context, source="runtime_delta"),
                ),
                _message_spec(
                    role="user",
                    content=_packet_payload_content("Turn action current request", volatile_payload),
                    kind="volatile_user",
                    source_ref="turn_action_current_request",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata=_dynamic_context_segment_metadata(dynamic_context, source="current_request"),
                ),
            ],
            enforce_dynamic_context_reports=True,
        )
        prompt_manifest = build_runtime_prompt_manifest(
            invocation_kind="turn_action",
            assembly=_merge_prompt_assemblies(
                prompt_assembly,
                agent_prompt_assembly,
                environment_prompt_assembly,
                invocation_kind="turn_action",
            ),
            packet_id=packet_id,
            dynamic_projection_refs=("agent_visible_runtime_projection", "operation_authorization"),
            volatile_state_refs=("runtime_envelope", "turn_id", "history", "user_message"),
        ).to_dict()
        prompt_manifest["segment_plan_ref"] = segment_plan.segment_plan_id
        prompt_manifest["dynamic_context_report"] = dynamic_context.to_report_dict()
        _attach_model_message_metrics(prompt_manifest, model_messages=model_messages, segment_plan=segment_plan.to_dict())
        packet = RuntimeInvocationPacket(
            packet_id=packet_id,
            envelope_ref=envelope.envelope_id,
            invocation_kind="turn_action",
            invocation_index=1,
            session_id=session_id,
            turn_id=turn_id,
            model_messages=model_messages,
            segment_plan=segment_plan.to_dict(),
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
            available_tools=tool_payloads,
            allowed_action_types=("respond", "ask_user", "tool_call", "request_task_run", "request_registered_engagement", "block"),
            output_contract={"schema": schema, "format": "json_object"},
            hidden_control_refs={"agent_invocation_id": agent_invocation_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
            context_refs=dynamic_context.context_refs,
            artifact_refs=dynamic_context.artifact_refs,
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
                "model_input_authority": "runtime_invocation_packet.model_messages",
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
        invocation_index: int = 1,
    ) -> RuntimeCompilationResult:
        assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
        self._bind_assembly_base_dir(assembly_payload)
        profile_payload = dict(assembly_payload.get("profile") or {})
        environment_payload = dict(assembly_payload.get("task_environment") or {})
        agent_profile_ref = str(agent_profile_ref or assembly_payload.get("agent_profile_ref") or "main_interactive_agent")
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
        graph_runtime_projection = bool(graph_slot)
        task_run_context_enabled = _task_run_context_enabled(profile_payload)
        prompt_pack_refs = _prompt_pack_refs_for_invocation(profile_payload, invocation_kind="task_execution")
        operation_authorization = dict(assembly_payload.get("operation_authorization") or {})
        agent_visible_runtime_projection = _agent_visible_runtime_projection(
            invocation_kind="task_execution",
            allowed_action_types=("respond", "ask_user", "tool_call", "block"),
            profile_payload=profile_payload,
            environment_payload=environment_payload,
            operation_authorization=operation_authorization,
            available_tools=tool_payloads,
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
            artifact_policy=dict(environment_payload.get("artifact_policy") or {}),
            permission_policy=permission_policy,
            prompt_policy={"invocation_kind": "task_execution"},
            output_policy={"format": "model_action_request_json"},
            graph_slot=graph_slot,
            diagnostics={
                "task_run_id": task_run_id,
                "model_selection": dict(model_selection or {}),
                "runtime_assembly_id": str(assembly_payload.get("assembly_id") or ""),
            },
        )
        schema = task_execution_action_schema()
        artifact_root = _artifact_root(environment_payload)
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
        if not task_run_context_enabled:
            task_prompt_contract = {}
        prompt_assembly = self._assemble_prompt_pack(
            invocation_kind="task_execution",
            prompt_pack_refs=prompt_pack_refs,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        task_prompt_assembly = self._assemble_prompt_contract(
            task_prompt_contract=task_prompt_contract,
            graph_node_prompt_contract=graph_node_prompt_contract,
        )
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="agent_profile",
            prompt_refs=_string_tuple(assembly_payload.get("agent_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        environment_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=_string_tuple(assembly_payload.get("environment_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        artifact_note = f"当前建议 artifact_root 是 {artifact_root}。" if artifact_root else ""
        runtime_instruction = _join_prompt_sections(
            artifact_note,
            _runtime_projection_instruction(agent_visible_runtime_projection),
        )
        active_skill_instruction, active_skill_meta = _active_skill_instruction(
            base_dir=self.base_dir,
            assembly_payload=assembly_payload,
        )
        environment_instruction = _environment_instruction(
            environment_payload,
            environment_prompt_assembly=environment_prompt_assembly,
        )
        agent_instruction = _agent_prompt_instruction(agent_prompt_assembly)
        stable_payload = {
            "schema": schema,
            "task_contract": _task_contract_stable_payload(contract),
            "task_environment": _environment_model_visible_payload(environment_payload),
            "available_tools": _stable_tool_catalog_payload(tool_payloads),
            "tool_catalog_hash": _stable_json_hash([dict(item) for item in tool_payloads]),
        }
        if task_run_context_enabled:
            stable_payload["task_run"] = _task_run_stable_payload(task_run, graph_runtime_projection=graph_runtime_projection)
        packet_id = f"rtpacket:{task_run_id}:task_execution:{executor_epoch}:{invocation_index}"
        dynamic_context = self.dynamic_context_manager.project(
            DynamicContextInput(
                invocation_kind="task_execution",
                session_id=session_id,
                task_run_id=task_run_id,
                task_run=dict(task_run or {}),
                observations=tuple(dict(item) for item in list(observations or []) if isinstance(item, dict)),
                execution_state=dict(execution_state or {}),
                work_rollout=dict(work_rollout or {}),
                runtime_assembly=assembly_payload,
                runtime_envelope=envelope.to_dict(),
                projection_policy={
                    "agent_visible_runtime_projection": agent_visible_runtime_projection,
                    "operation_authorization": operation_authorization,
                    "include_task_run_context": task_run_context_enabled,
                },
            )
        )
        dynamic_payload = dynamic_context.dynamic_runtime_projection
        volatile_payload = dynamic_context.volatile_state_projection
        model_messages, segment_plan = _model_messages_and_segment_plan(
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
                _message_spec(
                    role="system",
                    content=_packet_payload_content("Task execution stable contract", stable_payload),
                    kind="task_stable",
                    source_ref=str(contract.get("contract_id") or task_run.get("task_run_id") or "task_execution_stable_contract"),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=_prompt_contract_instruction(task_prompt_assembly),
                    kind="task_prompt_contract",
                    source_ref=",".join(task_prompt_assembly.manifest.get("stable_contract_refs") or ()),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=agent_instruction,
                    kind="agent_stable",
                    source_ref=",".join(_string_tuple(assembly_payload.get("agent_prompt_refs"))),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=active_skill_instruction,
                    kind="active_skills",
                    source_ref=",".join(active_skill_meta.get("source_refs") or ()),
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=environment_instruction,
                    kind="environment_stable",
                    source_ref=",".join(_string_tuple(assembly_payload.get("environment_prompt_refs"))),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=_join_prompt_sections(
                        runtime_instruction,
                        _packet_payload_content("Task execution runtime boundary", dynamic_payload),
                    ),
                    kind="runtime_boundary",
                    source_ref="agent_visible_runtime_projection",
                    cache_scope="task",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata=_dynamic_context_segment_metadata(dynamic_context, source="runtime_delta"),
                ),
                _message_spec(
                    role="user",
                    content=_packet_payload_content("Task execution current state", volatile_payload),
                    kind="volatile_task_state",
                    source_ref="task_execution_current_state",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata=_dynamic_context_segment_metadata(dynamic_context, source="execution_state"),
                ),
            ],
            enforce_dynamic_context_reports=True,
        )
        prompt_manifest = build_runtime_prompt_manifest(
            invocation_kind="task_execution",
            assembly=_merge_prompt_assemblies(
                prompt_assembly,
                task_prompt_assembly,
                agent_prompt_assembly,
                environment_prompt_assembly,
                invocation_kind="task_execution",
            ),
            packet_id=packet_id,
            dynamic_projection_refs=(
                "agent_visible_runtime_projection",
                "operation_authorization",
            ),
            volatile_state_refs=(
                "runtime_envelope",
                "execution_state",
                "pending_user_steers",
                "active_contract_revisions",
                "observations",
                "work_history",
            ),
        ).to_dict()
        prompt_manifest["segment_plan_ref"] = segment_plan.segment_plan_id
        prompt_manifest["dynamic_context_report"] = dynamic_context.to_report_dict()
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
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
            available_tools=tool_payloads,
            allowed_action_types=("respond", "ask_user", "tool_call", "block"),
            observation_refs=dynamic_context.observation_refs,
            artifact_refs=dynamic_context.artifact_refs,
            context_refs=dynamic_context.context_refs,
            output_contract={"schema": schema, "format": "json_object"},
            hidden_control_refs={"task_run_id": task_run_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
                "model_input_authority": "runtime_invocation_packet.model_messages",
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
        agent_profile_ref = str(agent_profile_ref or assembly_payload.get("agent_profile_ref") or "main_interactive_agent")
        task_environment_ref = str(environment_payload.get("environment_id") or "env.general.workspace")
        runtime_policy = {
            "planning_policy": dict(profile_payload.get("planning_policy") or {}),
            "task_lifecycle_policy": dict(profile_payload.get("task_lifecycle_policy") or {}),
            "soul_prompt_policy": dict(profile_payload.get("soul_prompt_policy") or {}),
        }
        permission_policy = dict(profile_payload.get("permission_policy") or {"permission_scope": "bounded_read_observation"})
        permission_policy.setdefault("permission_scope", str(permission_policy.get("scope") or "bounded_read_observation"))
        prompt_pack_refs = _prompt_pack_refs_for_invocation(profile_payload, invocation_kind="tool_observation_followup")
        soul_role_prompt = dict(assembly_payload.get("soul_role_prompt") or {})
        tool_payloads = tuple(dict(item) for item in list(available_tools or []) if isinstance(item, dict))
        agent_visible_runtime_projection = _agent_visible_runtime_projection(
            invocation_kind="tool_observation_followup",
            allowed_action_types=("respond", "ask_user", "tool_call", "request_task_run", "request_registered_engagement", "block"),
            profile_payload=profile_payload,
            environment_payload=environment_payload,
            operation_authorization=dict(assembly_payload.get("operation_authorization") or {}),
            available_tools=tool_payloads,
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
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="agent_profile",
            prompt_refs=_string_tuple(assembly_payload.get("agent_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        environment_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=_string_tuple(assembly_payload.get("environment_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
        )
        runtime_instruction = _runtime_projection_instruction(agent_visible_runtime_projection)
        environment_instruction = _environment_instruction(
            environment_payload,
            environment_prompt_assembly=environment_prompt_assembly,
        )
        agent_instruction = _agent_prompt_instruction(agent_prompt_assembly)
        soul_instruction = _soul_instruction(soul_role_prompt)
        skill_candidate_instruction = _skill_candidate_instruction(assembly_payload)
        stable_payload = {
            "schema": schema,
            "task_environment": _environment_model_visible_payload(environment_payload),
            "available_tools": _stable_tool_catalog_payload(tool_payloads),
            "tool_catalog_hash": _stable_json_hash([dict(item) for item in tool_payloads]),
        }
        packet_id = f"rtpacket:{turn_id}:tool_observation_followup:{len(observations) + 1}"
        dynamic_context = self.dynamic_context_manager.project(
            DynamicContextInput(
                invocation_kind="tool_observation_followup",
                session_id=session_id,
                turn_id=turn_id,
                history=tuple(dict(item) for item in list(history or []) if isinstance(item, dict)),
                observations=tuple(dict(item) for item in list(observations or []) if isinstance(item, dict)),
                runtime_assembly=assembly_payload,
                runtime_envelope=envelope.to_dict(),
                current_user_message=str(user_message or ""),
                projection_policy={
                    "agent_visible_runtime_projection": agent_visible_runtime_projection,
                    "operation_authorization": dict(assembly_payload.get("operation_authorization") or {}),
                },
            )
        )
        dynamic_payload = dynamic_context.dynamic_runtime_projection
        volatile_payload = dynamic_context.volatile_request_projection
        model_messages, segment_plan = _model_messages_and_segment_plan(
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
                _message_spec(
                    role="system",
                    content=_packet_payload_content("Observation followup stable contract", stable_payload),
                    kind="task_stable",
                    source_ref="observation_followup_stable_contract",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=skill_candidate_instruction,
                    kind="skill_candidates",
                    source_ref="runtime_skill_candidates",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=_join_prompt_sections(soul_instruction, agent_instruction),
                    kind="agent_stable",
                    source_ref=",".join(_string_tuple(assembly_payload.get("agent_prompt_refs"))),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=environment_instruction,
                    kind="environment_stable",
                    source_ref=",".join(_string_tuple(assembly_payload.get("environment_prompt_refs"))),
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                ),
                _message_spec(
                    role="system",
                    content=_join_prompt_sections(
                        runtime_instruction,
                        _packet_payload_content("Observation followup dynamic runtime", dynamic_payload),
                    ),
                    kind="dynamic_projection",
                    source_ref="agent_visible_runtime_projection",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata=_dynamic_context_segment_metadata(dynamic_context, source="runtime_delta"),
                ),
                _message_spec(
                    role="user",
                    content=_packet_payload_content("Observation followup current request", volatile_payload),
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
        prompt_manifest = build_runtime_prompt_manifest(
            invocation_kind="tool_observation_followup",
            assembly=_merge_prompt_assemblies(
                prompt_assembly,
                agent_prompt_assembly,
                environment_prompt_assembly,
                invocation_kind="tool_observation_followup",
            ),
            packet_id=packet_id,
            dynamic_projection_refs=("agent_visible_runtime_projection", "operation_authorization"),
            volatile_state_refs=("runtime_envelope", "turn_id", "history", "user_message", "observations"),
        ).to_dict()
        prompt_manifest["segment_plan_ref"] = segment_plan.segment_plan_id
        prompt_manifest["dynamic_context_report"] = dynamic_context.to_report_dict()
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
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
            available_tools=tool_payloads,
            allowed_action_types=("respond", "ask_user", "tool_call", "request_task_run", "request_registered_engagement", "block"),
            observation_refs=dynamic_context.observation_refs,
            artifact_refs=dynamic_context.artifact_refs,
            context_refs=dynamic_context.context_refs,
            output_contract={"schema": schema, "format": "json_object"},
            hidden_control_refs={"agent_invocation_id": agent_invocation_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
                "model_input_authority": "runtime_invocation_packet.model_messages",
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
        return PromptAssemblyService(self.base_dir).assemble(
            PromptAssemblyRequest(
                invocation_kind=invocation_kind,
                prompt_pack_refs=refs,
                agent_profile_ref=agent_profile_ref,
                task_environment_ref=task_environment_ref,
            )
        )

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
        return PromptAssemblyService(self.base_dir).assemble(
            PromptAssemblyRequest(
                invocation_kind=invocation_kind,
                prompt_pack_refs=(),
                prompt_refs=prompt_refs,
                agent_profile_ref=agent_profile_ref,
                task_environment_ref=task_environment_ref,
            )
        )


def model_action_request_schema(turn_id: str) -> dict[str, Any]:
    del turn_id
    return {
        "authority": "harness.loop.model_action_request",
        "action_type": "respond|ask_user|tool_call|request_task_run|request_registered_engagement|block",
        "public_progress_note": "一句用户可理解的公开进展；不包含内部编号、系统结构、协议字段或隐藏推理。",
        "public_action_state": {
            "evidence_refs": ["可选；你本轮判断引用的 observation/event/artifact ref"],
            "current_judgment": "可选；你基于当前上下文作出的公开判断，只写结论，不暴露隐藏推理链。",
            "next_action": "可选；你马上要采取的具体动作；如果收尾，说明准备提交什么结果。",
            "open_risks": ["可选；仍未解决、会影响完成判断的公开风险"],
            "completion_status": "可选；working|verifying|ready_to_finish|blocked"
        },
        "final_answer": "",
        "user_question": "",
        "blocking_reason": "",
        "tool_call": {"tool_name": "", "args": {}},
        "selected_skill_ids": ["可选；从候选 Skills 中选择需要激活的 skill_id，例如 skill.deep-web-research"],
        "task_contract_seed": {
            "user_visible_goal": "用户可理解的任务目标，必填",
            "task_run_goal": "给执行生命周期使用的任务目标，必填",
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
            "resource_requirements": {},
            "permission_requirements": {},
            "acceptance_policy": {},
            "recovery_policy": {}
        },
        "completion_contract": {
            "completion_criteria": [],
            "artifact_requirements": [],
            "required_verifications": []
        },
        "permission_request": {},
        "engagement_request": {
            "plan_id": "",
            "startup_parameters": {}
        },
        "diagnostics": {},
    }


def task_execution_action_schema() -> dict[str, Any]:
    return {
        "authority": "harness.loop.model_action_request",
        "action_type": "respond|ask_user|tool_call|block",
        "public_progress_note": "一句用户可理解的公开进展；必须来自 public_action_state 的公开判断和下一步，不包含内部编号、系统结构、协议字段或隐藏推理。",
        "public_action_state": {
            "evidence_refs": ["你本轮判断引用的 observation/event/artifact ref；没有证据时留空"],
            "current_judgment": "你基于当前上下文作出的公开判断，只写结论，不暴露隐藏推理链。",
            "next_action": "你马上要采取的具体动作；如果收尾，说明准备提交什么结果。",
            "open_risks": ["仍未解决、会影响完成判断的公开风险；没有则留空"],
            "completion_status": "working|verifying|ready_to_finish|blocked"
        },
        "final_answer": "",
        "user_question": "",
        "blocking_reason": "",
        "tool_call": {"tool_name": "", "args": {}},
        "selected_skill_ids": ["可选；当前任务执行中需要继续激活的 skill_id"],
        "task_contract_seed": {},
        "completion_contract": {},
        "permission_request": {},
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
        },
    }


def _message_spec(
    *,
    role: str,
    content: str,
    kind: str,
    source_ref: str,
    cache_scope: str,
    cache_role: str,
    compression_role: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "role": str(role or "user"),
        "content": str(content or ""),
        "kind": str(kind or "unknown_unplanned"),
        "source_ref": str(source_ref or ""),
        "cache_scope": str(cache_scope or "none"),
        "cache_role": str(cache_role or "volatile"),
        "compression_role": str(compression_role or "summarize"),
        "metadata": dict(metadata or {}),
    }


def _model_messages_and_segment_plan(
    *,
    packet_id: str,
    invocation_kind: str,
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    enforce_dynamic_context_reports: bool = False,
) -> tuple[list[dict[str, str]], Any]:
    clean_specs = [
        {
            **dict(spec),
            "role": str(dict(spec).get("role") or "user"),
            "content": str(dict(spec).get("content") or "").strip(),
        }
        for spec in list(specs or [])
        if str(dict(spec).get("content") or "").strip()
    ]
    if enforce_dynamic_context_reports:
        _validate_dynamic_context_metadata(clean_specs)
    model_messages = [
        {
            "role": str(spec.get("role") or "user"),
            "content": str(spec.get("content") or "").strip(),
        }
        for spec in clean_specs
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id=packet_id,
        invocation_kind=invocation_kind,
        message_specs=clean_specs,
        enforce_dynamic_context_reports=enforce_dynamic_context_reports,
    )
    return model_messages, segment_plan


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


def _valid_message_index(index: Any, message_chars: list[int]) -> bool:
    try:
        value = int(index)
    except (TypeError, ValueError):
        return False
    return 0 <= value < len(message_chars)


def _packet_payload_content(title: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{title}\n{body}"


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
            "authority": "prompt_library.prompt_assembly_manifest",
        },
    )


def _string_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _prompt_pack_refs_for_invocation(profile_payload: dict[str, Any], *, invocation_kind: str) -> tuple[str, ...]:
    by_invocation = dict(profile_payload.get("prompt_pack_refs_by_invocation") or {})
    refs = _string_tuple(by_invocation.get(invocation_kind))
    if refs:
        return refs
    return _string_tuple(profile_payload.get("prompt_pack_refs"))


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
    graph_prompt_contract = _graph_slot_node_prompt_contract(contract)
    payload = dict(graph_prompt_contract or contract.get("prompt_contract") or {})
    engagement_contract = dict(assembly_payload.get("engagement_contract") or {})
    if not payload:
        payload = dict(engagement_contract.get("prompt_contract") or {})
    result = _normalize_prompt_contract(
        payload,
        contract_id=str(
            payload.get("contract_id")
            or contract.get("contract_id")
            or engagement_contract.get("contract_id")
            or task_run.get("task_run_id")
            or "task_prompt_contract"
        ),
    )
    if not result.get("task_instruction"):
        result["task_instruction"] = _first_runtime_text(
            contract.get("task_run_goal"),
            contract.get("user_visible_goal"),
            task_run.get("title"),
        )
    if not result.get("definition_of_done"):
        result["definition_of_done"] = _string_list(contract.get("completion_criteria"))
    return result


def _graph_node_prompt_contract_from_runtime(
    *,
    task_run: dict[str, Any],
    contract: dict[str, Any],
    assembly_payload: dict[str, Any],
) -> dict[str, Any]:
    engagement_contract = dict(assembly_payload.get("engagement_contract") or {})
    payload = dict(
        _graph_slot_node_prompt_contract(contract)
        or dict(contract.get("graph_node_prompt_contract") or {})
        or dict(engagement_contract.get("graph_node_prompt_contract") or {})
        or dict(dict(engagement_contract.get("execution_strategy") or {}).get("graph_node_prompt_contract") or {})
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


def _agent_visible_runtime_projection(
    *,
    invocation_kind: str,
    allowed_action_types: tuple[str, ...],
    profile_payload: dict[str, Any],
    environment_payload: dict[str, Any],
    operation_authorization: dict[str, Any],
    available_tools: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    task_lifecycle = dict(profile_payload.get("task_lifecycle_policy") or {})
    planning = dict(profile_payload.get("planning_policy") or {})
    self_review = dict(profile_payload.get("self_review_policy") or {})
    step_summary = dict(profile_payload.get("step_summary_policy") or {})
    permission = dict(profile_payload.get("permission_policy") or {})
    subagent = dict(profile_payload.get("subagent_policy") or {})
    storage = dict(environment_payload.get("storage_space") or {})
    environment_boundary = dict(environment_payload.get("environment_boundary") or {})
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
    task_run_allowed = "request_task_run" in allowed_action_types and task_lifecycle.get("request_task_run") is not False
    return {
        "authority": "harness.runtime.agent_visible_runtime_projection",
        "invocation_kind": str(invocation_kind or ""),
        "allowed_action_types": list(allowed_action_types),
        "task_lifecycle": {
            "request_task_run_allowed": task_run_allowed,
            "requires_completion_evidence": bool(task_lifecycle.get("requires_completion_evidence") is True),
            "artifact_evidence_required": bool(task_lifecycle.get("artifact_evidence_required") is True),
        },
        "planning": {
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
            "allowed_operation_count": len(allowed_operations),
            "tools_are_limited_to_visible_context": True,
            "subagent_lifecycle_enabled": bool(subagent.get("enabled") is True),
            "allowed_subagent_ids": [str(item) for item in list(subagent.get("allowed_subagent_ids") or []) if str(item)],
        },
        "permission_boundary": {
            "permission_scope": str(permission.get("permission_scope") or permission.get("scope") or ""),
        },
        "environment_boundary": {
            "task_environment_id": str(environment_payload.get("environment_id") or ""),
            "artifact_root": str(storage.get("artifact_root") or ""),
            "environment_storage_root": str(storage.get("environment_storage_root") or ""),
            "boundary_authority": str(environment_boundary.get("authority") or ""),
        },
    }


def _runtime_projection_instruction(projection: dict[str, Any]) -> str:
    if not projection:
        return ""
    allowed_actions = {
        str(item)
        for item in list(projection.get("allowed_action_types") or [])
        if str(item)
    }
    task_lifecycle = dict(projection.get("task_lifecycle") or {})
    planning = dict(projection.get("planning") or {})
    self_review = dict(projection.get("self_review") or {})
    step_summary = dict(projection.get("step_summary") or {})
    tool_boundary = dict(projection.get("tool_boundary") or {})
    permission_boundary = dict(projection.get("permission_boundary") or {})
    lines = ["本次运行边界："]
    action_notes: list[str] = []
    if "respond" in allowed_actions:
        action_notes.append("直接回答")
    if "ask_user" in allowed_actions:
        action_notes.append("询问用户")
    if "tool_call" in allowed_actions:
        action_notes.append("调用本次可见工具")
    if "block" in allowed_actions:
        action_notes.append("在越界、缺少授权或无法继续时阻止")
    if action_notes:
        lines.append("- 你可以" + "、".join(action_notes) + "。")
    lines.append(
        "- 你必须先在内部完成任务状态审查、证据核对、风险判断和下一步选择；这些内部推理不得输出。"
    )
    lines.append(
        "- 在任务执行阶段，每次输出 JSON 时必须填写 public_action_state 和 public_progress_note。public_action_state 是公开行动状态，"
        "必须包含 current_judgment、next_action；open_risks 和 evidence_refs 只引用真实上下文证据，不复制原始思维过程。"
    )
    lines.append(
        "- public_progress_note 必须是 public_action_state 的一句自然语言摘要；不要写“正在思考”“正在分析当前目标”等空泛状态。"
    )
    if projection.get("invocation_kind") == "task_execution":
        lines.append(
            "- 如果当前执行状态里有 pending_user_steers，你必须先判断并处理这些用户补充要求；"
            "只有确实处理了某条补充要求时，才能在 diagnostics.consumed_steer_refs 中填写对应 steer_id。"
        )
        lines.append(
            "- 如果当前执行状态里有 active_contract_revisions，你必须裁决它们是否改变目标、验收标准、范围或约束；"
            "把裁决写入 diagnostics.contract_revision_decisions。未裁决前不能宣布完成。"
        )
    if bool(task_lifecycle.get("request_task_run_allowed") is True):
        lines.append(
            "- 当目标需要真实交付物、持续执行、文件修改、命令验证、浏览器验证或失败恢复时，可以请求进入持续处理流程。"
        )
    elif "request_task_run" in allowed_actions:
        lines.append("- 本轮不允许开启持续处理流程；如目标需要长期执行或真实交付物，应询问用户或说明阻塞边界。")
    if "request_registered_engagement" in allowed_actions:
        lines.append("- 如果系统已注册的承接计划能精确覆盖当前目标，可以请求该计划；不要用它替代普通回答或临时任务判断。")
    if "tool_call" in allowed_actions:
        visible_count = int(tool_boundary.get("visible_tool_count") or 0)
        lines.append(f"- 工具只能从本轮上下文中实际可见的工具选择；当前可见工具数：{visible_count}。")
    if bool(tool_boundary.get("subagent_lifecycle_enabled") is True):
        lines.append("- 如需子 agent 协作，只能通过可见的子 agent 生命周期工具启动、通信、观察和关闭；主 agent 仍负责最终判断和收口。")
    if bool(planning.get("todo_required_when_task_run") is True):
        lines.append("- 进入持续处理流程后，需要维护步骤状态；步骤状态不能替代真实交付物或验收证据。")
    if bool(task_lifecycle.get("requires_completion_evidence") is True):
        lines.append("- 最终完成声明必须基于合同、真实观察、真实产物或验证证据。")
    if bool(task_lifecycle.get("artifact_evidence_required") is True):
        lines.append("- 如果合同要求 artifact，收口前必须确认 artifact 真实存在且路径可复核。")
    if bool(self_review.get("enabled") is True):
        checkpoints = [str(item) for item in list(self_review.get("checkpoints") or []) if str(item)]
        if checkpoints:
            lines.append("- 需要在关键检查点进行自我审查：" + "、".join(checkpoints) + "。")
        else:
            lines.append("- 收口前需要自我审查目标、边界、证据和未完成项。")
    if bool(step_summary.get("enabled") is True):
        detail = str(step_summary.get("detail") or "").strip()
        suffix = f"；摘要粒度：{detail}" if detail else ""
        lines.append("- 系统会记录任务步骤摘要，你的行动应能被步骤摘要和观察记录复核" + suffix + "。")
    permission_scope = str(permission_boundary.get("permission_scope") or "").strip()
    if permission_scope:
        lines.append(f"- 权限边界由本轮运行上下文决定；当前权限范围：{permission_scope}。")
    return "\n".join(lines) + "\n"


def _soul_instruction(soul_role_prompt: dict[str, Any]) -> str:
    content = str(soul_role_prompt.get("content") or "").strip()
    if not content:
        return ""
    return "以下是本次角色表达锚点；它不改变工具、任务或系统边界：\n" + content + "\n"


def _agent_prompt_instruction(agent_prompt_assembly: PromptAssemblyResult) -> str:
    content = str(agent_prompt_assembly.content or "").strip()
    if not content:
        return ""
    return "\n当前主 agent 工作角色：\n" + content + "\n"


def _prompt_contract_instruction(prompt_contract_assembly: PromptAssemblyResult) -> str:
    sections = [section for section in prompt_contract_assembly.sections if str(section.content or "").strip()]
    if not sections:
        return ""
    lines = ["当前任务执行要求："]
    for section in sections:
        title = str(section.title or "").strip()
        content = str(section.content or "").strip()
        if title:
            lines.append(f"{title}：\n{content}")
        else:
            lines.append(content)
    return "\n\n".join(lines) + "\n"


def _environment_instruction(
    environment_payload: dict[str, Any],
    *,
    environment_prompt_assembly: PromptAssemblyResult,
) -> str:
    content = str(environment_prompt_assembly.content or "").strip()
    environment_id = str(environment_payload.get("environment_id") or environment_payload.get("task_environment_id") or "").strip()
    title = str(environment_payload.get("title") or environment_id or "未命名任务环境").strip()
    description = str(environment_payload.get("description") or "").strip()
    identity_lines = ["当前任务环境："]
    if environment_id:
        identity_lines.append(f"- 环境：{title}（{environment_id}）。")
    else:
        identity_lines.append(f"- 环境：{title}。")
    if description:
        identity_lines.append(f"- 说明：{description}")
    storage = dict(environment_payload.get("storage_space") or {})
    storage_note = ""
    if storage:
        storage_note = (
            "当前环境的存储空间由系统配置："
            f"environment_storage_root={storage.get('environment_storage_root') or ''}；"
            f"artifact_root={storage.get('artifact_root') or ''}；"
            "你不能自行改变环境存储边界。\n"
        )
    detail_sections: list[str] = []
    if content:
        detail_sections.append(content)
    if storage_note:
        detail_sections.append(storage_note.rstrip())
    if not detail_sections:
        return "\n".join(identity_lines) + "\n"
    return "\n".join(identity_lines) + "\n当前任务环境说明：\n" + "\n".join(detail_sections) + "\n"


def _environment_stable_payload(environment_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(environment_payload or {})
    prompt_refs = [
        str(item.get("prompt_id") or "").strip()
        for item in list(payload.get("environment_prompts") or [])
        if isinstance(item, dict) and str(item.get("prompt_id") or "").strip()
    ]
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


def _environment_model_visible_payload(environment_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(environment_payload or {})
    group = dict(payload.get("group") or {})
    storage = dict(payload.get("storage_space") or {})
    sandbox = dict(payload.get("sandbox_policy") or {})
    execution = dict(payload.get("execution_policy") or {})
    file_management = dict(payload.get("file_management") or {})
    environment_boundary = dict(payload.get("environment_boundary") or {})
    boundary_contract = dict(environment_boundary.get("boundary_contract") or {})
    prompt_refs = [
        str(item.get("prompt_id") or "").strip()
        for item in list(payload.get("environment_prompts") or [])
        if isinstance(item, dict) and str(item.get("prompt_id") or "").strip()
    ]
    model_payload = {
        "environment_id": str(payload.get("environment_id") or payload.get("task_environment_id") or ""),
        "title": str(payload.get("title") or ""),
        "description": str(payload.get("description") or ""),
        "group_id": str(group.get("group_id") or ""),
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
        "environment_prompt_refs": prompt_refs,
        "boundary_contract": _drop_empty_payload(
            {
                "tool_authority": str(boundary_contract.get("tool_authority") or ""),
                "file_boundary_authority": str(boundary_contract.get("file_boundary_authority") or ""),
                "environment_prompts_source": str(boundary_contract.get("environment_prompts_source") or ""),
            }
        ),
        "policy_hash": _stable_json_hash(payload) if payload else "",
        "authority": "task_system.environment.model_visible_projection",
    }
    return _drop_empty_payload(model_payload)


def _stable_tool_catalog_payload(tool_payloads: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for item in tool_payloads:
        tool = dict(item or {})
        name = str(tool.get("tool_name") or tool.get("name") or "").strip()
        if not name:
            continue
        required_inputs = [str(value) for value in list(tool.get("required_inputs") or []) if str(value)]
        payload: dict[str, Any] = {
            "tool_name": name,
            "operation_id": str(tool.get("operation_id") or ""),
        }
        if required_inputs:
            payload["required_inputs"] = required_inputs
        owner_scope = str(tool.get("owner_scope") or "")
        if owner_scope and owner_scope != "none":
            payload["owner_scope"] = owner_scope
        if bool(tool.get("read_only") is True):
            payload["read_only"] = True
        input_schema = dict(tool.get("input_schema") or {}) if isinstance(tool.get("input_schema"), dict) else {}
        if input_schema:
            payload["input_schema_summary"] = _input_schema_summary(input_schema)
            payload["input_schema_ref"] = _short_hash(_stable_json_hash(input_schema))
        catalog.append(payload)
    return catalog


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
            "Skill 使用规则：如果某个候选 skill 能改善当前任务，请在 selected_skill_ids 中填写对应 skill_id。"
            "候选卡片不是完整技能说明；进入持续任务后，运行时会展开已选择 skill 的全文。"
            "不要把 skill_id、内部路由或工具名暴露给用户。"
        ),
    )


def _active_skill_instruction(*, base_dir: Path, assembly_payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    selected_skill_ids = [
        str(item).strip()
        for item in list(assembly_payload.get("selected_skill_ids") or [])
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


def _input_schema_summary(schema: dict[str, Any]) -> dict[str, Any]:
    properties = dict(schema.get("properties") or {})
    summarized_properties: dict[str, str] = {}
    for name, value in properties.items():
        if not isinstance(value, dict):
            continue
        field_type = str(value.get("type") or "any")
        if isinstance(value.get("items"), dict):
            item_payload = dict(value.get("items") or {})
            item_type = str(item_payload.get("type") or "any")
            field_type = f"{field_type}<{item_type}>"
        parts = [field_type]
        if value.get("format"):
            parts.append(f"format={value.get('format')}")
        if "enum" in value:
            enum_values = [str(item) for item in list(value.get("enum") or [])]
            if enum_values:
                parts.append("enum=" + "|".join(enum_values))
        if "default" in value:
            parts.append("default=" + json.dumps(value.get("default"), ensure_ascii=False, separators=(",", ":")))
        summarized_properties[str(name)] = " ".join(parts)
    summary: dict[str, Any] = {"properties": summarized_properties}
    schema_type = str(schema.get("type") or "object")
    if schema_type != "object":
        summary["type"] = schema_type
    required = [str(item) for item in list(schema.get("required") or []) if str(item)]
    if required:
        summary["required"] = required
    return summary


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


def _task_run_stable_payload(task_run: dict[str, Any], *, graph_runtime_projection: bool = False) -> dict[str, Any]:
    diagnostics = dict(task_run.get("diagnostics") or {})
    return {
        "task_run_id": str(task_run.get("task_run_id") or ""),
        "session_id": str(task_run.get("session_id") or ""),
        "task_id": str(task_run.get("task_id") or ""),
        "task_contract_ref": str(task_run.get("task_contract_ref") or ""),
        "owner_agent_seat_id": str(task_run.get("owner_agent_seat_id") or ""),
        "agent_id": str(task_run.get("agent_id") or ""),
        "agent_profile_id": str(task_run.get("agent_profile_id") or ""),
        "execution_runtime_kind": str(task_run.get("execution_runtime_kind") or ""),
        "diagnostics": _graph_task_run_diagnostics_model_visible(diagnostics) if graph_runtime_projection else _task_run_diagnostics_stable_payload(diagnostics),
        "authority": str(task_run.get("authority") or "orchestration.task_run"),
    }


def _task_run_diagnostics_stable_payload(diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: diagnostics.get(key)
        for key in (
            "source",
            "origin",
            "origin_kind",
            "origin_authority",
            "origin_ref",
            "parent_run_ref",
            "graph_run_id",
            "graph_harness_config_id",
            "graph_node_id",
            "graph_work_order_id",
            "node_id",
            "project_id",
            "runtime_scope",
        )
        if key in diagnostics
    }


def _graph_task_run_diagnostics_model_visible(diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: diagnostics.get(key)
        for key in (
            "source",
            "origin_kind",
            "origin_authority",
            "node_id",
            "project_id",
            "runtime_scope",
        )
        if key in diagnostics
    }


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
        artifact_refs = _model_visible_artifact_refs(item.get("artifact_refs"))
        memory_refs = _model_visible_ref_summaries(item.get("memory_refs"), limit=8)
        inputs.append(
            _drop_empty_payload(
                {
                    "slot": slot,
                    "label": label,
                    "packet_type": str(item.get("packet_type") or ""),
                    "content": _authorized_input_content(payload),
                    "payload": _authorized_input_payload(payload),
                    "artifact_refs": artifact_refs,
                    "memory_refs": memory_refs,
                    "authority": "harness.runtime.graph_node_context.authorized_input",
                }
            )
        )
    return inputs


def _authorized_input_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed: dict[str, Any] = {}
    for key in (
        "initial_inputs",
        "artifact_payloads",
        "handoff_summary",
        "summary",
        "content",
        "text",
        "title",
        "project_id",
        "graph_id",
    ):
        if key in payload:
            allowed[key] = payload.get(key)
    return _truncate_value(allowed, max_chars=30000) if allowed else {}


def _authorized_input_content(payload: dict[str, Any]) -> str:
    for key in ("content", "text", "handoff_summary", "summary"):
        text = str(payload.get(key) or "").strip()
        if text:
            return text[:30000]
    artifact_payloads = [dict(item) for item in list(payload.get("artifact_payloads") or []) if isinstance(item, dict)]
    parts = [str(item.get("content") or item.get("text") or "").strip() for item in artifact_payloads]
    joined = "\n\n".join(part for part in parts if part)
    return joined[:30000]


def _model_visible_artifact_refs(value: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in _bounded_dict_list(value, limit=8):
        refs.append(
            _drop_empty_payload(
                {
                    "path": str(item.get("path") or item.get("artifact_path") or item.get("src") or item.get("absolute_path") or ""),
                    "title": str(item.get("title") or item.get("label") or ""),
                    "summary": str(item.get("summary") or "")[:1000],
                }
            )
        )
    return refs


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
    for item in list(memory_contract.get("resolved_snapshots") or [])[:12]:
        if isinstance(item, dict):
            snapshots.append(_graph_visible_memory_snapshot(dict(item)))
    return snapshots


def _graph_visible_memory_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    records = snapshot.get("records") or snapshot.get("items") or snapshot.get("memories") or []
    visible_records: list[dict[str, Any]] = []
    for item in list(records)[:8]:
        if not isinstance(item, dict):
            continue
        visible_records.append(
            _drop_empty_payload(
                {
                    "title": str(item.get("title") or item.get("label") or ""),
                    "summary": str(item.get("summary") or "")[:1000],
                    "content": str(item.get("canonical_text") or item.get("content") or item.get("text") or "")[:4000],
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
    return _drop_empty_payload(
        {
            "variables": _truncate_value(allowed, max_chars=8000),
            "authority": "harness.runtime.graph_node_context.loop",
        }
    )


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


def _task_contract_stable_payload(contract: dict[str, Any]) -> dict[str, Any]:
    payload = dict(contract or {})
    graph_slot = _graph_slot_from_contract(payload)
    if graph_slot:
        return _drop_empty_payload(
            {
                "contract_id": "graph_node_contract",
                "contract_source": str(payload.get("contract_source") or "graph_node_work_order"),
                "task_environment_id": str(payload.get("task_environment_id") or ""),
                "origin": _graph_task_contract_origin_model_visible(dict(payload.get("origin") or {})),
                "graph_node_context": _graph_node_model_context_projection(graph_slot),
                "completion_criteria": _string_list(payload.get("completion_criteria")),
                "authority": "harness.runtime.graph_node_contract.model_visible",
            }
        )
    resource_requirements = dict(payload.get("resource_requirements") or {})
    if resource_requirements:
        payload["resource_requirements"] = _resource_requirements_stable_payload(resource_requirements)
    return payload


def _graph_task_contract_origin_model_visible(origin: dict[str, Any]) -> dict[str, Any]:
    return {
        "origin_kind": str(origin.get("origin_kind") or ""),
        "origin_authority": str(origin.get("origin_authority") or ""),
        "node_id": str(origin.get("node_id") or ""),
        "authority": "harness.runtime.graph_task_contract_origin.model_visible_projection",
    }


def _resource_requirements_stable_payload(resource_requirements: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_state": _graph_state_model_visible_payload(dict(resource_requirements.get("graph_state") or {})),
        "input_package": _input_package_stable_payload(dict(resource_requirements.get("input_package") or {})),
        "context_refs": dict(resource_requirements.get("context_refs") or {}),
        "artifact_space_ref": str(resource_requirements.get("artifact_space_ref") or ""),
        "memory_space_ref": str(resource_requirements.get("memory_space_ref") or ""),
        "file_access_table_refs": [str(item) for item in list(resource_requirements.get("file_access_table_refs") or []) if str(item)],
        "artifact_repository_targets": [
            dict(item) for item in list(resource_requirements.get("artifact_repository_targets") or []) if isinstance(item, dict)
        ],
        "memory_repository_targets": [
            dict(item) for item in list(resource_requirements.get("memory_repository_targets") or []) if isinstance(item, dict)
        ],
    }


def _graph_state_model_visible_payload(graph_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "completed_node_ids": [str(item) for item in list(graph_state.get("completed_node_ids") or []) if str(item)],
        "failed_node_ids": [str(item) for item in list(graph_state.get("failed_node_ids") or []) if str(item)],
        "upstream_node_ids": [str(item) for item in list(graph_state.get("upstream_node_ids") or []) if str(item)],
        "available_result_node_ids": [str(item) for item in list(graph_state.get("available_result_node_ids") or []) if str(item)],
        "authority": "harness.runtime.graph_state.model_visible_projection",
    }


def _input_package_stable_payload(input_package: dict[str, Any]) -> dict[str, Any]:
    payload = dict(input_package or {})
    payload["inbound_context"] = _inbound_context_stable_payload(payload.get("inbound_context"))
    payload.pop("upstream_results", None)
    payload.pop("upstream_handoff_packets", None)
    payload.pop("handoff_packets", None)
    if "task_environment" in payload:
        payload["task_environment"] = {
            "environment_id": str(dict(payload.get("task_environment") or {}).get("environment_id") or ""),
            "task_environment_id": str(dict(payload.get("task_environment") or {}).get("task_environment_id") or ""),
            "storage_space": dict(dict(payload.get("task_environment") or {}).get("storage_space") or {}),
            "authority": str(dict(payload.get("task_environment") or {}).get("authority") or ""),
        }
    for key in ("memory_view", "artifact_view", "file_view"):
        if isinstance(payload.get(key), dict):
            payload[key] = _bounded_view_payload(dict(payload.get(key) or {}))
    payload.pop("hidden_control_refs", None)
    return payload


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
        result["initial_inputs"] = _truncate_value(dict(payload.get("initial_inputs") or {}), max_chars=30000)
    if payload.get("graph_id"):
        result["graph_id"] = str(payload.get("graph_id") or "")
    if payload.get("project_id"):
        result["project_id"] = str(payload.get("project_id") or "")
    if "handoff_summary" in payload:
        result["handoff_summary"] = str(payload.get("handoff_summary") or "")[:1200]
    if isinstance(payload.get("artifact_refs"), list):
        result["artifact_refs"] = [str(item) for item in list(payload.get("artifact_refs") or [])[:12] if str(item)]
    if isinstance(payload.get("receipt_refs"), list):
        result["receipt_refs"] = _bounded_dict_list(payload.get("receipt_refs"), limit=12)
    if isinstance(payload.get("bounded_outputs"), dict):
        result["bounded_outputs"] = _truncate_value(dict(payload.get("bounded_outputs") or {}), max_chars=30000)
    if isinstance(payload.get("artifact_payloads"), list):
        result["artifact_payloads"] = [
            _bounded_artifact_payload(dict(item))
            for item in list(payload.get("artifact_payloads") or [])[:8]
            if isinstance(item, dict)
        ]
    return result


def _bounded_artifact_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_ref": str(item.get("artifact_ref") or ""),
        "content": str(item.get("content") or "")[:30000],
        "truncated": bool(item.get("truncated") is True),
        "max_chars": int(item.get("max_chars") or 30000),
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


def _artifact_root(environment_payload: dict[str, Any]) -> str:
    storage = dict(environment_payload.get("storage_space") or {})
    artifact_root = str(storage.get("artifact_root") or "").strip()
    if artifact_root:
        return artifact_root
    artifact_policy = dict(environment_payload.get("artifact_policy") or {})
    return str(artifact_policy.get("artifact_root") or "").strip()
