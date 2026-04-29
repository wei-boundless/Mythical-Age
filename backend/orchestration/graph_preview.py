from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .plan import OrchestrationPlanPreview
from .validation import PlanValidationResult


@dataclass(slots=True, frozen=True)
class ExecutionNodePreview:
    node_id: str
    node_type: str
    executor_hint: str
    stage_ref: str
    operation_refs: tuple[str, ...] = ()
    policy_refs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    executable: bool = False
    blocked_reason: str = "preview_only"
    authority: str = "preview_only"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.executable:
            raise ValueError("ExecutionNodePreview cannot be executable")
        if self.authority != "preview_only":
            raise ValueError("ExecutionNodePreview authority must remain preview_only")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["operation_refs"] = list(self.operation_refs)
        payload["policy_refs"] = list(self.policy_refs)
        payload["depends_on"] = list(self.depends_on)
        return payload


@dataclass(slots=True, frozen=True)
class ExecutionGraphPreview:
    graph_preview_id: str
    task_id: str
    plan_ref: str
    node_previews: tuple[ExecutionNodePreview, ...] = ()
    edge_previews: tuple[dict[str, Any], ...] = ()
    runtime_executable: bool = False
    blocked_reason: str = "preview_only"
    preview_only: bool = True
    authority: str = "execution_graph_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.preview_only:
            raise ValueError("ExecutionGraphPreview must remain preview_only")
        if self.runtime_executable:
            raise ValueError("ExecutionGraphPreview cannot be runtime executable")
        if self.authority != "execution_graph_preview":
            raise ValueError("ExecutionGraphPreview cannot carry execution authority")

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_preview_id": self.graph_preview_id,
            "task_id": self.task_id,
            "plan_ref": self.plan_ref,
            "node_previews": [node.to_dict() for node in self.node_previews],
            "edge_previews": [dict(edge) for edge in self.edge_previews],
            "runtime_executable": self.runtime_executable,
            "blocked_reason": self.blocked_reason,
            "preview_only": self.preview_only,
            "authority": self.authority,
            "diagnostics": dict(self.diagnostics),
        }


def build_execution_graph_preview(
    plan: OrchestrationPlanPreview,
    validation: PlanValidationResult,
) -> ExecutionGraphPreview:
    node_previews = tuple(
        ExecutionNodePreview(
            node_id=f"node-preview:{stage.stage_id}",
            node_type=stage.stage_type,
            executor_hint=stage.executor_hint,
            stage_ref=stage.stage_id,
            operation_refs=stage.operation_refs,
            policy_refs=stage.policy_refs,
            depends_on=stage.depends_on,
            blocked_reason=validation.reason or stage.blocked_reason,
            diagnostics={
                "plan_ref": plan.plan_id,
                "runtime_directive_enabled": False,
                "runtime_executable": False,
            },
        )
        for stage in plan.stages
    )
    return ExecutionGraphPreview(
        graph_preview_id=f"graph-preview:{plan.plan_id}",
        task_id=plan.task_id,
        plan_ref=plan.plan_id,
        node_previews=node_previews,
        edge_previews=(),
        runtime_executable=False,
        blocked_reason=validation.reason or "preview_only",
        diagnostics={
            "preview_only": True,
            "fail_closed": True,
            "node_preview_count": len(node_previews),
            "execution_node_count": 0,
            "runtime_directive_enabled": False,
            "runtime_executable": False,
            "validation_ref": validation.validation_id,
            "validation_status": validation.status,
        },
    )
