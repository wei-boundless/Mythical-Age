from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


OutputChannel = Literal[
    "progress_text",
    "tool_raw_output",
    "tool_visible_summary",
    "answer_candidate",
    "fallback_answer",
]


@dataclass(slots=True)
class OutputCandidate:
    channel: OutputChannel
    text: str
    source: str
    route: str = ""
    tool_name: str = ""
    task_id: str = ""
    priority_hint: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutputDecision:
    canonical_answer: str
    selected_channel: OutputChannel
    selected_source: str
    rejected_candidates: list[OutputCandidate] = field(default_factory=list)
    leak_flags: list[str] = field(default_factory=list)
    fallback_reason: str = ""
