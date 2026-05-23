from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.model_gateway.structured_sidecar import invoke_structured_json_sidecar
from task_system.goal_profiles import known_task_goal_types

from .model_turn_decision import model_turn_decision_from_payload


@dataclass(frozen=True, slots=True)
class ModelTurnDecisionRequest:
    request_id: str
    user_message: str
    request_facts: dict[str, Any] = field(default_factory=dict)
    boundary_policy: dict[str, Any] = field(default_factory=dict)
    context_candidates: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    role_prompt: str = ""
    authority: str = "agent_runtime.model_turn_decision_request"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["request_facts"] = dict(self.request_facts or {})
        payload["boundary_policy"] = dict(self.boundary_policy or {})
        payload["context_candidates"] = dict(self.context_candidates or {})
        payload["output_schema"] = dict(self.output_schema or {})
        return payload


async def invoke_model_turn_decision(
    *,
    invoker: Any,
    user_message: str,
    request_facts: dict[str, Any],
    boundary_policy: dict[str, Any],
    context_candidates: dict[str, Any],
    model_spec: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request = ModelTurnDecisionRequest(
        request_id=f"model-turn-decision-request:{_slug(user_message)[:48] or 'runtime'}",
        user_message=str(user_message or "").strip(),
        request_facts=dict(request_facts or {}),
        boundary_policy=dict(boundary_policy or {}),
        context_candidates=dict(context_candidates or {}),
        output_schema=_schema(),
        role_prompt=_role_prompt(),
    )
    sidecar = await invoke_structured_json_sidecar(
        invoker=invoker,
        request_payload=request.to_dict(),
        sidecar_name="model_turn_decision",
        model_spec=model_spec,
    )
    decision, validation = model_turn_decision_from_payload(
        sidecar.payload,
        user_message=user_message,
    )
    diagnostics = {
        **dict(sidecar.diagnostics or {}),
        **dict(validation or {}),
        "request": request.to_dict(),
    }
    if decision is not None:
        return decision.to_dict(), {**diagnostics, "sidecar_status": "accepted", "model_call_performed": True}
    return _blocked_decision(user_message=user_message, request=request.to_dict()), {
        **diagnostics,
        "sidecar_status": str(diagnostics.get("sidecar_status") or diagnostics.get("decision_status") or "blocked_no_model_decision"),
        "blocked_no_model_decision": True,
    }


def _schema() -> dict[str, Any]:
    allowed_task_goal_types = list(known_task_goal_types())
    return {
        "authority": "agent_runtime.model_turn_decision",
        "required": ["decision_id", "user_message", "interaction_intent", "action_intent", "work_mode", "task_goal_type", "task_domain", "confidence", "authority"],
        "fields": {
            "interaction_intent": "answer|explain|inspect|review|plan|modify|create|run|verify|continue|stop|restore",
            "action_intent": "answer_only|read_context|search_external|edit_workspace|run_command|start_service|use_browser|delegate|ask_clarification|block",
            "work_mode": "conversation|read_only_analysis|implementation|verification|planning|delegated|background",
            "task_goal_type": "string, concrete task contract type. Must be one of allowed_task_goal_types unless the user explicitly names a new unsupported contract type.",
            "task_domain": "string, domain of the task, for example software_engineering|workspace|general",
            "target_objects": "list[str]",
            "desired_outcome": "string",
            "deliverables": "list[str]",
            "constraints": "list[str]",
            "forbidden_actions": "list[str]",
            "context_binding_decision": "object",
            "planning_required": "bool",
            "todo_required": "bool",
            "completion_criteria": "list[str]",
            "needs_clarification": "bool",
            "clarification_question": "string",
            "ambiguity": "list[str]",
        },
        "allowed_task_goal_types": allowed_task_goal_types,
    }


def _role_prompt() -> str:
    allowed = ", ".join(known_task_goal_types())
    return "\n".join(
        [
            "你是当前轮请求判断者。",
            "你负责判断用户本轮到底是在问、解释、审查、规划、修改、运行、验证、继续、停止还是恢复。",
            "你还要判断 agent 下一步行动：直接回答、读取上下文、搜索外部信息、编辑工作区、运行命令、启动服务、使用浏览器、委派、澄清或阻塞。",
            "你必须给出当前轮的 task_goal_type。它表示任务契约，不是执行姿态；例如分析失败报告是 test_report_triage，修代码并验证是 code_fix_execution，交付文件是 artifact_delivery，普通问答是 light_qa，闲聊是 role_conversation。",
            f"当前正式任务类型注册表：{allowed}。",
            "RequestFacts 只是不带裁决的事实；BoundaryPolicy 是不能越过的硬边界；ContextCandidates 只是候选上下文。",
            "你不能选择具体工具，不能绕过 BoundaryPolicy，不能把候选上下文当成当前轮事实。",
            "如果请求有明确专业任务类型，你必须在 task_goal_type 写出具体任务契约类型；不要用 planning 代替任务目标。",
            "如果用户禁止修改，action_intent 不能是 edit_workspace；如果用户要求先计划，planning_required 必须为 true。",
            "请只输出符合 agent_runtime.model_turn_decision schema 的 JSON object。",
        ]
    )


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "runtime"


def _blocked_decision(*, user_message: str, request: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": f"model-turn-decision:blocked:{_slug(user_message)[:48] or 'runtime'}",
        "user_message": str(user_message or "").strip(),
        "interaction_intent": "stop",
        "action_intent": "block",
        "work_mode": "conversation",
        "task_goal_type": "blocked",
        "task_domain": "general",
        "target_objects": [],
        "desired_outcome": "Model turn decision was not available; execution is blocked instead of falling back to heuristics.",
        "deliverables": [],
        "constraints": [],
        "forbidden_actions": ["execute_without_model_turn_decision"],
        "context_binding_decision": {},
        "planning_required": False,
        "todo_required": False,
        "completion_criteria": ["obtain_model_turn_decision_before_execution"],
        "needs_clarification": False,
        "clarification_question": "",
        "confidence": 0.0,
        "ambiguity": ["model_turn_decision_unavailable"],
        "diagnostics": {
            "blocked_no_model_decision": True,
            "request": request,
        },
        "authority": "agent_runtime.model_turn_decision",
    }
