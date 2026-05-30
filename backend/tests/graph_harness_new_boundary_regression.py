from __future__ import annotations

from pathlib import Path
import ast


BACKEND_DIR = Path(__file__).resolve().parents[1]
NEW_GRAPH_FILES = [
    BACKEND_DIR / "harness" / "graph_harness.py",
    *(BACKEND_DIR / "harness" / "graph").glob("*.py"),
]


def test_graph_harness_imports_only_harness_graph_layers() -> None:
    imports_by_file: dict[str, set[str]] = {}
    for path in NEW_GRAPH_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        imports_by_file[str(path.relative_to(BACKEND_DIR))] = imports

    assert any("graph.runtime" in imports for imports in imports_by_file.values())
    assert any("graph.loop" in imports for imports in imports_by_file.values())
    assert all(not any(item.startswith("task_system") for item in imports) for imports in imports_by_file.values())


def test_new_graph_harness_public_contract_uses_graph_run_language() -> None:
    text = (BACKEND_DIR / "harness" / "graph_harness.py").read_text(encoding="utf-8")

    assert "GraphHarnessStart" in text
    assert "graph_run_id" in text
    assert "get_graph_run_monitor" in text


def test_graph_loop_does_not_materialize_agent_input_package_inline() -> None:
    loop_text = (BACKEND_DIR / "harness" / "graph" / "loop.py").read_text(encoding="utf-8")
    materializer_text = (BACKEND_DIR / "harness" / "graph" / "context_materializer.py").read_text(encoding="utf-8")

    assert "harness.graph_node_input_package" not in loop_text
    assert "harness.graph_edge_handoff_packet" not in loop_text
    assert "agent_instruction" not in loop_text
    assert "harness.graph_node_input_package" not in materializer_text
    assert "harness.graph.node_materialization_package" in materializer_text
    assert "harness.graph.context_materializer" in materializer_text
