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
    source: str = "scaffold"
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


def build_agent_plan_draft(
    *,
    task_id: str,
    semantic_contract: dict[str, Any] | None,
    execution_obligation: dict[str, Any] | None = None,
    model_agent_plan_draft: dict[str, Any] | None = None,
) -> AgentPlanDraft:
    contract = dict(semantic_contract or {})
    obligation = dict(execution_obligation or contract.get("execution_obligation") or {})
    task_goal_type = str(contract.get("task_goal_type") or "general").strip()
    contract_ref = str(contract.get("contract_id") or "")
    model_plan, model_diagnostics = _model_plan_from_payload(
        model_agent_plan_draft,
        task_id=task_id,
        contract=contract,
    )
    planner_request = build_readonly_planner_request(
        task_id=task_id,
        semantic_contract=contract,
        domain_playbook=dict(dict(contract.get("diagnostics") or {}).get("task_domain_binding") or {}),
    ).to_dict()
    if model_plan is not None:
        return _with_plan_diagnostics(model_plan, {"readonly_planner_request": planner_request})
    return AgentPlanDraft(
        plan_id=f"agent-plan:{task_id or 'runtime'}",
        task_goal_type=task_goal_type,
        semantic_contract_ref=contract_ref,
        steps=tuple(_steps_for_contract(contract=contract, obligation=obligation)),
        source="deterministic_scaffold",
        model_plan_draft_ref=str(model_diagnostics.get("draft_id") or ""),
        plan_status="scaffold_fallback",
        assumptions=("deterministic_scaffold_until_model_plan_generation_is_enabled",),
        diagnostics={
            "source": "runtime.agent_plan_draft.scaffold",
            **model_diagnostics,
            "model_plan_absent": bool(model_diagnostics.get("model_plan_absent", True)),
            "model_plan_authority_used": False,
            "readonly_planner_request": planner_request,
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


def _steps_for_contract(*, contract: dict[str, Any], obligation: dict[str, Any]) -> list[AgentPlanStep]:
    task_goal_type = str(contract.get("task_goal_type") or "").strip()
    if task_goal_type == "game_vertical_slice_delivery":
        steps = []
        if "read_material" in {str(item).strip() for item in list(contract.get("required_actions") or []) if str(item).strip()}:
            steps.append(_step("read_required_materials", "读取必要材料", "读取并抽取任务所需材料证据。", ("op.read_file",), ("material_facts",), ("material_observation",), ("read_material",)))
        steps.extend([
            _step("inspect_project", "勘察项目入口", "确认项目结构、启动方式和游戏落点。", ("op.read_file", "op.search_text"), ("entrypoint_map",), ("source_tree_observation",), ("inspect_code",)),
            _step("plan_vertical_slice", "规划垂直切片", "把用户目标拆成玩法、资源、验证和报告阶段。", ("op.model_response",), ("implementation_plan",), ("plan_coverage_notes",), ("gameplay_acceptance", "visual_asset_refs")),
            _step("implement_core_gameplay", "实现核心玩法", "实现可观察的移动、攻击、敌人、推进和 HUD。", ("op.write_file", "op.edit_file"), ("source_changes",), ("file_write", "gameplay_check"), ("apply_real_change", "gameplay_acceptance")),
            _step("integrate_visual_asset", "接入视觉资源", "生成或接入至少一个真实可见的视觉资源。", ("op.write_file", "op.edit_file"), ("asset_refs",), ("asset_file", "asset_visible"), ("integrate_asset", "visual_asset_refs")),
            _step("run_browser_verification", "运行并浏览器验证", "启动项目或打开入口，检查画面、资源和关键玩法。", ("op.shell", "op.browser"), ("verification_evidence",), ("browser_open", "canvas_pixel_check", "gameplay_check"), ("run_browser_verification", "verification_evidence")),
            _step("write_final_report", "撰写最终报告", "只在核心实现和验证之后汇报变更、证据和限制。", ("op.write_file", "op.model_response"), ("final_report",), ("file_write", "completion_judgment"), ("final_report",)),
        ])
        return steps
    if task_goal_type == "frontend_app_delivery":
        return [
            _step("inspect_frontend_structure", "勘察前端结构", "确认入口、组件、路由和运行方式。", ("op.read_file", "op.search_text"), ("frontend_structure",), ("source_tree_observation",), ("inspect_code",)),
            _step("plan_user_workflow", "规划用户工作流", "明确要交付的核心页面和交互流程。", ("op.model_response",), ("workflow_plan",), ("plan_coverage_notes",), ("workflow_acceptance",)),
            _step("implement_frontend_changes", "实现前端变更", "完成真实源码修改和交互状态。", ("op.write_file", "op.edit_file"), ("source_changes",), ("file_write", "workflow_check"), ("apply_real_change", "workflow_acceptance")),
            _step("run_browser_verification", "运行并浏览器验证", "打开页面并检查关键工作流。", ("op.shell", "op.browser"), ("verification_evidence",), ("browser_open", "browser_dom_snapshot", "workflow_check"), ("run_browser_verification", "verification_evidence")),
            _step("synthesize_delivery", "交付说明", "汇总变更、验证证据和限制。", ("op.model_response",), ("final_answer",), ("completion_judgment",), ("limitations",)),
        ]
    steps: list[AgentPlanStep] = []
    actions = {str(item).strip() for item in list(contract.get("required_actions") or []) if str(item).strip()}
    if "read_material" in actions or list(obligation.get("required_reads") or []):
        steps.append(_step("read_required_materials", "读取必要材料", "读取并抽取任务所需材料证据。", ("op.read_file",), ("material_facts",), ("material_observation",), ("read_material",)))
    if "inspect_code" in actions:
        steps.append(_step("inspect_relevant_code", "检查相关代码", "理解相关模块职责和改动边界。", ("op.read_file", "op.search_text"), ("code_context",), ("source_tree_observation",), ("inspect_code",)))
    if "apply_real_change" in actions:
        steps.append(_step("apply_real_change", "执行真实修改", "按合同完成真实文件或代码变更。", ("op.write_file", "op.edit_file"), ("source_changes",), ("file_write",), ("apply_real_change",)))
    if "run_verification" in actions or "run_browser_verification" in actions or list(obligation.get("required_verifications") or []):
        operations = ("op.shell", "op.browser") if "run_browser_verification" in actions else ("op.shell",)
        steps.append(_step("run_verification", "执行验证", "运行真实验证或记录无法验证的限制。", operations, ("verification_evidence",), ("command_run", "test_result"), ("verification_evidence",)))
    steps.append(_step("synthesize_final_answer", "形成最终交付", "根据证据汇报结果、限制和下一步。", ("op.model_response",), ("final_answer",), ("completion_judgment",), tuple(contract.get("deliverables") or ())))
    return steps


def _step(
    step_id: str,
    title: str,
    purpose: str,
    required_operations: tuple[str, ...],
    expected_outputs: tuple[str, ...],
    evidence_expectations: tuple[str, ...],
    contract_refs: tuple[str, ...],
) -> AgentPlanStep:
    return AgentPlanStep(
        step_id=step_id,
        title=title,
        purpose=purpose,
        required_operations=required_operations,
        expected_outputs=expected_outputs,
        evidence_expectations=evidence_expectations,
        contract_refs=contract_refs,
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
