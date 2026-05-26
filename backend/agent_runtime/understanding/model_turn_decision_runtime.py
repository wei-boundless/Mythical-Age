from __future__ import annotations

import json
import re
import uuid
from typing import Any

from task_system.goal_profiles import get_task_goal_profile

from .model_turn_decision import model_turn_decision_from_payload


TASK_DOMAIN_AUTHORITY_KEYS = frozenset(
    {
        "domain",
        "task_domain",
        "task_domain_binding",
        "active_domain_binding",
        "domain_binding",
        "domain_playbook",
        "requested_domain",
        "bound_domain_id",
        "semantic_domain",
    }
)


async def main_model_owned_turn_decision(
    *,
    user_message: str,
    request_facts: dict[str, Any],
    task_selection: dict[str, Any],
    model_runtime: Any | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    invoker = getattr(model_runtime, "invoke_messages", None)
    if not callable(invoker):
        return blocked_model_turn_decision(
            user_message=user_message,
            reason="model_runtime_unavailable",
            diagnostics={"model_call_performed": False, "model_authority_used": False},
        )

    messages = model_turn_decision_messages(
        user_message=user_message,
        request_facts=request_facts,
        task_selection=task_selection,
    )
    raw_text = ""
    parse_diagnostics: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    accepted_attempt = 0
    for attempt in range(1, 3):
        try:
            response = await invoker(messages)
        except Exception as exc:
            return fallback_model_turn_decision(
                user_message=user_message,
                reason="model_turn_decision_model_call_failed",
                task_selection=task_selection,
                request_facts=request_facts,
                diagnostics={
                    "model_call_performed": True,
                    "model_authority_used": False,
                    "error": str(exc)[:500],
                    "understanding_attempts": attempt,
                },
            )

        raw_text = stringify_content(getattr(response, "content", response)).strip()
        payload, parse_diagnostics = parse_model_turn_decision_payload(raw_text)
        if payload is None:
            validation = {"decision_status": "rejected_invalid", **parse_diagnostics}
            messages = model_turn_decision_repair_messages(
                original_messages=messages,
                invalid_response=raw_text,
                validation=validation,
            )
            continue

        decision, validation = model_turn_decision_from_payload(payload, user_message=user_message)
        if decision is not None:
            decision_payload = canonical_model_turn_decision_payload(
                decision.to_dict(),
                user_message=user_message,
                task_selection=task_selection,
            )
            unsupported_task_goal_type = str(
                dict(decision_payload.get("diagnostics") or {}).get("unsupported_task_goal_type") or ""
            ).strip()
            if unsupported_task_goal_type:
                validation = {
                    "decision_status": "rejected_invalid",
                    "validation_errors": [f"task_goal_type_unsupported:{unsupported_task_goal_type}"],
                    "model_authority_used": False,
                }
                messages = model_turn_decision_repair_messages(
                    original_messages=messages,
                    invalid_response=raw_text,
                    validation=validation,
                )
                decision = None
                continue
            accepted_attempt = attempt
            break
        messages = model_turn_decision_repair_messages(
            original_messages=messages,
            invalid_response=raw_text,
            validation=validation,
        )
    else:
        decision = None

    if decision is None:
        return fallback_model_turn_decision(
            user_message=user_message,
            reason="model_turn_decision_invalid_after_repair",
            task_selection=task_selection,
            request_facts=request_facts,
            diagnostics={
                "model_call_performed": True,
                "model_authority_used": False,
                **parse_diagnostics,
                **dict(validation or {}),
                "understanding_attempts": 2,
            },
        )
    decision_payload["diagnostics"] = {
        **dict(decision_payload.get("diagnostics") or {}),
        "main_model_owns_task_understanding": True,
        "model_call_performed": True,
    }
    return decision_payload, {
        "decision_status": "accepted",
        "model_call_performed": True,
        "model_authority_used": True,
        "understanding_attempts": accepted_attempt or 1,
        **dict(validation or {}),
        **parse_diagnostics,
    }


def fallback_model_turn_decision(
    *,
    user_message: str,
    reason: str,
    task_selection: dict[str, Any],
    request_facts: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selection = dict(task_selection or {})
    facts = dict(request_facts or {})
    selected_task_id = str(selection.get("selected_task_id") or "").strip()
    details = dict(diagnostics or {})
    return blocked_model_turn_decision(
        user_message=user_message,
        reason=reason,
        diagnostics={
            **details,
            "model_call_performed": True,
            "model_authority_used": False,
            "fallback_understanding_removed": True,
            "fallback_policy": "fail_closed_without_system_authored_agent_decision",
            "selected_task_id": selected_task_id,
            "explicit_path_count": len(list(facts.get("explicit_paths") or [])),
        },
    )


def canonical_model_turn_decision_payload(
    payload: dict[str, Any],
    *,
    user_message: str,
    task_selection: dict[str, Any],
) -> dict[str, Any]:
    item = dict(payload or {})
    task_goal_type = str(item.get("task_goal_type") or "").strip()
    if task_goal_type and get_task_goal_profile(task_goal_type) is not None:
        return item
    diagnostics = dict(item.get("diagnostics") or {})
    diagnostics["unsupported_task_goal_type"] = task_goal_type
    diagnostics["supported_task_goal_types_required"] = True
    item["diagnostics"] = diagnostics
    return item


def model_turn_decision_messages(
    *,
    user_message: str,
    request_facts: dict[str, Any],
    task_selection: dict[str, Any],
) -> list[dict[str, str]]:
    model_visible_request_facts = model_turn_decision_visible_request_facts(request_facts)
    model_visible_task_selection = model_turn_decision_visible_task_selection(task_selection)
    schema = {
        "authority": "agent_runtime.model_turn_decision",
        "decision_id": "model-turn-decision:<stable id or omit>",
        "user_message": "<original user request>",
        "interaction_intent": "answer|explain|inspect|review|plan|modify|create|run|verify|continue|stop|restore",
        "action_intent": "answer_only|read_context|search_external|edit_workspace|run_command|start_service|use_browser|delegate|ask_clarification|block",
        "work_mode": "conversation|read_only_analysis|implementation|verification|planning|delegated|background",
        "task_goal_type": "<specific conventional task type>",
        "domain_mismatch_signal": {},
        "target_objects": [],
        "desired_outcome": "",
        "deliverables": [],
        "constraints": [],
        "forbidden_actions": [],
        "selected_skill_ids": [],
        "resource_contract": {
            "source_projects": [{"path": "", "role": "source", "required": True}],
            "target_projects": [{"path": "", "role": "target", "required": True}],
            "required_read_files": [],
            "required_read_dirs": [],
            "required_write_files": [],
            "required_write_dirs": [],
            "asset_policy": {},
        },
        "context_binding_decision": {},
        "planning_required": False,
        "todo_required": False,
        "completion_criteria": [],
        "needs_clarification": False,
        "clarification_question": "",
        "confidence": 0.0,
        "ambiguity": [],
        "diagnostics": {},
    }
    system = (
        "你是 agent 的当前轮理解决策器。你只负责理解用户请求并输出一个 JSON 对象，"
        "不要执行任务，不要选择具体工具，不要写解释文字。\n"
        "你的判断必须来自用户请求、request_facts、task_selection 和上下文显式事实。"
        "不要用关键词模板代替理解；如果资源、目录、产物是任务成功的必要条件，必须写入 resource_contract。\n"
        "如果请求要求基于已有项目继续开发，source_projects 表示必须读取和继承的源项目，"
        "target_projects 表示必须写入或交付的目标项目。assets、public、static、images、textures、sprites "
        "等资源目录如果需要继承或产出，必须进入 required_read_dirs / required_write_dirs。\n"
        "只输出合法 JSON，不要 Markdown，不要代码块。"
    )
    user = {
        "schema": schema,
        "request_facts": model_visible_request_facts,
        "task_selection": model_visible_task_selection,
        "user_message": str(user_message or ""),
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def model_turn_decision_visible_request_facts(request_facts: dict[str, Any] | None) -> dict[str, Any]:
    facts = dict(request_facts or {})
    if isinstance(facts.get("explicit_selection"), dict):
        facts["explicit_selection"] = model_turn_decision_visible_task_selection(
            dict(facts.get("explicit_selection") or {})
        )
    return model_turn_decision_visible_task_selection(facts)


def model_turn_decision_visible_task_selection(task_selection: dict[str, Any] | None) -> dict[str, Any]:
    sanitized = strip_task_domain_authority(dict(task_selection or {}))
    if isinstance(sanitized, dict):
        sanitized.pop("agent_invocation", None)
        sanitized.pop("runtime_control", None)
    return dict(sanitized or {})


def model_visible_semantic_contract(semantic_contract: dict[str, Any] | None) -> dict[str, Any]:
    contract = strip_task_domain_authority(dict(semantic_contract or {}))
    diagnostics = contract.get("diagnostics")
    if isinstance(diagnostics, dict) and not diagnostics:
        contract.pop("diagnostics", None)
    return contract


def parse_model_turn_decision_payload(text: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, {
            "parse_error": str(exc),
            "raw_response_preview": raw[:800],
        }
    if not isinstance(payload, dict):
        return None, {"parse_error": "model_turn_decision_json_must_be_object"}
    return payload, {"raw_response_chars": len(raw)}


def model_turn_decision_repair_messages(
    *,
    original_messages: list[dict[str, str]],
    invalid_response: str,
    validation: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        *list(original_messages),
        {
            "role": "assistant",
            "content": str(invalid_response or "")[:4000],
        },
        {
            "role": "user",
            "content": (
                "上一次输出不能作为 ModelTurnDecision 使用。"
                "请根据同一个用户请求重新输出一个合法 JSON 对象，只输出 JSON。\n"
                f"校验结果：{json.dumps(dict(validation or {}), ensure_ascii=False)}"
            ),
        },
    ]


def blocked_model_turn_decision(
    *,
    user_message: str,
    reason: str,
    diagnostics: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    details = dict(diagnostics or {})
    decision = {
        "decision_id": f"model-turn-decision:blocked:{uuid.uuid4().hex[:8]}",
        "user_message": str(user_message or "").strip(),
        "interaction_intent": "stop",
        "action_intent": "block",
        "work_mode": "conversation",
        "task_goal_type": "blocked",
        "domain_mismatch_signal": {},
        "target_objects": [],
        "desired_outcome": "理解决策未通过，运行时停止。",
        "deliverables": [],
        "constraints": [],
        "forbidden_actions": ["execute_without_model_turn_decision"],
        "selected_skill_ids": [],
        "resource_contract": {},
        "context_binding_decision": {"mode": "blocked_model_turn_decision", "reason": reason},
        "planning_required": False,
        "todo_required": False,
        "completion_criteria": [],
        "needs_clarification": False,
        "clarification_question": "",
        "confidence": 0.0,
        "ambiguity": [reason],
        "diagnostics": details,
        "authority": "agent_runtime.model_turn_decision",
    }
    return decision, {
        "decision_status": "blocked",
        "block_reason": reason,
        **details,
    }


def stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content or "")


def strip_task_domain_authority(value: Any) -> Any:
    if isinstance(value, dict):
        stripped: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key in TASK_DOMAIN_AUTHORITY_KEYS:
                continue
            stripped[key] = strip_task_domain_authority(raw_value)
        return stripped
    if isinstance(value, list):
        return [strip_task_domain_authority(item) for item in value]
    if isinstance(value, tuple):
        return tuple(strip_task_domain_authority(item) for item in value)
    return value
