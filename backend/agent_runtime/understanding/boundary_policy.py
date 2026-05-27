from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class BoundaryPolicy:
    policy_id: str
    forbidden_actions: tuple[str, ...] = ()
    required_process: tuple[str, ...] = ()
    write_allowed: bool = True
    network_allowed: bool = True
    shell_allowed: bool = True
    browser_allowed: bool = True
    approval_policy: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_runtime.boundary_policy"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["forbidden_actions"] = list(self.forbidden_actions)
        payload["required_process"] = list(self.required_process)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def build_boundary_policy(
    *,
    user_message: str,
    request_facts: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
) -> BoundaryPolicy:
    context = dict(current_turn_context or {})
    forbidden: list[str] = []
    required: list[str] = []
    for item in list(context.get("forbidden_actions") or []):
        if str(item).strip():
            forbidden.append(str(item).strip())
    for item in list(context.get("required_process") or []):
        if str(item).strip():
            required.append(str(item).strip())
    for item in _structured_forbidden_actions(context):
        forbidden.append(item)
    approval_policy = str(context.get("approval_policy") or context.get("permission_mode") or "").strip()
    forbidden_actions = tuple(_dedupe(forbidden))
    return BoundaryPolicy(
        policy_id=f"boundary:{str(dict(request_facts or {}).get('facts_id') or 'runtime')}",
        forbidden_actions=forbidden_actions,
        required_process=tuple(_dedupe(required)),
        write_allowed=not bool(set(forbidden_actions) & {"edit_workspace", "write_file", "modify_code"}),
        network_allowed=not bool(set(forbidden) & {"search_external", "fetch_url"}),
        shell_allowed="run_command" not in forbidden,
        browser_allowed="use_browser" not in forbidden,
        approval_policy=approval_policy,
        diagnostics={
            "source": "structured_context_only",
            "hard_boundary": False,
            "authority_boundary": "operation_gate_and_sandbox_policy",
            "natural_language_markers_are_intent_signals": False,
            "natural_language_marker_policy": "disabled_for_hard_permissions",
            "user_message_seen": bool(str(user_message or "").strip()),
            "structured_forbidden_actions_used": [
                item
                for item in forbidden_actions
                if item in {"edit_workspace", "write_file", "modify_code"}
            ],
        },
    )


def _structured_forbidden_actions(context: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for source in (
        dict(context.get("model_turn_decision") or {}),
        dict(context.get("task_goal_spec") or context.get("goal_frame") or {}),
    ):
        for item in list(source.get("forbidden_actions") or []):
            value = str(item or "").strip()
            if value:
                actions.append(value)
    return _dedupe(actions)


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


