from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from context_system.projection.projection import ContextProjection


@dataclass(slots=True)
class ObservationAggregation:
    projection: ContextProjection = field(default_factory=ContextProjection)
    tool_result_count: int = 0
    tool_names: list[str] = field(default_factory=list)
    evidence_items: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_compound(self) -> bool:
        return self.tool_result_count > 1 or len(set(self.tool_names)) > 1


class ObservationAggregator:
    def __init__(self) -> None:
        self._aggregation = ObservationAggregation()

    def add_projection(
        self,
        projection: ContextProjection,
        *,
        tool_name: str = "",
    ) -> ObservationAggregation:
        self._aggregation.projection = self._aggregation.projection.merge(projection)
        if tool_name:
            self._aggregation.tool_names.append(tool_name)
        return self._aggregation

    def add_tool_observation(
        self,
        payload: dict[str, Any],
        *,
        observation_ref: str = "",
    ) -> ObservationAggregation:
        tool_name = str(payload.get("tool_name") or "").strip()
        tool_args = dict(payload.get("tool_args") or {})
        result = str(payload.get("result") or "").strip()
        if tool_name:
            self._aggregation.tool_names.append(tool_name)
        self._aggregation.tool_result_count += 1
        self._aggregation.evidence_items.append(
            {
                "tool_name": tool_name,
                "tool_args": tool_args,
                "result_preview": _truncate_result(result),
                "result_chars": len(result),
                "observation_ref": str(observation_ref or payload.get("result_ref") or "").strip(),
                "truncated": bool(payload.get("truncated") is True),
            }
        )
        return self._aggregation

    def snapshot(self) -> ObservationAggregation:
        return self._aggregation


def _truncate_result(value: str, limit: int = 1200) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


