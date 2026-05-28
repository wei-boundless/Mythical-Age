from __future__ import annotations

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
NEW_GRAPH_FILES = [
    BACKEND_DIR / "harness" / "graph_harness.py",
    *(BACKEND_DIR / "harness" / "graph").glob("*.py"),
]


def test_new_graph_harness_does_not_use_old_stage_request_protocol() -> None:
    forbidden = (
        "stage_execution_request",
        "execution_runtime_kind",
        "NodeExecutionRequest",
        "GraphCoordination",
        "TaskGraphRuntimeSpec",
        "compile_task_graph_definition_runtime_spec",
        "TaskFlowRegistry",
        "graph_module",
        "linked_config_id",
        "modules",
    )
    offenders: dict[str, list[str]] = {}
    for path in NEW_GRAPH_FILES:
        text = path.read_text(encoding="utf-8")
        hits = [item for item in forbidden if item in text]
        if hits:
            offenders[str(path.relative_to(BACKEND_DIR))] = hits

    assert offenders == {}


def test_new_graph_harness_public_contract_uses_graph_run_language() -> None:
    text = (BACKEND_DIR / "harness" / "graph_harness.py").read_text(encoding="utf-8")

    assert "graph_run" in text
    assert "coordination_run" not in text
