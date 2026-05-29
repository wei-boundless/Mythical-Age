from __future__ import annotations

from pathlib import Path
from typing import Any

from prompt_library.manifest_validation import build_prompt_manifest_validation

from ..identity import normalize_agent_id
from ..profiles.body_registry import BodyProfileRegistry
from ..profiles.runtime_profile_models import AgentRuntimeProfile
from ..profiles.runtime_profile_registry import AgentRuntimeRegistry
from .runtime_spec_models import AgentRuntimeSpec, TaskBodyOrchestration


def build_orchestration_runtime_bundle(
    *,
    base_dir: Path,
    session_id: str,
    task_id: str,
    user_goal: str,
    task_assembly_bundle: dict[str, Any],
    memory_runtime_view: dict[str, Any] | None = None,
    context_policy_result: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    agent_runtime_profile: AgentRuntimeProfile | None = None,
) -> dict[str, Any]:
    base_dir = Path(base_dir)
    task_contract = dict(task_assembly_bundle.get("task_contract") or {})
    task_execution_assembly = dict(task_assembly_bundle.get("task_execution_assembly") or {})
    task_spec = dict(task_assembly_bundle.get("task_spec") or {})
    selected_recipe = dict(task_assembly_bundle.get("selected_recipe") or {})
    task_workflow = dict(task_assembly_bundle.get("_task_workflow_obj") or {})
    binding = dict(task_assembly_bundle.get("binding") or {})
    operation_requirement = dict(task_assembly_bundle.get("operation_requirement") or {})
    memory_request_profile = dict(task_assembly_bundle.get("task_memory_request_profile") or {})
    current_turn_payload = dict(current_turn_context or task_assembly_bundle.get("current_turn_context") or {})
    memory_view = dict(memory_runtime_view or {})
    context_policy = dict(context_policy_result or {})

    explicit_context_agent_id = normalize_agent_id(str(current_turn_payload.get("agent_id") or "").strip())
    if explicit_context_agent_id:
        current_turn_payload["agent_id"] = explicit_context_agent_id
    agent_id = normalize_agent_id(str(getattr(agent_runtime_profile, "agent_id", "") or explicit_context_agent_id or "").strip())
    if explicit_context_agent_id and not agent_id:
        raise ValueError(f"TaskGraph node agent has no runtime profile: {explicit_context_agent_id}")
    runtime_profile = agent_runtime_profile or AgentRuntimeRegistry(base_dir).get_profile(agent_id)
    if explicit_context_agent_id:
        if runtime_profile is None:
            raise ValueError(f"TaskGraph node agent has no runtime profile: {explicit_context_agent_id}")
        if normalize_agent_id(str(getattr(runtime_profile, "agent_id", "") or "").strip()) != explicit_context_agent_id:
            raise ValueError(
                "TaskGraph node agent profile mismatch: "
                f"requested {explicit_context_agent_id}, got {getattr(runtime_profile, 'agent_id', '')}"
            )
    agent_id = str(getattr(runtime_profile, "agent_id", "") or agent_id).strip() or "agent:0"
    profile_registry = BodyProfileRegistry(base_dir)

    body_profile = profile_registry.build_agent_body_profile(
        agent_id=agent_id,
        runtime_profile=runtime_profile,
    )
    prompt_profile = profile_registry.build_prompt_structure_profile(
        agent_id=agent_id,
        task_mode=str(task_execution_assembly.get("task_mode") or ""),
        output_contract_id=str(task_execution_assembly.get("output_contract_id") or ""),
    )
    memory_scope_profile = profile_registry.build_memory_scope_profile(
        agent_id=agent_id,
        runtime_profile=runtime_profile,
        memory_request_profile=memory_request_profile,
    )
    output_boundary_profile = profile_registry.build_output_boundary_profile(
        agent_id=agent_id,
        runtime_profile=runtime_profile,
        output_contract_id=str(task_execution_assembly.get("output_contract_id") or ""),
    )

    prompt_contract = _explicit_prompt_contract(
        task_id=task_id,
        user_goal=user_goal,
        task_contract=task_contract,
        task_execution_assembly=task_execution_assembly,
        task_spec=task_spec,
        task_workflow=task_workflow,
    )
    prompt_manifest = _prompt_manifest_from_contract(
        session_id=session_id,
        task_id=task_id,
        current_turn_context=current_turn_payload,
        prompt_contract=prompt_contract,
        interaction_mode=_interaction_mode(task_contract=task_contract, task_execution_assembly=task_execution_assembly),
    )
    orchestration = TaskBodyOrchestration(
        orchestration_id=f"orchestration:{task_id}",
        task_id=task_id,
        agent_id=agent_id,
        task_execution_assembly_ref=str(task_execution_assembly.get("assembly_id") or ""),
        body_profile_ref=body_profile.body_profile_id,
        prompt_structure_profile_ref=prompt_profile.profile_id,
        memory_scope_profile_ref=memory_scope_profile.profile_id,
        output_boundary_profile_ref=output_boundary_profile.profile_id,
        stage_plan={
            "stage_owner": "orchestration",
            "section_order": list(prompt_profile.section_order),
            "projection_policy": prompt_profile.stage_projection_policy,
            "current_turn_ref": str(current_turn_payload.get("turn_id") or ""),
            "prompt_contract_ref": str(prompt_contract.get("contract_id") or ""),
        },
        resource_binding_plan={
            "operation_requirement_ref": str(operation_requirement.get("requirement_id") or ""),
            "required_operations": list(operation_requirement.get("required_operations") or ()),
            "optional_operations": list(operation_requirement.get("optional_operations") or ()),
            "approval_policy": str(dict(operation_requirement.get("metadata") or {}).get("approval_policy") or "default"),
        },
        verification_gate_plan={
            "task_constraints": dict(task_execution_assembly.get("task_constraints") or {}),
            "safety_envelope": dict(task_execution_assembly.get("safety_envelope") or {}),
        },
        fallback_plan={
            "runtime_executable_default": True,
            "fallback_policy": "fail_closed",
        },
        prompt_manifest=prompt_manifest,
        diagnostics={
            "builder": "orchestration.build_orchestration_runtime_bundle",
            "soul_runtime_projection_enabled": False,
            "prompt_manifest_ref": str(prompt_manifest.get("manifest_id") or ""),
            "memory_view_ref": str(memory_view.get("view_id") or ""),
            "context_policy_ref": _context_policy_ref(context_policy),
            "continuation_decision": dict(current_turn_payload.get("continuation_decision") or {}),
        },
    )
    runtime_spec = AgentRuntimeSpec(
        runtime_spec_id=f"rtspec:{task_id}",
        task_id=task_id,
        session_id=session_id,
        agent_id=agent_id,
        task_execution_assembly_ref=str(task_execution_assembly.get("assembly_id") or ""),
        task_body_orchestration_ref=orchestration.orchestration_id,
        context_input_refs=tuple(
            item
            for item in (
                str(memory_view.get("view_id") or ""),
                _context_policy_ref(context_policy),
                str(current_turn_payload.get("turn_id") or ""),
            )
            if item
        ),
        resource_policy_candidate_ref=str(operation_requirement.get("requirement_id") or ""),
        input_contract_ref=str(task_execution_assembly.get("input_contract_id") or task_contract.get("input_contract_id") or ""),
        output_contract_ref=str(task_execution_assembly.get("output_contract_id") or task_contract.get("output_contract_id") or ""),
        runtime_executable=True,
        diagnostics={
            "builder": "orchestration.build_orchestration_runtime_bundle",
            "body_profile_ref": body_profile.body_profile_id,
            "prompt_structure_profile_ref": prompt_profile.profile_id,
            "memory_scope_profile_ref": memory_scope_profile.profile_id,
            "output_boundary_profile_ref": output_boundary_profile.profile_id,
            "soul_runtime_projection_enabled": False,
            "continuation_decision": dict(current_turn_payload.get("continuation_decision") or {}),
        },
    )
    return {
        "agent_body_profile": body_profile.to_dict(),
        "prompt_structure_profile": prompt_profile.to_dict(),
        "memory_scope_profile": memory_scope_profile.to_dict(),
        "output_boundary_profile": output_boundary_profile.to_dict(),
        "task_body_orchestration": orchestration.to_dict(),
        "agent_runtime_spec": runtime_spec.to_dict(),
        "runtime_executable": True,
    }


def _prompt_manifest_from_contract(
    *,
    session_id: str,
    task_id: str,
    current_turn_context: dict[str, Any],
    prompt_contract: dict[str, Any],
    interaction_mode: str,
) -> dict[str, Any]:
    section_payloads = _prompt_sections_from_contract(prompt_contract)
    validation = build_prompt_manifest_validation(
        interaction_mode=interaction_mode,
        sections=section_payloads,
    )
    assembly_order = [
        str(item.get("section_id") or "")
        for item in section_payloads
        if str(item.get("section_id") or "")
    ]
    return {
        "authority": "orchestration.prompt_manifest",
        "manifest_id": f"prompt-manifest:{task_id}",
        "task_id": task_id,
        "session_id": session_id,
        "turn_id": str(current_turn_context.get("turn_id") or ""),
        "assembly_order": assembly_order,
        "total_sections": len(section_payloads),
        "total_chars": sum(int(item.get("chars") or len(str(item.get("content") or ""))) for item in section_payloads),
        "sections": section_payloads,
        "validation": validation,
    }


def _explicit_prompt_contract(
    *,
    task_id: str,
    user_goal: str,
    task_contract: dict[str, Any],
    task_execution_assembly: dict[str, Any],
    task_spec: dict[str, Any],
    task_workflow: dict[str, Any],
) -> dict[str, Any]:
    prompt_contract = dict(
        task_contract.get("prompt_contract")
        or task_execution_assembly.get("prompt_contract")
        or task_workflow.get("prompt_contract")
        or {}
    )
    role_prompt = _first_text(
        prompt_contract.get("role_prompt"),
        task_workflow.get("prompt"),
        task_contract.get("role_prompt"),
    )
    task_instruction = _first_text(
        prompt_contract.get("task_instruction"),
        task_contract.get("task_instruction"),
        task_contract.get("task_run_goal"),
        task_contract.get("user_goal"),
        user_goal,
    )
    output_instruction = _first_text(
        prompt_contract.get("output_instruction"),
        task_contract.get("output_instruction"),
        task_execution_assembly.get("output_instruction"),
        task_spec.get("summary"),
    )
    return {
        "contract_id": f"orchprompt:{task_id}",
        "task_id": task_id,
        "role_prompt": role_prompt,
        "task_instruction": task_instruction,
        "output_instruction": output_instruction,
        "forbidden_behavior": _string_list(prompt_contract.get("forbidden_behavior") or task_contract.get("forbidden_behavior")),
        "definition_of_done": _string_list(
            prompt_contract.get("definition_of_done")
            or task_contract.get("definition_of_done")
            or task_contract.get("completion_criteria")
        ),
        "metadata": {
            "authority": "orchestration.explicit_prompt_contract",
            "source": "task_contract_or_workflow",
        },
    }


def _prompt_sections_from_contract(prompt_contract: dict[str, Any]) -> list[dict[str, Any]]:
    section_specs = (
        ("role_prompt", "graph_node.role", "角色职责"),
        ("task_instruction", "graph_node.task_instruction", "任务说明"),
        ("output_instruction", "graph_node.output_instruction", "输出要求"),
    )
    sections: list[dict[str, Any]] = []
    for order, (field, source_type, title) in enumerate(section_specs, start=1):
        content = str(prompt_contract.get(field) or "").strip()
        if not content:
            continue
        sections.append(_section(field, source_type=source_type, title=title, content=content, order=order))
    forbidden = _string_list(prompt_contract.get("forbidden_behavior"))
    if forbidden:
        sections.append(
            _section(
                "forbidden_behavior",
                source_type="graph_node.forbidden_behavior",
                title="禁止事项",
                content="\n".join(f"- {item}" for item in forbidden),
                order=4,
            )
        )
    done = _string_list(prompt_contract.get("definition_of_done"))
    if done:
        sections.append(
            _section(
                "definition_of_done",
                source_type="graph_node.definition_of_done",
                title="完成标准",
                content="\n".join(f"- {item}" for item in done),
                order=5,
            )
        )
    return sections


def _section(section_id: str, *, source_type: str, title: str, content: str, order: int) -> dict[str, Any]:
    return {
        "section_id": section_id,
        "title": title,
        "source_type": source_type,
        "source_id": "explicit_prompt_contract",
        "owner_layer": "task",
        "cache_scope": "task_stable",
        "visible_to_model": True,
        "content": content,
        "chars": len(content),
        "order": order,
    }


def _interaction_mode(*, task_contract: dict[str, Any], task_execution_assembly: dict[str, Any]) -> str:
    runtime_profile = dict(task_contract.get("runtime_profile") or {})
    mode_policy = dict(task_contract.get("runtime_mode_policy") or task_contract.get("mode_policy") or {})
    return str(
        mode_policy.get("interaction_mode")
        or runtime_profile.get("interaction_mode")
        or task_execution_assembly.get("task_mode")
        or "professional_mode"
    ).strip()


def _first_text(*values: Any) -> str:
    for value in values:
        item = str(value or "").strip()
        if item:
            return item
    return ""


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _context_policy_ref(context_policy_result: dict[str, Any]) -> str:
    package = dict(context_policy_result.get("package") or {})
    return str(
        context_policy_result.get("result_id")
        or package.get("package_id")
        or package.get("id")
        or package.get("rebuild_reason")
        or ""
    )


