from __future__ import annotations

from typing import Any

from intent.models import IntentDecision

from .models import ContinuationCandidate, ContinuationDecision
from .profile_registry import profile_by_domain


def decide_continuation(
    *,
    candidates: tuple[ContinuationCandidate, ...],
    intent_decision: IntentDecision,
) -> ContinuationDecision:
    if not intent_decision.needs_continuation:
        return ContinuationDecision(reason="intent_does_not_require_continuation")
    compatible = [candidate for candidate in candidates if candidate.compatible]
    rejected = [candidate.candidate_id for candidate in candidates if not candidate.compatible]
    if not compatible:
        return ContinuationDecision(
            decision_kind="clarify",
            confidence=0.0,
            reason="没有找到与当前语义兼容的续接候选；旧状态只保留为诊断证据。",
            rejected_candidate_ids=tuple(rejected),
            diagnostics={"candidate_count": len(candidates), "compatible_candidate_count": 0},
        )
    selected = max(compatible, key=lambda candidate: candidate.score)
    followup_target_kind = _followup_target_kind(selected)
    followup_scope = "active_subset" if followup_target_kind == "active_subset" else "active_object"
    bindings = _active_bindings(selected)
    target_refs = _target_refs(selected, bindings)
    return ContinuationDecision(
        decision_kind="selected",
        selected_candidate_id=selected.candidate_id,
        selected_target_kind=selected.target_kind,
        source_kind=selected.source_kind,
        followup_target_kind=followup_target_kind,
        followup_scope=followup_scope,
        followup_target_refs=tuple(target_refs),
        constraint_policy=(
            "result_subset_only_do_not_expand_to_full_object"
            if followup_target_kind == "active_subset"
            else "active_object_followup"
        ),
        active_bindings=bindings,
        confidence=min(max(float(selected.score or 0.0) / 100.0, 0.45), 0.96),
        reason=f"选择 {selected.source_kind} 候选 {selected.identity or selected.candidate_id}，因为它与当前动作 {intent_decision.primary_action} 兼容。",
        rejected_candidate_ids=tuple(rejected),
        diagnostics={
            "candidate_count": len(candidates),
            "compatible_candidate_count": len(compatible),
            "selected_score": selected.score,
            "selected_source": selected.source,
        },
    )


def _followup_target_kind(candidate: ContinuationCandidate) -> str:
    profile = profile_by_domain().get(str(candidate.metadata.get("profile_id") or candidate.source_kind))
    if candidate.target_kind == "result_subset":
        return str(getattr(profile, "subset_followup_target_kind", "") or "active_subset")
    profile_target = str(getattr(profile, "followup_target_kind", "") or "").strip()
    if profile_target:
        return profile_target
    return candidate.source_kind


def _active_bindings(candidate: ContinuationCandidate) -> dict[str, Any]:
    payload = dict(candidate.binding_payload or {})
    profile = profile_by_domain().get(str(candidate.metadata.get("profile_id") or candidate.source_kind))
    binding_key = str(getattr(profile, "binding_key", "") or f"active_{candidate.source_kind}").strip()
    if binding_key:
        path = str(payload.get(binding_key) or payload.get("path") or candidate.identity or "").strip()
        if path and candidate.target_kind == "source_object":
            payload[binding_key] = path
            payload.setdefault("path", path)
    payload["selected_candidate_id"] = candidate.candidate_id
    payload["selected_candidate_source"] = candidate.source
    payload["selected_target_kind"] = candidate.target_kind
    if profile is not None:
        if profile.delegation_kind:
            payload.setdefault("delegation_kind", profile.delegation_kind)
        if profile.target_agent_id:
            payload.setdefault("target_agent_id", profile.target_agent_id)
        if profile.return_contract:
            payload.setdefault("return_contract", dict(profile.return_contract))
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _target_refs(candidate: ContinuationCandidate, bindings: dict[str, Any]) -> list[str]:
    refs = [
        str(bindings.get("active_subset_handle_id") or "").strip(),
        str(bindings.get("active_result_handle_id") or bindings.get("result_handle_id") or "").strip(),
        str(bindings.get("active_object_handle_id") or "").strip(),
    ]
    if candidate.target_kind in {"task_result", "bundle_result"}:
        refs.append(str(candidate.identity or "").strip())
    return _dedupe(refs)


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
