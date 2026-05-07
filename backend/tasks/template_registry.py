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

_LONGFORM_WRITE_FIRST_METADATA = {
    "runtime_tool_policy": "write_first_artifact",
    "artifact_generation_mode": "direct_write",
    "read_before_write": "discouraged_unless_explicit_input_ref_required",
}

_PDF_TEMPLATE_ID = get_local_mcp_primary_template("pdf") or "template.pdf.document_analysis"
_STRUCTURED_DATA_TEMPLATE_ID = get_local_mcp_primary_template("structured_data") or "template.data.structured_analysis"
_RAG_TEMPLATE_ID = get_local_mcp_primary_template("retrieval") or "template.rag.knowledge_answer"


def default_task_templates() -> tuple[TaskTemplate, ...]:
    return ()

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
