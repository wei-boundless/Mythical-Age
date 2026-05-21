from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from runtime.contracts.compiler import compile_coordination_contract_manifest
from runtime.contracts.runtime_assembly_builder import build_node_runtime_assembly
from api import task_system as tasks_api
from task_system.registry.contract_registry import TaskContractRegistry
from task_system.registry.flow_registry import TaskFlowRegistry
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from tests.support.runtime_stubs import RuntimeBaseDirStub
from tests.support.writing_fixtures import load_writing_modular_config_module, seed_writing_storage


_RuntimeStub = RuntimeBaseDirStub
_load_config_module = load_writing_modular_config_module
_seed_storage = seed_writing_storage


def test_modular_writing_graph_config_compiles_graph_modules_and_chapter_batches(tmp_path: Path) -> None:
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
    world_artifact_policy = world_design.contract_bindings["artifact"]["artifact_policy"]
    assert world_artifact_policy["subdir_template"] == "{project_id}"
    assert "{task_run_id}" not in json.dumps(world_artifact_policy, ensure_ascii=False)
    assert world_artifact_policy["artifacts"][0]["path"] == "world/world_candidate_round_{round_index:03d}.md"
    assert world_review.contract_bindings["artifact"]["artifact_policy"]["artifacts"][0]["path"] == "world/world_review_round_{round_index:03d}.md"
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
    assert "只要报告中存在阻塞问题" in review_prompt
    assert "裁决必须是返修或拒绝" in review_prompt
    memory_commit_world = next(node for node in design_graph.nodes if node.node_id == "memory_commit_world")
    world_commit_prompt = memory_commit_world.metadata["role_prompt"]
    assert "没有阻塞问题" in world_commit_prompt
    assert "你必须拒绝提交" in world_commit_prompt
    character_review = next(node for node in design_graph.nodes if node.node_id == "character_review")
    memory_commit_character = next(node for node in design_graph.nodes if node.node_id == "memory_commit_character")
    plot_design = next(node for node in design_graph.nodes if node.node_id == "plot_design")
    assert "只要报告中存在阻塞问题" in character_review.metadata["role_prompt"]
    assert "裁决必须是返修或拒绝" in character_review.metadata["role_prompt"]
    assert "人设与关系基准库管理员" in memory_commit_character.metadata["role_prompt"]
    assert "没有阻塞问题" in memory_commit_character.metadata["role_prompt"]
    plot_memory_policy = plot_design.contract_bindings["memory"]["memory_read_policy"]
    assert "character_commit_ref" in plot_memory_policy["topics"]
    assert "character_commit_ref" in plot_memory_policy["required_topics"]
    assert "character_design_ref" not in plot_memory_policy["topics"]
    design_edge_pairs = {(edge.source_node_id, edge.target_node_id, edge.edge_type) for edge in design_graph.edges}
    assert ("character_review", "memory_commit_character", "structured_handoff") in design_edge_pairs
    assert ("memory_commit_character", "plot_design", "structured_handoff") in design_edge_pairs
    assert ("character_review", "plot_design", "structured_handoff") not in design_edge_pairs

    workflows = {item.workflow_id: item for item in registry.workflow_registry.list_workflows()}
    assert workflows["workflow.writing.modular_novel.node.world_design"].prompt == world_prompt
    assert workflows["workflow.writing.modular_novel.node.chapter_draft"].prompt == chapter_draft.metadata["role_prompt"]
    wrapper_task_ids = {
        "task.writing.modular_novel.master",
        "task.writing.modular_novel.design_init",
        "task.writing.modular_novel.chapter_cycle",
        "task.writing.modular_novel.finalize",
    }
    assert wrapper_task_ids.isdisjoint({item.task_id for item in registry.list_specific_task_records()})
    assert wrapper_task_ids.isdisjoint({item.task_id for item in registry.list_task_assignments()})
    assert wrapper_task_ids.isdisjoint({item.task_id for item in registry.list_projection_bindings()})
    assert not any(
        item.workflow_id in {
            "workflow.writing.modular_novel.master",
            "workflow.writing.modular_novel.design_init",
            "workflow.writing.modular_novel.chapter_cycle",
            "workflow.writing.modular_novel.finalize",
        }
        for item in workflows.values()
    )

    master_graph = graphs["graph.writing.modular_novel.master"]
    assert "model_requirement" not in master_graph.contract_bindings.get("runtime", {})
    assert "subtask_refs" not in master_graph.metadata
    assert master_graph.metadata["graph_module_refs"] == [
        "graph.writing.modular_novel.design_init",
        "graph.writing.modular_novel.chapter_cycle",
        "graph.writing.modular_novel.finalize",
    ]
    for node in master_graph.nodes:
        assert node.node_type == "graph_module"
        assert node.task_id == ""
        assert node.agent_id == ""
        assert node.agent_group_id == ""
        assert node.work_posture == ""
        assert node.projection_id == ""
        assert node.projection_overlay_id == ""
        assert "role_prompt" not in node.metadata
        assert "model_requirement" not in node.contract_bindings.get("runtime", {})
        assert node.contract_bindings["runtime"]["graph_module_runtime"]["linked_graph_id"] == node.metadata["linked_graph_id"]
        assert node.executor_policy["default_executor"] == "graph_module"
        assert node.executor_policy["allowed_executors"] == ["graph_module"]
    master_spec = compile_task_graph_definition_runtime_spec(
        graph=master_graph,
        specific_tasks=tuple(registry.list_specific_task_records()),
        communication_protocol=registry.get_task_communication_protocol(master_graph.default_protocol_id),
    )
    assert master_spec.valid is True
    assert [plan.linked_graph_id for plan in master_spec.graph_module_runtime_plans] == [
        "graph.writing.modular_novel.design_init",
        "graph.writing.modular_novel.chapter_cycle",
        "graph.writing.modular_novel.finalize",
    ]
    assert [node.node_id for node in master_spec.nodes] == [
        "graph_module.design_init",
        "graph_module.chapter_cycle",
        "graph_module.finalize",
    ]
    assert all(node.metadata.get("explicit_graph_module_node") is True for node in master_spec.nodes)
    assert master_spec.subtask_refs == ()
    for node in master_spec.nodes:
        assert node.node_type == "graph_module"
        assert node.role == "graph_module"
        assert node.agent_id == ""
        assert node.runtime_lane == ""
        assert node.projection_id == ""
        assert node.task_id.startswith("task_graph.node.graph.writing.modular_novel.master.graph_module.")
        assert node.metadata["runtime_role"] == "graph_module_container"
        assert node.metadata["model_visible"] is False
        assert "agent_group_id" not in node.metadata
        assert "model_requirement" not in node.metadata
        assert "model_resolution" not in node.metadata
        assert "model_requirement" not in node.metadata["contract_bindings"].get("runtime", {})

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
    assert master_package["summary"]["graph_module_count"] == 3
    assert master_package["summary"]["graph_module_execution_plan_count"] == 3
    assert master_package["summary"]["graph_module_execution_plan_issue_count"] == 0
    assert master_package["summary"]["assembly_count"] == 0
    assert master_package["runtime_spec"]["subtask_refs"] == ()
    assert master_package["node_runtime_assemblies"] == []
    assert [plan["linked_graph_id"] for plan in master_package["graph_module_execution_plans"]] == [
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
                    runtime_registry.get_profile("agent:writing_modular_creator"),
                    runtime_registry.get_profile("agent:writing_modular_reviewer"),
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
        assert "artifact_policy" in visible_section_ids
        assert "memory_snapshot" in visible_section_ids
        assert "memory_snapshot" not in assembly["diagnostics"]["context_sections_hidden_by_profile"]
        assert assembly["metadata"]["layered_context"]["memory_reads"]
        artifact_section = next(item for item in assembly["context_sections"] if item["section_id"] == "artifact_policy")
        assert artifact_section["metadata"]["artifact_policy"]["target_paths"]

    chapter_draft_revision_target = build_node_runtime_assembly(
        manifest=manifest,
        node_id="chapter_draft",
        agent_profile=runtime_registry.get_profile("agent:writing_modular_worker"),
    ).to_dict()
    assert "revision_context" in {item["section_id"] for item in chapter_draft_revision_target["context_sections"]}


def test_modular_writing_profiles_use_text_artifact_runtime_boundary(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    runtime_registry = AgentRuntimeRegistry(base_dir)
    worker = runtime_registry.get_profile("agent:writing_modular_worker")
    creator = runtime_registry.get_profile("agent:writing_modular_creator")
    memory = runtime_registry.get_profile("agent:writing_modular_memory_steward")

    assert worker is not None
    assert creator is not None
    assert memory is not None
    for profile in (worker, creator, memory):
        metadata = profile.metadata
        assert metadata["agent_mode"] == "text_artifact_worker"
        assert metadata["runtime_mode"] == "text_artifact_runtime"
        assert metadata["preexpanded_context_required"] is True
        assert metadata["pseudo_tool_output_forbidden"] is True
        assert metadata["file_and_memory_side_effects_owned_by"] == "orchestration_runtime"
        assert "op.read_file" not in profile.allowed_operations
        assert "op.search_text" not in profile.allowed_operations
        assert "op.search_files" not in profile.allowed_operations
        assert "op.delegate_to_agent" not in profile.allowed_operations
        assert "op.write_file" not in profile.allowed_operations
        assert "op.read_file" in profile.blocked_operations
        assert "op.search_text" in profile.blocked_operations
        assert "op.search_files" in profile.blocked_operations
        assert profile.model_profile.timeout_seconds >= 180.0
        assert profile.model_profile.long_output_timeout_seconds >= 600.0
        assert profile.model_profile.max_output_tokens >= 32768


def test_writing_runtime_spec_excludes_memory_repositories_from_execution_nodes(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    registry = TaskFlowRegistry(base_dir)
    graph = registry.get_task_graph("graph.writing.modular_novel.design_init")
    assert graph is not None

    runtime_spec = compile_task_graph_definition_runtime_spec(graph=graph)

    node_ids = {node.node_id for node in runtime_spec.nodes}
    assert "memory.writing.baseline" not in node_ids
    assert "memory.writing.mutable" not in node_ids
    assert "memory.writing.issue_ledger" not in node_ids
    assert "memory.writing.artifact_index" not in node_ids
    assert all(edge.target_node_id not in {"memory.writing.baseline", "memory.writing.mutable"} for edge in runtime_spec.edges)
    assert set(runtime_spec.diagnostics["resource_node_ids_excluded_from_execution"]) >= {
        "memory.writing.baseline",
        "memory.writing.mutable",
    }


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
