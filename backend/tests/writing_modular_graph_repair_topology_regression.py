from __future__ import annotations

from collections import Counter

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


def test_quality_gate_retry_same_node_remains_enabled_for_writing_nodes() -> None:
    module = load_writing_modular_config_module()
    node_by_id = {node.node_id: node for node in module.CHAPTER_NODES}

    draft_payload = module._node_payload(node_by_id["chapter_draft"])
    batch_payload = module._node_payload(node_by_id["chapter_batch_assemble"])

    assert draft_payload["quality_retry_policy"]["quality_failure_mode"] == "retry_same_node"
    assert batch_payload["quality_retry_policy"]["quality_failure_mode"] == "retry_same_node"
    assert draft_payload["contract_bindings"]["runtime"]["length_budget"]["target_enforcement"] == "advisory"
    assert draft_payload["contract_bindings"]["runtime"]["length_budget"]["max_units"] == module.CHAPTER_MAX_WORDS


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
    volume_plan_prompt = node_by_id["volume_plan"].prompt
    chapter_outline_prompt = node_by_id["chapter_outline"].prompt
    chapter_draft_prompt = node_by_id["chapter_draft"].prompt
    chapter_review_prompt = node_by_id["chapter_review"].prompt
    memory_commit_prompt = node_by_id["memory_commit_chapter"].prompt

    assert "全书细纲拥有全书结构权" in outline_design_prompt
    assert "每卷必须承接的目标、允许细化的空白、禁止提前或延后的关键节点" in outline_design_prompt
    assert "会导致分纲写手越过大纲" in outline_review_prompt

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
