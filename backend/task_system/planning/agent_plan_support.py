from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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


@dataclass(frozen=True, slots=True)
class PlanCoverageReview:
    review_id: str
    plan_id: str
    semantic_contract_ref: str
    passed: bool
    gate_status: str = "passed"
    covered_actions: tuple[str, ...] = ()
    missing_actions: tuple[str, ...] = ()
    covered_deliverables: tuple[str, ...] = ()
    missing_deliverables: tuple[str, ...] = ()
    unsupported_skips: tuple[str, ...] = ()
    required_replan_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.plan_coverage_review"

    def __post_init__(self) -> None:
        if self.authority != "runtime.plan_coverage_review":
            raise ValueError("PlanCoverageReview authority must be runtime.plan_coverage_review")
        if not self.review_id:
            raise ValueError("PlanCoverageReview requires review_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["covered_actions"] = list(self.covered_actions)
        payload["missing_actions"] = list(self.missing_actions)
        payload["covered_deliverables"] = list(self.covered_deliverables)
        payload["missing_deliverables"] = list(self.missing_deliverables)
        payload["unsupported_skips"] = list(self.unsupported_skips)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


class AgentPlanRequired(RuntimeError):
    def __init__(self, *, requirement: AgentPlanRequirement) -> None:
        self.requirement = requirement
        super().__init__(str(requirement.reason or "agent_plan_required"))


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
    planner_request = _readonly_planner_request(task_id=task_id, semantic_contract=contract)
    if model_plan is not None:
        return _with_plan_diagnostics(model_plan, {"readonly_planner_request": planner_request})
    raise AgentPlanRequired(
        requirement=_build_agent_plan_requirement(
            task_id=task_id,
            semantic_contract=contract,
            execution_obligation=execution_obligation,
            model_plan_diagnostics=model_diagnostics,
            planner_request=planner_request,
        )
    )


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


def review_plan_coverage(
    *,
    task_id: str,
    semantic_contract: dict[str, Any] | None,
    agent_plan_draft: dict[str, Any] | None,
) -> PlanCoverageReview:
    contract = dict(semantic_contract or {})
    plan = dict(agent_plan_draft or {})
    plan_source = str(plan.get("source") or dict(plan.get("diagnostics") or {}).get("source") or "").strip()
    plan_status = str(plan.get("plan_status") or "").strip()
    required_actions = _required_actions_for_review(contract)
    required_deliverables = _required_deliverables_for_review(contract)
    steps = [dict(item) for item in list(plan.get("steps") or []) if isinstance(item, dict)]
    covered_actions = _covered_items(steps, required_actions)
    covered_deliverables = _covered_items(steps, required_deliverables)
    missing_actions = [item for item in required_actions if item not in covered_actions]
    missing_deliverables = [item for item in required_deliverables if item not in covered_deliverables]
    unsupported_skips = [
        str(step.get("step_id") or "")
        for step in steps
        if str(step.get("may_skip_if") or "").strip() and not _skip_is_supported(step)
    ]
    plan_present = bool(steps)
    passed = bool(plan_present and not missing_actions and not missing_deliverables and not unsupported_skips)
    replan_reasons = []
    if not plan_present:
        replan_reasons.append("agent_plan_draft_missing_or_empty")
    if missing_actions:
        replan_reasons.append("missing_required_actions")
    if missing_deliverables:
        replan_reasons.append("missing_required_deliverables")
    if unsupported_skips:
        replan_reasons.append("unsupported_skip_conditions")
    return PlanCoverageReview(
        review_id=f"plan-coverage:{task_id or 'runtime'}",
        plan_id=str(plan.get("plan_id") or ""),
        semantic_contract_ref=str(contract.get("contract_id") or ""),
        passed=passed,
        gate_status="passed" if passed else "blocked_replan_required",
        covered_actions=tuple(covered_actions),
        missing_actions=tuple(missing_actions),
        covered_deliverables=tuple(covered_deliverables),
        missing_deliverables=tuple(missing_deliverables),
        unsupported_skips=tuple(item for item in unsupported_skips if item),
        required_replan_reason="" if passed else ",".join(replan_reasons or ["agent_plan_draft_does_not_cover_semantic_contract"]),
        diagnostics={
            "hard_gate": True,
            "execution_must_not_start_when_failed": not passed,
            "plan_present": plan_present,
            "plan_source": plan_source,
            "plan_status": plan_status,
            "required_actions": required_actions,
            "required_deliverables": required_deliverables,
        },
    )


def _build_agent_plan_requirement(
    *,
    task_id: str,
    semantic_contract: dict[str, Any] | None,
    execution_obligation: dict[str, Any] | None = None,
    model_plan_diagnostics: dict[str, Any] | None = None,
    planner_request: dict[str, Any] | None = None,
) -> AgentPlanRequirement:
    contract = dict(semantic_contract or {})
    obligation = dict(execution_obligation or contract.get("execution_obligation") or {})
    diagnostics = dict(model_plan_diagnostics or {})
    return AgentPlanRequirement(
        requirement_id=f"agent-plan-requirement:{task_id or 'runtime'}",
        task_goal_type=str(contract.get("task_goal_type") or "general").strip(),
        semantic_contract_ref=str(contract.get("contract_id") or ""),
        required_actions=tuple(_string_list(contract.get("required_actions"))),
        required_deliverables=tuple(_string_list(contract.get("deliverables"))),
        planner_request=dict(planner_request or _readonly_planner_request(task_id=task_id, semantic_contract=contract)),
        reason="agent_plan_invalid" if str(diagnostics.get("model_plan_status") or "") == "rejected_invalid" else "agent_plan_required",
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


def _readonly_planner_request(*, task_id: str, semantic_contract: dict[str, Any]) -> dict[str, Any]:
    contract = _model_visible_semantic_contract(semantic_contract)
    return {
        "request_id": f"readonly-planner-request:{task_id or 'runtime'}",
        "semantic_contract_ref": str(contract.get("contract_id") or ""),
        "semantic_contract": contract,
        "workspace_observations": [],
        "output_schema": {
            "authority": "runtime.agent_plan_draft",
            "required": ["plan_id", "task_goal_type", "semantic_contract_ref", "steps", "authority"],
            "step_required": ["step_id", "title", "purpose", "evidence_expectations"],
        },
        "role_prompt": "\n".join(
            [
                "你是一名只读任务计划员。",
                "你只根据语义任务合同、用户显式流程和已经存在的真实观察生成可执行计划草稿。",
                "你不修改文件，不运行命令，不宣称已经完成任何执行动作。",
                "每个计划步骤必须说明目的、预期产物、需要的操作类型和证据期望。",
                "请只输出符合 runtime.agent_plan_draft schema 的结构化结果。",
            ]
        ),
        "diagnostics": {
            "request_contract_only": True,
            "model_call_performed": False,
            "readonly": True,
            "expected_response_authority": "runtime.agent_plan_draft",
        },
    }


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
    if str(raw.get("authority") or "runtime.agent_plan_draft").strip() != "runtime.agent_plan_draft":
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


def _model_visible_semantic_contract(contract: dict[str, Any]) -> dict[str, Any]:
    blocked = {"diagnostics", "internal_state", "raw_current_turn_context"}
    return {key: value for key, value in dict(contract or {}).items() if key not in blocked}


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


def _required_actions_for_review(contract: dict[str, Any]) -> list[str]:
    actions = [str(item).strip() for item in list(contract.get("required_actions") or []) if str(item).strip()]
    allowed = {
        "read_material",
        "inspect_code",
        "apply_real_change",
        "integrate_asset",
        "run_browser_verification",
        "run_verification",
        "validate_deliverables",
    }
    return [item for item in actions if item in allowed]


def _required_deliverables_for_review(contract: dict[str, Any]) -> list[str]:
    deliverables = [str(item).strip() for item in list(contract.get("deliverables") or []) if str(item).strip()]
    task_goal_type = str(contract.get("task_goal_type") or "").strip()
    if task_goal_type == "game_vertical_slice_delivery":
        allowed = {"runnable_artifact_refs", "gameplay_acceptance", "visual_asset_refs", "verification_evidence", "final_report"}
        return [item for item in deliverables if item in allowed]
    if task_goal_type == "frontend_app_delivery":
        allowed = {"runnable_artifact_refs", "workflow_acceptance", "verification_evidence", "limitations"}
        return [item for item in deliverables if item in allowed]
    return deliverables


def _covered_items(steps: list[dict[str, Any]], required: list[str]) -> list[str]:
    return [item for item in required if any(_step_covers(step, item) for step in steps)]


def _step_covers(step: dict[str, Any], item: str) -> bool:
    refs = {
        str(value).strip()
        for key in ("contract_refs", "expected_outputs", "evidence_expectations")
        for value in list(step.get(key) or [])
        if str(value).strip()
    }
    step_id = str(step.get("step_id") or "").strip()
    if item in refs or item == step_id:
        return True
    aliases = {
        "runnable_artifact_refs": {"source_changes", "file_write", "apply_real_change"},
        "visual_asset_refs": {"asset_refs", "asset_file", "asset_visible", "integrate_asset"},
        "verification_evidence": {"verification_evidence", "browser_open", "command_run", "test_result"},
        "gameplay_acceptance": {"gameplay_acceptance", "gameplay_check", "implement_core_gameplay"},
        "workflow_acceptance": {"workflow_acceptance", "workflow_check", "implement_frontend_changes"},
        "validate_deliverables": {"completion_judgment", "final_answer"},
        "run_verification": {"run_browser_verification", "verification_evidence", "browser_open", "command_run", "test_result"},
        "final_report": {"final_report", "write_final_report"},
        "limitations": {"limitations", "final_answer"},
    }
    return bool(refs.intersection(aliases.get(item, set())))


def _skip_is_supported(step: dict[str, Any]) -> bool:
    text = str(step.get("may_skip_if") or "").lower()
    return any(token in text for token in ("blocked", "not applicable", "user forbids", "无法", "阻断", "不适用"))


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
