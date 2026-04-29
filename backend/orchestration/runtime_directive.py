from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RuntimeDirectiveExecutor = Literal["model", "tool", "worker", "agent"]


@dataclass(slots=True, frozen=True)
class RuntimeDirective:
    """Executable instruction contract.

    This object is intentionally not built by the preview chain. Executors may
    consume only RuntimeDirective, never RuntimeDirectiveCandidate.
    """

    directive_id: str
    task_id: str
    plan_ref: str
    stage_ref: str
    executor_type: RuntimeDirectiveExecutor
    adopted_resource_policy_ref: str
    operation_refs: tuple[str, ...] = ()
    input_contract_ref: str = ""
    output_contract_ref: str = ""
    execution_graph_ref: str = ""
    runtime_executable: bool = True
    authority: str = "runtime_directive"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "runtime_directive":
            raise ValueError("RuntimeDirective authority must be runtime_directive")
        if not self.runtime_executable:
            raise ValueError("RuntimeDirective must be executable; use RuntimeDirectiveCandidate for previews")
        if not self.adopted_resource_policy_ref:
            raise ValueError("RuntimeDirective requires an adopted resource policy ref")
        if self.plan_ref.endswith(":preview") or self.stage_ref.endswith(":preview"):
            raise ValueError("RuntimeDirective cannot reference preview plan or stage refs")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["operation_refs"] = list(self.operation_refs)
        return payload


@dataclass(slots=True, frozen=True)
class RuntimeDirectiveBuildBlock:
    block_id: str
    plan_ref: str
    stage_ref: str = ""
    reason: str = "preview_only"
    blocked: bool = True
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.blocked:
            raise ValueError("RuntimeDirectiveBuildBlock cannot allow directive build")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_preview_runtime_directive_block(
    *,
    plan_ref: str,
    stage_ref: str = "",
    reason: str = "preview_only",
) -> RuntimeDirectiveBuildBlock:
    return RuntimeDirectiveBuildBlock(
        block_id=f"runtime-directive-block:{plan_ref}",
        plan_ref=plan_ref,
        stage_ref=stage_ref,
        reason=reason,
        blocked=True,
        diagnostics={
            "runtime_directive_available": False,
            "adopted_resource_policy_required": True,
            "operation_gate_required_before_execution": True,
        },
    )
