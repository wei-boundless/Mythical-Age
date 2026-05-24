from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
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
            task_mode="request_intake",
            level="basic",
            goal_summary="Clarify and bind an ambiguous user request.",
            completion_criteria=("User goal is captured.", "No execution is performed."),
            default_projection_role="analyst",
        ),
        TaskDefinition(
            definition_id="task.information_search",
            title="Information search",
            task_mode="information_search",
            level="basic",
            goal_summary="Search external sources and summarize evidence.",
            completion_criteria=("Sources are traceable.", "Unknowns are called out."),
            default_skill_refs=(),
            default_operation_requirements=("op.web_search", "op.fetch_url"),
            default_projection_role="evidence_first",
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
            default_projection_role="operator",
        ),
        TaskDefinition(
            definition_id="task.knowledge_retrieval",
            title="Knowledge retrieval",
            task_mode="knowledge_retrieval",
            level="basic",
            goal_summary="Retrieve relevant knowledge-base evidence and answer from it.",
            completion_criteria=("Relevant evidence is retrieved.", "Answer is grounded in retrieved material."),
            default_skill_refs=("skill.rag-skill",),
            default_projection_role="evidence_first",
        ),
        TaskDefinition(
            definition_id="task.local_material_read",
            title="Local material read",
            task_mode="local_material_read",
            level="basic",
            goal_summary="Read task-relevant local material.",
            completion_criteria=("Only task-relevant local material is used.",),
            default_skill_refs=(),
            default_operation_requirements=("op.read_file", "op.search_files"),
            default_projection_role="analyst",
        ),
        TaskDefinition(
            definition_id="task.information_synthesis",
            title="Information synthesis",
            task_mode="information_synthesis",
            level="basic",
            goal_summary="Synthesize read material into a structured answer.",
            completion_criteria=("Summary is grounded in supplied material.",),
            default_skill_refs=(),
            default_operation_requirements=("op.search_text",),
            default_projection_role="structure_first",
        ),
        TaskDefinition(
            definition_id="task.memory_recall",
            title="Memory recall",
            task_mode="memory_recall",
            level="basic",
            goal_summary="Recall remembered user or session facts and answer from memory context.",
            completion_criteria=("Answer is grounded in memory context.", "No retrieval fallback is used unless memory is insufficient and route changes explicitly."),
            default_skill_refs=(),
            default_operation_requirements=("op.memory_read",),
            default_projection_role="structure_first",
        ),
        TaskDefinition(
            definition_id="task.task_execution",
            title="Task execution",
            task_mode="task_execution",
            level="basic",
            goal_summary="Prepare and execute a bounded change plan.",
            completion_criteria=("Changes are scoped.", "Side effects are gated."),
            default_skill_refs=(),
            default_operation_requirements=("op.read_file", "op.search_text", "op.edit_file"),
            default_projection_role="implementer",
            review_policy="required",
        ),
        TaskDefinition(
            definition_id="task.inspection_and_correction",
            title="Inspection and correction",
            task_mode="inspection_and_correction",
            level="basic",
            goal_summary="Inspect a proposed or completed change for conflicts and risks.",
            completion_criteria=("Risks are listed.", "Contradictions are identified."),
            default_skill_refs=(),
            default_operation_requirements=("op.read_file", "op.search_text"),
            default_projection_role="risk_reviewer",
            review_policy="required",
        ),
        TaskDefinition(
            definition_id="task.final_response",
            title="Final response",
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
    has_local_target = _has_local_material_evidence(text)
    if has_local_target and _has_change_intent(text) and _has_review_intent(text):
        return [
            definitions["task.task_execution"],
            definitions["task.inspection_and_correction"],
        ]
    if _has_external_search_intent(text):
        return [definitions["task.information_search"]]
    if has_local_target and _has_local_read_intent(text):
        return [
            definitions["task.local_material_read"],
            definitions["task.information_synthesis"],
        ]
    if has_local_target and _has_review_intent(text):
        return [definitions["task.inspection_and_correction"]]
    return [definitions["task.request_intake"]]


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
    decision = dict(understanding.get("model_turn_decision") or {})
    if not decision:
        raise RuntimeError("ModelTurnDecision is required to select runtime task definitions")
    action_intent = str(decision.get("action_intent") or "").strip()
    work_mode = str(decision.get("work_mode") or "").strip()
    interaction_intent = str(decision.get("interaction_intent") or "").strip()
    needs = capability_needs(understanding)
    kinds = material_kinds(understanding)
    binding = context_binding(understanding)
    if explicit_task_selected(understanding) or str(binding.get("kind") or "") == "explicit_task_selection":
        return [definitions["task.final_response"]]

    if action_intent == "block":
        raise RuntimeError("Blocked ModelTurnDecision cannot select runtime task definitions")
    if action_intent == "search_external":
        return [definitions["task.capability_execution"], definitions["task.information_search"]]
    if action_intent in {"edit_workspace", "run_command", "start_service"} or work_mode in {"implementation", "verification"}:
        return [
            definitions["task.task_execution"],
            definitions["task.inspection_and_correction"],
        ]
    if interaction_intent in {"review", "inspect"} or action_intent == "read_context":
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
    if action_intent == "answer_only":
        return [definitions["task.final_response"]]

    raise RuntimeError(f"Unsupported ModelTurnDecision action_intent for task definitions: {action_intent}")


def _has_local_material_evidence(text: str) -> bool:
    """Return true only when the request points at a concrete local artifact."""
    if _has_path_like_reference(text):
        return True
    explicit_local_refs = (
        "docs/",
        "backend/",
        "frontend/",
        "backend\\",
        "frontend\\",
        ".md",
        ".py",
        ".tsx",
        ".ts",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        "文件",
        "文档",
        "目录",
        "代码",
        "仓库",
        "项目代码",
        "本地",
    )
    return any(ref in text for ref in explicit_local_refs)

def _has_path_like_reference(text: str) -> bool:
    extension_pattern = r"\.(md|py|tsx|ts|json|toml|yaml|yml|css|html|sql|txt)\b"
    if re.search(extension_pattern, text):
        return True
    return bool(re.search(r"(^|\s|`)(\.{0,2}[a-z0-9_\-\u4e00-\u9fff]+[\\/][^\s`]+)", text))


def _has_change_intent(text: str) -> bool:
    return any(token in text for token in ("修改", "实现", "修复", "落地", "改一下", "更新", "edit", "change"))


def _has_local_read_intent(text: str) -> bool:
    return any(token in text for token in ("读取", "打开", "查看", "读一下", "看一下", "read", "open"))


def _has_review_intent(text: str) -> bool:
    return any(token in text for token in ("检查", "审查", "矛盾", "review", "verify"))


def _has_external_search_intent(text: str) -> bool:
    return any(token in text for token in ("联网", "搜索", "官方资料", "web search"))

