from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from core.project_layout import ProjectLayout


class ProjectWorkspaceMissing(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectWorkspace:
    key: str
    workspace_root: str
    name: str
    source: str
    created_at: float
    last_seen_at: float
    session_count: int = 0
    latest_session_at: float = 0.0
    available: bool = True
    authority: str = "project_workspaces.workspace"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "workspace_root": self.workspace_root,
            "name": self.name,
            "source": self.source,
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
            "session_count": self.session_count,
            "latest_session_at": self.latest_session_at,
            "available": self.available,
            "authority": self.authority,
        }


class ProjectWorkspaceService:
    def __init__(self, base_dir: str | Path, session_manager: Any) -> None:
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.storage_path = layout.storage_root / "project_workspaces.json"
        self.session_manager = session_manager

    def list_workspaces(self) -> list[dict[str, Any]]:
        stored = {item.key: item for item in self._load_stored()}
        derived: dict[str, ProjectWorkspace] = {}
        sessions_by_key: dict[str, list[dict[str, Any]]] = {}
        for session in self._main_chat_sessions():
            root = _session_workspace_root(session)
            if not root:
                continue
            workspace = _workspace_from_root(root, source="session.project_binding")
            derived[workspace.key] = workspace
            sessions_by_key.setdefault(workspace.key, []).append(session)

        merged: dict[str, ProjectWorkspace] = {}
        for key in sorted(set(stored) | set(derived)):
            base = stored.get(key) or derived[key]
            session_rows = sessions_by_key.get(key, [])
            latest_session_at = max([float(item.get("updated_at") or 0) for item in session_rows] or [0.0])
            last_seen_at = max(base.last_seen_at, latest_session_at)
            derived_root = derived.get(key)
            root = derived_root.workspace_root if derived_root else base.workspace_root
            merged[key] = ProjectWorkspace(
                key=key,
                workspace_root=root,
                name=Path(root).name or root,
                source=base.source,
                created_at=base.created_at,
                last_seen_at=last_seen_at,
                session_count=len(session_rows),
                latest_session_at=latest_session_at,
                available=Path(root).expanduser().is_dir(),
            )

        return [
            item.to_dict()
            for item in sorted(
                merged.values(),
                key=lambda workspace: (workspace.last_seen_at, workspace.latest_session_at, workspace.name.lower()),
                reverse=True,
            )
        ]

    def register_workspace(self, workspace_root: str, *, source: str = "manual") -> dict[str, Any]:
        workspace = _workspace_from_root(workspace_root, source=source, validate_root=True)
        stored = {item.key: item for item in self._load_stored()}
        current = stored.get(workspace.key)
        if current:
            workspace = ProjectWorkspace(
                key=current.key,
                workspace_root=current.workspace_root,
                name=current.name,
                source=current.source or workspace.source,
                created_at=current.created_at,
                last_seen_at=time.time(),
                available=Path(current.workspace_root).expanduser().is_dir(),
            )
        stored[workspace.key] = workspace
        self._write_stored(stored.values())
        return workspace.to_dict()

    def workspace_for_key(self, key: str) -> dict[str, Any]:
        target = str(key or "").strip()
        for workspace in self.list_workspaces():
            if workspace.get("key") == target:
                return workspace
        raise ProjectWorkspaceMissing("project workspace not found")

    def sessions_for_workspace(self, key: str) -> list[dict[str, Any]]:
        workspace = self.workspace_for_key(key)
        root = str(workspace.get("workspace_root") or "")
        return [
            session
            for session in self._main_chat_sessions()
            if _same_workspace_root(_session_workspace_root(session), root)
        ]

    def project_binding_for_key(self, key: str, *, source: str = "project_workspace") -> dict[str, str]:
        workspace = self.workspace_for_key(key)
        root = str(workspace.get("workspace_root") or "").strip()
        if not root:
            raise ProjectWorkspaceMissing("project workspace not found")
        if not Path(root).expanduser().is_dir():
            raise FileNotFoundError("project workspace root not found")
        return {
            "workspace_root": root,
            "source": source,
        }

    def remove_workspace(self, key: str, *, detach_sessions: bool = True) -> dict[str, Any]:
        workspace = self.workspace_for_key(key)
        workspace_key = str(workspace.get("key") or "").strip()
        workspace_root = str(workspace.get("workspace_root") or "").strip()
        if not workspace_key or not workspace_root:
            raise ProjectWorkspaceMissing("project workspace not found")

        stored = {item.key: item for item in self._load_stored()}
        removed_registry_entry = stored.pop(workspace_key, None) is not None
        detached_sessions: list[dict[str, Any]] = []
        if detach_sessions:
            for session in self.sessions_for_workspace(workspace_key):
                detached_sessions.append(
                    self.session_manager.clear_project_binding(
                        str(session.get("id") or ""),
                        workspace_root=workspace_root,
                    )
                )
        if removed_registry_entry:
            self._write_stored(stored.values())
        return {
            "project": workspace,
            "removed_registry_entry": removed_registry_entry,
            "detached_sessions": detached_sessions,
            "detached_session_count": len(detached_sessions),
        }

    def _main_chat_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for session in list(self.session_manager.list_sessions() or []):
            scope = dict(session.get("scope") or {})
            if str(scope.get("workspace_view") or "chat").strip() == "task_environment":
                continue
            task_binding = dict(session.get("task_binding") or {})
            if str(task_binding.get("kind") or "").strip() == "task_graph":
                continue
            sessions.append(session)
        return sessions

    def _load_stored(self) -> list[ProjectWorkspace]:
        path = self.storage_path
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = payload.get("workspaces") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return []
        return [
            item
            for item in (_workspace_from_payload(row) for row in rows if isinstance(row, dict))
            if item is not None
        ]

    def _write_stored(self, workspaces: Any) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "authority": "project_workspaces.registry",
            "workspaces": [item.to_dict() for item in sorted(workspaces, key=lambda workspace: workspace.last_seen_at, reverse=True)],
        }
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.storage_path.parent,
                prefix=f".{self.storage_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp_path = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.storage_path)
        except OSError:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise


def project_workspace_key(workspace_root: str) -> str:
    root = str(Path(workspace_root).expanduser().resolve())
    digest = hashlib.sha1(os.path.normcase(root).encode("utf-8")).hexdigest()[:16]
    return f"workspace-{digest}"


def _workspace_from_root(workspace_root: str, *, source: str, validate_root: bool = False) -> ProjectWorkspace:
    root_path = Path(str(workspace_root or "").strip()).expanduser().resolve()
    if validate_root and (not root_path.exists() or not root_path.is_dir()):
        raise ValueError("project workspace root must be an existing directory")
    now = time.time()
    root = str(root_path)
    return ProjectWorkspace(
        key=project_workspace_key(root),
        workspace_root=root,
        name=root_path.name or root,
        source=str(source or "manual").strip() or "manual",
        created_at=now,
        last_seen_at=now,
        available=root_path.is_dir(),
    )


def _workspace_from_payload(payload: dict[str, Any]) -> ProjectWorkspace | None:
    root = str(payload.get("workspace_root") or "").strip()
    if not root:
        return None
    try:
        root = str(Path(root).expanduser().resolve())
    except Exception:
        return None
    key = str(payload.get("key") or project_workspace_key(root)).strip()
    if not key:
        return None
    return ProjectWorkspace(
        key=key,
        workspace_root=root,
        name=str(payload.get("name") or Path(root).name or root).strip() or root,
        source=str(payload.get("source") or "manual").strip() or "manual",
        created_at=float(payload.get("created_at") or time.time()),
        last_seen_at=float(payload.get("last_seen_at") or payload.get("updated_at") or time.time()),
        available=Path(root).expanduser().is_dir(),
    )


def _session_workspace_root(session: dict[str, Any]) -> str:
    state = dict(session.get("conversation_state") or {})
    binding = dict(state.get("project_binding") or {})
    return str(binding.get("workspace_root") or "").strip()


def _same_workspace_root(left: str, right: str) -> bool:
    if not left or not right:
        return False
    try:
        left_key = os.path.normcase(str(Path(left).expanduser().resolve()))
        right_key = os.path.normcase(str(Path(right).expanduser().resolve()))
    except Exception:
        left_key = os.path.normcase(str(left or ""))
        right_key = os.path.normcase(str(right or ""))
    return left_key == right_key

