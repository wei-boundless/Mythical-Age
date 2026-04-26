from __future__ import annotations

from typing import Any

from orchestration.behavior_models import BehaviorDecisionEdge, BehaviorDecisionNode


NODE_DEFS: tuple[tuple[str, str, str, str], ...] = (
    ("input", "用户输入", "接收本轮请求，并绑定 session 与历史上下文。", "api.chat / orchestration.dry_run"),
    ("memory-intent", "记忆意图", "判断本轮是否读取、写入、忽略或总结记忆。", "understanding.memory_intent"),
    ("task-understanding", "任务理解", "抽取任务类型、来源、模态、结构信号和候选能力。", "understanding.task_understanding"),
    ("continuation", "续接判断", "根据显式对象、历史对象和会话摘要意图修正当前任务。", "query.continuation_resolver"),
    ("execution-mode", "执行模式", "决定 single_execution、bundle_execution 或 explicit_fanout。", "query.planner"),
    ("skill-policy", "Skill 策略", "根据结构化任务帧选择当前行为包和工具范围。", "skill_system.policy"),
    ("context", "上下文策略", "读取状态记忆、长期记忆和上下文预算，决定模型可见内容。", "memory.facade / context_management"),
    ("capability", "能力调度", "决定候选工具、worker request 和 prompt 暴露方式。", "query.capability_dispatch"),
    ("contract", "契约预检", "预检工具输入、绑定对象、scope、permission 和安全标签。", "tools.contracts / permissions"),
    ("prompt", "Prompt 装配", "透明化静态、会话、turn、skill 与记忆 prompt 来源。", "query.prompt_builder"),
    ("execution", "执行落点", "说明本轮会进入模型、direct tool、worker 或 bundle 分支。", "query.runtime"),
    ("output", "输出策略", "说明最终回答会经过可见输出边界和持久化策略。", "query.output_boundary"),
)

EDGE_DEFS: tuple[tuple[str, str, str, str], ...] = (
    ("input-memory", "input", "memory-intent", "先判断记忆意图"),
    ("memory-task", "memory-intent", "task-understanding", "进入结构化任务理解"),
    ("task-continuation", "task-understanding", "continuation", "结合历史和显式对象修正"),
    ("continuation-mode", "continuation", "execution-mode", "确定执行拓扑"),
    ("mode-skill", "execution-mode", "skill-policy", "选择行为包"),
    ("skill-context", "skill-policy", "context", "按行为包和任务读取上下文"),
    ("context-capability", "context", "capability", "进入能力调度"),
    ("capability-contract", "capability", "contract", "预检工具和权限边界"),
    ("contract-prompt", "contract", "prompt", "装配模型可见内容"),
    ("prompt-execution", "prompt", "execution", "进入执行落点"),
    ("execution-output", "execution", "output", "收口为可见回答"),
)


def build_behavior_snapshot(
    *,
    source: str,
    session_id: str,
    message: str,
    plan: Any,
    execution: Any | None,
    skill_inspection: dict[str, Any] | None = None,
    context_preview: dict[str, Any] | None = None,
    prompt_manifest: dict[str, Any] | None = None,
    contract_previews: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    execution = execution or (plan.iter_executions()[0] if plan.iter_executions() else None)
    understanding = getattr(execution, "query_understanding", None) or getattr(plan, "query_understanding", None)
    dispatch_plan = getattr(execution, "dispatch_plan", None) or getattr(plan, "dispatch_plan", None)
    contract_previews = list(contract_previews or [])
    prompt_manifest = dict(prompt_manifest or {})
    context_preview = dict(context_preview or {})
    skill_inspection = dict(skill_inspection or {})
    warning_items = [str(item) for item in list(warnings or []) if str(item or "").strip()]

    node_payloads = [
        _node(node_id, label, description, module, index + 1)
        for index, (node_id, label, description, module) in enumerate(NODE_DEFS)
    ]
    by_id = {node.id: node for node in node_payloads}

    _fill_input(by_id["input"], session_id=session_id, message=message, plan=plan)
    _fill_memory_intent(by_id["memory-intent"], execution)
    _fill_task_understanding(by_id["task-understanding"], understanding)
    _fill_continuation(by_id["continuation"], understanding)
    _fill_execution_mode(by_id["execution-mode"], plan)
    _fill_skill_policy(by_id["skill-policy"], execution, skill_inspection)
    _fill_context(by_id["context"], context_preview)
    _fill_capability(by_id["capability"], dispatch_plan, understanding)
    _fill_contract(by_id["contract"], contract_previews)
    _fill_prompt(by_id["prompt"], prompt_manifest, execution)
    _fill_execution(by_id["execution"], plan, execution)
    _fill_output(by_id["output"], execution)

    if warning_items:
        by_id["output"].status = "warning"
        by_id["output"].reasons.extend(warning_items)

    problem_node_id = _problem_node_id(contract_previews, warning_items)
    nodes = [node.to_dict() for node in node_payloads]
    return {
        "source": source,
        "session_id": session_id,
        "run_id": "",
        "turn_id": "",
        "turn_index": 0,
        "execution_mode": str(getattr(plan, "execution_mode", "") or "unknown"),
        "route": str(getattr(understanding, "route", "") or "unknown"),
        "status": "warning" if warning_items or problem_node_id else "success",
        "summary": _summary(plan, execution, contract_previews, warning_items),
        "problem_node_id": problem_node_id,
        "nodes": nodes,
        "edges": [_edge(edge_id, source_id, target_id, label).to_dict() for edge_id, source_id, target_id, label in EDGE_DEFS],
        "events": [],
        "artifacts": {
            "prompt_manifest_id": str(prompt_manifest.get("prompt_id") or ""),
        },
        "decision_trace": {
            "skill_policy": skill_inspection,
            "context_preview": context_preview,
            "prompt_manifest": prompt_manifest,
            "contract_previews": contract_previews,
            "warnings": warning_items,
        },
    }


def _node(node_id: str, label: str, description: str, module: str, index: int) -> BehaviorDecisionNode:
    return BehaviorDecisionNode(
        id=node_id,
        index=index,
        label=label,
        description=description,
        status="success",
        source_module=module,
    )


def _edge(edge_id: str, source: str, target: str, label: str) -> BehaviorDecisionEdge:
    return BehaviorDecisionEdge(id=edge_id, from_node=source, to=target, label=label, summary=label)


def _fill_input(node: BehaviorDecisionNode, *, session_id: str, message: str, plan: Any) -> None:
    history = list(getattr(plan, "history", []) or [])
    node.summary = f"session={session_id or '-'} / history={len(history)} / input={_clip(message, 96)}"
    node.inputs = {"message": message, "history_count": len(history)}
    node.outputs = {"session_id": session_id}


def _fill_memory_intent(node: BehaviorDecisionNode, execution: Any) -> None:
    intent = getattr(execution, "memory_intent", None)
    node.summary = (
        f"intent={getattr(intent, 'intent', 'general')} / "
        f"read={getattr(intent, 'memory_read_mode', 'none')} / "
        f"write={getattr(intent, 'memory_write_mode', 'none')}"
    )
    node.outputs = {
        "intent": getattr(intent, "intent", "general"),
        "read_mode": getattr(intent, "memory_read_mode", "none"),
        "write_mode": getattr(intent, "memory_write_mode", "none"),
        "ignore_memory": bool(getattr(intent, "ignore_memory", False)),
        "should_skip_rag": bool(getattr(intent, "should_skip_rag", False)),
    }


def _fill_task_understanding(node: BehaviorDecisionNode, understanding: Any) -> None:
    reasons = list(getattr(understanding, "reasons", []) or [])
    node.summary = (
        f"route={getattr(understanding, 'route', 'unknown')} / "
        f"posture={getattr(understanding, 'execution_posture', '-')} / "
        f"task={getattr(understanding, 'task_kind', '-')}"
    )
    node.reasons = [str(item) for item in reasons]
    node.outputs = {
        "intent": getattr(understanding, "intent", ""),
        "source_kind": getattr(understanding, "source_kind", ""),
        "task_kind": getattr(understanding, "task_kind", ""),
        "modality": getattr(understanding, "modality", ""),
        "route": getattr(understanding, "route", ""),
        "execution_posture": getattr(understanding, "execution_posture", ""),
        "capability_requests": list(getattr(understanding, "capability_requests", []) or []),
        "candidate_tools": list(getattr(understanding, "candidate_tools", []) or []),
        "structural_signals": dict(getattr(understanding, "structural_signals", {}) or {}),
    }


def _fill_continuation(node: BehaviorDecisionNode, understanding: Any) -> None:
    direct_reason = str(getattr(understanding, "direct_route_reason", "") or "")
    reasons = list(getattr(understanding, "reasons", []) or [])
    continuation_reasons = [
        str(item)
        for item in reasons
        if "followup" in str(item).lower() or "context" in str(item).lower() or "session_summary" in str(item).lower()
    ]
    node.summary = direct_reason or (", ".join(continuation_reasons) if continuation_reasons else "没有续接修正，沿用任务理解结果。")
    node.reasons = continuation_reasons or ([direct_reason] if direct_reason else [])
    node.status = "visited" if not node.reasons else "success"


def _fill_execution_mode(node: BehaviorDecisionNode, plan: Any) -> None:
    subqueries = list(getattr(plan, "subqueries", []) or [])
    bundle_plan = getattr(plan, "bundle_plan", None)
    node.summary = f"mode={getattr(plan, 'execution_mode', 'unknown')} / subqueries={len(subqueries)}"
    node.outputs = {
        "execution_mode": getattr(plan, "execution_mode", ""),
        "subqueries": subqueries,
        "bundle_items": [
            {
                "item_id": getattr(item, "item_id", ""),
                "title": getattr(item, "user_visible_title", ""),
                "capability": getattr(item, "capability", ""),
            }
            for item in list(getattr(bundle_plan, "items", []) or [])
        ],
    }


def _fill_skill_policy(node: BehaviorDecisionNode, execution: Any, inspection: dict[str, Any]) -> None:
    selected = dict(inspection.get("selected") or {})
    active_skill = getattr(execution, "active_skill", None)
    name = selected.get("name") or getattr(active_skill, "name", "") or ""
    candidates = list(inspection.get("candidates") or [])
    node.summary = f"active_skill={name or '-'} / candidates={len(candidates)}"
    node.status = "visited" if not name else "success"
    node.reasons = [str(item) for item in list(selected.get("reasons") or inspection.get("reasons") or [])]
    node.outputs = {"selected": selected, "candidates": candidates}


def _fill_context(node: BehaviorDecisionNode, preview: dict[str, Any]) -> None:
    context = dict(preview.get("context_management") or {})
    session_memory = dict(preview.get("session_memory") or {})
    durable = dict(preview.get("durable_memory") or {})
    node.summary = (
        f"pressure={context.get('pressure_level', 'unknown')} / "
        f"session_present={bool(session_memory.get('present'))} / "
        f"durable_exact={len(list(durable.get('exact_matches') or []))}"
    )
    node.outputs = {
        "context_management": context,
        "session_memory": session_memory,
        "durable_memory": durable,
    }


def _fill_capability(node: BehaviorDecisionNode, dispatch_plan: Any, understanding: Any) -> None:
    candidates = [
        getattr(candidate, "name", "")
        for candidate in list(getattr(dispatch_plan, "tool_candidates", []) or [])
        if getattr(candidate, "name", "")
    ]
    worker = str(getattr(dispatch_plan, "worker_route", "") or "")
    selected_tool = str(getattr(getattr(dispatch_plan, "selected_tool_request", None), "tool_name", "") or "")
    node.summary = f"tool={selected_tool or '-'} / worker={worker or '-'} / candidates={', '.join(candidates) or '-'}"
    node.outputs = {
        "route": getattr(understanding, "route", ""),
        "tool_candidates": [
            candidate.to_dict() if hasattr(candidate, "to_dict") else {"name": getattr(candidate, "name", "")}
            for candidate in list(getattr(dispatch_plan, "tool_candidates", []) or [])
        ],
        "selected_tool_request": (
            dispatch_plan.selected_tool_request.to_dict()
            if getattr(dispatch_plan, "selected_tool_request", None) is not None
            else None
        ),
        "selected_worker_request": (
            dispatch_plan.selected_worker_request.to_dict()
            if getattr(dispatch_plan, "selected_worker_request", None) is not None
            and hasattr(dispatch_plan.selected_worker_request, "to_dict")
            else None
        ),
        "reasons": list(getattr(dispatch_plan, "reasons", []) or []),
    }
    node.reasons = list(getattr(dispatch_plan, "reasons", []) or [])


def _fill_contract(node: BehaviorDecisionNode, previews: list[dict[str, Any]]) -> None:
    blocked = [
        item
        for item in previews
        if item.get("contract_action") not in {"allow", None} or not bool(item.get("permission_allowed", True))
    ]
    if not previews:
        node.summary = "本轮没有候选工具，契约预检跳过。"
        node.status = "skipped"
        return
    node.status = "blocked" if blocked else "success"
    node.summary = f"preview={len(previews)} / blocked={len(blocked)}"
    node.outputs = {"contract_previews": previews}
    node.reasons = [
        f"{item.get('tool_name')}: {item.get('contract_reason') or item.get('permission_reason')}"
        for item in blocked
    ]


def _fill_prompt(node: BehaviorDecisionNode, manifest: dict[str, Any], execution: Any) -> None:
    if not manifest:
        if getattr(execution, "execution_kind", "") in {"direct_tool", "worker"}:
            node.status = "skipped"
            node.summary = f"{getattr(execution, 'execution_kind', '')} 分支通常不先装配模型主链 prompt。"
        else:
            node.status = "warning"
            node.summary = "dry-run 未生成 prompt manifest。"
        return
    node.summary = f"sections={manifest.get('total_sections', 0)} / chars={manifest.get('total_chars', 0)}"
    node.outputs = manifest


def _fill_execution(node: BehaviorDecisionNode, plan: Any, execution: Any) -> None:
    understanding = getattr(execution, "query_understanding", None)
    node.summary = (
        f"kind={getattr(execution, 'execution_kind', 'agent')} / "
        f"mode={getattr(plan, 'execution_mode', '')} / "
        f"route={getattr(understanding, 'route', '')}"
    )
    node.outputs = {
        "execution_kind": getattr(execution, "execution_kind", ""),
        "execution_posture": getattr(execution, "execution_posture", ""),
        "worker_route": getattr(getattr(execution, "worker_plan", None), "worker_route", ""),
    }


def _fill_output(node: BehaviorDecisionNode, execution: Any) -> None:
    node.summary = "真实执行时会通过 output boundary、answer source 和 persistence gate 收口。"
    node.outputs = {
        "expected_boundary": "AssistantOutputBoundary / RuntimeOutputPolicy",
        "dry_run": True,
        "will_persist": False,
        "execution_kind": getattr(execution, "execution_kind", ""),
    }


def _summary(plan: Any, execution: Any, contract_previews: list[dict[str, Any]], warnings: list[str]) -> str:
    understanding = getattr(execution, "query_understanding", None)
    blocked = [
        item
        for item in contract_previews
        if item.get("contract_action") not in {"allow", None} or not bool(item.get("permission_allowed", True))
    ]
    parts = [
        f"dry-run 完成：route={getattr(understanding, 'route', 'unknown')}",
        f"mode={getattr(plan, 'execution_mode', 'unknown')}",
        f"kind={getattr(execution, 'execution_kind', 'agent')}",
    ]
    if blocked:
        parts.append(f"契约预检发现 {len(blocked)} 个阻断点")
    if warnings:
        parts.append(f"warnings={len(warnings)}")
    return " / ".join(parts)


def _problem_node_id(contract_previews: list[dict[str, Any]], warnings: list[str]) -> str:
    if any(
        item.get("contract_action") not in {"allow", None} or not bool(item.get("permission_allowed", True))
        for item in contract_previews
    ):
        return "contract"
    if warnings:
        return "output"
    return ""


def _clip(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"
