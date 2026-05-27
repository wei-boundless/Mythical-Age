from __future__ import annotations

from typing import Any

__all__ = ["build_server", "mcp"]


def __getattr__(name: str) -> Any:
    if name in {"build_server", "mcp"}:
        from . import server

        return getattr(server, name)
    raise AttributeError(name)


