from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import estimate_chars


@dataclass(frozen=True, slots=True)
class DynamicTokenBudget:
    invocation_kind: str
    volatile_char_budget: int
    warning_ratio: float = 0.9
    authority: str = "harness.runtime.dynamic_context.token_budget"


DEFAULT_VOLATILE_BUDGETS = {
    "single_agent_turn": 6000,
    "tool_observation_followup": 4000,
    "task_execution": 8000,
}


def budget_for_invocation(invocation_kind: str, policy: dict[str, Any] | None = None) -> DynamicTokenBudget:
    payload = dict(policy or {})
    budgets = dict(payload.get("volatile_char_budgets") or {})
    default_budget = DEFAULT_VOLATILE_BUDGETS.get(str(invocation_kind or ""), 6000)
    value = budgets.get(invocation_kind, payload.get("volatile_char_budget", default_budget))
    return DynamicTokenBudget(
        invocation_kind=str(invocation_kind or ""),
        volatile_char_budget=max(1000, int(value or default_budget)),
    )


def build_budget_report(
    *,
    invocation_kind: str,
    projection_policy: dict[str, Any] | None,
    volatile_payload: dict[str, Any],
    dynamic_payload: dict[str, Any],
) -> dict[str, Any]:
    budget = budget_for_invocation(invocation_kind, projection_policy)
    volatile_chars = estimate_chars(volatile_payload)
    dynamic_chars = estimate_chars(dynamic_payload)
    return {
        "authority": budget.authority,
        "invocation_kind": budget.invocation_kind,
        "volatile_char_budget": budget.volatile_char_budget,
        "volatile_chars": volatile_chars,
        "dynamic_chars": dynamic_chars,
        "budget_status": "over_budget" if volatile_chars > budget.volatile_char_budget else "ok",
        "warning": volatile_chars >= int(budget.volatile_char_budget * budget.warning_ratio),
    }
