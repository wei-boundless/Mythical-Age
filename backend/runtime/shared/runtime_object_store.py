from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any


_OBJECT_STORE_LOCK = threading.RLock()


class RuntimeObjectStore:
    """Durable store for runtime objects that are too heavy for state_index."""

    authority = "orchestration.runtime_object_store"

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.object_dir = self.root_dir / "runtime_objects"
        self.object_dir.mkdir(parents=True, exist_ok=True)

    def put_object(self, kind: str, object_id: str, payload: dict[str, Any]) -> str:
        clean_kind = _safe_segment(kind)
        clean_id = _safe_segment(object_id)
        if not clean_kind or not clean_id:
            raise ValueError("runtime object requires kind and object_id")
        ref = f"rtobj:{clean_kind}:{clean_id}"
        body = {
            "ref": ref,
            "kind": clean_kind,
            "object_id": str(object_id or ""),
            "payload": dict(payload or {}),
            "updated_at": time.time(),
            "authority": self.authority,
        }
        self._atomic_write(self._path(clean_kind, clean_id), body)
        return ref

    def put_json_once(self, kind: str, object_id: str, payload: dict[str, Any]) -> str:
        clean_kind = _safe_segment(kind)
        clean_id = _safe_segment(object_id)
        if not clean_kind or not clean_id:
            raise ValueError("runtime object requires kind and object_id")
        path = self._path(clean_kind, clean_id)
        ref = f"rtobj:{clean_kind}:{clean_id}"
        if path.exists():
            return ref
        return self.put_object(kind=clean_kind, object_id=object_id, payload=payload)

    def get_object(self, ref: str) -> dict[str, Any]:
        clean_kind, clean_id = self._parse_ref(ref)
        path = self._path(clean_kind, clean_id)
        if not path.exists():
            return {}
        body = json.loads(path.read_text(encoding="utf-8"))
        return dict(body.get("payload") or {})

    def delete_ref(self, ref: str) -> bool:
        clean_kind, clean_id = self._parse_ref(ref)
        path = self._path(clean_kind, clean_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def delete_graph_run_objects(self, *, graph_run_id: str, task_run_ids: set[str] | None = None) -> dict[str, Any]:
        graph_id = str(graph_run_id or "").strip()
        task_ids = {str(item).strip() for item in set(task_run_ids or set()) if str(item).strip()}
        if not graph_id and not task_ids:
            return {"authority": self.authority, "deleted_counts": {}}
        counts: dict[str, int] = {}
        with _OBJECT_STORE_LOCK:
            for path in self.object_dir.glob("*/*.json"):
                try:
                    body = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                payload = dict(body.get("payload") or {}) if isinstance(body, dict) else {}
                if not _runtime_object_matches(payload, graph_run_id=graph_id, task_run_ids=task_ids):
                    continue
                try:
                    path.unlink()
                except OSError:
                    continue
                counts[str(body.get("kind") or path.parent.name)] = counts.get(str(body.get("kind") or path.parent.name), 0) + 1
            for kind_dir in self.object_dir.iterdir():
                if kind_dir.is_dir() and not any(kind_dir.iterdir()):
                    shutil.rmtree(kind_dir, ignore_errors=True)
        return {
            "authority": self.authority,
            "graph_run_id": graph_id,
            "task_run_ids": sorted(task_ids),
            "deleted_counts": counts,
        }

    def _path(self, kind: str, object_id: str) -> Path:
        return self.object_dir / kind / f"{object_id}.json"

    @staticmethod
    def _parse_ref(ref: str) -> tuple[str, str]:
        parts = str(ref or "").split(":", 2)
        if len(parts) != 3 or parts[0] != "rtobj":
            raise ValueError(f"invalid runtime object ref: {ref}")
        kind = _safe_segment(parts[1])
        object_id = _safe_segment(parts[2])
        if not kind or not object_id:
            raise ValueError(f"invalid runtime object ref: {ref}")
        return kind, object_id

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        with _OBJECT_STORE_LOCK:
            tmp.write_text(text, encoding="utf-8")
            last_error: OSError | None = None
            for attempt in range(8):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.05 * (attempt + 1))
            try:
                path.write_text(text, encoding="utf-8")
                tmp.unlink(missing_ok=True)
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                if last_error is not None:
                    raise last_error from exc
                raise


def _safe_segment(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:180]


def _runtime_object_matches(payload: dict[str, Any], *, graph_run_id: str, task_run_ids: set[str]) -> bool:
    if graph_run_id and str(payload.get("graph_run_id") or "") == graph_run_id:
        return True
    if str(payload.get("task_run_id") or "") in task_run_ids:
        return True
    diagnostics = dict(payload.get("diagnostics") or {})
    if graph_run_id and str(diagnostics.get("graph_run_id") or "") == graph_run_id:
        return True
    if str(diagnostics.get("task_run_id") or "") in task_run_ids:
        return True
    outputs = dict(payload.get("outputs") or {})
    if str(outputs.get("node_executor_task_run_id") or "") in task_run_ids:
        return True
    return False


