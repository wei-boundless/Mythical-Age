from __future__ import annotations

from typing import Any

from request_intent.frame_access import (
    capability_needs,
    turn_signals,
)
from capability_system.local_mcp_registry import get_local_mcp_unit_for_source_kind
from intent.execution_obligation import build_execution_obligation

from task_system.services.bundle_models import BundleItemSpec, BundleSpec
from task_system.tasks.definitions import default_task_definitions
from task_system.registry.flow_registry import TaskFlowRegistry
from task_system.contracts.match_contracts import TaskIntentContract
from task_system.contracts.task_requirement_contracts import build_task_requirement_contract
from task_system.tasks.spec_models import TaskSpec
from task_system.tasks.step_models import StepInputBinding, TaskStepBlueprint
from task_system.registry.workflow_registry import TaskWorkflowRegistry


def _record_task_mode(record: Any, flow: Any | None = None) -> str:
    policy = dict(getattr(record, "task_policy", {}) or {})
    structure = dict(policy.get("task_structure") or {})
    metadata = dict(getattr(record, "metadata", {}) or {})
    flow_metadata = dict(getattr(flow, "metadata", {}) or {}) if flow is not None else {}
    return str(
        metadata.get("task_mode")
        or structure.get("task_mode")
        or flow_metadata.get("task_mode")
        or ""
    ).strip()


def _flow_task_mode(flow: Any) -> str:
    metadata = dict(getattr(flow, "metadata", {}) or {})
    return str(metadata.get("task_mode") or "").strip()


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


def _task_contract_execution_mode(current_turn_context: dict[str, Any]) -> str:
    mode = str(current_turn_context.get("execution_mode") or "").strip()
    if mode == "bundle":
        return "bundle_execution"
    return "single_agent_runtime"


def build_runtime_task_intent_contract(
    *,
    session_id: str,
    task_id: str,
    user_goal: str,
    query_understanding: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
) -> TaskIntentContract:
    understanding = dict(query_understanding or {})
    current_turn = dict(current_turn_context or {})
    explicit_inputs = dict(current_turn.get("explicit_inputs") or {})
    bundle_items = [
        dict(item)
        for item in list(current_turn.get("bundle_items") or [])
        if isinstance(item, dict)
    ]
    resolved_bindings = [
        dict(item)
        for item in list(current_turn.get("resolved_bindings") or [])
        if isinstance(item, dict)
    ]
    capability_requests = _dedupe(
        [
            *[
                str(item or "").strip()
                for item in sorted(capability_needs(understanding))
                if str(item or "").strip()
            ],
            *[
                str(item or "").strip()
                for item in list(explicit_inputs.get("capability_requests") or [])
                if str(item or "").strip()
            ],
        ]
    )
    capability_requests = _dedupe(
        [
            *capability_requests,
            *_capability_requests_from_intent(current_turn),
        ]
    )
    execution_obligation = build_execution_obligation(
        session_id=session_id,
        task_id=task_id,
        user_goal=user_goal,
        explicit_inputs=explicit_inputs,
        current_turn_context=current_turn,
    )
    execution_obligation_payload = execution_obligation.to_dict()
    if _current_turn_is_task_graph_node_runtime(current_turn):
        execution_obligation_payload = _task_graph_node_execution_obligation_payload(execution_obligation_payload)
    current_turn_with_obligation = {
        **current_turn,
        "execution_obligation": execution_obligation_payload,
    }
    followup_target_refs = _dedupe(
        [
            *[
                str(item.get("followup_target_ref") or item.get("target_ref") or "").strip()
                for item in bundle_items
                if isinstance(item, dict)
            ],
            *[
                str(item or "").strip()
                for item in list(current_turn.get("followup_target_refs") or [])
                if str(item or "").strip()
            ],
        ]
    )
    semantic_contract = build_task_requirement_contract(
        session_id=session_id,
        task_id=task_id,
        user_goal=user_goal,
        query_understanding=understanding,
        current_turn_context=current_turn_with_obligation,
        explicit_inputs=explicit_inputs,
        execution_obligation=execution_obligation_payload,
    )
    runtime_policy = build_runtime_policy_request(
        task_requirement_contract=semantic_contract.to_dict(),
        query_understanding=understanding,
        current_turn_context=current_turn_with_obligation,
        execution_obligation=execution_obligation_payload,
    )
    return TaskIntentContract(
        task_intent_id=f"task-intent:{session_id}:{task_id}",
        session_id=session_id,
        task_id=task_id,
        user_goal=user_goal,
        intent_kind=str(dict(current_turn.get("agent_turn_action_request") or {}).get("action_type") or current_turn.get("intent") or ""),
        execution_intent=_execution_intent_from_context(
            current_turn_context=current_turn,
            bundle_items=bundle_items,
            query_understanding=understanding,
        ),
        requested_outputs=tuple(
            _intent_requested_outputs(
                explicit_inputs=explicit_inputs,
                bundle_items=bundle_items,
                capability_requests=capability_requests,
                current_turn_context=current_turn,
            )
        ),
        explicit_inputs=explicit_inputs,
        source_binding_refs=tuple(
            _dedupe(
                [
                    str(item.get("binding_id") or "").strip()
                    for item in resolved_bindings
                    if str(item.get("binding_id") or "").strip()
                ]
            )
        ),
        followup_target_refs=tuple(followup_target_refs),
        capability_requests=tuple(capability_requests),
        execution_obligation=execution_obligation_payload,
        task_requirement_contract=semantic_contract.to_dict(),
        runtime_policy=runtime_policy,
        diagnostics={
            "execution_mode": str(current_turn.get("execution_mode") or "single"),
            "agent_turn_action_request": dict(current_turn.get("agent_turn_action_request") or {}),
            "task_contract_seed": dict(current_turn.get("task_contract_seed") or {}),
            "semantic_task_type": semantic_contract.task_goal_type,
            "professional_profile_id": semantic_contract.professional_profile_id,
            "execution_obligation": {
                "required_reads": len(list(execution_obligation_payload.get("required_reads") or [])),
                "required_writes": len(list(execution_obligation_payload.get("required_writes") or [])),
                "required_commands": len(list(execution_obligation_payload.get("required_commands") or [])),
                "required_verifications": len(list(execution_obligation_payload.get("required_verifications") or [])),
                "forbidden_actions": list(execution_obligation_payload.get("forbidden_actions") or []),
            },
            "bundle_item_count": len(bundle_items),
            "preferred_skill": str(understanding.get("preferred_skill") or ""),
            "followup_target_kind": str(
                turn_signals(understanding).get("followup_target_kind")
                or explicit_inputs.get("followup_target_kind")
                or ""
            ),
        },
    )


def build_runtime_policy_request(
    *,
    task_requirement_contract: dict[str, Any] | None = None,
    query_understanding: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    execution_obligation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = dict(task_requirement_contract or {})
    understanding = dict(query_understanding or {})
    current_turn = dict(current_turn_context or {})
    obligation = dict(execution_obligation or contract.get("execution_obligation") or current_turn.get("execution_obligation") or {})
    task_goal_type = str(contract.get("task_goal_type") or "").strip()
    graph_node_runtime = _current_turn_is_task_graph_node_runtime(current_turn)
    real_work_required = _obligation_requires_real_work(obligation, contract=contract, understanding=understanding)
    return {
        "authority": "task_system.runtime_policy_request",
        "policy_reason": "task_graph_node_runtime" if graph_node_runtime else ("real_work_required" if real_work_required else "semantic_task_contract"),
        "recipe_id": "runtime.recipe.graph_node_task" if graph_node_runtime else "runtime.recipe.single_agent_task",
        "semantic_contract_required": True,
        "planning_policy": {"specified_plan_allowed": True, "todo_required_when_task_run": bool(real_work_required)},
        "task_lifecycle_policy": {"request_task_run": True, "requires_completion_evidence": True},
        "diagnostics": {
            "task_goal_type": task_goal_type,
            "professional_profile_id": str(contract.get("professional_profile_id") or ""),
            "agent_turn_action_request": dict(understanding.get("agent_turn_action_request") or {}),
            "task_contract_seed": dict(understanding.get("task_contract_seed") or {}),
            "execution_obligation": _obligation_summary(obligation),
            "tool_permission_authority": "harness.runtime.assembly",
            "sandbox_authority": "task_environment",
        },
    }

def _obligation_requires_real_work(obligation: dict[str, Any], *, contract: dict[str, Any], understanding: dict[str, Any]) -> bool:
    item = dict(obligation or {})
    forbidden = {
        str(value).strip()
        for value in list(item.get("forbidden_actions") or [])
        if str(value).strip()
    }
    if forbidden.intersection({"modify_code", "write_file", "edit_file"}):
        return False
    if bool(
        list(item.get("required_writes") or [])
        or list(item.get("required_commands") or [])
        or list(item.get("required_verifications") or [])
    ):
        return True
    seed = dict(understanding.get("task_contract_seed") or {})
    resource_contract = dict(seed.get("resource_contract") or {})
    task_goal_type = str(contract.get("task_goal_type") or "").strip()
    return bool(
        task_goal_type
        or list(resource_contract.get("required_write_files") or [])
        or list(resource_contract.get("required_write_dirs") or [])
        or list(seed.get("deliverables") or [])
    )


def _obligation_summary(obligation: dict[str, Any]) -> dict[str, Any]:
    item = dict(obligation or {})
    return {
        "required_reads": len(list(item.get("required_reads") or [])),
        "required_writes": len(list(item.get("required_writes") or [])),
        "required_commands": len(list(item.get("required_commands") or [])),
        "required_verifications": len(list(item.get("required_verifications") or [])),
        "forbidden_actions": list(item.get("forbidden_actions") or []),
    }


def _current_turn_is_task_graph_node_runtime(current_turn_context: dict[str, Any]) -> bool:
    current_turn = dict(current_turn_context or {})
    if current_turn.get("task_graph_node_runtime") is True or current_turn.get("suppress_bundle_projection") is True:
        return True
    return False


def _task_graph_node_execution_obligation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    item = dict(payload or {})
    evidence = dict(item.get("extraction_evidence") or {})
    item["required_writes"] = []
    item["required_commands"] = []
    item["required_verifications"] = []
    item["required_deliverables"] = ["node_contract_output"]
    item["forbidden_actions"] = []
    item["task_graph_node_policy"] = "orchestration_owned_side_effects"
    item["extraction_evidence"] = {
        **evidence,
        "task_graph_node_runtime": True,
        "natural_language_write_markers_ignored": True,
    }
    return item


def _execution_intent_from_context(
    *,
    current_turn_context: dict[str, Any],
    bundle_items: list[dict[str, Any]],
    query_understanding: dict[str, Any],
) -> str:
    execution_mode = str(current_turn_context.get("execution_mode") or "").strip()
    if execution_mode == "bundle" or len(bundle_items) > 1:
        return "bundle_task"
    structural_signals = dict(current_turn_context.get("structural_signals") or {})
    understanding_signals = turn_signals(query_understanding)
    explicit_inputs = dict(current_turn_context.get("explicit_inputs") or {})
    if (
        str(
            understanding_signals.get("followup_target_kind")
            or structural_signals.get("followup_target_kind")
            or explicit_inputs.get("followup_target_kind")
            or ""
        ).strip()
        == "bundle_ordinals"
    ):
        return "bundle_followup_item"
    if str(current_turn_context.get("intent") or "") == "bundle_followup" and bundle_items:
        return "bundle_followup_item"
    followup_target_kind = str(
        understanding_signals.get("followup_target_kind")
        or structural_signals.get("followup_target_kind")
        or explicit_inputs.get("followup_target_kind")
        or dict(current_turn_context.get("continuation_decision") or {}).get("followup_target_kind")
        or ""
    ).strip()
    if followup_target_kind == "active_subset":
        return "subset_followup"
    if followup_target_kind in {"active_dataset", "active_pdf"}:
        return "object_followup"
    return "single_task"


def _intent_requested_outputs(
    *,
    explicit_inputs: dict[str, Any],
    bundle_items: list[dict[str, Any]],
    capability_requests: list[str],
    current_turn_context: dict[str, Any],
) -> list[str]:
    explicit_outputs = [
        str(item or "").strip()
        for item in list(explicit_inputs.get("requested_outputs") or [])
        if str(item or "").strip()
    ]
    if explicit_outputs:
        return explicit_outputs
    if len(bundle_items) > 1 or str(current_turn_context.get("execution_mode") or "") == "bundle":
        return ["final_answer", "bundle_result_refs"]
    if bundle_items:
        item_outputs = [
            str(item or "").strip()
            for item in list(bundle_items[0].get("requested_outputs") or [])
            if str(item or "").strip()
        ]
        if item_outputs:
            return item_outputs
    followup_target_kind = str(
        dict(current_turn_context.get("explicit_inputs") or {}).get("followup_target_kind")
        or dict(current_turn_context.get("continuation_decision") or {}).get("followup_target_kind")
        or ""
    ).strip()
    if followup_target_kind == "active_subset":
        return ["final_answer", "task_summary_refs"]
    if "document_analysis" in capability_requests or "dataset_analysis" in capability_requests:
        return ["final_answer", "task_summary_refs"]
    return ["final_answer"]


def _capability_requests_from_intent(current_turn_context: dict[str, Any]) -> list[str]:
    _ = current_turn_context
    return []


def _resolve_task_workflow(
    *,
    flow_registry: TaskFlowRegistry,
    workflow_registry: TaskWorkflowRegistry,
    registered_task: dict[str, Any] | None,
    selected_recipe,
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

    linked_flow_id = str(getattr(selected_recipe, "metadata", {}).get("linked_flow_id") or "").strip()
    if linked_flow_id:
        flow = flow_registry.get_flow(linked_flow_id)
        if flow is not None and flow.default_workflow_id:
            workflow = workflow_registry.get_workflow(flow.default_workflow_id)
            if workflow is not None:
                return workflow.to_dict()

    for definition in definitions:
        definition_mode = str(getattr(definition, "task_mode", "") or "").strip()
        matched_flow = next(
            (flow for flow in flow_registry.list_flows() if _flow_task_mode(flow) == definition_mode and flow.default_workflow_id),
            None,
        )
        if matched_flow is not None:
            workflow = workflow_registry.get_workflow(matched_flow.default_workflow_id)
            if workflow is not None:
                return workflow.to_dict()

    matched_flow = next(
        (flow for flow in flow_registry.list_flows() if _flow_task_mode(flow) == task_mode and flow.default_workflow_id),
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
    selected_recipe,
    registered_task: dict[str, Any] | None,
    task_intent_contract,
    bundle_spec,
    definitions: list[Any],
    current_turn_context: dict[str, Any],
    query_understanding: dict[str, Any],
    operation_requirement_ref: str,
    skill_runtime_views: list[Any],
    operation_requirement: dict[str, Any],
) -> TaskSpec:
    explicit_inputs = dict(current_turn_context.get("explicit_inputs") or {})
    coordination_request_brief = _build_coordination_request_brief(
        selected_recipe=selected_recipe,
        user_goal=user_goal,
        current_turn_context=current_turn_context,
        query_understanding=query_understanding,
    )
    registered_task_policy = dict((registered_task or {}).get("task_policy") or {})
    task_structure = dict(registered_task_policy.get("task_structure") or {})
    runtime_limits = _resolve_task_runtime_limits(
        selected_recipe=selected_recipe,
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
        selected_recipe=selected_recipe,
        current_turn_context=current_turn_context,
        bundle_spec=bundle_spec,
    )
    requested_outputs = tuple(str(key) for key in dict(selected_recipe.output_schema or {}).keys()) or ("final_answer",)
    visible_skill_ids = {
        str((item.to_dict() if hasattr(item, "to_dict") else dict(item)).get("skill_id") or "").strip()
        for item in list(skill_runtime_views or [])
        if str((item.to_dict() if hasattr(item, "to_dict") else dict(item)).get("skill_id") or "").strip()
    }
    action_selected_skill_ids = [
        str(item).strip()
        for item in list(dict(current_turn_context.get("agent_turn_action_request") or {}).get("selected_skill_ids") or [])
        if str(item).strip()
    ]
    selected_skill_ids = _dedupe(
        [
            skill_id if skill_id.startswith("skill.") else f"skill.{skill_id}"
            for skill_id in action_selected_skill_ids
            if (skill_id if skill_id.startswith("skill.") else f"skill.{skill_id}") in visible_skill_ids
        ]
    )
    default_artifact_path = _default_task_artifact_path(selected_recipe, current_turn_context)
    return TaskSpec(
        task_id=task_id,
        task_spec_ref=f"taskspec:{task_id}",
        recipe_id=str(getattr(selected_recipe, "recipe_id", "") or ""),
        session_id=session_id,
        user_goal=user_goal,
        inputs={
            **explicit_inputs,
            **({"explicit_workspace_path": default_artifact_path} if default_artifact_path else {}),
            **({"coordination_request_brief": coordination_request_brief} if coordination_request_brief else {}),
            **({"bundle_spec": bundle_spec.to_dict()} if bundle_spec is not None else {}),
        },
        bindings={
            "resolved_bindings": resolved_bindings,
        },
        constraints={
            "intent": str(dict(current_turn_context.get("agent_turn_action_request") or {}).get("action_type") or current_turn_context.get("intent") or ""),
            "execution_mode": str(current_turn_context.get("execution_mode") or "single"),
            "confidence": float(current_turn_context.get("confidence") or query_understanding.get("confidence") or 0.0),
            "runtime_limits": runtime_limits,
            "capability_needs": sorted(capability_needs(query_understanding)),
            **({"coordination_request_ref": coordination_request_brief["brief_id"]} if coordination_request_brief else {}),
        },
        current_turn_context_ref=str(current_turn_context.get("authority") or ""),
        task_intent_ref=str(task_intent_contract.task_intent_id or ""),
        bundle_spec_ref=bundle_spec.bundle_id if bundle_spec is not None else "",
        bundle_item_ref=_single_bundle_item_ref(bundle_spec),
        requested_outputs=requested_outputs,
        step_input_bindings=step_input_bindings,
        selected_skill_ids=tuple(selected_skill_ids),
        operation_requirement_ref=operation_requirement_ref,
        safety_envelope=dict(dict(operation_requirement.get("metadata") or {}).get("safety_envelope") or {}),
    )


def _default_task_artifact_path(selected_recipe, current_turn_context: dict[str, Any]) -> str:
    recipe_metadata = dict(getattr(selected_recipe, "metadata", {}) or {})
    default_artifact_name = str(recipe_metadata.get("default_artifact_name") or "").strip()
    if not default_artifact_name:
        return ""
    artifact_root = str(
        current_turn_context.get("artifact_root")
        or current_turn_context.get("workspace_root")
        or dict(current_turn_context.get("explicit_inputs") or {}).get("artifact_root")
        or dict(current_turn_context.get("explicit_inputs") or {}).get("workspace_root")
        or recipe_metadata.get("default_write_root")
        or (
            list(recipe_metadata.get("default_write_roots") or [""])[0]
            if isinstance(recipe_metadata.get("default_write_roots"), list)
            else ""
        )
        or "docs/系统规划/任务系统实测记录/artifacts"
    ).strip().rstrip("/\\")
    if not artifact_root:
        return ""
    task_mode = str(getattr(selected_recipe, "task_mode", "") or "").strip()
    if task_mode:
        return f"{artifact_root}/{task_mode}/{default_artifact_name}"
    return f"{artifact_root}/{default_artifact_name}"


def _build_coordination_request_brief(
    *,
    selected_recipe,
    user_goal: str,
    current_turn_context: dict[str, Any],
    query_understanding: dict[str, Any],
) -> dict[str, Any]:
    recipe_metadata = dict(getattr(selected_recipe, "metadata", {}) or {})
    task_graph_id = str(recipe_metadata.get("task_graph_id") or recipe_metadata.get("graph_id") or "").strip()
    graph_ref = str(task_graph_id or "").strip()
    if not graph_ref:
        return {}
    explicit_inputs = dict(current_turn_context.get("explicit_inputs") or {})
    context_ref_keys = (
        "selected_task_id",
        "graph_id",
        "task_graph_id",
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
        "brief_id": f"coordbrief:{current_turn_context.get('turn_id') or getattr(selected_recipe, 'recipe_id', 'runtime.recipe')}",
        "task_graph_id": graph_ref,
        "graph_id": graph_ref,
        "recipe_id": str(getattr(selected_recipe, "recipe_id", "") or ""),
        "natural_request": str(user_goal or "").strip(),
        "carrying_policy": "preserve_user_request_as_runtime_brief",
        "planning_policy": "coordinator_agent_interprets_request_inside_stable_workflow",
        "explicit_inputs": explicit_inputs,
        "context_refs": context_refs,
        "binding_refs": binding_refs,
        "understanding_refs": {
            "authority": str(query_understanding.get("authority") or ""),
            "agent_turn_action_request_ref": str(dict(current_turn_context.get("agent_turn_action_request") or {}).get("request_id") or ""),
        },
    }


def _resolve_task_runtime_limits(
    *,
    selected_recipe,
    registered_task_policy: dict[str, Any],
    task_structure: dict[str, Any],
    current_turn_context: dict[str, Any],
) -> dict[str, Any]:
    recipe_metadata = dict(getattr(selected_recipe, "metadata", {}) or {})
    recipe_limits = dict(recipe_metadata.get("runtime_limits") or {})
    policy_limits = dict(registered_task_policy.get("runtime_limits") or {})
    structure_limits = dict(task_structure.get("runtime_limits") or {})
    explicit_limits = dict(current_turn_context.get("runtime_limits") or {})
    merged = {**recipe_limits, **policy_limits, **structure_limits, **explicit_limits}
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
            flow_contract_binding = flow_registry.get_flow_contract_binding(specific_task_id)
            flow = flow_registry.get_flow(str(flow_contract_binding.flow_contract_id if flow_contract_binding is not None else record.default_flow_contract_id or "").strip())
            return {
                "task_type": "specific_task",
                "task_id": record.task_id,
                "task_title": record.task_title,
                "task_mode": _record_task_mode(record, flow),
                "workflow_id": str(record.default_workflow_id or getattr(flow, "default_workflow_id", "") or "").strip(),
                "input_contract_id": record.input_contract_id,
                "output_contract_id": record.output_contract_id,
                "flow_id": str(getattr(flow_contract_binding, "flow_contract_id", "") or record.default_flow_contract_id or "").strip(),
                "safety_policy": dict(dict(record.task_policy or {}).get("safety_policy") or {}),
                "task_policy": dict(record.task_policy or {}),
                "runtime_recipe_id": str(
                    (record.metadata or {}).get("runtime_recipe_id")
                    or getattr(flow, "metadata", {}).get("runtime_recipe_id")
                    or ""
                ),
                "metadata": dict(record.metadata or {}),
            }
        return None
    explicit_general_profile_id = str(
        current_turn_context.get("entry_policy_id")
        or current_turn_context.get("general_profile_id")
        or ""
    ).strip()
    if explicit_general_profile_id:
        default_general_profile = flow_registry.get_general_task_profile(explicit_general_profile_id)
    else:
        default_general_profile = None
    if default_general_profile is None:
        return None
    return {
        "task_type": "conversation_entry_policy",
        "task_id": default_general_profile.profile_id,
        "task_title": default_general_profile.title,
        "task_mode": "main_conversation_entry",
        "workflow_id": default_general_profile.default_workflow_id,
        "input_contract_id": default_general_profile.input_contract_id,
        "output_contract_id": default_general_profile.output_contract_id,
        "conversation_entry_policy": default_general_profile.conversation_entry_policy,
        "metadata": dict(default_general_profile.metadata or {}),
    }


def _resolve_task_mode(
    *,
    registered_task: dict[str, Any] | None,
    selected_recipe,
    definitions: list[Any],
) -> str:
    registered_mode = str((registered_task or {}).get("task_mode") or "").strip()
    if registered_mode:
        return registered_mode
    return str(selected_recipe.task_mode or "") or "+".join(
        definition.task_mode for definition in definitions
    )


def _align_runtime_definitions(
    *,
    definitions: list[Any],
    registered_task: dict[str, Any] | None,
    selected_recipe,
) -> list[Any]:
    if not registered_task or str(registered_task.get("task_type") or "") != "specific_task":
        return definitions

    recipe_id = str(getattr(selected_recipe, "recipe_id", "") or "")
    task_mode = str((registered_task or {}).get("task_mode") or getattr(selected_recipe, "task_mode", "") or "")
    definition_catalog = default_task_definitions()
    if recipe_id in {"runtime.recipe.workspace_patch", "runtime.recipe.light_web_game", "runtime.recipe.arcade_game_bundle"} or task_mode in {
        "workspace_patch",
        "light_web_game",
        "arcade_game_bundle",
    }:
        return [
            definition_catalog["task.task_execution"],
            definition_catalog["task.inspection_and_correction"],
        ]
    return definitions


def _align_task_binding_with_template(
    binding,
    *,
    selected_recipe,
):
    template_operations = {
        str(item).strip()
        for item in [
            *list(getattr(selected_recipe, "required_operations", ()) or ()),
            *list(getattr(selected_recipe, "optional_operations", ()) or ()),
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
            "required_operations": tuple(binding.required_operations or ()),
            "denied_operations": allowed_denied,
        }
    )


def _resolve_operation_approval_policy(
    *,
    merged_binding,
    selected_recipe,
    registered_task: dict[str, Any] | None,
) -> str:
    safety_policy = dict(getattr(selected_recipe, "safety_policy", {}) or {})
    write_mode = str(safety_policy.get("write_mode") or "").strip()
    if (
        registered_task
        and str(registered_task.get("task_type") or "") == "specific_task"
        and (
            write_mode in {"bounded_create", "scoped_patch"}
        )
    ):
        return "task_bounded_write"
    return str(merged_binding.approval_policy or "default")


def _build_task_safety_envelope(
    *,
    selected_recipe,
    registered_task: dict[str, Any] | None,
    current_turn_context: dict[str, Any],
) -> dict[str, Any]:
    recipe_policy = dict(getattr(selected_recipe, "safety_policy", {}) or {})
    registered_policy = dict((registered_task or {}).get("safety_policy") or {})
    effective_policy = {**recipe_policy, **registered_policy}
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
        "recipe_id": str(getattr(selected_recipe, "recipe_id", "") or ""),
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
                recipe_id=str(item.get("recipe_id") or ""),
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
    selected_recipe,
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
    for blueprint in list(getattr(selected_recipe, "step_blueprints", ()) or ()):
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
        if bundle_spec is not None and str(getattr(selected_recipe, "execution_kind", "") or "") != "bundle":
            binding_policy = "bundle_item_private_context"
        output_writebacks = _step_output_writebacks(
            recipe_id=str(getattr(selected_recipe, "recipe_id", "") or ""),
            source_kind=str(
                getattr(selected_recipe, "source_kind", "")
                or dict(getattr(selected_recipe, "metadata", {}) or {}).get("source_kind")
                or ""
            ),
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
    recipe_id: str,
    source_kind: str,
    blueprint: TaskStepBlueprint,
    bundle_spec: BundleSpec | None,
) -> dict[str, str]:
    step_kind = str(blueprint.step_kind or "")
    if source_kind == "mixed_sources":
        if step_kind == "understand":
            return {"bundle_plan": "runtime.bundle_plan"}
        if step_kind == "finalize":
            return {"final_answer": "task_result.final_answer", "bundle_result_refs": "state.bundle_result_refs"}
    unit = get_local_mcp_unit_for_source_kind(source_kind)
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



