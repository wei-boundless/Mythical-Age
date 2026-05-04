from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agents.a2a_cards import A2A_COMPATIBLE_PROTOCOL_VERSION, build_default_agent_cards
from capability_system.mcp_adapter import MCP_COMPATIBLE_PROTOCOL_VERSION
from evidence.worker_models import AGENT_ID_BY_WORKER_ROUTE
from .operation_registry import OperationRegistry


LOCAL_WORKER_SERVER_NAME = "local-workers"


@dataclass(frozen=True, slots=True)
class WorkerRegistryEntry:
    worker_id: str
    route: str
    name: str
    description: str
    operation_id: str
    agent_id: str
    implementation_module: str
    endpoint_protocol: str = MCP_COMPATIBLE_PROTOCOL_VERSION
    a2a_protocol_version: str = A2A_COMPATIBLE_PROTOCOL_VERSION
    transport: str = "in_process"
    server_name: str = LOCAL_WORKER_SERVER_NAME
    runtime_lane: str = "worker"
    model_visibility: str = "not_direct_model_tool"
    input_modes: list[str] = field(default_factory=list)
    output_modes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    mcp_profile: dict[str, Any] = field(default_factory=dict)
    operation: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_worker_entries(operation_registry: OperationRegistry | None = None) -> list[WorkerRegistryEntry]:
    registry = operation_registry
    cards = build_default_agent_cards()
    specs = [
        {
            "worker_id": "worker:knowledge:retrieval",
            "route": "retrieval",
            "operation_id": "op.worker_retrieval",
            "implementation_module": "evidence.retrieval_worker.RetrievalWorker",
            "tags": ["rag", "retrieval", "knowledge", "local_mcp"],
        },
        {
            "worker_id": "worker:document:pdf",
            "route": "pdf",
            "operation_id": "op.worker_pdf",
            "implementation_module": "evidence.pdf_worker.PDFWorker",
            "tags": ["pdf", "document", "local_mcp"],
        },
        {
            "worker_id": "worker:data:structured",
            "route": "structured_data",
            "operation_id": "op.worker_structured_data",
            "implementation_module": "evidence.structured_data_worker.StructuredDataWorker",
            "tags": ["table", "dataset", "analytics", "local_mcp"],
        },
    ]
    entries: list[WorkerRegistryEntry] = []
    for spec in specs:
        route = str(spec["route"])
        agent_id = AGENT_ID_BY_WORKER_ROUTE.get(route, "")
        card = cards.get(agent_id)
        operation = registry.get_operation(str(spec["operation_id"])) if registry is not None else None
        entries.append(
            WorkerRegistryEntry(
                worker_id=str(spec["worker_id"]),
                route=route,
                name=card.name if card is not None else route,
                description=card.description if card is not None else "",
                operation_id=str(spec["operation_id"]),
                agent_id=agent_id,
                implementation_module=str(spec["implementation_module"]),
                input_modes=list(card.default_input_modes if card is not None else []),
                output_modes=list(card.default_output_modes if card is not None else []),
                tags=list(spec["tags"]),
                mcp_profile=dict(card.mcp_profile if card is not None else {}),
                operation=operation.to_dict() if operation is not None else {},
                diagnostics={
                    "operation_registered": operation is not None,
                    "operation_type": str(operation.operation_type if operation is not None else ""),
                    "agent_card_registered": card is not None,
                    "local_mcp_compatible": True,
                    "direct_model_tool": False,
                },
            )
        )
    return entries


def build_worker_catalog(operation_registry: OperationRegistry | None = None) -> list[dict[str, Any]]:
    return [entry.to_dict() for entry in default_worker_entries(operation_registry)]
