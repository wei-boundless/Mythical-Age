from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


AGENT_CATEGORY_TO_SYSTEM_SLUG = {
    "main_agent": "task_system",
    "builtin_agent": "builtin_system",
    "custom_agent": "custom_agent_pool",
}


@dataclass(frozen=True, slots=True)
class AgentDescriptor:
    agent_id: str
    agent_name: str
    agent_category: str
    interface_target: str
    description: str = ""
    enabled: bool = True
    builtin: bool = False
    editable: bool = True
    default_soul_id: str = ""
    default_projection_id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.agent_name

    @property
    def profile_type(self) -> str:
        return self.agent_category

    @property
    def owner_system(self) -> str:
        if self.agent_category == "builtin_agent":
            return str(self.metadata.get("system_key") or self.metadata.get("managed_system") or "builtin_system")
        return AGENT_CATEGORY_TO_SYSTEM_SLUG.get(self.agent_category, "task_system")

    @property
    def builtin_kind(self) -> str:
        explicit = str(self.metadata.get("builtin_kind") or "").strip()
        if explicit:
            return explicit
        role = str(self.metadata.get("role") or "").strip()
        if self.agent_category == "main_agent":
            return "primary"
        if self.agent_category == "builtin_agent":
            if role == "system_manager" or self.metadata.get("system_key"):
                return "system_manager"
            return "specialist"
        return ""

    @property
    def agent_template_id(self) -> str:
        return str(self.metadata.get("agent_template_id") or "").strip()

    @property
    def delegation_enabled(self) -> bool:
        explicit = self.metadata.get("delegation_enabled")
        if isinstance(explicit, bool):
            return explicit
        if self.agent_category == "main_agent":
            return False
        if self.agent_category == "builtin_agent":
            return self.builtin_kind == "specialist"
        return True

    @property
    def group_eligible(self) -> bool:
        explicit = self.metadata.get("group_eligible")
        if isinstance(explicit, bool):
            return explicit
        return self.agent_category == "custom_agent"

    @property
    def lifecycle_state(self) -> str:
        if self.builtin and self.enabled:
            return "system_builtin"
        return "enabled" if self.enabled else "disabled"

    @property
    def definition_source(self) -> str:
        if self.builtin:
            return "system_builtin"
        return str(self.metadata.get("definition_source") or "user_created")

    @property
    def lifecycle_policy(self) -> str:
        return str(self.metadata.get("lifecycle_policy") or ("system_builtin" if self.builtin else "user_managed"))

    @property
    def mutable_fields(self) -> tuple[str, ...]:
        return (
            "agent_name",
            "interface_target",
            "description",
            "enabled",
            "editable",
            "default_soul_id",
            "default_projection_id",
            "metadata",
        )

    @property
    def governance_status(self) -> str:
        return "system_builtin" if self.builtin else "task_managed"

    @property
    def deletable(self) -> str:
        return "delete_allowed"

    @property
    def disable_allowed(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["display_name"] = self.display_name
        payload["profile_type"] = self.profile_type
        payload["owner_system"] = self.owner_system
        payload["lifecycle_state"] = self.lifecycle_state
        payload["definition_source"] = self.definition_source
        payload["lifecycle_policy"] = self.lifecycle_policy
        payload["mutable_fields"] = list(self.mutable_fields)
        payload["governance_status"] = self.governance_status
        payload["deletable"] = self.deletable
        payload["disable_allowed"] = self.disable_allowed
        payload["builtin_kind"] = self.builtin_kind
        payload["agent_template_id"] = self.agent_template_id
        payload["delegation_enabled"] = self.delegation_enabled
        payload["group_eligible"] = self.group_eligible
        return payload


@dataclass(frozen=True, slots=True)
class AgentLifecycleRecord:
    record_id: str
    agent_id: str
    action: str
    operator: str = "system"
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


