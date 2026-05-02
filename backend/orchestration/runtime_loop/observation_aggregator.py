from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from context_management.projection import ContextProjection


@dataclass(slots=True)
class ObservationAggregation:
    projection: ContextProjection = field(default_factory=ContextProjection)
    tool_result_count: int = 0
    tool_names: list[str] = field(default_factory=list)

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
        self._aggregation.tool_result_count += 1
        if tool_name:
            self._aggregation.tool_names.append(tool_name)
        return self._aggregation

    def snapshot(self) -> ObservationAggregation:
        return self._aggregation

