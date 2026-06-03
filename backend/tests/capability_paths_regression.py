from __future__ import annotations

from pathlib import Path

from capability_system.mcp.paths import CapabilityMCPPaths
from capability_system.paths import resolve_capability_backend_dir
from capability_system.skills.paths import CapabilitySkillPaths
from capability_system.tools.paths import CapabilityToolPaths


def test_capability_paths_pin_project_root_input_to_backend_package(tmp_path: Path) -> None:
    project_root = tmp_path
    backend_dir = _make_backend_package(project_root)
    (project_root / "capability_system" / "skills").mkdir(parents=True)

    assert resolve_capability_backend_dir(project_root) == backend_dir

    skill_paths = CapabilitySkillPaths.from_base_dir(project_root)
    tool_paths = CapabilityToolPaths.from_base_dir(project_root)
    mcp_paths = CapabilityMCPPaths.from_base_dir(project_root)

    assert skill_paths.base_dir == backend_dir
    assert tool_paths.base_dir == backend_dir
    assert mcp_paths.base_dir == backend_dir
    assert skill_paths.skills_registry_path.parent == backend_dir / "capability_system" / "skills" / "registries"
    assert tool_paths.tools_registry_path.parent == backend_dir / "capability_system" / "tools" / "registries"
    assert mcp_paths.external_servers_path == backend_dir / "mcp_external_servers.json"


def test_capability_path_ensure_does_not_create_project_root_capability_system(tmp_path: Path) -> None:
    project_root = tmp_path
    backend_dir = _make_backend_package(project_root)

    CapabilitySkillPaths.from_base_dir(project_root).ensure()
    CapabilityToolPaths.from_base_dir(project_root).ensure()
    CapabilityMCPPaths.from_base_dir(project_root).ensure()

    assert (backend_dir / "capability_system" / "skills" / "builtin").is_dir()
    assert (backend_dir / "capability_system" / "skills" / "registries").is_dir()
    assert (backend_dir / "capability_system" / "tools" / "registries").is_dir()
    assert not (project_root / "capability_system").exists()


def _make_backend_package(project_root: Path) -> Path:
    backend_dir = project_root / "backend"
    (backend_dir / "capability_system" / "skills").mkdir(parents=True)
    (backend_dir / "capability_system" / "tools").mkdir(parents=True)
    (backend_dir / "capability_system" / "mcp").mkdir(parents=True)
    (backend_dir / "app.py").write_text("", encoding="utf-8")
    return backend_dir.resolve()
