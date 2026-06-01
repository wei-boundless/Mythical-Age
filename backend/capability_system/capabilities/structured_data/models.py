from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class StructuredFilter:
    column: str
    operator: str
    value: str | list[str]

    @property
    def filter_expression(self) -> str:
        if self.operator == "in" and isinstance(self.value, list):
            return f"{self.column} in [{', '.join(str(item) for item in self.value)}]"
        separator = "=" if self.operator == "=" else "~"
        return f"{self.column}{separator}{self.value}"


@dataclass(frozen=True, slots=True)
class StructuredDerivedMetric:
    name: str
    kind: str
    left_column: str
    right_column: str
    lower_bound: float | None = None


@dataclass(slots=True)
class StructuredQueryPlan:
    table_name: str = "dataset"
    query_kind: str = "record"
    select_columns: list[str] = field(default_factory=list)
    filters: list[StructuredFilter] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    metric: str | None = None
    aggregate: str | None = None
    order_by: str | None = None
    order_direction: str = "desc"
    limit: int = 10
    derived_metrics: list[StructuredDerivedMetric] = field(default_factory=list)
    metric_condition_operator: str | None = None
    metric_condition_value: float | None = None

    @property
    def is_grouped(self) -> bool:
        return self.query_kind == "grouped" or bool(self.group_by)


@dataclass(slots=True)
class StructuredDataPlan:
    path: str
    analysis_type: str
    profile_id: str = ""
    sheet_name: str = ""
    limit: int = 10
    metric: str | None = None
    group_by: str | None = None
    agg: str = "sum"
    sort_direction: str = "desc"
    filters: list[str] = field(default_factory=list)
    structured_filters: list[StructuredFilter] = field(default_factory=list)
    query_mode: str = "record"
    order_by: str | None = None
    entity_column: str | None = None
    select_columns: list[str] = field(default_factory=list)
    diagnostic: bool = False
    query_plan: StructuredQueryPlan | None = None
    execution_backend: str = "sqlite"

    @property
    def is_grouped(self) -> bool:
        return bool(self.group_by) or self.query_mode == "grouped"


