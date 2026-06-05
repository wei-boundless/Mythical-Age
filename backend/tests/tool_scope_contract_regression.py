from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from permissions.service import PermissionService
from permissions.tool_scope import SkillToolScope, ToolScope
from capability_system.tools.contracts import ToolExecutionContract, ToolInvocationValidator
from capability_system.tools.native_tool_runtime import ToolRuntime


class _SettingsStub:
    def get_permission_mode(self) -> str:
        return "accept_edits"


def test_tool_scope_contract_limits_skill_visible_tools() -> None:
    scope = SkillToolScope(
        source="skill",
        allowed_tools=("web_search",),
        trust_level="project",
        reason="test_skill_scope",
        skill_name="compat-test-skill",
    )
    assert scope.allows("web_search")
    assert not scope.allows("read_file")
    assert scope.to_allowed_tools() == ["web_search"]

    validator = ToolInvocationValidator(mode="enforce")
    denied = validator.evaluate(
        tool_name="read_file",
        contract=ToolExecutionContract(required_inputs=["path"]),
        tool_input={"path": "docs/example.md"},
        tool_scope=scope,
    )
    assert denied.should_block
    assert denied.reason == "tool_not_allowed_by_skill_contract"

    allowed = validator.evaluate(
        tool_name="web_search",
        contract=ToolExecutionContract(required_inputs=["query"]),
        tool_input={"query": "北京天气"},
        tool_scope=scope,
    )
    assert allowed.allowed

    with tempfile.TemporaryDirectory() as tmp:
        permission = PermissionService(_SettingsStub(), ToolRuntime(Path(tmp)))
        scoped = permission.can_invoke_tool("read_file", allowed_tools=scope)
        assert not scoped.allowed
        assert scoped.reason == "tool_not_allowed_by_scope"

    open_scope = ToolScope(source="skill", reason="no_active_skill")
    assert open_scope.allows("web_search")



