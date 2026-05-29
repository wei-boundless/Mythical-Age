from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptResource:
    prompt_id: str = ""
    category: str = ""
    subtype: str = ""
    owner_layer: str = ""
    allowed_invocation_kinds: tuple[str, ...] = ()
    allowed_runtime_modes: tuple[str, ...] = ()
    allowed_agent_refs: tuple[str, ...] = ()
    allowed_environment_refs: tuple[str, ...] = ()
    status: str = "active"
    resource_id: str = ""
    resource_type: str = ""
    title: str = ""
    content: str = ""
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

    def __post_init__(self) -> None:
        prompt_id = str(self.prompt_id or self.resource_id or "").strip()
        resource_id = str(self.resource_id or prompt_id).strip()
        resource_type = str(self.resource_type or _resource_type_from_category_subtype(self.category, self.subtype)).strip()
        category = str(self.category or _category_from_resource_type(self.resource_type)).strip()
        subtype = str(self.subtype or _subtype_from_resource_type(self.resource_type)).strip()
        owner_layer = str(self.owner_layer or _owner_layer_from_category(category)).strip()
        status = str(self.status or ("active" if self.enabled else "deprecated")).strip()
        object.__setattr__(self, "prompt_id", prompt_id)
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "resource_type", resource_type)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "subtype", subtype)
        object.__setattr__(self, "owner_layer", owner_layer)
        object.__setattr__(self, "status", status)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "allowed_invocation_kinds",
            "allowed_runtime_modes",
            "allowed_agent_refs",
            "allowed_environment_refs",
            "tags",
            "applies_to_task_goal_types",
            "applies_to_domains",
            "applies_to_modes",
            "applies_to_agents",
        ):
            payload[key] = list(payload[key])
        payload["chars"] = len(self.content)
        return payload

    @property
    def active(self) -> bool:
        return self.enabled and self.status == "active"

    @property
    def deprecated_for_new_runtime(self) -> bool:
        return self.status in {"deprecated", "archived"} or bool(
            dict(self.metadata or {}).get("deprecated_for_new_runtime") is True
        )


@dataclass(frozen=True, slots=True)
class PromptPack:
    pack_id: str
    invocation_kind: str
    ordered_prompt_refs: tuple[str, ...]
    cache_scope: str = "static"
    status: str = "active"
    title: str = ""
    allowed_runtime_modes: tuple[str, ...] = ()
    allowed_agent_refs: tuple[str, ...] = ()
    allowed_environment_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.prompt_pack"

    def __post_init__(self) -> None:
        if not str(self.pack_id or "").strip():
            raise ValueError("PromptPack requires pack_id")
        if not str(self.invocation_kind or "").strip():
            raise ValueError("PromptPack requires invocation_kind")
        object.__setattr__(self, "ordered_prompt_refs", tuple(str(item).strip() for item in self.ordered_prompt_refs if str(item).strip()))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ordered_prompt_refs"] = list(self.ordered_prompt_refs)
        payload["allowed_runtime_modes"] = list(self.allowed_runtime_modes)
        payload["allowed_agent_refs"] = list(self.allowed_agent_refs)
        payload["allowed_environment_refs"] = list(self.allowed_environment_refs)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PromptSection:
    section_id: str
    prompt_ref: str
    category: str
    subtype: str
    title: str
    content: str
    owner_layer: str
    cache_scope: str
    source_ref: str = ""
    order: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PromptAssemblyRequest:
    invocation_kind: str
    prompt_pack_refs: tuple[str, ...] = ()
    prompt_refs: tuple[str, ...] = ()
    agent_profile_ref: str = ""
    task_environment_ref: str = ""
    runtime_mode: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_kind": self.invocation_kind,
            "prompt_pack_refs": list(self.prompt_pack_refs),
            "prompt_refs": list(self.prompt_refs),
            "agent_profile_ref": self.agent_profile_ref,
            "task_environment_ref": self.task_environment_ref,
            "runtime_mode": self.runtime_mode,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class PromptAssemblyResult:
    assembly_id: str
    invocation_kind: str
    sections: tuple[PromptSection, ...]
    prompt_pack_refs: tuple[str, ...] = ()
    rejected_refs: tuple[dict[str, Any], ...] = ()
    manifest: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.prompt_assembly_result"

    def to_dict(self) -> dict[str, Any]:
        return {
            "assembly_id": self.assembly_id,
            "invocation_kind": self.invocation_kind,
            "sections": [item.to_dict() for item in self.sections],
            "prompt_pack_refs": list(self.prompt_pack_refs),
            "rejected_refs": [dict(item) for item in self.rejected_refs],
            "manifest": dict(self.manifest),
            "authority": self.authority,
        }

    @property
    def content(self) -> str:
        return "\n".join(item.content for item in self.sections if item.content.strip()).strip()


@dataclass(frozen=True, slots=True)
class PromptSelectionContext:
    task_id: str
    user_goal: str = ""
    agent_id: str = ""
    interaction_mode: str = "standard_mode"
    process_kind: str = ""
    interaction_intent: str = ""
    action_intent: str = ""
    work_mode: str = ""
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
    agent_turn_action_request: dict[str, Any] = field(default_factory=dict)
    task_contract_seed: dict[str, Any] = field(default_factory=dict)
    runtime_admission: dict[str, Any] = field(default_factory=dict)
    permission_request: dict[str, Any] = field(default_factory=dict)
    context_binding: dict[str, Any] = field(default_factory=dict)
    task_requirement_contract: dict[str, Any] = field(default_factory=dict)
    goal_hypothesis_set: dict[str, Any] = field(default_factory=dict)
    task_goal_spec: dict[str, Any] = field(default_factory=dict)
    agent_plan_requirement: dict[str, Any] = field(default_factory=dict)
    agent_plan_draft: dict[str, Any] = field(default_factory=dict)
    plan_coverage_review: dict[str, Any] = field(default_factory=dict)
    verification_review: dict[str, Any] = field(default_factory=dict)
    completion_judgment: dict[str, Any] = field(default_factory=dict)
    model_turn_decision: dict[str, Any] = field(default_factory=dict)
    action_permit: dict[str, Any] = field(default_factory=dict)
    boundary_policy: dict[str, Any] = field(default_factory=dict)
    request_facts: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.selection_context"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["workflow_steps"] = [dict(item) for item in self.workflow_steps]
        payload["recipe_steps"] = [dict(item) for item in self.recipe_steps]
        payload["step_sequence"] = list(self.step_sequence)
        payload["skill_ids"] = list(self.skill_ids)
        payload["visible_tool_ids"] = list(self.visible_tool_ids)
        payload["agent_turn_action_request"] = dict(self.agent_turn_action_request or {})
        payload["task_contract_seed"] = dict(self.task_contract_seed or {})
        payload["runtime_admission"] = dict(self.runtime_admission or {})
        payload["permission_request"] = dict(self.permission_request or {})
        payload["context_binding"] = dict(self.context_binding or {})
        payload["task_requirement_contract"] = dict(self.task_requirement_contract or {})
        payload["goal_hypothesis_set"] = dict(self.goal_hypothesis_set or {})
        payload["task_goal_spec"] = dict(self.task_goal_spec or {})
        payload["agent_plan_requirement"] = dict(self.agent_plan_requirement or {})
        payload["agent_plan_draft"] = dict(self.agent_plan_draft or {})
        payload["plan_coverage_review"] = dict(self.plan_coverage_review or {})
        payload["verification_review"] = dict(self.verification_review or {})
        payload["completion_judgment"] = dict(self.completion_judgment or {})
        payload["model_turn_decision"] = dict(self.model_turn_decision or {})
        payload["action_permit"] = dict(self.action_permit or {})
        payload["boundary_policy"] = dict(self.boundary_policy or {})
        payload["request_facts"] = dict(self.request_facts or {})
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
        prompt_id=str(payload.get("prompt_id") or payload.get("resource_id") or ""),
        category=str(payload.get("category") or ""),
        subtype=str(payload.get("subtype") or ""),
        owner_layer=str(payload.get("owner_layer") or ""),
        allowed_invocation_kinds=tuple(
            str(item).strip()
            for item in list(payload.get("allowed_invocation_kinds") or [])
            if str(item).strip()
        ),
        allowed_runtime_modes=tuple(
            str(item).strip()
            for item in list(payload.get("allowed_runtime_modes") or payload.get("applies_to_modes") or [])
            if str(item).strip()
        ),
        allowed_agent_refs=tuple(
            str(item).strip()
            for item in list(payload.get("allowed_agent_refs") or payload.get("applies_to_agents") or [])
            if str(item).strip()
        ),
        allowed_environment_refs=tuple(
            str(item).strip()
            for item in list(payload.get("allowed_environment_refs") or [])
            if str(item).strip()
        ),
        status=str(payload.get("status") or ("active" if bool(payload.get("enabled", True)) else "deprecated")),
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


def prompt_pack_from_dict(payload: dict[str, Any]) -> PromptPack:
    return PromptPack(
        pack_id=str(payload.get("pack_id") or ""),
        invocation_kind=str(payload.get("invocation_kind") or ""),
        ordered_prompt_refs=tuple(
            str(item).strip()
            for item in list(payload.get("ordered_prompt_refs") or [])
            if str(item).strip()
        ),
        cache_scope=str(payload.get("cache_scope") or "static"),
        status=str(payload.get("status") or "active"),
        title=str(payload.get("title") or payload.get("pack_id") or ""),
        allowed_runtime_modes=tuple(
            str(item).strip()
            for item in list(payload.get("allowed_runtime_modes") or [])
            if str(item).strip()
        ),
        allowed_agent_refs=tuple(
            str(item).strip()
            for item in list(payload.get("allowed_agent_refs") or [])
            if str(item).strip()
        ),
        allowed_environment_refs=tuple(
            str(item).strip()
            for item in list(payload.get("allowed_environment_refs") or [])
            if str(item).strip()
        ),
        metadata=dict(payload.get("metadata") or {}),
        authority=str(payload.get("authority") or "prompt_library.prompt_pack"),
    )


def _category_from_resource_type(resource_type: str) -> str:
    value = str(resource_type or "").strip()
    mapping = {
        "common_contract": "runtime",
        "work_role": "agent",
        "environment_prompt": "environment",
        "understanding_policy": "task",
        "flow_matching_policy": "task",
        "role_prompt": "soul",
        "task_goal_role": "task",
        "stage_role": "graph_node",
        "skill_prompt": "skill",
        "tool_guidance": "runtime",
        "verification": "runtime",
        "output_boundary": "runtime",
    }
    return mapping.get(value, value.split(".", 1)[0] if "." in value else "runtime")


def _subtype_from_resource_type(resource_type: str) -> str:
    value = str(resource_type or "").strip()
    mapping = {
        "common_contract": "common_contract",
        "work_role": "main.work_role",
        "environment_prompt": "boundary",
        "understanding_policy": "understanding_policy",
        "flow_matching_policy": "flow_matching_policy",
        "role_prompt": "role_persona",
        "task_goal_role": "specific.role",
        "stage_role": "role",
        "skill_prompt": "usage",
        "tool_guidance": "tool_guidance",
        "verification": "verification",
        "output_boundary": "output_boundary",
    }
    if value in mapping:
        return mapping[value]
    if "." in value:
        return value.split(".", 1)[1]
    return value or "instruction"


def _owner_layer_from_category(category: str) -> str:
    value = str(category or "").strip()
    mapping = {
        "runtime": "runtime",
        "agent": "agent",
        "environment": "environment",
        "task": "task",
        "graph_node": "task",
        "skill": "agent",
        "soul": "agent",
    }
    return mapping.get(value, value or "runtime")


def _resource_type_from_category_subtype(category: str, subtype: str) -> str:
    category_value = str(category or "").strip()
    subtype_value = str(subtype or "").strip()
    if category_value == "agent" and subtype_value in {"main.work_role", "work_role"}:
        return "work_role"
    if category_value == "environment":
        return "environment_prompt"
    if category_value and subtype_value:
        return f"{category_value}.{subtype_value}"
    return category_value or subtype_value or "runtime.instruction"


