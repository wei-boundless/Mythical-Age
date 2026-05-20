from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from understanding.capability_resolution_view import capability_resolution_view

from .definitions import TaskDefinition
from .match_contracts import TaskIntentContract


@dataclass(frozen=True, slots=True)
class ExecutionShape:
    recipe_id: str
    execution_kind: str
    source_kind: str
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    finalization_policy: dict[str, Any] = field(default_factory=dict)
    operation_profile: dict[str, Any] = field(default_factory=dict)
    resolution_source: str = ""
    resolution_reasons: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resolution_reasons"] = list(self.resolution_reasons)
        return payload


def resolve_execution_shape(
    *,
    task_intent_contract: TaskIntentContract,
    query_understanding: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    definitions: list[TaskDefinition] | None = None,
    registered_task: dict[str, Any] | None = None,
) -> ExecutionShape:
    understanding = dict(query_understanding or {})
    current_turn = dict(current_turn_context or {})
    explicit_inputs = dict(task_intent_contract.explicit_inputs or {})
    definition_ids = {
        str(item.definition_id or "").strip()
        for item in list(definitions or [])
        if isinstance(item, TaskDefinition)
    }
    resolution = capability_resolution_view(understanding)
    effective_route = str(resolution.route or "").strip()
    execution_posture = str(resolution.execution_posture or "").strip()
    effective_skill = str(resolution.preferred_skill or "").strip()
    source_kind = str(
        understanding.get("source_kind")
        or dict((registered_task or {}).get("metadata") or {}).get("source_kind")
        or ""
    ).strip()
    modality = str(understanding.get("modality") or "").strip()
    lowered_goal = str(task_intent_contract.user_goal or "").lower()
    capability_requests = set(task_intent_contract.capability_requests)
    diagnostics_payload = dict(task_intent_contract.diagnostics or {})
    intent_target_domain = str(
        diagnostics_payload.get("intent_target_domain_hint")
        or dict(current_turn.get("intent_decision") or {}).get("target_domain_hint")
        or dict(current_turn.get("runtime_assembly_hint") or {}).get("target_domain_hint")
        or ""
    ).strip()
    intent_execution_strategy = str(
        diagnostics_payload.get("intent_execution_strategy")
        or dict(current_turn.get("intent_decision") or {}).get("execution_strategy")
        or dict(current_turn.get("runtime_assembly_hint") or {}).get("execution_strategy")
        or ""
    ).strip()
    structural_signals = dict(understanding.get("structural_signals") or {})
    followup_target_kind = str(
        diagnostics_payload.get("followup_target_kind")
        or explicit_inputs.get("followup_target_kind")
        or structural_signals.get("followup_target_kind")
        or dict(current_turn.get("continuation_decision") or {}).get("followup_target_kind")
        or ""
    ).strip()
    has_explicit_pdf = bool(str(explicit_inputs.get("explicit_pdf_path") or "").strip())
    has_explicit_dataset = bool(str(explicit_inputs.get("explicit_dataset_path") or "").strip())
    has_realtime_capability = (
        effective_route in {"search", "realtime_network"}
        or "task.information_search" in definition_ids
        or bool(capability_requests & {"weather", "gold_price", "latest_information", "realtime_network"})
    )
    has_pdf_route = (
        effective_route == "pdf"
        or effective_skill == "pdf-analysis"
        or modality == "pdf"
        or has_explicit_pdf
        or followup_target_kind == "active_pdf"
        or (
            intent_execution_strategy in {"specialist_handoff", "specialist_subagent_long_run"}
            and intent_target_domain == "pdf"
        )
    )
    has_dataset_route = (
        effective_route == "structured_data"
        or effective_skill == "structured-data-analysis"
        or source_kind == "dataset"
        or has_explicit_dataset
        or followup_target_kind == "active_dataset"
        or (
            intent_execution_strategy in {"specialist_handoff", "specialist_subagent_long_run"}
            and intent_target_domain == "dataset"
        )
    )
    reasons: list[str] = []

    if registered_task:
        if _explicit_task_runtime(current_turn, understanding):
            reasons.append("explicit_task_runtime")
            return ExecutionShape(
                recipe_id="runtime.recipe.task_graph_node",
                execution_kind="task_runtime",
                source_kind=source_kind or "task_system",
                finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
                resolution_source="registered_task",
                resolution_reasons=tuple(reasons),
                diagnostics=_shape_diagnostics(
                    definition_ids,
                    effective_route,
                    execution_posture,
                    effective_skill,
                    source_kind or "task_system",
                    modality,
                    current_turn,
                ),
            )
        registered_task_mode = str((registered_task or {}).get("task_mode") or "").strip()
        if registered_task_mode in {"bounded_patch", "workspace_patch", "light_web_game", "arcade_game_bundle"}:
            reasons.append("registered_task_mode")
            recipe_id = "runtime.recipe.light_web_game" if registered_task_mode == "light_web_game" else "runtime.recipe.workspace_patch"
            return _shape_from_recipe_id(
                recipe_id,
                source_kind=source_kind or "workspace",
                resolution_source="registered_task",
                reasons=reasons,
                diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, source_kind, modality, current_turn),
            )

    if intent_execution_strategy == "autonomous_task_run":
        reasons.append("intent_autonomous_task_run")
        if (
            has_realtime_capability
            or task_intent_contract.execution_intent == "bundle_task"
            or task_intent_contract.execution_intent == "subset_followup"
            or followup_target_kind == "active_subset"
            or has_explicit_dataset
            or has_explicit_pdf
            or execution_posture == "direct_rag"
            or effective_route == "rag"
            or effective_skill == "rag-skill"
            or has_pdf_route
            or has_dataset_route
        ):
            reasons.append("autonomous_task_run_owns_material_routes")
        return ExecutionShape(
            recipe_id="runtime.recipe.autonomous_task_run",
            execution_kind="autonomous_task_run",
            source_kind=source_kind or "runtime_task",
            finalization_policy={
                "requires_model_finalize": True,
                "tool_observation_can_finalize": False,
                "requires_verification_gate": True,
            },
            resolution_source="intent_runtime_assembly",
            resolution_reasons=tuple(reasons),
            diagnostics={
                **_shape_diagnostics(
                    definition_ids,
                    effective_route,
                    execution_posture,
                    effective_skill,
                    source_kind or "runtime_task",
                    modality,
                    current_turn,
                ),
                "intent_execution_strategy": intent_execution_strategy,
                "autonomy_mode": _autonomy_mode_from_turn(current_turn),
            },
        )
    if task_intent_contract.execution_intent == "bundle_task":
        reasons.append("bundle_execution_mode")
        return ExecutionShape(
            recipe_id="runtime.recipe.bundle",
            execution_kind="bundle",
            source_kind=source_kind or "mixed_sources",
            finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
            resolution_source="binding_contract",
            resolution_reasons=tuple(reasons),
            diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, source_kind, modality, current_turn),
        )
    if has_realtime_capability:
        reasons.append("search_route")
        return ExecutionShape(
            recipe_id="runtime.recipe.information_search",
            execution_kind="search",
            source_kind=source_kind or "external_web",
            finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
            resolution_source="capability_contract",
            resolution_reasons=tuple(reasons),
            diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, source_kind or "external_web", modality, current_turn),
        )
    if task_intent_contract.execution_intent == "subset_followup" or followup_target_kind == "active_subset":
        reasons.append("subset_followup")
        if (
            source_kind in {"document", "pdf"}
            or effective_route == "pdf"
            or effective_skill == "pdf-analysis"
            or "document_analysis" in capability_requests
        ) and not has_explicit_dataset:
            return _shape_from_source_kind("pdf", recipe_id="runtime.recipe.pdf_analysis", execution_kind="document_analysis", resolution_source="binding_contract", reasons=reasons, diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, "pdf", modality, current_turn))
        return _shape_from_source_kind("dataset", recipe_id="runtime.recipe.structured_data_analysis", execution_kind="dataset_analysis", resolution_source="binding_contract", reasons=reasons, diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, "dataset", modality, current_turn))
    if has_explicit_dataset:
        reasons.append("explicit_dataset_route")
        return _shape_from_source_kind("dataset", recipe_id="runtime.recipe.structured_data_analysis", execution_kind="dataset_analysis", resolution_source="capability_contract", reasons=reasons, diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, "dataset", modality, current_turn))
    if has_explicit_pdf:
        reasons.append("explicit_pdf_route")
        return _shape_from_source_kind("pdf", recipe_id="runtime.recipe.pdf_analysis", execution_kind="document_analysis", resolution_source="capability_contract", reasons=reasons, diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, "pdf", modality, current_turn))
    if execution_posture == "direct_rag" or effective_route == "rag" or effective_skill == "rag-skill":
        reasons.append("rag_execution_posture")
        return _shape_from_source_kind("knowledge", recipe_id="runtime.recipe.knowledge_retrieval", execution_kind="retrieval", resolution_source="capability_contract", reasons=reasons, diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, source_kind or "knowledge", modality, current_turn))
    if has_pdf_route:
        reasons.append("pdf_route")
        return _shape_from_source_kind("pdf", recipe_id="runtime.recipe.pdf_analysis", execution_kind="document_analysis", resolution_source="capability_contract", reasons=reasons, diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, "pdf", modality, current_turn))
    if has_dataset_route:
        reasons.append("dataset_route")
        return _shape_from_source_kind("dataset", recipe_id="runtime.recipe.structured_data_analysis", execution_kind="dataset_analysis", resolution_source="capability_contract", reasons=reasons, diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, "dataset", modality, current_turn))
    if execution_posture == "direct_memory" or effective_route == "memory":
        reasons.append("memory_route")
        return ExecutionShape(
            recipe_id="runtime.recipe.memory_recall",
            execution_kind="memory_recall",
            source_kind=source_kind or "memory",
            finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
            resolution_source="capability_contract",
            resolution_reasons=tuple(reasons),
            diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, source_kind or "memory", modality, current_turn),
        )
    if effective_route in {
        "workspace_read",
        "workspace_path_search",
        "workspace_text_search",
        "workspace_write",
        "workspace_edit",
    } or execution_posture == "builtin_tool_lane" or effective_route == "tool":
        reasons.append("builtin_tool_route")
        if effective_route in {"workspace_write", "workspace_edit"}:
            return _shape_from_recipe_id(
                "runtime.recipe.workspace_patch",
                source_kind=source_kind or "workspace",
                resolution_source="capability_contract",
                reasons=reasons,
                diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, source_kind or "workspace", modality, current_turn),
            )
        return ExecutionShape(
            recipe_id="runtime.recipe.capability",
            execution_kind="capability",
            source_kind=source_kind or "workspace",
            finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
            resolution_source="capability_contract",
            resolution_reasons=tuple(reasons),
            diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, source_kind or "workspace", modality, current_turn),
        )
    if _looks_like_light_web_game(lowered_goal):
        reasons.append("light_web_game_phrase")
        return _shape_from_recipe_id(
            "runtime.recipe.light_web_game",
            source_kind=source_kind or "workspace",
            resolution_source="heuristic_fallback",
            reasons=reasons,
            diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, source_kind or "workspace", modality, current_turn),
        )
    if source_kind == "workspace" or "task.task_execution" in definition_ids or "task.local_material_read" in definition_ids:
        reasons.append("workspace_source_kind")
        return _shape_from_recipe_id(
            "runtime.recipe.workspace_patch",
            source_kind="workspace",
            resolution_source="binding_contract",
            reasons=reasons,
            diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, "workspace", modality, current_turn),
        )
    reasons.append("fallback_general_response")
    return ExecutionShape(
        recipe_id="runtime.recipe.conversation",
        execution_kind="conversation",
        source_kind=source_kind or "knowledge_base",
        finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
        resolution_source="heuristic_fallback",
        resolution_reasons=tuple(reasons),
        diagnostics=_shape_diagnostics(definition_ids, effective_route, execution_posture, effective_skill, source_kind or "knowledge_base", modality, current_turn),
    )


def _shape_from_source_kind(
    source_kind: str,
    *,
    recipe_id: str,
    execution_kind: str,
    resolution_source: str,
    reasons: list[str],
    diagnostics: dict[str, Any],
) -> ExecutionShape:
    return ExecutionShape(
        recipe_id=recipe_id,
        execution_kind=execution_kind,
        source_kind=source_kind,
        finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
        resolution_source=resolution_source,
        resolution_reasons=tuple(reasons),
        diagnostics=diagnostics,
    )


def _shape_from_recipe_id(
    recipe_id: str,
    *,
    source_kind: str,
    resolution_source: str,
    reasons: list[str],
    diagnostics: dict[str, Any],
) -> ExecutionShape:
    execution_kind = "workspace_patch" if "workspace_patch" in recipe_id else "development" if "light_web_game" in recipe_id else "conversation"
    artifact_policy = {"requires_write_file": recipe_id in {"runtime.recipe.light_web_game"}}
    return ExecutionShape(
        recipe_id=recipe_id,
        execution_kind=execution_kind,
        source_kind=source_kind,
        artifact_policy=artifact_policy,
        finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
        resolution_source=resolution_source,
        resolution_reasons=tuple(reasons),
        diagnostics=diagnostics,
    )


def _shape_diagnostics(
    definition_ids: set[str],
    effective_route: str,
    execution_posture: str,
    effective_skill: str,
    source_kind: str,
    modality: str,
    current_turn: dict[str, Any],
) -> dict[str, Any]:
    return {
        "definition_ids": sorted(definition_ids),
        "effective_route": effective_route,
        "execution_posture": execution_posture,
        "effective_skill": effective_skill,
        "source_kind": source_kind,
        "modality": modality,
        "current_turn_execution_mode": str(current_turn.get("execution_mode") or ""),
    }


def _autonomy_mode_from_turn(current_turn: dict[str, Any]) -> str:
    mode = str(
        current_turn.get("autonomy_mode")
        or dict(current_turn.get("runtime_assembly_hint") or {}).get("autonomy_mode")
        or dict(current_turn.get("intent_decision") or {}).get("autonomy_mode")
        or ""
    ).strip().lower()
    if mode in {"standard", "managed"}:
        return mode
    if mode == "simple":
        return "simple"
    return ""


def _explicit_task_runtime(current_turn: dict[str, Any], understanding: dict[str, Any]) -> bool:
    signals = dict(understanding.get("structural_signals") or {})
    if signals.get("understanding_aligned_to_explicit_task"):
        return True
    if str(current_turn.get("selected_task_id") or current_turn.get("task_id") or "").strip():
        if str(understanding.get("source_kind") or "").strip() == "task_system":
            return True
    if str(current_turn.get("continuation_stage_id") or "").strip():
        return True
    if dict(current_turn.get("stage_execution_request") or {}):
        return True
    return False


def _looks_like_light_web_game(text: str) -> bool:
    return any(token in text for token in ("贪吃蛇", "小游戏", "game", "snake", "html5 game", "web game"))
