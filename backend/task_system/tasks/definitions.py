from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from request_intent.frame_access import (
    capability_needs,
    context_binding,
    explicit_task_selected,
    material_kinds,
)

@dataclass(frozen=True, slots=True)
class TaskDefinition:
    definition_id: str
    title: str
    task_mode: str
    level: str
    goal_summary: str
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    completion_criteria: tuple[str, ...] = ()
    default_operation_requirements: tuple[str, ...] = ()
    default_prompt_role: str = ""
    review_policy: str = "optional"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_task_definitions() -> dict[str, TaskDefinition]:
    definitions = [
        TaskDefinition(
            definition_id="task.request_intake",
            title="Request intake",
            task_mode="request_intake",
            level="basic",
            goal_summary="Clarify and bind an ambiguous user request.",
            completion_criteria=("User goal is captured.", "No execution is performed."),
            default_prompt_role="analyst",
        ),
        TaskDefinition(
            definition_id="task.information_search",
            title="Information search",
            task_mode="information_search",
            level="basic",
            goal_summary="Search external sources and summarize evidence.",
            completion_criteria=("Sources are traceable.", "Unknowns are called out."),
            default_operation_requirements=("op.web_search", "op.fetch_url"),
            default_prompt_role="evidence_first",
        ),
        TaskDefinition(
            definition_id="task.capability_execution",
            title="Capability execution",
            task_mode="capability_execution",
            level="basic",
            goal_summary="Execute the selected authorized capability for a clear user request.",
            completion_criteria=(
                "Required capability is selected.",
                "Available operation is executed when required inputs are present.",
                "Answer is grounded in the capability result.",
            ),
            default_prompt_role="operator",
        ),
        TaskDefinition(
            definition_id="task.knowledge_retrieval",
            title="Knowledge retrieval",
            task_mode="knowledge_retrieval",
            level="basic",
            goal_summary="Retrieve relevant knowledge-base evidence and answer from it.",
            completion_criteria=("Relevant evidence is retrieved.", "Answer is grounded in retrieved material."),
            default_prompt_role="evidence_first",
        ),
        TaskDefinition(
            definition_id="task.local_material_read",
            title="Local material read",
            task_mode="local_material_read",
            level="basic",
            goal_summary="Read task-relevant local material.",
            completion_criteria=("Only task-relevant local material is used.",),
            default_operation_requirements=("op.read_file", "op.search_files"),
            default_prompt_role="analyst",
        ),
        TaskDefinition(
            definition_id="task.information_synthesis",
            title="Information synthesis",
            task_mode="information_synthesis",
            level="basic",
            goal_summary="Synthesize read material into a structured answer.",
            completion_criteria=("Summary is grounded in supplied material.",),
            default_operation_requirements=("op.search_text",),
            default_prompt_role="structure_first",
        ),
        TaskDefinition(
            definition_id="task.memory_recall",
            title="Memory recall",
            task_mode="memory_recall",
            level="basic",
            goal_summary="Recall remembered user or session facts and answer from memory context.",
            completion_criteria=("Answer is grounded in memory context.", "No retrieval fallback is used unless memory is insufficient and route changes explicitly."),
            default_operation_requirements=("op.memory_read",),
            default_prompt_role="structure_first",
        ),
        TaskDefinition(
            definition_id="task.task_execution",
            title="Task execution",
            task_mode="task_execution",
            level="basic",
            goal_summary="Prepare and execute a bounded change plan.",
            completion_criteria=("Changes are scoped.", "Side effects are gated."),
            default_operation_requirements=("op.read_file", "op.search_text", "op.edit_file"),
            default_prompt_role="implementer",
            review_policy="required",
        ),
        TaskDefinition(
            definition_id="task.inspection_and_correction",
            title="Inspection and correction",
            task_mode="inspection_and_correction",
            level="basic",
            goal_summary="Inspect a proposed or completed change for conflicts and risks.",
            completion_criteria=("Risks are listed.", "Contradictions are identified."),
            default_operation_requirements=("op.read_file", "op.search_text"),
            default_prompt_role="risk_reviewer",
            review_policy="required",
        ),
        TaskDefinition(
            definition_id="task.final_response",
            title="Final response",
            task_mode="final_response",
            level="basic",
            goal_summary="Produce the final user-facing response.",
            completion_criteria=("Answer is concise.", "No hidden execution artifacts leak."),
            default_prompt_role="communicator",
        ),
    ]
    return {definition.definition_id: definition for definition in definitions}


def select_runtime_task_definitions(
    user_goal: str,
    *,
    query_understanding: dict[str, Any] | None = None,
) -> list[TaskDefinition]:
    """Select task definitions from cognition signals and contracts.

    Agent cognition contributes weak needs and material hints. It does not
    preselect concrete tools or preserve old keyword routes.
    """
    definitions = default_task_definitions()
    understanding = dict(query_understanding or {})
    action_request = dict(understanding.get("agent_turn_action_request") or {})
    task_contract_seed = dict(understanding.get("task_contract_seed") or {})
    task_goal_type = str(
        dict(understanding.get("task_goal_spec") or {}).get("task_goal_type")
        or task_contract_seed.get("task_goal_type")
        or ""
    ).strip()
    needs = capability_needs(understanding)
    kinds = material_kinds(understanding)
    binding = context_binding(understanding)
    if explicit_task_selected(understanding) or str(binding.get("kind") or "") == "explicit_task_contract":
        return [definitions["task.final_response"]]

    action_type = str(action_request.get("action_type") or "").strip()
    if action_type == "block":
        raise RuntimeError("Blocked AgentTurnActionRequest cannot select runtime task definitions")
    if action_type and action_type != "request_task_run":
        return [definitions["task.final_response"]]

    resource_contract = dict(task_contract_seed.get("resource_contract") or {})
    has_write_contract = bool(
        list(resource_contract.get("required_write_files") or [])
        or list(resource_contract.get("required_write_dirs") or [])
    )
    has_read_contract = bool(
        list(resource_contract.get("required_read_files") or [])
        or list(resource_contract.get("required_read_dirs") or [])
    )
    deliverables = {str(item).strip() for item in list(task_contract_seed.get("deliverables") or []) if str(item).strip()}

    if task_goal_type in {"external_research"}:
        return [definitions["task.capability_execution"], definitions["task.information_search"]]
    if (
        task_goal_type in {"code_fix_execution", "artifact_delivery", "frontend_app_delivery", "game_vertical_slice_delivery", "implementation", "verification"}
        or has_write_contract
        or deliverables
    ):
        return [
            definitions["task.task_execution"],
            definitions["task.inspection_and_correction"],
        ]
    if task_goal_type in {"inspection", "code_review", "pdf_analysis"} or has_read_contract:
        if kinds & {"workspace", "code", "pdf", "dataset"} or needs:
            return [definitions["task.inspection_and_correction"]]
        return [
            definitions["task.capability_execution"],
            definitions["task.local_material_read"],
            definitions["task.information_synthesis"],
        ]
    if "memory_candidate" in needs:
        return [definitions["task.memory_recall"]]
    if "knowledge_lookup" in needs:
        return [definitions["task.knowledge_retrieval"]]
    return [definitions["task.task_execution"], definitions["task.inspection_and_correction"]]



