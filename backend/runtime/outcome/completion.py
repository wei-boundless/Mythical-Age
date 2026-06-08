from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from prompt_library import READONLY_DELIVERY_VERIFIER_ROLE_PROMPT


@dataclass(frozen=True, slots=True)
class VerificationReview:
    review_id: str
    task_run_id: str
    verifier_mode: str
    passed: bool
    missing_deliverables: tuple[str, ...] = ()
    unsatisfied_obligations: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.verification_review"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "missing_deliverables",
            "unsatisfied_obligations",
            "unsupported_claims",
            "contradictions",
            "limitations",
        ):
            payload[key] = list(getattr(self, key))
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


@dataclass(frozen=True, slots=True)
class CompletionJudgment:
    judgment_id: str
    task_run_id: str
    status: str
    completion_allowed: bool
    missing_deliverables: tuple[str, ...] = ()
    unsatisfied_obligations: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.completion_judgment"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "missing_deliverables",
            "unsatisfied_obligations",
            "unsupported_claims",
            "limitations",
            "reasons",
        ):
            payload[key] = list(getattr(self, key))
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
    deliverable = dict(deliverable_validation or {})
    obligation = dict(obligation_validation or {})
    evidence = dict(evidence_packet or {})
    missing_deliverables = _strings(deliverable.get("missing_deliverables"))
    unsatisfied_obligations = _strings(obligation.get("unsatisfied_obligations") or obligation.get("missing_required_actions"))
    unsupported_claims = _strings(deliverable.get("unsupported_claims"))
    contradictions = tuple(f"unsupported_claim:{item}" for item in unsupported_claims)
    limitations = _strings(evidence.get("limitations"))
    passed = bool(
        deliverable.get("passed") is True
        and obligation.get("passed") is True
        and not missing_deliverables
        and not unsatisfied_obligations
        and not unsupported_claims
    )
    verifier_request = _readonly_verifier_request(
        task_run_id=task_run_id,
        semantic_contract=dict(semantic_contract or {}),
    )
    return VerificationReview(
        review_id=f"verification-review:{task_run_id or 'runtime'}",
        task_run_id=str(task_run_id or ""),
        verifier_mode="readonly_structured_review",
        passed=passed,
        missing_deliverables=tuple(missing_deliverables),
        unsatisfied_obligations=tuple(unsatisfied_obligations),
        unsupported_claims=tuple(unsupported_claims),
        contradictions=contradictions,
        limitations=tuple(limitations),
        diagnostics={
            "readonly_verifier_request": verifier_request,
            "deliverable_validation": deliverable,
            "obligation_validation": obligation,
            "evidence_packet_ref": str(evidence.get("packet_id") or ""),
        },
    )


def judge_completion(
    *,
    task_run_id: str,
    semantic_contract: dict[str, Any] | None,
    evidence_packet: dict[str, Any] | None,
    verification_review: VerificationReview | dict[str, Any],
    terminal_reason: str,
) -> CompletionJudgment:
    del semantic_contract
    evidence = dict(evidence_packet or {})
    review = verification_review.to_dict() if hasattr(verification_review, "to_dict") else dict(verification_review or {})
    missing_deliverables = _strings(review.get("missing_deliverables"))
    unsatisfied_obligations = _strings(review.get("unsatisfied_obligations"))
    unsupported_claims = _strings(review.get("unsupported_claims"))
    limitations = _strings([*list(evidence.get("limitations") or []), *list(review.get("limitations") or [])])
    passed = bool(review.get("passed") is True)
    terminal = str(terminal_reason or "").strip()
    if unsupported_claims or list(review.get("contradictions") or []):
        status = "contradicted"
    elif passed and terminal == "completed":
        status = "verified"
    elif missing_deliverables or unsatisfied_obligations:
        status = "partially_verified" if _has_real_evidence(evidence) and terminal == "completed" else "blocked"
    else:
        status = "unverified"
    completion_allowed = status == "verified"
    reasons = _completion_reasons(
        status=status,
        missing_deliverables=missing_deliverables,
        unsatisfied_obligations=unsatisfied_obligations,
        unsupported_claims=unsupported_claims,
        terminal_reason=terminal,
    )
    return CompletionJudgment(
        judgment_id=f"completion-judgment:{task_run_id or 'runtime'}",
        task_run_id=str(task_run_id or ""),
        status=status,
        completion_allowed=completion_allowed,
        missing_deliverables=tuple(missing_deliverables),
        unsatisfied_obligations=tuple(unsatisfied_obligations),
        unsupported_claims=tuple(unsupported_claims),
        limitations=tuple(limitations),
        reasons=tuple(reasons),
        diagnostics={
            "terminal_reason": terminal,
            "verification_review_ref": str(review.get("review_id") or ""),
            "evidence_packet_ref": str(evidence.get("packet_id") or ""),
        },
    )


def _readonly_verifier_request(*, task_run_id: str, semantic_contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": f"readonly-verifier-request:{task_run_id or 'runtime'}",
        "semantic_contract_ref": str(semantic_contract.get("contract_id") or ""),
        "semantic_contract": _model_visible_semantic_contract(semantic_contract),
        "evidence_requirements": [
            "Do not accept claimed tool execution without evidence facts.",
            "Do not accept claimed file writes without artifact or observed path evidence.",
            "Do not allow completion when required deliverables or obligations are missing.",
        ],
        "role_prompt": READONLY_DELIVERY_VERIFIER_ROLE_PROMPT,
        "diagnostics": {
            "request_contract_only": True,
            "model_call_performed": False,
            "readonly": True,
            "expected_response_authority": "runtime.verification_review",
        },
        "authority": "runtime.readonly_verifier_request",
    }


def _model_visible_semantic_contract(contract: dict[str, Any]) -> dict[str, Any]:
    blocked = {"diagnostics", "domain", "internal_state", "raw_current_turn_context"}
    return {key: value for key, value in dict(contract or {}).items() if key not in blocked}


def _has_real_evidence(evidence_packet: dict[str, Any]) -> bool:
    facts = [dict(item) for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    if not facts:
        return False
    for fact in facts:
        text = " ".join(str(value) for value in fact.values())
        if any(token in text for token in ("artifact", "write", "file", "browser", "terminal", "observed_paths")):
            return True
    return True


def _completion_reasons(
    *,
    status: str,
    missing_deliverables: list[str],
    unsatisfied_obligations: list[str],
    unsupported_claims: list[str],
    terminal_reason: str,
) -> list[str]:
    reasons = [f"status:{status}", f"terminal_reason:{terminal_reason or 'unknown'}"]
    reasons.extend(f"missing_deliverable:{item}" for item in missing_deliverables)
    reasons.extend(f"unsatisfied_obligation:{item}" for item in unsatisfied_obligations)
    reasons.extend(f"unsupported_claim:{item}" for item in unsupported_claims)
    return _strings(reasons)


def _strings(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
