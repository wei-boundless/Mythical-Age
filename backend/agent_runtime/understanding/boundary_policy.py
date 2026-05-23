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
    text = str(user_message or "").lower()
    context = dict(current_turn_context or {})
    forbidden: list[str] = []
    required: list[str] = []
    if any(marker in text for marker in ("不要改", "不要修改", "不要动代码", "只分析", "readonly", "read only", "do not modify")):
        forbidden.extend(["edit_workspace", "write_file", "modify_code"])
    if any(marker in text for marker in ("不要联网", "不要搜索", "不要查网页", "no web", "do not search")):
        forbidden.extend(["search_external", "fetch_url"])
    if any(marker in text for marker in ("先写计划", "先给计划", "必须先写计划", "计划书")):
        required.append("plan_before_execute")
    if any(marker in text for marker in ("必须测试", "必须验证", "跑测试", "run tests")):
        required.append("verify_before_final")
    for item in list(context.get("forbidden_actions") or []):
        if str(item).strip():
            forbidden.append(str(item).strip())
    approval_policy = str(context.get("approval_policy") or context.get("permission_mode") or "").strip()
    return BoundaryPolicy(
        policy_id=f"boundary:{str(dict(request_facts or {}).get('facts_id') or 'runtime')}",
        forbidden_actions=tuple(_dedupe(forbidden)),
        required_process=tuple(_dedupe(required)),
        write_allowed=not bool(set(forbidden) & {"edit_workspace", "write_file", "modify_code"}),
        network_allowed=not bool(set(forbidden) & {"search_external", "fetch_url"}),
        shell_allowed="run_command" not in forbidden,
        browser_allowed="use_browser" not in forbidden,
        approval_policy=approval_policy,
        diagnostics={"source": "latest_user_message_and_context", "hard_boundary": True},
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
