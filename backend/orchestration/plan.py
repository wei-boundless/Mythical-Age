from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .candidates import CandidateSet


@dataclass(slots=True, frozen=True)
class OrchestrationStagePreview:
    stage_id: str
    plan_id: str
    stage_type: str
    stage_goal: str
    executor_hint: str = "model"
    candidate_refs: tuple[str, ...] = ()
    operation_refs: tuple[str, ...] = ()
    policy_refs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    blocked_reason: str = "preview_only"
    preview_only: bool = True
    runtime_executable: bool = False
    authority: str = "orchestration_stage_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.preview_only:
            raise ValueError("OrchestrationStagePreview must remain preview_only")
        if self.runtime_executable:
            raise ValueError("OrchestrationStagePreview cannot be runtime executable")
        if self.authority != "orchestration_stage_preview":
            raise ValueError("OrchestrationStagePreview cannot carry execution authority")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidate_refs"] = list(self.candidate_refs)
        payload["operation_refs"] = list(self.operation_refs)
        payload["policy_refs"] = list(self.policy_refs)
        payload["depends_on"] = list(self.depends_on)
        return payload


@dataclass(slots=True, frozen=True)
class OrchestrationPlanPreview:
    plan_id: str
    task_id: str
    topology_ref: str
    topology_mode: str = "single_agent"
    task_contract_ref: str = ""
    task_prompt_contract_ref: str = ""
    resource_policy_ref: str = ""
    prompt_manifest_ref: str = ""
    selected_candidate_refs: tuple[str, ...] = ()
    stages: tuple[OrchestrationStagePreview, ...] = ()
    preview_only: bool = True
    adopted: bool = False
    runtime_executable: bool = False
    authority: str = "orchestration_plan_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.preview_only:
            raise ValueError("OrchestrationPlanPreview must remain preview_only")
        if self.adopted:
            raise ValueError("OrchestrationPlanPreview cannot be adopted")
        if self.runtime_executable:
            raise ValueError("OrchestrationPlanPreview cannot be runtime executable")
        if self.authority != "orchestration_plan_preview":
            raise ValueError("OrchestrationPlanPreview cannot carry execution authority")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["selected_candidate_refs"] = list(self.selected_candidate_refs)
        payload["stages"] = [stage.to_dict() for stage in self.stages]
        return payload


def build_single_agent_plan_preview(
    *,
    task_id: str,
    task_contract_ref: str,
    task_prompt_contract_ref: str,
    resource_policy_ref: str,
    prompt_manifest_ref: str,
    topology_ref: str,
    operation_refs: tuple[str, ...] = (),
    candidates: CandidateSet | None = None,
) -> OrchestrationPlanPreview:
    plan_id = f"orchplan:{task_id}:single-agent:preview"
    selected_candidate_refs = tuple(
        candidate.candidate_id for candidate in (candidates.candidates if candidates is not None else [])
    )
    stage = OrchestrationStagePreview(
        stage_id=f"orchstage:{task_id}:main-agent:preview",
        plan_id=plan_id,
        stage_type="main_agent_response",
        stage_goal="Build a single-agent response plan without executing runtime side effects.",
        executor_hint="model",
        candidate_refs=selected_candidate_refs,
        operation_refs=operation_refs,
        policy_refs=(resource_policy_ref,) if resource_policy_ref else (),
        blocked_reason="preview_only",
        diagnostics={
            "single_agent_main_chain": True,
            "runtime_directive_enabled": False,
            "runtime_executable": False,
        },
    )
    return OrchestrationPlanPreview(
        plan_id=plan_id,
        task_id=task_id,
        topology_ref=topology_ref,
        topology_mode="single_agent",
        task_contract_ref=task_contract_ref,
        task_prompt_contract_ref=task_prompt_contract_ref,
        resource_policy_ref=resource_policy_ref,
        prompt_manifest_ref=prompt_manifest_ref,
        selected_candidate_refs=selected_candidate_refs,
        stages=(stage,),
        diagnostics={
            "single_agent_main_chain": True,
            "stage_count": 1,
            "candidate_count": len(selected_candidate_refs),
            "runtime_directive_enabled": False,
            "runtime_executable": False,
        },
    )
