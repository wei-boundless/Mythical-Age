from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .planner_verifier_requests import build_readonly_planner_request


@dataclass(frozen=True, slots=True)
class AgentPlanStep:
    step_id: str
    title: str
    purpose: str
    required_operations: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    evidence_expectations: tuple[str, ...] = ()
    contract_refs: tuple[str, ...] = ()
    may_skip_if: str = ""
    authority: str = "runtime.agent_plan_step"

    def __post_init__(self) -> None:
        if self.authority != "runtime.agent_plan_step":
            raise ValueError("AgentPlanStep authority must be runtime.agent_plan_step")
        if not self.step_id:
            raise ValueError("AgentPlanStep requires step_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_operations"] = list(self.required_operations)
        payload["expected_outputs"] = list(self.expected_outputs)
        payload["evidence_expectations"] = list(self.evidence_expectations)
        payload["contract_refs"] = list(self.contract_refs)
        return payload


@dataclass(frozen=True, slots=True)
class AgentPlanDraft:
    plan_id: str
    task_goal_type: str
    semantic_contract_ref: str
    steps: tuple[AgentPlanStep, ...] = ()
    source: str = "model_agent_plan_draft"
    model_plan_draft_ref: str = ""
    plan_status: str = "accepted"
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.agent_plan_draft"

    def __post_init__(self) -> None:
        if self.authority != "runtime.agent_plan_draft":
            raise ValueError("AgentPlanDraft authority must be runtime.agent_plan_draft")
        if not self.plan_id:
            raise ValueError("AgentPlanDraft requires plan_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [item.to_dict() for item in self.steps]
        payload["assumptions"] = list(self.assumptions)
        payload["limitations"] = list(self.limitations)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


@dataclass(frozen=True, slots=True)
class AgentPlanRequirement:
    requirement_id: str
    task_goal_type: str
    semantic_contract_ref: str
    required_actions: tuple[str, ...] = ()
    required_deliverables: tuple[str, ...] = ()
    planner_request: dict[str, Any] = field(default_factory=dict)
    reason: str = "agent_plan_required"
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.agent_plan_requirement"

    def __post_init__(self) -> None:
        if self.authority != "runtime.agent_plan_requirement":
            raise ValueError("AgentPlanRequirement authority must be runtime.agent_plan_requirement")
        if not self.requirement_id:
            raise ValueError("AgentPlanRequirement requires requirement_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_actions"] = list(self.required_actions)
        payload["required_deliverables"] = list(self.required_deliverables)
        payload["planner_request"] = dict(self.planner_request or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def build_agent_plan_draft(
    *,
    task_id: str,
    semantic_contract: dict[str, Any] | None,
    execution_obligation: dict[str, Any] | None = None,
    model_agent_plan_draft: dict[str, Any] | None = None,
) -> AgentPlanDraft:
    contract = dict(semantic_contract or {})
    model_plan, model_diagnostics = _model_plan_from_payload(
        model_agent_plan_draft,
        task_id=task_id,
        contract=contract,
    )
    planner_request = build_readonly_planner_request(
        task_id=task_id,
        semantic_contract=contract,
    ).to_dict()
    if model_plan is not None:
        return _with_plan_diagnostics(model_plan, {"readonly_planner_request": planner_request})
    raise AgentPlanRequired(
        requirement=build_agent_plan_requirement(
            task_id=task_id,
            semantic_contract=contract,
            execution_obligation=execution_obligation,
            model_plan_diagnostics=model_diagnostics,
            planner_request=planner_request,
        )
    )


def build_agent_plan_requirement(
    *,
    task_id: str,
    semantic_contract: dict[str, Any] | None,
    execution_obligation: dict[str, Any] | None = None,
    model_plan_diagnostics: dict[str, Any] | None = None,
    planner_request: dict[str, Any] | None = None,
) -> AgentPlanRequirement:
    contract = dict(semantic_contract or {})
    obligation = dict(execution_obligation or contract.get("execution_obligation") or {})
    request = dict(
        planner_request
        or build_readonly_planner_request(
            task_id=task_id,
            semantic_contract=contract,
        ).to_dict()
    )
    diagnostics = dict(model_plan_diagnostics or {})
    return AgentPlanRequirement(
        requirement_id=f"agent-plan-requirement:{task_id or 'runtime'}",
        task_goal_type=str(contract.get("task_goal_type") or "general").strip(),
        semantic_contract_ref=str(contract.get("contract_id") or ""),
        required_actions=tuple(_string_list(contract.get("required_actions"))),
        required_deliverables=tuple(_string_list(contract.get("deliverables"))),
        planner_request=request,
        reason=(
            "agent_plan_invalid"
            if str(diagnostics.get("model_plan_status") or "") == "rejected_invalid"
            else "agent_plan_required"
        ),
        diagnostics={
            "source": "runtime.agent_plan_requirement",
            **diagnostics,
            "model_plan_absent": bool(diagnostics.get("model_plan_absent", True)),
            "model_plan_authority_used": False,
            "required_actions": list(contract.get("required_actions") or []),
            "deliverables": list(contract.get("deliverables") or []),
            "required_reads": list(obligation.get("required_reads") or []),
            "required_verifications": list(obligation.get("required_verifications") or []),
        },
    )


class AgentPlanRequired(RuntimeError):
    def __init__(self, *, requirement: AgentPlanRequirement) -> None:
        self.requirement = requirement
        super().__init__(str(requirement.reason or "agent_plan_required"))


def empty_agent_plan_draft(
    *,
    task_id: str,
    semantic_contract: dict[str, Any] | None,
    requirement: AgentPlanRequirement | dict[str, Any] | None = None,
) -> AgentPlanDraft:
    contract = dict(semantic_contract or {})
    requirement_payload = requirement.to_dict() if isinstance(requirement, AgentPlanRequirement) else dict(requirement or {})
    requirement_diagnostics = dict(requirement_payload.get("diagnostics") or {})
    return AgentPlanDraft(
        plan_id=f"agent-plan:{task_id or 'runtime'}",
        task_goal_type=str(contract.get("task_goal_type") or "general").strip(),
        semantic_contract_ref=str(contract.get("contract_id") or ""),
        steps=(),
        source="agent_plan_required",
        model_plan_draft_ref=str(requirement_diagnostics.get("draft_id") or ""),
        plan_status=str(requirement_payload.get("reason") or "agent_plan_required"),
        diagnostics={
            "source": "runtime.agent_plan_draft.empty",
            **requirement_diagnostics,
            "model_plan_absent": bool(requirement_diagnostics.get("model_plan_absent", True)),
            "model_plan_authority_used": False,
            "agent_plan_requirement_ref": str(requirement_payload.get("requirement_id") or ""),
            "required_actions": list(contract.get("required_actions") or []),
            "deliverables": list(contract.get("deliverables") or []),
        },
    )


def agent_plan_draft_from_payload(
    payload: dict[str, Any] | None,
    *,
    task_id: str,
    semantic_contract: dict[str, Any] | None,
) -> tuple[AgentPlanDraft | None, dict[str, Any]]:
    return _model_plan_from_payload(
        payload,
        task_id=task_id,
        contract=dict(semantic_contract or {}),
    )


def with_agent_plan_diagnostics(plan: AgentPlanDraft, extra: dict[str, Any]) -> AgentPlanDraft:
    return _with_plan_diagnostics(plan, extra)


def _model_plan_from_payload(
    payload: dict[str, Any] | None,
    *,
    task_id: str,
    contract: dict[str, Any],
) -> tuple[AgentPlanDraft | None, dict[str, Any]]:
    raw = dict(payload or {})
    if not raw:
        return None, {
            "model_plan_status": "absent",
            "model_plan_absent": True,
            "model_plan_authority_used": False,
        }
    draft_id = str(raw.get("plan_id") or raw.get("draft_id") or f"agent-plan:{task_id or 'runtime'}").strip()
    errors: list[str] = []
    authority = str(raw.get("authority") or "runtime.agent_plan_draft").strip()
    if authority != "runtime.agent_plan_draft":
        errors.append("invalid_authority")
    steps_payload = raw.get("steps")
    if not isinstance(steps_payload, list) or not steps_payload:
        errors.append("steps_must_be_non_empty_list")
        steps_payload = []
    steps: list[AgentPlanStep] = []
    seen: set[str] = set()
    for index, item in enumerate(steps_payload):
        if not isinstance(item, dict):
            errors.append(f"step_{index + 1}_must_be_object")
            continue
        step_id = str(item.get("step_id") or "").strip()
        title = str(item.get("title") or "").strip()
        purpose = str(item.get("purpose") or "").strip()
        if not step_id:
            errors.append(f"step_{index + 1}_missing_step_id")
            continue
        if step_id in seen:
            errors.append(f"duplicate_step_id:{step_id}")
            continue
        if not title:
            errors.append(f"step_{step_id}_missing_title")
        if not purpose:
            errors.append(f"step_{step_id}_missing_purpose")
        seen.add(step_id)
        steps.append(
            AgentPlanStep(
                step_id=step_id,
                title=title or step_id,
                purpose=purpose or title or step_id,
                required_operations=tuple(_string_list(item.get("required_operations"))),
                expected_outputs=tuple(_string_list(item.get("expected_outputs"))),
                evidence_expectations=tuple(_string_list(item.get("evidence_expectations"))),
                contract_refs=tuple(_string_list(item.get("contract_refs"))),
                may_skip_if=str(item.get("may_skip_if") or "").strip(),
            )
        )
    contract_ref = str(contract.get("contract_id") or "")
    semantic_ref = str(raw.get("semantic_contract_ref") or contract_ref).strip()
    if semantic_ref and contract_ref and semantic_ref != contract_ref:
        errors.append("semantic_contract_ref_mismatch")
    if errors:
        return None, {
            "model_plan_status": "rejected_invalid",
            "model_plan_absent": False,
            "model_plan_authority_used": False,
            "draft_id": draft_id,
            "validation_errors": errors,
        }
    return (
        AgentPlanDraft(
            plan_id=draft_id,
            task_goal_type=str(raw.get("task_goal_type") or contract.get("task_goal_type") or "general").strip(),
            semantic_contract_ref=contract_ref,
            steps=tuple(steps),
            source="model_agent_plan_draft",
            model_plan_draft_ref=draft_id,
            plan_status="accepted",
            assumptions=tuple(_string_list(raw.get("assumptions"))),
            limitations=tuple(_string_list(raw.get("limitations"))),
            diagnostics={
                **dict(raw.get("diagnostics") or {}),
                "source": "runtime.agent_plan_draft.model",
                "model_plan_status": "accepted",
                "model_plan_absent": False,
                "model_plan_authority_used": True,
                "required_actions": list(contract.get("required_actions") or []),
                "deliverables": list(contract.get("deliverables") or []),
            },
        ),
        {
            "model_plan_status": "accepted",
            "model_plan_absent": False,
            "model_plan_authority_used": True,
            "draft_id": draft_id,
            "validation_errors": [],
        },
    )


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, (list, tuple)):
        return [str(value).strip()] if str(value).strip() else []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _with_plan_diagnostics(plan: AgentPlanDraft, extra: dict[str, Any]) -> AgentPlanDraft:
    return AgentPlanDraft(
        plan_id=plan.plan_id,
        task_goal_type=plan.task_goal_type,
        semantic_contract_ref=plan.semantic_contract_ref,
        steps=plan.steps,
        source=plan.source,
        model_plan_draft_ref=plan.model_plan_draft_ref,
        plan_status=plan.plan_status,
        assumptions=plan.assumptions,
        limitations=plan.limitations,
        diagnostics={**dict(plan.diagnostics or {}), **dict(extra or {})},
    )
