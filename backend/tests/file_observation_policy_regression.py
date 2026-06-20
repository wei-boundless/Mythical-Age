from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.shared.file_observation_policy import (
    FILE_OBSERVATION_POLICY_AUTHORITY,
    READ_FILE_DEFAULT_LINE_COUNT,
    READ_FILE_FULL_FILE_LINE_LIMIT,
    READ_FILE_MAX_LINE_COUNT,
    SEARCH_MATCH_DEFAULT_CONTEXT_LINES,
    read_window_fingerprint_defaults,
    recommended_window_for_continuation,
    recommended_window_for_gap,
    recommended_windows_for_matches,
    select_read_window,
)


def test_policy_reads_small_files_in_one_window_when_line_count_is_omitted() -> None:
    selection = select_read_window(total_lines=42, start_line=1)

    assert selection.start_line == 1
    assert selection.line_count == 42
    assert selection.end_line == 42
    assert selection.reason == "small_file_full_read"
    assert selection.authority == FILE_OBSERVATION_POLICY_AUTHORITY


def test_policy_uses_controlled_large_window_and_clamps_explicit_requests() -> None:
    default_selection = select_read_window(total_lines=READ_FILE_FULL_FILE_LINE_LIMIT + 500, start_line=1)
    explicit_selection = select_read_window(
        total_lines=READ_FILE_FULL_FILE_LINE_LIMIT + 500,
        start_line=1,
        requested_line_count=READ_FILE_MAX_LINE_COUNT + 500,
    )

    assert default_selection.line_count == READ_FILE_DEFAULT_LINE_COUNT
    assert default_selection.reason == "default_large_window"
    assert explicit_selection.line_count == READ_FILE_MAX_LINE_COUNT
    assert explicit_selection.requested_line_count == READ_FILE_MAX_LINE_COUNT + 500
    assert explicit_selection.reason == "explicit_line_count"


def test_policy_recommends_full_read_for_search_match_in_small_file() -> None:
    windows = recommended_windows_for_matches(
        [{"path": "docs/plan.md", "line": 12, "text": "needle"}],
        total_lines_by_path={"docs/plan.md": 80},
        query="needle",
        context_lines=1,
    )

    assert windows == [
        {
            "path": "docs/plan.md",
            "start_line": 1,
            "line_count": 80,
            "match_line": 12,
            "query": "needle",
            "reason": "small file contains match near line 12",
            "authority": FILE_OBSERVATION_POLICY_AUTHORITY,
        }
    ]


def test_policy_recommends_bounded_match_window_for_large_file() -> None:
    windows = recommended_windows_for_matches(
        [{"path": "backend/app.py", "line": 500, "text": "needle"}],
        total_lines_by_path={"backend/app.py": 5000},
        query="needle",
    )

    assert windows == [
        {
            "path": "backend/app.py",
            "start_line": 500 - SEARCH_MATCH_DEFAULT_CONTEXT_LINES,
            "line_count": (SEARCH_MATCH_DEFAULT_CONTEXT_LINES * 2) + 1,
            "match_line": 500,
            "query": "needle",
            "reason": "match near line 500",
            "authority": FILE_OBSERVATION_POLICY_AUTHORITY,
        }
    ]


def test_policy_gap_and_continuation_windows_are_shared_with_runtime_guards() -> None:
    gap = recommended_window_for_gap(start_line=101, end_line=199, total_lines=300)
    continuation = recommended_window_for_continuation(next_start_line=901, total_lines=1200)
    defaults = read_window_fingerprint_defaults()

    assert gap["start_line"] == 101
    assert gap["line_count"] == 99
    assert gap["authority"] == FILE_OBSERVATION_POLICY_AUTHORITY
    assert continuation["start_line"] == 901
    assert continuation["line_count"] == 300
    assert continuation["authority"] == FILE_OBSERVATION_POLICY_AUTHORITY
    assert defaults == {"start_line": 1, "line_count": READ_FILE_DEFAULT_LINE_COUNT}
