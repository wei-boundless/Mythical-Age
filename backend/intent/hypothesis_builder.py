from __future__ import annotations

from .models import IntentDecision, IntentFrame


def decide_intent(frame: IntentFrame) -> IntentDecision:
    actions = tuple(frame.action_hypotheses or ("start_new",))
    primary = _primary_action(actions)
    non_memory_domains = [item for item in frame.target_domain_hints if item not in {"memory"}]
    target_domain = "mixed_sources" if {"dataset", "pdf"} <= set(non_memory_domains) else next(iter(non_memory_domains), "")
    strategy = next(iter(frame.execution_strategy_candidates or ("single_react_loop",)), "single_react_loop")
    needs_continuation = any(action in actions for action in ("continue", "refine_scope")) and primary not in {
        "recall_memory",
        "retrieve_knowledge",
    }
    return IntentDecision(
        primary_action=primary,
        actions=actions,
        target_domain_hint=target_domain,
        needs_continuation=needs_continuation,
        retrieval_required=primary == "retrieve_knowledge",
        memory_recall_required=primary == "recall_memory",
        execution_strategy=strategy,
        confidence=_confidence(actions=actions, target_domain=target_domain),
        reason=_reason(primary=primary, actions=actions, target_domain=target_domain, strategy=strategy),
        diagnostics={
            "source": "intent.hypothesis_builder",
            "task_complexity": frame.task_complexity,
            "strategy_candidates": list(frame.execution_strategy_candidates),
        },
    )


def _primary_action(actions: tuple[str, ...]) -> str:
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
