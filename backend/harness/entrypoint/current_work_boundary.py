from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from runtime.model_gateway.model_runtime import stringify_content


CurrentWorkBoundaryAction = Literal[
    "no_current_work",
    "continue_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
    "answer_then_continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "new_independent_turn_allowed",
    "ask_user",
    "block",
]

_ALLOWED_ACTIONS = {
    "no_current_work",
    "continue_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
    "answer_then_continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "new_independent_turn_allowed",
    "ask_user",
    "block",
}


@dataclass(frozen=True, slots=True)
class CurrentWorkBoundaryDecision:
    action: CurrentWorkBoundaryAction
    response: str = ""
    appended_instruction: str = ""
    relation_to_current_work: str = "ambiguous"
    continuation_strategy: str = ""
    confidence: float = 0.0
    reason: str = ""
    evidence: str = ""
    authority: str = "harness.entrypoint.current_work_boundary"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def decide_current_work_boundary(
    *,
    model_runtime: Any,
    model_selection: dict[str, Any],
    turn_input_facts: Any,
    active_work_context: Any | None,
) -> CurrentWorkBoundaryDecision:
    if active_work_context is None:
        return CurrentWorkBoundaryDecision(
            action="no_current_work",
            relation_to_current_work="none",
            confidence=1.0,
            reason="no_active_work_context",
        )

    invoker = getattr(model_runtime, "invoke_messages", None)
    if not callable(invoker):
        return CurrentWorkBoundaryDecision(
            action="new_independent_turn_allowed",
            confidence=0.0,
            reason="model_runtime_unavailable",
        )

    facts_payload = turn_input_facts.to_dict() if hasattr(turn_input_facts, "to_dict") else dict(turn_input_facts or {})
    active_payload = active_work_context.to_model_dict() if hasattr(active_work_context, "to_model_dict") else dict(active_work_context or {})
    prompt_payload = {
        "turn_input_facts": facts_payload,
        "current_work": active_payload,
        "allowed_actions": sorted(_ALLOWED_ACTIONS),
        "output_schema": {
            "authority": "harness.entrypoint.current_work_boundary",
            "action": "one allowed action",
            "relation_to_current_work": "current_work | independent_turn | ambiguous | none",
            "continuation_strategy": "same_run_resume | already_running | none | defer",
            "response": "short user-facing text when needed",
            "appended_instruction": "only when the user added constraints for current work",
            "confidence": "number between 0 and 1",
            "reason": "short internal reason",
            "evidence": "short evidence from the user message and current work snapshot",
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是当前工作边界裁决员。\n"
                "你只负责判断当前用户输入是否应该控制、续接、询问或说明已经存在的当前工作。\n"
                "你不执行工具，不改写用户目标，不创建新任务，不输出普通助手正文。\n"
                "如果用户输入应作为新的独立问题处理，必须返回 new_independent_turn_allowed。\n"
                "如果用户输入指向当前工作，必须返回相应 current-work 动作。\n"
                "只输出一个 JSON 对象，不要 Markdown，不要解释。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True),
        },
    ]
    try:
        response = await invoker(messages, model_selection=dict(model_selection or {}))
    except Exception as exc:
        return CurrentWorkBoundaryDecision(
            action="new_independent_turn_allowed",
            confidence=0.0,
            reason=f"boundary_model_error:{exc.__class__.__name__}",
        )
    payload = _json_object_from_text(stringify_content(getattr(response, "content", response)))
    return _decision_from_payload(payload)


def _decision_from_payload(payload: dict[str, Any]) -> CurrentWorkBoundaryDecision:
    authority = str(payload.get("authority") or "").strip()
    action = str(payload.get("action") or "").strip()
    if authority != "harness.entrypoint.current_work_boundary" or action not in _ALLOWED_ACTIONS:
        return CurrentWorkBoundaryDecision(
            action="new_independent_turn_allowed",
            confidence=0.0,
            reason="boundary_decision_invalid",
        )
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return CurrentWorkBoundaryDecision(
        action=action,  # type: ignore[arg-type]
        response=str(payload.get("response") or "").strip(),
        appended_instruction=str(payload.get("appended_instruction") or "").strip(),
        relation_to_current_work=str(payload.get("relation_to_current_work") or "ambiguous").strip() or "ambiguous",
        continuation_strategy=str(payload.get("continuation_strategy") or "").strip(),
        confidence=confidence,
        reason=str(payload.get("reason") or "").strip(),
        evidence=str(payload.get("evidence") or "").strip(),
    )


def _json_object_from_text(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
