from __future__ import annotations

from collections import Counter

from task_system.registry.flow_registry import TaskFlowRegistry
from task_system.storage import TaskSystemStorage

from tests.support.writing_fixtures import load_writing_modular_config_module


def _by_id(items, key: str = "node_id") -> dict[str, dict]:
    return {str(item.get(key) or ""): dict(item) for item in items}


def test_writer_self_repair_nodes_are_not_injected_into_chapter_topology() -> None:
    module = load_writing_modular_config_module()

    node_ids = [node.node_id for node in module.CHAPTER_NODES]
    edge_by_id = {edge[0]: edge for edge in module.CHAPTER_BUSINESS_EDGES}

    assert "volume_plan_self_repair" not in node_ids
    assert "chapter_outline_self_repair" not in node_ids
    assert "chapter_draft_self_repair" not in node_ids

    assert edge_by_id["edge.volume_plan.outline"][1:3] == ("volume_plan", "chapter_outline")
    assert edge_by_id["edge.outline.draft"][1:3] == ("chapter_outline", "chapter_draft")
    assert edge_by_id["edge.draft.unit_router"][1:3] == ("chapter_draft", "chapter_unit_router")
    assert not any("self_repair" in edge_id for edge_id in edge_by_id)


def test_quality_gate_retry_same_node_remains_enabled_only_for_chapter_draft() -> None:
    module = load_writing_modular_config_module()
    node_by_id = {node.node_id: node for node in module.CHAPTER_NODES}

    draft_payload = module._node_payload(node_by_id["chapter_draft"])
    batch_payload = module._node_payload(node_by_id["chapter_batch_assemble"])
    review_payload = module._node_payload(node_by_id["chapter_review"])
    draft_length_budget = draft_payload["contract_bindings"]["runtime"]["length_budget"]
    draft_quality_policy = draft_payload["quality_retry_policy"]

    assert module.CHAPTER_TARGET_WORDS == 3500
    assert module.CHAPTER_MIN_WORDS == 1800
    assert module.CHAPTER_MAX_WORDS == 8000
    assert draft_quality_policy["quality_failure_mode"] == "retry_same_node"
    assert draft_quality_policy["minimum_metric_ratio"] == 0.0
    assert draft_quality_policy["minimum_metric_per_unit"] == module.CHAPTER_MIN_WORDS
    assert draft_quality_policy["max_quality_retries"] == 1
    assert batch_payload["quality_retry_policy"] == {}
    assert review_payload["quality_retry_policy"] == {}
    assert draft_length_budget["target_enforcement"] == "advisory"
    assert draft_length_budget["target_units"] == module.CHAPTER_TARGET_WORDS
    assert draft_length_budget["min_units"] == module.CHAPTER_MIN_WORDS
    assert draft_length_budget["max_units"] == module.CHAPTER_MAX_WORDS
    assert "length_budget" not in batch_payload["contract_bindings"]["runtime"]
    assert "length_budget" not in review_payload["contract_bindings"]["runtime"]


def test_chapter_draft_prompts_keep_strict_length_contract_hidden_from_runtime_leniency() -> None:
    module = load_writing_modular_config_module()
    node_by_id = {node.node_id: node for node in module.CHAPTER_NODES}

    prompt = node_by_id["chapter_draft"].prompt
    retry_template = module._chapter_draft_quality_retry_policy()["requirements_template"]
    prompt_surface = "\n".join([prompt, retry_template])

    assert "硬性要求，不是建议" in prompt
    assert f"最低不得少于{module.CHAPTER_MIN_WORDS}字" in prompt_surface
    assert "目标字数代表正式连载成稿量" in prompt
    assert "必须完整重交当前" in retry_template
    assert "字数是否达标必须以系统质量门统计为准" in retry_template
    for forbidden in (
        "不要求精确卡字数",
        "超过目标不用压缩",
        "不需要为了贴近目标字数而强行压缩",
        "字数只做监督",
        "实在不够",
    ):
        assert forbidden not in prompt_surface


def test_chapter_draft_writer_runs_directly_with_preloaded_context_memory() -> None:
    module = load_writing_modular_config_module()
    node_by_id = {node.node_id: node for node in module.CHAPTER_NODES}

    draft_payload = module._node_payload(node_by_id["chapter_draft"])
    operation_policy = draft_payload["executor_policy"]["operation_policy"]
    memory_policy = draft_payload["memory_read_policy"]

    assert module.CHAPTER_BATCH_SIZE == 10
    assert module.CHAPTERS_PER_VOLUME == 100
    assert draft_payload["agent_id"] == module.WORKER_AGENT_ID
    assert "runtime_policy" not in draft_payload
    assert not any(str(item).startswith("op.subagent_") for item in operation_policy["allowed_operations"])
    assert memory_policy["enabled"] is True
    assert memory_policy["required_visibility"] is True
    assert memory_policy["access_model"] == "edge_based_repository_read"
    assert set(memory_policy["readable_repositories"]) == {
        "memory.writing.baseline",
        "memory.writing.mutable",
        "memory.writing.manuscript",
    }
    assert "上下文记忆是你的取材依据" in node_by_id["chapter_draft"].prompt


def test_stale_managed_self_repair_task_assets_are_deleted_from_storage(tmp_path) -> None:
    module = load_writing_modular_config_module()
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    registry = TaskFlowRegistry(backend_dir)
    active_node = next(node for node in module.CHAPTER_NODES if node.node_id == "chapter_draft")
    active_task_id = module._node_task_id(active_node.node_id)
    stale_task_id = module._node_task_id("chapter_draft_self_repair")

    module._upsert_task_asset(
        registry,
        task_id=active_task_id,
        title=active_node.title,
        input_contract_id=active_node.input_contract_id,
        output_contract_id=active_node.output_contract_id,
        prompt=active_node.prompt,
        agent_id=module.WORKER_AGENT_ID,
        node_id=active_node.node_id,
    )
    module._upsert_task_asset(
        registry,
        task_id=stale_task_id,
        title="旧正文自修节点",
        input_contract_id=active_node.input_contract_id,
        output_contract_id=active_node.output_contract_id,
        prompt="旧自修提示词",
        agent_id=module.WORKER_AGENT_ID,
        node_id="chapter_draft_self_repair",
    )

    module._delete_stale_managed_node_task_assets(registry, active_task_ids={active_task_id})

    refreshed = TaskFlowRegistry(backend_dir)
    assert refreshed.get_specific_task_record(active_task_id) is not None
    assert refreshed.get_specific_task_record(stale_task_id) is None
    assert all(item.task_id != stale_task_id for item in refreshed.list_task_assignments())
    assert all(item.flow_id != stale_task_id.replace("task.", "flow.", 1) for item in refreshed.list_flows())
    assert all(item.workflow_id != stale_task_id.replace("task.", "workflow.", 1) for item in refreshed.workflow_registry.list_workflows())
    assert all(item.task_id != stale_task_id for item in refreshed.list_explicit_task_execution_policies())
    assert all(item.task_id != stale_task_id for item in refreshed.list_explicit_task_memory_request_profiles())
    assert all(item.task_id != stale_task_id for item in refreshed.list_explicit_flow_contract_bindings())
    payload = TaskSystemStorage(backend_dir).read_object("specific_task_records.json", {"deleted_task_ids": []})
    assert stale_task_id not in set(payload.get("deleted_task_ids") or [])


def test_chapter_loop_scopes_do_not_reference_removed_self_repair_nodes() -> None:
    module = load_writing_modular_config_module()
    frames = {frame["frame_id"]: frame for frame in module._chapter_loop_frames()}

    unit_scope = frames["loop.chapter_unit"]["scope_node_ids"]
    batch_scope = frames["loop.chapter_batch"]["scope_node_ids"]

    assert unit_scope == ["chapter_draft", "chapter_unit_router"]
    assert "chapter_outline_self_repair" not in batch_scope
    assert "chapter_draft_self_repair" not in batch_scope


def test_memory_commit_uses_reviewed_batch_assembly_as_source_candidate() -> None:
    module = load_writing_modular_config_module()
    node_by_id = {node.node_id: node for node in module.CHAPTER_NODES}
    review_prompt = node_by_id["chapter_review"].prompt
    commit_prompt = node_by_id["memory_commit_chapter"].prompt
    commit_payload = module._node_payload(node_by_id["memory_commit_chapter"])
    commit_guard = dict(dict(dict(commit_payload.get("metadata") or {}).get("governance_policy") or {}).get("commit_guard") or {})
    memory_write = dict(commit_payload.get("memory_writeback_policy") or {})

    assert "语义连续性和明显矛盾点检查" in review_prompt
    assert "同一选拔既说三个月后又说三天后" in review_prompt
    assert "审核报告中的章节摘要必须忠实于正文实际状态" in review_prompt
    assert "把仍在继续的战争写成已收束" in commit_prompt
    assert commit_guard["source_candidate_node_id"] == "chapter_batch_assemble"
    assert commit_guard["source_candidate_must_be_repaired_output"] is False
    assert memory_write["source_candidate_node_id"] == "chapter_batch_assemble"
    assert "chapter_batch_assemble_ref" in memory_write["commit_identity_policy"]["artifact_ref_input_keys"]
    assert "chapter_draft_self_repair_ref" not in memory_write["commit_identity_policy"]["artifact_ref_input_keys"]


def test_writing_prompts_define_outline_hierarchy_and_node_handoffs() -> None:
    module = load_writing_modular_config_module()
    node_by_id = {node.node_id: node for node in module.CHAPTER_NODES}
    design_by_id = {node.node_id: node for node in module.DESIGN_NODES}

    outline_design_prompt = design_by_id["outline_design"].prompt
    outline_review_prompt = design_by_id["outline_review"].prompt
    baseline_commit_prompt = design_by_id["baseline_memory_seed"].prompt
    volume_plan_prompt = node_by_id["volume_plan"].prompt
    chapter_outline_prompt = node_by_id["chapter_outline"].prompt
    chapter_draft_prompt = node_by_id["chapter_draft"].prompt
    chapter_review_prompt = node_by_id["chapter_review"].prompt
    memory_commit_prompt = node_by_id["memory_commit_chapter"].prompt

    assert "全书细纲拥有全书结构权" in outline_design_prompt
    assert "每卷必须承接的目标、允许细化的空白、禁止提前或延后的关键节点" in outline_design_prompt
    assert "会导致分纲写手越过大纲" in outline_review_prompt
    assert "不得再出现“阻塞级”“必须裁决”" in outline_review_prompt
    assert "不影响当前卷执行的远期分歧必须标为非阻塞备注" in outline_review_prompt
    assert "带备注通过意味着允许进入基准库" in baseline_commit_prompt
    assert "不能把基准库提交成空" in baseline_commit_prompt
    assert "不得要求作者人工裁决" in baseline_commit_prompt

    assert "分卷计划只能把已通过全书细纲投影到当前卷" in volume_plan_prompt
    assert "全书细纲继承表" in volume_plan_prompt
    assert "不能直接重排全书节奏" in volume_plan_prompt

    assert "分纲写手不得越过大纲" in chapter_outline_prompt
    assert "输入继承证据表" in chapter_outline_prompt
    assert "不能把选拔、筑基、卷末战争等后续阶段压入第1-10章" in chapter_outline_prompt
    assert "运行时任务包里的章号范围是当前节点最高执行边界" in chapter_outline_prompt
    assert "卷内节奏段" in chapter_outline_prompt

    assert "正文写手只执行已通过当前批次细纲" in chapter_draft_prompt
    assert "层级来源链" in chapter_draft_prompt
    assert "不能擅自重排剧情" in chapter_draft_prompt
    assert "当前一章正文创作" in chapter_draft_prompt
    assert "Plan-and-Write 的章节生产流程" in chapter_draft_prompt
    assert "章节场景预算" in chapter_draft_prompt
    assert "预算总和必须接近" in chapter_draft_prompt
    assert "不得把预算表当作正文补量" in chapter_draft_prompt
    assert "系统会在你交稿后用质量门统计当前章实际字数" in chapter_draft_prompt
    assert "本轮 final_answer 中直接交付完整正文" in chapter_draft_prompt

    assert "大纲层级一致性检查" in chapter_review_prompt
    assert "正文越过章节细纲" in chapter_review_prompt
    assert "把层级越界或上游冲突当成带备注通过" in chapter_review_prompt

    assert "上游层级冲突" in memory_commit_prompt
    assert "不能用提交摘要把错误节奏固化成后续权威" in memory_commit_prompt


def test_writer_topology_does_not_register_duplicate_output_contracts() -> None:
    module = load_writing_modular_config_module()
    counts = Counter(spec.contract_id for spec in module._contract_specs())

    assert [contract_id for contract_id, count in counts.items() if count > 1] == []
    assert counts["contract.writing_modular_novel.volume_plan"] == 0
    assert counts["contract.writing.modular_novel.volume_plan"] == 1
    assert counts["contract.writing.modular_novel.chapter_outline"] == 1
    assert counts["contract.writing.modular_novel.chapter_draft"] == 1
    assert counts["contract.writing.modular_novel.chapter_batch_commit"] == 1
