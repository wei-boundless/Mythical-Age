from __future__ import annotations

from .models import IntentDecision, IntentFrame


def decide_intent(frame: IntentFrame) -> IntentDecision:
    actions = tuple(frame.action_hypotheses or ("start_new",))
    non_memory_domains = [item for item in frame.target_domain_hints if item not in {"memory"}]
    target_domain = "mixed_sources" if {"dataset", "pdf"} <= set(non_memory_domains) else next(iter(non_memory_domains), "")
    primary = _primary_action(actions, target_domain=target_domain, evidence=frame.evidence)
    strategy = next(iter(frame.execution_strategy_candidates or ("single_react_loop",)), "single_react_loop")
    needs_continuation = _needs_continuation(actions=actions, primary=primary, target_domain=target_domain, evidence=frame.evidence)
    return IntentDecision(
        primary_action=primary,
        actions=actions,
        target_domain_hint=target_domain,
        needs_continuation=needs_continuation,
        retrieval_required=primary == "retrieve_knowledge",
        memory_recall_required=primary == "recall_memory" and not needs_continuation,
        execution_strategy=strategy,
        confidence=_confidence(actions=actions, target_domain=target_domain),
        reason=_reason(primary=primary, actions=actions, target_domain=target_domain, strategy=strategy),
        diagnostics={
            "source": "intent.hypothesis_builder",
            "task_complexity": frame.task_complexity,
            "strategy_candidates": list(frame.execution_strategy_candidates),
            "user_message": frame.user_message,
        },
    )


def _primary_action(actions: tuple[str, ...], *, target_domain: str, evidence: dict[str, object]) -> str:
    if _has_object_continuation(actions=actions, target_domain=target_domain, evidence=evidence):
        if "refine_scope" in actions:
            return "refine_scope"
        return "continue"
    for action in ("recall_memory", "retrieve_knowledge", "switch_target"):
        if action in actions:
            return action
    if "refine_scope" in actions and "continue" in actions:
        return "refine_scope"
    if "continue" in actions:
        return "continue"
    if "delegate_work" in actions:
        return "delegate_work"
    return actions[0] if actions else "start_new"


def _needs_continuation(
    *,
    actions: tuple[str, ...],
    primary: str,
    target_domain: str,
    evidence: dict[str, object],
) -> bool:
    if _has_object_continuation(actions=actions, target_domain=target_domain, evidence=evidence):
        return True
    return False


def _has_object_continuation(*, actions: tuple[str, ...], target_domain: str, evidence: dict[str, object]) -> bool:
    if bool(evidence.get("explicit_target")) or "switch_target" in actions:
        return False
    if bool(evidence.get("weather_domain")) or bool(evidence.get("gold_price_domain")) or bool(evidence.get("external_requirement")):
        return False
    if target_domain not in {"dataset", "pdf", "mixed_sources", "workflow_graph"}:
        return False
    if not any(action in actions for action in ("continue", "refine_scope")):
        return False
    return bool(evidence.get("continuation_language")) and _has_source_candidate(evidence)


def _has_source_candidate(evidence: dict[str, object]) -> bool:
    return any(
        _safe_int(evidence.get(key)) > 0
        for key in (
            "state_candidate_count",
            "restore_candidate_count",
            "task_summary_candidate_count",
            "context_candidate_count",
        )
    )


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _confidence(*, actions: tuple[str, ...], target_domain: str) -> float:
    score = 0.62
    if target_domain:
        score += 0.12
    if "switch_target" in actions or "recall_memory" in actions or "retrieve_knowledge" in actions:
        score += 0.18
    if "continue" in actions and "refine_scope" in actions:
        score += 0.12
    return min(score, 0.96)


def _reason(*, primary: str, actions: tuple[str, ...], target_domain: str, strategy: str) -> str:
    target = f"，目标域倾向 {target_domain}" if target_domain else ""
    return f"当前 turn 的主动作是 {primary}{target}；候选动作={','.join(actions)}；建议执行策略={strategy}。"
