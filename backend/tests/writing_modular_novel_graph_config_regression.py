from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import sys
from pathlib import Path

from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from orchestration.runtime_loop.contract_compiler import compile_coordination_contract_manifest
from orchestration.runtime_loop.runtime_assembly_builder import build_node_runtime_assembly
from api import tasks as tasks_api
from tasks.contract_registry import TaskContractRegistry
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
    sys.modules[spec.name] = module
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
    assert result["requested_chapters"] == 500
    assert result["chapter_batch_size"] == 10
    assert result["target_volumes"] == 5
    assert result["chapters_per_volume"] == 100

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
    assert runtime_loop_policy["initial_inputs"]["target_volumes"] == 5
    assert runtime_loop_policy["initial_inputs"]["chapters_per_volume"] == 100
    assert runtime_loop_policy["initial_inputs"]["chapters_per_round"] == 10
    assert runtime_loop_policy["initial_inputs"]["chapter_batch_size"] == 10
    assert runtime_loop_policy["initial_inputs"]["target_chapters"] == 500
    assert runtime_loop_policy["initial_inputs"]["target_words"] == 1_000_000
    assert runtime_loop_policy["initial_inputs"]["volume_target_words"] == 200_000
    assert [frame["frame_id"] for frame in runtime_loop_policy["frames"]] == ["loop.chapter_batch", "loop.volume"]

    chapter_draft = next(node for node in chapter_graph.nodes if node.node_id == "chapter_draft")
    chapter_router = next(node for node in chapter_graph.nodes if node.node_id == "chapter_progress_router")
    next_volume_router = next(node for node in chapter_graph.nodes if node.node_id == "next_volume_router")
    chapter_review = next(node for node in chapter_graph.nodes if node.node_id == "chapter_review")
    volume_plan = next(node for node in chapter_graph.nodes if node.node_id == "volume_plan")
    volume_review = next(node for node in chapter_graph.nodes if node.node_id == "volume_review")
    assert chapter_draft.task_id == "task.writing.modular_novel.node.chapter_draft"
    assert chapter_draft.task_id in {item.task_id for item in registry.list_specific_task_records()}
    assert "名家级中文商业网文长篇写手" in chapter_draft.metadata["role_prompt"]
    assert "头部中文商业网文的连载质感" in chapter_draft.metadata["role_prompt"]
    assert "不能复刻任何具体作者" in chapter_draft.metadata["role_prompt"]
    assert "爽点兑现" in chapter_draft.metadata["role_prompt"]
    assert "章末牵引" in chapter_draft.metadata["role_prompt"]
    assert "名家级中文商业网文章节总审" in chapter_review.metadata["role_prompt"]
    assert "头部连载作品的阅读体验" in chapter_review.metadata["role_prompt"]
    assert "名家级中文商业网文分卷规划师" in volume_plan.metadata["role_prompt"]
    assert "不能复刻任何具体作者" in volume_plan.metadata["role_prompt"]
    assert "名家级中文商业网文卷级总审" in volume_review.metadata["role_prompt"]
    assert not any(
        node.task_id.startswith("task.writing.simple_novel.")
        for node in chapter_graph.nodes
        if node.task_id
    )
    assert chapter_draft.contract_bindings["unit_batch"]["unit_kind"] == "chapter"
    assert chapter_draft.contract_bindings["unit_batch"]["requested_count"] == 500
    assert chapter_draft.contract_bindings["unit_batch"]["range_start"] == 1
    assert chapter_draft.contract_bindings["runtime"]["split_policy"]["batch_size"] == 10
    assert chapter_draft.contract_bindings["runtime"]["length_budget"]["target_units"] == 20_000
    assert chapter_draft.contract_bindings["runtime"]["length_budget"]["batch_unit_count"] == 10
    assert chapter_draft.contract_bindings["runtime"]["batch_acceptance_policy"]["mode"] == "review_then_commit"
    assert chapter_draft.contract_bindings["runtime"]["merge_policy"]["mode"] == "wait_all_committed"
    assert chapter_draft.loop_scope_id == "loop.chapter_batch"
    assert chapter_router.loop_route_policy["continue_stage_id"] == "chapter_outline"
    assert chapter_router.loop_route_policy["exit_stage_id"] == "volume_review"
    assert chapter_router.loop_route_policy["target_key"] == "volume_target_words"
    assert next_volume_router.loop_route_policy["continue_stage_id"] == "volume_plan"
    assert next_volume_router.loop_route_policy["target_key"] == "target_volumes"

    edge_pairs = {(edge.source_node_id, edge.target_node_id, edge.edge_type) for edge in chapter_graph.edges}
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
    assert chapter_spec.loop_frames[0]["continue_stage_id"] == "chapter_outline"
    assert chapter_spec.loop_frames[0]["exit_stage_id"] == "volume_review"
    assert len(split_plans) == 1
    assert split_plans[0]["node_id"] == "chapter_draft"
    assert split_plans[0]["metadata"]["source_path"] == "graph.nodes[chapter_draft].contract_bindings"
    assert len(split_plans[0]["batches"]) == 50
    assert split_plans[0]["batches"][0]["range"] == {"start": 1, "end": 10, "label": "chapter_1_10"}
    assert split_plans[0]["batches"][-1]["range"] == {"start": 491, "end": 500, "label": "chapter_491_500"}
    assert split_plans[0]["merge_readiness_plan"]["ready_condition"] == "all_batches_committed"
    assert len(split_plans[0]["batch_lifecycle_plans"]) == 50
    assert [step["step_type"] for step in split_plans[0]["batch_lifecycle_plans"][0]["steps"]] == [
        "execute",
        "review",
        "repair_loop",
        "commit",
    ]

    design_graph = graphs["graph.writing.modular_novel.design_init"]
    world_design = next(node for node in design_graph.nodes if node.node_id == "world_design")
    world_review = next(node for node in design_graph.nodes if node.node_id == "world_review")
    world_prompt = world_design.metadata["role_prompt"]
    review_prompt = world_review.metadata["role_prompt"]
    assert "名家级中文商业网文世界架构师" in world_prompt
    assert "头部中文商业网文的共性能力" in world_prompt
    assert "不能复刻" in world_prompt
    assert "空间与场域结构" in world_prompt
    assert "交换体系" in world_prompt
    assert "成长与资源体系" in world_prompt
    assert "原创机制" in world_prompt
    assert "题材专属元素、套路资产或类型预设" in world_prompt
    assert "比如" not in world_prompt
    assert "例如" not in world_prompt
    assert "商业化追读钩子" in world_prompt
    assert "世界设定 Bible" in review_prompt
    assert "商业化承载" in review_prompt

    workflows = {item.workflow_id: item for item in registry.workflow_registry.list_workflows()}
    assert workflows["workflow.writing.modular_novel.node.world_design"].prompt == world_prompt
    assert workflows["workflow.writing.modular_novel.node.chapter_draft"].prompt == chapter_draft.metadata["role_prompt"]

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
    assert chapter_package["summary"]["split_batch_count"] == 50
    assert chapter_package["summary"]["split_batch_lifecycle_plan_count"] == 50
    assert chapter_package["summary"]["split_batch_lifecycle_step_count"] == 200
    assert chapter_package["summary"]["split_merge_readiness_plan_count"] == 1


def test_modular_writing_memory_context_is_visible_to_runtime_profiles(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    registry = TaskFlowRegistry(base_dir)
    contract_registry = TaskContractRegistry(base_dir)
    runtime_registry = AgentRuntimeRegistry(base_dir)
    graph = next(
        item
        for item in registry.list_task_graphs()
        if item.graph_id == "graph.writing.modular_novel.chapter_cycle"
    )
    runtime_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=tuple(registry.list_specific_task_records()),
        communication_protocol=registry.get_task_communication_protocol(graph.default_protocol_id),
    )
    manifest = compile_coordination_contract_manifest(
        contract_registry=contract_registry,
        coordination_task=registry.derive_coordination_task_view_from_graph(graph),
        graph_spec=runtime_spec,
        specific_tasks=tuple(registry.list_specific_task_records()),
        communication_protocol=registry.get_task_communication_protocol(graph.default_protocol_id),
        agent_profiles=tuple(
            profile
            for profile in (
                runtime_registry.get_profile("agent:writing_modular_worker"),
                runtime_registry.get_profile("agent:writing_modular_memory_steward"),
            )
            if profile is not None
        ),
    )
    assert manifest.valid is True

    for node_id in ("volume_plan", "chapter_outline", "chapter_draft", "chapter_review", "memory_commit_chapter"):
        node_contract = next(item for item in manifest.node_contracts if item.node_id == node_id)
        assembly = build_node_runtime_assembly(
            manifest=manifest,
            node_id=node_id,
            agent_profile=runtime_registry.get_profile(node_contract.agent_id),
        ).to_dict()
        visible_section_ids = {item["section_id"] for item in assembly["context_sections"]}

        assert assembly["diagnostics"]["layered_context"]["memory_read_edge_count"] > 0
        assert "memory_snapshot" in visible_section_ids
        assert "memory_snapshot" not in assembly["diagnostics"]["context_sections_hidden_by_profile"]
        assert assembly["metadata"]["layered_context"]["memory_reads"]

    chapter_draft_revision_target = build_node_runtime_assembly(
        manifest=manifest,
        node_id="chapter_draft",
        agent_profile=runtime_registry.get_profile("agent:writing_modular_worker"),
    ).to_dict()
    assert "revision_context" in {item["section_id"] for item in chapter_draft_revision_target["context_sections"]}


def test_modular_writing_review_and_commit_memory_boundaries(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    registry = TaskFlowRegistry(base_dir)
    graphs = {graph.graph_id: graph for graph in registry.list_task_graphs()}
    chapter_graph = graphs["graph.writing.modular_novel.chapter_cycle"]
    design_graph = graphs["graph.writing.modular_novel.design_init"]

    def node(graph_id: str, node_id: str):
        graph = graphs[graph_id]
        return next(item for item in graph.nodes if item.node_id == node_id)

    for graph in (design_graph, chapter_graph):
        edge_index = {(edge.source_node_id, edge.target_node_id, edge.edge_type): edge for edge in graph.edges}
        for review_node_id in (
            "world_review",
            "outline_review",
            "chapter_review",
            "volume_review",
            "extension_review",
        ):
            if review_node_id not in {item.node_id for item in graph.nodes}:
                continue
            review_node = next(item for item in graph.nodes if item.node_id == review_node_id)
            assert review_node.memory_writeback_policy["mode"] == "review_and_issue_ledger"
            assert (review_node_id, "memory.writing.issue_ledger", "memory_commit") in edge_index
            assert (review_node_id, "memory.writing.baseline", "memory_commit") not in edge_index
            assert (review_node_id, "memory.writing.mutable", "memory_commit") not in edge_index

    assert node("graph.writing.modular_novel.design_init", "memory_commit_world").memory_writeback_policy["mode"] == "baseline_commit"
    assert node("graph.writing.modular_novel.design_init", "baseline_memory_seed").memory_writeback_policy["mode"] == "baseline_commit"
    assert node("graph.writing.modular_novel.chapter_cycle", "memory_commit_chapter").memory_writeback_policy["mode"] == "chapter_commit"
    assert node("graph.writing.modular_novel.chapter_cycle", "volume_commit").memory_writeback_policy["mode"] == "volume_commit"
    assert node("graph.writing.modular_novel.chapter_cycle", "extension_commit").memory_writeback_policy["mode"] == "dynamic_memory_commit"

    chapter_edge_pairs = {(edge.source_node_id, edge.target_node_id, edge.edge_type) for edge in chapter_graph.edges}
    design_edge_pairs = {(edge.source_node_id, edge.target_node_id, edge.edge_type) for edge in design_graph.edges}
    assert ("world_review", "memory_commit_world", "structured_handoff") in design_edge_pairs
    assert ("outline_review", "baseline_memory_seed", "structured_handoff") in design_edge_pairs
    assert ("chapter_review", "memory_commit_chapter", "structured_handoff") in chapter_edge_pairs
    assert ("volume_review", "volume_commit", "structured_handoff") in chapter_edge_pairs
    assert ("extension_review", "extension_commit", "structured_handoff") in chapter_edge_pairs
    assert ("memory_commit_chapter", "memory.writing.mutable", "memory_commit") in chapter_edge_pairs
    assert ("memory_commit_chapter", "memory.writing.artifact_index", "memory_commit") in chapter_edge_pairs
    assert ("extension_commit", "memory.writing.mutable", "memory_commit") in chapter_edge_pairs


def test_modular_writing_state_protocols_prevent_candidate_review_commit_pollution(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    registry = TaskFlowRegistry(base_dir)
    graphs = {graph.graph_id: graph for graph in registry.list_task_graphs()}
    design_graph = graphs["graph.writing.modular_novel.design_init"]
    chapter_graph = graphs["graph.writing.modular_novel.chapter_cycle"]
    finalize_graph = graphs["graph.writing.modular_novel.finalize"]

    def node(graph_id: str, node_id: str):
        graph = graphs[graph_id]
        return next(item for item in graph.nodes if item.node_id == node_id)

    for graph in (design_graph, chapter_graph, finalize_graph):
        for item in graph.nodes:
            if item.node_id.startswith("memory."):
                continue
            governance = item.contract_bindings["governance"]
            state_boundary = governance["state_boundary"]
            assert state_boundary["raw_dialogue_visibility"] == "forbidden"
            assert state_boundary["on_boundary_violation"] == "fail_closed"
            assert governance["memory_pollution_guard"]["commit_nodes_are_the_only_memory_authority"] is True

            read_policy = item.memory_read_policy
            if read_policy["enabled"]:
                assert read_policy["required_visibility"] is True
                assert read_policy["on_hidden"] == "fail_closed"
                assert read_policy["snapshot_contract"]["visible_to_agent_required"] is True

    chapter_outline = node("graph.writing.modular_novel.chapter_cycle", "chapter_outline")
    chapter_review = node("graph.writing.modular_novel.chapter_cycle", "chapter_review")
    chapter_commit = node("graph.writing.modular_novel.chapter_cycle", "memory_commit_chapter")
    baseline_seed = node("graph.writing.modular_novel.design_init", "baseline_memory_seed")

    assert chapter_outline.contract_bindings["governance"]["state_boundary"]["state_kind"] == "candidate_with_derived_outline_thread_context"
    assert "candidate_artifact" in chapter_outline.contract_bindings["governance"]["state_boundary"]["allowed_write_states"]

    review_policy = chapter_review.review_gate_policy
    assert review_policy["approved_slice_schema"]["packet_kind"] == "WritingReviewApprovedSlices"
    assert review_policy["revision_packet_schema"]["packet_kind"] == "WritingRevisionRequest"
    assert review_policy["memory_write_permission"]["forbid_baseline_write"] is True
    assert review_policy["memory_write_permission"]["forbid_mutable_write"] is True
    assert chapter_review.contract_bindings["governance"]["review_guard"]["review_cannot_write_canon"] is True

    write_policy = chapter_commit.memory_writeback_policy
    assert write_policy["source_review_required"] is True
    assert write_policy["source_review_node_id"] == "chapter_review"
    assert write_policy["source_candidate_node_id"] == "chapter_draft"
    assert write_policy["approved_slices_required"] is True
    assert write_policy["allowed_write_targets"] == ["memory.writing.mutable", "memory.writing.artifact_index"]
    assert write_policy["commit_packet_schema"]["packet_kind"] == "WritingMemoryCommitPacket"
    assert "source_review_ref" in write_policy["commit_packet_schema"]["required_fields"]
    assert chapter_commit.contract_bindings["governance"]["commit_guard"]["reject_on_missing_review_receipt"] is True

    baseline_policy = baseline_seed.memory_writeback_policy
    assert baseline_policy["source_review_required"] is True
    assert baseline_policy["source_review_node_id"] == "outline_review"
    assert baseline_policy["allowed_write_targets"] == ["memory.writing.baseline", "memory.writing.artifact_index"]
    assert baseline_seed.contract_bindings["governance"]["write_permission_matrix"]["forbidden_write_targets"] == [
        "memory.writing.mutable",
        "memory.writing.issue_ledger",
    ]


def test_modular_writing_outline_threads_are_outline_owned_and_derived(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    registry = TaskFlowRegistry(base_dir)
    graphs = {graph.graph_id: graph for graph in registry.list_task_graphs()}
    all_nodes = [node for graph in graphs.values() for node in graph.nodes]
    serialized_graphs = json.dumps([graph.to_dict() for graph in graphs.values()], ensure_ascii=False)

    assert "memory.writing.thread_ledger" not in {node.node_id for node in all_nodes}
    assert "thread_ledger" not in serialized_graphs
    assert "memory.writing.outline_thread" not in serialized_graphs

    design_graph = graphs["graph.writing.modular_novel.design_init"]
    chapter_graph = graphs["graph.writing.modular_novel.chapter_cycle"]
    finalize_graph = graphs["graph.writing.modular_novel.finalize"]

    outline_design = next(node for node in design_graph.nodes if node.node_id == "outline_design")
    baseline_seed = next(node for node in design_graph.nodes if node.node_id == "baseline_memory_seed")
    chapter_outline = next(node for node in chapter_graph.nodes if node.node_id == "chapter_outline")
    chapter_commit = next(node for node in chapter_graph.nodes if node.node_id == "memory_commit_chapter")
    final_review = next(node for node in finalize_graph.nodes if node.node_id == "final_review")

    design_policy = outline_design.contract_bindings["governance"]["outline_thread_policy"]
    assert design_policy["authority"] == "outline_design_committed_canon"
    assert design_policy["mode"] == "outline_owns_plot_threads"
    assert design_policy["forbid_independent_thread_source"] is True
    assert "outline_thread_refs" in design_policy["required_outline_fields"]

    seed_policy = baseline_seed.contract_bindings["runtime"]["outline_thread_policy"]
    assert seed_policy["seed_derived_index_after_commit"] is True
    assert seed_policy["derived_index_contract"] == "WritingOutlineThreadIndex"
    assert seed_policy["derived_index_fields"] == ["outline_thread_refs", "active_outline_thread_refs", "due_outline_thread_refs"]

    for item in (chapter_outline, chapter_commit, final_review):
        policy = item.contract_bindings["runtime"]["outline_thread_policy"]
        assert policy["authority"] == "WritingOutlineThreadIndex"
        assert policy["mode"] == "derived_from_committed_outline"
        assert policy["source_outline_refs_required"] is True
        assert policy["forbid_independent_thread_creation"] is True
        assert policy["fields"] == ["outline_thread_refs", "active_outline_thread_refs", "due_outline_thread_refs"]

    commit_fields = chapter_commit.memory_writeback_policy["commit_packet_schema"]["required_fields"]
    assert "outline_thread_refs" in commit_fields
    assert "active_outline_thread_refs" in commit_fields
    assert "due_outline_thread_refs" in commit_fields
