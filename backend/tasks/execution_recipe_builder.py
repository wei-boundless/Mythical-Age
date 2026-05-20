from __future__ import annotations

from pathlib import Path
from typing import Any

from .execution_recipe_models import ExecutionRecipe
from .execution_shape_resolver import ExecutionShape
from .step_models import TaskStepBlueprint


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
    if recipe_id == "runtime.recipe.autonomous_task_run":
        autonomy_mode = str(execution_shape.diagnostics.get("autonomy_mode") or "simple").strip() or "simple"
        if autonomy_mode not in {"simple", "standard"}:
            autonomy_mode = "simple"
        return {
            "title": "Main Agent autonomous task",
            "description": "Run a graphless autonomous task through the main Agent with plan, observation, verification, and committed closeout.",
            "task_family": "runtime",
            "task_mode": "autonomous_task_run",
            "source_kind": execution_shape.source_kind or "runtime_task",
            "output_schema": {
                "final_answer": {"type": "string", "required": True},
                "autonomous_task_summary": {"type": "object", "required": False},
            },
            "required_operations": ("op.model_response",),
            "optional_operations": (
                "op.read_file",
                "op.search_text",
                "op.search_files",
                "op.git_status",
                "op.git_diff",
                "op.memory_read",
                "op.delegate_to_agent",
            ),
            "step_blueprints": (
                _step("understand_goal", "Understand goal", "understand", required_operations=("op.model_response",)),
                _step("draft_plan", "Draft lightweight plan", "plan", required_operations=("op.model_response",)),
                _step("summarize_result", "Summarize result", "finalize", required_operations=("op.model_response",)),
            ),
            "metadata": {
                "execution_strategy": "autonomous_task_run",
                "runtime_lane_hint": "autonomous_task",
                "runtime_driver": "autonomous_task_run",
                "autonomy_mode": autonomy_mode,
                "runtime_limits": {
                    "max_turns": 4,
                    "max_model_calls": 6,
                    "max_runtime_seconds": 300,
                    "max_events": 120,
                },
                "checkpoint_policy": {
                    "before_commit": True,
                    "terminal": True,
                    "after_each_plan_item": False,
                },
                "delegation_policy": {
                    "enabled": autonomy_mode == "standard",
                    "max_delegate_calls_per_step": 1,
                    "max_delegate_calls_per_task_run": 1,
                    "allowed_tool_name": "delegate_to_agent",
                    "allowed_operation_ref": "op.delegate_to_agent",
                    "allowed_agent_ids": [
                        "agent:rag_analyst",
                        "agent:pdf_reader",
                        "agent:table_analyst",
                        "agent:web_researcher",
                    ],
                },
                "tool_execution_policy": {
                    "enabled": autonomy_mode == "standard",
                    "max_tool_calls_per_round": 1,
                    "allowed_operation_refs": [
                        "op.read_file",
                        "op.search_text",
                        "op.search_files",
                        "op.git_status",
                        "op.git_diff",
                        "op.delegate_to_agent",
                    ],
                    "allowed_tool_names": [
                        "read_file",
                        "search_text",
                        "search_files",
                        "git_status",
                        "git_diff",
                        "delegate_to_agent",
                    ],
                    "denied_tool_names": [],
                },
                "verification_policy": {
                    "required": False,
                    "require_summary_check": True,
                    "require_artifact_refs_for_write": True,
                },
                "final_answer_requirements": (
                    "Explain the goal, the lightweight plan, the work completed, and any limitations.",
                    "Do not invent evidence or claim tool execution that did not happen.",
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
        return _delegate_profile(
            title="Information search",
            description="Search external or realtime information and summarize traceable results.",
            task_family="search",
            task_mode="information_search",
            source_kind="external_web",
            delegate_target_agent_id="agent:web_researcher",
            delegation_kind="web_research",
            fallback_operation="op.web_search",
            steps=(
                _step("search_information", "Search information", "execute", required_operations=("op.web_search",)),
                _step("summarize_sources", "Summarize sources", "finalize"),
            ),
        )
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
