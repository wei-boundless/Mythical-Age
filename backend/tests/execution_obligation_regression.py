from __future__ import annotations

from dataclasses import asdict

from intent.execution_obligation import build_execution_obligation
from intent.task_goal_interpreter import build_task_goal_frame
from task_system.services.assembly_support import build_runtime_task_intent_contract
from understanding.query_understanding import analyze_query_understanding


def test_execution_obligation_extracts_read_write_and_pytest_from_failure_repair_goal() -> None:
    obligation = build_execution_obligation(
        session_id="session-obligation",
        task_id="task-repair",
        user_goal=(
            "追踪 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败原因，"
            "修复代码，然后运行 pytest 验证。"
        ),
    )
    payload = obligation.to_dict()

    assert payload["authority"] == "runtime.execution_obligation"
    assert payload["required_reads"][0]["path"] == "backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"
    assert payload["required_writes"]
    assert payload["required_commands"][0]["command_hint"] == "pytest"
    assert payload["required_verifications"][0]["kind"] == "pytest"
    assert "change_summary" in payload["required_deliverables"]
    assert "verification_result_or_limitation" in payload["required_deliverables"]


def test_execution_obligation_forbid_write_wins_for_analysis_only_goal() -> None:
    contract = build_runtime_task_intent_contract(
        session_id="session-obligation-forbid",
        task_id="task-analysis-only",
        user_goal=(
            "先分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败原因，"
            "不要改代码，也不要修改文件。"
        ),
        query_understanding={"route": "workspace_read", "source_kind": "workspace"},
        current_turn_context={},
    )
    obligation = contract.execution_obligation
    semantic = contract.semantic_task_contract

    assert obligation["required_reads"]
    assert obligation["required_writes"] == []
    assert "modify_code" in obligation["forbidden_actions"]
    assert "modify_code" in semantic["forbidden_actions"]
    assert "apply_real_change" not in semantic["required_actions"]


def test_execution_obligation_trims_material_path_before_following_chinese_clause() -> None:
    obligation = build_execution_obligation(
        session_id="session-material-path",
        task_id="task-material-path",
        user_goal=(
            "请结合 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf 和 "
            "knowledge/E-commerce Data/inventory.xlsx，写一份风险与行动建议。"
        ),
    ).to_dict()

    paths = [item["path"] for item in obligation["required_reads"]]
    assert "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf" in paths
    assert "knowledge/E-commerce Data/inventory.xlsx" in paths
    assert not any("写一份" in path or "行动建议" in path for path in paths)


def test_execution_obligation_treats_created_game_files_as_writes_not_reads() -> None:
    obligation = build_execution_obligation(
        session_id="session-game-writes",
        task_id="task-game-writes",
        user_goal=(
            "请在 sandbox overlay 中完成多文件网页工程，目录必须是 frontend/public/games/snake_plus/。"
            "必须写入 index.html、styles.css、game.js、README.md。"
        ),
    ).to_dict()

    assert obligation["required_reads"] == []
    assert [item["path"] for item in obligation["required_writes"]] == [
        "frontend/public/games/snake_plus/index.html",
        "frontend/public/games/snake_plus/styles.css",
        "frontend/public/games/snake_plus/game.js",
        "frontend/public/games/snake_plus/README.md",
    ]


def test_execution_obligation_derives_browser_game_requirements_from_goal_frame() -> None:
    message = "做一个可运行的浏览器端 2D 肉鸽游戏垂直切片，需要真实接入至少一个图像资产。"
    query = analyze_query_understanding(message)
    goal_frame = build_task_goal_frame(message, query_understanding=asdict(query)).to_dict()
    obligation = build_execution_obligation(
        session_id="session-game-goal-frame",
        task_id="task-game-goal-frame",
        user_goal=message,
        current_turn_context={"task_goal_frame": goal_frame},
    ).to_dict()

    write_kinds = {item["kind"] for item in obligation["required_writes"]}
    verification_kinds = {item["kind"] for item in obligation["required_verifications"]}
    command_kinds = {item["kind"] for item in obligation["required_commands"]}

    assert "workspace_change" in write_kinds
    assert "asset_integration" in write_kinds
    assert "browser_or_runtime_check" in command_kinds
    assert "browser_verification" in verification_kinds
    assert "runnable_artifact_refs" in obligation["required_deliverables"]
    assert obligation["extraction_evidence"]["profile_obligation"]["matched"] is True
