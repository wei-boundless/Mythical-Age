from __future__ import annotations

import asyncio
import importlib.util
import shutil
from pathlib import Path

from api import tasks as tasks_api
from tasks.flow_registry import TaskFlowRegistry
from tasks.coordination_graph_compiler import compile_task_graph_definition_runtime_spec


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGURE_SCRIPT = REPO_ROOT / "scripts" / "configure_writing_modular_novel_graph.py"


class _RuntimeStub:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)


def _load_config_module():
    spec = importlib.util.spec_from_file_location("configure_writing_modular_novel_graph", CONFIGURE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_storage(tmp_path: Path) -> Path:
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / "storage" / "tasks", storage / "tasks")
    shutil.copytree(REPO_ROOT / "storage" / "orchestration", storage / "orchestration")
    return tmp_path


def test_modular_writing_graph_config_compiles_graph_units_and_chapter_batches(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()

    result = config.configure(base_dir)

    assert result["graph_ids"] == [
        "graph.writing.modular_novel.master",
        "graph.writing.modular_novel.design_init",
        "graph.writing.modular_novel.chapter_cycle",
        "graph.writing.modular_novel.finalize",
    ]
    assert result["requested_chapters"] == 50
    assert result["chapter_batch_size"] == 10
    assert result["target_volumes"] == 1
    assert result["chapters_per_volume"] == 50

    registry = TaskFlowRegistry(base_dir)
    graphs = {graph.graph_id: graph for graph in registry.list_task_graphs()}
    for graph_id in result["graph_ids"]:
        assert graph_id in graphs
        assert graphs[graph_id].publish_state == "published"
        assert graphs[graph_id].enabled is True
        assert graphs[graph_id].task_family == "writing_modular_novel"

    chapter_graph = graphs["graph.writing.modular_novel.chapter_cycle"]
    chapter_node_ids = {node.node_id for node in chapter_graph.nodes}
    assert {
        "volume_plan",
        "chapter_outline",
        "chapter_draft",
        "chapter_review",
        "memory_commit_chapter",
        "chapter_progress_router",
        "volume_review",
        "volume_commit",
        "volume_postmortem",
        "world_outline_extension_proposal",
        "extension_review",
        "extension_commit",
        "next_volume_router",
    }.issubset(chapter_node_ids)
    assert {"memory.writing.baseline", "memory.writing.mutable", "memory.writing.artifact_index", "memory.writing.issue_ledger"}.issubset(chapter_node_ids)

    runtime_loop_policy = chapter_graph.metadata["runtime_loop_policy"]
    assert runtime_loop_policy["enabled"] is True
    assert runtime_loop_policy["initial_inputs"]["target_volumes"] == 1
    assert runtime_loop_policy["initial_inputs"]["chapters_per_volume"] == 50
    assert runtime_loop_policy["initial_inputs"]["chapters_per_round"] == 10
    assert runtime_loop_policy["initial_inputs"]["chapter_batch_size"] == 10
    assert [frame["frame_id"] for frame in runtime_loop_policy["frames"]] == ["loop.chapter_batch", "loop.volume"]

    chapter_draft = next(node for node in chapter_graph.nodes if node.node_id == "chapter_draft")
    chapter_router = next(node for node in chapter_graph.nodes if node.node_id == "chapter_progress_router")
    next_volume_router = next(node for node in chapter_graph.nodes if node.node_id == "next_volume_router")
    assert chapter_draft.task_id == "task.writing.modular_novel.node.chapter_draft"
    assert chapter_draft.task_id in {item.task_id for item in registry.list_specific_task_records()}
    assert not any(
        node.task_id.startswith("task.writing.simple_novel.")
        for node in chapter_graph.nodes
        if node.task_id
    )
    assert chapter_draft.contract_bindings["unit_batch"]["unit_kind"] == "chapter"
    assert chapter_draft.contract_bindings["unit_batch"]["requested_count"] == 50
    assert chapter_draft.contract_bindings["unit_batch"]["range_start"] == 1
    assert chapter_draft.contract_bindings["runtime"]["split_policy"]["batch_size"] == 10
    assert chapter_draft.contract_bindings["runtime"]["batch_acceptance_policy"]["mode"] == "review_then_commit"
    assert chapter_draft.contract_bindings["runtime"]["merge_policy"]["mode"] == "wait_all_committed"
    assert chapter_draft.loop_scope_id == "loop.chapter_batch"
    assert chapter_router.loop_route_policy["continue_stage_id"] == "chapter_outline"
    assert chapter_router.loop_route_policy["exit_stage_id"] == "volume_review"
    assert chapter_router.loop_route_policy["target_key"] == "volume_target_words"
    assert next_volume_router.loop_route_policy["continue_stage_id"] == "volume_plan"
    assert next_volume_router.loop_route_policy["target_key"] == "target_volumes"

    edge_pairs = {(edge.source_node_id, edge.target_node_id, edge.edge_type) for edge in chapter_graph.edges}
    assert ("chapter_progress_router", "chapter_outline", "structured_handoff") in edge_pairs
    assert ("chapter_progress_router", "volume_review", "structured_handoff") in edge_pairs
    assert ("memory.writing.baseline", "chapter_draft", "memory_read") in edge_pairs
    assert ("memory_commit_chapter", "memory.writing.artifact_index", "memory_commit") in edge_pairs

    chapter_spec = compile_task_graph_definition_runtime_spec(
        graph=chapter_graph,
        specific_tasks=tuple(registry.list_specific_task_records()),
        communication_protocol=registry.get_task_communication_protocol(chapter_graph.default_protocol_id),
    )
    split_plans = chapter_spec.diagnostics["split_plans"]
    assert chapter_spec.valid is True
    assert [frame["frame_id"] for frame in chapter_spec.loop_frames[:2]] == ["loop.chapter_batch", "loop.volume"]
    assert chapter_spec.loop_frames[0]["entry_stage_id"] == "chapter_outline"
    assert chapter_spec.loop_frames[0]["router_stage_id"] == "chapter_progress_router"
    assert chapter_spec.loop_frames[0]["exit_stage_id"] == "volume_review"
    assert len(split_plans) == 1
    assert split_plans[0]["node_id"] == "chapter_draft"
    assert split_plans[0]["metadata"]["source_path"] == "graph.nodes[chapter_draft].contract_bindings"
    assert len(split_plans[0]["batches"]) == 5
    assert split_plans[0]["batches"][0]["range"] == {"start": 1, "end": 10, "label": "chapter_1_10"}
    assert split_plans[0]["batches"][-1]["range"] == {"start": 41, "end": 50, "label": "chapter_41_50"}
    assert split_plans[0]["merge_readiness_plan"]["ready_condition"] == "all_batches_committed"
    assert len(split_plans[0]["batch_lifecycle_plans"]) == 5
    assert [step["step_type"] for step in split_plans[0]["batch_lifecycle_plans"][0]["steps"]] == [
        "execute",
        "review",
        "repair_loop",
        "commit",
    ]

    master_graph = graphs["graph.writing.modular_novel.master"]
    master_spec = compile_task_graph_definition_runtime_spec(
        graph=master_graph,
        specific_tasks=tuple(registry.list_specific_task_records()),
        communication_protocol=registry.get_task_communication_protocol(master_graph.default_protocol_id),
    )
    assert master_spec.valid is True
    assert [plan.linked_graph_id for plan in master_spec.nested_runtime_plans] == [
        "graph.writing.modular_novel.design_init",
        "graph.writing.modular_novel.chapter_cycle",
        "graph.writing.modular_novel.finalize",
    ]
    assert [node.node_id for node in master_spec.nodes] == [
        "graph_unit.design_init",
        "graph_unit.chapter_cycle",
        "graph_unit.finalize",
    ]
    assert all(node.metadata.get("explicit_graph_unit_node") is True for node in master_spec.nodes)

    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(base_dir)  # type: ignore[assignment]
    try:
        master_package = asyncio.run(
            tasks_api.build_task_system_task_graph_execution_package("graph.writing.modular_novel.master")
        )
        chapter_package = asyncio.run(
            tasks_api.build_task_system_task_graph_execution_package("graph.writing.modular_novel.chapter_cycle")
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert master_package["valid"] is True
    assert master_package["summary"]["graph_unit_count"] == 3
    assert master_package["summary"]["graph_unit_execution_plan_count"] == 3
    assert master_package["summary"]["graph_unit_execution_plan_issue_count"] == 0
    assert [plan["linked_graph_id"] for plan in master_package["graph_unit_execution_plans"]] == [
        "graph.writing.modular_novel.design_init",
        "graph.writing.modular_novel.chapter_cycle",
        "graph.writing.modular_novel.finalize",
    ]
    assert chapter_package["valid"] is True
    assert chapter_package["summary"]["split_plan_count"] == 1
    assert chapter_package["summary"]["split_batch_count"] == 5
    assert chapter_package["summary"]["split_batch_lifecycle_plan_count"] == 5
    assert chapter_package["summary"]["split_batch_lifecycle_step_count"] == 20
    assert chapter_package["summary"]["split_merge_readiness_plan_count"] == 1
