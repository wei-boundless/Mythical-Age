from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .primary_execution_adapter import PrimaryExecutionAdapter


LOW_RISK_PRIMARY_SOURCES = {"rag", "local_files", "document", "data", "general"}
LOW_RISK_TAKEOVER_SOURCES = {"rag", "local_files", "general"}
PHASE7_LEGACY_AUTHORITIES = (
    "backend/query/planner.py:route_execution_worker_tool",
    "backend/understanding/task_understanding.py:intent_route_tool_candidates",
    "backend/query/runtime_tools.py:model_visible_tool_scope",
    "backend/query/runtime.py:execution_bus_context_memory_output",
    "backend/query/output_classifier.py:final_output_fallback",
)
PHASE7_REQUIRED_CONTROLS = (
    "validation",
    "allowlist",
    "field_mismatch_guard",
    "entry_eligibility",
    "entry_selection",
    "primary_execution_preview",
    "primary_entry_takeover",
    "search_policy",
    "tool_contract",
    "agent_binding",
)
PHASE7_PROTECTED_LEGACY_MODULES = (
    "backend/query/planner.py",
    "backend/understanding/task_understanding.py",
    "backend/query/runtime_tools.py",
    "backend/query/output_classifier.py",
    "backend/query/runtime.py",
)
PHASE7_DESIGN_PRINCIPLE_DOCS = (
    "docs/设计原则/01-项目全景.md",
    "docs/设计原则/03-状态管理.md",
    "docs/设计原则/04-System-Prompt-工程.md",
    "docs/设计原则/05-对话循环.md",
    "docs/设计原则/06-上下文管理.md",
    "docs/设计原则/07-Prompt-Cache.md",
    "docs/设计原则/09-工具系统设计.md",
    "docs/设计原则/10-BashTool-深度剖析.md",
    "docs/设计原则/11-命令系统.md",
    "docs/设计原则/12-Agent-系统.md",
    "docs/设计原则/13-内置Agent设计模式.md",
    "docs/设计原则/14-任务系统.md",
    "docs/设计原则/15-MCP-协议实现.md",
    "docs/设计原则/16-权限系统.md",
    "docs/设计原则/17-Settings-系统.md",
    "docs/设计原则/19-Feature-Flag与编译期优化.md",
    "docs/设计原则/20-API调用与错误恢复.md",
    "docs/设计原则/23-Memory系统.md",
    "docs/设计原则/24-Skill-Plugin开发实战.md",
    "docs/设计原则/25-架构模式总结.md",
)
PHASE7_LEGACY_POWER_DOMAINS = (
    {
        "module": "backend/query/planner.py",
        "domains": ["decide", "execute"],
        "current_authority": "route / worker / tool / compound execution",
        "target": "legacy fallback 与 candidate projector",
    },
    {
        "module": "backend/understanding/task_understanding.py",
        "domains": ["restore", "decide"],
        "current_authority": "PDF / 文件 / 数据 / 联网 / FAQ 规则识别",
        "target": "IntentFrame 候选与风险信号",
    },
    {
        "module": "backend/query/runtime_tools.py",
        "domains": ["execute"],
        "current_authority": "bounded agent 与 direct tool 可见范围",
        "target": "读取 ResourcePolicy 的硬权限门",
    },
    {
        "module": "backend/query/runtime.py",
        "domains": ["execute", "persist"],
        "current_authority": "执行总线、memory/context 写回、output boundary",
        "target": "runtime executor 与集中状态写回点",
    },
    {
        "module": "backend/query/output_classifier.py",
        "domains": ["present", "persist"],
        "current_authority": "文本启发式答案/进度/工具声明判断",
        "target": "输出边界、协议清洗、fallback 检查",
    },
    {
        "module": "backend/query/output_boundary.py",
        "domains": ["present", "persist"],
        "current_authority": "canonical answer、persist policy、finalization policy",
        "target": "输出层 canonical owner",
    },
    {
        "module": "backend/query/runtime_context_state.py",
        "domains": ["restore"],
        "current_authority": "session authoritative context 与状态恢复",
        "target": "ContextPolicy / MemoryPolicy 候选来源",
    },
    {
        "module": "backend/memory/*",
        "domains": ["restore", "persist"],
        "current_authority": "对话记忆、状态记忆、长期记忆读写",
        "target": "受 MemoryPolicy 和写回范围约束",
    },
    {
        "module": "backend/capabilities/*",
        "domains": ["restore", "execute"],
        "current_authority": "skills/tools/agents/bindings/search source",
        "target": "ResourcePolicy 事实源，不直接执行",
    },
)
REQUIRED_PRIMARY_CONTRACT_FIELDS = (
    "intent_frame",
    "memory_policy",
    "context_policy",
    "resource_policy",
    "execution_directives",
    "answer_policy",
    "validation",
    "executions",
)


@dataclass(slots=True)
class RuntimeControl:
    execution_mode: str
    executions: list[Any]
    source: str = "legacy"
    primary_active: bool = False
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        return {
            "type": "orchestration_runtime_control",
            "execution_mode": self.execution_mode,
            "source": self.source,
            "primary_active": self.primary_active,
            "execution_count": len(self.executions),
            "warnings": list(self.warnings),
            "diagnostics": dict(self.diagnostics),
        }


def build_runtime_control(
    *,
    orchestration_plan: dict[str, Any] | None,
    legacy_plan: Any,
    legacy_executions: list[Any],
    primary_entry_selection_enabled: bool = False,
    primary_entry_takeover_enabled: bool = False,
    restore_shadow_consumer_enabled: bool = False,
    restore_shadow_consumer_mode: str = "disabled",
) -> RuntimeControl:
    legacy_mode = str(getattr(legacy_plan, "execution_mode", "") or "single_execution")
    legacy_control = RuntimeControl(
        execution_mode=legacy_mode,
        executions=list(legacy_executions),
        diagnostics={
            "legacy_execution_count": len(legacy_executions),
            "phase7_readiness": _phase7_readiness_summary(
                primary_entry_takeover_enabled=primary_entry_takeover_enabled,
                restore_shadow_consumer_enabled=restore_shadow_consumer_enabled,
                restore_shadow_consumer_mode=restore_shadow_consumer_mode,
                reason="orchestration_plan_missing",
            ),
        },
    )
    if not isinstance(orchestration_plan, dict) or not orchestration_plan:
        return legacy_control
    mode = str(orchestration_plan.get("mode") or "plan_only")
    plan_diagnostics = dict(orchestration_plan.get("diagnostics") or {})
    intent_authority = dict(plan_diagnostics.get("intent_authority") or {})
    restore_authority = dict(plan_diagnostics.get("restore_authority") or {})
    output_authority = dict(plan_diagnostics.get("output_authority") or {})
    dispatch_authority = dict(plan_diagnostics.get("dispatch_authority") or {})
    if mode != "primary":
        legacy_control.source = "orchestration_plan_only"
        legacy_control.diagnostics["plan_id"] = str(orchestration_plan.get("plan_id") or "")
        validation = dict(orchestration_plan.get("validation") or {})
        if validation:
            legacy_control.diagnostics["validation_status"] = str(validation.get("status") or "")
            legacy_control.diagnostics["validation_issue_count"] = len(list(validation.get("issues") or []))
        legacy_control.diagnostics["phase7_readiness"] = _phase7_readiness_summary(
            primary_entry_takeover_enabled=primary_entry_takeover_enabled,
            restore_shadow_consumer_enabled=restore_shadow_consumer_enabled,
            restore_shadow_consumer_mode=restore_shadow_consumer_mode,
            validation_status=legacy_control.diagnostics.get("validation_status", ""),
            intent_authority=intent_authority,
            restore_authority=restore_authority,
            output_authority=output_authority,
            dispatch_authority=dispatch_authority,
            reason="orchestration_not_primary",
        )
        return legacy_control

    validation = dict(orchestration_plan.get("validation") or {})
    if str(validation.get("status") or "") == "blocked":
        phase7_readiness = _phase7_readiness_summary(
            primary_entry_takeover_enabled=primary_entry_takeover_enabled,
            restore_shadow_consumer_enabled=restore_shadow_consumer_enabled,
            restore_shadow_consumer_mode=restore_shadow_consumer_mode,
            validation_status="blocked",
            warnings=["primary_fallback_validation_blocked"],
            intent_authority=intent_authority,
            restore_authority=restore_authority,
            output_authority=output_authority,
            dispatch_authority=dispatch_authority,
            reason="validation_blocked",
        )
        return RuntimeControl(
            execution_mode=legacy_mode,
            executions=list(legacy_executions),
            source="legacy_fallback",
            primary_active=False,
            warnings=["primary_fallback_validation_blocked"],
            diagnostics={
                "plan_id": str(orchestration_plan.get("plan_id") or ""),
                "validation_status": "blocked",
                "validation_issues": list(validation.get("issues") or []),
                "legacy_execution_count": len(legacy_executions),
                "phase7_readiness": phase7_readiness,
            },
        )

    contract_blockers = _primary_contract_blockers(orchestration_plan)
    if contract_blockers:
        phase7_readiness = _phase7_readiness_summary(
            primary_entry_takeover_enabled=primary_entry_takeover_enabled,
            restore_shadow_consumer_enabled=restore_shadow_consumer_enabled,
            restore_shadow_consumer_mode=restore_shadow_consumer_mode,
            contract_blockers=contract_blockers,
            warnings=["primary_fallback_incomplete_contract"],
            intent_authority=intent_authority,
            restore_authority=restore_authority,
            output_authority=output_authority,
            dispatch_authority=dispatch_authority,
            reason="incomplete_contract",
        )
        return RuntimeControl(
            execution_mode=legacy_mode,
            executions=list(legacy_executions),
            source="legacy_fallback",
            primary_active=False,
            warnings=["primary_fallback_incomplete_contract"],
            diagnostics={
                "plan_id": str(orchestration_plan.get("plan_id") or ""),
                "contract_blockers": contract_blockers,
                "legacy_execution_count": len(legacy_executions),
                "phase7_readiness": phase7_readiness,
            },
        )

    planned_executions = [
        dict(item)
        for item in list(orchestration_plan.get("executions") or [])
        if isinstance(item, dict)
    ]
    directives = [
        dict(item)
        for item in list(orchestration_plan.get("execution_directives") or [])
        if isinstance(item, dict)
    ]
    execution_entries = _primary_execution_entries(
        planned_executions=planned_executions,
        directives=directives,
        strategy=_entry_strategy(primary_entry_selection_enabled),
    )
    entry_selection = _entry_selection_summary(
        execution_entries,
        primary_entry_selection_enabled=primary_entry_selection_enabled,
    )
    topology = dict(orchestration_plan.get("topology") or {})
    planned_mode = str(topology.get("mode") or legacy_mode)
    legacy_by_id = {
        _legacy_execution_id(execution, index=index): execution
        for index, execution in enumerate(legacy_executions, start=1)
    }
    primary_execution_preview = PrimaryExecutionAdapter().build_preview(
        entries=execution_entries,
        entry_selection=entry_selection,
        legacy_by_id=legacy_by_id,
    )
    primary_entry_takeover = _entry_takeover_summary(
        entries=execution_entries,
        primary_execution_preview=primary_execution_preview,
        primary_entry_takeover_enabled=primary_entry_takeover_enabled,
    )

    allowlist_blockers = _primary_allowlist_blockers(orchestration_plan)
    if allowlist_blockers:
        phase7_readiness = _phase7_readiness_summary(
            entries=execution_entries,
            entry_selection=entry_selection,
            primary_execution_preview=primary_execution_preview,
            primary_entry_takeover=primary_entry_takeover,
            primary_entry_takeover_enabled=primary_entry_takeover_enabled,
            restore_shadow_consumer_enabled=restore_shadow_consumer_enabled,
            restore_shadow_consumer_mode=restore_shadow_consumer_mode,
            allowlist_blockers=allowlist_blockers,
            warnings=["primary_fallback_allowlist_blocked"],
            intent_authority=intent_authority,
            restore_authority=restore_authority,
            output_authority=output_authority,
            dispatch_authority=dispatch_authority,
            reason="allowlist_blocked",
        )
        return RuntimeControl(
            execution_mode=legacy_mode,
            executions=list(legacy_executions),
            source="legacy_fallback",
            primary_active=False,
            warnings=["primary_fallback_allowlist_blocked"],
            diagnostics={
                "plan_id": str(orchestration_plan.get("plan_id") or ""),
                "allowlist_blockers": allowlist_blockers,
                "allowed_primary_sources": sorted(LOW_RISK_PRIMARY_SOURCES),
                "legacy_execution_count": len(legacy_executions),
                "execution_entries": execution_entries,
                "entry_selection": entry_selection,
                "primary_execution_preview": primary_execution_preview,
                "primary_entry_takeover": primary_entry_takeover,
                "phase7_readiness": phase7_readiness,
            },
        )

    ordered: list[Any] = []
    missing: list[str] = []
    for index, planned in enumerate(planned_executions, start=1):
        execution_id = str(planned.get("execution_id") or f"main-{index}")
        execution = legacy_by_id.get(execution_id)
        if execution is None:
            missing.append(execution_id)
            continue
        ordered.append(execution)

    warnings: list[str] = []
    if missing or len(ordered) != len(legacy_executions):
        warnings.append("primary_fallback_legacy_execution_mismatch")
        phase7_readiness = _phase7_readiness_summary(
            entries=execution_entries,
            entry_selection=entry_selection,
            primary_execution_preview=primary_execution_preview,
            primary_entry_takeover=primary_entry_takeover,
            primary_entry_takeover_enabled=primary_entry_takeover_enabled,
            restore_shadow_consumer_enabled=restore_shadow_consumer_enabled,
            restore_shadow_consumer_mode=restore_shadow_consumer_mode,
            warnings=warnings,
            execution_mismatches=[{"missing_execution_id": item} for item in missing],
            intent_authority=intent_authority,
            restore_authority=restore_authority,
            output_authority=output_authority,
            dispatch_authority=dispatch_authority,
            reason="legacy_execution_mismatch",
        )
        return RuntimeControl(
            execution_mode=legacy_mode,
            executions=list(legacy_executions),
            source="legacy_fallback",
            primary_active=False,
            warnings=warnings,
            diagnostics={
                "plan_id": str(orchestration_plan.get("plan_id") or ""),
                "planned_execution_count": len(planned_executions),
                "legacy_execution_count": len(legacy_executions),
                "missing_execution_ids": missing,
                "execution_entries": execution_entries,
                "entry_selection": entry_selection,
                "primary_execution_preview": primary_execution_preview,
                "primary_entry_takeover": primary_entry_takeover,
                "phase7_readiness": phase7_readiness,
            },
        )

    execution_mismatches = _primary_execution_field_mismatches(
        planned_executions=planned_executions,
        directives=[
            dict(item)
            for item in list(orchestration_plan.get("execution_directives") or [])
            if isinstance(item, dict)
        ],
        legacy_by_id=legacy_by_id,
    )
    if execution_mismatches:
        warnings.append("primary_fallback_legacy_field_mismatch")
        phase7_readiness = _phase7_readiness_summary(
            entries=execution_entries,
            entry_selection=entry_selection,
            primary_execution_preview=primary_execution_preview,
            primary_entry_takeover=primary_entry_takeover,
            primary_entry_takeover_enabled=primary_entry_takeover_enabled,
            restore_shadow_consumer_enabled=restore_shadow_consumer_enabled,
            restore_shadow_consumer_mode=restore_shadow_consumer_mode,
            warnings=warnings,
            execution_mismatches=execution_mismatches,
            intent_authority=intent_authority,
            restore_authority=restore_authority,
            output_authority=output_authority,
            dispatch_authority=dispatch_authority,
            reason="legacy_field_mismatch",
        )
        return RuntimeControl(
            execution_mode=legacy_mode,
            executions=list(legacy_executions),
            source="legacy_fallback",
            primary_active=False,
            warnings=warnings,
            diagnostics={
                "plan_id": str(orchestration_plan.get("plan_id") or ""),
                "planned_execution_count": len(planned_executions),
                "legacy_execution_count": len(legacy_executions),
                "execution_mismatches": execution_mismatches,
                "execution_entries": execution_entries,
                "entry_selection": entry_selection,
                "primary_execution_preview": primary_execution_preview,
                "primary_entry_takeover": primary_entry_takeover,
                "phase7_readiness": phase7_readiness,
            },
        )

    source = "orchestration_primary_entry" if primary_entry_takeover.get("state") == "active" else "orchestration_plan"
    phase7_readiness = _phase7_readiness_summary(
        entries=execution_entries,
        entry_selection=entry_selection,
        primary_execution_preview=primary_execution_preview,
        primary_entry_takeover=primary_entry_takeover,
        primary_entry_takeover_enabled=primary_entry_takeover_enabled,
        restore_shadow_consumer_enabled=restore_shadow_consumer_enabled,
        restore_shadow_consumer_mode=restore_shadow_consumer_mode,
        intent_authority=intent_authority,
        restore_authority=restore_authority,
        output_authority=output_authority,
        dispatch_authority=dispatch_authority,
        reason="primary_path_observed",
    )
    return RuntimeControl(
        execution_mode=planned_mode,
        executions=ordered,
        source=source,
        primary_active=True,
        diagnostics={
            "plan_id": str(orchestration_plan.get("plan_id") or ""),
            "planned_execution_count": len(planned_executions),
            "legacy_execution_count": len(legacy_executions),
            "execution_ids": [str(item.get("execution_id") or "") for item in planned_executions],
            "primary_entry_selection_enabled": bool(primary_entry_selection_enabled),
            "primary_entry_takeover_enabled": bool(primary_entry_takeover_enabled),
            "restore_shadow_consumer_enabled": bool(restore_shadow_consumer_enabled),
            "restore_shadow_consumer_mode": _restore_shadow_consumer_mode(restore_shadow_consumer_mode),
            "entry_strategy": _entry_strategy(primary_entry_selection_enabled),
            "execution_entries": execution_entries,
            "entry_selection": entry_selection,
            "primary_execution_preview": primary_execution_preview,
            "primary_entry_takeover": primary_entry_takeover,
            "phase7_readiness": phase7_readiness,
        },
    )


def _phase7_readiness_summary(
    *,
    entries: list[dict[str, Any]] | None = None,
    entry_selection: dict[str, Any] | None = None,
    primary_execution_preview: dict[str, Any] | None = None,
    primary_entry_takeover: dict[str, Any] | None = None,
    primary_entry_takeover_enabled: bool = False,
    restore_shadow_consumer_enabled: bool = False,
    restore_shadow_consumer_mode: str = "disabled",
    validation_status: str = "",
    contract_blockers: list[str] | None = None,
    allowlist_blockers: list[str] | None = None,
    execution_mismatches: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    intent_authority: dict[str, Any] | None = None,
    restore_authority: dict[str, Any] | None = None,
    output_authority: dict[str, Any] | None = None,
    dispatch_authority: dict[str, Any] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    normalized_entries = list(entries or [])
    normalized_entry_selection = dict(entry_selection or {})
    normalized_preview = dict(primary_execution_preview or {})
    normalized_takeover = dict(primary_entry_takeover or {})
    normalized_intent_authority = dict(intent_authority or {})
    normalized_restore_authority = dict(restore_authority or {})
    normalized_output_authority = dict(output_authority or {})
    normalized_dispatch_authority = dict(dispatch_authority or {})
    restore_shadow_consumer_control = _restore_shadow_consumer_runtime_control(
        restore_authority=normalized_restore_authority,
        restore_shadow_consumer_enabled=restore_shadow_consumer_enabled,
        restore_shadow_consumer_mode=restore_shadow_consumer_mode,
    )
    normalized_restore_authority["restore_shadow_consumer_control"] = restore_shadow_consumer_control
    normalized_restore_authority["restore_shadow_consumer_observation"] = _restore_shadow_consumer_observation(
        restore_authority=normalized_restore_authority,
        restore_shadow_consumer_control=restore_shadow_consumer_control,
    )
    normalized_restore_authority["restore_legacy_decommission_plan"] = _restore_legacy_decommission_plan(
        restore_authority=normalized_restore_authority,
    )
    blockers: list[str] = []

    if validation_status == "blocked":
        blockers.append("validation_blocked")
    blockers.extend(f"contract:{item}" for item in list(contract_blockers or []))
    blockers.extend(f"allowlist:{item}" for item in list(allowlist_blockers or []))
    blockers.extend(f"runtime_warning:{item}" for item in list(warnings or []))
    if execution_mismatches:
        blockers.append("execution_mismatch")
    blocked_sources = sorted(
        {
            str(entry.get("source") or "unknown")
            for entry in normalized_entries
            if str(entry.get("source") or "unknown") not in LOW_RISK_TAKEOVER_SOURCES
        }
    )
    blockers.extend(f"source_not_phase7_ready:{source}" for source in blocked_sources)

    selection_state = str(normalized_entry_selection.get("state") or "")
    preview_state = str(normalized_preview.get("state") or "")
    takeover_state = str(normalized_takeover.get("state") or "")
    takeover_reason = str(normalized_takeover.get("reason") or "")

    if primary_entry_takeover_enabled:
        if selection_state and selection_state != "ready":
            blockers.append(f"entry_selection:{selection_state}")
        if preview_state and preview_state != "ready":
            blockers.append(f"primary_preview:{preview_state}")
        if takeover_state != "active":
            blockers.append(f"primary_takeover:{takeover_state or 'missing'}:{takeover_reason or 'unknown'}")

    unique_blockers = sorted(set(item for item in blockers if item))
    if not primary_entry_takeover_enabled:
        state = "disabled"
        readiness_reason = reason or "primary_entry_takeover_disabled"
        safe_next_step = "保持只读诊断；如需验证 Phase 7A ready，只能在测试环境显式开启 selection/takeover。"
    elif unique_blockers:
        state = "blocked"
        readiness_reason = reason or "phase7_blockers_present"
        safe_next_step = "先修复 blocker 或保持 legacy fallback；不得进入主切换。"
    else:
        state = "ready"
        readiness_reason = reason or "phase7a_readiness_ready"
        safe_next_step = "仅代表 Phase 7A 诊断 ready；下一步可进入受控双轨验证，不删除旧链路。"

    decommission = _legacy_decommission_summary(
        readiness_state=state,
        blockers=unique_blockers,
        primary_entry_takeover_enabled=primary_entry_takeover_enabled,
        intent_authority=normalized_intent_authority,
    )
    principle_alignment = _principle_alignment_summary(
        readiness_state=state,
        readiness_blockers=unique_blockers,
        decommission=decommission,
    )
    cutover_readiness = _phase7_cutover_readiness_summary(
        readiness_state=state,
        readiness_blockers=unique_blockers,
        decommission=decommission,
        principle_alignment=principle_alignment,
        restore_authority=normalized_restore_authority,
        output_authority=normalized_output_authority,
        dispatch_authority=normalized_dispatch_authority,
    )
    return {
        "phase": "7A",
        "state": state,
        "reason": readiness_reason,
        "legacy_authorities": list(PHASE7_LEGACY_AUTHORITIES),
        "required_controls": list(PHASE7_REQUIRED_CONTROLS),
        "ready_sources": sorted(LOW_RISK_TAKEOVER_SOURCES),
        "blocked_sources": blocked_sources,
        "blockers": unique_blockers,
        "intent_authority": normalized_intent_authority,
        "restore_authority": normalized_restore_authority,
        "output_authority": normalized_output_authority,
        "dispatch_authority": normalized_dispatch_authority,
        "legacy_decommission": decommission,
        "principle_alignment": principle_alignment,
        "cutover_readiness": cutover_readiness,
        "safe_next_step": safe_next_step,
    }


def _restore_shadow_consumer_runtime_control(
    *,
    restore_authority: dict[str, Any],
    restore_shadow_consumer_enabled: bool,
    restore_shadow_consumer_mode: str,
) -> dict[str, Any]:
    mode = _restore_shadow_consumer_mode(restore_shadow_consumer_mode)
    contract = dict(restore_authority.get("restore_shadow_consumer_contract") or {})
    contract_state = str(contract.get("state") or "missing")
    blockers: list[str] = []
    if mode == "disabled" and restore_shadow_consumer_enabled:
        blockers.append("restore_shadow_consumer_mode_disabled")
    if mode not in {"disabled", "observe_only"}:
        blockers.append("restore_shadow_consumer_mode_unknown")
    if contract_state not in {"contract_ready", "no_candidates"}:
        blockers.append(f"restore_shadow_consumer_contract:{contract_state}")
    if bool(contract.get("state_write_allowed")):
        blockers.append("restore_shadow_consumer_contract_allows_state_write")
    if bool(contract.get("takeover_allowed")):
        blockers.append("restore_shadow_consumer_contract_allows_takeover")
    if bool(contract.get("delete_allowed")):
        blockers.append("restore_shadow_consumer_contract_allows_delete")

    if not restore_shadow_consumer_enabled:
        state = "disabled"
        reason = "restore_shadow_consumer_disabled"
    elif blockers:
        state = "blocked"
        reason = "restore_shadow_consumer_blocked"
    elif mode == "observe_only":
        state = "observe_only_active"
        reason = "observe_only_consumer_contract_ready"
    else:
        state = "disabled"
        reason = "restore_shadow_consumer_mode_disabled"

    return {
        "phase": "8F",
        "enabled": bool(restore_shadow_consumer_enabled),
        "mode": mode,
        "state": state,
        "reason": reason,
        "contract_state": contract_state,
        "candidate_count": int(contract.get("candidate_count") or 0),
        "blockers": sorted(set(blockers)),
        "state_write_allowed": False,
        "takeover_allowed": False,
        "delete_allowed": False,
        "safe_rule": "即使显式开启，也只允许 observe-only 观测；不得写 runtime 状态，不得替换 legacy restore。",
    }


def _restore_shadow_consumer_mode(mode: str) -> str:
    normalized = str(mode or "disabled").strip().lower()
    return normalized if normalized in {"disabled", "observe_only"} else "disabled"


def _restore_shadow_consumer_observation(
    *,
    restore_authority: dict[str, Any],
    restore_shadow_consumer_control: dict[str, Any],
) -> dict[str, Any]:
    contract = dict(restore_authority.get("restore_shadow_consumer_contract") or {})
    contract_candidates = [
        dict(item)
        for item in list(contract.get("contract_candidates") or [])
        if isinstance(item, dict)
    ]
    control_state = str(restore_shadow_consumer_control.get("state") or "missing")
    blockers: list[str] = []
    observations: list[dict[str, Any]] = []
    if control_state != "observe_only_active":
        blockers.append(f"restore_shadow_consumer_control:{control_state}")
    else:
        for item in contract_candidates:
            if str(item.get("consumer_state") or "") != "observe_only_ready":
                blockers.append("restore_shadow_consumer_candidate_not_ready")
                continue
            observations.append(
                {
                    "candidate_id": str(item.get("candidate_id") or ""),
                    "replacement_point": str(item.get("replacement_point") or "unknown"),
                    "legacy_consumer": str(item.get("legacy_consumer") or ""),
                    "comparison": str(item.get("comparison") or "unknown"),
                    "observation_state": "captured_observe_only",
                    "state_write_allowed": False,
                    "takeover_allowed": False,
                    "delete_allowed": False,
                }
            )
    if control_state != "observe_only_active":
        state = "disabled" if control_state == "disabled" else "blocked"
    elif not contract_candidates:
        state = "no_candidates"
    elif blockers:
        state = "blocked"
    else:
        state = "observed"
    return {
        "phase": "8G",
        "state": state,
        "mode": "runtime_observe_only",
        "control_state": control_state,
        "observation_count": len(observations),
        "observations": observations,
        "observation_state_counts": _runtime_count_by_key(observations, "observation_state"),
        "replacement_point_counts": _runtime_count_by_key(observations, "replacement_point"),
        "blockers": sorted(set(blockers)),
        "state_write_allowed": False,
        "takeover_allowed": False,
        "delete_allowed": False,
        "safe_rule": "8G 只在 RuntimeControl 中记录 observe-only observation；禁止写入真实恢复状态。",
    }


def _runtime_count_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _restore_legacy_decommission_plan(*, restore_authority: dict[str, Any]) -> dict[str, Any]:
    observation = dict(restore_authority.get("restore_shadow_consumer_observation") or {})
    context_gate = dict(restore_authority.get("restore_authority_context_gate") or {})
    observation_state = str(observation.get("state") or "missing")
    context_gate_state = str(context_gate.get("state") or "missing")
    observations = [
        dict(item)
        for item in list(observation.get("observations") or [])
        if isinstance(item, dict)
    ]
    decommission_targets = [
        {
            "target_id": "restore-context-authority",
            "legacy_entry": "query.runtime_context_state.load_session_authoritative_context",
            "replacement_seam": "query.runtime_context_state.load_session_restore_candidates + orchestration.restore_context.RestoreAuthorityContextGate",
            "delete_scope": "active_pdf / active_dataset / active_handle restore for current turn",
            "first_cut": True,
            "already_removed": True,
        },
        {
            "target_id": "restore-continuation-context",
            "legacy_entry": "query.continuation_resolver.apply_authoritative_context",
            "replacement_seam": "orchestration.intent_frame + restore adoption trace",
            "delete_scope": "authoritative context route rewrite hook",
            "first_cut": True,
            "already_removed": True,
        },
        {
            "target_id": "restore-evidence-runtime-state",
            "legacy_entry": "query.runtime._restore_evidence_state_from_session",
            "replacement_seam": "query.runtime._load_evidence_restore_candidates + query.runtime._apply_evidence_restore_candidates",
            "delete_scope": "binding candidate / evidence graph restore",
            "first_cut": False,
            "candidateized": True,
        },
        {
            "target_id": "restore-memory-intent-session-state",
            "legacy_entry": "understanding.memory_intent + memory facade session restore",
            "replacement_seam": "orchestration.memory_policy.restored_candidates",
            "delete_scope": "session_state memory restore",
            "first_cut": False,
        },
    ]
    blockers: list[str] = []
    if context_gate_state != "orchestration_filtered":
        blockers.append(f"authority_context_gate:{context_gate_state}")
    if observation_state != "observed":
        blockers.append(f"observe_only_observation:{observation_state}")
    if not observations:
        blockers.append("no_observed_restore_candidates")
    if any(bool(item.get("state_write_allowed")) or bool(item.get("takeover_allowed")) for item in observations):
        blockers.append("observation_not_read_only")
    target_plans = []
    for target in decommission_targets:
        first_cut = bool(target.get("first_cut"))
        target_blockers = list(blockers)
        if bool(target.get("already_removed")):
            target_blockers = []
        elif str(target.get("target_id") or "") == "restore-continuation-context":
            target_blockers = [
                item
                for item in target_blockers
                if not item.startswith("observe_only_observation:") and item != "no_observed_restore_candidates"
            ]
        if bool(target.get("candidateized")):
            target_blockers = ["deep_restore_candidateized_not_deleted"]
        elif not first_cut:
            target_blockers.append("not_first_cut_scope")
        if bool(target.get("already_removed")):
            state = "removed"
            target_blockers = []
        else:
            state = "ready_for_first_cut_review" if first_cut and not target_blockers else "blocked"
        target_plans.append(
            {
                **target,
                "state": state,
                "blockers": sorted(set(target_blockers)),
                "delete_allowed": False,
                "safe_rule": (
                    "该旧壳接口已删除，后续不得重新引入 authoritative-context route rewrite。"
                    if bool(target.get("already_removed"))
                    else "该深层入口已候选化，暂不删除 evidence graph / binding candidate 链路。"
                    if bool(target.get("candidateized"))
                    else "先提交替换 PR 和回滚开关；删除旧入口必须在 observe-only 对照稳定后单独执行。"
                ),
            }
        )
    ready_count = sum(1 for item in target_plans if str(item.get("state") or "") == "ready_for_first_cut_review")
    removed_first_cut_count = sum(
        1
        for item in target_plans
        if bool(item.get("first_cut")) and str(item.get("state") or "") == "removed"
    )
    first_cut_count = sum(1 for item in target_plans if bool(item.get("first_cut")))
    if ready_count:
        state = "first_cut_review_ready"
    elif first_cut_count and removed_first_cut_count == first_cut_count:
        state = "first_cut_removed"
    elif observation_state == "disabled":
        state = "disabled"
    else:
        state = "blocked"
    return {
        "phase": "8H",
        "state": state,
        "mode": "decommission_planning",
        "authority_context_gate_state": context_gate_state,
        "observation_state": observation_state,
        "observed_candidate_count": len(observations),
        "target_count": len(target_plans),
        "ready_count": ready_count,
        "removed_first_cut_count": removed_first_cut_count,
        "targets": target_plans,
        "target_state_counts": _runtime_count_by_key(target_plans, "state"),
        "blockers": sorted(set(blockers)),
        "delete_allowed": False,
        "takeover_allowed": False,
        "next_action": "浅层 authoritative-context 旧入口已退场；下一步只处理深层 restore 入口的候选化，不直接删除 evidence 或长期记忆链路。",
    }


def _phase7_cutover_readiness_summary(
    *,
    readiness_state: str,
    readiness_blockers: list[str],
    decommission: dict[str, Any],
    principle_alignment: dict[str, Any],
    restore_authority: dict[str, Any],
    output_authority: dict[str, Any],
    dispatch_authority: dict[str, Any],
) -> dict[str, Any]:
    domains = [
        _cutover_domain(
            domain="restore",
            authority=restore_authority,
            expected_owner="orchestration.restore_adoption",
        ),
        _cutover_domain(
            domain="present",
            authority=output_authority,
            expected_owner="orchestration.answer_policy",
            blocker_prefixes=("legacy_present", "legacy_fallback", "worker_result_boundary"),
        ),
        _cutover_domain(
            domain="persist",
            authority=output_authority,
            expected_owner="orchestration.answer_policy + MemoryPolicy",
            blocker_prefixes=("legacy_persist", "memory_writeback"),
        ),
        _cutover_domain(
            domain="decide",
            authority=dispatch_authority,
            expected_owner="orchestration.execution_directives",
            blocker_prefixes=("legacy_decide", "tool_selection", "worker_selection", "agent_dispatch", "route_requires"),
        ),
        _cutover_domain(
            domain="execute",
            authority=dispatch_authority,
            expected_owner="orchestration.runtime_adapter",
            blocker_prefixes=("legacy_execute", "runtime_tool_bridge", "tool_selection", "worker_selection"),
        ),
    ]
    gate_blockers: list[str] = []
    if readiness_state != "ready":
        gate_blockers.append(f"phase7_readiness:{readiness_state or 'missing'}")
    if readiness_blockers:
        gate_blockers.append("phase7_readiness_blockers_present")
    if str(decommission.get("state") or "") != "review_only":
        gate_blockers.append("legacy_decommission_not_ready")
    if str(principle_alignment.get("state") or "") != "aligned":
        gate_blockers.append("principle_alignment_not_ready")
    blockers: list[str] = list(gate_blockers)
    for domain in domains:
        if str(domain.get("state") or "") != "ready":
            blockers.append(f"{domain.get('domain')}:not_ready")
        blockers.extend(f"{domain.get('domain')}:{item}" for item in list(domain.get("blockers") or []))
    domain_summaries = [_cutover_domain_summary(domain) for domain in domains]
    migration_tasks = _cutover_migration_tasks(domain_summaries)
    top_blockers = _cutover_top_blockers(
        gate_blockers=gate_blockers,
        domain_summaries=domain_summaries,
    )
    unique_blockers = sorted(set(str(item) for item in blockers if str(item).strip()))
    blocked_domain_count = sum(1 for item in domains if str(item.get("state") or "") != "ready")
    return {
        "phase": "7K",
        "state": "blocked" if unique_blockers else "ready",
        "mode": "cutover_gate",
        "domains": domains,
        "domain_summaries": domain_summaries,
        "migration_tasks": migration_tasks,
        "gate_blockers": sorted(set(str(item) for item in gate_blockers if str(item).strip())),
        "top_blockers": top_blockers,
        "human_summary": _cutover_human_summary(
            blocked_domain_count=blocked_domain_count,
            domain_count=len(domains),
            top_blockers=top_blockers,
        ),
        "blockers": unique_blockers,
        "domain_count": len(domains),
        "blocked_domain_count": blocked_domain_count,
        "delete_allowed": False,
        "takeover_allowed": False if unique_blockers else True,
        "next_safe_step": "先让五个权力域全部 ready，再进入局部替换；当前不得删除旧链路或扩大接管范围。",
    }


def _cutover_migration_tasks(domain_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for summary in domain_summaries:
        domain = str(summary.get("domain") or "unknown")
        blockers = [
            str(item)
            for item in list(summary.get("primary_blockers") or [])
            if str(item).strip()
        ]
        if not blockers:
            continue
        tasks.append(
            {
                "task_id": f"phase7m:{domain}",
                "domain": domain,
                "state": "planned",
                "priority": _cutover_domain_priority(domain),
                "scope": "diagnostic_only",
                "target": _cutover_domain_target(domain),
                "primary_blockers": blockers,
                "required_controls": _cutover_domain_required_controls(domain),
                "safe_rule": "只做 dry-run、validator 和报告闭环；通过前不得删除旧链路或扩大实际接管。",
                "next_action": str(summary.get("next_action") or ""),
            }
        )
    return sorted(tasks, key=lambda item: (int(item.get("priority") or 99), str(item.get("domain") or "")))


def _cutover_domain_priority(domain: str) -> int:
    order = {
        "restore": 10,
        "present": 20,
        "persist": 30,
        "decide": 40,
        "execute": 50,
    }
    return order.get(domain, 99)


def _cutover_domain_target(domain: str) -> str:
    targets = {
        "restore": "restore adoption gate + MemoryPolicy/ContextPolicy 候选采用",
        "present": "canonical answer boundary + fallback gate",
        "persist": "session/state/durable memory writeback boundary",
        "decide": "ExecutionDirective validator owns route/tool/worker/agent decision",
        "execute": "RuntimeToolBridge/worker reads validated directive",
    }
    return targets.get(domain, "orchestration cutover domain")


def _cutover_domain_required_controls(domain: str) -> list[str]:
    controls = {
        "restore": ["candidate_schema", "owner_module", "intent_override_guard", "memory_context_validator"],
        "present": ["canonical_answer", "protocol_cleanup", "fallback_gate", "citation_policy"],
        "persist": ["MemoryPolicy", "write_scope_validator", "session_state_boundary", "durable_memory_boundary"],
        "decide": ["ResourcePolicy", "binding_graph", "search_policy", "directive_validator"],
        "execute": ["RuntimeToolBridge", "tool_contract", "agent_binding", "output_boundary"],
    }
    return controls.get(domain, ["validator", "dry_run_report"])


def _cutover_domain_summary(domain: dict[str, Any]) -> dict[str, Any]:
    blockers = sorted(
        {
            str(item)
            for item in list(domain.get("blockers") or [])
            if str(item).strip()
        }
    )
    state = str(domain.get("state") or "missing")
    domain_name = str(domain.get("domain") or "unknown")
    return {
        "domain": domain_name,
        "state": state,
        "blocker_count": len(blockers),
        "primary_blockers": blockers[:3],
        "next_action": _cutover_domain_next_action(domain_name=domain_name, blockers=blockers),
    }


def _cutover_top_blockers(
    *,
    gate_blockers: list[str],
    domain_summaries: list[dict[str, Any]],
) -> list[str]:
    top: list[str] = [f"gate:{item}" for item in sorted(set(gate_blockers))[:3]]
    for summary in domain_summaries:
        domain = str(summary.get("domain") or "unknown")
        for blocker in list(summary.get("primary_blockers") or [])[:2]:
            top.append(f"{domain}:{blocker}")
    return top[:10]


def _cutover_human_summary(
    *,
    blocked_domain_count: int,
    domain_count: int,
    top_blockers: list[str],
) -> str:
    if blocked_domain_count <= 0:
        return "五个权力域均已 ready；仍需人工复核后才能讨论局部替换。"
    preview = "、".join(top_blockers[:3]) if top_blockers else "无具体 blocker"
    return f"{blocked_domain_count}/{domain_count} 个权力域仍被阻断；优先查看：{preview}。"


def _cutover_domain_next_action(*, domain_name: str, blockers: list[str]) -> str:
    if not blockers:
        return "保持观察，等待总门禁人工复核。"
    if domain_name == "restore":
        return "先替换恢复候选采用点，确保记忆/上下文恢复只输出候选且不覆盖当前轮目标。"
    if domain_name == "present":
        return "先收束最终答案边界，避免 legacy fallback 或 worker 原始结果直接成为最终回答。"
    if domain_name == "persist":
        return "先统一状态与记忆写回入口，确保写回范围受 MemoryPolicy 约束。"
    if domain_name == "decide":
        return "先把 route、tool、worker、agent 的最终裁决迁入 ExecutionDirective validator。"
    if domain_name == "execute":
        return "先把 RuntimeToolBridge 与 worker 执行入口改为读取 validated directive。"
    return "先定位该权力域的 legacy 执行点，再做 dry-run 对照。"


def _cutover_domain(
    *,
    domain: str,
    authority: dict[str, Any],
    expected_owner: str,
    blocker_prefixes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    blockers = [
        str(item)
        for item in list(authority.get("blockers") or [])
        if str(item).strip()
    ]
    if blocker_prefixes is not None:
        blockers = [
            item
            for item in blockers
            if item.startswith(blocker_prefixes)
        ]
    authority_state = str(authority.get("state") or "missing")
    if authority_state in {"", "missing"}:
        blockers.append("authority_missing")
    if bool(authority.get("legacy_still_executes", True)):
        blockers.append("legacy_still_executes")
    unique_blockers = sorted(set(blockers))
    return {
        "domain": domain,
        "state": "blocked" if unique_blockers else "ready",
        "authority_state": authority_state or "missing",
        "canonical_owner": str(authority.get("canonical_owner") or expected_owner),
        "runtime_owner": str(authority.get("runtime_owner") or ""),
        "blockers": unique_blockers,
        "delete_allowed": False,
    }


def _principle_alignment_summary(
    *,
    readiness_state: str,
    readiness_blockers: list[str],
    decommission: dict[str, Any],
) -> dict[str, Any]:
    domains = sorted(
        {
            str(domain)
            for item in PHASE7_LEGACY_POWER_DOMAINS
            for domain in list(item.get("domains") or [])
            if str(domain).strip()
        }
    )
    blockers = [f"legacy_power_domain:{domain}" for domain in domains]
    if readiness_state != "ready":
        blockers.append(f"phase7_readiness:{readiness_state or 'missing'}")
    if str(decommission.get("state") or "") != "review_only":
        blockers.append("legacy_decommission_not_ready")
    if readiness_blockers:
        blockers.append("readiness_blockers_present")
    blockers.append("doc66_output_specialty_only")
    unique_blockers = sorted(set(blockers))
    return {
        "phase": "7E",
        "state": "blocked" if unique_blockers else "aligned",
        "reason": "phase7e_principle_alignment_required" if unique_blockers else "phase7e_principle_alignment_passed",
        "required_principles": list(PHASE7_DESIGN_PRINCIPLE_DOCS),
        "legacy_power_domains": [dict(item) for item in PHASE7_LEGACY_POWER_DOMAINS],
        "blockers": unique_blockers,
        "next_safe_phase": "Phase 7E 只允许继续做诊断、权力归档和迁移计划；不得删除旧链路或扩大接管范围。",
    }


def _legacy_decommission_summary(
    *,
    readiness_state: str,
    blockers: list[str],
    primary_entry_takeover_enabled: bool,
    intent_authority: dict[str, Any],
) -> dict[str, Any]:
    legacy_still_executes = bool(intent_authority.get("legacy_still_executes", True))
    decommission_blockers = list(blockers)
    if not primary_entry_takeover_enabled:
        decommission_blockers.append("primary_entry_takeover_disabled")
    if readiness_state != "ready":
        decommission_blockers.append(f"phase7_readiness:{readiness_state or 'missing'}")
    if legacy_still_executes:
        decommission_blockers.append("legacy_query_planner_still_executes")
    unique_blockers = sorted(set(item for item in decommission_blockers if item))
    state = "review_only" if not unique_blockers else "not_ready"
    return {
        "phase": "7D",
        "state": state,
        "reason": "legacy_cleanup_gate_review_only" if state == "review_only" else "legacy_cleanup_blocked",
        "protected_modules": list(PHASE7_PROTECTED_LEGACY_MODULES),
        "blockers": unique_blockers,
        "allowed_action": "write_cleanup_plan_only" if unique_blockers else "manual_review_required_before_any_deletion",
        "delete_allowed": False,
    }


def _legacy_execution_id(execution: Any, *, index: int) -> str:
    return str(
        getattr(execution, "subtask_id", "")
        or getattr(execution, "bundle_item_id", "")
        or "main"
    )


def _primary_execution_field_mismatches(
    *,
    planned_executions: list[dict[str, Any]],
    directives: list[dict[str, Any]],
    legacy_by_id: dict[str, Any],
) -> list[dict[str, str]]:
    directive_by_id = {
        str(item.get("execution_id") or f"main-{index}"): item
        for index, item in enumerate(directives, start=1)
    }
    mismatches: list[dict[str, str]] = []
    for index, planned in enumerate(planned_executions, start=1):
        execution_id = str(planned.get("execution_id") or f"main-{index}")
        legacy = legacy_by_id.get(execution_id)
        if legacy is None:
            continue
        directive = directive_by_id.get(execution_id, {})
        understanding = getattr(legacy, "query_understanding", None)
        active_skill = getattr(legacy, "active_skill", None)
        worker_plan = getattr(legacy, "worker_plan", None)
        checks = {
            "route": (
                str(planned.get("route") or ""),
                str(getattr(understanding, "route", "") or ""),
            ),
            "execution_kind": (
                str(planned.get("execution_kind") or ""),
                str(getattr(legacy, "execution_kind", "") or ""),
            ),
            "tool": (
                str(directive.get("tool") or planned.get("tool_name") or ""),
                str(getattr(understanding, "tool_name", "") or ""),
            ),
            "worker_route": (
                str(directive.get("worker_route") or planned.get("worker_route") or ""),
                str(getattr(worker_plan, "worker_route", "") or ""),
            ),
            "skill": (
                str(directive.get("skill") or planned.get("skill_name") or ""),
                str(getattr(active_skill, "name", "") or getattr(understanding, "skill_name", "") or ""),
            ),
        }
        for field_name, (planned_value, legacy_value) in checks.items():
            if not planned_value or not legacy_value or planned_value == legacy_value:
                continue
            mismatches.append(
                {
                    "execution_id": execution_id,
                    "field": field_name,
                    "planned": planned_value,
                    "legacy": legacy_value,
                }
            )
    return mismatches


def _primary_execution_entries(
    *,
    planned_executions: list[dict[str, Any]],
    directives: list[dict[str, Any]],
    strategy: str,
) -> list[dict[str, Any]]:
    directive_by_id = {
        str(item.get("execution_id") or f"main-{index}"): item
        for index, item in enumerate(directives, start=1)
    }
    entries: list[dict[str, Any]] = []
    for index, planned in enumerate(planned_executions, start=1):
        execution_id = str(planned.get("execution_id") or f"main-{index}")
        directive = directive_by_id.get(execution_id, {})
        tool = str(directive.get("tool") or planned.get("tool_name") or "")
        worker_route = str(directive.get("worker_route") or planned.get("worker_route") or "")
        agent_id = str(directive.get("agent_id") or "")
        action = str(directive.get("action") or "")
        route = str(planned.get("route") or "")
        execution_kind = str(planned.get("execution_kind") or "")
        risk_tags = [
            str(item or "").strip()
            for item in list(directive.get("risk_tags") or [])
            if str(item or "").strip()
        ]
        entry_kind = _entry_kind(
            action=action,
            execution_kind=execution_kind,
            tool=tool,
            worker_route=worker_route,
        )
        source = _entry_source(tool=tool, route=route)
        eligibility = _entry_eligibility(
            entry_kind=entry_kind,
            source=source,
            tool=tool,
            risk_tags=risk_tags,
        )
        entries.append(
            {
                "execution_id": execution_id,
                "step_id": str(directive.get("step_id") or f"step_{index}"),
                "entry_kind": entry_kind,
                "route": route,
                "tool": tool,
                "worker_route": worker_route,
                "skill": str(directive.get("skill") or planned.get("skill_name") or ""),
                "agent_id": agent_id,
                "source": source,
                "strategy": strategy,
                "risk_tags": risk_tags,
                "eligible_for_primary_entry": eligibility["eligible"],
                "eligibility_reason": eligibility["reason"],
                "eligibility_blockers": eligibility["blockers"],
            }
        )
    return entries


def _entry_eligibility(
    *,
    entry_kind: str,
    source: str,
    tool: str,
    risk_tags: list[str],
) -> dict[str, Any]:
    blockers: list[str] = []
    if source not in LOW_RISK_PRIMARY_SOURCES:
        blockers.append(f"source_not_low_risk:{source or 'unknown'}")
    high_risk_tags = {"high_risk_tool", "external_network", "writes_files", "network_write"}
    for tag in risk_tags:
        if tag in high_risk_tags:
            blockers.append(f"risk_tag:{tag}")
    if tool in {"terminal", "python_repl"}:
        blockers.append(f"system_execution:{tool}")
    if entry_kind not in {"worker", "direct_tool", "agent", "single_execution"}:
        blockers.append(f"entry_kind_not_supported:{entry_kind or 'unknown'}")
    if entry_kind == "agent" and source not in {"general"}:
        blockers.append(f"agent_entry_requires_general_source:{source or 'unknown'}")

    unique_blockers = sorted(set(blockers))
    if unique_blockers:
        return {
            "eligible": False,
            "reason": "blocked_for_primary_entry",
            "blockers": unique_blockers,
        }
    return {
        "eligible": True,
        "reason": "eligible_low_risk_primary_entry",
        "blockers": [],
    }


def _entry_selection_summary(
    entries: list[dict[str, Any]],
    *,
    primary_entry_selection_enabled: bool,
) -> dict[str, Any]:
    candidate_ids = [
        str(entry.get("execution_id") or "")
        for entry in entries
        if bool(entry.get("eligible_for_primary_entry"))
    ]
    candidate_ids = [item for item in candidate_ids if item]
    blocked_entries = [
        {
            "execution_id": str(entry.get("execution_id") or ""),
            "step_id": str(entry.get("step_id") or ""),
            "blockers": list(entry.get("eligibility_blockers") or []),
        }
        for entry in entries
        if not bool(entry.get("eligible_for_primary_entry"))
    ]
    if not primary_entry_selection_enabled:
        state = "disabled"
        selected_ids: list[str] = []
    elif not entries:
        state = "no_entries"
        selected_ids = []
    elif blocked_entries:
        state = "blocked"
        selected_ids = []
    else:
        state = "ready"
        selected_ids = list(candidate_ids)
    return {
        "enabled": bool(primary_entry_selection_enabled),
        "state": state,
        "candidate_execution_ids": candidate_ids,
        "selected_execution_ids": selected_ids,
        "eligible_count": len(candidate_ids),
        "blocked_count": len(blocked_entries),
        "blocked_entries": blocked_entries,
    }


def _entry_takeover_summary(
    *,
    entries: list[dict[str, Any]],
    primary_execution_preview: dict[str, Any],
    primary_entry_takeover_enabled: bool,
) -> dict[str, Any]:
    if not primary_entry_takeover_enabled:
        return {
            "enabled": False,
            "state": "disabled",
            "reason": "primary_entry_takeover_disabled",
            "selected_execution_ids": [],
            "blocked_sources": [],
            "output_source": "legacy_final_output",
        }
    preview_state = str(primary_execution_preview.get("state") or "")
    mismatch_count = int(primary_execution_preview.get("mismatch_count") or 0)
    if preview_state != "ready" or mismatch_count:
        return {
            "enabled": True,
            "state": "blocked",
            "reason": f"primary_preview_not_ready:{preview_state or 'missing'}",
            "selected_execution_ids": [],
            "blocked_sources": [],
            "output_source": "legacy_final_output",
        }
    blocked_sources = sorted(
        {
            str(entry.get("source") or "unknown")
            for entry in entries
            if str(entry.get("source") or "unknown") not in LOW_RISK_TAKEOVER_SOURCES
        }
    )
    if blocked_sources:
        return {
            "enabled": True,
            "state": "blocked",
            "reason": "source_not_in_takeover_scope",
            "selected_execution_ids": [],
            "blocked_sources": blocked_sources,
            "allowed_sources": sorted(LOW_RISK_TAKEOVER_SOURCES),
            "output_source": "legacy_final_output",
        }
    selected_ids = [
        str(entry.get("execution_id") or "")
        for entry in entries
        if str(entry.get("execution_id") or "")
    ]
    return {
        "enabled": True,
        "state": "active",
        "reason": "primary_entry_takeover_active",
        "selected_execution_ids": selected_ids,
        "blocked_sources": [],
        "allowed_sources": sorted(LOW_RISK_TAKEOVER_SOURCES),
        "output_source": "primary_entry_controlled_legacy_execution",
    }


def _entry_strategy(primary_entry_selection_enabled: bool) -> str:
    if primary_entry_selection_enabled:
        return "primary_entry_selection_preview"
    return "reuse_legacy_execution"


def _entry_kind(*, action: str, execution_kind: str, tool: str, worker_route: str) -> str:
    if worker_route or action == "delegate_agent":
        return "worker"
    if tool or action == "call_tool":
        return "direct_tool"
    if execution_kind:
        return execution_kind
    return "agent"


def _entry_source(*, tool: str, route: str) -> str:
    if tool:
        return _tool_source(tool)
    if route == "rag":
        return "rag"
    if route in {"worker", "tool"}:
        return "local_files"
    return "general"


def _primary_contract_blockers(orchestration_plan: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for field_name in REQUIRED_PRIMARY_CONTRACT_FIELDS:
        if field_name not in orchestration_plan:
            blockers.append(f"missing:{field_name}")

    validation = orchestration_plan.get("validation")
    if not isinstance(validation, dict):
        blockers.append("invalid:validation")
    else:
        status = str(validation.get("status") or "").strip()
        if not status:
            blockers.append("missing:validation.status")

    planned_executions = [
        dict(item)
        for item in list(orchestration_plan.get("executions") or [])
        if isinstance(item, dict)
    ]
    directives = [
        dict(item)
        for item in list(orchestration_plan.get("execution_directives") or [])
        if isinstance(item, dict)
    ]
    if planned_executions and not directives:
        blockers.append("missing:execution_directives")
    if directives and len(directives) != len(planned_executions):
        blockers.append("mismatch:execution_directives_vs_executions")

    return sorted(set(blockers))


def _primary_allowlist_blockers(orchestration_plan: dict[str, Any]) -> list[str]:
    resource_policy = dict(orchestration_plan.get("resource_policy") or {})
    sources = {
        str(item or "").strip()
        for item in list(resource_policy.get("allowed_sources") or [])
        if str(item or "").strip()
    }
    blocked = sorted(source for source in sources if source not in LOW_RISK_PRIMARY_SOURCES)
    directives = [
        dict(item)
        for item in list(orchestration_plan.get("execution_directives") or [])
        if isinstance(item, dict)
    ]
    for directive in directives:
        risks = {
            str(item or "").strip()
            for item in list(directive.get("risk_tags") or [])
            if str(item or "").strip()
        }
        if "high_risk_tool" in risks:
            blocked.append(f"high_risk_tool:{directive.get('tool') or directive.get('step_id') or 'unknown'}")
        tool = str(directive.get("tool") or "")
        if tool in {"terminal", "python_repl"}:
            blocked.append(f"system_execution:{tool}")
    return sorted(set(blocked))


def _tool_source(tool_name: str) -> str:
    if tool_name == "search_knowledge":
        return "rag"
    if tool_name in {"search_files", "search_text", "read_file"}:
        return "local_files"
    if tool_name in {"pdf_analysis", "analyze_multimodal_file"}:
        return "document"
    if tool_name == "structured_data_analysis":
        return "data"
    if tool_name in {"web_search", "fetch_url", "get_weather", "get_gold_price"}:
        return "web"
    if tool_name in {"terminal", "python_repl"}:
        return "system_execution"
    return "general"
