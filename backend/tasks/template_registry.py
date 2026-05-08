from __future__ import annotations

from pathlib import Path
from typing import Any

from capability_system import build_default_operation_registry
from capability_system.local_mcp_registry import get_local_mcp_primary_template, get_local_mcp_unit_for_source_kind
from orchestration.agent_registry import AgentRegistry
from orchestration.agent_runtime_registry import AgentRuntimeRegistry

from .match_contracts import TaskIntentContract, TemplateMatchResult
from .definitions import TaskDefinition
from .step_models import TaskStepBlueprint
from .template_models import TaskTemplate, TaskValidationRule

_PDF_TEMPLATE_ID = get_local_mcp_primary_template("pdf") or "template.pdf.document_analysis"
_STRUCTURED_DATA_TEMPLATE_ID = get_local_mcp_primary_template("structured_data") or "template.data.structured_analysis"
_RAG_TEMPLATE_ID = get_local_mcp_primary_template("retrieval") or "template.rag.knowledge_answer"


def default_task_templates() -> tuple[TaskTemplate, ...]:
    general_steps = (
        _step("understand_request", "理解当前请求", "understand"),
        _step("respond", "生成主会话回答", "finalize"),
    )
    return (
        TaskTemplate(
            template_id="template.general.main_conversation",
            title="主会话通用任务",
            description="承接没有命中特定工具、文件或注册任务的普通对话与最终回答。",
            task_family="general",
            task_mode="general_task",
            output_schema={"final_answer": {"type": "string", "required": True}},
            required_operations=("op.model_response",),
            step_blueprints=general_steps,
            metadata={
                "canonical_template": True,
                "legacy_template_ids": ("template.chat.general_response",),
                "workflow_id": "workflow.general.main_conversation",
                "final_answer_requirements": ("直接回答用户当前问题。",),
            },
        ),
        TaskTemplate(
            template_id="template.chat.general_response",
            title="主会话通用任务（迁移别名）",
            description="旧 template id 的迁移别名；运行语义与 template.general.main_conversation 相同。",
            task_family="general",
            task_mode="general_task",
            output_schema={"final_answer": {"type": "string", "required": True}},
            required_operations=("op.model_response",),
            step_blueprints=general_steps,
            metadata={
                "canonical_template_id": "template.general.main_conversation",
                "migration_alias": True,
                "workflow_id": "workflow.general.main_conversation",
            },
        ),
        TaskTemplate(
            template_id=_RAG_TEMPLATE_ID,
            title="知识检索回答",
            description="通过检索能力获取证据并生成有依据的回答。",
            task_family="retrieval",
            task_mode="knowledge_retrieval",
            output_schema={
                "final_answer": {"type": "string", "required": True},
                "task_summary_refs": {"type": "array", "required": False},
            },
            required_capability_tags=("retrieval",),
            required_operations=("op.model_response", "op.mcp_retrieval"),
            step_blueprints=(
                _step("retrieve_evidence", "检索相关证据", "execute", required_operations=("op.mcp_retrieval",)),
                _step("synthesize_answer", "综合检索结果", "finalize"),
            ),
            metadata={"source_kind": "retrieval", "workflow_id": "workflow.general.main_conversation"},
        ),
        TaskTemplate(
            template_id=_PDF_TEMPLATE_ID,
            title="PDF 文档分析",
            description="通过 PDF 能力读取指定文档并回答问题。",
            task_family="document",
            task_mode="capability_execution",
            output_schema={
                "final_answer": {"type": "string", "required": True},
                "task_summary_refs": {"type": "array", "required": False},
            },
            required_capability_tags=("pdf", "document_analysis"),
            required_operations=("op.model_response", "op.mcp_pdf"),
            step_blueprints=(
                _step("analyze_pdf", "分析 PDF", "analyze", required_operations=("op.mcp_pdf",)),
                _step("finalize_pdf_answer", "输出文档回答", "finalize"),
            ),
            metadata={"source_kind": "pdf", "workflow_id": "workflow.general.main_conversation"},
        ),
        TaskTemplate(
            template_id=_STRUCTURED_DATA_TEMPLATE_ID,
            title="结构化数据分析",
            description="通过结构化数据能力读取表格或数据集并回答问题。",
            task_family="data",
            task_mode="capability_execution",
            output_schema={
                "final_answer": {"type": "string", "required": True},
                "task_summary_refs": {"type": "array", "required": False},
            },
            required_capability_tags=("structured_data", "dataset_analysis"),
            required_operations=("op.model_response", "op.mcp_structured_data"),
            step_blueprints=(
                _step("analyze_dataset", "分析数据集", "analyze", required_operations=("op.mcp_structured_data",)),
                _step("finalize_dataset_answer", "输出数据回答", "finalize"),
            ),
            metadata={"source_kind": "dataset", "workflow_id": "workflow.general.main_conversation"},
        ),
        TaskTemplate(
            template_id="template.search.information_search",
            title="信息搜索",
            description="搜索外部或实时信息，并汇总可追踪结果。",
            task_family="search",
            task_mode="information_search",
            output_schema={"final_answer": {"type": "string", "required": True}},
            required_operations=("op.model_response", "op.web_search", "op.fetch_url"),
            step_blueprints=(
                _step("search_information", "搜索信息", "execute", required_operations=("op.web_search",)),
                _step("summarize_sources", "汇总来源", "finalize"),
            ),
            metadata={"workflow_id": "workflow.general.main_conversation"},
        ),
        TaskTemplate(
            template_id="template.capability.builtin_tool_lane",
            title="内置工具直达通道",
            description="用于文件读取、路径搜索、实时工具等明确能力的单步执行。",
            task_family="capability",
            task_mode="capability_execution",
            output_schema={
                "final_answer": {"type": "string", "required": True},
                "task_summary_refs": {"type": "array", "required": False},
            },
            required_operations=("op.model_response",),
            optional_operations=(
                "op.read_file",
                "op.list_dir",
                "op.stat_path",
                "op.path_exists",
                "op.glob_paths",
                "op.search_files",
                "op.search_text",
                "op.web_search",
                "op.fetch_url",
            ),
            step_blueprints=(
                _step("execute_capability", "执行已授权能力", "execute"),
                _step("finalize_tool_answer", "输出能力结果", "finalize"),
            ),
            metadata={"workflow_id": "workflow.general.main_conversation"},
        ),
        TaskTemplate(
            template_id="template.bundle.multi_capability",
            title="多能力组合任务",
            description="将多个已绑定子任务按顺序执行，并汇总为主回答。",
            task_family="bundle",
            task_mode="capability_execution",
            output_schema={
                "final_answer": {"type": "string", "required": True},
                "bundle_result_refs": {"type": "array", "required": False},
            },
            required_operations=("op.model_response",),
            step_blueprints=(
                _step("plan_bundle", "整理组合任务", "understand"),
                _step("execute_bundle_items", "执行组合项", "execute"),
                _step("finalize_bundle", "汇总组合结果", "finalize"),
            ),
            metadata={"workflow_id": "workflow.general.main_conversation"},
        ),
        TaskTemplate(
            template_id="template.dev.workspace_patch",
            title="工作区受限补丁",
            description="读取工作区、实施受限补丁并汇报验证状态。",
            task_family="development",
            task_mode="bounded_patch",
            output_schema={
                "final_answer": {"type": "string", "required": True},
                "artifact_refs": {"type": "array", "required": False},
            },
            required_operations=("op.model_response", "op.read_file", "op.search_text", "op.edit_file"),
            optional_operations=("op.search_files", "op.git_diff"),
            step_blueprints=(
                _step("scope_patch", "锁定补丁范围", "understand"),
                _step("inspect_code", "阅读相关代码", "analyze", required_operations=("op.read_file", "op.search_text")),
                _step("apply_patch", "实施受限补丁", "write", required_operations=("op.edit_file",)),
                _step("verify_patch", "验证变更", "verify"),
                _step("finalize_patch", "汇报补丁结果", "finalize"),
            ),
            safety_policy={
                "safety_class": "S1_bounded_patch",
                "write_mode": "scoped_patch",
                "forbidden_paths": [".env", ".env.local", ".git", "node_modules"],
            },
            metadata={"workflow_id": "workflow.dev.bounded_patch", "default_artifact_name": ""},
        ),
        TaskTemplate(
            template_id="template.dev.light_web_game",
            title="轻量网页小游戏",
            description="生成一个可运行、可验证的轻量网页小游戏产物。",
            task_family="development",
            task_mode="light_web_game",
            output_schema={
                "final_answer": {"type": "string", "required": True},
                "artifact_refs": {"type": "array", "required": False},
            },
            required_operations=("op.model_response", "op.write_file", "op.edit_file"),
            optional_operations=("op.read_file", "op.search_files"),
            step_blueprints=(
                _step("scope_game", "收束玩法目标", "understand"),
                _step("design_game", "设计状态与渲染结构", "analyze"),
                _step("write_game", "写入游戏产物", "write", required_operations=("op.write_file",)),
                _step("verify_game", "验证可运行性", "verify"),
                _step("finalize_game", "输出产物说明", "finalize"),
            ),
            safety_policy={
                "safety_class": "S1_bounded_artifact_write",
                "write_mode": "bounded_create",
                "default_write_roots": ["frontend/public/games", "docs/系统规划/任务系统实测记录/artifacts"],
                "forbidden_paths": [".env", ".env.local", ".git", "node_modules"],
            },
            metadata={
                "workflow_id": "workflow.dev.light_web_game",
                "default_artifact_name": "game.html",
                "default_write_roots": ["frontend/public/games", "docs/系统规划/任务系统实测记录/artifacts"],
            },
        ),
        TaskTemplate(
            template_id="template.dev.arcade_game_bundle",
            title="复合网页小游戏包",
            description="生成多文件网页小游戏包，并明确入口文件和资源关系。",
            task_family="development",
            task_mode="arcade_game_bundle",
            output_schema={
                "final_answer": {"type": "string", "required": True},
                "artifact_refs": {"type": "array", "required": False},
            },
            required_operations=("op.model_response", "op.write_file", "op.edit_file"),
            optional_operations=("op.read_file", "op.search_files"),
            step_blueprints=(
                _step("scope_bundle", "锁定目标目录", "understand"),
                _step("design_bundle", "设计文件结构", "analyze"),
                _step("write_bundle", "写入游戏包", "write", required_operations=("op.write_file",)),
                _step("verify_bundle", "验证入口关系", "verify"),
                _step("finalize_bundle_delivery", "输出交付结果", "finalize"),
            ),
            safety_policy={
                "safety_class": "S1_bounded_artifact_write",
                "write_mode": "bounded_create",
                "default_write_roots": ["frontend/public/games", "docs/系统规划/任务系统实测记录/artifacts"],
                "forbidden_paths": [".env", ".env.local", ".git", "node_modules"],
            },
            metadata={"workflow_id": "workflow.dev.arcade_game_bundle", "default_artifact_name": "index.html"},
        ),
        TaskTemplate(
            template_id="template.health.issue_triage",
            title="健康问题分诊",
            description="读取健康问题和追踪引用，输出归属与分诊建议。",
            task_family="health",
            task_mode="issue_triage",
            default_agent_id="agent:3",
            allowed_agent_ids=("agent:3",),
            output_schema={"triage_result": {"type": "object", "required": True}},
            required_operations=("op.model_response", "op.read_file", "op.search_text"),
            step_blueprints=(
                _step("collect_health_refs", "收集健康证据", "analyze", required_operations=("op.read_file",)),
                _step("finalize_triage", "输出分诊结论", "finalize"),
            ),
            metadata={"workflow_id": "workflow.health.issue_triage"},
        ),
        TaskTemplate(
            template_id="template.health.trace_analysis",
            title="健康链路分析",
            description="读取健康问题与运行链路证据，定位问题节点并给出修复范围建议。",
            task_family="health",
            task_mode="trace_analysis",
            default_agent_id="agent:3",
            allowed_agent_ids=("agent:3",),
            output_schema={"trace_analysis": {"type": "object", "required": True}},
            required_operations=("op.model_response", "op.read_file", "op.search_text"),
            step_blueprints=(
                _step("read_health_trace", "读取健康链路", "analyze", required_operations=("op.read_file",)),
                _step("locate_problem_node", "定位问题节点", "analyze"),
                _step("finalize_trace_analysis", "输出链路分析", "finalize"),
            ),
            metadata={"workflow_id": "workflow.health.trace_analysis"},
        ),
        TaskTemplate(
            template_id="template.health.case_draft",
            title="健康用例草案",
            description="围绕健康问题提取复现触发条件并生成验证用例草案。",
            task_family="health",
            task_mode="case_draft",
            default_agent_id="agent:3",
            allowed_agent_ids=("agent:3",),
            output_schema={"case_draft": {"type": "object", "required": True}},
            required_operations=("op.model_response", "op.read_file", "op.search_text"),
            step_blueprints=(
                _step("extract_health_trigger", "提取复现触发条件", "analyze", required_operations=("op.read_file",)),
                _step("draft_health_assertions", "生成断言草案", "analyze"),
                _step("finalize_case_draft", "输出用例草案", "finalize"),
            ),
            metadata={"workflow_id": "workflow.health.case_draft"},
        ),
        TaskTemplate(
            template_id="template.health.fix_verification",
            title="健康修复验证",
            description="比较修复前后证据，判断问题是否消失并输出验证建议。",
            task_family="health",
            task_mode="fix_verification",
            default_agent_id="agent:3",
            allowed_agent_ids=("agent:3",),
            output_schema={"fix_verification": {"type": "object", "required": True}},
            required_operations=("op.model_response", "op.read_file", "op.search_text"),
            step_blueprints=(
                _step("compare_before_after_trace", "比较修复前后链路", "analyze", required_operations=("op.read_file",)),
                _step("verify_health_fix", "验证问题是否消失", "analyze"),
                _step("finalize_fix_verification", "输出验证结论", "finalize"),
            ),
            metadata={"workflow_id": "workflow.health.fix_verification"},
        ),
    )


def _step(
    step_id: str,
    title: str,
    step_kind: str,
    *,
    executor_type: str = "model",
    required_operations: tuple[str, ...] = (),
    optional_operations: tuple[str, ...] = (),
    input_refs: tuple[str, ...] = (),
    output_contract_id: str = "",
) -> TaskStepBlueprint:
    return TaskStepBlueprint(
        step_id=step_id,
        title=title,
        step_kind=step_kind,
        executor_type=executor_type,
        required_operations=required_operations,
        optional_operations=optional_operations,
        input_refs=input_refs,
        output_contract_id=output_contract_id,
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
        elif (
            "flow.health.fix_verification" in lowered_goal
            or "task.health.fix_verification" in lowered_goal
            or "workflow.health.fix_verification" in lowered_goal
        ):
            template_id = "template.health.fix_verification"
            match_source = "capability_contract"
            match_reasons.append("health_fix_verification_goal")
        elif (
            "flow.health.case_draft" in lowered_goal
            or "task.health.case_draft" in lowered_goal
            or "workflow.health.case_draft" in lowered_goal
        ):
            template_id = "template.health.case_draft"
            match_source = "capability_contract"
            match_reasons.append("health_case_draft_goal")
        elif (
            "flow.health.trace_analysis" in lowered_goal
            or "task.health.trace_analysis" in lowered_goal
            or "workflow.health.trace_analysis" in lowered_goal
        ):
            template_id = "template.health.trace_analysis"
            match_source = "capability_contract"
            match_reasons.append("health_trace_analysis_goal")
        elif "flow.health.issue_triage" in lowered_goal or "health_issue" in capability_requests:
            template_id = "template.health.issue_triage"
            match_source = "capability_contract"
            match_reasons.append("health_issue_capability")
        elif execution_posture == "direct_rag" or route_hint == "rag" or preferred_skill == "rag-skill":
            template_id = _RAG_TEMPLATE_ID
            match_source = "capability_contract"
            match_reasons.append("rag_execution_posture")
        elif route_hint == "pdf" or preferred_skill == "pdf-analysis":
            template_id = _PDF_TEMPLATE_ID
            match_source = "capability_contract"
            match_reasons.append("pdf_mcp_route")
        elif route_hint == "structured_data" or preferred_skill == "structured-data-analysis":
            template_id = _STRUCTURED_DATA_TEMPLATE_ID
            match_source = "capability_contract"
            match_reasons.append("structured_data_mcp_route")
        elif route_hint == "search" or "task.information_search" in definition_ids:
            template_id = "template.search.information_search"
            match_source = "capability_contract"
            match_reasons.append("search_route_hint")
        elif route_hint == "realtime_network":
            template_id = "template.search.information_search"
            match_source = "capability_contract"
            match_reasons.append("realtime_network_route")
        elif route_hint in {"workspace_read", "workspace_path_search", "workspace_text_search"}:
            template_id = "template.capability.builtin_tool_lane"
            match_source = "capability_contract"
            match_reasons.append("builtin_tool_route_family")
        elif execution_posture == "builtin_tool_lane" or route_hint == "tool":
            template_id = "template.capability.builtin_tool_lane"
            match_source = "capability_contract"
            match_reasons.append("legacy_builtin_tool_lane_route")
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
                template_id = _PDF_TEMPLATE_ID
                match_source = "binding_contract"
                match_reasons.append("pdf_binding")
            elif (
                modality == "table"
                or source_kind == "dataset"
                or explicit_inputs.get("explicit_dataset_path")
                or explicit_inputs.get("bound_dataset_path")
            ):
                template_id = _STRUCTURED_DATA_TEMPLATE_ID
                match_source = "binding_contract"
                match_reasons.append("dataset_binding")

        if not template_id:
            template_id = "template.general.main_conversation"
            match_reasons.append("fallback_general_response")

        template_id = _select_existing_template_id(template_id, templates)
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


def _select_existing_template_id(template_id: str, templates: dict[str, TaskTemplate]) -> str:
    target = str(template_id or "").strip()
    if target in templates:
        return target
    aliases = {
        "template.chat.general_response": "template.general.main_conversation",
        "template.general.response": "template.general.main_conversation",
        "template.local.workspace_read": "template.capability.builtin_tool_lane",
    }
    alias_target = aliases.get(target, "")
    if alias_target and alias_target in templates:
        return alias_target
    fallback = "template.general.main_conversation"
    if fallback in templates:
        return fallback
    if templates:
        return next(iter(templates))
    raise ValueError("no task templates registered")


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
        candidates.append(_PDF_TEMPLATE_ID)
    if explicit_inputs.get("explicit_dataset_path") or explicit_inputs.get("bound_dataset_path"):
        candidates.append(_STRUCTURED_DATA_TEMPLATE_ID)
    binding_file_kinds = {
        str(item.get("file_kind") or "").strip()
        for item in resolved_bindings
        if str(item.get("binding_kind") or "").strip() == "source_file"
    }
    if "pdf" in binding_file_kinds:
        pdf_unit = get_local_mcp_unit_for_source_kind("pdf")
        if pdf_unit is not None and pdf_unit.template_ids:
            candidates.append(str(pdf_unit.template_ids[0]))
    if "dataset" in binding_file_kinds:
        dataset_unit = get_local_mcp_unit_for_source_kind("dataset")
        if dataset_unit is not None and dataset_unit.template_ids:
            candidates.append(str(dataset_unit.template_ids[0]))
    for request in capability_requests:
        if request in {"document_analysis", "pdf"}:
            candidates.append(_PDF_TEMPLATE_ID)
        if request in {"dataset_analysis", "structured_data"}:
            candidates.append(_STRUCTURED_DATA_TEMPLATE_ID)
        if request in {"weather", "gold_price", "latest_information"}:
            candidates.append("template.search.information_search")
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
