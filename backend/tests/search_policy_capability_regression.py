from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.search_policy import normalize_search_policy, operation_allowed_by_search_policy
from capability_system import build_default_operation_registry
from capability_system.tool_authorization import build_tool_authorization_index
from capability_system.tool_definitions import build_tool_instances, get_tool_definitions
from runtime.capabilities.current_turn_capability_plan import (
    build_current_turn_capability_plan,
    tool_instances_for_capability_plan,
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
    registry = build_default_operation_registry()
    resource_policy = SimpleNamespace(
        allowed_operations=(
            "op.model_response",
            "op.delegate_to_agent",
            "op.web_search",
            "op.fetch_url",
            "op.read_file",
        ),
        requires_approval_operations=(),
    )

    plan = build_current_turn_capability_plan(
        tool_instances=tools,
        resource_policy=resource_policy,
        definitions_by_name=index.definitions_by_name,
        normalize_operation_id=registry.normalize_id,
        allowed_search_sources={"rag"},
    )
    filtered = tool_instances_for_capability_plan(
        tool_instances=tools,
        capability_plan=plan,
    )
    names = {str(getattr(tool, "name", "") or "") for tool in filtered}
    filtered_reasons = {
        str(item.get("tool_name") or ""): str(item.get("reason") or "")
        for item in plan.filtered_tools
    }

    assert "delegate_to_agent" in names
    assert "web_search" not in names
    assert "fetch_url" not in names
    assert "read_file" not in names
    assert filtered_reasons["web_search"] == "search_policy_blocked"
    assert filtered_reasons["fetch_url"] == "search_policy_blocked"


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


