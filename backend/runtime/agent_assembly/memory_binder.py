from __future__ import annotations

from typing import Any

from .models import AgentAssemblyContract, MemoryAssemblyBinding


def bind_memory(assembly: AgentAssemblyContract) -> MemoryAssemblyBinding:
    return MemoryAssemblyBinding(
        read_scope=dict(assembly.memory_binding.read_scope),
        write_scope=dict(assembly.memory_binding.write_scope),
        snapshot_ref=str(assembly.memory_binding.snapshot_ref or assembly.memory_snapshot.get("memory_snapshot_id") or ""),
        durable_ref=str(assembly.memory_binding.durable_ref or assembly.work_order.get("durable_memory_ref") or ""),
    )


def memory_binding_snapshot(assembly: AgentAssemblyContract) -> dict[str, Any]:
    return bind_memory(assembly).to_dict()
