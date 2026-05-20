from __future__ import annotations

from health_system.maintenance.harness.contracts import RunContext, RunResult, ScenarioResult, TimingSnapshot
from health_system.maintenance.harness.reporter import render_markdown
from tests.system_eval.long_runner import (
    TurnResult,
    _collect_critical_quality_failures,
    _collect_quality_warnings,
    _cap_model_runtime_for_long_eval,
    _issues_from_result,
    _sync_memory,
)


def test_long_runner_collects_fallback_and_tool_failure_warnings() -> None:
    turn = TurnResult(
        index=34,
        session_alias="main",
        session_id="s",
        message="读取 docs/26-OpenClaw-架构改造计划.md，概括主路径分层。",
        plan_route="builtin_tool_lane",
        plan_tool="read_file",
        plan_mcp="",
        plan_skill="",
        subquery_count=1,
        event_types=["done"],
        tool_names=["read_file"],
        mcp_names=[],
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


def test_long_runner_reports_orchestration_fail_closed_warning() -> None:
    turn = TurnResult(
        index=8,
        session_alias="main",
        session_id="s",
        message="读 PDF",
        plan_route="mcp",
        plan_tool="",
        plan_mcp="pdf",
        plan_skill="",
        subquery_count=1,
        event_types=["error"],
        tool_names=[],
        mcp_names=[],
        response_text="编排计划未通过运行时校验",
        runtime_control_source="orchestration_blocked",
        runtime_control_warnings=["validation_blocked"],
    )

    assert "orchestration.runtime_control=validation_blocked" in _collect_quality_warnings(
        turn=turn,
        events=[],
    )


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


def test_long_runner_treats_budget_fallback_as_critical_failure() -> None:
    turn = TurnResult(
        index=3,
        session_alias="main",
        session_id="s",
        message="直接给我今天金价。",
        plan_route="builtin_tool_lane",
        plan_tool="web_search",
        plan_mcp="",
        plan_skill="",
        subquery_count=1,
        event_types=["done"],
        tool_names=["web_search"],
        mcp_names=[],
        response_text="本轮运行预算达到上限，所以先停止继续调用工具。",
        answer_channel="answer_candidate",
        answer_source="runtime_loop_control",
        answer_fallback_reason="runtime_budget_exhausted",
    )

    failures = _collect_critical_quality_failures(turn)

    assert "answer.fallback_critical=runtime_budget_exhausted" in failures
    assert any(item.startswith("response.critical_marker=") for item in failures)


def test_long_runner_caps_long_output_timeout_with_regular_timeout(monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_EVAL_LLM_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("SYSTEM_EVAL_LLM_MAX_RETRIES", "0")

    class _SettingsService:
        def __init__(self) -> None:
            self.values = {}

        def set_runtime_config_group(self, group_id, values):
            assert group_id == "runtime"
            self.values.update(values)

    class _ModelRuntime:
        request_timeout_seconds = 45.0
        long_output_timeout_seconds = 360.0
        max_retries = 2

        def __init__(self) -> None:
            self.settings_service = _SettingsService()

    class _Runtime:
        def __init__(self) -> None:
            self.model_runtime = _ModelRuntime()

    runtime = _Runtime()

    original = _cap_model_runtime_for_long_eval(runtime)

    assert original == (45.0, 360.0, 2)
    assert runtime.model_runtime.settings_service.values["llm_timeout_seconds"] == 7.0
    assert runtime.model_runtime.settings_service.values["llm_long_output_timeout_seconds"] == 7.0
    assert runtime.model_runtime.settings_service.values["llm_max_retries"] == 0


def test_forced_memory_sync_skips_background_wait_when_durable_not_requested() -> None:
    class _SessionSummaryManager:
        def load(self) -> str:
            return "state already projected"

    class _SessionMemory:
        def manager(self, _session_id):
            return _SessionSummaryManager()

    class _MemoryFacade:
        session_memory = _SessionMemory()

        def run_memory_maintenance_after_commit(self, **_kwargs):
            raise AssertionError("non-durable forced sync must not run heavy memory maintenance")

    class _Runtime:
        memory_facade = _MemoryFacade()

        class session_manager:
            @staticmethod
            def load_session(_session_id):
                return []

    result = _sync_memory(_Runtime(), "session-a", durable=False)

    assert result["memory_maintenance_status"] == "skipped"
    assert result["memory_maintenance_mode"] == "runtime_state_already_projected"


def test_reporter_renders_runtime_control_summary() -> None:
    result = RunResult(
        context=RunContext(
            run_id="runtime-report",
            profile="long",
            mode="inprocess",
            repo_root="",
            backend_root="",
            frontend_root="",
            output_dir="",
            generated_at="2026-04-27T00:00:00",
            python_version="3.12",
        ),
        results=[
            ScenarioResult(
                name="运营数据与实时信息切换",
                category="long_scenario",
                passed=True,
                status="passed",
                summary="10/10 user turns passed; runtime_blocked=2 turns",
                timing=TimingSnapshot(started_at="2026-04-27T00:00:00"),
                details={
                    "runtime_control_source_counts": {"orchestration_directive": 8, "orchestration_blocked": 2},
                    "runtime_control_warning_counts": {"validation_blocked": 2},
                    "runtime_execution_spec_kind_counts": {"mcp": 8, "builtin_tool_lane": 2},
                    "runtime_execution_spec_source_counts": {"data": 3, "document": 2, "web": 2},
                    "runtime_execution_spec_action_counts": {"call_tool": 8, "delegate_agent": 2},
                    "runtime_execution_spec_risk_counts": {"network": 2},
                    "runtime_validation_status_counts": {"passed": 8, "blocked": 2},
                    "runtime_blocked_reason_counts": {"validation_blocked": 2},
                    "runtime_directive_source_counts": {"data": 3, "document": 2, "web": 2},
                    "runtime_phase8_output_commit_state_counts": {"commit_candidates_projected": 10},
                    "runtime_phase8_output_commit_candidate_type_counts": {
                        "post_turn_refresh": 10,
                        "session_transcript": 10,
                        "state_memory_projection": 10,
                    },
                    "runtime_control_blocked_turns": [{"index": 7}, {"index": 8}],
                },
            )
        ],
    )

    report = render_markdown(result)

    assert "## Runtime Control" in report
    assert "sources `orchestration_blocked:2, orchestration_directive:8`" in report
    assert "blocked_turns `2`" in report
    assert "warnings `validation_blocked:2`" in report
    assert "execution_specs `builtin_tool_lane:2, mcp:8`" in report
    assert "spec_sources `data:3, document:2, web:2`" in report
    assert "spec_actions `call_tool:8, delegate_agent:2`" in report
    assert "spec_risks `network:2`" in report
    assert "validation `blocked:2, passed:8`" in report
    assert "blocked_reasons `validation_blocked:2`" in report
    assert "directive_sources `data:3, document:2, web:2`" in report
    assert "## Output Commit" in report
    assert "phase8_output_commit `commit_candidates_projected:10`" in report
    assert "commit_candidates `post_turn_refresh:10, session_transcript:10, state_memory_projection:10`" in report
