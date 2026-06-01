from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..context_budget_policy import build_model_aware_context_budget_policy
from .models import estimate_chars


@dataclass(frozen=True, slots=True)
class DynamicTokenBudget:
    invocation_kind: str
    volatile_char_budget: int
    warning_ratio: float = 0.9
    authority: str = "harness.runtime.dynamic_context.token_budget"


FALLBACK_VOLATILE_CHAR_BUDGET = 128_000


def budget_for_invocation(invocation_kind: str, policy: dict[str, Any] | None = None) -> DynamicTokenBudget:
    payload = dict(policy or {})
    context_policy = _context_policy_for_invocation(invocation_kind, payload)
    budgets = dict(payload.get("volatile_char_budgets") or {})
    default_budget = int(context_policy.get("volatile_char_budget") or FALLBACK_VOLATILE_CHAR_BUDGET)
    value = (
        context_policy.get("volatile_char_budget")
        or budgets.get(invocation_kind)
        or payload.get("volatile_char_budget")
        or default_budget
    )
    return DynamicTokenBudget(
        invocation_kind=str(invocation_kind or ""),
        volatile_char_budget=max(1000, int(value or default_budget)),
    )


def _context_policy_for_invocation(invocation_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    context_policy = dict(payload.get("context_budget_policy") or {})
    if context_policy:
        return context_policy
    try:
        return build_model_aware_context_budget_policy(invocation_kind=str(invocation_kind or "")).to_dict()
    except Exception:
        return {"volatile_char_budget": FALLBACK_VOLATILE_CHAR_BUDGET}


def build_budget_report(
    *,
    invocation_kind: str,
    projection_policy: dict[str, Any] | None,
    volatile_payload: dict[str, Any],
    dynamic_payload: dict[str, Any],
) -> dict[str, Any]:
    budget = budget_for_invocation(invocation_kind, projection_policy)
    context_policy = _context_policy_for_invocation(invocation_kind, dict(projection_policy or {}))
    volatile_chars = estimate_chars(volatile_payload)
    dynamic_chars = estimate_chars(dynamic_payload)
    return {
        "authority": budget.authority,
        "invocation_kind": budget.invocation_kind,
        "volatile_char_budget": budget.volatile_char_budget,
        "context_budget_policy": context_policy,
        "allocation_tokens": dict(context_policy.get("allocation_tokens") or {}),
        "projection_limits": dict(context_policy.get("projection_limits") or {}),
        "volatile_chars": volatile_chars,
        "dynamic_chars": dynamic_chars,
        "budget_status": "over_budget" if volatile_chars > budget.volatile_char_budget else "ok",
        "warning": volatile_chars >= int(budget.volatile_char_budget * budget.warning_ratio),
    }
