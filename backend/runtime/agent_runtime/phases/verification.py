from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from agent_runtime.understanding import model_visible_semantic_contract


COMPLETION_STATUSES = {"verified", "partially_verified", "unverified", "blocked", "contradicted"}


@dataclass(frozen=True, slots=True)
class RuntimeGoalContract:
    contract_id: str
    goal: str
    required_material_paths: list[str] = field(default_factory=list)
    required_output_paths: list[str] = field(default_factory=list)
    material_types: list[str] = field(default_factory=list)
    required_tool_kinds: list[str] = field(default_factory=list)
    required_output_kinds: list[str] = field(default_factory=list)
    requires_material_review: bool = False
    requires_write_output: bool = False
    requires_verification_command: bool = False
    requires_delegation: bool = False
    response_must_include: list[str] = field(default_factory=list)
    forbidden_visible_markers: list[str] = field(default_factory=list)
    authority: str = "runtime.agent_runtime.goal_contract"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReadonlyVerifierRequest:
    request_id: str
    semantic_contract_ref: str
    evidence_packet_ref: str = ""
    semantic_contract: dict[str, Any] = field(default_factory=dict)
    agent_plan_draft: dict[str, Any] = field(default_factory=dict)
    evidence_packet: dict[str, Any] = field(default_factory=dict)
    deliverable_validation: dict[str, Any] = field(default_factory=dict)
    obligation_validation: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    role_prompt: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.readonly_verifier_request"

    def __post_init__(self) -> None:
        if self.authority != "runtime.readonly_verifier_request":
            raise ValueError("ReadonlyVerifierRequest authority must be runtime.readonly_verifier_request")
        if not self.request_id:
            raise ValueError("ReadonlyVerifierRequest requires request_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["semantic_contract"] = dict(self.semantic_contract or {})
        payload["agent_plan_draft"] = dict(self.agent_plan_draft or {})
        payload["evidence_packet"] = dict(self.evidence_packet or {})
        payload["deliverable_validation"] = dict(self.deliverable_validation or {})
        payload["obligation_validation"] = dict(self.obligation_validation or {})
        payload["output_schema"] = dict(self.output_schema or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


@dataclass(frozen=True, slots=True)
class VerificationReview:
    review_id: str
    semantic_contract_ref: str
    evidence_packet_ref: str = ""
    deliverable_validation: dict[str, Any] = field(default_factory=dict)
    obligation_validation: dict[str, Any] = field(default_factory=dict)
    verifier_mode: str = "readonly_structured_review"
    passed: bool = False
    blocking_issues: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.verification_review"

    def __post_init__(self) -> None:
        if self.authority != "runtime.verification_review":
            raise ValueError("VerificationReview authority must be runtime.verification_review")
        if not self.review_id:
            raise ValueError("VerificationReview requires review_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["deliverable_validation"] = dict(self.deliverable_validation or {})
        payload["obligation_validation"] = dict(self.obligation_validation or {})
        payload["blocking_issues"] = list(self.blocking_issues)
        payload["contradictions"] = list(self.contradictions)
        payload["limitations"] = list(self.limitations)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


@dataclass(frozen=True, slots=True)
class CompletionJudgment:
    judgment_id: str
    semantic_contract_ref: str
    verification_review_ref: str
    status: str
    evidence_packet_ref: str = ""
    completion_allowed: bool = False
    user_visible_status: str = ""
    reasons: tuple[str, ...] = ()
    missing_deliverables: tuple[str, ...] = ()
    unsatisfied_obligations: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.completion_judgment"

    def __post_init__(self) -> None:
        if self.authority != "runtime.completion_judgment":
            raise ValueError("CompletionJudgment authority must be runtime.completion_judgment")
        if not self.judgment_id:
            raise ValueError("CompletionJudgment requires judgment_id")
        if self.status not in COMPLETION_STATUSES:
            raise ValueError(f"Invalid CompletionJudgment status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["missing_deliverables"] = list(self.missing_deliverables)
        payload["unsatisfied_obligations"] = list(self.unsatisfied_obligations)
        payload["unsupported_claims"] = list(self.unsupported_claims)
        payload["limitations"] = list(self.limitations)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def goal_contract_from_semantic_contract(
    *,
    task_run_id: str,
    user_message: str,
    semantic_contract: dict[str, Any],
) -> RuntimeGoalContract:
    materials = [dict(item) for item in list(semantic_contract.get("materials") or []) if isinstance(item, dict)]
    obligation = dict(semantic_contract.get("execution_obligation") or {})
    obligation_reads = [
        dict(item)
        for item in list(obligation.get("required_reads") or [])
        if isinstance(item, dict)
    ]
    obligation_writes = [
        dict(item)
        for item in list(obligation.get("required_writes") or [])
        if isinstance(item, dict)
    ]
    obligation_commands = [
        dict(item)
        for item in list(obligation.get("required_commands") or [])
        if isinstance(item, dict)
    ]
    obligation_verifications = [
        dict(item)
        for item in list(obligation.get("required_verifications") or [])
        if isinstance(item, dict)
    ]
    forbidden_actions = {
        str(item).strip()
        for item in list(obligation.get("forbidden_actions") or [])
        if str(item).strip()
    }
    raw_material_paths = _dedupe_strings(
        [
            *[str(item.get("path") or "").strip() for item in materials if str(item.get("path") or "").strip()],
            *[str(item.get("path") or "").strip() for item in obligation_reads if str(item.get("path") or "").strip()],
        ]
    )
    goal_text = str(semantic_contract.get("user_goal") or user_message or "").strip()
    output_paths = _structured_output_paths(
        semantic_contract=semantic_contract,
        obligation_writes=obligation_writes,
    )
    material_types = _dedupe_strings(
        [
            *[str(item.get("kind") or "").strip() for item in materials if str(item.get("kind") or "").strip()],
            *[str(item.get("kind") or "").strip() for item in obligation_reads if str(item.get("kind") or "").strip()],
            *[_path_suffix(path).lstrip(".") for path in raw_material_paths if _path_suffix(path)],
        ]
    )
    material_paths = [
        path
        for path in raw_material_paths
        if path and not _same_path_member(path, output_paths)
    ]
    required_actions = {
        str(item).strip()
        for item in list(semantic_contract.get("required_actions") or [])
        if str(item).strip()
    }
    deliverables = [
        str(item).strip()
        for item in list(semantic_contract.get("deliverables") or [])
        if str(item).strip()
    ]
    write_forbidden = bool(forbidden_actions.intersection({"modify_code", "write_file", "edit_file"}))
    requires_write = bool(obligation_writes) and not write_forbidden
    requires_verify = bool(obligation_commands or obligation_verifications)
    response_terms = _dedupe_strings(
        [
            *[str(item).strip() for item in list(semantic_contract.get("response_must_include") or []) if str(item).strip()],
        ]
    )
    return RuntimeGoalContract(
        contract_id=f"runtime-goal-contract:{task_run_id}",
        goal=goal_text,
        required_material_paths=material_paths,
        required_output_paths=output_paths,
        material_types=material_types,
        required_tool_kinds=_dedupe_strings(
            [
                *[
                    item
                    for item in list(required_actions)
                    if _semantic_action_is_active(
                        item,
                        material_paths=material_paths,
                        requires_write=requires_write,
                        requires_verify=requires_verify,
                    )
                ],
                *(["write_output"] if requires_write else []),
                *(["verify_command"] if requires_verify else []),
            ]
        ),
        required_output_kinds=["final_answer", *deliverables],
        requires_material_review=bool(material_paths),
        requires_write_output=requires_write,
        requires_verification_command=requires_verify,
        requires_delegation=False,
        response_must_include=response_terms,
        forbidden_visible_markers=_forbidden_visible_markers(),
    )


def build_readonly_verifier_request(
    *,
    task_run_id: str,
    semantic_contract: dict[str, Any] | None,
    evidence_packet: dict[str, Any] | None,
    agent_plan_draft: dict[str, Any] | None = None,
    deliverable_validation: dict[str, Any] | None = None,
    obligation_validation: dict[str, Any] | None = None,
) -> ReadonlyVerifierRequest:
    contract = model_visible_semantic_contract(semantic_contract)
    evidence = dict(evidence_packet or {})
    return ReadonlyVerifierRequest(
        request_id=f"readonly-verifier-request:{task_run_id or 'runtime'}",
        semantic_contract_ref=str(contract.get("contract_id") or ""),
        evidence_packet_ref=str(evidence.get("packet_id") or ""),
        semantic_contract=contract,
        agent_plan_draft=dict(agent_plan_draft or {}),
        evidence_packet=evidence,
        deliverable_validation=dict(deliverable_validation or {}),
        obligation_validation=dict(obligation_validation or {}),
        output_schema=_verification_review_schema(),
        role_prompt=_verifier_prompt(),
        diagnostics={
            "request_contract_only": True,
            "model_call_performed": False,
            "readonly": True,
            "expected_response_authority": "runtime.verification_review",
        },
    )


def build_verification_review(
    *,
    task_run_id: str,
    semantic_contract: dict[str, Any] | None,
    evidence_packet: dict[str, Any] | None,
    deliverable_validation: dict[str, Any] | None,
    obligation_validation: dict[str, Any] | None,
) -> VerificationReview:
    contract = dict(semantic_contract or {})
    evidence = dict(evidence_packet or {})
    deliverable = dict(deliverable_validation or {})
    obligation = dict(obligation_validation or {})
    missing = _string_list(deliverable.get("missing_deliverables"))
    unsupported = _string_list(deliverable.get("unsupported_claims"))
    unsatisfied = _unsatisfied_obligations(obligation)
    contradictions = _contradictions(deliverable=deliverable, obligation=obligation)
    limitations = _string_list(evidence.get("limitations"))
    verifier_request = build_readonly_verifier_request(
        task_run_id=task_run_id,
        semantic_contract=contract,
        evidence_packet=evidence,
        deliverable_validation=deliverable,
        obligation_validation=obligation,
    ).to_dict()
    blocking = _dedupe(
        [
            *[f"missing_deliverable:{item}" for item in missing],
            *[f"unsupported_claim:{item}" for item in unsupported],
            *[f"unsatisfied_obligation:{item}" for item in unsatisfied],
        ]
    )
    passed = bool(deliverable.get("passed") is True and obligation.get("passed") is True and not contradictions)
    return VerificationReview(
        review_id=f"verification-review:{task_run_id or 'runtime'}",
        semantic_contract_ref=str(contract.get("contract_id") or ""),
        evidence_packet_ref=str(evidence.get("packet_id") or ""),
        deliverable_validation=deliverable,
        obligation_validation=obligation,
        passed=passed,
        blocking_issues=tuple(blocking),
        contradictions=tuple(contradictions),
        limitations=tuple(limitations),
        diagnostics={
            "readonly_verifier": True,
            "readonly_verifier_request": verifier_request,
            "deliverable_passed": bool(deliverable.get("passed") is True),
            "obligation_passed": bool(obligation.get("passed") is True),
            "evidence_fact_count": len(list(evidence.get("facts") or [])),
            "evidence_confidence": str(evidence.get("confidence") or ""),
        },
    )


def verification_review_from_payload(
    payload: dict[str, Any] | None,
    *,
    task_run_id: str,
    semantic_contract: dict[str, Any] | None,
    evidence_packet: dict[str, Any] | None,
    deliverable_validation: dict[str, Any] | None,
    obligation_validation: dict[str, Any] | None,
) -> tuple[VerificationReview | None, dict[str, Any]]:
    raw = dict(payload or {})
    if not raw:
        return None, {
            "model_verifier_status": "absent",
            "model_verifier_absent": True,
            "model_verifier_authority_used": False,
        }
    contract = dict(semantic_contract or {})
    evidence = dict(evidence_packet or {})
    deliverable = dict(deliverable_validation or {})
    obligation = dict(obligation_validation or {})
    review_id = str(raw.get("review_id") or f"verification-review:{task_run_id or 'runtime'}").strip()
    errors: list[str] = []
    authority = str(raw.get("authority") or "runtime.verification_review").strip()
    if authority != "runtime.verification_review":
        errors.append("invalid_authority")
    contract_ref = str(contract.get("contract_id") or "").strip()
    semantic_ref = str(raw.get("semantic_contract_ref") or contract_ref).strip()
    if semantic_ref and contract_ref and semantic_ref != contract_ref:
        errors.append("semantic_contract_ref_mismatch")
    if "passed" not in raw or not isinstance(raw.get("passed"), bool):
        errors.append("passed_must_be_boolean")
    hard_contradictions = _contradictions(deliverable=deliverable, obligation=obligation)
    model_contradictions = _string_list(raw.get("contradictions"))
    contradictions = _dedupe([*hard_contradictions, *model_contradictions])
    hard_blocking = _dedupe(
        [
            *[f"missing_deliverable:{item}" for item in _string_list(deliverable.get("missing_deliverables"))],
            *[f"unsupported_claim:{item}" for item in _string_list(deliverable.get("unsupported_claims"))],
            *[f"unsatisfied_obligation:{item}" for item in _unsatisfied_obligations(obligation)],
        ]
    )
    hard_passed = bool(deliverable.get("passed") is True and obligation.get("passed") is True and not hard_contradictions)
    model_passed = bool(raw.get("passed") is True)
    diagnostics = {
        **dict(raw.get("diagnostics") or {}),
        "source": "runtime.verification_review.model",
        "model_verifier_status": "accepted" if not errors else "rejected_invalid",
        "model_verifier_absent": False,
        "model_verifier_authority_used": not errors,
        "model_passed": model_passed,
        "hard_validation_passed": hard_passed,
    }
    if errors:
        return None, {
            "model_verifier_status": "rejected_invalid",
            "model_verifier_absent": False,
            "model_verifier_authority_used": False,
            "review_id": review_id,
            "validation_errors": errors,
        }
    return (
        VerificationReview(
            review_id=review_id,
            semantic_contract_ref=contract_ref,
            evidence_packet_ref=str(raw.get("evidence_packet_ref") or evidence.get("packet_id") or ""),
            deliverable_validation=deliverable,
            obligation_validation=obligation,
            verifier_mode=str(raw.get("verifier_mode") or "readonly_model_review"),
            passed=bool(model_passed and hard_passed and not contradictions),
            blocking_issues=tuple(_dedupe([*_string_list(raw.get("blocking_issues")), *hard_blocking])),
            contradictions=tuple(contradictions),
            limitations=tuple(_string_list(raw.get("limitations"))),
            diagnostics=diagnostics,
        ),
        {
            "model_verifier_status": "accepted",
            "model_verifier_absent": False,
            "model_verifier_authority_used": True,
            "review_id": review_id,
            "validation_errors": [],
        },
    )


def judge_completion(
    *,
    task_run_id: str,
    semantic_contract: dict[str, Any] | None,
    evidence_packet: dict[str, Any] | None,
    verification_review: dict[str, Any] | VerificationReview | None,
    terminal_reason: str = "",
) -> CompletionJudgment:
    contract = dict(semantic_contract or {})
    evidence = dict(evidence_packet or {})
    review = verification_review.to_dict() if isinstance(verification_review, VerificationReview) else dict(verification_review or {})
    deliverable = dict(review.get("deliverable_validation") or {})
    obligation = dict(review.get("obligation_validation") or {})
    missing = _string_list(deliverable.get("missing_deliverables"))
    unsupported = _string_list(deliverable.get("unsupported_claims"))
    unsatisfied = _unsatisfied_obligations(obligation)
    contradictions = _string_list(review.get("contradictions"))
    limitations = _dedupe([*_string_list(evidence.get("limitations")), *_string_list(review.get("limitations"))])
    terminal = str(terminal_reason or "").strip()
    facts = list(evidence.get("facts") or [])
    passed = bool(review.get("passed") is True)
    status = _status(
        passed=passed,
        terminal_reason=terminal,
        facts_present=bool(facts),
        missing=missing,
        unsupported=unsupported,
        unsatisfied=unsatisfied,
        contradictions=contradictions,
    )
    reasons = _reasons(
        status=status,
        terminal_reason=terminal,
        missing=missing,
        unsupported=unsupported,
        unsatisfied=unsatisfied,
        contradictions=contradictions,
        facts_present=bool(facts),
    )
    return CompletionJudgment(
        judgment_id=f"completion-judgment:{task_run_id or 'runtime'}",
        semantic_contract_ref=str(contract.get("contract_id") or ""),
        verification_review_ref=str(review.get("review_id") or ""),
        evidence_packet_ref=str(evidence.get("packet_id") or ""),
        status=status,
        completion_allowed=status == "verified",
        user_visible_status=_user_visible_status(status),
        reasons=tuple(reasons),
        missing_deliverables=tuple(missing),
        unsatisfied_obligations=tuple(unsatisfied),
        unsupported_claims=tuple(unsupported),
        limitations=tuple(limitations),
        diagnostics={
            "terminal_reason": terminal,
            "evidence_fact_count": len(facts),
            "deliverable_passed": bool(deliverable.get("passed") is True),
            "obligation_passed": bool(obligation.get("passed") is True),
            "completion_is_evidence_judged": True,
        },
    )


def _status(
    *,
    passed: bool,
    terminal_reason: str,
    facts_present: bool,
    missing: list[str],
    unsupported: list[str],
    unsatisfied: list[str],
    contradictions: list[str],
) -> str:
    terminal = str(terminal_reason or "").strip()
    if contradictions or unsupported:
        return "contradicted"
    if terminal in {"contract_gate_blocked", "executor_failed", "tool_loop_budget_exceeded", "partial_contract_failed"}:
        return "blocked" if missing or unsatisfied else "unverified"
    if passed:
        return "verified"
    if facts_present and (missing or unsatisfied):
        return "partially_verified"
    if missing or unsatisfied:
        return "blocked"
    return "unverified"


def _reasons(
    *,
    status: str,
    terminal_reason: str,
    missing: list[str],
    unsupported: list[str],
    unsatisfied: list[str],
    contradictions: list[str],
    facts_present: bool,
) -> list[str]:
    reasons: list[str] = [f"status:{status}"]
    terminal = str(terminal_reason or "").strip()
    if terminal:
        reasons.append(f"terminal_reason:{terminal}")
    if not facts_present:
        reasons.append("no_evidence_facts")
    reasons.extend(f"missing_deliverable:{item}" for item in missing)
    reasons.extend(f"unsupported_claim:{item}" for item in unsupported)
    reasons.extend(f"unsatisfied_obligation:{item}" for item in unsatisfied)
    reasons.extend(f"contradiction:{item}" for item in contradictions)
    return _dedupe(reasons)


def _contradictions(*, deliverable: dict[str, Any], obligation: dict[str, Any]) -> list[str]:
    contradictions: list[str] = []
    if bool(deliverable.get("protocol_leak_detected") is True):
        contradictions.append("final_answer_contains_protocol_leak")
    unsupported = _string_list(deliverable.get("unsupported_claims"))
    contradictions.extend(f"unsupported_claim:{item}" for item in unsupported)
    if bool(obligation.get("contradicted") is True):
        contradictions.append("obligation_validator_reported_contradiction")
    return _dedupe(contradictions)


def _unsatisfied_obligations(obligation: dict[str, Any]) -> list[str]:
    explicit = _string_list(obligation.get("unsatisfied_obligations"))
    if explicit:
        return explicit
    missing = _string_list(obligation.get("missing_obligations"))
    if missing:
        return missing
    failed = _string_list(obligation.get("failed_checks"))
    return failed


def _user_visible_status(status: str) -> str:
    return {
        "verified": "verified",
        "partially_verified": "partially_verified",
        "unverified": "unverified",
        "blocked": "blocked",
        "contradicted": "contradicted",
    }.get(status, "unverified")


def _structured_output_paths(
    *,
    semantic_contract: dict[str, Any],
    obligation_writes: list[dict[str, Any]],
) -> list[str]:
    output_schema = dict(semantic_contract.get("output_schema") or {})
    structured_values = [
        *[str(item.get("path") or "").strip() for item in obligation_writes if str(item.get("path") or "").strip()],
        *[str(item or "").strip() for item in list(semantic_contract.get("required_output_paths") or []) if str(item or "").strip()],
        *[str(item or "").strip() for item in list(semantic_contract.get("output_paths") or []) if str(item or "").strip()],
        *[str(item or "").strip() for item in list(output_schema.get("required_output_paths") or []) if str(item or "").strip()],
        *[str(item or "").strip() for item in list(output_schema.get("output_paths") or []) if str(item or "").strip()],
    ]
    return _dedupe_strings(structured_values)


def _semantic_action_is_active(
    action: Any,
    *,
    material_paths: list[str],
    requires_write: bool,
    requires_verify: bool,
) -> bool:
    item = str(action or "").strip()
    if not item:
        return False
    if item == "read_material":
        return bool(material_paths)
    if item in {"apply_real_change", "integrate_asset"}:
        return bool(requires_write)
    if item in {"run_verification", "run_browser_verification"}:
        return bool(requires_verify)
    return True


def _same_path_member(path: str, paths: list[str]) -> bool:
    normalized = _normalize_path_for_match(path)
    return any(normalized == _normalize_path_for_match(item) for item in paths)


def _path_suffix(path: str) -> str:
    text = str(path or "").strip()
    if "." not in text:
        return ""
    suffix = "." + text.rsplit(".", 1)[-1].lower()
    return suffix if len(suffix) > 1 else ""


def _forbidden_visible_markers() -> list[str]:
    return [
        "<｜｜DSML",
        "｜｜parameter",
        "tool_calls",
        "invoke name=",
        "<tool_call",
        'name="read_file"',
        'name="search_text"',
        'name="search_files"',
        'name="delegate_to_agent"',
    ]


def _goal_contract_instruction(goal_contract: RuntimeGoalContract | None) -> str:
    if goal_contract is None:
        return ""
    lines: list[str] = ["目标契约："]
    if goal_contract.required_material_paths:
        lines.append("必须取得真实材料观察：" + "、".join(goal_contract.required_material_paths[:6]) + "。")
    if goal_contract.requires_write_output:
        lines.append("目标契约要求真实写入或修改产物；必须使用 write_file 或 edit_file，不能只口头声称完成。")
    if goal_contract.requires_verification_command:
        lines.append("目标契约要求命令验证；完成写入或修改后必须使用 terminal 返回真实验证结果。")
    if goal_contract.requires_delegation:
        lines.append("如主 Agent 不能稳定读取专业材料，只能通过 delegate_to_agent 发起受控材料核对，并综合回传证据。")
    if goal_contract.response_must_include:
        lines.append("最终回答必须覆盖：" + "、".join(goal_contract.response_must_include) + "。")
    lines.append("最终回答不得包含 DSML、tool_calls、invoke、工具参数或伪工具调用。")
    return "\n".join(lines) + "\n"


def _normalize_path_for_match(path: str) -> str:
    value = str(path or "").strip().strip("`'\"“”‘’").replace("\\", "/")
    match = re.search(r"(?i)^(.+?\.(?:json|py|md|txt|log|csv|tsv|xlsx|xls|pdf|yaml|yml|toml|docx|pptx))(?=$|[\s，,。；;:：、])", value)
    if match:
        value = match.group(1)
    return value.lower()


def _verification_review_schema() -> dict[str, Any]:
    return {
        "authority": "runtime.verification_review",
        "required": ["review_id", "semantic_contract_ref", "passed", "authority"],
        "fields": {
            "blocking_issues": "list[str]",
            "contradictions": "list[str]",
            "limitations": "list[str]",
            "diagnostics": "object",
        },
    }


def _verifier_prompt() -> str:
    return "\n".join(
        [
            "你是一名只读交付验证员。",
            "你只根据语义任务合同、执行计划、证据包和验证结果判断是否满足交付要求。",
            "你不修改文件，不补写产物，不替实现者完成缺失步骤。",
            "模型自述不是事实证据；只有工具观察、文件读写、命令、浏览器、测试和结构化材料可以作为事实。",
            "如果证据不足、存在无证据声明或合同义务未满足，你必须指出阻断原因。",
            "请只输出符合 runtime.verification_review schema 的结构化结果。",
        ]
    )


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        return _dedupe([str(item).strip() for item in value if str(item).strip()])
    return [str(value).strip()] if str(value).strip() else []


def _dedupe_strings(values: list[Any] | tuple[Any, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
