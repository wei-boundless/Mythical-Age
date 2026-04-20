from __future__ import annotations

from typing import Iterable

from permissions.decision_pipeline import decide_tool_permission, list_allowed_tool_names
from permissions.models import PermissionDecision
from permissions.policy import PERMISSION_MODES, normalize_permission_mode
from runtime.settings import AppSettingsService
from tools.runtime import ToolRuntime


class PermissionService:
    def __init__(self, settings_service: AppSettingsService, tool_runtime: ToolRuntime) -> None:
        self.settings_service = settings_service
        self.tool_runtime = tool_runtime

    def current_mode(self) -> str:
        return normalize_permission_mode(self.settings_service.get_permission_mode())

    def supported_modes(self) -> list[str]:
        return list(PERMISSION_MODES)

    def allowed_tool_names(self, *, allowed_tools: Iterable[str] | None = None) -> list[str]:
        return list_allowed_tool_names(
            self.tool_runtime.definitions,
            mode=self.current_mode(),
            allowed_tools=allowed_tools,
        )

    def can_invoke_tool(
        self,
        tool_name: str | None,
        *,
        allowed_tools: Iterable[str] | None = None,
        direct_route: bool = False,
        tool_input: object | None = None,
    ) -> PermissionDecision:
        if not tool_name:
            return PermissionDecision(False, "missing_tool")

        definition = self.tool_runtime.registry.get_by_name(tool_name)
        if definition is None:
            return PermissionDecision(False, "unknown_tool")

        return decide_tool_permission(
            definition,
            mode=self.current_mode(),
            allowed_tools=allowed_tools,
            direct_route=direct_route,
            tool_input=tool_input,
            tool_instance=self.tool_runtime.get_instance(tool_name),
        )
