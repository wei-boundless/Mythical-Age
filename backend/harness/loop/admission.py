from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from permissions import OperationGatePipelineContext, ResourcePolicy
from runtime.shared.safety import build_task_safety_validators

from .model_action_protocol import ModelActionRequest


AdmissionDecisionValue = Literal["allow", "deny", "ask_approval", "invalid", "needs_contract"]


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    admission_id: str
    action_request_ref: str
    decision: AdmissionDecisionValue
    user_visible_reason: str = ""
    system_reason: str = ""
    contract_errors: tuple[str, ...] = ()
    resource_errors: tuple[str, ...] = ()
    permission_delta: dict[str, Any] = field(default_factory=dict)
    approval_request_ref: str = ""
    authority: str = "harness.loop.admission"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.admission":
            raise ValueError("AdmissionDecision authority must be harness.loop.admission")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contract_errors"] = list(self.contract_errors)
        payload["resource_errors"] = list(self.resource_errors)
        payload["permission_delta"] = dict(self.permission_delta or {})
        return payload


def admit_model_action(
    action_request: ModelActionRequest,
    *,
    definitions_by_name: dict[str, Any] | None = None,
    allowed_tool_names: set[str] | None = None,
    runtime_profile: dict[str, Any] | None = None,
    operation_gate: Any | None = None,
    permission_mode: str = "default",
    directive_ref: str = "",
    workspace_root: Any | None = None,
    side_effect_tools_allowed: bool = False,
) -> AdmissionDecision:
    if action_request.action_type == "tool_call":
        tool_name = str(action_request.tool_call.get("tool_name") or action_request.tool_call.get("name") or "").strip()
        tool_args = action_request.tool_call.get("args") or action_request.tool_call.get("tool_args") or {}
        if not isinstance(tool_args, dict):
            return _invalid(action_request, "tool_args_must_be_object")
        definition = dict(definitions_by_name or {}).get(tool_name)
        if not tool_name:
            return _invalid(action_request, "tool_name_missing")
        if allowed_tool_names is not None and tool_name not in allowed_tool_names:
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="deny",
                user_visible_reason="请求的工具没有在本次运行时中开放。",
                system_reason="tool_not_in_runtime_assembly",
                resource_errors=(f"tool_not_in_runtime_assembly:{tool_name}",),
            )
        if definition is None:
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="deny",
                user_visible_reason="请求的工具当前不可用。",
                system_reason="tool_not_available",
                resource_errors=(f"tool_not_available:{tool_name}",),
            )
        if not bool(getattr(definition, "is_read_only", False)) and not side_effect_tools_allowed:
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="needs_contract",
                user_visible_reason="这个动作会改变环境，需要先进入正式任务生命周期。",
                system_reason="side_effect_tool_requires_task_run",
                resource_errors=(f"tool_requires_task_run:{tool_name}",),
            )
        operation_id = str(getattr(definition, "operation_id", "") or tool_name)
        gate_result = _check_operation_gate(
            operation_gate=operation_gate,
            operation_id=operation_id,
            action_request=action_request,
            directive_ref=directive_ref,
            permission_mode=permission_mode,
            tool_name=tool_name,
            tool_args=tool_args,
            workspace_root=workspace_root,
        )
        if gate_result is not None and getattr(gate_result, "requires_approval", False):
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="ask_approval",
                user_visible_reason="这个观察动作需要权限批准，当前通用 turn 不会自动执行。",
                system_reason=str(getattr(gate_result, "reason", "") or "operation_requires_approval"),
                permission_delta={"gate": gate_result.to_dict()},
                approval_request_ref=f"approval:{action_request.request_id}",
            )
        if gate_result is not None and not getattr(gate_result, "allowed", False):
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="deny",
                user_visible_reason="这个观察动作未通过运行时权限检查。",
                system_reason=str(getattr(gate_result, "reason", "") or "operation_gate_denied"),
                resource_errors=(f"operation_gate_denied:{operation_id}",),
                permission_delta={"gate": gate_result.to_dict()},
            )
        return AdmissionDecision(
            admission_id=f"admission:{action_request.request_id}",
            action_request_ref=action_request.request_id,
            decision="allow",
            permission_delta={
                "tool_name": tool_name,
                "operation_id": operation_id,
                "read_only": True,
                "gate": gate_result.to_dict() if hasattr(gate_result, "to_dict") else None,
            },
            )
    if action_request.action_type == "request_task_run":
        task_lifecycle_policy = dict(dict(runtime_profile or {}).get("task_lifecycle_policy") or {})
        if task_lifecycle_policy.get("request_task_run") is False:
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="deny",
                user_visible_reason="当前运行模式不允许开启正式任务生命周期。",
                system_reason="task_lifecycle_disabled_by_runtime_profile",
                contract_errors=("task_lifecycle_disabled_by_runtime_profile",),
            )
    if action_request.action_type == "request_task_run" and not action_request.task_contract_seed:
        return AdmissionDecision(
            admission_id=f"admission:{action_request.request_id}",
            action_request_ref=action_request.request_id,
            decision="needs_contract",
            user_visible_reason="需要先补充正式任务合同，才能开启长任务。",
            system_reason="task_contract_seed_missing",
            contract_errors=("task_contract_seed_missing",),
        )
    return AdmissionDecision(
        admission_id=f"admission:{action_request.request_id}",
        action_request_ref=action_request.request_id,
        decision="allow",
    )


def _invalid(action_request: ModelActionRequest, reason: str) -> AdmissionDecision:
    return AdmissionDecision(
        admission_id=f"admission:{action_request.request_id}",
        action_request_ref=action_request.request_id,
        decision="invalid",
        user_visible_reason="本轮动作请求格式不完整，运行时已停止执行。",
        system_reason=reason,
        resource_errors=(reason,),
    )


def _check_operation_gate(
    *,
    operation_gate: Any | None,
    operation_id: str,
    action_request: ModelActionRequest,
    directive_ref: str,
    permission_mode: str,
    tool_name: str,
    tool_args: dict[str, Any],
    workspace_root: Any | None,
) -> Any | None:
    if operation_gate is None or not hasattr(operation_gate, "check"):
        return None
    resource_policy = ResourcePolicy(
        policy_id=f"resource-policy:{action_request.turn_id}:bounded-observation",
        task_id=action_request.turn_id,
        allowed_operations=(str(operation_id or "").strip(),),
        allowed_tools=(tool_name,),
        authority="harness.loop.bounded_observation_resource_policy",
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
    )
    validators = {}
    if workspace_root is not None:
        validators = build_task_safety_validators(
            root_dir=workspace_root,
            safety_envelope={},
            sandbox_policy={},
        )
    return operation_gate.check(
        operation_id,
        resource_policy=resource_policy,
        directive_ref=directive_ref or f"bounded-observation:{action_request.request_id}",
        context=OperationGatePipelineContext(
            permission_mode=str(permission_mode or "default"),
            operation_input={
                "operation_id": operation_id,
                "id": action_request.request_id,
                "name": tool_name,
                "tool_name": tool_name,
                "args": dict(tool_args or {}),
            },
            validators=validators,
        ),
    )
