from __future__ import annotations

from pathlib import Path

from langchain_core.tools import BaseTool

from tools.definitions import build_tool_instances


def get_all_tools(base_dir: Path) -> list[BaseTool]:
    return build_tool_instances(base_dir)
