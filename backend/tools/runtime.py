from __future__ import annotations

from pathlib import Path

from langchain_core.tools import BaseTool

from tools.contracts import ToolExecutionContract
from tools.definitions import ToolDefinition, build_tool_instances, get_tool_definition_map
from tools.tool_registry import ToolRegistry


class ToolRuntime:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.registry = ToolRegistry(base_dir)
        self._instances: list[BaseTool] = []
        self._by_name: dict[str, BaseTool] = {}
        self.reload()

    def reload(self) -> None:
        self.registry.reload()
        self._instances = build_tool_instances(self.base_dir)
        self._by_name = {getattr(tool, "name", ""): tool for tool in self._instances}

    @property
    def instances(self) -> list[BaseTool]:
        return list(self._instances)

    @property
    def definitions(self) -> list[ToolDefinition]:
        return self.registry.tools

    def get_instance(self, name: str | None) -> BaseTool | None:
        if not name:
            return None
        return self._by_name.get(name.strip())

    def get_definition(self, name: str | None) -> ToolDefinition | None:
        return get_tool_definition_map().get((name or "").strip())

    def get_contract(self, name: str | None) -> ToolExecutionContract | None:
        definition = self.get_definition(name)
        if definition is None:
            return None
        return definition.contract
