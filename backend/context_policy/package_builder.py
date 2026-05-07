from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from context_management import ContextBudget, ContextPackage
from memory_system.runtime_view import MemoryRuntimeView
from memory_system.contracts import MemoryContextCandidate
from token_accounting import count_text_tokens

from .contracts import ContextCandidateDecision, ContextPolicyResult


SECTION_BY_LAYER = {
    "state": "active_process_context",
    "conversation": "hot_truth_window",
    "long_term": "relevant_durable_context",
}

PRIORITY_BY_LAYER = {
    "state": 100,
    "conversation": 70,
    "long_term": 30,
}


@dataclass(slots=True, frozen=True)
class MemoryContextPolicy:
    available_context_tokens: int = 6_000
    reserved_output_tokens: int = 1_200
    static_tokens: int = 0
    retrieval_tokens: int = 0
    long_term_token_cap: int = 1_000

    def build_context_package_result(
        self,
        memory_view: MemoryRuntimeView,
        *,
        rebuild_reason: str = "memory_context_policy_result",
        retrieval_results: list[dict[str, Any]] | None = None,
    ) -> ContextPolicyResult:
        budget = self._budget()
        sorted_candidates = sorted(
            memory_view.context_candidates,
            key=lambda candidate: (
                -_priority(candidate),
                candidate.memory_layer,
                candidate.candidate_id,
            ),
        )
        remaining = max(0, budget.available_context - budget.static - budget.retrieval)
        total_remaining = max(0, budget.available_context - budget.static)
        section_tokens: dict[str, int] = {}
        sections = {
            "static_context": [],
            "active_process_context": [],
            "hot_truth_window": [],
            "retrieval_evidence": [],
            "warm_snapshots": [],
            "exact_durable_context": [],
            "relevant_durable_context": [],
            "debug_session_trace": [],
        }
        debug_sections = {name: list(items) for name, items in sections.items()}
        decisions: list[ContextCandidateDecision] = []
        dropped_items: list[str] = []

        retrieval_render = _render_retrieval_results(
            retrieval_results,
            retrieval_budget=budget.retrieval,
            total_remaining=total_remaining,
        )
        retrieval_items = retrieval_render["items"]
        retrieval_used = int(retrieval_render["used_tokens"])
        total_remaining = max(0, total_remaining - retrieval_used)
        remaining = max(0, total_remaining)
        if retrieval_items:
            sections["retrieval_evidence"].extend(retrieval_items)
            debug_sections["retrieval_evidence"].extend(retrieval_items)
            section_tokens["retrieval_evidence"] = retrieval_used
        for dropped_reason in retrieval_render["dropped_items"]:
            dropped_items.append(str(dropped_reason))

        for candidate in sorted_candidates:
            section_name = SECTION_BY_LAYER.get(candidate.memory_layer, "debug_session_trace")
            tokens = max(1, int(candidate.token_estimate or count_text_tokens(candidate.rendered_preview) or 1))
            allowed, reason = self._can_include(
                candidate,
                section_name=section_name,
                tokens=tokens,
                remaining=remaining,
                section_tokens=section_tokens,
            )
            if allowed:
                rendered = str(candidate.rendered_preview or "").strip()
                if rendered:
                    sections[section_name].append(rendered)
                    debug_sections[section_name].append(
                        self._debug_item(candidate, section_name=section_name, tokens=tokens)
                    )
                    section_tokens[section_name] = section_tokens.get(section_name, 0) + tokens
                    remaining -= tokens
                decisions.append(self._decision(candidate, section_name, "include", reason, tokens))
            else:
                dropped_items.append(f"{candidate.candidate_id}: {reason}")
                decisions.append(self._decision(candidate, section_name, "drop", reason, tokens))

        if memory_view.restore_candidates:
            debug_sections["debug_session_trace"].append(
                f"State restore candidates: {len(memory_view.restore_candidates)} candidate-only hints"
            )

        selected_sections = [name for name, items in sections.items() if items]
        debug_selected_sections = [name for name, items in debug_sections.items() if items]
        token_accounting = {
            "available_context": budget.available_context,
            "reserved_output": budget.reserved_output,
            "retrieval_tokens": section_tokens.get("retrieval_evidence", 0),
            "candidate_tokens_included": sum(section_tokens.values()),
            "candidate_tokens_dropped": sum(
                decision.token_estimate for decision in decisions if decision.decision == "drop"
            ),
            "remaining_context": total_remaining,
        }
        package = ContextPackage(
            pressure_level="normal",
            budget=budget,
            sections=sections,
            model_visible_sections=sections,
            debug_sections=debug_sections,
            selected_sections=selected_sections,
            debug_selected_sections=debug_selected_sections,
            dropped_sections=[],
            dropped_items=dropped_items,
            rebuild_reason=rebuild_reason,
            compaction_strategy="none",
            compaction_decisions=[
                "memory runtime view consumed as candidate-only input",
                "state memory outranks conversation memory; long-term memory is optional and verification-scoped",
            ],
            token_accounting=token_accounting,
        )
        return ContextPolicyResult(
            package=package,
            decisions=tuple(decisions),
            read_only=True,
            diagnostics={
                "memory_runtime_view_ref": memory_view.view_id,
                "context_candidate_count": len(memory_view.context_candidates),
                "restore_candidate_count": len(memory_view.restore_candidates),
                "retrieval_evidence_count": len(retrieval_items),
                "retrieval_evidence_dropped_count": int(retrieval_render["dropped_count"]),
                "included_candidate_count": sum(1 for decision in decisions if decision.decision == "include"),
                "dropped_candidate_count": sum(1 for decision in decisions if decision.decision == "drop"),
                "memory_write_allowed": False,
            },
        )

    def _budget(self) -> ContextBudget:
        available = max(0, self.available_context_tokens)
        retrieval_tokens = max(0, self.retrieval_tokens)
        if available and retrieval_tokens <= 0:
            retrieval_tokens = min(max(400, int(available * 0.2)), 1_200)
        return ContextBudget(
            total=available + max(0, self.reserved_output_tokens),
            reserved_output=max(0, self.reserved_output_tokens),
            available_context=available,
            static=max(0, self.static_tokens),
            active_process=max(600, int(available * 0.35)) if available else 0,
            hot_truth=max(400, int(available * 0.25)) if available else 0,
            warm_snapshots=max(200, int(available * 0.1)) if available else 0,
            durable=min(max(0, self.long_term_token_cap), max(200, int(available * 0.15))) if available else 0,
            retrieval=retrieval_tokens,
        )

    def _can_include(
        self,
        candidate: MemoryContextCandidate,
        *,
        section_name: str,
        tokens: int,
        remaining: int,
        section_tokens: dict[str, int],
    ) -> tuple[bool, str]:
        if candidate.can_override_current_turn:
            return False, "candidate_cannot_override_current_turn"
        if candidate.memory_layer == "long_term":
            used = section_tokens.get(section_name, 0)
            if used + tokens > self.long_term_token_cap:
                return False, "long_term_budget_cap_exceeded"
        if remaining < tokens and candidate.budget_class != "required":
            return False, "context_budget_exceeded"
        if candidate.memory_layer == "state":
            return True, "state_memory_core_context"
        if candidate.memory_layer == "conversation":
            return True, "conversation_memory_continuity_context"
        if candidate.memory_layer == "long_term":
            return True, "long_term_memory_optional_verified_context"
        return False, "unknown_memory_layer"

    def _decision(
        self,
        candidate: MemoryContextCandidate,
        section_name: str,
        decision: str,
        reason: str,
        tokens: int,
    ) -> ContextCandidateDecision:
        return ContextCandidateDecision(
            candidate_id=candidate.candidate_id,
            memory_layer=candidate.memory_layer,
            target_section=section_name,
            decision=decision,  # type: ignore[arg-type]
            reason=reason,
            token_estimate=tokens,
            priority=_priority(candidate),
            budget_class=candidate.budget_class,
            requires_verification_before_use=candidate.requires_verification_before_use,
            metadata={
                "source": candidate.source,
                "content_ref": candidate.content_ref,
                "staleness": candidate.staleness,
            },
        )

    def _debug_item(self, candidate: MemoryContextCandidate, *, section_name: str, tokens: int) -> str:
        return (
            f"[{candidate.memory_layer} -> {section_name}] {candidate.candidate_id} "
            f"tokens={tokens} source={candidate.source}\n{candidate.rendered_preview}"
        )


def build_context_package_result(
    memory_view: MemoryRuntimeView,
    *,
    rebuild_reason: str = "memory_context_policy_result",
    retrieval_results: list[dict[str, Any]] | None = None,
    available_context_tokens: int = 6_000,
    reserved_output_tokens: int = 1_200,
    long_term_token_cap: int = 1_000,
) -> ContextPolicyResult:
    return MemoryContextPolicy(
        available_context_tokens=available_context_tokens,
        reserved_output_tokens=reserved_output_tokens,
        long_term_token_cap=long_term_token_cap,
    ).build_context_package_result(
        memory_view,
        rebuild_reason=rebuild_reason,
        retrieval_results=retrieval_results,
    )


def _priority(candidate: MemoryContextCandidate) -> int:
    base = PRIORITY_BY_LAYER.get(candidate.memory_layer, 0)
    if candidate.budget_class == "required":
        base += 20
    elif candidate.budget_class == "preferred":
        base += 10
    return base


def _render_retrieval_results(
    retrieval_results: list[dict[str, Any]] | None,
    *,
    retrieval_budget: int,
    total_remaining: int,
) -> dict[str, Any]:
    rendered: list[str] = []
    dropped_items: list[str] = []
    remaining = max(0, min(retrieval_budget, total_remaining))
    used_tokens = 0
    for index, item in enumerate(list(retrieval_results or [])[:8]):
        if not isinstance(item, dict):
            continue
        title = str(
            item.get("title")
            or item.get("source")
            or item.get("path")
            or item.get("document")
            or f"retrieval-{index + 1}"
        ).strip()
        text = str(
            item.get("content")
            or item.get("text")
            or item.get("snippet")
            or item.get("summary")
            or ""
        ).strip()
        if not text:
            continue
        rendered_item = f"{title}: {text[:600].strip()}"
        tokens = _estimate_tokens(rendered_item)
        if tokens > remaining:
            dropped_items.append(f"retrieval:{index + 1}: retrieval_budget_exceeded")
            continue
        rendered.append(rendered_item)
        used_tokens += tokens
        remaining = max(0, remaining - tokens)
    return {
        "items": rendered,
        "used_tokens": used_tokens,
        "dropped_count": len(dropped_items),
        "dropped_items": dropped_items,
    }


def _estimate_tokens(text: str) -> int:
    return count_text_tokens(text)
