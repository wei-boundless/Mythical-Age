from __future__ import annotations

from typing import Any

from .models import CapabilityValidationIssue


def validate_capability_catalog(
    *,
    skills: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    agent_bindings: dict[str, list[str]],
) -> list[CapabilityValidationIssue]:
    issues: list[CapabilityValidationIssue] = []
    known_tools = {str(tool.get("name") or "") for tool in tools}

    for skill in skills:
        runtime = skill.get("runtime") if isinstance(skill.get("runtime"), dict) else {}
        skill_name = str(runtime.get("name") or "")
        for tool_name in list(runtime.get("allowed_tools") or []):
            if tool_name not in known_tools:
                issues.append(
                    CapabilityValidationIssue(
                        severity="warning",
                        code="skill_unknown_tool",
                        message=f"Skill {skill_name} references unknown tool {tool_name}.",
                        subject=skill_name,
                    )
                )

    for agent_id, tool_names in agent_bindings.items():
        for tool_name in tool_names:
            if tool_name not in known_tools:
                issues.append(
                    CapabilityValidationIssue(
                        severity="warning",
                        code="agent_unknown_tool",
                        message=f"Agent {agent_id} owns unknown tool {tool_name}.",
                        subject=agent_id,
                    )
                )

    return issues
