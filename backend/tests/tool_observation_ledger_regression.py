from __future__ import annotations

from runtime.memory.tool_observation_ledger import (
    ToolObservationLedger,
    build_tool_observation_record,
)
from task_system.runtime_semantics.protocol_boundary import detect_protocol_leak, strip_protocol_leak
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope, tool_result_envelope_from_payload


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
                    "total_lines": 1,
                    "start_line": 1,
                    "line_count": 240,
                    "returned_lines": 1,
                    "end_line": 1,
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
                },
                "verification_intent": {
                    "stage": "verify_output",
                    "obligation": "verify_command",
                    "authority": "harness.loop.agent_phase_pipeline",
                },
            },
        },
    )
    ledger = ToolObservationLedger(ledger_id="ledger:tools", task_run_id="taskrun:tools")
    for ref, name, args, result in (
        ("obs:read", "read_file", {"path": "backend/app.py"}, {"result_envelope": read_envelope.to_dict()}),
        ("obs:write", "edit_file", {"path": "backend/app.py"}, {"result_envelope": write_envelope.to_dict()}),
        ("obs:verify", "terminal", {"command": "pytest -q"}, {"result_envelope": terminal_envelope.to_dict()}),
        ("obs:subagent", "start_subagent", {"target_agent_id": "agent:reviewer", "goal": "review"}, "subagent scheduled"),
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
    assert summary["subagent_lifecycle_count"] == 1
    assert summary["satisfied_obligations"] == [
        "read_material",
        "subagent_lifecycle",
        "verify_command",
        "write_output",
    ]


def test_read_file_observation_records_content_window_metadata() -> None:
    envelope = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "docs/long.md", "start_line": 11, "line_count": 5},
        result={
            "text": "11 | abcde",
            "structured_payload": {
                "observed_paths": ["docs/long.md"],
                "tool_result": {
                    "kind": "text_file",
                    "path": "docs/long.md",
                    "total_lines": 30,
                    "start_line": 11,
                    "line_count": 5,
                    "returned_lines": 5,
                    "end_line": 15,
                    "next_start_line": 16,
                    "has_more": True,
                    "truncated": True,
                    "content_sha256": "sha256:test",
                },
            },
        },
    )

    record = build_tool_observation_record(
        observation_ref="obs:window",
        tool_name="read_file",
        result={"result_envelope": envelope.to_dict()},
    ).to_dict()

    assert record["result_metadata"]["content_range"]["start_line"] == 11
    assert record["result_metadata"]["content_range"]["next_start_line"] == 16
    assert record["result_metadata"]["result_boundary"]["fact_status"] == "window_evidence"
    assert record["result_metadata"]["recovery_options"][0]["kind"] == "continue_reading"
    assert record["result_metadata"]["recovery_options"][0]["args_hint"]["start_line"] == 16


def test_tool_result_envelope_parser_does_not_backfill_identity_from_wrapper_payload() -> None:
    envelope = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "docs/source.md"},
        result={
            "text": "content",
            "structured_payload": {
                "observed_paths": ["docs/source.md"],
                "tool_result": {
                    "kind": "text_file",
                    "path": "docs/source.md",
                    "start_line": 1,
                    "end_line": 1,
                    "total_lines": 1,
                },
            },
        },
    )

    parsed = tool_result_envelope_from_payload(
        {
            "tool_name": "shadow_tool",
            "tool_call_id": "call:wrapper-shadow",
            "action_request_ref": "request:wrapper-shadow",
            "caller_ref": "turnrun:wrapper-shadow",
            "result": "wrapper shadow text",
            "execution_receipt": {"tool_call_id": "call:receipt-shadow"},
            "result_envelope": {
                key: value
                for key, value in envelope.to_dict().items()
                if key
                not in {
                    "tool_call_id",
                    "action_request_id",
                    "caller_ref",
                    "execution_receipt",
                }
            },
        }
    )

    assert parsed is not None
    assert parsed.tool_name == "read_file"
    assert parsed.tool_call_id == ""
    assert parsed.action_request_id == ""
    assert parsed.caller_ref == ""
    assert parsed.execution_receipt == {}
    assert parsed.text == "content"


def test_collect_subagent_result_records_authoritative_final_answer_metadata() -> None:
    final_answer = "CHILD REPORT\n" + "x" * 900
    envelope = build_tool_result_envelope(
        tool_name="collect_subagent_result",
        tool_args={"subagent_run_ref": "agrun:taskrun:parent:child"},
        result={
            "text": "short child summary",
            "structured_payload": {
                "subagent_control": {
                    "subagent_run_ref": "agrun:taskrun:parent:child",
                    "status": "completed",
                    "result_ref": "rtobj:agent_run_result:child",
                    "result_state": "read",
                    "result": {
                        "result_ref": "rtobj:agent_run_result:child",
                        "final_answer": final_answer,
                        "summary": "short child summary",
                        "evidence_refs": ["backend/harness/loop/task_executor.py:1"],
                    },
                }
            },
        },
    )

    record = build_tool_observation_record(
        observation_ref="obs:collect-subagent-result",
        tool_name="collect_subagent_result",
        tool_args={"subagent_run_ref": "agrun:taskrun:parent:child"},
        result={"result_envelope": envelope.to_dict()},
    )

    subagent_result = record.result_metadata["subagent_result"]
    assert record.result_preview == "short child summary"
    assert subagent_result["final_answer"] == final_answer
    assert subagent_result["result_ref"] == "rtobj:agent_run_result:child"
    assert subagent_result["subagent_run_ref"] == "agrun:taskrun:parent:child"
    assert subagent_result["evidence_refs"] == ["backend/harness/loop/task_executor.py:1"]


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
        tool_args={"query": "phase_pipeline"},
        result={
            "text": "backend/harness/loop/agent_phase_pipeline.py:1:1:def apply_post_model_phases:",
            "structured_payload": {
                "matched_paths": ["backend/harness/loop/agent_phase_pipeline.py"],
                "tool_result": {
                    "kind": "text_search",
                    "matches": [{"path": "backend/harness/loop/agent_phase_pipeline.py", "line": 1, "column": 1}],
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
                },
                "verification_intent": {
                    "stage": "verify_output",
                    "obligation": "verify_command",
                    "authority": "harness.loop.agent_phase_pipeline",
                },
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

    assert ledger.has_read("backend/harness/loop/agent_phase_pipeline.py") is True
    assert ledger.has_verification("pytest") is True
    assert ledger.verification_passed() is True
    assert ledger.summary()["matched_paths"] == ["backend/harness/loop/agent_phase_pipeline.py"]


def test_tool_observation_ledger_extracts_paths_from_wrapped_search_text() -> None:
    envelope = build_tool_result_envelope(
        tool_name="search_text",
        tool_args={"query": "phase_pipeline"},
        result={
            "text": "真实工具结果：query=phase_pipeline; 命中 backend/harness/loop/agent_phase_pipeline.py",
            "structured_payload": {
                "matched_paths": ["backend/harness/loop/agent_phase_pipeline.py"],
                "tool_result": {
                    "kind": "text_search",
                    "matches": [{"path": "backend/harness/loop/agent_phase_pipeline.py", "line": 1, "column": 1}],
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

    assert ledger.summary()["matched_paths"] == ["backend/harness/loop/agent_phase_pipeline.py"]
    assert ledger.has_read("backend/harness/loop/agent_phase_pipeline.py") is True


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
    assert ledger.has_verification("pytest") is False
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


def test_terminal_pytest_success_without_structured_intent_is_only_command_fact() -> None:
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
    assert ledger.has_verification("pytest") is False
    assert ledger.verification_passed() is False
    assert ledger.records[0].command_receipt["passed"] is True


def test_terminal_phase_verification_intent_satisfies_verify_command_without_keyword_guessing() -> None:
    envelope = build_tool_result_envelope(
        tool_name="terminal",
        tool_args={
            "command": (
                'Get-Item -Path "output/vibe-code-smoke/langchain-mini-chat-api-review.md" | '
                "Select-Object Name, Length, LastWriteTime"
            )
        },
        result={
            "text": "langchain-mini-chat-api-review.md   5367 2026/5/25 8:14:15",
            "structured_payload": {
                "command_receipt": {
                    "command": (
                        'Get-Item -Path "output/vibe-code-smoke/langchain-mini-chat-api-review.md" | '
                        "Select-Object Name, Length, LastWriteTime"
                    ),
                    "exit_code": 0,
                    "passed": True,
                    "output_preview": "langchain-mini-chat-api-review.md   5367 2026/5/25 8:14:15",
                },
                "verification_intent": {
                    "stage": "verify_output",
                    "obligation": "verify_command",
                    "authority": "harness.loop.agent_phase_pipeline",
                },
            },
        },
    )
    ledger = ToolObservationLedger(ledger_id="ledger:action-gate-verify", task_run_id="taskrun:action-gate-verify")
    ledger = ledger.append(
        build_tool_observation_record(
            observation_ref="obs:terminal-get-item",
            tool_name="terminal",
            result={"result_envelope": envelope.to_dict()},
        )
    )

    assert ledger.has_verification() is True
    assert ledger.verification_passed() is True
    assert "verify_command" in ledger.records[0].satisfies


def test_unstructured_write_and_terminal_results_do_not_satisfy_hard_evidence() -> None:
    ledger = ToolObservationLedger(ledger_id="ledger:unstructured", task_run_id="taskrun:unstructured")
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
    assert ledger.records[0].evidence_source == "unstructured_result"
    assert ledger.records[0].observed_paths == ()
    assert ledger.records[0].side_effect_hash == ""
    assert ledger.records[0].debug_hints["reason"] == "missing_result_envelope"
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


def test_tool_observation_record_keeps_freshness_separate_from_evidence() -> None:
    envelope = build_tool_result_envelope(
        tool_name="write_file",
        tool_args={"path": "output/result.md"},
        result={
            "text": "Write succeeded: output/result.md",
            "structured_payload": {
                "observed_paths": ["output/result.md"],
                "artifact_refs": [{"path": "output/result.md", "kind": "file"}],
            },
        },
    )
    record = build_tool_observation_record(
        observation_ref="obs:fresh-write",
        tool_name="write_file",
        result={"result_envelope": envelope.to_dict()},
        runtime_fingerprint={"tool_config_hash": "current"},
        freshness={"visibility": "active", "reuse_as_fact": True},
        structured_error={},
    )
    ledger = ToolObservationLedger(ledger_id="ledger:freshness", task_run_id="taskrun:freshness").append(record)

    assert ledger.has_write("output/result.md") is True
    assert record.runtime_freshness["visibility"] == "active"
    assert record.structured_error == {}


def test_protocol_boundary_detects_command_tool_markup() -> None:
    result = detect_protocol_leak('<｜｜DSML｜｜invoke name="command">pytest -q</｜｜DSML｜｜invoke>')

    assert result.detected is True
    assert "name=\"command\"" in result.markers
    assert strip_protocol_leak('正常回答\nname="command" pytest -q').strip() == "正常回答"

