from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from permissions import PermissionService
from capability_system.tool_runtime import ToolRuntime


class _SettingsStub:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    def get_permission_mode(self) -> str:
        return self.mode


def test_permission_service_plan_mode_only_surfaces_read_tools() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runtime = ToolRuntime(Path(tmp))
        service = PermissionService(_SettingsStub("plan"), runtime)

        allowed = service.allowed_tool_names()

        assert "get_weather" in allowed
        assert "terminal" not in allowed
        assert "index_multimodal_file" not in allowed


def test_permission_service_default_blocks_destructive_shell_tools() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runtime = ToolRuntime(Path(tmp))

        default_service = PermissionService(_SettingsStub("default"), runtime)
        default_decision = default_service.can_invoke_tool("terminal")
        assert default_decision.allowed is False
        assert default_decision.reason == "policy_default_blocks_high_risk_tool"

        accept_service = PermissionService(_SettingsStub("accept_edits"), runtime)
        accept_decision = accept_service.can_invoke_tool("python_repl")
        assert accept_decision.allowed is True
        assert accept_decision.mode == "accept_edits"

        bypass_service = PermissionService(_SettingsStub("bypass"), runtime)
        bypass_decision = bypass_service.can_invoke_tool("terminal")
        assert bypass_decision.allowed is True
        assert bypass_decision.mode == "bypass"


def test_permission_service_respects_scope_and_direct_route_safety() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runtime = ToolRuntime(Path(tmp))
        service = PermissionService(_SettingsStub("accept_edits"), runtime)

        scoped = service.can_invoke_tool("read_file", allowed_tools=["get_weather"])
        assert scoped.allowed is False
        assert scoped.reason == "tool_not_allowed_by_scope"

        direct = service.can_invoke_tool("read_file", direct_route=True)
        assert direct.allowed is False
        assert direct.reason == "tool_not_safe_for_auto_route"

        explicit_read = service.can_invoke_tool(
            "read_file",
            direct_route=True,
            tool_input={"path": "docs/example.md"},
        )
        assert explicit_read.allowed is True
        assert "route_eligibility:explicit_read_only" in explicit_read.checks
