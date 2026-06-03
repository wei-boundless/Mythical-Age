from __future__ import annotations

from pathlib import Path


def resolve_capability_backend_dir(base_dir: str | Path) -> Path:
    """Return the backend package root that owns capability_system code.

    Runtime callers usually pass the backend directory, while tests and a few
    tooling paths may pass the project root. Capability registries are code
    catalog artifacts, so when a project root contains a real backend package we
    pin capability paths to that backend package instead of creating a sibling
    root-level capability_system directory.
    """

    resolved = Path(base_dir).resolve()
    backend_candidate = resolved / "backend"
    if _looks_like_capability_backend(backend_candidate):
        return backend_candidate.resolve()
    if _looks_like_capability_backend(resolved):
        return resolved
    return resolved


def _looks_like_capability_backend(path: Path) -> bool:
    capability_dir = path / "capability_system"
    return (
        capability_dir.is_dir()
        and (path / "app.py").is_file()
        and (capability_dir / "skills").is_dir()
        and (capability_dir / "tools").is_dir()
    )
