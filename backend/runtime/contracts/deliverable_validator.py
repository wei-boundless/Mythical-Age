from __future__ import annotations
import re
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from task_system.runtime_semantics.protocol_boundary import has_protocol_leak

try:
    from task_system.goal_profiles import get_task_goal_profile
except Exception:  # pragma: no cover - runtime fallback for partial imports
    get_task_goal_profile = None  # type: ignore[assignment]


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
    if _requires_profile_evidence_validation(contract):
        return _validate_profile_driven_delivery(
            final_answer=text,
            semantic_contract=contract,
            evidence_packet=dict(evidence_packet or {}),
            protocol_leak_detected=protocol_leak,
            required_output_paths=required_output_paths,
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
    required = [
        str(item).strip()
        for item in list(semantic_contract.get("deliverables") or [])
        if str(item).strip()
    ] or ["failure_classification", "structural_root_causes", "regression_test_plan", "evidence_limits"]
    facts = [dict(item) for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    classifications = [
        dict(item)
        for item in list(evidence_packet.get("classifications") or [])
        if isinstance(item, dict)
    ]
    coverage = _triage_coverage_from_evidence(
        required=required,
        evidence_packet=evidence_packet,
        facts=facts,
        classifications=classifications,
    )
    missing = [key for key in required if not bool(dict(coverage.get(key) or {}).get("satisfied"))]
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
            "accepted": (bool(facts) or not strict) and not missing,
            "fact_count": len(facts),
            "classification_count": len(classifications),
            "strict": bool(strict),
            "coverage": coverage,
        },
        diagnostics={"coverage_checks": coverage},
    )


def _triage_coverage_from_evidence(
    *,
    required: list[str],
    evidence_packet: dict[str, Any],
    facts: list[dict[str, Any]],
    classifications: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    packet_coverage = {
        str(key): dict(value)
        for key, value in dict(evidence_packet.get("deliverable_coverage") or {}).items()
        if isinstance(value, dict)
    }
    coverage: dict[str, dict[str, Any]] = {}
    failure_facts = [fact for fact in facts if str(fact.get("fact_type") or "") == "failure"]
    has_write_evidence = bool(_artifact_write_paths_from_facts(facts)) or any(
        _contains_any(str(fact.get("preview") or fact.get("summary") or ""), ("write succeeded", "edit succeeded", "写入成功", "已写入"))
        for fact in facts
    )
    has_verification_evidence = any(
        _contains_any(
            str(fact.get("preview") or fact.get("summary") or ""),
            ("pytest", "PYTEST_OK", "passed", "verification", "terminal", "验证", "测试通过"),
        )
        for fact in facts
    )
    computed = {
        "failure_classification": bool(classifications),
        "structural_root_causes": bool(failure_facts and classifications),
        "regression_test_plan": bool(failure_facts),
        "evidence_limits": True,
        "change_summary": has_write_evidence,
        "changed_files": has_write_evidence,
        "verification_result_or_limitation": has_verification_evidence,
    }
    for item in required:
        declared = dict(packet_coverage.get(item) or {})
        if declared:
            coverage[item] = {
                **declared,
                "satisfied": bool(declared.get("satisfied")),
                "source": "evidence_packet.deliverable_coverage",
            }
            continue
        coverage[item] = {
            "satisfied": bool(computed.get(item, False)),
            "source": "computed_from_evidence",
        }
    return coverage


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
        path for path in required_paths if not _required_output_path_satisfied(path, observed_paths)
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


def _validate_profile_driven_delivery(
    *,
    final_answer: str,
    semantic_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
    protocol_leak_detected: bool,
    required_output_paths: list[str] | tuple[str, ...] | None = None,
) -> DeliverableValidationResult:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "general").strip()
    required_deliverables = [
        str(item)
        for item in list(semantic_contract.get("deliverables") or [])
        if str(item).strip()
    ]
    required_actions = [
        str(item)
        for item in list(semantic_contract.get("required_actions") or [])
        if str(item).strip()
    ]
    facts = [dict(item) for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    fact_text = _facts_text(facts)
    observed_paths = _artifact_write_paths_from_facts(facts)
    required_paths = _dedupe([str(item).replace("\\", "/").strip() for item in list(required_output_paths or [])])
    missing_required_paths = [
        path for path in required_paths if not _required_output_path_satisfied(path, observed_paths)
    ]
    asset_integrity = _asset_reference_integrity(facts=facts, observed_paths=observed_paths, required_output_paths=required_paths)
    dimensions = _profile_validation_dimensions(required_deliverables, required_actions)
    checks = {
        "source_or_artifact_evidence": not dimensions["source_or_artifact"] or _has_source_or_artifact_evidence(facts, final_answer),
        "runtime_or_browser_evidence": not dimensions["runtime_or_browser"] or _has_runtime_or_browser_evidence(facts),
        "asset_evidence": not dimensions["asset"] or bool(asset_integrity.get("accepted")),
        "functional_acceptance_evidence": not dimensions["functional_acceptance"] or _has_functional_acceptance_evidence(facts, final_answer, required_deliverables),
        "limitations": "limitations" not in required_deliverables or _generic_deliverable_present(final_answer, "limitations"),
        "final_report": "final_report" not in required_deliverables or _contains_any(final_answer, ("完成", "交付", "报告", "summary", "final")),
    }
    deliverable_checks = {
        item: _deliverable_satisfied_by_profile_checks(
            item,
            final_answer=final_answer,
            checks=checks,
        )
        for item in required_deliverables
    }
    missing = [item for item, passed in deliverable_checks.items() if not passed]
    missing.extend(f"output_path:{path}" for path in missing_required_paths)
    missing.extend(f"asset:{path}" for path in list(asset_integrity.get("missing_assets") or []))
    unsupported_claims = _unsupported_profile_claims(
        final_answer=final_answer,
        facts=facts,
        dimensions=dimensions,
    )
    if protocol_leak_detected:
        missing.append("protocol_boundary")
    passed = not missing and not unsupported_claims
    return DeliverableValidationResult(
        passed=passed,
        task_goal_type=task_goal_type,
        missing_deliverables=tuple(_dedupe(missing)),
        protocol_leak_detected=protocol_leak_detected,
        unsupported_claims=tuple(unsupported_claims),
        evidence_alignment={
            "accepted": passed,
            "mode": "profile_evidence_dimensions",
            "fact_count": len(facts),
            "required_actions": required_actions,
            "required_dimensions": {key: value for key, value in dimensions.items() if value},
            "observed": {
                "source_or_artifact": _has_source_or_artifact_evidence(facts, final_answer),
                "runtime_or_browser": _has_runtime_or_browser_evidence(facts),
                "asset": _has_asset_evidence(facts),
                "functional_acceptance": _has_functional_acceptance_evidence(facts, final_answer, required_deliverables),
            },
            "required_output_paths": required_paths,
            "observed_output_paths": observed_paths,
            "missing_required_output_paths": missing_required_paths,
            "asset_reference_integrity": asset_integrity,
        },
        diagnostics={
            "section_checks": checks,
            "deliverable_checks": deliverable_checks,
            "fact_terms_preview": fact_text[:500],
        },
    )


def _requires_profile_evidence_validation(semantic_contract: dict[str, Any]) -> bool:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    profile = get_task_goal_profile(task_goal_type) if get_task_goal_profile else None
    required_actions = set(
        str(item)
        for item in list(semantic_contract.get("required_actions") or getattr(profile, "required_actions", ()) or [])
        if str(item).strip()
    )
    deliverables = set(
        str(item)
        for item in list(semantic_contract.get("deliverables") or getattr(profile, "default_core_deliverables", ()) or [])
        if str(item).strip()
    )
    evidence_actions = {
        "apply_real_change",
        "integrate_asset",
        "run_browser_verification",
        "run_verification",
    }
    evidence_deliverables = {
        "runnable_artifact_refs",
        "visual_asset_refs",
        "verification_evidence",
        "gameplay_acceptance",
        "workflow_acceptance",
    }
    return bool(profile) and (
        bool(required_actions & evidence_actions)
        or bool(deliverables & evidence_deliverables)
    )


def _profile_validation_dimensions(deliverables: list[str], actions: list[str]) -> dict[str, bool]:
    deliverable_set = set(deliverables)
    action_set = set(actions)
    return {
        "source_or_artifact": bool(
            {"runnable_artifact_refs", "artifact_refs", "changed_files"} & deliverable_set
            or {"apply_real_change"} & action_set
        ),
        "runtime_or_browser": bool(
            "verification_evidence" in deliverable_set
            or {"run_browser_verification", "run_verification"} & action_set
        ),
        "asset": bool("visual_asset_refs" in deliverable_set or "integrate_asset" in action_set),
        "functional_acceptance": bool({"gameplay_acceptance", "workflow_acceptance"} & deliverable_set),
    }


def _deliverable_satisfied_by_profile_checks(
    deliverable: str,
    *,
    final_answer: str,
    checks: dict[str, bool],
) -> bool:
    mapping = {
        "runnable_artifact_refs": "source_or_artifact_evidence",
        "artifact_refs": "source_or_artifact_evidence",
        "changed_files": "source_or_artifact_evidence",
        "visual_asset_refs": "asset_evidence",
        "verification_evidence": "runtime_or_browser_evidence",
        "gameplay_acceptance": "functional_acceptance_evidence",
        "workflow_acceptance": "functional_acceptance_evidence",
        "limitations": "limitations",
        "final_report": "final_report",
    }
    key = mapping.get(str(deliverable or ""))
    if key:
        return bool(checks.get(key))
    return _generic_deliverable_present(final_answer, deliverable)


def _has_source_or_artifact_evidence(facts: list[dict[str, Any]], final_answer: str) -> bool:
    observed_paths = _artifact_write_paths_from_facts(facts)
    if observed_paths:
        return True
    text = _facts_text(facts)
    return _contains_any(
        text,
        (
            "write succeeded",
            "edit succeeded",
            "created",
            "modified",
            "changed file",
            "patch",
            "写入成功",
            "已写入",
            "已修改",
            "创建",
        ),
    ) and _contains_any(final_answer, ("文件", "路径", ".html", ".js", ".css", ".tsx", ".jsx", ".png", ".jpg", "artifact"))


def _has_runtime_or_browser_evidence(facts: list[dict[str, Any]]) -> bool:
    if _has_structured_verification_evidence(facts):
        return True
    text = _facts_text(facts)
    return _contains_any(
        text,
        (
            "browser",
            "playwright",
            "localhost",
            "127.0.0.1",
            "dev server",
            "server started",
            "npm run",
            "pytest",
            "passed",
            "verify_command",
            "verification_intent",
            "vite",
            "canvas",
            "screenshot",
            "dom",
            "浏览器",
            "启动",
            "运行",
            "截图",
            "页面",
        ),
    )


def _has_structured_verification_evidence(facts: list[dict[str, Any]]) -> bool:
    for fact in facts:
        item = dict(fact or {})
        receipt = dict(item.get("command_receipt") or {})
        intent = dict(item.get("verification_intent") or {})
        if str(item.get("tool_name") or "").strip() == "browser_control" and bool(receipt.get("passed", True)) is True:
            return True
        if str(item.get("tool_name") or "").strip() != "terminal":
            continue
        if receipt.get("passed") is not True:
            continue
        if str(intent.get("obligation") or "").strip() == "verify_command" or str(intent.get("stage") or "").strip() == "verify_output":
            return True
        command = str(receipt.get("command") or dict(item.get("tool_args") or {}).get("command") or "").lower()
        if any(marker in command for marker in ("pytest", "npm test", "pnpm test", "yarn test", "npm run build", "pnpm build", "tsc", "playwright")):
            return True
    return False


def _has_asset_evidence(facts: list[dict[str, Any]]) -> bool:
    text = _facts_text(facts)
    return _contains_any(
        text,
        (
            "asset",
            "assets/",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".svg",
            "image",
            "sprite",
            "texture",
            "visual",
            "资源",
            "图片",
            "图像",
            "贴图",
            "精灵",
        ),
    )


def _asset_reference_integrity(
    *,
    facts: list[dict[str, Any]],
    observed_paths: list[str],
    required_output_paths: list[str],
) -> dict[str, Any]:
    refs = _asset_refs_from_facts(facts)
    if not refs:
        return {
            "accepted": _has_asset_evidence(facts),
            "mode": "no_explicit_asset_refs",
            "asset_refs": [],
            "missing_assets": [],
        }
    output_roots = _output_roots(required_output_paths)
    observed = _dedupe([str(path or "").replace("\\", "/").strip().strip("/") for path in observed_paths])
    missing: list[str] = []
    for ref in refs:
        if _asset_ref_observed(ref, observed, output_roots):
            continue
        missing.append(ref)
    return {
        "accepted": not missing,
        "mode": "local_reference_integrity",
        "asset_refs": refs,
        "missing_assets": _dedupe(missing),
        "output_roots": output_roots,
    }


def _asset_refs_from_facts(facts: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    pattern = re.compile(r"(?P<path>assets/[A-Za-z0-9_.\-/\u4e00-\u9fff]+\.(?:svg|png|jpg|jpeg|webp|gif))", re.IGNORECASE)
    for fact in facts:
        text = json.dumps(fact, ensure_ascii=False, sort_keys=True)
        refs.extend(match.group("path").replace("\\", "/").strip("/") for match in pattern.finditer(text))
    return _dedupe(refs)


def _output_roots(required_output_paths: list[str]) -> list[str]:
    roots: list[str] = []
    for path in required_output_paths:
        normalized = str(path or "").replace("\\", "/").strip().strip("/")
        if not normalized:
            continue
        if "/assets" in normalized:
            roots.append(normalized.split("/assets", 1)[0])
            continue
        if "/" in normalized and "." in normalized.rsplit("/", 1)[-1]:
            roots.append(normalized.rsplit("/", 1)[0])
    return _dedupe(roots)


def _asset_ref_observed(ref: str, observed_paths: list[str], output_roots: list[str]) -> bool:
    normalized_ref = str(ref or "").replace("\\", "/").strip().strip("/").lower()
    candidates = {normalized_ref}
    for root in output_roots:
        root_norm = str(root or "").replace("\\", "/").strip().strip("/")
        if root_norm:
            candidates.add(f"{root_norm}/{normalized_ref}".lower())
    for observed in observed_paths:
        normalized_observed = str(observed or "").replace("\\", "/").strip().strip("/").lower()
        if not normalized_observed:
            continue
        if normalized_observed in candidates:
            return True
        if any(normalized_observed.endswith("/" + candidate) for candidate in candidates):
            return True
    return False


def _has_functional_acceptance_evidence(facts: list[dict[str, Any]], final_answer: str, deliverables: list[str]) -> bool:
    text = _facts_text(facts)
    if "gameplay_acceptance" in deliverables:
        return _contains_any(
            text,
            (
                "movement",
                "attack",
                "enemy",
                "wave",
                "boss",
                "hud",
                "collision",
                "health",
                "score",
                "gameplay",
                "移动",
                "攻击",
                "敌人",
                "波次",
                "生命",
                "玩法",
            ),
        )
    if "workflow_acceptance" in deliverables:
        return _contains_any(
            text,
            (
                "click",
                "input",
                "form",
                "workflow",
                "interaction",
                "navigation",
                "button",
                "state updated",
                "点击",
                "输入",
                "交互",
                "流程",
                "页面切换",
            ),
        )
    return _contains_any(final_answer, ("验收", "acceptance"))


def _unsupported_profile_claims(
    *,
    final_answer: str,
    facts: list[dict[str, Any]],
    dimensions: dict[str, bool],
) -> list[str]:
    claims: list[str] = []
    if dimensions["runtime_or_browser"] and _claims_runtime_verified(final_answer) and not _has_runtime_or_browser_evidence(facts):
        claims.append("claims_runtime_or_browser_verification_without_evidence")
    if dimensions["asset"] and _claims_asset_ready(final_answer) and not _has_asset_evidence(facts):
        claims.append("claims_asset_integration_without_evidence")
    if dimensions["functional_acceptance"] and _claims_functional_acceptance(final_answer) and not _has_functional_acceptance_evidence(facts, final_answer, ["gameplay_acceptance", "workflow_acceptance"]):
        claims.append("claims_functional_acceptance_without_evidence")
    if dimensions["source_or_artifact"] and _claims_files_changed(final_answer) and not _has_source_or_artifact_evidence(facts, final_answer):
        claims.append("claims_artifact_changes_without_write_evidence")
    return _dedupe(claims)


def _claims_runtime_verified(text: str) -> bool:
    return _contains_any(text, ("验证通过", "运行通过", "浏览器验证", "已验证", "tested", "verified", "browser verified", "playwright"))


def _claims_asset_ready(text: str) -> bool:
    return _contains_any(text, ("资源已", "图片已", "图像已", "asset", "assets", "sprite", "贴图", "视觉资源"))


def _claims_functional_acceptance(text: str) -> bool:
    return _contains_any(text, ("玩法已", "流程已", "可玩", "验收通过", "交互完成", "workflow complete", "playable"))


def _claims_files_changed(text: str) -> bool:
    return _contains_any(text, ("已创建", "已修改", "已写入", "changed", "created", ".html", ".js", ".css", ".tsx", ".jsx"))


def _facts_text(facts: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for fact in facts:
        try:
            chunks.append(json.dumps(fact, ensure_ascii=False, sort_keys=True))
        except Exception:
            chunks.append(str(fact))
    return "\n".join(chunks)


def _generic_deliverable_present(text: str, deliverable: str) -> bool:
    normalized = str(deliverable or "").lower()
    if normalized == "final_answer":
        return bool(str(text or "").strip())
    markers = {
        "change_summary": ("修改", "变更", "change"),
        "changed_files": ("文件", "changed file", "路径"),
        "verification_result_or_limitation": ("验证", "测试", "限制", "未运行"),
        "artifact_refs": ("产物", "文件", "artifact"),
        "material_findings": ("治理", "库存", "材料", "发现", "风险"),
        "cross_material_conclusions": ("行动", "优先", "建议", "综合", "负责人"),
        "limitations": ("limitations", "limitation", "限制", "边界", "不足"),
        "tool_grounded_answer": ("原因", "根因", "依据", "工具", "验证步骤", "修复建议", "结论", "tool grounded answer", "terminal"),
        "failure_classification": ("失败归类", "失败分类", "故障归类", "failure classification"),
        "structural_root_causes": ("结构性根因", "结构根因", "根因", "root cause", "root causes"),
        "regression_test_plan": ("回归测试", "回归用例", "测试计划", "regression test"),
        "evidence_limits": ("证据边界", "证据限制", "限制", "仅基于", "evidence limit"),
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


def _required_output_path_satisfied(target: str, observed_paths: list[str]) -> bool:
    normalized = str(target or "").replace("\\", "/").strip().strip("/")
    if not normalized:
        return True
    name = normalized.rsplit("/", 1)[-1]
    if "." in name:
        return any(_path_matches(normalized, observed) for observed in observed_paths)
    prefix = normalized.lower() + "/"
    return any(
        str(observed or "").replace("\\", "/").strip().strip("/").lower().startswith(prefix)
        for observed in observed_paths
    )


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
