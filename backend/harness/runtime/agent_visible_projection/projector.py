from __future__ import annotations

from typing import Any

from agent_system.identity import normalize_agent_id_sequence

from ..artifact_scope import runtime_artifact_scope_from_environment
from ..tool_call_contract import ToolCallContract, build_tool_call_contract


def build_agent_visible_runtime_projection(
    *,
    invocation_kind: str,
    allowed_action_types: tuple[str, ...],
    profile_payload: dict[str, Any],
    environment_payload: dict[str, Any],
    operation_authorization: dict[str, Any],
    available_tools: tuple[dict[str, Any], ...],
    permission_mode: str = "default",
    prompt_policy: dict[str, Any] | None = None,
    tool_plan: Any | None = None,
    tool_call_contract: ToolCallContract | None = None,
) -> dict[str, Any]:
    prompt_policy_payload = dict(prompt_policy or {})
    task_lifecycle = dict(profile_payload.get("task_lifecycle_policy") or {})
    planning = dict(profile_payload.get("planning_policy") or {})
    planning_protocol = _planning_protocol_payload(
        invocation_kind=invocation_kind,
        profile_payload=profile_payload,
        permission_mode=permission_mode,
    )
    self_review = dict(profile_payload.get("self_review_policy") or {})
    step_summary = dict(profile_payload.get("step_summary_policy") or {})
    permission = dict(profile_payload.get("permission_policy") or {})
    subagent = dict(profile_payload.get("subagent_policy") or {})
    storage = dict(environment_payload.get("storage_space") or {})
    environment_boundary = dict(environment_payload.get("environment_boundary") or {})
    artifact_scope = runtime_artifact_scope_from_environment(environment_payload)
    allowed_operations = [
        str(item)
        for item in list(operation_authorization.get("allowed_operations") or [])
        if str(item)
    ]
    tool_names = [
        str(item.get("tool_name") or item.get("name") or "")
        for item in available_tools
        if str(item.get("tool_name") or item.get("name") or "")
    ]
    task_scoped_tool_routes = _task_scoped_tool_routes_from_tool_plan(tool_plan)
    service_surface = _service_surface_payload(
        invocation_kind=invocation_kind,
        allowed_action_types=allowed_action_types,
        available_tools=available_tools,
        tool_plan=tool_plan,
    )
    resolved_tool_call_contract = tool_call_contract or build_tool_call_contract(
        invocation_kind=invocation_kind,
        allowed_action_types=allowed_action_types,
        available_tools=available_tools,
        runtime_assembly={"profile": profile_payload},
        tool_plan=tool_plan,
    )
    tool_call_contract_visible = resolved_tool_call_contract.to_agent_visible_payload()
    visible_tool_name_set = {name for name in tool_names if name}
    subagent_lifecycle_enabled = bool(subagent.get("enabled") is True) and bool(
        visible_tool_name_set.intersection(
            {
                "spawn_subagent",
                "send_subagent_message",
                "wait_subagent",
                "list_subagents",
                "close_subagent",
            }
        )
    )
    task_run_allowed = "request_task_run" in allowed_action_types and task_lifecycle.get("request_task_run") is not False
    model_decision_contract = _model_decision_contract_payload(
        invocation_kind=invocation_kind,
        allowed_action_types=allowed_action_types,
        task_run_allowed=task_run_allowed,
        tool_call_contract=resolved_tool_call_contract,
    )
    execution_boundary = _execution_boundary_payload(
        profile_payload=profile_payload,
        operation_authorization=operation_authorization,
        permission_mode=permission_mode,
    )
    payload = {
        "projection_kind": "agent_visible_runtime_projection",
        "invocation_kind": str(invocation_kind or ""),
        "action_surface": model_decision_contract,
        "tool_capability_surface": _tool_capability_surface_payload(
            service_surface=service_surface,
            tool_call_contract=resolved_tool_call_contract,
        ),
        "tool_call_contract": tool_call_contract_visible,
        "model_decision_contract": model_decision_contract,
        "service_surface": service_surface,
        "execution_boundary": execution_boundary,
        "allowed_action_types": list(allowed_action_types),
        "task_lifecycle": {
            "request_task_run_allowed": task_run_allowed,
            "requires_completion_evidence": bool(task_lifecycle.get("requires_completion_evidence") is True),
            "artifact_evidence_required": bool(task_lifecycle.get("artifact_evidence_required") is True),
        },
        "planning": {
            **planning_protocol,
            "specified_plan_allowed": bool(planning.get("specified_plan_allowed") is True),
            "todo_required_when_task_run": bool(planning.get("todo_required_when_task_run") is True),
        },
        "self_review": {
            "enabled": bool(self_review.get("enabled") is True),
            "before_final": str(self_review.get("before_final") or ""),
            "checkpoints": [str(item) for item in list(self_review.get("checkpoints") or []) if str(item)],
            "failure_recovery": str(self_review.get("failure_recovery") or ""),
        },
        "step_summary": {
            "enabled": bool(step_summary.get("enabled") is True),
            "detail": str(step_summary.get("detail") or ""),
        },
        "tool_boundary": {
            "visible_tool_count": len(tool_names),
            "visible_tool_names": tool_names,
            "task_scoped_tool_routes": task_scoped_tool_routes,
            "allowed_operation_count": len(allowed_operations),
            "tools_are_limited_to_visible_context": True,
            "subagent_lifecycle_enabled": subagent_lifecycle_enabled,
            "allowed_subagent_ids": list(
                normalize_agent_id_sequence(str(item) for item in list(subagent.get("allowed_subagent_ids") or []) if str(item))
            ),
        },
        "permission_boundary": {
            "permission_scope": str(permission.get("permission_scope") or permission.get("scope") or ""),
            "permission_mode": str(permission_mode or "default"),
        },
    }
    if _prompt_policy_visible(prompt_policy_payload, "runtime_environment_boundary_visibility", default=True):
        payload["environment_boundary"] = {
            "environment_contract_present": bool(environment_payload.get("environment_id") or environment_boundary),
            "artifact_workspace_available": bool(artifact_scope.artifact_root or storage.get("artifact_root")),
            "persistent_environment_storage_available": bool(storage.get("environment_storage_root")),
        }
    return payload


def _planning_protocol_payload(
    *,
    invocation_kind: str,
    profile_payload: dict[str, Any],
    permission_mode: str,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    planning = dict(profile_payload.get("planning_policy") or {})
    contract_payload = dict(contract or {})
    raw_lock = contract_payload.get("implementation_lock")
    implementation_lock = dict(raw_lock) if isinstance(raw_lock, dict) else {}
    plan_ref = str(
        contract_payload.get("plan_ref")
        or contract_payload.get("approved_plan_ref")
        or implementation_lock.get("plan_ref")
        or ""
    ).strip()
    plan_mode = str(planning.get("plan_mode") or "").strip().lower()
    normalized_permission_mode = str(permission_mode or "default").strip().lower()
    plan_mode_active = normalized_permission_mode == "plan" or plan_mode in {
        "plan",
        "active",
        "required",
        "plan_only",
    }
    plan_required = bool(
        planning.get("requires_plan") is True
        or plan_mode_active
        or implementation_lock
        or str(contract_payload.get("plan_required") or "").strip().lower() in {"1", "true", "yes", "required"}
    )
    lock_status = str(implementation_lock.get("status") or "").strip().lower()
    plan_approved = bool(
        implementation_lock.get("approved") is True
        or lock_status in {"approved", "locked", "implementation_locked"}
        or contract_payload.get("plan_approved") is True
    )
    implementation_allowed = not plan_mode_active and (not plan_required or plan_approved or bool(plan_ref))
    mode = "plan_only" if plan_mode_active else ("implementation_locked" if plan_ref or implementation_lock else str(planning.get("plan_mode") or "available"))
    return _drop_empty_payload(
        {
            "mode": mode,
            "invocation_kind": str(invocation_kind or ""),
            "permission_mode": str(permission_mode or "default"),
            "plan_required": plan_required,
            "plan_mode_active": plan_mode_active,
            "plan_ref": plan_ref,
            "implementation_lock": implementation_lock,
            "implementation_allowed": implementation_allowed,
            "allowed_during_plan": [
                "respond_with_plan",
                "ask_user",
                "read_only_observation",
                "search",
                "request_task_run_with_plan_requirement",
            ],
            "forbidden_during_plan": [
                "edit_file",
                "write_file",
                "side_effect_terminal",
                "git_write",
                "deliverable_write",
                "claim_completed",
            ],
            "deviation_policy": "ask_user_or_block_before_changing_approved_plan",
            "projection_source": "harness.runtime.agent_visible_projection.plan_mode_protocol",
        }
    )


def _model_decision_contract_payload(
    *,
    invocation_kind: str,
    allowed_action_types: tuple[str, ...],
    task_run_allowed: bool,
    tool_call_contract: ToolCallContract | None = None,
) -> dict[str, Any]:
    allowed_actions = [str(item) for item in tuple(allowed_action_types or ()) if str(item)]
    control_actions = [
        item
        for item in ("ask_user", "block", "request_task_run", "active_work_control", "pause_for_user_steer")
        if item in allowed_actions
    ]
    pause_for_user_steer_allowed = "pause_for_user_steer" in allowed_actions
    tool_contract = tool_call_contract.to_hidden_control_payload() if tool_call_contract is not None else {}
    ordinary_tool_submission = str(tool_contract.get("ordinary_tool_submission") or "none")
    control_action_submission = str(tool_contract.get("control_action_submission") or "none")
    ordinary_initial_response_allowed = str(invocation_kind or "") == "single_agent_turn"
    model_invocation_phase = "initial_decision" if ordinary_initial_response_allowed else f"{str(invocation_kind or 'runtime')}_action_decision"
    return {
        "projection_kind": "model_decision_contract",
        "prompt_authority": "runtime_action_contract",
        "invocation_kind": str(invocation_kind or ""),
        "model_invocation_phase": model_invocation_phase,
        "allowed_action_types": allowed_actions,
        "control_actions": control_actions,
        "assistant_response_form": (
            "ordinary_initial_assistant_message"
            if ordinary_initial_response_allowed
            else "model_action_user_visible_field"
        ),
        "natural_response_carrier": (
            "assistant_message"
            if ordinary_initial_response_allowed
            else "assistant_message_or_respond.final_answer"
        ),
        "ordinary_tool_action": "choose_available_tool_and_fill_arguments"
        if ordinary_tool_submission != "none"
        else "not_available",
        "control_action_submission": control_action_submission if control_actions else "none",
        "action_object_required_for": (
            "non_provider_control_fallback_only"
            if ordinary_initial_response_allowed
            else "all_action_phase_decisions_without_provider_control_tool"
        ),
        "assistant_text_allowed_when_no_action": bool(ordinary_initial_response_allowed),
        "required_action_form": (
            "assistant_message_or_tool_action_or_control_action"
            if ordinary_initial_response_allowed
            else "tool_action_or_control_action_or_structured_action_object"
        ),
        "action_phase_natural_response_carrier": "assistant_message_or_respond.final_answer",
        "action_object_shape": {
            "single_unambiguous_action_required": True,
            "markdown_fence_allowed_when_single_action": True,
            "wrapper_text_allowed_when_single_action": True,
            "respond_requires_top_level_final_answer": "action_type=respond 时，最终给用户看的自然回复必须写在顶层 final_answer；不要放入 payload.content、payload.final_answer 或 action.content。",
            "ask_user_requires_top_level_user_question": "action_type=ask_user 时，用户要回答的问题必须写在顶层 user_question；不要通过工具调用表达。",
            "block_requires_top_level_blocking_reason": "action_type=block 时，真实阻塞原因必须写在顶层 blocking_reason。",
            **(
                {
                    "request_task_run_uses_compact_task_start_intent": (
                        "action_type=request_task_run 时，只在 task_run_contract_seed 内填写紧凑 TaskStartIntent；"
                        "这是申请长任务资源的控制动作，不是普通工具调用，也不是第二套模型工作提示。"
                    )
                }
                if task_run_allowed
                else {}
            ),
            **(
                {
                    "pause_for_user_steer_requires_top_level_pause_request": (
                        "action_type=pause_for_user_steer 时，必须填写顶层 pause_request。"
                        "pause_request.reason 必须是 user_steer_requires_pause，必须引用当前 pending_user_steers 中的 steer_ref，"
                        "并写出 checkpoint_summary；不要把这条 steer 放入 consumed_steer_refs。"
                    )
                }
                if pause_for_user_steer_allowed
                else {}
            ),
        },
        **(
            {
                "task_pause_rule": {
                    "pause_for_user_steer_allowed": True,
                    "authority_boundary": "model_decides_semantic_pause_after_current_context_exposes_pending_user_steer",
                    "use_only_when": [
                        "当前请求上下文包含指向当前 task_run 的 pending_user_steers 或等价用户 steer 事实。",
                        "你判断继续当前执行步骤会越过用户最新要求，需要停在可继续边界。",
                        "你能提供 steer_ref 和 checkpoint_summary，让后续接入时先重新判断用户 steer。",
                    ],
                    "do_not_use_for": [
                        "缺权限、缺资源、缺文件、缺外部事实、工具失败、预算耗尽或普通不确定。",
                        "没有 pending_user_steers 的普通任务暂停。",
                        "已经真正处理并消费该 steer 的情况。",
                    ],
                    "resume_contract": "暂停后会留下可继续的事实和句柄；后续接入时，你仍要根据上下文缓存、pending steer 和当前工作事实重新判断下一步。",
                }
            }
            if pause_for_user_steer_allowed
            else {}
        ),
        "long_task_resource_rule": (
            {
                "request_task_run_allowed": True,
                "agent_selects_resource_request": True,
                "ask_user_when_contract_gaps_exist": True,
                "task_start_requires_structured_request_task_run": True,
                "resource_request_conditions": [
                    "需要为后续请求保存目标、计划游标、todo 游标、证据、检查点、验收边界或阶段反馈。",
                    "用户需要能暂停、停止或继续同一个工作单元。",
                    "当前动作需要一个明确的系统资源边界，而不是一次普通工具观察。",
                ],
                "request_task_run_when_agent_selects_resource": (
                    "如果你判断需要长任务资源，并且 TaskStartIntent 足够，提交 action_type=request_task_run；"
                    "不要先用普通工具调用替代资源申请。"
                ),
                "ask_user_when_resource_intent_incomplete": (
                    "如果你判断需要长任务资源但 primary_mode、task_shape、最小下一步、范围或验收模式不足，提交 ask_user 补齐。"
                ),
                "request_task_run_minimum_contract": [
                    "task_run_contract_seed.contract_shape=compact_task_start_intent",
                    "task_run_contract_seed.primary_mode",
                    "task_run_contract_seed.task_shape",
                    "task_run_contract_seed.minimum_viable_next_step",
                    "task_run_contract_seed.working_scope",
                    "task_run_contract_seed.acceptance.mode",
                    "task_run_contract_seed.mode_payload",
                ],
                "single_turn_tool_call_boundary": (
                    "tool_call 是当前请求内的有效路径，用于你判断有限工具观察即可回答、验证或推进的问题；"
                    "选择工具动作时，公开反馈应说明本次查证目标，不得宣称已经申请或绑定长任务资源。"
                ),
            }
            if task_run_allowed
            else {
                "request_task_run_allowed": False,
                "agent_selects_resource_request": False,
                "task_start_requires_structured_request_task_run": False,
                "resource_request_unavailable": "当前可用能力没有提供长任务资源申请入口；不要提交 request_task_run，也不要把普通工具调用描述成已开启 task。",
                "single_turn_tool_call_boundary": (
                    "tool_call 是当前请求内的有效路径，用于你判断有限工具观察即可回答、验证或推进的问题；"
                    "选择工具动作时，公开反馈应说明本次查证目标，不得宣称已经申请或绑定长任务资源。"
                ),
            }
        ),
        "feedback_obligation": {
            "agent_must_give_user_feedback": True,
            "pure_control_feedback_is_carried_by_control_payload_and_projection": True,
            "do_not_emit_detached_assistant_body_for_pure_control": True,
            "public_feedback_must_match_action_type": True,
            "task_resource_claim_requires_request_task_run": bool(task_run_allowed),
        },
    }


def _service_surface_payload(
    *,
    invocation_kind: str,
    allowed_action_types: tuple[str, ...],
    available_tools: tuple[dict[str, Any], ...],
    tool_plan: Any | None,
) -> dict[str, Any]:
    mounted_tools: list[dict[str, str]] = []
    for tool in available_tools:
        payload = dict(tool or {})
        tool_name = str(payload.get("tool_name") or payload.get("name") or "").strip()
        if not tool_name:
            continue
        mounted_tools.append(
            {
                "tool_name": tool_name,
                "operation_id": str(payload.get("operation_id") or tool_name),
                "owner_scope": str(payload.get("owner_scope") or "none"),
            }
        )
    return {
        "projection_kind": "service_surface",
        "invocation_kind": str(invocation_kind or ""),
        "tool_action_available": "tool_call" in set(allowed_action_types or ()),
        "ordinary_tool_submission": "tool_action" if "tool_call" in set(allowed_action_types or ()) else "none",
        "mounted_tools": mounted_tools,
        "unmounted_services": [
            {
                "service": str(issue.get("tool_name") or issue.get("operation_id") or ""),
                "tool_name": str(issue.get("tool_name") or ""),
                "operation_id": str(issue.get("operation_id") or ""),
                "category": _tool_filter_issue_category(issue),
                "reason": str(issue.get("reason") or ""),
                "source": str(issue.get("source") or ""),
                "required_action": str(dict(issue.get("metadata") or {}).get("required_action") or ""),
            }
            for issue in _tool_filter_issues_from_tool_plan(tool_plan)
            if str(issue.get("tool_name") or issue.get("operation_id") or "").strip()
        ],
    }


def _tool_capability_surface_payload(
    *,
    service_surface: dict[str, Any],
    tool_call_contract: ToolCallContract,
) -> dict[str, Any]:
    contract = tool_call_contract.to_hidden_control_payload()
    mounted_tools = [
        {
            "tool_name": str(item.get("tool_name") or ""),
            "operation_id": str(item.get("operation_id") or ""),
            "owner_scope": str(item.get("owner_scope") or "none"),
        }
        for item in list(dict(service_surface or {}).get("mounted_tools") or [])
        if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
    ]
    return {
        "projection_kind": "tool_capability_surface",
        "tool_action_available": str(contract.get("ordinary_tool_submission") or "none") != "none",
        "tool_action_submission": "choose_available_tool_and_fill_arguments"
        if str(contract.get("ordinary_tool_submission") or "none") != "none"
        else "not_available",
        "mounted_tools": mounted_tools,
        "unavailable_tools": list(dict(service_surface or {}).get("unmounted_services") or []),
        "mounted_tools_ref": "tool_index_stable.available_tools",
        "feedback_boundary": "denied, invalid, unmounted, or budget-exhausted tool actions return feedback for the next agent decision",
    }


def _execution_boundary_payload(
    *,
    profile_payload: dict[str, Any],
    operation_authorization: dict[str, Any],
    permission_mode: str,
) -> dict[str, Any]:
    permission = dict(profile_payload.get("permission_policy") or {})
    return {
        "permission_mode": str(permission_mode or "default"),
        "permission_scope": str(permission.get("permission_scope") or permission.get("scope") or ""),
        "allowed_operation_count": len(list(operation_authorization.get("allowed_operations") or [])),
        "approval_required_operation_count": len(list(operation_authorization.get("requires_approval_operations") or [])),
        "operation_gate_stage": "concrete tool actions are rechecked at execution time for permission and side-effect risk",
    }


def _tool_filter_issues_from_tool_plan(tool_plan: Any | None) -> list[dict[str, Any]]:
    plan = tool_plan.to_dict() if hasattr(tool_plan, "to_dict") else dict(tool_plan or {})
    capability_table = dict(plan.get("capability_table") or {})
    return [dict(item or {}) for item in list(capability_table.get("filtered") or []) if isinstance(item, dict)]


def _tool_filter_issue_category(issue: dict[str, Any]) -> str:
    reason = str(dict(issue or {}).get("reason") or "")
    source = str(dict(issue or {}).get("source") or "")
    if reason == "task_scoped_tool_requires_task_run":
        return "requires_task_run"
    if "approval" in reason:
        return "approval_required"
    if "denied" in reason or source == "operation_authorization":
        return "permission_denied"
    return "service_unavailable"


def _task_scoped_tool_routes_from_tool_plan(tool_plan: Any | None) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    for item in _tool_filter_issues_from_tool_plan(tool_plan):
        issue = dict(item or {})
        if str(issue.get("reason") or "") != "task_scoped_tool_requires_task_run":
            continue
        metadata = dict(issue.get("metadata") or {})
        routes.append(
            {
                "tool_name": str(issue.get("tool_name") or ""),
                "operation_id": str(issue.get("operation_id") or ""),
                "owner_scope": str(metadata.get("owner_scope") or ""),
                "required_action": str(metadata.get("required_action") or "request_task_run"),
            }
        )
    return [item for item in routes if item["tool_name"]]


def _prompt_policy_visible(policy: dict[str, Any], key: str, *, default: bool) -> bool:
    if key not in dict(policy or {}):
        return default
    value = dict(policy or {}).get(key)
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"", "default", "inherit"}:
        return default
    if normalized in {"hidden", "hide", "off", "false", "0", "none", "disabled", "omit", "omitted"}:
        return False
    if normalized in {"visible", "show", "on", "true", "1", "full", "enabled"}:
        return True
    return default


def _drop_empty_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {})
    }
