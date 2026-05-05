from __future__ import annotations

from pathlib import Path
from typing import Any

from capability_system import build_default_operation_registry
from orchestration.agent_registry import AgentRegistry
from orchestration.agent_runtime_registry import AgentRuntimeRegistry

from .match_contracts import TaskIntentContract, TemplateMatchResult
from .definitions import TaskDefinition
from .step_models import TaskStepBlueprint
from .template_models import TaskTemplate, TaskValidationRule


_LONGFORM_WRITING_SAFETY_POLICY = {
    "safety_class": "S1_bounded_artifact_write",
    "write_mode": "bounded_create",
    "default_write_roots": ["docs/系统规划/任务系统实测记录/artifacts"],
    "forbidden_paths": [".env", ".env.local", "backend", "storage", "node_modules", ".git"],
}

_LONGFORM_RUNTIME_LIMITS = {
    "authority": "task_system.runtime_limits",
    "limit_mode": "unlimited",
    "max_turns": 24,
    "max_model_calls": 24,
    "max_runtime_seconds": None,
    "max_events": 1200,
}

_LONGFORM_ARTIFACT_RULE = {
    "requires_write_file": True,
    "required_tool": "write_file",
    "artifact_contract": "target_path_must_exist",
}


def default_task_templates() -> tuple[TaskTemplate, ...]:
    return (
        TaskTemplate(
            template_id="template.chat.general_response",
            title="通用回答",
            description="处理不需要外部执行器的普通对话或结论性回答。",
            task_family="chat",
            task_mode="general_response",
            input_schema={"message": "string"},
            output_schema={"final_answer": "string"},
            required_operations=("op.model_response",),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.answer",
                    title="生成最终回答",
                    step_kind="finalize",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="AssistantFinalAnswer",
                ),
            ),
            validation_rules=(
                TaskValidationRule(
                    rule_id="rule.concise_answer",
                    title="回答收口",
                    validation_kind="final_answer_required",
                    severity="error",
                ),
            ),
            safety_policy={
                "safety_class": "S0_readonly",
                "write_mode": "none",
                "verification_mode": "final_answer_only",
            },
            ui_manifest={"icon": "message-square", "category": "chat"},
        ),
        TaskTemplate(
            template_id="template.bundle.multi_capability",
            title="复合任务编排",
            description="把一个用户请求拆成多个能力域子任务，并聚合结果账本。",
            task_family="orchestration",
            task_mode="bundle_execution",
            input_schema={"bundle_items": "BundleItem[]"},
            output_schema={"final_answer": "string", "bundle_result_refs": "TaskSummary[]"},
            required_operations=("op.model_response",),
            optional_operations=(
                "op.pdf_analysis",
                "op.structured_data_analysis",
                "op.get_weather",
                "op.get_gold_price",
                "op.search_knowledge",
            ),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.plan_bundle",
                    title="装配子任务",
                    step_kind="understand",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="BundlePlan",
                ),
                TaskStepBlueprint(
                    step_id="step.aggregate_results",
                    title="聚合结果账本",
                    step_kind="finalize",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="BundleAnswer",
                ),
            ),
            validation_rules=(
                TaskValidationRule(
                    rule_id="rule.bundle_ref_required",
                    title="复合结果可回指",
                    validation_kind="bundle_result_refs_required",
                    severity="error",
                ),
            ),
            safety_policy={
                "safety_class": "S0_readonly",
                "write_mode": "none",
                "verification_mode": "result_refs_required",
            },
            ui_manifest={"icon": "layers-3", "category": "orchestration"},
        ),
        TaskTemplate(
            template_id="template.search.information_search",
            title="联网信息检索",
            description="面向外部网页搜索与证据归纳的检索模板。",
            task_family="search",
            task_mode="information_search",
            input_schema={"query": "string"},
            output_schema={"final_answer": "string", "sources": "string[]"},
            required_operations=("op.model_response", "op.web_search", "op.fetch_url"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.search_web",
                    title="搜索外部资料",
                    step_kind="analyze",
                    executor_type="tool",
                    required_operations=("op.web_search", "op.fetch_url"),
                    output_contract_id="SearchEvidence",
                ),
                TaskStepBlueprint(
                    step_id="step.summarize_search",
                    title="整理搜索证据",
                    step_kind="finalize",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="GroundedAnswer",
                ),
            ),
            safety_policy={
                "safety_class": "S0_readonly",
                "write_mode": "none",
                "verification_mode": "sources_required",
            },
            ui_manifest={"icon": "globe", "category": "search"},
        ),
        TaskTemplate(
            template_id="template.capability.direct_tool",
            title="直接能力执行",
            description="针对已明确的实时查询或工具型能力执行请求。",
            task_family="execution",
            task_mode="capability_execution",
            input_schema={"tool_input": "object"},
            output_schema={"final_answer": "string"},
            required_operations=("op.model_response",),
            optional_operations=("op.get_weather", "op.get_gold_price", "op.web_search", "op.fetch_url"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.execute_capability",
                    title="执行能力",
                    step_kind="execute",
                    executor_type="tool",
                    optional_operations=("op.get_weather", "op.get_gold_price", "op.web_search", "op.fetch_url"),
                    output_contract_id="CapabilityResult",
                ),
            ),
            safety_policy={
                "safety_class": "S0_readonly",
                "write_mode": "none",
                "verification_mode": "tool_result_only",
            },
            ui_manifest={"icon": "zap", "category": "execution"},
        ),
        TaskTemplate(
            template_id="template.rag.knowledge_answer",
            title="知识库问答",
            description="基于知识库检索与证据归纳的回答模板。",
            task_family="search",
            task_mode="knowledge_answer",
            input_schema={"query": "string"},
            output_schema={"final_answer": "string", "citations": "string[]"},
            required_operations=("op.model_response", "op.search_knowledge"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.retrieve",
                    title="检索知识",
                    step_kind="analyze",
                    executor_type="tool",
                    required_operations=("op.search_knowledge",),
                    output_contract_id="KnowledgeEvidence",
                ),
                TaskStepBlueprint(
                    step_id="step.answer",
                    title="基于证据回答",
                    step_kind="finalize",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="GroundedAnswer",
                ),
            ),
            safety_policy={
                "safety_class": "S0_readonly",
                "write_mode": "none",
                "verification_mode": "citations_required",
            },
            ui_manifest={"icon": "book-open", "category": "knowledge"},
        ),
        TaskTemplate(
            template_id="template.pdf.document_analysis",
            title="PDF 文档分析",
            description="分析 PDF 文档、页码或章节，并形成可 follow-up 的结果。",
            task_family="document",
            task_mode="pdf_analysis",
            input_schema={"path": "string", "query": "string"},
            output_schema={"final_answer": "string", "task_summary_refs": "TaskSummary[]"},
            required_operations=("op.model_response", "op.pdf_analysis"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.inspect_pdf",
                    title="分析 PDF",
                    step_kind="analyze",
                    executor_type="tool",
                    required_operations=("op.pdf_analysis",),
                    input_refs=("input.path", "input.query"),
                    output_contract_id="PdfAnalysisResult",
                ),
                TaskStepBlueprint(
                    step_id="step.finalize_pdf",
                    title="整理 PDF 结果",
                    step_kind="finalize",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="GroundedAnswer",
                ),
            ),
            safety_policy={
                "safety_class": "S0_readonly",
                "write_mode": "none",
                "verification_mode": "task_summary_refs_required",
            },
            ui_manifest={"icon": "file-text", "category": "document"},
        ),
        TaskTemplate(
            template_id="template.data.structured_analysis",
            title="结构化数据分析",
            description="分析表格或结构化数据集，并形成可 follow-up 的结果。",
            task_family="data",
            task_mode="structured_analysis",
            input_schema={"path": "string", "query": "string"},
            output_schema={"final_answer": "string", "task_summary_refs": "TaskSummary[]"},
            required_operations=("op.model_response", "op.structured_data_analysis"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.inspect_dataset",
                    title="分析数据集",
                    step_kind="analyze",
                    executor_type="tool",
                    required_operations=("op.structured_data_analysis",),
                    input_refs=("input.path", "input.query"),
                    output_contract_id="StructuredAnalysisResult",
                ),
                TaskStepBlueprint(
                    step_id="step.finalize_dataset",
                    title="整理数据结果",
                    step_kind="finalize",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="GroundedAnswer",
                ),
            ),
            safety_policy={
                "safety_class": "S0_readonly",
                "write_mode": "none",
                "verification_mode": "task_summary_refs_required",
            },
            ui_manifest={"icon": "table", "category": "data"},
        ),
        TaskTemplate(
            template_id="template.dev.workspace_patch",
            title="工作区补丁任务",
            description="读取、修改并验证工作区文件的通用开发任务模板。",
            task_family="development",
            task_mode="workspace_patch",
            input_schema={"workspace_path": "string", "goal": "string"},
            output_schema={"final_answer": "string", "artifact_refs": "string[]"},
            required_operations=("op.model_response", "op.read_file", "op.search_files", "op.search_text", "op.edit_file"),
            optional_operations=("op.write_file", "op.shell"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.inspect_workspace",
                    title="检查工作区",
                    step_kind="read",
                    executor_type="tool",
                    required_operations=("op.read_file", "op.search_files", "op.search_text"),
                    output_contract_id="WorkspaceInspection",
                ),
                TaskStepBlueprint(
                    step_id="step_apply_patch",
                    title="修改文件",
                    step_kind="write",
                    executor_type="tool",
                    required_operations=("op.edit_file",),
                    optional_operations=("op.write_file",),
                    output_contract_id="WorkspacePatch",
                ),
                TaskStepBlueprint(
                    step_id="step_finalize_patch",
                    title="汇报变更结果",
                    step_kind="finalize",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="AssistantFinalAnswer",
                ),
            ),
            validation_rules=(
                TaskValidationRule(
                    rule_id="rule.artifact_claims_grounded",
                    title="产物声明必须有依据",
                    validation_kind="artifact_refs_or_edit_proof_required",
                    severity="error",
                ),
            ),
            safety_policy={
                "safety_class": "S2_bounded_patch",
                "write_mode": "scoped_patch",
                "default_write_roots": [],
                "forbidden_paths": [
                    ".env",
                    ".env.local",
                    "storage",
                    "node_modules",
                    ".git",
                ],
                "verification_mode": "artifact_or_edit_proof",
            },
            ui_manifest={"icon": "hammer", "category": "development"},
        ),
        TaskTemplate(
            template_id="template.dev.light_web_game",
            title="轻量网页小游戏",
            description="面向单文件或轻量前端页面的小游戏创建任务。",
            task_family="development",
            task_mode="light_web_game",
            input_schema={"workspace_path": "string", "goal": "string"},
            output_schema={"final_answer": "string", "artifact_refs": "string[]", "validation_state": "string"},
            required_operations=("op.model_response", "op.read_file", "op.search_files", "op.edit_file"),
            optional_operations=("op.write_file", "op.shell"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.inspect_workspace",
                    title="检查工作区",
                    step_kind="read",
                    executor_type="tool",
                    required_operations=("op.read_file", "op.search_files"),
                    output_contract_id="WorkspaceInspection",
                ),
                TaskStepBlueprint(
                    step_id="step.create_game_file",
                    title="创建或修改游戏文件",
                    step_kind="write",
                    executor_type="tool",
                    required_operations=("op.edit_file",),
                    optional_operations=("op.write_file",),
                    output_contract_id="GameArtifact",
                ),
                TaskStepBlueprint(
                    step_id="step.verify_artifact",
                    title="验证产物",
                    step_kind="verify",
                    executor_type="mcp",
                    optional_operations=("op.shell",),
                    output_contract_id="ArtifactVerification",
                    stop_policy="allow_unverified_completion",
                ),
                TaskStepBlueprint(
                    step_id="step.finalize_user_report",
                    title="汇报真实结果",
                    step_kind="finalize",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="AssistantFinalAnswer",
                ),
            ),
            validation_rules=(
                TaskValidationRule(
                    rule_id="rule.game_artifact_required",
                    title="必须有真实产物引用",
                    validation_kind="artifact_refs_required",
                    severity="error",
                ),
            ),
            safety_policy={
                "safety_class": "S1_bounded_artifact_write",
                "write_mode": "bounded_create",
                "default_write_roots": [
                    "frontend/public/games",
                ],
                "forbidden_paths": [
                    ".env",
                    ".env.local",
                    "storage",
                    "backend",
                    "node_modules",
                    ".git",
                ],
                "verification_mode": "artifact_refs_required",
            },
            ui_manifest={"icon": "gamepad-2", "category": "development"},
        ),
        TaskTemplate(
            template_id="template.writing.short_story",
            title="短篇小说协作写作",
            description="面向多 Agent 分阶段协作的短篇小说构思、编写、审校与验收任务。",
            task_family="writing",
            task_mode="short_story",
            input_schema={"goal": "string", "style_constraints": "string[]", "acceptance_requirements": "string[]"},
            output_schema={"final_answer": "string", "story_text": "string", "acceptance_result": "string"},
            required_operations=("op.model_response",),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.scope_story_goal",
                    title="收束题材目标与验收标准",
                    step_kind="understand",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="StoryTaskIntent",
                ),
                TaskStepBlueprint(
                    step_id="step.coordinate_story_pipeline",
                    title="推进创意、审校、编写与修正循环",
                    step_kind="coordinate",
                    executor_type="agent",
                    required_operations=("op.model_response",),
                    output_contract_id="StoryPipelineResult",
                ),
                TaskStepBlueprint(
                    step_id="step.finalize_story_delivery",
                    title="输出验收通过的短篇小说结果",
                    step_kind="finalize",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="AssistantFinalAnswer",
                ),
            ),
            validation_rules=(
                TaskValidationRule(
                    rule_id="rule.story_text_required",
                    title="必须产出短篇小说正文",
                    validation_kind="final_answer_required",
                    severity="error",
                ),
            ),
            safety_policy={
                "safety_class": "S0_readonly",
                "write_mode": "none",
                "verification_mode": "coordination_acceptance_required",
            },
            ui_manifest={"icon": "book-open-text", "category": "writing"},
            metadata={
                "coordination_task_id": "coord.writing.short_story_pipeline",
                "final_answer_requirements": [
                    "must_complete_pipeline_without_user_midpoint_approval",
                "must_include_complete_story_text",
                "must_include_idea_review_result",
                "must_include_content_inspection_result",
                "must_include_revision_result",
                "must_include_final_acceptance_result",
                "story_length_target_1200_to_1800_chinese_chars",
                "fixed_sections_coordination_summary_story_revision_acceptance",
            ],
                "forbidden_final_states": [
                    "waiting_for_user_approval",
                    "idea_only",
                    "outline_only",
                    "process_only_without_story",
                ],
            },
        ),
        TaskTemplate(
            template_id="template.writing.longform_novel_project",
            title="长篇小说项目立项",
            description="建立百万字级长篇小说项目规格、产物库结构、卷章拆解策略与验收闸门。",
            task_family="writing",
            task_mode="longform_novel_project",
            input_schema={"goal": "string", "target_word_count": "number", "artifact_root": "string"},
            output_schema={"project_spec": "NovelProjectSpec", "artifact_layout": "object", "next_task_refs": "string[]"},
            default_agent_id="agent:20",
            allowed_agent_ids=("agent:20", "agent:21", "agent:22", "agent:23"),
            required_operations=("op.model_response", "op.write_file"),
            optional_operations=("op.read_file", "op.search_text", "op.edit_file"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.longform_project_spec",
                    title="生成项目规格",
                    step_kind="coordinate",
                    executor_type="agent",
                    required_operations=("op.model_response", "op.write_file"),
                    output_contract_id="NovelProjectSpec",
                ),
            ),
            validation_rules=(
                TaskValidationRule(
                    "rule.project_spec_required",
                    "必须产出项目规格文件",
                    "artifact_file_required",
                    "error",
                    parameters=_LONGFORM_ARTIFACT_RULE,
                ),
            ),
            safety_policy={**_LONGFORM_WRITING_SAFETY_POLICY, "verification_mode": "project_spec_required"},
            ui_manifest={"icon": "book-marked", "category": "writing"},
            metadata={
                "coordination_task_id": "coord.writing.longform_project_bootstrap",
                "agent_group_id": "group.writing.longform_novel_core",
                "runtime_limits": _LONGFORM_RUNTIME_LIMITS,
            },
        ),
        TaskTemplate(
            template_id="template.writing.novel_bible_build",
            title="长篇小说圣经构建",
            description="构建长篇小说世界观、人物、剧情、时间线、风格与伏笔账本。",
            task_family="writing",
            task_mode="novel_bible_build",
            input_schema={"project_spec_ref": "string"},
            output_schema={"bible_bundle": "NovelBibleBundle"},
            default_agent_id="agent:20",
            allowed_agent_ids=("agent:20", "agent:21", "agent:22", "agent:23"),
            required_operations=("op.model_response", "op.write_file"),
            optional_operations=("op.read_file", "op.search_text", "op.edit_file"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.novel_bible_build",
                    title="生成圣经包",
                    step_kind="coordinate",
                    executor_type="agent",
                    required_operations=("op.model_response", "op.write_file"),
                    output_contract_id="NovelBibleBundle",
                ),
            ),
            validation_rules=(
                TaskValidationRule(
                    "rule.bible_bundle_required",
                    "必须产出圣经包文件",
                    "artifact_file_required",
                    "error",
                    parameters=_LONGFORM_ARTIFACT_RULE,
                ),
            ),
            safety_policy={**_LONGFORM_WRITING_SAFETY_POLICY, "verification_mode": "bible_bundle_required"},
            ui_manifest={"icon": "library", "category": "writing"},
            metadata={
                "coordination_task_id": "coord.writing.novel_bible_build",
                "agent_group_id": "group.writing.longform_novel_core",
                "runtime_limits": _LONGFORM_RUNTIME_LIMITS,
            },
        ),
        TaskTemplate(
            template_id="template.writing.volume_planning",
            title="长篇小说卷规划",
            description="为指定卷生成卷目标、章节范围、人物弧线、事件链和伏笔计划。",
            task_family="writing",
            task_mode="volume_planning",
            input_schema={"novel_bible_ref": "string", "volume_index": "number"},
            output_schema={"volume_plan": "VolumePlan"},
            default_agent_id="agent:20",
            allowed_agent_ids=("agent:20", "agent:22", "agent:23", "agent:25"),
            required_operations=("op.model_response", "op.write_file"),
            optional_operations=("op.read_file", "op.search_text", "op.edit_file"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.volume_plan",
                    title="生成卷纲",
                    step_kind="coordinate",
                    executor_type="agent",
                    required_operations=("op.model_response", "op.write_file"),
                    output_contract_id="VolumePlan",
                ),
            ),
            validation_rules=(TaskValidationRule("rule.volume_plan_required", "必须产出卷纲文件", "artifact_file_required", "error", parameters=_LONGFORM_ARTIFACT_RULE),),
            safety_policy={**_LONGFORM_WRITING_SAFETY_POLICY, "verification_mode": "volume_plan_required"},
            ui_manifest={"icon": "columns-3", "category": "writing"},
            metadata={"coordination_task_id": "coord.writing.volume_planning", "agent_group_id": "group.writing.longform_novel_core", "runtime_limits": _LONGFORM_RUNTIME_LIMITS},
        ),
        TaskTemplate(
            template_id="template.writing.chapter_planning",
            title="长篇小说章节规划",
            description="为单章生成场景节拍、章节目标、上下文引用和验收条件。",
            task_family="writing",
            task_mode="chapter_planning",
            input_schema={"volume_plan_ref": "string", "chapter_index": "number"},
            output_schema={"chapter_plan": "ChapterPlan"},
            default_agent_id="agent:23",
            allowed_agent_ids=("agent:20", "agent:23", "agent:24", "agent:25", "agent:26"),
            required_operations=("op.model_response", "op.write_file"),
            optional_operations=("op.read_file", "op.search_text", "op.edit_file"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.chapter_plan",
                    title="生成章节规划",
                    step_kind="coordinate",
                    executor_type="agent",
                    required_operations=("op.model_response", "op.write_file"),
                    output_contract_id="ChapterPlan",
                ),
            ),
            validation_rules=(TaskValidationRule("rule.chapter_plan_required", "必须产出章节规划文件", "artifact_file_required", "error", parameters=_LONGFORM_ARTIFACT_RULE),),
            safety_policy={**_LONGFORM_WRITING_SAFETY_POLICY, "verification_mode": "chapter_plan_required"},
            ui_manifest={"icon": "list-tree", "category": "writing"},
            metadata={"coordination_task_id": "coord.writing.chapter_pipeline", "agent_group_id": "group.writing.longform_novel_core", "runtime_limits": _LONGFORM_RUNTIME_LIMITS},
        ),
        TaskTemplate(
            template_id="template.writing.chapter_drafting",
            title="长篇小说章节正文",
            description="根据章节规划生成真实章节正文，并进入审校与验收流水线。",
            task_family="writing",
            task_mode="chapter_drafting",
            input_schema={"chapter_plan_ref": "string", "target_word_count": "number"},
            output_schema={"chapter_draft": "ChapterDraft", "artifact_refs": "string[]"},
            default_agent_id="agent:24",
            allowed_agent_ids=("agent:20", "agent:23", "agent:24", "agent:25", "agent:26"),
            required_operations=("op.model_response", "op.write_file"),
            optional_operations=("op.read_file", "op.search_text", "op.edit_file"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.chapter_pipeline",
                    title="生成、审校、修订并验收章节",
                    step_kind="coordinate",
                    executor_type="agent",
                    required_operations=("op.model_response", "op.write_file"),
                    output_contract_id="ChapterDraft",
                ),
            ),
            validation_rules=(TaskValidationRule("rule.chapter_body_required", "必须产出真实章节正文文件", "artifact_file_required", "error", parameters=_LONGFORM_ARTIFACT_RULE),),
            safety_policy={**_LONGFORM_WRITING_SAFETY_POLICY, "verification_mode": "chapter_body_required"},
            ui_manifest={"icon": "file-pen-line", "category": "writing"},
            metadata={
                "coordination_task_id": "coord.writing.chapter_pipeline",
                "agent_group_id": "group.writing.longform_novel_core",
                "runtime_limits": _LONGFORM_RUNTIME_LIMITS,
                "final_answer_requirements": ["must_include_complete_chapter_body_or_artifact_ref", "must_include_review_and_revision_status"],
                "forbidden_final_states": ["outline_only", "summary_only", "waiting_for_user_approval"],
            },
        ),
        TaskTemplate(
            template_id="template.writing.chapter_revision",
            title="长篇小说章节修订",
            description="根据审校和连续性问题修订章节正文。",
            task_family="writing",
            task_mode="chapter_revision",
            input_schema={"chapter_draft_ref": "string", "review_report_refs": "string[]"},
            output_schema={"chapter_revision": "ChapterRevision"},
            default_agent_id="agent:24",
            allowed_agent_ids=("agent:20", "agent:24", "agent:25", "agent:26"),
            required_operations=("op.model_response", "op.write_file"),
            optional_operations=("op.read_file", "op.search_text", "op.edit_file"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.chapter_revision",
                    title="修订章节正文",
                    step_kind="coordinate",
                    executor_type="agent",
                    required_operations=("op.model_response", "op.write_file"),
                    output_contract_id="ChapterRevision",
                ),
            ),
            validation_rules=(TaskValidationRule("rule.chapter_revision_required", "必须产出修订结果文件", "artifact_file_required", "error", parameters=_LONGFORM_ARTIFACT_RULE),),
            safety_policy={**_LONGFORM_WRITING_SAFETY_POLICY, "verification_mode": "chapter_revision_required"},
            ui_manifest={"icon": "file-check-2", "category": "writing"},
            metadata={"coordination_task_id": "coord.writing.chapter_pipeline", "agent_group_id": "group.writing.longform_novel_core", "runtime_limits": _LONGFORM_RUNTIME_LIMITS},
        ),
        TaskTemplate(
            template_id="template.writing.continuity_audit",
            title="长篇小说连续性审计",
            description="检查指定章节范围的设定、时间线、人物与伏笔连续性。",
            task_family="writing",
            task_mode="continuity_audit",
            input_schema={"chapter_range_refs": "string[]", "novel_bible_ref": "string"},
            output_schema={"audit_report": "ContinuityAuditReport"},
            default_agent_id="agent:26",
            allowed_agent_ids=("agent:20", "agent:21", "agent:25", "agent:26"),
            required_operations=("op.model_response", "op.write_file"),
            optional_operations=("op.read_file", "op.search_text", "op.edit_file"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.continuity_audit",
                    title="执行连续性审计",
                    step_kind="coordinate",
                    executor_type="agent",
                    required_operations=("op.model_response", "op.write_file"),
                    output_contract_id="ContinuityAuditReport",
                ),
            ),
            validation_rules=(TaskValidationRule("rule.audit_report_required", "必须产出审计报告文件", "artifact_file_required", "error", parameters=_LONGFORM_ARTIFACT_RULE),),
            safety_policy={**_LONGFORM_WRITING_SAFETY_POLICY, "verification_mode": "audit_report_required"},
            ui_manifest={"icon": "scan-search", "category": "writing"},
            metadata={"coordination_task_id": "coord.writing.continuity_audit", "agent_group_id": "group.writing.longform_novel_core", "runtime_limits": _LONGFORM_RUNTIME_LIMITS},
        ),
        TaskTemplate(
            template_id="template.writing.final_compilation",
            title="长篇小说全书编纂",
            description="汇总已验收章节与终审报告，生成全书编纂清单和最终产物引用。",
            task_family="writing",
            task_mode="final_compilation",
            input_schema={"accepted_chapter_refs": "string[]", "final_audit_refs": "string[]"},
            output_schema={"compilation": "LongformNovelCompilation"},
            default_agent_id="agent:20",
            allowed_agent_ids=("agent:20", "agent:24", "agent:25", "agent:26"),
            required_operations=("op.model_response", "op.write_file"),
            optional_operations=("op.read_file", "op.search_text", "op.edit_file"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.final_compilation",
                    title="编纂全书",
                    step_kind="coordinate",
                    executor_type="agent",
                    required_operations=("op.model_response", "op.write_file"),
                    output_contract_id="LongformNovelCompilation",
                ),
            ),
            validation_rules=(TaskValidationRule("rule.compilation_required", "必须产出编纂清单文件", "artifact_file_required", "error", parameters=_LONGFORM_ARTIFACT_RULE),),
            safety_policy={**_LONGFORM_WRITING_SAFETY_POLICY, "verification_mode": "compilation_required"},
            ui_manifest={"icon": "book-check", "category": "writing"},
            metadata={"coordination_task_id": "coord.writing.final_compilation", "agent_group_id": "group.writing.longform_novel_core", "runtime_limits": _LONGFORM_RUNTIME_LIMITS},
        ),
        TaskTemplate(
            template_id="template.dev.arcade_game_bundle",
            title="复合网页小游戏包",
            description="面向多文件网页小游戏的受限开发任务模板。",
            task_family="development",
            task_mode="arcade_game_bundle",
            input_schema={"workspace_path": "string", "goal": "string", "target_root": "string"},
            output_schema={
                "final_answer": "string",
                "artifact_refs": "string[]",
                "validation_state": "string",
                "entry_file": "string",
            },
            required_operations=("op.model_response", "op.read_file", "op.search_files", "op.search_text", "op.edit_file"),
            optional_operations=("op.write_file", "op.shell"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.inspect_target_root",
                    title="检查目标目录与已有资源",
                    step_kind="read",
                    executor_type="tool",
                    required_operations=("op.read_file", "op.search_files", "op.search_text"),
                    output_contract_id="WorkspaceInspection",
                ),
                TaskStepBlueprint(
                    step_id="step.design_file_set",
                    title="规划文件结构与运行入口",
                    step_kind="understand",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="ArtifactPlan",
                ),
                TaskStepBlueprint(
                    step_id="step.implement_artifacts",
                    title="生成或修改多文件产物",
                    step_kind="write",
                    executor_type="tool",
                    required_operations=("op.edit_file",),
                    optional_operations=("op.write_file",),
                    output_contract_id="GameArtifactBundle",
                ),
                TaskStepBlueprint(
                    step_id="step.verify_bundle",
                    title="验证入口文件与资源关系",
                    step_kind="verify",
                    executor_type="mcp",
                    optional_operations=("op.shell",),
                    output_contract_id="ArtifactVerification",
                    stop_policy="allow_unverified_completion",
                ),
                TaskStepBlueprint(
                    step_id="step.finalize_bundle_report",
                    title="汇报真实产物与限制",
                    step_kind="finalize",
                    executor_type="model",
                    required_operations=("op.model_response",),
                    output_contract_id="AssistantFinalAnswer",
                ),
            ),
            validation_rules=(
                TaskValidationRule(
                    rule_id="rule.bundle_artifacts_required",
                    title="必须产出多文件结果",
                    validation_kind="artifact_refs_required",
                    severity="error",
                    parameters={"min_artifact_count": 2},
                ),
            ),
            safety_policy={
                "safety_class": "S1_bounded_artifact_write",
                "write_mode": "bounded_create",
                "default_write_roots": [
                    "frontend/public/games",
                ],
                "forbidden_paths": [
                    ".env",
                    ".env.local",
                    "storage",
                    "backend",
                    "node_modules",
                    ".git",
                ],
                "verification_mode": "artifact_refs_required",
            },
            ui_manifest={"icon": "joystick", "category": "development"},
        ),
        TaskTemplate(
            template_id="template.health.issue_triage",
            title="健康问题分诊",
            description="健康系统专用的 issue triage 模板。",
            task_family="health",
            task_mode="issue_triage",
            input_schema={"issue": "HealthIssue"},
            output_schema={"result": "HealthTriageResult"},
            default_agent_id="agent:3",
            allowed_agent_ids=("agent:3",),
            required_operations=("op.model_response", "op.read_file", "op.search_text"),
            step_blueprints=(
                TaskStepBlueprint(
                    step_id="step.health_issue_triage",
                    title="健康问题分诊",
                    step_kind="analyze",
                    executor_type="agent",
                    required_operations=("op.model_response", "op.read_file", "op.search_text"),
                    output_contract_id="HealthTriageResult",
                ),
            ),
            safety_policy={
                "safety_class": "S0_readonly",
                "write_mode": "none",
                "verification_mode": "health_result_only",
            },
            ui_manifest={"icon": "shield-alert", "category": "health"},
            metadata={"linked_flow_id": "flow.health.issue_triage"},
        ),
    )


class TaskTemplateRegistry:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else None
        self.agent_registry = AgentRegistry(self.base_dir or Path(".")) if self.base_dir is not None else None
        self.agent_runtime_registry = AgentRuntimeRegistry(self.base_dir or Path(".")) if self.base_dir is not None else None
        self.operation_registry = build_default_operation_registry()

    def list_templates(self) -> list[TaskTemplate]:
        return list(default_task_templates())

    def get_template(self, template_id: str) -> TaskTemplate | None:
        target = str(template_id or "").strip()
        return next((item for item in self.list_templates() if item.template_id == target), None)

    def build_task_intent_contract(
        self,
        *,
        session_id: str,
        task_id: str,
        user_goal: str,
        query_understanding: dict[str, Any] | None = None,
        current_turn_context: dict[str, Any] | None = None,
    ) -> TaskIntentContract:
        understanding = dict(query_understanding or {})
        current_turn = dict(current_turn_context or {})
        explicit_inputs = dict(current_turn.get("explicit_inputs") or {})
        bundle_items = [
            dict(item)
            for item in list(current_turn.get("bundle_items") or [])
            if isinstance(item, dict)
        ]
        resolved_bindings = [
            dict(item)
            for item in list(current_turn.get("resolved_bindings") or [])
            if isinstance(item, dict)
        ]
        capability_requests = _dedupe(
            [
                *[
                    str(item or "").strip()
                    for item in list(understanding.get("capability_requests") or [])
                    if str(item or "").strip()
                ],
                *[
                    str(item or "").strip()
                    for item in list(explicit_inputs.get("capability_requests") or [])
                    if str(item or "").strip()
                ],
            ]
        )
        candidate_template_ids = _intent_candidate_template_ids(
            explicit_inputs=explicit_inputs,
            bundle_items=bundle_items,
            resolved_bindings=resolved_bindings,
            capability_requests=capability_requests,
            user_goal=user_goal,
            query_understanding=understanding,
            current_turn_context=current_turn,
        )
        followup_target_refs = _dedupe(
            [
                *[
                    str(item.get("followup_target_ref") or item.get("target_ref") or "").strip()
                    for item in bundle_items
                    if isinstance(item, dict)
                ],
                *[
                    str(item or "").strip()
                    for item in list(current_turn.get("followup_target_refs") or [])
                    if str(item or "").strip()
                ],
            ]
        )
        requested_outputs = _intent_requested_outputs(
            explicit_inputs=explicit_inputs,
            bundle_items=bundle_items,
            capability_requests=capability_requests,
            current_turn_context=current_turn,
        )
        execution_intent = _execution_intent_from_context(
            current_turn_context=current_turn,
            bundle_items=bundle_items,
        )
        return TaskIntentContract(
            task_intent_id=f"task-intent:{session_id}:{task_id}",
            session_id=session_id,
            task_id=task_id,
            user_goal=user_goal,
            intent_kind=str(current_turn.get("intent") or understanding.get("intent") or ""),
            execution_intent=execution_intent,
            requested_outputs=tuple(requested_outputs),
            explicit_inputs=explicit_inputs,
            source_binding_refs=tuple(
                _dedupe(
                    [
                        str(item.get("binding_id") or "").strip()
                        for item in resolved_bindings
                        if str(item.get("binding_id") or "").strip()
                    ]
                )
            ),
            followup_target_refs=tuple(followup_target_refs),
            capability_requests=tuple(capability_requests),
            candidate_template_ids=tuple(candidate_template_ids),
            diagnostics={
                "execution_mode": str(current_turn.get("execution_mode") or "single"),
                "bundle_item_count": len(bundle_items),
                "route_hint": str(understanding.get("route_hint") or ""),
                "preferred_skill": str(understanding.get("preferred_skill") or ""),
                "source_kind": str(understanding.get("source_kind") or ""),
                "modality": str(understanding.get("modality") or ""),
            },
        )

    def match_template(
        self,
        *,
        task_intent_contract: TaskIntentContract,
        query_understanding: dict[str, Any] | None = None,
        current_turn_context: dict[str, Any] | None = None,
        definitions: list[TaskDefinition] | None = None,
    ) -> TemplateMatchResult:
        templates = {item.template_id: item for item in self.list_templates()}
        understanding = dict(query_understanding or {})
        current_turn = dict(current_turn_context or {})
        explicit_inputs = dict(task_intent_contract.explicit_inputs or {})
        definition_ids = {
            str(item.definition_id or "").strip()
            for item in list(definitions or [])
            if isinstance(item, TaskDefinition)
        }
        route_hint = str(understanding.get("route_hint") or "").strip()
        execution_posture = str(understanding.get("execution_posture") or "").strip()
        preferred_skill = str(understanding.get("preferred_skill") or "").strip()
        source_kind = str(understanding.get("source_kind") or "").strip()
        modality = str(understanding.get("modality") or "").strip()
        lowered_goal = str(task_intent_contract.user_goal or "").lower()
        capability_requests = set(task_intent_contract.capability_requests)
        explicit_template_id = str(explicit_inputs.get("explicit_template_id") or "").strip()

        match_source = "heuristic_fallback"
        match_reasons: list[str] = []
        template_id = ""

        if explicit_template_id and explicit_template_id in templates:
            template_id = explicit_template_id
            match_source = "explicit_template"
            match_reasons.append("explicit_template_id")
        elif task_intent_contract.execution_intent == "bundle_task":
            template_id = "template.bundle.multi_capability"
            match_source = "binding_contract"
            match_reasons.append("bundle_execution_mode")
        elif task_intent_contract.candidate_template_ids:
            for candidate_template_id in task_intent_contract.candidate_template_ids:
                if candidate_template_id in templates:
                    template_id = candidate_template_id
                    match_source = "binding_contract"
                    match_reasons.append(f"candidate_template:{candidate_template_id}")
                    break
        elif "flow.health.issue_triage" in lowered_goal or "health_issue" in capability_requests:
            template_id = "template.health.issue_triage"
            match_source = "capability_contract"
            match_reasons.append("health_issue_capability")
        elif execution_posture == "direct_rag" or route_hint == "rag" or preferred_skill == "rag-skill":
            template_id = "template.rag.knowledge_answer"
            match_source = "capability_contract"
            match_reasons.append("rag_execution_posture")
        elif route_hint == "search" or "task.information_search" in definition_ids:
            template_id = "template.search.information_search"
            match_source = "capability_contract"
            match_reasons.append("search_route_hint")
        elif execution_posture == "direct_tool" or route_hint == "tool":
            template_id = "template.capability.direct_tool"
            match_source = "capability_contract"
            match_reasons.append("direct_tool_route")
        elif _looks_like_light_web_game(lowered_goal):
            template_id = "template.dev.light_web_game"
            match_source = "heuristic_fallback"
            match_reasons.append("light_web_game_phrase")
        elif source_kind == "workspace" or "task.task_execution" in definition_ids or "task.local_material_read" in definition_ids:
            template_id = "template.dev.workspace_patch"
            match_source = "binding_contract"
            match_reasons.append("workspace_source_kind")

        if not template_id:
            if modality == "pdf" or explicit_inputs.get("explicit_pdf_path") or explicit_inputs.get("bound_pdf_path"):
                template_id = "template.pdf.document_analysis"
                match_source = "binding_contract"
                match_reasons.append("pdf_binding")
            elif (
                modality == "table"
                or source_kind == "dataset"
                or explicit_inputs.get("explicit_dataset_path")
                or explicit_inputs.get("bound_dataset_path")
            ):
                template_id = "template.data.structured_analysis"
                match_source = "binding_contract"
                match_reasons.append("dataset_binding")

        if not template_id:
            template_id = "template.chat.general_response"
            match_reasons.append("fallback_general_response")

        selected_template = templates[template_id]
        return TemplateMatchResult(
            match_id=f"template-match:{task_intent_contract.task_id}",
            task_intent_ref=task_intent_contract.task_intent_id,
            template_id=selected_template.template_id,
            match_source=match_source,
            match_reasons=tuple(match_reasons),
            fallback_used=match_source == "heuristic_fallback",
            capability_contract=tuple(task_intent_contract.capability_requests),
            output_contract=tuple(task_intent_contract.requested_outputs),
            diagnostics={
                "definition_ids": sorted(definition_ids),
                "route_hint": route_hint,
                "execution_posture": execution_posture,
                "preferred_skill": preferred_skill,
                "source_kind": source_kind,
                "modality": modality,
                "current_turn_execution_mode": str(current_turn.get("execution_mode") or ""),
            },
        )

    def select_template(
        self,
        *,
        session_id: str = "",
        task_id: str = "",
        user_goal: str,
        query_understanding: dict[str, Any] | None = None,
        current_turn_context: dict[str, Any] | None = None,
        definitions: list[TaskDefinition] | None = None,
    ) -> TaskTemplate:
        task_intent_contract = self.build_task_intent_contract(
            session_id=session_id or "session",
            task_id=task_id or "task",
            user_goal=user_goal,
            query_understanding=query_understanding,
            current_turn_context=current_turn_context,
        )
        match = self.match_template(
            task_intent_contract=task_intent_contract,
            query_understanding=query_understanding,
            current_turn_context=current_turn_context,
            definitions=definitions,
        )
        template = self.get_template(match.template_id)
        if template is None:
            raise ValueError(f"Unknown template selected: {match.template_id}")
        return template

    def build_validation_matrix(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for template in self.list_templates():
            failures: list[str] = []
            diagnostics: dict[str, Any] = {}
            agent = self.agent_registry.get_agent(template.default_agent_id) if self.agent_registry is not None else None
            capability = self.agent_runtime_registry.get_profile(template.default_agent_id) if self.agent_runtime_registry is not None else None
            if agent is None:
                failures.append("default_agent_missing")
            elif agent.lifecycle_state not in {"enabled", "system_builtin"}:
                failures.append("default_agent_not_enabled")
            if capability is None:
                failures.append("runtime_profile_missing")
            else:
                missing_required = [
                    operation
                    for operation in template.required_operations
                    if operation not in capability.allowed_operations
                ]
                if missing_required:
                    failures.append("required_operations_not_allowed")
                    diagnostics["missing_required_operations"] = missing_required
                blocked_optional = [
                    operation
                    for operation in template.optional_operations
                    if operation not in capability.allowed_operations
                ]
                if blocked_optional:
                    diagnostics["optional_operations_not_allowed"] = blocked_optional
            unknown_operations = [
                operation
                for operation in (*template.required_operations, *template.optional_operations)
                if self.operation_registry.get_operation(operation) is None
            ]
            if unknown_operations:
                failures.append("operation_missing_from_registry")
                diagnostics["unknown_operations"] = unknown_operations
            rows.append(
                {
                    "template_id": template.template_id,
                    "default_agent_id": template.default_agent_id,
                    "required_operations": list(template.required_operations),
                    "optional_operations": list(template.optional_operations),
                    "validation_state": "valid" if not failures else "invalid",
                    "blocked_reasons": failures,
                    "diagnostics": diagnostics,
                }
            )
        return {
            "authority": "task_system.template_validation_matrix",
            "rows": rows,
        }


def _looks_like_light_web_game(text: str) -> bool:
    return any(token in text for token in ("贪吃蛇", "小游戏", "game", "snake", "html5 game", "web game"))


def _execution_intent_from_context(
    *,
    current_turn_context: dict[str, Any],
    bundle_items: list[dict[str, Any]],
) -> str:
    execution_mode = str(current_turn_context.get("execution_mode") or "").strip()
    if execution_mode == "bundle" or len(bundle_items) > 1:
        return "bundle_task"
    if str(current_turn_context.get("intent") or "") == "bundle_followup" and bundle_items:
        return "bundle_followup_item"
    return "single_task"


def _intent_requested_outputs(
    *,
    explicit_inputs: dict[str, Any],
    bundle_items: list[dict[str, Any]],
    capability_requests: list[str],
    current_turn_context: dict[str, Any],
) -> list[str]:
    explicit_outputs = [
        str(item or "").strip()
        for item in list(explicit_inputs.get("requested_outputs") or [])
        if str(item or "").strip()
    ]
    if explicit_outputs:
        return explicit_outputs
    if len(bundle_items) > 1 or str(current_turn_context.get("execution_mode") or "") == "bundle":
        return ["final_answer", "bundle_result_refs"]
    if bundle_items:
        item_outputs = [
            str(item or "").strip()
            for item in list(bundle_items[0].get("requested_outputs") or [])
            if str(item or "").strip()
        ]
        if item_outputs:
            return item_outputs
    if "document_analysis" in capability_requests:
        return ["final_answer", "task_summary_refs"]
    if "dataset_analysis" in capability_requests:
        return ["final_answer", "task_summary_refs"]
    return ["final_answer"]


def _intent_candidate_template_ids(
    *,
    explicit_inputs: dict[str, Any],
    bundle_items: list[dict[str, Any]],
    resolved_bindings: list[dict[str, Any]],
    capability_requests: list[str],
    user_goal: str,
    query_understanding: dict[str, Any],
    current_turn_context: dict[str, Any],
) -> list[str]:
    candidates: list[str] = []
    explicit_template_id = str(explicit_inputs.get("explicit_template_id") or "").strip()
    if explicit_template_id:
        candidates.append(explicit_template_id)
    execution_mode = str(current_turn_context.get("execution_mode") or "").strip()
    if execution_mode == "bundle" or len(bundle_items) > 1:
        candidates.append("template.bundle.multi_capability")
    if len(bundle_items) == 1:
        item_template = str(bundle_items[0].get("template_id") or "").strip()
        if item_template:
            candidates.append(item_template)
    if explicit_inputs.get("explicit_pdf_path") or explicit_inputs.get("bound_pdf_path"):
        candidates.append("template.pdf.document_analysis")
    if explicit_inputs.get("explicit_dataset_path") or explicit_inputs.get("bound_dataset_path"):
        candidates.append("template.data.structured_analysis")
    binding_file_kinds = {
        str(item.get("file_kind") or "").strip()
        for item in resolved_bindings
        if str(item.get("binding_kind") or "").strip() == "source_file"
    }
    if "pdf" in binding_file_kinds:
        candidates.append("template.pdf.document_analysis")
    if "dataset" in binding_file_kinds:
        candidates.append("template.data.structured_analysis")
    for request in capability_requests:
        if request in {"document_analysis", "pdf"}:
            candidates.append("template.pdf.document_analysis")
        if request in {"dataset_analysis", "structured_data"}:
            candidates.append("template.data.structured_analysis")
        if request in {"weather", "gold_price"}:
            candidates.append("template.capability.direct_tool")
    if _looks_like_light_web_game(str(user_goal or "").lower()):
        candidates.append("template.dev.light_web_game")
    source_kind = str(query_understanding.get("source_kind") or "").strip()
    if source_kind == "workspace":
        candidates.append("template.dev.workspace_patch")
    return _dedupe(candidates)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
