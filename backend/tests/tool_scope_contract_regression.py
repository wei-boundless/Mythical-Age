from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from permissions.service import PermissionService
from capability_system.tool_contracts import SkillToolScope, ToolContractGate, ToolExecutionContract, ToolScope
from capability_system.tool_runtime import ToolRuntime


class _SettingsStub:
    def get_permission_mode(self) -> str:
        return "accept_edits"


def main() -> None:
    scope = SkillToolScope(
        source="skill",
        allowed_tools=("get_weather",),
        trust_level="project",
        reason="test_skill_scope",
        skill_name="weather-advisor",
    )
    assert scope.allows("get_weather")
    assert not scope.allows("web_search")
    assert scope.to_allowed_tools() == ["get_weather"]

    gate = ToolContractGate(mode="enforce")
    denied = gate.evaluate(
        tool_name="web_search",
        contract=ToolExecutionContract(required_inputs=["query"]),
        tool_input={"query": "latest"},
        tool_scope=scope,
    )
    assert denied.should_block
    assert denied.reason == "tool_not_allowed_by_skill_contract"

    allowed = gate.evaluate(
        tool_name="get_weather",
        contract=ToolExecutionContract(required_inputs=["query"]),
        tool_input={"query": "北京天气"},
        tool_scope=scope,
    )
    assert allowed.allowed

    with tempfile.TemporaryDirectory() as tmp:
        permission = PermissionService(_SettingsStub(), ToolRuntime(Path(tmp)))
        scoped = permission.can_invoke_tool("web_search", allowed_tools=scope)
        assert not scoped.allowed
        assert scoped.reason == "tool_not_allowed_by_scope"

    open_scope = ToolScope(source="skill", reason="no_active_skill")
    assert open_scope.allows("web_search")

    print("ALL PASSED (tool scope contract)")


if __name__ == "__main__":
    main()
