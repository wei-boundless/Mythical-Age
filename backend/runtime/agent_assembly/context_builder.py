from __future__ import annotations

from typing import Any

from .models import AgentAssemblyContract, AssemblyPort


def build_model_context(assembly: AgentAssemblyContract) -> dict[str, Any]:
    return {
        "assembly_id": assembly.assembly_id,
        "work_order_id": assembly.work_order_id,
        "task_ref": assembly.task_ref,
        "executor_type": assembly.executor_type,
        "agent_id": assembly.agent_id,
        "agent_profile_id": assembly.agent_profile_id,
        "runtime_lane": assembly.runtime_lane,
        "prompt_manifest_ref": assembly.prompt_manifest_ref,
        "model_profile_id": assembly.model_profile_id,
        "projection_id": assembly.projection_id,
        "soul_id": assembly.soul_id,
        "memory_binding": assembly.memory_binding.to_dict(),
        "capability_binding": assembly.capability_binding.to_dict(),
        "output_boundary": assembly.output_boundary.to_dict(),
        "current_turn_context": dict(assembly.current_turn_context),
        "visible_ports": [port.to_dict() for port in assembly.ports if port.mode == "input" or port.required],
    }


def compact_visible_sections(assembly: AgentAssemblyContract) -> list[dict[str, Any]]:
    prompt = assembly.prompt_assembly
    if prompt is None:
        return []
    sections: list[dict[str, Any]] = []
    for port in prompt.visible_sections:
        sections.append(port.to_dict())
    return sections
