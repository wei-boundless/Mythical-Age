from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from runtime.tool_runtime.provider_tool_call_adapter import tool_calls_for_langchain_messages

from .final_output import (
    build_answer_readiness_judge_message,
    build_repeated_tool_halt_message,
    build_runtime_budget_exhausted_message,
    forced_synthesis_answer_metadata,
    forced_tool_synthesis_from_available_evidence,
    repeated_tool_halt_answer_metadata,
    runtime_budget_exhausted_answer_metadata,
    should_force_answer_after_tool_results,
)


@dataclass(frozen=True, slots=True)
class FollowupFinalization:
    finalized: bool
    content: str = ""
    answer_metadata: dict[str, Any] | None = None
    source: str = ""


def build_initial_followup_messages(
    *,
    context_model_messages: list[Any],
    tool_call_accumulator: Any,
    tool_messages: list[ToolMessage],
    user_message: str,
    aggregation: Any,
    current_bundle_items: list[dict[str, Any]],
    remaining_model_calls: int,
) -> list[Any]:
    if not getattr(tool_call_accumulator, "pending_tool_calls", None) or not tool_messages:
        return []
    followup_messages: list[Any] = [
        *list(context_model_messages),
        _assistant_message_from_tool_calls(tool_call_accumulator),
        *list(tool_messages),
    ]
    readiness_message = build_answer_readiness_judge_message(
        user_message=user_message,
        aggregation=aggregation,
        current_bundle_items=current_bundle_items,
        remaining_model_calls=max(int(remaining_model_calls or 0), 0),
    )
    if readiness_message:
        followup_messages.append(SystemMessage(content=readiness_message))
    return followup_messages


def build_next_followup_messages(
    *,
    previous_messages: list[Any],
    tool_call_accumulator: Any,
    tool_messages: list[ToolMessage],
    user_message: str,
    aggregation: Any,
    current_bundle_items: list[dict[str, Any]],
    remaining_model_calls: int,
) -> list[Any]:
    if not getattr(tool_call_accumulator, "pending_tool_calls", None) or not tool_messages:
        return []
    next_messages: list[Any] = [
        *list(previous_messages),
        _assistant_message_from_tool_calls(tool_call_accumulator),
        *list(tool_messages),
    ]
    readiness_message = build_answer_readiness_judge_message(
        user_message=user_message,
        aggregation=aggregation,
        current_bundle_items=current_bundle_items,
        remaining_model_calls=max(int(remaining_model_calls or 0), 0),
    )
    if readiness_message:
        next_messages.append(SystemMessage(content=readiness_message))
    return next_messages


def finalize_budget_exhausted_followup(
    *,
    user_message: str,
    aggregation: Any,
    final_task_summary_refs: list[dict[str, Any]],
    final_main_context: dict[str, Any],
    control_message: str,
    tool_observation_count: int,
) -> FollowupFinalization:
    synthesized = forced_tool_synthesis_from_available_evidence(
        user_message=user_message,
        aggregation=aggregation,
        final_task_summary_refs=final_task_summary_refs,
        final_main_context=final_main_context,
    )
    if synthesized:
        return FollowupFinalization(
            finalized=True,
            content=synthesized,
            answer_metadata=forced_synthesis_answer_metadata(
                source="runtime_loop.budget_exhausted_force_synthesis"
            ),
            source="budget_exhausted_force_synthesis",
        )
    return FollowupFinalization(
        finalized=True,
        content=build_runtime_budget_exhausted_message(
            control_message,
            tool_observation_count=tool_observation_count,
        ),
        answer_metadata=runtime_budget_exhausted_answer_metadata(),
        source="budget_exhausted_fallback",
    )


def finalize_after_followup_tool_results(
    *,
    user_message: str,
    aggregation: Any,
    final_task_summary_refs: list[dict[str, Any]],
    final_main_context: dict[str, Any],
    repeated_tool_halt: bool,
    final_content: str,
    tool_observation_count: int,
    retrieval_followup_force_synthesis: bool,
) -> FollowupFinalization:
    if should_force_answer_after_tool_results(
        aggregation=aggregation,
        final_task_summary_refs=final_task_summary_refs,
        final_main_context=final_main_context,
    ):
        synthesized = forced_tool_synthesis_from_available_evidence(
            user_message=user_message,
            aggregation=aggregation,
            final_task_summary_refs=final_task_summary_refs,
            final_main_context=final_main_context,
        )
        if synthesized:
            return FollowupFinalization(
                finalized=True,
                content=synthesized,
                answer_metadata=forced_synthesis_answer_metadata(
                    source="runtime_loop.post_tool_judgement_force_synthesis"
                ),
                source="post_tool_judgement_force_synthesis",
            )
    if retrieval_followup_force_synthesis:
        synthesized = forced_tool_synthesis_from_available_evidence(
            user_message=user_message,
            aggregation=aggregation,
            final_task_summary_refs=final_task_summary_refs,
            final_main_context=final_main_context,
        )
        if synthesized:
            return FollowupFinalization(
                finalized=True,
                content=synthesized,
                answer_metadata=forced_synthesis_answer_metadata(
                    source="runtime_loop.retrieval_followup_force_synthesis"
                ),
                source="retrieval_followup_force_synthesis",
            )
    if repeated_tool_halt and final_content:
        return FollowupFinalization(
            finalized=True,
            content=final_content,
            answer_metadata=None,
            source="repeated_tool_halt_existing_answer",
        )
    if repeated_tool_halt:
        synthesized = forced_tool_synthesis_from_available_evidence(
            user_message=user_message,
            aggregation=aggregation,
            final_task_summary_refs=final_task_summary_refs,
            final_main_context=final_main_context,
        )
        if synthesized:
            return FollowupFinalization(
                finalized=True,
                content=synthesized,
                answer_metadata=forced_synthesis_answer_metadata(source="runtime_loop.repeated_tool_halt"),
                source="repeated_tool_halt_synthesis",
            )
        return FollowupFinalization(
            finalized=True,
            content=build_repeated_tool_halt_message(tool_observation_count=tool_observation_count),
            answer_metadata=repeated_tool_halt_answer_metadata(),
            source="repeated_tool_halt_fallback",
        )
    return FollowupFinalization(finalized=False)


def _assistant_message_from_tool_calls(tool_call_accumulator: Any) -> AIMessage:
    return AIMessage(
        content=str(getattr(tool_call_accumulator, "assistant_content", "") or ""),
        tool_calls=tool_calls_for_langchain_messages(
            list(getattr(tool_call_accumulator, "pending_tool_calls", []) or [])
        ),
        additional_kwargs=dict(getattr(tool_call_accumulator, "assistant_additional_kwargs", {}) or {}),
    )
