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
        mode_policy = {
            "mode": str(profile_payload.get("mode") or "standard"),
            "interaction_mode": str(profile_payload.get("interaction_mode") or "standard_mode"),
            "planning_policy": dict(profile_payload.get("planning_policy") or {}),
            "task_lifecycle_policy": dict(profile_payload.get("task_lifecycle_policy") or {}),
            "soul_prompt_policy": dict(profile_payload.get("soul_prompt_policy") or {}),
        }
        permission_policy = dict(profile_payload.get("permission_policy") or {"permission_scope": "action_request_only"})
        permission_policy.setdefault("permission_scope", str(permission_policy.get("scope") or "action_request_only"))
        prompt_pack_refs = tuple(str(item) for item in list(profile_payload.get("prompt_pack_refs") or []) if str(item))
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
            mode_policy=mode_policy,
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
            runtime_mode=str(profile_payload.get("mode") or "standard"),
        )
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="agent_profile",
            prompt_refs=_string_tuple(assembly_payload.get("agent_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            runtime_mode=str(profile_payload.get("mode") or "standard"),
        )
        environment_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=_string_tuple(assembly_payload.get("environment_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            runtime_mode=str(profile_payload.get("mode") or "standard"),
        )
        runtime_instruction = _runtime_projection_instruction(agent_visible_runtime_projection)
        environment_instruction = _environment_instruction(
            environment_payload,
            environment_prompt_assembly=environment_prompt_assembly,
        )
        agent_instruction = _agent_prompt_instruction(agent_prompt_assembly)
        soul_instruction = _soul_instruction(soul_role_prompt)
        system = _join_prompt_sections(
            prompt_assembly.content,
            soul_instruction,
            agent_instruction,
            environment_instruction,
            runtime_instruction,
        )
        stable_payload = {
            "schema": schema,
            "task_environment": _environment_stable_payload(environment_payload),
            "available_tools": _stable_tool_catalog_payload(tool_payloads),
            "tool_catalog_hash": _stable_json_hash([dict(item) for item in tool_payloads]),
        }
        dynamic_payload = {
            "operation_authorization": dict(assembly_payload.get("operation_authorization") or {}),
            "runtime_context": _runtime_context_payload(
                assembly_payload,
                agent_visible_runtime_projection=agent_visible_runtime_projection,
            ),
        }
        volatile_payload = {
            "runtime_envelope": envelope.to_dict(),
            "turn_id": turn_id,
            "history": [dict(item) for item in list(history or [])],
            "user_message": str(user_message or ""),
        }
        packet_id = f"rtpacket:{turn_id}:turn_action:1"
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
                ),
                _message_spec(
                    role="user",
                    content=_packet_payload_content("Turn action current request", volatile_payload),
                    kind="volatile_user",
                    source_ref="turn_action_current_request",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                ),
            ],
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
        packet = RuntimeInvocationPacket(
            packet_id=packet_id,
            envelope_ref=envelope.envelope_id,
            invocation_kind="turn_action",
            invocation_index=1,
            session_id=session_id,
            turn_id=turn_id,
            model_messages=model_messages,
            segment_plan=segment_plan.to_dict(),
            system_instructions=system,
            agent_role_prompt="你是当前 turn 的主 agent，负责决定下一步动作。",
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
            available_tools=tool_payloads,
            available_modes=("respond", "ask_user", "tool_call", "request_task_run", "request_registered_engagement", "block"),
            output_contract={"schema": schema, "format": "json_object"},
            hidden_control_refs={"agent_invocation_id": agent_invocation_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
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
        mode_policy = {
            "mode": str(profile_payload.get("mode") or "professional"),
            "interaction_mode": str(profile_payload.get("interaction_mode") or "task_execution"),
            "planning_policy": dict(profile_payload.get("planning_policy") or {}),
            "task_lifecycle_policy": dict(profile_payload.get("task_lifecycle_policy") or {}),
            "self_review_policy": dict(profile_payload.get("self_review_policy") or {}),
        }
        permission_policy = dict(profile_payload.get("permission_policy") or {"permission_scope": "task_run_execution"})
        permission_policy.setdefault("permission_scope", str(permission_policy.get("scope") or "task_run_execution"))
        prompt_pack_refs = tuple(str(item) for item in list(profile_payload.get("prompt_pack_refs") or []) if str(item))
        tool_payloads = tuple(dict(item) for item in list(available_tools or []) if isinstance(item, dict))
        agent_visible_runtime_projection = _agent_visible_runtime_projection(
            invocation_kind="task_execution",
            allowed_action_types=("respond", "ask_user", "tool_call", "block"),
            profile_payload=profile_payload,
            environment_payload=environment_payload,
            operation_authorization=dict(assembly_payload.get("operation_authorization") or {}),
            available_tools=tool_payloads,
        )
        envelope = RuntimeEnvelope(
            envelope_id=f"rtenv:{task_run_id}:task_execution:{invocation_index}",
            scope_kind="task_run",
            session_id=session_id,
            task_run_id=task_run_id,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            mode_policy=mode_policy,
            sandbox_policy=dict(environment_payload.get("sandbox_policy") or {}),
            file_policy={
                "file_management": dict(environment_payload.get("file_management") or {}),
                "file_access_tables": list(environment_payload.get("file_access_tables") or []),
            },
            artifact_policy=dict(environment_payload.get("artifact_policy") or {}),
            permission_policy=permission_policy,
            prompt_policy={"invocation_kind": "task_execution"},
            output_policy={"format": "model_action_request_json"},
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
        prompt_assembly = self._assemble_prompt_pack(
            invocation_kind="task_execution",
            prompt_pack_refs=prompt_pack_refs,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            runtime_mode=str(profile_payload.get("mode") or "professional"),
            task_prompt_contract=task_prompt_contract,
            graph_node_prompt_contract=graph_node_prompt_contract,
        )
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="agent_profile",
            prompt_refs=_string_tuple(assembly_payload.get("agent_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            runtime_mode=str(profile_payload.get("mode") or "professional"),
        )
        environment_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=_string_tuple(assembly_payload.get("environment_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            runtime_mode=str(profile_payload.get("mode") or "professional"),
        )
        artifact_note = f"当前建议 artifact_root 是 {artifact_root}。" if artifact_root else ""
        runtime_instruction = _join_prompt_sections(
            artifact_note,
            _runtime_projection_instruction(agent_visible_runtime_projection),
        )
        environment_instruction = _environment_instruction(
            environment_payload,
            environment_prompt_assembly=environment_prompt_assembly,
        )
        agent_instruction = _agent_prompt_instruction(agent_prompt_assembly)
        system = _join_prompt_sections(
            prompt_assembly.content,
            agent_instruction,
            environment_instruction,
            runtime_instruction,
        )
        stable_payload = {
            "schema": schema,
            "task_run": _task_run_stable_payload(task_run),
            "task_contract": _task_contract_stable_payload(contract),
            "task_environment": _environment_stable_payload(environment_payload),
            "available_tools": _stable_tool_catalog_payload(tool_payloads),
            "tool_catalog_hash": _stable_json_hash([dict(item) for item in tool_payloads]),
        }
        dynamic_payload = {
            "operation_authorization": dict(assembly_payload.get("operation_authorization") or {}),
            "runtime_context": _runtime_context_payload(
                assembly_payload,
                agent_visible_runtime_projection=agent_visible_runtime_projection,
            ),
        }
        volatile_payload = {
            "runtime_envelope": envelope.to_dict(),
            "task_run_state": _task_run_volatile_payload(task_run),
            "execution_state": dict(execution_state or {}),
            "observations": [dict(item) for item in list(observations or [])],
        }
        packet_id = f"rtpacket:{task_run_id}:task_execution:{invocation_index}"
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
                    content=agent_instruction,
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
                        _packet_payload_content("Task execution dynamic runtime", dynamic_payload),
                    ),
                    kind="dynamic_projection",
                    source_ref="agent_visible_runtime_projection",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                ),
                _message_spec(
                    role="user",
                    content=_packet_payload_content("Task execution current state", volatile_payload),
                    kind="volatile_task_state",
                    source_ref="task_execution_current_state",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                ),
            ],
        )
        prompt_manifest = build_runtime_prompt_manifest(
            invocation_kind="task_execution",
            assembly=_merge_prompt_assemblies(
                prompt_assembly,
                agent_prompt_assembly,
                environment_prompt_assembly,
                invocation_kind="task_execution",
            ),
            packet_id=packet_id,
            dynamic_projection_refs=("agent_visible_runtime_projection", "operation_authorization"),
            volatile_state_refs=("runtime_envelope", "execution_state", "observations"),
        ).to_dict()
        prompt_manifest["segment_plan_ref"] = segment_plan.segment_plan_id
        packet = RuntimeInvocationPacket(
            packet_id=packet_id,
            envelope_ref=envelope.envelope_id,
            invocation_kind="task_execution",
            invocation_index=invocation_index,
            session_id=session_id,
            task_run_id=task_run_id,
            model_messages=model_messages,
            segment_plan=segment_plan.to_dict(),
            system_instructions=system,
            agent_role_prompt="你是正式 TaskRun 的执行 agent，负责真实交付合同产物。",
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
            available_tools=tool_payloads,
            available_modes=("respond", "ask_user", "tool_call", "block"),
            observation_refs=tuple(str(item.get("observation_id") or "") for item in observations if item.get("observation_id")),
            output_contract={"schema": schema, "format": "json_object"},
            hidden_control_refs={"task_run_id": task_run_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
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
        mode_policy = {
            "mode": str(profile_payload.get("mode") or "standard"),
            "interaction_mode": str(profile_payload.get("interaction_mode") or "standard_mode"),
            "planning_policy": dict(profile_payload.get("planning_policy") or {}),
            "task_lifecycle_policy": dict(profile_payload.get("task_lifecycle_policy") or {}),
            "soul_prompt_policy": dict(profile_payload.get("soul_prompt_policy") or {}),
        }
        permission_policy = dict(profile_payload.get("permission_policy") or {"permission_scope": "bounded_read_observation"})
        permission_policy.setdefault("permission_scope", str(permission_policy.get("scope") or "bounded_read_observation"))
        prompt_pack_refs = tuple(str(item) for item in list(profile_payload.get("prompt_pack_refs") or []) if str(item))
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
            mode_policy=mode_policy,
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
            runtime_mode=str(profile_payload.get("mode") or "standard"),
        )
        agent_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="agent_profile",
            prompt_refs=_string_tuple(assembly_payload.get("agent_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            runtime_mode=str(profile_payload.get("mode") or "standard"),
        )
        environment_prompt_assembly = self._assemble_prompt_refs(
            invocation_kind="environment",
            prompt_refs=_string_tuple(assembly_payload.get("environment_prompt_refs")),
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=task_environment_ref,
            runtime_mode=str(profile_payload.get("mode") or "standard"),
        )
        runtime_instruction = _runtime_projection_instruction(agent_visible_runtime_projection)
        environment_instruction = _environment_instruction(
            environment_payload,
            environment_prompt_assembly=environment_prompt_assembly,
        )
        agent_instruction = _agent_prompt_instruction(agent_prompt_assembly)
        soul_instruction = _soul_instruction(soul_role_prompt)
        system = _join_prompt_sections(
            prompt_assembly.content,
            soul_instruction,
            agent_instruction,
            environment_instruction,
            runtime_instruction,
        )
        stable_payload = {
            "schema": schema,
            "task_environment": _environment_stable_payload(environment_payload),
            "available_tools": _stable_tool_catalog_payload(tool_payloads),
            "tool_catalog_hash": _stable_json_hash([dict(item) for item in tool_payloads]),
        }
        dynamic_payload = {
            "operation_authorization": dict(assembly_payload.get("operation_authorization") or {}),
            "runtime_context": _runtime_context_payload(
                assembly_payload,
                agent_visible_runtime_projection=agent_visible_runtime_projection,
            ),
        }
        volatile_payload = {
            "runtime_envelope": envelope.to_dict(),
            "turn_id": turn_id,
            "history": [dict(item) for item in list(history or [])],
            "user_message": str(user_message or ""),
            "observations": [dict(item) for item in list(observations or [])],
        }
        packet_id = f"rtpacket:{turn_id}:tool_observation_followup:{len(observations) + 1}"
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
                ),
                _message_spec(
                    role="user",
                    content=_packet_payload_content("Observation followup current request", volatile_payload),
                    kind="tool_observations",
                    source_ref="observation_followup_current_request",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="ref_only",
                ),
            ],
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
        packet = RuntimeInvocationPacket(
            packet_id=packet_id,
            envelope_ref=envelope.envelope_id,
            invocation_kind="tool_observation_followup",
            invocation_index=len(observations) + 1,
            session_id=session_id,
            turn_id=turn_id,
            model_messages=model_messages,
            segment_plan=segment_plan.to_dict(),
            system_instructions=system,
            agent_role_prompt="你是当前 turn 的主 agent，负责基于观察继续行动。",
            prompt_pack_refs=prompt_assembly.prompt_pack_refs,
            available_tools=tool_payloads,
            available_modes=("respond", "ask_user", "tool_call", "request_task_run", "request_registered_engagement", "block"),
            observation_refs=tuple(str(item.get("observation_id") or "") for item in observations if item.get("observation_id")),
            output_contract={"schema": schema, "format": "json_object"},
            hidden_control_refs={"agent_invocation_id": agent_invocation_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
            diagnostics={
                "prompt_manifest": prompt_manifest,
                "segment_plan": segment_plan.to_dict(),
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
        runtime_mode: str,
        task_prompt_contract: dict[str, Any] | None = None,
        graph_node_prompt_contract: dict[str, Any] | None = None,
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
                runtime_mode=runtime_mode,
                task_prompt_contract=dict(task_prompt_contract or {}),
                graph_node_prompt_contract=dict(graph_node_prompt_contract or {}),
            )
        )

    def _bind_assembly_base_dir(self, assembly_payload: dict[str, Any]) -> None:
        backend_dir = str(assembly_payload.get("backend_dir") or "").strip()
        if backend_dir:
            self.base_dir = Path(backend_dir)

    def _assemble_prompt_refs(
        self,
        *,
        invocation_kind: str,
        prompt_refs: tuple[str, ...],
        agent_profile_ref: str,
        task_environment_ref: str,
        runtime_mode: str,
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
                runtime_mode=runtime_mode,
            )
        )


def model_action_request_schema(turn_id: str) -> dict[str, Any]:
    del turn_id
    return {
        "authority": "harness.loop.model_action_request",
        "action_type": "respond|ask_user|tool_call|request_task_run|request_registered_engagement|block",
        "final_answer": "",
        "user_question": "",
        "blocking_reason": "",
        "tool_call": {"tool_name": "", "args": {}},
        "task_contract_seed": {
            "user_visible_goal": "面向用户的正式任务目标，必填",
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
        "final_answer": "",
        "user_question": "",
        "blocking_reason": "",
        "tool_call": {"tool_name": "", "args": {}},
        "task_contract_seed": {},
        "completion_contract": {},
        "permission_request": {},
        "diagnostics": {
            "artifacts": [
                {"path": "真实交付物路径", "kind": "artifact kind", "summary": "产物说明"}
            ],
            "verification": "简短说明自审和验收结果",
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
) -> tuple[list[dict[str, str]], Any]:
    clean_specs = [
        dict(spec)
        for spec in list(specs or [])
        if str(dict(spec).get("content") or "").strip()
    ]
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
    )
    return model_messages, segment_plan


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


def _task_prompt_contract_from_runtime(
    *,
    task_run: dict[str, Any],
    contract: dict[str, Any],
    assembly_payload: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(contract.get("prompt_contract") or {})
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
        dict(contract.get("graph_node_prompt_contract") or {})
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
            "tools_are_limited_to_runtime_packet": True,
            "subagent_delegation_enabled": bool(subagent.get("enabled") is True),
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
    if bool(task_lifecycle.get("request_task_run_allowed") is True):
        lines.append(
            "- 当目标需要真实交付物、持续执行、文件修改、命令验证、浏览器验证或失败恢复时，可以请求正式 TaskRun。"
        )
    elif "request_task_run" in allowed_actions:
        lines.append("- 本次装配不允许开启正式 TaskRun；如任务需要长期执行或真实交付物，应询问用户或说明阻塞边界。")
    if "request_registered_engagement" in allowed_actions:
        lines.append("- 如果系统已注册的承接计划能精确覆盖当前目标，可以请求该计划；不要用它替代普通回答或临时任务判断。")
    if "tool_call" in allowed_actions:
        visible_count = int(tool_boundary.get("visible_tool_count") or 0)
        lines.append(f"- 工具只能从 runtime packet 中实际可见的工具选择；当前可见工具数：{visible_count}。")
    if bool(tool_boundary.get("subagent_delegation_enabled") is True):
        lines.append("- 如需委派子 agent，只能在可见委派工具和授权范围内进行；主 agent 仍负责最终判断和收口。")
    if bool(planning.get("todo_required_when_task_run") is True):
        lines.append("- 进入正式任务生命周期后，需要维护步骤状态；步骤状态不能替代真实交付物或验收证据。")
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
        lines.append(f"- 权限边界由本次 runtime 装配决定；当前权限范围：{permission_scope}。")
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


def _environment_instruction(
    environment_payload: dict[str, Any],
    *,
    environment_prompt_assembly: PromptAssemblyResult,
) -> str:
    content = str(environment_prompt_assembly.content or "").strip()
    storage = dict(environment_payload.get("storage_space") or {})
    storage_note = ""
    if storage:
        storage_note = (
            "当前环境的存储空间由系统配置："
            f"environment_storage_root={storage.get('environment_storage_root') or ''}；"
            f"artifact_root={storage.get('artifact_root') or ''}；"
            "你不能自行改变环境存储边界。\n"
        )
    if not content and not storage_note:
        return ""
    return "当前任务环境说明：\n" + (content + "\n" if content else "") + storage_note


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


def _stable_tool_catalog_payload(tool_payloads: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for item in tool_payloads:
        tool = dict(item or {})
        name = str(tool.get("tool_name") or tool.get("name") or "").strip()
        if not name:
            continue
        payload: dict[str, Any] = {
            "tool_name": name,
            "operation_id": str(tool.get("operation_id") or ""),
            "display_name": str(tool.get("display_name") or name),
            "required_inputs": [str(value) for value in list(tool.get("required_inputs") or []) if str(value)],
            "optional_inputs": [str(value) for value in list(tool.get("optional_inputs") or []) if str(value)],
            "owner_scope": str(tool.get("owner_scope") or "none"),
            "read_only": bool(tool.get("read_only") is True),
        }
        description = str(tool.get("description") or "").strip()
        if description:
            payload["description"] = description
        input_schema = dict(tool.get("input_schema") or {}) if isinstance(tool.get("input_schema"), dict) else {}
        if input_schema:
            payload["input_schema_summary"] = _input_schema_summary(input_schema)
            payload["input_schema_hash"] = _stable_json_hash(input_schema)
        catalog.append(payload)
    return catalog


def _input_schema_summary(schema: dict[str, Any]) -> dict[str, Any]:
    properties = dict(schema.get("properties") or {})
    summarized_properties: dict[str, Any] = {}
    for name, value in properties.items():
        if not isinstance(value, dict):
            continue
        field: dict[str, Any] = {}
        for key in ("type", "format", "enum", "default"):
            if key in value:
                field[key] = value.get(key)
        if isinstance(value.get("items"), dict):
            item_payload = dict(value.get("items") or {})
            field["items"] = {key: item_payload.get(key) for key in ("type", "format", "enum") if key in item_payload}
        description = str(value.get("description") or "").strip()
        if description:
            field["description"] = description
        summarized_properties[str(name)] = field
    return {
        "type": str(schema.get("type") or "object"),
        "required": [str(item) for item in list(schema.get("required") or []) if str(item)],
        "properties": summarized_properties,
    }


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _task_run_stable_payload(task_run: dict[str, Any]) -> dict[str, Any]:
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
        "diagnostics": _task_run_diagnostics_stable_payload(diagnostics),
        "authority": str(task_run.get("authority") or "orchestration.task_run"),
    }


def _task_run_volatile_payload(task_run: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(task_run.get("diagnostics") or {})
    return {
        "task_run_id": str(task_run.get("task_run_id") or ""),
        "status": str(task_run.get("status") or ""),
        "terminal_reason": str(task_run.get("terminal_reason") or ""),
        "started_at": task_run.get("started_at"),
        "updated_at": task_run.get("updated_at"),
        "completed_at": task_run.get("completed_at"),
        "current_step_index": task_run.get("current_step_index"),
        "diagnostics": {
            key: diagnostics.get(key)
            for key in (
                "executor_status",
                "recoverable_error",
                "recovery_action",
                "last_error",
                "last_observation_id",
                "last_model_action",
            )
            if key in diagnostics
        },
        "authority": "orchestration.task_run.volatile_state",
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


def _task_contract_stable_payload(contract: dict[str, Any]) -> dict[str, Any]:
    payload = dict(contract or {})
    resource_requirements = dict(payload.get("resource_requirements") or {})
    if resource_requirements:
        payload["resource_requirements"] = _resource_requirements_stable_payload(resource_requirements)
    return payload


def _resource_requirements_stable_payload(resource_requirements: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_state": dict(resource_requirements.get("graph_state") or {}),
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


def _input_package_stable_payload(input_package: dict[str, Any]) -> dict[str, Any]:
    payload = dict(input_package or {})
    payload.pop("inbound_context", None)
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


def _artifact_root(environment_payload: dict[str, Any]) -> str:
    storage = dict(environment_payload.get("storage_space") or {})
    artifact_root = str(storage.get("artifact_root") or "").strip()
    if artifact_root:
        return artifact_root
    artifact_policy = dict(environment_payload.get("artifact_policy") or {})
    return str(artifact_policy.get("artifact_root") or "").strip()


def _runtime_context_payload(
    assembly_payload: dict[str, Any],
    *,
    agent_visible_runtime_projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = dict(assembly_payload.get("profile") or {})
    environment = dict(assembly_payload.get("task_environment") or {})
    payload = {
        "assembly_id": str(assembly_payload.get("assembly_id") or ""),
        "agent_profile_ref": str(assembly_payload.get("agent_profile_ref") or ""),
        "mode": str(profile.get("mode") or ""),
        "interaction_mode": str(profile.get("interaction_mode") or ""),
        "task_lifecycle_policy": dict(profile.get("task_lifecycle_policy") or {}),
        "planning_policy": dict(profile.get("planning_policy") or {}),
        "self_review_policy": dict(profile.get("self_review_policy") or {}),
        "permission_policy": dict(profile.get("permission_policy") or {}),
        "task_environment_id": str(environment.get("environment_id") or ""),
        "storage_space": dict(environment.get("storage_space") or {}),
        "agent_prompt_refs": _string_tuple(assembly_payload.get("agent_prompt_refs")),
        "environment_prompt_refs": _string_tuple(assembly_payload.get("environment_prompt_refs")),
        "environment_boundary": {
            "authority": str(dict(environment.get("environment_boundary") or {}).get("authority") or ""),
            "environment_prompts_source": str(
                dict(dict(environment.get("environment_boundary") or {}).get("boundary_contract") or {}).get(
                    "environment_prompts_source"
                )
                or ""
            ),
            "tool_authority": str(
                dict(dict(environment.get("environment_boundary") or {}).get("boundary_contract") or {}).get("tool_authority")
                or ""
            ),
            "file_boundary_authority": str(
                dict(dict(environment.get("environment_boundary") or {}).get("boundary_contract") or {}).get(
                    "file_boundary_authority"
                )
                or ""
            ),
        },
        "allowed_operation_count": len(list(dict(assembly_payload.get("operation_authorization") or {}).get("allowed_operations") or [])),
    }
    if agent_visible_runtime_projection:
        payload["agent_visible_runtime_projection"] = dict(agent_visible_runtime_projection)
    return payload
