from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.models.model_profile_models import AgentModelProfile, parse_agent_model_profile
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.registry.agent_registry import AgentRegistry
from task_system.contracts.contract_definition_models import AcceptanceRule, ArtifactRequirement, ContractField, ContractSpec
from task_system.registry.contract_registry import TaskContractRegistry
from task_system.registry.flow_registry import TaskFlowRegistry


MANAGED_BY = "codex_writing_modular_novel_graph_20260521_native"
DOMAIN_ID = "domain.writing.modular_novel"
TASK_FAMILY = "writing_modular_novel"
PROTOCOL_ID = "protocol.writing.modular_novel"
MODEL_PROFILE_REF = "llm.deepseek.long_output_65536"

MASTER_GRAPH_ID = "graph.writing.modular_novel.master"
DESIGN_GRAPH_ID = "graph.writing.modular_novel.design_init"
CHAPTER_GRAPH_ID = "graph.writing.modular_novel.chapter_cycle"
FINALIZE_GRAPH_ID = "graph.writing.modular_novel.finalize"

WORKER_AGENT_ID = "agent:writing_modular_worker"
CREATOR_AGENT_ID = "agent:writing_modular_creator"
REVIEWER_AGENT_ID = "agent:writing_modular_reviewer"
MEMORY_AGENT_ID = "agent:writing_modular_memory_steward"
MONITOR_AGENT_ID = "agent:writing_modular_runtime_monitor"
AGENT_GROUP_ID = "group.writing.modular_novel"

TARGET_VOLUMES = 5
CHAPTERS_PER_VOLUME = 100
CHAPTER_BATCH_SIZE = 10
CHAPTER_TARGET_WORDS = 2000
CHAPTER_MIN_WORDS = 1200
CHAPTER_MAX_WORDS = 2600
BATCH_TARGET_WORDS = CHAPTER_BATCH_SIZE * CHAPTER_TARGET_WORDS
BATCH_MIN_WORDS = CHAPTER_BATCH_SIZE * CHAPTER_MIN_WORDS
BATCH_MAX_WORDS = CHAPTER_BATCH_SIZE * CHAPTER_MAX_WORDS
VOLUME_TARGET_WORDS = CHAPTERS_PER_VOLUME * CHAPTER_TARGET_WORDS
VOLUME_MIN_WORDS = CHAPTERS_PER_VOLUME * CHAPTER_MIN_WORDS
VOLUME_MAX_WORDS = CHAPTERS_PER_VOLUME * CHAPTER_MAX_WORDS
TARGET_WORDS = TARGET_VOLUMES * VOLUME_TARGET_WORDS
CHAPTER_REQUESTED_COUNT = TARGET_VOLUMES * CHAPTERS_PER_VOLUME

ARTIFACT_ROOT = "output/novel_artifacts/modular_novel/runs"

REPOSITORY_NODES = (
    {
        "node_id": "memory.writing.baseline",
        "node_type": "memory_repository",
        "title": "基准记忆库",
        "repository_id": "writing_modular_baseline",
        "collections": (
            "world_bible",
            "world_element_cards",
            "character_baselines",
            "relationship_baselines",
            "outline_canon",
            "outline_thread_index",
            "frozen_facts",
            "forbidden_changes",
        ),
        "mutable": False,
        "write_owner_node_ids": ("memory_commit_world", "memory_commit_character", "baseline_memory_seed"),
        "readable_by": ("plot_design", "design_sync", "outline_design", "outline_review", "baseline_memory_seed", "volume_plan", "chapter_outline", "chapter_draft", "chapter_review", "volume_review", "final_assemble", "final_review"),
        "library_role": "read_only_canon_baseline",
    },
    {
        "node_id": "memory.writing.mutable",
        "node_type": "memory_repository",
        "title": "动态记忆库",
        "repository_id": "writing_modular_mutable",
        "collections": (
            "chapter_state_deltas",
            "volume_state_deltas",
            "extension_commits",
            "continuity_notes",
            "character_state_snapshots",
            "setting_expansion_cards",
            "outline_adjustments",
            "next_batch_requirements",
        ),
        "mutable": True,
        "write_owner_node_ids": ("memory_commit_chapter", "volume_commit", "extension_commit", "memory_finalize"),
        "readable_by": ("volume_plan", "chapter_outline", "chapter_draft", "chapter_review", "memory_commit_chapter", "volume_review", "volume_commit", "volume_postmortem", "world_outline_extension_proposal", "extension_review", "final_assemble", "final_review"),
        "library_role": "post_batch_and_post_volume_update_layer",
    },
    {
        "node_id": "memory.writing.manuscript",
        "node_type": "memory_repository",
        "title": "正文记忆库",
        "repository_id": "writing_modular_manuscript",
        "collections": (
            "approved_chapter_batches",
            "chapter_summaries",
            "manuscript_fact_index",
            "scene_continuity",
            "chapter_hooks",
            "prose_refs",
        ),
        "mutable": True,
        "write_owner_node_ids": ("memory_commit_chapter", "memory_finalize"),
        "readable_by": ("volume_plan", "chapter_outline", "chapter_draft", "chapter_review", "memory_commit_chapter", "volume_review", "volume_commit", "final_assemble", "final_review", "memory_finalize"),
        "library_role": "approved_manuscript_and_summary_layer",
    },
    {
        "node_id": "memory.writing.artifact_index",
        "node_type": "artifact_repository",
        "title": "产物索引库",
        "repository_id": "writing_modular_artifact_index",
        "collections": ("draft_refs", "review_refs", "commit_refs", "debug_refs"),
        "mutable": True,
        "write_owner_node_ids": ("*",),
        "readable_by": ("*"),
        "library_role": "artifact_ref_index",
    },
    {
        "node_id": "memory.writing.issue_ledger",
        "node_type": "issue_ledger",
        "title": "问题台账",
        "repository_id": "writing_modular_issue_ledger",
        "collections": ("review_issues", "continuity_issues", "runtime_issues"),
        "mutable": True,
        "write_owner_node_ids": ("world_review", "outline_review", "chapter_review", "volume_review", "final_review"),
        "readable_by": ("*"),
        "library_role": "risk_and_issue_ledger",
    },
)

COMMIT_WRITE_MODES = {"baseline_commit", "chapter_commit", "volume_commit", "dynamic_memory_commit", "finalize_commit"}
MUTABLE_COMMIT_WRITE_MODES = {"chapter_commit", "volume_commit", "dynamic_memory_commit", "finalize_commit"}
MANUSCRIPT_COMMIT_WRITE_MODES = {"chapter_commit", "finalize_commit"}

SOURCE_REVIEW_BY_COMMIT_NODE = {
    "memory_commit_world": "world_review",
    "memory_commit_character": "character_review",
    "baseline_memory_seed": "outline_review",
    "memory_commit_chapter": "chapter_review",
    "volume_commit": "volume_review",
    "extension_commit": "extension_review",
    "memory_finalize": "final_review",
}

SOURCE_CANDIDATE_BY_COMMIT_NODE = {
    "memory_commit_world": "world_design",
    "memory_commit_character": "character_design",
    "baseline_memory_seed": "outline_design",
    "memory_commit_chapter": "chapter_draft",
    "volume_commit": "memory_commit_chapter",
    "extension_commit": "world_outline_extension_proposal",
    "memory_finalize": "final_assemble",
}

OUTLINE_THREAD_DESIGN_NODE_IDS = {"outline_design", "outline_review", "baseline_memory_seed"}
OUTLINE_THREAD_INDEX_NODE_IDS = {
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
    "final_assemble",
    "final_review",
    "memory_finalize",
}


def _repository_collection(repo_id: str) -> str:
    if repo_id.endswith("baseline"):
        return "baseline"
    if repo_id.endswith("mutable"):
        return "mutable"
    if repo_id.endswith("manuscript"):
        return "manuscript"
    if repo_id.endswith("issue_ledger"):
        return "issues"
    if repo_id.endswith("artifact_index"):
        return "artifact_refs"
    return "default"


def _repository_label(repo_id: str) -> str:
    return {
        "memory.writing.baseline": "基准库",
        "memory.writing.mutable": "动态记忆库",
        "memory.writing.manuscript": "正文记忆库",
        "memory.writing.artifact_index": "产物索引库",
        "memory.writing.issue_ledger": "问题台账",
    }.get(repo_id, "记忆库")


def _chapter_loop_derived_fields() -> list[dict[str, Any]]:
    return [
        {"key": "volume_index_padded", "op": "format", "template": "{volume_index:03d}"},
        {"key": "volume_label", "op": "format", "template": "第{volume_index}卷"},
        {"key": "chapter_index_padded", "op": "format", "template": "{chapter_index:03d}"},
        {"key": "chapter_label", "op": "format", "template": "第{chapter_index}章"},
        {"key": "chapter_file_prefix", "op": "format", "template": "chapter_{chapter_index:03d}"},
        {"key": "batch_start_index", "op": "copy", "from_key": "chapter_index"},
        {"key": "batch_end_index", "op": "add", "from_key": "chapter_index", "value_key": "chapters_per_round", "value": CHAPTER_BATCH_SIZE - 1, "offset": -1},
        {"key": "batch_index", "op": "ordinal_group", "from_key": "chapter_index", "size_key": "chapters_per_round", "size": CHAPTER_BATCH_SIZE},
        {"key": "batch_index_padded", "op": "format", "template": "{batch_index:03d}"},
        {"key": "batch_start_index_padded", "op": "format", "template": "{batch_start_index:03d}"},
        {"key": "batch_end_index_padded", "op": "format", "template": "{batch_end_index:03d}"},
        {"key": "batch_chapter_range", "op": "format", "template": "{batch_start_index:03d}-{batch_end_index:03d}"},
        {"key": "batch_label", "op": "format", "template": "第{batch_start_index}章至第{batch_end_index}章"},
        {"key": "batch_chapter_numbers", "op": "range", "start_key": "batch_start_index", "end_key": "batch_end_index"},
        {"key": "batch_chapter_list", "op": "join", "from_key": "batch_chapter_numbers", "prefix": "第", "suffix": "章", "separator": "、"},
        {"key": "batch_target_words", "op": "multiply", "from_key": "chapter_target_words", "value_key": "chapters_per_round", "value": CHAPTER_BATCH_SIZE},
        {"key": "runtime_loop_summary", "op": "format", "template": "当前卷：{volume_label}；当前批次：{batch_label}；本批允许范围：{batch_chapter_list}；本次目标 {target_volumes} 卷；全书累计约 {current_words}/{target_words} 字；本卷累计约 {volume_current_words}/{volume_target_words} 字。"},
    ]


def _chapter_progress_route_policy_static() -> dict[str, Any]:
    return {
        "mode": "metric_target",
        "loop_scope_id": "loop.chapter_batch",
        "continue_stage_id": "chapter_outline",
        "exit_stage_id": "volume_review",
        "metric_key": "chapter_words",
        "diagnostic_metric_key": "chapter_words",
        "fallback_increment_key": "batch_target_words",
        "default_increment": BATCH_TARGET_WORDS,
        "current_key": "volume_current_words",
        "target_key": "volume_target_words",
        "last_metric_key": "last_batch_words",
        "secondary_counters": [{"current_key": "current_words", "target_key": "target_words"}],
        "counter_updates": [{"key": "chapter_index", "mode": "increment", "step_key": "chapters_per_round", "step": CHAPTER_BATCH_SIZE}],
        "derived_fields": _chapter_loop_derived_fields(),
    }


def _next_volume_route_policy_static() -> dict[str, Any]:
    return {
        "mode": "metric_target",
        "loop_scope_id": "loop.volume",
        "continue_stage_id": "volume_plan",
        "exit_stage_id": "__graph_module_complete__",
        "metric_key": "volume_router_metric",
        "default_increment": 1,
        "current_key": "completed_volumes",
        "target_key": "target_volumes",
        "counter_updates": [
            {"key": "volume_index", "mode": "increment", "step": 1},
            {"key": "volume_current_words", "mode": "reset", "value": 0},
        ],
        "derived_fields": _chapter_loop_derived_fields(),
    }


def _length_budget_contract_static(scope: str, target_units: int, min_units: int, max_units: int, batch_unit_count: int) -> dict[str, Any]:
    return _length_budget_contract(scope, target_units, min_units, max_units, batch_unit_count, f"node.contract_bindings.runtime.length_budget.{scope}")


def _length_budget_contract(scope: str, target_units: int, min_units: int, max_units: int, batch_unit_count: int, source: str) -> dict[str, Any]:
    return {
        "enabled": True,
        "budget_scope": scope,
        "measurement_mode": "text_units",
        "unit_kind": "chapter" if scope == "batch" else "volume",
        "unit_label_zh": "章节" if scope == "batch" else "卷",
        "target_units": target_units,
        "min_units": min_units,
        "max_units": max_units,
        "batch_unit_count": batch_unit_count,
        "metric_section_keys": ["章节正文候选"],
        "metric_stop_section_keys": ["承接说明", "本章目标完成说明", "人物与冲突推进", "商业钩子与爽点兑现", "后续伏笔或待承接事项", "自检风险", "公开摘要"],
        "repair_policy": {"mode": "expand_or_split", "max_repair_rounds": 3, "repair_instruction": "扩写正文场景、行动、选择、冲突、代价和人物反应；不得用摘要、提纲或自检补量。"},
        "acceptance_policy": {"require_continuity": True, "require_formal_headings": True, "require_artifact_ref": True, "metric_tool_operation": "op.text_metric"},
        "source": source,
    }


def _chapter_batch_quality_retry_policy() -> dict[str, Any]:
    return {
        "acceptance_policies": ["sectioned_text_batch_quality"],
        "unit_start_key": "batch_start_index",
        "unit_end_key": "batch_end_index",
        "unit_count_key": "chapters_per_round",
        "target_metric_key": "batch_target_words",
        "unit_target_metric_key": "chapter_target_words",
        "minimum_metric_ratio": 0.55,
        "minimum_metric_per_unit": CHAPTER_MIN_WORDS,
        "unit_label": "章",
        "unit_summary_template": "第{index}章",
        "metric_summary_label": "字",
        "required_heading_patterns": [r"第\s*(?P<index>[0-9一二三四五六七八九十百零〇两]+)\s*[章节回]"],
        "heading_match_scope": "formal_heading",
        "metric_section_keys": ["章节正文候选"],
        "metric_stop_section_keys": [
            "承接说明",
            "本章目标完成说明",
            "人物与冲突推进",
            "商业钩子与爽点兑现",
            "后续伏笔或待承接事项",
            "自检风险",
            "公开摘要",
        ],
        "forbid_unexpected_unit_indexes": True,
        "forbid_unexpected_unit_ranges": True,
        "range_declaration_keywords": [
            "当前批次",
            "当前章批次",
            "本批允许范围",
            "本批允许章号",
            "允许范围",
            "批次目标",
            "批次摘要",
            "当前批次细纲",
            "当前批次正文",
        ],
        "broad_range_keywords": ["本批", "本轮"],
        "range_mention_patterns": [
            r"第\s*(?P<start>[0-9一二三四五六七八九十百零〇两]+)\s*章?\s*(?:至|到|[-—~～])\s*第?\s*(?P<end>[0-9一二三四五六七八九十百零〇两]+)\s*章"
        ],
        "future_range_keywords": [
            "下一批",
            "下批",
            "下一轮",
            "下轮",
            "后续批次",
            "后续章节",
            "后续章",
            "后续承接",
            "承接点",
            "下一阶段",
        ],
    }


@dataclass(frozen=True, slots=True)
class NodeSpec:
    node_id: str
    title: str
    node_type: str
    role: str
    prompt: str
    output_contract_id: str
    input_contract_id: str = "contract.user_request.basic"
    agent_id: str = ""
    projection_id: str = ""
    phase_id: str = ""
    sequence_index: int = 0
    required_inputs: tuple[str, ...] = ()
    memory_topics: tuple[str, ...] = ()
    required_memory_topics: tuple[str, ...] = ()
    forbidden_topics: tuple[str, ...] = ("raw_conversation_history",)
    readable_repositories: tuple[str, ...] = ()
    write_mode: str = "candidate_archive_only"
    artifact_paths: tuple[str, ...] = ()
    artifact_context_keys: tuple[str, ...] = ("上游交接包",)
    artifact_context_max_chars: int = 30000
    review_revision_stage_id: str = ""
    loop_scope_id: str = ""
    title_template: str = ""
    loop_route_policy: dict[str, Any] = field(default_factory=dict)
    length_budget: dict[str, Any] = field(default_factory=dict)
    extra_runtime: dict[str, Any] = field(default_factory=dict)


def _role_prompt(*sections: str) -> str:
    return "\n\n".join(section.strip() for section in sections if str(section or "").strip())


DESIGN_NODES: tuple[NodeSpec, ...] = (
    NodeSpec(
        node_id="project_brief",
        title="项目启动包",
        node_type="agent_role",
        role="creator",
        projection_id="projection.writing.modular_novel.project_brief",
        phase_id="phase.modular.design_init.start",
        sequence_index=10,
        output_contract_id="contract.writing.modular_novel.project_brief",
        memory_topics=("user_goal", "delivery_requirements", "source_refs"),
        forbidden_topics=("raw_conversation_history", "baseline_memory", "mutable_memory"),
        artifact_context_keys=(),
        artifact_paths=("project_brief.md",),
        prompt=_role_prompt(
            "你是一名中文商业网文项目启动整理员。你只负责把用户已经给出的目标、题材、世界背景、核心人物方向、字数规模、章节规模、风格偏好和硬性要求整理成可交接的项目启动包。",
            "你需要区分用户硬设定、可推断倾向、缺口问题和后续节点必须继续设计的开放项。任何没有被用户明确给出的世界观、角色关系、剧情转折、结局安排，都只能标为待设计问题，不能伪装成既定事实。",
            "你的输出要让后续节点按头部中文商业网文的共性标准直接开工：项目定位、读者预期、核心卖点、题材约束、不可违背设定、创作禁区、交付规模、待确认问题必须清楚。你不能替后续节点扩写世界观正文，也不能提前创作剧情。",
        ),
    ),
    NodeSpec(
        node_id="world_design",
        title="世界观设定候选",
        node_type="agent_role",
        role="creator",
        projection_id="projection.writing.modular_novel.world_designer",
        phase_id="phase.modular.design_init.world",
        sequence_index=20,
        output_contract_id="contract.writing.modular_novel.world_candidate",
        required_inputs=("上游交接包",),
        memory_topics=("project_brief", "user_goal", "source_refs"),
        artifact_paths=("world/world_candidate_round_{round_index:03d}.md",),
        prompt=_role_prompt(
            "你是一名名家级中文商业网文世界架构师。你只负责基于项目启动包构建一个能支撑百万字连载、升级爽点、长期追读、角色成长和分卷扩展的候选世界设定 Bible。",
            "你的专业目标是对标头部中文商业网文的共性能力：强辨识度、强代入、强升级产能、强情绪回报和强长线悬念。你可以学习名家级作品的结构能力和商业判断，但不能复刻某个具体作者的可识别句式、口癖、人物模板或专属设定。",
            "你要先定义作品的世界卖点和核心爽感：读者为什么愿意进入这个世界，核心人物通过什么路径获得阶段成长，世界秩序为什么压迫、诱惑或考验人物，长期矛盾为什么会持续升级。世界观不是名词表，而是一套能不断制造目标、阻碍、奖励、代价和反转的商业叙事引擎。",
            "你必须完整设计空间与场域结构：核心场域、边界区域、未知区域、通行或访问方式、资源/信息/机会产地、群体边界、风险梯度和可逐步解锁的层级。空间结构要服务剧情推进、成长路径、利益冲突和读者期待。",
            "你必须完整设计历史与秩序：时间尺度、关键时期、制度变迁、群体兴衰、核心源流、重大转折、被隐藏或误读的历史、公开叙事与隐秘真相的差异，以及这些历史如何转化为当前冲突、关键资源来源、恩怨链和长线悬念。",
            "你必须完整设计社会与交换体系：治理结构、群体形态、利益联盟、公共秩序、等价交换体系、交易规则、资源等级、分配机制、身份分层、传承机制、信息流通和日常运行逻辑。",
            "你必须完整设计成长与资源体系：成长路径、阶段门槛、突破条件、资源消耗、工具来源、路线分化、克制关系、失败代价、上限边界和稀缺资源的产出逻辑。成长体系要能支撑持续升级，同时避免无代价膨胀。",
            "你必须完整设计题材适配的原创机制：核心规则、关键制度、特殊流程、特殊场域、关键资源、记忆点、禁忌与代价、世界核心装置。原创设计要能产生记忆点、爽点、危机和伏笔，不只是装饰。",
            "你的设计必须给出可持续产能：每个重要场域可展开的冲突，每类资源可制造的争夺，每套制度可压迫或奖赏的人群，每个秘密可牵引的中后期揭示，每个机制可承载的副线、奖励、代价和反转。",
            "你必须把本项目写成只属于项目自身的商业世界，而不是套默认类型模板。没有项目硬设定或上游已审核依据时，禁止主动使用任何题材默认资产、通用组织模板、通用资源名词、通用探索场域、通用师承关系或通用奖励道具作为世界基础。若确实需要类似叙事功能，必须改造成由本项目历史和机制自然生成的专属制度、称谓、资源与场域，并明确其来源、权力归属、运行规则、成本、限制和剧情作用。",
            "你在设计社会组织、交换媒介、成长资源、特殊器物、教育传承和探索场域时，必须先说明它们为什么会在项目硬设定规定的时代、地域、权力结构、群体关系和历史后果中出现。不能只给一个网文常用名词，也不能把没有机制来源的套路资产写成冻结事实。",
            "你必须保留用户硬设定，并把新增设定标为候选设计。所有具体设定都必须来自用户题材、项目启动包和已建立世界逻辑；没有依据时，不得主动加入题材专属元素、套路资产或类型预设。你不能提前写具体章节剧情，不能把尚未审核的剧情细节写成世界事实。你的输出必须给后续人设、剧情、细纲节点留下可引用的规则、边界、场域资源、群体目标、成长钩子和商业化追读钩子。",
        ),
    ),
    NodeSpec(
        node_id="world_review",
        title="世界观审核",
        node_type="review_gate",
        role="reviewer",
        projection_id="projection.writing.modular_novel.world_reviewer",
        phase_id="phase.modular.design_init.world",
        sequence_index=30,
        output_contract_id="contract.writing.modular_novel.world_review",
        required_inputs=("上游交接包",),
        memory_topics=("project_brief", "world_candidate_ref"),
        artifact_paths=("world/world_review_round_{round_index:03d}.md",),
        review_revision_stage_id="world_design",
        write_mode="review_and_issue_ledger",
        prompt=_role_prompt(
            "你是一名名家级中文商业网文世界观总审。你只负责审核世界观候选是否达到头部连载作品的专业门槛，并判断它是否允许进入基准记忆提交。",
            "你需要逐项检查世界设定 Bible：世界卖点是否明确，空间分区是否能支撑探索与升级，历史秩序是否能制造秘密和恩怨链，群体格局是否有竞争目标，交换与资源体系是否能驱动交易和争夺，成长体系是否有清晰阶段、代价和上限，题材适配的原创机制是否有记忆点。",
            "你还需要检查商业化承载：核心人物成长路线是否有连续奖励，读者期待是否能分阶段释放，世界规则是否能自然制造冲突，关键设定是否便于后续人设、剧情、细纲和章节正文引用，是否存在只有概念没有机制、只有背景没有矛盾、只有阶段没有代价的问题。",
            "你的审核标准要像资深网文责编：不满足强辨识度、升级产能、情绪回报、持续冲突、章节可写性和读者记忆点的设计，不能因为完整而通过；只有能支撑高质量商业连载的世界观才允许进入下一阶段。",
            "你必须专门检查套路资产污染：候选世界观是否把题材默认资产、通用组织模板、通用资源名词、通用探索场域、通用师承关系或通用奖励道具当成默认事实。若这些功能没有被改造成项目专属的制度、称谓、资源、场域与机制来源，必须判为返修；不能把常见网文设定当作通过理由。",
            "你必须指出具体问题、风险等级、影响范围和返修建议，并检查候选世界观是否把用户未要求的题材专属元素强行写成事实。裁决只能是通过、带备注通过、返修或拒绝；返修时必须明确回到世界观设计节点的哪些部分。只要报告中存在阻塞问题、必须修改项、硬设定冲突、机制来源不明或冻结前必须处理的问题，裁决必须是返修或拒绝，不能写成通过或带备注通过。带备注通过只能用于不影响冻结和后续写作的轻微建议。你不负责替设计节点扩写世界观，也不能把自己的补充设定写成已通过事实。",
        ),
    ),
    NodeSpec(
        node_id="memory_commit_world",
        title="世界观提交",
        node_type="memory_commit",
        role="memory_steward",
        agent_id=MEMORY_AGENT_ID,
        projection_id="projection.writing.modular_novel.memory_steward",
        phase_id="phase.modular.design_init.world",
        sequence_index=40,
        output_contract_id="contract.writing.modular_novel.world_commit",
        required_inputs=("上游交接包",),
        memory_topics=("world_review", "world_candidate_ref", "project_brief"),
        artifact_paths=("memory/world/world_commit_round_{round_index:03d}.md",),
        write_mode="baseline_commit",
        prompt=_role_prompt(
            "你是一名世界观基准库管理员。你只负责把已经通过审核的世界观候选固化为后续节点可长期引用的世界观基准记录。",
            "你需要保留完整的商业网文世界设定 Bible：世界卖点、空间场域、历史秩序、权力结构、群体关系、交换体系、职业阶层、资源产出、成长体系、题材规则、群体生态、特殊场域、原创机制、升级路径、长期悬念和创作边界。摘要只能作为索引，不能替代正式设定内容。",
            "你需要把名家级质量要求一起固化：核心卖点、读者情绪回报、升级产能、可展开区域、可持续冲突、关键记忆点和禁止降级的创作边界必须可追踪。",
            "你必须把世界观全文的可引用事实提交清楚，不能只提交“已冻结哪些维度”的目录式声明。若候选中仍存在未专属化的套路资产、机制来源不明的社会组织或资源名词，即使审核报告误写通过，你也必须拒绝提交并要求回到世界观设计节点返修。",
            "你只能提交审核明确通过或带备注通过且没有阻塞问题、必须修改项、硬设定冲突、机制来源不明的内容。候选分歧、未审补充、过程讨论和你自己的推测不能进入冻结事实；如果审核报告虽然写了通过或带备注通过，但正文同时出现阻塞问题、必须修改、冻结前必须处理等要求，你必须拒绝提交并输出提交失败说明，要求回到世界观设计节点返修，不能替设计节点修补后冻结。",
        ),
    ),
    NodeSpec(
        node_id="character_design",
        title="人设与关系设计",
        node_type="agent_role",
        role="creator",
        projection_id="projection.writing.modular_novel.character_designer",
        phase_id="phase.modular.design_init.design",
        sequence_index=50,
        output_contract_id="contract.writing.modular_novel.character_design",
        required_inputs=("上游交接包",),
        memory_topics=("project_brief", "world_commit_ref", "approved_world_spine"),
        required_memory_topics=("world_commit_ref",),
        readable_repositories=("memory.writing.baseline",),
        artifact_context_keys=("上游交接包", "基准库"),
        artifact_paths=("design/character_design_round_{round_index:03d}.md",),
        prompt=_role_prompt(
            "你是一名名家级中文商业网文人设与关系设计师。你只负责在已提交世界观边界内设计核心视角人物、关键关系人物、对抗角色、合作角色、引导或制约角色、群体关系和角色动机网络。",
            "你要让角色从世界规则中生长出来：身份、欲望、能力、创伤、资源、立场、误解、利益冲突和成长压力都要能回到世界观基准事实。角色关系要能产生长期推进力，并服务升级爽点、身份反差、群体碰撞、情绪价值和追读期待。",
            "你的角色设计要对标头部作品的共性标准：核心视角人物有清晰欲望和独特生存逻辑，关键关系人物有可记忆的利益位置和行为方式，对抗角色有压迫感和合理目标，关系网能反复制造误会、合作、背叛、亏欠、竞争和情绪回报。",
            "你不得把未冻结的通用类型资产继续带入角色设计。角色的引导者、组织、资源、敌对者和身份关系必须来自已提交世界观的专属制度与机制；如果世界观只给了功能方向而未冻结具体称谓，你只能写方向性接口，不能默认写通用组织、通用资源、通用道具或通用师承称谓。",
            "你必须读取项目启动包和世界观提交内容，不得改写世界观冻结事实。你的输出仍是人设候选，不是最终基准库；未审核的新角色设定必须标明候选性质。",
        ),
    ),
    NodeSpec(
        node_id="character_review",
        title="人设与关系审核",
        node_type="review_gate",
        role="reviewer",
        projection_id="projection.writing.modular_novel.character_reviewer",
        phase_id="phase.modular.design_init.design",
        sequence_index=55,
        output_contract_id="contract.writing.modular_novel.character_review",
        required_inputs=("上游交接包",),
        memory_topics=("world_commit_ref", "character_design_ref", "project_brief"),
        required_memory_topics=("world_commit_ref", "character_design_ref"),
        readable_repositories=("memory.writing.baseline",),
        artifact_context_keys=("上游交接包", "基准库"),
        artifact_paths=("design/character_review_round_{round_index:03d}.md",),
        review_revision_stage_id="character_design",
        write_mode="review_and_issue_ledger",
        prompt=_role_prompt(
            "你是一名名家级中文商业网文人设审核员。你只负责审核角色与关系设计是否足够专业、可写、可信，能否进入后续剧情与全书细纲阶段。",
            "你需要检查核心视角人物、关键关系人物、对抗角色、合作角色、守护者、盟友和群体关系是否都从已冻结世界观中长出来，是否存在身份空泛、动机虚弱、关系功能化、角色之间缺少压力链的问题。",
            "你要以头部商业网文标准裁决：主角欲望是否明确，角色弧线是否能持续推进，关系网络是否能制造误会、合作、冲突、亏欠、反转和情绪回报，角色设定是否会污染世界边界或偷塞未冻结类型模板。",
            "你不能替设计师补写角色正文，也不能把自己的补充设定写成事实。裁决只能是通过、带备注通过、返修或拒绝；未通过时必须明确指出返修范围和影响到的下游节点。只要报告中存在阻塞问题、必须修改项、硬设定冲突、角色动机断裂、商业承载不足或进入剧情前必须处理的问题，裁决必须是返修或拒绝，不能写成通过或带备注通过。带备注通过只能用于不影响角色冻结和后续剧情设计的轻微建议。",
        ),
    ),
    NodeSpec(
        node_id="plot_design",
        title="剧情与伏笔设计",
        node_type="agent_role",
        role="creator",
        projection_id="projection.writing.modular_novel.plot_designer",
        phase_id="phase.modular.design_init.design",
        sequence_index=50,
        output_contract_id="contract.writing.modular_novel.plot_design",
        required_inputs=("上游交接包",),
        memory_topics=("project_brief", "world_commit_ref", "approved_world_spine"),
        required_memory_topics=("world_commit_ref",),
        readable_repositories=("memory.writing.baseline",),
        artifact_context_keys=("上游交接包", "基准库"),
        artifact_paths=("design/plot_design_round_{round_index:03d}.md",),
        prompt=_role_prompt(
            "你是一名名家级中文商业网文剧情与伏笔设计师。你只负责根据已提交世界观设计主线推进、阶段冲突、对抗压力、秘密揭示节奏、伏笔链和长期悬念，产出可与人设候选对齐的剧情候选。",
            "你要把剧情建立在世界机制上：每个阶段冲突都应来自规则、资源、场域、群体边界、价值秩序、成长体系或时代压力。主线需要有连续升级、阶段奖励、危机递进、身份变化、场域展开和读者期待管理。伏笔必须可追踪，包含埋设位置、误导方式、阶段性回收、最终兑现和失败风险。",
            "你的剧情设计要追求头部网文的节奏能力：小目标不断兑现，大目标持续抬高，危机与奖励交替出现，对抗压力推动核心人物选择，秘密揭示带来新场域、新身份、新关系或新规则。",
            "你不得用默认网文资产补剧情空洞。所有成长入口、交易奖励、组织压迫、探索场域、引导关系和关键物件都必须来自已提交世界观中的专属机制；未冻结的内容只能作为候选接口和待审伏笔，不能写成剧情事实。",
            "你不得改写世界观冻结事实，也不得预设角色候选已经通过。你需要为后续对齐节点留下清晰接口：哪些剧情压力需要角色欲望承接，哪些伏笔需要角色关系触发，哪些阶段奖励需要人设弧线支撑。你的输出是剧情候选结构，不是章节正文，也不是最终大纲。",
        ),
    ),
    NodeSpec(
        node_id="design_sync",
        title="创作架构对齐",
        node_type="agent_role",
        role="reviewer",
        projection_id="projection.writing.modular_novel.design_sync",
        phase_id="phase.modular.design_init.design",
        sequence_index=70,
        output_contract_id="contract.writing.modular_novel.design_alignment",
        required_inputs=("上游交接包",),
        memory_topics=("world_commit_ref", "character_design_ref", "character_review_ref", "plot_design_ref", "conflict_ledger"),
        required_memory_topics=("world_commit_ref", "character_design_ref", "character_review_ref", "plot_design_ref"),
        readable_repositories=("memory.writing.baseline",),
        artifact_context_keys=("上游交接包", "基准库"),
        artifact_paths=("design/design_alignment_round_{round_index:03d}.md",),
        write_mode="review_and_issue_ledger",
        prompt=_role_prompt(
            "你是一名名家级商业网文创作架构对齐审核员。你只负责把已提交世界观、人设候选与剧情候选汇合成同一套可执行创作架构，并裁决它们是否互相支撑，是否存在事实冲突、动机断裂、世界规则失效或长篇承载不足。",
            "你需要把冲突分成必须返修、可带备注接受和后续大纲需要注意三类，并说明应由哪个上游节点处理。对齐包要给大纲设计师明确可用的事实、候选、风险和取舍建议。",
            "你的对齐标准不只看逻辑通顺，还要看商业强度：世界卖点是否进入角色命运，角色欲望是否推动剧情，剧情奖励是否回扣成长和资源体系，伏笔是否能反复制造读者期待。",
            "你必须检查行为污染是否已经从世界观扩散到角色或剧情：通用类型资产、默认修仙称谓、无来源资源、无机制道具、无审核身份关系，一旦影响后续大纲，必须要求回到源头节点返修，而不是在对齐包里自行补丁。",
            "你不能代替大纲设计师写全书大纲，不能把自己的新设定直接并入基准事实。你的对齐结果必须明确哪些人设切片允许进入角色基准提交，哪些剧情接口允许进入全书细纲，哪些内容必须返修或丢弃。",
        ),
    ),
    NodeSpec(
        node_id="memory_commit_character",
        title="人设与关系提交",
        node_type="memory_commit",
        role="memory_steward",
        agent_id=MEMORY_AGENT_ID,
        projection_id="projection.writing.modular_novel.memory_steward",
        phase_id="phase.modular.design_init.design",
        sequence_index=75,
        output_contract_id="contract.writing.modular_novel.character_commit",
        required_inputs=("上游交接包",),
        memory_topics=("project_brief", "world_commit_ref", "character_design_ref", "character_review_ref", "design_sync_ref"),
        required_memory_topics=("world_commit_ref", "character_design_ref", "character_review_ref", "design_sync_ref"),
        readable_repositories=("memory.writing.baseline",),
        artifact_context_keys=("上游交接包", "基准库"),
        artifact_paths=("memory/character/character_commit_round_{round_index:03d}.md",),
        write_mode="baseline_commit",
        prompt=_role_prompt(
            "你是一名人设与关系基准库管理员。你只负责把人设审核通过、并在创作架构对齐中被明确允许进入基准库的人物设定、关系网络、动机网络、对抗关系、合作关系、情绪关系和角色边界固化为后续剧情与章节写作可长期引用的角色基准记录。",
            "你必须保留角色可写性的核心信息：身份来源、欲望链、能力边界、行动逻辑、关系压力、阶段弧线、对抗功能、情绪回报、商业爽点承载、剧情接口和禁止改写项。摘要只能作为索引，不能替代正式角色基准内容。",
            "你只能提交人设审核明确通过或带备注通过、且创作架构对齐明确允许提交的内容。候选分歧、未审补充、对齐节点判定为风险或返修的切片、过程讨论和你自己的推测不能进入冻结事实；如果审核或对齐报告同时出现阻塞问题、必须修改、进入剧情前必须处理等要求，你必须拒绝提交并输出提交失败说明，不能替设计节点修补后冻结。",
        ),
    ),
    NodeSpec(
        node_id="outline_design",
        title="全书细纲设计",
        node_type="agent_role",
        role="creator",
        projection_id="projection.writing.modular_novel.outline_designer",
        phase_id="phase.modular.design_init.core",
        sequence_index=80,
        output_contract_id="contract.writing.modular_novel.outline_design",
        required_inputs=("上游交接包",),
        memory_topics=("world_commit_ref", "character_commit_ref", "plot_design_ref", "design_sync_ref", "project_brief"),
        required_memory_topics=("world_commit_ref", "character_commit_ref", "plot_design_ref", "design_sync_ref"),
        readable_repositories=("memory.writing.baseline",),
        artifact_context_keys=("上游交接包", "基准库"),
        artifact_paths=("outline/outline_design_round_{round_index:03d}.md",),
        prompt=_role_prompt(
            "你是一名名家级中文商业网文全书细纲设计师。你只负责把已提交世界观、已提交人设、剧情候选和对齐包汇总成可执行的长篇细纲。",
            "你需要规划分卷目标、阶段矛盾、角色成长节点、场域展开、资源争夺、群体关系变化、伏笔布设与回收、信息揭示节奏、爽点兑现节奏、每卷的开局压力和收束结果。细纲必须让后续分卷规划和章节批次细纲能连续执行。",
            "你的细纲要具备头部连载作品的产能：每卷有明确钩子和阶段高潮，每个大段落有读者期待、冲突推进、奖励兑现和新问题抬升；不能只有事件顺序，必须给出情绪曲线和追读设计。",
            "你必须把伏笔、悬念、关系推进和回收窗口写成大纲权威内容。每条长线都要有来源、埋设窗口、误导或遮蔽方式、推进节点、回收窗口、预期读者效果和失效风险。你不能另起一个独立剧情事实源，也不能让后续章节靠临场发挥补主线。",
            "你不能从零另造设定，不能绕开对齐包中的冲突裁决。若必须补足细纲所需的连接设定，只能标为待审候选并说明依赖来源。",
        ),
    ),
    NodeSpec(
        node_id="outline_review",
        title="细纲审核",
        node_type="review_gate",
        role="reviewer",
        projection_id="projection.writing.modular_novel.outline_reviewer",
        phase_id="phase.modular.design_init.core",
        sequence_index=90,
        output_contract_id="contract.writing.modular_novel.outline_review",
        required_inputs=("上游交接包",),
        memory_topics=("world_commit_ref", "character_commit_ref", "plot_design_ref", "design_sync_ref", "outline_design_ref"),
        artifact_paths=("outline/outline_review_round_{round_index:03d}.md",),
        review_revision_stage_id="outline_design",
        write_mode="review_and_issue_ledger",
        prompt=_role_prompt(
            "你是一名名家级中文商业网文全书细纲审核员。你只负责判断细纲是否能支撑百万字、五卷结构、章节连续创作、角色成长和伏笔闭环。",
            "你需要检查细纲是否忠于世界观和人设边界，是否每卷都有明确目标和变化，是否存在中段空转、伏笔无回收、角色动机失真、世界规则被剧情便利破坏等问题。",
            "你还要以资深责编标准判断商业质量：每卷是否有留存点，每阶段是否有足够冲突和奖励，核心人物成长是否有情绪回报，场域与群体关系是否不断扩展，追读钩子是否能接住下一阶段。",
            "你必须给出通过、带备注通过、返修或拒绝裁决；未通过时必须指明返修范围、影响节点和最低修复标准。你不能替设计师重写大纲正文。",
        ),
    ),
    NodeSpec(
        node_id="baseline_memory_seed",
        title="基准库初始化",
        node_type="memory_commit",
        role="memory_steward",
        agent_id=MEMORY_AGENT_ID,
        projection_id="projection.writing.modular_novel.baseline_memory_steward",
        phase_id="phase.modular.design_init.core",
        sequence_index=100,
        output_contract_id="contract.writing.modular_novel.baseline_commit",
        required_inputs=("上游交接包",),
        memory_topics=("project_brief", "world_commit_ref", "outline_review_ref", "outline_design_ref", "character_commit_ref", "plot_design_ref", "design_sync_ref"),
        artifact_paths=("memory/baseline/baseline_commit_round_{round_index:03d}.md",),
        write_mode="baseline_commit",
        prompt=_role_prompt(
            "你是一名长篇项目基准库初始化管理员。你只负责固化已经通过审核的世界观、人设、关系、剧情结构、细纲、冻结事实和后续创作边界。",
            "你需要把可长期引用的内容整理成稳定基准：事实区、角色区、世界规则区、剧情结构区、伏笔台账区、禁止改写区、动态候选区要边界清楚。",
            "候选分歧、未审核补充、过程讨论不能进入冻结区；动态调整事项只能进入动态记忆库的候选说明。你不能为了补齐基准库而自行发明事实。",
        ),
    ),
)

CHAPTER_NODES: tuple[NodeSpec, ...] = (
    NodeSpec(
        node_id="volume_plan",
        title="分卷计划",
        node_type="agent_role",
        role="creator",
        projection_id="projection.writing.modular_novel.volume_planner",
        phase_id="phase.modular.chapter_cycle.volume_plan",
        sequence_index=10,
        output_contract_id="contract.writing.modular_novel.volume_plan",
        memory_topics=("baseline_world", "baseline_outline", "baseline_characters", "previous_volume_commit", "dynamic_memory"),
        required_memory_topics=("baseline_world", "baseline_outline", "baseline_characters"),
        readable_repositories=("memory.writing.baseline", "memory.writing.mutable", "memory.writing.manuscript"),
        artifact_context_keys=("上游交接包", "基准库", "动态记忆库", "正文记忆库"),
        artifact_paths=("volume_{volume_index_padded}/volume_plan_round_{round_index:03d}.md",),
        loop_scope_id="loop.volume",
        title_template="{volume_label}分卷计划",
        prompt=_role_prompt(
            "你是一名名家级中文商业网文分卷规划师。你必须读取基准库的完整世界观、角色、关系和全书细纲，以及动态记忆库里上一卷后的调整。",
            "你的规划目标要对标头部中文商业网文的分卷工艺：一卷必须有清晰商业承诺、阶段升级、场域展开、群体压力、情绪回报、爆点兑现和下一卷牵引。你可以学习名家级作品在节奏设计、压力递进和爽点排布上的共性能力，但不能复刻任何具体作者的可识别套路、口癖、桥段模板或专属设定。",
            "你只负责当前卷的卷目标、主题焦点、核心矛盾、场域推进、资源争夺、阶段性胜负、人物变化、群体关系变化、伏笔安排、爽点节奏、章末牵引方向和十章批次边界。每个批次都要有明确推进作用，必须说明目标、阻碍、转折、兑现、余波和下一批压力，不能只是均分章节数量。",
            "你不能改写基准库冻结事实，不能提前写章节正文。若动态记忆与基准事实冲突，必须以基准库为准并标出冲突风险。",
        ),
    ),
    NodeSpec(
        node_id="chapter_outline",
        title="章节批次细纲",
        node_type="agent_role",
        role="creator",
        projection_id="projection.writing.modular_novel.chapter_outliner",
        phase_id="phase.modular.chapter_cycle.chapter_loop",
        sequence_index=20,
        output_contract_id="contract.writing.modular_novel.chapter_outline",
        required_inputs=("上游交接包",),
        memory_topics=("baseline_world", "baseline_outline", "baseline_characters", "volume_plan_ref", "previous_chapter_commit", "previous_chapter_summaries", "manuscript_fact_index", "continuity_notes"),
        required_memory_topics=("baseline_world", "baseline_outline", "baseline_characters"),
        readable_repositories=("memory.writing.baseline", "memory.writing.mutable", "memory.writing.manuscript"),
        artifact_context_keys=("上游交接包", "基准库", "动态记忆库", "正文记忆库"),
        artifact_paths=("volume_{volume_index_padded}/chapters/chapter_{batch_chapter_range}/outline_round_{round_index:03d}.md",),
        loop_scope_id="loop.chapter_batch",
        title_template="{batch_label}章节批次细纲",
        prompt=_role_prompt(
            "你是一名名家级中文商业网文章节批次细纲师。你只负责当前运行时批次允许的十章细纲。",
            "你的细纲必须是专业中文网文的小说细纲，不是分镜表、舞台说明、场景清单或人物走位表。你要写的是章内叙事推进：起势、推进、碰撞、反应、回收、余韵和章末钩子，而不是把一章拆成镜头化条目。",
            "你的细纲要达到头部连载作品的生产标准：每一章都有当章目标、人物欲望、冲突压力、情节转折、信息释放、情绪兑现、代价余波和追读牵引；每一批十章还要形成小高潮、小回收和新的压力源。你必须让读者能看见这一批章为什么要这样走，而不是只看到场景编号。",
            "你必须读取基准库、当前卷计划、上一批提交摘要和动态连续性记录，为写手给出逐章叙事目标、关键冲突、角色状态变化、资源或线索流转、伏笔布设与回收、信息揭示、爽点兑现、章末牵引、前后文承接点和禁改边界。表达方式要像资深中文网文编辑在交付可写的章纲，而不是像舞台剧导演在分配调度。",
            "每章细纲都要能直接指导名家级正文创作，并明确这一章的叙事重心、阅读情绪、商业爽点和追读钩子，但不能替写手写成完整正文，也不能把细纲写成报表。若发现上游计划不足以支撑当前批次，必须提出返修或风险说明，不能用临时设定硬补。",
        ),
    ),
    NodeSpec(
        node_id="chapter_draft",
        title="章节正文草稿",
        node_type="agent_role",
        role="creator",
        projection_id="projection.writing.modular_novel.chapter_writer",
        phase_id="phase.modular.chapter_cycle.chapter_loop",
        sequence_index=30,
        output_contract_id="contract.writing.modular_novel.chapter_draft",
        required_inputs=("上游交接包",),
        memory_topics=("baseline_world", "baseline_outline", "baseline_characters", "volume_plan_ref", "chapter_outline_ref", "previous_chapter_commit", "previous_chapter_summaries", "manuscript_fact_index", "active_outline_thread_refs", "due_outline_thread_refs"),
        required_memory_topics=("baseline_world", "baseline_outline", "baseline_characters", "chapter_outline_ref"),
        readable_repositories=("memory.writing.baseline", "memory.writing.mutable", "memory.writing.manuscript"),
        artifact_context_keys=("上游交接包", "基准库", "动态记忆库", "正文记忆库"),
        artifact_paths=("volume_{volume_index_padded}/chapters/chapter_{batch_chapter_range}/draft_round_{round_index:03d}.md",),
        loop_scope_id="loop.chapter_batch",
        title_template="{batch_label}章节正文草稿",
        length_budget=_length_budget_contract_static("batch", BATCH_TARGET_WORDS, BATCH_MIN_WORDS, BATCH_MAX_WORDS, CHAPTER_BATCH_SIZE),
        extra_runtime={
            "split_policy": {
                "mode": "static_batch",
                "batch_size": CHAPTER_BATCH_SIZE,
                "range_label_template": "chapter_{start}_{end}",
                "child_execution_mode": "sequential",
                "source": "contract_bindings.runtime.split_policy",
            },
            "batch_acceptance_policy": {
                "mode": "review_then_commit",
                "review_node_id": "chapter_review",
                "commit_visibility": "next_batch_after_acceptance",
            },
            "merge_policy": {
                "mode": "wait_all_committed",
                "result_order": "batch_sequence",
                "allow_partial": False,
                "final_review_required": True,
            },
        },
        prompt=_role_prompt(
            "你是一名名家级中文商业网文长篇写手。你只负责当前运行时批次允许的十章正文创作。",
            "你的正文目标是头部中文商业网文的连载质感：语言自然、有现场感和节奏弹性，叙述像有经验的人类作者在铺陈情势、递进冲突和安放伏笔；人物有清晰欲望、当下情绪、关系立场和选择压力，冲突通过行动、对话、试探、代价和后果推进。",
            "你可以学习名家级网文作品在节奏、场景张力、人物欲望、爽点兑现、情绪回报和章末牵引上的共性能力，但不能复刻任何具体作者的可识别文风、句式、口癖、桥段模板或专属设定。",
            "你的文风要走中文网文里古朴大气、又不失细腻的路子：叙述要娓娓道来，句子要有呼吸感，画面要清楚但不堆砌术语，语言要质朴而有余味，情绪要落在人物动作、神情、语气和环境反馈里。避免说明腔、流水账、AI腔和机械化列项，也避免过度华丽、过度抒情或舞台台词化。",
            "每个场景都要有目标、阻碍、转折和结果；设定信息要融入动作、对话、观察、利益争夺、人物判断、物件细节和环境反馈里释放。对白要承担关系变化、信息交换、压迫试探或情绪爆发，内心活动要服务选择和行动，不要写成旁白讲解。",
            "每章都要服务商业连载阅读体验：开局有承接和当章目标，中段有阻碍、反应和推进，结尾形成自然的章末牵引，留下新的压力、期待、反转、奖励或疑问。爽点要以铺垫、触发、出手、代价、反馈和余波形成兑现，来源可以是角色选择、实力变化、身份反差、资源获得、局势翻盘或认知揭示。",
            "你必须先完成写前取材判断，再进入正文。写前取材判断只允许简短列出本批采用的世界规则、人物当前状态、上一批承接、正文事实索引、活跃伏笔、到期伏笔、禁改边界和本批叙事目标；它必须来自基准库、动态记忆库、正文记忆库、当前卷计划和当前批次细纲，不能凭空补设定。",
            "写前取材判断之后必须输出完整小说正文，正文才是主体。正文要尊重世界规则、角色动机、前后连续性和批次目标；如果旧产物或提示中出现其他章号，以运行时批次边界为准。你不能跳写未授权章节，也不能为方便剧情临时改世界规则。若发现必须新增设定才能写通，只能在正文后标为待审扩展建议，不能当作已成立事实写进正文核心逻辑。",
        ),
    ),
    NodeSpec(
        node_id="chapter_review",
        title="章节批次审核",
        node_type="review_gate",
        role="reviewer",
        projection_id="projection.writing.modular_novel.chapter_reviewer",
        phase_id="phase.modular.chapter_cycle.chapter_loop",
        sequence_index=40,
        output_contract_id="contract.writing.modular_novel.chapter_review",
        required_inputs=("上游交接包",),
        memory_topics=("chapter_draft_ref", "chapter_outline_ref", "baseline_world", "baseline_outline", "continuity_notes", "previous_chapter_summaries", "manuscript_fact_index"),
        required_memory_topics=("chapter_draft_ref", "chapter_outline_ref"),
        readable_repositories=("memory.writing.baseline", "memory.writing.mutable", "memory.writing.manuscript"),
        artifact_context_keys=("上游交接包", "基准库", "动态记忆库", "正文记忆库"),
        artifact_paths=("volume_{volume_index_padded}/chapters/chapter_{batch_chapter_range}/review_round_{round_index:03d}.md",),
        review_revision_stage_id="chapter_draft",
        loop_scope_id="loop.chapter_batch",
        title_template="{batch_label}章节批次审核",
        length_budget=_length_budget_contract_static("batch", BATCH_TARGET_WORDS, BATCH_MIN_WORDS, BATCH_MAX_WORDS, CHAPTER_BATCH_SIZE),
        write_mode="review_and_issue_ledger",
        prompt=_role_prompt(
            "你是一名名家级中文商业网文章节总审。你只负责审核当前十章正文是否满足批次细纲、基准设定、连续性、正文量、角色推进、场景完成度、商业节奏和伏笔推进要求。",
            "你需要以头部连载作品的阅读体验做裁决：章节开局是否承接有力，当章目标是否明确，叙事是否像小说而不是说明书，场景是否有画面、行动、阻碍和转折，人物是否有欲望、压力、立场和选择，设定是否通过情境自然释放，爽点是否完成铺垫和兑现，章末是否形成下一章追读牵引。",
            "你还需要像资深责编一样检查世界规则、角色动机、前后文承接、伏笔状态、批次目标、字数规模、语言自然度、情绪回报和商业卖点是否真实达标。问题必须定位到章节、场景和影响范围。",
            "你必须检查写手的写前取材判断是否真实使用了基准库、动态记忆库、正文记忆库和当前批次细纲，是否漏读了会影响本批的角色状态、世界规则、正文事实、活跃伏笔或禁改边界。取材判断缺失、取材依据与正文不一致、正文偏离取材依据，都必须进入返修或拒绝裁决。",
            "你不能替写手补写正文。你必须给出通过、带备注通过、返修或拒绝裁决，并把连续性问题、风格目标差距、偏移性质和返修要求登记清楚。若正文偏离世界观或大纲，你必须明确裁决为返修正文、提交动态吸收提案，或要求回到上游设计节点，不能默默当作通过事实。",
        ),
    ),
    NodeSpec(
        node_id="memory_commit_chapter",
        title="章节批次提交",
        node_type="memory_commit",
        role="memory_steward",
        agent_id=MEMORY_AGENT_ID,
        projection_id="projection.writing.modular_novel.memory_steward",
        phase_id="phase.modular.chapter_cycle.chapter_loop",
        sequence_index=50,
        output_contract_id="contract.writing.modular_novel.chapter_batch_commit",
        required_inputs=("上游交接包",),
        memory_topics=("chapter_draft_ref", "chapter_review_ref", "chapter_outline_ref", "continuity_notes", "chapter_summaries", "manuscript_fact_index", "next_batch_requirements"),
        required_memory_topics=("chapter_draft_ref", "chapter_review_ref"),
        readable_repositories=("memory.writing.baseline", "memory.writing.mutable", "memory.writing.manuscript"),
        artifact_context_keys=("上游交接包", "基准库", "动态记忆库", "正文记忆库"),
        artifact_paths=("volume_{volume_index_padded}/chapters/chapter_{batch_chapter_range}/chapter_commit_round_{round_index:03d}.md",),
        loop_scope_id="loop.chapter_batch",
        title_template="{batch_label}章节批次提交",
        write_mode="chapter_commit",
        prompt=_role_prompt(
            "你是一名章节记忆提交员。你只负责在章节审核通过或带备注通过后登记当前批次正文引用、章节摘要、角色状态变化、群体关系变化、伏笔状态、连续性说明和下一批承接事项。",
            "你需要把提交内容分层写清：正文记忆库记录已通过的正文引用、逐章摘要、正文事实索引、场景连续性和章末承接；动态记忆库记录人物状态变化、关系变化、世界细节增量、伏笔状态、下一批必须读取的状态和审核备注。",
            "你必须区分已发生正文事实、待跟踪伏笔、待审设定扩展、下一批取材清单和审核备注。登记内容必须可供后续章节细纲与写手直接引用，但不能把待审扩展写成已冻结设定。",
            "你不能改写正文，不能把未通过审核的草稿写入已提交记忆，也不能把审核员未认可的新设定固化为事实。若审核裁决要求动态吸收或上游重设，你只能登记提案入口和风险，不能替扩展提交节点越权完成。",
        ),
    ),
    NodeSpec(
        node_id="chapter_progress_router",
        title="章节进度路由",
        node_type="agent_role",
        role="router",
        projection_id="projection.writing.modular_novel.chapter_progress_router",
        phase_id="phase.modular.chapter_cycle.chapter_loop",
        sequence_index=60,
        output_contract_id="contract.writing.modular_novel.progress_route",
        required_inputs=("上游交接包",),
        memory_topics=("chapter_commit_ref", "volume_progress"),
        artifact_context_keys=("上游交接包",),
        artifact_paths=("volume_{volume_index_padded}/chapters/chapter_{batch_chapter_range}/progress_route_round_{round_index:03d}.md",),
        loop_scope_id="loop.chapter_batch",
        title_template="{batch_label}章节进度路由",
        loop_route_policy=_chapter_progress_route_policy_static(),
        prompt=_role_prompt(
            "你是一名章节进度路由员。你只负责读取已提交批次的度量结果、当前卷目标和运行时循环边界，判断继续下一批还是进入本卷审核。",
            "你需要依据已提交章节数量、已提交字数、当前卷目标和审核状态做路由裁决。只有已提交记忆可以计入完成进度。",
            "你不能创作正文，不能修正章节内容，也不能把未提交草稿或返修中草稿当作完成进度。",
        ),
    ),
    NodeSpec(
        node_id="volume_review",
        title="卷级审核",
        node_type="review_gate",
        role="reviewer",
        projection_id="projection.writing.modular_novel.volume_reviewer",
        phase_id="phase.modular.chapter_cycle.volume_review",
        sequence_index=70,
        output_contract_id="contract.writing.modular_novel.volume_review",
        required_inputs=("上游交接包",),
        memory_topics=("volume_chapter_commits", "baseline_outline", "volume_plan_ref", "continuity_notes", "approved_chapter_batches", "chapter_summaries", "manuscript_fact_index"),
        required_memory_topics=("volume_chapter_commits", "volume_plan_ref"),
        readable_repositories=("memory.writing.baseline", "memory.writing.mutable", "memory.writing.manuscript"),
        artifact_context_keys=("上游交接包", "基准库", "动态记忆库", "正文记忆库"),
        artifact_paths=("volume_{volume_index_padded}/volume_review_round_{round_index:03d}.md",),
        review_revision_stage_id="chapter_outline",
        loop_scope_id="loop.volume",
        title_template="{volume_label}卷级审核",
        write_mode="review_and_issue_ledger",
        prompt=_role_prompt(
            "你是一名名家级中文商业网文卷级总审。你只负责审核当前卷是否完成约二十万字的阶段目标、人物变化、群体关系变化、伏笔推进、连续性闭环和分卷主题表达。",
            "你需要以头部中文商业网文的分卷成品标准检查：章节是否齐全，卷目标是否兑现，关键角色是否发生有效变化，世界规则是否稳定，场域与群体关系推进是否有增量，伏笔是否推进或合理保留，阶段爽点是否有铺垫、爆发和余波，整卷是否形成可继续追读的压力。",
            "你还要判断本卷有没有商业阅读层面的结构问题：长线目标是否被稀释，人物线是否停滞，场景是否空转，转折是否缺少因果，情绪回报是否不足，章末牵引是否只停留在单章技巧而没有卷级悬念。",
            "你必须指出是否允许提交本卷，或要求回到章节批次返修。你不能替写手补写正文，也不能替规划节点重做整卷计划。",
        ),
    ),
    NodeSpec(
        node_id="volume_commit",
        title="卷级提交",
        node_type="memory_commit",
        role="memory_steward",
        agent_id=MEMORY_AGENT_ID,
        projection_id="projection.writing.modular_novel.memory_steward",
        phase_id="phase.modular.chapter_cycle.volume_review",
        sequence_index=80,
        output_contract_id="contract.writing.modular_novel.volume_commit",
        required_inputs=("上游交接包",),
        memory_topics=("volume_review_ref", "volume_chapter_commits", "continuity_notes", "chapter_summaries", "manuscript_fact_index"),
        required_memory_topics=("volume_review_ref", "volume_chapter_commits"),
        readable_repositories=("memory.writing.mutable", "memory.writing.manuscript"),
        artifact_context_keys=("上游交接包", "动态记忆库", "正文记忆库"),
        artifact_paths=("volume_{volume_index_padded}/volume_commit_round_{round_index:03d}.md",),
        loop_scope_id="loop.volume",
        title_template="{volume_label}卷级提交",
        write_mode="volume_commit",
        prompt=_role_prompt(
            "你是一名卷级记忆提交员。你只负责在卷级审核通过或带备注通过后登记本卷正文引用、卷摘要、角色状态、群体关系格局、世界状态、伏笔变更和下一卷承接事项。",
            "你需要把本卷已经发生的事实与下一卷可用的动态记忆整理清楚，尤其标出角色状态、公开信息、秘密状态、未回收伏笔和风险事项。",
            "你不能修改基准库冻结事实，不能把卷后设想写成已发生事实，也不能登记未通过审核的卷内容。",
        ),
    ),
    NodeSpec(
        node_id="volume_postmortem",
        title="卷后复盘",
        node_type="agent_role",
        role="reviewer",
        projection_id="projection.writing.modular_novel.volume_postmortem",
        phase_id="phase.modular.chapter_cycle.volume_extension",
        sequence_index=90,
        output_contract_id="contract.writing.modular_novel.volume_postmortem",
        required_inputs=("上游交接包",),
        memory_topics=("volume_commit_ref", "baseline_outline", "dynamic_memory"),
        readable_repositories=("memory.writing.baseline", "memory.writing.mutable"),
        artifact_context_keys=("上游交接包", "基准库", "动态记忆库"),
        artifact_paths=("volume_{volume_index_padded}/volume_postmortem_round_{round_index:03d}.md",),
        loop_scope_id="loop.volume",
        title_template="{volume_label}卷后复盘",
        prompt=_role_prompt(
            "你是一名卷后复盘员。你只负责总结本卷完成情况、节奏偏差、人物与群体关系变化、伏笔状态、下一卷风险和需要补充的设定候选。",
            "你需要判断哪些问题来自执行偏差，哪些来自原始设计不足，哪些需要下一卷动态调整。所有建议都必须区分事实观察、风险判断和候选提案。",
            "你必须把可能需要增长的内容分为世界细节、角色状态、大纲线程、正文连续性四类。每一类都要说明来源章节或卷级证据、为什么需要增长、如果不处理会影响什么、是否触碰冻结事实、是否只适合下一卷临时使用。",
            "你不能直接修改基准库，不能重写已提交章节，也不能把复盘建议当成已批准设定。",
        ),
    ),
    NodeSpec(
        node_id="world_outline_extension_proposal",
        title="设定与大纲补充提案",
        node_type="agent_role",
        role="creator",
        projection_id="projection.writing.modular_novel.extension_proposer",
        phase_id="phase.modular.chapter_cycle.volume_extension",
        sequence_index=100,
        output_contract_id="contract.writing.modular_novel.extension_proposal",
        required_inputs=("上游交接包",),
        memory_topics=("volume_postmortem_ref", "baseline_world", "baseline_outline", "dynamic_memory"),
        readable_repositories=("memory.writing.baseline", "memory.writing.mutable"),
        artifact_context_keys=("上游交接包", "基准库", "动态记忆库"),
        artifact_paths=("volume_{volume_index_padded}/extension_proposal_round_{round_index:03d}.md",),
        loop_scope_id="loop.volume",
        title_template="{volume_label}设定与大纲补充提案",
        prompt=_role_prompt(
            "你是一名设定与大纲补充提案员。你只负责把卷后复盘中确实需要补充的内容整理成候选提案，供审核节点判断能否进入动态记忆库。",
            "提案必须拆成世界细节卡、角色状态卡、大纲线程调整卡、正文连续性修正卡和拒绝项。每张卡都要说明来源引用、必要性、影响范围、有效窗口、下游使用方式、冲突检查、替代方案和为什么不能直接写入基准库。",
            "你必须把正文偏移处理清楚：如果偏移来自正文执行失误，应建议返修正文；如果偏移已经被审核允许吸收，只能作为动态提案；如果偏移暴露上游设计缺陷，应要求回到上游设计或大纲节点，而不是用单条补丁糊住。",
            "你不能直接修改基准库，不能推翻已冻结事实，也不能为了修补局部问题提出大范围重构。",
        ),
    ),
    NodeSpec(
        node_id="extension_review",
        title="补充提案审核",
        node_type="review_gate",
        role="reviewer",
        projection_id="projection.writing.modular_novel.extension_reviewer",
        phase_id="phase.modular.chapter_cycle.volume_extension",
        sequence_index=110,
        output_contract_id="contract.writing.modular_novel.extension_review",
        required_inputs=("上游交接包",),
        memory_topics=("extension_proposal_ref", "baseline_world", "baseline_outline"),
        readable_repositories=("memory.writing.baseline", "memory.writing.mutable"),
        artifact_context_keys=("上游交接包", "基准库", "动态记忆库"),
        artifact_paths=("volume_{volume_index_padded}/extension_review_round_{round_index:03d}.md",),
        review_revision_stage_id="world_outline_extension_proposal",
        loop_scope_id="loop.volume",
        title_template="{volume_label}补充提案审核",
        write_mode="review_and_issue_ledger",
        prompt=_role_prompt(
            "你是一名补充提案审核员。你只负责判断设定与大纲补充提案能否进入动态记忆库，是否触碰基准库冻结事实，是否会污染后续创作。",
            "你需要逐卡检查来源是否可靠、必要性是否成立、影响范围是否可控、有效窗口是否明确、是否与世界观/人设/细纲冲突、是否只是为了修补单章问题而扩大设定口径。",
            "你必须给出通过、带备注通过、拒绝或返修裁决。通过内容也只能作为动态记忆进入下一卷读取层，不能变成基准库冻结事实。若提案试图静默覆盖冻结事实、吸收未经审核的正文偏移、或把临时修补写成长期 canon，必须拒绝。",
        ),
    ),
    NodeSpec(
        node_id="extension_commit",
        title="动态记忆提交",
        node_type="memory_commit",
        role="memory_steward",
        agent_id=MEMORY_AGENT_ID,
        projection_id="projection.writing.modular_novel.memory_steward",
        phase_id="phase.modular.chapter_cycle.volume_extension",
        sequence_index=120,
        output_contract_id="contract.writing.modular_novel.extension_commit",
        required_inputs=("上游交接包",),
        memory_topics=("extension_review_ref", "extension_proposal_ref", "volume_commit_ref"),
        readable_repositories=("memory.writing.mutable",),
        artifact_context_keys=("上游交接包", "动态记忆库"),
        artifact_paths=("volume_{volume_index_padded}/extension_commit_round_{round_index:03d}.md",),
        loop_scope_id="loop.volume",
        title_template="{volume_label}动态记忆提交",
        write_mode="dynamic_memory_commit",
        prompt=_role_prompt(
            "你是一名动态记忆提交员。你只负责把审核通过或带备注通过的补充提案写入动态记忆库，作为下一卷读取层。",
            "你需要按世界细节卡、角色状态卡、大纲线程调整卡、正文连续性修正卡分别提交，并保留提案来源、审核裁决、适用范围、有效期、影响对象、下游读取方式、是否可升级基准库的判断和不得触碰的基准事实。动态记忆必须便于下一卷规划师判断是否采用。",
            "你不能改写基准库冻结事实，不能提交未通过提案，也不能把动态候选写成永久设定。",
        ),
    ),
    NodeSpec(
        node_id="next_volume_router",
        title="下一卷路由",
        node_type="agent_role",
        role="router",
        projection_id="projection.writing.modular_novel.next_volume_router",
        phase_id="phase.modular.chapter_cycle.volume_extension",
        sequence_index=130,
        output_contract_id="contract.writing.modular_novel.volume_route",
        required_inputs=("上游交接包",),
        memory_topics=("volume_commit_ref", "extension_commit_ref", "target_volumes"),
        artifact_context_keys=("上游交接包",),
        artifact_paths=("volume_{volume_index_padded}/next_volume_route_round_{round_index:03d}.md",),
        loop_scope_id="loop.volume",
        title_template="{volume_label}下一卷路由",
        loop_route_policy=_next_volume_route_policy_static(),
        prompt=_role_prompt(
            "你是一名分卷路由员。你只负责根据目标卷数、已提交卷数、卷级提交状态和动态记忆提交状态判断是否进入下一卷计划或结束章节图。",
            "只有完成卷级审核和卷级提交的卷才能计入完成进度。若补充提案需要进入下一卷，必须确认动态记忆提交已经完成。",
            "你不能创作正文，不能跳过卷级提交，不能因为接近目标就提前结束章节图。",
        ),
    ),
)

FINALIZE_NODES: tuple[NodeSpec, ...] = (
    NodeSpec(
        node_id="final_assemble",
        title="全书汇编",
        node_type="agent_role",
        role="creator",
        projection_id="projection.writing.modular_novel.final_assembler",
        phase_id="phase.modular.finalize.final",
        sequence_index=10,
        output_contract_id="contract.writing.modular_novel.final_manuscript",
        memory_topics=("all_chapter_commits", "baseline_memory", "dynamic_memory", "volume_commits", "approved_chapter_batches", "chapter_summaries", "manuscript_fact_index"),
        required_memory_topics=("all_chapter_commits",),
        readable_repositories=("memory.writing.baseline", "memory.writing.mutable", "memory.writing.manuscript"),
        artifact_context_keys=("上游交接包", "基准库", "动态记忆库", "正文记忆库"),
        artifact_paths=("final/final_manuscript.md", "final/delivery_manifest.md"),
        prompt=_role_prompt(
            "你是一名全书汇编员。你只负责按已提交章节、卷级提交和最终动态记忆汇编最终稿与交付清单。",
            "你需要保持章节顺序、卷结构、标题、正文引用和交付清单可追踪。若发现缺失章节、未提交草稿或卷级提交不完整，必须报告阻塞，不能自行补写。",
            "你不能改写正文内容，不能补写缺失章节，也不能把未提交草稿混入最终稿。",
        ),
    ),
    NodeSpec(
        node_id="final_review",
        title="最终审查",
        node_type="review_gate",
        role="reviewer",
        projection_id="projection.writing.modular_novel.final_reviewer",
        phase_id="phase.modular.finalize.final",
        sequence_index=20,
        output_contract_id="contract.writing.modular_novel.final_review",
        required_inputs=("上游交接包",),
        memory_topics=("final_manuscript_ref", "delivery_manifest_ref", "target_words", "target_chapters"),
        readable_repositories=("memory.writing.baseline", "memory.writing.mutable", "memory.writing.manuscript"),
        artifact_context_keys=("上游交接包", "基准库", "动态记忆库", "正文记忆库"),
        artifact_paths=("final/final_review_round_{round_index:03d}.md",),
        review_revision_stage_id="final_assemble",
        write_mode="review_and_issue_ledger",
        prompt=_role_prompt(
            "你是一名名家级中文商业网文最终总审。你只负责检查最终稿是否完全来自已提交章节，章节顺序是否完整，卷结构是否齐全，交付清单是否可追踪，目标规模和任务要求是否满足。",
            "你需要以头部中文商业长篇成品标准确认最终稿没有混入未提交草稿、没有漏章、没有重复章节、没有非法补写，也没有把动态候选当作正文事实。问题必须定位到交付项、卷或章节范围。",
            "你还需要从最终交付层面判断全书是否保持稳定的世界规则、人物成长线、商业卖点、情绪回报、伏笔闭环和长篇阅读连续性。",
            "你不能替汇编员补内容。你必须给出通过、带备注通过、返修或拒绝裁决。",
        ),
    ),
    NodeSpec(
        node_id="memory_finalize",
        title="最终记忆封存",
        node_type="memory_finalize",
        role="memory_steward",
        agent_id=MEMORY_AGENT_ID,
        projection_id="projection.writing.modular_novel.memory_steward",
        phase_id="phase.modular.finalize.final",
        sequence_index=30,
        output_contract_id="contract.writing.modular_novel.final_memory_seal",
        required_inputs=("上游交接包",),
        memory_topics=("final_review_ref", "final_manuscript_ref", "delivery_manifest_ref"),
        readable_repositories=("memory.writing.mutable", "memory.writing.manuscript"),
        artifact_context_keys=("上游交接包", "动态记忆库", "正文记忆库"),
        artifact_paths=("final/memory_finalize_round_{round_index:03d}.md",),
        write_mode="finalize_commit",
        prompt=_role_prompt(
            "你是一名最终记忆封存员。你只负责在最终审查通过或带备注通过后登记最终稿、交付清单、最终审查结论、封存说明和后续追溯索引。",
            "你需要让整个写作任务的最终产物、引用来源、审核裁决和封存边界可追踪。封存记录必须说明哪些内容是最终交付，哪些只是动态记忆或过程材料。",
            "你不能修改正文，不能修改基准事实，不能封存未通过最终审查的产物。",
        ),
    ),
)


DESIGN_BUSINESS_EDGES = (
    ("edge.project.world", "project_brief", "world_design", "contract.writing.modular_novel.project_brief", "把项目启动包交给世界观规划师。"),
    ("edge.world.review", "world_design", "world_review", "contract.writing.modular_novel.world_candidate", "把世界观候选交给世界观审核员。"),
    ("edge.world_review.commit", "world_review", "memory_commit_world", "contract.writing.modular_novel.world_review", "把世界观审核结果交给基准记忆管理员。"),
    ("edge.world_commit.character_design", "memory_commit_world", "character_design", "contract.writing.modular_novel.world_commit", "把已提交世界观交给人设与关系设计师。"),
    ("edge.world_commit.plot", "memory_commit_world", "plot_design", "contract.writing.modular_novel.world_commit", "把已提交世界观交给剧情与伏笔设计师。"),
    ("edge.character.review", "character_design", "character_review", "contract.writing.modular_novel.character_design", "把角色和关系候选交给人设审核员。"),
    ("edge.character_review.sync", "character_review", "design_sync", "contract.writing.modular_novel.character_review", "把已审核人设候选交给创作架构对齐节点。"),
    ("edge.plot.sync", "plot_design", "design_sync", "contract.writing.modular_novel.plot_design", "把剧情与伏笔候选交给创作架构对齐节点。"),
    ("edge.sync.character_commit", "design_sync", "memory_commit_character", "contract.writing.modular_novel.design_alignment", "把对齐通过的人设切片交给角色基准库管理员。"),
    ("edge.character_commit.outline", "memory_commit_character", "outline_design", "contract.writing.modular_novel.character_commit", "把已提交角色基准交给全书细纲设计师。"),
    ("edge.sync.outline", "design_sync", "outline_design", "contract.writing.modular_novel.design_alignment", "把对齐包交给全书细纲设计师。"),
    ("edge.outline.review", "outline_design", "outline_review", "contract.writing.modular_novel.outline_design", "把全书细纲交给细纲审核员。"),
    ("edge.outline_review.baseline", "outline_review", "baseline_memory_seed", "contract.writing.modular_novel.outline_review", "把通过审核的细纲和设计资产交给基准库初始化。"),
)

CHAPTER_BUSINESS_EDGES = (
    ("edge.volume_plan.outline", "volume_plan", "chapter_outline", "contract.writing.modular_novel.volume_plan", "把当前卷计划交给章节批次细纲节点。"),
    ("edge.outline.draft", "chapter_outline", "chapter_draft", "contract.writing.modular_novel.chapter_outline", "把当前十章细纲交给写手。"),
    ("edge.draft.review", "chapter_draft", "chapter_review", "contract.writing.modular_novel.chapter_draft", "把当前十章正文草稿交给审核员。"),
    ("edge.review.commit", "chapter_review", "memory_commit_chapter", "contract.writing.modular_novel.chapter_review", "把章节审核结果交给章节记忆提交员。"),
    ("edge.commit.progress", "memory_commit_chapter", "chapter_progress_router", "contract.writing.modular_novel.chapter_batch_commit", "把章节提交结果交给进度路由。"),
    ("edge.progress.volume_review", "chapter_progress_router", "volume_review", "contract.writing.modular_novel.progress_route", "当本卷目标达到时进入卷级审核。"),
    ("edge.volume_review.commit", "volume_review", "volume_commit", "contract.writing.modular_novel.volume_review", "把卷级审核结果交给卷级提交员。"),
    ("edge.volume_commit.postmortem", "volume_commit", "volume_postmortem", "contract.writing.modular_novel.volume_commit", "把卷级提交结果交给卷后复盘。"),
    ("edge.postmortem.extension", "volume_postmortem", "world_outline_extension_proposal", "contract.writing.modular_novel.volume_postmortem", "把卷后复盘交给补充提案节点。"),
    ("edge.extension.review", "world_outline_extension_proposal", "extension_review", "contract.writing.modular_novel.extension_proposal", "把补充提案交给审核员。"),
    ("edge.extension.commit", "extension_review", "extension_commit", "contract.writing.modular_novel.extension_review", "把审核通过的补充提案交给动态记忆提交员。"),
    ("edge.extension.next_volume", "extension_commit", "next_volume_router", "contract.writing.modular_novel.extension_commit", "把动态记忆提交结果交给下一卷路由。"),
)

FINALIZE_BUSINESS_EDGES = (
    ("edge.final_assemble.review", "final_assemble", "final_review", "contract.writing.modular_novel.final_manuscript", "把全书汇编稿交给最终审查员。"),
    ("edge.final_review.memory", "final_review", "memory_finalize", "contract.writing.modular_novel.final_review", "把最终审查结果交给最终记忆封存员。"),
)


def configure(base_dir: Path | str | None = None) -> dict[str, Any]:
    backend_dir = Path(base_dir or BACKEND_DIR).resolve()
    registry = TaskFlowRegistry(backend_dir)
    contract_registry = TaskContractRegistry(backend_dir)

    _delete_stale_managed_contract_specs(
        contract_registry,
        active_contract_ids={spec.contract_id for spec in _contract_specs()},
    )
    _upsert_domain(registry)
    _upsert_agents(backend_dir)
    _upsert_contracts(contract_registry)
    _upsert_protocol(registry)
    _delete_graph_module_wrapper_task_assets(registry)
    _upsert_task_assets(registry)
    _upsert_imported_module_graph(registry, graph_id=DESIGN_GRAPH_ID, nodes=DESIGN_NODES, business_edges=DESIGN_BUSINESS_EDGES)
    _upsert_imported_module_graph(registry, graph_id=CHAPTER_GRAPH_ID, nodes=CHAPTER_NODES, business_edges=CHAPTER_BUSINESS_EDGES)
    _upsert_imported_module_graph(registry, graph_id=FINALIZE_GRAPH_ID, nodes=FINALIZE_NODES, business_edges=FINALIZE_BUSINESS_EDGES)
    _upsert_master_graph(registry)

    configured = {
        "domain_id": DOMAIN_ID,
        "protocol_id": PROTOCOL_ID,
        "graph_ids": [MASTER_GRAPH_ID, DESIGN_GRAPH_ID, CHAPTER_GRAPH_ID, FINALIZE_GRAPH_ID],
        "requested_chapters": CHAPTER_REQUESTED_COUNT,
        "target_volumes": TARGET_VOLUMES,
        "chapters_per_volume": CHAPTERS_PER_VOLUME,
        "chapter_batch_size": CHAPTER_BATCH_SIZE,
        "batch_target_words": BATCH_TARGET_WORDS,
        "volume_target_words": VOLUME_TARGET_WORDS,
        "target_words": TARGET_WORDS,
        "managed_by": MANAGED_BY,
    }
    print(
        "configured native modular writing graphs: "
        f"{', '.join(configured['graph_ids'])}; "
        f"{TARGET_VOLUMES} volume(s), {CHAPTERS_PER_VOLUME} chapters per volume, "
        f"{CHAPTER_BATCH_SIZE} chapters per batch"
    )
    return configured


def _upsert_domain(registry: TaskFlowRegistry) -> None:
    registry.upsert_task_domain(
        domain_id=DOMAIN_ID,
        task_family=TASK_FAMILY,
        title="模块化长篇写作",
        description="以任务图为一等对象组织设计初始化、章节批次创作与收尾交付的长篇写作任务域。",
        enabled=True,
        sort_order=88,
        metadata={
            "managed_by": MANAGED_BY,
            "architecture": "native_graph_module_composition",
        },
    )


def _upsert_agents(backend_dir: Path) -> None:
    agent_registry = AgentRegistry(backend_dir)
    for agent_id, name, projection in (
        (WORKER_AGENT_ID, "模块化写作执行员", "projection.writing.modular_novel.worker"),
        (CREATOR_AGENT_ID, "模块化写作创作设计员", "projection.writing.modular_novel.world_designer"),
        (REVIEWER_AGENT_ID, "模块化写作专业审核员", "projection.writing.modular_novel.world_reviewer"),
        (MEMORY_AGENT_ID, "模块化写作记忆管家", "projection.writing.modular_novel.memory_steward"),
        (MONITOR_AGENT_ID, "模块化写作运行监控员", "projection.writing.modular_novel.runtime_monitor"),
    ):
        agent_registry.upsert_agent(
            agent_id=agent_id,
            display_name=name,
            agent_category="custom_agent",
            description=f"{name}。用于模块化长篇写作任务图运行；采用简单文本产出边界，文件、记忆与断点由编排系统托管。",
            enabled=True,
            default_projection_id=projection,
            metadata={
                "managed_by": MANAGED_BY,
                "task_family": TASK_FAMILY,
                "agent_template_id": f"task_graph.{TASK_FAMILY}.node_agent",
            },
        )

    runtime_registry = AgentRuntimeRegistry(backend_dir)
    for agent_id, template_id, lanes, contexts, extra_ops in (
        (
            WORKER_AGENT_ID,
            "task_graph.writing.modular_novel.worker",
            ("coordination_task",),
            ("task", "projection", "runtime_contracts", "artifact_refs", "memory_runtime_view"),
            ("op.text_metric",),
        ),
        (
            CREATOR_AGENT_ID,
            "task_graph.writing.modular_novel.creator",
            ("coordination_task",),
            ("task", "projection", "runtime_contracts", "artifact_refs", "memory_runtime_view"),
            ("op.text_metric",),
        ),
        (
            REVIEWER_AGENT_ID,
            "task_graph.writing.modular_novel.reviewer",
            ("coordination_task",),
            ("task", "projection", "runtime_contracts", "artifact_refs", "memory_runtime_view"),
            (),
        ),
        (
            MEMORY_AGENT_ID,
            "task_graph.writing.modular_novel.memory_steward",
            ("coordination_task", "system_memory"),
            ("task", "projection", "runtime_contracts", "artifact_refs", "memory_runtime_view"),
            (),
        ),
        (
            MONITOR_AGENT_ID,
            "task_graph.writing.modular_novel.runtime_monitor",
            ("task_graph_monitor",),
            ("task", "projection", "runtime_contracts", "artifact_refs", "memory_runtime_view", "task_graph_monitor"),
            (),
        ),
    ):
        current = runtime_registry.get_profile(agent_id)
        current_model_profile = getattr(current, "model_profile", None)
        writing_model_profile = parse_agent_model_profile(
            current_model_profile.to_dict() if current_model_profile is not None else {}
        )
        writing_model_profile = AgentModelProfile(
            profile_id=writing_model_profile.profile_id,
            display_name=writing_model_profile.display_name,
            provider=writing_model_profile.provider,
            model=writing_model_profile.model,
            credential_ref=writing_model_profile.credential_ref,
            max_output_tokens=max(int(writing_model_profile.max_output_tokens or 0), 32768),
            timeout_seconds=max(float(writing_model_profile.timeout_seconds or 0), 180.0),
            long_output_timeout_seconds=max(float(writing_model_profile.long_output_timeout_seconds or 0), 600.0),
            max_retries=max(int(writing_model_profile.max_retries or 0), 2),
            temperature=writing_model_profile.temperature,
            thinking_mode=writing_model_profile.thinking_mode,
            reasoning_effort=writing_model_profile.reasoning_effort,
            stream_policy=dict(writing_model_profile.stream_policy),
            fallback_profile_ref=writing_model_profile.fallback_profile_ref,
            capability_tags=tuple(writing_model_profile.capability_tags),
            metadata=dict(writing_model_profile.metadata),
        )
        runtime_registry.upsert_profile(
            agent_id=agent_id,
            agent_profile_id=str(getattr(current, "agent_profile_id", "") or f"{agent_id.removeprefix('agent:')}_runtime"),
            allowed_runtime_lanes=lanes,
            allowed_operations=tuple(dict.fromkeys(("op.model_response", "op.memory_read", *extra_ops))),
            blocked_operations=(
                "op.read_file",
                "op.search_files",
                "op.search_text",
                "op.read_structured_file",
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.python_repl",
                "op.delegate_to_agent",
                "op.web_search",
                "op.fetch_url",
            ),
            allowed_memory_scopes=("writing_modular_novel", "state_readonly"),
            allowed_context_sections=contexts,
            use_shared_contract=True,
            can_delegate_to_agents=False,
            allowed_delegate_agent_ids=(),
            max_delegate_calls_per_turn=0,
            delegate_context_policy="summary_and_refs_only",
            approval_policy="read_only_first",
            trace_policy="runtime_event_log",
            lifecycle_policy="task_graph_managed",
            model_profile=writing_model_profile.to_dict(),
            metadata={
                "managed_by": MANAGED_BY,
                "task_family": TASK_FAMILY,
                "source_task_graph_refs": [MASTER_GRAPH_ID, DESIGN_GRAPH_ID, CHAPTER_GRAPH_ID, FINALIZE_GRAPH_ID],
                "runtime_template_id": template_id,
                "agent_mode": "text_artifact_worker",
                "interaction_mode": "role_mode",
                "runtime_mode": "text_artifact_runtime",
                "text_artifact_runtime": True,
                "preexpanded_context_required": True,
                "pseudo_tool_output_forbidden": True,
                "model_may_not_request_file_reads": True,
                "file_and_memory_side_effects_owned_by": "orchestration_runtime",
                "generic_length_metric_tool_enabled": bool(extra_ops),
                "allow_unregistered_runtime_lanes": True,
            },
        )


def _upsert_contracts(registry: TaskContractRegistry) -> None:
    for spec in _contract_specs():
        registry.upsert_contract_spec(spec)


def _delete_stale_managed_contract_specs(
    registry: TaskContractRegistry,
    *,
    active_contract_ids: set[str],
) -> None:
    for spec in registry.list_contract_specs():
        if dict(spec.metadata or {}).get("managed_by") != MANAGED_BY:
            continue
        if spec.contract_id in active_contract_ids:
            continue
        try:
            registry.delete_contract_spec(spec.contract_id)
        except ValueError:
            pass


def _contract_specs() -> list[ContractSpec]:
    specs = [
        _contract_spec("contract.writing.modular_novel.graph", "模块化长篇写作图契约", "global_task", output_fields=("artifact_refs", "run_summary")),
        _contract_spec(
            "contract.writing.modular_novel.graph_module_handoff",
            "图模块导入交接契约",
            "edge_handoff",
            input_fields=("importing_graph_id", "source_graph_module_id", "upstream_commit_refs"),
            output_fields=("imported_graph_id", "imported_run_ref", "committed_output_refs", "handoff_summary"),
        ),
        _contract_spec(
            "contract.writing.modular_novel.design_commit",
            "设计初始化提交契约",
            "final_output",
            output_fields=("project_brief_ref", "world_commit_ref", "character_design_ref", "plot_design_ref", "outline_commit_ref", "baseline_memory_ref", "artifact_refs"),
        ),
        _contract_spec(
            "contract.writing.modular_novel.chapter_cycle_commit",
            "章节循环图提交契约",
            "final_output",
            input_fields=("baseline_memory_ref", "target_volumes", "chapters_per_volume"),
            output_fields=("volume_commit_refs", "chapter_commit_refs", "dynamic_memory_ref", "artifact_refs"),
        ),
        _contract_spec(
            "contract.writing.modular_novel.chapter_batch_commit",
            "章节批次提交契约",
            "final_output",
            input_fields=("chapter_draft_ref", "chapter_review_ref", "unit_batch_id"),
            output_fields=("chapter_commit_refs", "chapter_summary_refs", "batch_receipt_ref", "artifact_refs"),
        ),
        _contract_spec(
            "contract.writing.modular_novel.final_delivery",
            "最终交付契约",
            "final_output",
            input_fields=("chapter_commit_refs", "baseline_memory_ref", "delivery_requirements"),
            output_fields=("final_manuscript_ref", "final_review_ref", "delivery_manifest_ref", "memory_finalize_receipt_ref", "artifact_refs"),
        ),
        _contract_spec("contract.writing.modular_novel.memory_packet", "记忆库读写包契约", "edge_handoff", input_fields=("repository_node_id", "collection", "topics", "operation"), output_fields=("memory_refs", "canonical_text_refs", "artifact_refs", "memory_receipt_ref")),
    ]
    for node in (*DESIGN_NODES, *CHAPTER_NODES, *FINALIZE_NODES):
        specs.append(
            _contract_spec(
                node.output_contract_id,
                node.title + "输出契约",
                "final_output" if node.node_type in {"memory_commit", "memory_finalize"} else "node_execution",
                input_fields=tuple(node.required_inputs),
                output_fields=("artifact_refs", f"{node.node_id}_ref"),
                artifact_paths=node.artifact_paths,
            )
        )
    return specs


def _contract_spec(
    contract_id: str,
    title_zh: str,
    contract_kind: str,
    *,
    input_fields: tuple[str, ...] = (),
    output_fields: tuple[str, ...] = (),
    artifact_paths: tuple[str, ...] = (),
) -> ContractSpec:
    return ContractSpec(
        contract_id=contract_id,
        title_zh=title_zh,
        title_en=contract_id.rsplit(".", 1)[-1],
        contract_kind=contract_kind,
        description=f"{title_zh}。用于模块化长篇写作任务图，能力来自通用任务图契约、工具和运行策略。",
        input_fields=tuple(_field(name, source_hint="upstream_output", required=True) for name in input_fields),
        output_fields=tuple(_field(name, source_hint="artifact", required=name.endswith("_ref") or name == "artifact_refs") for name in output_fields),
        artifact_requirements=tuple(
            ArtifactRequirement(
                requirement_id=f"artifact.{_safe_id(path)}",
                title_zh=path,
                artifact_type="markdown",
                required=True,
                naming_rule=path,
                storage_policy="artifact_ref",
            )
            for path in artifact_paths
        ),
        acceptance_rules=(
            AcceptanceRule(
                rule_id=f"{_safe_id(contract_id)}.artifact_refs",
                title_zh="必须产出可追踪产物引用",
                rule_type="artifact_exists",
                severity="error",
                target_field="artifact_refs",
                criteria="长文本和节点结果必须以 artifact refs 交接，不能只返回摘要。",
            ),
        ),
        version="1.0.0",
        enabled=True,
        metadata={"managed_by": MANAGED_BY, "domain_id": DOMAIN_ID, "task_family": TASK_FAMILY},
    )


def _field(name: str, *, source_hint: str, required: bool = False) -> ContractField:
    if name.endswith("_refs") or name == "artifact_refs" or name == "committed_output_refs":
        field_type = "array"
    elif name.endswith("_ref"):
        field_type = "artifact_ref"
    else:
        field_type = "string"
    return ContractField(
        field_id=name,
        title_zh=name,
        field_type=field_type,
        required=required,
        description=name,
        source_hint=source_hint,
        visibility="model_visible",
    )


def _upsert_protocol(registry: TaskFlowRegistry) -> None:
    registry.upsert_task_communication_protocol(
        protocol_id=PROTOCOL_ID,
        title="模块化长篇写作通信协议",
        message_types=(
            "message/send",
            "task/status",
            "task/artifact",
            "task/review_feedback",
            "task/revision_request",
            "task/memory_read",
            "task/memory_write",
            "task/graph_module_commit",
        ),
        payload_contracts=(
            "contract.writing.modular_novel.graph",
            "contract.writing.modular_novel.graph_module_handoff",
            "contract.writing.modular_novel.design_commit",
            "contract.writing.modular_novel.chapter_batch_commit",
            "contract.writing.modular_novel.final_delivery",
        ),
        signal_rules=(
            "graph_module_commits_before_next_graph_module",
            "unit_batch_range_is_runtime_contract",
            "review_result_required_before_commit",
            "baseline_memory_updates_only_through_commit_nodes",
        ),
        handoff_rules=(
            "structured_artifact_refs_only",
            "no_raw_agent_dialogue",
            "committed_refs_only_between_graph_modules",
            "batch_candidate_not_visible_as_committed_memory",
        ),
        ack_policy="explicit_ack",
        timeout_policy="fail_closed",
        error_signal_policy="raise_to_coordinator",
        enabled=True,
        metadata={"managed_by": MANAGED_BY, "task_family": TASK_FAMILY, "domain_id": DOMAIN_ID},
    )


def _upsert_task_assets(registry: TaskFlowRegistry) -> None:
    for node in (*DESIGN_NODES, *CHAPTER_NODES, *FINALIZE_NODES):
        _upsert_task_asset(
            registry,
            task_id=_node_task_id(node.node_id),
            title=node.title,
            input_contract_id=node.input_contract_id,
            output_contract_id=node.output_contract_id,
            prompt=node.prompt,
            agent_id=_node_agent_id(node),
            projection_id=node.projection_id,
            node_id=node.node_id,
        )


def _delete_graph_module_wrapper_task_assets(registry: TaskFlowRegistry) -> None:
    """Remove legacy wrapper tasks; graph modules are reusable graph handles, not agent tasks."""
    for task_id in (
        "task.writing.modular_novel.master",
        "task.writing.modular_novel.design_init",
        "task.writing.modular_novel.chapter_cycle",
        "task.writing.modular_novel.finalize",
    ):
        if registry.get_specific_task_record(task_id) is None:
            continue
        registry.delete_specific_task_record(task_id)


def _upsert_task_asset(
    registry: TaskFlowRegistry,
    *,
    task_id: str,
    title: str,
    input_contract_id: str,
    output_contract_id: str,
    prompt: str,
    agent_id: str,
    projection_id: str,
    node_id: str = "",
) -> None:
    flow_id = task_id.replace("task.", "flow.", 1)
    workflow_id = task_id.replace("task.", "workflow.", 1)
    registry.workflow_registry.upsert_workflow(
        workflow_id=workflow_id,
        title=title,
        compatible_projection_ids=(projection_id,) if projection_id else (),
        steps=(
            {"step_id": "read_contract_packet", "title": "读取契约化输入包"},
            {"step_id": "execute_node", "title": "执行节点职责"},
            {"step_id": "commit_artifact_refs", "title": "提交结构化产物引用"},
        ),
        input_boundary=input_contract_id,
        output_boundary=output_contract_id,
        stop_conditions=("contract_output_ready", "blocking_issue_reported"),
        required_evidence_refs=("artifact_refs", "contract_payload"),
        output_contract_id=output_contract_id,
        prompt=prompt,
        enabled=True,
        metadata={"managed_by": MANAGED_BY, "domain_id": DOMAIN_ID, "task_family": TASK_FAMILY, "node_id": node_id},
    )
    registry.upsert_flow(
        flow_id=flow_id,
        task_family=TASK_FAMILY,
        title=title,
        input_contract_id=input_contract_id,
        output_contract_id=output_contract_id,
        default_agent_id=agent_id,
        default_workflow_id=workflow_id,
        default_runtime_lane="coordination_task",
        default_memory_scope="writing_modular_novel",
        enabled=True,
        metadata={
            "managed_by": MANAGED_BY,
            "domain_id": DOMAIN_ID,
            "task_id": task_id,
            "node_id": node_id,
            "runtime_interaction_mode": "role_mode",
            "interaction_mode": "role_mode",
            "execution_mode": "single",
            "suppress_bundle_projection": True,
            "task_graph_node_runtime": True,
        },
    )
    registry.upsert_specific_task_record(
        task_id=task_id,
        task_title=title,
        task_family=TASK_FAMILY,
        description=f"{title}。由模块化写作任务图原生配置生成。",
        enabled=True,
        runtime_lane="coordination_task",
        input_contract_id=input_contract_id,
        output_contract_id=output_contract_id,
        default_flow_contract_id=flow_id,
        default_workflow_id=workflow_id,
        default_projection_policy="fixed_projection" if projection_id else "workflow_compatible_or_task_default",
        task_policy={
            "safety_policy": {"verification_mode": "artifact_or_trace", "write_mode": "scoped", "safety_class": "S2_bounded"},
            "task_structure": {
                "execution_chain_type": "coordination_node",
                "memory_scope_hint": "writing_modular_novel",
                "projection_id": projection_id,
                "node_id": node_id,
                "runtime_interaction_mode": "role_mode",
                "suppress_bundle_projection": True,
            },
            "operation_policy": _node_operation_policy(node_id=node_id),
        },
        metadata={
            "managed_by": MANAGED_BY,
            "domain_id": DOMAIN_ID,
            "projection_id": projection_id,
            "node_id": node_id,
            "package_template": TASK_FAMILY,
            "runtime_interaction_mode": "role_mode",
            "interaction_mode": "role_mode",
            "execution_mode": "single",
            "suppress_bundle_projection": True,
            "task_graph_node_runtime": True,
        },
    )
    registry.upsert_task_assignment(
        task_id=task_id,
        task_title=title,
        task_kind="specific_task",
        task_family=TASK_FAMILY,
        flow_id=flow_id,
        runtime_lane="coordination_task",
        default_agent_id=agent_id,
        workflow_id=workflow_id,
        workflow_file_ref=f"workflow:{workflow_id}",
        projection_id=projection_id,
        input_contract_id=input_contract_id,
        output_contract_id=output_contract_id,
        safety_policy={"verification_mode": "artifact_or_trace", "write_mode": "scoped", "safety_class": "S2_bounded"},
        task_structure={
            "execution_chain_type": "coordination_node",
            "runtime_lane_hint": "coordination_task",
            "memory_scope_hint": "writing_modular_novel",
            "projection_id": projection_id,
            "node_id": node_id,
            "runtime_interaction_mode": "role_mode",
            "suppress_bundle_projection": True,
            "workflow_steps": [
                {"step_id": "read_contract_packet", "title": "读取契约化输入包"},
                {"step_id": "execute_node", "title": "执行节点职责"},
                {"step_id": "commit_artifact_refs", "title": "提交结构化产物引用"},
            ],
            "task_resource_kind": TASK_FAMILY,
        },
        enabled=True,
        metadata={
            "managed_by": MANAGED_BY,
            "domain_id": DOMAIN_ID,
            "projection_id": projection_id,
            "node_id": node_id,
            "package_template": TASK_FAMILY,
            "runtime_interaction_mode": "role_mode",
            "interaction_mode": "role_mode",
            "execution_mode": "single",
            "suppress_bundle_projection": True,
            "task_graph_node_runtime": True,
        },
    )
    registry.upsert_projection_binding(
        task_id=task_id,
        projection_selection_mode="fixed_projection" if projection_id else "workflow_compatible_or_task_default",
        allowed_projection_ids=(projection_id,) if projection_id else (),
        default_projection_id=projection_id,
        projection_required=bool(projection_id),
        notes="模块化写作任务图原生配置生成。",
        metadata={"managed_by": MANAGED_BY, "node_id": node_id},
    )
    registry.upsert_flow_contract_binding(
        task_id=task_id,
        flow_contract_id=flow_id,
        override_policy="task_default",
        fallback_policy="fail_closed",
        metadata={"managed_by": MANAGED_BY, "node_id": node_id},
    )
    registry.upsert_task_memory_request_profile(
        task_id=task_id,
        requested_memory_layers=("state", "task_durable", "artifact_refs"),
        requested_topics=("writing_modular_novel", "baseline_memory", "dynamic_memory", "chapter_commits"),
        memory_priority="high",
        writeback_policy="task_graph_commit_edges",
        allow_long_term_memory=True,
        memory_scope_hint="writing_modular_novel",
        metadata={"managed_by": MANAGED_BY, "node_id": node_id},
    )
    registry.upsert_task_agent_adoption_plan(
        task_id=task_id,
        adoption_mode="adopt_with_projection",
        default_agent_id=agent_id,
        allow_worker_agent_spawn=False,
        notes="模块化写作任务图使用通用任务图执行能力，不新增写作专用后端入口。",
        metadata={"managed_by": MANAGED_BY, "execution_chain_type": "coordination_node", "node_id": node_id},
    )


def _upsert_imported_module_graph(
    registry: TaskFlowRegistry,
    *,
    graph_id: str,
    nodes: tuple[NodeSpec, ...],
    business_edges: tuple[tuple[str, str, str, str, str], ...],
) -> None:
    graph_nodes = [_node_payload(node) for node in nodes]
    graph_nodes.extend(_repository_node_payload(item) for item in REPOSITORY_NODES if _repository_needed(item, nodes))
    graph_edges = [_business_edge(*edge) for edge in business_edges]
    graph_edges.extend(_memory_edges_for_nodes(nodes))
    graph_edges.extend(_revision_edges_for_nodes(nodes))
    if graph_id == CHAPTER_GRAPH_ID:
        metadata_extra = {
            "unit_batch_contract": _chapter_unit_batch_contract(),
            "length_budget_contract": _length_budget_contract("volume", VOLUME_TARGET_WORDS, VOLUME_MIN_WORDS, VOLUME_MAX_WORDS, CHAPTERS_PER_VOLUME, "graph.metadata.length_budget_contract"),
            "runtime_loop_policy": _chapter_runtime_loop_policy(),
            "loop_frames": list(_chapter_runtime_loop_policy()["frames"]),
        }
    else:
        metadata_extra = {}
    registry.upsert_task_graph(
        graph_id=graph_id,
        title=_graph_title(graph_id),
        domain_id=DOMAIN_ID,
        task_family=TASK_FAMILY,
        graph_kind="coordination",
        entry_node_id=nodes[0].node_id,
        output_node_id=nodes[-1].node_id,
        nodes=tuple(graph_nodes),
        edges=tuple(graph_edges),
        graph_contract_id=_graph_contract_id(graph_id),
        contract_bindings=_graph_contract_bindings(graph_id),
        default_protocol_id=PROTOCOL_ID,
        working_memory_policy_profile_id="wmprofile.writing.modular_novel",
        working_memory_policy=_working_memory_policy(),
        runtime_policy=_runtime_policy(),
        context_policy={"handoff": "contract_payload_and_refs", "raw_dialogue_handoff": "forbidden", "long_text_policy": "artifact_ref_with_authorized_expansion"},
        publish_state="published",
        enabled=True,
        metadata={
            "managed_by": MANAGED_BY,
            "architecture": "native_modular_task_graph_child",
            "business_communication_modes": ["structured_handoff", "memory_read", "memory_commit", "revision_request"],
            "phase_definitions": _phase_definitions_for_nodes(nodes),
            "subtask_refs": [_node_task_id(node.node_id) for node in nodes],
            "editor_publish_state": "published",
            "graph_module_role": graph_id.rsplit(".", 1)[-1],
            **metadata_extra,
        },
    )


def _node_payload(node: NodeSpec) -> dict[str, Any]:
    agent_id = _node_agent_id(node)
    artifact_policy = _artifact_policy(node)
    runtime_bindings = {"model_requirement": _model_requirement(node.node_id), **dict(node.extra_runtime)}
    if node.length_budget:
        runtime_bindings["length_budget"] = dict(node.length_budget)
    unit_batch_bindings = _node_unit_batch_contract(node)
    governance_policy = _node_governance_policy(node)
    outline_thread_policy = _outline_thread_policy(node)
    runtime_bindings["stage_packet_policy"] = _stage_packet_policy(node)
    if outline_thread_policy:
        runtime_bindings["outline_thread_policy"] = dict(outline_thread_policy)
    memory_write_policy = _memory_write_policy(node)
    executor_policy = _executor_policy(node)
    runtime_batch_boundary_policy = _runtime_batch_boundary_policy(node)
    if runtime_batch_boundary_policy:
        executor_policy["runtime_batch_boundary_policy"] = runtime_batch_boundary_policy
    replay_sanitization_policy = _replay_sanitization_policy(node)
    if replay_sanitization_policy:
        executor_policy["replay_sanitization_policy"] = replay_sanitization_policy
    payload = {
        "node_id": node.node_id,
        "node_type": node.node_type,
        "title": node.title,
        "task_id": _node_task_id(node.node_id),
        "agent_id": agent_id,
        "agent_group_id": AGENT_GROUP_ID,
        "work_posture": node.role,
        "projection_id": node.projection_id,
        "projection_overlay_id": node.projection_id,
        "runtime_lane": "coordination_task",
        "interaction_mode": "role_mode",
        "runtime_interaction_mode": "role_mode",
        "phase_id": node.phase_id,
        "sequence_index": node.sequence_index,
        "timeline_group_id": node.phase_id,
        "execution_mode": "sync",
        "wait_policy": "wait_all_upstream_completed",
        "join_policy": "all_success",
        "blocks_phase_exit": True,
        "executor_policy": executor_policy,
        "context_visibility_policy": {
            "shared_context_policy": "explicit_refs_only",
            "memory_sharing_policy": "memory_pack_only",
            "conversation_memory": "hidden",
            "suppress_conversation_memory": True,
        },
        "input_contract_id": node.input_contract_id,
        "output_contract_id": node.output_contract_id,
        "contract_bindings": {
            "schema": {"input_contract_id": node.input_contract_id, "output_contract_id": node.output_contract_id},
            "execution": {"node_contract_id": node.output_contract_id},
            "artifact": {"artifact_policy": artifact_policy, "artifact_context_policy": _artifact_context_policy(node)},
            "memory": {
                "memory_read_policy": _memory_read_policy(node),
                "memory_writeback_policy": memory_write_policy,
                "dynamic_memory_read_policy": _dynamic_memory_read_policy(node),
                "prewrite_memory_plan_policy": _prewrite_memory_plan_policy(node),
                "dynamic_expansion_policy": _dynamic_expansion_policy(node),
            },
            "acceptance": {"review_gate_policy": _review_gate_policy(node)} if node.node_type == "review_gate" else {},
            "runtime": runtime_bindings,
            "unit_batch": unit_batch_bindings,
            "governance": governance_policy,
        },
        "memory_read_policy": _memory_read_policy(node),
        "memory_writeback_policy": memory_write_policy,
        "dynamic_memory_read_policy": _dynamic_memory_read_policy(node),
        "artifact_context_policy": _artifact_context_policy(node),
        "artifact_policy": artifact_policy,
        "artifact_targets": [{"path": path, "required": True, "source": "node_spec"} for path in node.artifact_paths],
        "quality_retry_policy": _quality_retry_policy(node),
        "review_gate_policy": _review_gate_policy(node),
        "loop_policy": _loop_policy(node),
        "loop_kind": "bounded_metric_iteration" if node.loop_scope_id else "",
        "loop_scope_id": node.loop_scope_id,
        "title_template": node.title_template,
        "loop_route_policy": dict(node.loop_route_policy),
        "metadata": {
            "managed_by": MANAGED_BY,
            "node_spec_source": "native_modular_writing_graph",
            "role_prompt": node.prompt,
            "resolved_agent_id": agent_id,
            "runtime_interaction_mode": "role_mode",
            "interaction_mode": "role_mode",
            "execution_mode": "single",
            "suppress_bundle_projection": True,
            "model_profile_ref": MODEL_PROFILE_REF,
            "task_graph_node_runtime": True,
            "artifact_context_policy": _artifact_context_policy(node),
            "governance_policy": governance_policy,
            "outline_thread_policy": outline_thread_policy,
            "prewrite_memory_plan_policy": _prewrite_memory_plan_policy(node),
            "dynamic_expansion_policy": _dynamic_expansion_policy(node),
            "loop_route_policy": dict(node.loop_route_policy),
            "loop_scope_id": node.loop_scope_id,
            "title_template": node.title_template,
        },
    }
    return payload


def _repository_node_payload(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": spec["node_id"],
        "node_type": spec["node_type"],
        "title": spec["title"],
        "runtime_lane": "coordination_task",
        "execution_mode": "sync",
        "wait_policy": "wait_all_upstream_completed",
        "join_policy": "all_success",
        "resource_lifecycle_policy": {
            "versioning": "append_version",
            "mutable": bool(spec["mutable"]),
            "write_owner_node_ids": list(spec["write_owner_node_ids"]),
            "readable_by": list(spec["readable_by"]),
        },
        "contract_bindings": {
            "memory": {
                "repository_id": spec["repository_id"],
                "collections": list(spec["collections"]),
                "mutable": bool(spec["mutable"]),
                "library_role": spec["library_role"],
            }
        },
        "metadata": {
            "managed_by": MANAGED_BY,
            "repository_id": spec["repository_id"],
            "collections": list(spec["collections"]),
            "mutable": bool(spec["mutable"]),
            "library_role": spec["library_role"],
        },
    }


def _node_agent_id(node: NodeSpec) -> str:
    if node.agent_id:
        return node.agent_id
    if node.node_type == "review_gate":
        return REVIEWER_AGENT_ID
    if node.node_type in {"memory_commit", "memory_finalize"} or node.write_mode in COMMIT_WRITE_MODES:
        return MEMORY_AGENT_ID
    return CREATOR_AGENT_ID


def _repository_needed(spec: dict[str, Any], nodes: tuple[NodeSpec, ...]) -> bool:
    repo_id = str(spec["node_id"])
    return any(repo_id in node.readable_repositories or node.write_mode in {"baseline_commit", "chapter_commit", "volume_commit", "dynamic_memory_commit", "finalize_commit", "review_and_issue_ledger"} for node in nodes)


def _business_edge(edge_id: str, source: str, target: str, contract_id: str, summary: str) -> dict[str, Any]:
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_type": "structured_handoff",
        "payload_contract_id": contract_id,
        "ack_required": True,
        "ack_policy": "explicit_ack",
        "failure_propagation_policy": "fail_downstream",
        "result_delivery_policy": "contract_payload_and_refs",
        "context_filter_policy": {"mode": "explicit_refs_only", "raw_dialogue_handoff": "forbidden"},
        "artifact_ref_policy": {
            "required_for_long_outputs": True,
            "prefer_refs_over_text": False,
            "context_mode": "refs_and_authorized_text",
            "source_output_key": f"{contract_id}:artifact_refs",
            "target_input_key": "上游交接包",
            "usage_instruction": summary,
            "max_chars": 30000,
        },
        "contract_bindings": {
            "schema": {"payload_contract_id": contract_id},
            "handoff": {
                "ack_required": True,
                "ack_policy": "explicit_ack",
                "timeout_policy": "fail_closed",
                "failure_propagation_policy": "fail_downstream",
                "result_delivery_policy": "contract_payload_and_refs",
                "context_filter_policy": {"mode": "explicit_refs_only", "raw_dialogue_handoff": "forbidden"},
            },
            "artifact": {
                "artifact_ref_policy": {
                    "required_for_long_outputs": True,
                    "context_mode": "refs_and_authorized_text",
                    "target_input_key": "上游交接包",
                    "max_chars": 30000,
                }
            },
        },
        "metadata": {
            "managed_by": MANAGED_BY,
            "handoff_summary": summary,
            "packet_kind": "HandoffPacket",
            "input_alias": "上游交接包",
            "model_visible_label": "上游交接包",
            "must_use": True,
            "on_missing": "block",
            "expand_strategy": "refs_and_authorized_text",
        },
    }


def _memory_edges_for_nodes(nodes: tuple[NodeSpec, ...]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    node_by_id = {node.node_id: node for node in nodes}
    for node in nodes:
        for repo_id in node.readable_repositories:
            edges.append(
                _memory_edge(
                    edge_id=f"edge.memory_read.{repo_id}.{node.node_id}",
                    source=repo_id,
                    target=node.node_id,
                    operation="read",
                    collection=_repository_collection(repo_id),
                    topics=node.memory_topics,
                    label=_repository_label(repo_id),
                )
            )
        if node.write_mode in {"baseline_commit"}:
            edges.append(_memory_edge(f"edge.memory_commit.{node.node_id}.baseline", node.node_id, "memory.writing.baseline", "commit", "baseline", node.memory_topics, "基准库提交"))
        elif node.write_mode in MUTABLE_COMMIT_WRITE_MODES:
            edges.append(_memory_edge(f"edge.memory_commit.{node.node_id}.mutable", node.node_id, "memory.writing.mutable", "commit", "mutable", node.memory_topics, "动态记忆提交"))
        if node.write_mode in MANUSCRIPT_COMMIT_WRITE_MODES:
            edges.append(_memory_edge(f"edge.memory_commit.{node.node_id}.manuscript", node.node_id, "memory.writing.manuscript", "commit", "manuscript", node.memory_topics, "正文记忆提交"))
        elif node.write_mode == "review_and_issue_ledger":
            edges.append(_memory_edge(f"edge.issue_commit.{node.node_id}", node.node_id, "memory.writing.issue_ledger", "commit", "issues", node.memory_topics, "问题台账"))
        if node.artifact_paths:
            edges.append(_memory_edge(f"edge.artifact_index.{node.node_id}", node.node_id, "memory.writing.artifact_index", "commit", "artifact_refs", node.memory_topics, "产物索引"))
    return [edge for edge in edges if edge["source_node_id"] in node_by_id or edge["target_node_id"] in node_by_id or edge["source_node_id"].startswith("memory.") or edge["target_node_id"].startswith("memory.")]


def _memory_edge(edge_id: str, source: str, target: str, operation: str, collection: str, topics: tuple[str, ...], label: str) -> dict[str, Any]:
    edge_type = "memory_read" if operation == "read" else "memory_commit"
    repository = source if operation == "read" else target
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_type": edge_type,
        "payload_contract_id": "contract.writing.modular_novel.memory_packet",
        "ack_required": operation != "read",
        "ack_policy": "explicit_ack",
        "result_delivery_policy": "refs_only" if operation == "read" else "contract_payload_and_refs",
        "working_memory_handoff_policy": {
            "operation": operation,
            "repository_node_id": repository,
            "collection": collection,
            "topics": list(topics),
            "carry_kinds": list(topics),
            "carry_scopes": ["writing_modular_novel", collection],
            "model_visible_label": label,
        },
        "contract_bindings": {
            "schema": {"payload_contract_id": "contract.writing.modular_novel.memory_packet"},
            "memory": {
                "operation": operation,
                "repository_node_id": repository,
                "collection": collection,
                "topics": list(topics),
                "carry_kinds": list(topics),
                "carry_scopes": ["writing_modular_novel", collection],
                "model_visible_label": label,
            },
        },
        "metadata": {
            "managed_by": MANAGED_BY,
            "memory_edge_type": operation,
            "repository": repository,
            "collection": collection,
            "record_kinds": list(topics),
            "model_visible_label": label,
            "usage_instruction": f"读取或提交{label}，必须按节点契约使用。",
            "on_missing": "block" if operation == "read" else "warn",
        },
    }


def _revision_edges_for_nodes(nodes: tuple[NodeSpec, ...]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    node_ids = {node.node_id for node in nodes}
    for node in nodes:
        if not node.review_revision_stage_id or node.review_revision_stage_id not in node_ids:
            continue
        edges.append(
            {
                "edge_id": f"edge.revision.{node.node_id}.{node.review_revision_stage_id}",
                "source_node_id": node.node_id,
                "target_node_id": node.review_revision_stage_id,
                "edge_type": "revision_request",
                "payload_contract_id": node.output_contract_id,
                "ack_required": True,
                "ack_policy": "explicit_ack",
                "failure_propagation_policy": "fail_downstream",
                "result_delivery_policy": "contract_payload_and_refs",
                "artifact_ref_policy": {
                    "required_for_long_outputs": True,
                    "context_mode": "refs_and_authorized_text",
                    "target_input_key": "返修交接包",
                    "max_chars": 30000,
                },
                "metadata": {
                    "managed_by": MANAGED_BY,
                    "dependency_role": "repair_feedback",
                    "trigger": {"verdict": "revise"},
                    "carry": [
                        {"input_key": "返修交接包", "source": "current_review"},
                        {"input_key": "previous_candidate_ref", "source": "inherited_input", "from_key": "上游交接包"},
                    ],
                    "clear_input_keys": [],
                    "model_visible_label": "返修交接包",
                },
            }
        )
    return edges


def _artifact_policy(node: NodeSpec) -> dict[str, Any]:
    return {
        "enabled": bool(node.artifact_paths),
        "required": bool(node.artifact_paths),
        "default_artifact_root": ARTIFACT_ROOT,
        "subdir_template": "{project_id}",
        "source": "native_modular_writing_graph.node_spec",
        "artifacts": [
            {
                "path": path,
                "required": True,
                "content_source": "final_content",
                "fallback_to_full_content": True,
            }
            for path in node.artifact_paths
        ],
    }


def _artifact_context_policy(node: NodeSpec, *, include_revision: bool = True) -> dict[str, Any]:
    keys = list(node.artifact_context_keys)
    if include_revision and _is_revision_target(node.node_id) and "返修交接包" not in keys:
        keys.append("返修交接包")
    return {
        "mode": "explicit_model_visible_inputs",
        "default_max_chars": node.artifact_context_max_chars,
        "max_items": max(len(keys), 1),
        "items": [
            {
                "input_key": key,
                "label": key,
                "source": "input_key",
                "max_refs": 8,
                "max_chars": node.artifact_context_max_chars,
                "required": key in node.required_inputs,
            }
            for key in keys
        ],
    }


def _is_revision_target(node_id: str) -> bool:
    return any(node.review_revision_stage_id == node_id for node in (*DESIGN_NODES, *CHAPTER_NODES, *FINALIZE_NODES))


def _node_unit_batch_contract(node: NodeSpec) -> dict[str, Any]:
    if node.node_id != "chapter_draft":
        return {}
    return {
        "unit_kind": "chapter",
        "requested_count": CHAPTER_REQUESTED_COUNT,
        "batch_size": CHAPTER_BATCH_SIZE,
        "range_start": 1,
        "input_contract_id": node.input_contract_id,
        "output_contract_id": node.output_contract_id,
        "target_volumes": TARGET_VOLUMES,
        "chapters_per_volume": CHAPTERS_PER_VOLUME,
        "chapter_target_words": CHAPTER_TARGET_WORDS,
        "batch_target_words": BATCH_TARGET_WORDS,
        "volume_target_words": VOLUME_TARGET_WORDS,
        "metadata": {
            "source": "node.contract_bindings.unit_batch",
            "loop_scope_id": node.loop_scope_id,
            "review_node_id": "chapter_review",
            "commit_node_id": "memory_commit_chapter",
        },
    }


def _node_governance_policy(node: NodeSpec) -> dict[str, Any]:
    return {
        "no_writing_specific_backend_shortcut": True,
        "prompt_is_role_natural_language": True,
        "state_boundary": _state_boundary_policy(node),
        "write_permission_matrix": _write_permission_matrix(node),
        "commit_guard": _commit_guard_policy(node),
        "review_guard": _review_guard_policy(node),
        "memory_pollution_guard": {
            "authority": "task_graph.contract_bound_memory_governance",
            "raw_conversation_history": "forbidden",
            "candidate_artifacts_are_not_committed_memory": True,
            "review_feedback_is_not_canon": True,
            "commit_nodes_are_the_only_memory_authority": True,
            "unreviewed_supplement_cannot_become_fact": True,
        },
        "outline_thread_policy": _outline_thread_policy(node),
    }


def _state_boundary_policy(node: NodeSpec) -> dict[str, Any]:
    state_kind = _node_state_kind(node)
    return {
        "state_kind": state_kind,
        "candidate_state": "model_output_candidate",
        "review_state": "approved_slice_or_revision_request",
        "committed_state": "memory_commit_receipt",
        "allowed_read_states": _allowed_read_states(node),
        "allowed_write_states": _allowed_write_states(node),
        "candidate_visibility": "upstream_handoff_only_until_review",
        "committed_visibility": "after_memory_commit_receipt",
        "raw_dialogue_visibility": "forbidden",
        "on_boundary_violation": "fail_closed",
    }


def _node_state_kind(node: NodeSpec) -> str:
    if node.node_type == "review_gate":
        return "review_gate"
    if node.write_mode in COMMIT_WRITE_MODES:
        return "memory_commit"
    if node.role == "router":
        return "router"
    if node.node_id in OUTLINE_THREAD_INDEX_NODE_IDS:
        return "candidate_with_derived_outline_thread_context"
    return "candidate"


def _allowed_read_states(node: NodeSpec) -> list[str]:
    states = ["committed_memory", "structured_handoff", "artifact_refs"]
    if node.node_type == "review_gate":
        states.extend(["candidate_artifact", "candidate_handoff"])
    if node.write_mode in COMMIT_WRITE_MODES:
        states.extend(["approved_slices", "source_review", "source_candidate_refs"])
    if _outline_thread_policy(node):
        states.append("outline_thread_index")
    return list(dict.fromkeys(states))


def _allowed_write_states(node: NodeSpec) -> list[str]:
    if node.node_type == "review_gate":
        return ["review_verdict", "approved_slices", "revision_request", "issue_ledger_entry", "artifact_refs"]
    if node.write_mode in COMMIT_WRITE_MODES:
        return ["memory_commit_receipt", "artifact_refs", "write_receipts", "outline_thread_execution_state"]
    if node.role == "router":
        return ["route_decision", "progress_observation", "artifact_refs"]
    return ["candidate_artifact", "structured_handoff", "artifact_refs"]


def _write_permission_matrix(node: NodeSpec) -> dict[str, Any]:
    return {
        "mode": node.write_mode,
        "allowed_write_targets": _allowed_write_targets(node),
        "forbidden_write_targets": _forbidden_write_targets(node),
        "artifact_index_write": bool(node.artifact_paths),
        "issue_ledger_write": node.write_mode == "review_and_issue_ledger",
        "baseline_memory_write": node.write_mode == "baseline_commit",
        "mutable_memory_write": node.write_mode in MUTABLE_COMMIT_WRITE_MODES,
        "manuscript_memory_write": node.write_mode in MANUSCRIPT_COMMIT_WRITE_MODES,
        "candidate_archive_write": node.write_mode == "candidate_archive_only",
        "on_forbidden_write": "fail_closed",
    }


def _allowed_write_targets(node: NodeSpec) -> list[str]:
    targets: list[str] = []
    if node.write_mode == "baseline_commit":
        targets.append("memory.writing.baseline")
    elif node.write_mode in MUTABLE_COMMIT_WRITE_MODES:
        targets.append("memory.writing.mutable")
    if node.write_mode in MANUSCRIPT_COMMIT_WRITE_MODES:
        targets.append("memory.writing.manuscript")
    elif node.write_mode == "review_and_issue_ledger":
        targets.append("memory.writing.issue_ledger")
    if node.artifact_paths:
        targets.append("memory.writing.artifact_index")
    return list(dict.fromkeys(targets))


def _forbidden_write_targets(node: NodeSpec) -> list[str]:
    all_targets = ["memory.writing.baseline", "memory.writing.mutable", "memory.writing.manuscript", "memory.writing.issue_ledger"]
    return [target for target in all_targets if target not in _allowed_write_targets(node)]


def _commit_guard_policy(node: NodeSpec) -> dict[str, Any]:
    if node.write_mode not in COMMIT_WRITE_MODES:
        return {"enabled": False}
    source_review_node_id = SOURCE_REVIEW_BY_COMMIT_NODE.get(node.node_id, "")
    source_candidate_node_id = SOURCE_CANDIDATE_BY_COMMIT_NODE.get(node.node_id, "")
    return {
        "enabled": True,
        "source_review_required": bool(source_review_node_id),
        "source_review_node_id": source_review_node_id,
        "source_candidate_node_id": source_candidate_node_id,
        "allowed_review_verdicts": ["pass", "pass_with_notes"],
        "approved_slices_required": True,
        "reject_on_missing_review_receipt": True,
        "reject_on_revise_or_reject_verdict": True,
        "commit_packet_schema": _commit_packet_schema(node),
        "additional_required_refs": ["design_sync_ref"] if node.node_id == "memory_commit_character" else [],
        "barrier_node_id": "design_sync" if node.node_id == "memory_commit_character" else "",
    }


def _review_guard_policy(node: NodeSpec) -> dict[str, Any]:
    if node.node_type != "review_gate":
        return {"enabled": False}
    return {
        "enabled": True,
        "review_target_node_id": node.review_revision_stage_id,
        "review_cannot_mutate_candidate": True,
        "review_cannot_write_canon": True,
        "approved_slices_required_for_commit": True,
        "revision_packet_required_when_not_passed": True,
        "issue_ledger_write_only": node.write_mode == "review_and_issue_ledger",
    }


def _stage_packet_policy(node: NodeSpec) -> dict[str, Any]:
    memory_required = bool(node.memory_topics or node.readable_repositories)
    return {
        "authority": "task_graph.stage_packet_contract",
        "handoff_packet": {
            "raw_dialogue_handoff": "forbidden",
            "artifact_refs_required_for_long_outputs": True,
            "contract_payload_required": True,
        },
        "memory_snapshot": {
            "required_visibility": memory_required,
            "on_hidden": "fail_closed" if memory_required else "ignore",
            "version_selector": "latest_committed_before_stage_start",
            "resolved_records_required_for_read_edges": bool(node.readable_repositories),
        },
        "revision_context": {
            "visible_when_revision_target": _is_revision_target(node.node_id),
            "on_hidden": "fail_closed" if _is_revision_target(node.node_id) else "ignore",
        },
        "artifact_context": {
            "explicit_model_visible_inputs_only": True,
            "authorized_text_expansion_only": True,
        },
        "outline_thread_index": _outline_thread_policy(node),
        "prewrite_memory_plan": _prewrite_memory_plan_policy(node),
        "dynamic_expansion": _dynamic_expansion_policy(node),
    }


def _commit_packet_schema(node: NodeSpec) -> dict[str, Any]:
    fields = [
        "commit_id",
        "source_candidate_ref",
        "source_review_ref",
        "approved_slices",
        "rejected_slices",
        "conflict_checks",
        "write_receipts",
        "downstream_visibility",
        "artifact_refs",
    ]
    if _outline_thread_policy(node):
        fields.extend(["outline_thread_refs", "active_outline_thread_refs", "due_outline_thread_refs"])
    if node.node_id == "memory_commit_chapter":
        fields.extend(
            [
                "approved_chapter_batch_refs",
                "chapter_summaries",
                "manuscript_fact_index",
                "scene_continuity",
                "character_state_deltas",
                "relationship_state_deltas",
                "world_detail_deltas",
                "setting_expansion_candidates",
                "foreshadowing_status_updates",
                "continuity_index",
                "next_batch_memory_requests",
                "must_not_rewrite_facts",
                "review_verdict_receipt",
            ]
        )
    if node.node_id == "volume_commit":
        fields.extend(["volume_summary", "volume_character_state", "volume_thread_status", "next_volume_requirements"])
    if node.node_id == "memory_commit_character":
        fields.extend(["character_review_ref", "design_sync_ref", "approved_character_slices", "rejected_character_slices", "plot_interface_refs"])
    if node.node_id == "extension_commit":
        fields.extend(["world_detail_cards", "character_state_cards", "outline_adjustment_cards", "continuity_correction_cards", "rejected_extension_items", "effective_scope", "expiry_or_review_window", "baseline_upgrade_candidate"])
    return {
        "packet_kind": "WritingMemoryCommitPacket",
        "required_fields": list(dict.fromkeys(fields)),
        "source_candidate_node_id": SOURCE_CANDIDATE_BY_COMMIT_NODE.get(node.node_id, ""),
        "source_review_node_id": SOURCE_REVIEW_BY_COMMIT_NODE.get(node.node_id, ""),
        "write_receipt_required": True,
        "downstream_visibility": "visible_after_commit_receipt",
        "target_repositories": _allowed_write_targets(node),
    }


def _prewrite_memory_plan_policy(node: NodeSpec) -> dict[str, Any]:
    if node.node_id != "chapter_draft":
        return {}
    return {
        "enabled": True,
        "authority": "chapter_writer_self_selects_from_structured_memory_pack",
        "required_before_main_prose": True,
        "output_section": "写前取材记录",
        "max_section_chars": 2500,
        "required_sources": ["memory.writing.baseline", "memory.writing.mutable", "memory.writing.manuscript", "chapter_outline_ref", "volume_plan_ref"],
        "required_fields": [
            "本批叙事目标",
            "采用的世界规则",
            "采用的人物当前状态",
            "上一批承接",
            "正文事实索引",
            "活跃伏笔",
            "到期伏笔",
            "禁改边界",
            "本批不得新增为事实的内容",
        ],
        "main_prose_section_required_after_plan": True,
        "plan_is_not_canon": True,
        "missing_plan_verdict": "review_must_revise_or_reject",
    }


def _dynamic_expansion_policy(node: NodeSpec) -> dict[str, Any]:
    if node.node_id not in {"world_outline_extension_proposal", "extension_review", "extension_commit", "chapter_review", "memory_commit_chapter"}:
        return {}
    return {
        "enabled": True,
        "authority": "reviewed_dynamic_memory_growth",
        "baseline_overwrite_forbidden": True,
        "silent_absorption_forbidden": True,
        "deviation_resolutions": ["revise_source_text", "propose_dynamic_absorption", "return_to_upstream_design"],
        "card_types": ["world_detail_card", "character_state_card", "outline_adjustment_card", "continuity_correction_card"],
        "required_card_fields": ["source_ref", "reason", "affected_scope", "effective_window", "conflict_check", "downstream_usage", "not_baseline_until_reviewed"],
    }


def _outline_thread_policy(node: NodeSpec) -> dict[str, Any]:
    if node.node_id in OUTLINE_THREAD_DESIGN_NODE_IDS:
        return _outline_thread_design_policy(node)
    if node.node_id in OUTLINE_THREAD_INDEX_NODE_IDS:
        return _outline_thread_index_policy(node)
    return {}


def _outline_thread_design_policy(node: NodeSpec) -> dict[str, Any]:
    policy = {
        "authority": "outline_design_committed_canon",
        "mode": "outline_owns_plot_threads",
        "forbid_independent_thread_source": True,
        "required_outline_fields": [
            "outline_thread_refs",
            "thread_type",
            "setup_window",
            "active_window",
            "payoff_window",
            "responsible_volume_or_batch",
            "expected_reader_effect",
            "evidence_refs",
        ],
        "thread_kinds": ["foreshadowing", "mystery", "relationship_arc", "information_reveal", "payoff_chain"],
        "versioning": "outline_versioned_canon",
        "on_missing_outline_threads": "review_or_commit_must_block",
    }
    if node.node_id == "baseline_memory_seed":
        policy = {
            **policy,
            "seed_derived_index_after_commit": True,
            "derived_index_contract": "WritingOutlineThreadIndex",
            "derived_index_fields": ["outline_thread_refs", "active_outline_thread_refs", "due_outline_thread_refs"],
        }
    return policy


def _outline_thread_index_policy(node: NodeSpec) -> dict[str, Any]:
    return {
        "authority": "WritingOutlineThreadIndex",
        "mode": "derived_from_committed_outline",
        "source_outline_refs_required": True,
        "source_outline_version_selector": "current_committed_outline_version",
        "forbid_independent_thread_creation": True,
        "forbid_plot_design_mutation": True,
        "fields": ["outline_thread_refs", "active_outline_thread_refs", "due_outline_thread_refs"],
        "status_values": ["planned", "active", "advanced", "paid_off", "deferred", "cancelled", "invalidated"],
        "stale_policy": "regenerate_or_mark_stale_when_outline_version_changes",
        "due_policy": "review_must_flag_due_threads_without_rewriting_outline",
    }


def _memory_read_policy(node: NodeSpec) -> dict[str, Any]:
    return {
        "mode": "memory_pack_required",
        "access_model": "edge_based_repository_read",
        "memory_scope": "writing_modular_novel",
        "topics": list(node.memory_topics),
        "required_topics": list(node.required_memory_topics),
        "forbidden_topics": list(node.forbidden_topics),
        "readable_repositories": list(node.readable_repositories),
        "readable_scopes": ["writing_modular_novel", "project_state", "node_scope"],
        "summary_only": False,
        "prefer_canonical_text": True,
        "allow_artifact_text_expansion": True,
        "enabled": bool(node.memory_topics or node.readable_repositories),
        "required_visibility": bool(node.memory_topics or node.readable_repositories),
        "on_hidden": "fail_closed" if node.memory_topics or node.readable_repositories else "ignore",
        "snapshot_contract": {
            "packet_kind": "WritingMemorySnapshot",
            "visible_to_agent_required": bool(node.memory_topics or node.readable_repositories),
            "version_selector": "latest_committed_before_stage_start",
            "read_edge_ids_required": bool(node.readable_repositories),
            "raw_conversation_history": "forbidden",
        },
        "token_budget": 40000 if node.node_id in {"chapter_draft", "chapter_review", "volume_review", "final_assemble"} else 20000,
    }


def _dynamic_memory_read_policy(node: NodeSpec) -> dict[str, Any]:
    return {
        "enabled": any(repo_id in node.readable_repositories for repo_id in ("memory.writing.mutable", "memory.writing.manuscript")),
        "memory_scope": "writing_modular_novel",
        "repository_node_id": "memory.writing.mutable",
        "repository_node_ids": [repo_id for repo_id in ("memory.writing.mutable", "memory.writing.manuscript") if repo_id in node.readable_repositories],
        "version_selector": "latest_committed_before_stage_start",
        "summary_only": False,
        "prefer_canonical_text": True,
        "allow_artifact_text_expansion": True,
        "max_dynamic_reads_per_node_run": 8 if node.node_id in {"chapter_draft", "chapter_review", "volume_review", "final_assemble"} else 4,
        "max_temporal_neighbors": 2,
    }


def _memory_write_policy(node: NodeSpec) -> dict[str, Any]:
    is_commit = node.write_mode in COMMIT_WRITE_MODES
    policy = {
        "mode": node.write_mode,
        "access_model": "edge_based_repository_write",
        "memory_scope": "writing_modular_novel",
        "capture_artifact_refs": True,
        "allowed_write_targets": _allowed_write_targets(node),
        "source_review_required": bool(SOURCE_REVIEW_BY_COMMIT_NODE.get(node.node_id)) if is_commit else False,
        "source_review_node_id": SOURCE_REVIEW_BY_COMMIT_NODE.get(node.node_id, ""),
        "source_candidate_node_id": SOURCE_CANDIDATE_BY_COMMIT_NODE.get(node.node_id, ""),
        "approved_slices_required": is_commit,
        "commit_packet_schema": _commit_packet_schema(node) if is_commit else {},
        "writable_scopes": ["writing_modular_novel", "project_state", "node_scope"],
        "write_scope_guard": {
            "baseline_memory_mutable": node.write_mode == "baseline_commit",
            "mutable_memory_mutable": node.write_mode in MUTABLE_COMMIT_WRITE_MODES,
            "manuscript_memory_mutable": node.write_mode in MANUSCRIPT_COMMIT_WRITE_MODES,
            "forbid_frozen_character_rewrite": True,
            "forbid_frozen_relationship_rewrite": True,
            "requires_outline_review_before_baseline": node.node_id == "baseline_memory_seed",
            "review_verdict_required_before_commit": is_commit,
            "forbid_unreviewed_candidate_commit": is_commit,
            "forbid_unreviewed_manuscript_commit": node.write_mode in MANUSCRIPT_COMMIT_WRITE_MODES,
            "on_guard_failure": "fail_closed",
        },
    }
    if node.node_id == "memory_commit_chapter":
        policy["commit_identity_policy"] = {
            "mode": "scope_and_artifact_refs",
            "identity_namespace": "chapter_batch_commit",
            "input_keys": ["volume_index", "batch_start_index", "batch_end_index"],
            "artifact_ref_input_keys": [
                "chapter_draft_ref",
                "chapter_review_ref",
                "previous_candidate_ref",
                "previous_review_ref",
            ],
            "artifact_ref_input_suffixes": [":artifact_refs"],
            "artifact_ref_input_contains": ["chapter_draft", "chapter_review"],
            "fallback_to_result_artifact_refs": True,
        }
    return policy


def _runtime_batch_boundary_policy(node: NodeSpec) -> dict[str, Any]:
    if node.loop_scope_id != "loop.chapter_batch":
        return {}
    return {
        "enabled": True,
        "start_key": "batch_start_index",
        "end_key": "batch_end_index",
        "count_key": "chapters_per_round",
        "list_key": "batch_chapter_list",
        "target_metric_key": "batch_target_words",
        "unit_label": "章",
        "unit_label_prefix": "第",
        "unit_label_suffix": "章",
        "range_template": "本节点只允许处理第{start}章至第{end}章。",
        "list_template": "允许章号清单：{unit_list}。",
        "size_template": "当前运行时每轮批次大小为 {unit_count} 章。",
        "metric_template": "当前批次目标正文量约 {target_metric} 字。",
        "conflict_template": "如果项目启动包、上游旧产物或历史摘要出现其他批次大小或其他章号范围，以本运行时批次边界为准。",
    }


def _replay_sanitization_policy(node: NodeSpec) -> dict[str, Any]:
    if node.node_id != "chapter_draft":
        return {}
    return {
        "trigger_input_keys": ["revision_required", "chapter_revision_requirements"],
        "unit_label": "章",
        "unit_label_prefix": "第",
        "unit_label_suffix": "章",
        "unit_start_key": "batch_start_index",
        "unit_end_key": "batch_end_index",
        "unit_count_key": "chapters_per_round",
        "unit_target_metric_key": "chapter_target_words",
        "unit_list_key": "batch_chapter_list",
        "requirements_key": "chapter_revision_requirements",
        "requirements_template": "第{start}章至第{end}章上一轮审核未通过。本轮必须严格依据最新审核意见重写完整批次，共{count}章；每章约{unit_target}字，只输出完整正文，不要输出摘要、提纲、解释、拒绝、等待补充或工作说明。{review_hint}",
        "review_ref_key": "previous_chapter_review_ref",
        "batch_dir_template": "batch_{batch_index:03d}_chapters_{batch_start_index:03d}_{batch_end_index:03d}",
        "latest_artifact_sources": [
            {
                "input_key": "previous_chapter_review_ref",
                "directory_template": "reviews/chapters/{batch_dir_name}",
                "pattern": "review_round_*.md",
            },
            {
                "input_key": "previous_chapter_draft_ref",
                "directory_template": "chapters/{batch_dir_name}",
                "pattern": "draft_round_*.md",
            },
        ],
        "clear_input_key_contains": ["chapter_draft:artifact_refs"],
        "review_section_names": [
            "裁决",
            "裁决理由",
            "阻塞问题",
            "非阻塞问题",
            "下一轮修改要求",
            "canon一致性检查",
            "承接与推进检查",
            "商业阅读体验检查",
            "爽点与章末追读检查",
        ],
    }


def _quality_retry_policy(node: NodeSpec) -> dict[str, Any]:
    if node.node_id in {"chapter_draft", "chapter_review"}:
        return _chapter_batch_quality_retry_policy()
    return {}


def _review_gate_policy(node: NodeSpec) -> dict[str, Any]:
    if node.node_type != "review_gate":
        return {}
    return {
        "allowed_verdicts": ["pass", "pass_with_notes", "revise", "blocker_found", "reject", "fail_closed"],
        "revision_stage_id": node.review_revision_stage_id,
        "result_delivery_policy": "contract_payload_and_refs",
        "approved_slice_schema": {
            "packet_kind": "WritingReviewApprovedSlices",
            "required_fields": [
                "source_candidate_ref",
                "approved_slices",
                "conditional_notes",
                "rejected_slices",
                "must_not_commit_sections",
                "artifact_refs",
            ],
            "verdicts_allowing_commit": ["pass", "pass_with_notes"],
        },
        "revision_packet_schema": {
            "packet_kind": "WritingRevisionRequest",
            "required_fields": [
                "target_revision_stage_id",
                "source_candidate_ref",
                "blocking_issues",
                "revision_requirements",
                "affected_scope",
                "artifact_refs",
            ],
            "required_when_verdicts": ["revise", "blocker_found", "reject", "fail_closed"],
        },
        "memory_write_permission": {
            "allowed_write_targets": ["memory.writing.issue_ledger", "memory.writing.artifact_index"],
            "forbid_baseline_write": True,
            "forbid_mutable_write": True,
        },
    }


def _loop_policy(node: NodeSpec) -> dict[str, Any]:
    if not node.loop_scope_id:
        return {}
    return {
        "loop_kind": "bounded_metric_iteration",
        "loop_variable": "batch_start_index" if node.loop_scope_id == "loop.chapter_batch" else "volume_index",
        "iteration_size_key": "chapters_per_round" if node.loop_scope_id == "loop.chapter_batch" else "target_volumes",
        "iteration_size": CHAPTER_BATCH_SIZE if node.loop_scope_id == "loop.chapter_batch" else TARGET_VOLUMES,
        "exit_decision": "volume_target_reached" if node.loop_scope_id == "loop.chapter_batch" else "target_volumes_reached",
    }


def _executor_policy(node: NodeSpec) -> dict[str, Any]:
    return {
        "default_executor": "agent",
        "allowed_executors": ["agent"],
        "operation_policy": _node_operation_policy(node_id=node.node_id),
    }


def _node_operation_policy(*, node_id: str) -> dict[str, Any]:
    allowed = ["op.model_response", "op.memory_read"]
    optional: list[str] = []
    if node_id in {"chapter_draft", "chapter_review", "volume_review", "final_review", "chapter_progress_router"}:
        allowed.append("op.text_metric")
        optional.append("op.text_metric")
    return {
        "authority": "task_graph.contract_bound_operation_policy",
        "allowed_operations": allowed,
        "required_operations": [],
        "optional_operations": optional,
        "denied_operations": [
            "op.read_file",
            "op.search_files",
            "op.search_text",
            "op.read_structured_file",
            "op.shell",
            "op.python_repl",
            "op.delegate_to_agent",
            "op.web_search",
            "op.fetch_url",
            "op.write_file",
            "op.edit_file",
        ],
    }


def _upsert_master_graph(registry: TaskFlowRegistry) -> None:
    nodes = (
        _graph_module_node("graph_module.design_init", "设计初始化图", DESIGN_GRAPH_ID, "phase.master.design_init", 10),
        _graph_module_node("graph_module.chapter_cycle", "章节批次创作图", CHAPTER_GRAPH_ID, "phase.master.chapter_cycle", 20),
        _graph_module_node("graph_module.finalize", "收尾交付图", FINALIZE_GRAPH_ID, "phase.master.finalize", 30),
    )
    edges = (
        _master_edge("edge.design_init.chapter_cycle", "graph_module.design_init", "graph_module.chapter_cycle", "设计初始化提交后进入章节批次创作。"),
        _master_edge("edge.chapter_cycle.finalize", "graph_module.chapter_cycle", "graph_module.finalize", "目标卷数完成并形成卷级提交后进入收尾交付。"),
    )
    timeline_blocks = (
        _timeline_block("design_init", "设计初始化图", DESIGN_GRAPH_ID, "phase.master.design_init", 10),
        _timeline_block("chapter_cycle", "章节批次创作图", CHAPTER_GRAPH_ID, "phase.master.chapter_cycle", 20),
        _timeline_block("finalize", "收尾交付图", FINALIZE_GRAPH_ID, "phase.master.finalize", 30),
    )
    registry.upsert_task_graph(
        graph_id=MASTER_GRAPH_ID,
        title="模块化长篇写作总任务图",
        domain_id=DOMAIN_ID,
        task_family=TASK_FAMILY,
        graph_kind="coordination",
        entry_node_id="graph_module.design_init",
        output_node_id="graph_module.finalize",
        nodes=nodes,
        edges=edges,
        graph_contract_id="contract.writing.modular_novel.graph",
        contract_bindings={
            "schema": {"graph_contract_id": "contract.writing.modular_novel.graph"},
            "runtime": {
                "graph_module_composition": {"mode": "sequential_graph_module_runtime", "graph_module_count": 3, "imported_run_scope": "isolated_per_graph_module_run"},
            },
            "governance": {"no_writing_specific_backend_shortcut": True, "contract_source": "contract_bindings"},
        },
        default_protocol_id=PROTOCOL_ID,
        working_memory_policy_profile_id="wmprofile.writing.modular_novel",
        working_memory_policy={
            "memory_scope": "writing_modular_novel",
            "access_model": "graph_module_committed_refs_only",
            "conversation_memory": "suppressed_for_creator_and_reviewer",
            "raw_full_text_global_context": "forbidden",
        },
        runtime_policy=_runtime_policy(),
        context_policy={"handoff": "contract_payload_and_refs", "raw_dialogue_handoff": "forbidden", "long_text_policy": "artifact_ref_with_authorized_expansion"},
        publish_state="published",
        enabled=True,
        metadata={
            "managed_by": MANAGED_BY,
            "architecture": "graph_as_first_class_task_unit",
            "graph_module_composition": True,
            "timeline_blocks": list(timeline_blocks),
            "phase_definitions": [
                {"phase_id": "phase.master.design_init", "title": "设计初始化", "sequence_index": 10},
                {"phase_id": "phase.master.chapter_cycle", "title": "分卷创作循环", "sequence_index": 20},
                {"phase_id": "phase.master.finalize", "title": "收尾交付", "sequence_index": 30},
            ],
            "runtime_loop_policy": {
                "enabled": True,
                "flow_control": "graph_module_sequence",
                "initial_inputs": _chapter_initial_runtime_loop_inputs(),
                "frames": [
                    {"frame_id": "graph_module.design_init", "entry_stage_id": "graph_module.design_init", "exit_stage_id": "graph_module.chapter_cycle"},
                    {"frame_id": "graph_module.chapter_cycle", "entry_stage_id": "graph_module.chapter_cycle", "exit_stage_id": "graph_module.finalize"},
                ],
            },
            "graph_module_refs": [DESIGN_GRAPH_ID, CHAPTER_GRAPH_ID, FINALIZE_GRAPH_ID],
            "editor_publish_state": "published",
        },
    )


def _graph_module_node(node_id: str, title: str, linked_graph_id: str, phase_id: str, sequence_index: int) -> dict[str, Any]:
    block_id = node_id.removeprefix("graph_module.")
    return {
        "node_id": node_id,
        "node_type": "graph_module",
        "title": title,
        "phase_id": phase_id,
        "sequence_index": sequence_index,
        "execution_mode": "async",
        "wait_policy": "wait_all_upstream_completed",
        "join_policy": "all_success",
        "blocks_phase_exit": True,
        "executor_policy": {
            "default_executor": "graph_module",
            "allowed_executors": ["graph_module"],
            "linked_graph_id": linked_graph_id,
            "imported_graph_id": linked_graph_id,
            "auto_start_imported_initial_stage": True,
        },
        "context_visibility_policy": {"shared_context_policy": "explicit_refs_only", "graph_module_runtime_visibility": "committed_only", "importing_visible_scope": "run_handle_and_committed_output"},
        "contract_bindings": {
            "schema": {"input_contract_id": "contract.user_request.basic", "output_contract_id": _graph_contract_id(linked_graph_id)},
            "execution": {"node_contract_id": "contract.writing.modular_novel.graph_module_handoff"},
            "handoff": {"handoff_contract_id": "contract.writing.modular_novel.graph_module_handoff", "visibility_policy": "committed_only"},
            "runtime": {"graph_module_runtime": {"linked_graph_id": linked_graph_id, "version_ref": "published", "isolation_policy": "isolated_per_graph_module_run"}},
        },
        "metadata": {
            "managed_by": MANAGED_BY,
            "graph_module": True,
            "runtime_role": "graph_module_container",
            "model_visible": False,
            "linked_graph_id": linked_graph_id,
            "version_ref": "published",
            "handoff_contract_id": "contract.writing.modular_novel.graph_module_handoff",
            "input_port_id": "input.default",
            "output_port_id": "output.default",
            "isolation_policy": "isolated_per_graph_module_run",
            "visibility_policy": "committed_only",
            "detach_policy": "preserve_version_anchor",
            "execution_mode": "graph_module_run",
            "graph_module_runtime_plan_id": f"graph_module_runtime.{block_id}",
        },
    }


def _master_edge(edge_id: str, source: str, target: str, summary: str) -> dict[str, Any]:
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_type": "structured_handoff",
        "payload_contract_id": "contract.writing.modular_novel.graph_module_handoff",
        "ack_policy": "explicit_ack",
        "ack_required": True,
        "failure_propagation_policy": "fail_downstream",
        "result_delivery_policy": "contract_payload_and_refs",
        "contract_bindings": {
            "schema": {"payload_contract_id": "contract.writing.modular_novel.graph_module_handoff"},
            "handoff": {"handoff_contract_id": "contract.writing.modular_novel.graph_module_handoff", "trigger_timing": "after_source_commit", "visibility_policy": "committed_only"},
            "temporal": {"trigger_timing": "after_source_commit", "visibility_timing": "committed_only", "propagation_timing": "next_graph_module"},
        },
        "metadata": {"managed_by": MANAGED_BY, "handoff_summary": summary, "required_refs": ["committed_output_refs", "imported_run_ref"], "dependency_role": "graph_module_sequence", "temporal_semantics": {"trigger_timing": "after_source_commit", "visibility_timing": "committed_only"}},
    }


def _timeline_block(block_id: str, title: str, linked_graph_id: str, phase_id: str, sequence_index: int) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "block_type": "graph_module",
        "title": title,
        "phase_id": phase_id,
        "linked_graph_id": linked_graph_id,
        "version_ref": "published",
        "input_port_id": "input.default",
        "output_port_id": "output.default",
        "isolation_policy": "isolated_per_graph_module_run",
        "visibility_policy": "committed_only",
        "detach_policy": "preserve_version_anchor",
        "contract_bindings": {"handoff": {"handoff_contract_id": "contract.writing.modular_novel.graph_module_handoff"}, "runtime": {"sequence_index": sequence_index}},
        "metadata": {"managed_by": MANAGED_BY, "sequence_index": sequence_index},
    }


def _runtime_policy() -> dict[str, Any]:
    return {
        "execution_mode": "coordinator_driven",
        "coordinator_agent_id": "agent:0",
        "agent_group_id": AGENT_GROUP_ID,
        "default_execution_mode": "sync",
        "default_wait_policy": "wait_all_upstream_completed",
        "default_join_policy": "all_success",
        "human_gate_mode": "auto_continue",
        "task_run_scope_policy": "isolated_per_task_run",
        "failure_policy": "fail_closed",
        "working_memory_profile_id": "wmprofile.writing.modular_novel",
    }


def _working_memory_policy() -> dict[str, Any]:
    return {
        "memory_scope": "writing_modular_novel",
        "access_model": "edge_based_repository_access",
        "repository_node_ids": [item["node_id"] for item in REPOSITORY_NODES],
        "conversation_memory": "suppressed_for_creator_and_reviewer",
        "raw_full_text_global_context": "forbidden",
        "scheduler_binding": "memory_edges_are_context_edges_not_business_steps",
        "graph_module_boundary": "committed_refs_only",
        "libraries": {
            "baseline_memory": {
                "repository_node_id": "memory.writing.baseline",
                "write_authority": "memory_commit_edges_only",
                "read_authority": "memory_read_edges_only",
                "mutable": False,
                "library_role": "read_only_canon_baseline",
            },
            "mutable_memory": {
                "repository_node_id": "memory.writing.mutable",
                "write_authority": "extension_commit_memory_commit_edges",
                "read_authority": "memory_read_edges_only",
                "mutable": True,
                "library_role": "post_volume_adjustment_layer",
            },
            "manuscript_memory": {
                "repository_node_id": "memory.writing.manuscript",
                "write_authority": "chapter_commit_memory_commit_edges",
                "read_authority": "memory_read_edges_only",
                "mutable": True,
                "library_role": "approved_manuscript_and_summary_layer",
            },
        },
    }


def _graph_contract_bindings(graph_id: str) -> dict[str, Any]:
    bindings: dict[str, Any] = {
        "schema": {"graph_contract_id": _graph_contract_id(graph_id)},
        "runtime": {"model_requirement": _model_requirement(graph_id.rsplit(".", 1)[-1])},
        "memory": {"working_memory_policy": _working_memory_policy()},
        "handoff": {"context_policy": {"handoff": "contract_payload_and_refs", "raw_dialogue_handoff": "forbidden", "long_text_policy": "artifact_ref_with_authorized_expansion"}},
        "governance": {"no_writing_specific_backend_shortcut": True, "contract_source": "contract_bindings"},
    }
    if graph_id == CHAPTER_GRAPH_ID:
        bindings["unit_batch"] = _chapter_unit_batch_contract()
        bindings["runtime"] = {
            **dict(bindings["runtime"]),
            "loop_policy_ref": "metadata.runtime_loop_policy",
            "split_policy": {"mode": "static_batch", "batch_size": CHAPTER_BATCH_SIZE, "range_label_template": "chapter_{start}_{end}", "source": "graph.contract_bindings.runtime.split_policy"},
            "length_budget": _length_budget_contract("volume", VOLUME_TARGET_WORDS, VOLUME_MIN_WORDS, VOLUME_MAX_WORDS, CHAPTERS_PER_VOLUME, "graph.contract_bindings.runtime.length_budget"),
        }
    return bindings


def _chapter_unit_batch_contract() -> dict[str, Any]:
    return {
        "unit_kind": "chapter",
        "requested_count": CHAPTER_REQUESTED_COUNT,
        "batch_size": CHAPTER_BATCH_SIZE,
        "range_start": 1,
        "target_volumes": TARGET_VOLUMES,
        "chapters_per_volume": CHAPTERS_PER_VOLUME,
        "chapter_target_words": CHAPTER_TARGET_WORDS,
        "batch_target_words": BATCH_TARGET_WORDS,
        "volume_target_words": VOLUME_TARGET_WORDS,
        "unit_label_zh": "章节",
        "source": "metadata.runtime_loop_policy.initial_inputs",
    }


def _chapter_runtime_loop_policy() -> dict[str, Any]:
    return {
        "enabled": True,
        "loop_owner": "graph",
        "flow_control": "chapter_batch_and_volume_frames",
        "initial_inputs": _chapter_initial_runtime_loop_inputs(),
        "derived_fields": _chapter_loop_derived_fields(),
        "summary": "当前卷：{volume_label}；当前批次：{batch_label}；本批允许范围：{batch_chapter_list}；本次目标 {target_volumes} 卷；全书累计约 {current_words}/{target_words} 字；本卷累计约 {volume_current_words}/{volume_target_words} 字。",
        "frames": [
            {"frame_id": "loop.chapter_batch", "title": "章节批次循环", "entry_stage_id": "chapter_outline", "router_stage_id": "chapter_progress_router", "continue_stage_id": "chapter_outline", "exit_stage_id": "volume_review", "unit_kind": "chapter", "iteration_size_key": "chapters_per_round"},
            {"frame_id": "loop.volume", "title": "分卷大循环", "entry_stage_id": "volume_plan", "router_stage_id": "next_volume_router", "continue_stage_id": "volume_plan", "exit_stage_id": "__graph_module_complete__", "unit_kind": "volume", "iteration_size_key": "target_volumes"},
        ],
    }


def _chapter_initial_runtime_loop_inputs() -> dict[str, Any]:
    return {
        "target_volumes": TARGET_VOLUMES,
        "volume_index": 1,
        "completed_volumes": 0,
        "volume_current_words": 0,
        "volume_target_words": VOLUME_TARGET_WORDS,
        "chapters_per_volume": CHAPTERS_PER_VOLUME,
        "chapter_index": 1,
        "chapters_per_round": CHAPTER_BATCH_SIZE,
        "chapter_batch_size": CHAPTER_BATCH_SIZE,
        "target_chapters": CHAPTER_REQUESTED_COUNT,
        "metric_label": "words",
        "target_metric_total": TARGET_WORDS,
        "target_words": TARGET_WORDS,
        "current_words": 0,
        "chapter_target_words": CHAPTER_TARGET_WORDS,
    }


def _model_requirement(node_id: str) -> dict[str, Any]:
    preferred = 65536 if node_id in {"chapter_draft", "chapter_cycle"} else 32768 if node_id in {"volume_plan", "final_assemble"} else 16384
    return {
        "profile_ref": MODEL_PROFILE_REF,
        "provider_family": "deepseek",
        "model_family": "deepseek-v4",
        "capability_tags": ["long_output", "structured_artifact_refs", "creative_writing"],
        "min_context_tokens": 200000,
        "min_output_tokens": 8192,
        "preferred_output_tokens": preferred,
        "streaming_required": True,
        "fallback_allowed": True,
        "metadata": {"configured_by": MANAGED_BY, "node_id": node_id},
    }


def _graph_contract_id(graph_id: str) -> str:
    if graph_id == DESIGN_GRAPH_ID:
        return "contract.writing.modular_novel.design_commit"
    if graph_id == CHAPTER_GRAPH_ID:
        return "contract.writing.modular_novel.chapter_cycle_commit"
    if graph_id == FINALIZE_GRAPH_ID:
        return "contract.writing.modular_novel.final_delivery"
    return "contract.writing.modular_novel.graph"


def _graph_title(graph_id: str) -> str:
    return {
        DESIGN_GRAPH_ID: "设计初始化任务图",
        CHAPTER_GRAPH_ID: "章节批次创作任务图",
        FINALIZE_GRAPH_ID: "收尾交付任务图",
        MASTER_GRAPH_ID: "模块化长篇写作总任务图",
    }[graph_id]


def _phase_definitions_for_nodes(nodes: tuple[NodeSpec, ...]) -> list[dict[str, Any]]:
    phases: dict[str, dict[str, Any]] = {}
    for node in nodes:
        phases.setdefault(node.phase_id, {"phase_id": node.phase_id, "title": node.phase_id.removeprefix("phase.modular."), "sequence_index": node.sequence_index})
    return list(phases.values())


def _node_task_id(node_id: str) -> str:
    return f"task.writing.modular_novel.node.{_safe_id(node_id)}"


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value or "")).strip("_")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure native modular writing task graphs.")
    parser.add_argument("--base-dir", default=str(BACKEND_DIR), help="Backend dir or project root. Defaults to repo backend.")
    args = parser.parse_args()
    configure(Path(args.base_dir))


if __name__ == "__main__":
    main()
