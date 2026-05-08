import json
import urllib.error
import urllib.request
from typing import Any

BASE = "http://127.0.0.1:8000/api"


def request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def contract(contract_id: str, title: str, kind: str, fields: list[dict[str, Any]], description: str) -> dict[str, Any]:
    output_fields = [
        {
            "field_id": field["field_id"],
            "title_zh": field["title_zh"],
            "field_type": field.get("field_type", "string"),
            "required": field.get("required", True),
            "description": field.get("description", ""),
            "schema": field.get("schema", {}),
            "source_hint": field.get("source_hint", "upstream_output"),
            "visibility": field.get("visibility", "model_visible"),
        }
        for field in fields
    ]
    return {
        "contract_id": contract_id,
        "title_zh": title,
        "title_en": contract_id.split(".")[-1],
        "contract_kind": kind,
        "description": description,
        "input_fields": [],
        "output_fields": output_fields,
        "artifact_requirements": [],
        "acceptance_rules": [
            {
                "rule_id": f"{field['field_id']}_present",
                "title_zh": f"{field['title_zh']}必须存在",
                "rule_type": "required_field_present",
                "severity": "error",
                "target_field": field["field_id"],
                "criteria": f"{field['title_zh']}不能为空。",
                "config": {},
            }
            for field in output_fields
            if field.get("required", True)
        ],
        "runtime_requirements": [],
        "context_visibility_policy": {
            "main_session_history": "summary",
            "upstream_outputs": "summary",
            "sibling_nodes": "status_only",
            "artifact_access": "refs_only",
            "memory_scopes": [],
            "model_visible_sections": ["task", "runtime_contracts", "working_memory"],
            "hidden_sections": [],
            "notes": "",
        },
        "handoff_policy": {
            "handoff_mode": "structured_handoff",
            "include_artifact_refs": True,
            "include_raw_messages": False,
            "ack_required": True,
            "timeout_policy": "fail_closed",
        },
        "failure_policy": {
            "failure_mode": "fail_closed",
            "retry_allowed": True,
            "retry_limit": 1,
            "escalate_to": "coordinator",
            "fallback_contract_id": "contract.error_report.basic",
        },
        "human_gate_policy": {"required": False, "gate_type": "none", "reviewer_role": "", "decision_contract_id": ""},
        "allowed_agent_kinds": ["worker_sub_agent"],
        "allowed_runtime_lanes": ["longform_novel_graph"],
        "version": "1.0.0",
        "enabled": True,
        "metadata": {"managed_by": "task_package_wizard", "package_template": "longform_novel_writing"},
    }


PROMPTS = {
    "showrunner": "你是长篇小说任务的 Showrunner。你的职责不是直接写完整章节，而是维护整部作品的创作秩序。\n\n你必须：\n1. 把用户的创作目标拆成可执行阶段。\n2. 维护卷、章、角色线、世界线、风格线之间的一致性。\n3. 调度规划、写作、审查、修订、整理节点。\n4. 只采纳经过契约和连续性检查的工作记忆。\n5. 对冲突生成明确的返修指令，而不是直接覆盖旧事实。\n6. 把任务内长期有效的设定交给 Memory Publisher 形成 Task Durable 候选。\n\n你禁止：\n1. 跳过审查直接宣布全书完成。\n2. 把章节草稿、人物设定、世界观资产写入 Global Durable。\n3. 让下游 Agent 直接把 handoff 文本当作共享事实。\n\n你的输出必须符合当前节点绑定的契约。",
    "story_architect": "你是长篇小说的故事架构师。你负责把世界观、剧情结构、角色弧线和章节计划整合成可执行的创作蓝图。\n\n你必须：\n1. 输出世界规则、角色基线、卷纲、章节目标和关键转折。\n2. 每个章节目标都必须能交给 Chapter Writer 执行。\n3. 伏笔必须带 foreshadow_track，并声明预计回收位置。\n4. 修改剧情时必须说明影响到的人物状态、世界状态和时间线。\n5. 把稳定设定写成 working memory candidate，把长期有效资产标记为 promotion_candidate。\n6. 避免一次性写过多不可执行的百科。\n\n你禁止：\n1. 只写抽象主题而没有章节执行目标。\n2. 随意推翻已 accepted 的剧情事实。\n3. 绕过 Coordinator 采纳设定。\n4. 把世界观、人物、剧情资产直接提交 Global Durable。",
    "chapter_writer": "你是长篇小说的章节写作 Agent。你负责根据章节目标、角色状态、世界规则和风格约束写出章节草稿，并在修订轮次中完成正文改写。\n\n你必须：\n1. 只围绕当前 node_run 对应章节写作。\n2. 遵守 chapter_brief、character_state、world_state、style_constraint 和 revision_instruction。\n3. 输出 chapter_draft，并标记本章新增事实。\n4. 对新增人物状态、世界状态、伏笔提交候选。\n5. 遇到设定矛盾时提交 conflict_hint，而不是自行确认新事实。\n6. 修订时只处理 revision_gate 明确要求的部分。\n\n你禁止：\n1. 私自改动总大纲。\n2. 私自确认新的世界规则。\n3. 把草稿当作 accepted working fact。\n4. 跨章节读取不在策略允许范围内的私有草稿。",
    "continuity_editor": "你是长篇小说的连续性审校 Agent。你的职责是发现事实、人物、世界观、时间线、伏笔和文风节奏上的问题，不直接改写章节正文。\n\n你必须：\n1. 检查章节草稿与已 accepted 设定是否冲突。\n2. 检查角色状态、世界规则、时间线、伏笔是否自洽。\n3. 检查章节节奏、视角和语言风格是否破坏既定风格约束。\n4. 输出 evaluator_feedback、continuity_conflict 和 revision_instruction。\n5. 不确定时标记 needs_human_review 或 coordinator_decision。\n\n你禁止：\n1. 直接改写章节正文。\n2. 因个人审美否定契约内合格内容。\n3. 把未采纳的审查意见写成 accepted fact。",
    "memory_publisher": "你是长篇小说任务的记忆与交付管理 Agent。你负责把通过修订决策的工作记忆收束为任务长期记忆候选，并在任务末期整理最终交付包。\n\n你必须：\n1. 区分草稿、已采纳事实、冲突、审查意见和长期资产。\n2. 将人物设定、世界规则、时间线、风格约束整理为 promotion_candidate。\n3. 保留 source_work_memory_ids。\n4. 对不稳定草稿标记 archive 或 discard。\n5. 默认只晋升 Task Durable，不进入 Global Durable。\n6. 最终交付时只收集 accepted / archived / promoted_to_task_durable 的稳定内容。\n7. 输出 final_manuscript_package，并标注未解决冲突和未完成章节。\n\n你禁止：\n1. 把 chapter_draft 直接当成稳定设定。\n2. 丢失来源引用。\n3. 把任务资产写入主 Agent 长期记忆。\n4. 自行补写缺失章节。\n5. 忽略 unresolved conflict。\n6. 把私有审查草稿暴露为最终内容。",
}

AGENTS = [
    ("showrunner", "agent:novel_showrunner", "长篇小说总协调", "projection.longform_novel.showrunner", ["contract.novel.project_brief", "contract.novel.project_plan"], ["op.model_response", "op.memory_read", "op.memory_write_candidate", "op.artifact_result_ref"], ["working_memory.task_read", "working_memory.graph_read_write", "task_durable.read_candidate"]),
    ("story_architect", "agent:novel_story_architect", "故事架构师", "projection.longform_novel.story_architect", ["contract.novel.volume_outline", "contract.novel.chapter_brief", "contract.novel.world_bible_delta", "contract.novel.character_delta"], ["op.model_response", "op.memory_read", "op.memory_write_candidate"], ["working_memory.task_read", "working_memory.graph_read_write", "task_durable.read_candidate"]),
    ("chapter_writer", "agent:novel_chapter_writer", "章节写作 Agent", "projection.longform_novel.chapter_writer", ["contract.novel.chapter_draft"], ["op.model_response", "op.memory_read", "op.memory_write_candidate", "op.artifact_result_ref"], ["working_memory.handoff_read", "working_memory.node_write", "artifact.write_ref"]),
    ("continuity_editor", "agent:novel_continuity_editor", "连续性审校 Agent", "projection.longform_novel.continuity_editor", ["contract.novel.continuity_review"], ["op.model_response", "op.memory_read", "op.memory_write_candidate"], ["working_memory.task_read", "working_memory.graph_read_write", "working_memory.edge_write"]),
    ("memory_publisher", "agent:novel_memory_publisher", "记忆与交付管理 Agent", "projection.longform_novel.memory_publisher", ["contract.novel.memory_promotion_batch", "contract.novel.final_manuscript_package"], ["op.model_response", "op.memory_read", "op.memory_write_candidate", "op.artifact_result_ref"], ["working_memory.accepted_read", "task_durable.write_candidate", "artifact.read_write_ref"]),
]


def configure_projections_and_agents() -> None:
    for key, agent_id, title, projection_id, contracts, operations, memory_scopes in AGENTS:
        prompt = PROMPTS[key]
        request("POST", "/soul/projections", {
            "projection_id": projection_id,
            "soul_id": "goumang",
            "projection_name": title,
            "role_type": "longform_novel_agent",
            "task_mode": "longform_novel_graph",
            "agent_profile_id": agent_id,
            "projection_nodes": [{"id": "projection-node-identity-anchor-0", "type": "identity_anchor", "title": "身份锚点", "content": prompt}],
            "identity_anchor": prompt,
            "projection_prompt": "",
            "posture_tags": ["longform_novel", key],
            "attention_focus": ["contract_bound_output", "working_memory_governance"],
            "risk_notes": ["不写入 Global Durable", "不绕过任务图和契约"],
            "usage_summary": f"{title}的长篇小说专属投影。",
            "memory_policy_summary": "只能按任务图节点策略读取/提交工作记忆候选。",
            "output_contract_summary": "输出必须符合任务图节点绑定 ContractSpec。",
            "select_after_create": False,
        })
        request("PUT", f"/orchestration/agents/{agent_id}", {
            "agent_id": agent_id,
            "agent_name": title,
            "agent_category": "worker_sub_agent",
            "interface_target": "task_graph_node",
            "description": f"长篇小说核心团队成员：{title}。具体角色 prompt 由专属投影承载。",
            "enabled": True,
            "editable": True,
            "default_soul_id": "goumang",
            "default_projection_id": projection_id,
            "metadata": {"task_family": "longform_novel_writing", "managed_by": "frontend_configuration", "projection_owner": "soul_projection"},
        })
        request("PUT", f"/orchestration/agents/{agent_id}/runtime-profile", {
            "agent_profile_id": agent_id,
            "allowed_task_modes": ["longform_novel_graph", "longform_novel_writing"],
            "allowed_runtime_lanes": ["longform_novel_graph"],
            "allowed_operations": operations,
            "blocked_operations": ["op.write_global_durable", "op.direct_storage_write"],
            "allowed_memory_scopes": memory_scopes,
            "allowed_context_sections": ["task", "runtime_contracts", "working_memory", "task_durable_memory", "upstream_outputs", "artifact_refs", "runtime_trace", "projection"],
            "output_contracts": contracts,
            "approval_policy": "manual_approval_required",
            "trace_policy": "runtime_event_log",
            "lifecycle_policy": "orchestration_managed",
            "metadata": {"task_family": "longform_novel_writing", "projection_id": projection_id},
        })
    request("PUT", "/orchestration/agent-groups/group.longform_novel_core_team", {
        "group_id": "group.longform_novel_core_team",
        "title": "长篇小说核心创作组",
        "group_kind": "coordination_team",
        "coordinator_agent_id": "agent:novel_showrunner",
        "member_agent_ids": [item[1] for item in AGENTS[1:]],
        "description": "五人核心长篇小说创作团队，所有成员通过专属投影承载角色 prompt。",
        "default_topology_template_ids": ["topology.longform_novel.production_graph"],
        "default_communication_protocol_ids": ["protocol.longform_novel.a2a_handoff"],
        "allowed_coordination_task_ids": ["coord.longform_novel.core_production"],
        "lifecycle_state": "enabled",
        "metadata": {"task_family": "longform_novel_writing", "managed_by": "frontend_configuration"},
    })


CONTRACTS = [
    contract("contract.novel.project_brief", "长篇小说项目简报", "global_task", [{"field_id": "title", "title_zh": "作品标题", "required": False}, {"field_id": "genre", "title_zh": "题材类型"}, {"field_id": "target_length", "title_zh": "目标篇幅"}, {"field_id": "core_premise", "title_zh": "核心设定"}, {"field_id": "constraints", "title_zh": "创作约束", "field_type": "array", "required": False}], "长篇小说任务的项目级输入边界。"),
    contract("contract.novel.project_plan", "长篇小说生产计划", "workflow", [{"field_id": "volume_plan", "title_zh": "分卷计划", "field_type": "array"}, {"field_id": "chapter_count", "title_zh": "章节数量", "field_type": "number"}, {"field_id": "quality_gates", "title_zh": "质量门控", "field_type": "array"}], "由 Showrunner 输出的整体生产计划。"),
    contract("contract.novel.world_bible_delta", "世界观设定增量", "node_execution", [{"field_id": "world_rules", "title_zh": "世界规则", "field_type": "array"}, {"field_id": "setting_delta", "title_zh": "设定变更", "field_type": "array"}, {"field_id": "conflict_risks", "title_zh": "冲突风险", "field_type": "array", "required": False}], "故事架构阶段输出的世界观设定增量。"),
    contract("contract.novel.volume_outline", "分卷与章节大纲", "node_execution", [{"field_id": "volume_outline", "title_zh": "分卷大纲", "field_type": "array"}, {"field_id": "chapter_briefs", "title_zh": "章节简报", "field_type": "array"}, {"field_id": "foreshadow_track", "title_zh": "伏笔账本", "field_type": "array", "required": False}], "故事架构阶段输出的分卷、章节和伏笔规划。"),
    contract("contract.novel.character_delta", "角色连续性增量", "node_execution", [{"field_id": "character_states", "title_zh": "角色状态", "field_type": "array"}, {"field_id": "relationship_delta", "title_zh": "关系变化", "field_type": "array"}, {"field_id": "arc_risks", "title_zh": "人物弧风险", "field_type": "array", "required": False}], "故事架构与章节审校阶段输出的角色状态增量。"),
    contract("contract.novel.chapter_brief", "章节写作简报", "edge_handoff", [{"field_id": "chapter_index", "title_zh": "章节序号", "field_type": "number"}, {"field_id": "scene_goals", "title_zh": "场景目标", "field_type": "array"}, {"field_id": "required_memory_refs", "title_zh": "必需记忆引用", "field_type": "array"}], "章节计划到章节写作的交接契约。"),
    contract("contract.novel.chapter_draft", "章节草稿", "node_execution", [{"field_id": "chapter_index", "title_zh": "章节序号", "field_type": "number"}, {"field_id": "chapter_text", "title_zh": "章节正文"}, {"field_id": "new_facts", "title_zh": "新增事实", "field_type": "array", "required": False}], "章节写作阶段输出。"),
    contract("contract.novel.continuity_review", "连续性审查报告", "node_execution", [{"field_id": "conflicts", "title_zh": "连续性冲突", "field_type": "array"}, {"field_id": "severity", "title_zh": "严重程度"}, {"field_id": "fix_suggestions", "title_zh": "修复建议", "field_type": "array"}], "连续性审校阶段输出。"),
    contract("contract.novel.memory_promotion_batch", "任务记忆晋升批次", "node_execution", [{"field_id": "promotion_candidates", "title_zh": "晋升候选", "field_type": "array"}, {"field_id": "rejected_items", "title_zh": "拒绝项", "field_type": "array", "required": False}, {"field_id": "review_required", "title_zh": "是否需要人工复核", "field_type": "boolean"}], "记忆与交付管理阶段输出。"),
    contract("contract.novel.final_manuscript_package", "最终稿件交付包", "final_output", [{"field_id": "manuscript_refs", "title_zh": "正文产物引用", "field_type": "array"}, {"field_id": "bible_refs", "title_zh": "设定集引用", "field_type": "array"}, {"field_id": "unresolved_issues", "title_zh": "未解决问题", "field_type": "array", "required": False}], "长篇小说任务最终交付契约。"),
]


def sched(node_id: str) -> dict[str, Any]:
    base = {"execution_mode": "sync", "dispatch_group": "", "wait_policy": "wait_all_upstream_completed", "join_policy": "all_success", "background_policy": {"enabled": False, "blocks_downstream": True}, "notification_policy": {"on_started": "event_only", "on_completed": "event_only", "on_failed": "queued_alert", "include_result": "summary_and_refs", "priority": "next"}, "resource_lifecycle_policy": {"kill_on_parent_abort": True, "cleanup_on_terminal": True}, "human_gate_policy": {}, "failure_policy": {"on_contract_error": "retry_structure_only_once", "on_content_conflict": "route_to_revision_gate", "on_timeout": "queued_alert_and_pause_node", "max_retries": 1, "escalation": "revision_gate"}}
    if node_id == "revision_gate":
        base.update({"execution_mode": "barrier", "dispatch_group": "chapter_quality", "join_policy": "coordinator_decides", "human_gate_policy": {"required_when": ["blocking_conflict_repeated", "world_rule_retroactive_change", "user_goal_changed", "final_blocking_issue"], "decision_contract_id": "contract.novel.continuity_review", "reviewer_role": "user_or_showrunner"}})
    elif node_id == "memory_publish":
        base.update({"execution_mode": "background", "dispatch_group": "memory_maintenance", "join_policy": "allow_partial_with_issues", "background_policy": {"enabled": True, "blocks_downstream": False, "result_visibility": "summary_and_refs", "writeback_targets": ["working_memory_candidate", "task_durable_candidate"], "max_runtime_seconds": 900, "kill_on_parent_abort": True, "retain_after_completion_seconds": 1800}, "notification_policy": {"on_started": "event_only", "on_completed": "queued_summary", "on_failed": "queued_alert", "include_result": "summary_and_refs", "priority": "later"}})
    elif node_id == "final_assembly":
        base.update({"execution_mode": "barrier", "dispatch_group": "final_join", "join_policy": "all_success"})
    elif node_id == "continuity_review":
        base.update({"dispatch_group": "chapter_quality", "join_policy": "fail_on_any_error"})
    return base


def mem(node_id: str) -> dict[str, Any]:
    dynamic = {"enabled": True, "allow_dynamic_read": True, "max_dynamic_reads_per_node_run": 3, "allow_temporal_expansion": True, "max_temporal_expansion_depth": 2, "max_temporal_neighbors": 6}
    if node_id == "input_brief":
        return {"memory_read_policy": {"readable_kinds": [], "readable_scopes": []}, "memory_writeback_policy": {"writable_kinds": ["task_goal", "decision_record"], "writable_scopes": ["graph_scope"], "default_visibility": "shared_in_graph"}, "dynamic_memory_read_policy": {"enabled": False, "allow_dynamic_read": False, "max_dynamic_reads_per_node_run": 0}}
    if node_id == "chapter_draft":
        return {"memory_read_policy": {"readable_kinds": ["chapter_brief", "decision_record", "world_bible_delta", "character_state_delta", "style_constraint", "foreshadow_track", "retry_guidance", "artifact_ref"], "readable_scopes": ["task_scope", "graph_scope", "handoff_only"], "prefer_accepted_items": True, "reject_unaccepted_facts": True}, "memory_writeback_policy": {"writable_kinds": ["chapter_draft", "character_state_delta", "world_bible_delta", "foreshadow_track", "artifact_ref"], "writable_scopes": ["node_scope", "graph_scope"], "default_visibility": "private_to_node", "requires_coordinator_review": True, "accepted_write_forbidden": True}, "dynamic_memory_read_policy": dynamic}
    if node_id == "continuity_review":
        return {"memory_read_policy": {"readable_kinds": ["chapter_draft", "decision_record", "world_bible_delta", "character_state_delta", "style_constraint", "foreshadow_track", "artifact_ref"], "readable_scopes": ["task_scope", "graph_scope", "handoff_only", "node_scope"], "allow_unaccepted_draft_refs": True}, "memory_writeback_policy": {"writable_kinds": ["continuity_conflict", "evaluator_feedback", "revision_instruction"], "writable_scopes": ["edge_scope", "graph_scope"], "default_visibility": "shared_in_graph", "requires_coordinator_review": True}, "dynamic_memory_read_policy": {**dynamic, "max_dynamic_reads_per_node_run": 5}}
    if node_id == "revision_gate":
        return {"memory_read_policy": {"readable_kinds": ["continuity_conflict", "evaluator_feedback", "revision_instruction", "chapter_draft", "decision_record", "world_bible_delta", "character_state_delta", "artifact_ref"], "readable_scopes": ["task_scope", "graph_scope", "handoff_only", "edge_scope"]}, "memory_writeback_policy": {"writable_kinds": ["decision_record", "retry_guidance"], "writable_scopes": ["graph_scope"], "default_visibility": "shared_in_graph"}, "dynamic_memory_read_policy": {"enabled": True, "allow_dynamic_read": True, "max_dynamic_reads_per_node_run": 2, "allow_temporal_expansion": False, "max_temporal_expansion_depth": 0}}
    if node_id == "memory_publish":
        return {"memory_read_policy": {"readable_kinds": ["decision_record", "chapter_draft", "world_bible_delta", "character_state_delta", "foreshadow_track", "style_constraint", "continuity_conflict", "artifact_ref"], "readable_scopes": ["task_scope", "graph_scope", "handoff_only"], "require_acceptance_refs": True}, "memory_writeback_policy": {"writable_kinds": ["promotion_candidate", "artifact_ref"], "writable_scopes": ["task_scope"], "default_visibility": "coordinator_only", "requires_coordinator_review": True, "task_durable_candidate_only": True}, "dynamic_memory_read_policy": {**dynamic, "max_dynamic_reads_per_node_run": 4}}
    return {"memory_read_policy": {"readable_kinds": ["task_goal", "decision_record", "plan_fragment", "world_bible_delta", "character_state_delta", "style_constraint", "foreshadow_track"], "readable_scopes": ["task_scope", "graph_scope", "handoff_only"], "prefer_accepted_items": True, "reject_unaccepted_facts": True}, "memory_writeback_policy": {"writable_kinds": ["plan_fragment", "decision_record", "world_bible_delta", "character_state_delta", "foreshadow_track", "style_constraint", "chapter_brief", "artifact_ref"], "writable_scopes": ["node_scope", "graph_scope"], "default_visibility": "shared_in_graph", "requires_coordinator_review": True}, "dynamic_memory_read_policy": dynamic}


def graph_payloads() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    node_defs = [
        ("input_brief", "input", "项目简报", "agent:novel_showrunner", "contract.novel.project_brief"),
        ("story_architecture", "agent", "故事架构", "agent:novel_story_architect", "contract.novel.volume_outline"),
        ("chapter_plan", "agent", "章节计划", "agent:novel_story_architect", "contract.novel.chapter_brief"),
        ("chapter_draft", "agent", "章节写作", "agent:novel_chapter_writer", "contract.novel.chapter_draft"),
        ("continuity_review", "agent", "连续性审校", "agent:novel_continuity_editor", "contract.novel.continuity_review"),
        ("revision_gate", "coordinator", "修订决策", "agent:novel_showrunner", "contract.novel.project_plan"),
        ("memory_publish", "agent", "记忆与交付管理", "agent:novel_memory_publisher", "contract.novel.memory_promotion_batch"),
        ("final_assembly", "agent", "最终交付整理", "agent:novel_memory_publisher", "contract.novel.final_manuscript_package"),
    ]
    nodes = []
    for node_id, node_type, title, agent_id, contract_id in node_defs:
        nodes.append({"node_id": node_id, "node_type": node_type, "title": title, "label": title, "task_id": "task.longform_novel.create_full_novel", "task_title": "长篇小说完整创作", "task_family": "longform_novel_writing", "agent_id": agent_id, "agent_selection_policy": "explicit_agent", "role": "coordinator" if node_id == "input_brief" else "participant", "work_posture": node_id, "node_contract_id": contract_id, "input_contract_id": "contract.novel.project_brief" if node_id == "input_brief" else "", "output_contract_id": contract_id, "runtime_lane": "longform_novel_graph", **sched(node_id), **mem(node_id)})
    edge_defs = [
        ("e_brief_architecture", "input_brief", "story_architecture", "contract.novel.project_brief", ["task_goal"], "fail_downstream"),
        ("e_architecture_chapter", "story_architecture", "chapter_plan", "contract.novel.volume_outline", ["plan_fragment", "foreshadow_track", "world_state_delta", "character_state_delta"], "fail_downstream"),
        ("e_chapter_plan_draft", "chapter_plan", "chapter_draft", "contract.novel.chapter_brief", ["chapter_brief", "style_constraint", "accepted_refs"], "fail_downstream"),
        ("e_draft_review", "chapter_draft", "continuity_review", "contract.novel.chapter_draft", ["chapter_draft", "character_state_delta", "world_state_delta"], "fail_downstream"),
        ("e_review_gate", "continuity_review", "revision_gate", "contract.novel.continuity_review", ["continuity_conflict", "evaluator_feedback", "revision_instruction"], "coordinator_decides"),
        ("e_gate_memory", "revision_gate", "memory_publish", "contract.novel.continuity_review", ["accepted_refs", "decision_record", "retry_guidance"], "allow_partial"),
        ("e_memory_final", "memory_publish", "final_assembly", "contract.novel.memory_promotion_batch", ["promotion_candidate", "task_durable_refs", "unresolved_conflict"], "coordinator_decides"),
    ]
    edges = []
    for edge_id, src, dst, contract_id, carry_kinds, failure in edge_defs:
        edges.append({"edge_id": edge_id, "from": src, "to": dst, "source_node_id": src, "target_node_id": dst, "edge_type": "handoff", "mode": "structured_handoff", "policy": "structured_handoff", "a2a_message_type": "message/send", "payload_contract_id": contract_id, "wait_policy": "wait_all_upstream_completed", "ack_required": True, "ack_policy": "required_before_target_start", "failure_propagation_policy": failure, "result_delivery_policy": "contract_payload_and_refs", "timeout_policy": "fail_closed", "context_filter_policy": {"include_raw_messages": False, "include_private_memory": False, "prefer_refs": True}, "artifact_ref_policy": {"include_artifact_refs": True, "require_stable_refs_for_final": dst == "final_assembly"}, "communication_policy": {"sync_semantics": "async_background_after_gate" if dst == "memory_publish" else "barrier_wait_for_stable_refs" if dst == "final_assembly" else "sync_handoff_before_target_start", "payload_visibility": "contract_payload_and_refs", "ack_semantics": "target_must_ack_before_execution", "raw_message_forwarding": False}, "failure_policy": {"duplicate_source_message_hash": "reuse_handoff_transaction", "contract_mismatch": "block_downstream_and_route_to_revision_gate", "missing_ack": "pause_target_and_alert"}, "working_memory_handoff_policy": {"carry_kinds": carry_kinds, "carry_scopes": ["handoff_only", "graph_scope"], "working_memory_refs": [], "summary_only": True, "allow_artifact_refs": True, "prefer_accepted_items": True, "reject_unaccepted_facts": True, "quarantine_unaccepted_facts": True}})
    return nodes, edges


def configure_task_system() -> None:
    for item in CONTRACTS:
        request("PUT", f"/tasks/contracts/{item['contract_id']}", item)
    request("PUT", "/tasks/domains/domain.longform_novel", {"domain_id": "domain.longform_novel", "task_family": "longform_novel_writing", "title": "长篇小说创作", "description": "面向多章节、多角色、多设定连续性的长篇小说生产任务域。", "enabled": True, "sort_order": 260, "metadata": {"managed_by": "task_package_wizard", "package_template": "longform_novel_writing"}})
    request("PUT", "/tasks/specific-records/task.longform_novel.create_full_novel", {"task_id": "task.longform_novel.create_full_novel", "task_title": "长篇小说完整创作", "task_family": "longform_novel_writing", "task_mode": "longform_novel_graph", "description": "通过多 Agent 拓扑完成项目规划、设定管理、章节写作、连续性审查、记忆整理与最终交付。", "input_contract_id": "contract.novel.project_brief", "output_contract_id": "contract.novel.final_manuscript_package", "acceptance_profile_id": "", "default_flow_contract_id": "flow.longform_novel.graph_runtime", "default_workflow_id": "workflow.longform_novel.graph_runtime", "default_projection_policy": "task_graph_agent_projection", "task_policy": {"safety_policy": {"safety_class": "S2_bounded", "write_mode": "artifact_ref_only", "verification_mode": "contract_and_review"}, "task_structure": {"execution_chain_type": "graph_run_loop", "trigger_signals": ["task_package.longform_novel"]}}, "enabled": True, "metadata": {"managed_by": "task_package_wizard", "package_template": "longform_novel_writing"}})
    projection_ids = [item[3] for item in AGENTS]
    request("PUT", "/tasks/workflows/workflow.longform_novel.graph_runtime", {"workflow_id": "workflow.longform_novel.graph_runtime", "title": "长篇小说图运行流程", "task_mode": "longform_novel_graph", "compatible_projection_ids": projection_ids, "visible_skill_ids": [], "steps": [{"step_id": "project_plan", "title": "项目规划"}, {"step_id": "asset_build", "title": "设定与角色资产建立"}, {"step_id": "chapter_loop", "title": "章节循环"}, {"step_id": "final_assembly", "title": "最终整理"}], "input_boundary": "contract.novel.project_brief", "output_boundary": "contract.novel.final_manuscript_package", "stop_conditions": ["final_manuscript_package_ready"], "required_evidence_refs": [], "output_contract_id": "contract.novel.final_manuscript_package", "prompt": "使用任务图和专属 Agent 投影执行长篇小说生产流程。", "enabled": True, "metadata": {"managed_by": "task_package_wizard", "package_template": "longform_novel_writing"}})
    request("PUT", "/tasks/projection-bindings/task.longform_novel.create_full_novel", {"task_id": "task.longform_novel.create_full_novel", "projection_selection_mode": "task_graph_agent_projection", "allowed_projection_ids": projection_ids, "default_projection_id": "projection.longform_novel.showrunner", "projection_required": True, "notes": "长篇小说任务使用任务图节点 Agent 的专属投影。", "metadata": {"task_family": "longform_novel_writing", "managed_by": "task_package_wizard"}})
    request("PUT", "/tasks/execution-policies/task.longform_novel.create_full_novel", {"task_id": "task.longform_novel.create_full_novel", "execution_chain_type": "graph_run_loop", "runtime_agent_selection_policy": "task_graph_explicit_agent", "default_agent_id": "agent:novel_showrunner", "task_level": "standard", "task_privilege": "bounded", "allowed_agent_categories": ["worker_sub_agent"], "allow_worker_agent_spawn": False, "worker_agent_blueprint_id": "", "worker_agent_naming_rule": "", "notes": "Agent 必须先在编排系统前端创建，并由任务图节点显式绑定。", "metadata": {"managed_by": "task_package_wizard", "package_template": "longform_novel_writing"}})
    request("PUT", "/tasks/memory-request-profiles/task.longform_novel.create_full_novel", {"task_id": "task.longform_novel.create_full_novel", "requested_memory_layers": ["working", "task_durable"], "requested_topics": ["story_bible", "character_state", "chapter_draft", "continuity"], "memory_priority": "high", "writeback_policy": "task_durable_reviewed_promotion", "allow_long_term_memory": True, "memory_scope_hint": "任务工作记忆与任务长期记忆隔离，不写入 Global Durable。", "metadata": {"managed_by": "task_package_wizard", "package_template": "longform_novel_writing", "allow_working_memory": True, "allow_dynamic_working_memory_read": True, "working_memory_policy_profile_id": "wmprofile.longform_novel"}})
    nodes, edges = graph_payloads()
    request("PUT", "/tasks/topology-templates/topology.longform_novel.production_graph", {"template_id": "topology.longform_novel.production_graph", "title": "长篇小说生产拓扑", "nodes": nodes, "edges": edges, "handoff_rules": [], "join_policy": "explicit_join", "failure_policy": "fail_closed", "terminal_policy": "coordinator_terminal", "enabled": True, "metadata": {"task_family": "longform_novel_writing", "domain_id": "domain.longform_novel", "package_template": "longform_novel_writing"}})
    request("PUT", "/tasks/communication-protocols/protocol.longform_novel.a2a_handoff", {"protocol_id": "protocol.longform_novel.a2a_handoff", "title": "长篇小说 A2A 交接协议", "message_types": ["message/send"], "payload_contracts": [item["contract_id"] for item in CONTRACTS], "signal_rules": ["contract_payload_required", "working_memory_refs_are_refs_only"], "handoff_rules": ["no_raw_private_memory", "ack_required", "task_durable_only_after_review"], "ack_policy": "explicit_ack", "timeout_policy": "fail_closed", "error_signal_policy": "raise_to_coordinator", "enabled": True, "metadata": {"task_family": "longform_novel_writing", "domain_id": "domain.longform_novel", "a2a_protocol": "official"}})
    request("PUT", "/tasks/coordination-tasks/coord.longform_novel.core_production", {"coordination_task_id": "coord.longform_novel.core_production", "title": "长篇小说核心团队生产任务", "coordination_mode": "pipeline", "coordinator_agent_id": "agent:novel_showrunner", "task_family": "longform_novel_writing", "domain_id": "domain.longform_novel", "agent_group_id": "group.longform_novel_core_team", "participant_agent_ids": [item[1] for item in AGENTS[1:]], "topology_template_id": "topology.longform_novel.production_graph", "shared_context_policy": "explicit_refs_only", "memory_sharing_policy": "isolated_by_default", "handoff_policy": "filtered_handoff", "conflict_resolution_policy": "coordinator_review", "output_merge_policy": "coordinator_final_merge", "stop_conditions": ["final_manuscript_package_ready"], "subtask_refs": ["task.longform_novel.create_full_novel"], "graph_nodes": nodes, "graph_edges": edges, "communication_modes": ["structured_handoff", "review_feedback", "revision_gate"], "enabled": True, "metadata": {"managed_by": "task_package_wizard", "protocol_id": "protocol.longform_novel.a2a_handoff", "task_family": "longform_novel_writing", "domain_id": "domain.longform_novel", "package_template": "longform_novel_writing"}})
    request("PUT", "/tasks/task-graphs/graph.longform_novel.core_production", {"graph_id": "graph.longform_novel.core_production", "title": "长篇小说核心团队任务图", "domain_id": "domain.longform_novel", "task_family": "longform_novel_writing", "graph_kind": "multi_agent", "entry_node_id": "input_brief", "output_node_id": "final_assembly", "nodes": nodes, "edges": edges, "graph_contract_id": "contract.novel.final_manuscript_package", "default_protocol_id": "protocol.longform_novel.a2a_handoff", "working_memory_policy_profile_id": "wmprofile.longform_novel", "working_memory_policy": {"enabled": True, "default_scope": "node_scope", "default_visibility": "private_to_node", "allowed_kinds": ["chapter_draft", "character_state_delta", "world_bible_delta", "continuity_conflict", "promotion_candidate", "revision_instruction"], "finalize_requires_human_review": True, "promotion_requires_human_review": True}, "runtime_policy": {"loop_kind": "iterative_graph", "iteration_unit": "chapter", "max_iterations": 120, "max_attempts_per_iteration": 3, "revise_until": "no_error_conflict", "memory_finalize_per_iteration": True, "task_durable_promotion_cadence": "revision_gate_accept", "chapter_loop": {"plan_node_id": "chapter_plan", "draft_node_id": "chapter_draft", "review_node_id": "continuity_review", "gate_node_id": "revision_gate", "memory_node_id": "memory_publish", "max_attempts_per_chapter": 3, "retry_on": ["contract_error", "continuity_conflict", "style_drift"], "manual_gate_on": ["blocking_conflict_repeated", "world_rule_retroactive_change", "user_goal_changed", "memory_promotion_ambiguous"], "skip_policy": "coordinator_decides"}, "checkpoint_policy": {"checkpoint_after_nodes": ["revision_gate", "memory_publish"], "resume_from": "latest_successful_checkpoint", "idempotency_keys": ["task_run_id", "graph_run_id", "chapter_index", "node_run_id", "run_attempt_id", "handoff_transaction_id", "source_message_hash", "artifact_ref"]}, "memory_quarantine_policy": {"draft_kind": "draft_artifact", "accept_requires": ["continuity_review_passed", "revision_gate_accept"], "promotion_requires_human_review": True, "global_durable_write": "forbidden_without_manual_secondary_promotion"}}, "context_policy": {"sharing": "explicit_refs_only", "raw_private_memory": False, "unaccepted_facts": "ephemeral_only"}, "publish_state": "draft", "enabled": True, "metadata": {"managed_by": "task_package_wizard", "coordination_task_id": "coord.longform_novel.core_production", "package_template": "longform_novel_writing"}})


def verify() -> dict[str, Any]:
    manifest = request("GET", "/tasks/contract-manifests/coordination/coord.longform_novel.core_production")
    assembly = request("GET", "/tasks/runtime-assemblies/coordination/coord.longform_novel.core_production/nodes/chapter_draft")
    projections = request("GET", "/soul/projections")
    orchestration = request("GET", "/orchestration/agents")
    return {
        "configured_projection_ids": [item["projection_id"] for item in projections.get("cards", []) if str(item.get("projection_id", "")).startswith("projection.longform_novel.")],
        "configured_agent_ids": [item["agent_id"] for item in orchestration.get("agents", []) if str(item.get("agent_id", "")).startswith("agent:novel_")],
        "manifest_authority": manifest.get("authority"),
        "manifest_issue_count": len(manifest.get("issues", []) or []),
        "assembly_authority": assembly.get("authority"),
        "assembly_node": assembly.get("node_id"),
        "assembly_diagnostics": assembly.get("diagnostics", {}),
    }


if __name__ == "__main__":
    configure_projections_and_agents()
    configure_task_system()
    print(json.dumps(verify(), ensure_ascii=False, indent=2))

