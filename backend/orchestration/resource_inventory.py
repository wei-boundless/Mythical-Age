from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


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
    authority: str = "orchestration.runtime_resource_inventory"

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
            path="backend/intent/execution_obligation.py",
            runtime_consumer="semantic_contract.mode_policy.professional_driver",
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
            runtime_consumer="task_graph_scheduler.professional_runtime",
            can_authorize_side_effects=False,
            notes="Graph resources compile into runtime obligations and state transitions.",
        ),
        RuntimeResourceInventoryItem(
            resource_id="resource.orchestration_agents",
            title="Orchestration Agents",
            authority_layer="L5_orchestration_resource",
            path=str(layout.orchestration_dir / "agents.json"),
            runtime_consumer="delegation_and_runtime_assembly",
            can_authorize_side_effects=False,
            notes="Agent resources provide execution roles, not current-turn permission.",
        ),
        RuntimeResourceInventoryItem(
            resource_id="resource.soul_projection",
            title="Soul Projection",
            authority_layer="L6_projection_style",
            path="backend/soul/projections/catalog.json",
            runtime_consumer="prompt_manifest_and_projection_view",
            can_authorize_side_effects=False,
            notes="Projection affects expression and posture only; it cannot override obligations.",
        ),
        RuntimeResourceInventoryItem(
            resource_id="resource.runtime_checkpoint",
            title="Runtime Checkpoint",
            authority_layer="L7_persistent_state",
            path=str(layout.runtime_state_dir / "checkpoints"),
            runtime_consumer="professional_run_resume",
            can_authorize_side_effects=False,
            notes="Checkpoint restores progress evidence, then current turn is re-evaluated.",
        ),
    )
    return RuntimeResourceInventory(inventory_id="runtime-resource-inventory:default", items=items)
