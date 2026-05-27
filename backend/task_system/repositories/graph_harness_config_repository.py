from __future__ import annotations

from pathlib import Path
from typing import Any


class GraphHarnessConfigRepository:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def list(self) -> list[Any]:
        return []

    def get(self, config_id: str) -> Any | None:
        del config_id
        return None

    def get_published_for_graph(self, graph_id: str) -> Any | None:
        del graph_id
        return None

    def upsert(self, config: Any, *, publish: bool = True) -> Any:
        del config, publish
        raise RuntimeError("GraphHarnessConfig repository is not available in the rebuilt single-agent runtime")

    def published_bindings(self) -> dict[str, str]:
        return {}
