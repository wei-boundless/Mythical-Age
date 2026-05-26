from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptResource:
    resource_id: str
    resource_type: str
    title: str
    content: str
    workflow_id: str = ""
    task_id: str = ""
    graph_id: str = ""
    node_id: str = ""
    stage_id: str = ""
    phase_id: str = ""
    step_id: str = ""
    step_kind: str = ""
    tags: tuple[str, ...] = ()
    applies_to_task_goal_types: tuple[str, ...] = ()
    applies_to_domains: tuple[str, ...] = ()
    applies_to_modes: tuple[str, ...] = ()
    applies_to_agents: tuple[str, ...] = ()
    priority: int = 100
    cache_scope: str = "static"
    model_visible: bool = True
    source_ref: str = ""
    version: str = "v1"
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.prompt_resource"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "tags",
            "applies_to_task_goal_types",
            "applies_to_domains",
            "applies_to_modes",
            "applies_to_agents",
        ):
            payload[key] = list(payload[key])
        payload["chars"] = len(self.content)
        return payload


@dataclass(frozen=True, slots=True)
class PromptSelectionContext:
    task_id: str
    user_goal: str = ""
    agent_id: str = ""
    interaction_mode: str = "standard_mode"
    work_mode: str = ""
    interaction_intent: str = ""
    action_intent: str = ""
    runtime_lane: str = ""
    process_kind: str = ""
    task_goal_type: str = ""
    task_domain: str = ""
    task_mode: str = ""
    workflow_id: str = ""
    workflow_title: str = ""
    registered_task_id: str = ""
    graph_id: str = ""
    node_id: str = ""
    stage_id: str = ""
    phase_id: str = ""
    current_step_id: str = ""
    current_step_kind: str = ""
    current_step_title: str = ""
    current_step_index: int = -1
    current_step_source: str = ""
    task_graph_node_runtime: bool = False
    workflow_steps: tuple[dict[str, Any], ...] = ()
    recipe_steps: tuple[dict[str, Any], ...] = ()
    step_sequence: tuple[str, ...] = ()
    skill_ids: tuple[str, ...] = ()
    visible_tool_ids: tuple[str, ...] = ()
    model_turn_decision: dict[str, Any] = field(default_factory=dict)
    action_permit: dict[str, Any] = field(default_factory=dict)
    boundary_policy: dict[str, Any] = field(default_factory=dict)
    request_facts: dict[str, Any] = field(default_factory=dict)
    context_binding: dict[str, Any] = field(default_factory=dict)
    task_requirement_contract: dict[str, Any] = field(default_factory=dict)
    goal_hypothesis_set: dict[str, Any] = field(default_factory=dict)
    task_goal_spec: dict[str, Any] = field(default_factory=dict)
    agent_plan_requirement: dict[str, Any] = field(default_factory=dict)
    agent_plan_draft: dict[str, Any] = field(default_factory=dict)
    plan_coverage_review: dict[str, Any] = field(default_factory=dict)
    verification_review: dict[str, Any] = field(default_factory=dict)
    completion_judgment: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.selection_context"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["workflow_steps"] = [dict(item) for item in self.workflow_steps]
        payload["recipe_steps"] = [dict(item) for item in self.recipe_steps]
        payload["step_sequence"] = list(self.step_sequence)
        payload["skill_ids"] = list(self.skill_ids)
        payload["visible_tool_ids"] = list(self.visible_tool_ids)
        payload["model_turn_decision"] = dict(self.model_turn_decision or {})
        payload["action_permit"] = dict(self.action_permit or {})
        payload["boundary_policy"] = dict(self.boundary_policy or {})
        payload["request_facts"] = dict(self.request_facts or {})
        payload["context_binding"] = dict(self.context_binding or {})
        payload["task_requirement_contract"] = dict(self.task_requirement_contract or {})
        payload["goal_hypothesis_set"] = dict(self.goal_hypothesis_set or {})
        payload["task_goal_spec"] = dict(self.task_goal_spec or {})
        payload["agent_plan_requirement"] = dict(self.agent_plan_requirement or {})
        payload["agent_plan_draft"] = dict(self.agent_plan_draft or {})
        payload["plan_coverage_review"] = dict(self.plan_coverage_review or {})
        payload["verification_review"] = dict(self.verification_review or {})
        payload["completion_judgment"] = dict(self.completion_judgment or {})
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PromptAssemblyPlanItem:
    section_id: str
    resource_id: str
    resource_type: str
    title: str
    owner_layer: str
    cache_scope: str
    model_visible: bool
    source_ref: str = ""
    source_refs: tuple[str, ...] = ()
    renderer_id: str = ""
    order: int = 100
    priority: int = 100
    selection_reason: str = ""
    omitted_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_refs"] = list(self.source_refs)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PromptAssemblyPlan:
    plan_id: str
    task_id: str
    interaction_mode: str
    selected: tuple[PromptAssemblyPlanItem, ...] = ()
    omitted: tuple[PromptAssemblyPlanItem, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.assembly_plan"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "interaction_mode": self.interaction_mode,
            "selected": [item.to_dict() for item in self.selected],
            "omitted": [item.to_dict() for item in self.omitted],
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


def prompt_resource_from_dict(payload: dict[str, Any]) -> PromptResource:
    return PromptResource(
        resource_id=str(payload.get("resource_id") or ""),
        resource_type=str(payload.get("resource_type") or "stage_role"),
        title=str(payload.get("title") or payload.get("resource_id") or ""),
        content=str(payload.get("content") or ""),
        workflow_id=str(payload.get("workflow_id") or ""),
        task_id=str(payload.get("task_id") or ""),
        graph_id=str(payload.get("graph_id") or ""),
        node_id=str(payload.get("node_id") or ""),
        stage_id=str(payload.get("stage_id") or ""),
        phase_id=str(payload.get("phase_id") or ""),
        step_id=str(payload.get("step_id") or ""),
        step_kind=str(payload.get("step_kind") or ""),
        tags=tuple(str(item).strip() for item in list(payload.get("tags") or []) if str(item).strip()),
        applies_to_task_goal_types=tuple(
            str(item).strip()
            for item in list(payload.get("applies_to_task_goal_types") or [])
            if str(item).strip()
        ),
        applies_to_domains=tuple(
            str(item).strip()
            for item in list(payload.get("applies_to_domains") or [])
            if str(item).strip()
        ),
        applies_to_modes=tuple(
            str(item).strip()
            for item in list(payload.get("applies_to_modes") or [])
            if str(item).strip()
        ),
        applies_to_agents=tuple(
            str(item).strip()
            for item in list(payload.get("applies_to_agents") or [])
            if str(item).strip()
        ),
        priority=int(payload.get("priority") or 100),
        cache_scope=str(payload.get("cache_scope") or "static"),
        model_visible=bool(payload.get("model_visible", True)),
        source_ref=str(payload.get("source_ref") or ""),
        version=str(payload.get("version") or "v1"),
        enabled=bool(payload.get("enabled", True)),
        metadata=dict(payload.get("metadata") or {}),
        authority=str(payload.get("authority") or "prompt_library.prompt_resource"),
    )
