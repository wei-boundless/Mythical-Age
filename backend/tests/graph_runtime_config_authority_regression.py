from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.loop import assert_graph_config_compatible_with_state
from harness.graph.model_overrides import sanitize_runtime_overrides
from harness.graph.models import GraphHarnessConfig, GraphLoopState, GraphNodeWorkOrder
from harness.graph.runner import GraphRunRunner
from task_system.compiler.graph_compiler import build_graph_compilation_unit
from task_system.compiler.graph_harness_config_publisher import _node_config


def _config(*, config_id: str, model: str = "deepseek-v4-flash", extra_node: bool = False) -> GraphHarnessConfig:
    nodes = [
        {
            "node_id": "module.chapter::chapter_draft",
            "node_type": "agent",
            "task_id": "task.test.chapter_draft",
            "agent_id": "agent:writer",
            "metadata": {
                "runtime_profile": {
                    "model_requirement": {
                        "provider": "deepseek",
                        "model": model,
                        "credential_ref": "env:DEEPSEEK_WRITING_API_KEY",
                    },
                    "runtime_policy": {
                        "prompt_pack_refs_by_invocation": {"task_execution": ["runtime.pack.graph_node_execution"]},
                        "subagent_policy": {"enabled": True, "allowed_subagent_ids": ["agent:writing_modular_worker"]},
                    },
                }
            },
        }
    ]
    if extra_node:
        nodes.append(
            {
                "node_id": "module.chapter::chapter_review",
                "node_type": "review_gate",
                "task_id": "task.test.chapter_review",
            }
        )
    return GraphHarnessConfig(
        config_id=config_id,
        graph_id="graph.test.runtime_authority",
        graph_title="Runtime Authority",
        publish_version="test",
        content_hash="",
        nodes=tuple(nodes),
        edges=(
            {
                "edge_id": "edge:chapter_draft:chapter_review",
                "source_node_id": "module.chapter::chapter_draft",
                "target_node_id": "module.chapter::chapter_review" if extra_node else "module.chapter::chapter_draft",
                "edge_type": "control",
                "semantic_role": "control",
                "scheduler_role": "dependency",
            },
        )
        if extra_node
        else (),
    ).with_content_identity(config_id=config_id)


def _state(config: GraphHarnessConfig) -> GraphLoopState:
    return GraphLoopState(
        state_id="gstate:test",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        session_id="session:test",
        config_id="old-config",
        config_hash="old-hash",
        graph_id=config.graph_id,
        structure_hash=config.expected_structural_hash(),
        config_snapshot_id="old-config",
        config_snapshot_hash="old-hash",
    )


def test_structure_hash_ignores_model_runtime_changes() -> None:
    flash = _config(config_id="ghcfg:flash", model="deepseek-v4-flash")
    pro = _config(config_id="ghcfg:pro", model="deepseek-v4-pro")

    assert flash.content_hash != pro.content_hash
    assert flash.expected_structural_hash() == pro.expected_structural_hash()
    assert_graph_config_compatible_with_state(graph_config=pro, state=_state(flash))


def test_structure_hash_rejects_topology_changes() -> None:
    original = _config(config_id="ghcfg:one-node")
    changed = _config(config_id="ghcfg:two-node", extra_node=True)

    assert original.expected_structural_hash() != changed.expected_structural_hash()
    with pytest.raises(ValueError, match="structure_hash"):
        assert_graph_config_compatible_with_state(graph_config=changed, state=_state(original))


def test_runtime_settings_reject_authorization_expansion() -> None:
    with pytest.raises(ValueError, match="cannot expand"):
        sanitize_runtime_overrides({"tool_policy_overrides": {"nodes": {"chapter_draft": {"allowed_operations": ["op.file_write"]}}}})

    with pytest.raises(ValueError, match="cannot enable subagents"):
        sanitize_runtime_overrides({"subagent_policy": {"enabled": True, "allowed_subagent_ids": ["agent:any"]}})


def test_node_runtime_prompt_policy_survives_graph_publish_projection() -> None:
    node = {
        "node_id": "chapter_draft",
        "node_type": "agent",
        "task_id": "task.test.chapter_draft",
        "runtime_policy": {
            "prompt_policy": {
                "environment_prompt_visibility": "hidden",
                "project_instruction_visibility": "hidden",
                "personality_prompt_visibility": "hidden",
            }
        },
        "metadata": {"managed_by": "test"},
    }

    published = _node_config(node, graph_id="graph.test")

    runtime_policy = published["metadata"]["runtime_profile"]["runtime_policy"]
    assert runtime_policy["prompt_policy"] == {
        "environment_prompt_visibility": "hidden",
        "project_instruction_visibility": "hidden",
        "personality_prompt_visibility": "hidden",
    }
    assert published["runtime_policy"] == runtime_policy


def test_project_scoped_graph_binding_defaults_to_graph_task_workspace_without_environment() -> None:
    unit = build_graph_compilation_unit(
        graph_id="graph.test.project_scoped",
        graph_title="Project Scoped",
        nodes=[],
        edges=[],
        resource_nodes=[],
        environment={},
        permissions={},
        tools={},
        control={},
        protocol_index={},
        graph_runtime_policy={},
        graph_context_policy={},
    )

    assert unit.graph_binding_contract["binding_mode"] == "project_scoped"
    assert unit.graph_binding_contract["workspace_view"] == "graph_task"
    assert "task_environment_id" not in unit.graph_binding_contract


def test_runner_rejects_legacy_active_work_order_without_structure_hash() -> None:
    config = _config(config_id="ghcfg:current")
    state = _state(config)
    order = GraphNodeWorkOrder(
        work_order_id="gwork:test",
        work_kind="agent",
        graph_run_id=state.graph_run_id,
        task_run_id=state.task_run_id,
        node_id="module.chapter::chapter_draft",
        config_id="ghcfg:old",
        config_hash="old-hash",
        task_ref="task.test.chapter_draft",
    )
    runner = GraphRunRunner(services=object(), graph_loop=object(), execute_work_order=lambda **_: None)

    with pytest.raises(ValueError, match="structure_hash missing"):
        runner._validate_work_order(state=state, graph_config=config, work_order=order)
