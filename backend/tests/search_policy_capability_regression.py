from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.search_policy import normalize_search_policy, operation_allowed_by_search_policy
from capability_system.tool_authorization import build_tool_authorization_index
from capability_system.tool_definitions import build_tool_instances, get_tool_definitions
from harness.runtime import (
    build_runtime_tool_plan,
    tool_instances_for_runtime_tool_plan,
)
from runtime.context_management.system_retrieval import task_operation_requests_context_retrieval


def test_normalized_empty_search_policy_blocks_source_bound_operations() -> None:
    allowed = normalize_search_policy([])

    assert not operation_allowed_by_search_policy("op.web_search", allowed)
    assert not operation_allowed_by_search_policy("op.mcp_retrieval", allowed)
    assert not operation_allowed_by_search_policy("op.mcp_pdf", allowed)
    assert operation_allowed_by_search_policy("op.model_response", allowed)


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
            "task_environment": {"environment_id": "env.test"},
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


def test_graph_work_request_does_not_trigger_system_context_retrieval() -> None:
    allowed = task_operation_requests_context_retrieval(
        {
            "current_turn_context": {
                "work_request_ref": "workreq:graph-node:test",
                "continuation_stage_id": "world_design",
                "selected_task_id": "task.writing.modular_novel.node.world_design",
            },
            "operation_requirement": {"optional_operations": ["op.mcp_retrieval"]},
            "selected_recipe": {"source_kind": "knowledge"},
        },
    )

    assert allowed is False


def test_main_session_can_request_system_context_retrieval() -> None:
    allowed = task_operation_requests_context_retrieval(
        {
            "current_turn_context": {"turn_id": "turn:test"},
            "operation_requirement": {"optional_operations": ["op.mcp_retrieval"]},
            "selected_recipe": {"source_kind": "knowledge"},
        },
    )

    assert allowed is True


def test_direct_agent_invocation_ref_does_not_make_turn_coordination_scoped() -> None:
    allowed = task_operation_requests_context_retrieval(
        {
            "current_turn_context": {
                "turn_id": "turn:test",
                "work_order_id": "work:direct:test",
                "assembly_id": "assembly:direct:test",
            },
            "operation_requirement": {"optional_operations": ["op.mcp_retrieval"]},
            "selected_recipe": {"source_kind": "knowledge"},
        },
    )

    assert allowed is True


def _tool_view(tool_name: str, definitions_by_name: dict[str, object]) -> dict[str, object]:
    definition = definitions_by_name[tool_name]
    return {
        "tool_name": tool_name,
        "operation_id": str(getattr(definition, "operation_id", "") or tool_name),
        "read_only": bool(getattr(definition, "is_read_only", False)),
    }


