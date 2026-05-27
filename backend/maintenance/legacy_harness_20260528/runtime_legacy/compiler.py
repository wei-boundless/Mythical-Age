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
    """Compiles model-facing invocation packets without deciding user intent."""

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
    ) -> RuntimeCompilationResult:
        envelope = RuntimeEnvelope(
            envelope_id=f"rtenv:{turn_id}:turn",
            scope_kind="turn",
            session_id=session_id,
            turn_id=turn_id,
            agent_profile_ref=agent_profile_ref,
            task_environment_ref="interactive_turn",
            mode_policy={"mode": "turn"},
            permission_policy={"permission_scope": "action_request_only"},
            prompt_policy={"invocation_kind": "turn_action"},
            output_policy={"format": "model_action_request_json"},
            diagnostics={
                "agent_invocation_id": agent_invocation_id,
                "model_selection": dict(model_selection or {}),
            },
        )
        schema = {
            "authority": "agent_runtime.agent_turn_action_request",
            "request_id": "agent-turn-action:<stable id or omit>",
            "turn_id": turn_id,
            "action_type": "respond|ask_user|request_task_run|block",
            "final_answer": "",
            "user_question": "",
            "blocking_reason": "",
            "task_contract_seed": {},
            "completion_contract": {},
            "permission_request": {},
            "diagnostics": {},
        }
        system = (
            "你是当前 turn 的主 agent。系统已经为你装配本次调用的运行时边界、"
            "可用动作和输出契约；你负责理解用户请求并选择下一步动作。\n"
            "只输出一个合法 JSON 对象，不要 Markdown，不要暴露隐藏推理。\n"
            "如果可以直接回答，action_type=respond，并填写 final_answer。\n"
            "如果缺少必要信息，action_type=ask_user，并填写 user_question。\n"
            "如果必须进入正式任务生命周期，action_type=request_task_run，并填写 task_contract_seed；"
            "系统会做准入、开启 TaskRun、初始化 agent_todo，并继续为每一步装配运行时。\n"
            "如果请求越界或不能执行，action_type=block，并填写 blocking_reason。\n"
            "不要输出意图分类字段、任务类型字段、内部运行 ID 或控制协议。"
        )
        user_payload = {
            "schema": schema,
            "runtime_envelope": envelope.to_dict(),
            "turn_id": turn_id,
            "task_selection": dict(task_selection or {}),
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
            prompt_pack_refs=("runtime.prompt.turn_action.v1",),
            available_modes=("respond", "ask_user", "request_task_run", "block"),
            output_contract={"schema": schema, "format": "json_object"},
            hidden_control_refs={"agent_invocation_id": agent_invocation_id},
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
            task_environment_ref="interactive_turn",
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
            "你没有执行工具、没有读取文件、没有修改工作区，也没有创建任务；"
            "不要声称已经做过这些事情。\n"
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

