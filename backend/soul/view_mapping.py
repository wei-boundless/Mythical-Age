from __future__ import annotations

from typing import Any

from soul.contracts import SoulSkillView, SoulToolView


def soul_tool_view_from_resource_runtime_view(resource_view: Any) -> SoulToolView:
    data = resource_view.to_dict() if hasattr(resource_view, "to_dict") else dict(resource_view)
    return SoulToolView(
        tool_id=str(data.get("resource_id") or ""),
        title=str(data.get("title") or data.get("resource_id") or ""),
        capability_summary=str(data.get("capability_summary") or ""),
        input_schema_summary=str(data.get("input_contract_ref") or ""),
        output_schema_summary=str(data.get("output_contract_ref") or ""),
        risk_summary=str(data.get("risk_summary") or ""),
        authorized=bool(data.get("authorized", False)),
        authorization_owner=str(data.get("authorization_owner") or "ResourcePolicy"),
        requires_approval=bool(data.get("requires_approval", False)),
        available_to_model=bool(data.get("available_to_model", False)),
        runtime_executable=bool(data.get("runtime_executable", False)),
        denied_reason=str(data.get("denied_reason") or ""),
        policy_decision=str(data.get("policy_decision") or "unknown"),
    )


def soul_skill_view_from_skill_runtime_view(skill_view: Any) -> SoulSkillView:
    data = skill_view.to_dict() if hasattr(skill_view, "to_dict") else dict(skill_view)
    return SoulSkillView(
        skill_id=str(data.get("skill_id") or ""),
        title=str(data.get("title") or data.get("skill_id") or ""),
        capability_summary=str(data.get("method_summary") or ""),
        input_boundary=str(data.get("input_boundary") or ""),
        output_boundary=str(data.get("output_boundary") or ""),
        forbidden_uses=", ".join(list(data.get("forbidden_uses") or [])),
        current_task_reason=str(data.get("task_reason") or ""),
    )
