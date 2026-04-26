from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Any

from orchestration.models import (
    ContextPolicyDecision,
    ExecutionTopology,
    OrchestrationDecision,
    OrchestrationExecution,
    OrchestrationPlan,
    OutputPolicyDecision,
    PromptAssemblyDecision,
    SafetyDecision,
)


def build_shadow_orchestration_plan(
    *,
    session_id: str,
    message: str,
    query_plan: Any,
    source: str = "live-session",
    mode: str = "shadow",
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

    return OrchestrationPlan(
        plan_id=plan_id,
        session_id=session_id,
        input_text=message,
        source=source,
        mode=normalized_mode,
        behavior_policy_id=f"default:{normalized_mode}",
        topology=topology,
        decisions=decisions,
        executions=orchestration_executions,
        context_policy=ContextPolicyDecision(
            mode="runtime",
            summary="上下文压缩、状态记忆和长期记忆仍由 runtime 阶段执行；shadow plan 只声明控制点。",
            refs={"runtime_stage": "query.context_compaction"},
        ),
        prompt_policy=_prompt_policy(dispatch_plan, primary_execution),
        output_policy=OutputPolicyDecision(
            mode="runtime",
            answer_channel="runtime_output_boundary",
            refs={"module": "query.output_boundary"},
        ),
        safety=SafetyDecision(mode=normalized_mode, warnings=warning_items, risks=[]),
        diagnostics={
            "legacy_plan_type": type(query_plan).__name__,
            "legacy_execution_count": len(executions),
            "shadow_compatible": True,
            "contract_preview_count": len(contract_preview_items),
        },
    )


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or "shadow").strip().lower()
    return normalized if normalized in {"legacy", "shadow", "primary"} else "shadow"


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
        status="selected",
        outputs={
            "intent": str(getattr(understanding, "intent", "") or ""),
            "source_kind": str(getattr(understanding, "source_kind", "") or ""),
            "task_kind": str(getattr(understanding, "task_kind", "") or ""),
            "modality": str(getattr(understanding, "modality", "") or ""),
            "route": str(getattr(understanding, "route", "") or ""),
            "execution_posture": str(getattr(understanding, "execution_posture", "") or ""),
            "candidate_tools": list(getattr(understanding, "candidate_tools", []) or []),
            "capability_requests": list(getattr(understanding, "capability_requests", []) or []),
        },
        reasons=[str(item) for item in list(getattr(understanding, "reasons", []) or [])],
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
        node_type="shadow_safety",
        owner_module="orchestration",
        status="warning" if warnings else "selected",
        outputs={"mode": "shadow", "warning_count": len(warnings)},
        reasons=["shadow_plan_no_behavior_change"],
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
