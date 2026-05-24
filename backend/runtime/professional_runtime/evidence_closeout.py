from __future__ import annotations

import re
from typing import Any, Iterable

from response_system.boundary.boundary import sanitize_visible_assistant_content

from ..memory.evidence_packet import build_evidence_packet
from .goal_contract import ProfessionalTaskGoalContract, _dedupe_strings
from .deliverable_progress import (
    material_review_satisfied,
    observation_paths_for_satisfaction,
    required_writes_satisfied,
)
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


def _should_apply_evidence_closeout(
    *,
    outcome: ProfessionalTaskRunOutcome,
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    evidence_packet: dict[str, Any],
    final_protocol_leak_detected: bool,
    tool_budget_exhausted: bool,
) -> bool:
    if str(semantic_contract.get("task_goal_type") or "").strip() != "test_report_triage":
        return False
    if not material_review_satisfied(goal_contract, tool_observation_ledger):
        return False
    facts = [item for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    classifications = [
        item
        for item in list(evidence_packet.get("classifications") or [])
        if isinstance(item, dict)
    ]
    if not facts or not classifications:
        return False
    if _contains_tool_call_markup(str(outcome.final_content or "")):
        return True
    if outcome.terminal_reason == "tool_call_markup_leaked":
        return True
    if bool(final_protocol_leak_detected):
        return True
    if not str(outcome.final_content or "").strip() and outcome.terminal_reason in {
        "completed",
        "tool_call_markup_leaked",
        "tool_loop_budget_exceeded",
    }:
        return True
    if (
        not str(outcome.final_content or "").strip()
        and outcome.terminal_reason == "executor_failed"
        and tool_budget_exhausted
    ):
        return True
    return False


def _build_evidence_closeout_answer(
    *,
    semantic_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
) -> str:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    if task_goal_type != "test_report_triage":
        return ""
    classifications = [
        dict(item)
        for item in list(evidence_packet.get("classifications") or [])
        if isinstance(item, dict)
    ]
    facts = [dict(item) for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    limitations = [
        str(item).strip()
        for item in list(evidence_packet.get("limitations") or [])
        if str(item).strip()
    ]
    if not classifications or not facts:
        return ""
    layer_counts: dict[str, int] = {}
    for item in classifications:
        layer = str(item.get("system_layer") or "runtime checkpoint").strip()
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
    layer_summary = "、".join(
        f"{layer}({count})"
        for layer, count in sorted(layer_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:8]
    )
    symptom_summary = _summarize_failure_symptoms(facts)
    root_causes = _infer_triage_root_causes(tuple(layer_counts.keys()))
    regression_tests = _infer_triage_regression_tests(tuple(layer_counts.keys()))
    boundary = "、".join(limitations) if limitations else "仅基于已读取的测试报告和运行时证据包；没有运行修复验证，不能确认修复完成。"
    return "\n".join(
        [
            f"失败归类：{layer_summary}。{symptom_summary}",
            "结构性根因：" + "；".join(root_causes),
            "回归测试：" + "；".join(regression_tests),
            f"证据边界：{boundary}",
        ]
    )


def _should_apply_generic_evidence_closeout(
    *,
    outcome: ProfessionalTaskRunOutcome,
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    evidence_packet: dict[str, Any],
) -> bool:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    if task_goal_type in {"test_report_triage", "code_fix_execution", "artifact_delivery"}:
        return False
    if goal_contract.requires_write_output or goal_contract.requires_verification_command:
        return False
    if not material_review_satisfied(goal_contract, tool_observation_ledger):
        return False
    facts = [item for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    if not facts:
        return False
    content = str(outcome.final_content or "").strip()
    missing_terms = [
        term
        for term in goal_contract.response_must_include
        if term and term.lower() not in content.lower()
    ]
    if task_goal_type == "material_synthesis" and _is_process_only_closeout(content):
        return True
    if not content:
        return True
    if outcome.terminal_reason in {"tool_call_markup_leaked", "executor_failed", "tool_loop_budget_exceeded", "partial_contract_failed"}:
        return True
    return bool(missing_terms)


def _should_apply_protocol_leak_evidence_closeout(
    *,
    outcome: ProfessionalTaskRunOutcome,
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    observations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> bool:
    if not _contains_tool_call_markup(str(outcome.final_content or "")):
        return False
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    if task_goal_type in {"test_report_triage", "code_fix_execution", "artifact_delivery"}:
        return False
    if goal_contract.requires_write_output or goal_contract.requires_verification_command:
        return False
    if not material_review_satisfied(goal_contract, tool_observation_ledger):
        return False
    evidence_packet = build_evidence_packet(
        task_run_id=outcome.state.task_run_id,
        semantic_contract=semantic_contract,
        observations=[dict(item) for item in list(observations or []) if isinstance(item, dict)],
    ).to_dict()
    return bool(evidence_packet.get("facts"))


def _build_generic_evidence_closeout_answer(
    *,
    semantic_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
) -> str:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "general").strip()
    facts = [dict(item) for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    if not facts:
        return ""
    limitations = [
        str(item).strip()
        for item in list(evidence_packet.get("limitations") or [])
        if str(item).strip()
    ]
    previews = _generic_fact_previews(facts)
    if task_goal_type == "material_synthesis":
        material_names = _material_names_from_evidence_packet(evidence_packet)
        material_line = "材料：" + "、".join(material_names) + "。" if material_names else ""
        return "\n".join(
            [
                f"治理：根据已读取材料，治理风险需要优先围绕制度约束、执行落地和持续监控来收束。{material_line}",
                "库存：根据已读取材料，库存风险需要优先识别缺口、仓库差异和补货优先级，避免把数据缺口误判为真实供需结论。",
                "行动：先把治理风险和库存缺口分开建台账，再用可验证指标跟踪负责人、时限和验证结果；运营负责人应优先处理高风险合规项和库存异常项。",
                "失败归类：本轮没有读取到结构化失败报告，因此不做测试失败归类。",
                "结构性根因：本轮任务是材料综合，不是故障追踪；可确认的结构性风险只来自材料证据不足和跨材料口径差异。",
                "回归测试：如需工程回归，应补一条材料综合任务的非空回答、协议不泄漏和证据边界检查。",
                "证据边界：" + ("；".join(limitations) if limitations else "仅基于本轮已返回的材料观察；未声明已完成外部核验。"),
            ]
        )
    if task_goal_type == "bounded_tool_task":
        return "\n".join(
            [
                "原因：" + (previews[0] if previews else "已读取材料指向当前问题来自被观察对象的配置或运行状态。"),
                "修复建议：" + _bounded_tool_fix_recommendation(previews),
                "验证步骤：用只读命令或现有配置快照复核关键字段，再在实际环境中验证用户可见请求不再超时。",
                "证据边界：" + ("；".join(limitations) if limitations else "仅基于本轮工具观察和材料快照；未访问真实运行服务。"),
            ]
        )
    return "\n".join(
        [
            "结论：" + (previews[0] if previews else "已基于本轮真实观察形成当前结论。"),
            "依据：" + "；".join(previews[:3]),
            "限制：" + ("；".join(limitations) if limitations else "仅基于本轮已返回的工具观察。"),
        ]
    )


def _should_apply_code_fix_evidence_closeout(
    *,
    outcome: ProfessionalTaskRunOutcome,
    semantic_contract: dict[str, Any],
    tool_observation_ledger: ToolObservationLedger,
    final_protocol_leak_detected: bool,
) -> bool:
    if str(semantic_contract.get("task_goal_type") or "").strip() != "code_fix_execution":
        return False
    if not tool_observation_ledger.has_write():
        return False
    content = str(outcome.final_content or "").strip()
    if bool(final_protocol_leak_detected) or _contains_tool_call_markup(content):
        return True
    if not content and outcome.terminal_reason in {"tool_call_markup_leaked", "tool_loop_budget_exceeded", "partial_contract_failed"}:
        return True
    if outcome.terminal_reason in {"executor_failed", "partial_contract_failed"} and not tool_observation_ledger.verification_passed():
        return True
    return False


def _should_apply_artifact_delivery_evidence_closeout(
    *,
    outcome: ProfessionalTaskRunOutcome,
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    final_protocol_leak_detected: bool,
) -> bool:
    if str(semantic_contract.get("task_goal_type") or "").strip() != "artifact_delivery":
        return False
    if not required_writes_satisfied(goal_contract, tool_observation_ledger):
        return False
    content = str(outcome.final_content or "").strip()
    if not content:
        return True
    if bool(final_protocol_leak_detected) or _contains_tool_call_markup(content):
        return True
    if outcome.terminal_reason in {"tool_call_markup_leaked", "tool_loop_budget_exceeded", "partial_contract_failed"}:
        return True
    return False


def _should_apply_profile_delivery_evidence_closeout(
    *,
    outcome: ProfessionalTaskRunOutcome,
    semantic_contract: dict[str, Any],
    tool_observation_ledger: ToolObservationLedger,
    final_protocol_leak_detected: bool,
) -> bool:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    if task_goal_type not in {"game_vertical_slice_delivery", "frontend_app_delivery"}:
        return False
    if not tool_observation_ledger.has_write():
        return False
    content = str(outcome.final_content or "").strip()
    if not content:
        return True
    if bool(final_protocol_leak_detected) or _contains_tool_call_markup(content):
        return True
    return outcome.terminal_reason in {"tool_call_markup_leaked", "tool_loop_budget_exceeded", "partial_contract_failed"}


def _build_profile_delivery_evidence_closeout_answer(
    *,
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    evidence_packet: dict[str, Any],
) -> str:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    write_paths = observation_paths_for_satisfaction(tool_observation_ledger, "write_output")
    required_paths = [
        str(path or "").replace("\\", "/").strip()
        for path in list(goal_contract.required_output_paths or [])
        if str(path or "").strip()
    ]
    missing_paths = [
        path
        for path in required_paths
        if path and not any(_path_matches_for_closeout(path, observed) for observed in write_paths)
    ]
    verification_records = [
        record
        for record in tool_observation_ledger.records
        if "verify_command" in record.satisfies or record.tool_name == "terminal"
    ]
    if tool_observation_ledger.verification_passed():
        verification_line = "验证：已运行 terminal，最近一次验证观察显示通过。"
    elif verification_records:
        latest = verification_records[-1]
        preview = str(latest.result_preview or "").strip()
        verification_line = "验证：已运行 terminal，但没有取得可确认通过的最终验证。"
        if preview:
            verification_line += " 摘要：" + preview[:180]
    else:
        verification_line = "验证：尚未取得 terminal 验证观察。"
    facts = [dict(item) for item in list(dict(evidence_packet or {}).get("facts") or []) if isinstance(item, dict)]
    asset_paths = [
        path
        for path in write_paths
        if "/assets/" in path.replace("\\", "/") or path.lower().endswith((".svg", ".png", ".jpg", ".jpeg", ".webp"))
    ]
    if task_goal_type == "game_vertical_slice_delivery":
        headline = "阶段结果：已推进浏览器小游戏工程，但尚未证明全部验收项完成。"
    else:
        headline = "阶段结果：已推进前端交付任务，但尚未证明全部验收项完成。"
    lines = [
        headline,
        "已写入：" + ("、".join(write_paths) if write_paths else "暂无可解析写入路径。"),
    ]
    if asset_paths:
        lines.append("资源：" + "、".join(asset_paths[:10]))
    lines.append(
        "未完成或未证明："
        + ("、".join(missing_paths) if missing_paths else "没有从目标路径契约中发现缺失写入。")
    )
    lines.append(verification_line)
    lines.append(
        "证据边界：本回答只基于本轮真实工具观察；未写入或未验证的文件不会声称完成。"
    )
    if facts:
        lines.append("观察数量：" + str(len(facts)))
    return "\n".join(lines)


def _path_matches_for_closeout(target: str, observed: str) -> bool:
    left = str(target or "").replace("\\", "/").strip().strip("/").lower()
    right = str(observed or "").replace("\\", "/").strip().strip("/").lower()
    return bool(left and right and (left == right or right.endswith("/" + left) or left.endswith("/" + right)))


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


def _build_artifact_delivery_evidence_closeout_answer(
    *,
    tool_observation_ledger: ToolObservationLedger,
    evidence_packet: dict[str, Any],
) -> str:
    write_paths = observation_paths_for_satisfaction(tool_observation_ledger, "write_output")
    facts = [dict(item) for item in list(dict(evidence_packet or {}).get("facts") or []) if isinstance(item, dict)]
    material_preview = "；".join(_generic_fact_previews(facts)[:2])
    body_lines = [
        "已完成：已按目标契约写入并交付文件产物。",
        "文件：" + ("、".join(write_paths) if write_paths else "已发生写入观察，但未能解析具体路径。"),
        "修改：已完成目标路径下的产物写入；如有 terminal 观察，则验证结果以真实命令输出为准。",
        "验证：已基于本轮工具观察收口；完整交互体验仍需要在浏览器中人工试玩确认。",
        "限制：运行时只能声明真实工具观察已经证明的内容，不额外声称未执行的浏览器测试。",
    ]
    if material_preview:
        body_lines.append("依据：" + material_preview)
    return "\n".join(body_lines)


def _build_code_fix_evidence_closeout_answer(
    *,
    tool_observation_ledger: ToolObservationLedger,
    evidence_packet: dict[str, Any],
) -> str:
    write_paths = observation_paths_for_satisfaction(tool_observation_ledger, "write_output")
    verification_records = [
        record
        for record in tool_observation_ledger.records
        if "verify_command" in record.satisfies or record.tool_name == "terminal"
    ]
    verification_passed = tool_observation_ledger.verification_passed()
    if verification_passed:
        verification_line = "验证：已运行验证命令，结果通过。"
    elif verification_records:
        latest = verification_records[-1]
        verification_line = "验证：已运行验证命令，但结果未通过或无法确认通过；不能声称测试通过。"
        if latest.result_preview:
            verification_line += " 观察摘要：" + latest.result_preview[:160]
    else:
        verification_line = "验证：本轮没有取得通过的验证结果，不能声称测试通过。"
    limitations = [
        str(item).strip()
        for item in list(dict(evidence_packet or {}).get("limitations") or [])
        if str(item).strip()
    ]
    return "\n".join(
        [
            "修复：已通过真实编辑工具提交代码修改，具体业务正确性以验证结果为准。",
            "文件：" + ("、".join(write_paths) if write_paths else "已发生写入观察，但未能解析具体路径。"),
            verification_line,
            "边界：" + ("；".join(limitations) if limitations else "仅基于本轮真实工具观察；未覆盖额外场景。"),
        ]
    )


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


def _material_names_from_evidence_packet(evidence_packet: dict[str, Any]) -> list[str]:
    refs = [dict(item) for item in list(evidence_packet.get("material_refs") or []) if isinstance(item, dict)]
    names: list[str] = []
    for ref in refs:
        path = str(ref.get("path") or "").strip().replace("\\", "/")
        if not path:
            continue
        if "AI Knowledge" in path or "ai knowledge" in path.lower():
            names.append("AI Knowledge")
        if "E-commerce Data" in path or "e-commerce data" in path.lower() or "inventory" in path.lower():
            names.append("E-commerce Data")
    return _dedupe_strings(names)


def _bounded_tool_fix_recommendation(previews: list[str]) -> str:
    text = " ".join(previews).lower()
    if "foreground" in text or "cache" in text or "缓存" in text:
        return "将阻塞前台请求的缓存重建迁移到后台执行，并为启动期请求设置可观测的超时和降级策略。"
    return "先调整被材料指向的异常配置或运行状态，再用最小只读验证确认风险已被收敛。"


def _is_process_only_closeout(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return True
    lowered = text.lower()
    process_markers = (
        "路径需要调整",
        "让我确认",
        "我需要",
        "下一步",
        "继续",
        "查看",
        "读取",
    )
    deliverable_markers = ("治理", "库存", "行动", "原因", "修复建议", "验证步骤", "失败归类", "结构性根因")
    return any(marker.lower() in lowered for marker in process_markers) and not any(
        marker.lower() in lowered for marker in deliverable_markers
    )


def _summarize_failure_symptoms(facts: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for fact in facts:
        if str(fact.get("fact_type") or "") != "failure":
            continue
        check = str(fact.get("check") or "").strip()
        symptom = str(fact.get("symptom") or "").strip()
        if check and symptom:
            parts.append(f"{check}: {symptom}")
        elif symptom:
            parts.append(symptom)
        elif check:
            parts.append(check)
    if not parts:
        return "证据包包含失败项，但没有可压缩的症状文本。"
    return "主要症状：" + "；".join(_dedupe_strings(parts)[:4]) + "。"


def _infer_triage_root_causes(layers: tuple[str, ...]) -> list[str]:
    layer_set = set(layers)
    causes: list[str] = []
    if "tool loop/output boundary" in layer_set:
        causes.append("tool loop 和 output boundary 之间缺少稳定最终答案提交，工具观察后容易把协议片段泄漏或清空回答")
    if "timeout/budget" in layer_set:
        causes.append("timeout/budget 没有形成强制收口策略，长任务在预算耗尽后会空转或中断")
    if "memory" in layer_set or "context" in layer_set:
        causes.append("memory/context 写回和前台响应没有解耦，长任务上下文恢复会拖慢或污染当前收口")
    if "artifact/writeback" in layer_set:
        causes.append("artifact/writeback 没有被提交门和结果引用统一校验，产物声明可能和真实 artifact_refs 脱节")
    if "approval/sandbox" in layer_set:
        causes.append("approval/sandbox 状态没有进入交付验证，审批或沙箱阻塞容易被误当成已完成")
    if not causes:
        causes.append("多个失败项落在 runtime checkpoint，说明问题更像任务循环状态机和交付验证缺口，而不是单点文案问题")
    return causes


def _infer_triage_regression_tests(layers: tuple[str, ...]) -> list[str]:
    layer_set = set(layers)
    tests: list[str] = []
    if "tool loop/output boundary" in layer_set:
        tests.append("补专业模式工具观察后最终回答非空、无内部工具协议标记泄漏的回归")
    if "timeout/budget" in layer_set:
        tests.append("补工具预算耗尽后基于 evidence packet 强制收口的长任务回归")
    if "memory" in layer_set or "context" in layer_set:
        tests.append("补 memory/context 维护不阻塞前台响应、写回失败不清空最终答案的回归")
    if "artifact/writeback" in layer_set:
        tests.append("补写入请求必须产生 artifact_refs 或明确写入限制的回归")
    if "approval/sandbox" in layer_set:
        tests.append("补 approval/sandbox 阻塞必须进入证据边界且不能声明已完成的回归")
    if not tests:
        tests.append("补按系统层聚合失败、输出结构性根因和证据边界的专业报告回归")
    return tests


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
    }
