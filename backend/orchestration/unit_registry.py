from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .contracts import UnitDescriptor


@dataclass(slots=True)
class UnitCatalog:
    """Registry of retained modular units before the new wiring is rebuilt."""

    units: dict[str, UnitDescriptor] = field(default_factory=dict)

    def register(self, descriptor: UnitDescriptor) -> None:
        if descriptor.decision_authority:
            raise ValueError("modular units cannot register decision authority")
        self.units[descriptor.unit_id] = descriptor

    def extend(self, descriptors: Iterable[UnitDescriptor]) -> None:
        for descriptor in descriptors:
            self.register(descriptor)

    def get(self, unit_id: str) -> UnitDescriptor | None:
        return self.units.get(unit_id)

    def by_type(self, unit_type: str) -> list[UnitDescriptor]:
        return [item for item in self.units.values() if item.unit_type == unit_type]

    def to_list(self) -> list[dict[str, object]]:
        return [item.to_dict() for item in self.units.values()]


BASE_UNIT_DESCRIPTORS: tuple[UnitDescriptor, ...] = (
    UnitDescriptor(
        unit_id="tools.runtime",
        unit_type="tool",
        owner_module="backend.tools.runtime",
        ports=("execution", "artifact", "trace"),
        capability_tags=("tool_contract", "risk_tags"),
    ),
    UnitDescriptor(
        unit_id="skills.registry",
        unit_type="skill",
        owner_module="backend.skill_system",
        ports=("candidate", "policy", "trace"),
        capability_tags=("skill_contract", "prompt_view"),
    ),
    UnitDescriptor(
        unit_id="mcp.retrieval",
        unit_type="mcp",
        owner_module="backend.evidence.retrieval_worker",
        ports=("execution", "artifact", "trace"),
        capability_tags=("retrieval", "evidence"),
    ),
    UnitDescriptor(
        unit_id="mcp.pdf",
        unit_type="mcp",
        owner_module="backend.evidence.pdf_worker",
        ports=("execution", "artifact", "trace"),
        capability_tags=("pdf", "document_evidence"),
    ),
    UnitDescriptor(
        unit_id="mcp.structured_data",
        unit_type="mcp",
        owner_module="backend.evidence.structured_data_worker",
        ports=("execution", "artifact", "trace"),
        capability_tags=("table", "data_analysis"),
    ),
    UnitDescriptor(
        unit_id="memory.facade",
        unit_type="memory",
        owner_module="backend.memory_system.facade",
        ports=("candidate", "policy", "commit", "trace"),
        capability_tags=("session_memory", "durable_memory"),
    ),
    UnitDescriptor(
        unit_id="runtime.model",
        unit_type="agent",
        owner_module="backend.runtime.model_gateway.model_runtime",
        ports=("execution", "artifact", "trace"),
        capability_tags=("model_call", "stream"),
    ),
    UnitDescriptor(
        unit_id="session.store",
        unit_type="session",
        owner_module="backend.sessions.store",
        ports=("artifact", "commit", "trace"),
        capability_tags=("session_storage",),
    ),
    UnitDescriptor(
        unit_id="task.coordinator",
        unit_type="task",
        owner_module="backend.task_system.services.assembly_builder",
        ports=("artifact", "commit", "trace"),
        capability_tags=("task_record", "result_ref"),
    ),
)


def build_base_unit_catalog() -> UnitCatalog:
    catalog = UnitCatalog()
    catalog.extend(BASE_UNIT_DESCRIPTORS)
    return catalog


