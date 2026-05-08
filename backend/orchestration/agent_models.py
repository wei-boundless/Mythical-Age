from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


AGENT_CATEGORY_TO_SYSTEM_SLUG = {
    "main_agent": "task_system",
    "system_management_agent": "system_management",
    "worker_sub_agent": "worker_pool",
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
        if self.agent_category == "system_management_agent":
            return str(self.metadata.get("system_key") or self.metadata.get("managed_system") or "system_management")
        return AGENT_CATEGORY_TO_SYSTEM_SLUG.get(self.agent_category, "task_system")

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
        if self.builtin:
            return "system_locked"
        return str(self.metadata.get("lifecycle_policy") or "user_managed")

    @property
    def mutable_fields(self) -> tuple[str, ...]:
        if self.builtin:
            return ()
        return (
            "agent_name",
            "description",
            "enabled",
            "default_soul_id",
            "default_projection_id",
            "metadata",
        )

    @property
    def governance_status(self) -> str:
        return "system_builtin" if self.builtin else "task_managed"

    @property
    def deletable(self) -> str:
        return "never" if self.builtin else "archive_only"

    @property
    def disable_allowed(self) -> bool:
        return not self.builtin

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
