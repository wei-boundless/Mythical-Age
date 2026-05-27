from __future__ import annotations

from pathlib import Path
from typing import Any


def publish_graph_harness_config_for_graph(
    *,
    base_dir: Path,
    graph_id: str,
    publish_version: str = "published",
    _visited: set[str] | None = None,
) -> Any:
    del base_dir, graph_id, publish_version, _visited
    raise RuntimeError("GraphHarnessConfig publication is not available in the rebuilt single-agent runtime")
