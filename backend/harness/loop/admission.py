from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .model_action_protocol import AnyModelActionRequest


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
    action_request: AnyModelActionRequest,
    *,
    packet_allowed_action_types: tuple[str, ...] = (),
    invocation_kind: str = "",
    definitions_by_name: dict[str, Any] | None = None,
    allowed_tool_names: set[str] | None = None,
    runtime_profile: dict[str, Any] | None = None,
    permission_mode: str = "default",
    side_effect_policy: Literal["requires_task_run", "runtime_authorized"] = "requires_task_run",
) -> AdmissionDecision:
    allowed_actions = {str(item or "").strip() for item in tuple(packet_allowed_action_types or ()) if str(item or "").strip()}
    if allowed_actions and action_request.action_type not in allowed_actions:
        return AdmissionDecision(
            admission_id=f"admission:{action_request.request_id}",
            action_request_ref=action_request.request_id,
            decision="deny",
            user_visible_reason="本轮运行时不允许执行该动作。",
            system_reason="action_not_allowed_by_packet",
            resource_errors=(f"action_not_allowed_by_packet:{action_request.action_type}",),
            permission_delta={
                "action_type": action_request.action_type,
                "allowed_action_types": sorted(allowed_actions),
                "invocation_kind": str(invocation_kind or ""),
            },
        )
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
        if not bool(getattr(definition, "is_read_only", False)) and side_effect_policy != "runtime_authorized":
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="needs_contract",
                user_visible_reason="这个动作会改变环境，需要先确认处理目标和安全边界。",
                system_reason="side_effect_tool_requires_task_run",
                resource_errors=(f"tool_requires_task_run:{tool_name}",),
            )
        operation_id = str(getattr(definition, "operation_id", "") or tool_name)
        return AdmissionDecision(
            admission_id=f"admission:{action_request.request_id}",
            action_request_ref=action_request.request_id,
            decision="allow",
            permission_delta={
                "tool_name": tool_name,
                "operation_id": operation_id,
                "read_only": bool(getattr(definition, "is_read_only", False)),
                "gate_stage": "deferred_to_tool_control_plane",
                "permission_mode": str(permission_mode or "default"),
            },
            )
    if action_request.action_type == "request_task_run":
        task_lifecycle_policy = dict(dict(runtime_profile or {}).get("task_lifecycle_policy") or {})
        if task_lifecycle_policy.get("request_task_run") is False:
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="deny",
                user_visible_reason="当前运行模式不允许开始持续处理。",
                system_reason="task_lifecycle_disabled_by_runtime_profile",
                contract_errors=("task_lifecycle_disabled_by_runtime_profile",),
            )
    if action_request.action_type == "request_task_run" and not getattr(action_request, "task_contract_seed", {}):
        return AdmissionDecision(
            admission_id=f"admission:{action_request.request_id}",
            action_request_ref=action_request.request_id,
            decision="needs_contract",
            user_visible_reason="需要先补充处理目标和验收标准，才能开始持续处理。",
            system_reason="task_contract_seed_missing",
            contract_errors=("task_contract_seed_missing",),
        )
    if action_request.action_type == "request_registered_engagement":
        task_lifecycle_policy = dict(dict(runtime_profile or {}).get("task_lifecycle_policy") or {})
        if task_lifecycle_policy.get("request_task_run") is False:
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="deny",
                user_visible_reason="当前运行模式不允许发起已注册任务承接计划。",
                system_reason="registered_engagement_disabled_by_runtime_profile",
                contract_errors=("registered_engagement_disabled_by_runtime_profile",),
            )
        engagement_request = dict(getattr(action_request, "engagement_request", {}) or {})
        if not str(engagement_request.get("plan_id") or "").strip():
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="needs_contract",
                user_visible_reason="需要明确要接入的处理计划，当前不能替你猜测。",
                system_reason="engagement_plan_id_missing",
                contract_errors=("engagement_plan_id_missing",),
            )
    if action_request.action_type == "active_work_control":
        task_lifecycle_policy = dict(dict(runtime_profile or {}).get("task_lifecycle_policy") or {})
        if task_lifecycle_policy.get("active_work_control") is False:
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="deny",
                user_visible_reason="当前运行模式不允许控制进行中的工作。",
                system_reason="active_work_control_disabled_by_runtime_profile",
                contract_errors=("active_work_control_disabled_by_runtime_profile",),
            )
    return AdmissionDecision(
        admission_id=f"admission:{action_request.request_id}",
        action_request_ref=action_request.request_id,
        permission_delta={
            "action_type": action_request.action_type,
            "allowed_action_types": sorted(allowed_actions),
            "invocation_kind": str(invocation_kind or ""),
        },
        decision="allow",
    )


def _invalid(action_request: AnyModelActionRequest, reason: str) -> AdmissionDecision:
    return AdmissionDecision(
        admission_id=f"admission:{action_request.request_id}",
        action_request_ref=action_request.request_id,
        decision="invalid",
        user_visible_reason="本轮处理格式不完整，运行时未执行该动作；请修正动作格式后继续。",
        system_reason=reason,
        resource_errors=(reason,),
    )
