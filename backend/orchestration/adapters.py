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
    memory_policy = _memory_policy(primary_execution)
    context_policy = _context_policy(query_plan=query_plan, executions=executions)
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
        output_policy=OutputPolicyDecision(
            mode="runtime",
            answer_channel="runtime_output_boundary",
            refs={"module": "query.output_boundary"},
        ),
        safety=SafetyDecision(mode=normalized_mode, warnings=warning_items, risks=[]),
        diagnostics={
            "legacy_plan_type": type(query_plan).__name__,
            "legacy_execution_count": len(executions),
            "plan_compatible": True,
            "contract_preview_count": len(contract_preview_items),
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
        refs={"owner_module": "understanding.query_understanding"},
    )


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
