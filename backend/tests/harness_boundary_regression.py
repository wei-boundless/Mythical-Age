from __future__ import annotations

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_production_harness_does_not_import_test_harness() -> None:
    production_files = [
        path
        for path in BACKEND_DIR.rglob("*.py")
        if "__pycache__" not in path.parts and "tests" not in path.parts
    ]

    offenders: list[str] = []
    for path in production_files:
        text = path.read_text(encoding="utf-8")
        if (
            "tests.harness" in text
            or "backend.tests.harness" in text
            or "tests.test_runtime_support" in text
            or "backend.tests.test_runtime_support" in text
        ):
            offenders.append(str(path.relative_to(BACKEND_DIR)))

    assert offenders == []


def test_obsolete_runtime_control_packages_are_removed() -> None:
    removed_paths = [
        "runtime/agent_runtime",
        "runtime/graph_task_runtime",
        "runtime/subruntime",
        "runtime/search_agent_runtime",
        "runtime/codebase_search_runtime",
        "runtime/unit_runtime",
        "runtime/execution",
        "runtime/execution_engine",
        "runtime/execution_permit",
        "runtime/coordination_runtime",
    ]

    assert [path for path in removed_paths if (BACKEND_DIR / path).exists()] == []


def test_test_support_does_not_reuse_core_harness_module_name() -> None:
    assert not (BACKEND_DIR / "tests" / "harness").exists()


