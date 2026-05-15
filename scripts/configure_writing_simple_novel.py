import json
import re
import time
from pathlib import Path


NOW = time.time()
MANAGED = "codex_writing_simple_novel_config_20260516"
GROUP_ID = "group.writing.simple_novel"
DOMAIN_ID = "domain.writing.simple_novel"
TASK_FAMILY = "writing_simple_novel"
GRAPH_ID = "graph.writing.simple_novel"
TOPOLOGY_ID = "topology.writing.simple_novel"
PROTOCOL_ID = "protocol.writing.simple_novel"
MEMORY_SCOPE = "writing_simple_novel"
DESIGN_DOC = "docs/系统规划/108-写作组简易长篇小说任务图配置设计书-20260516.md"


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
            "必须符合 108 设计书的节点级闭环表。",
            "不得用普通消息文本代替结构化契约和 artifact refs。",
            "候选不得直接提升为 canon；canon 写入必须来自 pass 裁决。",
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
        "subdir_template": "{session_id}",
        "artifact_target": path,
        "storage_policy": "task_artifact_ref",
        "artifacts": [{"path": path, "required": True, "content_source": "final_content", "fallback_to_full_content": False}],
    }


def memory_read_policy(role):
    topics = {
        "creator": ["project_brief", "approved_canon", "issue_ledger", "previous_review_requirements"],
        "reviewer": ["current_candidate_ref", "approved_canon", "issue_ledger", "previous_review"],
        "memory_steward": ["pass_review", "canon_write_instructions", "candidate_ref", "old_canon_version"],
        "router": ["chapter_plan_commit", "completed_chapter_refs", "open_issue_refs"],
        "final_assembler": ["delivery_requirements", "chapter_commit_manifest", "chapter_file_refs", "chapter_summary_refs", "open_issue_refs"],
        "memory_system": ["memory_index_request", "artifact_refs", "version_state"],
        "human": ["safe_state_refs", "blocking_issues"],
    }.get(role, ["project_state"])
    return {
        "mode": "memory_pack_required",
        "memory_node": "memory_index_read",
        "topics": topics,
        "readable_kinds": ["canon", "candidate_ref", "review_record", "issue_ledger", "chapter_summary", "chapter_file_ref", "delivery_manifest"],
        "readable_scopes": [MEMORY_SCOPE, "project_state", "node_scope"],
        "summary_only": True,
        "enabled": True,
        "read_request_contract_id": "contract.writing.simple_novel.memory_read_request",
        "result_contract_id": "contract.writing.simple_novel.memory_pack",
        "suppress_conversation_memory": role in {"creator", "reviewer", "router", "final_assembler"},
        "token_budget": 6000,
    }


def memory_write_policy(role):
    modes = {
        "creator": ("candidate_archive_only", ["candidate_archive_index"]),
        "reviewer": ("review_and_issue_ledger", ["review_archive_index", "issue_ledger_index"]),
        "memory_steward": ("canon_or_delivery_commit_with_lock", ["canon_index", "chapter_commit_manifest", "delivery_manifest_index", "task_state"]),
        "final_assembler": ("delivery_manifest_only", ["delivery_manifest_index"]),
        "router": ("routing_decision_only", ["runtime_decision_log"]),
        "memory_system": ("system_receipt", ["memory_runtime_index"]),
    }
    mode, indexes = modes.get(role, ("system_receipt", ["memory_runtime_index"]))
    return {
        "mode": mode,
        "memory_node": "memory_index_write",
        "lock_node": "memory_index_lock" if role == "memory_steward" else "",
        "release_node": "memory_index_release" if role == "memory_steward" else "",
        "capture_artifact_refs": True,
        "writable_indexes": indexes,
        "writable_kinds": ["candidate", "review", "canon_commit", "chapter_commit", "delivery_manifest", "runtime_receipt"],
        "writable_scopes": [MEMORY_SCOPE, "project_state", "node_scope"],
        "write_contract_id": "contract.writing.simple_novel.memory_write_request",
        "receipt_contract_id": "contract.writing.simple_novel.memory_write_receipt",
    }


def parse_prompts():
    text = Path(DESIGN_DOC).read_text(encoding="utf-8")
    prompts = {}
    for match in re.finditer(r"### 8\.\d+ `([^`]+)`\s*\n\s*```text\s*\n(.*?)\n```", text, re.S):
        prompts[match.group(1)] = match.group(2).strip()
    repair_match = re.search(r"### 8\.16 修复 creator 投影差异.*?```text\s*\n(.*?)\n```", text, re.S)
    repair_delta = repair_match.group(1).strip() if repair_match else ""
    return prompts, repair_delta


NODE_DEFS = [
    ("project_brief", "项目启动包", "agent:writing_simple_creator", "projection.writing.simple_novel.project_brief", "contract.writing.simple_novel.user_goal", "contract.writing.simple_novel.project_brief", "phase.start", 1, "project_brief.md", "creator"),
    ("world_candidate", "世界观候选", "agent:writing_simple_creator", "projection.writing.simple_novel.world_creator", "contract.writing.simple_novel.world_input", "contract.writing.simple_novel.world_candidate", "phase.world", 10, "world/world_candidate.md", "creator"),
    ("world_review", "世界观审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.world_reviewer", "contract.writing.simple_novel.world_review_input", "contract.writing.simple_novel.world_review", "phase.world", 20, "reviews/world_review.md", "reviewer"),
    ("memory_commit_world", "世界观 canon 写入", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.world_review", "contract.writing.simple_novel.world_canon_commit", "phase.world", 30, "memory/world_canon_commit.md", "memory_steward"),
    ("outline_candidate", "大纲候选", "agent:writing_simple_creator", "projection.writing.simple_novel.outline_creator", "contract.writing.simple_novel.outline_input", "contract.writing.simple_novel.outline_candidate", "phase.outline", 40, "outline/outline_candidate.md", "creator"),
    ("outline_review", "大纲审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.outline_reviewer", "contract.writing.simple_novel.outline_review_input", "contract.writing.simple_novel.outline_review", "phase.outline", 50, "reviews/outline_review.md", "reviewer"),
    ("memory_commit_outline", "大纲 canon 写入", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.outline_review", "contract.writing.simple_novel.outline_canon_commit", "phase.outline", 60, "memory/outline_canon_commit.md", "memory_steward"),
    ("character_candidate", "人物候选", "agent:writing_simple_creator", "projection.writing.simple_novel.character_creator", "contract.writing.simple_novel.character_input", "contract.writing.simple_novel.character_candidate", "phase.character", 70, "characters/character_candidate.md", "creator"),
    ("character_review", "人物审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.character_reviewer", "contract.writing.simple_novel.character_review_input", "contract.writing.simple_novel.character_review", "phase.character", 80, "reviews/character_review.md", "reviewer"),
    ("memory_commit_character", "人物 canon 写入", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.character_review", "contract.writing.simple_novel.character_canon_commit", "phase.character", 90, "memory/character_canon_commit.md", "memory_steward"),
    ("chapter_plan_candidate", "分章规划候选", "agent:writing_simple_creator", "projection.writing.simple_novel.chapter_plan_creator", "contract.writing.simple_novel.chapter_plan_input", "contract.writing.simple_novel.chapter_plan_candidate", "phase.chapter_plan", 100, "chapter_plan/chapter_plan_candidate.md", "creator"),
    ("chapter_plan_review", "分章规划审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.chapter_plan_reviewer", "contract.writing.simple_novel.chapter_plan_review_input", "contract.writing.simple_novel.chapter_plan_review", "phase.chapter_plan", 110, "reviews/chapter_plan_review.md", "reviewer"),
    ("memory_commit_chapter_plan", "分章 canon 写入", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.chapter_plan_review", "contract.writing.simple_novel.chapter_plan_commit", "phase.chapter_plan", 120, "memory/chapter_plan_commit.md", "memory_steward"),
    ("chapter_draft", "当前章节正文候选", "agent:writing_simple_creator", "projection.writing.simple_novel.chapter_writer", "contract.writing.simple_novel.chapter_draft_input", "contract.writing.simple_novel.chapter_draft", "phase.chapter_loop", 130, "chapters/chapter_{chapter_index:03d}/draft_round_{round_index:03d}.md", "creator"),
    ("chapter_review", "当前章节审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.chapter_reviewer", "contract.writing.simple_novel.chapter_review_input", "contract.writing.simple_novel.chapter_review", "phase.chapter_loop", 140, "reviews/chapters/chapter_{chapter_index:03d}/review_round_{round_index:03d}.md", "reviewer"),
    ("memory_commit_chapter", "章节写入", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.chapter_review", "contract.writing.simple_novel.chapter_commit", "phase.chapter_loop", 150, "memory/chapters/chapter_{chapter_index:03d}/commit_round_{round_index:03d}.md", "memory_steward"),
    ("chapter_progress_router", "章节推进判断", "agent:writing_simple_reviewer", "projection.writing.simple_novel.chapter_progress_router", "contract.writing.simple_novel.chapter_commit", "contract.writing.simple_novel.chapter_progress_decision", "phase.chapter_loop", 160, "routing/chapters/chapter_{chapter_index:03d}/progress_round_{round_index:03d}.md", "router"),
    ("world_repair_candidate", "世界观专项修复候选", "agent:writing_simple_creator", "projection.writing.simple_novel.world_repair_creator", "contract.writing.simple_novel.world_repair_input", "contract.writing.simple_novel.world_candidate", "phase.repair", 210, "repairs/world_repair_candidate.md", "creator"),
    ("world_repair_review", "世界观专项修复审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.world_reviewer", "contract.writing.simple_novel.world_review_input", "contract.writing.simple_novel.world_review", "phase.repair", 220, "reviews/world_repair_review.md", "reviewer"),
    ("outline_repair_candidate", "大纲专项修复候选", "agent:writing_simple_creator", "projection.writing.simple_novel.outline_repair_creator", "contract.writing.simple_novel.outline_repair_input", "contract.writing.simple_novel.outline_candidate", "phase.repair", 230, "repairs/outline_repair_candidate.md", "creator"),
    ("outline_repair_review", "大纲专项修复审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.outline_reviewer", "contract.writing.simple_novel.outline_review_input", "contract.writing.simple_novel.outline_review", "phase.repair", 240, "reviews/outline_repair_review.md", "reviewer"),
    ("character_repair_candidate", "人物专项修复候选", "agent:writing_simple_creator", "projection.writing.simple_novel.character_repair_creator", "contract.writing.simple_novel.character_repair_input", "contract.writing.simple_novel.character_candidate", "phase.repair", 250, "repairs/character_repair_candidate.md", "creator"),
    ("character_repair_review", "人物专项修复审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.character_reviewer", "contract.writing.simple_novel.character_review_input", "contract.writing.simple_novel.character_review", "phase.repair", 260, "reviews/character_repair_review.md", "reviewer"),
    ("final_assemble", "交付包整编", "agent:writing_final_assembler", "projection.writing.simple_novel.final_assembler", "contract.writing.simple_novel.final_assemble_input", "contract.writing.simple_novel.final_manuscript", "phase.final", 300, "delivery/delivery_manifest.md", "final_assembler"),
    ("final_review", "最终交付审核", "agent:writing_simple_reviewer", "projection.writing.simple_novel.final_reviewer", "contract.writing.simple_novel.final_review_input", "contract.writing.simple_novel.final_review", "phase.final", 310, "reviews/final_review.md", "reviewer"),
    ("memory_finalize", "任务收尾归档", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.final_review", "contract.writing.simple_novel.delivery_package", "phase.final", 320, "memory/delivery_package.md", "memory_steward"),
    ("human_review_handoff", "人工接管", "agent:0", "hebo__primary", "contract.writing.simple_novel.human_review_input", "contract.writing.simple_novel.human_review_packet", "phase.terminal", 900, "handoff/human_review_packet.md", "human"),
    ("fail_closed", "失败关闭", "agent:writing_memory_steward", "projection.writing.simple_novel.memory_steward", "contract.writing.simple_novel.failure_input", "contract.writing.simple_novel.failure_report", "phase.terminal", 910, "failure/failure_report.md", "memory_steward"),
    ("memory_index_read", "记忆库读出", "agent:writing_memory_steward", "", "contract.writing.simple_novel.memory_read_request", "contract.writing.simple_novel.memory_pack", "phase.system_memory", 5, "memory/index_read_receipt.md", "memory_system"),
    ("memory_index_write", "记忆库写入", "agent:writing_memory_steward", "", "contract.writing.simple_novel.memory_write_request", "contract.writing.simple_novel.memory_write_receipt", "phase.system_memory", 6, "memory/index_write_receipt.md", "memory_system"),
    ("memory_index_lock", "记忆库写入锁", "agent:writing_memory_steward", "", "contract.writing.simple_novel.memory_write_request", "contract.writing.simple_novel.memory_lock_receipt", "phase.system_memory", 7, "memory/index_lock_receipt.md", "memory_system"),
    ("memory_index_release", "记忆库解锁", "agent:writing_memory_steward", "", "contract.writing.simple_novel.memory_lock_receipt", "contract.writing.simple_novel.memory_release_receipt", "phase.system_memory", 8, "memory/index_release_receipt.md", "memory_system"),
]


CONTRACT_FIELDS = {
    "user_goal": ["project_id", "source_user_goal", "delivery_requirements", "hard_constraints", "source_refs"],
    "project_brief": ["project_id", "project_title", "genre", "target_length", "style_requirements", "hard_constraints", "delivery_requirements", "source_user_goal", "open_questions", "downstream_world_input", "artifact_refs", "summary"],
    "world_input": ["project_id", "project_brief_ref", "world_issue_ledger_ref", "previous_world_review_ref", "memory_pack_id"],
    "world_candidate": ["project_id", "candidate_id", "candidate_kind", "input_refs", "candidate_body", "coverage_statement", "self_risk_notes", "public_summary", "not_canon", "artifact_refs", "summary"],
    "world_review_input": ["project_id", "project_brief_ref", "world_candidate_ref", "world_issue_ledger_ref", "memory_pack_id"],
    "world_review": ["project_id", "review_id", "reviewed_candidate_id", "verdict", "quality_score", "blocking_issues", "non_blocking_issues", "revision_requirements", "canon_write_instructions", "repair_request", "next_step", "summary"],
    "world_canon_commit": ["project_id", "canon_id", "canon_kind", "source_review_id", "source_candidate_id", "canon_body", "supersedes_canon_id", "readable_by_next_stages", "archived_candidate_refs", "summary"],
    "outline_input": ["project_id", "project_brief_ref", "world_canon_ref", "outline_issue_ledger_ref", "previous_outline_review_ref", "memory_pack_id"],
    "outline_candidate": ["project_id", "candidate_id", "candidate_kind", "input_refs", "candidate_body", "coverage_statement", "self_risk_notes", "public_summary", "not_canon", "artifact_refs", "summary"],
    "outline_review_input": ["project_id", "world_canon_ref", "outline_candidate_ref", "outline_issue_ledger_ref", "memory_pack_id"],
    "outline_review": ["project_id", "review_id", "reviewed_candidate_id", "verdict", "quality_score", "blocking_issues", "non_blocking_issues", "revision_requirements", "canon_write_instructions", "repair_request", "next_step", "summary"],
    "outline_canon_commit": ["project_id", "canon_id", "canon_kind", "source_review_id", "source_candidate_id", "canon_body", "supersedes_canon_id", "readable_by_next_stages", "archived_candidate_refs", "summary"],
    "character_input": ["project_id", "project_brief_ref", "world_canon_ref", "outline_canon_ref", "character_issue_ledger_ref", "memory_pack_id"],
    "character_candidate": ["project_id", "candidate_id", "candidate_kind", "input_refs", "candidate_body", "coverage_statement", "self_risk_notes", "public_summary", "not_canon", "artifact_refs", "summary"],
    "character_review_input": ["project_id", "world_canon_ref", "outline_canon_ref", "character_candidate_ref", "character_issue_ledger_ref", "memory_pack_id"],
    "character_review": ["project_id", "review_id", "reviewed_candidate_id", "verdict", "quality_score", "blocking_issues", "non_blocking_issues", "revision_requirements", "canon_write_instructions", "repair_request", "next_step", "summary"],
    "character_canon_commit": ["project_id", "canon_id", "canon_kind", "source_review_id", "source_candidate_id", "canon_body", "supersedes_canon_id", "readable_by_next_stages", "archived_candidate_refs", "summary"],
    "chapter_plan_input": ["project_id", "world_canon_ref", "outline_canon_ref", "character_canon_ref", "chapter_plan_issue_ledger_ref", "memory_pack_id"],
    "chapter_plan_candidate": ["project_id", "candidate_id", "candidate_kind", "input_refs", "candidate_body", "coverage_statement", "self_risk_notes", "public_summary", "not_canon", "artifact_refs", "summary"],
    "chapter_plan_review_input": ["project_id", "world_canon_ref", "outline_canon_ref", "character_canon_ref", "chapter_plan_candidate_ref", "chapter_plan_issue_ledger_ref", "memory_pack_id"],
    "chapter_plan_review": ["project_id", "review_id", "reviewed_candidate_id", "verdict", "quality_score", "blocking_issues", "non_blocking_issues", "revision_requirements", "canon_write_instructions", "repair_request", "next_step", "summary"],
    "chapter_plan_commit": ["project_id", "canon_id", "canon_kind", "source_review_id", "source_candidate_id", "canon_body", "chapter_order", "chapter_targets", "supersedes_canon_id", "readable_by_next_stages", "archived_candidate_refs", "summary"],
    "chapter_draft_input": ["project_id", "chapter_index", "chapter_target", "canon_summary_refs", "previous_chapter_summary_refs", "previous_chapter_review_ref", "memory_pack_id"],
    "chapter_draft": ["project_id", "candidate_id", "chapter_index", "candidate_kind", "input_refs", "candidate_body", "coverage_statement", "self_risk_notes", "public_summary", "not_canon", "artifact_refs", "summary"],
    "chapter_review_input": ["project_id", "chapter_index", "chapter_draft_ref", "chapter_input_ref", "previous_chapter_summary_refs", "canon_summary_refs", "chapter_issue_ledger_ref", "memory_pack_id"],
    "chapter_review": ["project_id", "review_id", "reviewed_candidate_id", "chapter_index", "verdict", "quality_score", "blocking_issues", "non_blocking_issues", "revision_requirements", "chapter_write_instructions", "repair_request", "next_step", "summary"],
    "chapter_commit": ["project_id", "chapter_commit_id", "chapter_index", "source_review_id", "source_candidate_id", "chapter_file_ref", "chapter_summary_ref", "chapter_facts_delta", "completed_chapter_refs", "summary"],
    "chapter_progress_decision": ["project_id", "current_chapter_index", "total_chapter_count", "completed_chapter_refs", "next_chapter_index", "decision", "next_step", "blocking_issues", "summary"],
    "repair_request": ["project_id", "repair_kind", "trigger_stage_id", "trigger_node_id", "return_stage_id", "return_node_id", "blocking_issue_ids", "repair_scope", "forbidden_scope", "reviewer_reason"],
    "world_repair_input": ["project_id", "repair_request_ref", "world_canon_ref", "trigger_review_ref", "repair_scope", "forbidden_scope", "memory_pack_id"],
    "outline_repair_input": ["project_id", "repair_request_ref", "outline_canon_ref", "trigger_review_ref", "repair_scope", "forbidden_scope", "memory_pack_id"],
    "character_repair_input": ["project_id", "repair_request_ref", "character_canon_ref", "trigger_review_ref", "repair_scope", "forbidden_scope", "memory_pack_id"],
    "final_assemble_input": ["project_id", "project_brief_ref", "canon_commit_refs", "chapter_plan_commit_ref", "chapter_commit_manifest", "chapter_file_refs", "chapter_summary_refs", "delivery_requirements", "open_issue_refs", "memory_pack_id"],
    "final_manuscript": ["project_id", "delivery_manifest_id", "chapter_order", "chapter_file_refs", "chapter_commit_refs", "chapter_summary_refs", "assembled_output_refs", "formatting_plan", "integrity_check_report", "known_non_blocking_limits", "delivery_blockers", "summary"],
    "final_review_input": ["project_id", "final_manuscript_ref", "delivery_manifest_id", "canon_commit_refs", "chapter_manifest_ref", "open_issue_refs", "memory_pack_id"],
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
    "memory_lock_receipt": ["lock_id", "project_id", "artifact_kind", "target_ref", "expected_version", "lock_status", "expires_at"],
    "memory_release_receipt": ["release_id", "lock_id", "project_id", "artifact_kind", "release_status", "commit_result", "released_at"],
}


def prompt_for(pid, prompts, repair_delta):
    if pid in prompts:
        return prompts[pid]
    base = {
        "projection.writing.simple_novel.world_repair_creator": "projection.writing.simple_novel.world_creator",
        "projection.writing.simple_novel.outline_repair_creator": "projection.writing.simple_novel.outline_creator",
        "projection.writing.simple_novel.character_repair_creator": "projection.writing.simple_novel.character_creator",
    }.get(pid)
    if base:
        return prompts.get(base, "") + "\n\n" + repair_delta
    return ""


def projection_cards():
    prompts, repair_delta = parse_prompts()
    titles = {
        "project_brief": "项目启动包整理者",
        "world_creator": "世界观创作者",
        "world_reviewer": "世界观审核员",
        "outline_creator": "大纲创作者",
        "outline_reviewer": "大纲审核员",
        "character_creator": "人物创作者",
        "character_reviewer": "人物审核员",
        "chapter_plan_creator": "分章规划者",
        "chapter_plan_reviewer": "分章规划审核员",
        "chapter_writer": "章节作者",
        "chapter_reviewer": "章节审核员",
        "chapter_progress_router": "章节推进审核员",
        "memory_steward": "写作资产记忆管家",
        "final_assembler": "交付包整编者",
        "final_reviewer": "最终交付审核员",
        "world_repair_creator": "世界观专项修复者",
        "outline_repair_creator": "大纲专项修复者",
        "character_repair_creator": "人物专项修复者",
    }
    projection_ids = sorted({node[3] for node in NODE_DEFS if node[3].startswith("projection.writing.simple_novel")})
    cards = []
    for pid in projection_ids:
        role = pid.split(".")[-1]
        prompt = prompt_for(pid, prompts, repair_delta)
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
            "memory_policy_summary": "记忆由 TaskGraph memory_index_read/write/lock/release 控制。",
            "output_contract_summary": "按节点 output_contract_id 输出。",
            "runtime_preview": {"identity_anchor": "", "projection_prompt": "", "usage_summary": "", "skill_views": [], "tool_views": [], "memory_policy_summary": "", "output_contract_summary": ""},
            "runtime_only_payload": False,
            "static_projection_card": True,
            "created_at": NOW,
            "updated_at": NOW,
            "is_primary": False,
            "is_system_default": False,
        })
    return cards


def graph_node(node):
    node_id, title, agent, projection, input_contract, output_contract, phase, seq, path, role = node
    node_type = {
        "reviewer": "review_gate",
        "memory_steward": "memory_commit",
        "router": "agent_role",
        "final_assembler": "agent_role",
        "human": "manual_gate",
        "memory_system": "memory_read",
    }.get(role, "agent_role")
    if role == "memory_system":
        if node_id == "memory_index_write":
            node_type = "memory_write"
        elif node_id == "memory_index_lock":
            node_type = "memory_resource"
        elif node_id == "memory_index_release":
            node_type = "memory_resource"
    if node_id == "memory_finalize":
        node_type = "memory_finalize"
    if node_id == "fail_closed":
        node_type = "memory_finalize"
    operation = ""
    if node_type == "memory_read":
        operation = "read"
    elif node_type == "memory_write":
        operation = "write"
    elif node_type in {"memory_commit", "memory_resource"}:
        operation = "commit" if node_id != "memory_index_release" else "finalize"
    elif node_type == "memory_finalize":
        operation = "finalize"
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
        "runtime_lane": "system_memory" if role == "memory_system" else "full_interactive" if role == "human" else "coordination_task",
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
        "memory_read_policy": memory_read_policy(role),
        "memory_writeback_policy": memory_write_policy(role),
        "dynamic_memory_read_policy": {},
        "phase_id": phase,
        "sequence_index": seq,
        "timeline_group_id": phase,
        "main_chain": role not in {"memory_system", "human"},
        "blocks_phase_exit": role != "memory_system",
        "loop_policy": {"loop_kind": "chapter_iteration", "loop_variable": "chapter_index", "exit_decision": "all_chapters_completed"} if node_id in {"chapter_draft", "chapter_review", "chapter_progress_router"} else {},
        "review_gate_policy": {"allowed_verdicts": ["pass", "revise", "repair_world", "repair_outline", "repair_character", "fail_closed"]} if role == "reviewer" else {},
        "artifact_policy": artifact_policy(path),
        "artifact_target": path,
        "output_path": path,
        "execution_mode": "sync",
        "dispatch_group": phase,
        "wait_policy": "wait_all_upstream_completed",
        "join_policy": "all_success",
        "background_policy": {},
        "notification_policy": {},
        "resource_lifecycle_policy": {},
        "metadata": {"managed_by": MANAGED, "role": role, "operation": operation, "memory_closed_loop": True, "requires_memory_pack": True, "design_doc": DESIGN_DOC},
    }


def edge(edge_id, source, target, contract_id, edge_type="structured_handoff", metadata=None):
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_type": edge_type,
        "a2a_message_type": "message/send",
        "payload_contract_id": contract_id,
        "context_filter_policy": {"mode": "explicit_refs_only", "raw_dialogue_handoff": "forbidden"},
        "artifact_ref_policy": {"required_for_long_outputs": True, "prefer_refs_over_text": True},
        "working_memory_handoff_policy": {
            "mode": "memory_pack_refs_only",
            "read_node": "memory_index_read",
            "carry_kinds": ["contract_payload", "artifact_ref", "memory_pack_ref", "issue_ledger_ref"],
            "carry_scopes": [MEMORY_SCOPE, "project_state", "node_scope"],
            "working_memory_refs": ["memory_pack_id", "artifact_refs"],
        },
        "ack_policy": "explicit_ack",
        "timeout_policy": "fail_closed",
        "wait_policy": "",
        "ack_required": True,
        "failure_propagation_policy": "fail_downstream",
        "result_delivery_policy": "contract_payload_and_refs",
        "failure_policy": {"on_missing_payload": "fail_closed"},
        "metadata": metadata or {},
    }


def build_edges():
    main = [
        ("edge.project.world", "project_brief", "world_candidate", "contract.writing.simple_novel.project_brief"),
        ("edge.world.review", "world_candidate", "world_review", "contract.writing.simple_novel.world_candidate"),
        ("edge.world_review.commit", "world_review", "memory_commit_world", "contract.writing.simple_novel.world_review"),
        ("edge.world_commit.outline", "memory_commit_world", "outline_candidate", "contract.writing.simple_novel.world_canon_commit"),
        ("edge.outline.review", "outline_candidate", "outline_review", "contract.writing.simple_novel.outline_candidate"),
        ("edge.outline_review.commit", "outline_review", "memory_commit_outline", "contract.writing.simple_novel.outline_review"),
        ("edge.outline_commit.character", "memory_commit_outline", "character_candidate", "contract.writing.simple_novel.outline_canon_commit"),
        ("edge.character.review", "character_candidate", "character_review", "contract.writing.simple_novel.character_candidate"),
        ("edge.character_review.commit", "character_review", "memory_commit_character", "contract.writing.simple_novel.character_review"),
        ("edge.character_commit.chapter_plan", "memory_commit_character", "chapter_plan_candidate", "contract.writing.simple_novel.character_canon_commit"),
        ("edge.chapter_plan.review", "chapter_plan_candidate", "chapter_plan_review", "contract.writing.simple_novel.chapter_plan_candidate"),
        ("edge.chapter_plan_review.commit", "chapter_plan_review", "memory_commit_chapter_plan", "contract.writing.simple_novel.chapter_plan_review"),
        ("edge.chapter_plan_commit.draft", "memory_commit_chapter_plan", "chapter_draft", "contract.writing.simple_novel.chapter_plan_commit"),
        ("edge.chapter_draft.review", "chapter_draft", "chapter_review", "contract.writing.simple_novel.chapter_draft"),
        ("edge.chapter_review.commit", "chapter_review", "memory_commit_chapter", "contract.writing.simple_novel.chapter_review"),
        ("edge.chapter_commit.router", "memory_commit_chapter", "chapter_progress_router", "contract.writing.simple_novel.chapter_commit"),
        ("edge.router.next_chapter", "chapter_progress_router", "chapter_draft", "contract.writing.simple_novel.chapter_progress_decision"),
        ("edge.router.final", "chapter_progress_router", "final_assemble", "contract.writing.simple_novel.chapter_progress_decision"),
        ("edge.final.review", "final_assemble", "final_review", "contract.writing.simple_novel.final_manuscript"),
        ("edge.final_review.finalize", "final_review", "memory_finalize", "contract.writing.simple_novel.final_review"),
    ]
    edges = [edge(*item) for item in main]
    for source, target, contract_name in [
        ("world_review", "world_candidate", "world_review"),
        ("outline_review", "outline_candidate", "outline_review"),
        ("character_review", "character_candidate", "character_review"),
        ("chapter_plan_review", "chapter_plan_candidate", "chapter_plan_review"),
        ("chapter_review", "chapter_draft", "chapter_review"),
        ("final_review", "final_assemble", "final_review"),
    ]:
        edges.append(edge(f"edge.{source}.revise", source, target, "contract.writing.simple_novel." + contract_name, "revision_request", {"verdict": "revise"}))
    repair_targets = {"repair_world": "world_repair_candidate", "repair_outline": "outline_repair_candidate", "repair_character": "character_repair_candidate"}
    for review_node in ["world_review", "outline_review", "character_review", "chapter_plan_review", "chapter_review", "final_review"]:
        allowed = ["repair_world"]
        if review_node != "world_review":
            allowed.append("repair_outline")
        if review_node in {"character_review", "chapter_plan_review", "chapter_review", "final_review"}:
            allowed.append("repair_character")
        for verdict in allowed:
            edges.append(edge(f"edge.{review_node}.{verdict}", review_node, repair_targets[verdict], "contract.writing.simple_novel.repair_request", "repair_route", {"verdict": verdict, "return_node_id": review_node}))
    for kind in ["world", "outline", "character"]:
        edges.append(edge(f"edge.{kind}_repair.review", f"{kind}_repair_candidate", f"{kind}_repair_review", f"contract.writing.simple_novel.{kind}_candidate", "structured_handoff", {"repair": True}))
        edges.append(edge(f"edge.{kind}_repair_review.commit", f"{kind}_repair_review", f"memory_commit_{kind}", f"contract.writing.simple_novel.{kind}_review", "canon_commit", {"repair": True, "dynamic_return": "repair_request.return_node_id"}))
    for review_node in ["world_review", "outline_review", "character_review", "chapter_plan_review", "chapter_review", "final_review", "chapter_progress_router"]:
        edges.append(edge(f"edge.{review_node}.human", review_node, "human_review_handoff", "contract.writing.simple_novel.human_review_input", "human_handoff", {"verdict": "human_review_required"}))
        edges.append(edge(f"edge.{review_node}.fail", review_node, "fail_closed", "contract.writing.simple_novel.failure_input", "fail_closed", {"verdict": "fail_closed"}))
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
                "runtime_lane_hint": "system_memory" if role == "memory_system" else "coordination_task",
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
            "operation_policy": {
                "allowed_operations": ["op.model_response", "op.memory_read"],
                "blocked_operations": ["op.shell", "op.python_repl", "op.delegate_to_agent", "op.web_search"],
            },
        },
        "metadata": {"managed_by": MANAGED, "domain_id": DOMAIN_ID, "task_id": "task.writing.simple_novel." + node_id, "projection_id": projection, "source_flow_id": "flow.writing.simple_novel." + node_id, "package_template": TASK_FAMILY},
    }


def workflow(node):
    node_id, title, agent, projection, input_contract, output_contract, phase, seq, path, role = node
    prompts, repair_delta = parse_prompts()
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
        "prompt": prompt_for(projection, prompts, repair_delta) if projection else "系统记忆节点。只按 memory contract 读写索引，不进行创作、审核或裁决。",
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
        "default_runtime_lane": "system_memory" if role == "memory_system" else "full_interactive" if role == "human" else "coordination_task",
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
        "requested_topics": memory_read_policy(role)["topics"],
        "memory_priority": "high" if role in {"reviewer", "memory_steward", "memory_system"} else "normal",
        "writeback_policy": memory_write_policy(role)["mode"],
        "allow_long_term_memory": False,
        "memory_scope_hint": MEMORY_SCOPE,
        "metadata": {"managed_by": MANAGED, "conversation_memory": "suppressed_by_assembly" if role in {"creator", "reviewer", "router", "final_assembler"} else "restricted", "memory_contract": "memory_pack_required", "read_node": "memory_index_read", "write_node": "memory_index_write"},
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
        "notes": "写作组简易长篇小说节点投影绑定。" if projection else "系统记忆节点不需要 agent-facing projection。",
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
        "agent:writing_simple_creator": ("写作组创作者", "projection.writing.simple_novel.project_brief", "生成项目启动包、世界观、大纲、人物、分章、章节正文和专项修复候选。"),
        "agent:writing_simple_reviewer": ("写作组审核员", "projection.writing.simple_novel.world_reviewer", "审核每个候选并输出有限裁决、问题台账和下一步要求。"),
        "agent:writing_memory_steward": ("写作组记忆管家", "projection.writing.simple_novel.memory_steward", "在 pass 后写入 canon、章节 commit、交付包和归档索引。"),
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
    data["communication_protocols"].append({"protocol_id": PROTOCOL_ID, "title": "写作组简易长篇小说通信协议", "message_types": ["message/send", "task/status", "task/artifact", "task/review_feedback", "task/revision_request", "task/canon_update", "task/memory_read", "task/memory_write", "task/memory_lock"], "payload_contracts": [item["contract_id"] for item in contracts], "signal_rules": ["memory_pack_required_before_business_node", "candidate_ref_required_before_review", "pass_required_before_memory_commit", "canon_commit_requires_lock_and_receipt", "repair_returns_to_trigger_node", "final_assemble_uses_manifest_not_full_text"], "handoff_rules": ["structured_artifact_refs_only", "no_raw_agent_dialogue", "memory_pack_refs_only", "no_unapproved_memory_commit", "candidate_outputs_are_not_canon", "chapter_full_text_not_handed_as_global_context", "delivery_manifest_not_full_text_context"], "ack_policy": "explicit_ack", "timeout_policy": "fail_closed", "error_signal_policy": "raise_to_coordinator", "enabled": True, "metadata": {"managed_by": MANAGED, "task_family": TASK_FAMILY, "domain_id": DOMAIN_ID, "memory_node_required": True}, "authority": "task_system.task_communication_protocol"})
    save("storage/tasks/task_communication_protocols.json", data)

    nodes = [graph_node(node) for node in NODE_DEFS]
    graph_nodes = [node for node in nodes if node.get("work_posture") != "memory_system"]
    edges = build_edges()

    topology_nodes = [{"node_id": n["node_id"], "node_type": n["node_type"], "title": n["title"], "task_id": n.get("task_id", ""), "agent_id": n.get("agent_id", ""), "role": n.get("work_posture", ""), "work_posture": n.get("work_posture", ""), "projection_id": n.get("projection_id", ""), "phase_id": n.get("phase_id", ""), "sequence_index": n.get("sequence_index", 0), "execution_mode": n.get("execution_mode", "sync"), "dispatch_group": n.get("dispatch_group", ""), "artifact_target": n.get("artifact_target", ""), "output_path": n.get("output_path", ""), "artifact_policy": n.get("artifact_policy", {})} for n in graph_nodes]
    topology_edges = [{"edge_id": e["edge_id"], "source_node_id": e["source_node_id"], "target_node_id": e["target_node_id"], "mode": e["edge_type"], "payload_contract_id": e["payload_contract_id"]} for e in edges]
    data = load("storage/tasks/topology_templates.json")
    data["topology_templates"] = strip_items(data["topology_templates"], "template_id", exact=(TOPOLOGY_ID,))
    data["topology_templates"].append({"template_id": TOPOLOGY_ID, "title": "写作组简易长篇小说拓扑", "nodes": topology_nodes, "edges": topology_edges, "handoff_rules": ["memory_pack_required", "candidate_ref_before_review", "pass_before_commit", "manifest_not_full_text"], "join_policy": "explicit_join", "failure_policy": "fail_closed", "terminal_policy": "coordinator_terminal", "enabled": True, "metadata": {"managed_by": MANAGED, "task_family": TASK_FAMILY, "domain_id": DOMAIN_ID, "graph_id": GRAPH_ID}})
    save("storage/tasks/topology_templates.json", data)

    data = load("storage/tasks/task_graphs.json")
    data["task_graphs"] = strip_items(data["task_graphs"], "graph_id", exact=(GRAPH_ID,))
    data["task_graphs"].append({"graph_id": GRAPH_ID, "title": "写作组简易长篇小说任务图", "domain_id": DOMAIN_ID, "task_family": TASK_FAMILY, "graph_kind": "coordination", "entry_node_id": "project_brief", "output_node_id": "memory_finalize", "nodes": graph_nodes, "edges": edges, "graph_contract_id": "contract.writing.simple_novel.graph", "default_protocol_id": PROTOCOL_ID, "working_memory_policy_profile_id": "wmprofile.writing.simple_novel", "working_memory_policy": {"memory_scope": MEMORY_SCOPE, "memory_index_node": "memory.writing.simple_novel.project_state", "read_node": "memory_index_read", "write_node": "memory_index_write", "lock_node": "memory_index_lock", "release_node": "memory_index_release", "conversation_memory": "suppressed_for_creator_and_reviewer", "raw_full_text_global_context": "forbidden", "scheduler_binding": "resource_step_not_business_node"}, "runtime_policy": {"execution_mode": "coordinator_driven", "fail_default": "fail_closed", "memory_pack_required": True, "human_gate_mode": "auto_continue"}, "context_policy": {"handoff": "contract_payload_and_refs", "raw_dialogue_handoff": "forbidden", "long_text_policy": "artifact_ref_and_summary_only"}, "publish_state": "published", "enabled": True, "metadata": {"managed_by": MANAGED, "design_doc": DESIGN_DOC, "memory_closed_loop": True, "memory_nodes_bound_as_resource_steps": True, "old_graph_dependency": "none", "editor_publish_state": "published", "continuation_policy": {"human_gate_mode": "auto_continue"}}, "authority": "task_system.task_graph", "graph_nodes": [n["node_id"] for n in graph_nodes], "graph_edges": [e["edge_id"] for e in edges], "issues": [], "valid": True, "subtask_refs": ["task.writing.simple_novel." + node[0] for node in NODE_DEFS]})
    save("storage/tasks/task_graphs.json", data)

    print(f"configured {len(NODE_DEFS)} node tasks, {len(edges)} edges, {len(contracts)} contracts, {len(projection_cards())} projections")


if __name__ == "__main__":
    configure()
