from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from file_management import build_file_access_table, default_file_environment_registry, resolve_file_environment
from file_management.filesystem_adapter import FsspecLocalFileAdapter
from file_management.gateway import RepositoryRootResolver
from file_management.models import ManagedFileRepositorySpec, normalize_logical_path
from project_layout import ProjectLayout
from task_system.projects.project_instance import ProjectInstance
from task_system.projects.project_library_manifest import ProjectLibraryManifest, ProjectRepositoryBinding
from task_system.repositories.project_instance_repository import ProjectInstanceRepository
from task_system.repositories.project_library_manifest_repository import ProjectLibraryManifestRepository


@dataclass(frozen=True, slots=True)
class ProjectFileResolution:
    project: ProjectInstance
    manifest: ProjectLibraryManifest
    repository_binding: ProjectRepositoryBinding
    repository: ManagedFileRepositorySpec
    root: Path


class ProjectFileService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.layout = ProjectLayout.from_backend_dir(self.base_dir)
        self.project_repository = ProjectInstanceRepository(self.base_dir)
        self.manifest_repository = ProjectLibraryManifestRepository(self.base_dir)

    def list_environment_projects(self, environment_id: str) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.project_repository.list_for_environment(environment_id)]

    def project_payload(self, project_id: str) -> dict[str, Any]:
        project = self.project_repository.require(project_id)
        manifest = self.manifest_repository.require_for_project(project.project_id)
        return {
            "authority": "task_system.project_library",
            "project": project.to_dict(),
            "library": manifest.to_dict(),
        }

    def repositories(self, project_id: str) -> dict[str, Any]:
        project = self.project_repository.require(project_id)
        manifest = self.manifest_repository.require_for_project(project.project_id)
        environment = resolve_file_environment(manifest.file_profile_id, registry=default_file_environment_registry())
        repositories = []
        for binding in manifest.repositories:
            repo = environment.repository(binding.repository_id)
            if repo is None:
                continue
            repositories.append(
                {
                    **repo.to_dict(),
                    "project_role": binding.role,
                    "project_root_ref": binding.root_ref,
                    "project_lifecycle": binding.lifecycle,
                    "selected_roles": _repository_roles(manifest, binding.repository_id),
                    "readable": bool(binding.readable and repo.readable),
                    "writable": bool(binding.writable and repo.writable),
                    "searchable": bool(binding.searchable and repo.searchable),
                }
            )
        return {
            "authority": "task_system.project_repositories",
            "project_id": project.project_id,
            "library_id": manifest.library_id,
            "repositories": repositories,
            "summary": {"repository_count": len(repositories)},
        }

    def tree(self, project_id: str, repository_id: str, path: str = "", *, max_depth: int = 4, max_entries: int = 500) -> dict[str, Any]:
        resolved = self._resolve(project_id, repository_id)
        self._check_access(resolved, "read")
        root_path = _normalize_tree_path(path)
        adapter = FsspecLocalFileAdapter(resolved.root)
        start = resolved.root if not root_path else adapter.resolve(root_path)
        if not start.exists():
            raise FileNotFoundError(root_path or ".")
        if not start.is_dir():
            raise NotADirectoryError(root_path or ".")
        counter = {"count": 0, "truncated": False}
        tree = _tree_node(start, resolved.root, depth=0, max_depth=max(0, int(max_depth)), max_entries=max(1, int(max_entries)), counter=counter)
        return {
            "authority": "task_system.project_file_tree",
            "project_id": resolved.project.project_id,
            "library_id": resolved.manifest.library_id,
            "repository_id": resolved.repository.repository_id,
            "path": root_path,
            "total_entries": counter["count"],
            "truncated": counter["truncated"],
            "tree": tree,
        }

    def read_file(self, project_id: str, repository_id: str, path: str) -> dict[str, Any]:
        resolved = self._resolve(project_id, repository_id)
        self._check_access(resolved, "read")
        logical_path = normalize_logical_path(path)
        adapter = FsspecLocalFileAdapter(resolved.root)
        content = adapter.read_text(logical_path)
        return {
            "authority": "task_system.project_file",
            "project_id": resolved.project.project_id,
            "library_id": resolved.manifest.library_id,
            "repository_id": resolved.repository.repository_id,
            "path": logical_path,
            "content": content,
            "metadata": {
                "repository_kind": resolved.repository.repository_kind,
                "project_role": resolved.repository_binding.role,
                "project_root_ref": resolved.repository_binding.root_ref,
            },
        }

    def _resolve(self, project_id: str, repository_id: str) -> ProjectFileResolution:
        project = self.project_repository.require(project_id)
        manifest = self.manifest_repository.require_for_project(project.project_id)
        repo_id = str(repository_id or "").strip()
        repository_binding = manifest.repository(repo_id)
        if repository_binding is None:
            raise PermissionError("repository is not part of the project library")
        environment = resolve_file_environment(manifest.file_profile_id, registry=default_file_environment_registry())
        repository = environment.repository(repo_id)
        if repository is None:
            raise KeyError(f"unknown project repository: {repo_id}")
        return ProjectFileResolution(
            project=project,
            manifest=manifest,
            repository_binding=repository_binding,
            repository=repository,
            root=self._repository_root(project, repository, repository_binding),
        )

    def _repository_root(self, project: ProjectInstance, repository: ManagedFileRepositorySpec, binding: ProjectRepositoryBinding) -> Path:
        root_ref = str(binding.root_ref or repository.root_ref or "").strip()
        if root_ref.startswith("project://"):
            fragment = _safe_root_fragment(root_ref.removeprefix("project://"))
            return (self.layout.project_root / "storage" / "task_projects" / project.project_id / fragment).resolve()
        if root_ref.startswith("environment://"):
            fragment = _safe_root_fragment(root_ref.removeprefix("environment://"))
            namespace = _project_environment_storage_namespace(project.environment_id)
            return (self.layout.project_root / "storage" / "task_environments" / namespace / fragment).resolve()
        resolver = RepositoryRootResolver(project_root=self.layout.project_root)
        return resolver.resolve(repository).root

    def _check_access(self, resolved: ProjectFileResolution, action: str) -> None:
        if action == "read" and not resolved.repository_binding.readable:
            raise PermissionError(f"{action} denied for {resolved.repository.repository_id}")
        if action == "write" and not resolved.repository_binding.writable:
            raise PermissionError(f"{action} denied for {resolved.repository.repository_id}")
        environment = resolve_file_environment(resolved.manifest.file_profile_id, registry=default_file_environment_registry())
        table = build_file_access_table(environment, table_id=f"file-access:{resolved.manifest.environment_id}:{resolved.manifest.file_profile_id}")
        if not table.is_allowed(repository_id=resolved.repository.repository_id, action=action):
            raise PermissionError(f"{action} denied for {resolved.repository.repository_id}")


def _normalize_tree_path(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip().strip("/")
    if not raw:
        return ""
    if "://" in raw or raw.startswith(("/", "\\")) or raw.startswith("//"):
        raise ValueError("tree path must be repository-relative")
    path = PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("tree path cannot contain traversal segments")
    return str(path)


def _tree_node(path: Path, root: Path, *, depth: int, max_depth: int, max_entries: int, counter: dict[str, Any]) -> dict[str, Any]:
    relative = "" if path == root else path.relative_to(root).as_posix()
    node = {
        "name": path.name or root.name,
        "path": relative,
        "kind": "directory" if path.is_dir() else "file",
        "depth": depth,
        "children": [],
        "truncated": False,
    }
    if not path.is_dir() or depth >= max_depth:
        return node
    children = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    for child in children:
        if counter["count"] >= max_entries:
            node["truncated"] = True
            counter["truncated"] = True
            break
        counter["count"] += 1
        node["children"].append(_tree_node(child, root, depth=depth + 1, max_depth=max_depth, max_entries=max_entries, counter=counter))
    return node


def _repository_roles(manifest: ProjectLibraryManifest, repository_id: str) -> list[str]:
    roles: list[str] = []
    binding = manifest.repository(repository_id)
    if binding is not None:
        roles.append(binding.role)
        roles.append(binding.lifecycle)
        if binding.readable:
            roles.append("read")
        if binding.writable:
            roles.append("write")
    return list(dict.fromkeys(item for item in roles if item))


def _safe_root_fragment(value: str) -> Path:
    normalized = str(value or "").replace("\\", "/").strip().strip("/")
    if not normalized:
        raise ValueError("project repository root fragment is required")
    path = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("project repository root fragment cannot contain traversal segments")
    return Path(*path.parts)


def _project_environment_storage_namespace(environment_id: str) -> Path:
    normalized = str(environment_id or "").strip()
    if normalized.startswith("env."):
        normalized = normalized.removeprefix("env.")
    normalized = normalized.replace("\\", "/").replace(".", "/").strip("/")
    path = PurePosixPath(normalized)
    if not normalized or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("project environment storage namespace is invalid")
    return Path(*path.parts)
