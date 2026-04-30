from __future__ import annotations

from pathlib import Path

from test_system.agent import TestAgentAdvisor


def test_test_agent_reports_registry_and_orphan_files(tmp_path: Path) -> None:
    backend_root = tmp_path / "backend"
    tests_root = backend_root / "tests"
    tests_root.mkdir(parents=True)
    (tests_root / "unregistered_regression.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )

    report = TestAgentAdvisor(backend_root).build_report()

    assert report["authority"] == "test_system.test_agent"
    assert "tests/unregistered_regression.py" in report["unregistered_paths"]
    assert any(item["code"] == "unregistered_test_file" for item in report["findings"])


def test_test_agent_exposes_profile_targets_from_case_registry() -> None:
    report = TestAgentAdvisor().build_report()

    assert report["profile_targets"]["chain"]
    assert "tests/test_system_runtime_loop_regression.py" in report["profile_targets"]["chain"]
    assert report["summary"]["active_case_count"] > 0
