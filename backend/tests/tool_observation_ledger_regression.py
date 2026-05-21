from __future__ import annotations

from orchestration.runtime_loop.tool_observation_ledger import (
    ToolObservationLedger,
    build_tool_observation_record,
)
from orchestration.runtime_loop.protocol_boundary import detect_protocol_leak, strip_protocol_leak
from execution.tool_result_envelope import build_tool_result_envelope


def test_tool_observation_ledger_classifies_core_tool_side_effects() -> None:
    ledger = ToolObservationLedger(ledger_id="ledger:tools", task_run_id="taskrun:tools")
    for ref, name, args, result in (
        ("obs:read", "read_file", {"path": "backend/app.py"}, "content"),
        ("obs:write", "edit_file", {"path": "backend/app.py"}, "patched"),
        ("obs:verify", "terminal", {"command": "pytest -q"}, "1 passed"),
        ("obs:delegate", "delegate_to_agent", {"agent_id": "agent:reviewer"}, "looks ok"),
    ):
        ledger = ledger.append(
            build_tool_observation_record(
                observation_ref=ref,
                tool_name=name,
                tool_args=args,
                result=result,
            )
        )

    summary = ledger.summary()

    assert summary["record_count"] == 4
    assert summary["read_count"] == 1
    assert summary["write_count"] == 1
    assert summary["verification_count"] == 1
    assert summary["delegation_count"] == 1
    assert summary["satisfied_obligations"] == [
        "delegate_review",
        "read_material",
        "verify_command",
        "write_output",
    ]


def test_tool_observation_ledger_hashes_real_side_effect_observations_stably() -> None:
    first = build_tool_observation_record(
        observation_ref="obs:write:1",
        tool_name="write_file",
        tool_args={"path": "output/plan.md"},
        result="wrote output/plan.md",
    )
    second = build_tool_observation_record(
        observation_ref="obs:write:2",
        tool_name="write_file",
        tool_args={"path": "output/plan.md"},
        result="wrote output/plan.md",
    )
    read = build_tool_observation_record(
        observation_ref="obs:read",
        tool_name="search_text",
        tool_args={"query": "plan"},
        result="matches",
    )

    assert first.side_effect_kind == "write"
    assert first.side_effect_hash
    assert first.side_effect_hash == second.side_effect_hash
    assert read.side_effect_kind == "read"
    assert read.side_effect_hash == ""


def test_tool_observation_ledger_records_structured_paths_and_command_receipts() -> None:
    search_envelope = build_tool_result_envelope(
        tool_name="search_text",
        tool_args={"query": "ProfessionalTaskRunDriver"},
        result="backend/orchestration/runtime_loop/professional_task_run_driver.py:107:1:class ProfessionalTaskRunDriver:",
    )
    terminal_envelope = build_tool_result_envelope(
        tool_name="terminal",
        tool_args={"command": "pytest -q"},
        result="1 passed",
    )
    ledger = ToolObservationLedger(ledger_id="ledger:structured", task_run_id="taskrun:structured")
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:search",
            tool_name="search_text",
            result={"result_envelope": search_envelope.to_dict()},
        )
    )
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:terminal",
            tool_name="terminal",
            result={"result_envelope": terminal_envelope.to_dict()},
        )
    )

    assert ledger.has_read("backend/orchestration/runtime_loop/professional_task_run_driver.py") is True
    assert ledger.has_verification("pytest") is True
    assert ledger.verification_passed() is True
    assert ledger.summary()["matched_paths"] == ["backend/orchestration/runtime_loop/professional_task_run_driver.py"]


def test_tool_observation_ledger_extracts_paths_from_wrapped_search_text() -> None:
    envelope = build_tool_result_envelope(
        tool_name="search_text",
        tool_args={"query": "ProfessionalTaskRunDriver"},
        result="真实工具结果：query=ProfessionalTaskRunDriver; 命中 backend/orchestration/runtime_loop/professional_task_run_driver.py",
    )
    ledger = ToolObservationLedger(ledger_id="ledger:wrapped-search", task_run_id="taskrun:wrapped-search")
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:wrapped-search",
            tool_name="search_text",
            result={"result_envelope": envelope.to_dict()},
        )
    )

    assert ledger.summary()["matched_paths"] == ["backend/orchestration/runtime_loop/professional_task_run_driver.py"]
    assert ledger.has_read("backend/orchestration/runtime_loop/professional_task_run_driver.py") is True


def test_terminal_parser_error_is_not_a_passing_verification() -> None:
    envelope = build_tool_result_envelope(
        tool_name="terminal",
        tool_args={"command": "cd /workspace && python -m pytest backend/tests/foo.py"},
        result=(
            "At line:7 char:15\n"
            "+ cd /workspace && python -m pytest backend/tests/foo.py\n"
            "+               ~~\n"
            "The token '&&' is not a valid statement separator in this version.\n"
            "    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException\n"
            "    + FullyQualifiedErrorId : InvalidEndOfLine"
        ),
    )
    ledger = ToolObservationLedger(ledger_id="ledger:parser-error", task_run_id="taskrun:parser-error")
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:terminal",
            tool_name="terminal",
            result={"result_envelope": envelope.to_dict()},
        )
    )

    assert envelope.status == "error"
    assert envelope.command_receipt["passed"] is False
    assert ledger.has_verification("pytest") is True
    assert ledger.verification_passed() is False


def test_terminal_pytest_failure_is_not_a_passing_verification() -> None:
    envelope = build_tool_result_envelope(
        tool_name="terminal",
        tool_args={"command": "python -m pytest backend/tests/foo.py"},
        result=(
            "============================= FAILURES =============================\n"
            "FAILED backend/tests/foo.py::test_example - AssertionError\n"
            "========================= 1 failed, 2 passed in 0.12s ========================="
        ),
    )
    ledger = ToolObservationLedger(ledger_id="ledger:pytest-failed", task_run_id="taskrun:pytest-failed")
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:terminal",
            tool_name="terminal",
            result={"result_envelope": envelope.to_dict()},
        )
    )

    assert envelope.status == "error"
    assert envelope.command_receipt["passed"] is False
    assert ledger.verification_passed() is False


def test_terminal_pytest_success_is_a_passing_verification() -> None:
    envelope = build_tool_result_envelope(
        tool_name="terminal",
        tool_args={"command": "python -m pytest backend/tests/foo.py"},
        result="========================= 1 passed in 0.12s =========================",
    )
    ledger = ToolObservationLedger(ledger_id="ledger:pytest-passed", task_run_id="taskrun:pytest-passed")
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:terminal",
            tool_name="terminal",
            result={"result_envelope": envelope.to_dict()},
        )
    )

    assert envelope.status == "ok"
    assert envelope.command_receipt["passed"] is True
    assert ledger.verification_passed() is True


def test_protocol_boundary_detects_command_tool_markup() -> None:
    result = detect_protocol_leak('<｜｜DSML｜｜invoke name="command">pytest -q</｜｜DSML｜｜invoke>')

    assert result.detected is True
    assert "name=\"command\"" in result.markers
    assert strip_protocol_leak('正常回答\nname="command" pytest -q').strip() == "正常回答"
