from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


AgentTurnActionType = Literal["respond", "ask_user", "request_task_run", "block"]


@dataclass(frozen=True, slots=True)
class AgentTurnActionRequest:
    request_id: str
    turn_id: str
    action_type: AgentTurnActionType
    final_answer: str = ""
    user_question: str = ""
    blocking_reason: str = ""
    task_contract_seed: dict[str, Any] = field(default_factory=dict)
    completion_contract: dict[str, Any] = field(default_factory=dict)
    permission_request: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_runtime.agent_turn_action_request"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["task_contract_seed"] = dict(self.task_contract_seed or {})
        payload["completion_contract"] = dict(self.completion_contract or {})
        payload["permission_request"] = dict(self.permission_request or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def agent_turn_action_request_from_payload(
    payload: dict[str, Any] | None,
    *,
    turn_id: str,
) -> tuple[AgentTurnActionRequest | None, dict[str, Any]]:
    raw = dict(payload or {})
    errors: list[str] = []
    if str(raw.get("authority") or "agent_runtime.agent_turn_action_request").strip() != "agent_runtime.agent_turn_action_request":
        errors.append("invalid_authority")
    action_type = str(raw.get("action_type") or "").strip()
    if action_type not in {"respond", "ask_user", "request_task_run", "block"}:
        errors.append(f"action_type_unsupported:{action_type}")
    task_contract_seed = raw.get("task_contract_seed") or {}
    completion_contract = raw.get("completion_contract") or {}
    permission_request = raw.get("permission_request") or {}
    if not isinstance(task_contract_seed, dict):
        errors.append("task_contract_seed_must_be_object")
        task_contract_seed = {}
    if not isinstance(completion_contract, dict):
        errors.append("completion_contract_must_be_object")
        completion_contract = {}
    if not isinstance(permission_request, dict):
        errors.append("permission_request_must_be_object")
        permission_request = {}
    final_answer = str(raw.get("final_answer") or "").strip()
    user_question = str(raw.get("user_question") or "").strip()
    blocking_reason = str(raw.get("blocking_reason") or "").strip()
    if action_type == "respond" and not final_answer:
        errors.append("final_answer_required_for_respond")
    if action_type == "ask_user" and not user_question:
        errors.append("user_question_required_for_ask_user")
    if action_type == "block" and not blocking_reason:
        errors.append("blocking_reason_required_for_block")
    if action_type == "request_task_run" and not task_contract_seed:
        errors.append("task_contract_seed_required_for_request_task_run")
    if errors:
        return None, {
            "decision_status": "rejected_invalid",
            "validation_errors": errors,
            "agent_action_authority_used": False,
        }
    return AgentTurnActionRequest(
        request_id=str(raw.get("request_id") or f"agent-turn-action:{turn_id}"),
        turn_id=str(raw.get("turn_id") or turn_id),
        action_type=action_type,  # type: ignore[arg-type]
        final_answer=final_answer,
        user_question=user_question,
        blocking_reason=blocking_reason,
        task_contract_seed=dict(task_contract_seed),
        completion_contract=dict(completion_contract),
        permission_request=dict(permission_request),
        diagnostics=dict(raw.get("diagnostics") or {}),
    ), {
        "decision_status": "accepted",
        "validation_errors": [],
        "agent_action_authority_used": True,
    }


async def main_agent_turn_action_request(
    *,
    user_message: str,
    history: list[dict[str, Any]],
    turn_id: str,
    task_selection: dict[str, Any],
    model_runtime: Any,
    model_selection: dict[str, Any] | None = None,
    runtime_compiler: Any | None = None,
    session_id: str = "",
    agent_invocation_id: str = "",
    agent_profile_ref: str = "main_interactive_agent",
) -> tuple[dict[str, Any], dict[str, Any]]:
    invoker = getattr(model_runtime, "invoke_messages", None)
    if not callable(invoker):
        return _unresolved(turn_id=turn_id, reason="model_runtime_unavailable")
    compilation = None
    if runtime_compiler is not None:
        compilation = runtime_compiler.compile_turn_action_packet(
            session_id=session_id,
            turn_id=turn_id,
            agent_invocation_id=agent_invocation_id,
            user_message=user_message,
            history=history,
            task_selection=task_selection,
            agent_profile_ref=agent_profile_ref,
            model_selection=model_selection,
        )
        messages = list(compilation.packet.model_messages)
    else:
        messages = agent_turn_action_request_messages(
            user_message=user_message,
            history=history,
            turn_id=turn_id,
            task_selection=task_selection,
        )
    try:
        response = await invoker(
            messages,
            **({"model_spec": dict(model_selection or {})} if model_selection else {}),
        )
    except Exception as exc:
        return _unresolved(turn_id=turn_id, reason="model_runtime_error", diagnostics={"error": str(exc)})
    payload = _parse_json_object(getattr(response, "content", response))
    request, validation = agent_turn_action_request_from_payload(payload, turn_id=turn_id)
    if request is None:
        return _unresolved(turn_id=turn_id, reason="agent_turn_action_invalid", diagnostics=validation)
    diagnostics = dict(validation)
    if compilation is not None:
        diagnostics["runtime_envelope"] = compilation.envelope.to_dict()
        diagnostics["runtime_invocation_packet"] = compilation.packet.to_dict()
    return request.to_dict(), diagnostics


def agent_turn_action_request_messages(
    *,
    user_message: str,
    history: list[dict[str, Any]],
    turn_id: str,
    task_selection: dict[str, Any],
) -> list[dict[str, str]]:
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
        "你是当前 turn 的主 agent。系统只为你装配运行时、权限、上下文和可发起的动作；"
        "你负责理解用户请求并决定下一步动作。\n"
        "只输出一个合法 JSON 对象，不要 Markdown，不要暴露隐藏推理。\n"
        "如果可以直接回答，action_type=respond，并填写 final_answer。\n"
        "如果缺少必要信息，action_type=ask_user，并填写 user_question。\n"
        "如果必须进入正式任务生命周期，action_type=request_task_run，并填写 task_contract_seed；"
        "系统会做准入、开启 TaskRun、初始化 agent_todo，并继续为每一步装配运行时。\n"
        "如果请求越界或不能执行，action_type=block，并填写 blocking_reason。\n"
        "不要输出任何意图分类字段；只选择 schema 中定义的动作请求字段。"
    )
    user = {
        "schema": schema,
        "turn_id": turn_id,
        "task_selection": dict(task_selection or {}),
        "history": [dict(item) for item in list(history or [])],
        "user_message": str(user_message or ""),
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def execution_decision_from_agent_action(
    *,
    turn_id: str,
    action_request: dict[str, Any],
) -> dict[str, Any]:
    action_type = str(dict(action_request or {}).get("action_type") or "").strip()
    if action_type == "request_task_run":
        mode = "task_run"
    elif action_type == "ask_user":
        mode = "ask_clarification"
    elif action_type == "block":
        mode = "block"
    else:
        mode = "direct_answer"
    return {
        "authority": "agent_runtime.execution_decision",
        "decision_id": f"execution-decision:{turn_id}",
        "turn_id": turn_id,
        "execution_mode": mode,
        "next_action": {
            "direct_answer": "respond",
            "ask_clarification": "ask_user",
            "task_run": "launch_task_run",
            "block": "block",
        }[mode],
        "requires_task_run": mode == "task_run",
        "task_contract_seed": dict(dict(action_request or {}).get("task_contract_seed") or {}),
        "completion_contract": dict(dict(action_request or {}).get("completion_contract") or {}),
        "permission_request": dict(dict(action_request or {}).get("permission_request") or {}),
        "clarification_question": str(dict(action_request or {}).get("user_question") or ""),
        "blocking_reason": str(dict(action_request or {}).get("blocking_reason") or ""),
        "diagnostics": {"derived_from_agent_turn_action_request": True},
    }


def _unresolved(*, turn_id: str, reason: str, diagnostics: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    return {
        "authority": "agent_runtime.agent_turn_action_request",
        "request_id": f"agent-turn-action:{turn_id}:unresolved",
        "turn_id": turn_id,
        "action_type": "ask_user",
        "user_question": "本轮请求还需要补充信息或重试。",
        "diagnostics": {"unresolved_reason": reason, **dict(diagnostics or {})},
    }, {
        "decision_status": "unresolved",
        "unresolved_reason": reason,
        "agent_action_authority_used": False,
    }


def _parse_json_object(content: Any) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}
