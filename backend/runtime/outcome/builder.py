from __future__ import annotations

from typing import Any

from .models import EvidenceConfidence, RunOutcome, RunOutcomeStatus


def build_professional_run_outcome(
    *,
    task_run_id: str,
    task_id: str,
    execution_runtime_kind: str,
    terminal_reason: str,
    verification: dict[str, Any],
    completion_judgment: dict[str, Any],
    tool_observation_ledger: dict[str, Any],
    result_refs: list[str] | tuple[str, ...],
    final_content: str,
) -> RunOutcome:
    verification_payload = dict(verification or {})
    judgment = dict(completion_judgment or {})
    ledger = dict(tool_observation_ledger or {})
    refs = _dedupe_strings([str(item) for item in list(result_refs or []) if str(item).strip()])
    artifact_refs = _artifact_refs(refs, ledger)
    verification_refs = _verification_refs(ledger)
    observation_refs = _observation_refs(ledger)
    missing_deliverables = _strings(
        [
            *list(judgment.get("missing_deliverables") or []),
            *list(verification_payload.get("missing_deliverables") or []),
        ]
    )
    missing_output_paths = _strings(verification_payload.get("missing_output_paths") or [])
    unsupported_claims = _strings(
        [
            *list(judgment.get("unsupported_claims") or []),
            *list(verification_payload.get("unsupported_claims") or []),
        ]
    )
    unsatisfied_obligations = _strings(
        [
            *list(judgment.get("unsatisfied_obligations") or []),
            *list(verification_payload.get("missing_required_actions") or []),
            *list(verification_payload.get("missing_response_terms") or []),
        ]
    )
    limitations = _strings(judgment.get("limitations") or [])
    completion_allowed = bool(judgment.get("completion_allowed") is True)
    verification_passed = bool(verification_payload.get("passed") is True)
    status = _status(
        terminal_reason=str(terminal_reason or ""),
        completion_allowed=completion_allowed,
        verification_passed=verification_passed,
        completion_status=str(judgment.get("status") or ""),
        artifact_refs=artifact_refs,
        observation_refs=observation_refs,
        missing_deliverables=missing_deliverables,
        missing_output_paths=missing_output_paths,
        unsupported_claims=unsupported_claims,
        unsatisfied_obligations=unsatisfied_obligations,
        final_content=final_content,
    )
    completed = status == "completed"
    evidence_confidence = _evidence_confidence(
        verification_passed=verification_passed,
        verification_refs=verification_refs,
        artifact_refs=artifact_refs,
        observation_refs=observation_refs,
        final_content=final_content,
    )
    next_actions = _next_required_actions(
        missing_deliverables=missing_deliverables,
        missing_output_paths=missing_output_paths,
        unsatisfied_obligations=unsatisfied_obligations,
        unsupported_claims=unsupported_claims,
    )
    return RunOutcome(
        outcome_id=f"run-outcome:{task_run_id or 'runtime'}",
        task_run_id=str(task_run_id or ""),
        task_id=str(task_id or ""),
        execution_runtime_kind=str(execution_runtime_kind or "single_agent_task"),
        source="agent_runtime.phases.verification",
        status=status,
        completed=completed,
        terminal_reason=str(terminal_reason or ""),
        user_visible_status=_user_visible_status(status),
        summary=_summary(status=status, missing=missing_deliverables, unsupported=unsupported_claims),
        evidence_confidence=evidence_confidence,
        verification_passed=verification_passed,
        completion_allowed=completion_allowed,
        completion_judgment_ref=str(judgment.get("judgment_id") or ""),
        verification_ref=str(dict(verification_payload.get("verification_review") or {}).get("review_id") or ""),
        evidence_packet_ref=str(verification_payload.get("evidence_packet_ref") or dict(verification_payload.get("evidence_packet") or {}).get("packet_id") or ""),
        satisfied_deliverables=_satisfied_deliverables(verification_payload),
        missing_deliverables=tuple(missing_deliverables),
        unsatisfied_obligations=tuple(unsatisfied_obligations),
        missing_output_paths=tuple(missing_output_paths),
        unsupported_claims=tuple(unsupported_claims),
        limitations=tuple(limitations),
        artifact_refs=tuple(artifact_refs),
        changed_files=tuple(_changed_files(artifact_refs, ledger)),
        verification_refs=tuple(verification_refs),
        observation_refs=tuple(observation_refs),
        resume_recommended=bool(status in {"partial", "blocked"} and next_actions),
        resume_reason=_resume_reason(status, next_actions),
        next_required_actions=tuple(next_actions),
        diagnostics={
            "completion_status": str(judgment.get("status") or ""),
            "completion_reasons": list(judgment.get("reasons") or []),
            "terminal_reason": str(terminal_reason or ""),
            "final_content_chars": len(str(final_content or "")),
        },
    )


def _status(
    *,
    terminal_reason: str,
    completion_allowed: bool,
    verification_passed: bool,
    completion_status: str,
    artifact_refs: list[str],
    observation_refs: list[str],
    missing_deliverables: list[str],
    missing_output_paths: list[str],
    unsupported_claims: list[str],
    unsatisfied_obligations: list[str],
    final_content: str,
) -> RunOutcomeStatus:
    terminal = str(terminal_reason or "").strip()
    if terminal == "user_aborted":
        return "aborted"
    if completion_allowed and verification_passed and not missing_deliverables and not missing_output_paths and not unsupported_claims and not unsatisfied_obligations:
        return "completed"
    if unsupported_claims or completion_status == "contradicted":
        return "partial" if artifact_refs or observation_refs or str(final_content or "").strip() else "failed"
    if terminal in {"executor_failed", "tool_call_markup_leaked", "internal_error", "commit_failed"}:
        return "failed"
    if artifact_refs or observation_refs or str(final_content or "").strip():
        return "partial"
    if missing_deliverables or missing_output_paths or unsatisfied_obligations:
        return "blocked"
    return "failed"


def _evidence_confidence(
    *,
    verification_passed: bool,
    verification_refs: list[str],
    artifact_refs: list[str],
    observation_refs: list[str],
    final_content: str,
) -> EvidenceConfidence:
    if verification_passed and verification_refs:
        return "verified"
    if artifact_refs or observation_refs:
        return "observed"
    if str(final_content or "").strip():
        return "claimed"
    return "none"


def _artifact_refs(result_refs: list[str], ledger: dict[str, Any]) -> list[str]:
    refs = [ref for ref in result_refs if ref.startswith("artifact:")]
    for item in list(ledger.get("artifact_refs") or []):
        path = str(dict(item).get("path") or "").strip()
        if path:
            refs.append("artifact:" + path)
    return _dedupe_strings(refs)


def _verification_refs(ledger: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for record in list(ledger.get("records") or []):
        item = dict(record or {})
        if "verify_command" in set(item.get("satisfies") or []):
            ref = str(item.get("observation_ref") or "").strip()
            if ref:
                refs.append(ref)
    return _dedupe_strings(refs)


def _observation_refs(ledger: dict[str, Any]) -> list[str]:
    refs = [
        str(dict(record or {}).get("observation_ref") or "").strip()
        for record in list(ledger.get("records") or [])
    ]
    return _dedupe_strings([ref for ref in refs if ref])


def _changed_files(artifact_refs: list[str], ledger: dict[str, Any]) -> list[str]:
    paths = [ref.removeprefix("artifact:") for ref in artifact_refs if ref.startswith("artifact:")]
    for path in list(ledger.get("observed_paths") or []):
        text = str(path or "").strip()
        if text:
            paths.append(text)
    return _dedupe_strings(paths)


def _satisfied_deliverables(verification: dict[str, Any]) -> tuple[str, ...]:
    deliverable_checks = dict(dict(verification.get("deliverable_validation") or {}).get("diagnostics") or {}).get("deliverable_checks")
    if not isinstance(deliverable_checks, dict):
        return ()
    return tuple(_dedupe_strings([str(key) for key, value in deliverable_checks.items() if value is True]))


def _next_required_actions(
    *,
    missing_deliverables: list[str],
    missing_output_paths: list[str],
    unsatisfied_obligations: list[str],
    unsupported_claims: list[str],
) -> list[str]:
    actions = [*missing_deliverables, *missing_output_paths, *unsatisfied_obligations]
    if unsupported_claims:
        actions.append("repair_unsupported_claims")
    return _dedupe_strings(actions)


def _summary(*, status: str, missing: list[str], unsupported: list[str]) -> str:
    if status == "completed":
        return "Task completed with evidence-backed verification."
    if missing or unsupported:
        return "Task has evidence-backed progress but did not satisfy completion requirements."
    return f"Task ended with status {status}."


def _resume_reason(status: str, next_actions: list[str]) -> str:
    if status not in {"partial", "blocked"} or not next_actions:
        return ""
    return "Missing completion requirements: " + ", ".join(next_actions[:8])


def _user_visible_status(status: str) -> str:
    return {
        "completed": "completed",
        "partial": "partial",
        "blocked": "blocked",
        "failed": "failed",
        "aborted": "aborted",
    }.get(status, "failed")


def _strings(values: Any) -> list[str]:
    return _dedupe_strings([str(item).strip() for item in list(values or []) if str(item).strip()])


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


