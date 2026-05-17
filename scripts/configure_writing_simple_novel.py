import json
import re
import time
from pathlib import Path


NOW = time.time()
MANAGED = "codex_writing_simple_novel_config_20260517"
GROUP_ID = "group.writing.simple_novel"
DOMAIN_ID = "domain.writing.simple_novel"
TASK_FAMILY = "writing_simple_novel"
GRAPH_ID = "graph.writing.simple_novel"
TOPOLOGY_ID = "topology.writing.simple_novel"
PROTOCOL_ID = "protocol.writing.simple_novel"
MEMORY_SCOPE = "writing_simple_novel"
DESIGN_DOC = "docs/系统规划/122-TaskGraph投影Prompt与交接包配置体验设计-20260517.md"
PROMPT_SOURCE_DOC = "docs/系统规划/122-TaskGraph投影Prompt与交接包配置体验设计-20260517.md"
CHAPTERS_PER_ROUND = 10
CHAPTER_TARGET_WORDS = 2000
TARGET_WORDS = 1000000
VOLUME_TARGET_WORDS = 200000
CHAPTERS_PER_VOLUME = VOLUME_TARGET_WORDS // CHAPTER_TARGET_WORDS
HUMAN_REVIEW_ENABLED = False


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def strip_items(items, key, prefixes=(), exact=()):
    return [
        item
        for item in items
        if not (
            isinstance(item, dict)
            and (
                any(str(item.get(key, "")).startswith(prefix) for prefix in prefixes)
                or str(item.get(key, "")) in exact
            )
        )
    ]


def field(field_id, field_type="string", required=False):
    if field_id.endswith("refs") or field_id.endswith("issues") or field_id.endswith("requirements"):
        field_type = "array"
    if field_id.endswith("instructions") or field_id.endswith("commits") or field_id.endswith("indexes"):
        field_type = "array"
    return {
        "field_id": field_id,
        "title_zh": field_id,
        "field_type": field_type,
        "required": required,
        "description": f"{field_id}。",
        "default_value": None,
        "schema": {},
        "source_hint": "node_output",
        "visibility": "model_visible",
    }


def contract(contract_id, fields, title=None, kind="node_execution"):
    return {
        "contract_id": contract_id,
        "title_zh": title or contract_id.split(".")[-1],
        "title_en": contract_id.split(".")[-1],
        "contract_kind": kind,
        "description": f"写作组简易长篇小说契约：{contract_id}。",
        "input_fields": [],
        "output_fields": [
            field(f, required=f in {"project_id", "candidate_id", "review_id", "verdict", "canon_id", "memory_pack_id", "receipt_id"})
            for f in fields
        ],
        "acceptance_rules": [
            "必须符合 122 设计书的投影 Prompt、交接包与边式记忆闭环要求。",
            "不得用普通消息文本代替结构化契约和 artifact refs。",
            "业务节点只能交接结构化引用；记忆库读写必须由 TaskGraph 的 memory_read、memory_write_candidate、memory_commit 边声明。",
        ],
        "metadata": {"managed_by": MANAGED, "domain_id": DOMAIN_ID, "task_family": TASK_FAMILY},
        "artifact_ref_policy": {"required_for_long_outputs": True, "raw_full_text_handoff": "forbidden_for_full_novel"},
    }


def artifact_policy(path):
    return {
        "enabled": True,
        "required": True,
        "source": "task_graph_node",
        "default_artifact_root": "output/novel_artifacts/simple_novel/runs",
        "subdir_template": "",
        "artifact_target": path,
        "storage_policy": "task_artifact_ref",
        "artifacts": [{"path": path, "required": True, "content_source": "final_content", "fallback_to_full_content": False}],
    }


def stream_policy(node_id, role):
    node_id = str(node_id or "").strip()
    enabled = role in {"creator", "reviewer", "memory_steward", "router", "final_assembler"}
    return {
        "enabled": enabled,
        "mode": "model_text_stream" if enabled else "disabled",
        "monitor_visibility": "task_graph_monitor" if enabled else "none",
        "chunk_event_type": "content_delta" if enabled else "",
        "emit_text_preview": bool(enabled),
        "preview_char_limit": 6000 if enabled else 0,
        "persist_full_stream_text": False,
        "fallback_to_non_stream_on_error": True,
    }


def memory_read_policy(role, node_id=""):
    node_id = str(node_id or "").strip()
    node_topics = {
        "project_brief": ["user_goal", "delivery_requirements", "source_refs"],
        "world_design": ["project_brief", "user_goal", "source_refs"],
        "world_review": ["project_brief", "world_candidate_ref"],
        "memory_commit_world": ["world_review", "world_candidate_ref", "project_brief"],
        "baseline_memory_seed": ["project_brief", "world_commit_ref", "source_refs"],
        "volume_plan": ["project_brief", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "delivery_requirements"],
        "chapter_outline": ["baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory", "volume_plan", "previous_chapter_summary", "previous_chapter_review", "chapter_revision_requirements", "current_batch_inputs"],
        "chapter_draft": ["baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory", "volume_plan", "chapter_outline_ref", "previous_chapter_summary", "previous_chapter_review", "chapter_revision_requirements", "current_batch_inputs"],
        "chapter_review": ["baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory", "volume_plan", "chapter_outline_ref", "chapter_draft_ref", "previous_chapter_summary", "chapter_issue_ledger"],
        "memory_commit_chapter": ["chapter_review", "chapter_outline_ref", "chapter_draft_ref", "chapter_file_refs", "previous_chapter_summary", "baseline_memory", "mutable_memory"],
        "chapter_progress_router": ["chapter_commit", "completed_chapter_refs", "volume_current_words", "volume_target_words", "chapter_issue_ledger"],
        "volume_review": ["baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory", "volume_plan", "chapter_commit_refs", "chapter_summary_refs", "volume_issue_ledger"],
        "volume_commit": ["volume_review", "chapter_commit_refs", "chapter_summary_refs", "baseline_memory", "mutable_memory"],
        "volume_postmortem": ["volume_commit", "chapter_summary_refs", "volume_review", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory"],
        "world_outline_extension_proposal": ["volume_postmortem", "volume_commit", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory"],
        "extension_review": ["world_outline_extension_proposal", "volume_postmortem", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory"],
        "extension_commit": ["extension_review", "world_outline_extension_proposal", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory"],
        "next_volume_router": ["extension_commit", "volume_commit", "completed_volume_refs", "current_words", "target_words", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory", "volume_plan"],
        "final_assemble": ["baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory", "volume_commit_manifest", "chapter_file_refs", "chapter_summary_refs", "delivery_requirements", "open_issue_refs"],
        "final_review": ["final_manuscript_ref", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory", "volume_commit_manifest", "open_issue_refs"],
        "memory_finalize": ["final_review", "final_manuscript_ref", "delivery_manifest_id", "volume_commit_manifest"],
        "fail_closed": ["safe_state_refs", "last_successful_commit_refs", "failure_reason"],
        "human_review_handoff": ["safe_state_refs", "blocking_issues"],
    }
    role_topics = {
        "creator": ["project_brief", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "volume_plan", "mutable_memory", "issue_ledger", "previous_review", "current_volume_commit"],
        "reviewer": ["project_brief", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "volume_plan", "chapter_summary", "chapter_commit", "mutable_memory", "issue_ledger", "previous_review"],
        "memory_steward": ["baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory", "volume_plan", "chapter_commit", "volume_commit", "mutable_memory_update_instructions", "delivery_requirements", "issue_ledger"],
        "router": ["volume_plan_commit", "completed_chapter_refs", "completed_volume_refs", "open_issue_refs", "current_words", "target_words", "volume_target_words"],
        "final_assembler": ["delivery_requirements", "volume_commit_manifest", "chapter_file_refs", "chapter_summary_refs", "open_issue_refs", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "mutable_memory"],
        "human": ["safe_state_refs", "blocking_issues"],
    }
    topics = node_topics.get(node_id) or role_topics.get(role, ["project_state"])
    required_topics = {
        "world_design": ["project_brief"],
        "world_review": ["project_brief", "world_candidate_ref"],
        "memory_commit_world": ["world_review", "world_candidate_ref"],
        "baseline_memory_seed": ["project_brief", "world_commit_ref"],
        "volume_plan": ["baseline_memory", "frozen_character_facts", "frozen_relationship_facts"],
        "chapter_outline": ["baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "volume_plan"],
        "chapter_draft": ["baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "volume_plan", "chapter_outline_ref"],
        "chapter_review": ["baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "chapter_outline_ref", "chapter_draft_ref"],
        "memory_commit_chapter": ["chapter_review", "chapter_outline_ref", "chapter_draft_ref"],
        "chapter_progress_router": ["chapter_commit"],
        "volume_review": ["baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "chapter_commit_refs"],
        "volume_commit": ["volume_review"],
        "volume_postmortem": ["volume_commit", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts"],
        "world_outline_extension_proposal": ["volume_postmortem", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts"],
        "extension_review": ["world_outline_extension_proposal", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts"],
        "extension_commit": ["extension_review"],
        "next_volume_router": ["extension_commit", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "current_words", "target_words"],
        "final_assemble": ["baseline_memory", "frozen_character_facts", "frozen_relationship_facts", "volume_commit_manifest", "chapter_file_refs"],
        "final_review": ["final_manuscript_ref", "baseline_memory", "frozen_character_facts", "frozen_relationship_facts"],
        "memory_finalize": ["final_review"],
    }.get(node_id, [])
    forbidden_topics = {
        "world_design": ["baseline_memory", "mutable_memory", "chapter_full_text"],
        "world_review": ["baseline_memory", "mutable_memory", "future_volume_full_text"],
        "memory_commit_world": ["baseline_memory_write", "mutable_memory_write"],
        "baseline_memory_seed": ["mutable_memory", "chapter_commit", "volume_commit"],
        "volume_plan": ["chapter_full_text"],
        "chapter_draft": ["future_volume_full_text", "full_project_raw_dialogue"],
        "chapter_review": ["future_volume_full_text", "full_project_raw_dialogue"],
        "world_outline_extension_proposal": ["future_unwritten_plan_as_fact", "frozen_character_fact_rewrite", "frozen_relationship_rewrite"],
        "extension_review": ["future_unwritten_plan_as_fact", "frozen_character_fact_rewrite", "frozen_relationship_rewrite"],
        "extension_commit": ["baseline_memory_write", "frozen_character_fact_rewrite", "frozen_relationship_rewrite"],
    }.get(node_id, ["raw_conversation_history"])
    return {
        "mode": "memory_pack_required",
        "access_model": "edge_based_repository_read",
        "topics": topics,
        "required_topics": required_topics,
        "forbidden_topics": forbidden_topics,
        "readable_kinds": ["baseline_memory", "mutable_memory", "candidate_ref", "review_record", "issue_ledger", "chapter_summary", "chapter_file_ref", "world_commit", "volume_commit", "delivery_manifest", "frozen_character_fact", "frozen_relationship_fact"],
        "readable_scopes": [MEMORY_SCOPE, "project_state", "node_scope"],
        "summary_only": True,
        "enabled": True,
        "read_request_contract_id": "contract.writing.simple_novel.memory_read_request",
        "result_contract_id": "contract.writing.simple_novel.memory_pack",
        "suppress_conversation_memory": role in {"creator", "reviewer", "router", "final_assembler"},
        "token_budget": 6000,
    }


def memory_write_policy(role, node_id=""):
    node_id = str(node_id or "").strip()
    node_modes = {
        "memory_commit_world": ("world_commit_manifest_only", ["world_commit_manifest"]),
        "baseline_memory_seed": ("baseline_memory_seed", ["baseline_memory"]),
        "memory_commit_chapter": ("chapter_commit_manifest_only", ["chapter_commit_manifest"]),
        "volume_commit": ("volume_commit_manifest_only", ["volume_commit_manifest"]),
        "volume_postmortem": ("volume_commit_receipt_only", ["volume_commit_manifest"]),
        "extension_commit": ("mutable_memory_update", ["mutable_memory"]),
        "final_assemble": ("delivery_manifest_only", ["delivery_manifest_index"]),
        "final_review": ("delivery_manifest_only", ["delivery_manifest_index"]),
        "memory_finalize": ("delivery_manifest_only", ["delivery_manifest_index", "task_state"]),
    }
    modes = {
        "creator": ("candidate_archive_only", ["candidate_archive_index"]),
        "reviewer": ("review_and_issue_ledger", ["review_archive_index", "issue_ledger_index"]),
        "memory_steward": node_modes.get(node_id, ("memory_write", ["task_state"])),
        "final_assembler": ("delivery_manifest_only", ["delivery_manifest_index"]),
        "router": ("routing_decision_only", ["runtime_decision_log"]),
    }
    mode, indexes = modes.get(role, ("system_receipt", ["memory_runtime_index"]))
    writable_kinds_by_mode = {
        "world_commit_manifest_only": ["world_commit", "runtime_receipt"],
        "baseline_memory_seed": ["baseline_memory"],
        "mutable_memory_update": ["mutable_memory"],
        "chapter_commit_manifest_only": ["chapter_commit", "runtime_receipt"],
        "volume_commit_manifest_only": ["volume_commit", "runtime_receipt"],
        "volume_commit_receipt_only": ["volume_commit", "runtime_receipt"],
        "delivery_manifest_only": ["delivery_manifest", "runtime_receipt"],
        "candidate_archive_only": ["candidate", "runtime_receipt"],
        "review_and_issue_ledger": ["review", "runtime_receipt"],
        "routing_decision_only": ["runtime_receipt"],
        "system_receipt": ["runtime_receipt"],
    }
    return {
        "mode": mode,
        "access_model": "edge_based_repository_write",
        "capture_artifact_refs": True,
        "writable_indexes": indexes,
        "writable_kinds": writable_kinds_by_mode.get(mode, ["runtime_receipt"]),
        "writable_scopes": [MEMORY_SCOPE, "project_state", "node_scope"],
        "write_scope_guard": {
            "baseline_memory_mutable": node_id == "baseline_memory_seed",
            "mutable_memory_mutable": node_id == "extension_commit",
            "forbid_frozen_character_rewrite": node_id != "baseline_memory_seed",
            "forbid_frozen_relationship_rewrite": node_id != "baseline_memory_seed",
        },
        "write_contract_id": "contract.writing.simple_novel.memory_write_request",
        "receipt_contract_id": "contract.writing.simple_novel.memory_write_receipt",
    }


def artifact_context_policy(node_id):
    context_items = {
        "world_design": [
            {"source": "input_key", "input_key": "previous_review_ref", "label": "上一轮世界观审核意见", "max_chars": 20000},
            {"source": "input_key", "input_key": "previous_candidate_ref", "label": "上一轮世界观原稿", "max_chars": 65000},
        ],
        "world_review": [
            {"source": "input_key", "input_key": "contract.writing.simple_novel.world_candidate:artifact_refs", "label": "待审世界观正文", "max_chars": 65000},
            {"source": "input_key", "input_key": "project_brief_ref", "label": "项目启动包", "max_chars": 16000},
        ],
        "memory_commit_world": [
            {"source": "input_key", "input_key": "contract.writing.simple_novel.world_candidate:artifact_refs", "label": "已审核世界观正文", "max_chars": 65000},
            {"source": "input_key", "input_key": "contract.writing.simple_novel.world_review:artifact_refs", "label": "世界观审核结论", "max_chars": 20000},
        ],
        "chapter_draft": [
            {"source": "input_key", "input_key": "previous_review_ref", "label": "上一轮审核意见", "max_chars": 24000},
            {"source": "input_key", "input_key": "previous_candidate_ref", "label": "上一轮被审核正文", "max_chars": 65000},
        ],
        "chapter_review": [
            {"source": "input_key", "input_key": "contract.writing.simple_novel.chapter_draft:artifact_refs", "label": "待审章节批次正文", "max_chars": 90000},
        ],
        "memory_commit_chapter": [
            {"source": "input_key", "input_key": "contract.writing.simple_novel.chapter_draft:artifact_refs", "label": "待提交章节正文", "max_chars": 90000},
            {"source": "input_key", "input_key": "contract.writing.simple_novel.chapter_review:artifact_refs", "label": "章节审核结论", "max_chars": 24000},
        ],
        "volume_review": [
            {"source": "input_key", "input_key": "contract.writing.simple_novel.chapter_commit:artifact_refs", "label": "本卷章节提交依据", "max_chars": 90000},
        ],
        "world_outline_extension_proposal": [
            {"source": "input_key", "input_key": "previous_review_ref", "label": "上一轮可改动库审核意见", "max_chars": 24000},
            {"source": "input_key", "input_key": "previous_candidate_ref", "label": "上一轮可改动库提案", "max_chars": 50000},
        ],
        "extension_review": [
            {"source": "input_key", "input_key": "contract.writing.simple_novel.world_outline_extension_proposal:artifact_refs", "label": "待审可改动库更新提案", "max_chars": 50000},
        ],
        "final_assemble": [
            {"source": "input_key", "input_key": "previous_review_ref", "label": "上一轮最终审核意见", "max_chars": 24000},
            {"source": "input_key", "input_key": "previous_candidate_ref", "label": "上一轮交付整编结果", "max_chars": 65000},
        ],
        "final_review": [
            {"source": "input_key", "input_key": "contract.writing.simple_novel.final_manuscript:artifact_refs", "label": "待审最终交付稿", "max_chars": 90000},
        ],
    }.get(str(node_id or "").strip(), [])
    return {"items": context_items, "default_max_chars": 20000, "max_items": len(context_items)} if context_items else {}


def revision_context_policy(node_id):
    source_ref_keys = {
        "world_review": "contract.writing.simple_novel.world_candidate:artifact_refs",
        "chapter_review": "contract.writing.simple_novel.chapter_draft:artifact_refs",
        "volume_review": "contract.writing.simple_novel.chapter_commit:artifact_refs",
        "extension_review": "contract.writing.simple_novel.world_outline_extension_proposal:artifact_refs",
        "final_review": "contract.writing.simple_novel.final_manuscript:artifact_refs",
    }
    source_ref_key = source_ref_keys.get(str(node_id or "").strip())
    if not source_ref_key:
        return {}
    requirements = {
        "world_review": "上一轮世界观审核未通过；请读取审核意见和被审核原稿，在原稿基础上逐条修订，不要另起设定。",
        "chapter_review": "上一轮章节批次审核未通过；请读取审核意见和被审核正文，重写本批允许章号内的完整正文。",
        "volume_review": "卷级总审未通过；请读取卷审意见和本卷提交依据，优先修正连续性和设定偏移问题。",
        "extension_review": "可改动库更新提案未通过；请读取审核意见和原提案，只修订可改动库方案，不得改写基准库。",
        "final_review": "最终交付审核未通过；请读取审核意见和当前交付稿，定向修补交付缺陷。",
    }
    return {
        "carry": [
            {"source": "current_review", "input_key": "previous_review_ref"},
            {"source": "inherited_input", "from_key": source_ref_key, "input_key": "previous_candidate_ref"},
        ],
        "requirements_input_key": "revision_requirements",
        "default_requirements": requirements.get(node_id, "上一轮审核未通过；请按审核意见修订。"),
        "clear_input_keys": [source_ref_key],
    }


def quality_retry_policy(node_id):
    if str(node_id or "").strip() != "chapter_draft":
        return {}
    return {
        "enabled": True,
        "retry_stage_id": "chapter_draft",
        "acceptance_policies": ["sectioned_text_batch_quality"],
        "unit_index_key": "chapter_index",
        "unit_start_key": "batch_start_index",
        "unit_end_key": "batch_end_index",
        "unit_count_key": "chapters_per_round",
        "target_metric_key": "batch_target_words",
        "unit_target_metric_key": "chapter_target_words",
        "minimum_metric_ratio": 0.55,
        "minimum_metric_per_unit": 1200,
        "required_heading_patterns": [r"第\s*(?P<index>[0-9一二三四五六七八九十百零〇两]+)\s*[章节回]"],
        "recoverable_issue_prefixes": [
            "insufficient_metric:",
            "missing_required_sections:",
            "empty_content",
            "refusal_or_process_text_detected",
        ],
        "carry_current_output_as": "previous_candidate_ref",
        "requirements_input_key": "chapter_revision_requirements",
        "requirements_template": (
            "上一轮章节正文候选未通过机器质量门，原因：{quality_issues}。"
            "本轮必须重写当前批次全部章节；只输出运行时允许的章号范围，正文必须完整，不得用摘要、提纲、解释或等待补充代替。"
        ),
        "clear_input_keys": ["contract.writing.simple_novel.chapter_draft:artifact_refs"],
    }


def progress_commit_policy(node_id):
    if str(node_id or "").strip() != "memory_commit_chapter":
        return {}
    return {
        "enabled": True,
        "unit_index_key": "chapter_index",
        "unit_start_key": "batch_start_index",
        "unit_end_key": "batch_end_index",
        "unit_count_key": "chapters_per_round",
        "metric_value_key": "content_metric_total",
        "metric_target_key": "batch_target_words",
        "receipt_kind": "progress_unit_commit",
    }


def parse_prompts():
    source = Path(PROMPT_SOURCE_DOC)
    if not source.exists():
        return {}
    text = source.read_text(encoding="utf-8")
    prompts = {}
    for match in re.finditer(r"### 8\.\d+ `([^`]+)`\s*\n\s*```text\s*\n(.*?)\n```", text, re.S):
        prompts[match.group(1)] = match.group(2).strip()
    return prompts


NODE_DEFS = [
    ("project_brief", "项目启动包", "agent:writing_simple_creator", "projection.writing.simple_novel.project_brief", "contract.writing.simple_novel.user_goal", "contract.writing.simple_novel.project_brief", "phase.start", 1, "project_brief.md", "creator"),
    ("world_design", "世界观设定候选", "agent:writing_simple_creator", "projection.writing.simple_novel.world_designer", "contract.writing.simple_novel.project_brief", "contract.writing.simple_novel.world_candidate", "phase.world", 10, "world/world_candidate.md", "creator"),
    ("world_review", "世界观审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.world_reviewer", "contract.writing.simple_novel.world_candidate", "contract.writing.simple_novel.world_review", "phase.world", 20, "world/world_review.md", "reviewer"),
    ("memory_commit_world", "世界观写入", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.world_review", "contract.writing.simple_novel.memory_commit_world", "phase.world", 30, "memory/world/world_commit.md", "memory_steward"),
    ("baseline_memory_seed", "基准记忆库初始化", "agent:writing_memory_steward", "projection.writing.simple_novel.baseline_memory_steward", "contract.writing.simple_novel.memory_commit_world", "contract.writing.simple_novel.baseline_memory_commit", "phase.core", 40, "memory/baseline/baseline_memory_commit.md", "memory_steward"),
    ("volume_plan", "分卷规划", "agent:writing_simple_creator", "projection.writing.simple_novel.volume_planner", "contract.writing.simple_novel.baseline_memory_commit", "contract.writing.simple_novel.volume_plan_commit", "phase.volume_plan", 50, "volume_plan/volume_plan.md", "creator"),
    ("chapter_outline", "当前批次细纲", "agent:writing_simple_creator", "projection.writing.simple_novel.chapter_outliner", "contract.writing.simple_novel.chapter_outline_input", "contract.writing.simple_novel.chapter_outline", "phase.chapter_loop", 120, "volume_{volume_index:03d}/chapters/chapter_{batch_start_index:03d}_{batch_end_index:03d}/outline_round_{round_index:03d}.md", "creator"),
    ("chapter_draft", "当前批次正文候选", "agent:writing_simple_creator", "projection.writing.simple_novel.chapter_writer", "contract.writing.simple_novel.chapter_draft_input", "contract.writing.simple_novel.chapter_draft", "phase.chapter_loop", 130, "volume_{volume_index:03d}/chapters/chapter_{batch_start_index:03d}_{batch_end_index:03d}/draft_round_{round_index:03d}.md", "creator"),
    ("chapter_review", "当前批次轻量审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.chapter_reviewer", "contract.writing.simple_novel.chapter_review_input", "contract.writing.simple_novel.chapter_review", "phase.chapter_loop", 140, "volume_{volume_index:03d}/chapters/chapter_{batch_start_index:03d}_{batch_end_index:03d}/review_round_{round_index:03d}.md", "reviewer"),
    ("memory_commit_chapter", "章节批次写入", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.chapter_review", "contract.writing.simple_novel.chapter_commit", "phase.chapter_loop", 150, "volume_{volume_index:03d}/chapters/chapter_{batch_start_index:03d}_{batch_end_index:03d}/commit_round_{round_index:03d}.md", "memory_steward"),
    ("chapter_progress_router", "章节批次推进判断", "agent:writing_simple_reviewer", "projection.writing.simple_novel.chapter_progress_router", "contract.writing.simple_novel.chapter_commit", "contract.writing.simple_novel.chapter_progress_decision", "phase.chapter_loop", 160, "volume_{volume_index:03d}/routing/progress_round_{round_index:03d}.md", "router"),
    ("volume_review", "卷级总审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.volume_reviewer", "contract.writing.simple_novel.volume_review_input", "contract.writing.simple_novel.volume_review", "phase.volume_review", 200, "volume_{volume_index:03d}/reviews/volume_review.md", "reviewer"),
    ("volume_commit", "卷级写入", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.volume_review", "contract.writing.simple_novel.volume_commit", "phase.volume_review", 210, "volume_{volume_index:03d}/memory/volume_commit.md", "memory_steward"),
    ("volume_postmortem", "卷后复盘", "agent:writing_simple_reviewer", "projection.writing.simple_novel.volume_postmortem", "contract.writing.simple_novel.volume_commit", "contract.writing.simple_novel.volume_postmortem", "phase.volume_extension", 220, "volume_{volume_index:03d}/reviews/volume_postmortem.md", "reviewer"),
    ("world_outline_extension_proposal", "可改动库更新提案", "agent:writing_simple_creator", "projection.writing.simple_novel.world_outline_extension_proposer", "contract.writing.simple_novel.volume_postmortem", "contract.writing.simple_novel.world_outline_extension_proposal", "phase.volume_extension", 230, "volume_{volume_index:03d}/memory/mutable_memory_proposal.md", "creator"),
    ("extension_review", "可改动库更新审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.extension_reviewer", "contract.writing.simple_novel.world_outline_extension_proposal", "contract.writing.simple_novel.extension_review", "phase.volume_extension", 240, "volume_{volume_index:03d}/memory/mutable_memory_review.md", "reviewer"),
    ("extension_commit", "可改动记忆库更新", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.extension_review", "contract.writing.simple_novel.extension_commit", "phase.volume_extension", 250, "volume_{volume_index:03d}/memory/mutable_memory_update.md", "memory_steward"),
    ("next_volume_router", "下一卷推进判断", "agent:writing_simple_reviewer", "projection.writing.simple_novel.next_volume_router", "contract.writing.simple_novel.extension_commit", "contract.writing.simple_novel.next_volume_decision", "phase.volume_extension", 260, "volume_{volume_index:03d}/routing/next_volume_decision.md", "router"),
    ("final_assemble", "交付包整编", "agent:writing_final_assembler", "projection.writing.simple_novel.final_assembler", "contract.writing.simple_novel.next_volume_decision", "contract.writing.simple_novel.final_manuscript", "phase.final", 300, "delivery/delivery_manifest.md", "final_assembler"),
    ("final_review", "最终交付审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.final_reviewer", "contract.writing.simple_novel.final_review_input", "contract.writing.simple_novel.final_review", "phase.final", 310, "delivery/final_review.md", "reviewer"),
    ("memory_finalize", "任务收尾归档", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.final_review", "contract.writing.simple_novel.delivery_package", "phase.final", 320, "delivery/delivery_package.md", "memory_steward"),
    ("human_review_handoff", "人工接管", "agent:0", "hebo__primary", "contract.writing.simple_novel.human_review_input", "contract.writing.simple_novel.human_review_packet", "phase.terminal", 900, "handoff/human_review_packet.md", "human"),
    ("fail_closed", "失败关闭", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.failure_input", "contract.writing.simple_novel.failure_report", "phase.terminal", 910, "failure/failure_report.md", "memory_steward"),
]


MEMORY_REPOSITORY_DEFS = [
    {
        "node_id": "memory.writing.baseline",
        "title": "基准记忆仓库",
        "node_type": "memory_repository",
        "phase_id": "phase.memory_resource",
        "sequence_index": 15,
        "repository_id": "memory.writing.baseline",
        "repository_kind": "memory",
        "mutability": "commit_only",
        "collections": [
            {"collection_id": "world", "title": "世界观主干", "record_kinds": ["baseline_world_spine", "world_rule", "approved_world_spine"]},
            {"collection_id": "outline", "title": "大纲主干", "record_kinds": ["baseline_outline_spine", "volume_plan"]},
            {"collection_id": "characters", "title": "人物事实", "record_kinds": ["baseline_character_spine", "frozen_character_fact"]},
            {"collection_id": "relationships", "title": "关系事实", "record_kinds": ["frozen_relationship_fact"]},
        ],
    },
    {
        "node_id": "memory.writing.mutable",
        "title": "可改动记忆仓库",
        "node_type": "memory_repository",
        "phase_id": "phase.memory_resource",
        "sequence_index": 16,
        "repository_id": "memory.writing.mutable",
        "repository_kind": "memory",
        "mutability": "reviewed_update",
        "collections": [
            {"collection_id": "strategy", "title": "策略调整", "record_kinds": ["strategy_adjustment", "next_volume_focus"]},
            {"collection_id": "outline_delta", "title": "大纲补充", "record_kinds": ["outline_memory_delta", "world_memory_delta"]},
            {"collection_id": "future_chapter_outline", "title": "未开写章纲整理区", "record_kinds": ["future_chapter_outline", "batch_outline_reorg", "next_batch_focus"]},
            {"collection_id": "character_weight", "title": "人物权重", "record_kinds": ["character_weight_delta", "exposure_schedule"]},
        ],
    },
    {
        "node_id": "memory.writing.artifact_index",
        "title": "产物索引仓库",
        "node_type": "memory_repository",
        "phase_id": "phase.memory_resource",
        "sequence_index": 17,
        "repository_id": "memory.writing.artifact_index",
        "repository_kind": "artifact_index",
        "mutability": "append_only",
        "collections": [
            {"collection_id": "candidates", "title": "候选稿索引", "record_kinds": ["candidate", "world_candidate", "chapter_outline", "chapter_draft"]},
            {"collection_id": "reviews", "title": "审核记录", "record_kinds": ["review", "world_review", "chapter_review", "volume_review"]},
            {"collection_id": "world_commits", "title": "世界观提交", "record_kinds": ["world_commit", "approved_world_spine"]},
            {"collection_id": "volume_plans", "title": "分卷计划索引", "record_kinds": ["volume_plan", "volume_plan_slice", "current_volume_plan"]},
            {"collection_id": "chapter_outlines", "title": "章节细纲索引", "record_kinds": ["chapter_outline", "frozen_chapter_outline", "future_chapter_outline"]},
            {"collection_id": "chapter_commits", "title": "章节提交", "record_kinds": ["chapter_commit", "chapter_summary", "chapter_file_ref"]},
            {"collection_id": "volume_commits", "title": "卷级提交", "record_kinds": ["volume_commit", "volume_summary"]},
            {"collection_id": "delivery", "title": "交付清单", "record_kinds": ["delivery_manifest", "delivery_package", "final_manuscript"]},
        ],
    },
    {
        "node_id": "memory.writing.issue_ledger",
        "title": "问题账本仓库",
        "node_type": "issue_ledger",
        "phase_id": "phase.memory_resource",
        "sequence_index": 18,
        "repository_id": "memory.writing.issue_ledger",
        "repository_kind": "issue_ledger",
        "mutability": "append_only",
        "collections": [
            {"collection_id": "world_issues", "title": "世界观问题", "record_kinds": ["completeness_issue", "consistency_issue", "revision_requirement"]},
            {"collection_id": "chapter_issues", "title": "章节问题", "record_kinds": ["blocking_issue", "non_blocking_issue", "revision_requirement"]},
            {"collection_id": "volume_issues", "title": "卷级问题", "record_kinds": ["canon_drift_issue", "continuity_issue", "pacing_issue"]},
            {"collection_id": "final_issues", "title": "交付问题", "record_kinds": ["delivery_blocker", "open_issue"]},
        ],
    },
]


CONTRACT_FIELDS = {
    "user_goal": ["project_id", "source_user_goal", "delivery_requirements", "hard_constraints", "source_refs"],
    "project_brief": ["project_id", "project_title", "genre", "target_length", "style_requirements", "hard_constraints", "delivery_requirements", "source_user_goal", "open_questions", "downstream_baseline_memory_input", "artifact_refs", "summary"],
    "world_candidate": ["project_id", "candidate_id", "world_positioning", "protagonist_origin", "five_side_framework", "world_rules", "major_conflict_axes", "growth_space", "forbidden_boundaries", "artifact_refs", "summary"],
    "world_review": ["project_id", "review_id", "reviewed_candidate_id", "verdict", "completeness_issues", "consistency_issues", "support_assessment", "revision_requirements", "approved_world_spine", "next_step", "summary"],
    "memory_commit_world": ["project_id", "world_commit_id", "source_review_id", "source_candidate_id", "world_memory_ref", "approved_world_spine", "artifact_refs", "summary"],
    "baseline_memory_commit": ["project_id", "baseline_memory_id", "baseline_version", "baseline_world_spine", "baseline_outline_spine", "baseline_character_spine", "frozen_character_facts", "frozen_relationship_facts", "baseline_memory_refs", "mutable_memory_scope", "readable_by_next_stages", "artifact_refs", "summary"],
    "volume_plan_commit": ["project_id", "canon_id", "volume_count", "volume_target_words", "chapters_per_volume", "volume_order", "volume_targets", "current_volume_index", "current_volume_focus", "artifact_refs", "summary"],
    "volume_review_input": ["project_id", "volume_index", "volume_label", "baseline_memory_ref", "volume_plan_ref", "chapter_commit_refs", "chapter_summary_refs", "volume_issue_ledger_ref", "memory_pack_id"],
    "volume_review": ["project_id", "review_id", "volume_index", "continuity_score", "drift_score", "commercial_score", "verdict", "quality_score", "continuity_issues", "canon_drift_issues", "pacing_issues", "revision_requirements", "volume_commit_instructions", "next_step", "summary"],
    "volume_commit": ["project_id", "volume_commit_id", "volume_index", "source_review_id", "chapter_file_refs", "chapter_summary_refs", "volume_summary_ref", "volume_facts_delta", "volume_memory_ref", "completed_volume_refs", "summary"],
    "volume_postmortem": ["project_id", "postmortem_id", "volume_index", "source_volume_commit_id", "actual_story_facts", "confirmed_character_facts", "confirmed_relationship_facts", "effective_additions", "weak_points", "mutable_memory_update_candidates", "next_volume_suggestions", "baseline_memory_ref", "summary"],
    "world_outline_extension_proposal": ["project_id", "proposal_id", "volume_index", "source_postmortem_id", "world_memory_delta", "outline_memory_delta", "character_weight_delta", "strategy_adjustments", "forbidden_frozen_fact_changes", "next_volume_focus", "evidence_refs", "baseline_memory_ref", "summary"],
    "extension_review": ["project_id", "review_id", "volume_index", "reviewed_proposal_id", "verdict", "boundary_violations", "rejected_frozen_fact_changes", "accepted_world_memory_delta", "accepted_outline_memory_delta", "accepted_character_weight_delta", "accepted_strategy_adjustments", "revision_requirements", "mutable_memory_write_instructions", "next_step", "summary"],
    "extension_commit": ["project_id", "mutable_memory_update_id", "volume_index", "source_review_id", "world_memory_ref", "outline_memory_ref", "character_weight_memory_ref", "strategy_memory_ref", "next_volume_readable_refs", "baseline_memory_ref", "summary"],
    "next_volume_decision": ["project_id", "current_volume_index", "next_volume_index", "current_words", "target_words", "volume_target_words", "decision", "next_step", "next_volume_input_refs", "completed_volume_refs", "blocking_issues", "summary"],
    "chapter_outline_input": ["project_id", "volume_index", "volume_label", "chapter_index", "batch_index", "batch_start_index", "batch_end_index", "batch_chapter_numbers", "batch_chapter_list", "chapters_per_round", "chapter_target", "batch_target_words", "baseline_memory_ref", "mutable_memory_refs", "volume_plan_ref", "previous_chapter_summary_refs", "previous_chapter_review_ref", "memory_pack_id"],
    "chapter_outline": ["project_id", "outline_id", "chapter_outline_ref", "volume_index", "batch_index", "batch_start_index", "batch_end_index", "batch_chapter_numbers", "batch_chapter_list", "chapters_per_round", "batch_story_objective", "chapter_outline_items", "batch_rhythm_plan", "chapter_focus_map", "hook_plan", "continuity_watchpoints", "artifact_refs", "summary"],
    "chapter_draft_input": ["project_id", "volume_index", "volume_label", "chapter_index", "batch_index", "batch_start_index", "batch_end_index", "batch_chapter_numbers", "batch_chapter_list", "chapters_per_round", "chapter_target", "batch_target_words", "baseline_memory_ref", "mutable_memory_refs", "volume_plan_ref", "chapter_outline_ref", "previous_chapter_summary_refs", "previous_chapter_review_ref", "memory_pack_id"],
    "chapter_draft": ["project_id", "candidate_id", "chapter_outline_ref", "chapter_draft_ref", "chapter_index", "batch_index", "batch_start_index", "batch_end_index", "chapters_per_round", "chapter_title", "chapter_goal", "scene_outline", "ending_hook", "candidate_kind", "input_refs", "candidate_body", "chapter_file_refs", "continuity_bridge_refs", "coverage_statement", "self_risk_notes", "public_summary", "not_canon", "artifact_refs", "summary"],
    "chapter_review_input": ["project_id", "volume_index", "volume_label", "chapter_index", "batch_index", "batch_start_index", "batch_end_index", "batch_chapter_numbers", "batch_chapter_list", "chapters_per_round", "chapter_outline_ref", "chapter_draft_ref", "chapter_input_ref", "previous_chapter_summary_refs", "baseline_memory_ref", "mutable_memory_refs", "volume_plan_ref", "chapter_issue_ledger_ref", "memory_pack_id"],
    "chapter_review": ["project_id", "review_id", "reviewed_candidate_id", "chapter_outline_ref", "chapter_draft_ref", "chapter_index", "batch_index", "batch_start_index", "batch_end_index", "chapters_per_round", "continuity_score", "drift_score", "commercial_score", "verdict", "quality_score", "blocking_issues", "non_blocking_issues", "revision_requirements", "allowed_to_commit", "chapter_write_instructions", "repair_request", "next_step", "summary"],
    "chapter_commit": ["project_id", "chapter_commit_id", "chapter_outline_ref", "chapter_draft_ref", "chapter_index", "batch_index", "batch_start_index", "batch_end_index", "batch_chapter_numbers", "batch_chapter_list", "chapters_per_round", "chapter_title", "source_review_id", "source_candidate_id", "chapter_file_ref", "chapter_file_refs", "chapter_summary_ref", "chapter_summary_refs", "chapter_facts_delta", "completed_chapter_refs", "summary"],
    "chapter_progress_decision": ["project_id", "current_chapter_index", "batch_index", "batch_start_index", "batch_end_index", "batch_chapter_numbers", "batch_chapter_list", "total_chapter_count", "completed_chapter_refs", "next_chapter_index", "decision", "next_step", "blocking_issues", "summary"],
    "repair_request": ["project_id", "repair_kind", "trigger_stage_id", "trigger_node_id", "return_stage_id", "return_node_id", "blocking_issue_ids", "repair_scope", "forbidden_scope", "reviewer_reason"],
    "final_assemble_input": ["project_id", "project_brief_ref", "baseline_memory_ref", "mutable_memory_refs", "volume_commit_manifest", "chapter_file_refs", "chapter_summary_refs", "delivery_requirements", "open_issue_refs", "memory_pack_id"],
    "final_manuscript": ["project_id", "delivery_manifest_id", "chapter_order", "chapter_file_refs", "chapter_commit_refs", "chapter_summary_refs", "assembled_output_refs", "formatting_plan", "integrity_check_report", "known_non_blocking_limits", "delivery_blockers", "summary"],
    "final_review_input": ["project_id", "final_manuscript_ref", "delivery_manifest_id", "baseline_memory_ref", "mutable_memory_refs", "volume_commit_manifest_ref", "open_issue_refs", "memory_pack_id"],
    "final_review": ["project_id", "review_id", "reviewed_candidate_id", "verdict", "quality_score", "blocking_issues", "non_blocking_issues", "revision_requirements", "delivery_permission", "repair_request", "next_step", "summary"],
    "delivery_package": ["project_id", "delivery_package_id", "final_review_id", "delivery_manifest_id", "assembled_output_refs", "archive_refs", "task_completion_state", "summary"],
    "human_review_input": ["project_id", "trigger_node_id", "trigger_contract_id", "blocking_issues", "required_human_decision", "safe_state_refs", "summary"],
    "human_review_packet": ["project_id", "handoff_id", "trigger_node_id", "decision_options", "safe_state_refs", "summary"],
    "failure_input": ["project_id", "trigger_node_id", "failure_reason", "safe_state_refs", "last_successful_commit_refs", "summary"],
    "failure_report": ["project_id", "failure_report_id", "failure_reason", "safe_state_refs", "last_successful_commit_refs", "task_state", "summary"],
    "memory_read_request": ["request_id", "project_id", "consumer_node_id", "stage_id", "round_index", "allowed_memory_keys", "required_artifact_refs", "forbidden_memory_keys", "max_payload_policy", "on_missing_required"],
    "memory_pack": ["memory_pack_id", "request_id", "consumer_node_id", "included_refs", "included_summaries", "included_commits", "included_issue_ledger", "missing_required_refs", "blocked", "block_reason"],
    "memory_write_request": ["request_id", "project_id", "producer_node_id", "write_kind", "artifact_kind", "artifact_ref", "artifact_summary", "source_refs", "not_canon", "expected_version"],
    "memory_write_receipt": ["receipt_id", "request_id", "write_status", "written_indexes", "artifact_ref", "new_version", "blocked", "block_reason"],
}


CUSTOM_PROJECTION_PROMPTS = {
    "projection.writing.simple_novel.world_designer": """你是一名世界观设定写手。

你的职责是为《洪荒时代》写出第一版可审的世界观候选正文。
你不是章节作者，不负责直接写剧情章节；你也不是大纲规划者，不负责把整本书拆成分卷。

你要解决的是：
1. 这个世界到底是什么样。
2. 主角从哪里来，他为什么能卷入更大的洪荒格局。
3. 勾芒、河伯、四岳、祝融、玄女这五方背景力量，分别如何影响天地、人间和主线。
4. 这个世界能支撑百万字连载的长期冲突、升级空间和资源体系是什么。

你必须写清楚：
1. 世界的底层气质和时代状态。
2. 主角起点所在的大泽，与外部洪荒的关系。
3. 五方背景角色的方位、权柄、象征、彼此张力与对主线的潜在牵引。
4. 修行、权力、资源、禁忌、灾异、遗迹或秩序的基础规则。
5. 这个世界适合商业连载推进的主干冲突与成长空间。

你不允许：
1. 直接写分卷表。
2. 把大纲当成世界观正文凑数。
3. 只列名词解释，不建立可写作的关系网络。
4. 推翻用户给定的五方背景角色定义。

输出必须包含：
【世界观总定位】
【主角起点与卷入方式】
【五方背景框架】
【天地规则与力量结构】
【长期冲突与成长空间】
【不可越界边界】
【供下游审核的世界观摘要】""",
    "projection.writing.simple_novel.baseline_memory_steward": """你是一名长篇小说基准库管理员。

你的职责是把项目最稳定、最不该被后续卷推翻的内容，整理成一份基准库。
你不负责创作世界观正文，不负责写卷计划，不负责写补充提案；你只负责把“项目启动包 + 已审核世界观”固定成后面所有人读取的骨架。

你需要回答五件事：
1. 这本书到底写什么，商业方向是什么。
2. 主角是谁，起点和核心驱动力是什么。
3. 世界的底层规则是什么，哪些内容属于基准库。
4. 哪些人物设定、人物关系和已成立事实必须冻结，后续只能延展不能改写。
5. 后续卷还能往哪里演进，哪些内容应该交给可改动库。

你必须从项目启动包和已审核世界观里提炼出：
1. 项目名称、题材方向、商业网文化方向。
2. 主角基本身份和核心标签。
3. 五方背景角色的方位、象征、功能和对主线的意义。
4. 世界底层规则的最小稳定骨架。
5. 全书主线的最小稳定方向。
6. 已确立人物设定、已确立人物关系、已提交历史事实的冻结边界。
7. 明确可交给可改动库的范围：卷节奏、人物权重、支线顺序、势力曝光强度、卷后补充点。

你必须像一个严谨的基准库管理员，而不是世界观写手或编辑。
你只做收口，不做自由重写，不得跳过已审核世界观另起一套设定。
一旦某个人物设定、人物关系或关键事实已经被确认为项目 canon，你必须把它写进冻结边界；后续节点不得把它重新定义成“可调整建议”。
尤其要注意：现有人物的人设、身份、立场、核心动机、关键关系，只要已经在基准阶段确认，就属于基准库冻结内容，不允许写进可改动库。
你只能沉淀最终定稿骨架，不能把世界观候选稿的旧版本、审核过程措辞、驳回意见、过程性分歧直接抄进基准库正文。
如果上游给了 approved_world_spine、world_commit 或明确的已通过世界主干，你必须以它为唯一世界观定稿来源；项目 brief 只用于补齐项目目标和读取边界，不得反向覆盖已通过世界主干。
你的输出必须像“定稿后的 canon 库”，不是“世界观演化记录”。

输出必须直接给下游节点使用，格式要清晰、可读、可检索，必须包含：
【基准库摘要】
【世界观基准】
【大纲基准】
【人物基准】
【冻结人物与关系事实】
【可改动库范围】
【读取边界】
【下游读取说明】

额外硬要求：
1. 【世界观基准】只能保留单一最终版本，不得出现“v1/v2/候选稿/上一稿/另一版说法”。
2. 基准库中凡是“待确认”的内容，必须明确标记为“未冻结”，不能混写成已成立事实。
3. 任何只属于卷级执行策略、章节节奏分配、后续可调人物权重的内容，都不得写进基准库冻结区。""",
    "projection.writing.simple_novel.chapter_outliner": """你是一名章节细纲规划者。

你的职责是把当前卷计划拆成当前批次可以直接开写的章纲。
你不是写正文的人，也不是只列关键词的提纲机器；你要给正文作者一个能稳定落地的批次执行蓝图。

你每次规划前必须明确：
1. 当前批次允许写哪些章。
2. 这一批在本卷里承担什么推进任务。
3. 这一批要推进哪些人物关系、冲突、爽点和钩子。
4. 哪些已冻结设定、人物事实和关系事实绝对不能越界。

你输出的细纲必须让正文作者可以直接写：
1. 每章标题或明确章目标。
2. 每章核心场景、冲突动作、信息释放点和章末钩子。
3. 批次内部的节奏安排：哪章起势、哪章升级、哪章兑现、哪章留悬念。
4. 需要重点防止的连续性风险和设定漂移点。

你不允许：
1. 只写一句话梗概就交稿。
2. 把整卷计划原样复制成批次细纲。
3. 用“自行发挥”“按正文展开”代替场景推进。
4. 擅自改写基准库和已冻结人物/关系事实。

输出必须包含：
【批次目标】
【逐章细纲】
【批次节奏设计】
【人物与冲突推进安排】
【章末钩子规划】
【连续性警戒点】
【供正文写作读取的批次摘要】""",
    "projection.writing.simple_novel.world_reviewer": """你是一名世界观审核员。

你的职责是审核当前世界观候选是否完整、一致、可支撑后续写作。
你不负责替创作者扩写设定，也不负责直接给出分卷计划。

你必须检查：
1. 世界观是否守住用户硬设定。
2. 五方背景框架是否清晰、互相有关系，而不是孤立名词。
3. 主角起点是否能自然进入主线。
4. 世界规则、势力张力、成长空间是否足以支撑百万字商业连载。
5. 是否存在明显冲突、空洞、不可写或后续无法承接的问题。

你的裁决只能表达真实状态：
pass
pass_with_notes
revise
fail_closed

输出必须包含：
【裁决】
【硬设定一致性检查】
【五方框架检查】
【主角起点可写性检查】
【长期连载支撑度检查】
【需要修订的问题】
【允许进入基准库的世界主干；仅 pass 时填写】""",
    "projection.writing.simple_novel.volume_planner": """你是一名长篇小说分卷规划者。

你的职责是把基准库拆成真正能连续生产的卷级作战图。
你要像一个懂商业连载节奏的总策划，不是把故事写死，而是把每卷的任务、钩子、爆点和边界排清楚。

你需要给下游节点提供：
1. 每卷目标字数、章节范围、阶段任务。
2. 每卷核心冲突和主角成长阶段。
3. 每卷要重点放大的势力、人物关系和爽点兑现顺序。
4. 每卷卷首钩子、卷中升级、卷尾爆点。
5. 每卷结束后可被卷后复盘吸收的观察点。
6. 下一卷开始时必须继承的输入清单。

你必须特别注意：
1. 规划要稳定，但不要写成无法调整的死表。
2. 每卷都要像一个独立连载单元，读完有收束，下一卷有新钩子。
3. 计划必须能被卷级审核和卷后复盘使用，不能只是人看着顺眼。
4. 你只能安排“尚未冻结”的人物权重与关系推进节奏；已经进入基准库冻结事实的人物身份与人物关系不能被改写，只能顺着既有事实继续展开。

输出必须包含：
【全书分卷总览】
【每卷目标】
【每卷章节范围】
【每卷冲突与爽点设计】
【卷后扩展观察点】
【下一步章节循环输入】""",
    "projection.writing.simple_novel.volume_reviewer": """你是一名长篇小说卷级总审核员。

你的职责是把一整卷当成一个连续阅读单元来审。
你不是单章挑错员，你要判断这一卷能不能作为“可交付的一卷”成立。

你必须检查：
1. 本卷是否遵守基准库。
2. 本卷是否遵守分卷计划，偏差是否有合理收益。
3. 章节之间是否连续，是否存在跳戏、换主角、换体系、设定漂移。
4. 主线推进、人物弧线、冲突升级、爽点兑现、卷尾钩子是否成立。
5. 这一卷能不能被写入卷级记忆，并作为下一卷的稳定输入。

你的裁决只应该表达真实状态：
pass：这一卷可以提交。
pass_with_notes：可以提交，但要留下卷后扩展建议。
revise_volume：卷内问题还能通过重写解决。
repair_canon：已经碰到主干设定，需要先修主干。
fail_closed：无法安全继续。

输出必须包含：
【裁决】
【整卷连续性检查】
【基准记忆一致性检查】
【人物与冲突弧线检查】
【商业阅读体验检查】
【需要卷内修订的问题】
【卷级写入指令；仅 pass 时填写】""",
    "projection.writing.simple_novel.volume_postmortem": """你是一名长篇小说卷后复盘员。

你的职责是把“这一卷真正写出来并被卷审承认的内容”提炼成复盘结论。
你不改写主干，只识别已经成立的新事实、新趋势和新风险。

你要输出：
1. 本卷真实发生了什么。
2. 哪些人物设定和人物关系已经在正文中被明确坐实，应该进入冻结事实。
3. 哪些人物线、冲突线、势力线、钩子比原计划更有效。
4. 哪些地方写弱了、写偏了、写慢了、写空了。
5. 哪些新增内容值得进入可改动库。
6. 下一卷最该吸收什么经验。

禁止把“打算写”“本来想写”“应该有”当成事实。
禁止改写基准库。
禁止直接输出主干重写稿。

输出必须包含：
【本卷事实复盘】
【应冻结的人物与关系事实】
【有效新增内容】
【弱点与风险】
【可进入可改动库的候选】
【下一卷建议】
【基准库引用】""",
    "projection.writing.simple_novel.world_outline_extension_proposer": """你是一名世界观与大纲补充提案员。

你的职责是根据卷后复盘，把“已经被事实证明有效”的内容写成可改动库更新提案。
你不是重写者，你只能扩展，不能推翻。

你必须输出：
1. 世界观补充：新增地理、势力、规则表现、仪式、传说、资源或限制。
2. 大纲补充：下一卷该吸收的冲突重心、人物权重、支线顺序和钩子布局。
3. 人物权重补充：哪些人物关系或对手线应获得更多篇幅。
4. 证据引用：每条补充必须能回指到本卷事实。
5. 冻结事实保护：明确哪些已确立人物设定、人物关系和已提交事实不能被本提案改写。

禁止修改主角身份。
禁止修改五方背景角色的根本定义。
禁止改写已经成立的人物身份、人物关系和已提交剧情事实。
禁止把已冻结人物设定、已冻结人物关系重写成“阶段性建议”或“下一卷可调整项”。
禁止把未发生的计划伪装成事实补充。
禁止删除既有 canon。

输出必须包含：
【世界观可改动库更新提案】
【大纲可改动库更新提案】
【人物权重可改动库更新提案】
【不得改写的冻结事实】
【证据引用】
【基准库引用】
【下一卷读取建议】""",
    "projection.writing.simple_novel.extension_reviewer": """你是一名可改动库更新审核员。

你的职责是审核可改动库更新提案有没有越过边界。
你不负责润色，只负责裁决：哪些能写入可改动库，哪些必须退回。

你必须检查：
1. 每条补充是否有本卷事实证据。
2. 是否越过了基准库边界，改写了主角、五方框架、世界底层规则、已确立人物设定、已确立人物关系或已提交历史。
3. 是否会破坏下一卷连续性。
4. 是否适合写入下一卷可读的可改动库。

裁决只能表达边界状态：
pass
pass_with_notes
revise_extension
reject

输出必须包含：
【裁决】
【证据充分性检查】
【基准库边界检查】
【允许写入的世界观更新】
【允许写入的大纲更新】
【允许写入的人物权重更新】
【拒绝写入的冻结事实改写】
【修订要求；非 pass 时填写】
【可改动库写入指令；仅 pass 时填写】""",
    "projection.writing.simple_novel.next_volume_router": """你是一名长篇小说分卷推进审核员。

你的职责是确认“这一卷已经收口，下一卷是否可以继续”。
你不能写正文，不能改 canon，不能跳过卷审和补充审。

你必须读取：
1. 当前卷 commit。
2. 当前卷可改动库更新 commit。
3. 全书累计字数。
4. 全书目标字数。
5. 下一卷计划和可改动库引用。

决策只能是：
next_volume
final_assemble
fail_closed

输出必须包含：
【决策】
【当前卷序号】
【下一卷序号；如适用】
【累计字数检查】
【下一卷输入引用】
【阻塞问题】
【下一步节点】""",
    "projection.writing.simple_novel.project_brief": """你是一名项目启动包整理者。

你的职责是把用户交代的目标整理成一份可执行的写作任务启动包。
你不是写正文的人，也不是设定扩写者，你的工作是把项目要求、风格方向、硬限制和下游需求整理清楚。

你必须输出：
1. 项目要写什么。
2. 用户明确给了什么硬设定。
3. 这个项目要追求什么风格和阅读感。
4. 下游最先需要哪些输入。
5. 有哪些问题必须在后续节点里继续确认。

你要像一个认真给后面所有人铺路的总入口，而不是像一个备忘录。

输出必须包含：
【项目目标】
【硬设定】
【风格方向】
【下游输入】
【待确认问题】
【启动摘要】""",
    "projection.writing.simple_novel.chapter_writer": """你是一名章节作者。

你的职责是写出当前批次的完整章节正文，并保证每一章都能被审核、被记忆、被下游继续使用。
你不是在写散文，也不是在写提纲；你要交付的是可以连载的正文。

你每次写作前必须明确：
1. 本批次允许写哪些章。
2. 本批次继承了哪些基准库内容、冻结人物/关系事实、卷计划和可改动库内容。
3. 本批次细纲已经给你安排了哪些章目标、场景推进、冲突节奏和章末钩子。
4. 本批次要推进什么冲突、什么人物关系、什么爽点和什么钩子。

你交付时必须让下游看得懂：
1. 每章发生了什么。
2. 每章是否落实了细纲要求，哪里做了合理展开。
3. 本批次结束时留下了什么悬念或推进。
4. 这一批哪些内容可以直接进入记忆库。

你必须牢记：
1. 已确立人物设定不能反向改写。
2. 已确立人物关系只能发展、恶化、缓和或揭露，不允许无因重置。
3. 如果要引入新关系变化，必须在正文里给出行为、对话、事件或代价证据。

输出必须包含：
【章节正文候选】
【承接说明】
【本章目标完成说明】
【人物与冲突推进】
【商业钩子与爽点兑现】
【后续伏笔或待承接事项】
【自检风险】
【公开摘要】""",
    "projection.writing.simple_novel.chapter_reviewer": """你是一名章节审核员。

你的职责是审核当前批次章节是否能进入记忆库。
你不负责重写正文，只负责判断这一批是不是合格、哪里不合格、需要怎么改。

你必须检查：
1. 本批是否守住基准记忆、冻结人物/关系事实和卷级计划。
2. 章节之间是否连续，是否有章号越界、角色乱跳、体系漂移。
3. 本批是否真的写出了剧情，而不是说明文字。
4. 本批是否能在商业连载上成立。
5. 这一批能不能进入记忆管家写入。

你给出的修改建议必须能被写作者直接执行，不要空泛，不要抽象。

输出必须包含：
【裁决】
【逐章连续性检查】
【基准记忆一致性检查】
【人物设定与关系冻结检查】
【人物与冲突检查】
【商业阅读检查】
【需要修订的问题】
【写入记忆指令；仅 pass 时填写】""",
    "projection.writing.simple_novel.chapter_progress_router": """你是一名章节推进审核员。

你的职责是判断这一批章写完之后，下一步是继续下一批、进入卷审，还是必须先修复问题。
你不是审核正文质量本身，而是判断推进方向。

你必须读取：
1. 本批章节提交结果。
2. 本批审核结果。
3. 当前卷累计字数。
4. 当前卷还剩多少目标字数。
5. 是否已经触发卷审条件。

你必须输出一个清晰的推进决定，方便系统接力。

输出必须包含：
【决策】
【当前章批次】
【下一章批次或卷审节点】
【累计字数检查】
【阻塞问题】
【下一步节点】""",
    "projection.writing.simple_novel.memory_steward": """你是一名写作资产记忆管家。

你的职责是把通过审核的内容写入正确的库。
你不负责写正文，不负责改写设定，不负责擅自优化内容。

系统只有两个写作记忆库：
1. 基准库：由基准库初始化节点写入；其它节点只有读取权限。
2. 可改动库：由卷后审核通过的更新写入，用来承载下一卷需要吸收的世界观、大纲、人物权重和连续性变化。

章节批次和卷级结果不是第三个设定库，它们是运行产物索引，用来支持审核、统计和交付。

你每次写入前必须确认：
1. 这次写入的是基准库、可改动库，还是运行产物索引。
2. 当前节点是否拥有这个目标的写权限。
3. 下游节点需要读到什么。
4. 如果内容属于已确立人物设定、已确立人物关系或已提交事实，只能进入冻结事实边界，不能伪装成可改动建议。

输出必须包含：
【写入目标库或索引】
【写入目标】
【写入结果】
【可供下游读取的引用】
【未写入原因】
【记忆状态摘要】""",
    "projection.writing.simple_novel.final_assembler": """你是一名交付包整编者。

你的职责是把所有已经通过审核和写入的卷级成果，整理成最终可交付包。
你不是重新编故事的人，你只负责汇总、排序、校验和打包。

你必须读取：
1. 基准记忆库。
2. 已提交的卷级记忆。
3. 已提交的增补记忆。
4. 已完成的章节文件和章节摘要。
5. 交付要求和未解决问题。

你必须输出一个让下游能直接交付和归档的包，不能缺引用，不能丢卷，不能乱序。

输出必须包含：
【交付清单】
【章节顺序】
【已整编内容】
【完整性检查】
【未解决问题】
【交付摘要】""",
    "projection.writing.simple_novel.final_reviewer": """你是一名最终交付审核员。

你的职责是确认整本书的交付包是否可以结束任务。
你检查的不是某一章，而是整本书的完整性、连续性和交付一致性。

你必须检查：
1. 基准库、可改动库、卷级结果和交付包是否一致。
2. 章节顺序是否正确，卷与卷之间是否断裂。
3. 是否还存在阻塞问题或明显缺失。
4. 最终交付是否真的可以对外使用。

你的裁决必须直接告诉系统能不能收尾。

输出必须包含：
【裁决】
【完整性交付检查】
【记忆一致性检查】
【阻塞问题】
【交付许可】
【下一步节点】""",
}


def prompt_for(pid, prompts):
    prompt = CUSTOM_PROJECTION_PROMPTS.get(pid) or prompts.get(pid, "")
    if not prompt:
        return ""
    batch_appendix = {
        "projection.writing.simple_novel.chapter_writer": (
            "批次执行硬要求：\n"
            f"- 你每轮必须连续完成 {CHAPTERS_PER_ROUND} 章正文，章节范围以运行时给出的 batch_start_index 和 batch_end_index 为准。\n"
            "- 你必须先确认本批允许输出的章号清单，只能写入清单中的章节；禁止提前写下一批任何章节编号、标题、正文或摘要。\n"
            "- 你必须先读取当前批次细纲，并逐章落实细纲中的场景目标、冲突推进和章末钩子；只有在不违背细纲目标的前提下，才能做正文层面的自然展开。\n"
            f"- 每章目标约 {CHAPTER_TARGET_WORDS} 字，本批目标约 {CHAPTERS_PER_ROUND * CHAPTER_TARGET_WORDS} 字；每章必须有独立标题、独立正文、独立结尾钩子。\n"
            "- 不允许只写一章后用提纲、摘要、占位、待续冒充其余章节。\n"
            "- 批次内十章要形成连续剧情推进：每章有小冲突、小爽点和章末推进，但批次结尾只能停在本批最后一章，不得把下一批剧情写进当前批次。\n"
            f"- 输出必须清楚标注每一章的章号，便于审核员和记忆管家拆分登记；第{CHAPTERS_PER_ROUND + 1}章及以后绝对不能出现。\n\n"
            "批次输出结构硬要求：\n"
            "- 【章节正文候选】下只能放本批十章的章号、标题和正文，不得在每章正文后插入承接说明、目标说明、自检或摘要。\n"
            "- 十章正文全部写完之后，才能输出【承接说明】【本章目标完成说明】【人物与冲突推进】【商业钩子与爽点兑现】【后续伏笔或待承接事项】【自检风险】【公开摘要】。\n"
            "- 【本章目标完成说明】必须按章列出“目标 / 完成状态 / 正文证据”。完成状态只能是：完成、部分完成、未完成、待后续。\n"
            "- 任一“完成”项必须能在正文中找到明确证据；没有证据就写“部分完成/未完成/待后续”，不得打勾。\n\n"
            "返修轮硬要求：\n"
            "- 如果输入中存在 previous_chapter_review_ref、chapter_revision_requirements、revision_required 或上一轮审核文本，你必须把它当作本轮最高优先级写作约束。\n"
            "- 如果返修意见指出细纲层面的问题，你必须先修正当前批次的推进结构，再改正文表现，不能只润色句子。\n"
            "- 你必须逐条修复上一轮审核中的【阻塞问题】和【下一轮修改要求】，不能只换措辞、不能重复上一版结构、不能用笼统说明代替正文改写。\n"
            "- 如果上一轮指出节奏过快，你必须在本批正文中增加实质性障碍、失败、代价、战斗、智斗或选择，禁止继续写“抵达、对话、获得、前往下一站”的流水账。\n"
            "- 如果上一轮指出用户硬设定角色缺席，你必须让相关角色以可感知人格、对话、行动或神性投影参与剧情；不能只把他们当令牌、地名或背景名词。\n"
            "- 如果上一轮指出主角成长不足，你必须写出本批内清晰的能力、关系、资源、认知或代价变化，并让变化影响后续行动。\n"
            "- 如果上一轮指出字数不足，你必须扩写正文场景本身，而不是增加说明、摘要、检查清单或重复句。\n"
            "- 你的【本章目标完成说明】、【人物与冲突推进】、【商业钩子与爽点兑现】、【自检风险】必须只陈述正文里真实发生或明确铺垫的内容；任何没有在正文中出现的事件、人物引入、成果或因果，禁止写进自检部分。\n"
            "- 【公开摘要】也只能复述正文已经明确发生的内容；禁止把计划、返修说明、未来补写事项或正文未出现的线索写成既成事实。\n"
            "- 如果上游目标只在本章推进了一部分，你必须如实写成“部分完成/推进到/尚待后文”，不得把未完成目标写成已完成。\n"
            "- 如果你写“已增加、已补充、已解释、已出现、掉落、揭示、完成交锋、获得线索”等结论，正文里必须先有可定位的场景、对话或行动；否则删除这条结论。\n"
            "- 如果某个章节目标写着“引入某人”或“揭示某个秘密”，正文里必须真的出现对应人物、对话、行动或证据；不得只在目标说明里声明完成。\n"
            "- 如果需要分散信息密度，你必须把秘密、背景和关系线拆到多个章节逐步揭示，不得在单章里一次性倾倒所有关键设定。\n"
            "- 返修稿必须是完整替换稿：重新输出本批全部章节，不得只输出修改说明或局部补丁。"
        ),
        "projection.writing.simple_novel.chapter_outliner": (
            "批次细纲硬要求：\n"
            f"- 你每轮必须为当前批次连续规划 {CHAPTERS_PER_ROUND} 章，章节范围以运行时给出的 batch_start_index 和 batch_end_index 为准。\n"
            "- 逐章细纲必须写清：本章目标、主场景、关键冲突动作、信息释放点、人物推进点、章末钩子。\n"
            "- 你必须让十章形成连续推进链，不允许十章都是并列事件说明。\n"
            "- 细纲必须为正文服务，不能只写世界观解释或人物设定说明。\n"
            "- 如果输入中存在 previous_chapter_review_ref 或 chapter_revision_requirements，你必须把返修要求吸收到本轮细纲安排中，明确哪些章承担修复任务。\n"
            "- 如果上一轮问题是节奏、结构、人物缺席、爽点落空，你必须在逐章细纲里给出具体修复落点，不能只在摘要里声明会处理。"
        ),
        "projection.writing.simple_novel.chapter_reviewer": (
            "章节轻量审核硬要求：\n"
            f"- 你审核的是当前卷内一个 {CHAPTERS_PER_ROUND} 章批次；重点检查连续性、设定偏移、章号越界和是否具备继续写作的最低质量。\n"
            "- 你不是卷级总审，不要把整卷结构问题全部压到单批次返工里；可记录到 volume_issue_ledger 等待卷级总审处理。\n"
            "- 只有出现缺章、严重短缺、主角/体系/世界观明显漂移、批次外章节、无法承接上一批时，才给 revise。\n"
            "- 局部节奏弱、个别爽点不足、人物权重需要调整等问题，优先 pass_with_notes 或记录为卷级问题，不要反复打回。\n"
            "- 审核结论必须包含 volume_index、batch_start_index、batch_end_index、逐章连续性检查、偏移检查和是否允许批次写入记忆。"
        ),
        "projection.writing.simple_novel.chapter_progress_router": (
            "批次推进硬要求：\n"
            f"- 当前批次通过 commit 后，优先推进到本卷下一批，也就是 next_chapter_index = batch_end_index + 1，默认每轮推进 {CHAPTERS_PER_ROUND} 章。\n"
            f"- 当前卷累计达到约 {VOLUME_TARGET_WORDS} 字或本卷章节范围完成后，必须进入 volume_review，而不是直接进入最终交付。\n"
            "- 只有确认当前批次所有章节均已通过轻审并写入 commit，才允许 decision=continue_volume 或 decision=volume_review。\n"
            "- 如果发现卷内连续性阻塞，输出 blocker_found 并交给卷级总审或结构修复。"
        ),
        "projection.writing.simple_novel.memory_steward": (
            "章节批次记忆写入硬要求：\n"
            f"- 当处理章节批次 commit 时，必须把 {CHAPTERS_PER_ROUND} 章分别登记为可追踪章节引用，不得只登记一个笼统批次。\n"
            "- 每章都要有 chapter_index、chapter_file_ref、chapter_summary_ref、关键事实增量和与上一章的连续性摘要。\n"
            "- 批次 manifest 可以共享同一产物文件，但记忆索引必须能按单章查到，防止后续读取污染或遗漏。"
        ),
    }.get(pid, "")
    if pid in {
        "projection.writing.simple_novel.chapter_reviewer",
        "projection.writing.simple_novel.volume_reviewer",
        "projection.writing.simple_novel.extension_reviewer",
        "projection.writing.simple_novel.chapter_progress_router",
        "projection.writing.simple_novel.next_volume_router",
        "projection.writing.simple_novel.final_reviewer",
    } and not HUMAN_REVIEW_ENABLED:
        no_human_appendix = (
            "自动版运行约束：\n"
            "- 本图为简易自动运行版，禁止输出 human_review_required 作为正常裁决。\n"
            "- 当候选不足但仍可通过补写或修订继续推进时，优先使用 revise 或对应 repair_*。\n"
            "- 只有确实无法继续且必须停机保留失败证据时，才允许 fail_closed。\n"
            "- 不得把本应由 revise/repair_* 处理的问题转成人工接管。"
        )
        prompt = (prompt.rstrip() + "\n\n" + no_human_appendix).strip()
    if batch_appendix:
        prompt = prompt.rstrip() + "\n\n" + batch_appendix
    return prompt


def projection_cards():
    prompts = parse_prompts()
    titles = {
        "project_brief": "项目启动包整理者",
        "world_designer": "世界观设定写手",
        "world_reviewer": "世界观审核员",
        "baseline_memory_steward": "基准记忆库管理员",
        "volume_planner": "分卷规划者",
        "chapter_outliner": "章节细纲规划者",
        "volume_reviewer": "卷级总审核员",
        "volume_postmortem": "卷后复盘员",
        "world_outline_extension_proposer": "可改动库更新提案员",
        "extension_reviewer": "可改动库更新审核员",
        "next_volume_router": "分卷推进审核员",
        "chapter_writer": "章节作者",
        "chapter_reviewer": "章节审核员",
        "chapter_progress_router": "章节推进审核员",
        "memory_steward": "写作资产记忆管家",
        "final_assembler": "交付包整编者",
        "final_reviewer": "最终交付审核员",
    }
    projection_ids = sorted({node[3] for node in NODE_DEFS if node[3].startswith("projection.writing.simple_novel")})
    cards = []
    for pid in projection_ids:
        role = pid.split(".")[-1]
        prompt = prompt_for(pid, prompts)
        if not prompt:
            continue
        cards.append({
            "projection_id": pid,
            "title": "写作组 / " + titles.get(role, role),
            "soul_id": "hebo",
            "soul_name": "河伯",
            "projection_kind": "task_graph_node",
            "owner_system": "task_system",
            "source_task_graph_refs": [GRAPH_ID],
            "projection_nodes": [{"node_id": pid + ".role", "title": "角色提示", "content": prompt, "node_type": "role_prompt", "weight": 1}],
            "identity_anchor": prompt.split("\n")[0],
            "role_type": role,
            "task_mode": role,
            "agent_profile_id": "agent:" + role,
            "posture_tags": ["writing_simple_novel", "bounded_role", "contract_first"],
            "expression_density": "structured_high_detail",
            "attention_focus": ["memory_pack", "artifact_refs", "contract_output", "bounded_context"],
            "risk_notes": ["不得越权写 canon；不得读取未授权上下文；不得把全文长篇塞进模型上下文。"],
            "projection_prompt": prompt,
            "usage_summary": "用于写作组简易长篇小说任务图节点。",
            "skill_views": [],
            "tool_views": [],
            "memory_policy_summary": "记忆由 TaskGraph 的 memory_read、memory_write_candidate、memory_commit 边控制；节点只读取边授权的仓库集合。",
            "output_contract_summary": "按节点 output_contract_id 输出。",
            "workflow_instruction_template": "先确认本轮时序位置，再读取输入包和授权记忆，随后完成职责，最后按输出契约交付。",
            "context_usage_rules": [
                "ArtifactContextPacket 是本轮指定产物，不得猜测其它版本。",
                "RevisionPacket 必须同时携带原稿和审核意见，返修必须基于原稿进行。",
                "MemorySnapshot 中的只读基准不得被改写，可改动库只能按提交边生效。",
            ],
            "output_behavior_rules": [
                "候选输出必须标明 not_canon 或等待审核状态。",
                "审核输出必须包含 verdict、问题清单和下一步要求。",
                "记忆写入必须通过 memory_write_candidate 与 memory_commit 边形成闭环。",
            ],
            "runtime_preview": {"identity_anchor": "", "projection_prompt": "", "usage_summary": "", "skill_views": [], "tool_views": [], "memory_policy_summary": "", "output_contract_summary": ""},
            "runtime_only_payload": False,
            "static_projection_card": True,
            "created_at": NOW,
            "updated_at": NOW,
            "is_primary": False,
            "is_system_default": False,
        })
    return cards


def loop_derived_fields():
    return [
        {"key": "volume_index_padded", "op": "format", "template": "{volume_index:03d}"},
        {"key": "volume_label", "op": "format", "template": "第{volume_index}卷"},
        {"key": "chapter_index_padded", "op": "format", "template": "{chapter_index:03d}"},
        {"key": "chapter_label", "op": "format", "template": "第{chapter_index}章"},
        {"key": "chapter_file_prefix", "op": "format", "template": "chapter_{chapter_index:03d}"},
        {"key": "batch_start_index", "op": "copy", "from_key": "chapter_index"},
        {"key": "batch_end_index", "op": "add", "from_key": "chapter_index", "value": CHAPTERS_PER_ROUND - 1},
        {"key": "batch_index", "op": "ordinal_group", "from_key": "chapter_index", "size": CHAPTERS_PER_ROUND},
        {"key": "batch_index_padded", "op": "format", "template": "{batch_index:03d}"},
        {"key": "batch_start_index_padded", "op": "format", "template": "{batch_start_index:03d}"},
        {"key": "batch_end_index_padded", "op": "format", "template": "{batch_end_index:03d}"},
        {"key": "batch_chapter_range", "op": "format", "template": "{batch_start_index:03d}-{batch_end_index:03d}"},
        {"key": "batch_label", "op": "format", "template": "第{batch_start_index}章至第{batch_end_index}章"},
        {"key": "batch_chapter_numbers", "op": "range", "start_key": "batch_start_index", "end_key": "batch_end_index"},
        {"key": "batch_chapter_list", "op": "join", "from_key": "batch_chapter_numbers", "prefix": "第", "suffix": "章", "separator": "、"},
        {"key": "batch_target_words", "op": "multiply", "from_key": "chapter_target_words", "value": CHAPTERS_PER_ROUND},
        {"key": "runtime_loop_summary", "op": "format", "template": "当前卷：{volume_label}；当前批次：{batch_label}；本批允许范围：{batch_chapter_list}；全书累计约 {current_words}/{target_words} 字；本卷累计约 {volume_current_words}/{volume_target_words} 字。"},
    ]


def initial_runtime_loop_inputs():
    inputs = {
        "volume_index": 1,
        "volume_current_words": 0,
        "volume_target_words": VOLUME_TARGET_WORDS,
        "chapters_per_volume": CHAPTERS_PER_VOLUME,
        "chapter_index": 1,
        "chapters_per_round": CHAPTERS_PER_ROUND,
        "chapter_batch_size": CHAPTERS_PER_ROUND,
        "metric_label": "words",
        "target_metric_total": TARGET_WORDS,
        "target_words": TARGET_WORDS,
        "current_words": 0,
        "chapter_target_words": CHAPTER_TARGET_WORDS,
    }
    return inputs


def node_responsibility_metadata(node_id, title, role):
    identities = {
        "project_brief": "你是一名项目启动包整理者。",
        "world_design": "你是一名世界观设定写手。",
        "world_review": "你是一名世界观审核员。",
        "memory_commit_world": "你是一名世界观提交管家。",
        "baseline_memory_seed": "你是一名基准记忆库管理员。",
        "volume_plan": "你是一名分卷规划者。",
        "chapter_outline": "你是一名章节细纲规划者。",
        "chapter_draft": "你是一名章节作者。",
        "chapter_review": "你是一名章节审核员。",
        "memory_commit_chapter": "你是一名章节提交管家。",
        "chapter_progress_router": "你是一名章节推进审核员。",
        "volume_review": "你是一名卷级总审核员。",
        "volume_commit": "你是一名卷级提交管家。",
        "volume_postmortem": "你是一名卷后复盘员。",
        "world_outline_extension_proposal": "你是一名可改动库更新提案员。",
        "extension_review": "你是一名可改动库边界审核员。",
        "extension_commit": "你是一名可改动库提交管家。",
        "next_volume_router": "你是一名分卷推进审核员。",
        "final_assemble": "你是一名交付包整编者。",
        "final_review": "你是一名最终交付审核员。",
        "memory_finalize": "你是一名任务收尾归档管家。",
        "human_review_handoff": "你是一名人工接管协调员。",
        "fail_closed": "你是一名失败关闭记录员。",
    }
    scopes = {
        "creator": "你只负责按输入包和授权记忆完成当前创作或规划产物。",
        "reviewer": "你只负责审核当前送审对象，指出问题并给出明确裁决。",
        "memory_steward": "你只负责按审核结果和提交边写入索引、回执和记忆提交记录。",
        "router": "你只负责根据提交状态、目标进度和阻塞问题决定下一步路由。",
        "final_assembler": "你只负责依据提交清单和交付要求整编交付包。",
        "human": "你只负责整理需要人工决策的阻塞信息。",
    }
    exclusions = {
        "creator": "你不负责审核自己产出的候选，也不负责把候选写成已提交事实。",
        "reviewer": "你不负责替创作者扩写正文，也不负责越过审核结果写入记忆库。",
        "memory_steward": "你不负责创作新内容，也不负责修改未被审核通过的候选。",
        "router": "你不负责补写正文或审核正文质量，只做推进裁决。",
        "final_assembler": "你不负责重写全书正文，也不负责创建未经提交的新设定。",
        "human": "你不负责自动替用户做不可恢复决策。",
    }
    done_by_role = {
        "creator": "完成标准：输出必须可被审核节点直接审阅，并明确引用输入包和未解决风险。",
        "reviewer": "完成标准：必须给出裁决、问题清单、返修要求和是否允许进入下一阶段。",
        "memory_steward": "完成标准：必须生成可追踪的提交记录、来源引用和 receipt 可见性说明。",
        "router": "完成标准：必须给出继续、转入下一阶段、最终交付或失败关闭的明确路由。",
        "final_assembler": "完成标准：必须生成交付清单、组装引用、完整性检查和残留限制。",
        "human": "完成标准：必须列出阻塞原因、安全状态和需要人工选择的事项。",
    }
    return {
        "role_identity": identities.get(node_id, f"你是一名{title}。"),
        "responsibility_scope": scopes.get(role, "你只负责完成当前节点明确交付给你的职责。"),
        "responsibility_exclusions": exclusions.get(role, "你不负责扩展未经确认的任务范围。"),
        "definition_of_done": done_by_role.get(role, "完成标准：输出必须符合节点契约，并能被下游节点接收。"),
        "workflow_instruction_template": "先确认本轮时序位置，再读取输入包和授权记忆，随后完成职责，最后按输出契约交付。",
        "context_usage_rules": [
            "只使用输入包、MemorySnapshot、ArtifactContextPacket、RevisionPacket 中明确授权的信息。",
            "遇到缺失的必需输入时必须报告阻塞，不得自行猜测。",
            "区分候选、审核结果、提交事实和只读基准。",
        ],
        "output_behavior_rules": [
            "按 output_contract_id 输出结构化结果。",
            "长文本只交付 artifact ref，不把全文塞进普通交接。",
            "候选写入不自动污染记忆库，必须等待 memory_commit 边提交。",
        ],
    }


def graph_node(node):
    node_id, title, agent, projection, input_contract, output_contract, phase, seq, path, role = node
    node_type = {
        "reviewer": "review_gate",
        "memory_steward": "memory_commit",
        "router": "agent_role",
        "final_assembler": "agent_role",
        "human": "manual_gate",
    }.get(role, "agent_role")
    if node_id == "memory_finalize":
        node_type = "memory_finalize"
    if node_id == "fail_closed":
        node_type = "memory_finalize"
    operation = ""
    if node_type in {"memory_commit", "memory_resource"}:
        operation = "commit"
    elif node_type == "memory_finalize":
        operation = "finalize"
    loop_policy = {"loop_kind": "bounded_metric_iteration", "loop_variable": "batch_start_index", "iteration_size": CHAPTERS_PER_ROUND, "exit_decision": "target_words_reached"} if node_id in {"chapter_outline", "chapter_draft", "chapter_review", "memory_commit_chapter", "chapter_progress_router"} else {}
    loop_scope_id = "loop.chapter_batch" if node_id in {"chapter_outline", "chapter_draft", "chapter_review", "memory_commit_chapter", "chapter_progress_router"} else ""
    loop_route_policy = {}
    if node_id == "chapter_progress_router":
        loop_route_policy = {
            "mode": "metric_target",
            "loop_scope_id": "loop.chapter_batch",
            "continue_stage_id": "chapter_outline",
            "exit_stage_id": "volume_review",
            "metric_key": "chapter_words",
            "diagnostic_metric_key": "chapter_words",
            "fallback_increment_key": "batch_target_words",
            "default_increment": CHAPTER_TARGET_WORDS * CHAPTERS_PER_ROUND,
            "current_key": "current_words",
            "target_key": "target_words",
            "last_metric_key": "last_batch_words",
            "secondary_counters": [{"current_key": "volume_current_words", "target_key": "volume_target_words"}],
            "counter_updates": [{"key": "chapter_index", "mode": "increment", "step": CHAPTERS_PER_ROUND}],
            "derived_fields": loop_derived_fields(),
        }
    if node_id == "next_volume_router":
        loop_route_policy = {
            "mode": "metric_target",
            "continue_stage_id": "chapter_outline",
            "exit_stage_id": "final_assemble",
            "metric_key": "volume_router_metric",
            "default_increment": 0,
            "current_key": "current_words",
            "target_key": "target_words",
            "counter_updates": [
                {"key": "volume_index", "mode": "increment", "step": 1},
                {"key": "volume_current_words", "mode": "reset", "value": 0},
                {"key": "chapter_index", "mode": "increment", "step": CHAPTERS_PER_ROUND},
            ],
            "derived_fields": loop_derived_fields(),
        }
    title_template = ""
    if node_id in {"chapter_outline", "chapter_draft", "chapter_review", "memory_commit_chapter", "chapter_progress_router"}:
        title_template = "{batch_label}批次" + title
    if node_id in {"volume_review", "volume_commit", "volume_postmortem", "world_outline_extension_proposal", "extension_review", "extension_commit", "next_volume_router"}:
        title_template = "{volume_label}" + title
    node_stream_policy = stream_policy(node_id, role)
    review_revision_targets = {
        "world_review": "world_design",
        "chapter_review": "chapter_draft",
        "volume_review": "chapter_draft",
        "extension_review": "world_outline_extension_proposal",
        "final_review": "final_assemble",
    }
    review_gate_policy = {}
    if role == "reviewer":
        review_gate_policy = {
            "allowed_verdicts": ["pass", "pass_with_notes", "revise", "blocker_found", "revise_volume", "repair_canon", "revise_extension", "reject", "fail_closed"],
            "revision_stage_id": review_revision_targets.get(node_id, ""),
        }
    return {
        "node_id": node_id,
        "node_type": node_type,
        "title": title,
        "task_id": "task.writing.simple_novel." + node_id,
        "agent_id": agent,
        "agent_selection_policy": "explicit_agent",
        "agent_group_id": GROUP_ID if role != "human" else "",
        "work_posture": role,
        "node_contract_id": output_contract,
        "input_contract_id": input_contract,
        "output_contract_id": output_contract,
        "runtime_lane": "full_interactive" if role == "human" else "coordination_task",
        "context_visibility_policy": {
            "shared_context_policy": "explicit_refs_only",
            "memory_sharing_policy": "memory_pack_only",
            "conversation_memory": "hidden" if role in {"creator", "reviewer", "router", "final_assembler"} else "restricted",
            "suppress_conversation_memory": role in {"creator", "reviewer", "router", "final_assembler"},
        },
        "projection_id": projection,
        "projection_overlay_id": projection,
        "failure_policy": {"default": "fail_closed", "on_missing_required_memory": "fail_closed"},
        "human_gate_policy": {"enabled": False, "mode": "auto_continue", "trigger_verdict": "human_review_required"},
        "memory_read_policy": memory_read_policy(role, node_id=node_id),
        "memory_writeback_policy": memory_write_policy(role, node_id=node_id),
        "dynamic_memory_read_policy": {},
        "phase_id": phase,
        "sequence_index": seq,
        "timeline_group_id": phase,
        "main_chain": role != "human",
        "blocks_phase_exit": role != "human",
        "loop_policy": loop_policy,
        "loop_kind": loop_policy.get("loop_kind", ""),
        "loop_scope_id": loop_scope_id,
        "title_template": title_template,
        "loop_route_policy": loop_route_policy,
        "review_gate_policy": review_gate_policy,
        "artifact_context_policy": artifact_context_policy(node_id),
        "revision_context_policy": revision_context_policy(node_id),
        "quality_retry_policy": quality_retry_policy(node_id),
        "progress_commit_policy": progress_commit_policy(node_id),
        "artifact_policy": artifact_policy(path),
        "stream_policy": node_stream_policy,
        "artifact_target": path,
        "output_path": path,
        "execution_mode": "sync",
        "dispatch_group": phase,
        "wait_policy": "wait_all_upstream_completed",
        "join_policy": "all_success",
        "background_policy": {},
        "notification_policy": {},
        "resource_lifecycle_policy": {},
        "metadata": {
            "managed_by": MANAGED,
            "role": role,
            **node_responsibility_metadata(node_id, title, role),
            "operation": operation,
            "memory_closed_loop": True,
            "requires_memory_pack": True,
            "design_doc": DESIGN_DOC,
            "chapters_per_round": CHAPTERS_PER_ROUND if loop_policy else 0,
            "streaming_enabled": bool(node_stream_policy.get("enabled")),
        },
    }


def memory_repository_nodes():
    nodes = []
    for item in MEMORY_REPOSITORY_DEFS:
        collections = list(item.get("collections") or [])
        collection_ids = [str(collection.get("collection_id") or "").strip() for collection in collections if str(collection.get("collection_id") or "").strip()]
        nodes.append({
            "node_id": item["node_id"],
            "node_type": item["node_type"],
            "title": item["title"],
            "task_id": "",
            "agent_id": "",
            "agent_selection_policy": "resource",
            "agent_group_id": "",
            "work_posture": "resource",
            "node_contract_id": "",
            "input_contract_id": "",
            "output_contract_id": "",
            "runtime_lane": "resource",
            "context_visibility_policy": {"shared_context_policy": "edge_authorized_only", "conversation_memory": "not_applicable"},
            "projection_id": "",
            "projection_overlay_id": "",
            "failure_policy": {"default": "fail_closed"},
            "human_gate_policy": {"enabled": False},
            "memory_read_policy": {},
            "memory_writeback_policy": {},
            "dynamic_memory_read_policy": {},
            "phase_id": item["phase_id"],
            "sequence_index": item["sequence_index"],
            "timeline_group_id": item["phase_id"],
            "main_chain": False,
            "blocks_phase_exit": False,
            "loop_policy": {},
            "loop_kind": "",
            "loop_scope_id": "",
            "title_template": "",
            "loop_route_policy": {},
            "review_gate_policy": {},
            "artifact_context_policy": {},
            "revision_context_policy": {},
            "quality_retry_policy": {},
            "progress_commit_policy": {},
            "artifact_policy": {},
            "stream_policy": stream_policy(item["node_id"], "resource"),
            "artifact_target": "",
            "output_path": "",
            "execution_mode": "sync",
            "dispatch_group": item["phase_id"],
            "wait_policy": "wait_all_upstream_completed",
            "join_policy": "all_success",
            "background_policy": {},
            "notification_policy": {},
            "resource_lifecycle_policy": {
                "versioning": "append_version",
                "mutable": item.get("mutability") != "commit_only",
                "readable_by": ["*"],
                "write_owner_node_ids": [],
                "write_authority": "edge.memory_write_candidate_or_commit",
            },
            "metadata": {
                "managed_by": MANAGED,
                "role": "resource",
                "operation": "store",
                "repository_id": item["repository_id"],
                "repository_kind": item["repository_kind"],
                "mutability": item["mutability"],
                "collections": collection_ids,
                "memory_repository": {
                    "repository_id": item["repository_id"],
                    "title": item["title"],
                    "schema_id": "schema.writing.simple_novel.memory_record",
                    "repository_kind": item["repository_kind"],
                    "mutability": item["mutability"],
                    "collections": collections,
                },
                "design_doc": DESIGN_DOC,
            },
        })
    return nodes


HANDOFF_DETAILS = {
    ("project_brief", "world_design"): {
        "handoff_summary": "把项目目标、硬设定和风格方向交给世界观设定写手。",
        "required_refs": ["project_brief_ref", "source_user_goal"],
        "memory_expectation": "世界观写手只读取启动包，不读取基准库和可改动库。",
    },
    ("world_design", "world_review"): {
        "handoff_summary": "把世界观候选交给世界观审核员裁决。",
        "required_refs": ["world_candidate_ref", "project_brief_ref"],
        "memory_expectation": "审核员只看世界观候选和启动包，不越权做分卷规划。",
    },
    ("world_review", "memory_commit_world"): {
        "handoff_summary": "把通过审核的世界观结果交给记忆管家登记世界观引用。",
        "required_refs": ["world_review_ref", "world_candidate_ref"],
        "memory_expectation": "记忆管家只登记世界观产物索引，不直接写基准库。",
    },
    ("world_review", "world_design"): {
        "handoff_summary": "把审核意见连同被审核世界观原稿退回给世界观写手修订，必须基于原稿改稿，不要脱离原稿另起一份。",
        "required_refs": ["world_review_ref", "world_candidate_ref", "project_brief_ref"],
        "memory_expectation": "世界观写手同时读取审核意见、被审核原稿和启动包，按审核问题逐条修订原稿。",
    },
    ("memory_commit_world", "baseline_memory_seed"): {
        "handoff_summary": "把已审核世界观交给基准库管理员固化主干。",
        "required_refs": ["world_commit_ref", "project_brief_ref"],
        "memory_expectation": "基准库管理员根据启动包和已审核世界观生成 baseline_memory。",
    },
    ("baseline_memory_seed", "volume_plan"): {
        "handoff_summary": "把基准库交给分卷规划者，作为全书规划边界。",
        "required_refs": ["baseline_memory_ref", "project_brief_ref"],
        "memory_expectation": "读取基准库，不写基准库。",
    },
    ("volume_plan", "chapter_outline"): {
        "handoff_summary": "把当前卷目标、章节范围、冲突和钩子交给细纲规划者，先生成本批可直接开写的章纲。",
        "required_refs": ["volume_plan_ref", "baseline_memory_ref", "mutable_memory_refs"],
        "memory_expectation": "细纲规划者读取基准库、可改动库、卷计划和上一批摘要，只整理当前批次蓝图。",
    },
    ("chapter_outline", "chapter_draft"): {
        "handoff_summary": "把当前批次细纲交给正文写手，要求严格按批次蓝图落正文。",
        "required_refs": ["chapter_outline_ref", "volume_plan_ref", "baseline_memory_ref", "mutable_memory_refs"],
        "memory_expectation": "写手读取基准库、可改动库、卷计划、当前批次细纲和上一批摘要。禁止跳过细纲直接凭分卷计划硬写正文。",
    },
    ("chapter_draft", "chapter_review"): {
        "handoff_summary": "把当前批次正文候选交给章节审核。",
        "required_refs": ["chapter_outline_ref", "chapter_draft_ref", "baseline_memory_ref", "mutable_memory_refs", "previous_chapter_summary_refs"],
        "memory_expectation": "审核员同时读取当前批次细纲、正文候选和必要连续性引用，检查正文是否真正完成了本批章纲。",
    },
    ("chapter_review", "memory_commit_chapter"): {
        "handoff_summary": "把通过审核的批次交给记忆管家登记章节索引。",
        "required_refs": ["chapter_review_ref", "chapter_outline_ref", "chapter_draft_ref", "chapter_file_refs"],
        "memory_expectation": "记忆管家同时知道当前批次章纲、正文和审核结果，只写章节产物索引与冻结章纲，不写两个设定库。",
    },
    ("chapter_review", "chapter_draft"): {
        "handoff_summary": "把章节审核意见连同当前批次原稿退回给写手修订，必须在原稿基础上改，不要整批重写漂移。",
        "required_refs": ["chapter_review_ref", "chapter_outline_ref", "chapter_draft_ref", "baseline_memory_ref", "mutable_memory_refs", "previous_chapter_summary_refs"],
        "memory_expectation": "写手读取审核意见、当前批次章纲、当前批次原稿、两个记忆库和上一批摘要，优先修正连续性、设定偏移和钩子问题。",
    },
    ("memory_commit_chapter", "chapter_progress_router"): {
        "handoff_summary": "把章节提交结果交给路由器判断继续写还是进入卷审。",
        "required_refs": ["chapter_commit_ref", "completed_chapter_refs"],
        "memory_expectation": "路由器读取累计字数、当前卷目标和章节提交清单。",
    },
    ("chapter_progress_router", "chapter_outline"): {
        "handoff_summary": "继续本卷下一批，先整理下一批细纲，再进入正文写作。",
        "required_refs": ["next_chapter_index", "batch_start_index", "batch_end_index", "baseline_memory_ref", "mutable_memory_refs"],
        "memory_expectation": "下一批细纲规划者继承上一批摘要和问题台账，先产出当前批次蓝图。",
    },
    ("chapter_progress_router", "volume_review"): {
        "handoff_summary": "本卷达到卷审条件，交给卷级总审。",
        "required_refs": ["chapter_commit_refs", "chapter_summary_refs", "volume_plan_ref"],
        "memory_expectation": "卷审读取整卷章节摘要、章节引用、基准库和可改动库。",
    },
    ("volume_review", "volume_commit"): {
        "handoff_summary": "把通过卷审的一卷提交为卷级事实。",
        "required_refs": ["volume_review_ref", "chapter_commit_refs", "chapter_summary_refs"],
        "memory_expectation": "卷级写入不写两个设定库，只写卷级产物索引。",
    },
    ("volume_review", "chapter_draft"): {
        "handoff_summary": "把卷级总审意见和本卷已写章节引用退回给写手，按卷级连续性和偏移问题进行定向返修。",
        "required_refs": ["volume_review_ref", "chapter_commit_refs", "chapter_summary_refs", "volume_plan_ref", "baseline_memory_ref", "mutable_memory_refs"],
        "memory_expectation": "返修写手读取卷审意见、整卷章节引用、卷计划和两个记忆库，按卷级问题修正，不推翻已成立主线。",
    },
    ("volume_commit", "volume_postmortem"): {
        "handoff_summary": "把已提交卷交给复盘员提取真实有效变化。",
        "required_refs": ["volume_commit_ref", "chapter_summary_refs", "volume_review_ref"],
        "memory_expectation": "复盘员读取事实，不把计划当事实。",
    },
    ("volume_postmortem", "world_outline_extension_proposal"): {
        "handoff_summary": "把卷后复盘交给可改动库更新提案员。",
        "required_refs": ["volume_postmortem_ref", "baseline_memory_ref", "mutable_memory_refs"],
        "memory_expectation": "提案只针对可改动库，不写基准库。",
    },
    ("world_outline_extension_proposal", "extension_review"): {
        "handoff_summary": "把可改动库更新提案交给边界审核。",
        "required_refs": ["mutable_memory_proposal_ref", "evidence_refs", "baseline_memory_ref"],
        "memory_expectation": "审核员检查提案是否越过基准库边界。",
    },
    ("extension_review", "extension_commit"): {
        "handoff_summary": "把通过审核的更新写入可改动库。",
        "required_refs": ["extension_review_ref", "mutable_memory_write_instructions"],
        "memory_expectation": "只写 mutable_memory，不写 baseline_memory。",
    },
    ("extension_review", "world_outline_extension_proposal"): {
        "handoff_summary": "把边界审核意见和原更新提案退回给提案员修订，必须在原提案上调整，不得越过基准库边界。",
        "required_refs": ["extension_review_ref", "mutable_memory_proposal_ref", "baseline_memory_ref", "evidence_refs"],
        "memory_expectation": "提案员读取审核意见、原提案、基准库边界和证据引用，只修订 mutable_memory 更新方案。",
    },
    ("extension_commit", "next_volume_router"): {
        "handoff_summary": "把可改动库更新结果交给续卷路由。",
        "required_refs": ["mutable_memory_ref", "volume_commit_ref", "current_words", "target_words"],
        "memory_expectation": "路由器决定下一卷或最终交付。",
    },
    ("next_volume_router", "chapter_outline"): {
        "handoff_summary": "进入下一卷第一批细纲规划，先把下一卷首批章纲整理清楚。",
        "required_refs": ["next_volume_index", "baseline_memory_ref", "mutable_memory_ref", "volume_plan_ref"],
        "memory_expectation": "新卷细纲规划者读取两个库和下一卷计划，先产出首批可执行章纲。",
    },
    ("next_volume_router", "final_assemble"): {
        "handoff_summary": "累计目标达成，进入最终交付整编。",
        "required_refs": ["volume_commit_manifest", "chapter_file_refs", "chapter_summary_refs"],
        "memory_expectation": "整编员读取全书产物索引和两个库，不重写正文。",
    },
    ("final_assemble", "final_review"): {
        "handoff_summary": "把交付包交给最终审核。",
        "required_refs": ["final_manuscript_ref", "delivery_manifest_id"],
        "memory_expectation": "最终审核检查完整性、一致性和交付许可。",
    },
    ("final_review", "memory_finalize"): {
        "handoff_summary": "把最终审核通过结果交给归档。",
        "required_refs": ["final_review_ref", "delivery_manifest_id", "assembled_output_refs"],
        "memory_expectation": "归档节点只写交付状态和任务状态。",
    },
    ("final_review", "final_assemble"): {
        "handoff_summary": "把最终审核意见连同当前整编稿退回给整编员修订，必须基于现有交付稿补正问题，不得脱离当前交付结果重组新稿。",
        "required_refs": ["final_review_ref", "final_manuscript_ref", "delivery_manifest_id", "assembled_output_refs"],
        "memory_expectation": "整编员读取最终审核意见和当前整编结果，定向修补交付缺陷，不重写正文。",
    },
}


def edge(edge_id, source, target, contract_id, edge_type="structured_handoff", metadata=None):
    detail = dict(HANDOFF_DETAILS.get((source, target)) or {})
    merged_metadata = {**detail, **dict(metadata or {})}
    working_memory_handoff_policy = dict(merged_metadata.get("working_memory_handoff_policy") or {})
    handoff_summary = str(merged_metadata.get("handoff_summary") or "").strip()
    memory_expectation = str(merged_metadata.get("memory_expectation") or "").strip()
    model_visible_label = str(merged_metadata.get("model_visible_label") or merged_metadata.get("input_alias") or "上游交接包").strip()
    usage_instruction = str(merged_metadata.get("usage_instruction") or "").strip()
    if not usage_instruction:
        usage_parts = [item for item in [handoff_summary, memory_expectation] if item]
        usage_instruction = " ".join(usage_parts) or "你必须只使用这条交接边提供的结构化引用，不得从其它版本或未授权上下文猜测。"
    merged_metadata = {
        **merged_metadata,
        "packet_kind": "RevisionPacket" if edge_type == "revision_request" else "HandoffPacket",
        "input_alias": model_visible_label,
        "model_visible_label": model_visible_label,
        "usage_instruction": usage_instruction,
        "must_use": True,
        "may_ignore": False,
        "forbidden_use": str(merged_metadata.get("forbidden_use") or "不得把交接包中未通过审核的候选内容当作已提交事实。"),
        "on_missing": str(merged_metadata.get("on_missing") or "block"),
        "expand_strategy": str(merged_metadata.get("expand_strategy") or "refs_and_summary"),
    }
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_type": edge_type,
        "a2a_message_type": "message/send",
        "payload_contract_id": contract_id,
        "context_filter_policy": {"mode": "explicit_refs_only", "raw_dialogue_handoff": "forbidden"},
        "artifact_ref_policy": {
            "required_for_long_outputs": True,
            "prefer_refs_over_text": True,
            "context_mode": "refs_and_summary",
            "target_input_key": model_visible_label,
            "usage_instruction": usage_instruction,
        },
        "working_memory_handoff_policy": working_memory_handoff_policy,
        "ack_policy": "explicit_ack",
        "timeout_policy": "fail_closed",
        "wait_policy": "",
        "ack_required": True,
        "failure_propagation_policy": "fail_downstream",
        "result_delivery_policy": "contract_payload_and_refs",
        "failure_policy": {"on_missing_payload": "fail_closed"},
        "metadata": merged_metadata,
    }


def safe_edge_token(value):
    return re.sub(r"[^a-zA-Z0-9_.:-]+", "_", str(value or "")).strip("_") or "item"


def memory_edge(
    operation,
    task_node_id,
    repository_node_id,
    collection_id,
    *,
    label,
    usage_instruction,
    record_kinds=None,
    on_missing="block",
    receipt_policy=None,
):
    if operation not in {"read", "write_candidate", "commit"}:
        raise ValueError(f"unsupported memory edge operation: {operation}")
    edge_type = {
        "read": "memory_read",
        "write_candidate": "memory_write_candidate",
        "commit": "memory_commit",
    }[operation]
    contract_id = {
        "read": "contract.writing.simple_novel.memory_pack",
        "write_candidate": "contract.writing.simple_novel.memory_write_request",
        "commit": "contract.writing.simple_novel.memory_write_receipt",
    }[operation]
    source = repository_node_id if operation == "read" else task_node_id
    target = task_node_id if operation == "read" else repository_node_id
    repository_id = repository_node_id
    collection_id = str(collection_id or "default").strip() or "default"
    edge_id = ".".join([
        "edge",
        edge_type,
        safe_edge_token(task_node_id),
        safe_edge_token(repository_id),
        safe_edge_token(collection_id),
    ])
    selector = {
        "collection": collection_id,
        "status_filter": ["committed"] if operation == "read" else [],
        "record_kinds": list(record_kinds or []),
        "limit": 50 if operation == "read" else 0,
    }
    metadata = {
        "repository": repository_id,
        "repository_node_id": repository_node_id,
        "collection": collection_id,
        "selector": selector,
        "record_keys": list(record_kinds or []),
        "version_selector": "latest_committed_before_clock" if operation == "read" else "current_clock_receipt",
        "effective_from": "current_stage" if operation == "read" else "next_clock",
        "on_missing": on_missing,
        "model_visible_label": label if operation == "read" else "",
        "usage_instruction": usage_instruction,
        "receipt_policy": dict(receipt_policy or ({"required_status": "committed", "visible_after": "next_clock"} if operation == "commit" else {})),
        "read_contract": {"snapshot_contract_id": "contract.writing.simple_novel.memory_pack"} if operation == "read" else {},
        "write_contract": {"request_contract_id": "contract.writing.simple_novel.memory_write_request", "receipt_contract_id": "contract.writing.simple_novel.memory_write_receipt"} if operation != "read" else {},
        "memory_edge_type": operation,
    }
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_type": edge_type,
        "a2a_message_type": "task/memory_read" if operation == "read" else "task/memory_write",
        "payload_contract_id": contract_id,
        "context_filter_policy": {"mode": "edge_authorized_repository_selector", "raw_dialogue_handoff": "forbidden"},
        "artifact_ref_policy": {},
        "working_memory_handoff_policy": {},
        "ack_policy": "explicit_ack",
        "timeout_policy": "fail_closed",
        "wait_policy": "",
        "ack_required": operation != "read",
        "failure_propagation_policy": "fail_downstream",
        "result_delivery_policy": "refs_only" if operation == "read" else "notification_only",
        "failure_policy": {"on_missing_payload": "fail_closed"},
        "metadata": metadata,
    }


def memory_read_edges_for(node_id, items, *, usage_instruction):
    return [
        memory_edge(
            "read",
            node_id,
            repository,
            collection,
            label=label,
            usage_instruction=usage_instruction,
            record_kinds=record_kinds,
        )
        for repository, collection, label, record_kinds in items
    ]


def build_edges():
    main = [
        ("edge.project.world", "project_brief", "world_design", "contract.writing.simple_novel.project_brief"),
        ("edge.world.review", "world_design", "world_review", "contract.writing.simple_novel.world_candidate"),
        ("edge.world_review.commit", "world_review", "memory_commit_world", "contract.writing.simple_novel.world_review"),
        ("edge.world_commit.baseline_memory", "memory_commit_world", "baseline_memory_seed", "contract.writing.simple_novel.memory_commit_world"),
        ("edge.baseline_memory.volume_plan", "baseline_memory_seed", "volume_plan", "contract.writing.simple_novel.baseline_memory_commit"),
        ("edge.volume_plan.outline", "volume_plan", "chapter_outline", "contract.writing.simple_novel.volume_plan_commit"),
        ("edge.chapter_outline.draft", "chapter_outline", "chapter_draft", "contract.writing.simple_novel.chapter_outline"),
        ("edge.chapter_draft.review", "chapter_draft", "chapter_review", "contract.writing.simple_novel.chapter_draft"),
        ("edge.chapter_review.commit", "chapter_review", "memory_commit_chapter", "contract.writing.simple_novel.chapter_review"),
        ("edge.chapter_commit.router", "memory_commit_chapter", "chapter_progress_router", "contract.writing.simple_novel.chapter_commit"),
        ("edge.router.next_chapter", "chapter_progress_router", "chapter_outline", "contract.writing.simple_novel.chapter_progress_decision"),
        ("edge.router.volume_review", "chapter_progress_router", "volume_review", "contract.writing.simple_novel.chapter_progress_decision"),
        ("edge.volume_review.commit", "volume_review", "volume_commit", "contract.writing.simple_novel.volume_review"),
        ("edge.volume_commit.postmortem", "volume_commit", "volume_postmortem", "contract.writing.simple_novel.volume_commit"),
        ("edge.postmortem.extension_proposal", "volume_postmortem", "world_outline_extension_proposal", "contract.writing.simple_novel.volume_postmortem"),
        ("edge.extension_proposal.review", "world_outline_extension_proposal", "extension_review", "contract.writing.simple_novel.world_outline_extension_proposal"),
        ("edge.extension_review.commit", "extension_review", "extension_commit", "contract.writing.simple_novel.extension_review"),
        ("edge.extension_commit.router", "extension_commit", "next_volume_router", "contract.writing.simple_novel.extension_commit"),
        ("edge.next_volume_router.draft", "next_volume_router", "chapter_outline", "contract.writing.simple_novel.next_volume_decision"),
        ("edge.next_volume_router.final", "next_volume_router", "final_assemble", "contract.writing.simple_novel.next_volume_decision"),
        ("edge.final.review", "final_assemble", "final_review", "contract.writing.simple_novel.final_manuscript"),
        ("edge.final_review.finalize", "final_review", "memory_finalize", "contract.writing.simple_novel.final_review"),
    ]
    edges = [edge(*item) for item in main]
    for source, target, contract_name, revision_packet in [
        ("world_review", "world_design", "world_review", {
            "model_visible_label": "世界观返修包",
            "usage_instruction": "你必须读取本轮被审核的世界观原稿和审核意见，在原稿基础上逐条修订；不得脱离原稿另写一版世界观。",
            "original_artifact_key": "world_candidate_ref",
            "review_result_key": "world_review_ref",
            "carry": [
                {"source": "current_output", "target_input_key": "previous_review_ref"},
                {"source": "inherited_input", "target_input_key": "previous_candidate_ref", "source_key": "world_candidate_ref"},
                {"source": "inherited_input", "target_input_key": "project_brief_ref"},
            ],
        }),
        ("chapter_review", "chapter_draft", "chapter_review", {
            "model_visible_label": "章节返修包",
            "usage_instruction": "你必须读取当前批次原稿和章节审核意见，只修订本批允许章号内的正文；不得改写未进入本批的章节。",
            "original_artifact_key": "chapter_draft_ref",
            "review_result_key": "chapter_review_ref",
            "carry": [
                {"source": "current_output", "target_input_key": "previous_chapter_review_ref"},
                {"source": "inherited_input", "target_input_key": "chapter_outline_ref"},
                {"source": "inherited_input", "target_input_key": "chapter_draft_ref"},
                {"source": "inherited_input", "target_input_key": "chapter_input_ref"},
            ],
        }),
        ("volume_review", "chapter_draft", "volume_review", {
            "model_visible_label": "卷级返修包",
            "usage_instruction": "你必须读取卷级审核意见和本卷已提交章节引用，围绕连续性、设定偏移和节奏问题定向返修；不得推翻已通过部分。",
            "original_artifact_key": "chapter_commit_refs",
            "review_result_key": "volume_review_ref",
            "carry": [
                {"source": "current_output", "target_input_key": "volume_review_ref"},
                {"source": "inherited_input", "target_input_key": "chapter_commit_refs"},
                {"source": "inherited_input", "target_input_key": "chapter_summary_refs"},
            ],
        }),
        ("extension_review", "world_outline_extension_proposal", "extension_review", {
            "model_visible_label": "可改动库提案返修包",
            "usage_instruction": "你必须读取原更新提案和边界审核意见，只修订可改动库方案；不得改写基准人物事实、关系事实和世界规则。",
            "original_artifact_key": "mutable_memory_proposal_ref",
            "review_result_key": "extension_review_ref",
            "carry": [
                {"source": "current_output", "target_input_key": "extension_review_ref"},
                {"source": "inherited_input", "target_input_key": "mutable_memory_proposal_ref"},
                {"source": "inherited_input", "target_input_key": "baseline_memory_ref"},
            ],
        }),
        ("final_review", "final_assemble", "final_review", {
            "model_visible_label": "最终交付返修包",
            "usage_instruction": "你必须读取当前交付稿和最终审核意见，定向修补交付缺陷；不得脱离当前交付结果重新组装一份无关稿件。",
            "original_artifact_key": "final_manuscript_ref",
            "review_result_key": "final_review_ref",
            "carry": [
                {"source": "current_output", "target_input_key": "final_review_ref"},
                {"source": "inherited_input", "target_input_key": "final_manuscript_ref"},
                {"source": "inherited_input", "target_input_key": "delivery_manifest_id"},
            ],
        }),
    ]:
        edges.append(edge(f"edge.{source}.revise", source, target, "contract.writing.simple_novel." + contract_name, "revision_request", {"verdict": "revise", **revision_packet}))
    if HUMAN_REVIEW_ENABLED:
        for review_node in ["world_review", "chapter_review", "volume_review", "extension_review", "final_review", "chapter_progress_router", "next_volume_router"]:
            edges.append(edge(f"edge.{review_node}.human", review_node, "human_review_handoff", "contract.writing.simple_novel.human_review_input", "human_handoff", {"verdict": "human_review_required"}))
    for review_node in ["world_review", "chapter_review", "volume_review", "extension_review", "final_review", "chapter_progress_router", "next_volume_router"]:
        edges.append(edge(f"edge.{review_node}.fail", review_node, "fail_closed", "contract.writing.simple_novel.failure_input", "fail_closed", {"verdict": "fail_closed"}))
    baseline_reads = [
        ("memory.writing.baseline", "world", "基准世界观", ["baseline_world_spine", "world_rule"]),
        ("memory.writing.baseline", "characters", "人物事实", ["baseline_character_spine", "frozen_character_fact"]),
        ("memory.writing.baseline", "relationships", "关系事实", ["frozen_relationship_fact"]),
    ]
    mutable_reads = [
        ("memory.writing.mutable", "strategy", "策略调整", ["strategy_adjustment", "next_volume_focus"]),
        ("memory.writing.mutable", "outline_delta", "大纲补充", ["outline_memory_delta", "world_memory_delta"]),
        ("memory.writing.mutable", "character_weight", "人物权重", ["character_weight_delta", "exposure_schedule"]),
    ]
    chapter_plan_reads = [
        ("memory.writing.artifact_index", "volume_plans", "分卷计划索引", ["volume_plan", "volume_plan_slice", "current_volume_plan"]),
        ("memory.writing.artifact_index", "chapter_outlines", "章节细纲索引", ["chapter_outline", "frozen_chapter_outline"]),
    ]
    chapter_artifact_reads = [
        ("memory.writing.artifact_index", "chapter_commits", "章节提交索引", ["chapter_commit", "chapter_summary", "chapter_file_ref"]),
        ("memory.writing.issue_ledger", "chapter_issues", "章节问题账本", ["blocking_issue", "non_blocking_issue", "revision_requirement"]),
    ]
    volume_artifact_reads = [
        ("memory.writing.artifact_index", "volume_commits", "卷级提交索引", ["volume_commit", "volume_summary"]),
        ("memory.writing.issue_ledger", "volume_issues", "卷级问题账本", ["canon_drift_issue", "continuity_issue", "pacing_issue"]),
    ]
    for node_id, read_items, usage in [
        ("volume_plan", baseline_reads, "你必须把基准世界观、人物事实和关系事实当作分卷规划的硬约束；不得改写既有人物与关系。"),
        ("chapter_outline", baseline_reads + mutable_reads + chapter_plan_reads + chapter_artifact_reads, "你必须只整理当前卷、当前批次的章纲计划；已开写并提交的章纲只能作为历史依据读取，未开写部分才允许重排。"),
        ("chapter_draft", baseline_reads + mutable_reads + chapter_plan_reads + chapter_artifact_reads, "你必须按这些记忆快照限定本批章节，不得把缺失信息自行补写成既成事实。"),
        ("chapter_review", baseline_reads + mutable_reads + chapter_artifact_reads, "你只依据当前稿件、基准事实、可改动层和问题账本进行审核；发现冲突要指出并裁决。"),
        ("memory_commit_chapter", baseline_reads + mutable_reads, "你只根据已通过审核的章节和当前记忆边界登记索引，不得改写基准事实。"),
        ("chapter_progress_router", chapter_artifact_reads, "你只根据已提交章节、累计进度和未关闭问题判断继续写作或进入卷审。"),
        ("volume_review", baseline_reads + mutable_reads + chapter_artifact_reads + volume_artifact_reads, "你必须把整卷提交索引、章节摘要和记忆边界作为卷审依据，不得要求读取未授权全文。"),
        ("volume_commit", baseline_reads + mutable_reads + chapter_artifact_reads, "你只把通过卷审的一卷登记为产物索引和摘要，不得写入未审核事实。"),
        ("volume_postmortem", baseline_reads + mutable_reads + volume_artifact_reads, "你必须区分已经发生的卷级事实和未来计划，只复盘已提交内容。"),
        ("world_outline_extension_proposal", baseline_reads + mutable_reads + volume_artifact_reads, "你只能提出可改动层更新，不得改写基准人物事实、关系事实和已冻结世界规则。"),
        ("extension_review", baseline_reads + mutable_reads + volume_artifact_reads, "你必须审核更新提案是否越过基准边界；允许的更新只能进入可改动层。"),
        ("extension_commit", baseline_reads + mutable_reads, "你只提交审核通过的可改动层更新，并保留来源审核引用。"),
        ("next_volume_router", baseline_reads + mutable_reads + volume_artifact_reads, "你只根据累计进度、卷级提交和可改动层决定进入下一卷或最终交付。"),
        ("final_assemble", baseline_reads + mutable_reads + chapter_artifact_reads + volume_artifact_reads + [("memory.writing.artifact_index", "delivery", "交付清单", ["delivery_manifest", "final_manuscript"])], "你只使用提交索引、摘要、交付清单和授权引用整编交付包，不要把未授权全文放进上下文。"),
        ("final_review", baseline_reads + mutable_reads + volume_artifact_reads + [("memory.writing.artifact_index", "delivery", "交付清单", ["delivery_manifest", "final_manuscript"]), ("memory.writing.issue_ledger", "final_issues", "交付问题账本", ["delivery_blocker", "open_issue"])], "你必须审核最终交付包是否完整、一致、可交付；缺陷要形成明确返修要求。"),
        ("memory_finalize", [("memory.writing.artifact_index", "delivery", "交付清单", ["delivery_manifest", "delivery_package"]), ("memory.writing.issue_ledger", "final_issues", "交付问题账本", ["delivery_blocker", "open_issue"])], "你只归档最终交付状态、交付清单和未关闭问题，不再创建新设定。"),
    ]:
        edges.extend(memory_read_edges_for(node_id, read_items, usage_instruction=usage))
    for task_node, repository, collection, label, kinds, usage in [
        ("volume_plan", "memory.writing.artifact_index", "volume_plans", "分卷计划候选", ["volume_plan", "volume_plan_slice", "current_volume_plan"], "将分卷规划按卷写成可读取计划记录，后续写手默认只消费当前卷计划。"),
        ("world_design", "memory.writing.artifact_index", "candidates", "世界观候选", ["world_candidate"], "这只是待审候选稿，不得让后续节点把它当作已提交事实。"),
        ("world_review", "memory.writing.artifact_index", "reviews", "世界观审核记录", ["world_review"], "记录审核裁决、问题清单和是否允许进入提交阶段。"),
        ("world_review", "memory.writing.issue_ledger", "world_issues", "世界观问题", ["completeness_issue", "consistency_issue", "revision_requirement"], "记录世界观审核中发现的问题，只有通过后续提交边才对下游稳定可见。"),
        ("chapter_outline", "memory.writing.artifact_index", "chapter_outlines", "章节细纲候选", ["chapter_outline", "future_chapter_outline"], "这是当前批次章纲；未开写批次可后续整理，已提交章节对应章纲不得再改写。"),
        ("chapter_draft", "memory.writing.artifact_index", "candidates", "章节候选", ["chapter_draft"], "这是当前批次候选正文，只能交给审核和返修使用。"),
        ("chapter_review", "memory.writing.artifact_index", "reviews", "章节审核记录", ["chapter_review"], "记录章节审核裁决和返修要求。"),
        ("chapter_review", "memory.writing.issue_ledger", "chapter_issues", "章节问题", ["blocking_issue", "non_blocking_issue", "revision_requirement"], "记录当前批次问题，后续提交节点负责确认可见性。"),
        ("volume_review", "memory.writing.artifact_index", "reviews", "卷级审核记录", ["volume_review"], "记录卷级审核裁决、偏移和连续性问题。"),
        ("volume_review", "memory.writing.issue_ledger", "volume_issues", "卷级问题", ["canon_drift_issue", "continuity_issue", "pacing_issue"], "记录卷级问题，提交前不得作为已解决事实。"),
        ("world_outline_extension_proposal", "memory.writing.mutable", "strategy", "策略更新候选", ["strategy_adjustment", "next_volume_focus"], "这是可改动层更新提案，必须等待审核和提交。"),
        ("world_outline_extension_proposal", "memory.writing.mutable", "outline_delta", "大纲补充候选", ["outline_memory_delta", "world_memory_delta"], "这是可改动层大纲补充提案，不能覆盖基准库。"),
        ("world_outline_extension_proposal", "memory.writing.mutable", "character_weight", "人物权重候选", ["character_weight_delta", "exposure_schedule"], "这是人物权重和出场节奏调整提案，不能改写人物既有事实。"),
        ("extension_review", "memory.writing.artifact_index", "reviews", "可改动层审核记录", ["extension_review"], "记录边界审核裁决和允许写入的更新。"),
        ("extension_review", "memory.writing.issue_ledger", "volume_issues", "可改动层问题", ["boundary_violation", "rejected_frozen_fact_change"], "记录越界风险和被拒绝更新。"),
        ("final_assemble", "memory.writing.artifact_index", "delivery", "交付候选", ["delivery_manifest", "final_manuscript"], "这是待终审交付候选，不代表最终完成。"),
        ("final_review", "memory.writing.artifact_index", "reviews", "最终审核记录", ["final_review"], "记录最终交付审核裁决。"),
        ("final_review", "memory.writing.issue_ledger", "final_issues", "最终交付问题", ["delivery_blocker", "open_issue"], "记录最终审核发现的交付问题。"),
    ]:
        edges.append(memory_edge("write_candidate", task_node, repository, collection, label=label, usage_instruction=usage, record_kinds=kinds, on_missing="warn"))
    for task_node, repository, collection, label, kinds, usage in [
        ("memory_commit_world", "memory.writing.artifact_index", "candidates", "已审核世界观候选", ["world_candidate"], "提交已通过审核的世界观候选引用，供基准库初始化使用。"),
        ("memory_commit_world", "memory.writing.artifact_index", "reviews", "已审核世界观审核记录", ["world_review"], "提交世界观审核裁决和通过记录。"),
        ("memory_commit_world", "memory.writing.artifact_index", "world_commits", "世界观提交", ["world_commit", "approved_world_spine"], "提交已经通过审核的世界观主干引用。"),
        ("memory_commit_world", "memory.writing.issue_ledger", "world_issues", "世界观问题提交", ["completeness_issue", "consistency_issue", "revision_requirement"], "提交世界观问题状态，确保下游知道哪些问题已处理或仍阻塞。"),
        ("baseline_memory_seed", "memory.writing.baseline", "world", "基准世界观提交", ["baseline_world_spine", "world_rule"], "将审核通过的世界观固化为基准约束。"),
        ("baseline_memory_seed", "memory.writing.baseline", "outline", "基准大纲提交", ["baseline_outline_spine", "volume_plan"], "固化初始大纲主干，供分卷和章节阶段读取。"),
        ("baseline_memory_seed", "memory.writing.baseline", "characters", "基准人物提交", ["baseline_character_spine", "frozen_character_fact"], "固化人物事实，后续节点不得改写。"),
        ("baseline_memory_seed", "memory.writing.baseline", "relationships", "基准关系提交", ["frozen_relationship_fact"], "固化人物关系事实，后续节点不得改写。"),
        ("memory_commit_chapter", "memory.writing.artifact_index", "chapter_outlines", "已冻结章节细纲", ["frozen_chapter_outline"], "把已经开写并提交的批次细纲冻结为历史依据；后续只能整理未开写部分。"),
        ("memory_commit_chapter", "memory.writing.artifact_index", "candidates", "已审核章节候选", ["chapter_draft"], "提交已通过审核的章节候选引用。"),
        ("memory_commit_chapter", "memory.writing.artifact_index", "reviews", "章节审核提交", ["chapter_review"], "提交章节审核记录和裁决。"),
        ("memory_commit_chapter", "memory.writing.artifact_index", "chapter_commits", "章节提交", ["chapter_commit", "chapter_summary", "chapter_file_ref"], "提交章节文件引用、摘要和事实增量索引。"),
        ("memory_commit_chapter", "memory.writing.issue_ledger", "chapter_issues", "章节问题提交", ["blocking_issue", "non_blocking_issue", "revision_requirement"], "提交章节问题状态，阻塞项必须在进入下一阶段前明确。"),
        ("volume_commit", "memory.writing.artifact_index", "reviews", "卷级审核提交", ["volume_review"], "提交卷级审核记录。"),
        ("volume_commit", "memory.writing.artifact_index", "volume_commits", "卷级提交", ["volume_commit", "volume_summary"], "提交卷级摘要、章节清单和卷级事实索引。"),
        ("volume_commit", "memory.writing.issue_ledger", "volume_issues", "卷级问题提交", ["canon_drift_issue", "continuity_issue", "pacing_issue"], "提交卷级问题处理状态。"),
        ("extension_commit", "memory.writing.mutable", "strategy", "策略更新提交", ["strategy_adjustment", "next_volume_focus"], "提交审核通过的策略调整。"),
        ("extension_commit", "memory.writing.mutable", "outline_delta", "大纲补充提交", ["outline_memory_delta", "world_memory_delta"], "提交审核通过的大纲补充，不能覆盖基准事实。"),
        ("extension_commit", "memory.writing.mutable", "character_weight", "人物权重提交", ["character_weight_delta", "exposure_schedule"], "提交审核通过的人物权重和出场节奏调整。"),
        ("extension_commit", "memory.writing.artifact_index", "reviews", "可改动层审核提交", ["extension_review"], "提交可改动层审核记录。"),
        ("extension_commit", "memory.writing.issue_ledger", "volume_issues", "可改动层问题提交", ["boundary_violation", "rejected_frozen_fact_change"], "提交可改动层问题处理状态。"),
        ("memory_finalize", "memory.writing.artifact_index", "delivery", "交付提交", ["delivery_manifest", "delivery_package", "final_manuscript"], "提交最终交付包、归档引用和完成状态。"),
        ("memory_finalize", "memory.writing.artifact_index", "reviews", "最终审核提交", ["final_review"], "提交最终审核记录。"),
        ("memory_finalize", "memory.writing.issue_ledger", "final_issues", "最终问题提交", ["delivery_blocker", "open_issue"], "提交最终问题状态和残留风险。"),
    ]:
        edges.append(memory_edge("commit", task_node, repository, collection, label=label, usage_instruction=usage, record_kinds=kinds, on_missing="warn"))
    return edges


def task_record(node):
    node_id, title, agent, projection, input_contract, output_contract, phase, seq, path, role = node
    task_mode = "general_task" if role == "human" else node_id
    return {
        "task_id": "task.writing.simple_novel." + node_id,
        "task_title": title,
        "task_family": TASK_FAMILY,
        "task_mode": task_mode,
        "description": "写作组简易长篇小说节点任务：" + title,
        "enabled": True,
        "input_contract_id": input_contract,
        "output_contract_id": output_contract,
        "acceptance_profile_id": "",
        "default_flow_contract_id": "flow.writing.simple_novel." + node_id,
        "default_workflow_id": "workflow.writing.simple_novel." + node_id,
        "default_projection_policy": "task_default_required" if projection else "projection_not_required",
        "task_policy": {
            "safety_policy": {"verification_mode": "artifact_or_trace", "write_mode": "scoped", "safety_class": "S2_bounded"},
            "task_structure": {
                "runtime_lane_hint": "coordination_task",
                "memory_scope_hint": MEMORY_SCOPE,
                "workflow_steps": [
                    {"step_id": "memory_read", "title": "读取授权记忆包"},
                    {"step_id": "execute_node", "title": "执行节点职责"},
                    {"step_id": "memory_write", "title": "写入候选/审核/commit 结果"},
                ],
                "task_resource_kind": "task.writing.simple_novel." + node_id,
                "execution_chain_type": "coordination_node",
                "role": role,
                "projection_id": projection,
                "memory_closed_loop": True,
            },
            "runtime_limits": {},
            "artifact_policy": artifact_policy(path),
            "stream_policy": stream_policy(node_id, role),
            "operation_policy": {
                "allowed_operations": ["op.model_response", "op.memory_read"],
                "blocked_operations": ["op.shell", "op.python_repl", "op.delegate_to_agent", "op.web_search"],
            },
        },
        "metadata": {"managed_by": MANAGED, "domain_id": DOMAIN_ID, "task_id": "task.writing.simple_novel." + node_id, "projection_id": projection, "source_flow_id": "flow.writing.simple_novel." + node_id, "package_template": TASK_FAMILY},
    }


def workflow(node):
    node_id, title, agent, projection, input_contract, output_contract, phase, seq, path, role = node
    prompts = parse_prompts()
    task_mode = "general_task" if role == "human" else node_id
    return {
        "workflow_id": "workflow.writing.simple_novel." + node_id,
        "title": title + "工作流",
        "task_mode": task_mode,
        "compatible_projection_ids": [projection] if projection else [],
        "visible_skill_ids": [],
        "steps": [
            {"step_id": "read_memory_pack", "title": "读取当前节点授权记忆包"},
            {"step_id": "produce_contract_output", "title": "按契约产出结构化结果"},
            {"step_id": "write_index_or_handoff", "title": "写入索引或交接下游"},
        ],
        "input_boundary": input_contract,
        "output_boundary": output_contract,
        "stop_conditions": ["contract_output_ready", "blocking_issue_reported", "memory_pack_blocked"],
        "required_evidence_refs": ["memory_pack", "artifact_refs", "contract_payload"],
        "output_contract_id": output_contract,
        "prompt": prompt_for(projection, prompts) if projection else "你需要按当前任务契约完成输出，只使用输入包中明确授权的上下文。",
        "enabled": True,
        "metadata": {"managed_by": MANAGED, "domain_id": DOMAIN_ID, "task_family": TASK_FAMILY, "task_id": "task.writing.simple_novel." + node_id, "flow_id": "flow.writing.simple_novel." + node_id, "projection_id": projection},
    }


def flow(node):
    node_id, title, agent, projection, input_contract, output_contract, phase, seq, path, role = node
    task_mode = "general_task" if role == "human" else node_id
    return {
        "flow_id": "flow.writing.simple_novel." + node_id,
        "task_mode": task_mode,
        "task_family": TASK_FAMILY,
        "title": title,
        "input_contract_id": input_contract,
        "output_contract_id": output_contract,
        "default_agent_id": agent,
        "default_workflow_id": "workflow.writing.simple_novel." + node_id,
        "default_runtime_lane": "full_interactive" if role == "human" else "coordination_task",
        "default_memory_scope": MEMORY_SCOPE,
        "enabled": True,
        "metadata": {"managed_by": MANAGED, "domain_id": DOMAIN_ID, "task_id": "task.writing.simple_novel." + node_id, "projection_id": projection},
    }


def assignment(node):
    node_id, title, agent, projection, input_contract, output_contract, phase, seq, path, role = node
    task_mode = "general_task" if role == "human" else node_id
    return {
        "task_id": "task.writing.simple_novel." + node_id,
        "task_title": title,
        "task_kind": "specific_task",
        "task_family": TASK_FAMILY,
        "task_mode": task_mode,
        "flow_id": "flow.writing.simple_novel." + node_id,
        "workflow_id": "workflow.writing.simple_novel." + node_id,
        "workflow_file_ref": "workflow:workflow.writing.simple_novel." + node_id,
        "projection_id": projection,
        "input_contract_id": input_contract,
        "output_contract_id": output_contract,
        "safety_policy": {"verification_mode": "artifact_or_trace", "write_mode": "scoped", "safety_class": "S2_bounded"},
        "task_structure": {"execution_chain_type": "coordination_node", "role": role, "projection_id": projection, "task_graph_id": GRAPH_ID, "communication_protocol_id": PROTOCOL_ID, "topology_template_id": TOPOLOGY_ID, "agent_group_id": GROUP_ID, "memory_scope_hint": MEMORY_SCOPE},
        "enabled": True,
        "metadata": {"managed_by": MANAGED, "domain_id": DOMAIN_ID, "package_template": TASK_FAMILY},
        "execution_chain_type": "coordination_node",
    }


def memory_profile(node):
    node_id, title, agent, projection, input_contract, output_contract, phase, seq, path, role = node
    return {
        "profile_id": "taskmem:task.writing.simple_novel." + node_id,
        "task_id": "task.writing.simple_novel." + node_id,
        "requested_memory_layers": ["task_state", "artifact_index", "issue_ledger"],
        "requested_topics": memory_read_policy(role, node_id=node_id)["topics"],
        "memory_priority": "high" if role in {"reviewer", "memory_steward"} else "normal",
        "writeback_policy": memory_write_policy(role, node_id=node_id)["mode"],
        "allow_long_term_memory": False,
        "memory_scope_hint": MEMORY_SCOPE,
        "metadata": {"managed_by": MANAGED, "conversation_memory": "suppressed_by_assembly" if role in {"creator", "reviewer", "router", "final_assembler"} else "restricted", "memory_contract": "memory_pack_required", "memory_access_model": "edge_based_repository_access"},
        "authority": "task_system.task_memory_request_profile",
    }


def projection_binding(node):
    node_id, title, agent, projection, input_contract, output_contract, phase, seq, path, role = node
    return {
        "binding_id": "taskprojbind:task.writing.simple_novel." + node_id,
        "task_id": "task.writing.simple_novel." + node_id,
        "projection_selection_mode": "task_default_required" if projection else "projection_not_required",
        "allowed_projection_ids": [projection] if projection else [],
        "default_projection_id": projection,
        "projection_required": bool(projection),
        "notes": "写作组简易长篇小说节点投影绑定。" if projection else "该节点未绑定 agent-facing projection。",
        "metadata": {"managed_by": MANAGED, "role": role},
        "authority": "task_system.task_projection_binding",
    }


def flow_binding(node):
    node_id, *_ = node
    return {
        "binding_id": "taskflowbind:task.writing.simple_novel." + node_id,
        "task_id": "task.writing.simple_novel." + node_id,
        "flow_contract_id": node[5],
        "override_policy": "task_default",
        "verification_gate_profile": "",
        "fallback_policy": "fail_closed",
        "metadata": {"managed_by": MANAGED, "derived_from": "writing_simple_novel_config"},
        "authority": "task_system.task_flow_contract_binding",
    }


def configure():
    agents = {
        "agent:writing_simple_creator": ("写作组创作者", "projection.writing.simple_novel.project_brief", "生成项目启动包、分卷计划、章节正文和卷后补充提案。"),
        "agent:writing_simple_reviewer": ("写作组审核员", "projection.writing.simple_novel.volume_reviewer", "执行章节轻审、卷级总审、补充边界审和推进裁决。"),
        "agent:writing_memory_steward": ("写作组记忆管家", "projection.writing.simple_novel.memory_steward", "初始化基准库，并写入章节、卷级、可改动库和交付索引。"),
        "agent:writing_final_assembler": ("写作组交付包整编者", "projection.writing.simple_novel.final_assembler", "基于 manifest、章节文件引用和摘要整理交付包。"),
    }

    data = load("storage/orchestration/agents.json")
    data["agents"] = strip_items(data["agents"], "agent_id", ("agent:writing_simple_", "agent:writing_memory_", "agent:writing_final_"))
    for agent_id, (name, projection, desc) in agents.items():
        data["agents"].append({"agent_id": agent_id, "agent_name": name, "display_name": name, "agent_category": "worker_sub_agent", "profile_type": "worker_sub_agent", "interface_target": "task_graph_node_runtime", "description": desc, "enabled": True, "builtin": False, "editable": True, "default_soul_id": "hebo", "default_projection_id": projection, "created_at": NOW, "updated_at": NOW, "metadata": {"managed_by": MANAGED, "task_family": TASK_FAMILY, "definition_source": "task_graph_assembly", "source_task_graph_refs": [GRAPH_ID], "system_key": "worker_pool"}})
    save("storage/orchestration/agents.json", data)

    data = load("storage/orchestration/agent_runtime_profiles.json")
    data["profiles"] = strip_items(data["profiles"], "agent_id", ("agent:writing_simple_", "agent:writing_memory_", "agent:writing_final_"))
    for agent_id in agents:
        role = "creator" if "creator" in agent_id else "reviewer" if "reviewer" in agent_id else "memory_steward" if "memory" in agent_id else "final_assembler"
        allowed_task_modes = sorted({node[0] for node in NODE_DEFS if node[2] == agent_id})
        data["profiles"].append({"agent_profile_id": agent_id.replace("agent:", "") + "_runtime", "agent_id": agent_id, "allowed_task_modes": allowed_task_modes, "allowed_runtime_lanes": ["coordination_task", "system_memory"] if role == "memory_steward" else ["coordination_task"], "allowed_operations": ["op.model_response", "op.memory_read"], "blocked_operations": ["op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.delegate_to_agent", "op.web_search"], "allowed_memory_scopes": [MEMORY_SCOPE, "state_readonly"], "allowed_context_sections": ["task", "projection", "runtime_contracts", "artifact_refs", "memory_runtime_view"], "use_shared_contract": True, "output_contracts": [node[5] for node in NODE_DEFS if node[2] == agent_id], "can_delegate_to_agents": False, "allowed_delegate_agent_ids": [], "allowed_delegate_agent_categories": ["worker_sub_agent"], "max_delegate_calls_per_turn": 0, "delegate_context_policy": "summary_and_refs_only", "approval_policy": "read_only_first", "trace_policy": "runtime_event_log", "lifecycle_policy": "task_graph_managed", "metadata": {"managed_by": MANAGED, "task_family": TASK_FAMILY, "source_task_graph_refs": [GRAPH_ID]}})
    save("storage/orchestration/agent_runtime_profiles.json", data)

    data = load("storage/orchestration/agent_groups.json")
    data["groups"] = strip_items(data["groups"], "group_id", exact=(GROUP_ID,))
    data["groups"].append({"group_id": GROUP_ID, "title": "写作组", "group_kind": "coordination_team", "description": "执行简易版长篇小说完整生产流程。", "coordinator_agent_id": "agent:0", "member_agent_ids": list(agents), "default_topology_template_ids": [TOPOLOGY_ID], "default_communication_protocol_ids": [PROTOCOL_ID], "allowed_task_graph_ids": [GRAPH_ID], "lifecycle_state": "enabled", "metadata": {"managed_by": MANAGED, "design_doc": DESIGN_DOC}, "authority": "orchestration.agent_group", "allowed_coordination_task_ids": ["task.writing.simple_novel." + node[0] for node in NODE_DEFS]})
    save("storage/orchestration/agent_groups.json", data)

    data = load("backend/soul/projections/catalog.json")
    data["cards"] = strip_items(data["cards"], "projection_id", ("projection.writing.simple_novel.",))
    data["cards"].extend(projection_cards())
    save("backend/soul/projections/catalog.json", data)

    data = load("storage/tasks/task_domains.json")
    data["task_domains"] = strip_items(data["task_domains"], "domain_id", exact=(DOMAIN_ID,))
    data["task_domains"].append({"domain_id": DOMAIN_ID, "task_family": TASK_FAMILY, "title": "写作组简易长篇小说", "description": "写作组简易长篇小说完整任务图配置域。", "enabled": True, "sort_order": 80, "metadata": {"managed_by": MANAGED}})
    save("storage/tasks/task_domains.json", data)

    contracts = [contract("contract.writing.simple_novel." + key, fields) for key, fields in CONTRACT_FIELDS.items()]
    contracts.append(contract("contract.writing.simple_novel.graph", ["project_id", "delivery_package_id", "task_state", "artifact_refs", "summary"], kind="graph_execution"))
    data = load("storage/tasks/contract_specs.json")
    data["contract_specs"] = strip_items(data["contract_specs"], "contract_id", ("contract.writing.simple_novel.",))
    data["contract_specs"].extend(contracts)
    save("storage/tasks/contract_specs.json", data)

    targets = [
        ("storage/tasks/specific_task_records.json", "specific_task_records", "task_id", ("task.writing.simple_novel.",), task_record),
        ("storage/tasks/task_workflows.json", "workflows", "workflow_id", ("workflow.writing.simple_novel.",), workflow),
        ("storage/tasks/task_flows.json", "flows", "flow_id", ("flow.writing.simple_novel.",), flow),
        ("storage/tasks/task_assignments.json", "assignments", "task_id", ("task.writing.simple_novel.",), assignment),
        ("storage/tasks/task_memory_request_profiles.json", "memory_request_profiles", "profile_id", ("taskmem:task.writing.simple_novel.",), memory_profile),
        ("storage/tasks/task_projection_bindings.json", "projection_bindings", "binding_id", ("taskprojbind:task.writing.simple_novel.",), projection_binding),
        ("storage/tasks/task_flow_contract_bindings.json", "flow_contract_bindings", "binding_id", ("taskflowbind:task.writing.simple_novel.",), flow_binding),
    ]
    for path, key, id_key, prefix, maker in targets:
        data = load(path)
        data[key] = strip_items(data[key], id_key, prefix)
        data[key].extend(maker(node) for node in NODE_DEFS)
        save(path, data)

    data = load("storage/tasks/task_communication_protocols.json")
    data["communication_protocols"] = strip_items(data["communication_protocols"], "protocol_id", exact=(PROTOCOL_ID,))
    data["communication_protocols"].append({
        "protocol_id": PROTOCOL_ID,
        "title": "写作组简易长篇小说通信协议",
        "message_types": ["message/send", "task/status", "task/artifact", "task/review_feedback", "task/revision_request", "task/canon_update", "task/memory_read", "task/memory_write"],
        "payload_contracts": [item["contract_id"] for item in contracts],
        "signal_rules": ["memory_pack_required_before_business_node", "candidate_ref_required_before_review", "pass_required_before_memory_commit", "baseline_memory_written_only_by_commit_edge", "mutable_memory_written_only_by_extension_commit_edge", "repair_returns_to_trigger_node", "final_assemble_uses_manifest_not_full_text"],
        "handoff_rules": ["structured_artifact_refs_only", "no_raw_agent_dialogue", "memory_pack_refs_only", "no_unapproved_memory_write", "candidate_outputs_are_not_memory", "chapter_full_text_not_handed_as_global_context", "delivery_manifest_not_full_text_context"],
        "ack_policy": "explicit_ack",
        "timeout_policy": "fail_closed",
        "error_signal_policy": "raise_to_coordinator",
        "enabled": True,
        "metadata": {"managed_by": MANAGED, "task_family": TASK_FAMILY, "domain_id": DOMAIN_ID, "memory_access_model": "edge_based_repository_access"},
        "authority": "task_system.task_communication_protocol",
    })
    save("storage/tasks/task_communication_protocols.json", data)

    graph_nodes = [graph_node(node) for node in NODE_DEFS] + memory_repository_nodes()
    edges = build_edges()

    topology_nodes = [{"node_id": n["node_id"], "node_type": n["node_type"], "title": n["title"], "task_id": n.get("task_id", ""), "agent_id": n.get("agent_id", ""), "role": n.get("work_posture", ""), "work_posture": n.get("work_posture", ""), "projection_id": n.get("projection_id", ""), "phase_id": n.get("phase_id", ""), "sequence_index": n.get("sequence_index", 0), "execution_mode": n.get("execution_mode", "sync"), "dispatch_group": n.get("dispatch_group", ""), "artifact_target": n.get("artifact_target", ""), "output_path": n.get("output_path", ""), "artifact_policy": n.get("artifact_policy", {}), "artifact_context_policy": n.get("artifact_context_policy", {}), "revision_context_policy": n.get("revision_context_policy", {}), "quality_retry_policy": n.get("quality_retry_policy", {}), "progress_commit_policy": n.get("progress_commit_policy", {}), "loop_policy": n.get("loop_policy", {}), "loop_kind": n.get("loop_kind", ""), "loop_scope_id": n.get("loop_scope_id", ""), "title_template": n.get("title_template", ""), "loop_route_policy": n.get("loop_route_policy", {}), "resource_lifecycle_policy": n.get("resource_lifecycle_policy", {}), "metadata": n.get("metadata", {})} for n in graph_nodes]
    topology_edges = [{"edge_id": e["edge_id"], "source_node_id": e["source_node_id"], "target_node_id": e["target_node_id"], "mode": e["edge_type"], "edge_type": e["edge_type"], "payload_contract_id": e["payload_contract_id"], "metadata": e.get("metadata", {})} for e in edges]
    data = load("storage/tasks/topology_templates.json")
    data["topology_templates"] = strip_items(data["topology_templates"], "template_id", exact=(TOPOLOGY_ID,))
    data["topology_templates"].append({"template_id": TOPOLOGY_ID, "title": "写作组简易长篇小说拓扑", "nodes": topology_nodes, "edges": topology_edges, "handoff_rules": ["memory_pack_required", "candidate_ref_before_review", "pass_before_commit", "manifest_not_full_text"], "join_policy": "explicit_join", "failure_policy": "fail_closed", "terminal_policy": "coordinator_terminal", "enabled": True, "metadata": {"managed_by": MANAGED, "task_family": TASK_FAMILY, "domain_id": DOMAIN_ID, "graph_id": GRAPH_ID}})
    save("storage/tasks/topology_templates.json", data)

    data = load("storage/tasks/task_graphs.json")
    data["task_graphs"] = strip_items(data["task_graphs"], "graph_id", exact=(GRAPH_ID,))
    working_memory_policy = {
        "memory_scope": MEMORY_SCOPE,
        "access_model": "edge_based_repository_access",
        "repository_node_ids": [item["node_id"] for item in MEMORY_REPOSITORY_DEFS],
        "conversation_memory": "suppressed_for_creator_and_reviewer",
        "raw_full_text_global_context": "forbidden",
        "scheduler_binding": "memory_edges_are_context_edges_not_business_steps",
        "libraries": {
            "baseline_memory": {
                "repository_node_id": "memory.writing.baseline",
                "write_authority": "memory_commit_edges_only",
                "read_authority": "memory_read_edges_only",
                "mutable": False,
                "library_role": "read_only_canon_baseline",
                "includes": ["baseline_world_spine", "baseline_outline_spine", "baseline_character_spine", "frozen_character_facts", "frozen_relationship_facts"],
                "frozen_fact_classes": ["world_rule", "character_fact", "relationship_fact", "committed_canon_fact"],
            },
            "mutable_memory": {
                "repository_node_id": "memory.writing.mutable",
                "write_authority": "extension_commit_memory_commit_edges",
                "read_authority": "memory_read_edges_only",
                "mutable": True,
                "library_role": "post_volume_adjustment_layer",
                "forbidden_rewrites": ["frozen_character_facts", "frozen_relationship_facts", "baseline_character_spine"],
                "allowed_update_classes": ["strategy_adjustment", "weight_adjustment", "exposure_schedule", "next_volume_focus", "supplemental_world_detail"],
            },
        },
    }
    data["task_graphs"].append({
        "graph_id": GRAPH_ID,
        "title": "写作组分卷长篇小说任务图",
        "domain_id": DOMAIN_ID,
        "task_family": TASK_FAMILY,
        "graph_kind": "coordination",
        "entry_node_id": "project_brief",
        "output_node_id": "memory_finalize",
        "nodes": graph_nodes,
        "edges": edges,
        "graph_contract_id": "contract.writing.simple_novel.graph",
        "default_protocol_id": PROTOCOL_ID,
        "working_memory_policy_profile_id": "wmprofile.writing.simple_novel",
        "working_memory_policy": working_memory_policy,
        "runtime_policy": {"execution_mode": "coordinator_driven", "fail_default": "fail_closed", "memory_pack_required": True, "human_gate_mode": "auto_continue", "agent_group_id": GROUP_ID},
        "context_policy": {"handoff": "contract_payload_and_refs", "raw_dialogue_handoff": "forbidden", "long_text_policy": "artifact_ref_and_summary_only"},
        "publish_state": "published",
        "enabled": True,
        "metadata": {
            "managed_by": MANAGED,
            "design_doc": DESIGN_DOC,
            "topology_template_id": TOPOLOGY_ID,
            "agent_group_id": GROUP_ID,
            "memory_closed_loop": True,
            "memory_access_model": "repository_nodes_and_memory_edges",
            "old_graph_dependency": "none",
            "editor_publish_state": "published",
            "continuation_policy": {"human_gate_mode": "auto_continue"},
            "runtime_loop_policy": {
                "enabled": True,
                "initial_inputs": initial_runtime_loop_inputs(),
                "derived_fields": loop_derived_fields(),
                "summary": "当前卷：{volume_label}；当前批次：{batch_label}；本批允许范围：{batch_chapter_list}；全书累计约 {current_words}/{target_words} 字；本卷累计约 {volume_current_words}/{volume_target_words} 字。",
                "frames": [
                    {"frame_id": "loop.chapter_batch", "entry_stage_id": "chapter_outline", "router_stage_id": "chapter_progress_router", "exit_stage_id": "volume_review"},
                    {"frame_id": "loop.volume", "router_stage_id": "next_volume_router", "continue_stage_id": "chapter_outline", "exit_stage_id": "final_assemble"},
                ],
            },
        },
        "authority": "task_system.task_graph",
        "graph_nodes": [n["node_id"] for n in graph_nodes],
        "graph_edges": [e["edge_id"] for e in edges],
        "issues": [],
        "valid": True,
        "subtask_refs": ["task.writing.simple_novel." + node[0] for node in NODE_DEFS],
    })
    save("storage/tasks/task_graphs.json", data)

    print(f"configured {len(NODE_DEFS)} node tasks, {len(edges)} edges, {len(contracts)} contracts, {len(projection_cards())} projections")


if __name__ == "__main__":
    configure()
