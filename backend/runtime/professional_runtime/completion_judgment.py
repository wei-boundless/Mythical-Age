from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .planner_verifier_requests import build_readonly_verifier_request


COMPLETION_STATUSES = {"verified", "partially_verified", "unverified", "blocked", "contradicted"}


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


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        return _dedupe([str(item).strip() for item in value if str(item).strip()])
    return [str(value).strip()] if str(value).strip() else []


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
