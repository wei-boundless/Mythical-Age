from __future__ import annotations

from pathlib import Path

from memory_system.paths import safe_runtime_session_key, safe_session_dir


def test_safe_session_dir_uses_path_safe_key_for_graph_node_session_ids(tmp_path: Path) -> None:
    session_id = "gsess:grun_graph:node:2"

    target = safe_session_dir(tmp_path, session_id)

    assert target == tmp_path.resolve() / "gsess_grun_graph_node_2"
    assert safe_runtime_session_key(session_id) == "gsess_grun_graph_node_2"
