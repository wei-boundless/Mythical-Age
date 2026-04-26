from __future__ import annotations

from typing import Any

from orchestration.models import OrchestrationPlan, ValidationDecision


CHECKED_RULES = [
    "directive_tool_must_be_allowed",
    "directive_skill_must_be_allowed",
    "directive_agent_must_be_allowed",
    "directive_source_must_be_allowed",
    "blocked_tools_must_not_be_directed",
]

TOOL_SOURCE_HINTS: dict[str, str] = {
    "search_knowledge": "rag",
    "search_files": "local_files",
    "search_text": "local_files",
    "read_file": "local_files",
    "pdf_analysis": "document",
    "analyze_multimodal_file": "document",
    "structured_data_analysis": "data",
    "web_search": "web",
    "fetch_url": "web",
    "terminal": "system_execution",
    "python_repl": "system_execution",
}


def validate_orchestration_plan(plan: OrchestrationPlan) -> ValidationDecision:
    """Validate the formal directive without changing runtime behavior."""
    issues: list[dict[str, Any]] = []
    resource_policy = plan.resource_policy
    allowed_tools = set(_clean(resource_policy.allowed_tools))
    allowed_skills = set(_clean(resource_policy.allowed_skills))
    allowed_agents = set(_clean(resource_policy.allowed_agents))
    allowed_sources = set(_clean(resource_policy.allowed_sources))
    blocked_tools = set(_clean(resource_policy.blocked_tools))

    for directive in plan.execution_directives:
        label = directive.step_id or directive.execution_id or "directive"
        if directive.tool:
            if directive.tool in blocked_tools:
                issues.append(_issue("blocked", "tool_blocked_by_search_policy", label, directive.tool))
            if allowed_tools and directive.tool not in allowed_tools:
                issues.append(_issue("blocked", "tool_not_in_resource_policy", label, directive.tool))
            source = TOOL_SOURCE_HINTS.get(directive.tool, "general")
            if allowed_sources and not _source_allowed(source, allowed_sources):
                issues.append(_issue("blocked", "tool_source_not_allowed", label, f"{directive.tool}:{source}"))
        if directive.skill and allowed_skills and directive.skill not in allowed_skills:
            issues.append(_issue("blocked", "skill_not_in_resource_policy", label, directive.skill))
        if directive.agent_id and allowed_agents and directive.agent_id not in allowed_agents:
            issues.append(_issue("blocked", "agent_not_in_resource_policy", label, directive.agent_id))

    status = "blocked" if any(item["severity"] == "blocked" for item in issues) else "passed"
    return ValidationDecision(
        status=status,
        issues=issues,
        checked_rules=list(CHECKED_RULES),
        refs={"validator": "orchestration.validation.validate_orchestration_plan"},
    )


def _clean(values: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _source_allowed(source: str, allowed: set[str]) -> bool:
    if source in allowed:
        return True
    if source in {"document", "data", "local_files"} and "local_files" in allowed:
        return True
    if source == "general":
        return True
    return False


def _issue(severity: str, code: str, subject: str, detail: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "subject": subject,
        "detail": detail,
    }
