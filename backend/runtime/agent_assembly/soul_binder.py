from __future__ import annotations

from typing import Any

from .models import AgentAssemblyContract, SoulAssemblyBinding


def bind_soul(assembly: AgentAssemblyContract) -> SoulAssemblyBinding:
    binding = assembly.soul_binding
    return SoulAssemblyBinding(
        projection_id=str(binding.projection_id or assembly.projection_id or ""),
        soul_id=str(binding.soul_id or assembly.soul_id or ""),
        prompt_manifest_ref=str(binding.prompt_manifest_ref or assembly.prompt_manifest_ref or ""),
        role_name=str(binding.role_name or (assembly.prompt_assembly.role_name if assembly.prompt_assembly is not None else "") or ""),
        role_summary=str(binding.role_summary or (assembly.prompt_assembly.role_summary if assembly.prompt_assembly is not None else "") or ""),
        metadata=dict(binding.metadata),
    )


def soul_binding_snapshot(assembly: AgentAssemblyContract) -> dict[str, Any]:
    return bind_soul(assembly).to_dict()
