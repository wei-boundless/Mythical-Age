from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class StrategyPrototype:
    prototype_id: str
    title: str
    match_signals: tuple[str, ...] = ()
    default_reasoning_steps: tuple[str, ...] = ()
    default_deliverables: tuple[str, ...] = ()
    prompt_profile_id: str = ""
    validator_profile_id: str = ""
    authority: str = "runtime.strategy_prototype"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["match_signals"] = list(self.match_signals)
        payload["default_reasoning_steps"] = list(self.default_reasoning_steps)
        payload["default_deliverables"] = list(self.default_deliverables)
        return payload


_PROTOTYPES: dict[str, StrategyPrototype] = {
    "code_change_execution": StrategyPrototype(
        prototype_id="code_change_execution",
        title="Code Change Execution",
        match_signals=("fix", "patch", "修改代码", "修复代码", "实现"),
        default_reasoning_steps=("inspect_relevant_code", "plan_structural_change", "edit_scoped_files", "run_or_explain_verification"),
        default_deliverables=("change_summary", "changed_files", "verification_result_or_limitation"),
        prompt_profile_id="professional.code_fix_execution",
        validator_profile_id="deliverable.code_fix_execution",
    ),
    "test_report_triage": StrategyPrototype(
        prototype_id="test_report_triage",
        title="Test Report Triage",
        match_signals=("失败报告", "long_runner", "triage", "回归"),
        default_reasoning_steps=("extract_failures", "classify_failures_by_system_layer", "infer_structural_root_causes"),
        default_deliverables=("failure_classification", "structural_root_causes", "regression_test_plan", "evidence_limits"),
        prompt_profile_id="professional.test_report_triage",
        validator_profile_id="deliverable.test_report_triage",
    ),
    "runtime_trace_analysis": StrategyPrototype(
        prototype_id="runtime_trace_analysis",
        title="Runtime Trace Analysis",
        match_signals=("trace", "checkpoint", "ledger", "事件链"),
        default_reasoning_steps=("extract_events", "identify_turning_points", "map_state_owners"),
        default_deliverables=("event_chain", "turning_points", "structural_root_causes", "recovery_candidates"),
        prompt_profile_id="professional.runtime_trace_analysis",
        validator_profile_id="deliverable.runtime_trace_analysis",
    ),
    "artifact_delivery": StrategyPrototype(
        prototype_id="artifact_delivery",
        title="Artifact Delivery",
        match_signals=("写入", "生成文件", "产物", "交付"),
        default_reasoning_steps=("understand_artifact_contract", "write_scoped_artifact", "validate_artifact_reference"),
        default_deliverables=("artifact_refs", "completion_status", "limitations"),
        validator_profile_id="deliverable.artifact_delivery",
    ),
    "material_synthesis": StrategyPrototype(
        prototype_id="material_synthesis",
        title="Material Synthesis",
        match_signals=("综合", "材料", "总结"),
        default_reasoning_steps=("read_materials", "extract_facts", "compare_findings", "synthesize_answer"),
        default_deliverables=("material_findings", "cross_material_conclusions", "limitations"),
        prompt_profile_id="professional.material_synthesis",
        validator_profile_id="deliverable.material_synthesis",
    ),
    "game_vertical_slice_delivery": StrategyPrototype(
        prototype_id="game_vertical_slice_delivery",
        title="Game Vertical Slice Delivery",
        match_signals=("游戏", "肉鸽", "roguelike", "垂直切片", "浏览器游戏"),
        default_reasoning_steps=(
            "understand_product_goal",
            "inspect_project_entrypoints",
            "plan_vertical_slice",
            "implement_core_gameplay",
            "integrate_visual_asset",
            "run_browser_verification",
            "write_final_report",
        ),
        default_deliverables=(
            "runnable_artifact_refs",
            "gameplay_acceptance",
            "visual_asset_refs",
            "verification_evidence",
            "final_report",
        ),
        prompt_profile_id="professional.game_vertical_slice_delivery",
        validator_profile_id="deliverable.game_vertical_slice_delivery",
    ),
    "frontend_app_delivery": StrategyPrototype(
        prototype_id="frontend_app_delivery",
        title="Frontend App Delivery",
        match_signals=("前端", "UI", "编辑器", "可运行", "浏览器验证"),
        default_reasoning_steps=(
            "understand_product_goal",
            "inspect_frontend_structure",
            "plan_user_workflow",
            "implement_frontend_changes",
            "run_browser_verification",
            "synthesize_delivery",
        ),
        default_deliverables=("runnable_artifact_refs", "workflow_acceptance", "verification_evidence", "limitations"),
        prompt_profile_id="professional.frontend_app_delivery",
        validator_profile_id="deliverable.frontend_app_delivery",
    ),
    "generic_professional_task": StrategyPrototype(
        prototype_id="generic_professional_task",
        title="Generic Professional Task",
        match_signals=("professional", "long_task", "unknown"),
        default_reasoning_steps=("understand_request", "bind_obligations", "execute_until_obligations_satisfied"),
        default_deliverables=("final_answer",),
    ),
}


def get_strategy_prototype(prototype_id: str) -> StrategyPrototype | None:
    return _PROTOTYPES.get(str(prototype_id or "").strip())


def strategy_prototype_for_task_goal(task_goal_type: str) -> StrategyPrototype:
    normalized = str(task_goal_type or "").strip()
    mapping = {
        "code_fix_execution": "code_change_execution",
        "test_report_triage": "test_report_triage",
        "runtime_trace_analysis": "runtime_trace_analysis",
        "artifact_delivery": "artifact_delivery",
        "material_synthesis": "material_synthesis",
        "game_vertical_slice_delivery": "game_vertical_slice_delivery",
        "frontend_app_delivery": "frontend_app_delivery",
    }
    return _PROTOTYPES.get(mapping.get(normalized, ""), _PROTOTYPES["generic_professional_task"])
