from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from file_management.filesystem_adapter import FsspecLocalFileAdapter
from file_management.models import normalize_logical_path
from core.project_layout import ProjectLayout
from task_system.graph_instances.repository import GraphTaskInstanceRepository


DEFAULT_INSTANCE_DIRS = ("input", "working", "artifacts", "memory", "logs", "runs")


class GraphTaskInstanceFileService:
    authority = "task_system.graph_task_instance_file_service"

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.layout = ProjectLayout.from_backend_dir(self.base_dir)
        self.repository = GraphTaskInstanceRepository(self.base_dir)

    def ensure_space(self, instance_id: str) -> dict[str, Any]:
        instance = self.repository.require(instance_id)
        root = self.root(instance.graph_task_instance_id)
        for name in DEFAULT_INSTANCE_DIRS:
            (root / name).mkdir(parents=True, exist_ok=True)
        return {
            "authority": "task_system.graph_task_instance_file_space",
            "graph_task_instance_id": instance.graph_task_instance_id,
            "root": str(root),
            "directories": list(DEFAULT_INSTANCE_DIRS),
        }

    def root(self, instance_id: str) -> Path:
        safe = _safe_path_component(instance_id)
        return (self.layout.storage_root / "graph_task_instances" / safe).resolve()

    def repositories(self, instance_id: str) -> dict[str, Any]:
        instance = self.repository.require(instance_id)
        self.ensure_space(instance.graph_task_instance_id)
        return {
            "authority": "task_system.graph_task_instance_repositories",
            "graph_task_instance_id": instance.graph_task_instance_id,
            "repositories": [
                {
                    "repository_id": "instance",
                    "title": "项目文件",
                    "repository_kind": "local",
                    "root_ref": f"graph-task-instance://{instance.graph_task_instance_id}",
                    "readable": True,
                    "writable": True,
                    "searchable": True,
                    "selected_roles": ["project", "read", "write"],
                }
            ],
            "summary": {"repository_count": 1},
        }

    def tree(self, instance_id: str, path: str = "", *, max_depth: int = 4, max_entries: int = 500) -> dict[str, Any]:
        instance = self.repository.require(instance_id)
        root = self.root(instance.graph_task_instance_id)
        self.ensure_space(instance.graph_task_instance_id)
        root_path = _normalize_tree_path(path)
        adapter = FsspecLocalFileAdapter(root)
        start = root if not root_path else adapter.resolve(root_path)
        if not start.exists():
            raise FileNotFoundError(root_path or ".")
        if not start.is_dir():
            raise NotADirectoryError(root_path or ".")
        counter = {"count": 0, "truncated": False}
        tree = _tree_node(start, root, depth=0, max_depth=max(0, int(max_depth)), max_entries=max(1, int(max_entries)), counter=counter)
        return {
            "authority": "task_system.graph_task_instance_file_tree",
            "graph_task_instance_id": instance.graph_task_instance_id,
            "repository_id": "instance",
            "path": root_path,
            "total_entries": counter["count"],
            "truncated": counter["truncated"],
            "tree": tree,
        }

    def read_file(self, instance_id: str, path: str) -> dict[str, Any]:
        instance = self.repository.require(instance_id)
        adapter = FsspecLocalFileAdapter(self.root(instance.graph_task_instance_id))
        logical_path = normalize_logical_path(path)
        return {
            "authority": "task_system.graph_task_instance_file",
            "graph_task_instance_id": instance.graph_task_instance_id,
            "repository_id": "instance",
            "path": logical_path,
            "content": adapter.read_text(logical_path),
        }

    def write_file(self, instance_id: str, path: str, content: str) -> dict[str, Any]:
        instance = self.repository.require(instance_id)
        self.ensure_space(instance.graph_task_instance_id)
        adapter = FsspecLocalFileAdapter(self.root(instance.graph_task_instance_id))
        logical_path = adapter.write_text(normalize_logical_path(path), content)
        return {
            "authority": "task_system.graph_task_instance_file_write",
            "graph_task_instance_id": instance.graph_task_instance_id,
            "repository_id": "instance",
            "path": logical_path,
            "written": True,
        }

    def artifacts(self, instance_id: str) -> dict[str, Any]:
        instance = self.repository.require(instance_id)
        root = self.root(instance.graph_task_instance_id)
        self.ensure_space(instance.graph_task_instance_id)
        artifact_roots = [root / "artifacts", root / "runs"]
        artifacts: list[dict[str, Any]] = []
        for artifact_root in artifact_roots:
            if not artifact_root.exists():
                continue
            for path in sorted(artifact_root.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                artifacts.append(
                    {
                        "artifact_id": f"artifact.{_safe_path_component(instance.graph_task_instance_id)}.{_safe_path_component(relative)}",
                        "graph_task_instance_id": instance.graph_task_instance_id,
                        "path": relative,
                        "name": path.name,
                        "size": path.stat().st_size,
                        "updated_at": path.stat().st_mtime,
                        "status": "available",
                        "authority": "task_system.graph_task_instance_artifact",
                    }
                )
        return {
            "authority": "task_system.graph_task_instance_artifacts",
            "graph_task_instance_id": instance.graph_task_instance_id,
            "artifacts": artifacts,
            "summary": {"artifact_count": len(artifacts)},
        }


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


def _safe_path_component(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "").strip())
    safe = safe.strip("_-")
    return safe or "graph_task_instance"

