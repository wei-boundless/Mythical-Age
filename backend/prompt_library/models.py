from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .taxonomy import normalize_conflict_policy, normalize_contract_priority, normalize_prompt_scope


@dataclass(frozen=True, slots=True)
class PromptResource:
    prompt_id: str = ""
    category: str = ""
    subtype: str = ""
    owner_layer: str = ""
    owner_kind: str = ""
    owner_ref: str = ""
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
    contract_priority: str = ""
    conflict_policy: str = ""
    scope: str = ""
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
        owner_kind = str(self.owner_kind or dict(self.metadata or {}).get("owner_kind") or owner_layer).strip()
        owner_ref = str(self.owner_ref or dict(self.metadata or {}).get("owner_ref") or "").strip()
        contract_priority = normalize_contract_priority(
            self.contract_priority or dict(self.metadata or {}).get("contract_priority"),
            category=category,
            resource_type=resource_type,
        )
        conflict_policy = normalize_conflict_policy(
            self.conflict_policy or dict(self.metadata or {}).get("conflict_policy"),
            contract_priority=contract_priority,
        )
        scope = normalize_prompt_scope(
            self.scope or dict(self.metadata or {}).get("scope"),
            owner_kind=owner_kind,
            owner_ref=owner_ref,
        )
        status = str(self.status or ("active" if self.enabled else "deprecated")).strip()
        object.__setattr__(self, "prompt_id", prompt_id)
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "resource_type", resource_type)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "subtype", subtype)
        object.__setattr__(self, "owner_layer", owner_layer)
        object.__setattr__(self, "owner_kind", owner_kind)
        object.__setattr__(self, "owner_ref", owner_ref)
        object.__setattr__(self, "contract_priority", contract_priority)
        object.__setattr__(self, "conflict_policy", conflict_policy)
        object.__setattr__(self, "scope", scope)
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
class PromptRule:
    rule_id: str
    prompt_ref: str
    rule_kind: str
    owner_layer: str
    applies_to: tuple[str, ...] = ()
    allowed_invocation_kinds: tuple[str, ...] = ()
    allowed_agent_refs: tuple[str, ...] = ()
    allowed_environment_refs: tuple[str, ...] = ()
    cache_tier: str = "global_static"
    enforcement_mode: str = "prompt_only"
    authority: str = "prompt_library.prompt_rule"
    conflicts_with: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    lint_tags: tuple[str, ...] = ()
    version: str = "v1"
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        rule_id = str(self.rule_id or self.prompt_ref or "").strip()
        prompt_ref = str(self.prompt_ref or rule_id).strip()
        rule_kind = str(self.rule_kind or "runtime.instruction").strip()
        owner_layer = str(self.owner_layer or "runtime").strip()
        cache_tier = str(self.cache_tier or "global_static").strip()
        enforcement_mode = str(self.enforcement_mode or "prompt_only").strip()
        status = str(self.status or "active").strip()
        object.__setattr__(self, "rule_id", rule_id)
        object.__setattr__(self, "prompt_ref", prompt_ref)
        object.__setattr__(self, "rule_kind", rule_kind)
        object.__setattr__(self, "owner_layer", owner_layer)
        object.__setattr__(self, "cache_tier", cache_tier)
        object.__setattr__(self, "enforcement_mode", enforcement_mode)
        object.__setattr__(self, "status", status)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "applies_to",
            "allowed_invocation_kinds",
            "allowed_agent_refs",
            "allowed_environment_refs",
            "conflicts_with",
            "requires",
            "supersedes",
            "lint_tags",
        ):
            payload[key] = list(payload[key])
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PromptRuleAssemblyResult:
    assembly_id: str
    invocation_kind: str
    rules: tuple[PromptRule, ...]
    rejected_rules: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.prompt_rule_assembly_result"

    def to_dict(self) -> dict[str, Any]:
        return {
            "assembly_id": self.assembly_id,
            "invocation_kind": self.invocation_kind,
            "rules": [item.to_dict() for item in self.rules],
            "rejected_rules": [dict(item) for item in self.rejected_rules],
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }

    @property
    def rule_refs(self) -> tuple[str, ...]:
        return tuple(item.rule_id for item in self.rules if item.rule_id)

    @property
    def rule_kinds(self) -> tuple[str, ...]:
        return tuple(item.rule_kind for item in self.rules if item.rule_kind)


@dataclass(frozen=True, slots=True)
class PromptSetSlot:
    slot: str
    prompt_refs: tuple[str, ...] = ()
    prompt_pack_refs: tuple[str, ...] = ()
    prompt_refs_by_invocation: dict[str, tuple[str, ...]] = field(default_factory=dict)
    prompt_pack_refs_by_invocation: dict[str, tuple[str, ...]] = field(default_factory=dict)
    owner_layer: str = ""
    cache_scope: str = ""
    visibility: str = "model_visible"
    locked: bool = False
    contract_priority: str = ""
    conflict_policy: str = ""
    scope: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot", str(self.slot or "").strip())
        object.__setattr__(self, "prompt_refs", _string_tuple(self.prompt_refs))
        object.__setattr__(self, "prompt_pack_refs", _string_tuple(self.prompt_pack_refs))
        object.__setattr__(self, "prompt_refs_by_invocation", _string_tuple_map(self.prompt_refs_by_invocation))
        object.__setattr__(self, "prompt_pack_refs_by_invocation", _string_tuple_map(self.prompt_pack_refs_by_invocation))
        contract_priority = normalize_contract_priority(
            self.contract_priority or dict(self.metadata or {}).get("contract_priority"),
            category=str(self.owner_layer or ""),
        )
        conflict_policy = normalize_conflict_policy(
            self.conflict_policy or dict(self.metadata or {}).get("conflict_policy"),
            contract_priority=contract_priority,
        )
        object.__setattr__(self, "contract_priority", contract_priority)
        object.__setattr__(self, "conflict_policy", conflict_policy)
        object.__setattr__(
            self,
            "scope",
            normalize_prompt_scope(self.scope or dict(self.metadata or {}).get("scope"), owner_kind=str(self.owner_layer or "")),
        )

    def refs_for_invocation(self, invocation_kind: str) -> tuple[str, ...]:
        invocation = str(invocation_kind or "").strip()
        return tuple(self.prompt_refs_by_invocation.get(invocation) or self.prompt_refs_by_invocation.get("default") or self.prompt_refs)

    def packs_for_invocation(self, invocation_kind: str) -> tuple[str, ...]:
        invocation = str(invocation_kind or "").strip()
        return tuple(
            self.prompt_pack_refs_by_invocation.get(invocation)
            or self.prompt_pack_refs_by_invocation.get("default")
            or self.prompt_pack_refs
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "prompt_refs": list(self.prompt_refs),
            "prompt_pack_refs": list(self.prompt_pack_refs),
            "prompt_refs_by_invocation": {key: list(value) for key, value in self.prompt_refs_by_invocation.items()},
            "prompt_pack_refs_by_invocation": {
                key: list(value) for key, value in self.prompt_pack_refs_by_invocation.items()
            },
            "owner_layer": self.owner_layer,
            "cache_scope": self.cache_scope,
            "visibility": self.visibility,
            "locked": self.locked,
            "contract_priority": self.contract_priority,
            "conflict_policy": self.conflict_policy,
            "scope": self.scope,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class PromptSet:
    prompt_set_id: str
    owner_kind: str = ""
    owner_ref: str = ""
    extends: tuple[str, ...] = ()
    slots: dict[str, PromptSetSlot] = field(default_factory=dict)
    policies: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    title: str = ""
    allowed_agent_refs: tuple[str, ...] = ()
    allowed_environment_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.prompt_set"

    def __post_init__(self) -> None:
        prompt_set_id = str(self.prompt_set_id or "").strip()
        if not prompt_set_id:
            raise ValueError("PromptSet requires prompt_set_id")
        object.__setattr__(self, "prompt_set_id", prompt_set_id)
        object.__setattr__(self, "extends", _string_tuple(self.extends))
        object.__setattr__(self, "allowed_agent_refs", _string_tuple(self.allowed_agent_refs))
        object.__setattr__(self, "allowed_environment_refs", _string_tuple(self.allowed_environment_refs))
        object.__setattr__(self, "slots", _prompt_set_slots(self.slots))

    @property
    def active(self) -> bool:
        return self.status == "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_set_id": self.prompt_set_id,
            "owner_kind": self.owner_kind,
            "owner_ref": self.owner_ref,
            "extends": list(self.extends),
            "slots": {key: slot.to_dict() for key, slot in self.slots.items()},
            "policies": dict(self.policies),
            "status": self.status,
            "title": self.title,
            "allowed_agent_refs": list(self.allowed_agent_refs),
            "allowed_environment_refs": list(self.allowed_environment_refs),
            "metadata": dict(self.metadata),
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class AgentPromptBinding:
    agent_profile_id: str
    prompt_set_refs: tuple[str, ...] = ()
    invocation_overrides: dict[str, tuple[str, ...]] = field(default_factory=dict)
    locked_slots: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.agent_prompt_binding"

    def __post_init__(self) -> None:
        object.__setattr__(self, "agent_profile_id", str(self.agent_profile_id or "").strip())
        object.__setattr__(self, "prompt_set_refs", _string_tuple(self.prompt_set_refs))
        object.__setattr__(self, "invocation_overrides", _string_tuple_map(self.invocation_overrides))
        object.__setattr__(self, "locked_slots", _string_tuple(self.locked_slots))

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_profile_id": self.agent_profile_id,
            "prompt_set_refs": list(self.prompt_set_refs),
            "invocation_overrides": {key: list(value) for key, value in self.invocation_overrides.items()},
            "locked_slots": list(self.locked_slots),
            "metadata": dict(self.metadata),
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class RuntimePromptWiringSlot:
    slot: str
    refs: tuple[str, ...] = ()
    pack_refs: tuple[str, ...] = ()
    owner_layer: str = ""
    cache_scope: str = ""
    visibility: str = "model_visible"
    locked: bool = False
    contract_priority: str = ""
    conflict_policy: str = ""
    scope: str = ""
    source_prompt_sets: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot", str(self.slot or "").strip())
        object.__setattr__(self, "refs", _string_tuple(self.refs))
        object.__setattr__(self, "pack_refs", _string_tuple(self.pack_refs))
        object.__setattr__(self, "source_prompt_sets", _string_tuple(self.source_prompt_sets))
        contract_priority = normalize_contract_priority(
            self.contract_priority or dict(self.metadata or {}).get("contract_priority"),
            category=str(self.owner_layer or ""),
        )
        object.__setattr__(self, "contract_priority", contract_priority)
        object.__setattr__(
            self,
            "conflict_policy",
            normalize_conflict_policy(
                self.conflict_policy or dict(self.metadata or {}).get("conflict_policy"),
                contract_priority=contract_priority,
            ),
        )
        object.__setattr__(
            self,
            "scope",
            normalize_prompt_scope(self.scope or dict(self.metadata or {}).get("scope"), owner_kind=str(self.owner_layer or "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "refs": list(self.refs),
            "pack_refs": list(self.pack_refs),
            "owner_layer": self.owner_layer,
            "cache_scope": self.cache_scope,
            "visibility": self.visibility,
            "locked": self.locked,
            "contract_priority": self.contract_priority,
            "conflict_policy": self.conflict_policy,
            "scope": self.scope,
            "source_prompt_sets": list(self.source_prompt_sets),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RuntimePromptWiringPlan:
    wiring_id: str
    agent_profile_id: str
    invocation_kind: str
    environment_id: str = ""
    slots: tuple[RuntimePromptWiringSlot, ...] = ()
    schema_refs: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.runtime_prompt_wiring_plan"

    def __post_init__(self) -> None:
        object.__setattr__(self, "slots", tuple(self.slots or ()))
        object.__setattr__(self, "schema_refs", _string_tuple(self.schema_refs))

    def refs_for_slot(self, slot_name: str) -> tuple[str, ...]:
        target = str(slot_name or "").strip()
        return tuple(ref for slot in self.slots if slot.slot == target for ref in slot.refs)

    def pack_refs_for_slot(self, slot_name: str) -> tuple[str, ...]:
        target = str(slot_name or "").strip()
        return tuple(ref for slot in self.slots if slot.slot == target for ref in slot.pack_refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wiring_id": self.wiring_id,
            "agent_profile_id": self.agent_profile_id,
            "invocation_kind": self.invocation_kind,
            "environment_id": self.environment_id,
            "slots": [slot.to_dict() for slot in self.slots],
            "schema_refs": list(self.schema_refs),
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


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


def prompt_set_slot_from_dict(payload: dict[str, Any]) -> PromptSetSlot:
    return PromptSetSlot(
        slot=str(payload.get("slot") or ""),
        prompt_refs=_string_tuple(payload.get("prompt_refs")),
        prompt_pack_refs=_string_tuple(payload.get("prompt_pack_refs")),
        prompt_refs_by_invocation=_string_tuple_map(payload.get("prompt_refs_by_invocation")),
        prompt_pack_refs_by_invocation=_string_tuple_map(payload.get("prompt_pack_refs_by_invocation")),
        owner_layer=str(payload.get("owner_layer") or ""),
        cache_scope=str(payload.get("cache_scope") or ""),
        visibility=str(payload.get("visibility") or "model_visible"),
        locked=bool(payload.get("locked") is True),
        contract_priority=str(payload.get("contract_priority") or ""),
        conflict_policy=str(payload.get("conflict_policy") or ""),
        scope=str(payload.get("scope") or ""),
        metadata=dict(payload.get("metadata") or {}),
    )


def prompt_set_from_dict(payload: dict[str, Any]) -> PromptSet:
    return PromptSet(
        prompt_set_id=str(payload.get("prompt_set_id") or ""),
        owner_kind=str(payload.get("owner_kind") or ""),
        owner_ref=str(payload.get("owner_ref") or ""),
        extends=_string_tuple(payload.get("extends")),
        slots=_prompt_set_slots(payload.get("slots")),
        policies=dict(payload.get("policies") or {}),
        status=str(payload.get("status") or "active"),
        title=str(payload.get("title") or payload.get("prompt_set_id") or ""),
        allowed_agent_refs=_string_tuple(payload.get("allowed_agent_refs")),
        allowed_environment_refs=_string_tuple(payload.get("allowed_environment_refs")),
        metadata=dict(payload.get("metadata") or {}),
        authority=str(payload.get("authority") or "prompt_library.prompt_set"),
    )


def agent_prompt_binding_from_dict(payload: dict[str, Any]) -> AgentPromptBinding:
    return AgentPromptBinding(
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        prompt_set_refs=_string_tuple(payload.get("prompt_set_refs")),
        invocation_overrides=_string_tuple_map(payload.get("invocation_overrides")),
        locked_slots=_string_tuple(payload.get("locked_slots")),
        metadata=dict(payload.get("metadata") or {}),
        authority=str(payload.get("authority") or "prompt_library.agent_prompt_binding"),
    )


def runtime_prompt_wiring_slot_from_dict(payload: dict[str, Any]) -> RuntimePromptWiringSlot:
    return RuntimePromptWiringSlot(
        slot=str(payload.get("slot") or ""),
        refs=_string_tuple(payload.get("refs")),
        pack_refs=_string_tuple(payload.get("pack_refs")),
        owner_layer=str(payload.get("owner_layer") or ""),
        cache_scope=str(payload.get("cache_scope") or ""),
        visibility=str(payload.get("visibility") or "model_visible"),
        locked=bool(payload.get("locked") is True),
        contract_priority=str(payload.get("contract_priority") or ""),
        conflict_policy=str(payload.get("conflict_policy") or ""),
        scope=str(payload.get("scope") or ""),
        source_prompt_sets=_string_tuple(payload.get("source_prompt_sets")),
        metadata=dict(payload.get("metadata") or {}),
    )


def runtime_prompt_wiring_plan_from_dict(payload: dict[str, Any]) -> RuntimePromptWiringPlan:
    return RuntimePromptWiringPlan(
        wiring_id=str(payload.get("wiring_id") or ""),
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        invocation_kind=str(payload.get("invocation_kind") or ""),
        environment_id=str(payload.get("environment_id") or ""),
        slots=tuple(
            runtime_prompt_wiring_slot_from_dict(dict(item))
            for item in list(payload.get("slots") or [])
            if isinstance(item, dict)
        ),
        schema_refs=_string_tuple(payload.get("schema_refs")),
        diagnostics=dict(payload.get("diagnostics") or {}),
        authority=str(payload.get("authority") or "prompt_library.runtime_prompt_wiring_plan"),
    )


def prompt_resource_from_dict(payload: dict[str, Any]) -> PromptResource:
    resource_type = str(payload.get("resource_type") or "").strip()
    prompt_id = str(payload.get("prompt_id") or payload.get("resource_id") or "")
    resource_id = str(payload.get("resource_id") or "")
    return PromptResource(
        prompt_id=prompt_id,
        category=str(payload.get("category") or ""),
        subtype=str(payload.get("subtype") or ""),
        owner_layer=str(payload.get("owner_layer") or ""),
        owner_kind=str(payload.get("owner_kind") or ""),
        owner_ref=str(payload.get("owner_ref") or ""),
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
        contract_priority=str(payload.get("contract_priority") or ""),
        conflict_policy=str(payload.get("conflict_policy") or ""),
        scope=str(payload.get("scope") or ""),
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
        "agent_personality": "personality",
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
        "agent_personality": "default",
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
        "personality": "personality",
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
    if category_value == "personality":
        return "agent_personality"
    if category_value == "environment":
        return "environment_prompt"
    if category_value and subtype_value:
        return f"{category_value}.{subtype_value}"
    return category_value or subtype_value or "runtime.instruction"


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values = [value]
    else:
        raw_values = list(value or [])
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


def _string_tuple_map(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for key, raw_values in value.items():
        normalized_key = str(key or "").strip()
        normalized_values = _string_tuple(raw_values)
        if normalized_key and normalized_values:
            result[normalized_key] = normalized_values
    return result


def _prompt_set_slots(value: Any) -> dict[str, PromptSetSlot]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, PromptSetSlot] = {}
    for key, raw_slot in value.items():
        slot_name = str(key or "").strip()
        if not slot_name:
            continue
        if isinstance(raw_slot, PromptSetSlot):
            slot = raw_slot
        else:
            payload = dict(raw_slot or {}) if isinstance(raw_slot, dict) else {}
            payload.setdefault("slot", slot_name)
            slot = prompt_set_slot_from_dict(payload)
        if slot.slot:
            result[slot.slot] = slot
    return result




