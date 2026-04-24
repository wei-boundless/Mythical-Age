from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from query.binding_models import StructuredDatasetBinding
from query.context_models import EvidenceSummary, MainContextState, TaskSummaryRef
from skill_system import SkillDefinition
from understanding import MemoryIntent, QueryUnderstanding


@dataclass(frozen=True, slots=True)
class QueryEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.payload}


@dataclass(frozen=True, slots=True)
class QueryRequest:
    session_id: str
    message: str
    history: list[dict[str, Any]] | None = None
    ephemeral_system_messages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QueryExecutionPlan:
    message: str
    history: list[dict[str, Any]]
    memory_intent: MemoryIntent
    query_understanding: QueryUnderstanding
    active_skill: SkillDefinition | None = None
    tool_input: dict[str, Any] = field(default_factory=dict)
    structured_binding: StructuredDatasetBinding | None = None
    execution_kind: Literal["agent", "direct_tool"] = "agent"
    execution_posture: str = ""
    ephemeral_system_messages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QueryPlan:
    session_id: str
    message: str
    history: list[dict[str, Any]]
    subqueries: list[str]
    memory_intent: MemoryIntent
    query_understanding: QueryUnderstanding
    active_skill: SkillDefinition | None = None
    tool_input: dict[str, Any] = field(default_factory=dict)
    structured_binding: StructuredDatasetBinding | None = None
    execution_kind: Literal["agent", "direct_tool"] = "agent"
    executions: list[QueryExecutionPlan] = field(default_factory=list)
    ephemeral_system_messages: list[str] = field(default_factory=list)

    def iter_executions(self) -> list[QueryExecutionPlan]:
        if self.executions:
            return list(self.executions)
        return [
            QueryExecutionPlan(
                message=self.message,
                history=list(self.history),
                ephemeral_system_messages=list(self.ephemeral_system_messages),
                memory_intent=self.memory_intent,
                query_understanding=self.query_understanding,
                active_skill=self.active_skill,
                tool_input=dict(self.tool_input or self.query_understanding.tool_input or {}),
                structured_binding=self.structured_binding,
                execution_kind=self.execution_kind,
                execution_posture=str(getattr(self.query_understanding, "execution_posture", "") or ""),
            )
        ]


@dataclass(slots=True)
class QueryContext:
    session_id: str
    history: list[dict[str, Any]]
    augmented_history: list[dict[str, Any]]
    main_context: MainContextState = field(default_factory=MainContextState)
    task_summary_refs: list[TaskSummaryRef] = field(default_factory=list)
    evidence_summaries: list[EvidenceSummary] = field(default_factory=list)
    context_compaction: dict[str, Any] | None = None
    retrieval_results: list[dict[str, Any]] = field(default_factory=list)
    relevant_memory_notes: list[Any] | None = None
    ephemeral_system_messages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QueryResult:
    content: str
    segments: list[dict[str, Any]] = field(default_factory=list)
