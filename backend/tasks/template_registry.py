from __future__ import annotations

from pathlib import Path
from typing import Any

from operations import AgentRegistry, build_default_operation_registry
from orchestration import AgentRuntimeRegistry

from .match_contracts import TaskIntentContract, TemplateMatchResult
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
