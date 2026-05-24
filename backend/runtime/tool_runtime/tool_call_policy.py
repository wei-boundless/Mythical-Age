from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolCallBindingOptions:
    """Provider-native tool binding controls for OpenAI-compatible chat models."""

    tool_choice: dict[str, Any] | str | bool | None = None
    strict: bool | None = None
    parallel_tool_calls: bool | None = None

    def bind_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.tool_choice is not None:
            kwargs["tool_choice"] = self.tool_choice
        if self.strict is not None:
            kwargs["strict"] = self.strict
        if self.parallel_tool_calls is not None:
            kwargs["parallel_tool_calls"] = self.parallel_tool_calls
        return kwargs


def build_round_tool_call_options(*, max_tool_calls: int) -> ToolCallBindingOptions | None:
    if max(1, int(max_tool_calls or 1)) <= 1:
        return ToolCallBindingOptions(parallel_tool_calls=False)
    return None
