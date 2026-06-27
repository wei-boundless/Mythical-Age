from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout


@dataclass(frozen=True, slots=True)
class RuntimeResourceInventoryItem:
    resource_id: str
    title: str
    authority_layer: str
    path: str
    runtime_consumer: str
    can_authorize_side_effects: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeResourceInventory:
    inventory_id: str
    items: tuple[RuntimeResourceInventoryItem, ...]
    authority: str = "capability_system.resource_inventory"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["items"] = [item.to_dict() for item in self.items]
        return payload


def build_runtime_resource_inventory(base_dir: Path | str | None = None) -> RuntimeResourceInventory:
    layout = ProjectLayout.from_backend_dir(base_dir or Path("."))
    items = (
        RuntimeResourceInventoryItem(
            resource_id="resource.user_current_turn",
            title="User Current Turn",
            authority_layer="L0_current_turn",
            path="runtime.request.message",
            runtime_consumer="intent_and_obligation_builder",
            can_authorize_side_effects=True,
            notes="Current user instruction is the highest semantic authority.",
        ),
        RuntimeResourceInventoryItem(
            resource_id="resource.execution_obligation",
            title="Execution Obligation",
            authority_layer="L1_execution_obligation",
            path="backend/task_system/contracts/execution_obligation.py",
            runtime_consumer="semantic_contract.runtime_policy.agent_runtime_control",
            can_authorize_side_effects=True,
            notes="Hard source for required read/write/verify/deliver and forbidden actions.",
        ),
        RuntimeResourceInventoryItem(
            resource_id="resource.task_domains",
            title="Task Domains",
            authority_layer="L4_directory_resource",
            path=str(layout.tasks_dir / "task_domains.json"),
            runtime_consumer="admin_and_resource_filtering",
            can_authorize_side_effects=False,
            notes="Directory/catalog resource only; not a runtime intent classifier.",
        ),
        RuntimeResourceInventoryItem(
            resource_id="resource.task_graphs",
            title="Task Graphs",
            authority_layer="L4_task_graph_resource",
            path=str(layout.tasks_dir / "task_graphs.json"),
            runtime_consumer="graph_system.scheduler",
            can_authorize_side_effects=False,
            notes="Graph resources compile into runtime obligations and state transitions.",
        ),
        RuntimeResourceInventoryItem(
            resource_id="resource.agent_system_agents",
            title="Agent System Agents",
            authority_layer="L5_agent_system_resource",
            path=str(layout.agent_system_dir / "agents.json"),
            runtime_consumer="subagent_lifecycle_and_runtime_assembly",
            can_authorize_side_effects=False,
            notes="Agent resources provide execution roles, not current-turn permission.",
        ),
        RuntimeResourceInventoryItem(
            resource_id="resource.runtime_checkpoint",
            title="Runtime Checkpoint",
            authority_layer="L7_persistent_state",
            path=str(layout.runtime_state_dir / "checkpoints"),
            runtime_consumer="agent_runtime.resume",
            can_authorize_side_effects=False,
            notes="Checkpoint restores progress evidence, then current turn is re-evaluated.",
        ),
    )
    return RuntimeResourceInventory(inventory_id="runtime-resource-inventory:default", items=items)



