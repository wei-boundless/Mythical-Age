from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestration.agent_registry import AgentRegistry
from project_layout import ProjectLayout
from orchestration.agent_runtime_registry import AgentRuntimeRegistry

from .flow_models import (
    AgentTaskCarryingProfile,
    AgentTaskConnectionProfile,
    CoordinationTaskDefinition,
    GeneralTaskProfile,
    SpecificTaskRecord,
    TaskDomainRecord,
    TaskAgentAdoptionPlan,
    TaskAgentBinding,
    TaskAssignment,
    TaskCommunicationProtocol,
    TaskFlowDefinition,
    TaskFlowContractBinding,
    TaskMemoryRequestProfile,
    TaskProjectionBinding,
    TopologyTemplate,
)
from .contract_models import TaskContractDescriptor
from .template_registry import TaskTemplateRegistry
from .workflow_registry import TaskWorkflowRegistry


CONTRACT_TITLE_MAP: dict[str, str] = {
    "UserMessage": "用户消息",
    "WorkspaceTaskInput": "工作区任务输入",
    "WorkspacePatchTaskInput": "工作区补丁任务输入",
    "AssistantFinalAnswer": "最终回答",
    "LightWebGameTaskInput": "网页小游戏任务输入",
    "LightWebGameResult": "网页游戏产物",
    "ArcadeGameBundleTaskInput": "复合网页游戏任务输入",
    "ShortStoryTaskInput": "短篇小说任务输入",
    "ShortStoryResult": "短篇小说成稿",
    "LongformNovelProjectInput": "长篇小说项目输入",
    "NovelProjectSpec": "长篇小说项目规格",
    "NovelBibleBuildInput": "长篇小说设定总纲输入",
    "NovelBibleBundle": "长篇小说设定总纲",
    "VolumePlanningInput": "卷规划输入",
    "VolumePlan": "卷规划方案",
    "ChapterPlanningInput": "章节规划输入",
    "ChapterPlan": "章节规划方案",
    "ChapterDraftInput": "章节正文输入",
    "ChapterDraft": "章节正文稿",
    "ChapterRevisionInput": "章节修订输入",
    "ChapterRevision": "章节修订稿",
    "ContinuityAuditInput": "连续性审计输入",
    "ContinuityAuditReport": "连续性审计报告",
    "LongformCompilationInput": "全书编纂输入",
    "LongformNovelCompilation": "长篇小说编纂稿",
    "HealthIssue": "健康问题",
    "HealthTriageResult": "健康分诊结果",
    "HealthTrace": "健康链路",
    "HealthTraceAnalysis": "健康链路分析",
    "HealthCaseDraftProposal": "复现用例草案",
    "HealthIssueWithBeforeAfterTrace": "带前后链路的健康问题",
    "HealthFixVerificationProposal": "修复验证方案",
}


CONTRACT_KIND_LABELS: dict[str, str] = {
    "input": "输入契约",
    "output": "输出契约",
    "flow": "流程契约",
    "payload": "通信载荷契约",
}


def normalize_task_agent_adoption_mode(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized == "spawn_worker_allowed":
        return "adopt_with_projection"
    return normalized or "adopt_existing"


def default_task_flows() -> tuple[TaskFlowDefinition, ...]:
    return (
        TaskFlowDefinition(
            flow_id="flow.dev.bounded_patch",
            task_mode="bounded_patch",
            task_family="development",
            title="受限补丁开发任务",
            input_contract_id="WorkspacePatchTaskInput",
            output_contract_id="AssistantFinalAnswer",
            default_agent_id="agent:0",
            default_workflow_id="workflow.dev.bounded_patch",
            default_runtime_lane="workspace_patch",
            default_memory_scope="conversation_read_write",
            metadata={
                "task_resource": "bounded_patch",
                "template_id": "template.dev.workspace_patch",
                "task_id": "task.dev.bounded_patch",
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.dev.light_web_game",
            task_mode="light_web_game",
            task_family="development",
            title="轻量网页小游戏开发",
            input_contract_id="LightWebGameTaskInput",
            output_contract_id="LightWebGameResult",
            default_agent_id="agent:0",
            default_workflow_id="workflow.dev.light_web_game",
            default_runtime_lane="game_delivery",
            default_memory_scope="conversation_read_write",
            metadata={
                "task_resource": "light_web_game",
                "template_id": "template.dev.light_web_game",
                "task_id": "task.dev.light_web_game",
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.writing.short_story",
            task_mode="short_story",
            task_family="writing",
            title="短篇小说协作写作",
            input_contract_id="ShortStoryTaskInput",
            output_contract_id="ShortStoryResult",
            default_agent_id="agent:0",
            default_workflow_id="workflow.writing.short_story",
            default_runtime_lane="story_coordination",
            default_memory_scope="conversation_read_write",
            metadata={
                "task_resource": "short_story",
                "template_id": "template.writing.short_story",
                "task_id": "task.writing.short_story",
                "coordination_task_id": "coord.writing.short_story_pipeline",
                "communication_protocol_id": "protocol.writing.short_story_pipeline",
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.writing.longform_novel_project",
            task_mode="longform_novel_project",
            task_family="writing",
            title="长篇小说持续交付",
            input_contract_id="LongformNovelProjectInput",
            output_contract_id="NovelProjectSpec",
            default_agent_id="agent:20",
            default_workflow_id="workflow.writing.longform_novel_project",
            default_runtime_lane="novel_continuous_delivery",
            default_memory_scope="novel_project_state",
            metadata={
                "task_resource": "longform_novel_project",
                "template_id": "template.writing.longform_novel_project",
                "task_id": "task.writing.longform_novel_project",
                "coordination_task_id": "coord.writing.longform_project_bootstrap",
                "communication_protocol_id": "protocol.writing.longform_project_bootstrap",
                "topology_template_id": "topology.writing.longform_project_bootstrap",
                "agent_group_id": "group.writing.longform_novel_core",
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.writing.novel_bible_build",
            task_mode="novel_bible_build",
            task_family="writing",
            title="长篇小说设定总纲构建",
            input_contract_id="NovelBibleBuildInput",
            output_contract_id="NovelBibleBundle",
            default_agent_id="agent:20",
            default_workflow_id="workflow.writing.novel_bible_build",
            default_runtime_lane="novel_bible_gate",
            default_memory_scope="novel_bible_read_write",
            metadata={
                "task_resource": "novel_bible_build",
                "template_id": "template.writing.novel_bible_build",
                "task_id": "task.writing.novel_bible_build",
                "coordination_task_id": "coord.writing.novel_bible_build",
                "communication_protocol_id": "protocol.writing.novel_bible_build",
                "topology_template_id": "topology.writing.novel_bible_build",
                "agent_group_id": "group.writing.longform_novel_core",
                "internal_stage": True,
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.writing.volume_planning",
            task_mode="volume_planning",
            task_family="writing",
            title="长篇小说卷规划",
            input_contract_id="VolumePlanningInput",
            output_contract_id="VolumePlan",
            default_agent_id="agent:20",
            default_workflow_id="workflow.writing.volume_planning",
            default_runtime_lane="volume_acceptance",
            default_memory_scope="novel_bible_read_write",
            metadata={
                "task_resource": "volume_planning",
                "template_id": "template.writing.volume_planning",
                "task_id": "task.writing.volume_planning",
                "coordination_task_id": "coord.writing.volume_planning",
                "communication_protocol_id": "protocol.writing.volume_planning",
                "topology_template_id": "topology.writing.volume_planning",
                "agent_group_id": "group.writing.longform_novel_core",
                "internal_stage": True,
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.writing.chapter_planning",
            task_mode="chapter_planning",
            task_family="writing",
            title="长篇小说章节规划",
            input_contract_id="ChapterPlanningInput",
            output_contract_id="ChapterPlan",
            default_agent_id="agent:23",
            default_workflow_id="workflow.writing.chapter_planning",
            default_runtime_lane="chapter_plot_plan",
            default_memory_scope="novel_chapter_refs",
            metadata={
                "task_resource": "chapter_planning",
                "template_id": "template.writing.chapter_planning",
                "task_id": "task.writing.chapter_planning",
                "coordination_task_id": "coord.writing.chapter_pipeline",
                "communication_protocol_id": "protocol.writing.chapter_pipeline",
                "topology_template_id": "topology.writing.chapter_pipeline",
                "agent_group_id": "group.writing.longform_novel_core",
                "internal_stage": True,
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.writing.chapter_drafting",
            task_mode="chapter_drafting",
            task_family="writing",
            title="长篇小说章节正文",
            input_contract_id="ChapterDraftInput",
            output_contract_id="ChapterDraft",
            default_agent_id="agent:24",
            default_workflow_id="workflow.writing.chapter_drafting",
            default_runtime_lane="chapter_drafting",
            default_memory_scope="chapter_draft_workspace",
            metadata={
                "task_resource": "chapter_drafting",
                "template_id": "template.writing.chapter_drafting",
                "task_id": "task.writing.chapter_drafting",
                "coordination_task_id": "coord.writing.chapter_pipeline",
                "communication_protocol_id": "protocol.writing.chapter_pipeline",
                "topology_template_id": "topology.writing.chapter_pipeline",
                "agent_group_id": "group.writing.longform_novel_core",
                "internal_stage": True,
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.writing.chapter_revision",
            task_mode="chapter_revision",
            task_family="writing",
            title="长篇小说章节修订",
            input_contract_id="ChapterRevisionInput",
            output_contract_id="ChapterRevision",
            default_agent_id="agent:24",
            default_workflow_id="workflow.writing.chapter_revision",
            default_runtime_lane="chapter_revision",
            default_memory_scope="chapter_draft_workspace",
            metadata={
                "task_resource": "chapter_revision",
                "template_id": "template.writing.chapter_revision",
                "task_id": "task.writing.chapter_revision",
                "coordination_task_id": "coord.writing.chapter_pipeline",
                "communication_protocol_id": "protocol.writing.chapter_pipeline",
                "topology_template_id": "topology.writing.chapter_pipeline",
                "agent_group_id": "group.writing.longform_novel_core",
                "internal_stage": True,
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.writing.continuity_audit",
            task_mode="continuity_audit",
            task_family="writing",
            title="长篇小说连续性审计",
            input_contract_id="ContinuityAuditInput",
            output_contract_id="ContinuityAuditReport",
            default_agent_id="agent:26",
            default_workflow_id="workflow.writing.continuity_audit",
            default_runtime_lane="continuity_audit",
            default_memory_scope="continuity_workspace",
            metadata={
                "task_resource": "continuity_audit",
                "template_id": "template.writing.continuity_audit",
                "task_id": "task.writing.continuity_audit",
                "coordination_task_id": "coord.writing.continuity_audit",
                "communication_protocol_id": "protocol.writing.continuity_audit",
                "topology_template_id": "topology.writing.continuity_audit",
                "agent_group_id": "group.writing.longform_novel_core",
                "internal_stage": True,
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.writing.final_compilation",
            task_mode="final_compilation",
            task_family="writing",
            title="长篇小说全书编纂",
            input_contract_id="LongformCompilationInput",
            output_contract_id="LongformNovelCompilation",
            default_agent_id="agent:20",
            default_workflow_id="workflow.writing.final_compilation",
            default_runtime_lane="final_compilation",
            default_memory_scope="novel_bible_read_write",
            metadata={
                "task_resource": "final_compilation",
                "template_id": "template.writing.final_compilation",
                "task_id": "task.writing.final_compilation",
                "coordination_task_id": "coord.writing.final_compilation",
                "communication_protocol_id": "protocol.writing.final_compilation",
                "topology_template_id": "topology.writing.final_compilation",
                "agent_group_id": "group.writing.longform_novel_core",
                "internal_stage": True,
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.dev.arcade_game_bundle",
            task_mode="arcade_game_bundle",
            task_family="development",
            title="复合网页小游戏包开发",
            input_contract_id="ArcadeGameBundleTaskInput",
            output_contract_id="LightWebGameResult",
            default_agent_id="agent:0",
            default_workflow_id="workflow.dev.arcade_game_bundle",
            default_runtime_lane="game_delivery",
            default_memory_scope="conversation_read_write",
            metadata={
                "task_resource": "arcade_game_bundle",
                "template_id": "template.dev.arcade_game_bundle",
                "task_id": "task.dev.arcade_game_bundle",
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.health.issue_triage",
            task_mode="issue_triage",
            task_family="health",
            title="健康问题分诊",
            input_contract_id="HealthIssue",
            output_contract_id="HealthTriageResult",
            default_agent_id="agent:3",
            default_workflow_id="workflow.health.issue_triage",
            default_runtime_lane="health_issue_read",
            default_memory_scope="issue_local_readonly",
        ),
        TaskFlowDefinition(
            flow_id="flow.health.trace_analysis",
            task_mode="trace_analysis",
            task_family="health",
            title="健康链路分析",
            input_contract_id="HealthTrace",
            output_contract_id="HealthTraceAnalysis",
            default_agent_id="agent:3",
            default_workflow_id="workflow.health.trace_analysis",
            default_runtime_lane="health_trace_read",
            default_memory_scope="health_trace_readonly",
        ),
        TaskFlowDefinition(
            flow_id="flow.health.case_draft",
            task_mode="case_draft",
            task_family="health",
            title="复现用例草案",
            input_contract_id="HealthIssue",
            output_contract_id="HealthCaseDraftProposal",
            default_agent_id="agent:3",
            default_workflow_id="workflow.health.case_draft",
            default_runtime_lane="case_draft_candidate",
            default_memory_scope="issue_local_readonly",
        ),
        TaskFlowDefinition(
            flow_id="flow.health.fix_verification",
            task_mode="fix_verification",
            task_family="health",
            title="修复验证",
            input_contract_id="HealthIssueWithBeforeAfterTrace",
            output_contract_id="HealthFixVerificationProposal",
            default_agent_id="agent:3",
            default_workflow_id="workflow.health.fix_verification",
            default_runtime_lane="fix_verification_candidate",
            default_memory_scope="health_trace_readonly",
        ),
    )


def _storage_root(base_dir: Path) -> Path:
    return ProjectLayout.from_backend_dir(base_dir).tasks_dir


def _flows_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_flows.json"


def _general_profiles_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "general_task_profiles.json"


def _assignments_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_assignments.json"


def _specific_task_records_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "specific_task_records.json"


def _task_domains_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_domains.json"


def _coordination_tasks_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "coordination_tasks.json"


def _topology_templates_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "topology_templates.json"


def _projection_bindings_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_projection_bindings.json"


def _flow_contract_bindings_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_flow_contract_bindings.json"


def _adoption_plans_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_agent_adoption_plans.json"


def _memory_request_profiles_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_memory_request_profiles.json"


def _communication_protocols_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_communication_protocols.json"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        import json

        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return loaded if isinstance(loaded, dict) else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_items_by_key(
    default_items: list[dict[str, Any]],
    stored_items: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in default_items:
        item_key = str(item.get(key) or "").strip()
        if item_key:
            merged[item_key] = dict(item)
    for item in stored_items:
        item_key = str(item.get(key) or "").strip()
        if item_key:
            merged[item_key] = dict(item)
    return list(merged.values())


def _merge_default_overlay_by_key(
    default_items: list[dict[str, Any]],
    stored_items: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    defaults_by_key = {
        str(item.get(key) or "").strip(): dict(item)
        for item in default_items
        if str(item.get(key) or "").strip()
    }
    merged: dict[str, dict[str, Any]] = {}
    for item_key, item in defaults_by_key.items():
        merged[item_key] = dict(item)
    for stored in stored_items:
        item_key = str(stored.get(key) or "").strip()
        if not item_key:
            continue
        base = dict(defaults_by_key.get(item_key) or {})
        merged_item = {**base, **dict(stored)}
        if isinstance(base.get("metadata"), dict) or isinstance(stored.get("metadata"), dict):
            merged_item["metadata"] = {
                **dict(base.get("metadata") or {}),
                **{
                    meta_key: meta_value
                    for meta_key, meta_value in dict(stored.get("metadata") or {}).items()
                    if meta_value not in ("", None, [], {})
                    or meta_key not in dict(base.get("metadata") or {})
                },
            }
        if isinstance(base.get("task_policy"), dict) or isinstance(stored.get("task_policy"), dict):
            base_policy = dict(base.get("task_policy") or {})
            stored_policy = dict(stored.get("task_policy") or {})
            merged_policy = {**base_policy, **stored_policy}
            if isinstance(base_policy.get("task_structure"), dict) or isinstance(stored_policy.get("task_structure"), dict):
                merged_policy["task_structure"] = {
                    **dict(base_policy.get("task_structure") or {}),
                    **dict(stored_policy.get("task_structure") or {}),
                }
            if isinstance(base_policy.get("safety_policy"), dict) or isinstance(stored_policy.get("safety_policy"), dict):
                merged_policy["safety_policy"] = {
                    **dict(base_policy.get("safety_policy") or {}),
                    **dict(stored_policy.get("safety_policy") or {}),
                }
            merged_item["task_policy"] = merged_policy
        merged[item_key] = merged_item
    return list(merged.values())


def _merge_authoritative_defaults_by_key(
    default_items: list[dict[str, Any]],
    stored_items: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    defaults_by_key = {
        str(item.get(key) or "").strip(): dict(item)
        for item in default_items
        if str(item.get(key) or "").strip()
    }
    merged: dict[str, dict[str, Any]] = {item_key: dict(item) for item_key, item in defaults_by_key.items()}
    for stored in stored_items:
        item_key = str(stored.get(key) or "").strip()
        if not item_key:
            continue
        default_item = dict(defaults_by_key.get(item_key) or {})
        if default_item and _is_system_managed_item(default_item):
            continue
        if default_item:
            merged[item_key] = {**default_item, **dict(stored)}
            continue
        merged[item_key] = dict(stored)
    return list(merged.values())


def _is_system_managed_item(item: dict[str, Any]) -> bool:
    metadata = dict(item.get("metadata") or {})
    if str(metadata.get("managed_by") or "").strip() == "task_system":
        return True
    return bool(str(metadata.get("task_resource") or "").strip())


def _next_prefixed_id(existing_ids: list[str], *, prefix: str, width: int = 6) -> str:
    max_value = 0
    for raw in existing_ids:
        value = str(raw or "").strip()
        if not value.startswith(prefix):
            continue
        suffix = value[len(prefix):]
        if suffix.isdigit():
            max_value = max(max_value, int(suffix))
    return f"{prefix}{max_value + 1:0{width}d}"


def _family_from_ref(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    prefixes = (
        ("development", ("task.dev.", "flow.dev.", "coord.dev.", "topology.dev.", "protocol.dev.", "workflow.dev.")),
        ("writing", ("task.writing.", "flow.writing.", "coord.writing.", "topology.writing.", "protocol.writing.", "workflow.writing.")),
        ("health", ("task.health.", "flow.health.", "coord.health.", "topology.health.", "protocol.health.", "workflow.health.")),
        ("general", ("task.general.", "flow.general.", "coord.general.", "topology.general.", "protocol.general.", "workflow.general.")),
    )
    for family, family_prefixes in prefixes:
        if any(raw.startswith(prefix) for prefix in family_prefixes):
            return family
    return ""


def _default_coordination_graph(
    *,
    coordinator_agent_id: str,
    participant_agent_ids: tuple[str, ...],
    task_family: str = "",
    subtask_refs: tuple[str, ...] = (),
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    coordinator = str(coordinator_agent_id or "agent:0").strip() or "agent:0"
    participants = tuple(str(item).strip() for item in participant_agent_ids if str(item).strip())
    subtasks = tuple(str(item).strip() for item in subtask_refs if str(item).strip())
    nodes: list[dict[str, Any]] = [
        {
            "node_id": "coordinator",
            "node_type": "coordinator",
            "agent_id": coordinator,
            "role": "coordinator",
            "label": "协调者",
        }
    ]
    edges: list[dict[str, Any]] = []
    for index, agent_id in enumerate(participants or tuple("" for _ in subtasks), start=1):
        task_id = subtasks[index - 1] if index - 1 < len(subtasks) else ""
        node_id = f"subtask_{index}" if task_id else f"agent_{index}"
        nodes.append(
            {
                "node_id": node_id,
                "node_type": "subtask" if task_id else "agent_role",
                "task_id": task_id,
                "task_family": task_family,
                "agent_id": agent_id,
                "role": "participant",
            }
        )
        edges.append({"edge_id": f"edge_{index}", "from": "coordinator", "to": node_id, "mode": "structured_handoff"})
        edges.append({"edge_id": f"edge_{index}_back", "from": node_id, "to": "coordinator", "mode": "review_feedback"})
    return tuple(nodes), tuple(edges)


def _subtask_refs_from_graph_nodes(nodes: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(node.get("task_id") or node.get("subtask_ref") or "").strip()
            for node in nodes
            if str(node.get("task_id") or node.get("subtask_ref") or "").strip().startswith("task.")
        )
    )


def default_task_domains() -> tuple[TaskDomainRecord, ...]:
    return (
        TaskDomainRecord(
            domain_id="domain.development",
            task_family="development",
            title="开发任务域",
            description="承接代码、网页、工具和工程交付类特定任务。",
            sort_order=10,
            metadata={"seed": "default"},
        ),
        TaskDomainRecord(
            domain_id="domain.writing",
            task_family="writing",
            title="写作任务域",
            description="承接短篇、长篇、章节、审校和编纂类写作任务。",
            sort_order=20,
            metadata={"seed": "default"},
        ),
        TaskDomainRecord(
            domain_id="domain.health",
            task_family="health",
            title="健康管理任务域",
            description="承接系统健康、链路分析、复现和修复验证类任务。",
            sort_order=30,
            metadata={"seed": "default"},
        ),
    )


def default_general_task_profiles() -> tuple[GeneralTaskProfile, ...]:
    return (
        GeneralTaskProfile(
            profile_id="general.conversation.default",
            title="通用对话任务",
            entry_channel="main_conversation",
            default_agent_id="agent:0",
            default_workflow_id="workflow.general.main_conversation",
            default_projection_id="",
            input_contract_id="UserMessage",
            output_contract_id="AssistantFinalAnswer",
            conversation_entry_policy="user_dialogue_to_main_agent",
            enabled=True,
            metadata={
                "managed_by": "task_system",
                "default_specific_task_handoff": "task.dev.light_web_game",
                "notes": "主会话默认保持通用承接，但允许稳定分流到已登记的开发类特定任务。",
            },
        ),
    )


def default_coordination_tasks() -> tuple[CoordinationTaskDefinition, ...]:
    return (
        CoordinationTaskDefinition(
            coordination_task_id="coord.health.repair_review",
            title="健康修复协作草案",
            coordination_mode="review_merge",
            coordinator_agent_id="agent:0",
            task_family="health",
            domain_id="domain.health",
            agent_group_id="",
            participant_agent_ids=("agent:3",),
            topology_template_id="topology.health.repair_review",
            stop_conditions=("all_participants_reported", "coordinator_final_merge"),
            enabled=False,
            metadata={"candidate_only": True},
        ),
        CoordinationTaskDefinition(
            coordination_task_id="coord.writing.short_story_pipeline",
            title="短篇小说协作流水线",
            coordination_mode="staged_review_loop",
            coordinator_agent_id="agent:0",
            task_family="writing",
            domain_id="domain.writing",
            agent_group_id="",
            participant_agent_ids=("agent:4", "agent:5"),
            topology_template_id="topology.writing.short_story_pipeline",
            shared_context_policy="structured_stage_refs_only",
            memory_sharing_policy="isolated_by_default",
            handoff_policy="stage_contract_handoff",
            conflict_resolution_policy="coordinator_review",
            output_merge_policy="acceptance_then_final_merge",
            stop_conditions=("acceptance_passed", "revision_budget_exhausted"),
            subtask_refs=("task.writing.short_story",),
            enabled=True,
            metadata={
                "max_revision_cycles": 1,
                "required_revision_cycles": 1,
                "task_id": "task.writing.short_story",
                "stage_sequence": [
                    {
                        "stage_id": "idea_proposal",
                        "title": "创意提出",
                        "node_id": "idea_worker",
                        "role": "participant",
                        "message_type": "idea_proposal",
                    },
                    {
                        "stage_id": "idea_review",
                        "title": "创意审核",
                        "node_id": "idea_review",
                        "role": "participant",
                        "message_type": "idea_review",
                    },
                    {
                        "stage_id": "approval_signal",
                        "title": "审核通过",
                        "node_id": "approval_gate",
                        "role": "coordinator",
                        "message_type": "approval_signal",
                    },
                    {
                        "stage_id": "draft_submission",
                        "title": "正式编写",
                        "node_id": "draft_writer",
                        "role": "participant",
                        "message_type": "draft_submission",
                    },
                    {
                        "stage_id": "content_issue",
                        "title": "内容纠察",
                        "node_id": "content_check",
                        "role": "participant",
                        "message_type": "content_issue",
                    },
                    {
                        "stage_id": "revision_request",
                        "title": "修正循环",
                        "node_id": "revision_loop",
                        "role": "participant",
                        "message_type": "revision_request",
                        "loop_kind": "revision_loop",
                    },
                    {
                        "stage_id": "acceptance_result",
                        "title": "内容验收",
                        "node_id": "acceptance",
                        "role": "coordinator",
                        "message_type": "acceptance_result",
                    },
                ],
            },
        ),
        CoordinationTaskDefinition(
            coordination_task_id="coord.writing.longform_project_bootstrap",
            title="长篇小说持续交付总协调",
            coordination_mode="continuous_delivery",
            coordinator_agent_id="agent:20",
            task_family="writing",
            domain_id="domain.writing",
            agent_group_id="group.writing.longform_novel_core",
            participant_agent_ids=("agent:21", "agent:22", "agent:23", "agent:24", "agent:25", "agent:26"),
            topology_template_id="topology.writing.longform_project_bootstrap",
            shared_context_policy="project_bible_refs_only",
            memory_sharing_policy="shared_project_bible_refs",
            handoff_policy="stage_contract_handoff",
            conflict_resolution_policy="editor_gate_review",
            output_merge_policy="editor_gate_merge",
            stop_conditions=(
                "project_scope_locked",
                "bible_backlog_defined",
                "volume_plan_accepted",
                "chapter_batch_accepted",
                "continuity_report_accepted",
                "compilation_ready",
            ),
            subtask_refs=(
                "task.writing.novel_bible_build",
                "task.writing.volume_planning",
                "task.writing.chapter_planning",
                "task.writing.chapter_drafting",
                "task.writing.chapter_revision",
                "task.writing.continuity_audit",
                "task.writing.final_compilation",
            ),
            enabled=True,
            metadata={
                "task_id": "task.writing.longform_novel_project",
                "managed_by": "task_system",
                "task_resource": "longform_novel_project",
                "stage_sequence": [
                    {
                        "stage_id": "project_scope",
                        "title": "项目规格锁定",
                        "node_id": "project_scope",
                        "role": "coordinator",
                        "task_ref": "task.writing.longform_novel_project",
                        "message_type": "project_scope",
                    },
                    {
                        "stage_id": "novel_bible",
                        "title": "设定总纲构建",
                        "node_id": "novel_bible",
                        "role": "participant",
                        "task_ref": "task.writing.novel_bible_build",
                        "message_type": "world_seed",
                    },
                    {
                        "stage_id": "volume_planning",
                        "title": "卷规划",
                        "node_id": "volume_planning",
                        "role": "participant",
                        "task_ref": "task.writing.volume_planning",
                        "message_type": "volume_plan",
                    },
                    {
                        "stage_id": "chapter_planning",
                        "title": "章节批次规划",
                        "node_id": "chapter_pipeline",
                        "role": "participant",
                        "task_ref": "task.writing.chapter_planning",
                        "message_type": "chapter_plan",
                    },
                    {
                        "stage_id": "chapter_pipeline",
                        "title": "章节批次交付",
                        "node_id": "chapter_drafting",
                        "role": "participant",
                        "task_ref": "task.writing.chapter_drafting",
                        "message_type": "chapter_batch",
                    },
                    {
                        "stage_id": "continuity_audit",
                        "title": "连续性审计",
                        "node_id": "continuity_audit",
                        "role": "participant",
                        "task_ref": "task.writing.continuity_audit",
                        "message_type": "continuity_audit",
                    },
                    {
                        "stage_id": "final_compilation",
                        "title": "全书编纂",
                        "node_id": "final_compilation",
                        "role": "coordinator",
                        "task_ref": "task.writing.final_compilation",
                        "message_type": "editor_merge",
                    },
                ],
                "continuation_policy": {
                    "mode": "topology_driven",
                    "auto_continue": True,
                    "max_auto_steps": 100,
                    "stop_on_missing_required_input": True,
                    "terminal_policy": "terminal_node_or_stop_condition",
                    "human_gate_stage_ids": [],
                    "retry_budget": {"default": 0, "revision_loop": 2},
                },
                "stage_contracts": [
                    {
                        "stage_id": "project_scope",
                        "node_id": "project_scope",
                        "task_ref": "task.writing.longform_novel_project",
                        "required_inputs": [],
                        "optional_inputs": ["artifact_root", "run_request"],
                        "input_bindings": [],
                        "output_mappings": [
                            {"output_key": "project_spec_ref", "ref_kind": "artifact", "required": True}
                        ],
                        "gate_policy": "artifact_validation_required",
                    },
                    {
                        "stage_id": "novel_bible",
                        "node_id": "novel_bible",
                        "task_ref": "task.writing.novel_bible_build",
                        "required_inputs": ["project_spec_ref"],
                        "optional_inputs": ["artifact_root", "run_request"],
                        "input_bindings": [
                            {
                                "input_key": "project_spec_ref",
                                "source": "latest_output",
                                "task_ref": "task.writing.longform_novel_project",
                                "required": True,
                            }
                        ],
                        "output_mappings": [
                            {"output_key": "novel_bible_ref", "ref_kind": "artifact", "required": True}
                        ],
                        "gate_policy": "artifact_validation_required",
                    },
                    {
                        "stage_id": "volume_planning",
                        "node_id": "volume_planning",
                        "task_ref": "task.writing.volume_planning",
                        "required_inputs": ["novel_bible_ref"],
                        "optional_inputs": ["artifact_root", "volume_index", "run_request"],
                        "input_bindings": [
                            {
                                "input_key": "novel_bible_ref",
                                "source": "latest_output",
                                "task_ref": "task.writing.novel_bible_build",
                                "required": True,
                            },
                            {"input_key": "volume_index", "source": "literal", "value": 1},
                        ],
                        "output_mappings": [
                            {"output_key": "volume_plan_ref", "ref_kind": "artifact", "required": True}
                        ],
                        "gate_policy": "artifact_validation_required",
                    },
                    {
                        "stage_id": "chapter_planning",
                        "node_id": "chapter_pipeline",
                        "task_ref": "task.writing.chapter_planning",
                        "required_inputs": ["novel_bible_ref", "volume_plan_ref", "context_refs"],
                        "optional_inputs": ["artifact_root", "chapter_index", "run_request"],
                        "input_bindings": [
                            {
                                "input_key": "novel_bible_ref",
                                "source": "latest_output",
                                "task_ref": "task.writing.novel_bible_build",
                                "required": True,
                            },
                            {
                                "input_key": "volume_plan_ref",
                                "source": "latest_output",
                                "task_ref": "task.writing.volume_planning",
                                "required": True,
                            },
                            {
                                "input_key": "context_refs",
                                "source": "collect",
                                "required": True,
                                "items": [
                                    {"source": "latest_output", "task_ref": "task.writing.novel_bible_build"},
                                    {"source": "latest_output", "task_ref": "task.writing.volume_planning"},
                                ],
                            },
                            {"input_key": "chapter_index", "source": "literal", "value": 1},
                            {
                                "input_key": "run_request",
                                "source": "literal",
                                "value": "按持续交付流程生成当前批次章节正文，单轮目标约一万字、约五章，最多两轮轻审，不等待用户再次确认。",
                            },
                        ],
                        "output_mappings": [
                            {"output_key": "chapter_plan_ref", "ref_kind": "artifact", "required": True}
                        ],
                        "gate_policy": "artifact_validation_required",
                    },
                    {
                        "stage_id": "chapter_pipeline",
                        "node_id": "chapter_drafting",
                        "task_ref": "task.writing.chapter_drafting",
                        "required_inputs": ["chapter_plan_ref", "context_refs"],
                        "optional_inputs": ["artifact_root", "run_request"],
                        "input_bindings": [
                            {
                                "input_key": "chapter_plan_ref",
                                "source": "stage_output",
                                "output_key": "chapter_plan_ref",
                                "required": True,
                            },
                            {
                                "input_key": "context_refs",
                                "source": "collect",
                                "required": True,
                                "items": [
                                    {"source": "stage_output", "output_key": "novel_bible_ref"},
                                    {"source": "stage_output", "output_key": "volume_plan_ref"},
                                    {"source": "stage_output", "output_key": "chapter_plan_ref"},
                                ],
                            },
                            {
                                "input_key": "run_request",
                                "source": "literal",
                                "value": "按持续交付流程生成当前批次章节正文，单轮目标约一万字、约五章，最多两轮轻审，不等待用户再次确认。",
                            },
                        ],
                        "output_mappings": [
                            {"output_key": "chapter_refs", "ref_kind": "artifact", "required": True, "single": False}
                        ],
                        "gate_policy": "artifact_validation_required",
                    },
                    {
                        "stage_id": "continuity_audit",
                        "node_id": "continuity_audit",
                        "task_ref": "task.writing.continuity_audit",
                        "required_inputs": ["novel_bible_ref", "chapter_refs"],
                        "optional_inputs": ["artifact_root"],
                        "input_bindings": [
                            {
                                "input_key": "novel_bible_ref",
                                "source": "latest_output",
                                "task_ref": "task.writing.novel_bible_build",
                                "required": True,
                            },
                            {
                                "input_key": "chapter_refs",
                                "source": "latest_output",
                                "task_ref": "task.writing.chapter_drafting",
                                "required": True,
                                "single": False,
                            },
                        ],
                        "output_mappings": [
                            {"output_key": "final_audit_refs", "ref_kind": "artifact", "required": True}
                        ],
                        "gate_policy": "artifact_validation_required",
                    },
                    {
                        "stage_id": "final_compilation",
                        "node_id": "final_compilation",
                        "task_ref": "task.writing.final_compilation",
                        "required_inputs": ["accepted_chapter_refs", "final_audit_refs"],
                        "optional_inputs": ["artifact_root"],
                        "input_bindings": [
                            {
                                "input_key": "accepted_chapter_refs",
                                "source": "stage_output",
                                "output_key": "chapter_refs",
                                "required": True,
                                "single": False,
                            },
                            {
                                "input_key": "final_audit_refs",
                                "source": "latest_output",
                                "task_ref": "task.writing.continuity_audit",
                                "required": True,
                                "single": False,
                            },
                        ],
                        "output_mappings": [
                            {"output_key": "final_manuscript_ref", "ref_kind": "artifact", "required": True}
                        ],
                        "gate_policy": "artifact_validation_required",
                    },
                ],
            },
        ),
        CoordinationTaskDefinition(
            coordination_task_id="coord.writing.novel_bible_build",
            title="长篇小说设定总纲协作",
            coordination_mode="parallel_bible_build",
            coordinator_agent_id="agent:20",
            task_family="writing",
            domain_id="domain.writing",
            agent_group_id="group.writing.longform_novel_core",
            participant_agent_ids=("agent:21", "agent:22", "agent:23"),
            topology_template_id="topology.writing.novel_bible_build",
            shared_context_policy="bible_section_refs_only",
            memory_sharing_policy="shared_project_bible_refs",
            handoff_policy="bible_section_contract_handoff",
            conflict_resolution_policy="editor_gate_review",
            output_merge_policy="editor_gate_merge",
            stop_conditions=("story_bible_complete", "consistency_passed"),
            subtask_refs=("task.writing.novel_bible_build",),
            enabled=True,
            metadata={"task_id": "task.writing.novel_bible_build", "internal_stage": True, "managed_by": "task_system", "task_resource": "novel_bible_build"},
        ),
        CoordinationTaskDefinition(
            coordination_task_id="coord.writing.volume_planning",
            title="长篇小说卷规划协作",
            coordination_mode="staged_volume_planning",
            coordinator_agent_id="agent:20",
            task_family="writing",
            domain_id="domain.writing",
            agent_group_id="group.writing.longform_novel_core",
            participant_agent_ids=("agent:22", "agent:23", "agent:25"),
            topology_template_id="topology.writing.volume_planning",
            shared_context_policy="volume_plan_refs_only",
            memory_sharing_policy="shared_project_bible_refs",
            handoff_policy="volume_contract_handoff",
            conflict_resolution_policy="editor_gate_review",
            output_merge_policy="editor_gate_merge",
            stop_conditions=("volume_plan_accepted",),
            subtask_refs=("task.writing.volume_planning",),
            enabled=True,
            metadata={"task_id": "task.writing.volume_planning", "internal_stage": True, "managed_by": "task_system", "task_resource": "volume_planning"},
        ),
        CoordinationTaskDefinition(
            coordination_task_id="coord.writing.chapter_pipeline",
            title="长篇小说章节协作流水线",
            coordination_mode="chapter_collaboration_loop",
            coordinator_agent_id="agent:20",
            task_family="writing",
            domain_id="domain.writing",
            agent_group_id="group.writing.longform_novel_core",
            participant_agent_ids=("agent:23", "agent:24", "agent:25", "agent:26"),
            topology_template_id="topology.writing.chapter_pipeline",
            shared_context_policy="chapter_refs_only",
            memory_sharing_policy="shared_project_bible_refs",
            handoff_policy="chapter_contract_handoff",
            conflict_resolution_policy="editor_gate_review",
            output_merge_policy="editor_gate_merge",
            stop_conditions=("chapter_work_accepted", "review_completed", "revision_loop_closed", "revision_budget_exhausted"),
            subtask_refs=(
                "task.writing.chapter_planning",
                "task.writing.chapter_drafting",
                "task.writing.chapter_revision",
                "task.writing.continuity_audit",
            ),
            enabled=True,
            metadata={
                "task_id": "task.writing.chapter_drafting",
                "structure_role": "stable_coordination_skeleton",
                "request_policy": "runtime_request_is_carried_as_natural_language_brief",
                "max_revision_cycles": 2,
                "required_revision_cycles": 0,
                "internal_stage": True,
                "managed_by": "task_system",
                "task_resource": "chapter_pipeline",
            },
        ),
        CoordinationTaskDefinition(
            coordination_task_id="coord.writing.continuity_audit",
            title="长篇小说连续性审计协作",
            coordination_mode="continuity_audit",
            coordinator_agent_id="agent:20",
            task_family="writing",
            domain_id="domain.writing",
            agent_group_id="group.writing.longform_novel_core",
            participant_agent_ids=("agent:21", "agent:26", "agent:25"),
            topology_template_id="topology.writing.continuity_audit",
            shared_context_policy="audit_refs_only",
            memory_sharing_policy="shared_project_bible_refs",
            handoff_policy="audit_contract_handoff",
            conflict_resolution_policy="editor_gate_review",
            output_merge_policy="editor_gate_merge",
            stop_conditions=("continuity_report_accepted",),
            subtask_refs=("task.writing.continuity_audit",),
            enabled=True,
            metadata={"task_id": "task.writing.continuity_audit", "internal_stage": True, "managed_by": "task_system", "task_resource": "continuity_audit"},
        ),
        CoordinationTaskDefinition(
            coordination_task_id="coord.writing.final_compilation",
            title="长篇小说全书编纂协作",
            coordination_mode="final_compilation",
            coordinator_agent_id="agent:20",
            task_family="writing",
            domain_id="domain.writing",
            agent_group_id="group.writing.longform_novel_core",
            participant_agent_ids=("agent:24", "agent:25", "agent:26"),
            topology_template_id="topology.writing.final_compilation",
            shared_context_policy="book_refs_only",
            memory_sharing_policy="shared_project_bible_refs",
            handoff_policy="compilation_contract_handoff",
            conflict_resolution_policy="editor_gate_review",
            output_merge_policy="editor_final_book_merge",
            stop_conditions=("book_compilation_accepted",),
            subtask_refs=("task.writing.final_compilation",),
            enabled=True,
            metadata={"task_id": "task.writing.final_compilation", "internal_stage": True, "managed_by": "task_system", "task_resource": "final_compilation"},
        ),
    )


def default_task_communication_protocols() -> tuple[TaskCommunicationProtocol, ...]:
    return (
        TaskCommunicationProtocol(
            protocol_id="protocol.health.repair_review",
            title="健康修复协作协议草案",
            message_types=("issue_summary", "trace_findings", "verification_result", "final_merge_request"),
            payload_contracts=("HealthIssue", "HealthTraceAnalysis", "HealthFixVerificationProposal"),
            signal_rules=("participant_report_to_coordinator", "coordinator_final_merge"),
            handoff_rules=("issue_refs_only", "structured_result_only"),
            ack_policy="explicit_ack",
            timeout_policy="fail_closed",
            error_signal_policy="raise_to_coordinator",
            enabled=False,
            metadata={"candidate_only": True},
        ),
        TaskCommunicationProtocol(
            protocol_id="protocol.writing.short_story_pipeline",
            title="短篇小说协作协议",
            message_types=(
                "idea_proposal",
                "idea_review",
                "approval_signal",
                "draft_submission",
                "content_issue",
                "revision_request",
                "acceptance_result",
            ),
            payload_contracts=(
                "StoryIdeaProposal",
                "StoryIdeaReview",
                "StoryApprovalSignal",
                "ShortStoryDraft",
                "StoryContentIssueReport",
                "StoryRevisionRequest",
                "StoryAcceptanceResult",
            ),
            signal_rules=("participant_report_to_coordinator", "coordinator_stage_gate", "acceptance_then_merge"),
            handoff_rules=("stage_refs_only", "structured_story_result_only"),
            ack_policy="explicit_ack",
            timeout_policy="fail_closed",
            error_signal_policy="raise_to_coordinator",
            enabled=True,
            metadata={"task_id": "task.writing.short_story"},
        ),
        TaskCommunicationProtocol(
            protocol_id="protocol.writing.longform_project_bootstrap",
            title="长篇小说持续交付协议",
            message_types=("project_scope", "world_seed", "character_seed", "volume_plan", "chapter_batch", "continuity_audit", "editor_merge"),
            payload_contracts=("LongformNovelProjectInput", "WorldSeed", "CharacterSeed", "VolumePlan", "ChapterDraft", "ContinuityAuditReport", "LongformNovelCompilation"),
            signal_rules=("participants_report_to_editor", "editor_locks_project_scope", "stage_gate_required", "editor_merge_gate"),
            handoff_rules=("project_refs_only", "structured_spec_only", "chapter_refs_only", "artifact_refs_only"),
            ack_policy="explicit_ack",
            timeout_policy="fail_closed",
            error_signal_policy="raise_to_editor",
            enabled=True,
            metadata={"task_id": "task.writing.longform_novel_project", "agent_group_id": "group.writing.longform_novel_core", "managed_by": "task_system", "task_resource": "longform_novel_project"},
        ),
        TaskCommunicationProtocol(
            protocol_id="protocol.writing.novel_bible_build",
            title="长篇小说设定总纲协议",
            message_types=("world_bible_section", "character_bible_section", "plot_bible_section", "bible_conflict_report", "editor_bible_merge"),
            payload_contracts=("WorldBible", "CharacterBible", "PlotBible", "BibleConflictReport", "NovelBibleBundle"),
            signal_rules=("parallel_section_submit", "conflict_report_required", "editor_merge_gate"),
            handoff_rules=("section_refs_only", "conflict_refs_required", "structured_bible_bundle_only"),
            ack_policy="explicit_ack",
            timeout_policy="fail_closed",
            error_signal_policy="raise_to_editor",
            enabled=True,
            metadata={"task_id": "task.writing.novel_bible_build", "agent_group_id": "group.writing.longform_novel_core", "internal_stage": True, "managed_by": "task_system", "task_resource": "novel_bible_build"},
        ),
        TaskCommunicationProtocol(
            protocol_id="protocol.writing.volume_planning",
            title="长篇小说卷规划协议",
            message_types=("volume_goal", "character_arc_plan", "plot_volume_plan", "volume_quality_review", "editor_volume_acceptance"),
            payload_contracts=("VolumeGoal", "CharacterArcPlan", "VolumePlotPlan", "VolumeQualityReview", "VolumePlan"),
            signal_rules=("stage_gate_required", "review_before_acceptance", "editor_acceptance_required"),
            handoff_rules=("volume_refs_only", "structured_volume_plan_only"),
            ack_policy="explicit_ack",
            timeout_policy="fail_closed",
            error_signal_policy="raise_to_editor",
            enabled=True,
            metadata={"task_id": "task.writing.volume_planning", "agent_group_id": "group.writing.longform_novel_core", "internal_stage": True, "managed_by": "task_system", "task_resource": "volume_planning"},
        ),
        TaskCommunicationProtocol(
            protocol_id="protocol.writing.chapter_pipeline",
            title="长篇小说章节协作协议",
            message_types=(
                "chapter_goal",
                "chapter_plan",
                "chapter_draft",
                "style_review",
                "continuity_review",
                "revision_request",
                "chapter_revision",
                "editor_acceptance",
            ),
            payload_contracts=(
                "ChapterGoal",
                "ChapterPlan",
                "ChapterDraft",
                "ChapterQualityReview",
                "ChapterContinuityReview",
                "ChapterRevisionRequest",
                "ChapterRevision",
                "ChapterAcceptanceResult",
            ),
            signal_rules=("plan_before_draft", "review_before_acceptance", "revision_loop_optional", "editor_acceptance_required"),
            handoff_rules=("chapter_refs_only", "draft_artifact_ref_required", "review_issue_refs_required"),
            ack_policy="explicit_ack",
            timeout_policy="fail_closed",
            error_signal_policy="raise_to_editor",
            enabled=True,
            metadata={
                "task_id": "task.writing.chapter_drafting",
                "agent_group_id": "group.writing.longform_novel_core",
                "protocol_role": "message_contract_only",
                "internal_stage": True,
                "managed_by": "task_system",
                "task_resource": "chapter_pipeline",
            },
        ),
        TaskCommunicationProtocol(
            protocol_id="protocol.writing.continuity_audit",
            title="长篇小说连续性审计协议",
            message_types=("audit_scope", "world_consistency_report", "timeline_report", "style_risk_report", "editor_audit_merge"),
            payload_contracts=("ContinuityAuditScope", "WorldConsistencyReport", "TimelineReport", "StyleRiskReport", "ContinuityAuditReport"),
            signal_rules=("evidence_refs_required", "blocking_conflicts_must_be_marked", "editor_merge_gate"),
            handoff_rules=("chapter_range_refs_only", "issue_refs_required"),
            ack_policy="explicit_ack",
            timeout_policy="fail_closed",
            error_signal_policy="raise_to_editor",
            enabled=True,
            metadata={"task_id": "task.writing.continuity_audit", "agent_group_id": "group.writing.longform_novel_core", "internal_stage": True, "managed_by": "task_system", "task_resource": "continuity_audit"},
        ),
        TaskCommunicationProtocol(
            protocol_id="protocol.writing.final_compilation",
            title="长篇小说全书编纂协议",
            message_types=("compilation_scope", "chapter_bundle_refs", "quality_final_report", "continuity_final_report", "editor_final_merge"),
            payload_contracts=("LongformCompilationInput", "ChapterBundleRefs", "FinalQualityReport", "FinalContinuityReport", "LongformNovelCompilation"),
            signal_rules=("all_chapters_refs_required", "final_reviews_required", "editor_final_merge_gate"),
            handoff_rules=("artifact_refs_only", "structured_final_book_manifest_only"),
            ack_policy="explicit_ack",
            timeout_policy="fail_closed",
            error_signal_policy="raise_to_editor",
            enabled=True,
            metadata={"task_id": "task.writing.final_compilation", "agent_group_id": "group.writing.longform_novel_core", "internal_stage": True, "managed_by": "task_system", "task_resource": "final_compilation"},
        ),
    )


def default_topology_templates() -> tuple[TopologyTemplate, ...]:
    return (
        TopologyTemplate(
            template_id="topology.health.repair_review",
            title="健康修复拓扑草案",
            nodes=(
                {"node_id": "health_triage", "agent_id": "agent:3", "lane": "health_issue_read"},
                {"node_id": "fix_verification", "agent_id": "agent:3", "lane": "fix_verification_candidate"},
                {"node_id": "final_merge", "agent_id": "agent:0", "lane": "final_integration"},
            ),
            edges=(
                {"from": "health_triage", "to": "fix_verification", "policy": "issue_refs_only"},
                {"from": "fix_verification", "to": "final_merge", "policy": "structured_result_only"},
            ),
            enabled=False,
        ),
        TopologyTemplate(
            template_id="topology.writing.short_story_pipeline",
            title="短篇小说协作拓扑",
            nodes=(
                {"node_id": "idea_worker", "agent_id": "agent:5", "lane": "creative_ideation", "role": "participant"},
                {"node_id": "idea_review", "agent_id": "agent:4", "lane": "content_review", "role": "participant"},
                {"node_id": "approval_gate", "agent_id": "agent:0", "lane": "coordination_gate", "role": "coordinator"},
                {"node_id": "draft_writer", "agent_id": "agent:5", "lane": "story_drafting", "role": "participant"},
                {"node_id": "content_check", "agent_id": "agent:4", "lane": "content_inspection", "role": "participant"},
                {"node_id": "revision_loop", "agent_id": "agent:5", "lane": "story_revision", "role": "participant"},
                {"node_id": "acceptance", "agent_id": "agent:0", "lane": "final_acceptance", "role": "coordinator"},
            ),
            edges=(
                {"from": "idea_worker", "to": "idea_review", "policy": "stage_contract_handoff"},
                {"from": "idea_review", "to": "approval_gate", "policy": "stage_contract_handoff"},
                {"from": "approval_gate", "to": "draft_writer", "policy": "stage_contract_handoff"},
                {"from": "draft_writer", "to": "content_check", "policy": "stage_contract_handoff"},
                {"from": "content_check", "to": "revision_loop", "policy": "stage_contract_handoff"},
                {"from": "revision_loop", "to": "acceptance", "policy": "stage_contract_handoff"},
            ),
            enabled=True,
        ),
        TopologyTemplate(
            template_id="topology.writing.longform_project_bootstrap",
            title="长篇小说持续交付拓扑",
            nodes=(
                {"node_id": "coordinator", "agent_id": "agent:20", "lane": "novel_project_control", "role": "coordinator"},
                {"node_id": "project_scope", "agent_id": "agent:20", "lane": "novel_project_control", "role": "participant"},
                {"node_id": "novel_bible", "agent_id": "agent:21", "lane": "novel_bible_gate", "role": "participant"},
                {"node_id": "volume_planning", "agent_id": "agent:22", "lane": "volume_acceptance", "role": "participant"},
                {"node_id": "chapter_pipeline", "agent_id": "agent:23", "lane": "chapter_planning", "role": "participant"},
                {"node_id": "chapter_drafting", "agent_id": "agent:24", "lane": "chapter_drafting", "role": "participant"},
                {"node_id": "continuity_audit", "agent_id": "agent:26", "lane": "continuity_audit", "role": "participant"},
                {"node_id": "final_compilation", "agent_id": "agent:20", "lane": "final_compilation", "role": "coordinator"},
            ),
            edges=(
                {"from": "project_scope", "to": "novel_bible", "policy": "project_contract_handoff"},
                {"from": "novel_bible", "to": "volume_planning", "policy": "stage_contract_handoff"},
                {"from": "volume_planning", "to": "chapter_pipeline", "policy": "stage_contract_handoff"},
                {"from": "chapter_pipeline", "to": "chapter_drafting", "policy": "stage_contract_handoff"},
                {"from": "chapter_drafting", "to": "continuity_audit", "policy": "stage_contract_handoff"},
                {"from": "continuity_audit", "to": "final_compilation", "policy": "stage_contract_handoff"},
            ),
            enabled=True,
            metadata={"managed_by": "task_system", "task_resource": "longform_project_bootstrap"},
        ),
        TopologyTemplate(
            template_id="topology.writing.novel_bible_build",
            title="长篇小说设定总纲拓扑",
            nodes=(
                {"node_id": "world_bible", "agent_id": "agent:21", "lane": "world_bible_build", "role": "participant"},
                {"node_id": "character_bible", "agent_id": "agent:22", "lane": "character_bible_build", "role": "participant"},
                {"node_id": "plot_bible", "agent_id": "agent:23", "lane": "volume_plot_plan", "role": "participant"},
                {"node_id": "editor_merge", "agent_id": "agent:20", "lane": "novel_bible_gate", "role": "coordinator"},
            ),
            edges=(
                {"from": "world_bible", "to": "editor_merge", "policy": "bible_section_contract_handoff"},
                {"from": "character_bible", "to": "editor_merge", "policy": "bible_section_contract_handoff"},
                {"from": "plot_bible", "to": "editor_merge", "policy": "bible_section_contract_handoff"},
            ),
            enabled=True,
        ),
        TopologyTemplate(
            template_id="topology.writing.volume_planning",
            title="长篇小说卷规划拓扑",
            nodes=(
                {"node_id": "character_arc", "agent_id": "agent:22", "lane": "volume_character_arc", "role": "participant"},
                {"node_id": "volume_plot", "agent_id": "agent:23", "lane": "volume_plot_plan", "role": "participant"},
                {"node_id": "quality_review", "agent_id": "agent:25", "lane": "arc_review", "role": "participant"},
                {"node_id": "editor_acceptance", "agent_id": "agent:20", "lane": "volume_acceptance", "role": "coordinator"},
            ),
            edges=(
                {"from": "character_arc", "to": "volume_plot", "policy": "volume_contract_handoff"},
                {"from": "volume_plot", "to": "quality_review", "policy": "volume_contract_handoff"},
                {"from": "quality_review", "to": "editor_acceptance", "policy": "volume_contract_handoff"},
            ),
            enabled=True,
        ),
        TopologyTemplate(
            template_id="topology.writing.chapter_pipeline",
            title="长篇小说章节协作拓扑",
            nodes=(
                {"node_id": "request_brief", "agent_id": "agent:20", "lane": "chapter_request_brief", "role": "coordinator", "label": "请求承接"},
                {"node_id": "chapter_plan", "agent_id": "agent:23", "lane": "chapter_plot_plan", "role": "participant", "label": "章节规划"},
                {"node_id": "chapter_draft", "agent_id": "agent:24", "lane": "chapter_drafting", "role": "participant", "label": "章节正文"},
                {"node_id": "quality_review", "agent_id": "agent:25", "lane": "chapter_quality_review", "role": "participant", "label": "质量审查"},
                {"node_id": "continuity_review", "agent_id": "agent:26", "lane": "chapter_continuity_review", "role": "participant", "label": "连续性审查"},
                {"node_id": "chapter_revision", "agent_id": "agent:24", "lane": "chapter_revision", "role": "participant", "label": "正文修订"},
                {"node_id": "editor_acceptance", "agent_id": "agent:20", "lane": "chapter_acceptance", "role": "coordinator", "label": "编辑验收"},
            ),
            edges=(
                {"from": "request_brief", "to": "chapter_plan", "policy": "chapter_contract_handoff"},
                {"from": "chapter_plan", "to": "chapter_draft", "policy": "chapter_contract_handoff"},
                {"from": "chapter_draft", "to": "quality_review", "policy": "chapter_contract_handoff"},
                {"from": "chapter_draft", "to": "continuity_review", "policy": "chapter_contract_handoff"},
                {"from": "quality_review", "to": "chapter_revision", "policy": "chapter_contract_handoff"},
                {"from": "continuity_review", "to": "chapter_revision", "policy": "chapter_contract_handoff"},
                {"from": "chapter_revision", "to": "editor_acceptance", "policy": "chapter_contract_handoff"},
            ),
            enabled=True,
            metadata={
                "task_family": "writing",
                "domain_id": "domain.writing",
                "topology_role": "stable_agent_collaboration_graph",
            },
        ),
        TopologyTemplate(
            template_id="topology.writing.continuity_audit",
            title="长篇小说连续性审计拓扑",
            nodes=(
                {"node_id": "world_consistency", "agent_id": "agent:21", "lane": "continuity_audit", "role": "participant"},
                {"node_id": "timeline_audit", "agent_id": "agent:26", "lane": "continuity_audit", "role": "participant"},
                {"node_id": "style_risk", "agent_id": "agent:25", "lane": "style_audit", "role": "participant"},
                {"node_id": "editor_audit_merge", "agent_id": "agent:20", "lane": "arc_review", "role": "coordinator"},
            ),
            edges=(
                {"from": "world_consistency", "to": "editor_audit_merge", "policy": "audit_contract_handoff"},
                {"from": "timeline_audit", "to": "editor_audit_merge", "policy": "audit_contract_handoff"},
                {"from": "style_risk", "to": "editor_audit_merge", "policy": "audit_contract_handoff"},
            ),
            enabled=True,
        ),
        TopologyTemplate(
            template_id="topology.writing.final_compilation",
            title="长篇小说全书编纂拓扑",
            nodes=(
                {"node_id": "chapter_bundle", "agent_id": "agent:24", "lane": "chapter_revision", "role": "participant"},
                {"node_id": "final_quality", "agent_id": "agent:25", "lane": "style_audit", "role": "participant"},
                {"node_id": "final_continuity", "agent_id": "agent:26", "lane": "arc_continuity_review", "role": "participant"},
                {"node_id": "editor_final_merge", "agent_id": "agent:20", "lane": "final_compilation", "role": "coordinator"},
            ),
            edges=(
                {"from": "chapter_bundle", "to": "final_quality", "policy": "compilation_contract_handoff"},
                {"from": "chapter_bundle", "to": "final_continuity", "policy": "compilation_contract_handoff"},
                {"from": "final_quality", "to": "editor_final_merge", "policy": "compilation_contract_handoff"},
                {"from": "final_continuity", "to": "editor_final_merge", "policy": "compilation_contract_handoff"},
            ),
            enabled=True,
        ),
    )


def _default_projection_binding(task: TaskAssignment) -> TaskProjectionBinding:
    selected_projection_ids = tuple(
        item
        for item in [str(task.projection_id or "").strip()]
        if item
    )
    default_projection_id = selected_projection_ids[0] if selected_projection_ids else ""
    return TaskProjectionBinding(
        binding_id=f"taskprojbind:{task.task_id}",
        task_id=task.task_id,
        projection_selection_mode="task_default" if default_projection_id else "workflow_compatible_or_task_default",
        allowed_projection_ids=selected_projection_ids,
        default_projection_id=default_projection_id,
        projection_required=bool(default_projection_id),
        notes="Derived from task assignment defaults.",
        metadata={"derived_from": "task_assignment"},
    )


def _default_flow_contract_binding(task: TaskAssignment) -> TaskFlowContractBinding:
    flow_contract_id = str(task.flow_id or "").strip()
    return TaskFlowContractBinding(
        binding_id=f"taskflowbind:{task.task_id}",
        task_id=task.task_id,
        flow_contract_id=flow_contract_id,
        override_policy="task_default",
        verification_gate_profile=str(dict(task.safety_policy or {}).get("verification_mode") or ""),
        fallback_policy="fail_closed",
        metadata={"derived_from": "task_assignment"},
    )


def _default_adoption_plan(task: TaskAssignment) -> TaskAgentAdoptionPlan:
    participant_ids = tuple(str(item).strip() for item in task.participant_agent_ids if str(item).strip())
    task_structure = dict(task.task_structure or {})
    task_metadata = dict(task.metadata or {})
    runtime_limits = dict(task_structure.get("runtime_limits") or {})
    coordination_task_id = str(
        task_structure.get("coordination_task_id") or task_metadata.get("coordination_task_id") or ""
    ).strip()
    communication_protocol_id = str(
        task_structure.get("communication_protocol_id") or task_metadata.get("communication_protocol_id") or ""
    ).strip()
    topology_template_id = str(
        task_structure.get("topology_template_id") or task_metadata.get("topology_template_id") or ""
    ).strip()
    agent_group_id = str(task_structure.get("agent_group_id") or task_metadata.get("agent_group_id") or "").strip()
    execution_chain_type = str(task.to_dict().get("execution_chain_type") or "").strip() or (
        "coordination_chain" if coordination_task_id else "single_agent_chain"
    )
    return TaskAgentAdoptionPlan(
        plan_id=f"taskadopt:{task.task_id}",
        task_id=task.task_id,
        adoption_mode="adopt_existing" if not participant_ids else "adopt_with_projection",
        default_agent_id=str(task.default_agent_id or "agent:0").strip() or "agent:0",
        allowed_agent_categories=("main_agent", "system_management_agent", "worker_sub_agent"),
        allow_worker_agent_spawn=False,
        worker_agent_blueprint_id="",
        worker_agent_naming_rule="",
        notes="Derived from task assignment defaults.",
        metadata={
            "derived_from": "task_assignment",
            "participant_agent_ids": list(participant_ids),
            "runtime_limits": runtime_limits,
            "execution_chain_type": execution_chain_type,
            "coordination_task_id": coordination_task_id,
            "communication_protocol_id": communication_protocol_id,
            "topology_template_id": topology_template_id,
            "agent_group_id": agent_group_id,
        },
    )


def _default_memory_request_profile(task: TaskAssignment) -> TaskMemoryRequestProfile:
    task_family = str(task.task_family or "").strip()
    task_mode = str(task.task_mode or "").strip()
    memory_scope_hint = str(dict(task.task_structure or {}).get("memory_scope_hint") or "").strip()
    requested_layers = ["conversation"]
    requested_topics = [task_family or task_mode or "general_task"]
    allow_long_term_memory = False
    if task_family == "health":
        requested_layers = ["state", "conversation"]
        requested_topics = ["health_issue", task_mode or "health"]
    elif task_family == "development":
        requested_layers = ["conversation", "state", "long_term"]
        requested_topics = ["project_background", "recent_workspace_state", task_mode or "development"]
        allow_long_term_memory = True
    elif task_family == "writing":
        requested_layers = ["conversation", "state", "long_term"]
        requested_topics = ["story_goal", "story_style", task_mode or "writing"]
        if task_mode.startswith("longform_") or task_mode in {
            "novel_bible_build",
            "volume_planning",
            "chapter_planning",
            "chapter_drafting",
            "chapter_revision",
            "continuity_audit",
            "final_compilation",
        }:
            requested_topics = [
                "novel_project_spec",
                "novel_bible",
                "volume_plan",
                "chapter_refs",
                task_mode,
            ]
        allow_long_term_memory = True
    elif task_mode == "general_task":
        requested_layers = ["conversation"]
        requested_topics = ["current_conversation"]
    return TaskMemoryRequestProfile(
        profile_id=f"taskmem:{task.task_id}",
        task_id=task.task_id,
        requested_memory_layers=tuple(requested_layers),
        requested_topics=tuple(requested_topics),
        memory_priority="high" if task_family in {"health", "development"} else "normal",
        writeback_policy="task_default",
        allow_long_term_memory=allow_long_term_memory,
        memory_scope_hint=memory_scope_hint,
        metadata={"derived_from": "task_assignment"},
    )


def _specific_task_record_from_assignment(task: TaskAssignment) -> SpecificTaskRecord:
    projection_policy = "fixed_projection" if str(task.projection_id or "").strip() else "workflow_compatible_or_task_default"
    return SpecificTaskRecord(
        task_id=task.task_id,
        task_title=task.task_title,
        task_family=task.task_family,
        task_mode=task.task_mode,
        description=str(dict(task.metadata or {}).get("description") or task.task_title),
        enabled=task.enabled,
        input_contract_id=task.input_contract_id,
        output_contract_id=task.output_contract_id,
        acceptance_profile_id=str(dict(task.metadata or {}).get("acceptance_profile_id") or ""),
        default_flow_contract_id=str(task.flow_id or ""),
        default_workflow_id=str(task.workflow_id or ""),
        default_projection_policy=projection_policy,
        task_policy={
            "safety_policy": dict(task.safety_policy or {}),
            "task_structure": dict(task.task_structure or {}),
            "runtime_limits": dict(dict(task.task_structure or {}).get("runtime_limits") or {}),
        },
        metadata=dict(task.metadata or {}),
    )


def _default_projection_binding_from_specific_record(record: SpecificTaskRecord) -> TaskProjectionBinding:
    projection_policy = str(record.default_projection_policy or "").strip()
    projection_required = projection_policy == "fixed_projection"
    return TaskProjectionBinding(
        binding_id=f"taskprojbind:{record.task_id}",
        task_id=record.task_id,
        projection_selection_mode=projection_policy or "workflow_compatible_or_task_default",
        allowed_projection_ids=(),
        default_projection_id="",
        projection_required=projection_required,
        notes="Derived from specific task record defaults.",
        metadata={"derived_from": "specific_task_record"},
    )


def _default_flow_contract_binding_from_specific_record(record: SpecificTaskRecord) -> TaskFlowContractBinding:
    return TaskFlowContractBinding(
        binding_id=f"taskflowbind:{record.task_id}",
        task_id=record.task_id,
        flow_contract_id=str(record.default_flow_contract_id or "").strip(),
        override_policy="task_default",
        verification_gate_profile=str(dict(record.task_policy or {}).get("verification_gate_profile") or ""),
        fallback_policy="fail_closed",
        metadata={"derived_from": "specific_task_record"},
    )


def _default_memory_request_profile_from_specific_record(record: SpecificTaskRecord) -> TaskMemoryRequestProfile:
    task_family = str(record.task_family or "").strip()
    task_mode = str(record.task_mode or "").strip()
    task_policy = dict(record.task_policy or {})
    task_structure = dict(task_policy.get("task_structure") or {})
    memory_scope_hint = str(task_structure.get("memory_scope_hint") or "").strip()
    requested_layers = ["conversation"]
    requested_topics = [task_family or task_mode or "specific_task"]
    allow_long_term_memory = False
    if task_family == "health":
        requested_layers = ["state", "conversation"]
        requested_topics = ["health_issue", task_mode or "health"]
    elif task_family == "development":
        requested_layers = ["conversation", "state", "long_term"]
        requested_topics = ["project_background", "recent_workspace_state", task_mode or "development"]
        allow_long_term_memory = True
    elif task_family == "writing":
        requested_layers = ["conversation", "state", "long_term"]
        requested_topics = ["story_goal", "story_style", task_mode or "writing"]
        if task_mode.startswith("longform_") or task_mode in {
            "novel_bible_build",
            "volume_planning",
            "chapter_planning",
            "chapter_drafting",
            "chapter_revision",
            "continuity_audit",
            "final_compilation",
        }:
            requested_topics = [
                "novel_project_spec",
                "novel_bible",
                "volume_plan",
                "chapter_refs",
                task_mode,
            ]
        allow_long_term_memory = True
    return TaskMemoryRequestProfile(
        profile_id=f"taskmem:{record.task_id}",
        task_id=record.task_id,
        requested_memory_layers=tuple(requested_layers),
        requested_topics=tuple(requested_topics),
        memory_priority="high" if task_family in {"health", "development"} else "normal",
        writeback_policy="task_default",
        allow_long_term_memory=allow_long_term_memory,
        memory_scope_hint=memory_scope_hint,
        metadata={"derived_from": "specific_task_record"},
    )


def _synthetic_task_from_general_profile(profile: GeneralTaskProfile) -> TaskAssignment:
    return TaskAssignment(
        task_id=profile.profile_id,
        task_title=profile.title,
        task_kind="general_task",
        task_family="general",
        task_mode="general_task",
        flow_id="flow.general.main_conversation",
        default_agent_id=str(profile.default_agent_id or "agent:0").strip() or "agent:0",
        participant_agent_ids=(),
        workflow_id=str(profile.default_workflow_id or ""),
        workflow_file_ref=f"workflow:{profile.default_workflow_id}" if profile.default_workflow_id else "",
        projection_id=str(profile.default_projection_id or ""),
        input_contract_id=str(profile.input_contract_id or ""),
        output_contract_id=str(profile.output_contract_id or ""),
        safety_policy={},
        task_structure={
            "entry_channel": str(profile.entry_channel or "main_conversation"),
            "memory_scope_hint": "conversation_read_write",
        },
        enabled=profile.enabled,
        metadata=dict(profile.metadata or {}),
    )


class TaskFlowRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.agent_registry = AgentRegistry(self.base_dir)
        self.agent_group_registry = None
        self.agent_runtime_registry = AgentRuntimeRegistry(self.base_dir)
        self.template_registry = TaskTemplateRegistry(self.base_dir)
        self.workflow_registry = TaskWorkflowRegistry(self.base_dir)

    def list_general_task_profiles(self) -> list[GeneralTaskProfile]:
        payload = _read_json(
            _general_profiles_path(self.base_dir),
            {"profiles": [item.to_dict() for item in default_general_task_profiles()]},
        )
        profiles: list[GeneralTaskProfile] = []
        for item in list(payload.get("profiles") or []):
            if not isinstance(item, dict):
                continue
            profiles.append(
                GeneralTaskProfile(
                    profile_id=str(item.get("profile_id") or ""),
                    title=str(item.get("title") or ""),
                    entry_channel=str(item.get("entry_channel") or "main_conversation"),
                    default_agent_id=str(item.get("default_agent_id") or "agent:0"),
                    default_workflow_id=str(item.get("default_workflow_id") or ""),
                    default_projection_id=str(item.get("default_projection_id") or ""),
                    input_contract_id=str(item.get("input_contract_id") or ""),
                    output_contract_id=str(item.get("output_contract_id") or ""),
                    conversation_entry_policy=str(item.get("conversation_entry_policy") or "user_dialogue_to_main_agent"),
                    enabled=bool(item.get("enabled", True)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return profiles

    def upsert_general_task_profile(
        self,
        *,
        profile_id: str,
        title: str,
        default_agent_id: str,
        default_workflow_id: str,
        default_projection_id: str = "",
        input_contract_id: str = "",
        output_contract_id: str = "",
        conversation_entry_policy: str = "user_dialogue_to_main_agent",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> GeneralTaskProfile:
        target = str(profile_id or "").strip()
        if not target.startswith("general."):
            raise ValueError("profile_id must start with general.")
        profile = GeneralTaskProfile(
            profile_id=target,
            title=str(title or target).strip(),
            entry_channel="main_conversation",
            default_agent_id=str(default_agent_id or "agent:0").strip() or "agent:0",
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_projection_id=str(default_projection_id or "").strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            conversation_entry_policy=str(conversation_entry_policy or "user_dialogue_to_main_agent").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        profiles = [item for item in self.list_general_task_profiles() if item.profile_id != target]
        profiles.append(profile)
        _write_json(_general_profiles_path(self.base_dir), {"profiles": [item.to_dict() for item in profiles]})
        return profile

    def list_flows(self) -> list[TaskFlowDefinition]:
        default_payload = [item.to_dict() for item in default_task_flows()]
        payload = _read_json(
            _flows_path(self.base_dir),
            {"flows": default_payload},
        )
        merged_payload = _merge_default_overlay_by_key(
            default_payload,
            [item for item in list(payload.get("flows") or []) if isinstance(item, dict)],
            key="flow_id",
        )
        flows = []
        for item in merged_payload:
            flows.append(
                TaskFlowDefinition(
                    flow_id=str(item.get("flow_id") or ""),
                    task_mode=str(item.get("task_mode") or ""),
                    task_family=str(item.get("task_family") or ""),
                    title=str(item.get("title") or ""),
                    input_contract_id=str(item.get("input_contract_id") or ""),
                    output_contract_id=str(item.get("output_contract_id") or ""),
                    default_agent_id=str(item.get("default_agent_id") or ""),
                    default_workflow_id=str(item.get("default_workflow_id") or ""),
                    default_runtime_lane=str(item.get("default_runtime_lane") or ""),
                    default_memory_scope=str(item.get("default_memory_scope") or ""),
                    enabled=bool(item.get("enabled", True)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in flows]
        if payload.get("flows") != normalized:
            _write_json(_flows_path(self.base_dir), {"flows": normalized})
        return flows

    def get_flow(self, flow_id: str) -> TaskFlowDefinition | None:
        target = str(flow_id or "").strip()
        return next((item for item in self.list_flows() if item.flow_id == target), None)

    def next_flow_id(self) -> str:
        return _next_prefixed_id(
            [item.flow_id for item in self.list_flows()],
            prefix="flow.",
        )

    def upsert_flow(
        self,
        *,
        flow_id: str,
        task_mode: str,
        task_family: str,
        title: str,
        input_contract_id: str,
        output_contract_id: str,
        default_agent_id: str,
        default_workflow_id: str,
        default_runtime_lane: str,
        default_memory_scope: str,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TaskFlowDefinition:
        normalized_flow_id = str(flow_id or "").strip()
        if not normalized_flow_id.startswith("flow."):
            raise ValueError("flow_id must start with flow.")
        flow = TaskFlowDefinition(
            flow_id=normalized_flow_id,
            task_mode=str(task_mode or "").strip(),
            task_family=str(task_family or "").strip(),
            title=str(title or normalized_flow_id).strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            default_agent_id=str(default_agent_id or "").strip(),
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_runtime_lane=str(default_runtime_lane or "").strip(),
            default_memory_scope=str(default_memory_scope or "").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        flows = [item for item in self.list_flows() if item.flow_id != normalized_flow_id]
        flows.append(flow)
        _write_json(_flows_path(self.base_dir), {"flows": [item.to_dict() for item in flows]})
        return flow

    def list_task_assignments(self) -> list[TaskAssignment]:
        default_assignments = [self._assignment_from_specific_task_record(item).to_dict() for item in self.list_specific_task_records()]
        payload = _read_json(
            _assignments_path(self.base_dir),
            {"assignments": default_assignments},
        )
        merged_payload = _merge_items_by_key(
            default_assignments,
            [item for item in list(payload.get("assignments") or []) if isinstance(item, dict)],
            key="task_id",
        )
        assignments: list[TaskAssignment] = []
        for item in merged_payload:
            assignments.append(_assignment_from_dict(item))
        normalized = [item.to_dict() for item in assignments]
        if payload.get("assignments") != normalized:
            _write_json(_assignments_path(self.base_dir), {"assignments": normalized})
        return assignments

    def get_general_task_profile(self, profile_id: str) -> GeneralTaskProfile | None:
        target = str(profile_id or "").strip()
        return next((item for item in self.list_general_task_profiles() if item.profile_id == target), None)

    def get_task_assignment(self, task_id: str) -> TaskAssignment | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_task_assignments() if item.task_id == target), None)

    def next_specific_task_id(self) -> str:
        ids = [item.task_id for item in self.list_task_assignments()]
        ids.extend(item.task_id for item in self.list_specific_task_records())
        return _next_prefixed_id(ids, prefix="task.")

    def list_task_domains(self) -> list[TaskDomainRecord]:
        default_payload = [item.to_dict() for item in default_task_domains()]
        payload = _read_json(
            _task_domains_path(self.base_dir),
            {"task_domains": default_payload},
        )
        deleted_domain_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_domain_ids") or [])
            if str(item).strip()
        }
        merged_payload = _merge_default_overlay_by_key(
            [item for item in default_payload if str(item.get("domain_id") or "").strip() not in deleted_domain_ids],
            [item for item in list(payload.get("task_domains") or []) if isinstance(item, dict)],
            key="domain_id",
        )
        domains: list[TaskDomainRecord] = []
        for item in merged_payload:
            task_family = str(item.get("task_family") or "").strip()
            domain_id = str(item.get("domain_id") or "").strip() or f"domain.{task_family or 'custom'}"
            domains.append(
                TaskDomainRecord(
                    domain_id=domain_id,
                    task_family=task_family,
                    title=str(item.get("title") or domain_id).strip(),
                    description=str(item.get("description") or "").strip(),
                    enabled=bool(item.get("enabled", True)),
                    sort_order=int(item.get("sort_order", 0) or 0),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        known_families = {item.task_family for item in domains if item.task_family}
        inferred_families = sorted({item.task_family for item in self.list_specific_task_records() if item.task_family})
        next_sort = max((item.sort_order for item in domains), default=0)
        for family in inferred_families:
            if family in known_families:
                continue
            next_sort += 10
            domains.append(
                TaskDomainRecord(
                    domain_id=f"domain.{family}",
                    task_family=family,
                    title=f"{family}任务域",
                    description="",
                    enabled=True,
                    sort_order=next_sort,
                    metadata={"derived": True},
                )
            )
        domains = sorted(domains, key=lambda item: (item.sort_order, item.title, item.domain_id))
        normalized = [item.to_dict() for item in domains]
        if payload.get("task_domains") != normalized:
            _write_json(
                _task_domains_path(self.base_dir),
                {
                    "task_domains": normalized,
                    "deleted_domain_ids": sorted(deleted_domain_ids),
                },
            )
        return domains

    def get_task_domain(self, domain_id: str) -> TaskDomainRecord | None:
        target = str(domain_id or "").strip()
        if not target:
            return None
        return next((item for item in self.list_task_domains() if item.domain_id == target), None)

    def upsert_task_domain(
        self,
        *,
        domain_id: str,
        task_family: str,
        title: str,
        description: str = "",
        enabled: bool = True,
        sort_order: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> TaskDomainRecord:
        normalized_family = str(task_family or "").strip()
        normalized_domain_id = str(domain_id or "").strip() or f"domain.{normalized_family}"
        if not normalized_family:
            raise ValueError("task_family is required")
        if not normalized_domain_id.startswith("domain."):
            raise ValueError("domain_id must start with domain.")
        record = TaskDomainRecord(
            domain_id=normalized_domain_id,
            task_family=normalized_family,
            title=str(title or normalized_family).strip(),
            description=str(description or "").strip(),
            enabled=bool(enabled),
            sort_order=int(sort_order),
            metadata=dict(metadata or {}),
        )
        domains = [item for item in self.list_task_domains() if item.domain_id != normalized_domain_id]
        domains.append(record)
        domains = sorted(domains, key=lambda item: (item.sort_order, item.title, item.domain_id))
        payload = _read_json(_task_domains_path(self.base_dir), {"task_domains": []})
        deleted_domain_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_domain_ids") or [])
            if str(item).strip() and str(item).strip() != normalized_domain_id
        }
        _write_json(
            _task_domains_path(self.base_dir),
            {
                "task_domains": [item.to_dict() for item in domains],
                "deleted_domain_ids": sorted(deleted_domain_ids),
            },
        )
        return record

    def delete_task_domain(self, domain_id: str) -> dict[str, Any]:
        target = str(domain_id or "").strip()
        domain = self.get_task_domain(target)
        if domain is None:
            raise ValueError("task domain not found")
        task_family = domain.task_family
        task_ids = {item.task_id for item in self.list_specific_task_records() if item.task_family == task_family}
        flow_ids = {
            item.flow_id
            for item in self.list_flows()
            if item.task_family == task_family
            or str(item.metadata.get("task_id") or "") in task_ids
            or _family_from_ref(item.flow_id) == task_family
        }
        coordination_ids = {
            item.coordination_task_id
            for item in self.list_coordination_tasks()
            if str(item.metadata.get("task_family") or "") == task_family
            or str(item.metadata.get("domain_id") or "") == target
            or any(ref in task_ids for ref in item.subtask_refs)
            or _family_from_ref(item.coordination_task_id) == task_family
        }
        topology_ids = {
            item.template_id
            for item in self.list_topology_templates()
            if str(item.metadata.get("task_family") or "") == task_family
            or str(item.metadata.get("domain_id") or "") == target
            or _family_from_ref(item.template_id) == task_family
        }
        protocol_ids = {
            item.protocol_id
            for item in self.list_task_communication_protocols()
            if str(item.metadata.get("task_family") or "") == task_family
            or str(item.metadata.get("domain_id") or "") == target
            or str(item.metadata.get("task_id") or "") in task_ids
            or _family_from_ref(item.protocol_id) == task_family
        }
        workflow_ids = self._collect_deletable_workflow_ids(
            task_ids=task_ids,
            flow_ids=flow_ids,
        )

        domains = [item for item in self.list_task_domains() if item.domain_id != target]
        payload = _read_json(_task_domains_path(self.base_dir), {"task_domains": []})
        deleted_domain_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_domain_ids") or [])
            if str(item).strip()
        }
        deleted_domain_ids.add(target)
        _write_json(
            _task_domains_path(self.base_dir),
            {
                "task_domains": [item.to_dict() for item in domains],
                "deleted_domain_ids": sorted(deleted_domain_ids),
            },
        )
        _write_json(
            _specific_task_records_path(self.base_dir),
            {"specific_task_records": [item.to_dict() for item in self.list_specific_task_records() if item.task_id not in task_ids]},
        )
        _write_json(
            _assignments_path(self.base_dir),
            {"assignments": [item.to_dict() for item in self.list_task_assignments() if item.task_id not in task_ids]},
        )
        _write_json(
            _flows_path(self.base_dir),
            {"flows": [item.to_dict() for item in self.list_flows() if item.flow_id not in flow_ids]},
        )
        _write_json(
            _projection_bindings_path(self.base_dir),
            {"projection_bindings": [item.to_dict() for item in self.list_projection_bindings() if item.task_id not in task_ids]},
        )
        _write_json(
            _flow_contract_bindings_path(self.base_dir),
            {"flow_contract_bindings": [item.to_dict() for item in self.list_flow_contract_bindings() if item.task_id not in task_ids]},
        )
        _write_json(
            _adoption_plans_path(self.base_dir),
            {"adoption_plans": [item.to_legacy_dict() for item in self.list_task_agent_adoption_plans() if item.task_id not in task_ids]},
        )
        _write_json(
            _memory_request_profiles_path(self.base_dir),
            {"memory_request_profiles": [item.to_dict() for item in self.list_task_memory_request_profiles() if item.task_id not in task_ids]},
        )
        _write_json(
            _coordination_tasks_path(self.base_dir),
            {"coordination_tasks": [item.to_dict() for item in self.list_coordination_tasks() if item.coordination_task_id not in coordination_ids]},
        )
        _write_json(
            _topology_templates_path(self.base_dir),
            {"topology_templates": [item.to_dict() for item in self.list_topology_templates() if item.template_id not in topology_ids]},
        )
        _write_json(
            _communication_protocols_path(self.base_dir),
            {"communication_protocols": [item.to_dict() for item in self.list_task_communication_protocols() if item.protocol_id not in protocol_ids]},
        )
        deleted_workflow_ids = self.workflow_registry.delete_workflows(workflow_ids)
        return {
            "domain_id": target,
            "task_family": task_family,
            "deleted_task_ids": sorted(task_ids),
            "deleted_flow_ids": sorted(flow_ids),
            "deleted_workflow_ids": list(deleted_workflow_ids),
            "deleted_coordination_task_ids": sorted(coordination_ids),
            "deleted_topology_template_ids": sorted(topology_ids),
            "deleted_protocol_ids": sorted(protocol_ids),
        }

    def list_specific_task_records(self) -> list[SpecificTaskRecord]:
        default_records = [self._specific_task_record_from_flow(flow).to_dict() for flow in self.list_flows()]
        payload = _read_json(
            _specific_task_records_path(self.base_dir),
            {"specific_task_records": default_records},
        )
        deleted_task_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_task_ids") or [])
            if str(item).strip()
        }
        records: list[SpecificTaskRecord] = []
        merged_payload = _merge_default_overlay_by_key(
            [item for item in default_records if str(item.get("task_id") or "").strip() not in deleted_task_ids],
            [item for item in list(payload.get("specific_task_records") or []) if isinstance(item, dict)],
            key="task_id",
        )
        for item in merged_payload:
            records.append(
                SpecificTaskRecord(
                    task_id=str(item.get("task_id") or ""),
                    task_title=str(item.get("task_title") or ""),
                    task_family=str(item.get("task_family") or ""),
                    task_mode=str(item.get("task_mode") or ""),
                    description=str(item.get("description") or ""),
                    enabled=bool(item.get("enabled", True)),
                    input_contract_id=str(item.get("input_contract_id") or ""),
                    output_contract_id=str(item.get("output_contract_id") or ""),
                    acceptance_profile_id=str(item.get("acceptance_profile_id") or ""),
                    default_flow_contract_id=str(item.get("default_flow_contract_id") or ""),
                    default_workflow_id=str(item.get("default_workflow_id") or ""),
                    default_projection_policy=str(item.get("default_projection_policy") or ""),
                    task_policy=dict(item.get("task_policy") or {}),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        if not records:
            legacy_payload = _read_json(_assignments_path(self.base_dir), {"assignments": []})
            for item in list(legacy_payload.get("assignments") or []):
                if not isinstance(item, dict):
                    continue
                records.append(_specific_task_record_from_assignment(_assignment_from_dict(item)))
        if not records:
            records = [self._specific_task_record_from_flow(flow) for flow in self.list_flows()]
        if records:
            normalized = [item.to_dict() for item in records]
            if payload.get("specific_task_records") != normalized:
                _write_json(
                    _specific_task_records_path(self.base_dir),
                    {
                        "specific_task_records": normalized,
                        "deleted_task_ids": sorted(deleted_task_ids),
                    },
                )
        return records

    def get_specific_task_record(self, task_id: str) -> SpecificTaskRecord | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_specific_task_records() if item.task_id == target), None)

    def upsert_task_assignment(
        self,
        *,
        task_id: str,
        task_title: str,
        task_kind: str,
        task_family: str,
        task_mode: str,
        flow_id: str,
        default_agent_id: str,
        participant_agent_ids: tuple[str, ...] = (),
        workflow_id: str = "",
        workflow_file_ref: str = "",
        projection_id: str = "",
        input_contract_id: str = "",
        output_contract_id: str = "",
        safety_policy: dict[str, Any] | None = None,
        task_structure: dict[str, Any] | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TaskAssignment:
        target = str(task_id or "").strip()
        if not target.startswith("task."):
            raise ValueError("task_id must start with task.")
        normalized_flow_id = str(flow_id or f"flow.{target.removeprefix('task.')}").strip()
        if not normalized_flow_id.startswith("flow."):
            raise ValueError("flow_id must start with flow.")
        normalized_metadata = dict(metadata or {})
        normalized_task_structure = dict(task_structure or {})
        record = self.upsert_specific_task_record(
            task_id=target,
            task_title=task_title,
            task_family=task_family,
            task_mode=task_mode,
            description=str(normalized_metadata.get("description") or task_title or target).strip(),
            enabled=enabled,
            input_contract_id=input_contract_id,
            output_contract_id=output_contract_id,
            acceptance_profile_id=str(normalized_metadata.get("acceptance_profile_id") or ""),
            default_flow_contract_id=normalized_flow_id,
            default_workflow_id=workflow_id,
            default_projection_policy="fixed_projection" if str(projection_id or "").strip() else "workflow_compatible_or_task_default",
            task_policy={
                "safety_policy": dict(safety_policy or {}),
                "task_structure": {
                    **normalized_task_structure,
                    "trigger_signals": list(normalized_task_structure.get("trigger_signals") or []),
                    "notes": str(normalized_task_structure.get("notes") or ""),
                },
            },
            metadata=normalized_metadata,
        )
        self.upsert_flow(
            flow_id=normalized_flow_id,
            task_mode=record.task_mode,
            task_family=record.task_family,
            title=record.task_title,
            input_contract_id=record.input_contract_id,
            output_contract_id=record.output_contract_id,
            default_agent_id=str(default_agent_id or "agent:0").strip() or "agent:0",
            default_workflow_id=record.default_workflow_id,
            default_runtime_lane=str(dict(record.task_policy or {}).get("task_structure", {}).get("runtime_lane_hint") or ""),
            default_memory_scope=str(dict(record.task_policy or {}).get("task_structure", {}).get("memory_scope_hint") or ""),
            enabled=record.enabled,
            metadata={**dict(record.metadata or {}), "task_assignment_id": record.task_id},
        )
        assignment = TaskAssignment(
            task_id=target,
            task_title=record.task_title,
            task_kind=str(task_kind or "specific_task").strip(),
            task_family=record.task_family,
            task_mode=record.task_mode,
            flow_id=normalized_flow_id,
            default_agent_id=str(default_agent_id or "agent:0").strip() or "agent:0",
            participant_agent_ids=tuple(str(item).strip() for item in participant_agent_ids if str(item).strip()),
            workflow_id=record.default_workflow_id,
            workflow_file_ref=str(workflow_file_ref or "").strip(),
            projection_id=str(projection_id or "").strip(),
            input_contract_id=record.input_contract_id,
            output_contract_id=record.output_contract_id,
            safety_policy=dict(safety_policy or {}),
            task_structure=normalized_task_structure,
            enabled=record.enabled,
            metadata=normalized_metadata,
        )
        assignments = [item for item in self.list_task_assignments() if item.task_id != target]
        assignments.append(assignment)
        _write_json(_assignments_path(self.base_dir), {"assignments": [item.to_dict() for item in assignments]})
        return assignment

    def upsert_specific_task_record(
        self,
        *,
        task_id: str,
        task_title: str,
        task_family: str,
        task_mode: str,
        description: str = "",
        enabled: bool = True,
        input_contract_id: str = "",
        output_contract_id: str = "",
        acceptance_profile_id: str = "",
        default_flow_contract_id: str = "",
        default_workflow_id: str = "",
        default_projection_policy: str = "",
        task_policy: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpecificTaskRecord:
        target = str(task_id or "").strip()
        if not target.startswith("task."):
            raise ValueError("task_id must start with task.")
        record = SpecificTaskRecord(
            task_id=target,
            task_title=str(task_title or target).strip(),
            task_family=str(task_family or "").strip(),
            task_mode=str(task_mode or "").strip(),
            description=str(description or task_title or target).strip(),
            enabled=bool(enabled),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            acceptance_profile_id=str(acceptance_profile_id or "").strip(),
            default_flow_contract_id=str(default_flow_contract_id or "").strip(),
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_projection_policy=str(default_projection_policy or "").strip(),
            task_policy=dict(task_policy or {}),
            metadata=dict(metadata or {}),
        )
        records = [item for item in self.list_specific_task_records() if item.task_id != target]
        records.append(record)
        payload = _read_json(_specific_task_records_path(self.base_dir), {"specific_task_records": []})
        deleted_task_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_task_ids") or [])
            if str(item).strip() and str(item).strip() != target
        }
        _write_json(
            _specific_task_records_path(self.base_dir),
            {
                "specific_task_records": [item.to_dict() for item in records],
                "deleted_task_ids": sorted(deleted_task_ids),
            },
        )
        return record

    def delete_specific_task_record(self, task_id: str) -> dict[str, Any]:
        target = str(task_id or "").strip()
        record = self.get_specific_task_record(target)
        if record is None:
            raise ValueError("specific task not found")
        flow_ids = {
            item.flow_id
            for item in self.list_flows()
            if str(item.metadata.get("task_id") or "") == target
            or item.flow_id == record.default_flow_contract_id
            or item.flow_id == f"flow.{target.removeprefix('task.')}"
        }
        workflow_ids = self._collect_deletable_workflow_ids(
            task_ids={target},
            flow_ids=flow_ids,
        )
        payload = _read_json(_specific_task_records_path(self.base_dir), {"specific_task_records": []})
        deleted_task_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_task_ids") or [])
            if str(item).strip()
        }
        deleted_task_ids.add(target)
        _write_json(
            _specific_task_records_path(self.base_dir),
            {
                "specific_task_records": [item.to_dict() for item in self.list_specific_task_records() if item.task_id != target],
                "deleted_task_ids": sorted(deleted_task_ids),
            },
        )
        _write_json(
            _assignments_path(self.base_dir),
            {"assignments": [item.to_dict() for item in self.list_task_assignments() if item.task_id != target]},
        )
        _write_json(
            _flows_path(self.base_dir),
            {"flows": [item.to_dict() for item in self.list_flows() if item.flow_id not in flow_ids]},
        )
        _write_json(
            _projection_bindings_path(self.base_dir),
            {"projection_bindings": [item.to_dict() for item in self.list_projection_bindings() if item.task_id != target]},
        )
        _write_json(
            _flow_contract_bindings_path(self.base_dir),
            {"flow_contract_bindings": [item.to_dict() for item in self.list_flow_contract_bindings() if item.task_id != target]},
        )
        _write_json(
            _adoption_plans_path(self.base_dir),
            {"adoption_plans": [item.to_legacy_dict() for item in self.list_task_agent_adoption_plans() if item.task_id != target]},
        )
        _write_json(
            _memory_request_profiles_path(self.base_dir),
            {"memory_request_profiles": [item.to_dict() for item in self.list_task_memory_request_profiles() if item.task_id != target]},
        )
        coordination_updates: list[CoordinationTaskDefinition] = []
        for item in self.list_coordination_tasks():
            next_nodes = tuple(
                dict(node)
                for node in item.graph_nodes
                if str(dict(node).get("task_id") or dict(node).get("subtask_ref") or "").strip() != target
            )
            next_edges = tuple(
                dict(edge)
                for edge in item.graph_edges
                if str(dict(edge).get("from") or "") in {str(node.get("node_id") or "") for node in next_nodes}
                and str(dict(edge).get("to") or "") in {str(node.get("node_id") or "") for node in next_nodes}
            )
            next_subtasks = tuple(ref for ref in item.subtask_refs if ref != target)
            if len(next_nodes) != len(item.graph_nodes) or len(next_subtasks) != len(item.subtask_refs):
                coordination_updates.append(
                    CoordinationTaskDefinition(
                        coordination_task_id=item.coordination_task_id,
                        title=item.title,
                        coordination_mode=item.coordination_mode,
                        coordinator_agent_id=item.coordinator_agent_id,
                        task_family=item.task_family,
                        domain_id=item.domain_id,
                        agent_group_id=item.agent_group_id,
                        participant_agent_ids=item.participant_agent_ids,
                        topology_template_id=item.topology_template_id,
                        shared_context_policy=item.shared_context_policy,
                        memory_sharing_policy=item.memory_sharing_policy,
                        handoff_policy=item.handoff_policy,
                        conflict_resolution_policy=item.conflict_resolution_policy,
                        output_merge_policy=item.output_merge_policy,
                        stop_conditions=item.stop_conditions,
                        subtask_refs=next_subtasks,
                        graph_nodes=next_nodes,
                        graph_edges=next_edges,
                        communication_modes=item.communication_modes,
                        enabled=item.enabled,
                        metadata=item.metadata,
                    )
                )
            else:
                coordination_updates.append(item)
        _write_json(
            _coordination_tasks_path(self.base_dir),
            {"coordination_tasks": [item.to_dict() for item in coordination_updates]},
        )
        deleted_workflow_ids = self.workflow_registry.delete_workflows(workflow_ids)
        return {
            "task_id": target,
            "task_family": record.task_family,
            "deleted_flow_ids": sorted(flow_ids),
            "deleted_workflow_ids": list(deleted_workflow_ids),
        }

    def _assignment_from_flow(self, flow: TaskFlowDefinition) -> TaskAssignment:
        workflow = self.workflow_registry.get_workflow(flow.default_workflow_id)
        template = self.template_registry.get_template(str(flow.metadata.get("template_id") or ""))
        task_id = str(flow.metadata.get("task_id") or f"task.{flow.task_family}.{flow.task_mode}").strip()
        return TaskAssignment(
            task_id=task_id,
            task_title=flow.title,
            task_kind="specific_task",
            task_family=flow.task_family,
            task_mode=flow.task_mode,
            flow_id=flow.flow_id,
            default_agent_id=flow.default_agent_id or "agent:0",
            participant_agent_ids=(),
            workflow_id=flow.default_workflow_id,
            workflow_file_ref=f"workflow:{flow.default_workflow_id}" if flow.default_workflow_id else "",
            projection_id="",
            input_contract_id=flow.input_contract_id,
            output_contract_id=flow.output_contract_id,
            safety_policy=dict(getattr(template, "safety_policy", {}) or {}),
            task_structure={
                "runtime_lane_hint": flow.default_runtime_lane,
                "memory_scope_hint": flow.default_memory_scope,
                "workflow_steps": [dict(item) for item in workflow.steps] if workflow is not None else [],
                "task_resource_kind": str(flow.metadata.get("task_resource") or ""),
            },
            enabled=flow.enabled,
            metadata={**flow.metadata, "source_flow_id": flow.flow_id},
        )

    def _specific_task_record_from_flow(self, flow: TaskFlowDefinition) -> SpecificTaskRecord:
        assignment = self._assignment_from_flow(flow)
        return _specific_task_record_from_assignment(assignment)

    def _assignment_from_specific_task_record(self, record: SpecificTaskRecord) -> TaskAssignment:
        flow_id = str(record.default_flow_contract_id or f"flow.{record.task_id.removeprefix('task.')}").strip()
        task_policy = dict(record.task_policy or {})
        task_structure = dict(task_policy.get("task_structure") or {})
        safety_policy = dict(task_policy.get("safety_policy") or {})
        flow = self.get_flow(flow_id)
        default_agent_id = str(getattr(flow, "default_agent_id", "") or "agent:0").strip() or "agent:0"
        flow_metadata = dict(getattr(flow, "metadata", {}) or {})
        task_structure = {
            **task_structure,
            **(
                {
                    "coordination_task_id": str(flow_metadata.get("coordination_task_id") or "").strip(),
                    "communication_protocol_id": str(flow_metadata.get("communication_protocol_id") or "").strip(),
                    "topology_template_id": str(flow_metadata.get("topology_template_id") or "").strip(),
                    "agent_group_id": str(flow_metadata.get("agent_group_id") or "").strip(),
                }
                if flow is not None
                else {}
            ),
        }
        projection_id = ""
        projection_binding = self.get_projection_binding(record.task_id)
        if projection_binding is not None:
            projection_id = str(projection_binding.default_projection_id or "").strip()
        workflow_file_ref = f"workflow:{record.default_workflow_id}" if record.default_workflow_id else ""
        return TaskAssignment(
            task_id=record.task_id,
            task_title=record.task_title,
            task_kind="specific_task",
            task_family=record.task_family,
            task_mode=record.task_mode,
            flow_id=flow_id,
            default_agent_id=default_agent_id,
            participant_agent_ids=(),
            workflow_id=record.default_workflow_id,
            workflow_file_ref=workflow_file_ref,
            projection_id=projection_id,
            input_contract_id=record.input_contract_id,
            output_contract_id=record.output_contract_id,
            safety_policy=safety_policy,
            task_structure=task_structure,
            enabled=record.enabled,
            metadata=dict(record.metadata or {}),
        )

    def list_bindings(self) -> list[TaskAgentBinding]:
        return [self.build_binding_for_flow(flow) for flow in self.list_flows()]

    def list_projection_bindings(self) -> list[TaskProjectionBinding]:
        default_bindings = [
            *[_default_projection_binding(_synthetic_task_from_general_profile(item)).to_dict() for item in self.list_general_task_profiles()],
            *[_default_projection_binding_from_specific_record(item).to_dict() for item in self.list_specific_task_records()],
        ]
        payload = _read_json(
            _projection_bindings_path(self.base_dir),
            {"projection_bindings": default_bindings},
        )
        merged_payload = _merge_items_by_key(
            default_bindings,
            [item for item in list(payload.get("projection_bindings") or []) if isinstance(item, dict)],
            key="binding_id",
        )
        bindings: list[TaskProjectionBinding] = []
        for item in merged_payload:
            bindings.append(
                TaskProjectionBinding(
                    binding_id=str(item.get("binding_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    projection_selection_mode=str(item.get("projection_selection_mode") or "task_default"),
                    allowed_projection_ids=tuple(
                        str(value).strip()
                        for value in list(item.get("allowed_projection_ids") or [])
                        if str(value).strip()
                    ),
                    default_projection_id=str(item.get("default_projection_id") or ""),
                    projection_required=bool(item.get("projection_required", False)),
                    notes=str(item.get("notes") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in bindings]
        if payload.get("projection_bindings") != normalized:
            _write_json(_projection_bindings_path(self.base_dir), {"projection_bindings": normalized})
        return bindings

    def get_projection_binding(self, task_id: str) -> TaskProjectionBinding | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_projection_bindings() if item.task_id == target), None)

    def upsert_projection_binding(
        self,
        *,
        task_id: str,
        projection_selection_mode: str = "task_default",
        allowed_projection_ids: tuple[str, ...] = (),
        default_projection_id: str = "",
        projection_required: bool = False,
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskProjectionBinding:
        target = str(task_id or "").strip()
        if not target.startswith(("task.", "general.")):
            raise ValueError("task_id must start with task. or general.")
        binding = TaskProjectionBinding(
            binding_id=f"taskprojbind:{target}",
            task_id=target,
            projection_selection_mode=str(projection_selection_mode or "task_default").strip(),
            allowed_projection_ids=tuple(
                str(value).strip()
                for value in allowed_projection_ids
                if str(value).strip()
            ),
            default_projection_id=str(default_projection_id or "").strip(),
            projection_required=bool(projection_required),
            notes=str(notes or "").strip(),
            metadata=dict(metadata or {}),
        )
        bindings = [item for item in self.list_projection_bindings() if item.task_id != target]
        bindings.append(binding)
        _write_json(
            _projection_bindings_path(self.base_dir),
            {"projection_bindings": [item.to_dict() for item in bindings]},
        )
        return binding

    def list_flow_contract_bindings(self) -> list[TaskFlowContractBinding]:
        default_bindings = [
            *[_default_flow_contract_binding(_synthetic_task_from_general_profile(item)).to_dict() for item in self.list_general_task_profiles()],
            *[_default_flow_contract_binding_from_specific_record(item).to_dict() for item in self.list_specific_task_records()],
        ]
        payload = _read_json(
            _flow_contract_bindings_path(self.base_dir),
            {"flow_contract_bindings": default_bindings},
        )
        merged_payload = _merge_items_by_key(
            default_bindings,
            [item for item in list(payload.get("flow_contract_bindings") or []) if isinstance(item, dict)],
            key="binding_id",
        )
        bindings: list[TaskFlowContractBinding] = []
        for item in merged_payload:
            bindings.append(
                TaskFlowContractBinding(
                    binding_id=str(item.get("binding_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    flow_contract_id=str(item.get("flow_contract_id") or ""),
                    override_policy=str(item.get("override_policy") or "task_default"),
                    verification_gate_profile=str(item.get("verification_gate_profile") or ""),
                    fallback_policy=str(item.get("fallback_policy") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in bindings]
        if payload.get("flow_contract_bindings") != normalized:
            _write_json(_flow_contract_bindings_path(self.base_dir), {"flow_contract_bindings": normalized})
        return bindings

    def get_flow_contract_binding(self, task_id: str) -> TaskFlowContractBinding | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_flow_contract_bindings() if item.task_id == target), None)

    def upsert_flow_contract_binding(
        self,
        *,
        task_id: str,
        flow_contract_id: str,
        override_policy: str = "task_default",
        verification_gate_profile: str = "",
        fallback_policy: str = "fail_closed",
        metadata: dict[str, Any] | None = None,
    ) -> TaskFlowContractBinding:
        target = str(task_id or "").strip()
        if not target.startswith(("task.", "general.")):
            raise ValueError("task_id must start with task. or general.")
        binding = TaskFlowContractBinding(
            binding_id=f"taskflowbind:{target}",
            task_id=target,
            flow_contract_id=str(flow_contract_id or "").strip(),
            override_policy=str(override_policy or "task_default").strip(),
            verification_gate_profile=str(verification_gate_profile or "").strip(),
            fallback_policy=str(fallback_policy or "fail_closed").strip(),
            metadata=dict(metadata or {}),
        )
        bindings = [item for item in self.list_flow_contract_bindings() if item.task_id != target]
        bindings.append(binding)
        _write_json(
            _flow_contract_bindings_path(self.base_dir),
            {"flow_contract_bindings": [item.to_dict() for item in bindings]},
        )
        return binding

    def list_task_agent_adoption_plans(self) -> list[TaskAgentAdoptionPlan]:
        default_tasks = [
            *[_synthetic_task_from_general_profile(item) for item in self.list_general_task_profiles()],
            *[self._assignment_from_specific_task_record(item) for item in self.list_specific_task_records()],
        ]
        payload = _read_json(
            _adoption_plans_path(self.base_dir),
            {"adoption_plans": [_default_adoption_plan(item).to_dict() for item in default_tasks]},
        )
        default_plans = [_default_adoption_plan(item).to_dict() for item in default_tasks]
        merged_payload = _merge_default_overlay_by_key(
            default_plans,
            [item for item in list(payload.get("adoption_plans") or []) if isinstance(item, dict)],
            key="plan_id",
        )
        plans: list[TaskAgentAdoptionPlan] = []
        for item in merged_payload:
            plans.append(
                TaskAgentAdoptionPlan(
                    plan_id=str(item.get("plan_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    adoption_mode=normalize_task_agent_adoption_mode(str(item.get("adoption_mode") or "adopt_existing")),
                    default_agent_id=str(item.get("default_agent_id") or "agent:0"),
                    allowed_agent_categories=tuple(
                        str(value).strip()
                        for value in list(item.get("allowed_agent_categories") or [])
                        if str(value).strip()
                    ),
                    allow_worker_agent_spawn=bool(item.get("allow_worker_agent_spawn", False)),
                    worker_agent_blueprint_id=str(item.get("worker_agent_blueprint_id") or ""),
                    worker_agent_naming_rule=str(item.get("worker_agent_naming_rule") or ""),
                    notes=str(item.get("notes") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in plans]
        if payload.get("adoption_plans") != normalized:
            _write_json(_adoption_plans_path(self.base_dir), {"adoption_plans": normalized})
        return plans

    def get_task_agent_adoption_plan(self, task_id: str) -> TaskAgentAdoptionPlan | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_task_agent_adoption_plans() if item.task_id == target), None)

    def upsert_task_agent_adoption_plan(
        self,
        *,
        task_id: str,
        adoption_mode: str,
        default_agent_id: str = "agent:0",
        allowed_agent_categories: tuple[str, ...] = (),
        allow_worker_agent_spawn: bool = False,
        worker_agent_blueprint_id: str = "",
        worker_agent_naming_rule: str = "",
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskAgentAdoptionPlan:
        target = str(task_id or "").strip()
        if not target.startswith(("task.", "general.")):
            raise ValueError("task_id must start with task. or general.")
        plan = TaskAgentAdoptionPlan(
            plan_id=f"taskadopt:{target}",
            task_id=target,
            adoption_mode=normalize_task_agent_adoption_mode(adoption_mode),
            default_agent_id=str(default_agent_id or "agent:0").strip() or "agent:0",
            allowed_agent_categories=tuple(
                str(value).strip()
                for value in allowed_agent_categories
                if str(value).strip()
            ),
            allow_worker_agent_spawn=bool(allow_worker_agent_spawn),
            worker_agent_blueprint_id=str(worker_agent_blueprint_id or "").strip(),
            worker_agent_naming_rule=str(worker_agent_naming_rule or "").strip(),
            notes=str(notes or "").strip(),
            metadata=dict(metadata or {}),
        )
        plans = [item for item in self.list_task_agent_adoption_plans() if item.task_id != target]
        plans.append(plan)
        _write_json(
            _adoption_plans_path(self.base_dir),
            {"adoption_plans": [item.to_dict() for item in plans]},
        )
        return plan

    def _collect_deletable_workflow_ids(
        self,
        *,
        task_ids: set[str],
        flow_ids: set[str],
    ) -> set[str]:
        candidates = {
            str(item.default_workflow_id or "").strip()
            for item in self.list_specific_task_records()
            if item.task_id in task_ids
        }
        candidates.update(
            str(item.workflow_id or "").strip()
            for item in self.list_task_assignments()
            if item.task_id in task_ids
        )
        candidates.update(
            str(item.default_workflow_id or "").strip()
            for item in self.list_flows()
            if item.flow_id in flow_ids or str(item.metadata.get("task_id") or "") in task_ids
        )
        candidates = {item for item in candidates if item}
        if not candidates:
            return set()

        remaining_task_ids = {
            item.task_id
            for item in self.list_specific_task_records()
            if item.task_id not in task_ids
        }
        referenced_after_delete: set[str] = set()
        referenced_after_delete.update(
            str(item.default_workflow_id or "").strip()
            for item in self.list_general_task_profiles()
            if str(item.default_workflow_id or "").strip()
        )
        referenced_after_delete.update(
            str(item.default_workflow_id or "").strip()
            for item in self.list_specific_task_records()
            if item.task_id in remaining_task_ids and str(item.default_workflow_id or "").strip()
        )
        referenced_after_delete.update(
            str(item.workflow_id or "").strip()
            for item in self.list_task_assignments()
            if item.task_id in remaining_task_ids and str(item.workflow_id or "").strip()
        )
        referenced_after_delete.update(
            str(item.default_workflow_id or "").strip()
            for item in self.list_flows()
            if item.flow_id not in flow_ids
            and str(item.metadata.get("task_id") or "") not in task_ids
            and str(item.default_workflow_id or "").strip()
        )
        return {
            item
            for item in candidates
            if item not in referenced_after_delete
        }

    def list_task_memory_request_profiles(self) -> list[TaskMemoryRequestProfile]:
        default_profiles = [
            *[_default_memory_request_profile(_synthetic_task_from_general_profile(item)).to_dict() for item in self.list_general_task_profiles()],
            *[_default_memory_request_profile_from_specific_record(item).to_dict() for item in self.list_specific_task_records()],
        ]
        payload = _read_json(
            _memory_request_profiles_path(self.base_dir),
            {"memory_request_profiles": default_profiles},
        )
        merged_payload = _merge_items_by_key(
            default_profiles,
            [item for item in list(payload.get("memory_request_profiles") or []) if isinstance(item, dict)],
            key="profile_id",
        )
        profiles: list[TaskMemoryRequestProfile] = []
        for item in merged_payload:
            profiles.append(
                TaskMemoryRequestProfile(
                    profile_id=str(item.get("profile_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    requested_memory_layers=tuple(
                        str(value).strip()
                        for value in list(item.get("requested_memory_layers") or [])
                        if str(value).strip()
                    ),
                    requested_topics=tuple(
                        str(value).strip()
                        for value in list(item.get("requested_topics") or [])
                        if str(value).strip()
                    ),
                    memory_priority=str(item.get("memory_priority") or "normal"),
                    writeback_policy=str(item.get("writeback_policy") or "task_default"),
                    allow_long_term_memory=bool(item.get("allow_long_term_memory", False)),
                    memory_scope_hint=str(item.get("memory_scope_hint") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in profiles]
        if payload.get("memory_request_profiles") != normalized:
            _write_json(_memory_request_profiles_path(self.base_dir), {"memory_request_profiles": normalized})
        return profiles

    def get_task_memory_request_profile(self, task_id: str) -> TaskMemoryRequestProfile | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_task_memory_request_profiles() if item.task_id == target), None)

    def upsert_task_memory_request_profile(
        self,
        *,
        task_id: str,
        requested_memory_layers: tuple[str, ...] = (),
        requested_topics: tuple[str, ...] = (),
        memory_priority: str = "normal",
        writeback_policy: str = "task_default",
        allow_long_term_memory: bool = False,
        memory_scope_hint: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskMemoryRequestProfile:
        target = str(task_id or "").strip()
        if not target.startswith(("task.", "general.")):
            raise ValueError("task_id must start with task. or general.")
        profile = TaskMemoryRequestProfile(
            profile_id=f"taskmem:{target}",
            task_id=target,
            requested_memory_layers=tuple(
                str(value).strip()
                for value in requested_memory_layers
                if str(value).strip()
            ),
            requested_topics=tuple(
                str(value).strip()
                for value in requested_topics
                if str(value).strip()
            ),
            memory_priority=str(memory_priority or "normal").strip(),
            writeback_policy=str(writeback_policy or "task_default").strip(),
            allow_long_term_memory=bool(allow_long_term_memory),
            memory_scope_hint=str(memory_scope_hint or "").strip(),
            metadata=dict(metadata or {}),
        )
        profiles = [item for item in self.list_task_memory_request_profiles() if item.task_id != target]
        profiles.append(profile)
        _write_json(
            _memory_request_profiles_path(self.base_dir),
            {"memory_request_profiles": [item.to_dict() for item in profiles]},
        )
        return profile

    def list_coordination_tasks(self) -> list[CoordinationTaskDefinition]:
        default_payload = [item.to_dict() for item in default_coordination_tasks()]
        payload = _read_json(
            _coordination_tasks_path(self.base_dir),
            {"coordination_tasks": default_payload},
        )
        merged_payload = _merge_authoritative_defaults_by_key(
            default_payload,
            [item for item in list(payload.get("coordination_tasks") or []) if isinstance(item, dict)],
            key="coordination_task_id",
        )
        tasks: list[CoordinationTaskDefinition] = []
        records_by_task_id = {record.task_id: record for record in self.list_specific_task_records()}
        for item in merged_payload:
            coordinator_agent_id = str(item.get("coordinator_agent_id") or "agent:0")
            metadata = dict(item.get("metadata") or {})
            task_family = str(item.get("task_family") or metadata.get("task_family") or "").strip()
            if not task_family:
                task_family = _family_from_ref(item.get("coordination_task_id")) or _family_from_ref(item.get("topology_template_id"))
            domain_id = str(item.get("domain_id") or metadata.get("domain_id") or (f"domain.{task_family}" if task_family else "")).strip()
            stored_nodes = tuple(
                dict(value)
                for value in list(item.get("graph_nodes") or item.get("nodes") or [])
                if isinstance(value, dict)
            )
            metadata_task_id = str(metadata.get("task_id") or "").strip()
            raw_subtask_refs = [
                *[str(value).strip() for value in list(item.get("subtask_refs") or []) if str(value).strip()],
                *_subtask_refs_from_graph_nodes(stored_nodes),
                *([metadata_task_id] if metadata_task_id.startswith("task.") else []),
            ]
            subtask_refs = tuple(dict.fromkeys(value for value in raw_subtask_refs if value.startswith("task.")))
            if not task_family and subtask_refs:
                task_family = str(getattr(records_by_task_id.get(subtask_refs[0]), "task_family", "") or "").strip()
            if not domain_id and task_family:
                domain_id = f"domain.{task_family}"
            participant_agent_ids = self._resolve_coordination_participants(
                coordinator_agent_id=coordinator_agent_id,
                agent_group_id=str(item.get("agent_group_id") or ""),
                participant_agent_ids=tuple(str(value) for value in list(item.get("participant_agent_ids") or []) if str(value)),
            )
            fallback_nodes, fallback_edges = _default_coordination_graph(
                coordinator_agent_id=coordinator_agent_id,
                participant_agent_ids=participant_agent_ids,
                task_family=task_family,
                subtask_refs=subtask_refs,
            )
            graph_nodes = stored_nodes or fallback_nodes
            graph_edges = tuple(dict(value) for value in list(item.get("graph_edges") or item.get("edges") or []) if isinstance(value, dict)) or fallback_edges
            subtask_refs = tuple(dict.fromkeys([*subtask_refs, *_subtask_refs_from_graph_nodes(graph_nodes)]))
            communication_modes = tuple(
                str(value).strip()
                for value in list(item.get("communication_modes") or [])
                if str(value).strip()
            ) or tuple(
                dict(edge).get("mode", "")
                for edge in graph_edges
                if str(dict(edge).get("mode", "")).strip()
            )
            tasks.append(
                CoordinationTaskDefinition(
                    coordination_task_id=str(item.get("coordination_task_id") or ""),
                    title=str(item.get("title") or ""),
                    coordination_mode=str(item.get("coordination_mode") or "review_merge"),
                    coordinator_agent_id=coordinator_agent_id,
                    task_family=task_family,
                    domain_id=domain_id,
                    agent_group_id=str(item.get("agent_group_id") or ""),
                    participant_agent_ids=participant_agent_ids,
                    topology_template_id=str(item.get("topology_template_id") or ""),
                    shared_context_policy=str(item.get("shared_context_policy") or "explicit_refs_only"),
                    memory_sharing_policy=str(item.get("memory_sharing_policy") or "isolated_by_default"),
                    handoff_policy=str(item.get("handoff_policy") or "filtered_handoff"),
                    conflict_resolution_policy=str(item.get("conflict_resolution_policy") or "coordinator_review"),
                    output_merge_policy=str(item.get("output_merge_policy") or "coordinator_final_merge"),
                    stop_conditions=tuple(str(value) for value in list(item.get("stop_conditions") or []) if str(value)),
                    subtask_refs=subtask_refs,
                    graph_nodes=graph_nodes,
                    graph_edges=graph_edges,
                    communication_modes=tuple(dict.fromkeys(str(value).strip() for value in communication_modes if str(value).strip())),
                    enabled=bool(item.get("enabled", False)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in tasks]
        if payload.get("coordination_tasks") != normalized:
            _write_json(_coordination_tasks_path(self.base_dir), {"coordination_tasks": normalized})
        return tasks

    def get_coordination_task(self, coordination_task_id: str) -> CoordinationTaskDefinition | None:
        target = str(coordination_task_id or "").strip()
        return next((item for item in self.list_coordination_tasks() if item.coordination_task_id == target), None)

    def next_coordination_task_id(self) -> str:
        return _next_prefixed_id(
            [item.coordination_task_id for item in self.list_coordination_tasks()],
            prefix="coord.",
        )

    def get_topology_template(self, template_id: str) -> TopologyTemplate | None:
        target = str(template_id or "").strip()
        return next((item for item in self.list_topology_templates() if item.template_id == target), None)

    def list_topology_templates(self) -> list[TopologyTemplate]:
        default_payload = [item.to_dict() for item in default_topology_templates()]
        payload = _read_json(
            _topology_templates_path(self.base_dir),
            {"topology_templates": default_payload},
        )
        merged_payload = _merge_authoritative_defaults_by_key(
            default_payload,
            [item for item in list(payload.get("topology_templates") or []) if isinstance(item, dict)],
            key="template_id",
        )
        templates: list[TopologyTemplate] = []
        for item in merged_payload:
            templates.append(
                TopologyTemplate(
                    template_id=str(item.get("template_id") or ""),
                    title=str(item.get("title") or ""),
                    nodes=tuple(dict(value) for value in list(item.get("nodes") or []) if isinstance(value, dict)),
                    edges=tuple(dict(value) for value in list(item.get("edges") or []) if isinstance(value, dict)),
                    handoff_rules=tuple(dict(value) for value in list(item.get("handoff_rules") or []) if isinstance(value, dict)),
                    join_policy=str(item.get("join_policy") or "explicit_join"),
                    failure_policy=str(item.get("failure_policy") or "fail_closed"),
                    terminal_policy=str(item.get("terminal_policy") or "coordinator_terminal"),
                    enabled=bool(item.get("enabled", False)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in templates]
        if payload.get("topology_templates") != normalized:
            _write_json(_topology_templates_path(self.base_dir), {"topology_templates": normalized})
        return templates

    def next_topology_template_id(self) -> str:
        return _next_prefixed_id(
            [item.template_id for item in self.list_topology_templates()],
            prefix="topology.",
        )

    def list_task_communication_protocols(self) -> list[TaskCommunicationProtocol]:
        default_payload = [item.to_dict() for item in default_task_communication_protocols()]
        payload = _read_json(
            _communication_protocols_path(self.base_dir),
            {"communication_protocols": default_payload},
        )
        merged_payload = _merge_authoritative_defaults_by_key(
            default_payload,
            [item for item in list(payload.get("communication_protocols") or []) if isinstance(item, dict)],
            key="protocol_id",
        )
        protocols: list[TaskCommunicationProtocol] = []
        for item in merged_payload:
            protocols.append(
                TaskCommunicationProtocol(
                    protocol_id=str(item.get("protocol_id") or ""),
                    title=str(item.get("title") or ""),
                    message_types=tuple(str(value).strip() for value in list(item.get("message_types") or []) if str(value).strip()),
                    payload_contracts=tuple(str(value).strip() for value in list(item.get("payload_contracts") or []) if str(value).strip()),
                    signal_rules=tuple(str(value).strip() for value in list(item.get("signal_rules") or []) if str(value).strip()),
                    handoff_rules=tuple(str(value).strip() for value in list(item.get("handoff_rules") or []) if str(value).strip()),
                    ack_policy=str(item.get("ack_policy") or "explicit_ack"),
                    timeout_policy=str(item.get("timeout_policy") or "fail_closed"),
                    error_signal_policy=str(item.get("error_signal_policy") or "raise_to_coordinator"),
                    enabled=bool(item.get("enabled", False)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in protocols]
        if payload.get("communication_protocols") != normalized:
            _write_json(_communication_protocols_path(self.base_dir), {"communication_protocols": normalized})
        return protocols

    def list_contract_descriptors(self) -> list[TaskContractDescriptor]:
        collected: dict[tuple[str, str], dict[str, Any]] = {}

        def append_contract(
            contract_id: str,
            kind: str,
            *,
            source_ref: str = "",
            usage_ref: str = "",
            title: str = "",
            summary: str = "",
            metadata: dict[str, Any] | None = None,
        ) -> None:
            normalized_id = str(contract_id or "").strip()
            if not normalized_id:
                return
            normalized_kind = str(kind or "").strip() or "unknown"
            key = (normalized_id, normalized_kind)
            current = collected.setdefault(
                key,
                {
                    "contract_id": normalized_id,
                    "title": str(title or CONTRACT_TITLE_MAP.get(normalized_id) or normalized_id).strip(),
                    "contract_kind": normalized_kind,
                    "summary": str(summary or CONTRACT_KIND_LABELS.get(normalized_kind) or "").strip(),
                    "source_refs": [],
                    "usage_refs": [],
                    "metadata": {},
                },
            )
            if source_ref:
                current["source_refs"].append(source_ref)
            if usage_ref:
                current["usage_refs"].append(usage_ref)
            current["metadata"] = {**dict(current.get("metadata") or {}), **dict(metadata or {})}

        for profile in self.list_general_task_profiles():
            append_contract(profile.input_contract_id, "input", source_ref=profile.profile_id, usage_ref=profile.title)
            append_contract(profile.output_contract_id, "output", source_ref=profile.profile_id, usage_ref=profile.title)

        for flow in self.list_flows():
            append_contract(flow.input_contract_id, "input", source_ref=flow.flow_id, usage_ref=flow.title)
            append_contract(flow.output_contract_id, "output", source_ref=flow.flow_id, usage_ref=flow.title)
            append_contract(
                flow.flow_id,
                "flow",
                source_ref=flow.flow_id,
                usage_ref=flow.title,
                title=flow.title,
                summary=f"{CONTRACT_TITLE_MAP.get(flow.input_contract_id, flow.input_contract_id)} -> {CONTRACT_TITLE_MAP.get(flow.output_contract_id, flow.output_contract_id)}",
                metadata={
                    "task_family": flow.task_family,
                    "task_mode": flow.task_mode,
                    "default_workflow_id": flow.default_workflow_id,
                },
            )

        for record in self.list_specific_task_records():
            append_contract(record.input_contract_id, "input", source_ref=record.task_id, usage_ref=record.task_title)
            append_contract(record.output_contract_id, "output", source_ref=record.task_id, usage_ref=record.task_title)
            append_contract(record.default_flow_contract_id, "flow", source_ref=record.task_id, usage_ref=record.task_title)

        for protocol in self.list_task_communication_protocols():
            for contract_id in protocol.payload_contracts:
                append_contract(contract_id, "payload", source_ref=protocol.protocol_id, usage_ref=protocol.title)

        descriptors = []
        for item in collected.values():
            descriptors.append(
                TaskContractDescriptor(
                    contract_id=str(item["contract_id"]),
                    title=str(item["title"]),
                    contract_kind=str(item["contract_kind"]),
                    summary=str(item.get("summary") or ""),
                    source_refs=tuple(dict.fromkeys(str(ref) for ref in list(item.get("source_refs") or []) if str(ref))),
                    usage_refs=tuple(dict.fromkeys(str(ref) for ref in list(item.get("usage_refs") or []) if str(ref))),
                    editable=False,
                    status="derived",
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return sorted(descriptors, key=lambda item: (item.contract_kind, item.title, item.contract_id))

    def get_task_communication_protocol(self, protocol_id: str) -> TaskCommunicationProtocol | None:
        target = str(protocol_id or "").strip()
        return next((item for item in self.list_task_communication_protocols() if item.protocol_id == target), None)

    def upsert_task_communication_protocol(
        self,
        *,
        protocol_id: str,
        title: str,
        message_types: tuple[str, ...] = (),
        payload_contracts: tuple[str, ...] = (),
        signal_rules: tuple[str, ...] = (),
        handoff_rules: tuple[str, ...] = (),
        ack_policy: str = "explicit_ack",
        timeout_policy: str = "fail_closed",
        error_signal_policy: str = "raise_to_coordinator",
        enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> TaskCommunicationProtocol:
        target = str(protocol_id or "").strip()
        if not target.startswith("protocol."):
            raise ValueError("protocol_id must start with protocol.")
        protocol = TaskCommunicationProtocol(
            protocol_id=target,
            title=str(title or target).strip(),
            message_types=tuple(
                str(value).strip()
                for value in message_types
                if str(value).strip()
            ),
            payload_contracts=tuple(
                str(value).strip()
                for value in payload_contracts
                if str(value).strip()
            ),
            signal_rules=tuple(
                str(value).strip()
                for value in signal_rules
                if str(value).strip()
            ),
            handoff_rules=tuple(
                str(value).strip()
                for value in handoff_rules
                if str(value).strip()
            ),
            ack_policy=str(ack_policy or "explicit_ack").strip(),
            timeout_policy=str(timeout_policy or "fail_closed").strip(),
            error_signal_policy=str(error_signal_policy or "raise_to_coordinator").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        protocols = [item for item in self.list_task_communication_protocols() if item.protocol_id != target]
        protocols.append(protocol)
        _write_json(
            _communication_protocols_path(self.base_dir),
            {"communication_protocols": [item.to_dict() for item in protocols]},
        )
        return protocol

    def upsert_coordination_task(
        self,
        *,
        coordination_task_id: str,
        title: str,
        coordination_mode: str,
        coordinator_agent_id: str,
        task_family: str = "",
        domain_id: str = "",
        agent_group_id: str = "",
        participant_agent_ids: tuple[str, ...] = (),
        topology_template_id: str = "",
        shared_context_policy: str = "explicit_refs_only",
        memory_sharing_policy: str = "isolated_by_default",
        handoff_policy: str = "filtered_handoff",
        conflict_resolution_policy: str = "coordinator_review",
        output_merge_policy: str = "coordinator_final_merge",
        stop_conditions: tuple[str, ...] = (),
        subtask_refs: tuple[str, ...] = (),
        graph_nodes: tuple[dict[str, Any], ...] = (),
        graph_edges: tuple[dict[str, Any], ...] = (),
        communication_modes: tuple[str, ...] = (),
        enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> CoordinationTaskDefinition:
        target = str(coordination_task_id or "").strip()
        if not target.startswith("coord."):
            raise ValueError("coordination_task_id must start with coord.")
        normalized_family = str(task_family or "").strip() or _family_from_ref(target)
        normalized_domain_id = str(domain_id or "").strip() or (f"domain.{normalized_family}" if normalized_family else "")
        normalized_subtask_refs = tuple(
            dict.fromkeys(str(item).strip() for item in subtask_refs if str(item).strip().startswith("task."))
        )
        normalized_graph_nodes = tuple(dict(item) for item in graph_nodes if isinstance(item, dict))
        if normalized_graph_nodes:
            normalized_subtask_refs = tuple(
                dict.fromkeys([*normalized_subtask_refs, *_subtask_refs_from_graph_nodes(normalized_graph_nodes)])
            )
        else:
            normalized_graph_nodes, _ = _default_coordination_graph(
                coordinator_agent_id=str(coordinator_agent_id or "agent:0").strip() or "agent:0",
                participant_agent_ids=tuple(str(item).strip() for item in participant_agent_ids if str(item).strip()),
                task_family=normalized_family,
                subtask_refs=normalized_subtask_refs,
            )
        if not normalized_family and normalized_subtask_refs:
            record = self.get_specific_task_record(normalized_subtask_refs[0])
            normalized_family = str(getattr(record, "task_family", "") or "").strip()
            if not normalized_domain_id and normalized_family:
                normalized_domain_id = f"domain.{normalized_family}"
        task = CoordinationTaskDefinition(
            coordination_task_id=target,
            title=str(title or target).strip(),
            coordination_mode=str(coordination_mode or "review_merge").strip(),
            coordinator_agent_id=str(coordinator_agent_id or "agent:0").strip() or "agent:0",
            task_family=normalized_family,
            domain_id=normalized_domain_id,
            agent_group_id=str(agent_group_id or "").strip(),
            participant_agent_ids=self._resolve_coordination_participants(
                coordinator_agent_id=str(coordinator_agent_id or "agent:0").strip() or "agent:0",
                agent_group_id=str(agent_group_id or "").strip(),
                participant_agent_ids=tuple(str(item).strip() for item in participant_agent_ids if str(item).strip()),
            ),
            topology_template_id=str(topology_template_id or "").strip(),
            shared_context_policy=str(shared_context_policy or "explicit_refs_only").strip(),
            memory_sharing_policy=str(memory_sharing_policy or "isolated_by_default").strip(),
            handoff_policy=str(handoff_policy or "filtered_handoff").strip(),
            conflict_resolution_policy=str(conflict_resolution_policy or "coordinator_review").strip(),
            output_merge_policy=str(output_merge_policy or "coordinator_final_merge").strip(),
            stop_conditions=tuple(str(item).strip() for item in stop_conditions if str(item).strip()),
            subtask_refs=normalized_subtask_refs,
            graph_nodes=normalized_graph_nodes,
            graph_edges=tuple(dict(item) for item in graph_edges if isinstance(item, dict)),
            communication_modes=tuple(str(item).strip() for item in communication_modes if str(item).strip()),
            enabled=bool(enabled),
            metadata={
                **dict(metadata or {}),
                "task_family": normalized_family,
                "domain_id": normalized_domain_id,
            },
        )
        tasks = [item for item in self.list_coordination_tasks() if item.coordination_task_id != target]
        tasks.append(task)
        _write_json(_coordination_tasks_path(self.base_dir), {"coordination_tasks": [item.to_dict() for item in tasks]})
        return task

    def _resolve_coordination_participants(
        self,
        *,
        coordinator_agent_id: str,
        agent_group_id: str,
        participant_agent_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        explicit = tuple(str(item).strip() for item in participant_agent_ids if str(item).strip())
        if explicit:
            return explicit
        from orchestration.agent_group_registry import AgentGroupRegistry

        group = AgentGroupRegistry(self.base_dir).get_group(agent_group_id)
        if group is None:
            return ()
        coordinator = str(coordinator_agent_id or group.coordinator_agent_id or "").strip()
        return tuple(
            item
            for item in group.member_agent_ids
            if item and item != coordinator
        )

    def upsert_topology_template(
        self,
        *,
        template_id: str,
        title: str,
        nodes: tuple[dict[str, Any], ...] = (),
        edges: tuple[dict[str, Any], ...] = (),
        handoff_rules: tuple[dict[str, Any], ...] = (),
        join_policy: str = "explicit_join",
        failure_policy: str = "fail_closed",
        terminal_policy: str = "coordinator_terminal",
        enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> TopologyTemplate:
        target = str(template_id or "").strip()
        if not target.startswith("topology."):
            raise ValueError("template_id must start with topology.")
        template = TopologyTemplate(
            template_id=target,
            title=str(title or target).strip(),
            nodes=tuple(dict(item) for item in nodes if isinstance(item, dict)),
            edges=tuple(dict(item) for item in edges if isinstance(item, dict)),
            handoff_rules=tuple(dict(item) for item in handoff_rules if isinstance(item, dict)),
            join_policy=str(join_policy or "explicit_join").strip(),
            failure_policy=str(failure_policy or "fail_closed").strip(),
            terminal_policy=str(terminal_policy or "coordinator_terminal").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        templates = [item for item in self.list_topology_templates() if item.template_id != target]
        templates.append(template)
        _write_json(_topology_templates_path(self.base_dir), {"topology_templates": [item.to_dict() for item in templates]})
        return template

    def build_binding_for_flow(self, flow: TaskFlowDefinition) -> TaskAgentBinding:
        agent = self.agent_registry.get_agent(flow.default_agent_id)
        profile = self.agent_runtime_registry.get_profile(flow.default_agent_id)
        diagnostics: dict[str, Any] = {}
        failures: list[str] = []
        if agent is None:
            failures.append("agent_missing")
        elif agent.lifecycle_state not in {"enabled", "system_builtin"}:
            failures.append("agent_not_enabled")
        if profile is None:
            failures.append("runtime_profile_missing")
        else:
            _validate_contains(failures, diagnostics, "task_mode", flow.task_mode, profile.allowed_task_modes)
            _validate_contains(failures, diagnostics, "runtime_lane", flow.default_runtime_lane, profile.allowed_runtime_lanes)
            _validate_contains(failures, diagnostics, "memory_scope", flow.default_memory_scope, profile.allowed_memory_scopes)
            _validate_contains(failures, diagnostics, "output_contract", flow.output_contract_id, profile.output_contracts)
        self._validate_workflow_ref(failures, diagnostics, flow.default_workflow_id)
        return TaskAgentBinding(
            binding_id=f"binding:{flow.flow_id}:{flow.default_agent_id}",
            task_id=f"task-template:{flow.task_mode}",
            flow_id=flow.flow_id,
            agent_id=flow.default_agent_id,
            agent_profile_id=profile.agent_profile_id if profile is not None else "",
            runtime_lane=flow.default_runtime_lane,
            workflow_id=flow.default_workflow_id,
            memory_scope=flow.default_memory_scope,
            output_contract_id=flow.output_contract_id,
            resource_policy_ref=f"resource-policy:{flow.flow_id}:candidate",
            validation_state="valid" if not failures else "invalid",
            diagnostics={**diagnostics, "failures": failures},
        )

    def build_link_permission_matrix(self) -> dict[str, Any]:
        bindings = self.list_bindings()
        return {
            "authority": "task_system.link_permission_matrix",
            "rows": [
                {
                    "agent_id": item.agent_id,
                    "agent_profile_id": item.agent_profile_id,
                    "task_mode": next((flow.task_mode for flow in self.list_flows() if flow.flow_id == item.flow_id), ""),
                    "runtime_lane": item.runtime_lane,
                    "workflow": item.workflow_id,
                    "memory_scope": item.memory_scope,
                    "output_contract": item.output_contract_id,
                    "validation_state": item.validation_state,
                    "blocked_reasons": list(item.diagnostics.get("failures") or []),
                }
                for item in bindings
            ],
        }

    def list_agent_task_connection_profiles(
        self,
        *,
        owner_system: str = "",
        task_family: str = "",
    ) -> list[AgentTaskConnectionProfile]:
        flows = self.list_flows()
        bindings = self.list_bindings()
        topologies = self.list_topology_templates()
        profiles: list[AgentTaskConnectionProfile] = []
        for agent in self.agent_registry.list_agents():
            agent_bindings = [item for item in bindings if item.agent_id == agent.agent_id]
            agent_flows = [flow for flow in flows if any(binding.flow_id == flow.flow_id for binding in agent_bindings)]
            if owner_system and agent.owner_system != owner_system:
                continue
            if task_family and not any(flow.task_family == task_family for flow in agent_flows):
                continue
            capability = self.agent_runtime_registry.get_profile(agent.agent_id)
            topology_refs = tuple(
                template.template_id
                for template in topologies
                if any(dict(node).get("agent_id") == agent.agent_id for node in template.nodes)
            )
            blocked_reasons = tuple(
                dict.fromkeys(
                    reason
                    for binding in agent_bindings
                    for reason in list(binding.diagnostics.get("failures") or [])
                    if reason
                )
            )
            profile_validation_state = "valid" if agent_bindings and not blocked_reasons else "invalid" if blocked_reasons else "unbound"
            default_flow = agent_flows[0] if agent_flows else None
            default_binding = agent_bindings[0] if agent_bindings else None
            profiles.append(
                AgentTaskConnectionProfile(
                    profile_id=f"agent-task-connection:{agent.agent_id}",
                    agent_id=agent.agent_id,
                    agent_profile_id=capability.agent_profile_id if capability is not None else "",
                    owner_system=agent.owner_system,
                    profile_type=agent.profile_type,
                    lifecycle_state=agent.lifecycle_state,
                    task_family_refs=tuple(dict.fromkeys(flow.task_family for flow in agent_flows)),
                    available_task_modes=tuple(dict.fromkeys(flow.task_mode for flow in agent_flows)),
                    flow_refs=tuple(flow.flow_id for flow in agent_flows),
                    binding_refs=tuple(binding.binding_id for binding in agent_bindings),
                    workflow_refs=tuple(
                        dict.fromkeys(binding.workflow_id for binding in agent_bindings if binding.workflow_id)
                    ),
                    topology_refs=topology_refs,
                    default_flow_ref=default_flow.flow_id if default_flow is not None else "",
                    default_workflow_ref=default_binding.workflow_id if default_binding is not None else "",
                    default_runtime_lane_hint=default_binding.runtime_lane if default_binding is not None else "",
                    validation_state=profile_validation_state,
                    blocked_reasons=blocked_reasons,
                    diagnostics={
                        "agent": agent.to_dict(),
                        "runtime_profile_present": capability is not None,
                        "flow_count": len(agent_flows),
                        "binding_count": len(agent_bindings),
                        "topology_count": len(topology_refs),
                    },
                )
            )
        return profiles

    def build_agent_task_connection_overview(
        self,
        *,
        owner_system: str = "",
        task_family: str = "",
    ) -> dict[str, Any]:
        profiles = self.list_agent_task_connection_profiles(owner_system=owner_system, task_family=task_family)
        task_families = {family for profile in profiles for family in profile.task_family_refs}
        topology_refs = {topology for profile in profiles for topology in profile.topology_refs}
        return {
            "authority": "task_system.agent_task_connections",
            "profiles": [item.to_dict() for item in profiles],
            "summary": {
                "profile_count": len(profiles),
                "invalid_profile_count": sum(1 for item in profiles if item.validation_state == "invalid"),
                "task_family_count": len(task_families),
                "topology_count": len(topology_refs),
            },
            "diagnostics": {
                "owner_system_filter": owner_system,
                "task_family_filter": task_family,
            },
        }

    def list_agent_task_carrying_profiles(self) -> list[AgentTaskCarryingProfile]:
        general_profiles = self.list_general_task_profiles()
        assignments = self.list_task_assignments()
        bindings = self.list_bindings()
        binding_by_flow = {item.flow_id: item for item in bindings}
        profiles: list[AgentTaskCarryingProfile] = []
        for agent in self.agent_registry.list_agents():
            carried_general = [
                item
                for item in general_profiles
                if item.default_agent_id == agent.agent_id
            ]
            carried_specific = [
                item
                for item in assignments
                if item.default_agent_id == agent.agent_id or agent.agent_id in set(item.participant_agent_ids)
            ]
            workflow_refs = tuple(
                dict.fromkeys(
                    [
                        *(item.default_workflow_id for item in carried_general if item.default_workflow_id),
                        *(item.workflow_id for item in carried_specific if item.workflow_id),
                    ]
                )
            )
            blocked_reasons = list(self._agent_assignment_failures(agent.agent_id, carried_general, carried_specific))
            for assignment in carried_specific:
                binding = binding_by_flow.get(assignment.flow_id)
                if binding is not None and binding.validation_state != "valid":
                    blocked_reasons.extend(str(item) for item in list(binding.diagnostics.get("failures") or []) if item)
            validation_state = "valid" if (carried_general or carried_specific) and not blocked_reasons else "invalid" if blocked_reasons else "unbound"
            profiles.append(
                AgentTaskCarryingProfile(
                    agent_id=agent.agent_id,
                    display_name=agent.display_name,
                    profile_type=agent.profile_type,
                    owner_system=agent.owner_system,
                    lifecycle_state=agent.lifecycle_state,
                    carried_general_task_refs=tuple(item.profile_id for item in carried_general),
                    carried_specific_task_refs=tuple(item.task_id for item in carried_specific),
                    workflow_refs=workflow_refs,
                    validation_state=validation_state,
                    blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
                    diagnostics={
                        "general_task_count": len(carried_general),
                        "specific_task_count": len(carried_specific),
                        "workflow_count": len(workflow_refs),
                    },
                )
            )
        return profiles

    def build_agent_carrying_overview(self) -> dict[str, Any]:
        profiles = self.list_agent_task_carrying_profiles()
        return {
            "authority": "task_system.agent_carrying_profiles",
            "profiles": [item.to_dict() for item in profiles],
            "summary": {
                "profile_count": len(profiles),
                "invalid_profile_count": sum(1 for item in profiles if item.validation_state == "invalid"),
                "unbound_profile_count": sum(1 for item in profiles if item.validation_state == "unbound"),
            },
        }

    def build_connection_diagnostics(self) -> dict[str, Any]:
        agents = {item.agent_id for item in self.agent_registry.list_agents()}
        workflows = {item.workflow_id for item in self.workflow_registry.list_workflows()}
        general_profiles = self.list_general_task_profiles()
        assignments = self.list_task_assignments()
        issues: list[dict[str, Any]] = []
        for profile in general_profiles:
            self._append_ref_issue(issues, profile.profile_id, "general_task", "default_agent_id", profile.default_agent_id, agents)
            if profile.default_workflow_id:
                self._append_ref_issue(issues, profile.profile_id, "general_task", "workflow_id", profile.default_workflow_id, workflows)
            else:
                issues.append(_diagnostic_issue(profile.profile_id, "general_task", "workflow_missing", "default_workflow_id"))
        for assignment in assignments:
            self._append_ref_issue(issues, assignment.task_id, "specific_task", "default_agent_id", assignment.default_agent_id, agents)
            for participant_id in assignment.participant_agent_ids:
                self._append_ref_issue(issues, assignment.task_id, "specific_task", "participant_agent_id", participant_id, agents)
            if assignment.workflow_id:
                self._append_ref_issue(issues, assignment.task_id, "specific_task", "workflow_id", assignment.workflow_id, workflows)
            else:
                issues.append(_diagnostic_issue(assignment.task_id, "specific_task", "workflow_missing", "workflow_id"))
            if not assignment.input_contract_id:
                issues.append(_diagnostic_issue(assignment.task_id, "specific_task", "input_contract_missing", "input_contract_id"))
            if not assignment.output_contract_id:
                issues.append(_diagnostic_issue(assignment.task_id, "specific_task", "output_contract_missing", "output_contract_id"))
        for profile in self.list_agent_task_carrying_profiles():
            if profile.validation_state == "unbound":
                issues.append(_diagnostic_issue(profile.agent_id, "agent", "agent_without_task", "carried_tasks"))
            for reason in profile.blocked_reasons:
                issues.append(_diagnostic_issue(profile.agent_id, "agent", reason, "task_connection"))
        return {
            "authority": "task_system.connection_diagnostics",
            "issues": issues,
            "summary": {
                "issue_count": len(issues),
                "blocking_issue_count": sum(1 for item in issues if item.get("severity") == "blocking"),
            },
        }

    def _agent_assignment_failures(
        self,
        agent_id: str,
        general_profiles: list[GeneralTaskProfile],
        assignments: list[TaskAssignment],
    ) -> tuple[str, ...]:
        failures: list[str] = []
        if any(item.default_workflow_id and self.workflow_registry.get_workflow(item.default_workflow_id) is None for item in general_profiles):
            failures.append("general_workflow_missing")
        if any(item.workflow_id and self.workflow_registry.get_workflow(item.workflow_id) is None for item in assignments):
            failures.append("specific_workflow_missing")
        if agent_id == "agent:0" and not general_profiles:
            failures.append("main_agent_without_general_task")
        return tuple(dict.fromkeys(failures))

    def _append_ref_issue(
        self,
        issues: list[dict[str, Any]],
        object_id: str,
        object_type: str,
        field: str,
        value: str,
        allowed: set[str],
    ) -> None:
        if not value or value not in allowed:
            issues.append(_diagnostic_issue(object_id, object_type, f"{field}_missing_ref", field, value=value))

    def _validate_workflow_ref(
        self,
        failures: list[str],
        diagnostics: dict[str, Any],
        workflow_id: str,
    ) -> None:
        value = str(workflow_id or "").strip()
        if not value:
            failures.append("workflow_missing")
            diagnostics["workflow"] = {"value": value, "status": "missing"}
            return
        if self.workflow_registry.get_workflow(value) is not None:
            return
        failures.append("workflow_missing")
        diagnostics["workflow"] = {"value": value, "status": "missing"}

    def build_overview(self) -> dict[str, Any]:
        agent_catalog = self.agent_registry.build_catalog()
        flows = self.list_flows()
        bindings = self.list_bindings()
        general_profiles = self.list_general_task_profiles()
        task_assignments = self.list_task_assignments()
        coordination_tasks = self.list_coordination_tasks()
        task_domains = self.list_task_domains()
        templates = self.template_registry.list_templates()
        template_validation_matrix = self.template_registry.build_validation_matrix()
        invalid_bindings = [item for item in bindings if item.validation_state != "valid"]
        return {
            "authority": "task_system.overview",
            "summary": {
                "agent_count": agent_catalog["summary"]["agent_count"],
                "main_agent_count": agent_catalog["summary"]["main_agent_count"],
                "system_management_agent_count": agent_catalog["summary"]["system_management_agent_count"],
                "worker_sub_agent_count": agent_catalog["summary"]["worker_sub_agent_count"],
                "general_task_count": len(general_profiles),
                "specific_task_count": len(task_assignments),
                "task_flow_count": len(flows),
                "enabled_task_flow_count": sum(1 for item in flows if item.enabled),
                "task_template_count": len(templates),
                "enabled_task_template_count": sum(1 for item in templates if item.enabled),
                "task_domain_count": len(task_domains),
                "coordination_task_count": len(coordination_tasks),
                "projection_binding_count": len(self.list_projection_bindings()),
                "flow_contract_binding_count": len(self.list_flow_contract_bindings()),
                "adoption_plan_count": len(self.list_task_agent_adoption_plans()),
                "memory_request_profile_count": len(self.list_task_memory_request_profiles()),
                "communication_protocol_count": len(self.list_task_communication_protocols()),
                "invalid_binding_count": len(invalid_bindings),
                "invalid_template_count": sum(
                    1
                    for item in list(template_validation_matrix.get("rows") or [])
                    if str(item.get("validation_state") or "") != "valid"
                ),
            },
            "agents": agent_catalog["agents"],
            "task_domains": [item.to_dict() for item in task_domains],
            "general_task_profiles": [item.to_dict() for item in general_profiles],
            "specific_task_records": [item.to_dict() for item in self.list_specific_task_records()],
            "task_assignments": [item.to_dict() for item in task_assignments],
            "flows": [item.to_dict() for item in flows],
            "bindings": [item.to_dict() for item in bindings],
            "projection_bindings": [item.to_dict() for item in self.list_projection_bindings()],
            "flow_contract_bindings": [item.to_dict() for item in self.list_flow_contract_bindings()],
            "agent_adoption_plans": [item.to_dict() for item in self.list_task_agent_adoption_plans()],
            "memory_request_profiles": [item.to_dict() for item in self.list_task_memory_request_profiles()],
            "templates": [item.to_dict() for item in templates],
            "template_validation_matrix": template_validation_matrix,
            "coordination_tasks": [item.to_dict() for item in coordination_tasks],
            "topology_templates": [item.to_dict() for item in self.list_topology_templates()],
            "communication_protocols": [item.to_dict() for item in self.list_task_communication_protocols()],
            "link_permission_matrix": self.build_link_permission_matrix(),
            "agent_task_connections": self.build_agent_task_connection_overview(),
            "agent_carrying_profiles": self.build_agent_carrying_overview(),
            "connection_diagnostics": self.build_connection_diagnostics(),
        }


def _validate_contains(
    failures: list[str],
    diagnostics: dict[str, Any],
    field: str,
    value: str,
    allowed: tuple[str, ...],
) -> None:
    if value not in allowed:
        failures.append(f"{field}_not_allowed")
        diagnostics[field] = {"value": value, "allowed": list(allowed)}


def _assignment_from_dict(payload: dict[str, Any]) -> TaskAssignment:
    return TaskAssignment(
        task_id=str(payload.get("task_id") or ""),
        task_title=str(payload.get("task_title") or ""),
        task_kind=str(payload.get("task_kind") or "specific_task"),
        task_family=str(payload.get("task_family") or ""),
        task_mode=str(payload.get("task_mode") or ""),
        flow_id=str(payload.get("flow_id") or ""),
        default_agent_id=str(payload.get("default_agent_id") or "agent:0"),
        participant_agent_ids=tuple(str(item) for item in list(payload.get("participant_agent_ids") or []) if str(item)),
        workflow_id=str(payload.get("workflow_id") or ""),
        workflow_file_ref=str(payload.get("workflow_file_ref") or ""),
        projection_id=str(payload.get("projection_id") or payload.get("projection_template_id") or ""),
        input_contract_id=str(payload.get("input_contract_id") or ""),
        output_contract_id=str(payload.get("output_contract_id") or ""),
        safety_policy=dict(payload.get("safety_policy") or {}),
        task_structure=dict(payload.get("task_structure") or {}),
        enabled=bool(payload.get("enabled", True)),
        metadata=dict(payload.get("metadata") or {}),
    )


def _diagnostic_issue(
    object_id: str,
    object_type: str,
    reason: str,
    field: str,
    *,
    value: str = "",
) -> dict[str, Any]:
    return {
        "object_id": object_id,
        "object_type": object_type,
        "reason": reason,
        "field": field,
        "value": value,
        "severity": "blocking" if reason != "agent_without_task" else "warning",
    }
