from __future__ import annotations

from collections import deque
from pathlib import Path
import subprocess

from code_environment.models import CodeEnvironmentTreeNode, CodeEnvironmentWorkspaceTreeResponse


EXCLUDED_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".next",
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "checkpoints",
    "coordination_checkpoints",
    "coverage",
    "dist",
    "events",
    "executions",
    "node_modules",
    "output",
    "runtime_objects",
    "runtime_views",
    "state_index",
    "venv",
    "working_memory",
}

EXCLUDED_RELATIVE_PATHS = {
    "storage/document_cache",
    "storage/embedding_cache",
    "storage/health_system",
    "storage/indexes",
    "storage/modality_artifacts",
    "storage/runtime_state",
    "storage/session_memory",
    "storage/sessions",
    "storage/task_durable_memory",
    "storage/working_memory",
}


class _TreeBudget:
    def __init__(self, max_entries: int) -> None:
        self.max_entries = max_entries
        self.total_entries = 0
        self.truncated = False

    def consume(self) -> bool:
        if self.total_entries >= self.max_entries:
            self.truncated = True
            return False
        self.total_entries += 1
        return True


def build_workspace_tree(
    root: Path,
    *,
    max_depth: int = 10,
    max_entries: int = 10_000,
) -> CodeEnvironmentWorkspaceTreeResponse:
    resolved_root = root.resolve()
    depth_limit = max(1, min(max_depth, 12))
    entry_limit = max(1, min(max_entries, 50_000))
    tree = CodeEnvironmentTreeNode(
        name=resolved_root.name,
        path="",
        kind="directory",
        depth=0,
    )
    git_paths = _git_visible_file_paths(resolved_root)
    if git_paths is not None:
        budget = _populate_tree_from_relative_files(
            tree,
            git_paths,
            root=resolved_root,
            max_depth=depth_limit,
            max_entries=entry_limit,
        )
    else:
        budget = _populate_tree_breadth_first(
            tree,
            resolved_root,
            root=resolved_root,
            max_depth=depth_limit,
            max_entries=entry_limit,
        )
    return CodeEnvironmentWorkspaceTreeResponse(
        root_name=resolved_root.name,
        root_path=str(resolved_root),
        max_depth=depth_limit,
        max_entries=entry_limit,
        total_entries=budget.total_entries,
        truncated=budget.truncated or tree.truncated,
        tree=tree,
    )


def _populate_tree_from_relative_files(
    tree: CodeEnvironmentTreeNode,
    relative_files: list[str],
    *,
    root: Path,
    max_depth: int,
    max_entries: int,
) -> _TreeBudget:
    budget = _TreeBudget(max_entries)
    directory_index: dict[str, CodeEnvironmentTreeNode] = {"": tree}
    for relative_file in _sort_relative_paths(relative_files):
        if _is_excluded_relative_path(relative_file):
            continue
        parts = [part for part in relative_file.replace("\\", "/").split("/") if part]
        if not parts:
            continue

        parent = tree
        current_parts: list[str] = []
        should_stop = False
        visible_parts = parts[:max_depth]
        file_fits = len(parts) <= max_depth
        for depth, part in enumerate(visible_parts, start=1):
            current_parts.append(part)
            current_path = "/".join(current_parts)
            terminal_visible_part = depth == len(visible_parts)
            existing = directory_index.get(current_path)
            if existing is not None:
                if terminal_visible_part and not file_fits:
                    existing.truncated = True
                parent = existing
                continue
            if not budget.consume():
                parent.truncated = True
                should_stop = True
                break
            is_file = terminal_visible_part and file_fits
            node = CodeEnvironmentTreeNode(
                name=part,
                path=current_path,
                kind="file" if is_file else "directory",
                depth=depth,
                truncated=terminal_visible_part and not file_fits,
            )
            parent.children.append(node)
            if not is_file:
                directory_index[current_path] = node
                parent = node
        if should_stop:
            break
    _sort_tree_children(tree)
    return budget


def _populate_tree_breadth_first(
    tree: CodeEnvironmentTreeNode,
    root_path: Path,
    *,
    root: Path,
    max_depth: int,
    max_entries: int,
) -> _TreeBudget:
    budget = _TreeBudget(max_entries)
    queue: deque[tuple[Path, CodeEnvironmentTreeNode]] = deque([(root_path, tree)])
    while queue:
        directory_path, directory_node = queue.popleft()
        if directory_node.depth >= max_depth:
            directory_node.truncated = True
            continue
        for child in _iter_visible_children(directory_path, root=root):
            if not budget.consume():
                directory_node.truncated = True
                break
            child_is_directory = child.is_dir()
            child_node = CodeEnvironmentTreeNode(
                name=child.name,
                path=_relative_path(child, root),
                kind="directory" if child_is_directory else "file",
                depth=directory_node.depth + 1,
                truncated=child_is_directory and directory_node.depth + 1 >= max_depth,
            )
            directory_node.children.append(child_node)
            if child_is_directory and child_node.depth < max_depth:
                queue.append((child, child_node))
        _sort_tree_children(directory_node)
    return budget


def _git_visible_file_paths(root: Path) -> list[str] | None:
    git_root = _git_root(root)
    if git_root != root.resolve():
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
            capture_output=True,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    paths = [
        item.decode("utf-8", errors="replace").replace("\\", "/").strip("/")
        for item in completed.stdout.split(b"\x00")
        if item
    ]
    return [
        path
        for path in paths
        if path
        and not _is_excluded_relative_path(path)
        and (root / path).exists()
    ]


def _git_root(root: Path) -> Path | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    if not value:
        return None
    try:
        return Path(value).resolve()
    except OSError:
        return None


def _sort_tree_children(node: CodeEnvironmentTreeNode) -> None:
    node.children.sort(key=lambda child: (child.kind != "directory", child.name.startswith("."), child.name.lower()))
    for child in node.children:
        if child.children:
            _sort_tree_children(child)


def _sort_relative_paths(paths: list[str]) -> list[str]:
    return sorted(
        paths,
        key=lambda path: tuple((part.startswith("."), part.lower()) for part in path.split("/")),
    )


def _iter_visible_children(path: Path, *, root: Path) -> list[Path]:
    try:
        children = [
            child
            for child in path.iterdir()
            if not _is_excluded(child, root=root)
        ]
    except OSError:
        return []
    return sorted(children, key=lambda item: (not item.is_dir(), item.name.lower()))


def _is_excluded(path: Path, *, root: Path) -> bool:
    if path.is_symlink():
        return True
    if path.name in EXCLUDED_NAMES:
        return True
    relative = _relative_path(path, root)
    return _is_excluded_relative_path(relative)


def _is_excluded_relative_path(relative: str) -> bool:
    normalized = relative.replace("\\", "/").strip("/")
    if not normalized:
        return False
    if any(part in EXCLUDED_NAMES for part in normalized.split("/")):
        return True
    if normalized in EXCLUDED_RELATIVE_PATHS:
        return True
    return any(normalized.startswith(f"{excluded}/") for excluded in EXCLUDED_RELATIVE_PATHS)


def _relative_path(path: Path, root: Path) -> str:
    if path == root:
        return ""
    return path.relative_to(root).as_posix()


