from __future__ import annotations

import json
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


RUNTIME_CACHE_DIR_NAME = "runtime_cache"
SANDBOX_CACHE_NAMESPACE = "sandboxes"
DEFAULT_SANDBOX_CACHE_TTL_SECONDS = 3 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class RuntimeCacheManifest:
    cache_key: str
    owner: str
    source_refs: tuple[str, ...] = ()
    schema_version: str = "runtime_cache_manifest.v1"
    created_at: float = 0.0
    last_accessed_at: float = 0.0
    ttl_seconds: int = 0
    size_bytes: int = 0
    rebuildable: bool = True
    authority: str = "runtime.cache_manager"

    def to_dict(self) -> dict[str, Any]:
        created_at = float(self.created_at or time.time())
        last_accessed_at = float(self.last_accessed_at or created_at)
        return {
            "cache_key": self.cache_key,
            "owner": self.owner,
            "source_refs": list(self.source_refs),
            "schema_version": self.schema_version,
            "created_at": created_at,
            "last_accessed_at": last_accessed_at,
            "ttl_seconds": int(self.ttl_seconds or 0),
            "size_bytes": int(self.size_bytes or 0),
            "rebuildable": bool(self.rebuildable),
            "authority": self.authority,
        }


class RuntimeCacheManager:
    """Owns rebuildable runtime cache roots.

    This manager deliberately does not decide task or graph facts. It can create,
    describe, and delete cache entries only inside the runtime cache root.
    """

    def __init__(self, cache_root: str | Path) -> None:
        self.cache_root = Path(cache_root).resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_runtime_root(cls, runtime_root: str | Path) -> "RuntimeCacheManager":
        return cls(runtime_cache_root_from_runtime_root(runtime_root))

    def namespace_root(self, namespace: str) -> Path:
        root = (self.cache_root / safe_cache_namespace(namespace)).resolve()
        _assert_inside(root, self.cache_root)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def sandbox_root(
        self,
        cache_key: str,
        *,
        owner: str = "runtime_sandbox",
        source_refs: tuple[str, ...] | list[str] = (),
        ttl_seconds: int = DEFAULT_SANDBOX_CACHE_TTL_SECONDS,
    ) -> Path:
        root = (self.namespace_root(SANDBOX_CACHE_NAMESPACE) / safe_cache_namespace(cache_key)).resolve()
        _assert_inside(root, self.cache_root)
        root.mkdir(parents=True, exist_ok=True)
        self.write_manifest(
            root,
            cache_key=cache_key,
            owner=owner,
            source_refs=source_refs,
            ttl_seconds=ttl_seconds,
            measure_size=False,
        )
        return root

    def delete_cache_entry(
        self,
        *,
        namespace: str,
        cache_key: str,
        reason: str = "",
        dry_run: bool = False,
        measure_size: bool = True,
        defer_delete: bool = False,
    ) -> dict[str, Any]:
        clean_namespace = safe_cache_namespace(namespace)
        clean_key = safe_cache_namespace(cache_key)
        path = (self.namespace_root(clean_namespace) / clean_key).resolve()
        _assert_inside(path, self.cache_root)
        exists = path.exists()
        size_measured = bool(measure_size)
        size_bytes = _tree_size(path) if exists and size_measured else 0
        detached_path = ""
        if exists and not dry_run:
            if defer_delete:
                detached_path = _detach_tree_for_deferred_delete(path, trash_root=self.cache_root / ".trash")
            else:
                shutil.rmtree(path)
        return {
            "authority": "runtime.cache_manager.delete_cache_entry",
            "mode": "dry_run" if dry_run else "execute",
            "namespace": clean_namespace,
            "cache_key": clean_key,
            "path": str(path),
            "existed": exists,
            "deleted": bool(exists and not dry_run and not defer_delete),
            "detached": bool(detached_path),
            "pending_delete_path": detached_path,
            "size_measured": size_measured,
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / 1024 / 1024, 2),
            "reason": str(reason or "runtime_cache_entry_deleted"),
            "updated_at": time.time(),
        }

    def write_manifest(
        self,
        cache_path: str | Path,
        *,
        cache_key: str,
        owner: str,
        source_refs: tuple[str, ...] | list[str] = (),
        ttl_seconds: int = 0,
        measure_size: bool = True,
    ) -> Path:
        path = Path(cache_path).resolve()
        _assert_inside(path, self.cache_root)
        path.mkdir(parents=True, exist_ok=True)
        existing = _read_manifest(path)
        now = time.time()
        manifest = RuntimeCacheManifest(
            cache_key=str(cache_key or ""),
            owner=str(owner or ""),
            source_refs=tuple(str(item) for item in tuple(source_refs or ()) if str(item).strip()),
            ttl_seconds=int(ttl_seconds or 0),
            created_at=float(existing.get("created_at") or now),
            last_accessed_at=now,
            size_bytes=_tree_size(path) if measure_size else int(existing.get("size_bytes") or 0),
        )
        manifest_path = path / ".runtime_cache_manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest_path

    def cleanup(
        self,
        *,
        namespace: str = "",
        now: float | None = None,
        default_ttl_seconds: int = 0,
        protected_paths: tuple[str | Path, ...] | list[str | Path] = (),
        dry_run: bool = True,
    ) -> dict[str, Any]:
        scan_root = self.namespace_root(namespace) if namespace else self.cache_root
        current_time = time.time() if now is None else float(now)
        protected = {_normalized_path(Path(item).resolve()) for item in tuple(protected_paths or ())}
        actions: list[dict[str, Any]] = []
        for child in sorted((item for item in scan_root.iterdir() if item.is_dir()), key=lambda item: item.stat().st_mtime):
            resolved = child.resolve()
            _assert_inside(resolved, self.cache_root)
            if _normalized_path(resolved) in protected:
                continue
            manifest = _read_manifest(resolved)
            ttl = int(manifest.get("ttl_seconds") or default_ttl_seconds or 0)
            if ttl <= 0:
                continue
            last_accessed_at = float(manifest.get("last_accessed_at") or manifest.get("created_at") or resolved.stat().st_mtime)
            if current_time - last_accessed_at < ttl:
                continue
            size_bytes = _tree_size(resolved)
            action = {
                "action": "delete_tree",
                "path": str(resolved),
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / 1024 / 1024, 2),
                "reason": "runtime_cache_ttl_expired",
            }
            actions.append(action)
            if not dry_run:
                shutil.rmtree(resolved)
        return {
            "authority": "runtime.cache_manager.cleanup",
            "mode": "dry_run" if dry_run else "execute",
            "cache_root": str(self.cache_root),
            "namespace": str(namespace or ""),
            "action_count": len(actions),
            "size_bytes": sum(int(item.get("size_bytes") or 0) for item in actions),
            "actions": actions,
            "updated_at": current_time,
        }


def runtime_cache_root_from_runtime_root(runtime_root: str | Path) -> Path:
    root = Path(runtime_root).resolve()
    if root.name == "runtime_state" and root.parent.name == "storage":
        return ProjectLayout.from_runtime_root(root).runtime_cache_dir
    return root / RUNTIME_CACHE_DIR_NAME


def runtime_cache_manager_for_host(runtime_host: Any) -> RuntimeCacheManager:
    existing = getattr(runtime_host, "runtime_cache", None)
    if isinstance(existing, RuntimeCacheManager):
        return existing
    return RuntimeCacheManager.from_runtime_root(Path(getattr(runtime_host, "root_dir", ".")))


def safe_cache_namespace(value: Any) -> str:
    text = str(value or "").strip()
    result = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text)
    result = result.strip("._-")
    return result or "cache"


def _read_manifest(cache_path: Path) -> dict[str, Any]:
    manifest_path = cache_path / ".runtime_cache_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _tree_size(path: Path) -> int:
    total = 0
    if path.is_file():
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        try:
            total += int(item.stat().st_size)
        except OSError:
            continue
    return total


def _detach_tree_for_deferred_delete(path: Path, *, trash_root: Path) -> str:
    trash_root.mkdir(parents=True, exist_ok=True)
    target = (trash_root / f"{path.name}-{int(time.time() * 1000)}").resolve()
    counter = 0
    while target.exists():
        counter += 1
        target = (trash_root / f"{path.name}-{int(time.time() * 1000)}-{counter}").resolve()
    path.replace(target)
    thread = threading.Thread(
        target=_delete_tree_quietly,
        args=(target,),
        name=f"runtime-cache-delete:{path.name}",
        daemon=True,
    )
    thread.start()
    return str(target)


def _delete_tree_quietly(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return
    except OSError:
        return


def _assert_inside(path: Path, root: Path) -> None:
    resolved_path = Path(path).resolve()
    resolved_root = Path(root).resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError(f"runtime cache path escapes cache root: {resolved_path}")


def _normalized_path(path: Path) -> str:
    return Path(path).resolve().as_posix().lower()
