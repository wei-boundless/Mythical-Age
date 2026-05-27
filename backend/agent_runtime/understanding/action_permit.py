from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ActionPermit:
    permit_id: str
    allowed: bool
    action_intent: str
    denied_reasons: tuple[str, ...] = ()
    required_operations: tuple[str, ...] = ()
    optional_operations: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_runtime.action_permit"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["denied_reasons"] = list(self.denied_reasons)
        payload["required_operations"] = list(self.required_operations)
        payload["optional_operations"] = list(self.optional_operations)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def build_action_permit(
    *,
    model_turn_decision: dict[str, Any],
    boundary_policy: dict[str, Any],
) -> ActionPermit:
    decision = dict(model_turn_decision or {})
    boundary = dict(boundary_policy or {})
    action = str(decision.get("action_intent") or "").strip()
    boundary_forbidden = {
        str(item).strip()
        for item in list(boundary.get("forbidden_actions") or [])
        if str(item).strip()
    }
    decision_forbidden = {
        str(item).strip()
        for item in list(decision.get("forbidden_actions") or [])
        if str(item).strip()
    }
    forbidden = {*boundary_forbidden, *decision_forbidden}
    denied: list[str] = []
    if action == "edit_workspace" and forbidden & {"edit_workspace", "write_file", "modify_code"}:
        denied.append(
            "write_forbidden_by_model_turn_decision"
            if decision_forbidden & {"edit_workspace", "write_file", "modify_code"}
            else "write_forbidden_by_boundary"
        )
    if action == "search_external" and forbidden & {"search_external", "fetch_url"}:
        denied.append("network_forbidden_by_boundary")
    required = ["op.model_response"]
    optional: list[str] = []
    if action == "read_context":
        optional.extend(["op.read_file", "op.search_text", "op.search_files"])
    elif action == "search_external":
        required.append("op.web_search")
        optional.append("op.fetch_url")
    elif action == "edit_workspace":
        required.extend(["op.read_file", "op.edit_file"])
        optional.extend(["op.search_text", "op.write_file", "op.shell"])
    elif action == "run_command":
        required.append("op.shell")
    elif action == "use_browser":
        required.append("op.browser_control")
    elif action == "delegate":
        required.append("op.delegate_to_agent")
    return ActionPermit(
        permit_id=f"action-permit:{decision.get('decision_id') or 'runtime'}",
        allowed=not denied,
        action_intent=action,
        denied_reasons=tuple(denied),
        required_operations=tuple(_dedupe(required)),
        optional_operations=tuple(_dedupe(optional)),
        diagnostics={
            "permit_does_not_change_goal": True,
            "boundary_forbidden_actions": sorted(boundary_forbidden),
            "model_turn_forbidden_actions": sorted(decision_forbidden),
        },
    )


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


