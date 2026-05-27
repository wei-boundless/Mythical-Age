from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.context_management import compact_child_result_observation

from .delegation_models import AgentDelegationRequest, AgentDelegationResult
from .delegation_review import delegation_kind_is_model_only_review


def build_parent_delegation_observation(
    *,
    result: AgentDelegationResult,
    root_dir: Path,
) -> dict[str, Any]:
    context_writeback_hints = context_writeback_hints_from_result(result)
    observation = {
        "type": "agent_delegation_result",
        "status": result.status,
        "target_agent_id": result.target_agent_id,
        "summary": result.summary,
        "answer_candidate": result.answer_candidate,
        "diagnostics": dict(result.diagnostics or {}),
        **verifier_observation_fields(result),
        "evidence_refs": list(result.evidence_refs),
        "artifact_refs": list(result.artifact_refs),
        "confidence": result.confidence,
        "limitations": list(result.limitations),
        "followup_questions": list(result.followup_questions),
        "consumed_handles": list(result.consumed_handles),
        "produced_handles": list(result.produced_handles),
        "result_ref": result.result_id,
        "child_agent_run_ref": result.child_agent_run_ref,
        **({"context_writeback_hints": context_writeback_hints} if context_writeback_hints else {}),
    }
    return compact_child_result_observation(
        observation,
        root_dir=root_dir,
        run_id=result.result_id,
    )


def context_writeback_hints_from_result(result: AgentDelegationResult) -> dict[str, Any]:
    diagnostics = dict(result.diagnostics or {})
    direct_hints = {
        key: value
        for key, value in dict(diagnostics.get("context_writeback_hints") or {}).items()
        if value not in ("", [], {}, None)
    }
    if direct_hints:
        return direct_hints
    mcp_result = dict(diagnostics.get("mcp_result") or {})
    canonical = dict(mcp_result.get("canonical_result") or {})
    bindings = dict(canonical.get("bindings") or {})
    presentation_hints = dict(canonical.get("presentation_hints") or {})
    source_path = str(bindings.get("active_dataset") or bindings.get("active_pdf") or bindings.get("active_table") or "").strip()
    source_kind = "dataset" if bindings.get("active_dataset") else "pdf" if bindings.get("active_pdf") else "table" if bindings.get("active_table") else ""
    subset_labels = [
        str(item or "").strip()
        for item in list(presentation_hints.get("subset_labels") or [])
        if str(item or "").strip()
    ]
    payload = {
        "source_kind": source_kind,
        "source_path": source_path,
        "active_object_handle_id": first_text(canonical.get("object_handle_ids")),
        "active_result_handle_id": str(canonical.get("primary_result_handle_id") or first_text(canonical.get("result_handle_ids"))),
        "active_subset_handle_id": str(presentation_hints.get("subset_handle_id") or ""),
        "subset_filter_column": str(presentation_hints.get("subset_filter_column") or ""),
        "subset_labels": subset_labels,
    }
    return {key: value for key, value in payload.items() if value not in ("", [], {}, None)}


def verifier_observation_fields(result: AgentDelegationResult) -> dict[str, Any]:
    diagnostics = dict(result.diagnostics or {})
    review = dict(diagnostics.get("verifier_review") or {})
    if not review:
        return {}
    return {
        "verifier_review": review,
        "verdict": str(review.get("verdict") or diagnostics.get("verdict") or ""),
        "missing_requirements": list(review.get("missing_requirements") or diagnostics.get("missing_requirements") or []),
        "unsupported_claims": list(review.get("unsupported_claims") or diagnostics.get("unsupported_claims") or []),
        "required_revisions": list(review.get("required_revisions") or diagnostics.get("required_revisions") or []),
    }


def delegation_consumed_handles(*, request: AgentDelegationRequest, child_payload: dict[str, Any]) -> list[str]:
    explicit = [
        str(item).strip()
        for item in list(child_payload.get("consumed_handles") or [])
        if str(item).strip()
    ]
    if explicit:
        return list(dict.fromkeys(explicit))
    payload = dict(request.input_payload or {})
    handles = [
        str(payload.get("active_subset_handle_id") or "").strip(),
        str(payload.get("active_result_handle_id") or "").strip(),
        str(payload.get("active_object_handle_id") or "").strip(),
        delegation_payload_primary_path(payload),
    ]
    return [item for item in dict.fromkeys(handles) if item]


def delegation_produced_handles(*, child_payload: dict[str, Any]) -> list[str]:
    explicit = [
        str(item).strip()
        for item in list(child_payload.get("produced_handles") or [])
        if str(item).strip()
    ]
    if explicit:
        return list(dict.fromkeys(explicit))
    diagnostics = dict(child_payload.get("diagnostics") or {})
    mcp_result = dict(diagnostics.get("mcp_result") or {})
    canonical = dict(mcp_result.get("canonical_result") or {})
    handles = [
        str(canonical.get("primary_result_handle_id") or "").strip(),
        *[str(item or "").strip() for item in list(canonical.get("result_handle_ids") or [])],
        *[str(item or "").strip() for item in list(canonical.get("artifact_refs") or [])],
    ]
    return [item for item in dict.fromkeys(handles) if item]


def delegation_payload_primary_path(payload: dict[str, Any]) -> str:
    direct = str(
        payload.get("file_path")
        or payload.get("path")
        or payload.get("active_pdf")
        or payload.get("active_dataset")
        or ""
    ).strip()
    if direct:
        return direct
    for key in ("file_paths", "paths", "active_pdfs", "active_datasets"):
        values = payload.get(key)
        if isinstance(values, (list, tuple)):
            for item in values:
                value = str(item or "").strip()
                if value:
                    return value
        elif isinstance(values, str) and values.strip():
            return values.strip()
    return ""


def agent_evidence_shadow_readiness(*, packet: dict[str, Any], summary: str) -> dict[str, Any]:
    facts = list(packet.get("facts") or [])
    evidence = list(packet.get("evidence") or [])
    hints = list(packet.get("hints") or [])
    unknowns = list(packet.get("unknowns") or [])
    limits = list(packet.get("limits") or [])
    confidence = str(packet.get("confidence") or "unknown")
    fact_count = len(facts)
    evidence_count = len(evidence)
    unknown_count = len(unknowns)
    limit_count = len(limits)
    evidence_sufficient = fact_count > 0 and evidence_count > 0 and confidence in {"high", "medium"}
    if evidence_sufficient and not unknowns:
        recommendation = "main_agent_can_reason_from_facts"
    elif evidence_sufficient:
        recommendation = "main_agent_can_reason_from_facts_with_caveats"
    elif hints:
        recommendation = "main_agent_should_treat_child_answer_as_hint_only"
    else:
        recommendation = "main_agent_should_request_or_recover_evidence"
    return {
        "mode": "shadow_only",
        "packet_id": str(packet.get("packet_id") or ""),
        "domain": str(packet.get("domain") or "other"),
        "evidence_sufficient": evidence_sufficient,
        "fact_count": fact_count,
        "evidence_count": evidence_count,
        "hint_count": len(hints),
        "unknown_count": unknown_count,
        "limit_count": limit_count,
        "confidence": confidence,
        "summary_is_primary_path": True,
        "summary_chars": len(str(summary or "")),
        "recommendation": recommendation,
    }


def validate_delegation_result_quality(
    *,
    request: AgentDelegationRequest,
    child_payload: dict[str, Any],
    summary: str,
) -> dict[str, Any]:
    text = str(summary or "").strip()
    evidence_refs = [str(item) for item in list(child_payload.get("evidence_refs") or []) if str(item)]
    artifact_refs = [str(item) for item in list(child_payload.get("artifact_refs") or []) if str(item)]
    limitations = [str(item) for item in list(child_payload.get("limitations") or []) if str(item)]
    reasons: list[str] = []
    lowered = text.casefold()
    plan_markers = (
        "我将",
        "我会",
        "首先，我将",
        "让我",
        "将使用",
        "尝试读取",
        "i will",
        "i'll",
    )
    pseudo_tool_markers = (
        "<op.",
        "</op.",
        '"action"',
        "```json",
        "op.mcp_pdf",
        "op.read_structured_file",
        "op.mcp_structured_data",
        "op.mcp_retrieval",
    )
    if not text:
        reasons.append("empty_child_summary")
    if any(marker.casefold() in lowered for marker in plan_markers) and not (evidence_refs or artifact_refs or limitations):
        reasons.append("plan_text_without_evidence")
    if any(marker.casefold() in lowered for marker in pseudo_tool_markers) and not (evidence_refs or artifact_refs):
        reasons.append("pseudo_tool_text_without_execution_refs")
    specialist_kind = str(request.delegation_kind or "").strip()
    if delegation_kind_is_model_only_review(specialist_kind):
        verdict = str(child_payload.get("verdict") or dict(child_payload.get("diagnostics") or {}).get("verdict") or "").strip()
        review = dict(dict(child_payload.get("diagnostics") or {}).get("verifier_review") or {})
        if not verdict and review:
            verdict = str(review.get("verdict") or "").strip()
        if verdict not in {"pass", "needs_revision", "blocked"}:
            reasons.append("verifier_result_missing_valid_verdict")
        status = "invalid" if "verifier_result_missing_valid_verdict" in reasons else "pass"
        normalized_status = str(child_payload.get("status") or "completed")
        if status == "invalid":
            normalized_status = "invalid_output"
        return {
            "status": status,
            "reasons": reasons,
            "normalized_status": normalized_status,
        }
    if specialist_kind in {
        "pdf",
        "pdf_reading",
        "table_analysis",
        "structured_data",
        "structured_data_lookup",
        "retrieval",
        "evidence_lookup",
        "knowledge_search",
        "knowledge_retrieval",
        "codebase_search",
        "local_search",
        "workspace_search",
        "file_search",
        "memory_search",
        "memory_lookup",
        "memory_recall",
        "web",
        "web_research",
        "external_web_lookup",
        "current_information_lookup",
        "official_source_lookup",
    }:
        if not (evidence_refs or artifact_refs or limitations):
            reasons.append("specialist_result_without_refs_or_limitations")
    status = "pass"
    normalized_status = str(child_payload.get("status") or "completed")
    invalid_reasons = {"empty_child_summary", "plan_text_without_evidence", "pseudo_tool_text_without_execution_refs"}
    if any(reason in invalid_reasons for reason in reasons):
        status = "invalid"
        normalized_status = "invalid_output"
    elif reasons:
        status = "warning"
    if limitations and normalized_status == "completed" and not (evidence_refs or artifact_refs):
        normalized_status = "failed"
    return {
        "status": status,
        "reasons": reasons,
        "normalized_status": normalized_status,
    }


def first_text(values: Any) -> str:
    for item in list(values or []):
        text = str(item or "").strip()
        if text:
            return text
    return ""


