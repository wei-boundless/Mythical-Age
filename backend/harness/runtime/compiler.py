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
            mode_policy=mode_policy,
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
            "如果必须进入正式任务生命周期，action_type=request_task_run，并填写 task_contract_seed。\n"
            "如果请求越界或不能执行，action_type=block，并填写 blocking_reason。\n"
            + _mode_instruction(mode_policy)
            + _soul_instruction(soul_role_prompt)
            "request_id 和 turn_id 可省略；如果输出 turn_id，必须与本次 runtime_envelope.turn_id 完全一致。\n"
            "不要输出意图分类字段、任务类型字段、task_run_id 或其他内部控制协议。"
        )
        user_payload = {
            "schema": schema,
            "runtime_envelope": envelope.to_dict(),
            "turn_id": turn_id,
            "task_selection": dict(task_selection or {}),
            "available_tools": [dict(item) for item in tool_payloads],
            "runtime_assembly": assembly_payload,
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
            mode_policy=mode_policy,
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
            "如果发现任务需要写入、命令、长期跟进或真实交付物，action_type=request_task_run，并填写 task_contract_seed。\n"
            "如果缺少用户信息，action_type=ask_user。\n"
            + _mode_instruction(mode_policy)
            + _soul_instruction(soul_role_prompt)
            "request_id 和 turn_id 可省略；如果输出 turn_id，必须与本次 runtime_envelope.turn_id 完全一致。\n"
            "不要输出 task_run_id、其他内部控制协议或隐藏推理。"
        )
        user_payload = {
            "schema": schema,
            "runtime_envelope": envelope.to_dict(),
            "turn_id": turn_id,
            "available_tools": [dict(item) for item in tool_payloads],
            "runtime_assembly": assembly_payload,
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
        "task_contract_seed": {},
        "completion_contract": {},
        "permission_request": {},
        "diagnostics": {},
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
