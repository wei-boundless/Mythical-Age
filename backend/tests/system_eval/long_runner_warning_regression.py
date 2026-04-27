from __future__ import annotations

from harness.contracts import RunContext, RunResult, ScenarioResult, TimingSnapshot
from harness.reporter import render_markdown
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


def test_long_runner_distinguishes_expected_runtime_allowlist_fallback() -> None:
    expected = TurnResult(
        index=7,
        session_alias="main",
        session_id="s",
        message="查一下实时信息",
        plan_route="tool",
        plan_tool="web_search",
        plan_worker="",
        plan_skill="",
        subquery_count=1,
        event_types=["done"],
        tool_names=[],
        worker_names=[],
        response_text="ok",
        runtime_control_source="legacy_fallback",
        runtime_control_warnings=["primary_fallback_allowlist_blocked"],
    )
    unexpected = TurnResult(
        index=8,
        session_alias="main",
        session_id="s",
        message="读 PDF",
        plan_route="worker",
        plan_tool="pdf_analysis",
        plan_worker="pdf",
        plan_skill="",
        subquery_count=1,
        event_types=["done"],
        tool_names=[],
        worker_names=[],
        response_text="ok",
        runtime_control_source="legacy_fallback",
        runtime_control_warnings=["primary_fallback_legacy_field_mismatch"],
    )

    assert not _collect_quality_warnings(turn=expected, events=[])
    assert "orchestration.runtime_fallback=primary_fallback_legacy_field_mismatch" in _collect_quality_warnings(
        turn=unexpected,
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
                summary="10/10 user turns passed; runtime_fallback=2 turns",
                timing=TimingSnapshot(started_at="2026-04-27T00:00:00"),
                details={
                    "runtime_control_source_counts": {"orchestration_plan": 8, "legacy_fallback": 2},
                    "runtime_control_warning_counts": {"primary_fallback_allowlist_blocked": 2},
                    "runtime_entry_kind_counts": {"worker": 8, "direct_tool": 2},
                    "runtime_entry_source_counts": {"data": 3, "document": 2, "web": 2},
                    "runtime_entry_strategy_counts": {"primary_entry_selection_preview": 10},
                    "runtime_entry_eligible_counts": {"eligible": 8, "blocked": 2},
                    "runtime_entry_blocker_counts": {"source_not_low_risk:web": 2},
                    "runtime_entry_selection_state_counts": {"ready": 8, "blocked": 2},
                    "runtime_primary_preview_state_counts": {"ready": 8, "blocked": 2},
                    "runtime_primary_preview_mismatch_counts": {},
                    "runtime_primary_takeover_state_counts": {"active": 8, "blocked": 2},
                    "runtime_phase7_readiness_state_counts": {"ready": 8, "blocked": 2},
                    "runtime_phase7_readiness_blocker_counts": {"source_not_phase7_ready:web": 2},
                    "runtime_phase7_intent_authority_state_counts": {"candidate_projected": 10},
                    "runtime_phase7_restore_authority_state_counts": {"candidate_projected": 10},
                    "runtime_phase7_restore_authority_blocker_counts": {"legacy_restore_still_executes": 10},
                    "runtime_phase7_restore_candidate_type_counts": {"target_handle": 2, "session_state": 1},
                    "runtime_phase7_restore_adoption_state_counts": {"adopted_by_legacy": 3},
                    "runtime_phase7_restore_adoption_gate_state_counts": {"blocked": 10},
                    "runtime_phase7_restore_adoption_gate_blocker_counts": {"legacy_restore_still_executes": 10},
                    "runtime_phase7_restore_adoption_decision_counts": {"blocked": 3},
                    "runtime_phase7_memory_context_validation_counts": {"passed": 3},
                    "runtime_phase7_restore_cutover_state_counts": {"blocked": 10},
                    "runtime_phase7_restore_cutover_blocker_counts": {"legacy_restore_still_executes": 10},
                    "runtime_phase7_restore_dry_run_state_counts": {"observed_delta": 3, "blocked": 7},
                    "runtime_phase7_restore_dry_run_alignment_counts": {"expected_legacy_delta": 3},
                    "runtime_phase8_restore_formal_review_state_counts": {"candidate_decisions_ready": 3, "no_candidates": 7},
                    "runtime_phase8_restore_formal_decision_counts": {"accepted": 3},
                    "runtime_phase8_restore_legacy_alignment_counts": {"legacy_matches_formal_acceptance": 3},
                    "runtime_phase7_output_authority_state_counts": {"candidate_projected": 10},
                    "runtime_phase7_output_authority_blocker_counts": {"legacy_present_still_executes": 10},
                    "runtime_phase7_output_writeback_scope_counts": {"state_memory": 1},
                    "runtime_phase8_output_commit_state_counts": {"commit_candidates_projected": 10},
                    "runtime_phase8_output_commit_candidate_type_counts": {
                        "post_turn_refresh": 10,
                        "session_transcript": 10,
                        "state_memory_projection": 10,
                    },
                    "runtime_phase7_dispatch_authority_state_counts": {"candidate_projected": 10},
                    "runtime_phase7_dispatch_authority_blocker_counts": {"legacy_decide_still_executes": 10},
                    "runtime_phase7_dispatch_target_counts": {"call_tool": 8, "delegate_agent": 1, "respond": 1},
                    "runtime_phase7_cutover_readiness_state_counts": {"blocked": 10},
                    "runtime_phase7_cutover_readiness_blocker_counts": {"decide:not_ready": 10},
                    "runtime_phase7_cutover_gate_blocker_counts": {"principle_alignment_not_ready": 10},
                    "runtime_phase7_cutover_top_blocker_counts": {"gate:principle_alignment_not_ready": 10},
                    "runtime_phase7_cutover_domain_state_counts": {"decide:blocked": 10, "execute:blocked": 10},
                    "runtime_phase7_cutover_domain_blocker_counts": {"decide:legacy_decide_still_executes": 10},
                    "runtime_phase7_cutover_migration_task_counts": {"decide:planned": 10},
                    "runtime_phase7_execution_contract_state_counts": {"preview_ready": 8, "blocked": 2},
                    "runtime_phase7_decommission_state_counts": {"not_ready": 10},
                    "runtime_phase7_principle_alignment_state_counts": {"blocked": 10},
                    "runtime_phase7_principle_alignment_blocker_counts": {"legacy_power_domain:decide": 10},
                    "runtime_control_fallback_turns": [{"index": 7}, {"index": 8}],
                },
            )
        ],
    )

    report = render_markdown(result)

    assert "## Runtime Control" in report
    assert "fallback_turns `2`" in report
    assert "primary_fallback_allowlist_blocked:2" in report
    assert "entries `direct_tool:2, worker:8`" in report
    assert "entry_sources `data:3, document:2, web:2`" in report
    assert "entry_strategy `primary_entry_selection_preview:10`" in report
    assert "entry_eligible `blocked:2, eligible:8`" in report
    assert "entry_blockers `source_not_low_risk:web:2`" in report
    assert "entry_selection `blocked:2, ready:8`" in report
    assert "primary_preview `blocked:2, ready:8`" in report
    assert "primary_preview_mismatches `none`" in report
    assert "primary_takeover `active:8, blocked:2`" in report
    assert "phase7_readiness `blocked:2, ready:8`" in report
    assert "phase7_blockers `source_not_phase7_ready:web:2`" in report
    assert "phase7_intent `candidate_projected:10`" in report
    assert "phase7_restore `candidate_projected:10`" in report
    assert "phase7_restore_blockers `legacy_restore_still_executes:10`" in report
    assert "phase7_restore_types `session_state:1, target_handle:2`" in report
    assert "phase7_restore_adoption `adopted_by_legacy:3`" in report
    assert "phase7_restore_gate `blocked:10`" in report
    assert "phase7_restore_gate_blockers `legacy_restore_still_executes:10`" in report
    assert "phase7_restore_decisions `blocked:3`" in report
    assert "phase7_memory_context_validation `passed:3`" in report
    assert "phase7_restore_cutover `blocked:10`" in report
    assert "phase7_restore_cutover_blockers `legacy_restore_still_executes:10`" in report
    assert "phase7_restore_dry_run `blocked:7, observed_delta:3`" in report
    assert "phase7_restore_dry_run_alignments `expected_legacy_delta:3`" in report
    assert "phase8_restore_formal `candidate_decisions_ready:3, no_candidates:7`" in report
    assert "phase8_restore_decisions `accepted:3`" in report
    assert "phase8_restore_alignment `legacy_matches_formal_acceptance:3`" in report
    assert "phase7_output `candidate_projected:10`" in report
    assert "phase7_output_blockers `legacy_present_still_executes:10`" in report
    assert "phase7_output_writeback `state_memory:1`" in report
    assert "## Output Commit" in report
    assert "phase8_output_commit `commit_candidates_projected:10`" in report
    assert "commit_candidates `post_turn_refresh:10, session_transcript:10, state_memory_projection:10`" in report
    assert "phase7_dispatch `candidate_projected:10`" in report
    assert "phase7_dispatch_blockers `legacy_decide_still_executes:10`" in report
    assert "phase7_dispatch_targets `call_tool:8, delegate_agent:1, respond:1`" in report
    assert "phase7_cutover `blocked:10`" in report
    assert "phase7_cutover_top `gate:principle_alignment_not_ready:10`" in report
    assert "phase7_cutover_gate `principle_alignment_not_ready:10`" in report
    assert "phase7_cutover_domains `decide:blocked:10, execute:blocked:10`" in report
    assert "phase7_cutover_domain_blockers `decide:legacy_decide_still_executes:10`" in report
    assert "phase7_cutover_tasks `decide:planned:10`" in report
    assert "phase7_cutover_blockers_full `decide:not_ready:10`" in report
    assert "phase7_execution `blocked:2, preview_ready:8`" in report
    assert "phase7_decommission `not_ready:10`" in report
    assert "phase7_principles `blocked:10`" in report
    assert "phase7_principle_blockers `legacy_power_domain:decide:10`" in report
