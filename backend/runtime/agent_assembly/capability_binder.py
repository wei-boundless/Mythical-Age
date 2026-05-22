from __future__ import annotations

from typing import Any

from .models import AgentAssemblyContract, CapabilityAssemblyBinding


def bind_capabilities(assembly: AgentAssemblyContract) -> CapabilityAssemblyBinding:
    binding = assembly.capability_binding
    visible_tools = tuple(str(item).strip() for item in binding.visible_tools if str(item).strip())
    dispatchable_tools = tuple(str(item).strip() for item in binding.dispatchable_tools if str(item).strip())
    allowed_operations = tuple(str(item).strip() for item in binding.allowed_operations if str(item).strip())
    return CapabilityAssemblyBinding(
        allowed_operations=allowed_operations,
        visible_tools=visible_tools,
        dispatchable_tools=dispatchable_tools,
        mcp_routes=tuple(str(item).strip() for item in binding.mcp_routes if str(item).strip()),
        delegated_agent_ids=tuple(str(item).strip() for item in binding.delegated_agent_ids if str(item).strip()),
        metadata=dict(binding.metadata),
    )


def capability_binding_snapshot(assembly: AgentAssemblyContract) -> dict[str, Any]:
    return bind_capabilities(assembly).to_dict()
