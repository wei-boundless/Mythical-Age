from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capability_system.search_policy import normalize_search_policy
from task_system.planning.execution_recipe_models import ExecutionRecipe, TaskValidationRule
from task_system.tasks.run_models import TaskRunLedger, build_task_run_ledger
from task_system.tasks.spec_models import TaskSpec
from task_system.tasks.step_models import StepInputBinding, TaskStepBlueprint

from runtime.agent_assembly import DirectWorkOrder, build_agent_invocation, build_model_context_payload
from harness.execution.node_protocol.node_execution_request import build_node_execution_idempotency_key
from harness.loop.control import HarnessLoopLimits
from .execution_policy import execution_permit_diagnostics


@dataclass(frozen=True, slots=True)
class AgentRunContext:
    """Immutable system facts prepared before the agent turn loop runs."""

    request_facts: dict[str, Any] = field(default_factory=dict)
    boundary_policy: dict[str, Any] = field(default_factory=dict)
    context_candidates: dict[str, Any] = field(default_factory=dict)
    model_turn_decision: dict[str, Any] = field(default_factory=dict)
    action_permit: dict[str, Any] = field(default_factory=dict)
    runtime_start_packet: dict[str, Any] = field(default_factory=dict)
    agent_invocation: dict[str, Any] = field(default_factory=dict)
    execution_permit: dict[str, Any] = field(default_factory=dict)
    task_operation: dict[str, Any] = field(default_factory=dict)
    resource_policy: dict[str, Any] = field(default_factory=dict)
    tool_capability_table: dict[str, Any] = field(default_factory=dict)
    sandbox_policy: dict[str, Any] = field(default_factory=dict)
    file_management_policy: dict[str, Any] = field(default_factory=dict)
    agent_runtime_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_facts": dict(self.request_facts),
            "boundary_policy": dict(self.boundary_policy),
            "context_candidates": dict(self.context_candidates),
            "model_turn_decision": dict(self.model_turn_decision),
            "action_permit": dict(self.action_permit),
            "runtime_start_packet": dict(self.runtime_start_packet),
            "agent_invocation": dict(self.agent_invocation),
            "execution_permit": dict(self.execution_permit),
            "task_operation": dict(self.task_operation),
            "resource_policy": dict(self.resource_policy),
            "tool_capability_table": dict(self.tool_capability_table),
            "sandbox_policy": dict(self.sandbox_policy),
            "file_management_policy": dict(self.file_management_policy),
            "agent_runtime_config": dict(self.agent_runtime_config),
            "authority": "harness.runtime.agent_context",
        }


def build_initial_task_run_ledger(
    *,
    task_run_id: str,
    task_contract_ref: str,
    task_spec_payload: dict[str, Any],
    selected_recipe_payload: dict[str, Any],
) -> TaskRunLedger | None:
    task_spec = task_spec_from_payload(task_spec_payload)
    selected_recipe = recipe_from_payload(selected_recipe_payload)
    if task_spec is None or selected_recipe is None:
        return None
    return build_task_run_ledger(
        task_run_id=task_run_id,
        task_contract_ref=task_contract_ref,
        task_spec=task_spec,
        selected_recipe=selected_recipe,
        status="running",
    )


def is_retrieval_task_mode(task_mode: str) -> bool:
    normalized = str(task_mode or "").strip().lower()
    return "retrieval" in normalized or "knowledge" in normalized


def task_spec_from_payload(payload: dict[str, Any]) -> TaskSpec | None:
    if not payload:
        return None
    try:
        return TaskSpec(
            task_id=str(payload.get("task_id") or ""),
            task_spec_ref=str(payload.get("task_spec_ref") or ""),
            recipe_id=str(payload.get("recipe_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            user_goal=str(payload.get("user_goal") or ""),
            inputs=dict(payload.get("inputs") or {}),
            bindings=dict(payload.get("bindings") or {}),
            constraints=dict(payload.get("constraints") or {}),
            current_turn_context_ref=str(payload.get("current_turn_context_ref") or ""),
            task_intent_ref=str(payload.get("task_intent_ref") or ""),
            bundle_spec_ref=str(payload.get("bundle_spec_ref") or ""),
            bundle_item_ref=str(payload.get("bundle_item_ref") or ""),
            requested_outputs=tuple(str(item) for item in list(payload.get("requested_outputs") or [])),
            step_input_bindings=tuple(
                step_input_binding_from_payload(item)
                for item in list(payload.get("step_input_bindings") or [])
            ),
            selected_skill_ids=tuple(str(item) for item in list(payload.get("selected_skill_ids") or [])),
            operation_requirement_ref=str(payload.get("operation_requirement_ref") or ""),
            safety_envelope=dict(payload.get("safety_envelope") or {}),
            status=str(payload.get("status") or "selected"),
        )
    except ValueError:
        return None


def recipe_from_payload(payload: dict[str, Any]) -> ExecutionRecipe | None:
    if not payload:
        return None
    try:
        return ExecutionRecipe(
            recipe_id=str(payload.get("recipe_id") or ""),
            title=str(payload.get("title") or ""),
            description=str(payload.get("description") or ""),
            execution_kind=str(payload.get("execution_kind") or ""),
            task_mode=str(payload.get("task_mode") or ""),
            source_kind=str(payload.get("source_kind") or ""),
            input_schema=dict(payload.get("input_schema") or {}),
            output_schema=dict(payload.get("output_schema") or {}),
            default_agent_id=str(payload.get("default_agent_id") or "agent:0"),
            allowed_agent_ids=tuple(str(item) for item in list(payload.get("allowed_agent_ids") or ["agent:0"])),
            required_capability_tags=tuple(str(item) for item in list(payload.get("required_capability_tags") or [])),
            required_operations=tuple(str(item) for item in list(payload.get("required_operations") or [])),
            optional_operations=tuple(str(item) for item in list(payload.get("optional_operations") or [])),
            step_blueprints=tuple(task_step_blueprint_from_payload(item) for item in list(payload.get("step_blueprints") or [])),
            validation_rules=tuple(task_validation_rule_from_payload(item) for item in list(payload.get("validation_rules") or [])),
            safety_policy=dict(payload.get("safety_policy") or {}),
            artifact_policy=dict(payload.get("artifact_policy") or {}),
            finalization_policy=dict(payload.get("finalization_policy") or {}),
            ui_manifest=dict(payload.get("ui_manifest") or {}),
            enabled=bool(payload.get("enabled", True)),
            metadata=dict(payload.get("metadata") or {}),
        )
    except ValueError:
        return None


def task_step_blueprint_from_payload(payload: Any) -> TaskStepBlueprint:
    data = dict(payload or {})
    return TaskStepBlueprint(
        step_id=str(data.get("step_id") or ""),
        title=str(data.get("title") or ""),
        step_kind=str(data.get("step_kind") or ""),
        executor_type=str(data.get("executor_type") or ""),
        required_operations=tuple(str(item) for item in list(data.get("required_operations") or [])),
        optional_operations=tuple(str(item) for item in list(data.get("optional_operations") or [])),
        input_refs=tuple(str(item) for item in list(data.get("input_refs") or [])),
        output_contract_id=str(data.get("output_contract_id") or ""),
        stop_policy=str(data.get("stop_policy") or "on_success"),
        retry_policy=dict(data.get("retry_policy") or {}),
    )


def step_input_binding_from_payload(payload: Any) -> StepInputBinding:
    data = dict(payload or {})
    return StepInputBinding(
        step_id=str(data.get("step_id") or ""),
        input_refs=tuple(str(item) for item in list(data.get("input_refs") or [])),
        inherited_parent_refs=tuple(str(item) for item in list(data.get("inherited_parent_refs") or [])),
        private_state_refs=tuple(str(item) for item in list(data.get("private_state_refs") or [])),
        output_writebacks=dict(data.get("output_writebacks") or {}),
        binding_policy=str(data.get("binding_policy") or "inherit_parent_context"),
    )


def bundle_items_from_runtime_contract(
    *,
    task_spec_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    bundle_spec = dict(dict(task_spec_payload.get("inputs") or {}).get("bundle_spec") or {})
    bundle_spec_items = [
        dict(item)
        for item in list(bundle_spec.get("items") or [])
        if isinstance(item, dict)
    ]
    return [
        {
            **item,
            "bundle_id": str(bundle_spec.get("bundle_id") or item.get("bundle_id") or ""),
        }
        for item in bundle_spec_items
    ]


def task_validation_rule_from_payload(payload: Any) -> TaskValidationRule:
    data = dict(payload or {})
    return TaskValidationRule(
        rule_id=str(data.get("rule_id") or ""),
        title=str(data.get("title") or ""),
        validation_kind=str(data.get("validation_kind") or ""),
        severity=str(data.get("severity") or "warning"),
        parameters=dict(data.get("parameters") or {}),
        message=str(data.get("message") or ""),
    )


def runtime_limits_from_task_operation(
    task_operation: dict[str, Any],
    *,
    fallback: HarnessLoopLimits,
) -> HarnessLoopLimits:
    task_spec = dict(task_operation.get("task_spec") or {})
    task_assembly = dict(task_operation.get("task_execution_assembly") or {})
    execution_policy = dict(task_operation.get("task_execution_policy") or {})
    metadata = dict(task_assembly.get("metadata") or {})
    constraints = dict(task_spec.get("constraints") or {})
    policy_metadata = dict(execution_policy.get("metadata") or {})
    limits = {
        **dict(metadata.get("runtime_limits") or {}),
        **dict(policy_metadata.get("runtime_limits") or {}),
        **dict(constraints.get("runtime_limits") or {}),
    }
    if not limits:
        return fallback
    return HarnessLoopLimits.from_policy(limits, fallback=fallback)


def resolve_runtime_search_sources(
    *,
    search_policy: list[str] | tuple[str, ...] | set[str] | None,
    task_selection: dict[str, Any] | None,
) -> set[str]:
    if search_policy is not None:
        return normalize_search_policy(search_policy)
    selection = dict(task_selection or {})
    if selection_is_coordination_task(selection):
        explicit_policy = extract_task_search_policy(selection)
        if explicit_policy is not None:
            return normalize_search_policy(explicit_policy)
        return set()
    return normalize_search_policy(None)


def selection_is_coordination_task(selection: dict[str, Any]) -> bool:
    if str(selection.get("continuation_stage_id") or "").strip():
        return True
    if str(selection.get("coordination_run_id") or "").strip():
        return True
    runtime_assembly = dict(selection.get("runtime_assembly") or {})
    if str(runtime_assembly.get("runtime_lane") or "").strip() == "coordination_task":
        return True
    return str(selection.get("runtime_lane") or "").strip() == "coordination_task"


def intent_continuation_trace_events(current_turn_context: dict[str, Any]) -> list[dict[str, Any]]:
    context = dict(current_turn_context or {})
    continuation_candidates = [
        dict(item)
        for item in list(context.get("continuation_candidates") or [])
        if isinstance(item, dict)
    ]
    continuation_decision = dict(context.get("continuation_decision") or {})
    events: list[dict[str, Any]] = []
    if continuation_candidates:
        events.append(
            {
                "event_type": "continuation_candidates_built",
                "payload": {
                    "continuation_candidates": continuation_candidates,
                    "candidate_count": len(continuation_candidates),
                    "compatible_candidate_count": sum(1 for item in continuation_candidates if item.get("compatible") is True),
                },
            }
        )
    if continuation_decision:
        events.append(
            {
                "event_type": "continuation_decision_made",
                "payload": {
                    "continuation_decision": continuation_decision,
                    "selected_candidate_id": str(continuation_decision.get("selected_candidate_id") or ""),
                    "decision_kind": str(continuation_decision.get("decision_kind") or ""),
                },
            }
        )
    return events


def stage_execution_request_diagnostics(selection: dict[str, Any]) -> dict[str, Any]:
    request = dict(selection.get("stage_execution_request") or {})
    request_ref = str(selection.get("stage_execution_request_ref") or "").strip()
    if not request and request_ref:
        return {
            "stage_request_ref": request_ref,
            "continuation_stage_id": str(selection.get("continuation_stage_id") or ""),
        }
    if not request:
        return {}
    stage_id = str(request.get("stage_id") or request.get("node_id") or "").strip()
    idempotency_key = str(request.get("idempotency_key") or "").strip()
    if not idempotency_key:
        idempotency_key = build_node_execution_idempotency_key(
            coordination_run_id=str(request.get("coordination_run_id") or ""),
            node_id=str(request.get("node_id") or stage_id),
            explicit_inputs=dict(request.get("explicit_inputs") or {}),
            dispatch_context=dict(request.get("dispatch_context") or {}),
        )
    return {
        "stage_execution_request": request,
        "coordination_run_id": str(request.get("coordination_run_id") or ""),
        "coordination_stage_id": stage_id,
        "stage_id": stage_id,
        "node_id": str(request.get("node_id") or stage_id),
        "stage_request_id": str(request.get("request_id") or ""),
        "stage_idempotency_key": idempotency_key,
        "stage_dispatch_event_id": str(dict(request.get("dispatch_context") or {}).get("dispatch_event_id") or ""),
        "continuation_stage_id": str(selection.get("continuation_stage_id") or stage_id),
    }


def extract_task_search_policy(selection: dict[str, Any]) -> list[str] | tuple[str, ...] | set[str] | None:
    for key in ("search_policy", "allowed_search_sources"):
        value = selection.get(key)
        if isinstance(value, (list, tuple, set)):
            return value
    operation_policy = dict(selection.get("operation_policy") or {})
    for key in ("search_policy", "allowed_search_sources"):
        value = operation_policy.get(key)
        if isinstance(value, (list, tuple, set)):
            return value
    runtime_assembly = dict(selection.get("runtime_assembly") or {})
    permission_policy = dict(runtime_assembly.get("permission_policy") or runtime_assembly.get("resource_policy") or {})
    for key in ("search_policy", "allowed_search_sources"):
        value = permission_policy.get(key)
        if isinstance(value, (list, tuple, set)):
            return value
    return None


def agent_profile_id_for_runtime_spec(registry: Any, runtime_spec_payload: dict[str, Any]) -> str:
    agent_id = str(runtime_spec_payload.get("agent_id") or "").strip()
    if not agent_id:
        return ""
    getter = getattr(registry, "get_profile", None)
    if not callable(getter):
        return ""
    profile = getter(agent_id)
    return str(getattr(profile, "agent_profile_id", "") or "").strip()


def diagnostic_int(payload: dict[str, Any], key: str) -> int:
    diagnostics = dict(payload.get("diagnostics") or {})
    try:
        return int(diagnostics.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def build_direct_agent_invocation_payload(
    *,
    base_dir: Path,
    task_id: str,
    user_message: str,
    task_selection: dict[str, Any] | None = None,
    agent_runtime_profile: Any | None = None,
) -> dict[str, Any]:
    selection = dict(task_selection or {})
    work_order = DirectWorkOrder(
        work_order_id="",
        task_ref=str(
            selection.get("selected_task_id")
            or selection.get("task_id")
            or selection.get("specific_task_id")
            or task_id
            or "task.runtime.direct"
        ),
        coordination_run_id=str(selection.get("coordination_run_id") or ""),
        thread_id=str(selection.get("thread_id") or selection.get("coordination_run_id") or ""),
        root_task_run_id=str(selection.get("root_task_run_id") or ""),
        agent_id=str(selection.get("agent_id") or getattr(agent_runtime_profile, "agent_id", "") or ""),
        agent_profile_id=str(selection.get("agent_profile_id") or getattr(agent_runtime_profile, "agent_profile_id", "") or ""),
        runtime_lane=str(selection.get("runtime_lane") or ""),
        message=user_message,
        explicit_inputs=dict(selection.get("explicit_inputs") or {}),
        input_package=dict(selection.get("input_package") or selection.get("standard_input_package") or {}),
        current_turn_context=build_model_context_payload(current_turn_context=selection),
        artifact_policy=dict(selection.get("artifact_policy") or {}),
        stream_policy=dict(selection.get("stream_policy") or {}),
        artifact_root=str(selection.get("artifact_root") or ""),
        runtime_assembly=direct_runtime_assembly_from_selection(selection),
    )
    return build_agent_invocation(
        work_order,
        base_dir=base_dir,
        agent_runtime_profile=agent_runtime_profile,
    ).to_dict()


def direct_runtime_assembly_from_selection(selection: dict[str, Any]) -> dict[str, Any]:
    runtime_assembly = dict(selection.get("runtime_assembly") or {})
    operation_policy = dict(selection.get("operation_policy") or {})
    if operation_policy:
        runtime_assembly["operation_policy"] = operation_policy
    return runtime_assembly


def model_requirement_for_model_resolution(
    *,
    task_execution_assembly: dict[str, Any] | None,
    current_turn_context: dict[str, Any] | None,
    agent_assembly_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    task_assembly = dict(task_execution_assembly or {})
    current_turn = dict(current_turn_context or {})
    assembly = dict(agent_assembly_contract or {})
    candidates = [
        dict(dict(task_assembly.get("contract_bindings") or {}).get("runtime") or {}).get("model_requirement"),
        dict(assembly.get("metadata") or {}).get("model_requirement"),
        dict(dict(assembly.get("prompt_assembly") or {}).get("metadata") or {}).get("model_requirement"),
        dict(dict(dict(assembly.get("runtime_assembly") or {}).get("metadata") or {}).get("contract_bindings") or {}).get("runtime", {}).get("model_requirement")
        if isinstance(dict(dict(assembly.get("runtime_assembly") or {}).get("metadata") or {}).get("contract_bindings"), dict)
        else {},
        dict(dict(dict(current_turn.get("runtime_assembly") or {}).get("metadata") or {}).get("contract_bindings") or {}).get("runtime", {}).get("model_requirement")
        if isinstance(dict(dict(current_turn.get("runtime_assembly") or {}).get("metadata") or {}).get("contract_bindings"), dict)
        else {},
        dict(dict(current_turn.get("contract_bindings") or {}).get("runtime") or {}).get("model_requirement"),
        dict(current_turn.get("model_requirement") or {}),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
    return {}


def merge_invocation_identity_into_task_selection(
    *,
    task_selection: dict[str, Any] | None,
    invocation_payload: dict[str, Any] | None,
    assembly_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    selection = dict(task_selection or {})
    invocation = dict(invocation_payload or {})
    invocation_selection = dict(invocation.get("task_selection") or {})
    assembly = dict(assembly_contract or {})
    work_order = dict(invocation.get("work_order") or assembly.get("work_order") or {})

    task_ref = str(
        invocation.get("task_ref")
        or assembly.get("task_ref")
        or work_order.get("task_ref")
        or invocation_selection.get("selected_task_id")
        or invocation_selection.get("task_id")
        or ""
    ).strip()
    if task_ref:
        selection["selected_task_id"] = task_ref
        selection["task_id"] = task_ref
        selection["specific_task_id"] = task_ref

    for key in ("stage_execution_request_ref", "continuation_stage_id", "coordination_run_id"):
        value = invocation_selection.get(key)
        if has_runtime_value(value):
            selection[key] = value
    for key in ("work_order_id", "assembly_id", "executor_type", "agent_id", "agent_profile_id", "runtime_lane"):
        value = assembly.get(key) or invocation_selection.get(key)
        if has_runtime_value(value):
            selection[key] = value
    if has_runtime_value(invocation.get("invocation_id")):
        selection["agent_invocation_id"] = str(invocation.get("invocation_id") or "")
    selection.pop("agent_invocation", None)
    return selection


def has_runtime_value(value: Any) -> bool:
    return value not in ("", None, [], {})


def assert_agent_runtime_spec_matches_invocation(
    agent_runtime_spec: dict[str, Any],
    assembly_contract: dict[str, Any],
    *,
    strict_runtime_lane: bool,
) -> None:
    spec = dict(agent_runtime_spec or {})
    assembly = dict(assembly_contract or {})
    expected_agent_id = str(assembly.get("agent_id") or "").strip()
    actual_agent_id = str(spec.get("agent_id") or "").strip()
    if expected_agent_id and actual_agent_id and expected_agent_id != actual_agent_id:
        raise ValueError(
            "AgentRuntimeSpec agent_id does not match AgentInvocation: "
            f"expected {expected_agent_id}, got {actual_agent_id}"
        )
    expected_runtime_lane = str(assembly.get("runtime_lane") or "").strip()
    actual_runtime_lane = str(spec.get("runtime_lane") or "").strip()
    if strict_runtime_lane and expected_runtime_lane and actual_runtime_lane and expected_runtime_lane != actual_runtime_lane:
        raise ValueError(
            "AgentRuntimeSpec runtime_lane does not match AgentInvocation: "
            f"expected {expected_runtime_lane}, got {actual_runtime_lane}"
        )


def assembly_contract_diagnostics(assembly_contract: dict[str, Any] | None) -> dict[str, Any]:
    assembly = dict(assembly_contract or {})
    if not assembly:
        return {}
    return {
        "assembly_id": str(assembly.get("assembly_id") or ""),
        "work_order_id": str(assembly.get("work_order_id") or ""),
        "work_kind": str(assembly.get("work_kind") or ""),
        "agent_id": str(assembly.get("agent_id") or ""),
        "agent_profile_id": str(assembly.get("agent_profile_id") or ""),
        "runtime_lane": str(assembly.get("runtime_lane") or ""),
        "executor_type": str(assembly.get("executor_type") or ""),
    }


def agent_invocation_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, dict):
        return dict(value)
    return {}


def agent_invocation_diagnostics(invocation: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(invocation or {})
    if not payload:
        return {}
    return {
        "invocation_id": str(payload.get("invocation_id") or ""),
        "work_order_id": str(payload.get("work_order_id") or ""),
        "assembly_id": str(payload.get("assembly_id") or ""),
        "task_ref": str(payload.get("task_ref") or ""),
        "executor_type": str(payload.get("executor_type") or ""),
        "agent_id": str(payload.get("agent_id") or ""),
        "agent_profile_id": str(payload.get("agent_profile_id") or ""),
        "runtime_lane": str(payload.get("runtime_lane") or ""),
    }


def persist_agent_invocation_boundary_objects(
    runtime_objects: Any,
    *,
    task_run_id: str,
    agent_invocation: dict[str, Any] | None,
    assembly_contract: dict[str, Any] | None,
    execution_permit: dict[str, Any] | None,
) -> dict[str, str]:
    invocation = dict(agent_invocation or {})
    assembly = dict(assembly_contract or {})
    permit = dict(execution_permit or {})
    refs: dict[str, str] = {}
    invocation_id = str(invocation.get("invocation_id") or "").strip()
    assembly_id = str(assembly.get("assembly_id") or "").strip()
    permit_id = str(permit.get("permit_id") or "").strip()
    if invocation_id:
        refs["agent_invocation_object_ref"] = runtime_objects.put_json_once(
            "agent_invocation",
            invocation_id,
            {
                "task_run_id": task_run_id,
                "agent_invocation": invocation,
                "agent_invocation_summary": agent_invocation_diagnostics(invocation),
            },
        )
    if assembly_id:
        refs["agent_assembly_object_ref"] = runtime_objects.put_json_once(
            "agent_assembly_contract",
            assembly_id,
            {
                "task_run_id": task_run_id,
                "agent_assembly_contract": assembly,
                "agent_assembly_summary": assembly_contract_diagnostics(assembly),
            },
        )
    if permit_id:
        refs["execution_permit_object_ref"] = runtime_objects.put_json_once(
            "execution_permit",
            permit_id,
            {
                "task_run_id": task_run_id,
                "execution_permit": permit,
                "execution_permit_summary": execution_permit_diagnostics(permit),
            },
        )
    return refs


def chat_model_selection_runtime_defaults(model_selection: dict[str, Any] | None) -> dict[str, Any]:
    selection = dict(model_selection or {})
    provider = str(selection.get("provider") or "").strip().lower()
    model = str(selection.get("model") or "").strip()
    base_url = str(selection.get("base_url") or "").strip()
    if not provider or not model:
        return {}
    defaults: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "credential_ref": str(selection.get("credential_ref") or f"provider:{provider}:primary").strip(),
    }
    if base_url:
        defaults["base_url"] = base_url
    thinking_mode = str(selection.get("thinking_mode") or "").strip().lower()
    if thinking_mode in {"enabled", "disabled"}:
        defaults["thinking_mode"] = thinking_mode
    reasoning_effort = str(selection.get("reasoning_effort") or "").strip().lower()
    if reasoning_effort in {"high", "max"}:
        defaults["reasoning_effort"] = reasoning_effort
    return defaults


