from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


LOW_RISK_PRIMARY_SOURCES = {"rag", "local_files", "document", "data", "general"}
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
) -> RuntimeControl:
    legacy_mode = str(getattr(legacy_plan, "execution_mode", "") or "single_execution")
    legacy_control = RuntimeControl(
        execution_mode=legacy_mode,
        executions=list(legacy_executions),
        diagnostics={"legacy_execution_count": len(legacy_executions)},
    )
    if not isinstance(orchestration_plan, dict) or not orchestration_plan:
        return legacy_control
    mode = str(orchestration_plan.get("mode") or "plan_only")
    if mode != "primary":
        legacy_control.source = "orchestration_plan_only"
        legacy_control.diagnostics["plan_id"] = str(orchestration_plan.get("plan_id") or "")
        validation = dict(orchestration_plan.get("validation") or {})
        if validation:
            legacy_control.diagnostics["validation_status"] = str(validation.get("status") or "")
            legacy_control.diagnostics["validation_issue_count"] = len(list(validation.get("issues") or []))
        return legacy_control

    validation = dict(orchestration_plan.get("validation") or {})
    if str(validation.get("status") or "") == "blocked":
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
            },
        )

    contract_blockers = _primary_contract_blockers(orchestration_plan)
    if contract_blockers:
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

    allowlist_blockers = _primary_allowlist_blockers(orchestration_plan)
    if allowlist_blockers:
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
            },
        )

    topology = dict(orchestration_plan.get("topology") or {})
    planned_mode = str(topology.get("mode") or legacy_mode)
    legacy_by_id = {
        _legacy_execution_id(execution, index=index): execution
        for index, execution in enumerate(legacy_executions, start=1)
    }
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
            },
        )

    return RuntimeControl(
        execution_mode=planned_mode,
        executions=ordered,
        source="orchestration_plan",
        primary_active=True,
        diagnostics={
            "plan_id": str(orchestration_plan.get("plan_id") or ""),
            "planned_execution_count": len(planned_executions),
            "legacy_execution_count": len(legacy_executions),
            "execution_ids": [str(item.get("execution_id") or "") for item in planned_executions],
            "primary_entry_selection_enabled": bool(primary_entry_selection_enabled),
            "entry_strategy": _entry_strategy(primary_entry_selection_enabled),
            "execution_entries": execution_entries,
        },
    )


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
        entries.append(
            {
                "execution_id": execution_id,
                "step_id": str(directive.get("step_id") or f"step_{index}"),
                "entry_kind": _entry_kind(
                    action=action,
                    execution_kind=execution_kind,
                    tool=tool,
                    worker_route=worker_route,
                ),
                "route": route,
                "tool": tool,
                "worker_route": worker_route,
                "skill": str(directive.get("skill") or planned.get("skill_name") or ""),
                "agent_id": agent_id,
                "source": _entry_source(tool=tool, route=route),
                "strategy": strategy,
            }
        )
    return entries


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
