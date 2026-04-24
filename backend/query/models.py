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
    explicit_subtasks: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class BundleItemPlan:
    item_id: str
    index: int
    goal: str
    user_visible_title: str
    execution_message: str
    source_kind: str
    capability: str
    execution_kind: str
    explicit_refs: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    followup_aliases: list[str] = field(default_factory=list)
    origin: str = "strong_anchor_bundle"


@dataclass(slots=True)
class BundlePlan:
    bundle_id: str
    parent_query_id: str
    items: list[BundleItemPlan] = field(default_factory=list)
    origin: str = "strong_anchor_bundle"


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
    dispatch_plan: Any | None = None
    ephemeral_system_messages: list[str] = field(default_factory=list)
    subtask_id: str = ""
    subtask_goal: str = ""
    subtask_title: str = ""
    subtask_refs: dict[str, Any] = field(default_factory=dict)
    subtask_depends_on: list[str] = field(default_factory=list)
    subtask_origin: str = "planner"
    bundle_id: str = ""
    bundle_item_id: str = ""
    bundle_item_index: int = 0
    bundle_origin: str = ""


@dataclass(slots=True)
class SubtaskPlan:
    subtask_id: str
    goal: str
    user_visible_title: str
    execution_message: str
    task_kind: str = "query"
    owner: str = "planner"
    depends_on: list[str] = field(default_factory=list)
    refs: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    origin: str = "planner"

    @classmethod
    def single(cls, message: str) -> "SubtaskPlan":
        normalized = (message or "").strip()
        return cls(
            subtask_id="main",
            goal=normalized,
            user_visible_title=normalized,
            execution_message=normalized,
        )


@dataclass(slots=True)
class QueryPlan:
    session_id: str
    message: str
    history: list[dict[str, Any]]
    subqueries: list[str]
    memory_intent: MemoryIntent
    query_understanding: QueryUnderstanding
    execution_mode: Literal["single_execution", "bundle_execution", "explicit_fanout"] = "single_execution"
    subtasks: list[SubtaskPlan] = field(default_factory=list)
    bundle_plan: BundlePlan | None = None
    active_skill: SkillDefinition | None = None
    tool_input: dict[str, Any] = field(default_factory=dict)
    structured_binding: StructuredDatasetBinding | None = None
    execution_kind: Literal["agent", "direct_tool"] = "agent"
    dispatch_plan: Any | None = None
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
                dispatch_plan=getattr(self, "dispatch_plan", None),
                subtask_id=(self.subtasks[0].subtask_id if self.subtasks else "main"),
                subtask_goal=(self.subtasks[0].goal if self.subtasks else self.message),
                subtask_title=(self.subtasks[0].user_visible_title if self.subtasks else self.message),
                subtask_refs=dict(self.subtasks[0].refs if self.subtasks else {}),
                subtask_depends_on=list(self.subtasks[0].depends_on if self.subtasks else []),
                subtask_origin=(self.subtasks[0].origin if self.subtasks else "planner"),
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
