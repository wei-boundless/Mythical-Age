from __future__ import annotations

from runtime.shared.file_observation_policy import FILE_OBSERVATION_POLICY_AUTHORITY
from runtime.memory.file_state_authority import FileStateAuthority
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope


def test_file_state_authority_tracks_partial_read_without_implicit_next_read() -> None:
    envelope = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "backend/app.py", "start_line": 1, "line_count": 2},
        result={
            "text": "1 | a\n2 | b",
            "structured_payload": {
                "observed_paths": ["backend/app.py"],
                "tool_result": {
                    "kind": "text_file",
                    "path": "backend/app.py",
                    "start_line": 1,
                    "end_line": 2,
                    "returned_lines": 2,
                    "line_count": 2,
                    "total_lines": 5,
                    "next_start_line": 3,
                    "has_more": True,
                    "content_sha256": "sha256:before",
                    "read_intent": "edit_target",
                },
            },
        },
        tool_call_id="call:read",
        action_request_id="rtact:read",
        caller_kind="task_run",
        caller_ref="taskrun:file-state",
    )

    authority = FileStateAuthority.from_observations(
        [{"observation_id": "obs:read", "payload": {"result_envelope": envelope.to_dict()}}],
        task_run_id="taskrun:file-state",
    )
    projection = authority.projection()

    assert projection[0]["path"] == "backend/app.py"
    assert projection[0]["status"] == "partial"
    assert projection[0]["coverage"]["start_line"] == 1
    assert projection[0]["coverage"]["end_line"] == 2
    assert projection[0]["coverage"]["range_count"] == 1
    assert projection[0]["coverage"]["complete"] is False
    assert projection[0]["coverage"]["missing_ranges"] == [{"start_line": 3, "end_line": 5}]
    assert projection[0]["read_ranges"][0]["read_intent"] == "edit_target"
    assert "next_suggested_read" not in projection[0]
    assert projection[0]["last_tool_call_id"] == "call:read"


def test_file_state_authority_does_not_backfill_tool_call_id_from_wrapper_payload() -> None:
    envelope = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "backend/app.py", "start_line": 1, "line_count": 1},
        result={
            "text": "1 | a",
            "structured_payload": {
                "observed_paths": ["backend/app.py"],
                "tool_result": {
                    "kind": "text_file",
                    "path": "backend/app.py",
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

    authority = FileStateAuthority.from_observations(
        [
            {
                "observation_id": "obs:read:wrapper-shadow",
                "payload": {
                    "tool_call_id": "call:wrapper-shadow",
                    "result_envelope": {
                        key: value
                        for key, value in envelope.to_dict().items()
                        if key != "tool_call_id"
                    },
                },
            }
        ],
        task_run_id="taskrun:file-state",
    )
    state = authority.projection()[0]

    assert state["last_observation_ref"] == "obs:read:wrapper-shadow"
    assert "last_tool_call_id" not in state


def test_file_state_authority_marks_reads_stale_after_write() -> None:
    read_envelope = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "backend/app.py", "start_line": 1, "line_count": 10},
        result={
            "text": "1 | a",
            "structured_payload": {
                "observed_paths": ["backend/app.py"],
                "tool_result": {
                    "kind": "text_file",
                    "path": "backend/app.py",
                    "start_line": 1,
                    "end_line": 1,
                    "returned_lines": 1,
                    "line_count": 10,
                    "total_lines": 1,
                    "has_more": False,
                    "content_sha256": "sha256:before",
                },
            },
        },
    )
    write_envelope = build_tool_result_envelope(
        tool_name="edit_file",
        tool_args={"path": "backend/app.py", "old_text": "a", "new_text": "b"},
        result={
            "text": "Edit succeeded: backend/app.py",
            "structured_payload": {
                "observed_paths": ["backend/app.py"],
                "artifact_refs": [{"path": "backend/app.py", "kind": "file", "source": "edit_file"}],
                "tool_result": {"kind": "file_edit", "path": "backend/app.py", "sha256": "sha256:after"},
            },
        },
    )

    authority = FileStateAuthority.from_observations(
        [
            {"observation_id": "obs:read", "payload": {"result_envelope": read_envelope.to_dict()}},
            {"observation_id": "obs:edit", "payload": {"result_envelope": write_envelope.to_dict()}},
        ],
        task_run_id="taskrun:file-state",
    )
    state = authority.projection()[0]

    assert state["status"] == "stale"
    assert state["read_ranges"][0]["stale"] is True
    assert state["write_events"][0]["operation"] == "edit"
    assert state["next_suggested_read"]["start_line"] == 1


def test_file_state_authority_keeps_complete_aggregate_after_later_partial_window() -> None:
    authority = FileStateAuthority(task_run_id="taskrun:file-state-complete")
    for index, (start, end) in enumerate(((1, 200), (201, 440), (441, 680), (681, 957)), start=1):
        authority = authority.apply_event(
            {
                "event_type": "read",
                "path": "mario.html",
                "start_line": start,
                "end_line": end,
                "total_lines": 957,
                "has_more": end < 957,
                "content_sha256": "sha256:mario",
            },
            observation_ref=f"obs:read:{index}",
            tool_call_id=f"call:read:{index}",
        )
    authority = authority.apply_event(
        {
            "event_type": "read",
            "path": "mario.html",
            "start_line": 320,
            "end_line": 409,
            "total_lines": 957,
            "has_more": True,
            "content_sha256": "sha256:mario",
        },
        observation_ref="obs:read:local-window",
        tool_call_id="call:read:local-window",
    )

    state = authority.projection()[0]

    assert state["status"] == "complete"
    assert state["has_more"] is False
    assert "next_suggested_read" not in state
    assert state["coverage"]["complete"] is True
    assert state["coverage"]["start_line"] == 1
    assert state["coverage"]["end_line"] == 957
    assert state["coverage"]["merged_ranges"] == [{"start_line": 1, "end_line": 957}]
    assert "missing_ranges" not in state["coverage"]
    assert state["last_observation_ref"] == "obs:read:local-window"


def test_file_state_authority_reports_gap_without_implicit_next_read() -> None:
    authority = FileStateAuthority(task_run_id="taskrun:file-state-gap")
    for index, (start, end) in enumerate(((1, 100), (200, 300)), start=1):
        authority = authority.apply_event(
            {
                "event_type": "read",
                "path": "src/app.py",
                "start_line": start,
                "end_line": end,
                "total_lines": 300,
                "has_more": False,
                "content_sha256": "sha256:app",
            },
            observation_ref=f"obs:gap:{index}",
            tool_call_id=f"call:gap:{index}",
        )

    state = authority.projection()[0]

    assert state["status"] == "partial"
    assert state["has_more"] is True
    assert state["coverage"]["complete"] is False
    assert state["coverage"]["missing_ranges"] == [{"start_line": 101, "end_line": 199}]
    assert "next_suggested_read" not in state


def test_file_state_authority_projection_keeps_recent_updates_over_path_sort() -> None:
    authority = FileStateAuthority(task_run_id="taskrun:file-state-recency")
    for index in range(25):
        authority = authority.apply_event(
            {
                "event_type": "read",
                "path": f"z{index:02}.py",
                "start_line": 1,
                "end_line": 1,
                "total_lines": 1,
                "has_more": False,
            },
            observation_ref=f"obs:z{index:02}",
        )
    authority = authority.apply_event(
        {
            "event_type": "read",
            "path": "a.py",
            "start_line": 1,
            "end_line": 1,
            "total_lines": 1,
            "has_more": False,
        },
        observation_ref="obs:a-latest",
    )

    projection = authority.projection(limit=20)
    paths = [item["path"] for item in projection]

    assert "a.py" in paths
    assert projection[-1]["path"] == "a.py"
    assert projection[-1]["last_observation_ref"] == "obs:a-latest"


def test_file_state_authority_tracks_search_hits_without_reading_full_file() -> None:
    envelope = build_tool_result_envelope(
        tool_name="search_text",
        tool_args={"query": "FileStateAuthority"},
        result={
            "text": "backend/runtime/memory/file_state_authority.py:1:1:class FileStateAuthority",
            "structured_payload": {
                "matched_paths": ["backend/runtime/memory/file_state_authority.py"],
                "tool_result": {
                    "kind": "text_search",
                    "query": "FileStateAuthority",
                    "matches": [
                        {
                            "path": "backend/runtime/memory/file_state_authority.py",
                            "line": 1,
                            "column": 1,
                            "text": "class FileStateAuthority",
                        }
                    ],
                },
            },
        },
    )

    authority = FileStateAuthority.from_observations(
        [{"observation_id": "obs:search", "payload": {"result_envelope": envelope.to_dict()}}],
        task_run_id="taskrun:file-state",
    )
    state = authority.projection()[0]

    assert state["status"] == "matched"
    assert state["search_hits"][0]["query"] == "FileStateAuthority"
    assert "read_ranges" not in state


def test_file_state_authority_stores_and_consumes_search_read_recommendations() -> None:
    search_envelope = build_tool_result_envelope(
        tool_name="search_text",
        tool_args={"query": "needle", "paths": ["docs/plan.md"]},
        result={
            "text": "docs/plan.md:2:1:needle here",
            "structured_payload": {
                "matched_paths": ["docs/plan.md"],
                "tool_result": {
                    "kind": "text_search",
                    "query": "needle",
                    "matches": [
                        {
                            "path": "docs/plan.md",
                            "line": 2,
                            "column": 1,
                            "text": "needle here",
                        }
                    ],
                    "recommended_read_windows": [
                        {
                            "path": "docs/plan.md",
                            "start_line": 1,
                            "line_count": 4,
                            "match_line": 2,
                            "query": "needle",
                            "reason": "small file contains match near line 2",
                            "authority": FILE_OBSERVATION_POLICY_AUTHORITY,
                        }
                    ],
                },
            },
        },
        tool_call_id="call:search",
    )

    authority = FileStateAuthority.from_observations(
        [{"observation_id": "obs:search", "payload": {"result_envelope": search_envelope.to_dict()}}],
        task_run_id="taskrun:file-state",
    )
    matched = authority.projection()[0]

    assert matched["status"] == "matched"
    assert matched["recommended_read_windows"][0]["decision"] == "read_search_recommendation"
    assert matched["recommended_read_windows"][0]["path"] == "docs/plan.md"
    assert matched["recommended_read_windows"][0]["start_line"] == 1
    assert matched["recommended_read_windows"][0]["line_count"] == 4
    assert matched["recommended_read_windows"][0]["match_line"] == 2
    assert matched["recommended_read_windows"][0]["source_observation_ref"] == "obs:search"
    assert matched["next_suggested_read"]["decision"] == "read_search_recommendation"

    authority = authority.apply_event(
        {
            "event_type": "read",
            "path": "docs/plan.md",
            "start_line": 1,
            "end_line": 4,
            "total_lines": 4,
            "has_more": False,
            "content_sha256": "sha256:plan",
        },
        observation_ref="obs:read",
        tool_call_id="call:read",
    )
    consumed = authority.projection()[0]

    assert consumed["status"] == "complete"
    assert "recommended_read_windows" not in consumed
    assert consumed["read_recommendations"][0]["status"] == "consumed"
    assert "next_suggested_read" not in consumed
