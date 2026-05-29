from __future__ import annotations

from pathlib import Path
from typing import Any

from task_system.planning.execution_recipe_models import ExecutionRecipe
from task_system.planning.execution_shape_resolver import ExecutionShape
from task_system.planning.agent_plan_support import (
    AgentPlanRequired,
    build_agent_plan_draft,
    empty_agent_plan_draft,
    review_plan_coverage,
)
from task_system.tasks.step_models import TaskStepBlueprint


def build_execution_recipe(
    *,
    base_dir: Path,
    execution_shape: ExecutionShape,
) -> ExecutionRecipe:
    _ = base_dir
    profile = _recipe_profile(execution_shape)
    metadata = {
        **dict(profile.get("metadata") or {}),
        "execution_shape": execution_shape.to_dict(),
        "template_protocol_removed": True,
    }
    return ExecutionRecipe(
        recipe_id=str(execution_shape.recipe_id or "runtime.recipe.conversation"),
        title=str(profile.get("title") or "Runtime task"),
        description=str(profile.get("description") or "Runtime assembly derived from capability resolution and TaskGraph context."),
        execution_kind=str(execution_shape.execution_kind or "conversation"),
        task_mode=str(profile.get("task_mode") or execution_shape.execution_kind or "runtime"),
        source_kind=str(execution_shape.source_kind or profile.get("source_kind") or ""),
        input_schema=dict(profile.get("input_schema") or {}),
        output_schema=dict(profile.get("output_schema") or {"final_answer": {"type": "string", "required": True}}),
        default_agent_id=str(profile.get("default_agent_id") or "agent:0"),
        allowed_agent_ids=tuple(str(item) for item in tuple(profile.get("allowed_agent_ids") or ("agent:0",))),
        required_capability_tags=tuple(str(item) for item in tuple(profile.get("required_capability_tags") or ())),
        required_operations=tuple(str(item) for item in tuple(profile.get("required_operations") or ("op.model_response",))),
        optional_operations=tuple(str(item) for item in tuple(profile.get("optional_operations") or ())),
        step_blueprints=tuple(profile.get("step_blueprints") or ()),
        validation_rules=(),
        safety_policy=dict(profile.get("safety_policy") or {}),
        artifact_policy=dict(execution_shape.artifact_policy),
        finalization_policy=dict(execution_shape.finalization_policy),
        ui_manifest={},
        enabled=True,
        metadata=metadata,
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


def _recipe_profile(execution_shape: ExecutionShape) -> dict[str, Any]:
    recipe_id = str(execution_shape.recipe_id or "").strip()
    if recipe_id in {
        "runtime.recipe.role_interaction",
        "runtime.recipe.standard_task",
        "runtime.recipe.professional_task",
    }:
        mode_policy = dict(execution_shape.diagnostics.get("mode_policy") or {})
        semantic_contract = dict(execution_shape.diagnostics.get("task_requirement_contract") or {})
        interaction_mode = str(
            mode_policy.get("interaction_mode")
            or execution_shape.diagnostics.get("interaction_mode")
            or execution_shape.execution_kind
            or "professional_mode"
        ).strip()
        planning_policy = dict(mode_policy.get("planning_policy") or {})
        task_lifecycle_policy = dict(mode_policy.get("task_lifecycle_policy") or {})
        execution_obligation = dict(semantic_contract.get("execution_obligation") or execution_shape.diagnostics.get("execution_obligation") or {})
        professional = interaction_mode == "professional_mode"
        standard_or_professional = interaction_mode in {"standard_mode", "professional_mode"}
        runtime_task_id = _runtime_task_id_from_contract(semantic_contract)
        if professional:
            try:
                agent_plan_draft = build_agent_plan_draft(
                    task_id=runtime_task_id,
                    semantic_contract=semantic_contract,
                    execution_obligation=execution_obligation,
                    model_agent_plan_draft=dict(execution_shape.diagnostics.get("model_agent_plan_draft") or {}),
                ).to_dict()
                agent_plan_requirement = {}
            except AgentPlanRequired as exc:
                agent_plan_requirement = exc.requirement.to_dict()
                agent_plan_draft = empty_agent_plan_draft(
                    task_id=runtime_task_id,
                    semantic_contract=semantic_contract,
                    requirement=agent_plan_requirement,
                ).to_dict()
            plan_coverage_review = review_plan_coverage(
                task_id=runtime_task_id,
                semantic_contract=semantic_contract,
                agent_plan_draft=agent_plan_draft,
            ).to_dict()
        else:
            agent_plan_requirement = {}
            agent_plan_draft = {}
            plan_coverage_review = {}
        step_blueprints = _main_agent_runtime_steps(
            mode_policy=mode_policy,
            semantic_contract=semantic_contract,
            execution_obligation=execution_obligation,
        )
        optional_operations = _agent_runtime_operations(
            mode_policy=mode_policy,
            semantic_contract=semantic_contract,
            execution_obligation=execution_obligation,
        )
        if _agent_todo_explicitly_available(semantic_contract=semantic_contract):
            optional_operations = (*optional_operations, "op.agent_todo")
        return {
            "title": _interaction_mode_title(interaction_mode),
            "description": "Run the main Agent through the unified interaction-mode runtime with semantic contract, evidence, validation, and committed closeout.",
            "task_mode": interaction_mode,
            "source_kind": execution_shape.source_kind or "runtime_task",
            "output_schema": {
                "final_answer": {"type": "string", "required": True},
                "interaction_mode_summary": {"type": "object", "required": False},
            },
            "required_operations": ("op.model_response",),
            "optional_operations": tuple(_dedupe(optional_operations)),
            "step_blueprints": step_blueprints,
            "metadata": {
                "execution_strategy": "interaction_mode_run",
                "interaction_mode": interaction_mode,
                "runtime_step_topology": "unified_agent_task_lifecycle",
                "compiled_step_count": len(step_blueprints),
                "compiled_step_ids": [step.step_id for step in step_blueprints],
                "mode_policy": mode_policy,
                "task_requirement_contract": semantic_contract,
                "execution_obligation": execution_obligation,
                "agent_plan_requirement": agent_plan_requirement,
                "agent_plan_draft": agent_plan_draft,
                "plan_coverage_review": plan_coverage_review,
                "semantic_task_type": str(semantic_contract.get("task_goal_type") or ""),
                "professional_profile_id": str(semantic_contract.get("professional_profile_id") or ""),
                "projection_strength": str(mode_policy.get("projection_strength") or ""),
                "requires_evidence_packet": professional,
                "runtime_limits": {
                    "max_turns": 12 if professional else (4 if standard_or_professional else 2),
                    "max_model_calls": 32 if professional else (12 if standard_or_professional else 4),
                    "max_runtime_seconds": 1800 if professional else (600 if standard_or_professional else 120),
                    "max_events": 480 if professional else (180 if standard_or_professional else 80),
                    "repair_budget": 3 if professional else (1 if standard_or_professional else 0),
                    "stall_detector": standard_or_professional,
                },
                "checkpoint_policy": {
                    "authority": "harness.runtime.assembly",
                    "terminal": True,
                    "after_each_tool_action": professional,
                    "after_delegation": professional,
                },
                "delegation_policy": {
                    "authority": "harness.runtime.assembly",
                    "requested": professional,
                },
                "runtime_mode_policy": {
                    "authority": "task_system.runtime_mode_request",
                    "planning_policy": planning_policy,
                    "task_lifecycle_policy": task_lifecycle_policy,
                    "tool_permission_authority": "harness.runtime.assembly",
                    "sandbox_authority": "task_environment",
                },
                "background_policy": {
                    "enabled": professional,
                    "progress_event_interval_seconds": 30,
                    "notify_on_blocked": professional,
                    "notify_on_completed": professional,
                },
                "recovery_policy": {
                    "allow_resume": professional,
                    "manual_recovery_on_unknown_side_effect": professional,
                    "reuse_completed_read_results": True,
                },
                "verification_policy": {
                    "required": standard_or_professional,
                    "strict": professional,
                    "deliverable_validator": standard_or_professional,
                },
                "final_answer_requirements": (
                    "Answer according to the semantic task contract and the active interaction mode.",
                    "Do not invent evidence, tool execution, file writes, or test results that did not happen.",
                    "Do not output tool calls, DSML, raw parameters, or internal protocol fragments.",
                    *tuple(_deliverable_requirement_lines(semantic_contract, strict=professional)),
                ),
            },
        }
    if recipe_id == "runtime.recipe.task_graph_node":
        return {
            "title": "Task graph node runtime",
            "description": "Run a task-system stage through its assigned agent runtime assembly without resolving a nested conversation route.",
            "task_mode": "task_runtime",
            "source_kind": "task_system",
            "output_schema": {
                "final_answer": {"type": "string", "required": True},
                "node_result": {"type": "object", "required": False},
                "artifact_refs": {"type": "array", "required": False},
            },
            "required_operations": ("op.model_response",),
            "optional_operations": (),
            "step_blueprints": (
                _step("execute_task_node", "Execute task node", "execute"),
                _step("finalize_task_node", "Finalize task node", "finalize"),
            ),
            "metadata": {
                "execution_strategy": "task_system_managed_node",
                "final_answer_requirements": (
                    "Complete the current task-system stage according to the provided stage work order.",
                    "Do not choose a different task environment, route, or retrieval source from the stage instructions.",
                    "Do not invent evidence, file writes, or node outputs that were not produced in this run.",
                ),
            },
        }
    if recipe_id == "runtime.recipe.knowledge_retrieval":
        return _delegate_profile(
            title="Knowledge retrieval answer",
            description="Retrieve knowledge-base evidence and answer from grounded context.",
            task_mode="knowledge_retrieval",
            source_kind="knowledge",
            delegate_target_agent_id="agent:knowledge_searcher",
            delegation_kind="evidence_lookup",
            fallback_operation="op.mcp_retrieval",
            steps=(
                _step("retrieve_evidence", "Retrieve evidence", "execute"),
                _step("synthesize_answer", "Synthesize answer", "finalize"),
            ),
        )
    if recipe_id == "runtime.recipe.pdf_analysis":
        return _delegate_profile(
            title="PDF document analysis",
            description="Read PDF evidence and answer the current question.",
            task_mode="capability_execution",
            source_kind="pdf",
            delegate_target_agent_id="agent:pdf_reader",
            delegation_kind="pdf_reading",
            fallback_operation="op.mcp_pdf",
            steps=(
                _step("analyze_pdf", "Analyze PDF", "analyze"),
                _step("finalize_pdf_answer", "Finalize PDF answer", "finalize"),
            ),
            output_schema={"final_answer": {"type": "string", "required": True}, "task_summary_refs": {"type": "array", "required": False}},
        )
    if recipe_id == "runtime.recipe.structured_data_analysis":
        return _delegate_profile(
            title="Structured data analysis",
            description="Analyze table or dataset evidence and answer the current question.",
            task_mode="capability_execution",
            source_kind="dataset",
            delegate_target_agent_id="agent:table_analyst",
            delegation_kind="table_analysis",
            fallback_operation="op.mcp_structured_data",
            steps=(
                _step("analyze_dataset", "Analyze dataset", "analyze"),
                _step("finalize_dataset_answer", "Finalize data answer", "finalize"),
            ),
            output_schema={"final_answer": {"type": "string", "required": True}, "task_summary_refs": {"type": "array", "required": False}},
        )
    if recipe_id == "runtime.recipe.information_search":
        return {
            "title": "Information search",
            "description": "Search external or realtime information and summarize traceable results.",
            "task_mode": "information_search",
            "source_kind": "external_web",
            "required_operations": ("op.model_response", "op.web_search"),
            "optional_operations": ("op.fetch_url",),
            "step_blueprints": (
                _step("search_information", "Search information", "execute", required_operations=("op.web_search",)),
                _step("summarize_sources", "Summarize sources", "finalize"),
            ),
            "metadata": {
                "execution_strategy": "direct_tool_preferred",
                "primary_tool_name": "web_search",
                "primary_operation_ref": "op.web_search",
            },
        }
    if recipe_id == "runtime.recipe.memory_recall":
        return {
            "title": "Memory recall answer",
            "description": "Answer from conversation, state, and long-term memory context.",
            "task_mode": "memory_recall",
            "source_kind": "memory",
            "required_operations": ("op.model_response", "op.memory_read"),
            "step_blueprints": (
                _step("read_memory_context", "Read memory context", "analyze", required_operations=("op.memory_read",)),
                _step("finalize_memory_answer", "Finalize memory answer", "finalize"),
            ),
            "metadata": {
                "memory_answer": True,
                "final_answer_requirements": ("Answer from current memory context before using any search route.",),
            },
        }
    if recipe_id == "runtime.recipe.bundle":
        return {
            "title": "Multi-capability bundle",
            "description": "Execute multiple bound runtime items and combine the result.",
            "task_mode": "capability_execution",
            "source_kind": "mixed_sources",
            "output_schema": {"final_answer": {"type": "string", "required": True}, "bundle_result_refs": {"type": "array", "required": False}},
            "required_operations": ("op.model_response",),
            "step_blueprints": (
                _step("plan_bundle", "Plan bundle", "understand"),
                _step("execute_bundle_items", "Execute bundle items", "execute"),
                _step("finalize_bundle", "Finalize bundle", "finalize"),
            ),
        }
    if recipe_id == "runtime.recipe.capability":
        return {
            "title": "Builtin capability execution",
            "description": "Execute authorized capability operations and return grounded results.",
            "task_mode": "capability_execution",
            "source_kind": execution_shape.source_kind or "workspace",
            "required_operations": ("op.model_response",),
            "optional_operations": (
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
            "step_blueprints": (
                _step("execute_capability", "Execute capability", "execute"),
                _step("finalize_capability_answer", "Finalize capability answer", "finalize"),
            ),
        }
    if recipe_id in {"runtime.recipe.workspace_patch", "runtime.recipe.light_web_game", "runtime.recipe.arcade_game_bundle"}:
        is_game = recipe_id == "runtime.recipe.light_web_game"
        return {
            "title": "Light web game" if is_game else "Workspace patch",
            "description": "Produce a bounded workspace artifact or patch.",
            "task_mode": "light_web_game" if is_game else "bounded_patch",
            "source_kind": "workspace",
            "output_schema": {"final_answer": {"type": "string", "required": True}, "artifact_refs": {"type": "array", "required": False}},
            "required_operations": ("op.model_response", "op.write_file", "op.edit_file") if is_game else ("op.model_response", "op.read_file", "op.search_text", "op.write_file", "op.edit_file"),
            "optional_operations": ("op.read_file", "op.search_files") if is_game else ("op.search_files", "op.git_diff"),
            "step_blueprints": (
                _step("scope_work", "Scope work", "understand"),
                _step("inspect_or_design", "Inspect or design", "analyze"),
                _step("write_artifact", "Write artifact", "write"),
                _step("verify_result", "Verify result", "verify"),
                _step("finalize_delivery", "Finalize delivery", "finalize"),
            ),
            "safety_policy": {
                "safety_class": "S1_bounded_artifact_write" if is_game else "S1_bounded_patch",
                "write_mode": "bounded_create" if is_game else "scoped_patch",
                "default_write_roots": ["frontend/public/games", "docs/系统规划/任务系统实测记录/artifacts"] if is_game else [],
                "forbidden_paths": [".env", ".env.local", ".git", "node_modules"],
            },
            "metadata": {
                "default_artifact_name": "game.html" if is_game else "",
                "default_write_roots": ["frontend/public/games", "docs/系统规划/任务系统实测记录/artifacts"] if is_game else [],
            },
        }
    return {
        "title": "Main conversation",
        "description": "General runtime conversation and final answer.",
        "task_mode": "general_task",
        "source_kind": execution_shape.source_kind or "conversation",
        "required_operations": ("op.model_response",),
        "step_blueprints": (
            _step("understand_request", "Understand request", "understand"),
            _step("respond", "Respond", "finalize"),
        ),
        "metadata": {"final_answer_requirements": ("Answer the user's current request directly.",)},
    }


def _delegate_profile(
    *,
    title: str,
    description: str,
    task_mode: str,
    source_kind: str,
    delegate_target_agent_id: str,
    delegation_kind: str,
    fallback_operation: str,
    steps: tuple[TaskStepBlueprint, ...],
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "task_mode": task_mode,
        "source_kind": source_kind,
        "output_schema": output_schema or {"final_answer": {"type": "string", "required": True}},
        "required_operations": ("op.model_response",),
        "step_blueprints": steps,
        "metadata": {
            "execution_strategy": "delegate_preferred",
            "delegate_target_agent_id": delegate_target_agent_id,
            "delegation_kind": delegation_kind,
            "fallback_operation": fallback_operation,
        },
    }


def _interaction_mode_title(interaction_mode: str) -> str:
    return {
        "role_mode": "Main Agent role interaction",
        "standard_mode": "Main Agent standard task",
        "professional_mode": "Main Agent professional task",
    }.get(str(interaction_mode or ""), "Main Agent interaction task")


def _main_agent_runtime_steps(
    *,
    mode_policy: dict[str, Any],
    semantic_contract: dict[str, Any],
    execution_obligation: dict[str, Any],
) -> tuple[TaskStepBlueprint, ...]:
    execution_operations = _agent_runtime_operations(
        mode_policy=mode_policy,
        semantic_contract=semantic_contract,
        execution_obligation=execution_obligation,
    )
    verification_operations = _verification_operations(
        mode_policy=mode_policy,
        semantic_contract=semantic_contract,
        execution_obligation=execution_obligation,
    )
    return (
        _step(
            "agent_execution",
            "Agent execution",
            "execute",
            executor_type="agent",
            required_operations=("op.model_response",),
            optional_operations=execution_operations,
            output_contract_id="execution_evidence",
        ),
        _step(
            "final_acceptance",
            "Final acceptance",
            "verify",
            executor_type="system",
            input_refs=("execution_evidence",),
            required_operations=(),
            optional_operations=verification_operations,
            output_contract_id="completion_judgment",
        ),
    )


def _agent_runtime_operations(
    *,
    mode_policy: dict[str, Any],
    semantic_contract: dict[str, Any],
    execution_obligation: dict[str, Any],
) -> tuple[str, ...]:
    _ = mode_policy
    values = [str(item).strip() for item in list(semantic_contract.get("optional_operations") or []) if str(item).strip()]
    actions = {str(item).strip() for item in list(semantic_contract.get("required_actions") or []) if str(item).strip()}
    if list(execution_obligation.get("required_reads") or []) or actions.intersection({"read_material", "inspect_code"}):
        values.extend(["op.read_file", "op.search_text", "op.search_files"])
    if list(execution_obligation.get("required_writes") or []) or actions.intersection({"apply_real_change", "integrate_asset"}):
        values.extend(["op.write_file", "op.edit_file"])
    if list(execution_obligation.get("required_commands") or []) or "run_browser_verification" in actions:
        values.append("op.shell")
    if "run_browser_verification" in actions:
        values.append("op.browser_control")
    return tuple(item for item in _dedupe(values) if item != "op.model_response")


def _verification_operations(
    *,
    mode_policy: dict[str, Any],
    semantic_contract: dict[str, Any],
    execution_obligation: dict[str, Any],
) -> tuple[str, ...]:
    values = list(
        _agent_runtime_operations(
            mode_policy=mode_policy,
            semantic_contract=semantic_contract,
            execution_obligation=execution_obligation,
        )
    )
    if list(execution_obligation.get("required_verifications") or []):
        values.append("op.shell")
    return tuple(_dedupe(values))


def _runtime_task_id_from_contract(semantic_contract: dict[str, Any]) -> str:
    contract_id = str(semantic_contract.get("contract_id") or "").strip()
    if contract_id.startswith("semantic-task:"):
        return contract_id.rsplit(":", 1)[-1] or "runtime"
    return contract_id or "runtime"


def _agent_todo_explicitly_available(*, semantic_contract: dict[str, Any]) -> bool:
    todo_policy = dict(semantic_contract.get("todo_policy") or {}) if isinstance(semantic_contract.get("todo_policy"), dict) else {}
    if bool(todo_policy.get("enabled") is False):
        return False
    if bool(todo_policy.get("required") is True or todo_policy.get("suggested") is True):
        return True
    explicit_optional = {
        str(item).strip()
        for item in list(semantic_contract.get("optional_operations") or [])
        if str(item).strip()
    }
    if "op.agent_todo" in explicit_optional:
        return True
    tool_policy = dict(semantic_contract.get("tool_policy") or {}) if isinstance(semantic_contract.get("tool_policy"), dict) else {}
    return "op.agent_todo" in {
        str(item).strip()
        for item in list(tool_policy.get("optional_operations") or tool_policy.get("allowed_operation_refs") or [])
        if str(item).strip()
    }


def _deliverable_requirement_lines(semantic_contract: dict[str, Any], *, strict: bool) -> tuple[str, ...]:
    deliverables = [
        str(item).strip()
        for item in list(semantic_contract.get("deliverables") or [])
        if str(item).strip()
    ]
    forbidden = [
        str(item).strip()
        for item in list(semantic_contract.get("forbidden_actions") or [])
        if str(item).strip()
    ]
    lines: list[str] = []
    if deliverables:
        lines.append("Required deliverables: " + ", ".join(deliverables) + ".")
    if forbidden:
        lines.append("Forbidden actions: " + ", ".join(forbidden) + ".")
    if strict:
        lines.append("Strict validation is enabled; missing required deliverables must block completion.")
    return tuple(lines)


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


