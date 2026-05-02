from __future__ import annotations

from pathlib import Path
from typing import Any

from operations import AgentRegistry, build_default_operation_registry

from .definitions import TaskDefinition
from .step_models import TaskStepBlueprint
from .template_models import TaskTemplate, TaskValidationRule


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
                    executor_type="worker",
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
            ui_manifest={"icon": "gamepad-2", "category": "development"},
        ),
        TaskTemplate(
            template_id="template.health.issue_triage",
            title="健康问题分诊",
            description="健康系统专用的 issue triage 模板。",
            task_family="health",
            task_mode="issue_triage",
            input_schema={"issue": "HealthIssue"},
            output_schema={"result": "HealthTriageResult"},
            default_agent_id="agent:health:maintainer",
            allowed_agent_ids=("agent:health:maintainer",),
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
            ui_manifest={"icon": "shield-alert", "category": "health"},
            metadata={"linked_flow_id": "flow.health.issue_triage"},
        ),
    )


class TaskTemplateRegistry:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else None
        self.agent_registry = AgentRegistry(self.base_dir or Path(".")) if self.base_dir is not None else None
        self.operation_registry = build_default_operation_registry()

    def list_templates(self) -> list[TaskTemplate]:
        return list(default_task_templates())

    def get_template(self, template_id: str) -> TaskTemplate | None:
        target = str(template_id or "").strip()
        return next((item for item in self.list_templates() if item.template_id == target), None)

    def select_template(
        self,
        *,
        user_goal: str,
        query_understanding: dict[str, Any] | None = None,
        current_turn_context: dict[str, Any] | None = None,
        definitions: list[TaskDefinition] | None = None,
    ) -> TaskTemplate:
        templates = {item.template_id: item for item in self.list_templates()}
        understanding = dict(query_understanding or {})
        current_turn = dict(current_turn_context or {})
        explicit_inputs = dict(current_turn.get("explicit_inputs") or {})
        definition_ids = {
            str(item.definition_id or "").strip()
            for item in list(definitions or [])
            if isinstance(item, TaskDefinition)
        }
        candidate_tools = {
            str(item or "").strip()
            for item in list(understanding.get("candidate_tools") or [])
            if str(item or "").strip()
        }
        capability_requests = {
            str(item or "").strip()
            for item in list(understanding.get("capability_requests") or [])
            if str(item or "").strip()
        }
        route_hint = str(understanding.get("route_hint") or "").strip()
        execution_posture = str(understanding.get("execution_posture") or "").strip()
        preferred_skill = str(understanding.get("preferred_skill") or "").strip()
        source_kind = str(understanding.get("source_kind") or "").strip()
        modality = str(understanding.get("modality") or "").strip()
        execution_mode = str(current_turn.get("execution_mode") or "").strip()
        lowered_goal = str(user_goal or "").lower()

        if execution_mode == "bundle":
            return templates["template.bundle.multi_capability"]
        if "flow.health.issue_triage" in lowered_goal or "health_issue" in capability_requests:
            return templates["template.health.issue_triage"]
        if execution_posture == "direct_rag" or route_hint == "rag" or preferred_skill == "rag-skill":
            return templates["template.rag.knowledge_answer"]
        if modality == "pdf" or "document_analysis" in capability_requests or explicit_inputs.get("explicit_pdf_path") or explicit_inputs.get("bound_pdf_path"):
            return templates["template.pdf.document_analysis"]
        if (
            modality == "table"
            or source_kind == "dataset"
            or "dataset_analysis" in capability_requests
            or explicit_inputs.get("explicit_dataset_path")
            or explicit_inputs.get("bound_dataset_path")
        ):
            return templates["template.data.structured_analysis"]
        if execution_posture == "direct_tool" or route_hint == "tool":
            return templates["template.capability.direct_tool"]
        if route_hint == "search" or "task.information_search" in definition_ids:
            return templates["template.search.information_search"]
        if _looks_like_light_web_game(lowered_goal):
            return templates["template.dev.light_web_game"]
        if source_kind == "workspace" or "task.task_execution" in definition_ids or "task.local_material_read" in definition_ids:
            return templates["template.dev.workspace_patch"]
        if candidate_tools & {"read_file", "search_files", "search_text"}:
            return templates["template.dev.workspace_patch"]
        return templates["template.chat.general_response"]

    def build_validation_matrix(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for template in self.list_templates():
            failures: list[str] = []
            diagnostics: dict[str, Any] = {}
            agent = self.agent_registry.get_agent(template.default_agent_id) if self.agent_registry is not None else None
            capability = (
                self.agent_registry.get_capability_profile(template.default_agent_id)
                if self.agent_registry is not None
                else None
            )
            if agent is None:
                failures.append("default_agent_missing")
            elif agent.lifecycle_state not in {"enabled", "system_builtin"}:
                failures.append("default_agent_not_enabled")
            if capability is None:
                failures.append("capability_profile_missing")
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
