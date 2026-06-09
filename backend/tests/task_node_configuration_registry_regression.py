from __future__ import annotations

import asyncio
from pathlib import Path

from api import task_system as tasks_api
from task_system import TaskFlowRegistry
from task_system.node_configurations.catalog import build_node_configuration_catalog
from task_system.node_configurations.repository import TaskNodeConfigurationRepository
from tests.support.runtime_stubs import RuntimeBaseDirStub


def test_node_configuration_repository_persists_editable_node_config(tmp_path: Path) -> None:
    repository = TaskNodeConfigurationRepository(tmp_path)

    spec = repository.upsert(
        {
            "node_config_id": "nodecfg.review.writer",
            "title": "Review Writer",
            "description": "Writes review notes from a bounded role prompt.",
            "node_kind": "agent",
            "environment_scope": ["env.office.file_search"],
            "role_prompt": "你是一名审稿员。你只审查作品结构和商业可读性，不扩写正文。",
            "executor_ref": {
                "agent_id": "agent:0",
                "agent_profile_id": "main_interactive_agent",
                "agent_selection_policy": "explicit_agent",
            },
            "contract_bindings": {
                "input_contract_id": "contract.review.input",
                "output_contract_id": "contract.review.output",
            },
            "tool_policy": {"allowed_operations": ["op.model_response"]},
        }
    )

    loaded = TaskNodeConfigurationRepository(tmp_path).get("nodecfg.review.writer")

    assert spec.node_config_id == "nodecfg.review.writer"
    assert loaded is not None
    assert loaded.environment_scope == ("env.office.file_search",)
    assert loaded.executor_ref["agent_profile_id"] == "main_interactive_agent"
    assert "审稿员" in loaded.role_prompt


def test_node_configuration_catalog_derives_graph_node_candidates_and_issues(tmp_path: Path) -> None:
    catalog = build_node_configuration_catalog(
        tmp_path,
        task_graphs=[
            {
                "graph_id": "graph.review",
                "runtime_policy": {"task_environment_id": "env.office.file_search"},
                "nodes": [
                    {
                        "node_id": "node.review",
                        "node_type": "agent",
                        "title": "Review",
                        "agent_id": "agent:missing",
                        "input_contract_id": "contract.known",
                        "output_contract_id": "contract.missing",
                        "metadata": {"role_prompt": "你是一名审稿员。你只做审查，不扩写。"},
                    }
                ],
            }
        ],
        agents=[{"agent_id": "agent:0"}],
        profiles=[{"agent_profile_id": "main_interactive_agent"}],
        contract_ids={"contract.known"},
    )

    spec = next(item for item in catalog["node_configurations"] if item["node_config_id"] == "nodecfg.graph.review.node.review")

    assert spec["environment_scope"] == ["env.office.file_search"]
    assert spec["metadata"]["requires_review"] is True
    assert catalog["usage_index"]["nodecfg.graph.review.node.review"] == [
        {"graph_id": "graph.review", "node_id": "node.review"}
    ]
    issue_codes = {item["code"] for item in catalog["issues"]}
    assert "agent_not_found" in issue_codes
    assert "contract_not_found" in issue_codes


def test_node_configuration_runtime_preview_resolves_runtime_profile_by_profile_id(tmp_path: Path) -> None:
    TaskNodeConfigurationRepository(tmp_path).upsert(
        {
            "node_config_id": "nodecfg.preview.profile",
            "title": "Preview Profile",
            "role_prompt": "你是一名节点执行员。你只按契约产出结果。",
            "executor_ref": {
                "agent_profile_id": "main_interactive_agent",
                "agent_selection_policy": "explicit_agent",
            },
        }
    )

    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: RuntimeBaseDirStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            tasks_api.preview_task_system_node_configuration_runtime(
                "nodecfg.preview.profile",
                tasks_api.TaskNodeRuntimePreviewRequest(),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert payload["runtime_profile"]["agent_profile_id"] == "main_interactive_agent"
    assert payload["runtime_start_packet_preview"]["role_prompt"].startswith("你是一名节点执行员")


def test_node_configuration_runtime_preview_resolves_derived_graph_candidate(tmp_path: Path) -> None:
    TaskFlowRegistry(tmp_path).upsert_task_graph(
        graph_id="graph.preview",
        title="Preview Graph",
        nodes=(
            {
                "node_id": "writer",
                "node_type": "agent",
                "title": "Writer",
                "agent_id": "agent:0",
                "metadata": {
                    "role_prompt": "你是一名写作节点执行员。你只根据输入契约产出草稿。",
                },
            },
        ),
    )

    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: RuntimeBaseDirStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            tasks_api.preview_task_system_node_configuration_runtime(
                "nodecfg.graph.preview.writer",
                tasks_api.TaskNodeRuntimePreviewRequest(),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert payload["node_configuration"]["metadata"]["migration_source"] == "task_graph_node"
    assert payload["runtime_start_packet_preview"]["executor_ref"]["agent_id"] == "agent:0"
    assert payload["runtime_start_packet_preview"]["role_prompt"].startswith("你是一名写作节点执行员")
