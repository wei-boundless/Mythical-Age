from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from intent.task_goal_interpreter import build_task_goal_frame
from intent.task_goal_interpreter import build_goal_hypothesis_set
from task_system.services.assembly_support import build_runtime_task_intent_contract
from understanding.query_understanding import analyze_query_understanding


ROGUELIKE_PROMPT = """你是一名独立游戏原型开发负责人。

你的目标是在当前项目中完成一个可运行、可测试、可迭代的浏览器端 2D 肉鸽游戏垂直切片。

你必须按阶段推进：项目简报、玩法设计、技术设计、资产清单、生图提示词与资源生成、MVP 实现、资源接入、运行验证、最终报告。

最低产品范围：
- 俯视角移动。
- 玩家攻击。
- 至少三类敌人或三种敌人行为。
- 房间、竞技场或波次推进。
- 经验、金币或奖励拾取。
- 升级三选一，至少三个升级选项。
- Boss 或精英敌人。
- 死亡或胜利状态。
- 可见 HUD。
- 至少一个生图资源真实显示在游戏里。

你需要真实修改代码、真实生成或接入至少一个图像资产、真实启动项目并验证。
你不能把未运行、未验证的功能说成已经完成。
遇到失败时，追踪原因、修复并重新验证。

请把阶段产物写入 docs/experiments/roguelike_long_task/，最终报告写入 docs/experiments/roguelike_long_task/final_report.md。"""


def main() -> None:
    query = analyze_query_understanding(ROGUELIKE_PROMPT)
    goal_frame = build_task_goal_frame(
        ROGUELIKE_PROMPT,
        query_understanding=asdict(query),
    )
    hypothesis_set = build_goal_hypothesis_set(ROGUELIKE_PROMPT, query_understanding=asdict(query)).to_dict()
    payload = goal_frame.to_dict()
    rejected_types = {item["task_goal_type"] for item in payload["rejected_goal_candidates"]}
    assert payload["task_goal_type"] == "game_vertical_slice_delivery"
    assert payload["task_domain"] == "development"
    assert hypothesis_set["chosen"]["task_goal_type"] == "game_vertical_slice_delivery"
    assert "artifact_delivery" in {item["task_goal_type"] for item in hypothesis_set["rejected"]}
    assert "artifact_delivery" in rejected_types
    assert "final_report_only" in payload["unacceptable_outcomes"]
    assert "treat_supporting_report_as_core_output" in payload["forbidden_actions"]
    assert any(item["deliverable_id"] == "final_report" for item in payload["supporting_deliverables"])
    assert not any(item["deliverable_id"] == "final_report" for item in payload["core_deliverables"])
    assert any(item["stage_id"] == "verification" for item in payload["stage_prompt_profiles"])
    assert payload["evidence"]["goal_hypothesis_set"]["chosen"]["task_goal_type"] == "game_vertical_slice_delivery"

    contract = build_runtime_task_intent_contract(
        session_id="goal-frame-test-session",
        task_id="goal-frame-test-task",
        user_goal=ROGUELIKE_PROMPT,
        query_understanding=asdict(query),
        current_turn_context={
            "interaction_mode": "professional_mode",
            "intent_decision": {"execution_strategy": "professional_task_run"},
            "runtime_assembly_hint": {"execution_strategy": "professional_task_run"},
            "task_goal_frame": payload,
        },
    )
    semantic = contract.semantic_task_contract
    assert semantic["task_goal_type"] == "game_vertical_slice_delivery"
    assert semantic["strategy_prototype_id"] == "game_vertical_slice_delivery"
    assert semantic["professional_profile_id"] == "professional.game_vertical_slice_delivery"
    assert "runnable_artifact_refs" in semantic["deliverables"]
    assert "final_report" in semantic["deliverables"]
    assert "change_summary" not in semantic["deliverables"]
    assert "changed_files" not in semantic["deliverables"]
    assert "stage_prompt_profiles_required" in semantic["material_handling_policy"]
    assert semantic["diagnostics"]["goal_hypothesis_set"]["chosen"]["task_goal_type"] == "game_vertical_slice_delivery"
    assert "final_report_only" in semantic["diagnostics"]["unacceptable_outcomes"]

    simple_query = analyze_query_understanding("请创建 docs/tmp/test.md，内容是 hello")
    simple_goal = build_task_goal_frame("请创建 docs/tmp/test.md，内容是 hello", query_understanding=asdict(simple_query))
    assert simple_goal.task_goal_type == "artifact_delivery"

    triage_text = "分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败，输出结构性根因和回归测试建议。"
    triage_query = analyze_query_understanding(triage_text)
    triage_goal = build_task_goal_frame(triage_text, query_understanding=asdict(triage_query))
    assert triage_goal.task_goal_type == "test_report_triage"
    assert triage_goal.task_domain == "agent_runtime_quality"
    assert "domain_profile" in triage_goal.evidence["goal_signals"]

    analysis_only = "先看一下前端任务图编辑器为什么布局不稳定，不要急着修。"
    analysis_query = analyze_query_understanding(analysis_only)
    analysis_goal = build_task_goal_frame(analysis_only, query_understanding=asdict(analysis_query))
    assert analysis_goal.task_goal_type != "frontend_app_delivery"

    print("ALL PASSED (task goal frame)")


if __name__ == "__main__":
    main()
