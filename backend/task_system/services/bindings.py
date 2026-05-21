from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from task_system.tasks.definitions import TaskDefinition


@dataclass(frozen=True, slots=True)
class TaskBindingRecord:
    binding_id: str
    definition_id: str
    enabled: bool = True
    source: str = "builtin"
    agent_profile_id: str = ""
    projection_selector: str = "task_default"
    skill_scope: tuple[str, ...] = ()
    denied_skills: tuple[str, ...] = ()
    operation_scope: tuple[str, ...] = ()
    denied_operations: tuple[str, ...] = ()
    memory_scope: str = "session_read"
    output_contract_id: str = ""
    review_policy: str = "optional"
    approval_policy: str = "default"
    guardrail_overrides: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_task_binding(definition: TaskDefinition) -> TaskBindingRecord:
    denied_operations = (
        "op.write_file",
        "op.edit_file",
        "op.shell",
        "op.python_repl",
        "op.memory_write_candidate",
    )
    operation_scope = definition.default_operation_requirements
    if definition.definition_id == "task.task_execution":
        denied_operations = ("op.shell", "op.python_repl", "op.memory_write_candidate")
    if definition.definition_id == "task.inspection_and_correction":
        denied_operations = ("op.shell", "op.python_repl", "op.memory_write_candidate")
    if definition.definition_id == "task.information_search":
        denied_operations = ("op.write_file", "op.edit_file", "op.shell", "op.python_repl")
    return TaskBindingRecord(
        binding_id=f"binding:{definition.definition_id}:builtin",
        definition_id=definition.definition_id,
        projection_selector=definition.default_projection_role or "task_default",
        skill_scope=definition.default_skill_refs,
        operation_scope=operation_scope,
        denied_operations=denied_operations,
        review_policy=definition.review_policy,
    )


def merge_task_bindings(bindings: list[TaskBindingRecord]) -> TaskBindingRecord:
    if not bindings:
        return TaskBindingRecord(binding_id="binding:empty", definition_id="task.request_intake")
    return TaskBindingRecord(
        binding_id="+".join(binding.binding_id for binding in bindings),
        definition_id="+".join(binding.definition_id for binding in bindings),
        enabled=all(binding.enabled for binding in bindings),
        source="merged_runtime",
        projection_selector=bindings[-1].projection_selector,
        skill_scope=tuple(_dedupe([skill for binding in bindings for skill in binding.skill_scope])),
        denied_skills=tuple(_dedupe([skill for binding in bindings for skill in binding.denied_skills])),
        operation_scope=tuple(_dedupe([operation for binding in bindings for operation in binding.operation_scope])),
        denied_operations=tuple(_dedupe([operation for binding in bindings for operation in binding.denied_operations])),
        memory_scope=bindings[-1].memory_scope,
        output_contract_id=bindings[-1].output_contract_id,
        review_policy="required" if any(binding.review_policy == "required" for binding in bindings) else "optional",
        approval_policy=bindings[-1].approval_policy,
    )


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
