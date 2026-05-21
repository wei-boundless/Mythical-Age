from __future__ import annotations
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .protocol_boundary import has_protocol_leak


@dataclass(frozen=True, slots=True)
class DeliverableValidationResult:
    passed: bool
    task_goal_type: str
    missing_deliverables: tuple[str, ...] = ()
    protocol_leak_detected: bool = False
    unsupported_claims: tuple[str, ...] = ()
    evidence_alignment: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.deliverable_validator"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["missing_deliverables"] = list(self.missing_deliverables)
        payload["unsupported_claims"] = list(self.unsupported_claims)
        return payload


def validate_deliverable(
    *,
    final_answer: str,
    semantic_contract: dict[str, Any] | None,
    evidence_packet: dict[str, Any] | None = None,
    strict: bool = False,
    required_output_paths: list[str] | tuple[str, ...] | None = None,
) -> DeliverableValidationResult:
    contract = dict(semantic_contract or {})
    task_goal_type = str(contract.get("task_goal_type") or "general").strip()
    text = str(final_answer or "").strip()
    protocol_leak = _protocol_leak_detected(text)
    if not text:
        return DeliverableValidationResult(
            passed=False,
            task_goal_type=task_goal_type,
            missing_deliverables=("final_answer",),
            protocol_leak_detected=protocol_leak,
            evidence_alignment={"accepted": False, "reason": "empty_answer"},
        )
    if task_goal_type == "test_report_triage":
        return _validate_test_report_triage(
            final_answer=text,
            semantic_contract=contract,
            evidence_packet=dict(evidence_packet or {}),
            protocol_leak_detected=protocol_leak,
            strict=strict,
        )
    if task_goal_type == "artifact_delivery":
        return _validate_artifact_delivery(
            final_answer=text,
            semantic_contract=contract,
            evidence_packet=dict(evidence_packet or {}),
            protocol_leak_detected=protocol_leak,
            required_output_paths=required_output_paths,
        )
    if task_goal_type == "material_synthesis":
        return _validate_material_synthesis(
            final_answer=text,
            semantic_contract=contract,
            evidence_packet=dict(evidence_packet or {}),
            protocol_leak_detected=protocol_leak,
        )
    required = [str(item) for item in list(contract.get("deliverables") or []) if str(item).strip()]
    missing = [item for item in required if not _generic_deliverable_present(text, item)]
    if protocol_leak:
        missing.append("protocol_boundary")
    return DeliverableValidationResult(
        passed=not missing,
        task_goal_type=task_goal_type,
        missing_deliverables=tuple(_dedupe(missing)),
        protocol_leak_detected=protocol_leak,
        evidence_alignment={"accepted": True, "mode": "generic"},
    )


def _validate_test_report_triage(
    *,
    final_answer: str,
    semantic_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
    protocol_leak_detected: bool,
    strict: bool,
) -> DeliverableValidationResult:
    _ = semantic_contract
    checks = {
        "failure_classification": _contains_any(final_answer, ("失败归类", "故障归类", "分类", "system layer", "层")),
        "structural_root_causes": _contains_any(final_answer, ("结构性根因", "根因", "结构问题", "不是孤立")),
        "regression_test_plan": _contains_any(final_answer, ("回归测试", "补充测试", "测试建议", "regression")),
        "evidence_limits": _contains_any(final_answer, ("证据不足", "仍需确认", "边界", "限制")),
    }
    missing = [key for key, present in checks.items() if not present]
    facts = [dict(item) for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    classifications = [
        dict(item)
        for item in list(evidence_packet.get("classifications") or [])
        if isinstance(item, dict)
    ]
    if strict and not facts:
        missing.append("evidence_packet_facts")
    if strict and facts and not classifications:
        missing.append("failure_layer_classifications")
    unsupported_claims: list[str] = []
    if _contains_any(final_answer, ("已修复", "测试已通过", "全部通过")) and not _contains_any(final_answer, ("未执行", "没有运行", "不能确认")):
        unsupported_claims.append("claims_fix_or_pass_without_execution_evidence")
    if protocol_leak_detected:
        missing.append("protocol_boundary")
    passed = not missing and not unsupported_claims
    return DeliverableValidationResult(
        passed=passed,
        task_goal_type="test_report_triage",
        missing_deliverables=tuple(_dedupe(missing)),
        protocol_leak_detected=protocol_leak_detected,
        unsupported_claims=tuple(unsupported_claims),
        evidence_alignment={
            "accepted": bool(facts) or not strict,
            "fact_count": len(facts),
            "classification_count": len(classifications),
            "strict": bool(strict),
        },
        diagnostics={"section_checks": checks},
    )


def _validate_artifact_delivery(
    *,
    final_answer: str,
    semantic_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
    protocol_leak_detected: bool,
    required_output_paths: list[str] | tuple[str, ...] | None = None,
) -> DeliverableValidationResult:
    required = [str(item) for item in list(semantic_contract.get("deliverables") or []) if str(item).strip()]
    facts = [dict(item) for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    has_write_evidence = any(
        _contains_any(str(fact.get("preview") or fact.get("summary") or ""), ("write succeeded", "edit succeeded", "写入成功", "已写入"))
        for fact in facts
    )
    observed_paths = _artifact_write_paths_from_facts(facts)
    required_paths = _dedupe([str(item).replace("\\", "/").strip() for item in list(required_output_paths or [])])
    missing_required_paths = [
        path for path in required_paths if not any(_path_matches(path, observed) for observed in observed_paths)
    ]
    checks = {
        "artifact_refs": has_write_evidence and _contains_any(final_answer, ("文件", "路径", "产物", "artifact", ".md", ".json", ".txt")),
        "completion_status": _contains_any(final_answer, ("已完成", "已写入", "完成", "修改", "交付", "生成")),
        "limitations": _contains_any(final_answer, ("limitations", "limitation", "限制", "边界", "未运行", "未执行", "没有运行", "证据")),
        "change_summary": _contains_any(final_answer, ("修改", "变更", "change", "已完成", "已写入", "交付")),
        "changed_files": _contains_any(final_answer, ("文件", "路径", ".html", ".css", ".js", ".md")),
        "verification_result_or_limitation": _contains_any(final_answer, ("验证", "terminal", "命令", "未运行", "未执行", "限制")),
    }
    missing = [item for item in required if not checks.get(item, _generic_deliverable_present(final_answer, item))]
    missing.extend(f"output_path:{path}" for path in missing_required_paths)
    if protocol_leak_detected:
        missing.append("protocol_boundary")
    return DeliverableValidationResult(
        passed=not missing,
        task_goal_type="artifact_delivery",
        missing_deliverables=tuple(_dedupe(missing)),
        protocol_leak_detected=protocol_leak_detected,
        evidence_alignment={
            "accepted": bool(has_write_evidence),
            "mode": "artifact_write_evidence",
            "fact_count": len(facts),
            "has_write_evidence": bool(has_write_evidence),
            "required_output_paths": required_paths,
            "observed_output_paths": observed_paths,
            "missing_required_output_paths": missing_required_paths,
        },
        diagnostics={"section_checks": checks},
    )


def _validate_material_synthesis(
    *,
    final_answer: str,
    semantic_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
    protocol_leak_detected: bool,
) -> DeliverableValidationResult:
    material_deliverables = {
        "material_findings",
        "cross_material_conclusions",
        "limitations",
        "evidence_limits",
    }
    required = [
        str(item)
        for item in list(semantic_contract.get("deliverables") or [])
        if str(item).strip() in material_deliverables
    ]
    facts = [dict(item) for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    checks = {
        "material_findings": _contains_any(final_answer, ("治理", "库存", "材料", "发现", "风险")),
        "cross_material_conclusions": _contains_any(final_answer, ("行动", "优先", "建议", "综合", "负责人")),
        "limitations": _contains_any(final_answer, ("证据边界", "限制", "边界", "未", "仅基于")),
    }
    missing = [item for item in required if not checks.get(item, _generic_deliverable_present(final_answer, item))]
    if protocol_leak_detected:
        missing.append("protocol_boundary")
    return DeliverableValidationResult(
        passed=not missing,
        task_goal_type="material_synthesis",
        missing_deliverables=tuple(_dedupe(missing)),
        protocol_leak_detected=protocol_leak_detected,
        evidence_alignment={
            "accepted": bool(facts),
            "mode": "material_evidence",
            "fact_count": len(facts),
        },
        diagnostics={"section_checks": checks},
    )


def _generic_deliverable_present(text: str, deliverable: str) -> bool:
    normalized = str(deliverable or "").lower()
    markers = {
        "change_summary": ("修改", "变更", "change"),
        "changed_files": ("文件", "changed file", "路径"),
        "verification_result_or_limitation": ("验证", "测试", "限制", "未运行"),
        "artifact_refs": ("产物", "文件", "artifact"),
        "material_findings": ("治理", "库存", "材料", "发现", "风险"),
        "cross_material_conclusions": ("行动", "优先", "建议", "综合", "负责人"),
        "limitations": ("limitations", "limitation", "限制", "边界", "不足"),
        "tool_grounded_answer": ("原因", "依据", "工具", "验证步骤", "修复建议", "结论", "tool grounded answer", "terminal"),
    }
    return _contains_any(text, markers.get(normalized, (normalized.replace("_", " "), normalized.replace("_", ""))))


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(str(marker).lower() in lowered for marker in markers)


def _artifact_write_paths_from_facts(facts: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    path_pattern = re.compile(
        r"(?P<path>(?:[\w.\-\u4e00-\u9fff]+[\\/])+[\w.\-\u4e00-\u9fff ()（）]+\.[A-Za-z0-9]+)",
        flags=re.IGNORECASE,
    )
    for fact in facts:
        for key in ("path", "artifact_ref"):
            value = str(fact.get(key) or "").replace("\\", "/").strip()
            if value:
                paths.append(value.removeprefix("artifact:"))
        text = str(fact.get("preview") or fact.get("summary") or "").replace("\\", "/")
        paths.extend(match.group("path").strip() for match in path_pattern.finditer(text))
    return _dedupe(paths)


def _path_matches(target: str, candidate: str) -> bool:
    normalized_target = str(target or "").replace("\\", "/").strip().strip("`'\"“”‘’").lower()
    normalized_candidate = str(candidate or "").replace("\\", "/").strip().strip("`'\"“”‘’").lower()
    if not normalized_target or not normalized_candidate:
        return False
    target_base = normalized_target.rsplit("/", 1)[-1]
    candidate_base = normalized_candidate.rsplit("/", 1)[-1]
    return (
        normalized_candidate == normalized_target
        or normalized_candidate.endswith("/" + normalized_target)
        or normalized_target.endswith("/" + normalized_candidate)
        or bool(target_base and target_base == candidate_base)
    )


def _protocol_leak_detected(text: str) -> bool:
    return has_protocol_leak(text)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
