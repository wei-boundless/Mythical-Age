from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


OutputChannel = Literal[
    "progress_text",
    "procedural_promise",
    "tool_claim_without_receipt",
    "tool_raw_output",
    "tool_visible_summary",
    "answer_candidate",
    "fallback_answer",
]

CanonicalState = Literal[
    "stable_answer",
    "unstable_answer",
    "progress_only",
    "tool_summary",
    "missing_answer",
]

PersistPolicy = Literal[
    "persist_canonical",
    "persist_debug_only",
    "do_not_persist",
]

FinalizationPolicy = Literal[
    "none",
    "route_optional",
    "route_required",
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
    canonical_state: CanonicalState = "missing_answer"
    persist_policy: PersistPolicy = "do_not_persist"
    finalization_policy: FinalizationPolicy = "none"
    rejected_candidates: list[OutputCandidate] = field(default_factory=list)
    leak_flags: list[str] = field(default_factory=list)
    fallback_reason: str = ""


@dataclass(slots=True)
class ToolResultEnvelope:
    tool_name: str
    raw_text: str
    display_text: str
    display_mode: str
    finalization_policy: str = "none"
    persistence_policy: str = "persist_canonical"
    allow_unlabeled_answer: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


