from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.shared.models import RuntimeTerminalReason

from .state import HarnessLoopState


@dataclass(frozen=True, slots=True)
class HarnessLoopLimits:
    """Hard stop limits for one Harness loop execution."""

    max_turns: int = 8
    max_model_calls: int = 8
    max_runtime_seconds: float | None = 300.0
    max_events: int = 200
    authority: str = "harness.loop_limits"

    def __post_init__(self) -> None:
        if self.authority not in {"harness.loop_limits", "runtime_limits"}:
            raise ValueError("HarnessLoopLimits authority must be harness.loop_limits")
        if self.authority == "runtime_limits":
            object.__setattr__(self, "authority", "harness.loop_limits")
        if self.max_turns < 1:
            raise ValueError("HarnessLoopLimits.max_turns must be positive")
        if self.max_model_calls < 1:
            raise ValueError("HarnessLoopLimits.max_model_calls must be positive")
        if self.max_runtime_seconds is not None and self.max_runtime_seconds <= 0:
            raise ValueError("HarnessLoopLimits.max_runtime_seconds must be positive")
        if self.max_events < 1:
            raise ValueError("HarnessLoopLimits.max_events must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_policy(
        cls,
        policy: dict[str, Any] | None,
        *,
        fallback: "HarnessLoopLimits | None" = None,
    ) -> "HarnessLoopLimits":
        base = fallback or cls()
        payload = dict(policy or {})
        limit_mode = str(payload.get("limit_mode") or payload.get("runtime_limit_mode") or "").strip()

        def _int_value(key: str, current: int) -> int:
            value = payload.get(key, current)
            if value is None:
                return current
            return int(value)

        def _seconds_value() -> float | None:
            if limit_mode in {"unlimited", "no_time_limit"} or payload.get("unlimited_runtime") is True:
                return None
            if "max_runtime_seconds" not in payload:
                return base.max_runtime_seconds
            value = payload.get("max_runtime_seconds")
            if value is None:
                return None
            return float(value)

        return cls(
            max_turns=_int_value("max_turns", base.max_turns),
            max_model_calls=_int_value("max_model_calls", base.max_model_calls),
            max_runtime_seconds=_seconds_value(),
            max_events=_int_value("max_events", base.max_events),
        )


@dataclass(frozen=True, slots=True)
class HarnessLoopControlDecision:
    allowed: bool
    reason: RuntimeTerminalReason = ""
    message: str = ""
    snapshot: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.loop_control"

    def __post_init__(self) -> None:
        if self.authority not in {"harness.loop_control", "runtime_control"}:
            raise ValueError("HarnessLoopControlDecision authority must be harness.loop_control")
        if self.authority == "runtime_control":
            object.__setattr__(self, "authority", "harness.loop_control")
        if not self.allowed and not self.reason:
            raise ValueError("blocked HarnessLoopControlDecision requires reason")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_harness_loop_control(
    state: HarnessLoopState,
    *,
    limits: HarnessLoopLimits,
    started_at: float,
    model_call_count: int,
    event_count: int,
) -> HarnessLoopControlDecision:
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
        return HarnessLoopControlDecision(
            allowed=False,
            reason="max_turns",
            message="HarnessLoop reached max_turns before the next dispatch.",
            snapshot=snapshot,
        )
    if model_call_count >= limits.max_model_calls:
        return HarnessLoopControlDecision(
            allowed=False,
            reason="budget_exhausted",
            message="HarnessLoop reached max_model_calls before the next dispatch.",
            snapshot=snapshot,
        )
    if limits.max_runtime_seconds is not None and elapsed_seconds > limits.max_runtime_seconds:
        return HarnessLoopControlDecision(
            allowed=False,
            reason="budget_exhausted",
            message="HarnessLoop reached max_runtime_seconds before the next dispatch.",
            snapshot=snapshot,
        )
    if event_count >= limits.max_events:
        return HarnessLoopControlDecision(
            allowed=False,
            reason="budget_exhausted",
            message="HarnessLoop reached max_events before the next dispatch.",
            snapshot=snapshot,
        )
    return HarnessLoopControlDecision(
        allowed=True,
        message="HarnessLoop control limits allow the next dispatch.",
        snapshot=snapshot,
    )


