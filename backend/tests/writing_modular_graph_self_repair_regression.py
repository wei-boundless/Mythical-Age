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
