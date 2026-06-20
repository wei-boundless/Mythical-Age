from __future__ import annotations

from types import SimpleNamespace

from runtime.memory.file_evidence_scope import task_run_file_evidence_scope
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime.memory.tool_memory_events import (
    TOOL_MEMORY_COMMIT_AUTHORITY,
    build_tool_memory_events_from_envelope,
    build_tool_memory_events_from_file_state_events,
    commit_tool_memory_events_from_envelope,
)
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope


def test_tool_memory_events_wrap_file_state_events_with_explicit_target() -> None:
    events = build_tool_memory_events_from_file_state_events(
        (
            {
                "event_type": "recommended_read_window_created",
                "path": "docs/plan.md",
                "start_line": 1,
                "line_count": 4,
            },
        ),
        source_tool_name="search_text",
        observation_ref="obs:search",
        tool_call_id="call:search",
    )

    assert events == (
        {
            "event_type": "recommended_read_window_created",
            "memory_target": "file_state",
            "payload": {
                "event_type": "recommended_read_window_created",
                "path": "docs/plan.md",
                "start_line": 1,
                "line_count": 4,
            },
            "path": "docs/plan.md",
            "source_tool_name": "search_text",
            "source_observation_ref": "obs:search",
            "tool_call_id": "call:search",
            "authority": "runtime.memory.tool_memory_events",
        },
    )


def test_tool_memory_commit_persists_search_recommendations_to_file_state(tmp_path) -> None:
    scope = task_run_file_evidence_scope("taskrun:tool-memory")
    envelope = build_tool_result_envelope(
        tool_name="search_text",
        tool_args={"query": "needle", "paths": ["docs/plan.md"]},
        result={
            "text": "docs/plan.md:2:1:needle here",
            "structured_payload": {
                "matched_paths": ["docs/plan.md"],
                "tool_result": {
                    "kind": "text_search",
                    "query": "needle",
                    "matches": [{"path": "docs/plan.md", "line": 2, "column": 1, "text": "needle here"}],
                    "recommended_read_windows": [
                        {
                            "path": "docs/plan.md",
                            "start_line": 1,
                            "line_count": 4,
                            "match_line": 2,
                            "query": "needle",
                            "reason": "small file contains match near line 2",
                        }
                    ],
                },
            },
        },
        tool_call_id="call:search",
    )

    commit = commit_tool_memory_events_from_envelope(
        envelope=envelope,
        file_evidence_scope=scope,
        observation_ref="obs:search",
        tool_call_id="call:search",
        runtime_host=SimpleNamespace(root_dir=tmp_path),
        source_tool_name="search_text",
    )
    snapshot = FileStateAuthorityStore(tmp_path).snapshot_scope(scope)

    assert commit["authority"] == TOOL_MEMORY_COMMIT_AUTHORITY
    assert commit["status"] == "committed"
    assert commit["tool_memory_event_count"] == 2
    assert commit["file_state_event_count"] == 2
    assert commit["ledger_event_count"] == 0
    assert commit["committed_targets"] == ["file_state"]
    assert commit["memory_delta"]["persistent_targets"] == ["file_state"]
    assert commit["memory_delta"]["non_persistent_targets"] == []
    assert commit["file_state_commit"]["event_count"] == 2
    assert snapshot[0]["path"] == "docs/plan.md"
    assert snapshot[0]["recommended_read_windows"][0]["start_line"] == 1
    assert snapshot[0]["recommended_read_windows"][0]["source_observation_ref"] == "obs:search"


def test_tool_memory_commit_reports_missing_scope_without_committing() -> None:
    envelope = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "README.md"},
        result={
            "text": "1 | title",
            "structured_payload": {
                "observed_paths": ["README.md"],
                "tool_result": {
                    "kind": "text_file",
                    "path": "README.md",
                    "start_line": 1,
                    "end_line": 1,
                    "returned_lines": 1,
                    "line_count": 1,
                    "total_lines": 1,
                    "has_more": False,
                },
            },
        },
    )

    commit = commit_tool_memory_events_from_envelope(
        envelope=envelope,
        file_evidence_scope={},
        observation_ref="obs:read",
    )

    assert commit["status"] == "skipped"
    assert commit["skipped_reason"] == "missing_file_evidence_scope"
    assert commit["tool_memory_event_count"] == 1


def test_tool_memory_events_record_command_receipts_without_persistence(tmp_path) -> None:
    envelope = build_tool_result_envelope(
        tool_name="terminal",
        tool_args={"command": "python -m pytest backend/tests/foo.py -q"},
        result={
            "text": "1 passed",
            "structured_payload": {
                "command_receipt": {
                    "command": "python -m pytest backend/tests/foo.py -q",
                    "exit_code": 0,
                    "passed": True,
                    "output_preview": "1 passed",
                }
            },
        },
        tool_call_id="call:terminal",
    )

    events = build_tool_memory_events_from_envelope(
        envelope,
        source_tool_name="terminal",
        observation_ref="obs:terminal",
        tool_call_id="call:terminal",
    )
    commit = commit_tool_memory_events_from_envelope(
        envelope=envelope,
        file_evidence_scope={},
        observation_ref="obs:terminal",
        tool_call_id="call:terminal",
        runtime_host=SimpleNamespace(root_dir=tmp_path),
        source_tool_name="terminal",
    )

    assert len(events) == 1
    assert events[0]["memory_target"] == "command_state"
    assert events[0]["event_type"] == "command_observed"
    assert events[0]["payload"]["passed"] is True
    assert events[0]["payload"]["exit_code"] == 0
    assert commit["status"] == "observed"
    assert commit["committed_targets"] == []
    assert commit["memory_targets"] == ["command_state"]
    assert commit["non_persistent_event_count"] == 1
    assert commit["memory_delta"]["persistent_targets"] == []
    assert commit["memory_delta"]["non_persistent_targets"] == ["command_state"]
    assert commit["memory_delta"]["authority_boundary"] == "observation_feedback_only"


def test_tool_memory_events_record_tool_failures_as_observations() -> None:
    envelope = build_tool_result_envelope(
        tool_name="terminal",
        tool_args={"command": "python -m pytest backend/tests/foo.py -q"},
        status="error",
        result={
            "text": "1 failed",
            "structured_payload": {
                "command_receipt": {
                    "command": "python -m pytest backend/tests/foo.py -q",
                    "exit_code": 1,
                    "passed": False,
                    "output_preview": "1 failed",
                    "failure_kind": "command_exit_nonzero",
                }
            },
        },
        tool_call_id="call:terminal",
    )

    events = build_tool_memory_events_from_envelope(
        envelope,
        source_tool_name="terminal",
        observation_ref="obs:terminal",
        tool_call_id="call:terminal",
    )

    assert [event["memory_target"] for event in events] == ["command_state", "tool_failure_state"]
    failure = events[1]
    assert failure["event_type"] == "tool_failure_observed"
    assert failure["payload"]["status"] == "error"
    assert failure["payload"]["command_receipt"]["passed"] is False


def test_tool_memory_events_record_artifact_and_explicit_verification_targets(tmp_path) -> None:
    envelope = build_tool_result_envelope(
        tool_name="terminal",
        tool_args={"command": "Get-Item output/report.md"},
        result={
            "text": "output/report.md 1024",
            "structured_payload": {
                "artifact_refs": [{"path": "output/report.md", "kind": "document"}],
                "verification_events": [
                    {
                        "event_type": "verification_completed",
                        "stage": "verify_output",
                        "obligation": "verify_command",
                        "passed": True,
                    }
                ],
                "command_receipt": {
                    "command": "Get-Item output/report.md",
                    "exit_code": 0,
                    "passed": True,
                    "output_preview": "output/report.md 1024",
                },
            },
        },
        tool_call_id="call:terminal",
    )

    commit = commit_tool_memory_events_from_envelope(
        envelope=envelope,
        file_evidence_scope={},
        observation_ref="obs:terminal",
        tool_call_id="call:terminal",
        runtime_host=SimpleNamespace(root_dir=tmp_path),
        source_tool_name="terminal",
    )

    assert commit["status"] == "observed"
    assert commit["committed_targets"] == []
    assert commit["memory_target_counts"] == {
        "artifact_state": 1,
        "command_state": 1,
        "verification_state": 1,
    }
