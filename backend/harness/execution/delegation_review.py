from __future__ import annotations

import json
from typing import Any

from orchestration.delegation_protocol import default_expected_output_contract

from .delegation_models import AgentDelegationRequest


def delegation_requires_model_only_review(request: AgentDelegationRequest, profile: Any) -> bool:
    if profile_requires_model_only_review(profile):
        return True
    return delegation_kind_is_model_only_review(request.delegation_kind)


def profile_requires_model_only_review(profile: Any) -> bool:
    metadata = dict(getattr(profile, "metadata", {}) or {})
    return str(metadata.get("child_execution_mode") or "").strip() == "model_only_review"


def delegation_kind_is_model_only_review(delegation_kind: str) -> bool:
    kind = str(delegation_kind or "").strip()
    return kind in {
        "completion_verification",
        "semantic_verification",
        "deliverable_review",
        "artifact_review",
        "quality_review",
        "plan_review",
    }


def parse_model_only_review_payload(content: str) -> dict[str, Any]:
    raw = str(content or "").strip()
    if not raw:
        return {}
    candidates = [raw]
    if raw.startswith("```"):
        stripped = raw.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
        candidates.append(stripped)
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return dict(payload)
    return {}


def child_system_prompt(agent: Any | None, profile: Any | None) -> str:
    description = str(getattr(agent, "description", "") or "").strip()
    operations = ", ".join(str(item) for item in tuple(getattr(profile, "allowed_operations", ()) or ()))
    lines: list[str] = []
    lines.append(description or "你是一名受限子 Agent，只负责完成委派给你的边界化任务。")
    if profile_requires_model_only_review(profile):
        lines.extend(
            [
                "## 复核职责",
                "你是一名交付复核员。你只负责检查主 Agent 的候选回答、产物、证据和用户目标是否互相支撑。",
                "你不修改文件，不替主 Agent 重写最终回答，不把缺失证据包装成已完成。",
                "你的裁决只能是 pass、needs_revision 或 blocked。",
                "请返回 JSON 对象，字段包括 summary、verdict、missing_requirements、unsupported_claims、required_revisions、evidence_refs、artifact_refs、confidence、limitations。",
            ]
        )
    lines.extend(
        [
            "## 协作边界",
            "你服务于主 Agent 的委派任务。你要把专业材料整理成主 Agent 可以判断和收口的结果。",
            "你不负责替主 Agent 做最终面向用户的表达，也不要扩大任务范围。",
            "你只返回已经完成的结果、证据引用、产物引用、置信度和限制说明。",
            f"你可使用的操作范围是：{operations or '仅模型响应'}。",
            "不要输出执行计划、伪工具调用语法或“我将调用某工具”的描述。",
            "如果已经拿到结果，直接整理结果；如果无法执行，直接说明失败原因和限制。",
            "如果信息不足或能力不可用，请明确写入限制和缺口，不要假装完成。",
        ]
    )
    return "\n\n".join(part for part in lines if str(part).strip())


def child_user_message(request: AgentDelegationRequest) -> str:
    payload = dict(request.input_payload or {})
    protocol = dict(payload.get("agent_communication_protocol") or {})
    expected_output_contract = dict(
        request.expected_output_contract
        or protocol.get("expected_output_contract")
        or default_expected_output_contract(
            source_kind=str(protocol.get("source_kind") or payload.get("source_kind") or ""),
            delegation_kind=request.delegation_kind,
        )
    )
    lines = [
        f"委派类型：{request.delegation_kind}",
        f"任务说明：{request.instruction}",
        "通信协议：",
        json.dumps(
            {
                "protocol_id": str(protocol.get("protocol_id") or "protocol.agent.direct_delegation.v1"),
                "child_agent_contract": dict(protocol.get("child_agent_contract") or {}),
                "expected_output_contract": expected_output_contract,
            },
            ensure_ascii=False,
            indent=2,
        ),
        "输入：",
        json.dumps(payload, ensure_ascii=False, indent=2),
    ]
    if delegation_kind_is_model_only_review(request.delegation_kind):
        lines.extend(
            [
                "请只返回一个 JSON 对象，不要写 Markdown，不要写执行计划。",
                "JSON 字段：summary、verdict、missing_requirements、unsupported_claims、required_revisions、evidence_refs、artifact_refs、confidence、limitations。",
                "verdict 只能是 pass、needs_revision 或 blocked。",
            ]
        )
    else:
        lines.extend(
            [
                "请返回可供主 Agent 收口使用的中文结果摘要，只写已经完成的结果或明确失败原因。",
                "不要写执行计划，不要输出 <op.*> 或 JSON action 这类工具调用文本。",
            ]
        )
    return "\n".join(lines)


