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
            "allowed_agent_refs",
            "allowed_environment_refs",
            "tags",
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
    task_prompt_contract: dict[str, Any] = field(default_factory=dict)
    graph_node_prompt_contract: dict[str, Any] = field(default_factory=dict)
    skill_prompt_refs: tuple[str, ...] = ()
    soul_prompt_ref: str = ""
    agent_profile_ref: str = ""
    task_environment_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_kind": self.invocation_kind,
            "prompt_pack_refs": list(self.prompt_pack_refs),
            "prompt_refs": list(self.prompt_refs),
            "task_prompt_contract": dict(self.task_prompt_contract),
            "graph_node_prompt_contract": dict(self.graph_node_prompt_contract),
            "skill_prompt_refs": list(self.skill_prompt_refs),
            "soul_prompt_ref": self.soul_prompt_ref,
            "agent_profile_ref": self.agent_profile_ref,
            "task_environment_ref": self.task_environment_ref,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class PromptAssemblyResult:
    assembly_id: str
    invocation_kind: str
    sections: tuple[PromptSection, ...]
    prompt_pack_refs: tuple[str, ...] = ()
    rejected_refs: tuple[dict[str, Any], ...] = ()
    dynamic_projection_refs: tuple[str, ...] = ()
    volatile_state_refs: tuple[str, ...] = ()
    manifest: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.prompt_assembly_result"

    def to_dict(self) -> dict[str, Any]:
        return {
            "assembly_id": self.assembly_id,
            "invocation_kind": self.invocation_kind,
            "sections": [item.to_dict() for item in self.sections],
            "prompt_pack_refs": list(self.prompt_pack_refs),
            "rejected_refs": [dict(item) for item in self.rejected_refs],
            "dynamic_projection_refs": list(self.dynamic_projection_refs),
            "volatile_state_refs": list(self.volatile_state_refs),
            "manifest": dict(self.manifest),
            "authority": self.authority,
        }

    @property
    def content(self) -> str:
        return "\n".join(item.content for item in self.sections if item.content.strip()).strip()


def prompt_resource_from_dict(payload: dict[str, Any]) -> PromptResource:
    resource_type = str(payload.get("resource_type") or "").strip()
    prompt_id = str(payload.get("prompt_id") or payload.get("resource_id") or "")
    resource_id = str(payload.get("resource_id") or "")
    return PromptResource(
        prompt_id=prompt_id,
        category=str(payload.get("category") or ""),
        subtype=str(payload.get("subtype") or ""),
        owner_layer=str(payload.get("owner_layer") or ""),
        allowed_invocation_kinds=tuple(
            str(item).strip()
            for item in list(payload.get("allowed_invocation_kinds") or [])
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
        status=str(payload.get("status") or ("active" if bool(payload.get("enabled", True)) else "deprecated")),
        resource_id=resource_id,
        resource_type=resource_type,
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
        "work_role": "agent",
        "environment_prompt": "environment",
        "role_prompt": "agent",
        "graph_node.role": "graph_node",
        "skill_prompt": "skill",
        "tool_guidance": "runtime",
        "verification": "runtime",
        "output_boundary": "runtime",
    }
    return mapping.get(value, value.split(".", 1)[0] if "." in value else "runtime")


def _subtype_from_resource_type(resource_type: str) -> str:
    value = str(resource_type or "").strip()
    mapping = {
        "work_role": "main.work_role",
        "environment_prompt": "boundary",
        "role_prompt": "role",
        "graph_node.role": "role",
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




