from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from task_system.tasks.definitions import TaskDefinition
from task_system.contracts.match_contracts import TaskIntentContract


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
    current_turn = dict(current_turn_context or {})
    definition_ids = {
        str(item.definition_id or "").strip()
        for item in list(definitions or [])
        if isinstance(item, TaskDefinition)
    }
    semantic_contract = dict(task_intent_contract.task_requirement_contract or {})
    execution_obligation = dict(task_intent_contract.execution_obligation or semantic_contract.get("execution_obligation") or {})
    mode_policy = dict(task_intent_contract.mode_policy or {})
    agent_turn_action_request = dict(current_turn.get("agent_turn_action_request") or {})
    task_contract_seed = dict(current_turn.get("task_contract_seed") or {})
    interaction_mode = str(mode_policy.get("interaction_mode") or current_turn.get("interaction_mode") or "").strip()
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    source_kind = _source_kind_from_contract(
        task_contract_seed=task_contract_seed,
        semantic_contract=semantic_contract,
    )
    diagnostics = _shape_diagnostics(
        definition_ids,
        source_kind,
        current_turn,
        agent_turn_action_request=agent_turn_action_request,
        task_contract_seed=task_contract_seed,
    )
    reasons: list[str] = []

    if _explicit_task_runtime(current_turn):
        reasons.append("explicit_task_runtime")
        return ExecutionShape(
            recipe_id="runtime.recipe.task_graph_node",
            execution_kind="task_runtime",
            source_kind="task_system",
            finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
            resolution_source="task_runtime_context",
            resolution_reasons=tuple(reasons),
            diagnostics={
                **diagnostics,
                "registered_task_present": bool(registered_task),
            },
        )

    if str(agent_turn_action_request.get("action_type") or "") == "block":
        reasons.append("agent_action:block")
        return ExecutionShape(
            recipe_id="runtime.recipe.conversation",
            execution_kind="blocked",
            source_kind="conversation",
            finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
            resolution_source="agent_turn_action_request",
            resolution_reasons=tuple(reasons),
            diagnostics=diagnostics,
        )

    if interaction_mode in {"role_mode", "standard_mode", "professional_mode"}:
        reasons.append(f"interaction_mode:{interaction_mode}")
        return _agent_mode_shape(
            mode_policy=mode_policy,
            semantic_contract=semantic_contract,
            execution_obligation=execution_obligation,
            interaction_mode=interaction_mode,
            source_kind=source_kind or "runtime_task",
            definition_ids=definition_ids,
            current_turn=current_turn,
            task_goal_type=task_goal_type,
            reasons=reasons,
            agent_turn_action_request=agent_turn_action_request,
            task_contract_seed=task_contract_seed,
        )

    if task_intent_contract.execution_intent == "bundle_task":
        reasons.append("bundle_execution_mode")
        return ExecutionShape(
            recipe_id="runtime.recipe.bundle",
            execution_kind="bundle",
            source_kind="mixed_sources",
            finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
            resolution_source="task_contract",
            resolution_reasons=tuple(reasons),
            diagnostics=diagnostics,
        )

    if task_goal_type == "external_research":
        reasons.append("task_goal_type:external_research")
        return ExecutionShape(
            recipe_id="runtime.recipe.information_search",
            execution_kind="search",
            source_kind="external_web",
            finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
            resolution_source="task_contract",
            resolution_reasons=tuple(reasons),
            diagnostics=diagnostics,
        )

    if task_goal_type in {"code_fix_execution", "artifact_delivery", "frontend_app_delivery", "game_vertical_slice_delivery", "implementation", "verification"}:
        reasons.append(f"task_goal_type:{task_goal_type}")
        return _shape_from_recipe_id(
            "runtime.recipe.workspace_patch",
            source_kind=source_kind or "workspace",
            resolution_source="task_contract",
            reasons=reasons,
            diagnostics=diagnostics,
        )

    if task_goal_type in {"inspection", "code_review", "pdf_analysis"} or source_kind in {"pdf", "dataset", "knowledge", "workspace"}:
        reasons.append(f"task_contract_source:{source_kind or task_goal_type}")
        if source_kind == "pdf":
            return _shape_from_source_kind(
                source_kind,
                recipe_id="runtime.recipe.pdf_analysis",
                execution_kind="capability",
                resolution_source="task_contract",
                reasons=reasons,
                diagnostics=diagnostics,
            )
        if source_kind == "dataset":
            return _shape_from_source_kind(
                source_kind,
                recipe_id="runtime.recipe.structured_data_analysis",
                execution_kind="capability",
                resolution_source="task_contract",
                reasons=reasons,
                diagnostics=diagnostics,
            )
        if source_kind in {"knowledge", "knowledge_base", "retrieval"}:
            return _shape_from_source_kind(
                "knowledge",
                recipe_id="runtime.recipe.knowledge_retrieval",
                execution_kind="retrieval",
                resolution_source="task_contract",
                reasons=reasons,
                diagnostics=diagnostics,
            )
        return ExecutionShape(
            recipe_id="runtime.recipe.capability",
            execution_kind="capability",
            source_kind=source_kind or "workspace",
            finalization_policy={"requires_model_finalize": True, "tool_observation_can_finalize": False},
            resolution_source="task_contract",
            resolution_reasons=tuple(reasons),
            diagnostics=diagnostics,
        )

    reasons.append("default_task_contract")
    return _shape_from_recipe_id(
        "runtime.recipe.capability",
        source_kind=source_kind or "runtime_task",
        resolution_source="task_contract",
        reasons=reasons,
        diagnostics=diagnostics,
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


def _agent_mode_shape(
    *,
    mode_policy: dict[str, Any],
    semantic_contract: dict[str, Any],
    execution_obligation: dict[str, Any],
    interaction_mode: str,
    source_kind: str,
    definition_ids: set[str],
    current_turn: dict[str, Any],
    task_goal_type: str,
    reasons: list[str],
    agent_turn_action_request: dict[str, Any],
    task_contract_seed: dict[str, Any],
) -> ExecutionShape:
    return ExecutionShape(
        recipe_id=str(mode_policy.get("recipe_id") or _default_agent_mode_recipe_id(interaction_mode)),
        execution_kind=interaction_mode,
        source_kind=source_kind,
        finalization_policy={
            "requires_model_finalize": True,
            "tool_observation_can_finalize": False,
            "requires_verification_gate": bool(
                dict(mode_policy.get("verification_policy") or {}).get("required") is not False
            ),
        },
        resolution_source="task_contract_policy",
        resolution_reasons=tuple(reasons),
        diagnostics={
            **_shape_diagnostics(
                definition_ids,
                source_kind,
                current_turn,
                agent_turn_action_request=agent_turn_action_request,
                task_contract_seed=task_contract_seed,
            ),
            "interaction_mode": interaction_mode,
            "runtime_lane": str(mode_policy.get("runtime_lane") or ""),
            "projection_strength": str(mode_policy.get("projection_strength") or ""),
            "semantic_task_type": task_goal_type,
            "professional_profile_id": str(semantic_contract.get("professional_profile_id") or ""),
            "mode_policy": mode_policy,
            "task_requirement_contract": semantic_contract,
            "execution_obligation": execution_obligation,
        },
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


def _default_agent_mode_recipe_id(interaction_mode: str) -> str:
    return {
        "role_mode": "runtime.recipe.role_interaction",
        "standard_mode": "runtime.recipe.standard_task",
        "professional_mode": "runtime.recipe.professional_task",
    }.get(str(interaction_mode or "").strip(), "runtime.recipe.standard_task")


def _shape_diagnostics(
    definition_ids: set[str],
    source_kind: str,
    current_turn: dict[str, Any],
    *,
    agent_turn_action_request: dict[str, Any],
    task_contract_seed: dict[str, Any],
) -> dict[str, Any]:
    return {
        "definition_ids": sorted(definition_ids),
        "source_kind": source_kind,
        "current_turn_execution_mode": str(current_turn.get("execution_mode") or ""),
        "agent_turn_action_request": dict(agent_turn_action_request or {}),
        "task_contract_seed": dict(task_contract_seed or {}),
    }


def _explicit_task_runtime(current_turn: dict[str, Any]) -> bool:
    if str(current_turn.get("continuation_stage_id") or "").strip():
        return True
    if str(current_turn.get("stage_execution_request_ref") or "").strip():
        return True
    if str(current_turn.get("coordination_run_id") or "").strip():
        return True
    if dict(current_turn.get("stage_execution_request") or {}):
        return True
    if dict(current_turn.get("node_work_order") or {}):
        return True
    return False


def _source_kind_from_contract(*, task_contract_seed: dict[str, Any], semantic_contract: dict[str, Any]) -> str:
    domain = str(semantic_contract.get("domain") or semantic_contract.get("task_domain") or "").strip()
    task_goal_type = str(task_contract_seed.get("task_goal_type") or semantic_contract.get("task_goal_type") or "").strip()
    resource_contract = dict(task_contract_seed.get("resource_contract") or {})
    targets = [
        str(item or "").strip().lower()
        for key in ("required_read_files", "required_read_dirs", "required_write_files", "required_write_dirs")
        for item in list(resource_contract.get(key) or [])
        if str(item or "").strip()
    ]
    if task_goal_type == "external_research":
        return "external_web"
    if any(target.endswith(".pdf") for target in targets):
        return "pdf"
    if any(target.endswith((".csv", ".tsv", ".xlsx", ".xls", ".parquet")) for target in targets):
        return "dataset"
    if any(target.startswith(("knowledge/", "knowledge\\", "kb:", "knowledge:")) for target in targets):
        return "knowledge"
    if targets or task_goal_type in {"code_fix_execution", "artifact_delivery", "frontend_app_delivery", "game_vertical_slice_delivery", "implementation", "verification", "inspection", "code_review"}:
        return "workspace"
    return domain or "conversation"




