from __future__ import annotations

from collections import Counter

from tests.support.writing_fixtures import load_writing_modular_config_module


def _by_id(items, key: str = "node_id") -> dict[str, dict]:
    return {str(item.get(key) or ""): dict(item) for item in items}


def test_writer_self_repair_nodes_are_inserted_before_downstream_review_and_commit() -> None:
    module = load_writing_modular_config_module()

    node_ids = [node.node_id for node in module.CHAPTER_NODES]
    edge_by_id = {edge[0]: edge for edge in module.CHAPTER_BUSINESS_EDGES}

    assert node_ids[node_ids.index("volume_plan") + 1] == "volume_plan_self_repair"
    assert node_ids[node_ids.index("chapter_outline") + 1] == "chapter_outline_self_repair"
    assert node_ids[node_ids.index("chapter_draft") + 1] == "chapter_draft_self_repair"

    assert edge_by_id["edge.volume_plan.self_repair"][1:3] == ("volume_plan", "volume_plan_self_repair")
    assert edge_by_id["edge.volume_plan_repair.outline"][1:3] == ("volume_plan_self_repair", "chapter_outline")
    assert edge_by_id["edge.outline.self_repair"][1:3] == ("chapter_outline", "chapter_outline_self_repair")
    assert edge_by_id["edge.outline_repair.draft"][1:3] == ("chapter_outline_self_repair", "chapter_draft")
    assert edge_by_id["edge.draft.self_repair"][1:3] == ("chapter_draft", "chapter_draft_self_repair")
    assert edge_by_id["edge.draft_repair.review"][1:3] == ("chapter_draft_self_repair", "chapter_review")
    assert module.SOURCE_CANDIDATE_BY_COMMIT_NODE["memory_commit_chapter"] == "chapter_draft_self_repair"


def test_writer_self_repair_nodes_are_candidate_only_without_file_or_memory_tools() -> None:
    module = load_writing_modular_config_module()
    payload_by_id = _by_id([module._node_payload(node) for node in module.CHAPTER_NODES])

    for node_id in ("volume_plan_self_repair", "chapter_outline_self_repair", "chapter_draft_self_repair"):
        node = payload_by_id[node_id]
        prompt = str(dict(node.get("metadata") or {}).get("role_prompt") or "")
        governance = dict(dict(node.get("metadata") or {}).get("governance_policy") or {})
        operation_policy = dict(dict(node.get("executor_policy") or {}).get("operation_policy") or {})
        write_matrix = dict(governance.get("write_permission_matrix") or {})
        self_repair_policy = dict(dict(node.get("contract_bindings") or {}).get("governance") or {}).get("self_repair_policy") or {}

        assert write_matrix["candidate_archive_write"] is True
        assert write_matrix["baseline_memory_write"] is False
        assert write_matrix["mutable_memory_write"] is False
        assert write_matrix["manuscript_memory_write"] is False
        assert "op.read_file" in operation_policy["denied_operations"]
        assert "op.write_file" in operation_policy["denied_operations"]
        assert self_repair_policy["max_repair_passes"] == 1
        assert self_repair_policy["self_check_report_is_not_canonical"] is True
        assert self_repair_policy["forbid_review_verdict"] is True
        assert "不是审核员" in prompt
        assert "不能提交记忆" in prompt
        assert "自修处理记录不是正文事实" in prompt


def test_chapter_draft_self_repair_keeps_long_output_and_full_handoff_budget() -> None:
    module = load_writing_modular_config_module()
    node_by_id = {node.node_id: node for node in module.CHAPTER_NODES}

    draft_repair = node_by_id["chapter_draft_self_repair"]
    draft_payload = module._node_payload(draft_repair)
    draft_runtime = dict(dict(draft_payload.get("contract_bindings") or {}).get("runtime") or {})
    artifact_context = dict(draft_payload.get("artifact_context_policy") or {})
    operation_policy = dict(dict(draft_payload.get("executor_policy") or {}).get("operation_policy") or {})

    assert draft_runtime["model_requirement"]["preferred_output_tokens"] == module.WRITING_CHAPTER_DRAFT_OUTPUT_TOKENS
    assert dict(draft_payload["memory_read_policy"])["token_budget"] == 40000
    assert artifact_context["default_max_chars"] == 60000
    assert "op.text_metric" in operation_policy["allowed_operations"]

    edge = module._business_edge(
        "edge.test",
        "chapter_draft",
        "chapter_draft_self_repair",
        "contract.writing.modular_novel.chapter_draft",
        "正文自修。",
        "待自修候选稿",
    )
    assert edge["artifact_ref_policy"]["target_input_key"] == "待自修候选稿"
    assert edge["artifact_ref_policy"]["max_chars"] == 60000


def test_self_repair_nodes_do_not_register_duplicate_source_output_contracts() -> None:
    module = load_writing_modular_config_module()
    counts = Counter(spec.contract_id for spec in module._contract_specs())

    assert [contract_id for contract_id, count in counts.items() if count > 1] == []
    assert counts["contract.writing.modular_novel.volume_plan"] == 1
    assert counts["contract.writing.modular_novel.chapter_outline"] == 1
    assert counts["contract.writing.modular_novel.chapter_draft"] == 1
    assert counts["contract.writing.modular_novel.chapter_batch_commit"] == 1


def test_chapter_review_and_commit_prompts_guard_semantic_continuity_and_self_repair_pollution() -> None:
    module = load_writing_modular_config_module()
    node_by_id = {node.node_id: node for node in module.CHAPTER_NODES}
    review_prompt = node_by_id["chapter_review"].prompt
    commit_prompt = node_by_id["memory_commit_chapter"].prompt
    commit_payload = module._node_payload(node_by_id["memory_commit_chapter"])
    commit_guard = dict(dict(dict(commit_payload.get("metadata") or {}).get("governance_policy") or {}).get("commit_guard") or {})
    memory_write = dict(commit_payload.get("memory_writeback_policy") or {})

    assert "语义连续性和明显矛盾点检查" in review_prompt
    assert "同一选拔既说三个月后又说三天后" in review_prompt
    assert "同一战争状态既已收束又仍在继续" in review_prompt
    assert "审核报告中的章节摘要必须忠实于正文实际状态" in review_prompt
    assert "自修处理记录、自检说明、返修过程" in commit_prompt
    assert "把仍在继续的战争写成已收束" in commit_prompt
    assert commit_guard["source_candidate_node_id"] == "chapter_draft_self_repair"
    assert commit_guard["source_candidate_must_be_repaired_output"] is True
    assert "自修处理记录（非正史）" in commit_guard["noncanonical_source_sections"]
    assert memory_write["source_candidate_node_id"] == "chapter_draft_self_repair"
    assert "chapter_draft_self_repair_ref" in memory_write["commit_identity_policy"]["artifact_ref_input_keys"]


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
    chapter_outline_repair_prompt = node_by_id["chapter_outline_self_repair"].prompt

    assert "全书细纲拥有全书结构权" in outline_design_prompt
    assert "每卷必须承接的目标、允许细化的空白、禁止提前或延后的关键节点" in outline_design_prompt
    assert "会导致分纲写手越过大纲" in outline_review_prompt

    assert "分卷计划只能把已通过全书细纲投影到当前卷" in volume_plan_prompt
    assert "全书细纲继承表" in volume_plan_prompt
    assert "不能直接重排全书节奏" in volume_plan_prompt

    assert "分纲写手不得越过大纲" in chapter_outline_prompt
    assert "输入继承证据表" in chapter_outline_prompt
    assert "不能把选拔、筑基、卷末战争等后续阶段压入第1-10章" in chapter_outline_prompt

    assert "正文写手只执行已通过当前批次细纲" in chapter_draft_prompt
    assert "层级来源链" in chapter_draft_prompt
    assert "不能擅自重排剧情" in chapter_draft_prompt

    assert "大纲层级一致性检查" in chapter_review_prompt
    assert "正文越过章节细纲" in chapter_review_prompt
    assert "把层级越界或上游冲突当成带备注通过" in chapter_review_prompt

    assert "上游层级冲突" in memory_commit_prompt
    assert "不能用提交摘要把错误节奏固化成后续权威" in memory_commit_prompt

    assert "上游层级冲突/返修请求" in chapter_outline_repair_prompt
    assert "节点对接协议" in chapter_outline_repair_prompt
