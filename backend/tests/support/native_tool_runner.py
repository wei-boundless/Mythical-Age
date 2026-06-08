from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from capability_system.tools.native_tool_catalog import get_tool_definition_map
from runtime.tool_runtime.native_tools import build_native_runtime_tool
from runtime.tool_runtime.tool_result_envelope import ToolResultEnvelope
from runtime.tool_runtime.tool_use_context import ToolUseContext


def call_native_tool(
    tool_name: str,
    args: dict[str, Any],
    *,
    workspace_root: str | Path,
    **context_kwargs: Any,
) -> ToolResultEnvelope:
    definition = get_tool_definition_map()[tool_name]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None
    context = ToolUseContext(workspace_root=workspace_root, **context_kwargs)
    validation = tool.validate_input(dict(args or {}), context)
    assert validation.allowed, validation
    return asyncio.run(tool.call(validation.normalized_args, context))
