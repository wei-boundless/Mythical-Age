from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    definition_id: str
    title: str
    task_family: str
    task_mode: str
    level: str
    goal_summary: str
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    completion_criteria: tuple[str, ...] = ()
    default_skill_refs: tuple[str, ...] = ()
    default_operation_requirements: tuple[str, ...] = ()
    default_projection_role: str = ""
    review_policy: str = "optional"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_task_definitions() -> dict[str, TaskDefinition]:
    definitions = [
        TaskDefinition(
            definition_id="task.request_intake",
            title="Request intake",
            task_family="qa",
            task_mode="request_intake",
            level="basic",
            goal_summary="Clarify and bind an ambiguous user request.",
            completion_criteria=("User goal is captured.", "No execution is performed."),
            default_projection_role="analyst",
        ),
        TaskDefinition(
            definition_id="task.information_search",
            title="Information search",
            task_family="search",
            task_mode="information_search",
            level="basic",
            goal_summary="Search external sources and summarize evidence.",
            completion_criteria=("Sources are traceable.", "Unknowns are called out."),
            default_skill_refs=("skill.web_search", "skill.evidence_summary"),
            default_operation_requirements=("op.web_search", "op.fetch_url"),
            default_projection_role="evidence_first",
        ),
        TaskDefinition(
            definition_id="task.local_material_read",
            title="Local material read",
            task_family="local_processing",
            task_mode="local_material_read",
            level="basic",
            goal_summary="Read task-relevant local material.",
            completion_criteria=("Only task-relevant local material is used.",),
            default_skill_refs=("skill.local_read",),
            default_operation_requirements=("op.read_file", "op.search_files"),
            default_projection_role="analyst",
        ),
        TaskDefinition(
            definition_id="task.information_synthesis",
            title="Information synthesis",
            task_family="local_processing",
            task_mode="information_synthesis",
            level="basic",
            goal_summary="Synthesize read material into a structured answer.",
            completion_criteria=("Summary is grounded in supplied material.",),
            default_skill_refs=("skill.synthesis",),
            default_operation_requirements=("op.search_text",),
            default_projection_role="structure_first",
        ),
        TaskDefinition(
            definition_id="task.task_execution",
            title="Task execution",
            task_family="execution",
            task_mode="task_execution",
            level="basic",
            goal_summary="Prepare a bounded change plan or staged edit preview.",
            completion_criteria=("Changes are scoped.", "Side effects are gated."),
            default_skill_refs=("skill.implementation",),
            default_operation_requirements=("op.read_file", "op.search_text", "op.edit_file"),
            default_projection_role="implementer",
            review_policy="required",
        ),
        TaskDefinition(
            definition_id="task.inspection_and_correction",
            title="Inspection and correction",
            task_family="review",
            task_mode="inspection_and_correction",
            level="basic",
            goal_summary="Inspect a proposed or completed change for conflicts and risks.",
            completion_criteria=("Risks are listed.", "Contradictions are identified."),
            default_skill_refs=("skill.review",),
            default_operation_requirements=("op.read_file", "op.search_text"),
            default_projection_role="risk_reviewer",
            review_policy="required",
        ),
        TaskDefinition(
            definition_id="task.final_response",
            title="Final response",
            task_family="finalization",
            task_mode="final_response",
            level="basic",
            goal_summary="Produce the final user-facing response.",
            completion_criteria=("Answer is concise.", "No hidden execution artifacts leak."),
            default_projection_role="communicator",
        ),
    ]
    return {definition.definition_id: definition for definition in definitions}


def select_task_definitions(user_goal: str) -> list[TaskDefinition]:
    text = str(user_goal or "").lower()
    definitions = default_task_definitions()
    if any(token in text for token in ("修改", "实现", "修复", "落地", "edit", "change")) and any(
        token in text for token in ("检查", "审查", "矛盾", "review", "verify")
    ):
        return [
            definitions["task.task_execution"],
            definitions["task.inspection_and_correction"],
        ]
    if any(token in text for token in ("联网", "搜索", "官方资料", "web", "search")):
        return [definitions["task.information_search"]]
    if any(token in text for token in ("读取", "打开", "总结", "docs/", ".md", "read", "summarize")):
        return [
            definitions["task.local_material_read"],
            definitions["task.information_synthesis"],
        ]
    if any(token in text for token in ("检查", "审查", "矛盾", "review")):
        return [definitions["task.inspection_and_correction"]]
    return [definitions["task.request_intake"]]

