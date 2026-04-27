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
) -> RuntimeControl:
    legacy_mode = str(getattr(legacy_plan, "execution_mode", "") or "single_execution")
    legacy_control = RuntimeControl(
        execution_mode=legacy_mode,
        executions=list(legacy_executions),
        diagnostics={
            "legacy_execution_count": len(legacy_executions),
            "phase7_readiness": _phase7_readiness_summary(
                primary_entry_takeover_enabled=primary_entry_takeover_enabled,
                reason="orchestration_plan_missing",
            ),
        },
    )
    if not isinstance(orchestration_plan, dict) or not orchestration_plan:
        return legacy_control
    mode = str(orchestration_plan.get("mode") or "plan_only")
    plan_diagnostics = dict(orchestration_plan.get("diagnostics") or {})
    intent_authority = dict(plan_diagnostics.get("intent_authority") or {})
    if mode != "primary":
        legacy_control.source = "orchestration_plan_only"
        legacy_control.diagnostics["plan_id"] = str(orchestration_plan.get("plan_id") or "")
        validation = dict(orchestration_plan.get("validation") or {})
        if validation:
            legacy_control.diagnostics["validation_status"] = str(validation.get("status") or "")
            legacy_control.diagnostics["validation_issue_count"] = len(list(validation.get("issues") or []))
        legacy_control.diagnostics["phase7_readiness"] = _phase7_readiness_summary(
            primary_entry_takeover_enabled=primary_entry_takeover_enabled,
            validation_status=legacy_control.diagnostics.get("validation_status", ""),
            intent_authority=intent_authority,
            reason="orchestration_not_primary",
        )
        return legacy_control

    validation = dict(orchestration_plan.get("validation") or {})
    if str(validation.get("status") or "") == "blocked":
        phase7_readiness = _phase7_readiness_summary(
            primary_entry_takeover_enabled=primary_entry_takeover_enabled,
            validation_status="blocked",
            warnings=["primary_fallback_validation_blocked"],
            intent_authority=intent_authority,
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
            contract_blockers=contract_blockers,
            warnings=["primary_fallback_incomplete_contract"],
            intent_authority=intent_authority,
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
            allowlist_blockers=allowlist_blockers,
            warnings=["primary_fallback_allowlist_blocked"],
            intent_authority=intent_authority,
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
            warnings=warnings,
            execution_mismatches=[{"missing_execution_id": item} for item in missing],
            intent_authority=intent_authority,
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
            warnings=warnings,
            execution_mismatches=execution_mismatches,
            intent_authority=intent_authority,
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
        intent_authority=intent_authority,
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
    validation_status: str = "",
    contract_blockers: list[str] | None = None,
    allowlist_blockers: list[str] | None = None,
    execution_mismatches: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    intent_authority: dict[str, Any] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    normalized_entries = list(entries or [])
    normalized_entry_selection = dict(entry_selection or {})
    normalized_preview = dict(primary_execution_preview or {})
    normalized_takeover = dict(primary_entry_takeover or {})
    normalized_intent_authority = dict(intent_authority or {})
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
        "legacy_decommission": decommission,
        "safe_next_step": safe_next_step,
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
