from __future__ import annotations

from pathlib import Path

from tools.read_file_tool import ReadFileTool
from tools.search_files_tool import SearchFilesTool, SearchTextTool
from understanding.task_understanding import analyze_task_understanding


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_search_files_finds_workspace_root_docs_from_backend_runtime() -> None:
    tool = SearchFilesTool(root_dir=BACKEND_ROOT)

    output = tool.invoke({"query": "OpenClaw", "roots": ["docs"], "max_results": 5})

    assert "docs/26-OpenClaw-架构改造计划.md" in output


def test_search_text_finds_content_with_safe_relative_paths() -> None:
    tool = SearchTextTool(root_dir=BACKEND_ROOT)

    output = tool.invoke(
        {
            "query": "quality_warnings",
            "roots": ["backend/tests"],
            "glob": "**/*.py",
            "max_results": 10,
        }
    )

    assert "backend/tests/system_eval/long_runner_warning_regression.py" in output


def test_read_file_can_read_workspace_root_docs_without_breaking_backend_paths() -> None:
    tool = ReadFileTool(root_dir=BACKEND_ROOT)

    docs_output = tool.invoke({"path": "docs/26-OpenClaw-架构改造计划.md"})
    backend_output = tool.invoke({"path": "understanding/task_understanding.py"})

    assert "OpenClaw" in docs_output
    assert "TaskUnderstanding" in backend_output


def test_workspace_search_routes_to_search_files() -> None:
    understanding = analyze_task_understanding("帮我查找 OpenClaw 相关文件路径")

    assert understanding.route_hint == "tool"
    assert understanding.task_kind == "workspace_file_search"
    assert understanding.candidate_tools == ["search_files"]
    assert understanding.capability_requests == ["workspace_search"]
