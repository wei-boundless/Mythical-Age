from __future__ import annotations

from pathlib import Path
from typing import Any

from task_system.planning.execution_recipe_models import ExecutionRecipe
from task_system.planning.execution_shape_resolver import ExecutionShape
from task_system.planning.understanding_step_compiler import compile_understanding_runtime_steps
from task_system.tasks.step_models import TaskStepBlueprint
from runtime.professional_runtime.agent_plan import build_agent_plan_draft
from runtime.professional_runtime.plan_coverage import review_plan_coverage


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
        task_family=str(profile.get("task_family") or execution_shape.source_kind or "general"),
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
        semantic_contract = dict(execution_shape.diagnostics.get("semantic_task_contract") or {})
        interaction_mode = str(
            mode_policy.get("interaction_mode")
            or execution_shape.diagnostics.get("interaction_mode")
            or execution_shape.execution_kind
            or "professional_mode"
        ).strip()
        runtime_lane = str(mode_policy.get("runtime_lane") or "").strip()
        tool_policy = dict(mode_policy.get("tool_policy") or {})
        delegation_policy = dict(mode_policy.get("delegation_policy") or {})
        checkpoint_policy = dict(mode_policy.get("checkpoint_policy") or {})
        verification_policy = dict(mode_policy.get("verification_policy") or {})
        sandbox_policy = dict(mode_policy.get("sandbox_policy") or {})
        context_policy = dict(mode_policy.get("context_policy") or {})
        output_policy = dict(mode_policy.get("output_policy") or {})
        execution_obligation = dict(semantic_contract.get("execution_obligation") or execution_shape.diagnostics.get("execution_obligation") or {})
        strict = bool(verification_policy.get("strict") is True)
        standard_or_professional = interaction_mode in {"standard_mode", "professional_mode"}
        professional = interaction_mode == "professional_mode"
        runtime_task_id = _runtime_task_id_from_contract(semantic_contract)
        agent_plan_draft = build_agent_plan_draft(
            task_id=runtime_task_id,
            semantic_contract=semantic_contract,
            execution_obligation=execution_obligation,
            model_agent_plan_draft=dict(execution_shape.diagnostics.get("model_agent_plan_draft") or {}),
        ).to_dict()
        plan_coverage_review = review_plan_coverage(
            task_id=runtime_task_id,
            semantic_contract=semantic_contract,
            agent_plan_draft=agent_plan_draft,
        ).to_dict()
        step_blueprints = compile_understanding_runtime_steps(
            interaction_mode=interaction_mode,
            semantic_contract=semantic_contract,
            mode_policy=mode_policy,
            execution_obligation=execution_obligation,
            plan_coverage_review=plan_coverage_review,
        )
        optional_operations = [
            str(item)
            for item in tuple(tool_policy.get("allowed_operation_refs") or ())
            if str(item).strip() != "op.model_response"
        ]
        if _needs_agent_todo(
            interaction_mode=interaction_mode,
            semantic_contract=semantic_contract,
            agent_plan_draft=agent_plan_draft,
            step_blueprints=step_blueprints,
        ):
            optional_operations.append("op.agent_todo")
        return {
            "title": _interaction_mode_title(interaction_mode),
            "description": "Run the main Agent through the unified interaction-mode runtime with semantic contract, evidence, validation, and committed closeout.",
            "task_family": "runtime",
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
                "runtime_lane_hint": runtime_lane,
                "runtime_driver": "professional_task_run",
                "interaction_mode": interaction_mode,
                "understanding_step_compiler": "task_system.planning.understanding_step_compiler",
                "compiled_step_count": len(step_blueprints),
                "compiled_step_ids": [step.step_id for step in step_blueprints],
                "mode_policy": mode_policy,
                "semantic_task_contract": semantic_contract,
                "execution_obligation": execution_obligation,
                "agent_plan_draft": agent_plan_draft,
                "plan_coverage_review": plan_coverage_review,
                "semantic_task_type": str(semantic_contract.get("task_goal_type") or ""),
                "professional_profile_id": str(semantic_contract.get("professional_profile_id") or ""),
                "projection_strength": str(mode_policy.get("projection_strength") or ""),
                "requires_evidence_packet": bool(tool_policy.get("requires_evidence_packet") or professional),
                "runtime_limits": {
                    "max_turns": 12 if professional else (4 if standard_or_professional else 2),
                    "max_model_calls": 32 if professional else (12 if standard_or_professional else 4),
                    "max_runtime_seconds": 1800 if professional else (600 if standard_or_professional else 120),
                    "max_events": 480 if professional else (180 if standard_or_professional else 80),
                    "repair_budget": 3 if professional else (1 if standard_or_professional else 0),
                    "stall_detector": standard_or_professional,
                },
                "checkpoint_policy": checkpoint_policy,
                "delegation_policy": delegation_policy,
                "tool_execution_policy": tool_policy,
                "sandbox_policy": sandbox_policy,
                "context_policy": context_policy,
                "output_policy": output_policy,
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
                "verification_policy": verification_policy,
                "final_answer_requirements": (
                    "Answer according to the semantic task contract and the active interaction mode.",
                    "Do not invent evidence, tool execution, file writes, or test results that did not happen.",
                    "Do not output tool calls, DSML, raw parameters, or internal protocol fragments.",
                    *tuple(_deliverable_requirement_lines(semantic_contract, strict=strict)),
                ),
            },
        }
    if recipe_id == "runtime.recipe.knowledge_retrieval":
        return _delegate_profile(
            title="Knowledge retrieval answer",
            description="Retrieve knowledge-base evidence and answer from grounded context.",
            task_family="retrieval",
            task_mode="knowledge_retrieval",
            source_kind="knowledge",
            delegate_target_agent_id="agent:rag_analyst",
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
            task_family="document",
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
            task_family="data",
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
            "task_family": "search",
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
                "runtime_lane_hint": "information_search",
                "primary_tool_name": "web_search",
                "primary_operation_ref": "op.web_search",
            },
        }
    if recipe_id == "runtime.recipe.memory_recall":
        return {
            "title": "Memory recall answer",
            "description": "Answer from conversation, state, and long-term memory context.",
            "task_family": "memory",
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
            "task_family": "bundle",
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
            "title": "Builtin capability lane",
            "description": "Execute authorized capability operations and return grounded results.",
            "task_family": "capability",
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
            "task_family": "development",
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
        "task_family": "general",
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
    task_family: str,
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
        "task_family": task_family,
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


def _runtime_task_id_from_contract(semantic_contract: dict[str, Any]) -> str:
    contract_id = str(semantic_contract.get("contract_id") or "").strip()
    if contract_id.startswith("semantic-task:"):
        return contract_id.rsplit(":", 1)[-1] or "runtime"
    return contract_id or "runtime"


def _needs_agent_todo(
    *,
    interaction_mode: str,
    semantic_contract: dict[str, Any],
    agent_plan_draft: dict[str, Any],
    step_blueprints: tuple[TaskStepBlueprint, ...],
) -> bool:
    if interaction_mode == "professional_mode":
        return True
    steps = [item for item in list(agent_plan_draft.get("steps") or []) if isinstance(item, dict)]
    if len(steps) > 1 or len(step_blueprints) > 2:
        return True
    diagnostics = dict(semantic_contract.get("diagnostics") or {})
    understanding = dict(
        diagnostics.get("task_understanding_frame")
        or dict(diagnostics.get("task_goal_frame") or {}).get("task_understanding_frame")
        or {}
    )
    return len(list(understanding.get("user_provided_flow") or [])) > 1


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
