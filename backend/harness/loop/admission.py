from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from harness.current_work_receipt import current_work_control_availability_from_receipt

from .model_action_protocol import AnyModelActionRequest


AdmissionDecisionValue = Literal["allow", "deny", "ask_approval", "invalid", "needs_contract", "needs_task_run", "operation_unavailable"]
_TASK_RUNTIME_OWNER_SCOPES = {"task_memory"}
_TASK_RUNTIME_TOOL_NAMES = {"agent_todo"}
_TASK_RUNTIME_OPERATION_IDS = {"op.agent_todo"}


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
    issue_category: str = ""
    issue_code: str = ""
    action_issue: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.loop.admission"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.admission":
            raise ValueError("AdmissionDecision authority must be harness.loop.admission")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contract_errors"] = list(self.contract_errors)
        payload["resource_errors"] = list(self.resource_errors)
        payload["permission_delta"] = dict(self.permission_delta or {})
        payload["action_issue"] = dict(self.action_issue or {})
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
    current_work_boundary_receipt: dict[str, Any] | None = None,
) -> AdmissionDecision:
    allowed_actions = {str(item or "").strip() for item in tuple(packet_allowed_action_types or ()) if str(item or "").strip()}
    if allowed_actions and action_request.action_type not in allowed_actions:
        issue = _action_issue(
            action_request,
            category="protocol_violation",
            code="action_not_in_model_decision_contract",
            user_visible_summary="模型动作不在本轮开发者动作合同中，运行时未执行。",
            repair_instruction="请按本轮 model_decision_contract.semantic_actions 选择一个合法动作。",
            extra={
                "allowed_action_types": sorted(allowed_actions),
                "invocation_kind": str(invocation_kind or ""),
            },
        )
        return AdmissionDecision(
            admission_id=f"admission:{action_request.request_id}",
            action_request_ref=action_request.request_id,
            decision="deny",
            user_visible_reason="模型动作不在本轮动作合同中，运行时未执行。",
            system_reason="action_not_in_model_decision_contract",
            resource_errors=(f"action_not_in_model_decision_contract:{action_request.action_type}",),
            permission_delta={
                "action_type": action_request.action_type,
                "allowed_action_types": sorted(allowed_actions),
                "invocation_kind": str(invocation_kind or ""),
            },
            issue_category="protocol_violation",
            issue_code="action_not_in_model_decision_contract",
            action_issue=issue,
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
            issue = _action_issue(
                action_request,
                category="service_unavailable",
                code="tool_not_in_runtime_service_surface",
                requested_tool_name=tool_name,
                user_visible_summary="请求的工具没有在本次运行时服务面中开放。",
                repair_instruction="请改用当前可见工具，或在任务需要该服务时请求进入正确任务环境/持续任务。",
            )
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="deny",
                user_visible_reason="请求的工具没有在本次运行时中开放。",
                system_reason="tool_not_in_runtime_assembly",
                resource_errors=(f"tool_not_in_runtime_assembly:{tool_name}",),
                issue_category="service_unavailable",
                issue_code="tool_not_in_runtime_service_surface",
                action_issue=issue,
            )
        if definition is None:
            issue = _action_issue(
                action_request,
                category="service_unavailable",
                code="tool_definition_not_available",
                requested_tool_name=tool_name,
                user_visible_summary="请求的工具当前没有可执行定义。",
                repair_instruction="请改用当前服务面中已有工具，或说明能力投影缺口。",
            )
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="deny",
                user_visible_reason="请求的工具当前不可用。",
                system_reason="tool_not_available",
                resource_errors=(f"tool_not_available:{tool_name}",),
                issue_category="service_unavailable",
                issue_code="tool_definition_not_available",
                action_issue=issue,
            )
        owner_scope = _tool_owner_scope(definition)
        operation_id = str(getattr(definition, "operation_id", "") or tool_name)
        if invocation_kind in {"single_agent_turn", "agent_turn"} and (
            owner_scope in _TASK_RUNTIME_OWNER_SCOPES
            or tool_name in _TASK_RUNTIME_TOOL_NAMES
            or operation_id in _TASK_RUNTIME_OPERATION_IDS
        ):
            issue = _action_issue(
                action_request,
                category="requires_task_run",
                code="task_scoped_tool_requires_task_run",
                requested_tool_name=tool_name,
                user_visible_summary="该工具属于任务运行态服务，需要先进入持续任务。",
                repair_instruction="如果当前目标需要该工具，请提交 request_task_run；若合同信息不足，请 ask_user 补齐。",
                extra={
                    "operation_id": operation_id,
                    "owner_scope": owner_scope,
                    "required_action": "request_task_run",
                },
            )
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="needs_task_run",
                user_visible_reason="这个工具属于任务运行作用域，需要先进入持续任务。",
                system_reason="task_scoped_tool_requires_task_run",
                resource_errors=(f"task_scoped_tool_requires_task_run:{tool_name}",),
                permission_delta={
                    "tool_name": tool_name,
                    "operation_id": operation_id,
                    "owner_scope": owner_scope,
                    "required_action": "request_task_run",
                    "invocation_kind": str(invocation_kind or ""),
                },
                issue_category="requires_task_run",
                issue_code="task_scoped_tool_requires_task_run",
                action_issue=issue,
            )
        if str(permission_mode or "").strip().lower() == "plan" and not _tool_allowed_in_plan_mode(definition, tool_name):
            issue = _action_issue(
                action_request,
                category="permission_denied",
                code="plan_mode_blocks_side_effect_tool",
                requested_tool_name=tool_name,
                user_visible_summary="当前计划模式没有挂载实施类副作用工具。",
                repair_instruction="请继续只读探索、整理计划、ask_user，或在计划获批后进入执行。",
                extra={"permission_mode": str(permission_mode or "default")},
            )
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="deny",
                user_visible_reason="当前处于计划模式，只允许只读探索、搜索和询问；实施类工具需要计划获批后再执行。",
                system_reason="plan_mode_blocks_side_effect_tool",
                resource_errors=(f"plan_mode_blocks_side_effect_tool:{tool_name}",),
                permission_delta={
                    "tool_name": tool_name,
                    "permission_mode": str(permission_mode or "default"),
                    "plan_mode_allowed_actions": ["respond", "ask_user", "read_only_tool_call", "request_task_run"],
                },
                issue_category="permission_denied",
                issue_code="plan_mode_blocks_side_effect_tool",
                action_issue=issue,
            )
        if not bool(getattr(definition, "is_read_only", False)) and side_effect_policy != "runtime_authorized":
            issue = _action_issue(
                action_request,
                category="requires_task_run",
                code="side_effect_tool_requires_task_run",
                requested_tool_name=tool_name,
                user_visible_summary="该动作会改变环境，需要先形成任务合同和执行边界。",
                repair_instruction="请先提交 request_task_run 或 ask_user 补齐目标、范围和验收标准。",
            )
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="needs_contract",
                user_visible_reason="这个动作会改变环境，需要先确认处理目标和安全边界。",
                system_reason="side_effect_tool_requires_task_run",
                resource_errors=(f"tool_requires_task_run:{tool_name}",),
                issue_category="requires_task_run",
                issue_code="side_effect_tool_requires_task_run",
                action_issue=issue,
            )
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
            issue = _action_issue(
                action_request,
                category="runtime_unavailable",
                code="task_lifecycle_disabled_by_runtime_profile",
                user_visible_summary="当前运行模式未开放持续任务生命周期。",
                repair_instruction="请改用 ask_user、respond 或 block 说明持续任务生命周期未挂载；不要假装已经进入持续任务。",
            )
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="deny",
                user_visible_reason="当前运行模式没有挂载持续任务生命周期。",
                system_reason="task_lifecycle_disabled_by_runtime_profile",
                contract_errors=("task_lifecycle_disabled_by_runtime_profile",),
                issue_category="runtime_unavailable",
                issue_code="task_lifecycle_disabled_by_runtime_profile",
                action_issue=issue,
            )
    if action_request.action_type == "request_task_run" and not getattr(action_request, "task_run_contract_seed", {}):
        issue = _action_issue(
            action_request,
            category="contract_gap",
            code="task_run_contract_seed_missing",
            user_visible_summary="持续任务缺少任务运行合同。",
            repair_instruction="请 ask_user 补齐进入原因、primary Work Mode、下一步和验收模式，或重新提交完整 request_task_run。",
        )
        return AdmissionDecision(
            admission_id=f"admission:{action_request.request_id}",
            action_request_ref=action_request.request_id,
            decision="needs_contract",
            user_visible_reason="需要先补充任务运行合同和 primary Work Mode，才能开始持续处理。",
            system_reason="task_run_contract_seed_missing",
            contract_errors=("task_run_contract_seed_missing",),
            issue_category="contract_gap",
            issue_code="task_run_contract_seed_missing",
            action_issue=issue,
        )
    if action_request.action_type == "active_work_control":
        receipt = dict(current_work_boundary_receipt or {})
        active_work_availability = current_work_control_availability_from_receipt(receipt)
        if not active_work_availability.available:
            issue = _action_issue(
                action_request,
                category="operation_unavailable",
                code="active_work_control_unavailable",
                user_visible_summary="当前运行状态没有开放进行中工作控制。",
                repair_instruction="请选择 respond、ask_user 或 block；不要把历史任务或普通上下文当成可控制的当前工作。",
                extra={
                    "receipt_id": str(receipt.get("receipt_id") or ""),
                    "boundary_decision": str(receipt.get("boundary_decision") or ""),
                    "availability_reason": active_work_availability.reason,
                },
            )
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="operation_unavailable",
                user_visible_reason="当前运行状态没有开放进行中工作控制。",
                system_reason="active_work_control_unavailable",
                contract_errors=("active_work_control_unavailable",),
                permission_delta={
                    "action_type": action_request.action_type,
                    "receipt_id": str(receipt.get("receipt_id") or ""),
                    "invocation_kind": str(invocation_kind or ""),
                },
                issue_category="operation_unavailable",
                issue_code="active_work_control_unavailable",
                action_issue=issue,
            )
        task_lifecycle_policy = dict(dict(runtime_profile or {}).get("task_lifecycle_policy") or {})
        if task_lifecycle_policy.get("active_work_control") is False:
            issue = _action_issue(
                action_request,
                category="runtime_unavailable",
                code="active_work_control_disabled_by_runtime_profile",
                user_visible_summary="当前运行模式未开放 active work 控制。",
                repair_instruction="请改用 respond、ask_user 或 block 说明 active work 控制未挂载；不要假装已控制当前工作。",
            )
            return AdmissionDecision(
                admission_id=f"admission:{action_request.request_id}",
                action_request_ref=action_request.request_id,
                decision="deny",
                user_visible_reason="当前运行模式没有挂载进行中工作控制。",
                system_reason="active_work_control_disabled_by_runtime_profile",
                contract_errors=("active_work_control_disabled_by_runtime_profile",),
                issue_category="runtime_unavailable",
                issue_code="active_work_control_disabled_by_runtime_profile",
                action_issue=issue,
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
    issue = _action_issue(
        action_request,
        category="protocol_violation",
        code=reason,
        user_visible_summary="模型动作格式不完整，运行时未执行。",
        repair_instruction="请按本轮动作协议重新提交一个合法 action。",
    )
    return AdmissionDecision(
        admission_id=f"admission:{action_request.request_id}",
        action_request_ref=action_request.request_id,
        decision="invalid",
        user_visible_reason="本轮处理格式不完整，运行时未执行该动作；请修正动作格式后继续。",
        system_reason=reason,
        resource_errors=(reason,),
        issue_category="protocol_violation",
        issue_code=reason,
        action_issue=issue,
    )


def _action_issue(
    action_request: AnyModelActionRequest,
    *,
    category: str,
    code: str,
    user_visible_summary: str,
    repair_instruction: str,
    requested_tool_name: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "authority": "harness.loop.action_issue",
        "category": str(category or ""),
        "code": str(code or ""),
        "model_intent_preserved": True,
        "requested_action_type": str(getattr(action_request, "action_type", "") or ""),
        "requested_tool_name": str(requested_tool_name or ""),
        "repair_instruction": str(repair_instruction or ""),
        "user_visible_summary": str(user_visible_summary or ""),
    }
    if extra:
        payload.update(dict(extra))
    return payload


def _tool_allowed_in_plan_mode(definition: Any, tool_name: str) -> bool:
    if bool(getattr(definition, "is_read_only", False)):
        return True
    operation_id = str(getattr(definition, "operation_id", "") or tool_name).strip()
    read_only_operations = {
        "op.model_response",
        "op.read_file",
        "op.read_structured_file",
        "op.list_dir",
        "op.stat_path",
        "op.path_exists",
        "op.glob_paths",
        "op.search_files",
        "op.search_text",
        "op.git_status",
        "op.git_diff",
        "op.git_log",
        "op.git_show",
        "op.git_branch_list",
        "op.web_search",
        "op.fetch_url",
        "op.codebase_search",
        "op.memory_read",
        "op.mcp_retrieval",
        "op.mcp_pdf",
        "op.mcp_structured_data",
    }
    return operation_id in read_only_operations or str(tool_name or "").strip() in {
        "read_file",
        "read_structured_file",
        "list_dir",
        "stat_path",
        "path_exists",
        "glob_paths",
        "search_files",
        "search_text",
        "git_status",
        "git_diff",
        "git_log",
        "git_show",
        "git_branch_list",
        "web_search",
        "fetch_url",
    }


def _tool_owner_scope(definition: Any) -> str:
    contract = getattr(definition, "contract", None)
    return str(getattr(contract, "owner_scope", "") or getattr(definition, "owner_scope", "") or "none").strip()
