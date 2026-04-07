from __future__ import annotations

from pathlib import Path

from .memory_manager import MemoryManager


class TeamMemoryManager(MemoryManager):
    """Shared memory subtree.

    This local implementation provides path isolation and a hook point for
    later remote sync. It mirrors the TS design where team memory lives under
    auto-memory as a subdirectory.
    """

    def __init__(self, root_dir: str | Path) -> None:
        self._base_root = Path(root_dir).resolve()
        super().__init__(self._base_root / "team")

    def validate_relative_key(self, key: str) -> Path:
        if "\x00" in key or key.startswith("/") or ".." in key or "\\" in key:
            raise ValueError(f"Unsafe team memory key: {key}")
        candidate = (self.root_dir / key).resolve()
        if self.root_dir not in candidate.parents and candidate != self.root_dir:
            raise ValueError(f"Team memory path escapes root: {key}")
        return candidate

    def sync_pull(self) -> None:
        """Placeholder for server-to-local sync."""

    def sync_push(self) -> None:
        """Placeholder for local-to-server sync."""
