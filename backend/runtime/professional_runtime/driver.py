from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, ToolMessage

from config import get_settings
from runtime_encoding import build_windows_powershell_command, is_windows, utf8_subprocess_text_kwargs
from capability_system.units.tools.sandbox_command_guard import validate_sandbox_command_text
from runtime.tool_runtime.tool_call_policy import ToolCallBindingOptions, build_round_tool_call_options
from runtime.environment import RuntimeEnvironment, check_runtime_connection_health
from runtime.tool_runtime.provider_tool_call_adapter import tool_calls_for_langchain_messages
from orchestration.runtime_directive import RuntimeDirective
from task_system.tasks.run_models import (
    TaskRunLedger,
    advance_task_run_ledger,
    append_plan_item_step,
    complete_task_run_step,
    current_task_step_run,
    find_task_step_run,
    next_pending_step_run,
    start_task_run_step,
    update_task_run_step_diagnostics,
)

from ..contracts.deliverable_validator import validate_deliverable
from ..memory.evidence_packet import build_evidence_packet
from ..shared.models import RuntimeLoopState
from ..contracts.obligation_validation import validate_obligations
from .evidence_closeout import (
    _adopt_runtime_event_ref,
    _answer_metadata_from_done_event,
    _artifact_output_refs_from_tool_payload,
    _contains_tool_call_markup,
    _event_protocol_leak_detected,
    _evidence_packet_prompt,
    _normalize_professional_verification,
    _professional_closeout_repair_instruction,
    _runtime_event_observation_ref,
    _sanitize_final_content,
    _should_repair_professional_closeout,
    _strip_tool_call_markup,
    _tool_observation_payload,
)
from .goal_contract import (
    ProfessionalTaskGoalContract,
    _dedupe_strings,
    _goal_contract_from_semantic_contract,
)
from .completion_judgment import build_verification_review, judge_completion
from .run_session import build_professional_run_session
from .runtime_policy import (
    _allowed_tool_names_from_policy,
    _first_finalize_step_id,
    _model_only_directive,
    _professional_runtime_policy,
    _professional_task_directive,
    _standard_action_step_id,
    _with_professional_task_instruction,
)
from .deliverable_progress import DeliverableProgress, build_deliverable_progress
from .progress_policy import check_progress_policy
from .action_gate import ActionGateDecision, decide_next_action_gate
from runtime.shared.policy_rejection_observation import build_policy_rejection_observation
from runtime.shared.action_request import build_tool_result_observation
from .stage_summary import build_stage_summary
from .timeout_recovery import build_timeout_recovery_observation, timeout_recovery_messages
from .state_machine import initial_professional_run_state, unsatisfied_obligations_from_verification
from .closeout_repair import (
    build_evidence_gap_guidance,
    suggest_evidence_repair_tools,
)
from ..memory.tool_observation_ledger import ToolObservationLedger, build_tool_observation_record
from ..outcome import build_professional_run_outcome
from ..execution_engine.event_translation import append_executor_observation_event, append_tool_result_received_event


RuntimeEventBuilder = Callable[..., Any]
StateWithLedger = Callable[..., RuntimeLoopState]


def _deliverable_progress(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> DeliverableProgress:
    return build_deliverable_progress(
        goal_contract=goal_contract,
        tool_observation_ledger=tool_observation_ledger,
    )


def _queue_diagnostics(deliverable_progress: DeliverableProgress) -> dict[str, Any]:
    return {"deliverable_progress": deliverable_progress.to_dict()}


def _runtime_feedback_payload(
    *,
    source: str,
    requested_tool_name: str = "",
    action_gate: ActionGateDecision | None = None,
    deliverable_progress: DeliverableProgress | None = None,
    repair_instruction: str = "",
) -> dict[str, Any]:
    progress_payload = deliverable_progress.to_dict() if deliverable_progress is not None else {}
    next_missing = dict(progress_payload.get("next_missing_deliverable") or {})
    gate_payload = action_gate.to_dict() if action_gate is not None else {}
    allowed_tools = list(gate_payload.get("allowed_tool_names") or [])
    suggested_tools = list(next_missing.get("suggested_tool_names") or [])
    missing_obligations = list(gate_payload.get("missing_obligations") or progress_payload.get("missing_obligations") or [])
    target_path = str(gate_payload.get("target_path") or next_missing.get("path") or "")
    if str(gate_payload.get("stage") or "") not in {"read_material", "verify_output"}:
        target_path = str(next_missing.get("path") or gate_payload.get("target_path") or "")
    return {
        "authority": "professional_runtime.runtime_feedback",
        "source": str(source or ""),
        "requested_tool": str(requested_tool_name or ""),
        "allowed_tool_names": allowed_tools,
        "suggested_tool_names": suggested_tools or allowed_tools,
        "next_missing_obligation": next_missing,
        "missing_obligations": missing_obligations,
        "target_path": target_path,
        "repair_instruction": str(repair_instruction or ""),
        "principle": "runtime_provides_environment_guardrails_and_actionable_feedback; agent_chooses_next_valid_action",
    }


def _tools_with_goal_contract_requirements(
    *,
    allowed_tool_names: list[str],
    tool_policy: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    runtime_tool_instances: list[Any] | None,
    tool_runtime_executor: Any | None = None,
) -> list[str]:
    allowed = list(allowed_tool_names or [])
    available = {
        str(getattr(tool, "name", "") or "").strip()
        for tool in list(runtime_tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip()
    }
    runtime = getattr(tool_runtime_executor, "tool_runtime", None) if tool_runtime_executor is not None else None
    for tool_name in ("terminal", "browser_control"):
        getter = getattr(runtime, "get_instance", None)
        if callable(getter) and getter(tool_name) is not None:
            available.add(tool_name)
    denied = {
        str(item or "").strip()
        for item in list(dict(tool_policy or {}).get("denied_tool_names") or [])
        if str(item or "").strip()
    }
    if goal_contract.requires_verification_command:
        for tool_name in ("terminal", "browser_control"):
            if tool_name in available and tool_name not in denied and tool_name not in allowed:
                allowed.append(tool_name)
    return allowed


def _filter_tool_names_by_capability_table(
    *,
    allowed_tool_names: list[str],
    task_operation: dict[str, Any],
) -> list[str]:
    table = dict(task_operation or {}).get("tool_capability_table")
    if table is None or not hasattr(table, "dispatchable_tools"):
        return list(allowed_tool_names or [])
    dispatchable = {
        str(item or "").strip()
        for item in tuple(getattr(table, "dispatchable_tools", ()) or ())
        if str(item or "").strip()
    }
    if not dispatchable:
        return []
    return [
        str(item or "").strip()
        for item in list(allowed_tool_names or [])
        if str(item or "").strip() in dispatchable
    ]


def _runtime_tool_instances_for_allowed_tools(
    *,
    runtime_tool_instances: list[Any] | None,
    tool_runtime_executor: Any | None,
    allowed_tool_names: list[str],
    tool_execution_enabled: bool,
) -> list[Any]:
    if not tool_execution_enabled:
        return []
    allowed = {str(item or "").strip() for item in list(allowed_tool_names or []) if str(item or "").strip()}
    instances = [
        tool
        for tool in list(runtime_tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip() in allowed
    ]
    seen = {str(getattr(tool, "name", "") or "").strip() for tool in instances}
    runtime = getattr(tool_runtime_executor, "tool_runtime", None) if tool_runtime_executor is not None else None
    getter = getattr(runtime, "get_instance", None)
    if callable(getter):
        for name in sorted(allowed):
            if name in seen:
                continue
            tool = getter(name)
            if tool is not None:
                instances.append(tool)
                seen.add(name)
    return instances


def _professional_progress_page(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    deliverable_progress: DeliverableProgress,
    turn_count: int,
    tool_call_count: int,
    tool_observation_count: int,
) -> dict[str, Any]:
    written_paths = _ledger_paths_for_satisfaction(tool_observation_ledger, "write_output")
    verified = tool_observation_ledger.verification_passed()
    pending_deliverables = [
        {
            "obligation_id": obligation.obligation_id,
            "kind": obligation.kind,
            "path": obligation.path,
            "suggested_tool_names": list(obligation.suggested_tool_names),
        }
        for obligation in deliverable_progress.obligations
        if not obligation.satisfied
    ]
    next_missing = deliverable_progress.next_missing_deliverable
    completed_kinds = sorted({item for record in tool_observation_ledger.records for item in record.satisfies})
    if next_missing is not None:
        next_step = deliverable_progress.progress_hint()
    elif goal_contract.requires_verification_command and not verified:
        next_step = "下一步运行 terminal 验证命令，并基于真实输出收口。"
    else:
        next_step = "下一步根据证据包判断是否可以最终收口。"
    return {
        "title": "阶段进展",
        "status": "running",
        "turn_count": int(turn_count or 0),
        "tool_call_count": int(tool_call_count or 0),
        "tool_observation_count": int(tool_observation_count or 0),
        "completed": completed_kinds,
        "written_paths": written_paths,
        "verification_passed": bool(verified),
        "pending_deliverables": pending_deliverables,
        "next_missing_deliverable": next_missing.to_dict() if next_missing is not None else {},
        "next_step": next_step,
        "summary": _progress_page_summary(
            written_paths=written_paths,
            pending_deliverables=pending_deliverables,
            verified=verified,
            next_step=next_step,
        ),
        "authority": "professional_runtime.progress_page",
    }


def _progress_page_summary(
    *,
    written_paths: list[str],
    pending_deliverables: list[dict[str, Any]],
    verified: bool,
    next_step: str,
) -> str:
    lines = ["阶段总结："]
    if written_paths:
        lines.append("已写入：" + "、".join(written_paths[-8:]))
    else:
        lines.append("已写入：暂无真实写入产物")
    if pending_deliverables:
        pending_paths = [str(item.get("path") or item.get("kind") or "").strip() for item in pending_deliverables[:8]]
        lines.append("待完成：" + "、".join(path for path in pending_paths if path))
    else:
        lines.append("待完成：无明确缺失交付物")
    lines.append("验证：" + ("已通过" if verified else "尚未通过或尚未运行"))
    lines.append("下一步：" + next_step)
    return "\n".join(lines)


def _closeout_resubmission_tools(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    deliverable_validation: dict[str, Any],
    obligation_validation: dict[str, Any],
    allowed_tool_names: list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    allowed = {str(item or "").strip() for item in list(allowed_tool_names or []) if str(item or "").strip()}
    deliverable_progress = _deliverable_progress(goal_contract, tool_observation_ledger)
    if deliverable_progress.next_missing_deliverable is not None:
        return tuple(name for name in deliverable_progress.next_missing_deliverable.suggested_tool_names if name in allowed)
    missing = {
        str(item or "").strip()
        for item in [
            *list(deliverable_validation.get("missing_deliverables") or []),
            *list(deliverable_validation.get("unsupported_claims") or []),
            *list(obligation_validation.get("missing_required_actions") or []),
            *list(obligation_validation.get("missing_output_paths") or []),
            *list(obligation_validation.get("missing_response_terms") or []),
        ]
        if str(item or "").strip()
    }
    if any(item.startswith("output_path:") for item in missing):
        return tuple(name for name in ("write_file", "edit_file") if name in allowed)
    verification_missing = bool(
        missing.intersection({"verification_evidence", "verify_command", "run_verification", "run_browser_verification"})
        or "verification_evidence" in missing
    )
    if verification_missing:
        return tuple(name for name in ("browser_control", "terminal") if name in allowed)
    if "visual_asset_refs" in missing or "runnable_artifact_refs" in missing or "gameplay_acceptance" in missing:
        if not tool_observation_ledger.has_write():
            return tuple(name for name in ("write_file", "edit_file") if name in allowed)
        return tuple(name for name in ("browser_control", "terminal") if name in allowed)
    return ()


def _closeout_resubmission_instruction(
    *,
    suggested_tool_names: tuple[str, ...],
    deliverable_validation: dict[str, Any],
    obligation_validation: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> str:
    missing_items = _dedupe_strings(
        [
            *[str(item) for item in list(deliverable_validation.get("missing_deliverables") or [])],
            *[str(item) for item in list(obligation_validation.get("missing_required_actions") or [])],
            *[str(item) for item in list(obligation_validation.get("missing_output_paths") or [])],
        ]
    )
    deliverable_progress = _deliverable_progress(goal_contract, tool_observation_ledger)
    return (
        "上一轮最终回答还不能收口：运行时验收发现仍缺少真实证据或真实产物。"
        f"缺失项：{'、'.join(missing_items) if missing_items else '未满足的执行义务'}。"
        f"建议补交证据的工具：{'、'.join(suggested_tool_names)}。"
        f"{deliverable_progress.progress_hint()}"
        "不要重写总结来绕过验收；先补齐真实证据，工具返回后再基于真实结果收口。"
    )


def _round_tool_instances_for_gate(
    *,
    model_tool_instances: list[Any] | tuple[Any, ...],
    gate: ActionGateDecision,
) -> list[Any]:
    if not gate.forced:
        return list(model_tool_instances or [])
    allowed = set(gate.allowed_tool_names)
    return [
        tool
        for tool in list(model_tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip() in allowed
    ]


def _round_tool_call_options_for_gate(
    *,
    max_tool_calls: int,
    gate: ActionGateDecision,
) -> ToolCallBindingOptions | None:
    if gate.forced and len(gate.allowed_tool_names) == 1:
        return ToolCallBindingOptions(
            tool_choice={"type": "function", "function": {"name": gate.allowed_tool_names[0]}},
            parallel_tool_calls=False,
        )
    return build_round_tool_call_options(max_tool_calls=max_tool_calls)


def _round_tool_call_limit_for_gate(
    *,
    max_tool_calls: int,
    gate: ActionGateDecision,
) -> int:
    base_limit = max(1, int(max_tool_calls or 1))
    if not gate.forced:
        return base_limit
    stage_minimums = {
        "read_material": 4,
        "write_output": 1,
        "verify_output": 2,
    }
    return max(base_limit, int(gate.reserved_tool_calls or 0), stage_minimums.get(gate.stage, 1))


def _round_model_stream_policy_for_gate(
    *,
    model_stream_policy: dict[str, Any] | None,
    gate: ActionGateDecision,
) -> dict[str, Any] | None:
    policy = dict(model_stream_policy or {})
    if not gate.forced:
        return model_stream_policy
    timeout_seconds = _action_gate_timeout_seconds(policy)
    policy["model_response_timeout_seconds"] = timeout_seconds
    policy["non_stream_fallback_timeout_seconds"] = min(
        timeout_seconds,
        _positive_float(policy.get("non_stream_fallback_timeout_seconds"), timeout_seconds),
    )
    policy["stream_recovery_timeout_seconds"] = min(
        timeout_seconds,
        _positive_float(policy.get("stream_recovery_timeout_seconds"), timeout_seconds),
    )
    policy["fallback_timeout_seconds"] = min(
        timeout_seconds,
        _positive_float(policy.get("fallback_timeout_seconds"), timeout_seconds),
    )
    policy["action_gate_forced_stage"] = gate.stage
    policy["action_gate_timeout_applied"] = True
    return policy


def _action_gate_timeout_seconds(policy: dict[str, Any]) -> float:
    configured = _positive_float(policy.get("action_gate_timeout_seconds"), 0.0)
    if configured > 0:
        return configured
    current = _positive_float(policy.get("model_response_timeout_seconds"), 0.0)
    if current > 0:
        return min(current, 45.0)
    return 45.0


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _delivery_tool_call_count(
    tool_calls: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    gate: ActionGateDecision,
) -> int:
    if not gate.forced:
        return len(list(tool_calls or []))
    forced_tools = set(gate.allowed_tool_names)
    return sum(
        1
        for tool_call in list(tool_calls or [])
        if _tool_call_counts_for_gate(tool_call, gate=gate, forced_tools=forced_tools)
    )


def _delivery_budget_remaining(
    tool_calls: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    gate: ActionGateDecision,
    max_tool_calls_per_task_run: int,
) -> int:
    if not gate.forced:
        return max(0, int(max_tool_calls_per_task_run or 0) - len(list(tool_calls or [])))
    reserved = max(1, int(gate.reserved_tool_calls or 1))
    return max(0, reserved - _delivery_tool_call_count(tool_calls, gate=gate))


def _tool_call_budget_exhausted(
    *,
    round_tool_calls: list[dict[str, Any]],
    pending_tool_calls: list[dict[str, Any]],
    requested_tool_name: str,
    gate: ActionGateDecision,
    max_tool_calls: int,
    max_tool_calls_per_task_run: int,
) -> bool:
    if len(round_tool_calls) >= max_tool_calls:
        return True
    if not gate.forced:
        return len(pending_tool_calls) >= max_tool_calls_per_task_run
    if str(requested_tool_name or "").strip() not in set(gate.allowed_tool_names):
        return False
    return _delivery_budget_remaining(
        pending_tool_calls,
        gate=gate,
        max_tool_calls_per_task_run=max_tool_calls_per_task_run,
    ) <= 0


def _tool_call_budget_exhaustion_scope(
    *,
    round_tool_calls: list[dict[str, Any]],
    requested_tool_name: str,
    gate: ActionGateDecision,
    max_tool_calls: int,
) -> str:
    if len(round_tool_calls) >= max_tool_calls:
        return "round"
    if gate.forced and str(requested_tool_name or "").strip() in set(gate.allowed_tool_names):
        return "forced_delivery"
    return "task"


def _tool_call_counts_for_gate(
    tool_call: dict[str, Any],
    *,
    gate: ActionGateDecision,
    forced_tools: set[str],
) -> bool:
    item = dict(tool_call or {})
    name = str(item.get("name") or "").strip()
    if name not in forced_tools:
        return False
    if gate.stage == "write_output":
        if name not in {"write_file", "edit_file"}:
            return False
        target_path = str(gate.target_path or "").strip()
        if not target_path:
            return True
        args = dict(item.get("args") or {})
        candidate_path = str(args.get("path") or "").strip()
        return _paths_match_for_gate(target_path, candidate_path)
    if gate.stage == "read_material":
        if name in {"terminal", "browser_control"}:
            return True
        if name not in {"read_file", "read_structured_file", "search_files", "search_text", "glob_paths", "list_dir", "path_exists", "stat_path"}:
            return False
        target_path = str(gate.target_path or "").strip()
        if not target_path:
            return True
        args = dict(item.get("args") or {})
        candidate_path = str(args.get("path") or args.get("query") or args.get("pattern") or "").strip()
        return _paths_match_for_gate(target_path, candidate_path)
    return True


def _paths_match_for_gate(target_path: str, candidate_path: str) -> bool:
    target = str(target_path or "").strip().strip("/").replace("\\", "/").lower()
    candidate = str(candidate_path or "").strip().strip("/").replace("\\", "/").lower()
    if not target or not candidate:
        return False
    return bool(
        target == candidate
        or target.endswith("/" + candidate)
        or candidate.endswith("/" + target)
    )


def _gate_rejection_instruction(*, gate: ActionGateDecision, requested_tool_name: str) -> str:
    instruction = gate.instruction()
    requested = str(requested_tool_name or "").strip()
    if requested:
        return f"{instruction} 本次请求的 {requested} 不会推进当前强制交付阶段。"
    return instruction


def _action_gate_recovery_messages(
    *,
    user_message: str,
    gate: ActionGateDecision,
    repair_instruction: str,
    stage_summary: dict[str, Any],
    structured_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    assistant_tool_call_content: str,
    assistant_tool_call_kwargs: dict[str, Any],
    round_message_tool_calls: list[dict[str, Any]],
    round_tool_messages: list[ToolMessage],
) -> list[Any]:
    payload = {
        "reason": "forced_action_gate_recovery",
        "action_gate": gate.to_dict(),
        "stage_summary": dict(stage_summary or {}),
        "material_evidence": _action_gate_recovery_material_evidence(structured_observations),
        "repair_instruction": str(repair_instruction or gate.instruction()).strip(),
        "runtime_feedback": _runtime_feedback_payload(
            source="action_gate_recovery",
            action_gate=gate,
            deliverable_progress=None,
            repair_instruction=str(repair_instruction or gate.instruction()).strip(),
        ),
    }
    messages: list[Any] = [
        {
            "role": "system",
            "content": (
                "你是一名正在恢复执行的专业 coding agent。上一轮工具请求没有推进当前强制交付阶段，"
                "但任务没有失败；你需要基于已经取得的真实材料观察继续完成交付。"
            ),
        },
        {"role": "user", "content": str(user_message or "")},
        {
            "role": "system",
            "content": (
                "下面是运行时压缩后的恢复上下文。它保留了任务目标、已读材料摘录、待完成交付物和当前动作门。"
                "不要重新读取已经满足的材料；优先完成当前动作门指定的真实操作。\n"
                "action_gate_recovery_context="
                + json.dumps(payload, ensure_ascii=False, sort_keys=True)
            ),
        },
    ]
    paired_tool_calls = tool_calls_for_langchain_messages(round_message_tool_calls)
    if paired_tool_calls and round_tool_messages:
        messages.extend(
            [
                AIMessage(
                    content=str(assistant_tool_call_content or ""),
                    tool_calls=paired_tool_calls,
                    additional_kwargs=dict(assistant_tool_call_kwargs or {}),
                ),
                *round_tool_messages,
            ]
        )
    messages.append(
        {
            "role": "system",
            "content": (
                f"{gate.instruction()}"
                "下一步必须使用当前可见工具完成该动作门要求；如果当前阶段是写入，就调用写入工具并写到目标路径。"
                "不要把工具调用写成可见文本，不要用总结替代真实操作。"
            ),
        }
    )
    return messages


def _budget_closeout_messages(
    *,
    conversation_messages: list[Any],
    evidence_packet: dict[str, Any],
    tool_observation_ledger: ToolObservationLedger,
    structured_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    goal_contract: ProfessionalTaskGoalContract,
) -> list[Any]:
    latest_observations = [
        dict(item)
        for item in list(structured_observations or [])[-6:]
        if isinstance(item, dict)
    ]
    payload = {
        "reason": "tool_budget_exhausted_model_closeout",
        "evidence_packet": dict(evidence_packet or {}),
        "tool_observation_ledger": tool_observation_ledger.to_dict(),
        "deliverable_progress": _deliverable_progress(goal_contract, tool_observation_ledger).to_dict(),
        "latest_observations": latest_observations,
    }
    return [
        *list(conversation_messages or []),
        {
            "role": "system",
            "content": (
                "工具轮次预算已经用尽，运行时不会再开放工具调用。"
                "下面是已发生的真实工具观察、自动验证结果和证据包。"
                "你只能基于这些真实证据给用户收口；不要发起或描述新的工具调用，"
                "不要输出 DSML、JSON schema 或内部协议文本。\n"
                "budget_closeout_context="
                + json.dumps(payload, ensure_ascii=False, sort_keys=True)
            ),
        },
    ]


def _action_gate_recovery_material_evidence(
    structured_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    evidence_by_path: dict[str, dict[str, Any]] = {}
    for observation in list(structured_observations or []):
        if not isinstance(observation, dict):
            continue
        item = dict(observation)
        tool_name = str(item.get("tool_name") or "").strip()
        if tool_name not in {"read_file", "read_structured_file"}:
            continue
        structured_payload = dict(item.get("structured_payload") or {})
        if str(structured_payload.get("type") or "").strip() == "tool_policy_rejection":
            continue
        envelope = dict(item.get("result_envelope") or {})
        if str(envelope.get("status") or "ok").strip().lower() == "error":
            continue
        tool_args = dict(item.get("tool_args") or envelope.get("tool_args") or {})
        paths = [
            str(tool_args.get("path") or "").strip(),
            *[str(path).strip() for path in list(item.get("observed_paths") or []) if str(path).strip()],
            *[str(path).strip() for path in list(envelope.get("observed_paths") or []) if str(path).strip()],
        ]
        path = next((candidate for candidate in paths if candidate), "")
        if not path:
            continue
        result_text = str(item.get("result") or envelope.get("text") or "")
        normalized_path = path.replace("\\", "/")
        evidence_by_path[normalized_path] = {
            "path": normalized_path,
            "tool_name": tool_name,
            "observation_ref": str(item.get("observation_ref") or ""),
            "excerpt": result_text[:1800],
            "result_chars": len(result_text),
        }
    return list(evidence_by_path.values())[-6:]


def _observation_payload_with_action_gate_intent(
    payload: dict[str, Any],
    *,
    gate: ActionGateDecision,
) -> dict[str, Any]:
    item = dict(payload or {})
    tool_name = str(item.get("tool_name") or "").strip()
    if not gate.forced or gate.stage != "verify_output" or tool_name not in {"terminal", "browser_control"}:
        return item
    verification_intent = {
        "stage": gate.stage,
        "obligation": "verify_command",
        "reason": gate.reason,
        "authority": "professional_runtime.action_gate",
    }
    structured_payload = {
        **dict(item.get("structured_payload") or {}),
        "verification_intent": verification_intent,
    }
    envelope = dict(item.get("result_envelope") or {})
    if envelope:
        envelope["structured_payload"] = {
            **dict(envelope.get("structured_payload") or {}),
            "verification_intent": verification_intent,
        }
        envelope["command_receipt"] = dict(item.get("command_receipt") or envelope.get("command_receipt") or {})
    item["structured_payload"] = structured_payload
    item["result_envelope"] = envelope
    return item


def _auto_verify_output_observation(
    *,
    task_run_id: str,
    directive_ref: str,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    gate: ActionGateDecision,
    sandbox_policy: dict[str, Any] | None,
) -> Any | None:
    if not gate.forced or gate.stage != "verify_output":
        return None
    if tool_observation_ledger.verification_passed():
        return None
    if _requires_agent_supplied_verification(goal_contract):
        return None
    target_path = next(
        (
            str(path).strip().replace("\\", "/")
            for path in list(goal_contract.required_output_paths or [])
            if str(path).strip() and tool_observation_ledger.has_write(str(path).strip())
        ),
        "",
    )
    if not target_path:
        written_paths = _ledger_paths_for_satisfaction(tool_observation_ledger, "write_output")
        target_path = str(written_paths[0] if written_paths else "").strip().replace("\\", "/")
    if not target_path:
        return None
    command = (
        "$p = "
        + _powershell_single_quoted(target_path)
        + "; if (Test-Path -LiteralPath $p -PathType Leaf) { "
        + "Get-Item -LiteralPath $p | Select-Object FullName,Length,LastWriteTime | ConvertTo-Json -Compress; exit 0 "
        + "} else { Write-Error \"missing required output file: $p\"; exit 1 }"
    )
    sandbox = dict(sandbox_policy or {})
    execution_root = Path(str(sandbox.get("sandbox_root") or sandbox.get("workspace_root") or ".")).resolve()
    blocked_reason = validate_sandbox_command_text(command, kind="command")
    if blocked_reason:
        exit_code = 1
        output_preview = blocked_reason
    else:
        settings = get_settings()
        shell_command = build_windows_powershell_command(command) if is_windows() else ["bash", "-lc", command]
        try:
            completed = subprocess.run(
                shell_command,
                cwd=execution_root,
                capture_output=True,
                timeout=settings.terminal_timeout_seconds,
                check=False,
                **utf8_subprocess_text_kwargs(),
            )
            exit_code = int(completed.returncode or 0)
            output_preview = (((completed.stdout or "") + (completed.stderr or "")).strip() or "[no output]")[:5000]
        except subprocess.TimeoutExpired:
            exit_code = 124
            output_preview = f"Timed out after {settings.terminal_timeout_seconds} seconds."
    passed = exit_code == 0
    receipt = {
        "command": command,
        "exit_code": exit_code,
        "passed": passed,
        "output_preview": output_preview,
        "auto_verification": True,
    }
    envelope = {
        "envelope_id": f"tool-result:auto-verify:{task_run_id}",
        "tool_name": "terminal",
        "tool_args": {"command": command},
        "status": "ok" if passed else "error",
        "text": output_preview,
        "structured_payload": {
            "tool_result": {
                "kind": "required_output_file_exists",
                "path": target_path,
                "exists": passed,
            },
            "verification_intent": {
                "stage": gate.stage,
                "obligation": "verify_command",
                "reason": "auto_verify_required_output_file",
                "authority": "professional_runtime.action_gate",
            },
            "command_receipt": receipt,
        },
        "observed_paths": [target_path] if passed else [],
        "matched_paths": [target_path] if passed else [],
        "artifact_refs": [{"path": target_path, "kind": "file", "source": "auto_verify"}] if passed else [],
        "command_receipt": receipt,
        "execution_receipt": {
            "execution_mode": "runtime_auto_verify_terminal",
            "passed": passed,
            "workspace_root": str(execution_root),
        },
        "result_ref": "",
        "error": "" if passed else output_preview,
        "authority": "execution.tool_result_envelope",
    }
    return build_tool_result_observation(
        task_run_id=task_run_id,
        request_ref=f"auto-verify:{task_run_id}:{target_path}",
        directive_ref=directive_ref,
        tool_name="terminal",
        tool_call_id=f"auto-verify:{task_run_id}",
        tool_args={"command": command},
        result=output_preview,
        execution_receipt=dict(envelope.get("execution_receipt") or {}),
        result_envelope=envelope,
    )


def _requires_agent_supplied_verification(goal_contract: ProfessionalTaskGoalContract) -> bool:
    tool_kinds = {
        str(item or "").strip()
        for item in list(goal_contract.required_tool_kinds or [])
        if str(item or "").strip()
    }
    if "verify_command" not in tool_kinds:
        return False
    output_kinds = {
        str(item or "").strip()
        for item in list(goal_contract.required_output_kinds or [])
        if str(item or "").strip()
    }
    return bool(output_kinds.intersection({"change_summary", "changed_files"}))


def _powershell_single_quoted(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _ledger_paths_for_satisfaction(
    tool_observation_ledger: ToolObservationLedger,
    satisfaction: str,
) -> list[str]:
    paths: list[str] = []
    for record in tool_observation_ledger.records:
        if satisfaction not in record.satisfies:
            continue
        paths.extend(str(path).strip() for path in list(record.observed_paths or ()) if str(path).strip())
        paths.extend(str(path).strip() for path in list(record.matched_paths or ()) if str(path).strip())
        paths.extend(
            str(dict(ref).get("path") or "").strip()
            for ref in list(record.artifact_refs or ())
            if str(dict(ref).get("path") or "").strip()
        )
    return _dedupe_strings(paths)


def _structured_observation_entry(
    *,
    observation_ref: str,
    observation_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "observation_ref": observation_ref,
        "tool_name": str(observation_payload.get("tool_name") or ""),
        "tool_args": dict(observation_payload.get("tool_args") or {}),
        "result": observation_payload.get("result"),
        "result_envelope": dict(observation_payload.get("result_envelope") or {}),
        "structured_payload": dict(observation_payload.get("structured_payload") or {}),
        "observed_paths": list(observation_payload.get("observed_paths") or []),
        "matched_paths": list(observation_payload.get("matched_paths") or []),
        "artifact_refs": [
            dict(item)
            for item in list(observation_payload.get("artifact_refs") or [])
            if isinstance(item, dict)
        ],
        "command_receipt": dict(observation_payload.get("command_receipt") or {}),
    }


def _agent_plan_items_from_draft(
    *,
    agent_plan_draft: dict[str, Any],
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
) -> list[dict[str, Any]]:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "general").strip()
    plan: list[dict[str, Any]] = []
    for index, raw in enumerate(list(agent_plan_draft.get("steps") or []), start=1):
        if not isinstance(raw, dict):
            continue
        step_id = str(raw.get("step_id") or f"agent_step_{index}").strip()
        title = str(raw.get("title") or step_id).strip()
        purpose = str(raw.get("purpose") or "").strip()
        required_operations = [
            str(item).strip()
            for item in list(raw.get("required_operations") or [])
            if str(item).strip()
        ]
        plan.append(
            {
                "plan_item_id": step_id,
                "step_id": step_id,
                "title": title,
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": purpose or title,
                "required_operations": required_operations or ["op.model_response"],
                "contract_refs": [
                    str(item).strip()
                    for item in list(raw.get("contract_refs") or [])
                    if str(item).strip()
                ],
                "evidence_expectations": [
                    str(item).strip()
                    for item in list(raw.get("evidence_expectations") or [])
                    if str(item).strip()
                ],
                "source": "model_agent_plan_draft",
                "contract_required": True,
            }
        )
    if not plan:
        return []
    plan.append(
        {
            "plan_item_id": "professional.validate_deliverable",
            "title": "按交付物验证最终回答",
            "step_kind": "plan_item",
            "executor_type": "model",
            "action_kind": "main_agent",
            "summary": f"检查 {task_goal_type} 的交付物、证据对齐、协议泄漏和未支持声明。",
            "required_operations": ["op.model_response"],
            "response_must_include": list(goal_contract.response_must_include),
            "source": "system_validation_gate",
            "contract_required": True,
        }
    )
    return plan


def _blocked_plan_final_content(
    *,
    semantic_contract: dict[str, Any],
    plan_coverage_review: dict[str, Any],
) -> str:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "general").strip()
    missing_actions = [
        str(item).strip()
        for item in list(plan_coverage_review.get("missing_actions") or [])
        if str(item).strip()
    ]
    missing_deliverables = [
        str(item).strip()
        for item in list(plan_coverage_review.get("missing_deliverables") or [])
        if str(item).strip()
    ]
    reason = str(plan_coverage_review.get("required_replan_reason") or "agent_plan_required").strip()
    details = []
    if missing_actions:
        details.append("缺少动作覆盖：" + "、".join(missing_actions))
    if missing_deliverables:
        details.append("缺少交付物覆盖：" + "、".join(missing_deliverables))
    detail_text = "；".join(details) if details else reason
    return (
        f"当前 {task_goal_type} 任务还不能进入执行：需要先由 agent 提交可校验的执行计划。"
        f"计划覆盖审查未通过，{detail_text}。"
    )


@dataclass(slots=True)
class ProfessionalTaskRunOutcome:
    ledger: TaskRunLedger | None
    state: RuntimeLoopState
    result_refs: list[str] = field(default_factory=list)
    final_content: str = ""
    final_answer_metadata: dict[str, Any] = field(default_factory=dict)
    run_outcome: dict[str, Any] = field(default_factory=dict)
    terminal_reason: str = "completed"
    turn_count: int = 0
    model_call_count: int = 0
    main_context: dict[str, Any] = field(default_factory=dict)
    task_summary_refs: list[dict[str, Any]] = field(default_factory=list)
    bundle_summary_refs: list[dict[str, Any]] = field(default_factory=list)

class ProfessionalTaskRunDriver:
    """Runtime driver for graphless interaction-mode task execution.

    The driver owns professional task control states, while TaskRunLoop still owns
    the shared event log, checkpoints, ledger, TaskResult, and commit gates.
    """

    def __init__(
        self,
        *,
        workspace_root: Path,
        event_log: Any,
        execution_engine: Any,
        record_task_run_step_event: RuntimeEventBuilder,
        record_task_run_ledger_updated: RuntimeEventBuilder,
        state_with_task_run_ledger: StateWithLedger,
        write_checkpoint_event: Callable[..., Any],
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.event_log = event_log
        self.execution_engine = execution_engine
        self.record_task_run_step_event = record_task_run_step_event
        self.record_task_run_ledger_updated = record_task_run_ledger_updated
        self.state_with_task_run_ledger = state_with_task_run_ledger
        self.write_checkpoint_event = write_checkpoint_event
        self._ledger_transition_events: list[Any] = []

    async def run_stream(
        self,
        *,
        outcome: ProfessionalTaskRunOutcome,
        user_message: str,
        task_id: str,
        task_operation: dict[str, Any],
        task_contract_ref: str,
        selected_recipe_payload: dict[str, Any],
        context_snapshot: Any,
        directive: RuntimeDirective,
        resource_policy: Any,
        model_response_executor: Any,
        runtime_context_manager: Any,
        model_stream_policy: dict[str, Any] | None = None,
        resolved_model_spec: Any | None = None,
        tool_runtime_executor: Any | None = None,
        runtime_tool_instances: list[Any] | None = None,
        allowed_search_sources: set[str] | None = None,
        sandbox_policy: dict[str, Any] | None = None,
        file_management_policy: dict[str, Any] | None = None,
    ):
        task_run_id = outcome.state.task_run_id
        policy = _professional_runtime_policy(selected_recipe_payload)
        mode_policy = dict(policy.get("mode_policy") or {})
        semantic_contract = dict(policy.get("task_requirement_contract") or {})
        execution_obligation = dict(semantic_contract.get("execution_obligation") or policy.get("execution_obligation") or {})
        interaction_mode = str(
            mode_policy.get("interaction_mode")
            or policy.get("interaction_mode")
            or "professional_mode"
        ).strip()
        run_state = initial_professional_run_state(task_run_id)
        tool_observation_ledger = ToolObservationLedger(
            ledger_id=f"tool-observation-ledger:{task_run_id}",
            task_run_id=task_run_id,
        )
        tool_policy = dict(policy.get("tool_execution_policy") or {})
        delegation_policy = dict(policy.get("delegation_policy") or {})
        verification_policy = dict(policy.get("verification_policy") or {})
        delegation_enabled = bool(delegation_policy.get("enabled") is True)
        allowed_tool_names = _allowed_tool_names_from_policy(
            tool_policy,
            runtime_tool_instances=runtime_tool_instances,
            delegation_enabled=delegation_enabled,
        )
        allowed_tool_names = _filter_tool_names_by_capability_table(
            allowed_tool_names=allowed_tool_names,
            task_operation=task_operation,
        )
        tool_execution_enabled = bool(tool_policy.get("enabled") is True) and bool(
            tool_runtime_executor is not None and allowed_tool_names
        )
        if interaction_mode == "role_mode":
            delegation_enabled = False
            side_effect_tools = {"write_file", "edit_file", "terminal", "python_repl", "delegate_to_agent"}
            allowed_tool_names = [name for name in allowed_tool_names if name not in side_effect_tools]
            tool_execution_enabled = bool(tool_policy.get("enabled") is True) and bool(
                tool_runtime_executor is not None and allowed_tool_names
            )
        model_tool_instances = (
            [
                tool
                for tool in list(runtime_tool_instances or [])
                if str(getattr(tool, "name", "") or "").strip() in set(allowed_tool_names)
            ]
            if tool_execution_enabled
            else []
        )
        max_tool_calls = max(1, int(tool_policy.get("max_tool_calls_per_round") or 1))
        max_tool_calls_per_task_run = max(
            max_tool_calls,
            int(tool_policy.get("max_tool_calls_per_task_run") or max_tool_calls),
        )
        max_tool_rounds = max(1, int(tool_policy.get("max_tool_rounds_per_task_run") or 1))
        max_delegate_calls = max(0, int(delegation_policy.get("max_delegate_calls_per_task_run") or 0))
        goal_contract = _goal_contract_from_semantic_contract(
            task_run_id=task_run_id,
            user_message=user_message,
            semantic_contract=semantic_contract,
        )
        allowed_tool_names = _tools_with_goal_contract_requirements(
            allowed_tool_names=allowed_tool_names,
            tool_policy=tool_policy,
            goal_contract=goal_contract,
            runtime_tool_instances=runtime_tool_instances,
            tool_runtime_executor=tool_runtime_executor,
        )
        allowed_tool_names = _filter_tool_names_by_capability_table(
            allowed_tool_names=allowed_tool_names,
            task_operation=task_operation,
        )
        tool_execution_enabled = bool(tool_policy.get("enabled") is True) and bool(
            tool_runtime_executor is not None and allowed_tool_names
        )
        model_tool_instances = _runtime_tool_instances_for_allowed_tools(
            runtime_tool_instances=runtime_tool_instances,
            tool_runtime_executor=tool_runtime_executor,
            allowed_tool_names=allowed_tool_names,
            tool_execution_enabled=tool_execution_enabled,
        )
        runtime_environment = RuntimeEnvironment(workspace_root=self.workspace_root)
        runtime_environment_snapshot = runtime_environment.snapshot()
        runtime_environment_health = check_runtime_connection_health(runtime_environment)
        recipe_metadata = dict(dict(selected_recipe_payload or {}).get("metadata") or {})
        agent_plan_draft = dict(recipe_metadata.get("agent_plan_draft") or {})
        plan_coverage_review = dict(recipe_metadata.get("plan_coverage_review") or {})
        plan = _agent_plan_items_from_draft(
            agent_plan_draft=agent_plan_draft,
            semantic_contract=semantic_contract,
            goal_contract=goal_contract,
        )
        plan_gate_required = interaction_mode == "professional_mode"
        plan_coverage_passed = bool(plan_coverage_review.get("passed") is True) if plan_gate_required else True
        planner_event = self.event_log.append(
            task_run_id,
            "professional_task_model_plan_bound",
            payload={
                "interaction_mode": interaction_mode,
                "agent_plan_draft": agent_plan_draft,
                "plan_coverage_review": plan_coverage_review,
                "plan_item_count": len(plan),
                "authority": "professional_runtime.main_model_plan_binding",
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": planner_event.to_dict()}
        start_event = self.event_log.append(
            task_run_id,
            "professional_task_started",
            payload={
                "interaction_mode": interaction_mode,
                "runtime_driver": "professional_task_run",
                "goal": user_message,
                "task_requirement_contract": semantic_contract,
                "execution_obligation": execution_obligation,
                "goal_contract": goal_contract.to_dict(),
                "plan_item_count": len(plan),
                "policy": policy,
                "runtime_environment": runtime_environment_snapshot,
                "runtime_environment_health": runtime_environment_health.to_dict(),
                "professional_run_state": run_state.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": start_event.to_dict()}
        run_state = run_state.advance("mode_policy_bound", reason="mode_policy_bound")
        state_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={
                "from_state": "initialized",
                "to_state": "mode_policy_bound",
                "interaction_mode": interaction_mode,
                "professional_run_state": run_state.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": state_event.to_dict()}
        initial_deliverable_progress = _deliverable_progress(goal_contract, tool_observation_ledger)
        run_state = run_state.advance(
            "obligation_bound",
            reason="execution_obligation_bound",
            unsatisfied_obligations=initial_deliverable_progress.missing_obligations(),
            diagnostics={
                "execution_obligation": execution_obligation,
                **_queue_diagnostics(initial_deliverable_progress),
            },
        )
        obligation_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={
                "from_state": "mode_policy_bound",
                "to_state": "obligation_bound",
                "interaction_mode": interaction_mode,
                "professional_run_state": run_state.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": obligation_event.to_dict()}
        run_state = run_state.advance(
            "prototype_bound",
            reason="strategy_prototype_bound",
            diagnostics={"strategy_prototype_id": str(semantic_contract.get("strategy_prototype_id") or "")},
        )
        prototype_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={
                "from_state": "obligation_bound",
                "to_state": "prototype_bound",
                "interaction_mode": interaction_mode,
                "professional_run_state": run_state.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": prototype_event.to_dict()}
        outcome.state, outcome.ledger = self._complete_current_and_advance(
            state=outcome.state,
            ledger=outcome.ledger,
            reason="professional_task_mode_policy_bound",
            refs={"task_contract_ref": task_contract_ref},
            diagnostics={
                "professional_state": "mode_policy_bound",
                "interaction_mode": interaction_mode,
                "semantic_task_type": str(semantic_contract.get("task_goal_type") or ""),
            },
        )
        for event in self._ledger_transition_events:
            yield {"type": "runtime_loop_event", "event": event.to_dict()}

        if outcome.ledger is not None:
            before_step_ids = {item.step_id for item in outcome.ledger.step_runs}
            final_step_id = _first_finalize_step_id(outcome.ledger)
            for item in plan:
                outcome.ledger = append_plan_item_step(
                    outcome.ledger,
                    plan_item=item,
                    before_step_id=final_step_id,
                    diagnostics={
                        "transition_reason": "professional_task_semantic_plan_drafted",
                        "interaction_mode": interaction_mode,
                    },
                )
            added_steps = [
                item for item in outcome.ledger.step_runs if item.step_id not in before_step_ids
            ]
            for step in added_steps:
                step_event = self.record_task_run_step_event(
                    outcome.state.task_run_id,
                    event_type="step_added",
                    step_run=step,
                    ledger=outcome.ledger,
                    reason="professional_task_semantic_plan_drafted",
                    refs={"task_contract_ref": task_contract_ref},
                    diagnostics={"interaction_mode": interaction_mode},
                )
                yield {"type": "runtime_loop_event", "event": step_event.to_dict()}
            ledger_event = self.record_task_run_ledger_updated(
                outcome.state.task_run_id,
                ledger=outcome.ledger,
                reason="professional_task_semantic_plan_drafted",
                refs={"task_contract_ref": task_contract_ref},
                diagnostics={"interaction_mode": interaction_mode, "dynamic_plan_step_count": len(added_steps)},
            )
            yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
            outcome.state = self.state_with_task_run_ledger(
                outcome.state,
                outcome.ledger,
                diagnostics={
                    "last_step_transition": "professional_task_semantic_plan_drafted",
                    "interaction_mode": interaction_mode,
                },
            )
            checkpoint_event = self.write_checkpoint_event(outcome.state, event_offset=ledger_event.offset)
            yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}

        plan_event = self.event_log.append(
            task_run_id,
            "professional_task_semantic_plan_drafted",
            payload={
                "interaction_mode": interaction_mode,
                "plan_items": plan,
                "delegation_enabled": delegation_enabled,
                "max_delegate_calls_per_task_run": max_delegate_calls,
                "tool_execution_enabled": tool_execution_enabled,
                "allowed_tool_names": allowed_tool_names,
                "max_tool_calls_per_round": max_tool_calls,
                "max_tool_calls_per_task_run": max_tool_calls_per_task_run,
                "max_tool_rounds_per_task_run": max_tool_rounds,
                "plan_source": (
                    "model_agent_plan_draft"
                    if str(agent_plan_draft.get("source") or "") == "model_agent_plan_draft"
                    else "agent_plan_required"
                ),
                "agent_plan_draft": agent_plan_draft,
                "plan_coverage_review": plan_coverage_review,
                "goal_contract": goal_contract.to_dict(),
                "ledger_backed": outcome.ledger is not None,
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": plan_event.to_dict()}
        run_state = run_state.advance(
            "plan_drafted",
            reason="agent_plan_validated" if plan_coverage_passed else "agent_plan_required",
            diagnostics={
                "plan_item_count": len(plan),
                "plan_coverage_passed": plan_coverage_passed,
                "plan_coverage_gate_status": str(plan_coverage_review.get("gate_status") or ""),
            },
        )
        state_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={
                "from_state": "prototype_bound",
                "to_state": "plan_drafted",
                "interaction_mode": interaction_mode,
                "professional_run_state": run_state.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": state_event.to_dict()}

        if not plan_coverage_passed:
            blocked_event = self.event_log.append(
                task_run_id,
                "professional_task_plan_blocked",
                payload={
                    "interaction_mode": interaction_mode,
                    "agent_plan_draft": agent_plan_draft,
                    "plan_coverage_review": plan_coverage_review,
                    "terminal_reason": "agent_plan_required",
                    "authority": "professional_runtime.plan_coverage_gate",
                },
                refs={"task_contract_ref": task_contract_ref},
            )
            yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
            outcome.final_content = _blocked_plan_final_content(
                semantic_contract=semantic_contract,
                plan_coverage_review=plan_coverage_review,
            )
            outcome.terminal_reason = "agent_plan_required"
            outcome.final_answer_metadata = {
                **dict(outcome.final_answer_metadata or {}),
                "answer_channel": "plan_required",
                "answer_source": "professional_runtime.plan_coverage_gate",
                "plan_coverage_review": plan_coverage_review,
            }
            return

        outcome.state, outcome.ledger = self._prepare_standard_action_step(
            state=outcome.state,
            ledger=outcome.ledger,
            plan=plan,
            task_contract_ref=task_contract_ref,
            interaction_mode=interaction_mode,
        )
        for event in self._ledger_transition_events:
            yield {"type": "runtime_loop_event", "event": event.to_dict()}
        run_state = run_state.advance(
            "action_dispatched",
            reason="action_dispatched",
            unsatisfied_obligations=_deliverable_progress(goal_contract, tool_observation_ledger).missing_obligations(),
            diagnostics={
                "tool_execution_enabled": tool_execution_enabled,
                **_queue_diagnostics(_deliverable_progress(goal_contract, tool_observation_ledger)),
            },
        )
        action_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={
                "from_state": "plan_drafted",
                "to_state": "action_dispatched",
                "interaction_mode": interaction_mode,
                "professional_run_state": run_state.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": action_event.to_dict()}
        executor_event = self.event_log.append(
            task_run_id,
            "executor_started",
            payload={
                "executor_type": "model",
                "runtime_channel": "professional_task_run",
                "interaction_mode": interaction_mode,
                "tool_execution_enabled": tool_execution_enabled,
                "allowed_tool_names": allowed_tool_names,
                "delegation_enabled": delegation_enabled,
                "max_delegate_calls_per_task_run": max_delegate_calls,
            },
            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
        )
        yield {"type": "runtime_loop_event", "event": executor_event.to_dict()}

        safe_directive = _professional_task_directive(
            directive,
            mode=interaction_mode,
            tool_execution_enabled=tool_execution_enabled,
            delegation_enabled=delegation_enabled,
            allowed_tool_operation_refs=list(tool_policy.get("allowed_operation_refs") or ()),
            max_tool_rounds=max_tool_rounds,
        )
        model_messages = _with_professional_task_instruction(
            list(getattr(context_snapshot, "model_messages", ()) or ()),
            mode=interaction_mode,
            plan_items=plan,
            plan_coverage_review=plan_coverage_review,
            tool_execution_enabled=tool_execution_enabled,
            delegation_enabled=delegation_enabled,
            allowed_tool_names=allowed_tool_names,
            max_tool_calls=max_tool_calls,
            max_tool_calls_per_task_run=max_tool_calls_per_task_run,
            max_tool_rounds=max_tool_rounds,
            max_delegate_calls=max_delegate_calls,
            goal_contract=goal_contract,
            semantic_contract=semantic_contract,
            mode_policy=mode_policy,
            sandbox_policy=sandbox_policy,
        )
        write_output_required = bool(goal_contract.requires_write_output)
        pending_tool_calls: list[dict[str, Any]] = []
        tool_messages: list[ToolMessage] = []
        tool_observation_count = 0
        delegation_observation_count = 0
        write_observation_count = 0
        tool_call_budget_exceeded = False
        action_observation_refs: list[str] = []
        structured_observations: list[dict[str, Any]] = []
        action_step_completed = False
        forced_verify_round_count = 0
        conversation_messages: list[Any] = list(model_messages)
        while outcome.terminal_reason == "completed":
            round_index = int(outcome.turn_count or 0) + 1
            if round_index > max_tool_rounds:
                budget_gate = decide_next_action_gate(
                    goal_contract=goal_contract,
                    tool_observation_ledger=tool_observation_ledger,
                    allowed_tool_names=allowed_tool_names,
                )
                auto_verify_observation = _auto_verify_output_observation(
                    task_run_id=task_run_id,
                    directive_ref=directive.directive_id,
                    goal_contract=goal_contract,
                    tool_observation_ledger=tool_observation_ledger,
                    gate=budget_gate,
                    sandbox_policy=sandbox_policy,
                )
                if auto_verify_observation is not None:
                    context_record = runtime_context_manager.record_observation(auto_verify_observation)
                    auto_refs = {
                        "task_contract_ref": task_contract_ref,
                        "directive_ref": directive.directive_id,
                        "tool_policy": "action_gate_auto_verify_budget_closeout",
                    }
                    result_event = append_tool_result_received_event(
                        event_log=self.event_log,
                        task_run_id=task_run_id,
                        observation=auto_verify_observation,
                        context_record=context_record,
                        refs=auto_refs,
                    )
                    observation_event = append_executor_observation_event(
                        event_log=self.event_log,
                        task_run_id=task_run_id,
                        observation=auto_verify_observation,
                        context_record=context_record,
                        refs=auto_refs,
                    )
                    observation_payload = _observation_payload_with_action_gate_intent(
                        dict(auto_verify_observation.payload or {}),
                        gate=budget_gate,
                    )
                    tool_observation_count += 1
                    observation_ref = auto_verify_observation.observation_id
                    action_observation_refs.append(observation_ref)
                    structured_observations.append(
                        _structured_observation_entry(
                            observation_ref=observation_ref,
                            observation_payload=observation_payload,
                        )
                    )
                    tool_observation_ledger = tool_observation_ledger.append(
                        build_tool_observation_record(
                            observation_ref=observation_ref,
                            tool_name="terminal",
                            tool_args=dict(observation_payload.get("tool_args") or {}),
                            result=observation_payload,
                        )
                    )
                    tool_observation_count = max(tool_observation_count, len(structured_observations))
                    conversation_messages.append(
                        {
                            "role": "system",
                            "content": (
                                "运行时已完成一次系统级输出文件验证。该观察来自系统动作门，"
                                "不是你发起的新工具调用；你可以把它作为真实证据使用。\n"
                                "runtime_observation="
                                + json.dumps(observation_payload, ensure_ascii=False, sort_keys=True)
                            ),
                        }
                    )
                    yield {"type": "runtime_loop_event", "event": result_event.to_dict()}
                    yield {"type": "runtime_loop_event", "event": observation_event.to_dict()}
                    if tool_observation_ledger.verification_passed():
                        tool_call_budget_exceeded = True
                        break
                tool_call_budget_exceeded = True
                budget_event = self.event_log.append(
                    task_run_id,
                    "loop_error",
                    payload={
                        "error": "professional_task_tool_round_budget_exceeded",
                        "message": "专业任务工具观察轮次已达上限，停止继续请求工具。",
                        "max_tool_rounds_per_task_run": max_tool_rounds,
                        "action_gate": budget_gate.to_dict(),
                    },
                    refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                )
                yield {"type": "runtime_loop_event", "event": budget_event.to_dict()}
                break
            outcome.turn_count = round_index
            outcome.model_call_count += 1
            round_tool_calls: list[dict[str, Any]] = []
            round_message_tool_calls: list[dict[str, Any]] = []
            round_tool_messages: list[ToolMessage] = []
            protocol_violation_repair_requested = False
            model_timeout_recovery_requested = False
            round_protocol_leak_detected = False
            action_gate_recovery_context_rebuilt = False
            assistant_tool_call_content = ""
            assistant_tool_call_kwargs: dict[str, Any] = {}
            action_gate = decide_next_action_gate(
                goal_contract=goal_contract,
                tool_observation_ledger=tool_observation_ledger,
                allowed_tool_names=allowed_tool_names,
            )
            if round_index > 1:
                followup_event = self.event_log.append(
                    task_run_id,
                    "loop_iteration_started",
                    payload={
                        "transition": "professional_task_continue_after_tool_result",
                        "turn_count": round_index,
                        "tool_call_count": len(pending_tool_calls),
                        "delivery_tool_call_count": _delivery_tool_call_count(pending_tool_calls, gate=action_gate),
                        "tool_observation_count": tool_observation_count,
                        "delegation_observation_count": delegation_observation_count,
                        "action_gate": action_gate.to_dict(),
                    },
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": followup_event.to_dict()}
            deliverable_progress = _deliverable_progress(goal_contract, tool_observation_ledger)
            round_tool_call_limit = _round_tool_call_limit_for_gate(
                max_tool_calls=max_tool_calls,
                gate=action_gate,
            )
            round_model_tool_instances = _round_tool_instances_for_gate(
                model_tool_instances=model_tool_instances,
                gate=action_gate,
            )
            round_tool_call_options = (
                _round_tool_call_options_for_gate(
                    max_tool_calls=round_tool_call_limit,
                    gate=action_gate,
                )
                if round_model_tool_instances
                else None
            )
            round_model_stream_policy = _round_model_stream_policy_for_gate(
                model_stream_policy=model_stream_policy,
                gate=action_gate,
            )
            if action_gate.forced:
                if action_gate.stage == "verify_output":
                    forced_verify_round_count += 1
                gate_event = self.event_log.append(
                    task_run_id,
                    "professional_task_action_gate_applied",
                    payload={
                        "action_gate": action_gate.to_dict(),
                        "visible_tool_names": [
                            str(getattr(tool, "name", "") or "").strip()
                            for tool in round_model_tool_instances
                            if str(getattr(tool, "name", "") or "").strip()
                        ],
                        "tool_call_options": (
                            round_tool_call_options.bind_kwargs()
                            if hasattr(round_tool_call_options, "bind_kwargs")
                            else {}
                        ),
                        "effective_max_tool_calls_per_round": round_tool_call_limit,
                        "model_stream_policy": dict(round_model_stream_policy or {}),
                    },
                    refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                )
                yield {"type": "runtime_loop_event", "event": gate_event.to_dict()}
                auto_verify_observation = _auto_verify_output_observation(
                    task_run_id=task_run_id,
                    directive_ref=directive.directive_id,
                    goal_contract=goal_contract,
                    tool_observation_ledger=tool_observation_ledger,
                    gate=action_gate,
                    sandbox_policy=sandbox_policy,
                )
                if forced_verify_round_count <= 1:
                    auto_verify_observation = None
                if auto_verify_observation is not None:
                    context_record = runtime_context_manager.record_observation(auto_verify_observation)
                    auto_refs = {
                        "task_contract_ref": task_contract_ref,
                        "directive_ref": directive.directive_id,
                        "tool_policy": "action_gate_auto_verify",
                    }
                    result_event = append_tool_result_received_event(
                        event_log=self.event_log,
                        task_run_id=task_run_id,
                        observation=auto_verify_observation,
                        context_record=context_record,
                        refs=auto_refs,
                    )
                    observation_event = append_executor_observation_event(
                        event_log=self.event_log,
                        task_run_id=task_run_id,
                        observation=auto_verify_observation,
                        context_record=context_record,
                        refs=auto_refs,
                    )
                    observation_payload = _observation_payload_with_action_gate_intent(
                        dict(auto_verify_observation.payload or {}),
                        gate=action_gate,
                    )
                    tool_observation_count += 1
                    observation_ref = auto_verify_observation.observation_id
                    action_observation_refs.append(observation_ref)
                    structured_observations.append(
                        _structured_observation_entry(
                            observation_ref=observation_ref,
                            observation_payload=observation_payload,
                        )
                    )
                    tool_observation_ledger = tool_observation_ledger.append(
                        build_tool_observation_record(
                            observation_ref=observation_ref,
                            tool_name="terminal",
                            tool_args=dict(observation_payload.get("tool_args") or {}),
                            result=observation_payload,
                        )
                    )
                    round_tool_messages.append(
                        ToolMessage(
                            content=str(observation_payload.get("result") or ""),
                            tool_call_id=str(observation_payload.get("tool_call_id") or f"auto-verify:{task_run_id}"),
                        )
                    )
                    yield {"type": "runtime_loop_event", "event": result_event.to_dict()}
                    yield {"type": "runtime_loop_event", "event": observation_event.to_dict()}
                    continue
            async for event in self.execution_engine.stream_raw_model_events(
                user_message=user_message,
                model_response_executor=model_response_executor,
                model_messages=conversation_messages,
                directive=safe_directive,
                tool_instances=round_model_tool_instances,
                tool_call_options=round_tool_call_options,
                model_stream_policy=round_model_stream_policy,
                model_spec=resolved_model_spec,
            ):
                event_type = str(event.get("type") or "")
                if _event_protocol_leak_detected(event):
                    round_protocol_leak_detected = True
                if event_type == "tool_call_requested":
                    requested_tool_name = str(event.get("tool_name") or dict(event.get("tool_call") or {}).get("name") or "")
                    blocked_tool_call = dict(event.get("tool_call") or {})
                    if action_gate.forced and not _tool_call_counts_for_gate(
                        blocked_tool_call,
                        gate=action_gate,
                        forced_tools=set(action_gate.allowed_tool_names),
                    ):
                        repair_text = _gate_rejection_instruction(
                            gate=action_gate,
                            requested_tool_name=requested_tool_name,
                        )
                        rejection_observation = build_policy_rejection_observation(
                            task_run_id=task_run_id,
                            request_ref=str(blocked_tool_call.get("id") or f"action-gate:{task_run_id}:{round_index}"),
                            directive_ref=directive.directive_id,
                            tool_name=requested_tool_name,
                            tool_call_id=str(blocked_tool_call.get("id") or requested_tool_name),
                            tool_args=dict(blocked_tool_call.get("args") or {}),
                            policy="action_gate",
                            reason=action_gate.reason,
                            repair_instruction=repair_text,
                            diagnostics={
                                "action_gate": action_gate.to_dict(),
                                "deliverable_progress": deliverable_progress.to_dict(),
                                "runtime_feedback": _runtime_feedback_payload(
                                    source="action_gate",
                                    requested_tool_name=requested_tool_name,
                                    action_gate=action_gate,
                                    deliverable_progress=deliverable_progress,
                                    repair_instruction=repair_text,
                                ),
                            },
                        )
                        context_record = runtime_context_manager.record_observation(rejection_observation)
                        rejection_refs = {
                            "task_contract_ref": task_contract_ref,
                            "directive_ref": directive.directive_id,
                            "tool_policy": "action_gate",
                        }
                        result_event = append_tool_result_received_event(
                            event_log=self.event_log,
                            task_run_id=task_run_id,
                            observation=rejection_observation,
                            context_record=context_record,
                            refs=rejection_refs,
                        )
                        observation_event = append_executor_observation_event(
                            event_log=self.event_log,
                            task_run_id=task_run_id,
                            observation=rejection_observation,
                            context_record=context_record,
                            refs=rejection_refs,
                        )
                        assistant_tool_call_content = str(event.get("assistant_content") or assistant_tool_call_content)
                        event_kwargs = dict(event.get("assistant_additional_kwargs") or {})
                        if event_kwargs:
                            assistant_tool_call_kwargs.update(event_kwargs)
                        rejection_payload = dict(rejection_observation.payload or {})
                        rejection_ref = rejection_observation.observation_id
                        tool_observation_count += 1
                        action_observation_refs.append(rejection_ref)
                        structured_observations.append(
                            {
                                "observation_ref": rejection_ref,
                                "tool_name": str(rejection_payload.get("tool_name") or ""),
                                "tool_args": dict(rejection_payload.get("tool_args") or {}),
                                "result": rejection_payload.get("result"),
                                "result_envelope": dict(rejection_payload.get("result_envelope") or {}),
                                "structured_payload": dict(rejection_payload.get("structured_payload") or {}),
                                "observed_paths": list(rejection_payload.get("observed_paths") or []),
                                "matched_paths": list(rejection_payload.get("matched_paths") or []),
                                "artifact_refs": [
                                    dict(item)
                                    for item in list(rejection_payload.get("artifact_refs") or [])
                                    if isinstance(item, dict)
                                ],
                                "command_receipt": dict(rejection_payload.get("command_receipt") or {}),
                            }
                        )
                        tool_observation_ledger = tool_observation_ledger.append(
                            build_tool_observation_record(
                                observation_ref=rejection_ref,
                                tool_name=str(rejection_payload.get("tool_name") or requested_tool_name),
                                tool_args=dict(rejection_payload.get("tool_args") or {}),
                                result=rejection_payload,
                            )
                        )
                        if blocked_tool_call:
                            round_message_tool_calls.append(blocked_tool_call)
                        rejection_tool_message = ToolMessage(
                            content=str(rejection_payload.get("result") or repair_text),
                            tool_call_id=str(
                                rejection_payload.get("tool_call_id")
                                or blocked_tool_call.get("id")
                                or getattr(event, "event_id", "")
                                or requested_tool_name
                            ),
                        )
                        round_tool_messages.append(rejection_tool_message)
                        tool_messages.append(rejection_tool_message)
                        blocked_event = self.event_log.append(
                            task_run_id,
                            "tool_call_blocked_by_action_gate",
                            payload={
                                "tool_name": requested_tool_name,
                                "action_gate": action_gate.to_dict(),
                                "deliverable_progress": deliverable_progress.to_dict(),
                                "runtime_feedback": _runtime_feedback_payload(
                                    source="action_gate",
                                    requested_tool_name=requested_tool_name,
                                    action_gate=action_gate,
                                    deliverable_progress=deliverable_progress,
                                    repair_instruction=repair_text,
                                ),
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
                        yield {"type": "runtime_loop_event", "event": result_event.to_dict()}
                        yield {"type": "runtime_loop_event", "event": observation_event.to_dict()}
                        stage_summary = build_stage_summary(
                            task_run_id=task_run_id,
                            turn_count=outcome.turn_count,
                            tool_call_count=len(pending_tool_calls),
                            tool_observation_count=tool_observation_count,
                            tool_observation_ledger=tool_observation_ledger,
                            deliverable_progress=_deliverable_progress(goal_contract, tool_observation_ledger),
                            structured_observations=structured_observations,
                            environment_snapshot=runtime_environment_snapshot,
                        )
                        conversation_messages = _action_gate_recovery_messages(
                            user_message=user_message,
                            gate=action_gate,
                            repair_instruction=repair_text,
                            stage_summary=stage_summary.to_dict(),
                            structured_observations=structured_observations,
                            assistant_tool_call_content=assistant_tool_call_content,
                            assistant_tool_call_kwargs=assistant_tool_call_kwargs,
                            round_message_tool_calls=round_message_tool_calls,
                            round_tool_messages=round_tool_messages,
                        )
                        action_gate_recovery_context_rebuilt = True
                        continue
                    progress_decision = check_progress_policy(
                        goal_contract=goal_contract,
                        ledger=tool_observation_ledger,
                        requested_tool_name=requested_tool_name,
                        requested_tool_args=dict(dict(event.get("tool_call") or {}).get("args") or {}),
                        recent_observations=structured_observations,
                    )
                    if not progress_decision.allowed:
                        blocked_tool_call = dict(event.get("tool_call") or {})
                        repair_payload = dict(progress_decision.repair_observation or {})
                        repair_text = str(repair_payload.get("repair_instruction") or progress_decision.reason)
                        rejection_observation = build_policy_rejection_observation(
                            task_run_id=task_run_id,
                            request_ref=str(blocked_tool_call.get("id") or f"progress-policy:{task_run_id}:{round_index}"),
                            directive_ref=directive.directive_id,
                            tool_name=requested_tool_name,
                            tool_call_id=str(blocked_tool_call.get("id") or requested_tool_name),
                            tool_args=dict(blocked_tool_call.get("args") or {}),
                            policy="progress_policy",
                            reason=progress_decision.reason,
                            repair_instruction=repair_text,
                            diagnostics={
                                "progress_policy": progress_decision.to_dict(),
                                "deliverable_progress": deliverable_progress.to_dict(),
                                "runtime_feedback": _runtime_feedback_payload(
                                    source="progress_policy",
                                    requested_tool_name=requested_tool_name,
                                    action_gate=action_gate,
                                    deliverable_progress=deliverable_progress,
                                    repair_instruction=repair_text,
                                ),
                            },
                        )
                        context_record = runtime_context_manager.record_observation(rejection_observation)
                        rejection_refs = {
                            "task_contract_ref": task_contract_ref,
                            "directive_ref": directive.directive_id,
                            "tool_policy": "progress_policy",
                        }
                        result_event = append_tool_result_received_event(
                            event_log=self.event_log,
                            task_run_id=task_run_id,
                            observation=rejection_observation,
                            context_record=context_record,
                            refs=rejection_refs,
                        )
                        observation_event = append_executor_observation_event(
                            event_log=self.event_log,
                            task_run_id=task_run_id,
                            observation=rejection_observation,
                            context_record=context_record,
                            refs=rejection_refs,
                        )
                        assistant_tool_call_content = str(event.get("assistant_content") or assistant_tool_call_content)
                        event_kwargs = dict(event.get("assistant_additional_kwargs") or {})
                        if event_kwargs:
                            assistant_tool_call_kwargs.update(event_kwargs)
                        rejection_payload = dict(rejection_observation.payload or {})
                        rejection_ref = rejection_observation.observation_id
                        tool_observation_count += 1
                        action_observation_refs.append(rejection_ref)
                        structured_observations.append(
                            {
                                "observation_ref": rejection_ref,
                                "tool_name": str(rejection_payload.get("tool_name") or ""),
                                "tool_args": dict(rejection_payload.get("tool_args") or {}),
                                "result": rejection_payload.get("result"),
                                "result_envelope": dict(rejection_payload.get("result_envelope") or {}),
                                "structured_payload": dict(rejection_payload.get("structured_payload") or {}),
                                "observed_paths": list(rejection_payload.get("observed_paths") or []),
                                "matched_paths": list(rejection_payload.get("matched_paths") or []),
                                "artifact_refs": [
                                    dict(item)
                                    for item in list(rejection_payload.get("artifact_refs") or [])
                                    if isinstance(item, dict)
                                ],
                                "command_receipt": dict(rejection_payload.get("command_receipt") or {}),
                            }
                        )
                        tool_observation_ledger = tool_observation_ledger.append(
                            build_tool_observation_record(
                                observation_ref=rejection_ref,
                                tool_name=str(rejection_payload.get("tool_name") or requested_tool_name),
                                tool_args=dict(rejection_payload.get("tool_args") or {}),
                                result=rejection_payload,
                            )
                        )
                        if blocked_tool_call:
                            round_message_tool_calls.append(blocked_tool_call)
                        rejection_tool_message = ToolMessage(
                            content=str(rejection_payload.get("result") or repair_text),
                            tool_call_id=str(
                                rejection_payload.get("tool_call_id")
                                or blocked_tool_call.get("id")
                                or getattr(event, "event_id", "")
                                or requested_tool_name
                            ),
                        )
                        round_tool_messages.append(rejection_tool_message)
                        tool_messages.append(rejection_tool_message)
                        blocked_event = self.event_log.append(
                            task_run_id,
                            "tool_call_blocked_by_progress_policy",
                            payload={
                                "tool_name": requested_tool_name,
                                "progress_policy": progress_decision.to_dict(),
                                "deliverable_progress": deliverable_progress.to_dict(),
                                "runtime_feedback": _runtime_feedback_payload(
                                    source="progress_policy",
                                    requested_tool_name=requested_tool_name,
                                    action_gate=action_gate,
                                    deliverable_progress=deliverable_progress,
                                    repair_instruction=repair_text,
                                ),
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
                        yield {"type": "runtime_loop_event", "event": result_event.to_dict()}
                        yield {"type": "runtime_loop_event", "event": observation_event.to_dict()}
                        if action_gate.forced:
                            stage_summary = build_stage_summary(
                                task_run_id=task_run_id,
                                turn_count=outcome.turn_count,
                                tool_call_count=len(pending_tool_calls),
                                tool_observation_count=tool_observation_count,
                                tool_observation_ledger=tool_observation_ledger,
                                deliverable_progress=_deliverable_progress(goal_contract, tool_observation_ledger),
                                structured_observations=structured_observations,
                                environment_snapshot=runtime_environment_snapshot,
                            )
                            conversation_messages = _action_gate_recovery_messages(
                                user_message=user_message,
                                gate=action_gate,
                                repair_instruction=repair_text,
                                stage_summary=stage_summary.to_dict(),
                                structured_observations=structured_observations,
                                assistant_tool_call_content=assistant_tool_call_content,
                                assistant_tool_call_kwargs=assistant_tool_call_kwargs,
                                round_message_tool_calls=round_message_tool_calls,
                                round_tool_messages=round_tool_messages,
                            )
                            action_gate_recovery_context_rebuilt = True
                        continue
                    if requested_tool_name == "delegate_to_agent" and (
                        not delegation_enabled or delegation_observation_count >= max_delegate_calls
                    ):
                        tool_call_budget_exceeded = True
                        blocked_event = self.event_log.append(
                            task_run_id,
                            "loop_error",
                            payload={
                                "error": "professional_task_delegation_budget_exceeded",
                                "message": "专业任务委派次数已达上限，超出预算的委派请求未执行。",
                                "max_delegate_calls_per_task_run": max_delegate_calls,
                                "tool_name": requested_tool_name,
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
                        continue
                    if _tool_call_budget_exhausted(
                        round_tool_calls=round_tool_calls,
                        pending_tool_calls=pending_tool_calls,
                        requested_tool_name=requested_tool_name,
                        gate=action_gate,
                        max_tool_calls=round_tool_call_limit,
                        max_tool_calls_per_task_run=max_tool_calls_per_task_run,
                    ):
                        exhaustion_scope = _tool_call_budget_exhaustion_scope(
                            round_tool_calls=round_tool_calls,
                            requested_tool_name=requested_tool_name,
                            gate=action_gate,
                            max_tool_calls=round_tool_call_limit,
                        )
                        if exhaustion_scope != "round":
                            tool_call_budget_exceeded = True
                        blocked_event = self.event_log.append(
                            task_run_id,
                            "loop_error",
                            payload={
                                "error": "professional_task_tool_call_budget_exceeded",
                                "message": "专业任务工具调用次数已达上限，超出预算的工具请求未执行。",
                                "budget_scope": exhaustion_scope,
                                "max_tool_calls_per_round": max_tool_calls,
                                "effective_max_tool_calls_per_round": round_tool_call_limit,
                                "max_tool_calls_per_task_run": max_tool_calls_per_task_run,
                                "delivery_tool_call_count": _delivery_tool_call_count(
                                    pending_tool_calls,
                                    gate=action_gate,
                                ),
                                "delivery_budget_remaining": _delivery_budget_remaining(
                                    pending_tool_calls,
                                    gate=action_gate,
                                    max_tool_calls_per_task_run=max_tool_calls_per_task_run,
                                ),
                                "action_gate": action_gate.to_dict(),
                                "tool_name": requested_tool_name,
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
                        continue
                    tool_call = dict(event.get("tool_call") or {})
                    if tool_call:
                        round_tool_calls.append(tool_call)
                        round_message_tool_calls.append(tool_call)
                        pending_tool_calls.append(tool_call)
                    assistant_tool_call_content = str(event.get("assistant_content") or assistant_tool_call_content)
                    event_kwargs = dict(event.get("assistant_additional_kwargs") or {})
                    if event_kwargs:
                        assistant_tool_call_kwargs.update(event_kwargs)
                runtime_events = await self.execution_engine.translate_event(
                    task_run_id=task_run_id,
                    user_message=user_message,
                    task_id=task_id,
                    task_operation=task_operation,
                    adopted_resource_policy=resource_policy,
                    current_step_id=outcome.ledger.current_step_id if outcome.ledger is not None else outcome.state.current_step_id,
                    runtime_context_manager=runtime_context_manager,
                    model_response_executor=model_response_executor,
                    tool_runtime_executor=tool_runtime_executor,
                    event=event,
                    allowed_search_sources=allowed_search_sources,
                    sandbox_policy=sandbox_policy,
                    file_management_policy=file_management_policy,
                )
                for runtime_event in runtime_events:
                    _adopt_runtime_event_ref(outcome, runtime_event)
                    observation_payload = _tool_observation_payload(runtime_event)
                    if observation_payload:
                        observation_payload = _observation_payload_with_action_gate_intent(
                            observation_payload,
                            gate=action_gate,
                        )
                        tool_observation_count += 1
                        observation_ref = _runtime_event_observation_ref(runtime_event)
                        if observation_ref:
                            action_observation_refs.append(observation_ref)
                        if str(observation_payload.get("tool_name") or "") == "delegate_to_agent":
                            delegation_observation_count += 1
                        if str(observation_payload.get("tool_name") or "") in {"write_file", "edit_file"}:
                            write_observation_count += 1
                            for artifact_ref in _artifact_output_refs_from_tool_payload(observation_payload):
                                if artifact_ref not in outcome.result_refs:
                                    outcome.result_refs.append(artifact_ref)
                        structured_observations.append(
                            {
                                "observation_ref": observation_ref,
                                "tool_name": str(observation_payload.get("tool_name") or ""),
                                "tool_args": dict(observation_payload.get("tool_args") or {}),
                                "result": observation_payload.get("result"),
                                "result_envelope": dict(observation_payload.get("result_envelope") or {}),
                                "structured_payload": dict(observation_payload.get("structured_payload") or {}),
                                "observed_paths": list(observation_payload.get("observed_paths") or []),
                                "matched_paths": list(observation_payload.get("matched_paths") or []),
                                "artifact_refs": [
                                    dict(item)
                                    for item in list(observation_payload.get("artifact_refs") or [])
                                    if isinstance(item, dict)
                                ],
                                "command_receipt": dict(observation_payload.get("command_receipt") or {}),
                            }
                        )
                        tool_observation_ledger = tool_observation_ledger.append(
                            build_tool_observation_record(
                                observation_ref=observation_ref,
                                tool_name=str(observation_payload.get("tool_name") or ""),
                                tool_args=dict(observation_payload.get("tool_args") or {}),
                                result=observation_payload,
                            )
                        )
                        message = ToolMessage(
                            content=str(observation_payload.get("result") or ""),
                            tool_call_id=str(
                                observation_payload.get("tool_call_id")
                                or dict(event.get("tool_call") or {}).get("id")
                                or getattr(runtime_event, "event_id", "")
                            ),
                        )
                        round_tool_messages.append(message)
                        tool_messages.append(message)
                    yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
                if event_type == "done":
                    outcome.final_content = str(event.get("content") or "")
                    outcome.final_answer_metadata = _answer_metadata_from_done_event(event)
                    event_terminal_reason = str(event.get("terminal_reason") or "").strip()
                    if event_terminal_reason and event_terminal_reason != "completed":
                        outcome.terminal_reason = event_terminal_reason
                    outcome.main_context = dict(event.get("main_context") or {})
                    outcome.task_summary_refs = [
                        dict(item) for item in list(event.get("task_summary_refs") or []) if isinstance(item, dict)
                    ]
                    outcome.bundle_summary_refs = [
                        dict(item) for item in list(event.get("bundle_summary_refs") or []) if isinstance(item, dict)
                    ]
                elif event_type == "error":
                    if (
                        (
                            _is_model_response_timeout_event(event)
                            or (
                                action_gate.forced
                                and _is_recoverable_model_error_event(event)
                            )
                        )
                        and tool_execution_enabled
                        and suggest_evidence_repair_tools(goal_contract, tool_observation_ledger)
                        and outcome.turn_count < max_tool_rounds
                    ):
                        timeout_stage_summary = build_stage_summary(
                            task_run_id=task_run_id,
                            turn_count=outcome.turn_count,
                            tool_call_count=len(pending_tool_calls),
                            tool_observation_count=tool_observation_count,
                            tool_observation_ledger=tool_observation_ledger,
                            deliverable_progress=_deliverable_progress(goal_contract, tool_observation_ledger),
                            structured_observations=structured_observations,
                            environment_snapshot=runtime_environment_snapshot,
                        )
                        timeout_observation = build_timeout_recovery_observation(
                            task_run_id=task_run_id,
                            directive_ref=directive.directive_id,
                            stage_summary=timeout_stage_summary.to_dict(),
                            suggested_tool_names=suggest_evidence_repair_tools(goal_contract, tool_observation_ledger),
                        )
                        context_record = runtime_context_manager.record_observation(timeout_observation)
                        timeout_result_event = append_tool_result_received_event(
                            event_log=self.event_log,
                            task_run_id=task_run_id,
                            observation=timeout_observation,
                            context_record=context_record,
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        timeout_observation_event = append_executor_observation_event(
                            event_log=self.event_log,
                            task_run_id=task_run_id,
                            observation=timeout_observation,
                            context_record=context_record,
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        recovery_event = self.event_log.append(
                            task_run_id,
                            "loop_error",
                            payload={
                                "error": "professional_task_model_timeout_recoverable"
                                if _is_model_response_timeout_event(event)
                                else "professional_task_model_error_recoverable",
                                "message": (
                                    "模型本轮响应超时，但目标契约仍有缺失动作，运行时将压缩上下文并继续下一轮。"
                                    if _is_model_response_timeout_event(event)
                                    else "模型本轮响应失败，但目标契约仍有明确缺失动作，运行时将保留证据并继续下一轮。"
                                ),
                                "source_error": dict(event),
                                "suggested_tool_names": list(suggest_evidence_repair_tools(goal_contract, tool_observation_ledger)),
                                "deliverable_progress": _deliverable_progress(goal_contract, tool_observation_ledger).to_dict(),
                                "tool_observation_ledger": tool_observation_ledger.summary(),
                                "stage_summary": timeout_stage_summary.to_dict(),
                                "timeout_observation": timeout_observation.to_dict(),
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": recovery_event.to_dict()}
                        yield {"type": "runtime_loop_event", "event": timeout_result_event.to_dict()}
                        yield {"type": "runtime_loop_event", "event": timeout_observation_event.to_dict()}
                        conversation_messages = timeout_recovery_messages(
                            user_message=user_message,
                            timeout_observation=timeout_observation,
                        )
                        outcome.final_content = ""
                        model_timeout_recovery_requested = True
                        continue
                    outcome.terminal_reason = "executor_failed"
                    yield event
                elif event_type == "model_protocol_violation":
                    if (
                        tool_execution_enabled
                        and _delivery_budget_remaining(
                            pending_tool_calls,
                            gate=action_gate,
                            max_tool_calls_per_task_run=max_tool_calls_per_task_run,
                        ) > 0
                        and outcome.turn_count < max_tool_rounds
                    ):
                        repair_event = self.event_log.append(
                            task_run_id,
                            "loop_error",
                            payload={
                                "error": "professional_task_model_protocol_violation_repair_requested",
                                "message": "模型输出了可见伪工具协议，运行时要求下一轮必须使用原生工具调用接口。",
                                "protocol_leak": dict(event.get("protocol_leak") or {}),
                                "tool_call_count": len(pending_tool_calls),
                                "max_tool_calls_per_task_run": max_tool_calls_per_task_run,
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": repair_event.to_dict()}
                        protocol_violation_repair_requested = True
                        conversation_messages = [
                            *conversation_messages,
                            {"role": "assistant", "content": str(event.get("content") or "")},
                            {
                                "role": "system",
                                "content": (
                                    "上一条回复无效：你把工具调用写成了可见文本，运行时没有执行它。"
                                    "如果任务需要读取、搜索、写入或命令验证，下一步必须使用原生工具调用接口。"
                                    "如果已有证据足够，只能基于真实观察收口，不要输出 DSML、tool_calls、invoke 或工具参数片段。"
                                ),
                            },
                        ]
                        outcome.final_content = ""
                        continue
                    outcome.final_content = _sanitize_final_content(str(event.get("content") or ""))
                    outcome.terminal_reason = "tool_call_markup_leaked"
                    yield event
                else:
                    yield event

            if protocol_violation_repair_requested and outcome.terminal_reason == "completed":
                continue

            if model_timeout_recovery_requested and outcome.terminal_reason == "completed":
                continue

            if round_protocol_leak_detected or _contains_tool_call_markup(outcome.final_content):
                if (
                    tool_execution_enabled
                    and _delivery_budget_remaining(
                        pending_tool_calls,
                        gate=action_gate,
                        max_tool_calls_per_task_run=max_tool_calls_per_task_run,
                    ) > 0
                    and outcome.turn_count < max_tool_rounds
                ):
                    repair_event = self.event_log.append(
                        task_run_id,
                        "loop_error",
                        payload={
                            "error": "professional_task_tool_markup_repair_requested",
                            "message": "模型把工具调用写成了可见文本，运行时要求重新用真实工具接口执行或基于已有证据收口。",
                            "tool_call_count": len(pending_tool_calls),
                            "max_tool_calls_per_task_run": max_tool_calls_per_task_run,
                            "leak_detected_before_output_boundary": bool(round_protocol_leak_detected),
                        },
                        refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                    )
                    yield {"type": "runtime_loop_event", "event": repair_event.to_dict()}
                    conversation_messages = [
                        *conversation_messages,
                        {"role": "assistant", "content": outcome.final_content},
                        {
                            "role": "system",
                            "content": (
                                "上一条回复无效：你把工具调用写进了最终文本，但运行时没有执行它。"
                                "如果需要操作，请现在使用真实工具调用接口；如果不需要工具，请只总结已真实发生的观察。"
                            ),
                        },
                    ]
                    outcome.final_content = ""
                    continue
                sanitized = _sanitize_final_content(outcome.final_content)
                outcome.final_content = sanitized
                if not sanitized:
                    outcome.terminal_reason = "tool_call_markup_leaked"
                else:
                    outcome.terminal_reason = "partial_contract_failed"
                break

            if round_tool_messages and outcome.terminal_reason == "completed":
                observation_state_event = self.event_log.append(
                    task_run_id,
                    "professional_task_state_changed",
                    payload={
                        "from_state": "action_dispatched" if not action_step_completed else "plan_item_validated",
                        "to_state": "observation_received",
                        "interaction_mode": interaction_mode,
                        "tool_observation_count": tool_observation_count,
                        "delegation_observation_count": delegation_observation_count,
                        "round_tool_observation_count": len(round_tool_messages),
                    },
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": observation_state_event.to_dict()}
                if not action_step_completed:
                    outcome.state, outcome.ledger = self._complete_standard_action_step_after_observation(
                        state=outcome.state,
                        ledger=outcome.ledger,
                        plan=plan,
                        task_contract_ref=task_contract_ref,
                        observation_refs=tuple(action_observation_refs),
                        interaction_mode=interaction_mode,
                    )
                    action_step_completed = True
                    for runtime_event in self._ledger_transition_events:
                        yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
                last_observation_refs = tuple(action_observation_refs[-len(round_tool_messages):]) if round_tool_messages else ()
                latest_tool_names = {
                    str(getattr(message, "name", "") or "")
                    for message in round_tool_messages
                }
                latest_structured = structured_observations[-len(round_tool_messages):] if round_tool_messages else []
                latest_payload_tool_names = {
                    str(item.get("tool_name") or "")
                    for item in latest_structured
                    if isinstance(item, dict)
                }
                deliverable_progress = _deliverable_progress(goal_contract, tool_observation_ledger)
                state_diagnostics = {
                    "tool_observation_ledger": tool_observation_ledger.summary(),
                    **_queue_diagnostics(deliverable_progress),
                }
                if "terminal" in latest_tool_names or "terminal" in latest_payload_tool_names:
                    run_state = run_state.advance(
                        "verification_observed",
                        reason="verification_observation_received",
                        evidence_refs=last_observation_refs,
                        unsatisfied_obligations=deliverable_progress.missing_obligations(),
                        diagnostics=state_diagnostics,
                    )
                elif tool_observation_ledger.has_write() and (
                    {"write_file", "edit_file"}.intersection(latest_tool_names)
                    or {"write_file", "edit_file"}.intersection(latest_payload_tool_names)
                ):
                    run_state = run_state.advance(
                        "artifact_written",
                        reason="write_observation_received",
                        evidence_refs=last_observation_refs,
                        unsatisfied_obligations=deliverable_progress.missing_obligations(),
                        diagnostics=state_diagnostics,
                    )
                else:
                    run_state = run_state.advance(
                        "tool_observed",
                        reason="tool_observation_received",
                        evidence_refs=last_observation_refs,
                        unsatisfied_obligations=deliverable_progress.missing_obligations(),
                        diagnostics=state_diagnostics,
                    )
                ledger_event = self.event_log.append(
                    task_run_id,
                    "professional_tool_observation_ledger_updated",
                    payload={
                        "tool_observation_ledger": tool_observation_ledger.to_dict(),
                        "summary": tool_observation_ledger.summary(),
                        "deliverable_progress": deliverable_progress.to_dict(),
                        "professional_run_state": run_state.to_dict(),
                    },
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
                progress_page = _professional_progress_page(
                    goal_contract=goal_contract,
                    tool_observation_ledger=tool_observation_ledger,
                    deliverable_progress=deliverable_progress,
                    turn_count=outcome.turn_count,
                    tool_call_count=len(pending_tool_calls),
                    tool_observation_count=tool_observation_count,
                )
                progress_event = self.event_log.append(
                    task_run_id,
                    "professional_task_progress_page",
                    payload={"progress_page": progress_page},
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": progress_event.to_dict()}
                stage_summary = build_stage_summary(
                    task_run_id=task_run_id,
                    turn_count=outcome.turn_count,
                    tool_call_count=len(pending_tool_calls),
                    tool_observation_count=tool_observation_count,
                    tool_observation_ledger=tool_observation_ledger,
                    deliverable_progress=deliverable_progress,
                    structured_observations=structured_observations,
                    environment_snapshot=runtime_environment_snapshot,
                )
                stage_summary_event = self.event_log.append(
                    task_run_id,
                    "professional_task_stage_summary",
                    payload={"stage_summary": stage_summary.to_dict()},
                    refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                )
                yield {"type": "runtime_loop_event", "event": stage_summary_event.to_dict()}
                evidence_packet = build_evidence_packet(
                    task_run_id=task_run_id,
                    semantic_contract=semantic_contract,
                    observations=structured_observations,
                )
                evidence_event = self.event_log.append(
                    task_run_id,
                    "professional_task_evidence_packet_built",
                    payload={"evidence_packet": evidence_packet.to_dict()},
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": evidence_event.to_dict()}
                evaluated_state_event = self.event_log.append(
                    task_run_id,
                    "professional_task_state_changed",
                    payload={"from_state": "observation_received", "to_state": "plan_item_validated", "interaction_mode": interaction_mode},
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": evaluated_state_event.to_dict()}
                write_guidance = ""
                if write_output_required and write_observation_count <= 0 and "write_file" in set(allowed_tool_names):
                    write_guidance = (
                        "用户目标包含写入/保存/产出文件要求；如果核心材料已经足够，"
                        "下一步应优先使用 write_file 在 sandbox overlay 中产出草案文件。"
                    )
                contract_guidance = build_evidence_gap_guidance(goal_contract=goal_contract, tool_observation_ledger=tool_observation_ledger)
                queue_guidance = deliverable_progress.progress_hint()
                next_action_gate = decide_next_action_gate(
                    goal_contract=goal_contract,
                    tool_observation_ledger=tool_observation_ledger,
                    allowed_tool_names=allowed_tool_names,
                )
                action_gate_guidance = next_action_gate.instruction()
                evidence_guidance = _evidence_packet_prompt(evidence_packet.to_dict())
                access_recovery_guidance = _access_recovery_guidance(structured_observations)
                material_mount_guidance = _material_mount_guidance(sandbox_policy)
                followup_system_message = {
                    "role": "system",
                    "content": (
                        "你已经收到上一轮真实工具观察结果，并且运行时已经形成证据包。"
                        f"{evidence_guidance}"
                        f"{material_mount_guidance}"
                        f"{access_recovery_guidance}"
                        "如果还需要读文件、修改、验证或委派，请继续使用真实工具调用接口；"
                        "如果已经满足语义契约，请直接收口。"
                        f"{write_guidance}"
                        f"{contract_guidance}"
                        f"{queue_guidance}"
                        f"{action_gate_guidance}"
                        "不要把工具调用、DSML、JSON schema 或内部协议当作回答文本输出。"
                    ),
                }
                if action_gate_recovery_context_rebuilt:
                    conversation_messages = [
                        *conversation_messages,
                        followup_system_message,
                    ]
                else:
                    conversation_messages = [
                        *conversation_messages,
                        AIMessage(
                            content=assistant_tool_call_content,
                            tool_calls=tool_calls_for_langchain_messages(round_message_tool_calls),
                            additional_kwargs=assistant_tool_call_kwargs,
                        ),
                        *round_tool_messages,
                        followup_system_message,
                    ]
                outcome.final_content = ""
                continue

            if (
                tool_execution_enabled
                and str(outcome.final_content or "").strip()
                and outcome.terminal_reason == "completed"
                and outcome.turn_count < max_tool_rounds
                and _delivery_budget_remaining(
                    pending_tool_calls,
                    gate=action_gate,
                    max_tool_calls_per_task_run=max_tool_calls_per_task_run,
                ) > 0
            ):
                provisional_evidence_packet = build_evidence_packet(
                    task_run_id=task_run_id,
                    semantic_contract=semantic_contract,
                    observations=structured_observations,
                )
                provisional_deliverable_validation = validate_deliverable(
                    final_answer=outcome.final_content,
                    semantic_contract=semantic_contract,
                    evidence_packet=provisional_evidence_packet.to_dict(),
                    strict=bool(verification_policy.get("strict") is True),
                    required_output_paths=goal_contract.required_output_paths,
                ).to_dict()
                provisional_obligation_validation = validate_obligations(
                    execution_obligation=execution_obligation,
                    semantic_contract=semantic_contract,
                    goal_contract=goal_contract,
                    tool_observation_ledger=tool_observation_ledger,
                    final_content=outcome.final_content,
                    deliverable_validation=provisional_deliverable_validation,
                    terminal_reason="completed",
                    tool_execution_enabled=tool_execution_enabled,
                    tool_call_count=len(pending_tool_calls),
                    tool_observation_count=tool_observation_count,
                    delegation_enabled=delegation_enabled,
                    delegation_observation_count=delegation_observation_count,
                    write_budget_reserved=False,
                    tool_budget_exhausted=tool_call_budget_exceeded,
                    contract_gate_blocked=False,
                    protocol_leak_detected=round_protocol_leak_detected,
                ).to_dict()
                if not bool(provisional_obligation_validation.get("passed") is True):
                    resubmission_tools = _closeout_resubmission_tools(
                        goal_contract=goal_contract,
                        tool_observation_ledger=tool_observation_ledger,
                        deliverable_validation=provisional_deliverable_validation,
                        obligation_validation=provisional_obligation_validation,
                        allowed_tool_names=allowed_tool_names,
                    )
                    if resubmission_tools:
                        resubmit_event = self.event_log.append(
                            task_run_id,
                            "professional_task_evidence_resubmission_requested",
                            payload={
                                "interaction_mode": interaction_mode,
                                "reason": "closeout_validation_failed_with_recoverable_tool_actions",
                                "suggested_tool_names": list(resubmission_tools),
                                "deliverable_validation": provisional_deliverable_validation,
                                "obligation_validation": provisional_obligation_validation,
                                "tool_observation_ledger": tool_observation_ledger.summary(),
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": resubmit_event.to_dict()}
                        conversation_messages = [
                            *conversation_messages,
                            {"role": "assistant", "content": _sanitize_final_content(outcome.final_content)},
                            {
                                "role": "system",
                                "content": _closeout_resubmission_instruction(
                                    suggested_tool_names=resubmission_tools,
                                    deliverable_validation=provisional_deliverable_validation,
                                    obligation_validation=provisional_obligation_validation,
                                    goal_contract=goal_contract,
                                    tool_observation_ledger=tool_observation_ledger,
                                ),
                            },
                        ]
                        outcome.final_content = ""
                        continue

            break

        closeout_protocol_leak_detected = False
        if tool_call_budget_exceeded and outcome.terminal_reason == "completed" and not str(outcome.final_content or "").strip():
            closeout_started_event = self.event_log.append(
                task_run_id,
                "professional_task_budget_closeout_started",
                payload={
                    "interaction_mode": interaction_mode,
                    "reason": "tool_budget_exhausted",
                    "tool_call_count": len(pending_tool_calls),
                    "tool_observation_count": tool_observation_count,
                    "delegation_observation_count": delegation_observation_count,
                    "max_tool_calls_per_task_run": max_tool_calls_per_task_run,
                    "max_tool_rounds_per_task_run": max_tool_rounds,
                    "write_budget_reserved": False,
                },
                refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
            )
            yield {"type": "runtime_loop_event", "event": closeout_started_event.to_dict()}
            evidence_packet = build_evidence_packet(
                task_run_id=task_run_id,
                semantic_contract=semantic_contract,
                observations=structured_observations,
            )
            outcome.terminal_reason = "tool_loop_budget_exceeded"
            if not (
                _requires_agent_supplied_verification(goal_contract)
                and not tool_observation_ledger.verification_passed()
            ):
                budget_closeout_messages = _budget_closeout_messages(
                    conversation_messages=conversation_messages,
                    evidence_packet=evidence_packet.to_dict(),
                    tool_observation_ledger=tool_observation_ledger,
                    structured_observations=structured_observations,
                    goal_contract=goal_contract,
                )
                outcome.model_call_count += 1
                async for event in self.execution_engine.stream_raw_model_events(
                    user_message=user_message,
                    model_response_executor=model_response_executor,
                    model_messages=budget_closeout_messages,
                    directive=_model_only_directive(safe_directive, mode=interaction_mode),
                    tool_instances=[],
                    model_stream_policy=_silent_model_stream_policy(model_stream_policy),
                    model_spec=resolved_model_spec,
                ):
                    runtime_events = await self.execution_engine.translate_event(
                        task_run_id=task_run_id,
                        user_message=user_message,
                        task_id=task_id,
                        task_operation=task_operation,
                        adopted_resource_policy=resource_policy,
                        current_step_id=outcome.ledger.current_step_id if outcome.ledger is not None else outcome.state.current_step_id,
                        runtime_context_manager=runtime_context_manager,
                        model_response_executor=model_response_executor,
                        tool_runtime_executor=tool_runtime_executor,
                        event=event,
                        allowed_search_sources=allowed_search_sources,
                        sandbox_policy=sandbox_policy,
                        file_management_policy=file_management_policy,
                    )
                    for runtime_event in runtime_events:
                        _adopt_runtime_event_ref(outcome, runtime_event)
                        yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
                    event_type = str(event.get("type") or "")
                    if event_type == "done":
                        outcome.final_content = _sanitize_final_content(str(event.get("content") or ""))
                        outcome.final_answer_metadata = _answer_metadata_from_done_event(event)
                        event_terminal_reason = str(event.get("terminal_reason") or "").strip()
                        if event_terminal_reason and event_terminal_reason != "completed":
                            outcome.terminal_reason = event_terminal_reason
                        outcome.main_context = dict(event.get("main_context") or {})
                        outcome.task_summary_refs = [
                            dict(item) for item in list(event.get("task_summary_refs") or []) if isinstance(item, dict)
                        ]
                        outcome.bundle_summary_refs = [
                            dict(item) for item in list(event.get("bundle_summary_refs") or []) if isinstance(item, dict)
                        ]
                        if str(outcome.final_content or "").strip() and outcome.terminal_reason == "tool_loop_budget_exceeded":
                            outcome.terminal_reason = "completed"
                    elif event_type == "error":
                        outcome.terminal_reason = "executor_failed"
                        yield event
                    else:
                        yield event

        if closeout_protocol_leak_detected and outcome.terminal_reason == "completed":
            outcome.final_content = _sanitize_final_content(outcome.final_content)
            if not str(outcome.final_content or "").strip():
                outcome.terminal_reason = "tool_call_markup_leaked"

        if _contains_tool_call_markup(outcome.final_content):
            sanitized_final_content = _strip_tool_call_markup(outcome.final_content)
            if sanitized_final_content and sanitized_final_content != str(outcome.final_content or "").strip():
                outcome.final_content = sanitized_final_content
            else:
                outcome.terminal_reason = "tool_call_markup_leaked"

        final_protocol_leak_detected = bool(closeout_protocol_leak_detected or _contains_tool_call_markup(outcome.final_content))
        if final_protocol_leak_detected:
            sanitized = _sanitize_final_content(outcome.final_content)
            if sanitized != str(outcome.final_content or "").strip():
                outcome.final_content = sanitized
        if tool_call_budget_exceeded and outcome.terminal_reason == "completed" and not str(outcome.final_content or "").strip():
            outcome.terminal_reason = "tool_loop_budget_exceeded"

        evidence_packet = build_evidence_packet(
            task_run_id=task_run_id,
            semantic_contract=semantic_contract,
            observations=structured_observations,
        )
        evidence_event = self.event_log.append(
            task_run_id,
            "professional_task_evidence_packet_built",
            payload={"evidence_packet": evidence_packet.to_dict(), "final_packet": True},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": evidence_event.to_dict()}
        verification_ready_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={"from_state": "plan_item_validated", "to_state": "deliverable_validation_ready", "interaction_mode": interaction_mode},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": verification_ready_event.to_dict()}
        final_deliverable_progress = _deliverable_progress(goal_contract, tool_observation_ledger)
        run_state = run_state.advance(
            "deliverable_validating",
            reason="deliverable_validation_ready",
            evidence_refs=tuple(action_observation_refs),
            unsatisfied_obligations=final_deliverable_progress.missing_obligations(),
            diagnostics={
                "tool_observation_ledger": tool_observation_ledger.summary(),
                **_queue_diagnostics(final_deliverable_progress),
            },
        )
        deliverable_validation = validate_deliverable(
            final_answer=outcome.final_content,
            semantic_contract=semantic_contract,
            evidence_packet=evidence_packet.to_dict(),
            strict=bool(verification_policy.get("strict") is True),
            required_output_paths=goal_contract.required_output_paths,
        ).to_dict()
        obligation_validation = validate_obligations(
            execution_obligation=execution_obligation,
            semantic_contract=semantic_contract,
            goal_contract=goal_contract,
            tool_observation_ledger=tool_observation_ledger,
            final_content=outcome.final_content,
            deliverable_validation=deliverable_validation,
            terminal_reason=outcome.terminal_reason,
            tool_execution_enabled=tool_execution_enabled,
            tool_call_count=len(pending_tool_calls),
            tool_observation_count=tool_observation_count,
            delegation_enabled=delegation_enabled,
            delegation_observation_count=delegation_observation_count,
            write_budget_reserved=False,
            tool_budget_exhausted=tool_call_budget_exceeded,
            contract_gate_blocked=False,
            protocol_leak_detected=final_protocol_leak_detected,
        ).to_dict()
        verification = {
            **obligation_validation,
            "interaction_mode": interaction_mode,
            "mode": interaction_mode,
            "semantic_task_type": str(semantic_contract.get("task_goal_type") or ""),
            "evidence_packet": evidence_packet.to_dict(),
            "deliverable_validation": deliverable_validation,
            "obligation_validation": obligation_validation,
            "passed": bool(obligation_validation.get("passed") is True),
        }
        verification = _normalize_professional_verification(verification)
        verification_review = build_verification_review(
            task_run_id=task_run_id,
            semantic_contract=semantic_contract,
            evidence_packet=evidence_packet.to_dict(),
            deliverable_validation=deliverable_validation,
            obligation_validation=obligation_validation,
        )
        completion_judgment = judge_completion(
            task_run_id=task_run_id,
            semantic_contract=semantic_contract,
            evidence_packet=evidence_packet.to_dict(),
            verification_review=verification_review,
            terminal_reason=outcome.terminal_reason,
        )
        verification["verification_review"] = verification_review.to_dict()
        verification["completion_judgment"] = completion_judgment.to_dict()
        if _should_repair_professional_closeout(verification):
            repair_base_content = str(outcome.final_content or "").strip()
            repair_base_metadata = dict(outcome.final_answer_metadata or {})
            repair_base_main_context = dict(outcome.main_context or {})
            repair_base_task_summary_refs = [
                dict(item) for item in list(outcome.task_summary_refs or []) if isinstance(item, dict)
            ]
            repair_base_bundle_summary_refs = [
                dict(item) for item in list(outcome.bundle_summary_refs or []) if isinstance(item, dict)
            ]
            repair_candidate_content = ""
            repair_candidate_metadata: dict[str, Any] = {}
            repair_candidate_main_context: dict[str, Any] = {}
            repair_candidate_task_summary_refs: list[dict[str, Any]] = []
            repair_candidate_bundle_summary_refs: list[dict[str, Any]] = []
            repair_started_event = self.event_log.append(
                task_run_id,
                "professional_task_deliverable_repair_started",
                payload={
                    "interaction_mode": interaction_mode,
                    "missing_deliverables": list(deliverable_validation.get("missing_deliverables") or []),
                    "protocol_leak_detected": bool(deliverable_validation.get("protocol_leak_detected") is True),
                },
                refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
            )
            yield {"type": "runtime_loop_event", "event": repair_started_event.to_dict()}
            repair_messages = [
                *conversation_messages,
                {"role": "assistant", "content": str(outcome.final_content or "")},
                {
                    "role": "system",
                    "content": _professional_closeout_repair_instruction(
                        semantic_contract=semantic_contract,
                        evidence_packet=evidence_packet.to_dict(),
                        validation=deliverable_validation,
                    ),
                },
            ]
            outcome.model_call_count += 1
            async for event in self.execution_engine.stream_raw_model_events(
                user_message=user_message,
                model_response_executor=model_response_executor,
                model_messages=repair_messages,
                directive=_model_only_directive(safe_directive, mode=interaction_mode),
                tool_instances=[],
                model_stream_policy=_silent_model_stream_policy(model_stream_policy),
                model_spec=resolved_model_spec,
            ):
                runtime_events = await self.execution_engine.translate_event(
                    task_run_id=task_run_id,
                    user_message=user_message,
                    task_id=task_id,
                    task_operation=task_operation,
                    adopted_resource_policy=resource_policy,
                    current_step_id=outcome.ledger.current_step_id if outcome.ledger is not None else outcome.state.current_step_id,
                    runtime_context_manager=runtime_context_manager,
                    model_response_executor=model_response_executor,
                    tool_runtime_executor=tool_runtime_executor,
                    event=event,
                    allowed_search_sources=allowed_search_sources,
                    sandbox_policy=sandbox_policy,
                    file_management_policy=file_management_policy,
                )
                for runtime_event in runtime_events:
                    _adopt_runtime_event_ref(outcome, runtime_event)
                    yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
                event_type = str(event.get("type") or "")
                if event_type == "done":
                    repair_candidate_content = _sanitize_final_content(str(event.get("content") or ""))
                    repair_candidate_metadata = _answer_metadata_from_done_event(event)
                    event_terminal_reason = str(event.get("terminal_reason") or "").strip()
                    if event_terminal_reason and event_terminal_reason != "completed":
                        outcome.terminal_reason = event_terminal_reason
                    repair_candidate_main_context = dict(event.get("main_context") or {})
                    repair_candidate_task_summary_refs = [
                        dict(item) for item in list(event.get("task_summary_refs") or []) if isinstance(item, dict)
                    ]
                    repair_candidate_bundle_summary_refs = [
                        dict(item) for item in list(event.get("bundle_summary_refs") or []) if isinstance(item, dict)
                    ]
                elif event_type == "error":
                    outcome.terminal_reason = "executor_failed"
                    yield event
                else:
                    yield event
            repair_candidate_leaked = _contains_tool_call_markup(repair_candidate_content)
            repair_candidate_deliverable = validate_deliverable(
                final_answer=repair_candidate_content,
                semantic_contract=semantic_contract,
                evidence_packet=evidence_packet.to_dict(),
                strict=bool(verification_policy.get("strict") is True),
                required_output_paths=goal_contract.required_output_paths,
            ).to_dict()
            repair_candidate_obligation = validate_obligations(
                execution_obligation=execution_obligation,
                semantic_contract=semantic_contract,
                goal_contract=goal_contract,
                tool_observation_ledger=tool_observation_ledger,
                final_content=repair_candidate_content,
                deliverable_validation=repair_candidate_deliverable,
                terminal_reason="completed",
                tool_execution_enabled=tool_execution_enabled,
                tool_call_count=len(pending_tool_calls),
                tool_observation_count=tool_observation_count,
                delegation_enabled=delegation_enabled,
                delegation_observation_count=delegation_observation_count,
                write_budget_reserved=False,
                tool_budget_exhausted=tool_call_budget_exceeded,
                contract_gate_blocked=False,
                protocol_leak_detected=bool(repair_candidate_leaked),
            ).to_dict()
            repair_candidate_passed = bool(
                repair_candidate_obligation.get("passed") is True
            )
            if repair_candidate_passed:
                outcome.final_content = repair_candidate_content
                outcome.final_answer_metadata = repair_candidate_metadata
                outcome.main_context = repair_candidate_main_context
                outcome.task_summary_refs = repair_candidate_task_summary_refs
                outcome.bundle_summary_refs = repair_candidate_bundle_summary_refs
                outcome.terminal_reason = "completed"
                final_protocol_leak_detected = False
            else:
                outcome.final_content = repair_base_content
                outcome.final_answer_metadata = repair_base_metadata
                outcome.main_context = repair_base_main_context
                outcome.task_summary_refs = repair_base_task_summary_refs
                outcome.bundle_summary_refs = repair_base_bundle_summary_refs
                final_protocol_leak_detected = bool(final_protocol_leak_detected or _contains_tool_call_markup(outcome.final_content))
                repair_rejected_event = self.event_log.append(
                    task_run_id,
                    "professional_task_deliverable_repair_rejected",
                    payload={
                        "interaction_mode": interaction_mode,
                        "reason": "repair_candidate_failed_validation",
                        "candidate_empty": not bool(repair_candidate_content.strip()),
                        "candidate_protocol_leak_detected": bool(repair_candidate_leaked),
                        "candidate_deliverable_validation": repair_candidate_deliverable,
                        "candidate_obligation_validation": repair_candidate_obligation,
                    },
                    refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                )
                yield {"type": "runtime_loop_event", "event": repair_rejected_event.to_dict()}
            deliverable_validation = validate_deliverable(
                final_answer=outcome.final_content,
                semantic_contract=semantic_contract,
                evidence_packet=evidence_packet.to_dict(),
                strict=bool(verification_policy.get("strict") is True),
                required_output_paths=goal_contract.required_output_paths,
            ).to_dict()
            obligation_validation = validate_obligations(
                execution_obligation=execution_obligation,
                semantic_contract=semantic_contract,
                goal_contract=goal_contract,
                tool_observation_ledger=tool_observation_ledger,
                final_content=outcome.final_content,
                deliverable_validation=deliverable_validation,
                terminal_reason=outcome.terminal_reason,
                tool_execution_enabled=tool_execution_enabled,
                tool_call_count=len(pending_tool_calls),
                tool_observation_count=tool_observation_count,
                delegation_enabled=delegation_enabled,
                delegation_observation_count=delegation_observation_count,
                write_budget_reserved=False,
                tool_budget_exhausted=tool_call_budget_exceeded,
                contract_gate_blocked=False,
                protocol_leak_detected=final_protocol_leak_detected,
            ).to_dict()
            verification = {
                **obligation_validation,
                "interaction_mode": interaction_mode,
                "mode": interaction_mode,
                "semantic_task_type": str(semantic_contract.get("task_goal_type") or ""),
                "evidence_packet": evidence_packet.to_dict(),
                "deliverable_validation": deliverable_validation,
                "obligation_validation": obligation_validation,
                "passed": bool(obligation_validation.get("passed") is True),
            }
            verification = _normalize_professional_verification(verification)
            verification_review = build_verification_review(
                task_run_id=task_run_id,
                semantic_contract=semantic_contract,
                evidence_packet=evidence_packet.to_dict(),
                deliverable_validation=deliverable_validation,
                obligation_validation=obligation_validation,
            )
            completion_judgment = judge_completion(
                task_run_id=task_run_id,
                semantic_contract=semantic_contract,
                evidence_packet=evidence_packet.to_dict(),
                verification_review=verification_review,
                terminal_reason=outcome.terminal_reason,
            )
            verification["verification_review"] = verification_review.to_dict()
            verification["completion_judgment"] = completion_judgment.to_dict()
        if not bool(verification.get("passed") is True):
            if final_protocol_leak_detected:
                outcome.terminal_reason = "tool_call_markup_leaked"
            elif outcome.terminal_reason == "tool_loop_budget_exceeded" and str(outcome.final_content or "").strip():
                outcome.terminal_reason = "partially_completed"
            elif outcome.terminal_reason in {"completed", "tool_loop_budget_exceeded", "partially_completed"} or str(outcome.final_content or "").strip():
                outcome.terminal_reason = "partial_contract_failed"
            completion_judgment = judge_completion(
                task_run_id=task_run_id,
                semantic_contract=semantic_contract,
                evidence_packet=evidence_packet.to_dict(),
                verification_review=verification.get("verification_review"),
                terminal_reason=outcome.terminal_reason,
            )
            verification["completion_judgment"] = completion_judgment.to_dict()
        deliverable_progress = _deliverable_progress(goal_contract, tool_observation_ledger)
        unsatisfied = tuple(
            dict.fromkeys(
                [
                    *deliverable_progress.missing_obligations(),
                    *unsatisfied_obligations_from_verification(verification),
                ]
            )
        )
        closeout_has_content = bool(str(outcome.final_content or "").strip())
        verification_passed = bool(verification.get("passed") is True)
        final_run_state = "complete" if verification_passed else "blocked"
        final_blocked_reason = "" if verification_passed else (
            "partial_closeout_unsatisfied_obligations" if closeout_has_content else "unsatisfied_execution_obligations"
        )
        run_state = run_state.advance(
            final_run_state,
            reason="deliverable_validation_checked",
            evidence_refs=tuple(action_observation_refs),
            unsatisfied_obligations=unsatisfied,
            blocked_reason=final_blocked_reason,
            diagnostics={
                "verification_passed": verification_passed,
                "closeout_status": "completed" if verification_passed else "partially_completed" if closeout_has_content else "failed",
                "terminal_reason": outcome.terminal_reason,
                "tool_observation_ledger": tool_observation_ledger.summary(),
                **_queue_diagnostics(deliverable_progress),
            },
        )
        verification["professional_run_state"] = run_state.to_dict()
        verification["tool_observation_ledger"] = tool_observation_ledger.to_dict()
        outcome.final_answer_metadata = {
            **dict(outcome.final_answer_metadata or {}),
            "verification_review": dict(verification.get("verification_review") or {}),
            "completion_judgment": dict(verification.get("completion_judgment") or {}),
        }
        verify_event = self.event_log.append(
            task_run_id,
            "professional_task_deliverable_validation_checked",
            payload={"verification": verification},
            refs={"task_contract_ref": task_contract_ref, "task_step_ref": "professional.validate_deliverable"},
        )
        yield {"type": "runtime_loop_event", "event": verify_event.to_dict()}
        completion_judgment_event = self.event_log.append(
            task_run_id,
            "professional_task_completion_judged",
            payload={
                "completion_judgment": dict(verification.get("completion_judgment") or {}),
                "verification_review": dict(verification.get("verification_review") or {}),
            },
            refs={"task_contract_ref": task_contract_ref, "task_step_ref": "professional.completion_judgment"},
        )
        yield {"type": "runtime_loop_event", "event": completion_judgment_event.to_dict()}
        run_outcome = build_professional_run_outcome(
            task_run_id=task_run_id,
            task_id=task_id,
            runtime_lane="professional_task",
            terminal_reason=outcome.terminal_reason,
            verification=verification,
            completion_judgment=dict(verification.get("completion_judgment") or {}),
            tool_observation_ledger=tool_observation_ledger.to_dict(),
            result_refs=list(outcome.result_refs or []),
            final_content=outcome.final_content,
        ).to_dict()
        outcome.run_outcome = run_outcome
        outcome.final_answer_metadata = {
            **dict(outcome.final_answer_metadata or {}),
            "run_outcome": run_outcome,
        }
        run_outcome_event = self.event_log.append(
            task_run_id,
            "professional_task_run_outcome_built",
            payload={"run_outcome": run_outcome},
            refs={"task_contract_ref": task_contract_ref, "task_step_ref": "professional.completion_judgment"},
        )
        yield {"type": "runtime_loop_event", "event": run_outcome_event.to_dict()}
        session_event = self.event_log.append(
            task_run_id,
            "professional_run_session_updated",
            payload={
                "professional_run_session": build_professional_run_session(
                    session_id=str(outcome.state.diagnostics.get("session_id") or ""),
                    task_run_id=task_run_id,
                    interaction_mode=interaction_mode,
                    state_ref=run_state.run_state_id,
                    tool_observation_ledger_ref=tool_observation_ledger.ledger_id,
                    execution_obligation=execution_obligation,
                ).to_dict(),
                "professional_run_state": run_state.to_dict(),
                "tool_observation_ledger": tool_observation_ledger.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": session_event.to_dict()}
        outcome.state, outcome.ledger = self._complete_standard_final_check_after_verification(
            state=outcome.state,
            ledger=outcome.ledger,
            task_contract_ref=task_contract_ref,
            verification_event_ref=f"runtime_event:{verify_event.event_id}",
            observation_refs=tuple(action_observation_refs),
            result_refs=tuple(outcome.result_refs),
            final_content=outcome.final_content,
            verification_passed=bool(verification.get("passed") is True),
            interaction_mode=interaction_mode,
        )
        for runtime_event in self._ledger_transition_events:
            yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
        finalizing_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={"from_state": "deliverable_validation_ready", "to_state": "finalizing", "interaction_mode": interaction_mode},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": finalizing_event.to_dict()}
        committed_state_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={
                "from_state": "finalizing",
                "to_state": "ready_for_commit",
                "interaction_mode": interaction_mode,
                "terminal_reason": outcome.terminal_reason,
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": committed_state_event.to_dict()}
        if not outcome.final_content and outcome.terminal_reason == "completed":
            outcome.terminal_reason = "executor_failed"

    def _complete_current_and_advance(
        self,
        *,
        state: RuntimeLoopState,
        ledger: TaskRunLedger | None,
        reason: str,
        refs: dict[str, str] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> tuple[RuntimeLoopState, TaskRunLedger | None]:
        self._ledger_transition_events = []
        if ledger is None:
            return state, ledger
        current = current_task_step_run(ledger)
        if current is not None and current.status == "pending":
            ledger = start_task_run_step(
                ledger,
                step_id=current.step_id,
                started_at=time.time(),
                diagnostics={"transition_reason": reason, **dict(diagnostics or {})},
            )
            current = current_task_step_run(ledger)
            if current is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_entered",
                        step_run=current,
                        ledger=ledger,
                        reason=reason,
                        refs=refs,
                    )
                )
        if current is not None and current.status == "running":
            ledger = complete_task_run_step(
                ledger,
                step_id=current.step_id,
                completed_at=time.time(),
                output_refs=(),
                executor_ref=current.executor_ref or "professional_task_run",
                diagnostics={"transition_reason": reason, **dict(diagnostics or {})},
            )
            completed = find_task_step_run(ledger, current.step_id)
            if completed is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_completed",
                        step_run=completed,
                        ledger=ledger,
                        reason=reason,
                        refs=refs,
                    )
                )
        ledger = advance_task_run_ledger(
            ledger,
            started_at=time.time(),
            executor_ref="professional_task_run",
            diagnostics={"transition_reason": reason, **dict(diagnostics or {})},
        )
        entered = current_task_step_run(ledger)
        if entered is not None and entered.status == "running":
            self._ledger_transition_events.append(
                self.record_task_run_step_event(
                    state.task_run_id,
                    event_type="step_entered",
                    step_run=entered,
                    ledger=ledger,
                    reason=reason,
                    refs=refs,
                )
            )
        ledger_event = self.record_task_run_ledger_updated(
            state.task_run_id,
            ledger=ledger,
            reason=reason,
            refs=refs,
            diagnostics=diagnostics,
        )
        self._ledger_transition_events.append(ledger_event)
        state = self.state_with_task_run_ledger(
            state,
            ledger,
            diagnostics={"last_step_transition": reason},
        )
        checkpoint_event = self.write_checkpoint_event(state, event_offset=ledger_event.offset)
        self._ledger_transition_events.append(checkpoint_event)
        return state, ledger

    def _prepare_standard_action_step(
        self,
        *,
        state: RuntimeLoopState,
        ledger: TaskRunLedger | None,
        plan: list[dict[str, Any]],
        task_contract_ref: str,
        interaction_mode: str = "standard",
    ) -> tuple[RuntimeLoopState, TaskRunLedger | None]:
        self._ledger_transition_events = []
        if ledger is None:
            return state, ledger
        action_step_id = _standard_action_step_id(plan)
        if not action_step_id:
            return state, ledger

        current = current_task_step_run(ledger)
        if current is not None and current.step_id != action_step_id:
            if current.status == "pending":
                ledger = start_task_run_step(
                    ledger,
                    step_id=current.step_id,
                    started_at=time.time(),
                    executor_ref="professional_task_run",
                    diagnostics={"transition_reason": "professional_task_action_step_selected", "interaction_mode": interaction_mode},
                )
                current = current_task_step_run(ledger)
                if current is not None:
                    self._ledger_transition_events.append(
                        self.record_task_run_step_event(
                            state.task_run_id,
                            event_type="step_entered",
                            step_run=current,
                            ledger=ledger,
                            reason="professional_task_action_step_selected",
                            refs={"task_contract_ref": task_contract_ref},
                            diagnostics={"interaction_mode": interaction_mode},
                        )
                    )
            if current is not None and current.status == "running":
                ledger = complete_task_run_step(
                    ledger,
                    step_id=current.step_id,
                    completed_at=time.time(),
                    output_refs=(f"professional_control_step:{current.step_id}",),
                    executor_ref=current.executor_ref or "professional_task_run",
                    diagnostics={
                        "transition_reason": "professional_task_action_step_selected",
                        "interaction_mode": interaction_mode,
                    },
                )
                completed = find_task_step_run(ledger, current.step_id)
                if completed is not None:
                    self._ledger_transition_events.append(
                        self.record_task_run_step_event(
                            state.task_run_id,
                            event_type="step_completed",
                            step_run=completed,
                            ledger=ledger,
                            reason="professional_task_action_step_selected",
                            refs={"task_contract_ref": task_contract_ref},
                            diagnostics={"interaction_mode": interaction_mode},
                        )
                    )

        for item in plan:
            step_id = str(item.get("plan_item_id") or item.get("step_id") or "").strip()
            if not step_id or step_id == action_step_id:
                break
            step = find_task_step_run(ledger, step_id)
            if step is None or step.status in {"completed", "failed", "skipped"}:
                continue
            if step.status == "pending":
                ledger = start_task_run_step(
                    ledger,
                    step_id=step.step_id,
                    started_at=time.time(),
                    executor_ref="professional_task_run",
                    diagnostics={"transition_reason": "professional_task_prerequisite_step_completed", "interaction_mode": interaction_mode},
                )
                entered = current_task_step_run(ledger)
                if entered is not None:
                    self._ledger_transition_events.append(
                        self.record_task_run_step_event(
                            state.task_run_id,
                            event_type="step_entered",
                            step_run=entered,
                            ledger=ledger,
                            reason="professional_task_prerequisite_step_completed",
                            refs={"task_contract_ref": task_contract_ref},
                            diagnostics={"interaction_mode": interaction_mode},
                        )
                    )
            current = current_task_step_run(ledger)
            if current is None or current.status != "running":
                continue
            ledger = update_task_run_step_diagnostics(
                ledger,
                step_id=current.step_id,
                diagnostics={
                    "professional_state": "step_evaluated",
                    "transition_reason": "professional_task_prerequisite_step_completed",
                    "interaction_mode": interaction_mode,
                    "execution_scope": "goal_and_scope_locked",
                },
            )
            current = current_task_step_run(ledger)
            ledger = complete_task_run_step(
                ledger,
                step_id=current.step_id if current is not None else None,
                completed_at=time.time(),
                output_refs=(f"professional_plan_item:{current.step_id}",) if current is not None else (),
                executor_ref="professional_task_run",
                diagnostics={
                    "transition_reason": "professional_task_prerequisite_step_completed",
                    "interaction_mode": interaction_mode,
                    "execution_scope": "goal_and_scope_locked",
                },
            )
            completed = find_task_step_run(ledger, current.step_id if current is not None else "")
            if completed is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_completed",
                        step_run=completed,
                        ledger=ledger,
                        reason="professional_task_prerequisite_step_completed",
                        refs={"task_contract_ref": task_contract_ref},
                        diagnostics={"interaction_mode": interaction_mode},
                    )
                )

        action_step = find_task_step_run(ledger, action_step_id)
        if action_step is not None and action_step.status == "pending":
            ledger = start_task_run_step(
                ledger,
                step_id=action_step.step_id,
                started_at=time.time(),
                executor_ref="professional_task_run",
                diagnostics={
                    "transition_reason": "professional_task_action_step_selected",
                    "professional_state": "step_selected",
                    "interaction_mode": interaction_mode,
                    "execution_scope": "controlled_tool_or_delegation_observation",
                },
            )
            entered = current_task_step_run(ledger)
            if entered is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_entered",
                        step_run=entered,
                        ledger=ledger,
                        reason="professional_task_action_step_selected",
                        refs={"task_contract_ref": task_contract_ref},
                        diagnostics={"interaction_mode": interaction_mode},
                    )
                )
        ledger_event = self.record_task_run_ledger_updated(
            state.task_run_id,
            ledger=ledger,
            reason="professional_task_action_step_selected",
            refs={"task_contract_ref": task_contract_ref},
            diagnostics={"interaction_mode": interaction_mode},
        )
        self._ledger_transition_events.append(ledger_event)
        state = self.state_with_task_run_ledger(
            state,
            ledger,
            diagnostics={
                "last_step_transition": "professional_task_action_step_selected",
                "professional_state": "step_selected",
                "interaction_mode": interaction_mode,
            },
        )
        checkpoint_event = self.write_checkpoint_event(state, event_offset=ledger_event.offset)
        self._ledger_transition_events.append(checkpoint_event)
        return state, ledger

    def _complete_standard_action_step_after_observation(
        self,
        *,
        state: RuntimeLoopState,
        ledger: TaskRunLedger | None,
        plan: list[dict[str, Any]],
        task_contract_ref: str,
        observation_refs: tuple[str, ...],
        interaction_mode: str = "standard",
    ) -> tuple[RuntimeLoopState, TaskRunLedger | None]:
        self._ledger_transition_events = []
        if ledger is None:
            return state, ledger
        action_step_id = _standard_action_step_id(plan)
        current = current_task_step_run(ledger)
        if current is None or current.step_id != action_step_id:
            action_step = find_task_step_run(ledger, action_step_id)
            if action_step is None:
                return state, ledger
            if action_step.status == "pending":
                ledger = start_task_run_step(
                    ledger,
                    step_id=action_step.step_id,
                    started_at=time.time(),
                    executor_ref="professional_task_run",
                    diagnostics={
                        "transition_reason": "professional_task_observation_received",
                        "interaction_mode": interaction_mode,
                    },
                )
                current = current_task_step_run(ledger)
            else:
                current = action_step
        if current is not None and current.status == "running":
            deduped_observation_refs = tuple(_dedupe_strings(observation_refs))
            ledger = complete_task_run_step(
                ledger,
                step_id=current.step_id,
                completed_at=time.time(),
                observation_refs=deduped_observation_refs,
                output_refs=tuple(f"professional_observation:{ref}" for ref in deduped_observation_refs),
                executor_ref=current.executor_ref or "professional_task_run",
                diagnostics={
                    "transition_reason": "professional_task_observation_received",
                    "professional_state": "step_evaluated",
                    "interaction_mode": interaction_mode,
                    "execution_scope": "controlled_observation_completed",
                },
            )
            completed = find_task_step_run(ledger, current.step_id)
            if completed is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_completed",
                        step_run=completed,
                        ledger=ledger,
                        reason="professional_task_observation_received",
                        refs={"task_contract_ref": task_contract_ref},
                        diagnostics={"interaction_mode": interaction_mode},
                    )
                )
        ledger = advance_task_run_ledger(
            ledger,
            started_at=time.time(),
            executor_ref="professional_task_run",
            diagnostics={
                "transition_reason": "professional_task_step_evaluated",
                "professional_state": "step_evaluated",
                "interaction_mode": interaction_mode,
            },
        )
        entered = current_task_step_run(ledger)
        if entered is not None and entered.status == "running":
            self._ledger_transition_events.append(
                self.record_task_run_step_event(
                    state.task_run_id,
                    event_type="step_entered",
                    step_run=entered,
                    ledger=ledger,
                    reason="professional_task_step_evaluated",
                    refs={"task_contract_ref": task_contract_ref},
                    diagnostics={"interaction_mode": interaction_mode},
                )
            )
        ledger_event = self.record_task_run_ledger_updated(
            state.task_run_id,
            ledger=ledger,
            reason="professional_task_step_evaluated",
            refs={"task_contract_ref": task_contract_ref},
            diagnostics={"interaction_mode": interaction_mode, "observation_ref_count": len(observation_refs)},
        )
        self._ledger_transition_events.append(ledger_event)
        state = self.state_with_task_run_ledger(
            state,
            ledger,
            diagnostics={
                "last_step_transition": "professional_task_step_evaluated",
                "professional_state": "step_evaluated",
                "interaction_mode": interaction_mode,
            },
        )
        checkpoint_event = self.write_checkpoint_event(state, event_offset=ledger_event.offset)
        self._ledger_transition_events.append(checkpoint_event)
        return state, ledger

    def _complete_standard_final_check_after_verification(
        self,
        *,
        state: RuntimeLoopState,
        ledger: TaskRunLedger | None,
        task_contract_ref: str,
        verification_event_ref: str,
        observation_refs: tuple[str, ...],
        result_refs: tuple[str, ...],
        final_content: str,
        verification_passed: bool,
        interaction_mode: str = "standard",
    ) -> tuple[RuntimeLoopState, TaskRunLedger | None]:
        self._ledger_transition_events = []
        if ledger is None:
            return state, ledger
        final_step_id = "professional.validate_deliverable"
        if find_task_step_run(ledger, final_step_id) is None:
            return state, ledger

        evidence_refs = tuple(_dedupe_strings([*observation_refs, verification_event_ref]))
        final_output_refs = tuple(_dedupe_strings([verification_event_ref, *result_refs]))
        refs = {
            "task_contract_ref": task_contract_ref,
            "verification_ref": verification_event_ref,
        }
        now = time.time()

        while True:
            current = current_task_step_run(ledger)
            if current is None or current.step_id == final_step_id:
                break
            if current.status == "pending":
                ledger = start_task_run_step(
                    ledger,
                    step_id=current.step_id,
                    started_at=now,
                    executor_ref="professional_task_run",
                    diagnostics={
                        "transition_reason": "professional_task_pre_validation_step_completed",
                        "professional_state": "verification_ready",
                        "interaction_mode": interaction_mode,
                    },
                )
                entered = current_task_step_run(ledger)
                if entered is not None:
                    self._ledger_transition_events.append(
                        self.record_task_run_step_event(
                            state.task_run_id,
                            event_type="step_entered",
                            step_run=entered,
                            ledger=ledger,
                            reason="professional_task_pre_validation_step_completed",
                            refs=refs,
                            diagnostics={"interaction_mode": interaction_mode},
                        )
                    )
                current = current_task_step_run(ledger)
            if current is None or current.step_id == final_step_id:
                break
            if current.status != "running":
                break
            current_observation_refs = tuple(_dedupe_strings(observation_refs))
            current_output_refs = tuple(
                _dedupe_strings(
                    [
                        f"professional_plan_item:{current.step_id}",
                        *current_observation_refs,
                    ]
                )
            )
            ledger = complete_task_run_step(
                ledger,
                step_id=current.step_id,
                completed_at=time.time(),
                observation_refs=current_observation_refs,
                output_refs=current_output_refs,
                executor_ref=current.executor_ref or "professional_task_run",
                diagnostics={
                    "transition_reason": "professional_task_pre_validation_step_completed",
                    "professional_state": "verification_ready",
                    "interaction_mode": interaction_mode,
                    "execution_scope": "model_observation_ready_for_final_check",
                },
            )
            completed = find_task_step_run(ledger, current.step_id)
            if completed is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_completed",
                        step_run=completed,
                        ledger=ledger,
                        reason="professional_task_pre_validation_step_completed",
                        refs=refs,
                        diagnostics={"interaction_mode": interaction_mode},
                    )
                )

        final_step = find_task_step_run(ledger, final_step_id)
        if final_step is not None and final_step.status == "pending":
            ledger = start_task_run_step(
                ledger,
                step_id=final_step.step_id,
                started_at=time.time(),
                executor_ref="professional_task_run",
                diagnostics={
                    "transition_reason": "professional_task_validation_started",
                    "professional_state": "verification_ready",
                    "interaction_mode": interaction_mode,
                    "verification_ref": verification_event_ref,
                },
            )
            entered = current_task_step_run(ledger)
            if entered is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_entered",
                        step_run=entered,
                        ledger=ledger,
                        reason="professional_task_validation_started",
                        refs=refs,
                        diagnostics={"interaction_mode": interaction_mode},
                    )
                )
            final_step = current_task_step_run(ledger)

        if final_step is not None and final_step.status == "running":
            ledger = complete_task_run_step(
                ledger,
                step_id=final_step.step_id,
                completed_at=time.time(),
                observation_refs=evidence_refs,
                output_refs=final_output_refs or evidence_refs,
                step_result_ref=verification_event_ref,
                executor_ref=final_step.executor_ref or "professional_task_run",
                diagnostics={
                    "transition_reason": "professional_task_validation_completed",
                    "professional_state": "verification_ready",
                    "interaction_mode": interaction_mode,
                    "verification_ref": verification_event_ref,
                    "verification_passed": bool(verification_passed),
                    "final_content_chars": len(str(final_content or "")),
                    "observation_ref_count": len(evidence_refs),
                },
            )
            completed = find_task_step_run(ledger, final_step.step_id)
            if completed is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_completed",
                        step_run=completed,
                        ledger=ledger,
                        reason="professional_task_validation_completed",
                        refs=refs,
                        diagnostics={"interaction_mode": interaction_mode, "verification_passed": bool(verification_passed)},
                    )
                )

        ledger_event = self.record_task_run_ledger_updated(
            state.task_run_id,
            ledger=ledger,
            reason="professional_task_validation_completed",
            refs={**refs, "task_step_ref": final_step_id},
            diagnostics={
                "interaction_mode": interaction_mode,
                "verification_ref": verification_event_ref,
                "verification_passed": bool(verification_passed),
            },
        )
        self._ledger_transition_events.append(ledger_event)
        state = self.state_with_task_run_ledger(
            state,
            ledger,
            diagnostics={
                "last_step_transition": "professional_task_validation_completed",
                "professional_state": "verification_ready",
                "interaction_mode": interaction_mode,
                "verification_ref": verification_event_ref,
                "verification_passed": bool(verification_passed),
            },
        )
        checkpoint_event = self.write_checkpoint_event(state, event_offset=ledger_event.offset)
        self._ledger_transition_events.append(checkpoint_event)
        return state, ledger


def _silent_model_stream_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    return {**dict(policy or {}), "emit_content_delta": False}


def _is_model_response_timeout_event(event: dict[str, Any]) -> bool:
    if str(event.get("type") or "") != "error":
        return False
    fields = {
        "error": str(event.get("error") or ""),
        "code": str(event.get("code") or ""),
        "detail": str(event.get("detail") or ""),
        "content": str(event.get("content") or ""),
    }
    if fields["error"] in {"model_response_timeout", "model_stream_recovery_timeout"}:
        return True
    if fields["code"].strip().lower() == "timeout":
        return True
    combined = " ".join(value for value in fields.values() if value).lower()
    return any(marker in combined for marker in ("timeouterror", "timed out", "timeout", "超时"))


def _is_recoverable_model_error_event(event: dict[str, Any]) -> bool:
    if str(event.get("type") or "").strip() != "error":
        return False
    fields = {
        "error": str(event.get("error") or "").strip().lower(),
        "code": str(event.get("code") or "").strip().lower(),
        "detail": str(event.get("detail") or "").strip().lower(),
        "content": str(event.get("content") or "").strip().lower(),
    }
    combined = " ".join(value for value in fields.values() if value)
    if fields["code"] in {"provider_unavailable", "rate_limit", "connection_error", "timeout"}:
        return True
    return any(
        marker in combined
        for marker in (
            "temporarily unavailable",
            "connection error",
            "readerror",
            "remoteprotocolerror",
            "rate limit",
            "too many requests",
            "暂时不可用",
            "连接",
            "限流",
        )
    )


def _access_recovery_guidance(structured_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> str:
    recent = [
        str(item.get("result") or item.get("text") or item.get("content") or "")
        for item in list(structured_observations or [])[-8:]
        if isinstance(item, dict)
    ]
    combined = "\n".join(recent).lower()
    markers = (
        "path traversal detected",
        "blocked: command references",
        "outside the sandbox workspace",
        "permission denied",
        "read only",
        "readonly",
        "access denied",
        "权限",
        "沙箱",
        "越界",
        "只读",
    )
    if not any(marker in combined for marker in markers):
        return ""
    return (
        "最近工具观察包含权限、沙箱、路径穿越、绝对路径越界或只读阻断。"
        "不要重复同一个被拒绝的路径或命令；把阻断当作环境边界来调整执行方式。"
        "优先改用当前 sandbox/workspace 内允许的相对路径、搜索工具、目录列表、已挂载材料、已有观察结果或目标目录内副本继续推进。"
        "如果必要材料仍不可达，明确记录缺口，并先完成仍可合法完成的输出路径。"
    )


def _material_mount_guidance(sandbox_policy: dict[str, Any] | None) -> str:
    mounts = [
        dict(item)
        for item in list(dict(sandbox_policy or {}).get("material_mounts") or [])
        if isinstance(item, dict) and str(item.get("mount_path") or "").strip()
    ]
    if not mounts:
        return ""
    mounted = [
        f"{item.get('mount_id')}: {item.get('mount_path')} ({item.get('role') or 'source'}, {item.get('status') or 'unknown'})"
        for item in mounts
    ]
    return (
        "运行时已把外部源材料导入 sandbox 内的只读材料入口。"
        f"可用材料入口：{'; '.join(mounted)}。"
        "读取源项目时使用这些 sandbox 相对路径，不要读取外部绝对源路径。"
        "目标产物仍写入用户指定的目标输出目录。"
    )





