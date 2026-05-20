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


def build_required_tool_call_options(
    tool_names: list[str] | tuple[str, ...],
    *,
    strict: bool | None = None,
    parallel_tool_calls: bool | None = False,
) -> ToolCallBindingOptions:
    names = _clean_tool_names(tool_names)
    if len(names) == 1:
        tool_choice: dict[str, Any] | str = {
            "type": "function",
            "function": {"name": names[0]},
        }
    elif len(names) > 1:
        tool_choice = "required"
    else:
        tool_choice = "auto"
    return ToolCallBindingOptions(
        tool_choice=tool_choice,
        strict=strict,
        parallel_tool_calls=parallel_tool_calls,
    )


def _clean_tool_names(tool_names: list[str] | tuple[str, ...]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in list(tool_names or ()):
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        cleaned.append(name)
    return cleaned
