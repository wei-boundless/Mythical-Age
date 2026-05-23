from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelUnderstandingRequest:
    request_id: str
    user_message: str
    deterministic_signals: dict[str, Any] = field(default_factory=dict)
    communication_frame: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    role_prompt: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "intent.model_understanding_request"

    def __post_init__(self) -> None:
        if self.authority != "intent.model_understanding_request":
            raise ValueError("ModelUnderstandingRequest authority must be intent.model_understanding_request")
        if not self.request_id:
            raise ValueError("ModelUnderstandingRequest requires request_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["deterministic_signals"] = dict(self.deterministic_signals or {})
        payload["communication_frame"] = dict(self.communication_frame or {})
        payload["output_schema"] = dict(self.output_schema or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def build_model_understanding_request(
    *,
    request_id: str,
    user_message: str,
    deterministic_signals: dict[str, Any],
    communication_frame: dict[str, Any] | None = None,
) -> ModelUnderstandingRequest:
    signals = _public_signals(dict(deterministic_signals or {}))
    return ModelUnderstandingRequest(
        request_id=str(request_id or f"model-understanding-request:{_slug(user_message)}").strip(),
        user_message=str(user_message or "").strip(),
        deterministic_signals=signals,
        communication_frame=dict(communication_frame or {}),
        output_schema=_model_understanding_schema(),
        role_prompt=_role_prompt(),
        diagnostics={
            "request_contract_only": True,
            "model_call_performed": False,
            "expected_response_authority": "intent.model_understanding_draft",
            "deterministic_signal_role": "weak_signal_and_fallback",
        },
    )


def _model_understanding_schema() -> dict[str, Any]:
    return {
        "authority": "intent.model_understanding_draft",
        "required": ["draft_id", "user_message", "confidence", "authority"],
        "fields": {
            "interaction_intent": "ask|explore|execute|correct|continue_task|review|conversation",
            "action_intent": "answer|inspect|modify|create|verify|research|execute",
            "target_objects": "list[str]",
            "desired_outcomes": "list[str]",
            "explicit_constraints": "list[str]",
            "forbidden_actions": "list[str]",
            "user_provided_flow": "list[str]",
            "context_binding": "object",
            "execution_mode_hint": "answer|analysis_only|investigation|implementation|verification|agent_execution",
            "task_domain_hint": "string",
            "task_goal_type_hint": "string",
            "evidence_requirements": "list[str]",
            "ambiguity_points": "list[str]",
            "assumption_set": "list[str]",
        },
    }


def _role_prompt() -> str:
    return "\n".join(
        [
            "你是一名请求理解裁决员。",
            "你只负责理解用户本轮真实意图、行动边界、显式流程、禁令、上下文绑定和证据要求。",
            "你不负责生成执行步骤，不负责选择工具，不负责修改文件，也不负责替任务域决定用户目标。",
            "如果用户给出明确流程或禁止动作，你必须原样保留；如果你的判断与这些内容冲突，必须把冲突写入 ambiguity_points 或 assumption_set，而不是覆盖它们。",
            "确定性信号只是弱信号和兜底材料；你可以修正弱信号，但不能篡改用户原话中的硬约束。",
            "请只输出符合 intent.model_understanding_draft schema 的结构化结果。",
        ]
    )


def _public_signals(signals: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in signals.items() if not str(key).startswith("_")}


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "runtime"
