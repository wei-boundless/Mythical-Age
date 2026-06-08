from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prompt_cache_policy import is_cache_eligible_prefix

from .models import PromptSegment


@dataclass(frozen=True, slots=True)
class CompressionBudgetDecision:
    decision: str
    before_tokens: int
    hard_required_tokens: int
    compressible_tokens: int
    compressible_budget: int
    target_compressible_tokens: int
    required_reduction_tokens: int
    over_budget_tokens: int
    preserved_segments: tuple[str, ...]
    compressible_segments: tuple[str, ...]
    summarized_segments: tuple[str, ...]
    dropped_segments: tuple[str, ...]
    cache_impact: str
    cache_impact_tiers: dict[str, str]
    summary_target_tokens: int
    strategy: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "before_tokens": self.before_tokens,
            "hard_required_tokens": self.hard_required_tokens,
            "compressible_tokens": self.compressible_tokens,
            "compressible_budget": self.compressible_budget,
            "target_compressible_tokens": self.target_compressible_tokens,
            "required_reduction_tokens": self.required_reduction_tokens,
            "over_budget_tokens": self.over_budget_tokens,
            "preserved_segments": list(self.preserved_segments),
            "compressible_segments": list(self.compressible_segments),
            "summarized_segments": list(self.summarized_segments),
            "dropped_segments": list(self.dropped_segments),
            "cache_impact": self.cache_impact,
            "cache_impact_tiers": dict(self.cache_impact_tiers),
            "summary_target_tokens": self.summary_target_tokens,
            "strategy": self.strategy,
        }


class CompressionBudgetPlanner:
    """Segment-aware compression budget planner.

    Existing compactors can use this without becoming token authorities: the
    segment map supplies the token facts, this planner only derives a budget.
    """

    def plan(
        self,
        segments: list[PromptSegment] | tuple[PromptSegment, ...],
        *,
        context_window_tokens: int,
        reserved_output_tokens: int,
    ) -> CompressionBudgetDecision:
        items = list(segments or [])
        before_tokens = sum(int(item.predicted_tokens or 0) for item in items)
        preserved = [item for item in items if self._is_hard_required(item)]
        hard_required = sum(int(item.predicted_tokens or 0) for item in preserved)
        available_context = max(0, int(context_window_tokens or 0) - int(reserved_output_tokens or 0))
        compressible_budget = max(0, available_context - hard_required)
        preserved_ids = {preserved_item.segment_id for preserved_item in preserved}
        compressible = [item for item in items if item.segment_id not in preserved_ids]
        dropped = [item for item in compressible if item.compression_role == "drop_if_cold"]
        summarized = [item for item in compressible if item.compression_role != "drop_if_cold"]
        compressible_tokens = sum(int(item.predicted_tokens or 0) for item in compressible)
        over_budget_tokens = max(0, before_tokens - available_context)
        target_compressible_tokens = min(compressible_tokens, compressible_budget)
        required_reduction_tokens = max(0, compressible_tokens - target_compressible_tokens)
        if before_tokens <= available_context:
            decision = "no_compaction"
        elif compressible_budget > 0 and target_compressible_tokens > 0:
            decision = "microcompact"
        else:
            decision = "fail_closed"
        strategy = self._strategy(
            decision=decision,
            dropped=dropped,
            summarized=summarized,
            required_reduction_tokens=required_reduction_tokens,
        )
        cache_impact_tiers = self._cache_impact_tiers(compressible)
        cache_impact = cache_impact_tiers.get("provider_global") or "preserved"
        summary_target_tokens = self._summary_target_tokens(
            compressible_budget=compressible_budget,
            compressible_tokens=compressible_tokens,
            hard_required_tokens=hard_required,
        )
        return CompressionBudgetDecision(
            decision=decision,
            before_tokens=before_tokens,
            hard_required_tokens=hard_required,
            compressible_tokens=compressible_tokens,
            compressible_budget=compressible_budget,
            target_compressible_tokens=target_compressible_tokens,
            required_reduction_tokens=required_reduction_tokens,
            over_budget_tokens=over_budget_tokens,
            preserved_segments=tuple(item.segment_id for item in preserved),
            compressible_segments=tuple(item.segment_id for item in compressible),
            summarized_segments=tuple(item.segment_id for item in summarized),
            dropped_segments=tuple(item.segment_id for item in dropped),
            cache_impact=cache_impact,
            cache_impact_tiers=cache_impact_tiers,
            summary_target_tokens=summary_target_tokens,
            strategy=strategy,
        )

    def _is_hard_required(self, segment: PromptSegment) -> bool:
        authority_class = str(getattr(segment, "authority_class", "") or dict(getattr(segment, "metadata", {}) or {}).get("authority_class") or "")
        if authority_class in {
            "contract",
            "permission",
            "current_user_intent",
            "runtime_state",
            "evidence_ref",
        }:
            return True
        if segment.compression_role == "preserve":
            return True
        if str(segment.cache_role or "").strip() == "session_stable":
            return True
        if is_cache_eligible_prefix(
            cache_role=segment.cache_role,
            prefix_tier=getattr(segment, "prefix_tier", ""),
        ):
            return True
        return False

    def _strategy(
        self,
        *,
        decision: str,
        dropped: list[PromptSegment],
        summarized: list[PromptSegment],
        required_reduction_tokens: int,
    ) -> str:
        if decision == "no_compaction":
            return "none"
        if decision == "fail_closed":
            return "blocking_required"
        if dropped:
            return "ref_projection"
        if summarized and required_reduction_tokens > 0:
            return "session_memory_compact"
        return "microcompact"

    def _cache_impact(self, compressible: list[PromptSegment]) -> str:
        return self._cache_impact_tiers(compressible).get("provider_global", "preserved")

    def _cache_impact_tiers(self, compressible: list[PromptSegment]) -> dict[str, str]:
        tiers = {str(getattr(item, "prefix_tier", "") or "none") for item in compressible}
        return {
            "provider_global": "global_invalidated" if "provider_global" in tiers else "preserved",
            "session": "session_rebuilt" if "session" in tiers else "preserved",
            "task": "task_rebuilt" if "task" in tiers else "preserved",
            "volatile": "volatile_preserved" if "volatile" in tiers else "preserved",
        }

    def _summary_target_tokens(
        self,
        *,
        compressible_budget: int,
        compressible_tokens: int,
        hard_required_tokens: int,
    ) -> int:
        if compressible_tokens <= 0 or compressible_budget <= 0:
            return 0
        # Reserve most post-compact budget for hard-required context and the
        # live tail; the handoff summary should be dense, not a second history.
        ceiling = max(160, min(1400, int(compressible_budget * 0.35)))
        floor = 120 if hard_required_tokens else 80
        return max(floor, min(ceiling, compressible_tokens))
