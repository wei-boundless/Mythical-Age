from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.capabilities.search_policy import (
    normalize_search_policy,
    operation_allowed_by_search_policy,
    operation_source_class,
    source_allowed_by_search_policy,
)
from capability_system.tools.authorization import build_tool_authorization_index
from capability_system.tools.native_tool_catalog import build_tool_instances, get_tool_definitions
from harness.runtime import (
    build_runtime_tool_plan,
    tool_instances_for_runtime_tool_plan,
)


def test_normalized_empty_search_policy_blocks_source_bound_operations() -> None:
    allowed = normalize_search_policy([])

    assert not operation_allowed_by_search_policy("op.web_search", allowed)
    assert not operation_allowed_by_search_policy("op.mcp_retrieval", allowed)
    assert not operation_allowed_by_search_policy("op.mcp_pdf", allowed)
    assert operation_allowed_by_search_policy("op.model_response", allowed)
    assert not operation_allowed_by_search_policy("op.unknown_search_source", allowed)
    assert operation_source_class("op.mcp_pdf") == "document"
    assert operation_source_class("op.mcp_structured_data") == "data"
    assert operation_source_class("op.read_structured_file") == "data"
    assert operation_source_class("op.codebase_search") == "local_files"
    assert operation_source_class("op.search_agent") == "web"
    assert not source_allowed_by_search_policy("unknown_source", allowed)


def test_harness_service_host_filters_main_runtime_tools_by_search_policy(tmp_path) -> None:
    tools = build_tool_instances(BACKEND_DIR)
    index = build_tool_authorization_index(get_tool_definitions())
    assembly = SimpleNamespace(
        to_dict=lambda: {
            "session_id": "session:test",
            "turn_id": "turn:test",
            "agent_invocation_id": "aginvoke:test",
            "available_tools": [
                _tool_view("memory_search", index.definitions_by_name),
            ],
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {},
        }
    )

    plan = build_runtime_tool_plan(
        runtime_assembly=assembly,
        invocation_kind="task_execution",
        tool_definitions_by_name=index.definitions_by_name,
    )
    filtered = tool_instances_for_runtime_tool_plan(
        tool_instances=tools,
        tool_plan=plan,
    )
    names = {str(getattr(tool, "name", "") or "") for tool in filtered}

    assert "memory_search" in names
    assert "web_search" not in names
    assert "fetch_url" not in names
    assert "read_file" not in names
    assert plan.dispatchable_tool_names == ("memory_search",)


def _tool_view(tool_name: str, definitions_by_name: dict[str, object]) -> dict[str, object]:
    definition = definitions_by_name[tool_name]
    return {
        "tool_name": tool_name,
        "operation_id": str(getattr(definition, "operation_id", "") or tool_name),
        "read_only": bool(getattr(definition, "is_read_only", False)),
    }


