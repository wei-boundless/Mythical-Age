from __future__ import annotations

from pathlib import Path

from agent_system.assembly.runtime_bundle_builder import build_orchestration_runtime_bundle
from orchestration.runtime_lane_registry import DEFAULT_RUNTIME_LANE_REGISTRY
from runtime.contracts.deliverable_validator import validate_deliverable
from runtime.memory.evidence_packet import build_evidence_packet
from prompting.professional_profiles import get_professional_prompt_profile
from request_intent.request_signals import build_request_signals
from task_system.services.assembly_builder import build_task_execution_assembly_bundle
from tests.support.runtime_stubs import model_turn_context
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope


def _professional_triage_inputs(user_goal: str) -> dict[str, object]:
    turn_context = model_turn_context(
        action_intent="read_context",
        work_mode="read_only_analysis",
        interaction_intent="review",
        target_objects=["backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"],
        desired_outcome=user_goal,
        task_goal_type="test_report_triage",
        task_domain="testing",
    )
    return {
        "query_understanding": {
            **build_request_signals(user_goal).to_dict(),
            "model_turn_decision": dict(turn_context["model_turn_decision"]),
            "request_facts": dict(turn_context["request_facts"]),
            "boundary_policy": dict(turn_context["boundary_policy"]),
            "action_permit": dict(turn_context["action_permit"]),
        },
        "current_turn_context": dict(turn_context),
    }


def test_professional_mode_recipe_uses_new_runtime_names() -> None:
    user_goal = (
        "分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json "
        "里的失败，输出失败归类、结构性根因和回归测试建议。"
    )
    bundle = build_task_execution_assembly_bundle(
        base_dir=Path("backend"),
        session_id="session-professional-recipe",
        task_id="task-professional-recipe",
        user_goal=user_goal,
        source="test",
        **_professional_triage_inputs(user_goal),
    )

    shape = bundle["execution_shape"]
    recipe = bundle["selected_recipe"]
    metadata = recipe["metadata"]

    assert shape["recipe_id"] == "runtime.recipe.professional_task"
    assert shape["execution_kind"] == "professional_mode"
    assert metadata["runtime_driver"] == "professional_task_run"
    assert metadata["interaction_mode"] == "professional_mode"
    assert metadata["runtime_lane_hint"] == "professional_task"
    assert metadata["task_requirement_contract"]["task_goal_type"] == "test_report_triage"
    retired_mode_key = "_".join(("autonomy", "mode"))
    assert retired_mode_key not in metadata


def test_professional_profile_is_injected_into_soul_runtime_view() -> None:
    user_goal = (
        "分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json "
        "里的失败，输出失败归类、结构性根因和回归测试建议。"
    )
    task_bundle = build_task_execution_assembly_bundle(
        base_dir=Path("backend"),
        session_id="session-professional-prompt",
        task_id="task-professional-prompt",
        user_goal=user_goal,
        source="test",
        **_professional_triage_inputs(user_goal),
    )
    runtime = build_orchestration_runtime_bundle(
        base_dir=Path("backend"),
        session_id="session-professional-prompt",
        task_id="task-professional-prompt",
        user_goal=user_goal,
        task_assembly_bundle=task_bundle,
        current_turn_context=task_bundle["current_turn_context"],
    )

    orchestration = runtime["task_body_orchestration"]
    sections = {
        section["section_id"]: section
        for section in orchestration["soul_runtime_view"]["sections"]
    }

    assert orchestration["projection_requirement"]["interaction_mode"] == "professional_mode"
    assert orchestration["projection_requirement"]["projection_strength"] == "style_only"
    assert "professional_profile_section" in sections
    assert "专业长任务测试报告诊断员" in sections["professional_profile_section"]["content"]
    assert "semantic_task_section" in sections
    assert "test_report_triage" in sections["semantic_task_section"]["content"]
    assert "agent_plan_section" in sections
    assert "计划" in sections["agent_plan_section"]["content"]
    assert "agent_todo" in sections["agent_plan_section"]["content"]
    assert "plan_coverage_section" in sections
    assert "计划覆盖审查" in sections["plan_coverage_section"]["content"]

    requirement = task_bundle["operation_requirement"]
    assert "op.agent_todo" in set(requirement["required_operations"])


def test_evidence_packet_and_validator_require_triage_deliverables() -> None:
    semantic_contract = {
        "contract_id": "semantic-task:test",
        "task_goal_type": "test_report_triage",
        "materials": [{"path": "failing_sixty_turn_summary.json", "kind": "json", "role": "failure_report"}],
    }
    evidence = build_evidence_packet(
        task_run_id="taskrun:test",
        semantic_contract=semantic_contract,
        observations=[
            {
                "observation_ref": "obs:1",
                "tool_name": "read_structured_file",
                "result": {
                    "run_id": "run-1",
                    "total_turns": 60,
                    "failed_turns": 2,
                    "failures": [
                        {
                            "turn": 17,
                            "check": "output_boundary",
                            "symptom": "missing required response terms",
                            "evidence": "结构、根因、回归缺失",
                        }
                    ],
                },
            }
        ],
    )
    answer = "失败归类：output boundary。结构性根因：语义契约没有进入收口。回归测试：补长跑验收。证据边界：未运行新测试。"

    result = validate_deliverable(
        final_answer=answer,
        semantic_contract=semantic_contract,
        evidence_packet=evidence.to_dict(),
        strict=True,
    )

    assert evidence.facts
    assert evidence.classifications
    assert result.passed is True


def test_structured_file_payload_builds_triage_evidence_without_summary_parsing() -> None:
    semantic_contract = {
        "contract_id": "semantic-task:test",
        "task_goal_type": "test_report_triage",
        "deliverables": ["failure_classification", "structural_root_causes", "regression_test_plan", "evidence_limits"],
        "materials": [{"path": "failing_summary.json", "kind": "json", "role": "failure_report"}],
    }
    envelope = build_tool_result_envelope(
        tool_name="read_structured_file",
        tool_args={"path": "failing_summary.json"},
        result={
            "text": "root_type: dict\n$: object keys=['failures']",
            "structured_payload": {
                "tool_result": {
                    "kind": "structured_file",
                    "path": "failing_summary.json",
                    "format": "json",
                    "root_type": "dict",
                    "data": {
                        "run_id": "run-structured",
                        "failures": [
                            {
                                "turn": 8,
                                "check": "response.nonempty",
                                "symptom": "final answer was empty after tool loop",
                                "evidence": "tool loop returned observation but no final content",
                            }
                        ],
                    },
                }
            },
        },
    )
    evidence = build_evidence_packet(
        task_run_id="taskrun:structured",
        semantic_contract=semantic_contract,
        observations=[
            {
                "observation_ref": "obs:structured",
                "tool_name": "read_structured_file",
                "result": envelope.text,
                "result_envelope": envelope.to_dict(),
                "structured_payload": dict(envelope.structured_payload),
            }
        ],
    )

    result = validate_deliverable(
        final_answer="结论：失败集中在输出边界。原因是工具观察没有可靠转换为最终回答。建议增加长跑回归，并说明现有证据只覆盖该报告。",
        semantic_contract=semantic_contract,
        evidence_packet=evidence.to_dict(),
        strict=True,
    )

    failure_facts = [fact for fact in evidence.facts if fact.get("fact_type") == "failure"]
    assert failure_facts
    assert failure_facts[0]["turn"] == 8
    assert evidence.deliverable_coverage["failure_classification"]["satisfied"] is True
    assert result.passed is True


def test_triage_validator_rejects_polished_answer_without_evidence() -> None:
    result = validate_deliverable(
        final_answer="结论：这是输出边界问题。需要补充长跑回归，并说明证据边界。",
        semantic_contract={
            "task_goal_type": "test_report_triage",
            "deliverables": ["failure_classification", "structural_root_causes", "regression_test_plan", "evidence_limits"],
        },
        evidence_packet={"facts": [], "classifications": []},
        strict=True,
    )

    assert result.passed is False
    assert "failure_classification" in result.missing_deliverables
    assert "evidence_packet_facts" in result.missing_deliverables


def test_deliverable_validator_flags_read_file_tag_leak() -> None:
    result = validate_deliverable(
        final_answer="<read_file>\n<path>outline_review.md</path>\n</read_file>",
        semantic_contract={"task_goal_type": "general"},
    )

    assert result.passed is False
    assert result.protocol_leak_detected is True
    assert "protocol_boundary" in result.missing_deliverables


def test_deliverable_validator_flags_command_tool_markup_leak() -> None:
    result = validate_deliverable(
        final_answer='我将调用 name="command" 运行 pytest。',
        semantic_contract={"task_goal_type": "general"},
    )

    assert result.passed is False
    assert result.protocol_leak_detected is True
    assert "protocol_boundary" in result.missing_deliverables


def test_profile_driven_validator_rejects_game_completion_without_evidence() -> None:
    result = validate_deliverable(
        final_answer=(
            "已创建 index.html 和 game.js，视觉资源已接入，玩法已可玩，"
            "浏览器验证通过，最终报告已完成。"
        ),
        semantic_contract={
            "task_goal_type": "game_vertical_slice_delivery",
            "deliverables": [
                "runnable_artifact_refs",
                "gameplay_acceptance",
                "visual_asset_refs",
                "verification_evidence",
                "final_report",
            ],
            "required_actions": [
                "inspect_code",
                "apply_real_change",
                "integrate_asset",
                "run_browser_verification",
                "validate_deliverables",
            ],
        },
        evidence_packet={"facts": []},
    )

    assert result.passed is False
    assert "runnable_artifact_refs" in result.missing_deliverables
    assert "visual_asset_refs" in result.missing_deliverables
    assert "verification_evidence" in result.missing_deliverables
    assert "claims_runtime_or_browser_verification_without_evidence" in result.unsupported_claims
    assert "claims_artifact_changes_without_write_evidence" in result.unsupported_claims


def test_profile_driven_validator_accepts_game_evidence_dimensions() -> None:
    result = validate_deliverable(
        final_answer=(
            "已完成浏览器游戏垂直切片：文件 backend/game/index.html、backend/game/game.js "
            "和 backend/game/assets/hero.png 已交付；玩法包含移动、攻击、敌人和 HUD；"
            "浏览器验证通过；最终报告已完成。"
        ),
        semantic_contract={
            "task_goal_type": "game_vertical_slice_delivery",
            "deliverables": [
                "runnable_artifact_refs",
                "gameplay_acceptance",
                "visual_asset_refs",
                "verification_evidence",
                "final_report",
            ],
            "required_actions": [
                "inspect_code",
                "apply_real_change",
                "integrate_asset",
                "run_browser_verification",
                "validate_deliverables",
            ],
        },
        evidence_packet={
            "facts": [
                {
                    "fact_type": "observation",
                    "preview": "write succeeded backend/game/index.html and backend/game/game.js",
                },
                {
                    "fact_type": "observation",
                    "preview": "write succeeded backend/game/assets/hero.png image asset sprite",
                },
                {
                    "fact_type": "observation",
                    "preview": "browser opened localhost:5173 canvas screenshot nonblank",
                },
                {
                    "fact_type": "observation",
                    "preview": "gameplay acceptance: movement attack enemy wave health hud",
                },
            ]
        },
    )

    assert result.passed is True
    assert result.missing_deliverables == ()
    assert result.unsupported_claims == ()


def test_profile_driven_validator_requires_frontend_workflow_evidence() -> None:
    result = validate_deliverable(
        final_answer="前端页面已修改，核心流程已完成并通过浏览器验证，但暂无额外限制。",
        semantic_contract={
            "task_goal_type": "frontend_app_delivery",
            "deliverables": [
                "runnable_artifact_refs",
                "workflow_acceptance",
                "verification_evidence",
                "limitations",
            ],
            "required_actions": [
                "inspect_code",
                "apply_real_change",
                "run_browser_verification",
                "validate_deliverables",
            ],
        },
        evidence_packet={
            "facts": [
                {"fact_type": "observation", "preview": "write succeeded frontend/src/App.tsx"},
                {"fact_type": "observation", "preview": "browser opened localhost:3000 DOM screenshot"},
            ]
        },
    )

    assert result.passed is False
    assert "workflow_acceptance" in result.missing_deliverables
    assert "claims_functional_acceptance_without_evidence" in result.unsupported_claims


def test_profile_driven_validator_accepts_frontend_write_browser_and_workflow_evidence() -> None:
    result = validate_deliverable(
        final_answer=(
            "已完成前端工作流交付：文件 frontend/src/App.tsx 已修改；"
            "浏览器验证已覆盖点击、输入和页面状态更新；限制是未覆盖生产构建。"
        ),
        semantic_contract={
            "task_goal_type": "frontend_app_delivery",
            "deliverables": [
                "runnable_artifact_refs",
                "workflow_acceptance",
                "verification_evidence",
                "limitations",
            ],
            "required_actions": [
                "inspect_code",
                "apply_real_change",
                "run_browser_verification",
                "validate_deliverables",
            ],
        },
        evidence_packet={
            "facts": [
                {"fact_type": "observation", "preview": "write succeeded frontend/src/App.tsx"},
                {"fact_type": "observation", "preview": "browser opened localhost:3000 DOM screenshot"},
                {"fact_type": "observation", "preview": "workflow acceptance click input state updated navigation"},
            ]
        },
    )

    assert result.passed is True
    assert result.missing_deliverables == ()
    assert result.unsupported_claims == ()


def test_artifact_delivery_requires_each_declared_output_path() -> None:
    result = validate_deliverable(
        final_answer="已交付 output/a.md，output/b.md 尚未写入，限制已说明。",
        semantic_contract={
            "task_goal_type": "artifact_delivery",
            "deliverables": ["artifact_refs", "completion_status", "limitations"],
        },
        evidence_packet={
            "facts": [
                {"fact_type": "observation", "preview": "write succeeded output/a.md"},
            ]
        },
        required_output_paths=["output/a.md", "output/b.md"],
    )

    assert result.passed is False
    assert "output_path:output/b.md" in result.missing_deliverables


def test_runtime_lane_registry_exposes_three_modes_and_removes_old_lane() -> None:
    assert DEFAULT_RUNTIME_LANE_REGISTRY.get("role_interaction") is not None
    assert DEFAULT_RUNTIME_LANE_REGISTRY.get("standard_task") is not None
    assert DEFAULT_RUNTIME_LANE_REGISTRY.get("professional_task") is not None
    assert DEFAULT_RUNTIME_LANE_REGISTRY.get("vibe_coding_task") is not None
    assert DEFAULT_RUNTIME_LANE_REGISTRY.get("autonomous_task") is None


def test_professional_profile_registry_has_test_report_triage_role_prompt() -> None:
    profile = get_professional_prompt_profile("professional.test_report_triage")

    assert profile is not None
    assert "你是一名专业长任务测试报告诊断员" in profile.prompt
    assert "不负责修改代码" not in profile.prompt
    assert "如果用户本轮明确要求修复或修改" in profile.prompt
