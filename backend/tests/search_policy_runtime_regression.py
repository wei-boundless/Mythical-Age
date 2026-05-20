from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.search_policy import normalize_search_policy, operation_allowed_by_search_policy
from capability_system.tool_definitions import build_tool_instances
from orchestration.runtime_loop.task_run_loop import TaskRunLoop
from orchestration.runtime_loop.task_run_loop import _resolve_runtime_search_sources


def test_normalized_empty_search_policy_blocks_source_bound_operations() -> None:
    allowed = normalize_search_policy([])

    assert not operation_allowed_by_search_policy("op.web_search", allowed)
    assert not operation_allowed_by_search_policy("op.mcp_retrieval", allowed)
    assert not operation_allowed_by_search_policy("op.mcp_pdf", allowed)
    assert operation_allowed_by_search_policy("op.model_response", allowed)


def test_task_run_loop_filters_main_runtime_tools_by_search_policy(tmp_path) -> None:
    loop = TaskRunLoop(tmp_path, backend_dir=BACKEND_DIR)
    tools = build_tool_instances(BACKEND_DIR)
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

    filtered = loop._tool_instances_for_resource_policy(
        tools,
        resource_policy,
        allowed_search_sources={"rag"},
    )
    names = {str(getattr(tool, "name", "") or "") for tool in filtered}

    assert "delegate_to_agent" in names
    assert "web_search" not in names
    assert "fetch_url" not in names
    assert "read_file" not in names


def test_coordination_task_without_search_policy_defaults_to_no_search_sources() -> None:
    allowed = _resolve_runtime_search_sources(
        search_policy=None,
        task_selection={
            "coordination_run_id": "coordrun:test",
            "continuation_stage_id": "world_design",
            "selected_task_id": "task.writing.modular_novel.node.world_design",
        },
    )

    assert allowed == set()


def test_main_session_without_search_policy_keeps_default_search_sources() -> None:
    allowed = _resolve_runtime_search_sources(
        search_policy=None,
        task_selection={"turn_id": "turn:test"},
    )

    assert {"rag", "local_files", "web"} <= allowed
