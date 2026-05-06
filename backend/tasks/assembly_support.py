from __future__ import annotations

from typing import Any

from capability_system.local_mcp_registry import get_local_mcp_primary_template, get_local_mcp_unit_for_template

from .bundle_models import BundleItemSpec, BundleSpec
from .definitions import default_task_definitions
from .flow_registry import TaskFlowRegistry
from .spec_models import TaskSpec
from .step_models import StepInputBinding, TaskStepBlueprint
from .workflow_registry import TaskWorkflowRegistry


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _projection_tags(task_mode: str) -> list[str]:
    if "capability_execution" in task_mode:
        return ["direct-execution", "result-first"]
    if "knowledge_retrieval" in task_mode:
        return ["evidence-first", "grounded-answer"]
    if "information_search" in task_mode:
        return ["evidence-first", "traceability"]
    if "inspection_and_correction" in task_mode:
        return ["risk-review", "consistency"]
    if "local_material_read" in task_mode:
        return ["structure-first", "precise"]
    return ["concise"]


def _task_contract_execution_mode(current_turn_context: dict[str, Any]) -> str:
    mode = str(current_turn_context.get("execution_mode") or "").strip()
    if mode == "bundle":
        return "bundle_execution"
    return "single_agent_runtime"


def _resolve_task_workflow(
    *,
    flow_registry: TaskFlowRegistry,
    workflow_registry: TaskWorkflowRegistry,
    registered_task: dict[str, Any] | None,
    selected_template,
    definitions: list[Any],
    current_turn_context: dict[str, Any],
    task_mode: str,
) -> dict[str, Any] | None:
    if registered_task:
        registered_workflow_id = str(registered_task.get("workflow_id") or "").strip()
        if registered_workflow_id:
            workflow = workflow_registry.get_workflow(registered_workflow_id)
            if workflow is not None:
                return workflow.to_dict()

    explicit_workflow_id = str(
        current_turn_context.get("workflow_id")
        or current_turn_context.get("task_workflow_id")
        or ""
    ).strip()
    if explicit_workflow_id:
        workflow = workflow_registry.get_workflow(explicit_workflow_id)
        if workflow is not None:
            return workflow.to_dict()

    linked_flow_id = str(getattr(selected_template, "metadata", {}).get("linked_flow_id") or "").strip()
    if linked_flow_id:
        flow = flow_registry.get_flow(linked_flow_id)
        if flow is not None and flow.default_workflow_id:
            workflow = workflow_registry.get_workflow(flow.default_workflow_id)
            if workflow is not None:
                return workflow.to_dict()

    for definition in definitions:
        definition_mode = str(getattr(definition, "task_mode", "") or "").strip()
        matched_flow = next(
            (flow for flow in flow_registry.list_flows() if flow.task_mode == definition_mode and flow.default_workflow_id),
            None,
        )
        if matched_flow is not None:
            workflow = workflow_registry.get_workflow(matched_flow.default_workflow_id)
            if workflow is not None:
                return workflow.to_dict()

    matched_flow = next(
        (flow for flow in flow_registry.list_flows() if flow.task_mode == task_mode and flow.default_workflow_id),
        None,
    )
    if matched_flow is not None:
        workflow = workflow_registry.get_workflow(matched_flow.default_workflow_id)
        if workflow is not None:
            return workflow.to_dict()
    return None


def _build_task_spec(
    *,
    task_id: str,
    session_id: str,
    user_goal: str,
    selected_template,
    registered_task: dict[str, Any] | None,
    task_intent_contract,
    template_match,
    bundle_spec,
    definitions: list[Any],
    current_turn_context: dict[str, Any],
    query_understanding: dict[str, Any],
    operation_requirement_ref: str,
    active_skill: dict[str, Any],
    operation_requirement: dict[str, Any],
) -> TaskSpec:
    explicit_inputs = dict(current_turn_context.get("explicit_inputs") or {})
    coordination_request_brief = _build_coordination_request_brief(
        selected_template=selected_template,
        user_goal=user_goal,
        current_turn_context=current_turn_context,
        query_understanding=query_understanding,
    )
    registered_task_policy = dict((registered_task or {}).get("task_policy") or {})
    task_structure = dict(registered_task_policy.get("task_structure") or {})
    runtime_limits = _resolve_task_runtime_limits(
        selected_template=selected_template,
        registered_task_policy=registered_task_policy,
        task_structure=task_structure,
        current_turn_context=current_turn_context,
    )
    resolved_bindings = [
        dict(item)
        for item in list(current_turn_context.get("resolved_bindings") or [])
        if isinstance(item, dict)
    ]
    step_input_bindings = _build_step_input_bindings(
        selected_template=selected_template,
        current_turn_context=current_turn_context,
        bundle_spec=bundle_spec,
    )
    requested_outputs = tuple(str(key) for key in dict(selected_template.output_schema or {}).keys()) or ("final_answer",)
    selected_skill_ids = _dedupe(
        [
            *[
                str(skill or "").strip()
                for definition in definitions
                for skill in list(getattr(definition, "default_skill_refs", ()) or ())
                if str(skill or "").strip()
            ],
            str(active_skill.get("name") or "").strip(),
        ]
    )
    return TaskSpec(
        task_id=task_id,
        task_spec_ref=f"taskspec:{task_id}",
        template_id=selected_template.template_id,
        session_id=session_id,
        user_goal=user_goal,
        inputs={
            **explicit_inputs,
            **({"coordination_request_brief": coordination_request_brief} if coordination_request_brief else {}),
            **({"bundle_spec": bundle_spec.to_dict()} if bundle_spec is not None else {}),
        },
        bindings={
            "resolved_bindings": resolved_bindings,
        },
        constraints={
            "intent": str(current_turn_context.get("intent") or query_understanding.get("intent") or ""),
            "execution_mode": str(current_turn_context.get("execution_mode") or "single"),
            "confidence": float(current_turn_context.get("confidence") or query_understanding.get("confidence") or 0.0),
            "template_match_source": str(template_match.match_source or ""),
            "template_match_reasons": list(template_match.match_reasons),
            "runtime_limits": runtime_limits,
            "candidate_tools": [
                str(item).strip()
                for item in list(query_understanding.get("candidate_tools") or [])
                if str(item).strip()
            ],
            **({"coordination_request_ref": coordination_request_brief["brief_id"]} if coordination_request_brief else {}),
        },
        current_turn_context_ref=str(current_turn_context.get("authority") or ""),
        task_intent_ref=str(task_intent_contract.task_intent_id or ""),
        template_match_ref=str(template_match.match_id or ""),
        bundle_spec_ref=bundle_spec.bundle_id if bundle_spec is not None else "",
        bundle_item_ref=_single_bundle_item_ref(bundle_spec),
        requested_outputs=requested_outputs,
        step_input_bindings=step_input_bindings,
        selected_skill_ids=tuple(selected_skill_ids),
        operation_requirement_ref=operation_requirement_ref,
        safety_envelope=dict(dict(operation_requirement.get("metadata") or {}).get("safety_envelope") or {}),
    )


def _build_coordination_request_brief(
    *,
    selected_template,
    user_goal: str,
    current_turn_context: dict[str, Any],
    query_understanding: dict[str, Any],
) -> dict[str, Any]:
    template_metadata = dict(getattr(selected_template, "metadata", {}) or {})
    coordination_task_id = str(template_metadata.get("coordination_task_id") or "").strip()
    if not coordination_task_id:
        return {}
    explicit_inputs = dict(current_turn_context.get("explicit_inputs") or {})
    context_ref_keys = (
        "selected_task_id",
        "coordination_task_id",
        "selected_coordination_task_id",
        "projection_id",
        "selected_projection_id",
        "workflow_id",
        "task_workflow_id",
        "target_root",
        "workspace_target_root",
    )
    context_refs = {
        key: current_turn_context.get(key)
        for key in context_ref_keys
        if current_turn_context.get(key) not in ("", None, [], {})
    }
    binding_refs = [
        str(item.get("binding_id") or "").strip()
        for item in list(current_turn_context.get("resolved_bindings") or [])
        if isinstance(item, dict) and str(item.get("binding_id") or "").strip()
    ]
    return {
        "authority": "task_system.coordination_request_brief",
        "brief_id": f"coordbrief:{current_turn_context.get('turn_id') or getattr(selected_template, 'template_id', 'template')}",
        "coordination_task_id": coordination_task_id,
        "template_id": str(getattr(selected_template, "template_id", "") or ""),
        "natural_request": str(user_goal or "").strip(),
        "carrying_policy": "preserve_user_request_as_runtime_brief",
        "planning_policy": "coordinator_agent_interprets_request_inside_stable_workflow",
        "explicit_inputs": explicit_inputs,
        "context_refs": context_refs,
        "binding_refs": binding_refs,
        "understanding_refs": {
            "intent": str(query_understanding.get("intent") or ""),
            "task_kind": str(query_understanding.get("task_kind") or ""),
            "route": str(query_understanding.get("route") or ""),
        },
    }


def _resolve_task_runtime_limits(
    *,
    selected_template,
    registered_task_policy: dict[str, Any],
    task_structure: dict[str, Any],
    current_turn_context: dict[str, Any],
) -> dict[str, Any]:
    template_metadata = dict(getattr(selected_template, "metadata", {}) or {})
    template_limits = dict(template_metadata.get("runtime_limits") or {})
    policy_limits = dict(registered_task_policy.get("runtime_limits") or {})
    structure_limits = dict(task_structure.get("runtime_limits") or {})
    explicit_limits = dict(current_turn_context.get("runtime_limits") or {})
    merged = {**template_limits, **policy_limits, **structure_limits, **explicit_limits}
    if not merged:
        return {}
    normalized = {
        "authority": "task_system.runtime_limits",
        "limit_mode": str(merged.get("limit_mode") or merged.get("runtime_limit_mode") or "bounded").strip(),
        "max_turns": merged.get("max_turns"),
        "max_model_calls": merged.get("max_model_calls"),
        "max_runtime_seconds": merged.get("max_runtime_seconds"),
        "max_events": merged.get("max_events"),
    }
    if normalized["limit_mode"] in {"unlimited", "no_time_limit"} or merged.get("unlimited_runtime") is True:
        normalized["limit_mode"] = "unlimited"
        normalized["max_runtime_seconds"] = None
    return {key: value for key, value in normalized.items() if value is not None or key == "max_runtime_seconds"}


def _resolve_registered_task(
    *,
    flow_registry: TaskFlowRegistry,
    current_turn_context: dict[str, Any],
) -> dict[str, Any] | None:
    specific_task_id = str(
        current_turn_context.get("selected_task_id")
        or current_turn_context.get("task_id")
        or current_turn_context.get("specific_task_id")
        or current_turn_context.get("task_assignment_id")
        or ""
    ).strip()
    if specific_task_id:
        record = flow_registry.get_specific_task_record(specific_task_id)
        if record is not None:
            projection_binding = flow_registry.get_projection_binding(specific_task_id)
            flow_contract_binding = flow_registry.get_flow_contract_binding(specific_task_id)
            flow = flow_registry.get_flow(str(flow_contract_binding.flow_contract_id if flow_contract_binding is not None else record.default_flow_contract_id or "").strip())
            return {
                "task_type": "specific_task",
                "task_id": record.task_id,
                "task_title": record.task_title,
                "task_family": record.task_family,
                "task_mode": record.task_mode,
                "workflow_id": str(record.default_workflow_id or getattr(flow, "default_workflow_id", "") or "").strip(),
                "projection_id": str(getattr(projection_binding, "default_projection_id", "") or "").strip(),
                "input_contract_id": record.input_contract_id,
                "output_contract_id": record.output_contract_id,
                "flow_id": str(getattr(flow_contract_binding, "flow_contract_id", "") or record.default_flow_contract_id or "").strip(),
                "safety_policy": dict(dict(record.task_policy or {}).get("safety_policy") or {}),
                "task_policy": dict(record.task_policy or {}),
                "template_id": str((record.metadata or {}).get("template_id") or getattr(flow, "metadata", {}).get("template_id") or ""),
                "metadata": dict(record.metadata or {}),
            }
    explicit_general_profile_id = str(
        current_turn_context.get("entry_policy_id")
        or current_turn_context.get("general_profile_id")
        or ""
    ).strip()
    if explicit_general_profile_id:
        default_general_profile = flow_registry.get_general_task_profile(explicit_general_profile_id)
    else:
        default_general_profile = next(
        (profile for profile in flow_registry.list_general_task_profiles() if profile.enabled),
        None,
        )
    if default_general_profile is None:
        return None
    return {
        "task_type": "conversation_entry_policy",
        "task_id": default_general_profile.profile_id,
        "task_title": default_general_profile.title,
        "task_family": "conversation_entry",
        "task_mode": "main_conversation_entry",
        "workflow_id": default_general_profile.default_workflow_id,
        "projection_id": default_general_profile.default_projection_id,
        "input_contract_id": default_general_profile.input_contract_id,
        "output_contract_id": default_general_profile.output_contract_id,
        "conversation_entry_policy": default_general_profile.conversation_entry_policy,
        "metadata": dict(default_general_profile.metadata or {}),
    }


def _resolve_task_family(
    *,
    registered_task: dict[str, Any] | None,
    selected_template,
    definitions: list[Any],
) -> str:
    registered_family = str((registered_task or {}).get("task_family") or "").strip()
    if registered_family:
        return registered_family
    return str(selected_template.task_family or "") or "+".join(
        _dedupe([definition.task_family for definition in definitions])
    )


def _resolve_task_mode(
    *,
    registered_task: dict[str, Any] | None,
    selected_template,
    definitions: list[Any],
) -> str:
    registered_mode = str((registered_task or {}).get("task_mode") or "").strip()
    if registered_mode:
        return registered_mode
    return str(selected_template.task_mode or "") or "+".join(
        definition.task_mode for definition in definitions
    )


def _align_runtime_definitions(
    *,
    definitions: list[Any],
    registered_task: dict[str, Any] | None,
    selected_template,
) -> list[Any]:
    if not registered_task or str(registered_task.get("task_type") or "") != "specific_task":
        return definitions

    template_id = str(getattr(selected_template, "template_id", "") or "")
    task_mode = str((registered_task or {}).get("task_mode") or getattr(selected_template, "task_mode", "") or "")
    definition_catalog = default_task_definitions()
    if template_id in {"template.dev.workspace_patch", "template.dev.light_web_game", "template.dev.arcade_game_bundle"} or task_mode in {
        "workspace_patch",
        "light_web_game",
        "arcade_game_bundle",
    }:
        return [
            definition_catalog["task.task_execution"],
            definition_catalog["task.inspection_and_correction"],
        ]
    if template_id == "template.writing.short_story" or task_mode == "short_story":
        return [
            definition_catalog["task.information_synthesis"],
            definition_catalog["task.inspection_and_correction"],
            definition_catalog["task.final_response"],
        ]
    return definitions


def _align_task_binding_with_template(
    binding,
    *,
    selected_template,
):
    template_operations = {
        str(item).strip()
        for item in [
            *list(getattr(selected_template, "required_operations", ()) or ()),
            *list(getattr(selected_template, "optional_operations", ()) or ()),
        ]
        if str(item).strip()
    }
    if not template_operations:
        return binding
    allowed_denied = tuple(
        operation
        for operation in tuple(binding.denied_operations or ())
        if str(operation).strip() not in template_operations
    )
    if allowed_denied == tuple(binding.denied_operations or ()):
        return binding
    return type(binding)(
        **{
            **binding.to_dict(),
            "skill_scope": tuple(binding.skill_scope or ()),
            "denied_skills": tuple(binding.denied_skills or ()),
            "operation_scope": tuple(binding.operation_scope or ()),
            "denied_operations": allowed_denied,
        }
    )


def _resolve_operation_approval_policy(
    *,
    merged_binding,
    selected_template,
    registered_task: dict[str, Any] | None,
) -> str:
    safety_policy = dict(getattr(selected_template, "safety_policy", {}) or {})
    write_mode = str(safety_policy.get("write_mode") or "").strip()
    if (
        registered_task
        and str(registered_task.get("task_type") or "") == "specific_task"
        and (
            str(getattr(selected_template, "task_family", "") or "") == "development"
            or write_mode in {"bounded_create", "scoped_patch"}
        )
    ):
        return "task_bounded_write"
    return str(merged_binding.approval_policy or "default")


def _build_task_safety_envelope(
    *,
    selected_template,
    registered_task: dict[str, Any] | None,
    current_turn_context: dict[str, Any],
) -> dict[str, Any]:
    template_policy = dict(getattr(selected_template, "safety_policy", {}) or {})
    registered_policy = dict((registered_task or {}).get("safety_policy") or {})
    effective_policy = {**template_policy, **registered_policy}
    explicit_target_root = str(
        current_turn_context.get("target_root")
        or current_turn_context.get("workspace_target_root")
        or dict(current_turn_context.get("explicit_inputs") or {}).get("target_root")
        or ""
    ).strip()
    write_roots = [
        str(item).strip()
        for item in list(effective_policy.get("write_roots") or effective_policy.get("default_write_roots") or [])
        if str(item).strip()
    ]
    if explicit_target_root:
        write_roots = [explicit_target_root]
    return {
        "safety_class": str(effective_policy.get("safety_class") or "S0_readonly").strip(),
        "write_mode": str(effective_policy.get("write_mode") or "none").strip(),
        "write_roots": write_roots,
        "forbidden_paths": [
            str(item).strip()
            for item in list(effective_policy.get("forbidden_paths") or [])
            if str(item).strip()
        ],
        "verification_mode": str(effective_policy.get("verification_mode") or "none").strip(),
        "task_id": str((registered_task or {}).get("task_id") or ""),
        "template_id": str(getattr(selected_template, "template_id", "") or ""),
    }


def _build_bundle_spec(
    *,
    task_id: str,
    current_turn_context: dict[str, Any],
) -> BundleSpec | None:
    bundle_items = [
        dict(item)
        for item in list(current_turn_context.get("bundle_items") or [])
        if isinstance(item, dict)
    ]
    if not bundle_items:
        return None
    bundle_id = str(current_turn_context.get("bundle_id") or f"bundle:{task_id}").strip()
    item_specs: list[BundleItemSpec] = []
    for item in bundle_items:
        ordinal = int(item.get("ordinal") or 0)
        capability_kind = str(item.get("capability_kind") or "")
        bundle_id = str(current_turn_context.get("bundle_id") or f"bundle:{task_id}")
        item_specs.append(
            BundleItemSpec(
                item_id=str(item.get("item_id") or f"{bundle_id}:item:{ordinal or len(item_specs) + 1}"),
                ordinal=ordinal,
                user_text=str(item.get("user_text") or ""),
                template_id=str(item.get("template_id") or _template_id_for_capability(capability_kind)),
                capability_kind=capability_kind,
                required_tool=str(item.get("required_tool") or ""),
                requested_outputs=tuple(
                    str(value).strip()
                    for value in list(item.get("requested_outputs") or [])
                    if str(value).strip()
                ),
                inherited_binding_refs=tuple(
                    str(value).strip()
                    for value in list(item.get("inherited_binding_refs") or [])
                    if str(value).strip()
                ),
                target_binding_ref=str(
                    item.get("target_binding_ref")
                    or (
                        dict(item.get("target_binding") or {}).get("binding_id")
                        if isinstance(item.get("target_binding"), dict)
                        else ""
                    )
                    or ""
                ),
                followup_target_ref=str(item.get("followup_target_ref") or item.get("target_ref") or ""),
                metadata=dict(item.get("metadata") or {}),
            )
        )
    return BundleSpec(
        bundle_id=bundle_id,
        parent_task_id=task_id,
        aggregation_policy="ordered_sections",
        items=tuple(item_specs),
        diagnostics={
            "item_count": len(item_specs),
            "execution_mode": str(current_turn_context.get("execution_mode") or "single"),
        },
    )


def _build_step_input_bindings(
    *,
    selected_template,
    current_turn_context: dict[str, Any],
    bundle_spec: BundleSpec | None,
) -> tuple[StepInputBinding, ...]:
    explicit_inputs = dict(current_turn_context.get("explicit_inputs") or {})
    resolved_bindings = [
        dict(item)
        for item in list(current_turn_context.get("resolved_bindings") or [])
        if isinstance(item, dict)
    ]
    inherited_binding_refs = tuple(
        _dedupe(
            [
                str(item.get("binding_id") or "").strip()
                for item in resolved_bindings
                if str(item.get("binding_id") or "").strip()
            ]
        )
    )
    explicit_input_refs = tuple(
        _dedupe(
            [f"input.{key}" for key, value in explicit_inputs.items() if value not in ("", None, [], {})]
        )
    )
    step_bindings: list[StepInputBinding] = []
    previous_step_id = ""
    for blueprint in list(getattr(selected_template, "step_blueprints", ()) or ()):
        blueprint_input_refs = tuple(str(item).strip() for item in list(blueprint.input_refs or ()) if str(item).strip())
        computed_input_refs = list(blueprint_input_refs)
        if bundle_spec is not None:
            computed_input_refs.append("input.bundle_spec")
        elif explicit_input_refs:
            computed_input_refs.extend(list(explicit_input_refs))
        private_state_refs: list[str] = []
        if previous_step_id:
            private_state_refs.append(f"step_output:{previous_step_id}")
        binding_policy = "inherit_parent_context"
        if bundle_spec is not None and str(selected_template.template_id or "") != "template.bundle.multi_capability":
            binding_policy = "bundle_item_private_context"
        output_writebacks = _step_output_writebacks(
            template_id=str(selected_template.template_id or ""),
            blueprint=blueprint,
            bundle_spec=bundle_spec,
        )
        step_bindings.append(
            StepInputBinding(
                step_id=str(blueprint.step_id or ""),
                input_refs=tuple(_dedupe(computed_input_refs)),
                inherited_parent_refs=inherited_binding_refs,
                private_state_refs=tuple(_dedupe(private_state_refs)),
                output_writebacks=output_writebacks,
                binding_policy=binding_policy,
            )
        )
        previous_step_id = str(blueprint.step_id or "")
    return tuple(step_bindings)


def _step_output_writebacks(
    *,
    template_id: str,
    blueprint: TaskStepBlueprint,
    bundle_spec: BundleSpec | None,
) -> dict[str, str]:
    step_kind = str(blueprint.step_kind or "")
    if template_id == "template.bundle.multi_capability":
        if step_kind == "understand":
            return {"bundle_plan": "runtime.bundle_plan"}
        if step_kind == "finalize":
            return {"final_answer": "task_result.final_answer", "bundle_result_refs": "state.bundle_result_refs"}
    unit = get_local_mcp_unit_for_template(template_id)
    if unit is not None and unit.source_kind in {"pdf", "dataset"}:
        if step_kind == "analyze":
            return {"task_summary_refs": "state.current_result_refs"}
        if step_kind == "finalize":
            return {"final_answer": "task_result.final_answer", "task_summary_refs": "state.current_result_refs"}
    if step_kind == "finalize":
        return {"final_answer": "task_result.final_answer"}
    if step_kind in {"write", "verify"}:
        return {"artifact_refs": "task_result.artifact_refs"}
    return {"step_result": f"runtime.step:{blueprint.step_id}:output"}


def _single_bundle_item_ref(bundle_spec: BundleSpec | None) -> str:
    if bundle_spec is None or len(bundle_spec.items) != 1:
        return ""
    return str(bundle_spec.items[0].item_id or "")


def _template_id_for_capability(capability: str) -> str:
    template_id = get_local_mcp_primary_template(capability)
    if template_id:
        return template_id
    if capability in {"weather", "gold_price"}:
        return "template.search.information_search"
    return "template.chat.general_response"
