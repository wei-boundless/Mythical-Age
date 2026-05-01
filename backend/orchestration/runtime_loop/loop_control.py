from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import RuntimeLoopState, RuntimeTerminalReason


@dataclass(frozen=True, slots=True)
class RuntimeLoopLimits:
    """Hard stop limits for one TaskRunLoop execution."""

    max_turns: int = 8
    max_model_calls: int = 8
    max_runtime_seconds: float = 300.0
    max_events: int = 200
    authority: str = "orchestration.runtime_loop_limits"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.runtime_loop_limits":
            raise ValueError("RuntimeLoopLimits authority must be orchestration.runtime_loop_limits")
        if self.max_turns < 1:
            raise ValueError("RuntimeLoopLimits.max_turns must be positive")
        if self.max_model_calls < 1:
            raise ValueError("RuntimeLoopLimits.max_model_calls must be positive")
        if self.max_runtime_seconds <= 0:
            raise ValueError("RuntimeLoopLimits.max_runtime_seconds must be positive")
        if self.max_events < 1:
            raise ValueError("RuntimeLoopLimits.max_events must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeLoopControlDecision:
    allowed: bool
    reason: RuntimeTerminalReason = ""
    message: str = ""
    snapshot: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.runtime_loop_control"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.runtime_loop_control":
            raise ValueError("RuntimeLoopControlDecision authority must be orchestration.runtime_loop_control")
        if not self.allowed and not self.reason:
            raise ValueError("blocked RuntimeLoopControlDecision requires reason")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_runtime_loop_control(
    state: RuntimeLoopState,
    *,
    limits: RuntimeLoopLimits,
    started_at: float,
    model_call_count: int,
    event_count: int,
) -> RuntimeLoopControlDecision:
    elapsed_seconds = max(0.0, time.time() - started_at)
    snapshot = {
        "task_run_id": state.task_run_id,
        "status": state.status,
        "transition": state.transition,
        "turn_count": state.turn_count,
        "step_count": state.step_count,
        "model_call_count": model_call_count,
        "event_count": event_count,
        "elapsed_seconds": elapsed_seconds,
        "limits": limits.to_dict(),
    }
    if state.turn_count > limits.max_turns:
        return RuntimeLoopControlDecision(
            allowed=False,
            reason="max_turns",
            message="RuntimeLoop reached max_turns before the next dispatch.",
            snapshot=snapshot,
        )
    if model_call_count >= limits.max_model_calls:
        return RuntimeLoopControlDecision(
            allowed=False,
            reason="budget_exhausted",
            message="RuntimeLoop reached max_model_calls before the next dispatch.",
            snapshot=snapshot,
        )
    if elapsed_seconds > limits.max_runtime_seconds:
        return RuntimeLoopControlDecision(
            allowed=False,
            reason="budget_exhausted",
            message="RuntimeLoop reached max_runtime_seconds before the next dispatch.",
            snapshot=snapshot,
        )
    if event_count >= limits.max_events:
        return RuntimeLoopControlDecision(
            allowed=False,
            reason="budget_exhausted",
            message="RuntimeLoop reached max_events before the next dispatch.",
            snapshot=snapshot,
        )
    return RuntimeLoopControlDecision(
        allowed=True,
        message="RuntimeLoop control limits allow the next dispatch.",
        snapshot=snapshot,
    )
