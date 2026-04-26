from __future__ import annotations

from harness.contracts import ScenarioResult, TimingSnapshot
from tests.system_eval.long_runner import TurnResult, _collect_quality_warnings, _issues_from_result


def test_long_runner_collects_fallback_and_tool_failure_warnings() -> None:
    turn = TurnResult(
        index=34,
        session_alias="main",
        session_id="s",
        message="读取 docs/26-OpenClaw-架构改造计划.md，概括主路径分层。",
        plan_route="tool",
        plan_tool="read_file",
        plan_worker="",
        plan_skill="",
        subquery_count=1,
        event_types=["done"],
        tool_names=["read_file"],
        worker_names=[],
        response_text="无法调用工具 read_file：tool_not_safe_for_auto_route",
        answer_channel="fallback_answer",
        answer_source="permission_guard",
        answer_fallback_reason="tool_permission_denied",
        orchestration_diff_status="warning",
        orchestration_diff_summary="编排计划与实际执行缺少部分可比字段。",
    )
    events = [
        {
            "event": "tool_end",
            "data": {"tool": "read_file", "output": "Read failed: file does not exist."},
        }
    ]

    warnings = _collect_quality_warnings(turn=turn, events=events)

    assert "answer.fallback=tool_permission_denied source=permission_guard" in warnings
    assert "response.marker=tool_not_safe_for_auto_route" in warnings
    assert "tool.read_file.marker=file does not exist" in warnings
    assert any(item.startswith("orchestration.diff.warning=") for item in warnings)


def test_long_runner_emits_warning_issue_for_passed_scenario() -> None:
    result = ScenarioResult(
        name="六十轮真实用户长跑",
        category="long_scenario",
        passed=True,
        status="passed",
        summary="1/1 user turns passed; warnings=1 turns",
        command="long_scenario::sixty-turn-real-user-marathon",
        timing=TimingSnapshot(started_at="2026-04-26T00:00:00"),
        details={
            "quality_warning_counts": {"answer.fallback": 1},
            "quality_warning_turns": [
                {
                    "index": 34,
                    "session_alias": "main",
                    "message": "读取文件",
                    "warnings": ["answer.fallback=tool_permission_denied source=permission_guard"],
                }
            ],
        },
    )

    issues = _issues_from_result(1, result)

    assert len(issues) == 1
    assert issues[0].severity == "medium"
    assert issues[0].category == "long_scenario/warning"
    assert "1 turns emitted quality warnings" in issues[0].summary
