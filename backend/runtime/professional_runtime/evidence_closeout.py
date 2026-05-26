from __future__ import annotations

import re
from typing import Any, Iterable

from response_system.boundary.boundary import sanitize_visible_assistant_content

from .goal_contract import ProfessionalTaskGoalContract, _dedupe_strings
from .deliverable_progress import observation_paths_for_satisfaction
from task_system.runtime_semantics.protocol_boundary import has_protocol_leak, strip_protocol_leak
from ..memory.tool_observation_ledger import ToolObservationLedger


def _contains_tool_call_markup(content: str) -> bool:
    return has_protocol_leak(content)


def _strip_tool_call_markup(content: str) -> str:
    return strip_protocol_leak(content)


def _tool_observation_payload(runtime_event: Any) -> dict[str, Any]:
    if str(getattr(runtime_event, "event_type", "") or "") != "executor_observation_received":
        return {}
    payload = dict(getattr(runtime_event, "payload", {}) or {})
    observation = dict(payload.get("observation") or {})
    if observation.get("observation_type") != "tool_result":
        return {}
    observation_payload = dict(observation.get("payload") or {})
    return observation_payload if observation_payload else {}


def _runtime_event_observation_ref(runtime_event: Any) -> str:
    refs = dict(getattr(runtime_event, "refs", {}) or {})
    payload = dict(getattr(runtime_event, "payload", {}) or {})
    observation = dict(payload.get("observation") or {})
    return str(
        refs.get("observation_ref")
        or observation.get("observation_id")
        or getattr(runtime_event, "event_id", "")
        or ""
    ).strip()


def _event_protocol_leak_detected(event: dict[str, Any]) -> bool:
    event_type = str(event.get("type") or "")
    if event_type == "model_protocol_violation":
        return True
    candidates = [
        event.get("content"),
        event.get("assistant_content"),
        event.get("answer_candidate"),
    ]
    output = dict(event.get("output") or {})
    candidates.extend([output.get("visible_text"), output.get("canonical_answer")])
    return any(has_protocol_leak(str(candidate or "")) for candidate in candidates)


def _normalize_professional_verification(verification: dict[str, Any]) -> dict[str, Any]:
    payload = dict(verification or {})
    missing_actions = _dedupe_strings(
        [str(item).strip() for item in list(payload.get("missing_required_actions") or []) if str(item).strip()]
    )
    missing_terms = _dedupe_strings(
        [str(item).strip() for item in list(payload.get("missing_response_terms") or []) if str(item).strip()]
    )
    deliverable_validation = dict(payload.get("deliverable_validation") or {})
    deliverable_missing = _dedupe_strings(
        [str(item).strip() for item in list(deliverable_validation.get("missing_deliverables") or []) if str(item).strip()]
    )
    unsupported = _dedupe_strings(
        [str(item).strip() for item in list(deliverable_validation.get("unsupported_claims") or []) if str(item).strip()]
    )
    protocol_leak = bool(
        payload.get("protocol_leak_detected") is True
        or deliverable_validation.get("protocol_leak_detected") is True
    )
    normalized_passed = bool(
        payload.get("passed") is True
        and not missing_actions
        and not missing_terms
        and not deliverable_missing
        and not unsupported
        and not protocol_leak
    )
    checks = dict(payload.get("checks") or {})
    checks["contract_passed"] = bool(
        checks.get("contract_passed") is True
        and not missing_actions
        and not missing_terms
        and not protocol_leak
    )
    checks["missing_required_actions"] = list(missing_actions)
    checks["missing_response_terms"] = list(missing_terms)
    checks["protocol_leak_detected"] = protocol_leak
    payload["missing_required_actions"] = list(missing_actions)
    payload["missing_response_terms"] = list(missing_terms)
    payload["protocol_leak_detected"] = protocol_leak
    payload["checks"] = checks
    payload["passed"] = normalized_passed
    return payload


def _evidence_packet_prompt(evidence_packet: dict[str, Any]) -> str:
    facts = [dict(item) for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    classifications = [
        dict(item)
        for item in list(evidence_packet.get("classifications") or [])
        if isinstance(item, dict)
    ]
    limitations = [
        str(item).strip()
        for item in list(evidence_packet.get("limitations") or [])
        if str(item).strip()
    ]
    parts = [f"证据包：facts={len(facts)}，classifications={len(classifications)}。"]
    if classifications:
        layers = _dedupe_strings([str(item.get("system_layer") or "") for item in classifications])
        if layers:
            parts.append("已归类系统层：" + "、".join(layers[:8]) + "。")
    if limitations:
        parts.append("证据限制：" + "、".join(limitations[:4]) + "。")
    return "".join(parts)


def _should_repair_professional_closeout(verification: dict[str, Any]) -> bool:
    if bool(verification.get("passed") is True):
        return False
    legacy_missing = list(verification.get("missing_required_actions") or [])
    if legacy_missing:
        return False
    validation = dict(verification.get("deliverable_validation") or {})
    missing_deliverables = list(validation.get("missing_deliverables") or [])
    unsupported_claims = list(validation.get("unsupported_claims") or [])
    return bool(missing_deliverables or unsupported_claims or validation.get("protocol_leak_detected") is True)


def _professional_closeout_repair_instruction(
    *,
    semantic_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
    validation: dict[str, Any],
) -> str:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "general").strip()
    deliverables = [
        str(item).strip()
        for item in list(semantic_contract.get("deliverables") or [])
        if str(item).strip()
    ]
    missing = [
        str(item).strip()
        for item in list(validation.get("missing_deliverables") or [])
        if str(item).strip()
    ]
    missing_line = "缺失交付物：" + "、".join(missing) + "。" if missing else ""
    deliverable_line = "必须交付：" + "、".join(deliverables) + "。" if deliverables else ""
    return (
        "上一条最终回答没有通过专业交付验证。工具预算已经关闭，禁止再请求任何工具或委派。"
        f"任务类型：{task_goal_type}。"
        f"{deliverable_line}"
        f"{missing_line}"
        f"{_evidence_packet_prompt(evidence_packet)}"
        "请只基于已有真实观察重新组织最终回答；如果证据不足，明确写出证据边界。"
        "不要输出工具调用、DSML、参数片段或内部协议。"
    )


def _artifact_output_refs_from_tool_payload(payload: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for item in list(dict(payload or {}).get("artifact_refs") or []):
        if not isinstance(item, dict):
            value = str(item or "").strip()
            if value:
                refs.append(value if value.startswith("artifact:") else f"artifact:{value}")
            continue
        for key in ("artifact_ref", "ref"):
            value = str(item.get(key) or "").strip()
            if value:
                refs.append(value if value.startswith("artifact:") else f"artifact:{value}")
                break
        else:
            path = str(item.get("path") or "").replace("\\", "/").strip().strip("/")
            if path:
                refs.append(f"artifact:{path}")
    return _dedupe_text(refs)


def _dedupe_text(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _generic_fact_previews(facts: list[dict[str, Any]]) -> list[str]:
    previews: list[str] = []
    for fact in facts:
        if "preview" in fact:
            value = str(fact.get("preview") or "").strip()
        elif "summary" in fact:
            value = str(fact.get("summary") or "").strip()
        elif "symptom" in fact:
            value = str(fact.get("symptom") or "").strip()
        else:
            value = str(fact)[:240]
        value = re.sub(r"\s+", " ", value).strip()
        if value:
            previews.append(value[:260])
    return _dedupe_strings(previews)[:6]


def _sanitize_final_content(content: str) -> str:
    return sanitize_visible_assistant_content(_strip_tool_call_markup(content)).strip()


def _adopt_runtime_event_ref(outcome: ProfessionalTaskRunOutcome, runtime_event: Any) -> None:
    event_type = str(getattr(runtime_event, "event_type", "") or "")
    refs = dict(getattr(runtime_event, "refs", {}) or {})
    payload = dict(getattr(runtime_event, "payload", {}) or {})
    if event_type == "executor_observation_received":
        observation_ref = str(refs.get("observation_ref") or getattr(runtime_event, "event_id", "") or "")
        if observation_ref:
            outcome.result_refs.append(observation_ref)
    elif event_type == "output_boundary_applied":
        outcome.result_refs.append(f"output_boundary:{getattr(runtime_event, 'event_id', '')}")
    elif event_type == "commit_gate_checked":
        commit_ref = str(
            refs.get("commit_gate_ref")
            or dict(payload.get("commit_gate") or {}).get("gate_id")
            or getattr(runtime_event, "event_id", "")
        )
        outcome.result_refs.append(f"commit_gate:{commit_ref}")


def _answer_metadata_from_done_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer_channel": str(event.get("answer_channel") or ""),
        "answer_source": str(event.get("answer_source") or "runtime_directive:model_response"),
        "answer_canonical_state": str(event.get("answer_canonical_state") or ""),
        "answer_persist_policy": str(event.get("answer_persist_policy") or ""),
        "answer_finalization_policy": str(event.get("answer_finalization_policy") or ""),
        "answer_fallback_reason": str(event.get("answer_fallback_reason") or ""),
        "completion_state": str(event.get("completion_state") or ""),
        "terminal_reason": str(event.get("terminal_reason") or ""),
        "timeout_seconds": str(event.get("timeout_seconds") or ""),
        "partial_delta_count": str(event.get("partial_delta_count") or ""),
    }
