from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskGoalProfile:
    task_domain: str
    task_goal_type: str
    title: str
    description: str
    match_markers: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    default_core_deliverables: tuple[str, ...] = ()
    default_supporting_deliverables: tuple[str, ...] = ()
    default_success_criteria: tuple[str, ...] = ()
    default_verifications: tuple[str, ...] = ()
    default_reasoning_steps: tuple[str, ...] = ()
    required_actions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    strategy_prototype_id: str = ""
    professional_profile_id: str = ""
    validator_profile_id: str = ""
    material_policy: dict[str, Any] | None = None
    authority: str = "task_system.task_goal_profile"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_goal_profile":
            raise ValueError("TaskGoalProfile authority must be task_system.task_goal_profile")
        if not self.task_domain:
            raise ValueError("TaskGoalProfile requires task_domain")
        if not self.task_goal_type:
            raise ValueError("TaskGoalProfile requires task_goal_type")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["match_markers"] = list(self.match_markers)
        payload["required_capabilities"] = list(self.required_capabilities)
        payload["default_core_deliverables"] = list(self.default_core_deliverables)
        payload["default_supporting_deliverables"] = list(self.default_supporting_deliverables)
        payload["default_success_criteria"] = list(self.default_success_criteria)
        payload["default_verifications"] = list(self.default_verifications)
        payload["default_reasoning_steps"] = list(self.default_reasoning_steps)
        payload["required_actions"] = list(self.required_actions)
        payload["forbidden_actions"] = list(self.forbidden_actions)
        payload["material_policy"] = dict(self.material_policy or {})
        return payload


def task_goal_profiles() -> tuple[TaskGoalProfile, ...]:
    return tuple(_PROFILES.values())


def get_task_goal_profile(task_goal_type: str) -> TaskGoalProfile | None:
    normalized = str(task_goal_type or "").strip()
    return _PROFILES.get(normalized)


_COMMON_FORBIDDEN = ("invent_evidence", "visible_tool_markup", "surface_only_summary")


_PROFILES: dict[str, TaskGoalProfile] = {
    "task_graph_node_execution": TaskGoalProfile(
        task_domain="task_graph",
        task_goal_type="task_graph_node_execution",
        title="Task Graph Node Execution",
        description="Execute one orchestration-owned node contract and return typed node output.",
        default_core_deliverables=("node_contract_output", "artifact_refs_or_structured_output", "blocking_issue_if_any"),
        default_reasoning_steps=(
            "read_node_contract_packet",
            "execute_professional_node_role",
            "produce_declared_node_output",
            "report_blocking_issue_if_contract_cannot_be_satisfied",
        ),
        required_actions=("execute_node_contract", "produce_contract_output"),
        forbidden_actions=(*_COMMON_FORBIDDEN, "override_node_role_with_chat_intent", "treat_orchestration_artifact_write_as_code_patch"),
        validator_profile_id="deliverable.task_graph_node_execution",
    ),
    "test_report_triage": TaskGoalProfile(
        task_domain="agent_runtime_quality",
        task_goal_type="test_report_triage",
        title="Test Report Triage",
        description="Analyze failed test or long-run reports and produce structural diagnosis.",
        match_markers=("失败", "fail", "failing", "测试报告", "long_runner", "triage", "根因", "回归"),
        required_capabilities=("workspace_read",),
        default_core_deliverables=("failure_classification", "structural_root_causes", "regression_test_plan", "evidence_limits"),
        default_reasoning_steps=(
            "extract_failures",
            "classify_failures_by_system_layer",
            "infer_structural_root_causes",
            "map_regression_tests",
            "synthesize_final_answer",
        ),
        required_actions=("build_evidence_packet", "validate_deliverables"),
        forbidden_actions=(*_COMMON_FORBIDDEN, "invent_test_result"),
        strategy_prototype_id="test_report_triage",
        professional_profile_id="professional.test_report_triage",
        validator_profile_id="deliverable.test_report_triage",
        material_policy={"structured_extraction": True, "evidence_packet_required": True},
    ),
    "runtime_trace_analysis": TaskGoalProfile(
        task_domain="agent_runtime_quality",
        task_goal_type="runtime_trace_analysis",
        title="Runtime Trace Analysis",
        description="Analyze runtime events, checkpoints, and state owner drift.",
        match_markers=("runtime trace", "运行追踪", "checkpoint", "事件链", "trace"),
        required_capabilities=("workspace_read",),
        default_core_deliverables=("event_chain", "turning_points", "structural_root_causes", "recovery_candidates"),
        default_reasoning_steps=("extract_events", "identify_turning_points", "map_state_owners", "synthesize_recovery_plan"),
        required_actions=("build_evidence_packet", "validate_deliverables"),
        forbidden_actions=_COMMON_FORBIDDEN,
        strategy_prototype_id="runtime_trace_analysis",
        professional_profile_id="professional.runtime_trace_analysis",
        validator_profile_id="deliverable.runtime_trace_analysis",
        material_policy={"structured_extraction": True, "evidence_packet_required": True},
    ),
    "code_fix_execution": TaskGoalProfile(
        task_domain="development",
        task_goal_type="code_fix_execution",
        title="Code Fix Execution",
        description="Inspect relevant code, apply real changes, and verify or explain verification limits.",
        match_markers=("修复", "修改代码", "改代码", "fix", "patch", "bug"),
        required_capabilities=("workspace_read", "workspace_write", "terminal"),
        default_core_deliverables=("change_summary", "changed_files", "verification_result_or_limitation"),
        default_reasoning_steps=("inspect_relevant_code", "plan_structural_change", "edit_scoped_files", "run_or_explain_verification"),
        required_actions=("inspect_code", "apply_real_change", "validate_deliverables"),
        forbidden_actions=(*_COMMON_FORBIDDEN, "claim_unrun_tests_as_passed"),
        strategy_prototype_id="code_change_execution",
        professional_profile_id="professional.code_fix_execution",
        validator_profile_id="deliverable.code_fix_execution",
    ),
    "regression_test_design": TaskGoalProfile(
        task_domain="development",
        task_goal_type="regression_test_design",
        title="Regression Test Design",
        description="Turn a failure or risk into reproducible inputs, assertions, and test placement.",
        match_markers=("回归测试", "测试设计", "补测试", "regression test"),
        required_capabilities=("workspace_read",),
        default_core_deliverables=("reproduction_inputs", "assertions", "coverage_risks", "target_files"),
        default_reasoning_steps=("identify_regression_surface", "design_repro_inputs", "define_assertions", "map_test_files"),
        required_actions=("validate_deliverables",),
        forbidden_actions=_COMMON_FORBIDDEN,
        professional_profile_id="professional.regression_test_design",
        validator_profile_id="deliverable.regression_test_design",
    ),
    "artifact_delivery": TaskGoalProfile(
        task_domain="general",
        task_goal_type="artifact_delivery",
        title="Artifact Delivery",
        description="Produce a scoped file or artifact requested by the user.",
        match_markers=("写入", "生成文件", "产物", "交付"),
        required_capabilities=("workspace_write",),
        default_core_deliverables=("artifact_refs", "completion_status", "limitations"),
        default_reasoning_steps=("understand_artifact_contract", "write_scoped_artifact", "validate_artifact_reference"),
        required_actions=("validate_deliverables",),
        forbidden_actions=_COMMON_FORBIDDEN,
        strategy_prototype_id="artifact_delivery",
        validator_profile_id="deliverable.artifact_delivery",
    ),
    "material_synthesis": TaskGoalProfile(
        task_domain="general",
        task_goal_type="material_synthesis",
        title="Material Synthesis",
        description="Read and synthesize multiple materials with explicit evidence boundaries.",
        match_markers=("综合", "总结", "分析这些", "材料"),
        required_capabilities=("workspace_read",),
        default_core_deliverables=("material_findings", "cross_material_conclusions", "limitations"),
        default_reasoning_steps=("read_materials", "extract_facts", "compare_findings", "synthesize_answer"),
        required_actions=("read_material", "build_evidence_packet"),
        forbidden_actions=_COMMON_FORBIDDEN,
        strategy_prototype_id="material_synthesis",
        professional_profile_id="professional.material_synthesis",
        validator_profile_id="deliverable.material_synthesis",
        material_policy={"evidence_packet_required": True},
    ),
    "game_vertical_slice_delivery": TaskGoalProfile(
        task_domain="development",
        task_goal_type="game_vertical_slice_delivery",
        title="Browser Game Vertical Slice Delivery",
        description="Deliver a runnable browser game vertical slice with gameplay, asset integration, and browser verification.",
        match_markers=("游戏", "肉鸽", "roguelike", "垂直切片", "浏览器游戏"),
        required_capabilities=("workspace_read", "workspace_write", "terminal", "browser", "image_generation_or_asset_integration"),
        default_core_deliverables=("runnable_artifact_refs", "gameplay_acceptance", "visual_asset_refs", "verification_evidence", "final_report"),
        default_supporting_deliverables=("stage_docs",),
        default_reasoning_steps=(
            "understand_product_goal",
            "inspect_project_entrypoints",
            "plan_vertical_slice",
            "implement_core_gameplay",
            "integrate_visual_asset",
            "run_browser_verification",
            "write_final_report",
        ),
        required_actions=("inspect_code", "apply_real_change", "integrate_asset", "run_browser_verification", "validate_deliverables"),
        forbidden_actions=(*_COMMON_FORBIDDEN, "treat_supporting_report_as_core_output", "claim_unverified_game_as_complete"),
        strategy_prototype_id="game_vertical_slice_delivery",
        professional_profile_id="professional.game_vertical_slice_delivery",
        validator_profile_id="deliverable.game_vertical_slice_delivery",
        material_policy={"stage_prompt_profiles_required": True},
    ),
    "frontend_app_delivery": TaskGoalProfile(
        task_domain="development",
        task_goal_type="frontend_app_delivery",
        title="Frontend App Delivery",
        description="Deliver a runnable frontend workflow with source changes and browser verification.",
        match_markers=("前端", "ui", "页面", "编辑器", "应用", "浏览器验证"),
        required_capabilities=("workspace_read", "workspace_write", "terminal", "browser"),
        default_core_deliverables=("runnable_artifact_refs", "workflow_acceptance", "verification_evidence", "limitations"),
        default_reasoning_steps=(
            "understand_product_goal",
            "inspect_frontend_structure",
            "plan_user_workflow",
            "implement_frontend_changes",
            "run_browser_verification",
            "synthesize_delivery",
        ),
        required_actions=("inspect_code", "apply_real_change", "run_browser_verification", "validate_deliverables"),
        forbidden_actions=(*_COMMON_FORBIDDEN, "surface_only_ui_claim", "claim_unverified_frontend_as_complete"),
        strategy_prototype_id="frontend_app_delivery",
        professional_profile_id="professional.frontend_app_delivery",
        validator_profile_id="deliverable.frontend_app_delivery",
        material_policy={"stage_prompt_profiles_required": True},
    ),
}
