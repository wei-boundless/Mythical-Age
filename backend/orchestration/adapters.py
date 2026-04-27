from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Any

from agents.a2a_cards import AGENT_ID_BY_WORKER_ROUTE
from orchestration.models import (
    AnswerPolicy,
    ContextPolicyDecision,
    ExecutionDirective,
    ExecutionTopology,
    IntentFrame,
    MemoryPolicy,
    OrchestrationDecision,
    OrchestrationExecution,
    OrchestrationPlan,
    OutputPolicyDecision,
    PromptAssemblyDecision,
    ResourcePolicy,
    SafetyDecision,
)
from orchestration.validation import validate_orchestration_plan


MAIN_AGENT_ID = "agent:main:conversation"


def build_orchestration_plan(
    *,
    session_id: str,
    message: str,
    query_plan: Any,
    source: str = "live-session",
    mode: str = "plan_only",
    warnings: list[str] | None = None,
    contract_previews: list[dict[str, Any]] | None = None,
) -> OrchestrationPlan:
    executions = list(query_plan.iter_executions()) if hasattr(query_plan, "iter_executions") else []
    primary_execution = executions[0] if executions else None
    understanding = getattr(primary_execution, "query_understanding", None) or getattr(query_plan, "query_understanding", None)
    dispatch_plan = getattr(primary_execution, "dispatch_plan", None) or getattr(query_plan, "dispatch_plan", None)
    normalized_mode = _normalize_mode(mode)
    warning_items = [str(item) for item in list(warnings or []) if str(item or "").strip()]
    plan_id = _plan_id(session_id=session_id, message=message, query_plan=query_plan)

    topology = ExecutionTopology(
        mode=str(getattr(query_plan, "execution_mode", "") or "single_execution"),
        route=str(getattr(understanding, "route", "") or "unknown"),
        execution_kind=str(getattr(primary_execution, "execution_kind", "") or getattr(query_plan, "execution_kind", "") or "agent"),
        reason=_first_reason(understanding) or str(getattr(understanding, "direct_route_reason", "") or ""),
        branch_count=max(1, len(executions)),
    )

    orchestration_executions = [
        _execution_to_orchestration(index=index, execution=execution)
        for index, execution in enumerate(executions, start=1)
    ]

    contract_preview_items = [
        dict(item)
        for item in list(contract_previews or [])
        if isinstance(item, dict)
    ]
    decisions = [
        _input_decision(session_id=session_id, message=message, query_plan=query_plan),
        _memory_decision(primary_execution),
        _task_decision(understanding),
        _topology_decision(query_plan, topology),
        _skill_decision(primary_execution),
        _dispatch_decision(dispatch_plan, understanding),
        _contract_decision(contract_preview_items),
        _execution_decision(primary_execution, topology),
        _safety_decision(warning_items),
    ]

    intent_frame = _intent_frame(message=message, understanding=understanding, executions=executions)
    intent_candidates = _intent_candidates(
        message=message,
        understanding=understanding,
        intent_frame=intent_frame,
    )
    intent_authority = _intent_authority(intent_candidates=intent_candidates)
    memory_policy = _memory_policy(primary_execution)
    context_policy = _context_policy(query_plan=query_plan, executions=executions)
    restore_authority = _restore_authority(
        memory_policy=memory_policy,
        context_policy=context_policy,
        intent_frame=intent_frame,
        executions=executions,
    )
    resource_policy = _resource_policy(
        query_plan=query_plan,
        executions=executions,
        contract_previews=contract_preview_items,
    )
    execution_directives = [
        _execution_directive(index=index, execution=execution)
        for index, execution in enumerate(executions, start=1)
    ]
    answer_policy = _answer_policy(primary_execution)
    output_policy = OutputPolicyDecision(
        mode="runtime",
        answer_channel="runtime_output_boundary",
        refs={"module": "query.output_boundary"},
    )
    output_authority = _output_authority(
        answer_policy=answer_policy,
        output_policy=output_policy,
        memory_policy=memory_policy,
        topology=topology,
        executions=executions,
    )
    dispatch_authority = _dispatch_authority(
        resource_policy=resource_policy,
        execution_directives=execution_directives,
        topology=topology,
        contract_previews=contract_preview_items,
    )

    plan = OrchestrationPlan(
        plan_id=plan_id,
        session_id=session_id,
        input_text=message,
        source=source,
        mode=normalized_mode,
        behavior_policy_id=f"default:{normalized_mode}",
        topology=topology,
        intent_frame=intent_frame,
        memory_policy=memory_policy,
        resource_policy=resource_policy,
        execution_directives=execution_directives,
        answer_policy=answer_policy,
        decisions=decisions,
        executions=orchestration_executions,
        context_policy=context_policy,
        prompt_policy=_prompt_policy(dispatch_plan, primary_execution),
        output_policy=output_policy,
        safety=SafetyDecision(mode=normalized_mode, warnings=warning_items, risks=[]),
        diagnostics={
            "legacy_plan_type": type(query_plan).__name__,
            "legacy_execution_count": len(executions),
            "plan_compatible": True,
            "contract_preview_count": len(contract_preview_items),
            "intent_candidates": intent_candidates,
            "intent_authority": intent_authority,
            "restore_authority": restore_authority,
            "output_authority": output_authority,
            "dispatch_authority": dispatch_authority,
        },
    )
    validation = validate_orchestration_plan(plan)
    plan.validation = validation
    plan.decisions.append(_validation_decision(validation.to_dict()))
    if validation.status == "blocked":
        plan.safety.risks.extend([str(item.get("code") or "") for item in validation.issues])
    return plan


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or "plan_only").strip().lower()
    if normalized == "shadow":
        return "plan_only"
    return normalized if normalized in {"legacy", "plan_only", "primary"} else "plan_only"


def _intent_frame(*, message: str, understanding: Any, executions: list[Any]) -> IntentFrame:
    candidate_tools = list(getattr(understanding, "candidate_tools", []) or [])
    tool_name = str(getattr(understanding, "tool_name", "") or "")
    execution_kinds = {str(getattr(item, "execution_kind", "") or "") for item in executions}
    source_needs = _source_needs(understanding=understanding, candidate_tools=candidate_tools + ([tool_name] if tool_name else []))
    risk_signals = []
    signals = getattr(understanding, "structural_signals", None)
    if isinstance(signals, dict):
        risk_signals.extend(str(item) for item in list(signals.get("search_policy_blocked_tools") or []) if str(item).strip())
    return IntentFrame(
        user_goal=message,
        intent=str(getattr(understanding, "intent", "") or "general_query"),
        task_kind=str(getattr(understanding, "task_kind", "") or "knowledge_lookup"),
        source_kind=str(getattr(understanding, "source_kind", "") or "knowledge_base"),
        modality=str(getattr(understanding, "modality", "") or "general"),
        route=str(getattr(understanding, "route", "") or "unknown"),
        source_needs=source_needs,
        freshness_required="web" in source_needs,
        needs_tool=bool(tool_name or candidate_tools or "direct_tool" in execution_kinds or "worker" in execution_kinds),
        needs_agent=not bool("direct_tool" in execution_kinds and len(execution_kinds) == 1),
        risk_signals=_dedupe(risk_signals),
        confidence=float(getattr(understanding, "confidence", 0.0) or 0.0),
        refs={
            "owner_module": "understanding.query_understanding",
            "authority": "candidate_only",
            "canonical_owner": "orchestration.intent_frame",
            "legacy_runtime_owner": "query.planner",
        },
    )


def _intent_candidates(*, message: str, understanding: Any, intent_frame: IntentFrame) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": "legacy-understanding:primary",
            "source": "legacy_understanding",
            "owner_module": "understanding.task_understanding",
            "authority": "candidate_only",
            "selected_by": "orchestration.intent_frame",
            "legacy_still_executes": True,
            "user_goal": message,
            "intent": intent_frame.intent,
            "task_kind": intent_frame.task_kind,
            "source_kind": intent_frame.source_kind,
            "modality": intent_frame.modality,
            "route": intent_frame.route,
            "source_needs": list(intent_frame.source_needs),
            "candidate_tools": list(getattr(understanding, "candidate_tools", []) or []),
            "tool_name": str(getattr(understanding, "tool_name", "") or ""),
            "worker_hint": str(getattr(understanding, "worker_route", "") or ""),
            "confidence": intent_frame.confidence,
            "reasons": [str(item) for item in list(getattr(understanding, "reasons", []) or [])],
        }
    ]


def _intent_authority(*, intent_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "phase": "7B",
        "state": "candidate_projected",
        "canonical_owner": "orchestration.intent_frame",
        "candidate_owner": "understanding.task_understanding",
        "runtime_owner": "query.planner",
        "legacy_still_executes": True,
        "candidate_count": len(intent_candidates),
        "cutover_state": "not_started",
        "rule": "理解层只提交候选；正式编排层负责仲裁，但当前运行时仍由 legacy QueryPlanner 执行。",
    }


def _restore_authority(
    *,
    memory_policy: MemoryPolicy,
    context_policy: ContextPolicyDecision,
    intent_frame: IntentFrame,
    executions: list[Any],
) -> dict[str, Any]:
    memory_candidates = [str(item) for item in list(memory_policy.restored_candidates or []) if str(item).strip()]
    context_candidates = [str(item) for item in list(context_policy.restore_indexes or []) if str(item).strip()]
    handle_candidates = [str(item) for item in list(context_policy.required_handles or []) if str(item).strip()]
    candidates = _restore_candidate_objects(
        memory_candidates=memory_candidates,
        context_candidates=context_candidates,
        handle_candidates=handle_candidates,
        executions=executions,
    )
    candidate_count = len(candidates)
    blockers = ["legacy_restore_still_executes"]
    if candidate_count:
        blockers.append("restore_candidates_present")
    if memory_policy.use_session_state:
        blockers.append("session_state_restore_candidate")
    if memory_policy.use_durable_memory:
        blockers.append("durable_memory_restore_candidate")
    if context_candidates or handle_candidates:
        blockers.append("context_handle_restore_candidate")
    adoption_decisions = _restore_adoption_decisions(candidates=candidates, intent_frame=intent_frame)
    adoption_gate = _restore_adoption_gate(
        candidates=candidates,
        adoption_decisions=adoption_decisions,
        intent_frame=intent_frame,
    )
    cutover_plan = _restore_cutover_plan(
        candidates=candidates,
        adoption_gate=adoption_gate,
    )
    dry_run_comparison = _restore_dry_run_comparison(
        candidates=candidates,
        adoption_decisions=adoption_decisions,
        cutover_plan=cutover_plan,
    )
    formal_adoption_review = _restore_formal_adoption_review(
        candidates=candidates,
        intent_frame=intent_frame,
    )
    adoption_trace = _restore_adoption_trace(
        candidates=candidates,
        formal_adoption_review=formal_adoption_review,
        cutover_plan=cutover_plan,
    )
    shadow_replacement_plan = _restore_shadow_replacement_plan(adoption_trace=adoption_trace)
    shadow_comparison = _restore_shadow_comparison(
        adoption_trace=adoption_trace,
        shadow_replacement_plan=shadow_replacement_plan,
    )
    real_shadow_consumer_gate = _restore_real_shadow_consumer_gate(
        shadow_comparison=shadow_comparison,
    )
    shadow_consumer_contract = _restore_shadow_consumer_contract(
        real_shadow_consumer_gate=real_shadow_consumer_gate,
    )
    return {
        "phase": "7F",
        "state": "candidate_projected",
        "canonical_owner": "orchestration.intent_frame",
        "candidate_owners": [
            "understanding.memory_intent",
            "query.runtime_context_state",
            "query.continuation_resolver",
            "query.context_management",
        ],
        "runtime_owner": "query.planner/runtime_context_state",
        "legacy_still_executes": True,
        "current_turn_override_allowed": False,
        "candidate_count": candidate_count,
        "candidates": candidates,
        "memory_candidates": memory_candidates,
        "context_candidates": context_candidates,
        "handle_candidates": handle_candidates,
        "adoption_decisions": adoption_decisions,
        "adoption_gate": adoption_gate,
        "cutover_plan": cutover_plan,
        "dry_run_comparison": dry_run_comparison,
        "formal_adoption_review": formal_adoption_review,
        "restore_adoption_trace": adoption_trace,
        "restore_shadow_replacement_plan": shadow_replacement_plan,
        "restore_shadow_comparison": shadow_comparison,
        "restore_real_shadow_consumer_gate": real_shadow_consumer_gate,
        "restore_shadow_consumer_contract": shadow_consumer_contract,
        "intent_route": intent_frame.route,
        "intent_source_kind": intent_frame.source_kind,
        "blockers": sorted(set(blockers)),
        "rule": "恢复层只能提交候选，不得覆盖当前轮 IntentFrame；当前阶段仍由 legacy runtime 消费恢复结果。",
    }


def _restore_shadow_consumer_contract(*, real_shadow_consumer_gate: dict[str, Any]) -> dict[str, Any]:
    candidate_plan = [
        dict(item)
        for item in list(real_shadow_consumer_gate.get("candidate_plan") or [])
        if isinstance(item, dict)
    ]
    runtime_interfaces = [
        dict(item)
        for item in list(real_shadow_consumer_gate.get("runtime_interfaces") or [])
        if isinstance(item, dict)
    ]
    required_interfaces = {
        "RestoreShadowConsumer",
        "RestoreComparisonSink",
        "RestoreStateWriteGuard",
        "RestoreRollbackGate",
    }
    provided_interfaces = {
        str(item.get("interface") or "")
        for item in runtime_interfaces
        if str(item.get("interface") or "").strip()
    }
    missing_interfaces = sorted(required_interfaces - provided_interfaces)
    blocked_candidates = [
        str(item.get("candidate_id") or item.get("replacement_point") or "unknown")
        for item in candidate_plan
        if str(item.get("design_status") or "") != "ready_for_interface_design"
    ]
    blockers: list[str] = []
    gate_state = str(real_shadow_consumer_gate.get("state") or "")
    if gate_state not in {"design_gate_ready", "no_candidates"}:
        blockers.append(f"real_shadow_gate:{gate_state or 'missing'}")
    if missing_interfaces:
        blockers.append("shadow_consumer_interfaces_missing")
    if blocked_candidates:
        blockers.append("shadow_consumer_candidate_blocked")

    contract_candidates = [
        {
            "candidate_id": str(item.get("candidate_id") or ""),
            "replacement_point": str(item.get("replacement_point") or "unknown"),
            "legacy_consumer": str(item.get("legacy_consumer") or ""),
            "comparison": str(item.get("comparison") or "unknown"),
            "consumer_state": "observe_only_ready"
            if str(item.get("design_status") or "") == "ready_for_interface_design"
            else "blocked",
            "state_write_allowed": False,
            "takeover_allowed": False,
        }
        for item in candidate_plan
    ]
    if not candidate_plan:
        state = "no_candidates"
    elif blockers:
        state = "blocked"
    else:
        state = "contract_ready"
    return {
        "phase": "8F",
        "state": state,
        "mode": "observe_only_contract",
        "candidate_count": len(contract_candidates),
        "contract_candidates": contract_candidates,
        "required_interfaces": sorted(required_interfaces),
        "provided_interfaces": sorted(provided_interfaces),
        "missing_interfaces": missing_interfaces,
        "consumer_state_counts": _count_by_key(contract_candidates, "consumer_state"),
        "replacement_point_counts": _count_by_key(contract_candidates, "replacement_point"),
        "blockers": sorted(set(blockers)),
        "observe_only_allowed": state == "contract_ready",
        "state_write_allowed": False,
        "takeover_allowed": False,
        "delete_allowed": False,
        "safe_rule": "8F 只允许 observe-only contract；真实恢复消费、状态写回、旧链路替换仍全部禁止。",
        "next_safe_step": "把运行时开关接到 observe-only consumer gate；默认关闭，只在显式开启时记录观测，不接管恢复结果。",
    }


def _restore_real_shadow_consumer_gate(*, shadow_comparison: dict[str, Any]) -> dict[str, Any]:
    observations = [
        dict(item)
        for item in list(shadow_comparison.get("shadow_observations") or [])
        if isinstance(item, dict)
    ]
    matched_count = sum(
        1
        for item in observations
        if str(item.get("comparison") or "") == "shadow_matches_legacy_observation"
    )
    blocked_count = sum(
        1
        for item in observations
        if str(item.get("comparison") or "") == "shadow_blocked"
    )
    unmatched_count = len(observations) - matched_count - blocked_count
    blockers: list[str] = ["legacy_restore_still_executes", "real_shadow_consumer_not_implemented"]
    comparison_state = str(shadow_comparison.get("state") or "")
    if comparison_state not in {"shadow_observed", "no_candidates"}:
        blockers.append(f"shadow_comparison:{comparison_state or 'missing'}")
    if blocked_count:
        blockers.append("shadow_observation_blocked")
    if unmatched_count:
        blockers.append("shadow_legacy_comparison_unresolved")
    runtime_interfaces = [
        {
            "interface": "RestoreShadowConsumer",
            "owner": "orchestration.restore_shadow",
            "purpose": "只读消费 restore candidate，不写 runtime 状态。",
            "required_before_enable": True,
        },
        {
            "interface": "RestoreComparisonSink",
            "owner": "orchestration.restore_shadow",
            "purpose": "记录 shadow 与 legacy restore 输出对照。",
            "required_before_enable": True,
        },
        {
            "interface": "RestoreStateWriteGuard",
            "owner": "orchestration.validation",
            "purpose": "阻止 shadow observation 写入 MemoryPolicy、ContextPolicy 或 IntentFrame。",
            "required_before_enable": True,
        },
        {
            "interface": "RestoreRollbackGate",
            "owner": "runtime.control",
            "purpose": "任何异常立即回退 legacy restore 消费。",
            "required_before_enable": True,
        },
    ]
    candidate_plan = [
        {
            "candidate_id": str(item.get("candidate_id") or ""),
            "replacement_point": str(item.get("replacement_point") or "unknown"),
            "legacy_consumer": str(item.get("legacy_consumer") or ""),
            "shadow_value": str(item.get("shadow_value") or ""),
            "comparison": str(item.get("comparison") or "unknown"),
            "design_status": "ready_for_interface_design"
            if str(item.get("comparison") or "") == "shadow_matches_legacy_observation"
            else "blocked",
        }
        for item in observations
    ]
    if not observations:
        state = "no_candidates"
    elif blocked_count or unmatched_count or comparison_state != "shadow_observed":
        state = "blocked"
    else:
        state = "design_gate_ready"
    return {
        "phase": "8E",
        "state": state,
        "mode": "diagnostic_only",
        "observation_count": len(observations),
        "matched_count": matched_count,
        "blocked_count": blocked_count,
        "unmatched_count": unmatched_count,
        "candidate_plan": candidate_plan,
        "runtime_interfaces": runtime_interfaces,
        "design_status_counts": _count_by_key(candidate_plan, "design_status"),
        "replacement_point_counts": _count_by_key(candidate_plan, "replacement_point"),
        "blockers": sorted(set(blockers)),
        "enable_allowed": False,
        "takeover_allowed": False,
        "delete_allowed": False,
        "next_safe_step": "先实现真实 shadow consumer 的接口边界与回滚门禁；在开关默认关闭前，不得替换 legacy restore。",
    }


def _restore_shadow_comparison(
    *,
    adoption_trace: dict[str, Any],
    shadow_replacement_plan: dict[str, Any],
) -> dict[str, Any]:
    trace_by_id = {
        str(item.get("candidate_id") or ""): dict(item)
        for item in list(adoption_trace.get("traces") or [])
        if isinstance(item, dict) and str(item.get("candidate_id") or "").strip()
    }
    observations: list[dict[str, Any]] = []
    for candidate in list(shadow_replacement_plan.get("replacement_candidates") or []):
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        trace = trace_by_id.get(candidate_id, {})
        shadow_status = str(candidate.get("shadow_status") or "")
        shadow_value = _restore_shadow_observation_value(trace)
        if shadow_status == "eligible_for_shadow":
            shadow_state = "observed_read_only"
        else:
            shadow_state = "blocked"
        legacy_state = str(trace.get("legacy_state") or "observed")
        if shadow_state == "observed_read_only" and legacy_state == "adopted_by_legacy":
            comparison = "shadow_matches_legacy_observation"
        elif shadow_state == "blocked":
            comparison = "shadow_blocked"
        else:
            comparison = "observed"
        observations.append(
            {
                "candidate_id": candidate_id,
                "candidate_type": str(candidate.get("candidate_type") or trace.get("candidate_type") or ""),
                "replacement_point": str(candidate.get("replacement_point") or trace.get("replacement_point") or "unknown"),
                "shadow_state": shadow_state,
                "shadow_value": shadow_value,
                "legacy_state": legacy_state,
                "legacy_consumer": str(candidate.get("legacy_consumer") or trace.get("legacy_consumer") or ""),
                "comparison": comparison,
                "required_next_controls": [
                    "real_shadow_consumer_boundary",
                    "legacy_restore_output_snapshot",
                    "no_state_write_guard",
                    "rollback_to_legacy_restore",
                ],
            }
        )
    blockers = ["legacy_restore_still_executes"]
    if any(str(item.get("shadow_state") or "") == "blocked" for item in observations):
        blockers.append("shadow_observation_blocked")
    if observations:
        blockers.append("real_shadow_consumer_not_enabled")
    if not observations:
        state = "no_candidates"
    elif any(str(item.get("comparison") or "") == "shadow_blocked" for item in observations):
        state = "needs_shadow_review"
    else:
        state = "shadow_observed"
    return {
        "phase": "8D",
        "state": state,
        "mode": "diagnostic_only",
        "observation_count": len(observations),
        "shadow_observations": observations,
        "comparison_counts": _count_by_key(observations, "comparison"),
        "shadow_state_counts": _count_by_key(observations, "shadow_state"),
        "replacement_point_counts": _count_by_key(observations, "replacement_point"),
        "blockers": sorted(set(blockers)),
        "state_write_allowed": False,
        "takeover_allowed": False,
        "delete_allowed": False,
        "next_safe_step": "只读 shadow observation 稳定后，才允许设计真实 shadow consumer；当前仍不得替换 legacy restore。",
    }


def _restore_shadow_observation_value(trace: dict[str, Any]) -> str:
    candidate_type = str(trace.get("candidate_type") or "").strip()
    value = str(trace.get("value") or "").strip()
    if not value:
        return ""
    if candidate_type in {"target_handle", "upstream_object_handle", "upstream_result_handle", "restore_index"}:
        return f"context:{value}"
    if candidate_type in {"session_state", "durable_memory"}:
        return f"memory:{value}"
    return value


def _restore_shadow_replacement_plan(*, adoption_trace: dict[str, Any]) -> dict[str, Any]:
    traces = [
        dict(item)
        for item in list(adoption_trace.get("traces") or [])
        if isinstance(item, dict)
    ]
    replacement_candidates = [
        {
            "candidate_id": str(item.get("candidate_id") or ""),
            "candidate_type": str(item.get("candidate_type") or ""),
            "replacement_point": str(item.get("replacement_point") or "unknown"),
            "legacy_consumer": str(item.get("legacy_consumer") or ""),
            "target_owner": str(item.get("target_owner") or ""),
            "alignment": str(item.get("alignment") or ""),
            "shadow_status": "eligible_for_shadow" if str(item.get("status") or "") == "ready_for_shadow_replacement" else "blocked",
            "required_controls": [
                "read_only_shadow_consumer",
                "legacy_output_comparison",
                "intent_override_guard",
                "rollback_to_legacy_restore",
            ],
        }
        for item in traces
    ]
    eligible_count = sum(1 for item in replacement_candidates if item["shadow_status"] == "eligible_for_shadow")
    blocked_count = len(replacement_candidates) - eligible_count
    blockers: list[str] = []
    trace_state = str(adoption_trace.get("state") or "")
    if trace_state not in {"trace_ready", "no_candidates"}:
        blockers.append(f"adoption_trace:{trace_state or 'missing'}")
    if blocked_count:
        blockers.append("shadow_candidates_blocked")
    if traces:
        blockers.extend(["shadow_consumer_not_implemented", "legacy_restore_still_executes"])
    if not traces:
        state = "no_candidates"
    elif blocked_count:
        state = "needs_trace_review"
    else:
        state = "shadow_plan_ready"
    return {
        "phase": "8C",
        "state": state,
        "mode": "diagnostic_only",
        "candidate_count": len(replacement_candidates),
        "eligible_count": eligible_count,
        "blocked_count": blocked_count,
        "replacement_candidates": replacement_candidates,
        "replacement_point_counts": _count_by_key(replacement_candidates, "replacement_point"),
        "shadow_status_counts": _count_by_key(replacement_candidates, "shadow_status"),
        "blockers": sorted(set(blockers)),
        "shadow_execution_allowed": False,
        "takeover_allowed": False,
        "delete_allowed": False,
        "next_safe_step": "下一步只能实现只读 shadow consumer，对比 legacy restore 输出；稳定前不得切换真实消费入口。",
    }


def _restore_adoption_trace(
    *,
    candidates: list[dict[str, Any]],
    formal_adoption_review: dict[str, Any],
    cutover_plan: dict[str, Any],
) -> dict[str, Any]:
    decisions_by_id = {
        str(item.get("candidate_id") or ""): item
        for item in list(formal_adoption_review.get("decisions") or [])
        if isinstance(item, dict) and str(item.get("candidate_id") or "").strip()
    }
    observations_by_id = {
        str(item.get("candidate_id") or ""): item
        for item in list(formal_adoption_review.get("legacy_observations") or [])
        if isinstance(item, dict) and str(item.get("candidate_id") or "").strip()
    }
    comparison_by_id = {
        str(item.get("candidate_id") or ""): item
        for item in list((dict(formal_adoption_review.get("comparison") or {})).get("items") or [])
        if isinstance(item, dict) and str(item.get("candidate_id") or "").strip()
    }
    replacement_points = [
        dict(item)
        for item in list(cutover_plan.get("required_replacement_points") or [])
        if isinstance(item, dict)
    ]

    traces: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        decision = dict(decisions_by_id.get(candidate_id) or {})
        observation = dict(observations_by_id.get(candidate_id) or {})
        comparison = dict(comparison_by_id.get(candidate_id) or {})
        candidate_type = str(candidate.get("candidate_type") or "")
        replacement_point = _restore_replacement_point_for_candidate(
            candidate_type=candidate_type,
            replacement_points=replacement_points,
        )
        formal_decision = str(decision.get("decision") or "missing")
        legacy_state = str(observation.get("legacy_state") or candidate.get("adoption_state") or "observed")
        alignment = str(comparison.get("alignment") or "missing_comparison")
        if alignment == "legacy_matches_formal_acceptance":
            status = "ready_for_shadow_replacement"
            safe_next_step = "把该候选接入只读 shadow replacement，对比输出稳定后再考虑切换消费入口。"
        elif alignment == "legacy_over_adopts_rejected_candidate":
            status = "blocked_by_formal_rejection"
            safe_next_step = "先修正旧链路过度采用或补齐候选结构，不能替换消费入口。"
        elif formal_decision == "missing" or alignment == "missing_comparison":
            status = "trace_incomplete"
            safe_next_step = "先补齐正式裁决、legacy 观测和 alignment，再进入替换评估。"
        elif legacy_state != "adopted_by_legacy" and formal_decision == "accepted":
            status = "accepted_but_unconsumed"
            safe_next_step = "确认 legacy 未消费是否符合预期，再决定是否加入 restore 消费候选。"
        else:
            status = "observed_only"
            safe_next_step = "继续观察，不改变运行行为。"
        traces.append(
            {
                "trace_id": f"restore-trace:{candidate_id}",
                "candidate_id": candidate_id,
                "candidate_type": candidate_type,
                "value": str(candidate.get("value") or ""),
                "source": str(candidate.get("source") or ""),
                "owner_module": str(candidate.get("owner_module") or ""),
                "formal_decision": formal_decision,
                "formal_reason": str(decision.get("reason") or ""),
                "formal_blockers": list(decision.get("blockers") or []),
                "legacy_state": legacy_state,
                "legacy_consumer": str(observation.get("legacy_consumer") or candidate.get("owner_module") or ""),
                "legacy_reason": str(observation.get("legacy_reason") or candidate.get("adoption_reason") or ""),
                "alignment": alignment,
                "replacement_point": replacement_point.get("domain", "unknown"),
                "runtime_owner": str(observation.get("runtime_owner") or replacement_point.get("legacy_owner") or ""),
                "target_owner": str(replacement_point.get("target_owner") or ""),
                "status": status,
                "safe_next_step": safe_next_step,
            }
        )

    trace_counts = _count_by_key(traces, "status")
    alignment_counts = _count_by_key(traces, "alignment")
    blockers = ["legacy_restore_still_executes"]
    if any(str(item.get("status") or "") in {"blocked_by_formal_rejection", "trace_incomplete"} for item in traces):
        blockers.append("restore_trace_not_ready")
    if not candidates:
        state = "no_candidates"
    elif "restore_trace_not_ready" in blockers:
        state = "needs_review"
    else:
        state = "trace_ready"
    return {
        "phase": "8B",
        "state": state,
        "mode": "diagnostic_only",
        "trace_count": len(traces),
        "traces": traces,
        "status_counts": trace_counts,
        "alignment_counts": alignment_counts,
        "replacement_point_counts": _count_by_key(traces, "replacement_point"),
        "blockers": sorted(set(blockers)),
        "takeover_allowed": False,
        "delete_allowed": False,
        "next_safe_step": "先让 restore adoption trace 在长场景中稳定；下一步才能做 shadow replacement，仍不允许直接删除旧链路。",
    }


def _restore_replacement_point_for_candidate(
    *,
    candidate_type: str,
    replacement_points: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized_type = str(candidate_type or "").strip()
    fallback = {
        "domain": "current_turn_override_guard",
        "legacy_owner": "query.planner/runtime_context_state",
        "target_owner": "orchestration.intent_frame",
    }
    for point in replacement_points:
        point_types = {str(item) for item in list(point.get("candidate_types") or [])}
        if normalized_type in point_types:
            return point
    if normalized_type in {"session_state", "durable_memory"}:
        return {
            "domain": "memory_restore",
            "legacy_owner": "understanding.memory_intent / backend/memory/*",
            "target_owner": "orchestration.restore_adoption + MemoryPolicy",
        }
    if normalized_type in {"target_handle", "upstream_object_handle", "upstream_result_handle", "restore_index"}:
        return {
            "domain": "context_handle_restore",
            "legacy_owner": "query.runtime_context_state / query.continuation_resolver / query.runtime_followup",
            "target_owner": "orchestration.restore_adoption + ContextPolicy",
        }
    return fallback


def _restore_formal_adoption_review(
    *,
    candidates: list[dict[str, Any]],
    intent_frame: IntentFrame,
) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    legacy_observations: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    for candidate in candidates:
        validation = _memory_context_validation(candidate=candidate, intent_frame=intent_frame)
        blockers: list[str] = []
        if validation["status"] == "blocked":
            blockers.append("memory_context_validator_blocked")
        if bool(candidate.get("can_override_current_intent")):
            blockers.append("current_intent_override_detected")
        if not str(candidate.get("owner_module") or "").strip():
            blockers.append("candidate_missing_owner")
        if not str(candidate.get("adoption_reason") or "").strip():
            blockers.append("candidate_missing_adoption_reason")
        if not str(intent_frame.intent or "").strip():
            blockers.append("intent_frame_missing")
        unique_blockers = sorted(set(blockers))
        formal_decision = "rejected" if unique_blockers else "accepted"
        candidate_id = str(candidate.get("candidate_id") or "")
        legacy_state = str(candidate.get("adoption_state") or "observed")
        legacy_reason = str(candidate.get("adoption_reason") or "")
        legacy_consumer = str(candidate.get("owner_module") or "")
        decisions.append(
            {
                "candidate_id": candidate_id,
                "candidate_type": str(candidate.get("candidate_type") or ""),
                "value": str(candidate.get("value") or ""),
                "owner_module": legacy_consumer,
                "decision": formal_decision,
                "reason": "restore_candidate_formally_valid" if formal_decision == "accepted" else "restore_candidate_formally_rejected",
                "blockers": unique_blockers,
                "memory_context_validation": validation,
                "validator": "phase8a_restore_formal_adoption",
            }
        )
        legacy_observations.append(
            {
                "candidate_id": candidate_id,
                "candidate_type": str(candidate.get("candidate_type") or ""),
                "legacy_state": legacy_state,
                "legacy_consumer": legacy_consumer,
                "legacy_reason": legacy_reason,
                "runtime_owner": "query.runtime_context_state/query.planner",
            }
        )
        if legacy_state == "adopted_by_legacy" and formal_decision == "accepted":
            alignment = "legacy_matches_formal_acceptance"
        elif legacy_state == "adopted_by_legacy" and formal_decision == "rejected":
            alignment = "legacy_over_adopts_rejected_candidate"
        elif legacy_state != "adopted_by_legacy" and formal_decision == "accepted":
            alignment = "formal_accepts_unconsumed_candidate"
        else:
            alignment = "observed"
        comparisons.append(
            {
                "candidate_id": candidate_id,
                "candidate_type": str(candidate.get("candidate_type") or ""),
                "legacy_state": legacy_state,
                "formal_decision": formal_decision,
                "alignment": alignment,
                "legacy_reason": legacy_reason,
                "formal_blockers": unique_blockers,
            }
        )

    accepted_count = sum(1 for item in decisions if str(item.get("decision") or "") == "accepted")
    rejected_count = sum(1 for item in decisions if str(item.get("decision") or "") == "rejected")
    blockers = ["legacy_restore_still_executes"]
    if rejected_count:
        blockers.append("formal_rejections_present")
    if any(str(item.get("alignment") or "") == "legacy_over_adopts_rejected_candidate" for item in comparisons):
        blockers.append("legacy_over_adopts_rejected_candidate")
    if not candidates:
        state = "no_candidates"
    elif rejected_count:
        state = "needs_review"
    else:
        state = "candidate_decisions_ready"
    return {
        "phase": "8A",
        "state": state,
        "mode": "diagnostic_only",
        "candidate_count": len(candidates),
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "decisions": decisions,
        "legacy_observations": legacy_observations,
        "comparison": {
            "mode": "diagnostic_only",
            "items": comparisons,
            "alignment_counts": _count_by_key(comparisons, "alignment"),
        },
        "blockers": sorted(set(blockers)),
        "delete_allowed": False,
        "takeover_allowed": False,
        "next_safe_step": "先用正式裁决对照 legacy 采用原因；全部稳定后再替换 legacy restore 消费入口。",
    }


def _restore_dry_run_comparison(
    *,
    candidates: list[dict[str, Any]],
    adoption_decisions: list[dict[str, Any]],
    cutover_plan: dict[str, Any],
) -> dict[str, Any]:
    decision_by_id = {
        str(item.get("candidate_id") or ""): item
        for item in adoption_decisions
        if str(item.get("candidate_id") or "").strip()
    }
    comparisons: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        legacy_state = str(candidate.get("adoption_state") or "observed")
        decision = dict(decision_by_id.get(candidate_id) or {})
        planned_decision = str(decision.get("decision") or "missing")
        if legacy_state == "adopted_by_legacy" and planned_decision == "blocked":
            alignment = "expected_legacy_delta"
        elif legacy_state == "adopted_by_legacy" and planned_decision == "accepted":
            alignment = "ready_to_compare_output"
        elif planned_decision == "missing":
            alignment = "missing_planned_decision"
        else:
            alignment = "observed"
        comparisons.append(
            {
                "candidate_id": candidate_id,
                "candidate_type": str(candidate.get("candidate_type") or ""),
                "value": str(candidate.get("value") or ""),
                "legacy_state": legacy_state,
                "planned_decision": planned_decision,
                "alignment": alignment,
                "decision_reason": str(decision.get("reason") or ""),
                "decision_blockers": list(decision.get("blockers") or []),
            }
        )

    delta_count = sum(1 for item in comparisons if str(item.get("alignment") or "") == "expected_legacy_delta")
    missing_decision_count = sum(1 for item in comparisons if str(item.get("alignment") or "") == "missing_planned_decision")
    blockers = ["legacy_restore_still_executes"]
    if delta_count:
        blockers.append("legacy_adoption_differs_from_orchestration_decision")
    if missing_decision_count:
        blockers.append("restore_candidate_missing_adoption_decision")
    cutover_state = str(cutover_plan.get("state") or "")
    if cutover_state != "ready_for_dry_run":
        blockers.append(f"cutover_plan:{cutover_state or 'missing'}")
    unique_blockers = sorted(set(blockers))
    return {
        "phase": "7H",
        "state": "observed_delta" if delta_count else ("blocked" if unique_blockers else "aligned"),
        "mode": "dry_run_only",
        "comparison_count": len(comparisons),
        "delta_count": delta_count,
        "missing_decision_count": missing_decision_count,
        "legacy_adopted_count": sum(1 for item in candidates if str(item.get("adoption_state") or "") == "adopted_by_legacy"),
        "planned_blocked_count": sum(1 for item in adoption_decisions if str(item.get("decision") or "") == "blocked"),
        "comparisons": comparisons,
        "blockers": unique_blockers,
        "next_safe_step": "先让 dry-run delta 在长场景中稳定可解释，再替换 legacy restore 消费入口。",
    }


def _restore_cutover_plan(
    *,
    candidates: list[dict[str, Any]],
    adoption_gate: dict[str, Any],
) -> dict[str, Any]:
    candidate_types = sorted(
        {
            str(candidate.get("candidate_type") or "")
            for candidate in candidates
            if str(candidate.get("candidate_type") or "").strip()
        }
    )
    owner_modules = sorted(
        {
            str(candidate.get("owner_module") or "")
            for candidate in candidates
            if str(candidate.get("owner_module") or "").strip()
        }
    )
    required_replacement_points = [
        {
            "domain": "memory_restore",
            "legacy_owner": "understanding.memory_intent / backend/memory/*",
            "target_owner": "orchestration.restore_adoption + MemoryPolicy",
            "candidate_types": [item for item in candidate_types if item in {"session_state", "durable_memory"}],
        },
        {
            "domain": "context_handle_restore",
            "legacy_owner": "query.runtime_context_state / query.continuation_resolver / query.runtime_followup",
            "target_owner": "orchestration.restore_adoption + ContextPolicy",
            "candidate_types": [
                item
                for item in candidate_types
                if item in {"target_handle", "upstream_object_handle", "upstream_result_handle", "restore_index"}
            ],
        },
        {
            "domain": "current_turn_override_guard",
            "legacy_owner": "query.planner/runtime_context_state",
            "target_owner": "orchestration.intent_frame",
            "candidate_types": list(candidate_types),
        },
    ]
    blockers = ["legacy_restore_still_executes"]
    gate_state = str(adoption_gate.get("state") or "")
    if gate_state != "ready":
        blockers.append(f"adoption_gate:{gate_state or 'missing'}")
    if candidates and not owner_modules:
        blockers.append("candidate_owner_missing")
    unique_blockers = sorted(set(blockers))
    return {
        "phase": "7H",
        "state": "blocked" if unique_blockers else "ready_for_dry_run",
        "mode": "diagnostic_only",
        "candidate_types": candidate_types,
        "owner_modules": owner_modules,
        "required_replacement_points": required_replacement_points,
        "blockers": unique_blockers,
        "delete_allowed": False,
        "next_safe_step": "先实现 restore adoption 的 dry-run 裁决与 legacy 消费点对照；在报告稳定前不得删除旧恢复链路。",
    }


def _restore_adoption_decisions(
    *,
    candidates: list[dict[str, Any]],
    intent_frame: IntentFrame,
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for candidate in candidates:
        memory_context_validation = _memory_context_validation(candidate=candidate, intent_frame=intent_frame)
        blockers = ["legacy_restore_still_executes"]
        if memory_context_validation["status"] == "blocked":
            blockers.append("memory_context_validator_blocked")
        if str(candidate.get("adoption_state") or "") == "adopted_by_legacy":
            blockers.append("candidate_still_adopted_by_legacy")
        if bool(candidate.get("can_override_current_intent")):
            blockers.append("current_intent_override_detected")
        if not str(candidate.get("owner_module") or "").strip():
            blockers.append("candidate_missing_owner")
        if not str(candidate.get("adoption_reason") or "").strip():
            blockers.append("candidate_missing_adoption_reason")
        if not str(intent_frame.intent or "").strip():
            blockers.append("intent_frame_missing")
        unique_blockers = sorted(set(blockers))
        decisions.append(
            {
                "candidate_id": str(candidate.get("candidate_id") or ""),
                "candidate_type": str(candidate.get("candidate_type") or ""),
                "value": str(candidate.get("value") or ""),
                "owner_module": str(candidate.get("owner_module") or ""),
                "decision": "blocked" if unique_blockers else "accepted",
                "reason": "restore_adoption_blocked_by_legacy" if unique_blockers else "restore_candidate_validated",
                "blockers": unique_blockers,
                "can_override_current_intent": False,
                "memory_context_validation": memory_context_validation,
                "validator": "phase7g_restore_adoption_preview",
            }
        )
    return decisions


def _memory_context_validation(*, candidate: dict[str, Any], intent_frame: IntentFrame) -> dict[str, Any]:
    candidate_type = str(candidate.get("candidate_type") or "").strip()
    value = str(candidate.get("value") or "").strip()
    owner_module = str(candidate.get("owner_module") or "").strip()
    source = str(candidate.get("source") or "").strip()
    ref = dict(candidate.get("ref") or {})
    blockers: list[str] = []
    checked_rules = [
        "candidate_has_type",
        "candidate_has_value",
        "candidate_has_owner",
        "candidate_cannot_override_current_intent",
        "candidate_matches_memory_or_context_shape",
    ]

    if not candidate_type:
        blockers.append("missing_candidate_type")
    if not value:
        blockers.append("missing_candidate_value")
    if not owner_module:
        blockers.append("missing_owner_module")
    if bool(candidate.get("can_override_current_intent")):
        blockers.append("current_intent_override_not_allowed")
    if not str(intent_frame.intent or "").strip():
        blockers.append("missing_intent_frame")

    if candidate_type in {"session_state", "durable_memory"}:
        if source != "memory_policy":
            blockers.append("memory_candidate_source_mismatch")
        if owner_module != "understanding.memory_intent":
            blockers.append("memory_candidate_owner_mismatch")
    elif candidate_type == "target_handle":
        if ":" not in value and not str(ref.get("handle_kind") or "").strip():
            blockers.append("target_handle_missing_kind")
        if owner_module not in {"query.runtime_context_state", "query.context_management", "query.continuation_resolver"}:
            blockers.append("target_handle_owner_mismatch")
    elif candidate_type in {"upstream_object_handle", "upstream_result_handle", "restore_index"}:
        if owner_module != "query.context_management":
            blockers.append("context_candidate_owner_mismatch")
    elif candidate_type:
        blockers.append(f"unknown_candidate_type:{candidate_type}")

    unique_blockers = sorted(set(blockers))
    return {
        "phase": "7G",
        "status": "blocked" if unique_blockers else "passed",
        "checked_rules": checked_rules,
        "blockers": unique_blockers,
        "intent_route": intent_frame.route,
        "intent_source_kind": intent_frame.source_kind,
        "candidate_type": candidate_type,
        "owner_module": owner_module,
    }


def _restore_adoption_gate(
    *,
    candidates: list[dict[str, Any]],
    adoption_decisions: list[dict[str, Any]],
    intent_frame: IntentFrame,
) -> dict[str, Any]:
    blockers = ["legacy_restore_still_executes"]
    adopted_by_legacy_count = sum(
        1 for item in candidates if str(item.get("adoption_state") or "") == "adopted_by_legacy"
    )
    blocked_decision_count = sum(
        1 for item in adoption_decisions if str(item.get("decision") or "") == "blocked"
    )
    validator_blocked_count = sum(
        1
        for item in adoption_decisions
        if str((dict(item.get("memory_context_validation") or {})).get("status") or "") == "blocked"
    )
    if adopted_by_legacy_count:
        blockers.append("restore_candidates_still_adopted_by_legacy")
    if blocked_decision_count:
        blockers.append("restore_adoption_decisions_blocked")
    if validator_blocked_count:
        blockers.append("memory_context_validator_blocked")
    if any(bool(item.get("can_override_current_intent")) for item in candidates):
        blockers.append("current_intent_override_detected")
    missing_owner_count = sum(1 for item in candidates if not str(item.get("owner_module") or "").strip())
    if missing_owner_count:
        blockers.append("restore_candidate_missing_owner")
    if candidates and not str(intent_frame.route or "").strip():
        blockers.append("intent_frame_route_missing")
    unique_blockers = sorted(set(blockers))
    return {
        "phase": "7G",
        "state": "blocked" if unique_blockers else "ready",
        "reason": "restore_adoption_gate_blocked" if unique_blockers else "restore_adoption_gate_ready",
        "candidate_count": len(candidates),
        "adopted_by_legacy_count": adopted_by_legacy_count,
        "blocked_decision_count": blocked_decision_count,
        "validator_blocked_count": validator_blocked_count,
        "missing_owner_count": missing_owner_count,
        "current_turn_override_allowed": False,
        "blockers": unique_blockers,
        "required_controls": [
            "candidate_schema",
            "owner_module",
            "intent_override_guard",
            "adoption_reason",
            "legacy_consumption_replaced",
            "memory_context_validator",
        ],
        "next_safe_step": "只有当 legacy restore 不再消费候选，并且每个候选都有 owner、采用原因和 validator 结果后，才允许进入恢复接管。",
    }


def _restore_candidate_objects(
    *,
    memory_candidates: list[str],
    context_candidates: list[str],
    handle_candidates: list[str],
    executions: list[Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_candidate(
        *,
        source: str,
        owner_module: str,
        candidate_type: str,
        value: str,
        execution_id: str = "",
        adoption_reason: str = "",
        ref: dict[str, Any] | None = None,
    ) -> None:
        normalized_value = str(value or "").strip()
        if not normalized_value:
            return
        base_id = _restore_candidate_id(
            source=source,
            candidate_type=candidate_type,
            value=normalized_value,
            execution_id=execution_id,
        )
        if base_id in seen:
            return
        seen.add(base_id)
        candidates.append(
            {
                "candidate_id": base_id,
                "source": source,
                "owner_module": owner_module,
                "candidate_type": candidate_type,
                "value": normalized_value,
                "ref": dict(ref or {}),
                "execution_id": execution_id,
                "adoption_state": "adopted_by_legacy",
                "adoption_reason": adoption_reason or "legacy_runtime_still_consumes_restore_candidate",
                "can_override_current_intent": False,
            }
        )

    for item in memory_candidates:
        candidate_type = "durable_memory" if item == "durable_memory" else "session_state"
        add_candidate(
            source="memory_policy",
            owner_module="understanding.memory_intent",
            candidate_type=candidate_type,
            value=item,
            adoption_reason="memory_intent_projected_from_legacy_plan",
            ref={"memory_candidate": item},
        )

    for index, execution in enumerate(executions, start=1):
        execution_id = str(
            getattr(execution, "subtask_id", "")
            or getattr(execution, "bundle_item_id", "")
            or "main"
        )
        target_kind = str(getattr(execution, "target_handle_kind", "") or "")
        target_id = str(getattr(execution, "target_handle_id", "") or "")
        arbitration_reason = str(getattr(execution, "arbitration_reason", "") or "")
        owner_module = _restore_owner_from_arbitration(arbitration_reason)
        if target_kind and target_kind != "none" and target_id:
            handle_value = target_id if target_id.startswith(f"{target_kind}:") else f"{target_kind}:{target_id}"
            add_candidate(
                source="execution_target_handle",
                owner_module=owner_module,
                candidate_type="target_handle",
                value=handle_value,
                execution_id=execution_id,
                adoption_reason=arbitration_reason or "legacy_execution_target_handle",
                ref={
                    "handle_kind": target_kind,
                    "handle_id": target_id,
                    "execution_index": index,
                    "arbitration_reason": arbitration_reason,
                },
            )
        for handle_id in list(getattr(execution, "upstream_object_handle_ids", []) or []):
            add_candidate(
                source="execution_upstream_object",
                owner_module="query.context_management",
                candidate_type="upstream_object_handle",
                value=str(handle_id),
                execution_id=execution_id,
                adoption_reason=arbitration_reason or "legacy_upstream_object_restore",
                ref={"execution_index": index, "arbitration_reason": arbitration_reason},
            )
        for handle_id in list(getattr(execution, "upstream_result_handle_ids", []) or []):
            add_candidate(
                source="execution_upstream_result",
                owner_module="query.context_management",
                candidate_type="upstream_result_handle",
                value=str(handle_id),
                execution_id=execution_id,
                adoption_reason=arbitration_reason or "legacy_upstream_result_restore",
                ref={"execution_index": index, "arbitration_reason": arbitration_reason},
            )

    known_context_values = {
        str(candidate.get("value") or "")
        for candidate in candidates
        if str(candidate.get("candidate_type") or "") in {"target_handle", "upstream_object_handle", "upstream_result_handle"}
    }
    for item in context_candidates:
        if item in known_context_values:
            continue
        add_candidate(
            source="context_policy",
            owner_module="query.context_management",
            candidate_type="restore_index",
            value=item,
            adoption_reason="context_policy_restore_index",
            ref={"restore_index": item},
        )
    for item in handle_candidates:
        if item in known_context_values:
            continue
        add_candidate(
            source="context_policy",
            owner_module="query.runtime_context_state",
            candidate_type="target_handle",
            value=item,
            adoption_reason="context_policy_required_handle",
            ref={"required_handle": item},
        )
    return candidates


def _restore_owner_from_arbitration(reason: str) -> str:
    normalized = str(reason or "").strip().lower()
    if "followup" in normalized or "binding" in normalized or "continuation" in normalized:
        return "query.continuation_resolver"
    if "context" in normalized or "handle" in normalized:
        return "query.context_management"
    return "query.runtime_context_state"


def _restore_candidate_id(*, source: str, candidate_type: str, value: str, execution_id: str) -> str:
    basis = "|".join([source, candidate_type, value, execution_id])
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]
    return f"restore:{candidate_type}:{digest}"


def _output_authority(
    *,
    answer_policy: AnswerPolicy,
    output_policy: OutputPolicyDecision,
    memory_policy: MemoryPolicy,
    topology: ExecutionTopology,
    executions: list[Any],
) -> dict[str, Any]:
    answer_channel = str(answer_policy.answer_channel or output_policy.answer_channel or "")
    writeback_scope = [
        str(item)
        for item in list(memory_policy.writeback_scope or [])
        if str(item).strip()
    ]
    fallback_allowed = bool(answer_policy.allow_fallback)
    persist_candidates: list[dict[str, Any]] = [
        {
            "candidate_id": "persist:session_transcript",
            "candidate_type": "session_transcript",
            "owner_module": "query.runtime/session_manager",
            "write_scope": "session_messages",
            "legacy_still_executes": True,
        }
    ]
    for scope in writeback_scope:
        persist_candidates.append(
            {
                "candidate_id": f"persist:{scope}",
                "candidate_type": scope,
                "owner_module": "backend/memory/*",
                "write_scope": scope,
                "legacy_still_executes": True,
            }
        )

    blockers = ["legacy_present_still_executes", "legacy_persist_still_executes"]
    if fallback_allowed:
        blockers.append("legacy_fallback_answer_allowed")
    if writeback_scope:
        blockers.append("memory_writeback_still_legacy")
    if str(topology.mode or "") in {"bundle_execution", "explicit_fanout"}:
        blockers.append("compound_answer_assembly_still_legacy")
    if any(str(getattr(item, "execution_kind", "") or "") == "worker" for item in executions):
        blockers.append("worker_result_boundary_still_legacy")

    cutover_plan = {
        "phase": "7I",
        "state": "blocked",
        "mode": "diagnostic_only",
        "delete_allowed": False,
        "required_replacement_points": [
            {
                "domain": "present",
                "legacy_owner": "query.output_boundary / query.output_classifier / query.answer_finalizer",
                "target_owner": "orchestration.answer_policy + output_boundary",
            },
            {
                "domain": "persist",
                "legacy_owner": "query.runtime / session_manager / backend/memory/*",
                "target_owner": "orchestration.answer_policy + MemoryPolicy",
            },
            {
                "domain": "fallback",
                "legacy_owner": "query.output_classifier / fallback_answer",
                "target_owner": "orchestration.answer_policy fallback gate",
            },
        ],
        "blockers": sorted(set(blockers)),
        "next_safe_step": "先把输出收口和写回权力保持诊断化；在 restore 接管前不得改动真实输出或持久化路径。",
    }
    return {
        "phase": "7I",
        "state": "candidate_projected",
        "canonical_owner": "orchestration.answer_policy",
        "candidate_owners": [
            "query.output_boundary",
            "query.output_classifier",
            "query.answer_finalizer",
            "query.runtime",
            "backend/memory/*",
        ],
        "runtime_owner": "query.runtime/output_boundary",
        "legacy_still_executes": True,
        "answer_channel": answer_channel,
        "require_citations": bool(answer_policy.require_citations),
        "hide_internal_protocol": bool(answer_policy.hide_internal_protocol),
        "allow_fallback": fallback_allowed,
        "memory_writeback_allowed": bool(answer_policy.memory_writeback_allowed),
        "writeback_scope": _dedupe(writeback_scope),
        "persist_candidates": persist_candidates,
        "present_controls": [
            "canonical_answer",
            "protocol_cleanup",
            "fallback_gate",
            "citation_policy",
        ],
        "persist_controls": [
            "session_message_write",
            "state_memory_write",
            "durable_memory_write",
            "task_summary_refs",
        ],
        "output_commit_gate": {
            "phase": "8L",
            "state": "commit_candidates_projected",
            "replacement_seam": "orchestration.output_commit.OutputCommitGate",
            "apply_mode": "legacy_runtime_apply",
            "candidate_types": [
                "state_memory_projection",
                "session_transcript",
                "post_turn_refresh",
            ],
            "takeover_allowed": False,
            "delete_allowed": False,
        },
        "cutover_plan": cutover_plan,
        "blockers": sorted(set(blockers)),
        "rule": "输出收口与状态写回仍由 legacy runtime 执行；编排层当前只声明 AnswerPolicy，不接管最终答案或持久化。",
    }


def _dispatch_authority(
    *,
    resource_policy: ResourcePolicy,
    execution_directives: list[ExecutionDirective],
    topology: ExecutionTopology,
    contract_previews: list[dict[str, Any]],
) -> dict[str, Any]:
    directive_items = [item.to_dict() for item in execution_directives]
    tool_count = len([item for item in directive_items if str(item.get("tool") or "").strip()])
    worker_count = len([item for item in directive_items if str(item.get("worker_route") or "").strip()])
    agent_count = len([item for item in directive_items if str(item.get("agent_id") or "").strip()])
    blockers = ["legacy_decide_still_executes", "legacy_execute_still_executes"]
    if tool_count:
        blockers.append("tool_selection_still_legacy")
    if worker_count:
        blockers.append("worker_selection_still_legacy")
    if agent_count:
        blockers.append("agent_dispatch_still_legacy")
    if resource_policy.blocked_tools:
        blockers.append("resource_policy_blocked_tools_present")
    if contract_previews:
        blockers.append("runtime_tool_bridge_still_gates")
    if str(topology.route or "") in {"tool", "worker", "bundle"}:
        blockers.append(f"route_requires_legacy_execution:{topology.route}")

    execution_targets = []
    for item in directive_items:
        execution_targets.append(
            {
                "execution_id": str(item.get("execution_id") or ""),
                "action": str(item.get("action") or ""),
                "tool": str(item.get("tool") or ""),
                "worker_route": str(item.get("worker_route") or ""),
                "agent_id": str(item.get("agent_id") or ""),
                "risk_tags": list(item.get("risk_tags") or []),
                "fallback": str(item.get("fallback") or "legacy_runtime"),
            }
        )

    cutover_plan = {
        "phase": "7J",
        "state": "blocked",
        "mode": "diagnostic_only",
        "delete_allowed": False,
        "required_replacement_points": [
            {
                "domain": "route_decision",
                "legacy_owner": "understanding.task_understanding / query.planner",
                "target_owner": "orchestration.intent_frame + ResourcePolicy",
            },
            {
                "domain": "tool_visibility",
                "legacy_owner": "query.runtime_tools / RuntimeToolBridge",
                "target_owner": "orchestration.resource_policy + tool contracts",
            },
            {
                "domain": "worker_agent_selection",
                "legacy_owner": "query.planner / evidence_orchestrator / worker plans",
                "target_owner": "orchestration.execution_directives + agent binding",
            },
            {
                "domain": "execution_entry",
                "legacy_owner": "query.runtime execution bus",
                "target_owner": "orchestration.runtime_adapter + PrimaryExecutionAdapter",
            },
        ],
        "blockers": sorted(set(blockers)),
        "next_safe_step": "先把 route/tool/worker/agent 的旧裁决权持续暴露在报告中；未通过 readiness 前不得扩大接管范围。",
    }
    return {
        "phase": "7J",
        "state": "candidate_projected",
        "canonical_owner": "orchestration.execution_directives",
        "candidate_owners": [
            "understanding.task_understanding",
            "query.planner",
            "query.runtime_tools",
            "query.evidence_orchestrator",
            "capabilities.manifest",
        ],
        "runtime_owner": "query.planner/query.runtime",
        "legacy_still_executes": True,
        "route": str(topology.route or ""),
        "execution_kind": str(topology.execution_kind or ""),
        "allowed_sources": list(resource_policy.allowed_sources or []),
        "allowed_tools": list(resource_policy.allowed_tools or []),
        "allowed_agents": list(resource_policy.allowed_agents or []),
        "allowed_workers": list(resource_policy.allowed_workers or []),
        "blocked_tools": list(resource_policy.blocked_tools or []),
        "directive_count": len(execution_directives),
        "tool_directive_count": tool_count,
        "worker_directive_count": worker_count,
        "agent_directive_count": agent_count,
        "execution_targets": execution_targets,
        "cutover_plan": cutover_plan,
        "blockers": sorted(set(blockers)),
        "rule": "理解层和操作系统只提供候选与资源边界；route/tool/worker/agent 的最终接管仍受 RuntimeControl、validator 和旧链路 fallback 保护。",
    }


def _memory_policy(execution: Any) -> MemoryPolicy:
    intent = getattr(execution, "memory_intent", None)
    read_mode = str(getattr(intent, "memory_read_mode", "") or "none")
    write_mode = str(getattr(intent, "memory_write_mode", "") or "none")
    restored_candidates = []
    if read_mode == "session_state":
        restored_candidates.append("session_state")
    if read_mode == "durable_exact":
        restored_candidates.append("durable_memory")
    writeback_scope = []
    if write_mode == "session_state":
        writeback_scope.append("state_memory")
    if write_mode == "durable_fact":
        writeback_scope.append("durable_memory")
    return MemoryPolicy(
        read_mode=read_mode,
        write_mode=write_mode,
        use_session_state=read_mode == "session_state",
        use_durable_memory=read_mode == "durable_exact",
        ignore_memory=bool(getattr(intent, "ignore_memory", False)),
        restored_candidates=restored_candidates,
        writeback_scope=writeback_scope,
        refs={"owner_module": "understanding.memory_intent"},
    )


def _context_policy(*, query_plan: Any, executions: list[Any]) -> ContextPolicyDecision:
    required_handles: list[str] = []
    restore_indexes: list[str] = []
    for execution in executions:
        target_kind = str(getattr(execution, "target_handle_kind", "") or "")
        target_id = str(getattr(execution, "target_handle_id", "") or "")
        if target_kind and target_kind != "none" and target_id:
            required_handles.append(target_id if target_id.startswith(f"{target_kind}:") else f"{target_kind}:{target_id}")
        restore_indexes.extend(str(item) for item in list(getattr(execution, "upstream_object_handle_ids", []) or []) if str(item).strip())
        restore_indexes.extend(str(item) for item in list(getattr(execution, "upstream_result_handle_ids", []) or []) if str(item).strip())
    prompt_sections = ["soul", "skill", "state"]
    if any(getattr(execution, "evidence_envelope", None) is not None for execution in executions):
        prompt_sections.append("evidence")
    if getattr(query_plan, "active_skill", None) is not None or any(getattr(item, "active_skill", None) is not None for item in executions):
        prompt_sections.append("active_skill")
    return ContextPolicyDecision(
        mode="runtime",
        summary="上下文压缩、状态记忆、长期记忆和证据装配仍由 runtime 执行；编排层只声明本轮需要的上下文约束。",
        required_handles=_dedupe(required_handles),
        evidence_budget="normal",
        prompt_sections=_dedupe(prompt_sections),
        restore_indexes=_dedupe(restore_indexes),
        refs={"runtime_stage": "query.context_compaction"},
    )


def _resource_policy(
    *,
    query_plan: Any,
    executions: list[Any],
    contract_previews: list[dict[str, Any]],
) -> ResourcePolicy:
    raw_policy = getattr(query_plan, "search_policy", None)
    source_policy = [str(item) for item in list(raw_policy or []) if str(item).strip()] if raw_policy is not None else None
    inferred_sources: list[str] = []
    allowed_tools: list[str] = []
    allowed_skills: list[str] = []
    allowed_agents: list[str] = []
    allowed_workers: list[str] = []
    blocked_tools: list[str] = []
    for execution in executions:
        understanding = getattr(execution, "query_understanding", None)
        tool_name = str(getattr(understanding, "tool_name", "") or "")
        candidate_tools = [str(item) for item in list(getattr(understanding, "candidate_tools", []) or []) if str(item).strip()]
        inferred_sources.extend(_source_needs(understanding=understanding, candidate_tools=candidate_tools + ([tool_name] if tool_name else [])))
        allowed_tools.extend(str(item) for item in list(getattr(understanding, "candidate_tools", []) or []) if str(item).strip())
        if tool_name:
            allowed_tools.append(tool_name)
        active_skill = getattr(execution, "active_skill", None)
        skill_name = str(getattr(active_skill, "name", "") or getattr(understanding, "skill_name", "") or "")
        if skill_name:
            allowed_skills.append(skill_name)
        allowed_tools.extend(_tool_scope_names(active_skill))
        worker_plan = getattr(execution, "worker_plan", None)
        worker_route = str(getattr(worker_plan, "worker_route", "") or "")
        if worker_route:
            allowed_workers.append(worker_route)
            agent_id = AGENT_ID_BY_WORKER_ROUTE.get(worker_route)
            if agent_id:
                allowed_agents.append(agent_id)
        elif str(getattr(execution, "execution_kind", "") or "") == "agent":
            allowed_agents.append(MAIN_AGENT_ID)
        signals = getattr(understanding, "structural_signals", None)
        if isinstance(signals, dict):
            blocked_tools.extend(str(item) for item in list(signals.get("search_policy_blocked_tools") or []) if str(item).strip())
    for preview in contract_previews:
        tool_name = str(preview.get("tool_name") or "")
        if tool_name:
            allowed_tools.append(tool_name)
            source = _tool_source(tool_name)
            if source:
                inferred_sources.append(source)
    return ResourcePolicy(
        allowed_sources=_expand_allowed_sources(source_policy, inferred_sources=inferred_sources),
        allowed_skills=_dedupe(allowed_skills),
        allowed_tools=_dedupe(allowed_tools),
        allowed_agents=_dedupe(allowed_agents),
        allowed_workers=_dedupe(allowed_workers),
        blocked_tools=_dedupe(blocked_tools),
        source_policy=source_policy,
        refs={"owner_module": "capabilities.manifest / query.planner.search_policy"},
    )


def _execution_directive(*, index: int, execution: Any) -> ExecutionDirective:
    understanding = getattr(execution, "query_understanding", None)
    worker_plan = getattr(execution, "worker_plan", None)
    worker_route = str(getattr(worker_plan, "worker_route", "") or "")
    tool_name = str(getattr(understanding, "tool_name", "") or "")
    active_skill = getattr(execution, "active_skill", None)
    execution_kind = str(getattr(execution, "execution_kind", "") or "agent")
    agent_id = AGENT_ID_BY_WORKER_ROUTE.get(worker_route, MAIN_AGENT_ID if execution_kind == "agent" else "")
    if worker_route:
        action = "delegate_agent"
    elif execution_kind == "direct_tool":
        action = "call_tool"
    else:
        action = "respond"
    return ExecutionDirective(
        step_id=f"step_{index}",
        action=action,
        execution_id=str(
            getattr(execution, "subtask_id", "")
            or getattr(execution, "bundle_item_id", "")
            or "main"
        ),
        skill=str(getattr(active_skill, "name", "") or getattr(understanding, "skill_name", "") or ""),
        tool=tool_name,
        agent_id=agent_id,
        worker_route=worker_route,
        input_summary=str(getattr(execution, "message", "") or ""),
        inputs=dict(getattr(execution, "tool_input", {}) or getattr(understanding, "tool_input", {}) or {}),
        risk_tags=_directive_risks(tool_name=tool_name, worker_route=worker_route),
        shared_channels=_shared_channels(execution),
        fallback="legacy_runtime",
        refs={"legacy_execution_kind": execution_kind},
    )


def _answer_policy(execution: Any) -> AnswerPolicy:
    understanding = getattr(execution, "query_understanding", None)
    memory_intent = getattr(execution, "memory_intent", None)
    route = str(getattr(understanding, "route", "") or "")
    task_kind = str(getattr(understanding, "task_kind", "") or "")
    return AnswerPolicy(
        require_citations=route == "rag" or task_kind in {"document_qa", "pdf_page_lookup", "knowledge_lookup"},
        hide_internal_protocol=True,
        allow_fallback=True,
        answer_channel="runtime_output_boundary",
        memory_writeback_allowed=str(getattr(memory_intent, "memory_write_mode", "") or "none") != "none",
        refs={"module": "query.output_boundary"},
    )


def _validation_decision(validation: dict[str, Any]) -> OrchestrationDecision:
    status = "blocked" if validation.get("status") == "blocked" else "selected"
    return OrchestrationDecision(
        node_id="plan-validator",
        node_type="validation_decision",
        owner_module="orchestration.validation",
        status=status,
        outputs=validation,
        reasons=list(validation.get("checked_rules") or []),
        risks=[str(item.get("code") or "") for item in list(validation.get("issues") or []) if isinstance(item, dict)],
    )


def _plan_id(*, session_id: str, message: str, query_plan: Any) -> str:
    basis = "|".join(
        [
            session_id,
            message,
            str(getattr(query_plan, "execution_mode", "") or ""),
            str(getattr(getattr(query_plan, "query_understanding", None), "route", "") or ""),
        ]
    )
    return f"orch:{hashlib.sha1(basis.encode('utf-8')).hexdigest()[:16]}"


def _execution_to_orchestration(*, index: int, execution: Any) -> OrchestrationExecution:
    understanding = getattr(execution, "query_understanding", None)
    worker_plan = getattr(execution, "worker_plan", None)
    worker_request = getattr(worker_plan, "request", None)
    binding = getattr(execution, "structured_binding", None)
    active_skill = getattr(execution, "active_skill", None)
    return OrchestrationExecution(
        execution_id=str(
            getattr(execution, "subtask_id", "")
            or getattr(execution, "bundle_item_id", "")
            or "main"
        ),
        message=str(getattr(execution, "message", "") or ""),
        route=str(getattr(understanding, "route", "") or "unknown"),
        execution_kind=str(getattr(execution, "execution_kind", "") or "agent"),
        skill_name=str(getattr(active_skill, "name", "") or getattr(understanding, "skill_name", "") or ""),
        tool_name=str(getattr(understanding, "tool_name", "") or ""),
        worker_route=str(getattr(worker_plan, "worker_route", "") or ""),
        tool_input=dict(getattr(execution, "tool_input", {}) or getattr(understanding, "tool_input", {}) or {}),
        worker_request=_to_dict(worker_request) if worker_request is not None else None,
        structured_binding=_to_dict(binding) if binding is not None else None,
        arbitration={
            "reason": str(getattr(execution, "arbitration_reason", "") or ""),
            "target_handle_kind": str(getattr(execution, "target_handle_kind", "") or "none"),
            "target_handle_id": str(getattr(execution, "target_handle_id", "") or ""),
        },
    )


def _input_decision(*, session_id: str, message: str, query_plan: Any) -> OrchestrationDecision:
    return OrchestrationDecision(
        node_id="input",
        node_type="input_signal",
        owner_module="query.runtime",
        status="selected",
        inputs={"message": message},
        outputs={
            "session_id": session_id,
            "history_count": len(list(getattr(query_plan, "history", []) or [])),
        },
        reasons=["request_received"],
    )


def _memory_decision(execution: Any) -> OrchestrationDecision:
    intent = getattr(execution, "memory_intent", None)
    return OrchestrationDecision(
        node_id="memory-intent",
        node_type="memory_intent",
        owner_module="understanding.memory_intent",
        status="selected",
        outputs={
            "intent": str(getattr(intent, "intent", "") or "general"),
            "read_mode": str(getattr(intent, "memory_read_mode", "") or "none"),
            "write_mode": str(getattr(intent, "memory_write_mode", "") or "none"),
            "ignore_memory": bool(getattr(intent, "ignore_memory", False)),
            "should_skip_rag": bool(getattr(intent, "should_skip_rag", False)),
        },
        reasons=["memory_intent_analyzed"],
    )


def _task_decision(understanding: Any) -> OrchestrationDecision:
    return OrchestrationDecision(
        node_id="task-understanding",
        node_type="task_understanding",
        owner_module="understanding.query_understanding",
        status="candidate",
        outputs={
            "authority": "candidate_only",
            "canonical_owner": "orchestration.intent_frame",
            "legacy_runtime_owner": "query.planner",
            "intent": str(getattr(understanding, "intent", "") or ""),
            "source_kind": str(getattr(understanding, "source_kind", "") or ""),
            "task_kind": str(getattr(understanding, "task_kind", "") or ""),
            "modality": str(getattr(understanding, "modality", "") or ""),
            "route": str(getattr(understanding, "route", "") or ""),
            "execution_posture": str(getattr(understanding, "execution_posture", "") or ""),
            "candidate_tools": list(getattr(understanding, "candidate_tools", []) or []),
            "capability_requests": list(getattr(understanding, "capability_requests", []) or []),
        },
        reasons=["phase7b_intent_candidate"] + [str(item) for item in list(getattr(understanding, "reasons", []) or [])],
    )


def _topology_decision(query_plan: Any, topology: ExecutionTopology) -> OrchestrationDecision:
    return OrchestrationDecision(
        node_id="execution-topology",
        node_type="execution_topology",
        owner_module="query.planner",
        status="selected",
        outputs=topology.to_dict(),
        reasons=[
            str(getattr(query_plan, "execution_mode", "") or "single_execution"),
            f"branch_count={topology.branch_count}",
        ],
    )


def _skill_decision(execution: Any) -> OrchestrationDecision:
    active_skill = getattr(execution, "active_skill", None)
    status = "selected" if active_skill is not None else "skipped"
    return OrchestrationDecision(
        node_id="skill-policy",
        node_type="skill_policy",
        owner_module="skill_system.policy",
        status=status,
        outputs={
            "skill_name": str(getattr(active_skill, "name", "") or ""),
            "skill_title": str(getattr(active_skill, "title", "") or ""),
            "tool_scope": _to_dict(active_skill.tool_scope()) if active_skill is not None and hasattr(active_skill, "tool_scope") else {},
        },
        reasons=["skill_policy_resolved"] if active_skill is not None else ["no_active_skill"],
    )


def _dispatch_decision(dispatch_plan: Any, understanding: Any) -> OrchestrationDecision:
    candidates = [
        _to_dict(candidate)
        for candidate in list(getattr(dispatch_plan, "tool_candidates", []) or [])
    ]
    selected_tool = getattr(dispatch_plan, "selected_tool_request", None)
    selected_worker = getattr(dispatch_plan, "selected_worker_request", None)
    return OrchestrationDecision(
        node_id="capability-dispatch",
        node_type="capability_dispatch",
        owner_module="query.capability_dispatch",
        status="selected" if dispatch_plan is not None else "skipped",
        inputs={
            "route": str(getattr(understanding, "route", "") or ""),
            "candidate_tools": list(getattr(understanding, "candidate_tools", []) or []),
        },
        outputs={
            "tool_candidates": candidates,
            "selected_tool": _to_dict(selected_tool) if selected_tool is not None else {},
            "selected_worker": _to_dict(selected_worker) if selected_worker is not None else {},
            "worker_route": str(getattr(dispatch_plan, "worker_route", "") or ""),
        },
        reasons=[str(item) for item in list(getattr(dispatch_plan, "reasons", []) or [])],
    )


def _contract_decision(contract_previews: list[dict[str, Any]]) -> OrchestrationDecision:
    blocked = [
        item for item in contract_previews
        if item.get("contract_action") not in {"allow", None, ""} or not bool(item.get("permission_allowed", True))
    ]
    status = "blocked" if blocked else ("selected" if contract_previews else "skipped")
    return OrchestrationDecision(
        node_id="contract-policy",
        node_type="tool_contract_preview",
        owner_module="tools.contracts / permissions",
        status=status,
        outputs={
            "contract_previews": contract_previews,
            "preview_count": len(contract_previews),
            "blocked_count": len(blocked),
        },
        reasons=[
            f"{item.get('tool_name')}: {item.get('contract_reason') or item.get('permission_reason') or item.get('contract_action')}"
            for item in blocked
        ] or (["contract_preview_resolved"] if contract_previews else ["no_candidate_tool"]),
    )


def _execution_decision(execution: Any, topology: ExecutionTopology) -> OrchestrationDecision:
    return OrchestrationDecision(
        node_id="execution",
        node_type="execution_landing",
        owner_module="query.runtime",
        status="selected",
        outputs={
            "execution_kind": topology.execution_kind,
            "route": topology.route,
            "tool_name": str(getattr(getattr(execution, "query_understanding", None), "tool_name", "") or ""),
            "worker_route": str(getattr(getattr(execution, "worker_plan", None), "worker_route", "") or ""),
        },
        reasons=[topology.reason] if topology.reason else [],
    )


def _safety_decision(warnings: list[str]) -> OrchestrationDecision:
    return OrchestrationDecision(
        node_id="safety",
        node_type="plan_safety",
        owner_module="orchestration",
        status="warning" if warnings else "selected",
        outputs={"mode": "plan_only", "warning_count": len(warnings)},
        reasons=["plan_only_no_behavior_change"],
        risks=warnings,
    )


def _prompt_policy(dispatch_plan: Any, execution: Any) -> PromptAssemblyDecision:
    prompt_exposure = getattr(dispatch_plan, "prompt_exposure", None)
    active_skill = getattr(execution, "active_skill", None)
    return PromptAssemblyDecision(
        mode="runtime",
        active_skill_name=str(
            getattr(prompt_exposure, "active_skill_name", "")
            or getattr(active_skill, "name", "")
            or ""
        ),
        tool_schema_names=[
            str(item)
            for item in list(getattr(prompt_exposure, "tool_schema_names", []) or [])
            if str(item).strip()
        ],
        refs={"module": "query.prompt_builder"},
    )


def _source_needs(*, understanding: Any, candidate_tools: list[str]) -> list[str]:
    needs: list[str] = []
    source_kind = str(getattr(understanding, "source_kind", "") or "")
    modality = str(getattr(understanding, "modality", "") or "")
    route = str(getattr(understanding, "route", "") or "")
    task_kind = str(getattr(understanding, "task_kind", "") or "")
    if route == "rag" or source_kind in {"knowledge_base", "rag"}:
        needs.append("rag")
    if source_kind in {"file", "local_file", "workspace"}:
        needs.append("local_files")
    if source_kind in {"web", "internet"}:
        needs.append("web")
    if modality in {"pdf", "document"} or "pdf" in task_kind or "document" in task_kind:
        needs.append("document")
    if modality in {"table", "data", "structured_data"} or "data" in task_kind:
        needs.append("data")
    for tool_name in candidate_tools:
        source = _tool_source(str(tool_name or ""))
        if source:
            needs.append(source)
    return _dedupe(needs or ["general"])


def _expand_allowed_sources(source_policy: list[str] | None, *, inferred_sources: list[str] | None = None) -> list[str]:
    if source_policy is None:
        allowed = set(_dedupe(list(inferred_sources or [])))
        if "local_files" in allowed:
            allowed.update({"document", "data"})
        allowed.add("general")
        return _dedupe(sorted(allowed))
    allowed = set(_dedupe(source_policy))
    expanded = set(allowed)
    if "local_files" in allowed:
        expanded.update({"document", "data"})
    expanded.add("general")
    return _dedupe(sorted(expanded))


def _tool_scope_names(active_skill: Any) -> list[str]:
    if active_skill is None:
        return []
    try:
        scope = active_skill.tool_scope()
    except Exception:
        return list(getattr(active_skill, "allowed_tools", []) or [])
    allowed = getattr(scope, "allowed_tools", None)
    return [str(item) for item in list(allowed or []) if str(item).strip()]


def _directive_risks(*, tool_name: str, worker_route: str) -> list[str]:
    risks: list[str] = []
    source = _tool_source(tool_name)
    if source in {"system_execution"}:
        risks.append("high_risk_tool")
    if source in {"web"}:
        risks.append("external_network")
    if worker_route:
        risks.append("delegated_execution")
    return _dedupe(risks)


def _shared_channels(execution: Any) -> list[str]:
    channels = ["trace"]
    if getattr(execution, "target_handle_id", ""):
        channels.append("state_memory")
    if getattr(execution, "evidence_envelope", None) is not None:
        channels.append("evidence")
    if getattr(execution, "artifact_graph_delta", None) is not None:
        channels.append("artifact_graph")
    return _dedupe(channels)


def _tool_source(tool_name: str) -> str:
    normalized = str(tool_name or "").strip()
    if normalized in {"search_knowledge"}:
        return "rag"
    if normalized in {"search_files", "search_text", "read_file"}:
        return "local_files"
    if normalized in {"pdf_analysis", "analyze_multimodal_file"}:
        return "document"
    if normalized in {"structured_data_analysis"}:
        return "data"
    if normalized in {"web_search", "fetch_url", "get_weather", "get_gold_price"}:
        return "web"
    if normalized in {"terminal", "python_repl"}:
        return "system_execution"
    return ""


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _count_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _first_reason(understanding: Any) -> str:
    reasons = list(getattr(understanding, "reasons", []) or [])
    return str(reasons[0]) if reasons else ""


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        return dict(payload) if isinstance(payload, dict) else {"value": payload}
    try:
        payload = asdict(value)
        return dict(payload) if isinstance(payload, dict) else {"value": payload}
    except TypeError:
        if isinstance(value, dict):
            return dict(value)
        return {"value": str(value)}
