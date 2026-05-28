from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .envelope import RuntimeEnvelope
from .invocation_packet import RuntimeInvocationPacket


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
        profile_payload = dict(assembly_payload.get("profile") or {})
        environment_payload = dict(assembly_payload.get("task_environment") or {})
        work_role_prompt = str(assembly_payload.get("work_role_prompt") or "").strip()
        mode_policy = {
            "mode": str(profile_payload.get("mode") or "standard"),
            "interaction_mode": str(profile_payload.get("interaction_mode") or "standard_mode"),
            "runtime_lane": str(profile_payload.get("runtime_lane") or "standard_task"),
            "planning_policy": dict(profile_payload.get("planning_policy") or {}),
            "task_lifecycle_policy": dict(profile_payload.get("task_lifecycle_policy") or {}),
            "soul_prompt_policy": dict(profile_payload.get("soul_prompt_policy") or {}),
        }
        permission_policy = dict(profile_payload.get("permission_policy") or {"permission_scope": "action_request_only"})
        permission_policy.setdefault("permission_scope", str(permission_policy.get("scope") or "action_request_only"))
        prompt_pack_refs = tuple(str(item) for item in list(profile_payload.get("prompt_pack_refs") or []) if str(item))
        soul_role_prompt = dict(assembly_payload.get("soul_role_prompt") or {})
        tool_payloads = tuple(dict(item) for item in list(available_tools or []) if isinstance(item, dict))
        envelope = RuntimeEnvelope(
            envelope_id=f"rtenv:{turn_id}:turn",
            scope_kind="turn",
            session_id=session_id,
            turn_id=turn_id,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(environment_payload.get("environment_id") or "env.general.workspace"),
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
        system = (
            "你是当前 turn 的主 agent。系统已经为你装配本次调用的运行时边界、"
            "可用动作和输出契约；你负责理解用户请求并选择下一步动作。\n"
            "只输出一个合法 JSON 对象，不要 Markdown，不要暴露隐藏推理。\n"
            "如果可以直接回答，action_type=respond，并填写 final_answer。\n"
            "如果缺少必要信息，action_type=ask_user，并填写 user_question。\n"
            "如果只需要一次只读观察，action_type=tool_call，并填写 tool_call。tool_call 必须包含 tool_name 和 args。\n"
            "如果必须进入正式任务生命周期，action_type=request_task_run，并严格按 schema.task_contract_seed 填写任务合同；"
            "合同必须包含 user_visible_goal、task_run_goal，并且至少包含 completion_criteria、required_artifacts、required_verifications 之一。\n"
            "如果请求越界或不能执行，action_type=block，并填写 blocking_reason。\n"
            + _mode_instruction(mode_policy)
            + _environment_instruction(environment_payload)
            + _soul_instruction(soul_role_prompt)
            + "request_id 和 turn_id 可省略；如果输出 turn_id，必须与本次 runtime_envelope.turn_id 完全一致。\n"
            "不要输出意图分类字段、任务类型字段、task_run_id 或其他内部控制协议。"
            + _work_role_instruction(work_role_prompt)
        )
        user_payload = {
            "schema": schema,
            "runtime_envelope": envelope.to_dict(),
            "task_environment": environment_payload,
            "turn_id": turn_id,
            "available_tools": [dict(item) for item in tool_payloads],
            "runtime_context": _runtime_context_payload(assembly_payload),
            "history": [dict(item) for item in list(history or [])],
            "user_message": str(user_message or ""),
        }
        packet = RuntimeInvocationPacket(
            packet_id=f"rtpacket:{turn_id}:turn_action:1",
            envelope_ref=envelope.envelope_id,
            invocation_kind="turn_action",
            invocation_index=1,
            session_id=session_id,
            turn_id=turn_id,
            model_messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            system_instructions=system,
            agent_role_prompt="你是当前 turn 的主 agent，负责决定下一步动作。",
            prompt_pack_refs=(*prompt_pack_refs, "runtime.prompt.turn_action.v1") if prompt_pack_refs else ("runtime.prompt.turn_action.v1",),
            available_tools=tool_payloads,
            available_modes=("respond", "ask_user", "tool_call", "request_task_run", "block"),
            output_contract={"schema": schema, "format": "json_object"},
            hidden_control_refs={"agent_invocation_id": agent_invocation_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
        )
        return RuntimeCompilationResult(envelope=envelope, packet=packet)

    def compile_task_execution_packet(
        self,
        *,
        session_id: str,
        task_run: dict[str, Any],
        contract: dict[str, Any],
        observations: list[dict[str, Any]],
        agent_profile_ref: str = "main_interactive_agent",
        model_selection: dict[str, Any] | None = None,
        available_tools: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
        runtime_assembly: Any | None = None,
        invocation_index: int = 1,
    ) -> RuntimeCompilationResult:
        assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
        profile_payload = dict(assembly_payload.get("profile") or {})
        environment_payload = dict(assembly_payload.get("task_environment") or {})
        work_role_prompt = str(assembly_payload.get("work_role_prompt") or "").strip()
        task_run_id = str(task_run.get("task_run_id") or "")
        mode_policy = {
            "mode": str(profile_payload.get("mode") or "professional"),
            "interaction_mode": str(profile_payload.get("interaction_mode") or "task_execution"),
            "runtime_lane": str(profile_payload.get("runtime_lane") or "single_agent_task"),
            "planning_policy": dict(profile_payload.get("planning_policy") or {}),
            "task_lifecycle_policy": dict(profile_payload.get("task_lifecycle_policy") or {}),
            "self_review_policy": dict(profile_payload.get("self_review_policy") or {}),
        }
        permission_policy = dict(profile_payload.get("permission_policy") or {"permission_scope": "task_run_execution"})
        permission_policy.setdefault("permission_scope", str(permission_policy.get("scope") or "task_run_execution"))
        prompt_pack_refs = tuple(str(item) for item in list(profile_payload.get("prompt_pack_refs") or []) if str(item))
        tool_payloads = tuple(dict(item) for item in list(available_tools or []) if isinstance(item, dict))
        envelope = RuntimeEnvelope(
            envelope_id=f"rtenv:{task_run_id}:task_execution:{invocation_index}",
            scope_kind="task_run",
            session_id=session_id,
            task_run_id=task_run_id,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(environment_payload.get("environment_id") or "env.general.workspace"),
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
        system = (
            "你是正式 TaskRun 的执行 agent。你已经不在普通对话轮次中，而是在执行一个已建立合同的长任务。\n"
            "你的职责是按合同真实推进工作：必要时调用工具创建或修改交付物，记录可验证证据，最后只在合同满足时给出完成答复。\n"
            "只输出一个合法 JSON 对象，不要 Markdown 包裹，不要暴露隐藏推理。\n"
            "如果需要执行一步工作，action_type=tool_call，并填写 tool_call.tool_name 与 tool_call.args。\n"
            "如果合同已经满足，action_type=respond，final_answer 必须总结完成情况，并在 diagnostics.artifacts 中列出真实产物路径。\n"
            "如果缺少用户决策，action_type=ask_user。\n"
            "如果任务无法继续，action_type=block，并说明 blocking_reason。\n"
            "不要再次 request_task_run，不要输出 task_run_id 作为用户可见内容。\n"
            "写入交付物时优先使用 write_file；路径必须落在任务环境允许的 artifact/storage 范围内。"
            + (f" 当前建议 artifact_root 是 {artifact_root}。" if artifact_root else "")
            + "\n"
            "完成前必须自我审查合同中的 completion_criteria、required_artifacts、required_verifications。\n"
            + _environment_instruction(environment_payload)
            + _work_role_instruction(work_role_prompt)
        )
        user_payload = {
            "schema": schema,
            "runtime_envelope": envelope.to_dict(),
            "task_run": dict(task_run),
            "task_contract": dict(contract),
            "task_environment": environment_payload,
            "available_tools": [dict(item) for item in tool_payloads],
            "runtime_context": _runtime_context_payload(assembly_payload),
            "observations": [dict(item) for item in list(observations or [])],
        }
        packet = RuntimeInvocationPacket(
            packet_id=f"rtpacket:{task_run_id}:task_execution:{invocation_index}",
            envelope_ref=envelope.envelope_id,
            invocation_kind="task_execution",
            invocation_index=invocation_index,
            session_id=session_id,
            task_run_id=task_run_id,
            model_messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            system_instructions=system,
            agent_role_prompt="你是正式 TaskRun 的执行 agent，负责真实交付合同产物。",
            prompt_pack_refs=(*prompt_pack_refs, "runtime.prompt.task_execution.v1") if prompt_pack_refs else ("runtime.prompt.task_execution.v1",),
            available_tools=tool_payloads,
            available_modes=("respond", "ask_user", "tool_call", "block"),
            observation_refs=tuple(str(item.get("observation_id") or "") for item in observations if item.get("observation_id")),
            output_contract={"schema": schema, "format": "json_object"},
            hidden_control_refs={"task_run_id": task_run_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
        )
        return RuntimeCompilationResult(envelope=envelope, packet=packet)

    def compile_direct_answer_packet(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent_invocation_id: str,
        user_message: str,
        history: list[dict[str, Any]],
        agent_profile_ref: str = "main_interactive_agent",
        model_selection: dict[str, Any] | None = None,
    ) -> RuntimeCompilationResult:
        envelope = RuntimeEnvelope(
            envelope_id=f"rtenv:{turn_id}:direct_answer",
            scope_kind="turn",
            session_id=session_id,
            turn_id=turn_id,
            agent_profile_ref=agent_profile_ref,
            mode_policy={"mode": "direct_answer"},
            permission_policy={"permission_scope": "no_tool_side_effects"},
            prompt_policy={"invocation_kind": "direct_answer"},
            output_policy={"format": "natural_final_answer"},
            diagnostics={
                "agent_invocation_id": agent_invocation_id,
                "model_selection": dict(model_selection or {}),
            },
        )
        system = (
            "你是当前对话轮次的回答 agent。你只回答用户当前问题。\n"
            "你没有执行工具、没有读取文件、没有修改工作区，也没有创建任务；不要声称已经做过这些事情。\n"
            "回答必须自然、简洁、直接，不要输出内部运行 ID、控制协议或隐藏推理。"
        )
        packet = RuntimeInvocationPacket(
            packet_id=f"rtpacket:{turn_id}:direct_answer:1",
            envelope_ref=envelope.envelope_id,
            invocation_kind="direct_answer",
            invocation_index=1,
            session_id=session_id,
            turn_id=turn_id,
            model_messages=[
                {"role": "system", "content": system},
                *[dict(message) for message in list(history or [])],
                {"role": "user", "content": str(user_message or "")},
            ],
            system_instructions=system,
            agent_role_prompt="你是当前对话轮次的回答 agent。",
            prompt_pack_refs=("runtime.prompt.direct_answer.v1",),
            available_modes=("respond",),
            permission_snapshot={"tools_enabled": False, "task_run_enabled": False},
            output_contract={"format": "natural_final_answer"},
            hidden_control_refs={"agent_invocation_id": agent_invocation_id},
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
        profile_payload = dict(assembly_payload.get("profile") or {})
        environment_payload = dict(assembly_payload.get("task_environment") or {})
        work_role_prompt = str(assembly_payload.get("work_role_prompt") or "").strip()
        mode_policy = {
            "mode": str(profile_payload.get("mode") or "standard"),
            "interaction_mode": str(profile_payload.get("interaction_mode") or "standard_mode"),
            "runtime_lane": str(profile_payload.get("runtime_lane") or "standard_task"),
            "planning_policy": dict(profile_payload.get("planning_policy") or {}),
            "task_lifecycle_policy": dict(profile_payload.get("task_lifecycle_policy") or {}),
            "soul_prompt_policy": dict(profile_payload.get("soul_prompt_policy") or {}),
        }
        permission_policy = dict(profile_payload.get("permission_policy") or {"permission_scope": "bounded_read_observation"})
        permission_policy.setdefault("permission_scope", str(permission_policy.get("scope") or "bounded_read_observation"))
        prompt_pack_refs = tuple(str(item) for item in list(profile_payload.get("prompt_pack_refs") or []) if str(item))
        soul_role_prompt = dict(assembly_payload.get("soul_role_prompt") or {})
        tool_payloads = tuple(dict(item) for item in list(available_tools or []) if isinstance(item, dict))
        envelope = RuntimeEnvelope(
            envelope_id=f"rtenv:{turn_id}:observation_followup",
            scope_kind="turn",
            session_id=session_id,
            turn_id=turn_id,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref=str(environment_payload.get("environment_id") or "env.general.workspace"),
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
        system = (
            "你是当前 turn 的主 agent。你刚收到系统执行的只读观察结果。\n"
            "请基于用户请求、历史和观察结果继续判断下一步。只输出一个合法 JSON 对象。\n"
            "如果 observation 带有 error，必须把它当作真实失败处理：可以改用其他只读观察、请求正式任务、询问用户或阻止，不能声称该观察成功。\n"
            "如果观察足够，action_type=respond，并填写 final_answer。\n"
            "如果还需要一次只读观察，action_type=tool_call，并填写 tool_call。\n"
            "如果发现任务需要写入、命令、长期跟进或真实交付物，action_type=request_task_run，并严格按 schema.task_contract_seed 填写任务合同；"
            "合同必须包含 user_visible_goal、task_run_goal，并且至少包含 completion_criteria、required_artifacts、required_verifications 之一。\n"
            "如果观察结果指出 task_contract_invalid，你需要修正合同字段后重新提交 request_task_run，而不是直接放弃。\n"
            "如果缺少用户信息，action_type=ask_user。\n"
            + _mode_instruction(mode_policy)
            + _environment_instruction(environment_payload)
            + _soul_instruction(soul_role_prompt)
            + "request_id 和 turn_id 可省略；如果输出 turn_id，必须与本次 runtime_envelope.turn_id 完全一致。\n"
            "不要输出 task_run_id、其他内部控制协议或隐藏推理。"
            + _work_role_instruction(work_role_prompt)
        )
        user_payload = {
            "schema": schema,
            "runtime_envelope": envelope.to_dict(),
            "task_environment": environment_payload,
            "turn_id": turn_id,
            "available_tools": [dict(item) for item in tool_payloads],
            "runtime_context": _runtime_context_payload(assembly_payload),
            "history": [dict(item) for item in list(history or [])],
            "user_message": str(user_message or ""),
            "observations": [dict(item) for item in list(observations or [])],
        }
        packet = RuntimeInvocationPacket(
            packet_id=f"rtpacket:{turn_id}:tool_observation_followup:{len(observations) + 1}",
            envelope_ref=envelope.envelope_id,
            invocation_kind="tool_observation_followup",
            invocation_index=len(observations) + 1,
            session_id=session_id,
            turn_id=turn_id,
            model_messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            system_instructions=system,
            agent_role_prompt="你是当前 turn 的主 agent，负责基于观察继续行动。",
            prompt_pack_refs=(*prompt_pack_refs, "runtime.prompt.tool_observation_followup.v1") if prompt_pack_refs else ("runtime.prompt.tool_observation_followup.v1",),
            available_tools=tool_payloads,
            available_modes=("respond", "ask_user", "tool_call", "request_task_run", "block"),
            observation_refs=tuple(str(item.get("observation_id") or "") for item in observations if item.get("observation_id")),
            output_contract={"schema": schema, "format": "json_object"},
            hidden_control_refs={"agent_invocation_id": agent_invocation_id, "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "")},
        )
        return RuntimeCompilationResult(envelope=envelope, packet=packet)


def model_action_request_schema(turn_id: str) -> dict[str, Any]:
    del turn_id
    return {
        "authority": "harness.loop.model_action_request",
        "action_type": "respond|ask_user|tool_call|request_task_run|block",
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


def _mode_instruction(mode_policy: dict[str, Any]) -> str:
    mode = str(mode_policy.get("mode") or "standard").strip()
    planning = dict(mode_policy.get("planning_policy") or {})
    task_lifecycle = dict(mode_policy.get("task_lifecycle_policy") or {})
    if mode == "role":
        return (
            "当前 runtime 是 role 模式：你主要进行角色化对话，可使用已显式提供的只读/搜索能力；"
            "不要开启正式任务生命周期，不要声称拥有未提供的工具权限。\n"
        )
    if mode == "professional":
        plan_note = "可以使用指定计划或先请求正式任务生命周期。" if planning.get("specified_plan_allowed") else "不强制计划。"
        return (
            "当前 runtime 是 professional 模式：你需要以高标准完成任务，重视真实交付物、验证、失败恢复和最终验收。"
            + plan_note
            + "\n"
        )
    lifecycle_note = (
        "如果任务需要长期执行或真实交付物，可以请求正式任务生命周期。"
        if task_lifecycle.get("request_task_run") is not False
        else "当前 runtime 不允许开启正式任务生命周期。"
    )
    return (
        "当前 runtime 是 standard 模式：不默认启动计划模式；你可以在已装配工具和权限范围内行动。"
        + lifecycle_note
        + "\n"
    )


def _soul_instruction(soul_role_prompt: dict[str, Any]) -> str:
    content = str(soul_role_prompt.get("content") or "").strip()
    if not content:
        return ""
    return "以下是 role 模式专属角色表达锚点；它不改变工具、任务或系统边界：\n" + content + "\n"


def _work_role_instruction(work_role_prompt: str) -> str:
    content = str(work_role_prompt or "").strip()
    if not content:
        return ""
    return "\n当前主 agent 工作角色：\n" + content + "\n"


def _environment_instruction(environment_payload: dict[str, Any]) -> str:
    prompts = [
        str(item.get("content") or "").strip()
        for item in list(environment_payload.get("environment_prompts") or [])
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]
    storage = dict(environment_payload.get("storage_space") or {})
    storage_note = ""
    if storage:
        storage_note = (
            "当前环境的存储空间由系统配置："
            f"environment_storage_root={storage.get('environment_storage_root') or ''}；"
            f"artifact_root={storage.get('artifact_root') or ''}；"
            "你不能自行改变环境存储边界。\n"
        )
    if not prompts and not storage_note:
        return ""
    return "当前任务环境说明：\n" + "\n".join(prompts) + ("\n" if prompts else "") + storage_note


def _artifact_root(environment_payload: dict[str, Any]) -> str:
    storage = dict(environment_payload.get("storage_space") or {})
    artifact_root = str(storage.get("artifact_root") or "").strip()
    if artifact_root:
        return artifact_root
    artifact_policy = dict(environment_payload.get("artifact_policy") or {})
    return str(artifact_policy.get("artifact_root") or "").strip()


def _runtime_context_payload(assembly_payload: dict[str, Any]) -> dict[str, Any]:
    profile = dict(assembly_payload.get("profile") or {})
    environment = dict(assembly_payload.get("task_environment") or {})
    return {
        "assembly_id": str(assembly_payload.get("assembly_id") or ""),
        "agent_profile_ref": str(assembly_payload.get("agent_profile_ref") or ""),
        "mode": str(profile.get("mode") or ""),
        "interaction_mode": str(profile.get("interaction_mode") or ""),
        "runtime_lane": str(profile.get("runtime_lane") or ""),
        "task_lifecycle_policy": dict(profile.get("task_lifecycle_policy") or {}),
        "planning_policy": dict(profile.get("planning_policy") or {}),
        "self_review_policy": dict(profile.get("self_review_policy") or {}),
        "permission_policy": dict(profile.get("permission_policy") or {}),
        "task_environment_id": str(environment.get("environment_id") or ""),
        "storage_space": dict(environment.get("storage_space") or {}),
    }
