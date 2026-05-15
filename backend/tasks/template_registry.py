from __future__ import annotations

from pathlib import Path
from typing import Any

from capability_system import build_default_operation_registry
from orchestration.agent_registry import AgentRegistry
from orchestration.agent_runtime_registry import AgentRuntimeRegistry

from .match_contracts import TaskIntentContract
from .step_models import TaskStepBlueprint
from .template_models import TaskTemplate, TaskValidationRule

_PDF_TEMPLATE_ID = "template.pdf.document_analysis"
_STRUCTURED_DATA_TEMPLATE_ID = "template.data.structured_analysis"
_RAG_TEMPLATE_ID = "template.rag.knowledge_answer"


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
            required_operations=("op.model_response",),
            step_blueprints=(
                _step("retrieve_evidence", "检索相关证据", "execute"),
                _step("synthesize_answer", "综合检索结果", "finalize"),
            ),
            metadata={
                "source_kind": "retrieval",
                "workflow_id": "workflow.general.main_conversation",
                "execution_strategy": "delegate_preferred",
                "delegate_target_agent_id": "agent:rag_analyst",
                "delegate_target_agent_category": "worker_sub_agent",
                "delegation_kind": "retrieval",
                "fallback_operation": "op.mcp_retrieval",
            },
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
            required_operations=("op.model_response",),
            step_blueprints=(
                _step("analyze_pdf", "分析 PDF", "analyze"),
                _step("finalize_pdf_answer", "输出文档回答", "finalize"),
            ),
            metadata={
                "source_kind": "pdf",
                "workflow_id": "workflow.general.main_conversation",
                "execution_strategy": "delegate_preferred",
                "delegate_target_agent_id": "agent:pdf_reader",
                "delegate_target_agent_category": "worker_sub_agent",
                "delegation_kind": "pdf",
                "fallback_operation": "op.mcp_pdf",
            },
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
            required_operations=("op.model_response",),
            step_blueprints=(
                _step("analyze_dataset", "分析数据集", "analyze"),
                _step("finalize_dataset_answer", "输出数据回答", "finalize"),
            ),
            metadata={
                "source_kind": "dataset",
                "workflow_id": "workflow.general.main_conversation",
                "execution_strategy": "delegate_preferred",
                "delegate_target_agent_id": "agent:table_analyst",
                "delegate_target_agent_category": "worker_sub_agent",
                "delegation_kind": "structured_data",
                "fallback_operation": "op.mcp_structured_data",
            },
        ),
        TaskTemplate(
            template_id="template.search.information_search",
            title="信息搜索",
            description="搜索外部或实时信息，并汇总可追踪结果。",
            task_family="search",
            task_mode="information_search",
            output_schema={"final_answer": {"type": "string", "required": True}},
            required_operations=("op.model_response",),
            step_blueprints=(
                _step("search_information", "搜索信息", "execute", required_operations=("op.web_search",)),
                _step("summarize_sources", "汇总来源", "finalize"),
            ),
            metadata={
                "workflow_id": "workflow.general.main_conversation",
                "execution_strategy": "delegate_preferred",
                "delegate_target_agent_id": "agent:web_researcher",
                "delegate_target_agent_category": "worker_sub_agent",
                "delegation_kind": "web_research",
                "fallback_operation": "op.web_search",
            },
        ),
        TaskTemplate(
            template_id="template.memory.recall_answer",
            title="记忆回忆回答",
            description="基于会话记忆与长期记忆上下文直接回答回忆类问题。",
            task_family="memory",
            task_mode="memory_recall",
            output_schema={"final_answer": {"type": "string", "required": True}},
            required_operations=("op.model_response", "op.memory_read"),
            step_blueprints=(
                _step("read_memory_context", "读取记忆上下文", "analyze", required_operations=("op.memory_read",)),
                _step("finalize_memory_answer", "输出记忆回答", "finalize"),
            ),
            metadata={
                "workflow_id": "workflow.general.main_conversation",
                "memory_answer": True,
                "final_answer_requirements": ("优先依据当前记忆上下文直接回答，不要把记忆问题退回到通用检索。",),
            },
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
            required_operations=("op.model_response", "op.read_file", "op.search_text", "op.write_file", "op.edit_file"),
            optional_operations=("op.search_files", "op.git_diff"),
            step_blueprints=(
                _step("scope_patch", "锁定补丁范围", "understand"),
                _step("inspect_code", "阅读相关代码", "analyze", required_operations=("op.read_file", "op.search_text")),
                _step("apply_patch", "实施受限补丁", "write", required_operations=("op.write_file", "op.edit_file")),
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
            query_understanding=understanding,
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
            diagnostics={
                "execution_mode": str(current_turn.get("execution_mode") or "single"),
                "bundle_item_count": len(bundle_items),
                "route_hint": str(understanding.get("route_hint") or ""),
                "preferred_skill": str(understanding.get("preferred_skill") or ""),
                "source_kind": str(understanding.get("source_kind") or ""),
                "modality": str(understanding.get("modality") or ""),
                "followup_target_kind": str(
                    dict(understanding.get("structural_signals") or {}).get("followup_target_kind")
                    or explicit_inputs.get("followup_target_kind")
                    or ""
                ),
            },
        )

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


def _execution_intent_from_context(
    *,
    current_turn_context: dict[str, Any],
    bundle_items: list[dict[str, Any]],
    query_understanding: dict[str, Any],
) -> str:
    execution_mode = str(current_turn_context.get("execution_mode") or "").strip()
    if execution_mode == "bundle" or len(bundle_items) > 1:
        return "bundle_task"
    structural_signals = dict(current_turn_context.get("structural_signals") or {})
    understanding_signals = dict(query_understanding.get("structural_signals") or {})
    explicit_inputs = dict(current_turn_context.get("explicit_inputs") or {})
    if (
        str(
            understanding_signals.get("followup_target_kind")
            or structural_signals.get("followup_target_kind")
            or explicit_inputs.get("followup_target_kind")
            or ""
        ).strip()
        == "bundle_ordinals"
    ):
        return "bundle_followup_item"
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
