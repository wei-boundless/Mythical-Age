from __future__ import annotations

from typing import Any


TOOL_TRANSCRIPT_CALL_KIND = "single_agent_turn_tool_call"
TOOL_TRANSCRIPT_DELTA_KIND = "tool_transcript_delta"

# Historical provider-visible entries may still carry these kinds. They are
# only valid when detecting/replaying already sealed bytes.
HISTORICAL_TOOL_TRANSCRIPT_RESULT_KINDS = frozenset(
    {
        "single_agent_turn_tool_observation",
        "tool_observations",
    }
)

CURRENT_TOOL_TRANSCRIPT_KINDS = frozenset(
    {
        TOOL_TRANSCRIPT_CALL_KIND,
        TOOL_TRANSCRIPT_DELTA_KIND,
    }
)


def is_current_tool_transcript_kind(kind: Any) -> bool:
    return str(kind or "").strip() in CURRENT_TOOL_TRANSCRIPT_KINDS


def is_historical_tool_transcript_kind(kind: Any) -> bool:
    return str(kind or "").strip() in HISTORICAL_TOOL_TRANSCRIPT_RESULT_KINDS


def is_tool_transcript_kind(kind: Any, *, include_historical: bool = False) -> bool:
    normalized = str(kind or "").strip()
    if normalized in CURRENT_TOOL_TRANSCRIPT_KINDS:
        return True
    return include_historical and normalized in HISTORICAL_TOOL_TRANSCRIPT_RESULT_KINDS
