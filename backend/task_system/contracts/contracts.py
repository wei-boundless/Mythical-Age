from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskContract:
    """Fixed task contract issued by TaskSystem for Harness consumption.

    This is not an execution lifecycle. Runtime packets, loop state, task runs,
    and result receipts belong to Harness/read models and must not be written
    back into this contract.
    """

    task_id: str
    schema_version: str = "task_contract.v1"
    contract_kind: str = "specific_task"
    session_id: str = ""
    user_goal: str = ""
    contract_id: str = ""
    environment_id: str = ""
    source: str = "user_request"
    source_ref: str = ""
    objective: str = ""
    runtime_shape: str = "single_agent"
    runtime_requirements: dict[str, Any] = field(default_factory=dict)
    loop_requirements: dict[str, Any] = field(default_factory=dict)
    runtime_assembly_plan: dict[str, Any] = field(default_factory=dict)
    loop_plan: dict[str, Any] = field(default_factory=dict)
    graph_contract: dict[str, Any] = field(default_factory=dict)
    graph_runtime_assembly_plan: dict[str, Any] = field(default_factory=dict)
    graph_loop_plan: dict[str, Any] = field(default_factory=dict)
    human_gate_contract: dict[str, Any] = field(default_factory=dict)
    working_objects: tuple[dict[str, Any], ...] = ()
    input_refs: tuple[dict[str, Any], ...] = ()
    resource_scope: dict[str, Any] = field(default_factory=dict)
    tool_scope: dict[str, Any] = field(default_factory=dict)
    memory_scope: dict[str, Any] = field(default_factory=dict)
    artifact_scope: dict[str, Any] = field(default_factory=dict)
    agent_assignment: dict[str, Any] = field(default_factory=dict)
    prompt_pack_refs: tuple[str, ...] = ()
    skill_pack_refs: tuple[str, ...] = ()
    output_contract: dict[str, Any] = field(default_factory=dict)
    acceptance_policy: dict[str, Any] = field(default_factory=dict)
    recovery_policy: dict[str, Any] = field(default_factory=dict)
    approval_policy: dict[str, Any] = field(default_factory=dict)
    risk_policy: dict[str, Any] = field(default_factory=dict)
    extension_slots: dict[str, Any] = field(default_factory=dict)
    recipe_id: str = ""
    task_mode: str = "unknown"
    parent_task_id: str = ""
    task_spec_ref: str = ""
    bindings: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    requested_outputs: tuple[str, ...] = ()
    candidate_refs: tuple[str, ...] = ()
    refs: dict[str, Any] = field(default_factory=dict)
    status: str = "issued"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_contract"

    def __post_init__(self) -> None:
        if self.authority not in {"task_system.task_contract", "task_contract"}:
            raise ValueError("TaskContract authority must be task_system.task_contract")
        if self.authority == "task_contract":
            object.__setattr__(self, "authority", "task_system.task_contract")
        if not str(self.task_id or "").strip():
            raise ValueError("TaskContract requires task_id")
        if not str(self.schema_version or "").strip():
            raise ValueError("TaskContract requires schema_version")
        if not str(self.contract_kind or "").strip():
            raise ValueError("TaskContract requires contract_kind")
        if not str(self.contract_id or "").strip():
            safe_task_id = str(self.task_id or "").replace(":", "_")
            object.__setattr__(self, "contract_id", f"taskcontract:{safe_task_id}")
        if not str(self.objective or "").strip() and str(self.user_goal or "").strip():
            object.__setattr__(self, "objective", str(self.user_goal or "").strip())
        if not str(self.user_goal or "").strip() and str(self.objective or "").strip():
            object.__setattr__(self, "user_goal", str(self.objective or "").strip())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["working_objects"] = [dict(item) for item in self.working_objects]
        payload["input_refs"] = [dict(item) for item in self.input_refs]
        payload["prompt_pack_refs"] = list(self.prompt_pack_refs)
        payload["skill_pack_refs"] = list(self.skill_pack_refs)
        payload["requested_outputs"] = list(self.requested_outputs)
        payload["candidate_refs"] = list(self.candidate_refs)
        return payload


def build_task_contract(
    *,
    task_id: str,
    session_id: str,
    user_goal: str,
    source: str = "runtime",
    recipe_id: str = "",
    task_mode: str = "unknown",
    task_spec_ref: str = "",
    environment_id: str = "",
    source_ref: str = "",
    objective: str = "",
    runtime_shape: str = "single_agent",
    runtime_requirements: dict[str, Any] | None = None,
    loop_requirements: dict[str, Any] | None = None,
    output_contract: dict[str, Any] | None = None,
    acceptance_policy: dict[str, Any] | None = None,
    extension_slots: dict[str, Any] | None = None,
) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        session_id=session_id,
        user_goal=user_goal,
        environment_id=environment_id,
        source=source,
        source_ref=source_ref,
        objective=objective or user_goal,
        recipe_id=recipe_id,
        task_mode=task_mode,
        task_spec_ref=task_spec_ref,
        runtime_shape=runtime_shape,
        runtime_requirements=dict(runtime_requirements or {}),
        loop_requirements=dict(loop_requirements or {}),
        output_contract=dict(output_contract or {}),
        acceptance_policy=dict(acceptance_policy or {}),
        extension_slots=dict(extension_slots or {}),
    )


