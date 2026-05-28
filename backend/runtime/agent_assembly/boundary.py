from __future__ import annotations

from typing import Any

from task_system.runtime_semantics.protocol_boundary import is_internal_protocol_input_key


CONTROL_CONTEXT_KEYS = frozenset(
    {
        "stage_execution_request",
        "node_work_order",
        "agent_assembly_contract",
        "execution_permit",
        "runtime_control",
        "graph_module_runtime_handle",
        "human_work_packet",
        "standard_input_package",
        "runtime_assembly",
        "a2a_payload",
    }
)

MODEL_CONTEXT_KEYS = frozenset(
    {
        "turn_id",
        "selected_task_id",
        "task_id",
        "agent_id",
        "agent_profile_id",
        "runtime_limits",
        "agent_group_id",
        "artifact_root",
        "workspace_root",
        "explicit_inputs",
        "coordination_run_id",
        "continuation_stage_id",
        "stage_execution_request_ref",
        "work_order_id",
        "assembly_id",
        "execution_mode",
        "bundle_id",
        "bundle_items",
        "followup_target_refs",
        "resolved_bindings",
        "context_recall_candidates",
        "continuation_candidates",
        "continuation_decision",
        "authority",
        "graph_id",
        "task_graph_id",
        "selected_graph_id",
        "stale_stage_execution_retry",
    }
)

TASK_SEMANTIC_CONTEXT_KEYS = frozenset(
    {
        "interaction_mode",
        "runtime_interaction_mode",
        "mode_policy",
        "runtime_mode_policy",
        "semantic_task_type",
        "agent_turn_action_request",
        "agent_turn_action_diagnostics",
        "task_contract_seed",
        "runtime_admission",
        "task_goal_spec",
        "model_agent_plan_draft",
        "execution_obligation",
        "structural_signals",
    }
)

TASK_SELECTION_KEYS = frozenset(
    {
        "stage_execution_request",
        "turn_id",
        "selected_task_id",
        "task_id",
        "task_assignment_id",
        "specific_task_id",
        "graph_id",
        "agent_id",
        "agent_profile_id",
        "runtime_limits",
        "agent_group_id",
        "artifact_root",
        "workspace_root",
        "explicit_inputs",
        "coordination_run_id",
        "continuation_stage_id",
        "stage_execution_request_ref",
        "work_order_id",
        "assembly_id",
        "executor_type",
        "search_policy",
        "allowed_search_sources",
        "operation_policy",
        "sandbox_policy",
        "stream_policy",
        "runtime_assembly",
        *TASK_SEMANTIC_CONTEXT_KEYS,
    }
)


def has_value(value: Any) -> bool:
    return value not in ("", None, [], {})


def sanitize_explicit_inputs(explicit_inputs: dict[str, Any] | None) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in dict(explicit_inputs or {}).items()
        if str(key).strip() and not is_internal_protocol_input_key(str(key))
    }


def strip_control_context(payload: dict[str, Any] | None) -> dict[str, Any]:
    return {
        key: _sanitize_model_context_value(key, value)
        for key, value in dict(payload or {}).items()
        if key not in CONTROL_CONTEXT_KEYS and has_value(value)
    }


def build_runtime_control_payload(
    *,
    stage_execution_request: dict[str, Any],
    stage_execution_request_ref: str = "",
    node_work_order: dict[str, Any] | None = None,
    agent_assembly_contract: dict[str, Any] | None = None,
    standard_input_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = dict(stage_execution_request or {})
    return {
        "stage_execution_request": request,
        "stage_execution_request_ref": str(stage_execution_request_ref or request.get("request_id") or request.get("idempotency_key") or ""),
        "node_work_order": dict(node_work_order or {}),
        "agent_assembly_contract": dict(agent_assembly_contract or {}),
        "standard_input_package": dict(standard_input_package or {}),
        "authority": "runtime.agent_assembly.runtime_control",
    }


def build_model_context_payload(
    *,
    current_turn_context: dict[str, Any] | None = None,
    stage_execution_request: dict[str, Any] | None = None,
    node_work_order: dict[str, Any] | None = None,
    agent_assembly_contract: dict[str, Any] | None = None,
    stage_execution_request_ref: str = "",
) -> dict[str, Any]:
    request = dict(stage_execution_request or {})
    work_order = dict(node_work_order or {})
    assembly = dict(agent_assembly_contract or {})
    context = {
        key: value
        for key, value in strip_control_context(current_turn_context).items()
        if key in MODEL_CONTEXT_KEYS
    }

    task_ref = str(work_order.get("task_ref") or request.get("task_ref") or context.get("task_id") or "").strip()
    agent_id = str(assembly.get("agent_id") or work_order.get("agent_id") or request.get("agent_id") or context.get("agent_id") or "").strip()
    agent_profile_id = str(
        assembly.get("agent_profile_id")
        or work_order.get("agent_profile_id")
        or request.get("agent_profile_id")
        or context.get("agent_profile_id")
        or ""
    ).strip()
    runtime_assembly = dict(work_order.get("runtime_assembly") or request.get("runtime_assembly") or {})
    work_kind = str(work_order.get("work_kind") or request.get("work_kind") or "").strip()
    stage_id = ""
    if work_kind and work_kind != "direct":
        stage_id = str(work_order.get("stage_id") or request.get("stage_id") or request.get("node_id") or "").strip()
    elif not work_kind and (work_order.get("stage_id") or request.get("stage_id")):
        stage_id = str(work_order.get("stage_id") or request.get("stage_id") or request.get("node_id") or "").strip()
    request_ref = str(stage_execution_request_ref or request.get("request_id") or request.get("idempotency_key") or "").strip()

    overlays: dict[str, Any] = {
        "selected_task_id": task_ref,
        "task_id": task_ref,
        "agent_id": agent_id,
        "agent_profile_id": agent_profile_id,
        "coordination_run_id": str(work_order.get("coordination_run_id") or request.get("coordination_run_id") or ""),
        "continuation_stage_id": stage_id,
        "work_order_id": str(work_order.get("work_order_id") or request.get("request_id") or ""),
        "assembly_id": str(assembly.get("assembly_id") or ""),
        "stage_execution_request_ref": request_ref,
    }
    explicit_inputs = sanitize_explicit_inputs(work_order.get("explicit_inputs") or request.get("explicit_inputs") or {})
    if explicit_inputs:
        overlays["explicit_inputs"] = explicit_inputs
    artifact_root = str(work_order.get("artifact_root") or request.get("artifact_root") or context.get("artifact_root") or "").strip()
    if artifact_root:
        overlays["artifact_root"] = artifact_root

    for key, value in overlays.items():
        if has_value(value):
            context[key] = value
    return context


def build_turn_context_payload(
    *,
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    allowed = MODEL_CONTEXT_KEYS | TASK_SELECTION_KEYS | TASK_SEMANTIC_CONTEXT_KEYS
    return {
        key: value
        for key, value in strip_control_context(current_turn_context).items()
        if key in allowed
    }


def build_task_selection_payload(
    *,
    task_selection: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    agent_assembly_contract: dict[str, Any] | None = None,
    runtime_control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selection = _selection_projection(task_selection)
    context = _selection_projection(current_turn_context)
    selection.update(context)

    control = dict(runtime_control or {})
    request = dict(control.get("stage_execution_request") or {})
    work_order = dict(control.get("node_work_order") or {})
    assembly = dict(agent_assembly_contract or control.get("agent_assembly_contract") or {})

    task_ref = str(work_order.get("task_ref") or assembly.get("task_ref") or request.get("task_ref") or "").strip()
    if task_ref:
        selection["selected_task_id"] = task_ref
        selection["task_id"] = task_ref
    graph_ref = str(selection.get("graph_id") or selection.get("task_graph_id") or selection.get("selected_graph_id") or "").strip()
    if graph_ref:
        selection["graph_id"] = graph_ref
        selection["task_graph_id"] = graph_ref
        selection["selected_graph_id"] = graph_ref
    for key in ("agent_id", "agent_profile_id", "work_order_id", "assembly_id", "executor_type"):
        value = str(assembly.get(key) or work_order.get(key) or request.get(key) or "").strip()
        if value:
            selection[key] = value
    request_ref = str(control.get("stage_execution_request_ref") or request.get("request_id") or request.get("idempotency_key") or "").strip()
    if request_ref:
        selection["stage_execution_request_ref"] = request_ref
    work_kind = str(work_order.get("work_kind") or request.get("work_kind") or "").strip()
    stage_id = ""
    if work_kind and work_kind != "direct":
        stage_id = str(work_order.get("stage_id") or request.get("stage_id") or request.get("node_id") or "").strip()
    elif not work_kind and (work_order.get("stage_id") or request.get("stage_id")):
        stage_id = str(work_order.get("stage_id") or request.get("stage_id") or request.get("node_id") or "").strip()
    if stage_id:
        selection["continuation_stage_id"] = stage_id
    coordination_run_id = str(work_order.get("coordination_run_id") or request.get("coordination_run_id") or "").strip()
    if coordination_run_id:
        selection["coordination_run_id"] = coordination_run_id
    return {key: value for key, value in selection.items() if has_value(value)}


def node_work_order_from_runtime_control(payload: dict[str, Any] | None) -> dict[str, Any]:
    item = dict(payload or {})
    control = dict(item.get("runtime_control") or {})
    return dict(control.get("node_work_order") or item.get("node_work_order") or {})


def stage_execution_request_from_runtime_control(payload: dict[str, Any] | None) -> dict[str, Any]:
    item = dict(payload or {})
    control = dict(item.get("runtime_control") or {})
    return dict(control.get("stage_execution_request") or item.get("stage_execution_request") or {})


def runtime_control_ref_summary(runtime_control: dict[str, Any] | None) -> dict[str, Any]:
    control = dict(runtime_control or {})
    request = dict(control.get("stage_execution_request") or {})
    work_order = dict(control.get("node_work_order") or {})
    assembly = dict(control.get("agent_assembly_contract") or {})
    runtime_assembly = dict(work_order.get("runtime_assembly") or request.get("runtime_assembly") or {})
    graph_handle = dict(runtime_assembly.get("graph_module_runtime_handle") or {})
    return {
        "stage_execution_request_ref": str(control.get("stage_execution_request_ref") or request.get("request_id") or request.get("idempotency_key") or ""),
        "work_order_id": str(work_order.get("work_order_id") or request.get("request_id") or ""),
        "assembly_id": str(assembly.get("assembly_id") or ""),
        "task_ref": str(work_order.get("task_ref") or request.get("task_ref") or assembly.get("task_ref") or ""),
        "stage_id": str(work_order.get("stage_id") or request.get("stage_id") or request.get("node_id") or ""),
        "agent_id": str(assembly.get("agent_id") or work_order.get("agent_id") or request.get("agent_id") or ""),
        "agent_profile_id": str(assembly.get("agent_profile_id") or work_order.get("agent_profile_id") or request.get("agent_profile_id") or ""),
        "executor_type": str(assembly.get("executor_type") or work_order.get("executor_type") or request.get("executor_type") or ""),
        "graph_module_runtime_handle_id": str(graph_handle.get("handle_id") or ""),
    }


def _selection_projection(payload: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        if key in CONTROL_CONTEXT_KEYS or key not in TASK_SELECTION_KEYS or not has_value(value):
            continue
        result[key] = _sanitize_model_context_value(key, value)
    return result


def _sanitize_model_context_value(key: str, value: Any) -> Any:
    if key == "explicit_inputs" and isinstance(value, dict):
        return sanitize_explicit_inputs(value)
    return value


