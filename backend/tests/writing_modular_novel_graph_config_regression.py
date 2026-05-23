from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.assembly.runtime_chain import AgentRuntimeChainAssembler
from runtime.contracts.compiler import compile_coordination_contract_manifest
from runtime.contracts.runtime_assembly_builder import build_node_runtime_assembly
from runtime.shared.stage_projection import StageProjectionCycle
from api import task_system as tasks_api
from prompt_library import PromptLibraryRegistry
from task_system.registry.contract_registry import TaskContractRegistry
from task_system.registry.flow_registry import TaskFlowRegistry
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from tests.support.runtime_stubs import QueryRuntimeMemoryFacadeStub, RuntimeBaseDirStub
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
    assert {"memory.writing.baseline", "memory.writing.mutable", "memory.writing.manuscript", "memory.writing.artifact_index", "memory.writing.issue_ledger"}.issubset(chapter_node_ids)

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
    assert "主动搜索任务记忆数据库" in chapter_draft.metadata["role_prompt"]
    assert "每章目标约两千字" in chapter_draft.metadata["role_prompt"]
    assert "最低不得少于一千八百字" in chapter_draft.metadata["role_prompt"]
    assert "不得把十章压缩成剧情摘要" in chapter_draft.metadata["role_prompt"]
    assert "章节正文候选才是交付主体" in chapter_draft.metadata["role_prompt"]
    assert "严格按运行时允许章号逐章书写" in chapter_draft.metadata["role_prompt"]
    assert "按第1章至第10章逐章书写" not in chapter_draft.metadata["role_prompt"]
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
    assert chapter_draft.contract_bindings["runtime"]["tool_execution_policy"]["allowed_tool_names"] == ["memory_search"]
    assert chapter_draft.contract_bindings["runtime"]["tool_execution_policy"]["allowed_operation_refs"] == ["op.memory_read"]
    assert chapter_draft.contract_bindings["runtime"]["tool_execution_policy"]["database_search_only"] is True
    assert chapter_draft.contract_bindings["runtime"]["length_budget"]["target_units"] == 20_000
    assert chapter_draft.contract_bindings["runtime"]["length_budget"]["min_units"] == 18_000
    assert chapter_draft.contract_bindings["runtime"]["length_budget"]["batch_unit_count"] == 10
    assert (
        chapter_draft.contract_bindings["runtime"]["length_budget"]["repair_policy"]["max_repair_rounds"]
        == 4
    )
    assert "最低不得少于一万八千字" in chapter_draft.contract_bindings["runtime"]["length_budget"]["repair_policy"]["repair_instruction"]
    assert chapter_draft.quality_retry_policy["requirements_input_key"] == "chapter_revision_requirements"
    assert chapter_draft.quality_retry_policy["carry_current_output_as"] == "previous_chapter_draft_ref"
    assert "完整重交当前批次小说正文" in chapter_draft.quality_retry_policy["requirements_template"]
    assert "质量门统计：{quality_issue_summary}" in chapter_draft.quality_retry_policy["requirements_template"]
    assert "不是补丁说明" in chapter_draft.quality_retry_policy["requirements_template"]
    assert "最低不得少于1800字" in chapter_draft.quality_retry_policy["requirements_template"]
    assert "整批正文最低不得少于18000字" in chapter_draft.quality_retry_policy["requirements_template"]
    assert "压缩转述" in chapter_draft.quality_retry_policy["requirements_template"]
    replay_template = chapter_draft.executor_policy["replay_sanitization_policy"]["requirements_template"]
    assert "完整重交当前批次小说正文" in replay_template
    assert "不是补丁说明" in replay_template
    assert "最低不得少于1800字" in replay_template
    assert "整批正文最低不得少于18000字" in replay_template
    assert "压缩转述" in replay_template
    assert "requirements_input_key" not in chapter_review.quality_retry_policy
    assert chapter_draft.contract_bindings["runtime"]["batch_acceptance_policy"]["mode"] == "review_then_commit"
    assert chapter_draft.contract_bindings["runtime"]["batch_acceptance_policy"]["max_repair_rounds"] == 4
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
    assert ("memory.writing.manuscript", "chapter_draft", "memory_read") in edge_pairs
    assert ("memory_commit_chapter", "memory.writing.manuscript", "memory_commit") in edge_pairs
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
    assert split_plans[0]["acceptance_policy"]["max_repair_rounds"] == 4
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
    assert "宗门" not in world_prompt
    assert "洪荒时代" not in world_prompt
    assert "世界设定 Bible" in review_prompt
    assert "商业化承载" in review_prompt
    assert "报告第一行必须单独写成" in review_prompt
    assert "审核裁决：返修" in review_prompt
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
    assert "报告第一行必须单独写成" in character_review.metadata["role_prompt"]
    assert "裁决必须是返修或拒绝" in character_review.metadata["role_prompt"]
    assert "人设与关系基准库管理员" in memory_commit_character.metadata["role_prompt"]
    assert "创作架构对齐" in memory_commit_character.metadata["role_prompt"]
    plot_memory_policy = plot_design.contract_bindings["memory"]["memory_read_policy"]
    assert "world_commit_ref" in plot_memory_policy["topics"]
    assert "world_commit_ref" in plot_memory_policy["required_topics"]
    assert "character_commit_ref" not in plot_memory_policy["topics"]
    assert "character_design_ref" not in plot_memory_policy["topics"]
    design_edge_pairs = {(edge.source_node_id, edge.target_node_id, edge.edge_type) for edge in design_graph.edges}
    assert ("memory_commit_world", "plot_design", "structured_handoff") in design_edge_pairs
    assert ("character_review", "design_sync", "structured_handoff") in design_edge_pairs
    assert ("plot_design", "design_sync", "structured_handoff") in design_edge_pairs
    assert ("design_sync", "memory_commit_character", "structured_handoff") in design_edge_pairs
    assert ("memory_commit_character", "outline_design", "structured_handoff") in design_edge_pairs
    assert ("character_review", "plot_design", "structured_handoff") not in design_edge_pairs
    assert ("memory_commit_character", "plot_design", "structured_handoff") not in design_edge_pairs

    workflows = {item.workflow_id: item for item in registry.workflow_registry.list_workflows()}
    assert workflows["workflow.writing.modular_novel.node.world_design"].prompt == world_prompt
    assert workflows["workflow.writing.modular_novel.node.chapter_draft"].prompt == chapter_draft.metadata["role_prompt"]
    prompt_registry = PromptLibraryRegistry(base_dir)
    world_prompt_resource = prompt_registry.resolve_stage_role(
        workflow_id="workflow.writing.modular_novel.node.world_design",
    )
    chapter_prompt_resource = prompt_registry.resolve_stage_role(
        workflow_id="workflow.writing.modular_novel.node.chapter_draft",
    )
    assert world_prompt_resource is not None
    assert world_prompt_resource.resource_type == "stage_role"
    assert world_prompt_resource.content == world_prompt
    assert world_prompt_resource.source_ref == (
        "storage/tasks/task_workflows.json#workflow.writing.modular_novel.node.world_design.prompt"
    )
    assert world_prompt_resource.legacy_projection_ids == ()
    assert chapter_prompt_resource is not None
    assert chapter_prompt_resource.content == chapter_draft.metadata["role_prompt"]
    assert registry.get_projection_binding("task.writing.modular_novel.node.world_design") is None
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
        node_payload = node.to_dict()
        assert "projection_id" not in node_payload
        assert "projection_overlay_id" not in node_payload
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
        assert assembly["metadata"]["role_prompt"] == node_contract.metadata["role_prompt"]
        assert assembly["metadata"]["layered_context"]["memory_reads"]
        artifact_section = next(item for item in assembly["context_sections"] if item["section_id"] == "artifact_policy")
        assert artifact_section["metadata"]["artifact_policy"]["target_paths"]

    chapter_draft_node = next(node for node in graph.nodes if node.node_id == "chapter_draft")
    chapter_draft_contract = next(item for item in manifest.node_contracts if item.node_id == "chapter_draft")
    assert "名家级中文商业网文长篇写手" in chapter_draft_contract.metadata["role_prompt"]
    assert "memory.writing.manuscript" in chapter_draft_node.memory_read_policy["readable_repositories"]
    assert "memory.writing.manuscript" in chapter_draft_node.dynamic_memory_read_policy["repository_node_ids"]
    assert chapter_draft_node.dynamic_memory_read_policy["allow_dynamic_read"] is True
    assert chapter_draft_node.dynamic_memory_read_policy["dynamic_read_tool_name"] == "memory_search"
    assert chapter_draft_node.contract_bindings["memory"]["prewrite_memory_plan_policy"]["enabled"] is True
    assert chapter_draft_node.contract_bindings["memory"]["prewrite_memory_plan_policy"]["required_before_main_prose"] is True
    assert "正文记忆库" in {item["label"] for item in chapter_draft_node.artifact_context_policy["items"]}

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
        assert profile.default_runtime_mode == "standard"
        assert "custom" in profile.enabled_runtime_modes
        assert "coordination_task" in profile.allowed_runtime_lanes
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
        assert profile.model_profile.max_output_tokens >= 65536


def test_modular_writing_model_requirements_prefer_long_output_budget(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    registry = TaskFlowRegistry(base_dir)
    graph_by_id = {graph.graph_id: graph for graph in registry.list_task_graphs()}
    graphs = [
        graph_by_id.get("graph.writing.modular_novel.design_init"),
        graph_by_id.get("graph.writing.modular_novel.chapter_cycle"),
        graph_by_id.get("graph.writing.modular_novel.finalize"),
    ]
    checked_node_ids: set[str] = set()
    for graph in graphs:
        assert graph is not None
        for node in graph.nodes:
            requirement = node.contract_bindings.get("runtime", {}).get("model_requirement")
            if not requirement:
                continue
            checked_node_ids.add(node.node_id)
            assert requirement["preferred_output_tokens"] >= 65536

    assert {"volume_plan", "chapter_outline", "chapter_draft", "chapter_review", "final_assemble"} <= checked_node_ids


def test_modular_writing_formal_memory_is_project_scoped_and_optional_layers_do_not_block_first_batch(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    registry = TaskFlowRegistry(base_dir)
    chapter_graph = registry.get_task_graph("graph.writing.modular_novel.chapter_cycle")
    assert chapter_graph is not None

    repo_nodes = [node for node in chapter_graph.nodes if node.node_id.startswith("memory.writing.")]
    assert repo_nodes
    for node in repo_nodes:
        policy = dict(node.metadata.get("memory_repository", {}).get("lifecycle_policy") or {})
        assert policy["scope_kind"] == "project_scoped"
        assert policy["scope_id_source"] == "runtime_project_id"

    memory_edges = [
        edge
        for edge in chapter_graph.edges
        if edge.edge_type == "memory_read"
    ]
    assert memory_edges
    for edge in memory_edges:
        metadata = dict(edge.metadata or {})
        repository = str(metadata.get("repository") or "")
        if repository == "memory.writing.baseline":
            assert metadata["on_missing"] == "block"
        elif repository in {"memory.writing.mutable", "memory.writing.manuscript"}:
            assert metadata["on_missing"] == "warn"
        assert metadata["resource_lifecycle_policy"]["scope_kind"] == "project_scoped"


def test_modular_writing_world_design_runtime_uses_node_professional_prompt(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    profile = AgentRuntimeRegistry(base_dir).get_profile("agent:writing_modular_creator")
    assert profile is not None
    chain = AgentRuntimeChainAssembler(
        base_dir=base_dir,
        memory_facade=QueryRuntimeMemoryFacadeStub(),
    )
    task_selection = {
        "selected_task_id": "task.writing.modular_novel.node.world_design",
        "task_id": "task.writing.modular_novel.node.world_design",
        "agent_id": "agent:writing_modular_creator",
        "coordination_run_id": "coordrun:test-world-design",
        "continuation_stage_id": "world_design",
        "runtime_lane": "coordination_task",
    }

    from tests.support.runtime_stubs import model_turn_context

    task_selection.update(
        model_turn_context(
            action_intent="edit_workspace",
            work_mode="implementation",
            interaction_intent="create",
            desired_outcome="修复世界观候选并产出世界观设定",
            deliverables=["node_contract_output"],
            planning_required=True,
            todo_required=True,
        )
    )
    runtime = chain.build_runtime(
        session_id="session:test-world-design",
        task_id="taskinst:test-world-design:world_design",
        turn_id="turn:test-world-design",
        message="请根据上一轮评审修复世界观候选，产出世界观设定并提交。",
        source="test",
        task_selection=task_selection,
        current_turn_context_override=task_selection,
        agent_runtime_profile=profile,
    )
    task_contract = dict(dict(runtime["task_operation"]).get("task_contract") or {})
    semantic_contract = dict(task_contract.get("task_requirement_contract") or {})
    mode_policy = dict(task_contract.get("mode_policy") or {})
    stage_projection = StageProjectionCycle().build_from_orchestration(
        task_id="taskinst:test-world-design:world_design",
        task_body_orchestration=dict(runtime["task_body_orchestration"]),
        agent_runtime_spec=dict(runtime["agent_runtime_spec"]),
    )
    sections = [
        dict(item)
        for item in list(dict(stage_projection.soul_runtime_view).get("sections") or [])
        if isinstance(item, dict)
    ]
    section_text = "\n".join(str(item.get("content") or "") for item in sections)
    section_ids = {str(item.get("section_id") or "") for item in sections}

    assert semantic_contract["task_goal_type"] == "task_graph_node_execution"
    assert semantic_contract["domain"] == "task_graph"
    assert semantic_contract["professional_profile_id"] == ""
    assert mode_policy["interaction_mode"] == "role_mode"
    assert mode_policy["mode_reason"] == "task_graph_node_runtime"
    assert "node_professional_prompt_section" in section_ids
    manifest_sections = {
        str(item.get("section_id") or ""): dict(item)
        for item in list(dict(runtime["task_body_orchestration"]).get("prompt_manifest", {}).get("sections") or [])
        if isinstance(item, dict)
    }
    node_prompt_manifest = manifest_sections["node_professional_prompt_section"]
    assert node_prompt_manifest["source_type"] == "prompt_library_resource"
    assert str(node_prompt_manifest["source_id"]).startswith("prompt.task_graph.writing.modular_novel.node.world_design")
    assert "名家级中文商业网文世界架构师" in section_text
    assert "题材专属元素、套路资产或类型预设" in section_text
    assert "结构性代码修复执行员" not in section_text
    assert "code_fix_execution" not in section_text


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
    assert "memory.writing.manuscript" not in node_ids
    assert "memory.writing.issue_ledger" not in node_ids
    assert "memory.writing.artifact_index" not in node_ids
    assert all(edge.target_node_id not in {"memory.writing.baseline", "memory.writing.mutable", "memory.writing.manuscript"} for edge in runtime_spec.edges)
    assert set(runtime_spec.diagnostics["resource_node_ids_excluded_from_execution"]) >= {
        "memory.writing.baseline",
    }
    assert "memory.writing.mutable" not in {node.node_id for node in graph.nodes}
    assert "memory.writing.manuscript" not in {node.node_id for node in graph.nodes}


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
            assert (review_node_id, "memory.writing.manuscript", "memory_commit") not in edge_index

    assert node("graph.writing.modular_novel.design_init", "memory_commit_world").memory_writeback_policy["mode"] == "baseline_commit"
    assert node("graph.writing.modular_novel.design_init", "baseline_memory_seed").memory_writeback_policy["mode"] == "baseline_commit"
    assert node("graph.writing.modular_novel.chapter_cycle", "memory_commit_chapter").memory_writeback_policy["mode"] == "chapter_commit"
    assert node("graph.writing.modular_novel.chapter_cycle", "memory_commit_chapter").memory_writeback_policy["commit_identity_policy"]["mode"] == "scope_and_artifact_refs"
    assert node("graph.writing.modular_novel.chapter_cycle", "volume_commit").memory_writeback_policy["mode"] == "volume_commit"
    assert node("graph.writing.modular_novel.chapter_cycle", "extension_commit").memory_writeback_policy["mode"] == "dynamic_memory_commit"

    chapter_edge_pairs = {(edge.source_node_id, edge.target_node_id, edge.edge_type) for edge in chapter_graph.edges}
    design_edge_pairs = {(edge.source_node_id, edge.target_node_id, edge.edge_type) for edge in design_graph.edges}
    design_edges = {(edge.source_node_id, edge.target_node_id, edge.edge_id): edge for edge in design_graph.edges}
    world_candidate_commit_edge = design_edges[("world_design", "memory_commit_world", "edge.world.commit_candidate")]
    world_review_commit_edge = design_edges[("world_review", "memory_commit_world", "edge.world_review.commit")]
    assert ("world_review", "memory_commit_world", "structured_handoff") in design_edge_pairs
    assert ("world_design", "memory_commit_world", "structured_handoff") in design_edge_pairs
    assert world_candidate_commit_edge.artifact_ref_policy["target_input_key"] == "通过候选正文"
    assert world_review_commit_edge.artifact_ref_policy["target_input_key"] == "审核裁决报告"
    world_commit_context_items = node("graph.writing.modular_novel.design_init", "memory_commit_world").contract_bindings["artifact"]["artifact_context_policy"]["items"]
    required_world_commit_inputs = {
        str(item["input_key"])
        for item in world_commit_context_items
        if item.get("required") is True
    }
    assert required_world_commit_inputs == {"通过候选正文", "审核裁决报告"}
    assert ("outline_review", "baseline_memory_seed", "structured_handoff") in design_edge_pairs
    assert ("chapter_review", "memory_commit_chapter", "structured_handoff") in chapter_edge_pairs
    assert ("volume_review", "volume_commit", "structured_handoff") in chapter_edge_pairs
    assert ("extension_review", "extension_commit", "structured_handoff") in chapter_edge_pairs
    assert ("memory_commit_chapter", "memory.writing.mutable", "memory_commit") in chapter_edge_pairs
    assert ("memory_commit_chapter", "memory.writing.manuscript", "memory_commit") in chapter_edge_pairs
    assert ("memory_commit_chapter", "memory.writing.artifact_index", "memory_commit") in chapter_edge_pairs
    assert ("extension_commit", "memory.writing.mutable", "memory_commit") in chapter_edge_pairs
    assert ("extension_commit", "memory.writing.manuscript", "memory_commit") not in chapter_edge_pairs


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
    assert write_policy["allowed_write_targets"] == ["memory.writing.mutable", "memory.writing.manuscript", "memory.writing.artifact_index"]
    assert write_policy["commit_packet_schema"]["packet_kind"] == "WritingMemoryCommitPacket"
    assert "source_review_ref" in write_policy["commit_packet_schema"]["required_fields"]
    assert "chapter_summaries" in write_policy["commit_packet_schema"]["required_fields"]
    assert "manuscript_fact_index" in write_policy["commit_packet_schema"]["required_fields"]
    assert "next_batch_memory_requests" in write_policy["commit_packet_schema"]["required_fields"]
    assert "memory.writing.manuscript" in write_policy["commit_packet_schema"]["target_repositories"]
    assert chapter_commit.contract_bindings["governance"]["commit_guard"]["reject_on_missing_review_receipt"] is True
    assert chapter_outline.executor_policy["runtime_batch_boundary_policy"]["unit_label"] == "章"
    assert chapter_outline.executor_policy["runtime_batch_boundary_policy"]["list_key"] == "batch_chapter_list"

    baseline_policy = baseline_seed.memory_writeback_policy
    assert baseline_policy["source_review_required"] is True
    assert baseline_policy["source_review_node_id"] == "outline_review"
    assert baseline_policy["allowed_write_targets"] == ["memory.writing.baseline", "memory.writing.artifact_index"]
    assert baseline_seed.contract_bindings["governance"]["write_permission_matrix"]["forbidden_write_targets"] == [
        "memory.writing.mutable",
        "memory.writing.manuscript",
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


def test_modular_writing_memory_taxonomy_and_growth_protocols(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    registry = TaskFlowRegistry(base_dir)
    graphs = {graph.graph_id: graph for graph in registry.list_task_graphs()}
    chapter_graph = graphs["graph.writing.modular_novel.chapter_cycle"]
    design_graph = graphs["graph.writing.modular_novel.design_init"]

    manuscript_repo = next(node for node in chapter_graph.nodes if node.node_id == "memory.writing.manuscript")
    repo_config = manuscript_repo.contract_bindings["memory"]
    assert repo_config["repository_id"] == "writing_modular_manuscript"
    assert set(repo_config["collections"]) >= {
        "approved_chapter_batches",
        "chapter_summaries",
        "manuscript_fact_index",
        "scene_continuity",
        "chapter_hooks",
    }
    assert "chapter_draft" in manuscript_repo.metadata["readable_by"]
    assert "memory_commit_chapter" in manuscript_repo.metadata["write_owner_node_ids"]

    chapter_draft = next(node for node in chapter_graph.nodes if node.node_id == "chapter_draft")
    prewrite_policy = chapter_draft.contract_bindings["memory"]["prewrite_memory_plan_policy"]
    assert prewrite_policy["authority"] == "chapter_writer_self_selects_from_structured_memory_pack"
    assert prewrite_policy["plan_is_not_canon"] is True
    assert set(prewrite_policy["required_sources"]) >= {
        "memory.writing.baseline",
        "memory.writing.mutable",
        "memory.writing.manuscript",
        "chapter_outline_ref",
    }
    assert "写前取材判断" in chapter_draft.metadata["role_prompt"]

    chapter_review = next(node for node in chapter_graph.nodes if node.node_id == "chapter_review")
    assert "取材判断缺失" in chapter_review.metadata["role_prompt"]
    assert chapter_review.contract_bindings["runtime"]["dynamic_expansion"]["silent_absorption_forbidden"] is True

    extension_commit = next(node for node in chapter_graph.nodes if node.node_id == "extension_commit")
    extension_schema = extension_commit.memory_writeback_policy["commit_packet_schema"]
    assert set(extension_schema["required_fields"]) >= {
        "world_detail_cards",
        "character_state_cards",
        "outline_adjustment_cards",
        "continuity_correction_cards",
        "baseline_upgrade_candidate",
    }
    assert extension_schema["target_repositories"] == ["memory.writing.mutable", "memory.writing.artifact_index"]
    assert "memory.writing.manuscript" not in extension_schema["target_repositories"]

    memory_commit_character = next(node for node in design_graph.nodes if node.node_id == "memory_commit_character")
    character_guard = memory_commit_character.contract_bindings["governance"]["commit_guard"]
    assert character_guard["source_review_node_id"] == "character_review"
    assert character_guard["barrier_node_id"] == "design_sync"
    assert character_guard["additional_required_refs"] == ["design_sync_ref"]
    assert set(memory_commit_character.memory_writeback_policy["commit_packet_schema"]["required_fields"]) >= {
        "character_review_ref",
        "design_sync_ref",
        "approved_character_slices",
        "plot_interface_refs",
    }


def test_modular_writing_memory_edges_use_concrete_collection_addresses(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    registry = TaskFlowRegistry(base_dir)
    graphs = {graph.graph_id: graph for graph in registry.list_task_graphs()}
    coarse_collections = {"baseline", "mutable", "manuscript", "issues", "artifact_refs"}

    memory_edges = [
        edge
        for graph in graphs.values()
        for edge in graph.edges
        if edge.edge_type in {"memory_read", "memory_write", "memory_write_candidate", "memory_commit"}
    ]
    artifact_index_repos = [
        node
        for graph in graphs.values()
        for node in graph.nodes
        if node.node_id == "memory.writing.artifact_index"
    ]
    assert artifact_index_repos
    assert {node.node_type for node in artifact_index_repos} == {"memory_repository"}
    assert all(
        dict(spec).get("content_requirement", {}).get("artifact_ref_only_allowed") is True
        for node in artifact_index_repos
        for spec in dict(node.metadata or {}).get("memory_repository", {}).get("collections", [])
    )
    assert memory_edges
    assert not [
        {
            "graph_id": graph.graph_id,
            "edge_id": edge.edge_id,
            "collection": dict(edge.metadata or {}).get("collection"),
        }
        for graph in graphs.values()
        for edge in graph.edges
        if edge.edge_type in {"memory_read", "memory_write", "memory_write_candidate", "memory_commit"}
        and str(dict(edge.metadata or {}).get("collection") or "") in coarse_collections
    ]
    for edge in memory_edges:
        metadata = dict(edge.metadata or {})
        collection = str(metadata.get("collection") or "").strip()
        requirement = dict(metadata.get("content_requirement") or {})
        assert collection
        assert "canonical_text_required" in requirement
        assert "artifact_ref_only_allowed" in requirement
        if edge.edge_type != "memory_read":
            if requirement["canonical_text_required"]:
                assert metadata["materialization_policy"]["canonical_text_mode"] == "full_text"
            else:
                assert metadata["materialization_policy"]["canonical_text_mode"] == "refs_only"


def test_modular_writing_design_parallelism_uses_alignment_barrier(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    registry = TaskFlowRegistry(base_dir)
    graph = registry.get_task_graph("graph.writing.modular_novel.design_init")
    assert graph is not None

    node_ids = {node.node_id for node in graph.nodes}
    assert "character_design" in node_ids
    assert "plot_design" in node_ids
    assert "design_sync" in node_ids

    edge_pairs = {(edge.source_node_id, edge.target_node_id, edge.edge_type) for edge in graph.edges}
    assert ("memory_commit_world", "character_design", "structured_handoff") in edge_pairs
    assert ("memory_commit_world", "plot_design", "structured_handoff") in edge_pairs
    assert ("character_review", "design_sync", "structured_handoff") in edge_pairs
    assert ("plot_design", "design_sync", "structured_handoff") in edge_pairs
    assert ("character_review", "memory_commit_character", "structured_handoff") in edge_pairs
    assert ("design_sync", "memory_commit_character", "structured_handoff") in edge_pairs
    assert ("memory_commit_character", "outline_design", "structured_handoff") in edge_pairs
    assert ("memory_commit_character", "plot_design", "structured_handoff") not in edge_pairs

    plot_design = next(node for node in graph.nodes if node.node_id == "plot_design")
    plot_policy = plot_design.memory_read_policy
    assert plot_policy["required_topics"] == ["world_commit_ref"]
    assert "character_commit_ref" not in plot_policy["topics"]
