from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskNodeConfigurationSpec:
    node_config_id: str
    title: str
    description: str = ""
    node_kind: str = "agent"
    environment_scope: tuple[str, ...] = ()
    role_prompt: str = ""
    executor_ref: dict[str, Any] = field(default_factory=dict)
    contract_bindings: dict[str, Any] = field(default_factory=dict)
    model_requirements: dict[str, Any] = field(default_factory=dict)
    tool_policy: dict[str, Any] = field(default_factory=dict)
    memory_policy: dict[str, Any] = field(default_factory=dict)
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    failure_policy: dict[str, Any] = field(default_factory=dict)
    human_gate_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    authority: str = "task_system.task_node_configuration_spec"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskNodeConfigurationSpec":
        return cls(
            node_config_id=str(payload.get("node_config_id") or payload.get("id") or "").strip(),
            title=str(payload.get("title") or payload.get("node_config_id") or "未命名节点配置").strip(),
            description=str(payload.get("description") or ""),
            node_kind=str(payload.get("node_kind") or payload.get("node_type") or "agent").strip() or "agent",
            environment_scope=_tuple_of_strings(payload.get("environment_scope")),
            role_prompt=str(payload.get("role_prompt") or ""),
            executor_ref=dict(payload.get("executor_ref") or {}),
            contract_bindings=dict(payload.get("contract_bindings") or {}),
            model_requirements=dict(payload.get("model_requirements") or {}),
            tool_policy=dict(payload.get("tool_policy") or {}),
            memory_policy=dict(payload.get("memory_policy") or {}),
            artifact_policy=dict(payload.get("artifact_policy") or {}),
            failure_policy=dict(payload.get("failure_policy") or {}),
            human_gate_policy=dict(payload.get("human_gate_policy") or {}),
            metadata=dict(payload.get("metadata") or {}),
            enabled=bool(payload.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["environment_scope"] = list(self.environment_scope)
        return payload


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace(",", "\n").splitlines() if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())
