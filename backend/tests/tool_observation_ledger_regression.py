from __future__ import annotations

from runtime.memory.tool_observation_ledger import (
    ToolObservationLedger,
    build_tool_observation_record,
)
from task_system.runtime_semantics.protocol_boundary import detect_protocol_leak, strip_protocol_leak
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope


def test_tool_observation_ledger_classifies_core_tool_side_effects() -> None:
    read_envelope = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "backend/app.py"},
        result={
            "text": "content",
            "structured_payload": {
                "observed_paths": ["backend/app.py"],
                "tool_result": {
                    "kind": "text_file",
                    "path": "backend/app.py",
                    "size_chars": 7,
                    "truncated": False,
                },
            },
        },
    )
    write_envelope = build_tool_result_envelope(
        tool_name="edit_file",
        tool_args={"path": "backend/app.py"},
        result={
            "text": "Edit succeeded: backend/app.py",
            "structured_payload": {
                "observed_paths": ["backend/app.py"],
                "artifact_refs": [{"path": "backend/app.py", "kind": "file", "source": "edit_file"}],
            },
        },
    )
    terminal_envelope = build_tool_result_envelope(
        tool_name="terminal",
        tool_args={"command": "pytest -q"},
        result={
            "text": "1 passed",
            "structured_payload": {
                "command_receipt": {
                    "command": "pytest -q",
                    "exit_code": 0,
                    "passed": True,
                    "output_preview": "1 passed",
                }
            },
        },
    )
    ledger = ToolObservationLedger(ledger_id="ledger:tools", task_run_id="taskrun:tools")
    for ref, name, args, result in (
        ("obs:read", "read_file", {"path": "backend/app.py"}, {"result_envelope": read_envelope.to_dict()}),
        ("obs:write", "edit_file", {"path": "backend/app.py"}, {"result_envelope": write_envelope.to_dict()}),
        ("obs:verify", "terminal", {"command": "pytest -q"}, {"result_envelope": terminal_envelope.to_dict()}),
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
    envelope = build_tool_result_envelope(
        tool_name="write_file",
        tool_args={"path": "output/plan.md"},
        result={
            "text": "Write succeeded: output/plan.md",
            "structured_payload": {
                "observed_paths": ["output/plan.md"],
                "artifact_refs": [{"path": "output/plan.md", "kind": "file", "source": "write_file"}],
            },
        },
    )
    first = build_tool_observation_record(
        observation_ref="obs:write:1",
        tool_name="write_file",
        tool_args={"path": "output/plan.md"},
        result={"result_envelope": envelope.to_dict()},
    )
    second = build_tool_observation_record(
        observation_ref="obs:write:2",
        tool_name="write_file",
        tool_args={"path": "output/plan.md"},
        result={"result_envelope": envelope.to_dict()},
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
        result={
            "text": "backend/runtime/professional_runtime/driver.py:102:1:class ProfessionalTaskRunDriver:",
            "structured_payload": {
                "matched_paths": ["backend/runtime/professional_runtime/driver.py"],
                "tool_result": {
                    "kind": "text_search",
                    "matches": [{"path": "backend/runtime/professional_runtime/driver.py", "line": 102, "column": 1}],
                },
            },
        },
    )
    terminal_envelope = build_tool_result_envelope(
        tool_name="terminal",
        tool_args={"command": "pytest -q"},
        result={
            "text": "1 passed",
            "structured_payload": {
                "command_receipt": {
                    "command": "pytest -q",
                    "exit_code": 0,
                    "passed": True,
                    "output_preview": "1 passed",
                }
            },
        },
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

    assert ledger.has_read("backend/runtime/professional_runtime/driver.py") is True
    assert ledger.has_verification("pytest") is True
    assert ledger.verification_passed() is True
    assert ledger.summary()["matched_paths"] == ["backend/runtime/professional_runtime/driver.py"]


def test_tool_observation_ledger_extracts_paths_from_wrapped_search_text() -> None:
    envelope = build_tool_result_envelope(
        tool_name="search_text",
        tool_args={"query": "ProfessionalTaskRunDriver"},
        result={
            "text": "真实工具结果：query=ProfessionalTaskRunDriver; 命中 backend/runtime/professional_runtime/driver.py",
            "structured_payload": {
                "matched_paths": ["backend/runtime/professional_runtime/driver.py"],
                "tool_result": {
                    "kind": "text_search",
                    "matches": [{"path": "backend/runtime/professional_runtime/driver.py", "line": 1, "column": 1}],
                },
            },
        },
    )
    ledger = ToolObservationLedger(ledger_id="ledger:wrapped-search", task_run_id="taskrun:wrapped-search")
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:wrapped-search",
            tool_name="search_text",
            result={"result_envelope": envelope.to_dict()},
        )
    )

    assert ledger.summary()["matched_paths"] == ["backend/runtime/professional_runtime/driver.py"]
    assert ledger.has_read("backend/runtime/professional_runtime/driver.py") is True


def test_terminal_parser_error_is_not_a_passing_verification() -> None:
    envelope = build_tool_result_envelope(
        tool_name="terminal",
        tool_args={"command": "cd /workspace && python -m pytest backend/tests/foo.py"},
        result={
            "text": (
                "At line:7 char:15\n"
                "+ cd /workspace && python -m pytest backend/tests/foo.py\n"
                "+               ~~\n"
                "The token '&&' is not a valid statement separator in this version.\n"
                "    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException\n"
                "    + FullyQualifiedErrorId : InvalidEndOfLine"
            ),
            "structured_payload": {
                "command_receipt": {
                    "command": "cd /workspace && python -m pytest backend/tests/foo.py",
                    "exit_code": 1,
                    "passed": False,
                    "output_preview": "ParserError",
                }
            },
        },
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
        result={
            "text": (
                "============================= FAILURES =============================\n"
                "FAILED backend/tests/foo.py::test_example - AssertionError\n"
                "========================= 1 failed, 2 passed in 0.12s ========================="
            ),
            "structured_payload": {
                "command_receipt": {
                    "command": "python -m pytest backend/tests/foo.py",
                    "exit_code": 1,
                    "passed": False,
                    "output_preview": "1 failed, 2 passed",
                }
            },
        },
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
        result={
            "text": "========================= 1 passed in 0.12s =========================",
            "structured_payload": {
                "command_receipt": {
                    "command": "python -m pytest backend/tests/foo.py",
                    "exit_code": 0,
                    "passed": True,
                    "output_preview": "1 passed",
                }
            },
        },
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


def test_plain_text_write_and_terminal_do_not_satisfy_hard_evidence() -> None:
    ledger = ToolObservationLedger(ledger_id="ledger:legacy-text", task_run_id="taskrun:legacy-text")
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:write",
            tool_name="write_file",
            tool_args={"path": "output/plan.md"},
            result="Write succeeded: output/plan.md",
        )
    )
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:terminal",
            tool_name="terminal",
            tool_args={"command": "pytest -q"},
            result="1 passed",
        )
    )

    assert ledger.has_write("output/plan.md") is False
    assert ledger.has_verification("pytest") is False
    assert ledger.verification_passed() is False
    assert ledger.records[0].evidence_source == "legacy_text"
    assert ledger.records[0].debug_hints["hard_evidence_accepted"] is False


def test_error_envelope_does_not_satisfy_read_material() -> None:
    envelope = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "missing.md"},
        result={
            "text": "Read failed: file does not exist",
            "status": "error",
            "structured_payload": {
                "tool_result": {
                    "kind": "text_file",
                    "status": "error",
                    "error": "file does not exist",
                }
            },
        },
    )
    ledger = ToolObservationLedger(ledger_id="ledger:error-read", task_run_id="taskrun:error-read")
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:error-read",
            tool_name="read_file",
            result={"result_envelope": envelope.to_dict()},
        )
    )

    assert ledger.has_read("missing.md") is False
    assert "read_material" not in ledger.summary()["satisfied_obligations"]


def test_protocol_boundary_detects_command_tool_markup() -> None:
    result = detect_protocol_leak('<｜｜DSML｜｜invoke name="command">pytest -q</｜｜DSML｜｜invoke>')

    assert result.detected is True
    assert "name=\"command\"" in result.markers
    assert strip_protocol_leak('正常回答\nname="command" pytest -q').strip() == "正常回答"
