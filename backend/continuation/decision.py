from __future__ import annotations

from .models import ContinuationCandidate, ContinuationDecision
from .profile_registry import profile_by_domain


def decide_continuation(
    *,
    candidates: tuple[ContinuationCandidate, ...],
    request_intent,
) -> ContinuationDecision:
    if not candidates:
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
    target_refs = _target_refs(selected)
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
        confidence=min(max(float(selected.score or 0.0) / 100.0, 0.45), 0.96),
        reason=f"选择 {selected.source_kind} 候选 {selected.identity or selected.candidate_id}，因为它与当前续接候选兼容。",
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


def _target_refs(candidate: ContinuationCandidate) -> list[str]:
    payload = dict(candidate.recall_payload or {})
    refs = [
        str(payload.get("active_subset_handle_id") or "").strip(),
        str(payload.get("active_result_handle_id") or payload.get("result_handle_id") or "").strip(),
        str(payload.get("active_object_handle_id") or "").strip(),
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
