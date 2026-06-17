from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from runtime.storage_policy import DEFAULT_RUNTIME_STORAGE_POLICY, RuntimeStoragePolicy


TERMINAL_TASK_STATUSES = {"completed", "failed", "aborted"}


@dataclass(frozen=True, slots=True)
class RuntimeArchiveAction:
    action: str
    source: str
    target: str
    size_bytes: int
    reason: str
    run_id: str = ""
    storage_class: str = "runtime_fact"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.retention_archiver"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["size_mb"] = round(self.size_bytes / 1024 / 1024, 2)
        return payload


class RuntimeFactArchiver:
    """Moves old runtime facts out of the hot path into L2 cold archive."""

    authority = "runtime.retention_archiver"

    def __init__(
        self,
        project_root: str | Path,
        *,
        storage_policy: RuntimeStoragePolicy = DEFAULT_RUNTIME_STORAGE_POLICY,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.storage_policy = storage_policy
        self.runtime_root = self.project_root / "storage" / "runtime_state"
        self.archive_root = self.runtime_root / "cold_archive"

    def plan(self, *, now: float | None = None) -> dict[str, Any]:
        timestamp = time.time() if now is None else float(now)
        protection = self._runtime_protection()
        actions = [
            *self._event_log_actions(now=timestamp, protection=protection),
            *self._event_payload_actions(now=timestamp, protection=protection),
            *self._runtime_object_actions(now=timestamp, protection=protection),
            *self._checkpoint_history_actions(now=timestamp, protection=protection),
        ]
        return self._result(actions, mode="dry_run", now=timestamp, protection=protection)

    def execute(self, *, now: float | None = None) -> dict[str, Any]:
        timestamp = time.time() if now is None else float(now)
        protection = self._runtime_protection()
        planned = [
            *self._event_log_actions(now=timestamp, protection=protection),
            *self._event_payload_actions(now=timestamp, protection=protection),
            *self._runtime_object_actions(now=timestamp, protection=protection),
            *self._checkpoint_history_actions(now=timestamp, protection=protection),
        ]
        executed: list[RuntimeArchiveAction] = []
        for action in planned:
            if action.action == "archive_file":
                if self._archive_file(action):
                    executed.append(action)
            elif action.action == "archive_runtime_object":
                if self._archive_file(action, prune_empty_parents=True):
                    executed.append(action)
            elif action.action == "compact_checkpoint_history":
                compacted = self._compact_checkpoint_history(action)
                if compacted is not None:
                    executed.append(compacted)
        result = self._result(executed, mode="execute", now=timestamp, protection=protection)
        if executed:
            receipt_path = self._receipt_path(timestamp)
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(receipt_path, result)
            result["receipt_path"] = _relative(self.project_root, receipt_path)
        return result

    def _event_log_actions(self, *, now: float, protection: dict[str, set[str]]) -> list[RuntimeArchiveAction]:
        event_dir = self.runtime_root / "events"
        if not event_dir.exists():
            return []
        cutoff = now - self.storage_policy.terminal_hot_seconds
        actions: list[RuntimeArchiveAction] = []
        for path in sorted(event_dir.glob("*.jsonl")):
            run_id = path.stem
            if _safe_id(run_id) in protection["safe_run_ids"] or run_id in protection["safe_run_ids"]:
                continue
            if _mtime(path) >= cutoff:
                continue
            actions.append(
                self._archive_action(
                    path,
                    category="events",
                    reason="archive_terminal_event_log_after_hot_retention",
                    run_id=run_id,
                    storage_class="runtime_event_log",
                )
            )
        return actions

    def _event_payload_actions(self, *, now: float, protection: dict[str, set[str]]) -> list[RuntimeArchiveAction]:
        payload_dir = self.runtime_root / "event_payloads"
        if not payload_dir.exists():
            return []
        cutoff = now - self.storage_policy.temporary_output_ttl_seconds
        actions: list[RuntimeArchiveAction] = []
        for path in _event_payload_paths(payload_dir):
            run_id, safe_run_id = _payload_run_identity(path)
            if _identity_protected(run_id, safe_run_id, protection=protection):
                continue
            if _mtime(path) >= cutoff:
                continue
            actions.append(
                self._archive_action(
                    path,
                    category="event_payloads",
                    reason="archive_externalized_event_payload_after_hot_retention",
                    run_id=run_id or safe_run_id,
                    storage_class="runtime_event_payload",
                )
            )
        return actions

    def _runtime_object_actions(self, *, now: float, protection: dict[str, set[str]]) -> list[RuntimeArchiveAction]:
        object_dir = self.runtime_root / "runtime_objects"
        if not object_dir.exists():
            return []
        cutoff = now - self.storage_policy.terminal_hot_seconds
        actions: list[RuntimeArchiveAction] = []
        for path in sorted(object_dir.glob("*/*.json")):
            identities = _runtime_object_identities(path)
            if _object_identity_protected(identities, protection=protection):
                continue
            if _mtime(path) >= cutoff:
                continue
            actions.append(
                self._archive_action(
                    path,
                    category="runtime_objects",
                    reason="archive_runtime_object_after_hot_retention",
                    run_id=str(identities.get("task_run_id") or identities.get("graph_run_id") or ""),
                    storage_class="runtime_object",
                    action="archive_runtime_object",
                )
            )
        return actions

    def _checkpoint_history_actions(self, *, now: float, protection: dict[str, set[str]]) -> list[RuntimeArchiveAction]:
        db_path = self.runtime_root / "graph_checkpoints.sqlite"
        if not db_path.exists() or _mtime(db_path) >= now - self.storage_policy.terminal_hot_seconds:
            return []
        thread_ids = _checkpoint_threads_with_prunable_history(db_path, protected_graph_run_ids=protection["graph_run_ids"])
        if not thread_ids:
            return []
        target = self._archive_target(db_path, category="checkpoints")
        return [
            RuntimeArchiveAction(
                action="compact_checkpoint_history",
                source=_relative(self.project_root, db_path),
                target=_relative(self.project_root, target),
                size_bytes=_tree_size(db_path),
                reason="archive_checkpoint_sqlite_before_pruning_old_history",
                storage_class="runtime_checkpoint",
                metadata={
                    "thread_ids": thread_ids,
                    "latest_checkpoint_per_thread_retained": True,
                },
            )
        ]

    def _archive_action(
        self,
        path: Path,
        *,
        category: str,
        reason: str,
        run_id: str,
        storage_class: str,
        action: str = "archive_file",
    ) -> RuntimeArchiveAction:
        target = self._archive_target(path, category=category)
        return RuntimeArchiveAction(
            action=action,
            source=_relative(self.project_root, path),
            target=_relative(self.project_root, target),
            size_bytes=_tree_size(path),
            reason=reason,
            run_id=run_id,
            storage_class=storage_class,
        )

    def _archive_target(self, path: Path, *, category: str) -> Path:
        relative = _relative(self.runtime_root, path)
        return self.archive_root / category / time.strftime("%Y%m%d") / relative

    def _archive_file(self, action: RuntimeArchiveAction, *, prune_empty_parents: bool = False) -> bool:
        source = (self.project_root / action.source).resolve()
        target = (self.project_root / action.target).resolve()
        _assert_inside(source, self.project_root)
        _assert_inside(target, self.project_root)
        if not source.exists() or not source.is_file():
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = target.with_name(f"{target.stem}-{uuid.uuid4().hex[:8]}{target.suffix}")
        shutil.move(str(source), str(target))
        manifest = target.with_suffix(target.suffix + ".manifest.json")
        _atomic_write_json(
            manifest,
            {
                "authority": self.authority,
                "action": action.to_dict(),
                "archived_at": time.time(),
            },
        )
        if prune_empty_parents:
            _prune_empty_parents(source.parent, stop_at=self.runtime_root / "runtime_objects")
        return True

    def _compact_checkpoint_history(self, action: RuntimeArchiveAction) -> RuntimeArchiveAction | None:
        source = (self.project_root / action.source).resolve()
        target = (self.project_root / action.target).resolve()
        _assert_inside(source, self.project_root)
        _assert_inside(target, self.project_root)
        if not source.exists():
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        thread_ids = [str(item) for item in list(action.metadata.get("thread_ids") or []) if str(item)]
        deleted_counts = _prune_checkpoint_history(source, thread_ids=thread_ids)
        _atomic_write_json(
            target.with_suffix(target.suffix + ".manifest.json"),
            {
                "authority": self.authority,
                "source": action.source,
                "archive": action.target,
                "thread_ids": thread_ids,
                "deleted_counts": deleted_counts,
                "latest_checkpoint_per_thread_retained": True,
                "archived_at": time.time(),
            },
        )
        return RuntimeArchiveAction(
            action=action.action,
            source=action.source,
            target=action.target,
            size_bytes=action.size_bytes,
            reason=action.reason,
            storage_class=action.storage_class,
            metadata={**dict(action.metadata), "deleted_counts": deleted_counts},
        )

    def _runtime_protection(self) -> dict[str, set[str]]:
        task_run_ids: set[str] = set()
        session_ids: set[str] = set()
        graph_run_ids: set[str] = set()
        try:
            from runtime.memory.state_index import RuntimeStateIndex
        except Exception:
            return {"task_run_ids": set(), "session_ids": set(), "graph_run_ids": set(), "safe_run_ids": set()}
        try:
            task_runs = RuntimeStateIndex(self.runtime_root).list_recent_task_run_summaries(limit=2000)
        except Exception:
            task_runs = []
        for task_run in task_runs:
            status = str(getattr(task_run, "status", "") or "").strip()
            if status in TERMINAL_TASK_STATUSES:
                continue
            task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
            session_id = str(getattr(task_run, "session_id", "") or "").strip()
            diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
            graph_run_id = str(diagnostics.get("graph_run_id") or diagnostics.get("graph_run_ref") or "").strip()
            if task_run_id:
                task_run_ids.add(task_run_id)
            if session_id:
                session_ids.add(session_id)
            if graph_run_id:
                graph_run_ids.add(graph_run_id)
        safe_run_ids = {_safe_id(item) for item in task_run_ids | graph_run_ids if item}
        return {
            "task_run_ids": task_run_ids,
            "session_ids": session_ids,
            "graph_run_ids": graph_run_ids,
            "safe_run_ids": safe_run_ids,
        }

    def _result(
        self,
        actions: list[RuntimeArchiveAction],
        *,
        mode: str,
        now: float,
        protection: dict[str, set[str]],
    ) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "mode": mode,
            "storage_policy": self.storage_policy.to_dict(),
            "summary": {
                "action_count": len(actions),
                "size_bytes": sum(int(item.size_bytes or 0) for item in actions),
                "size_mb": round(sum(int(item.size_bytes or 0) for item in actions) / 1024 / 1024, 2),
                "active_task_run_protection_count": len(protection.get("task_run_ids") or set()),
                "active_graph_run_protection_count": len(protection.get("graph_run_ids") or set()),
            },
            "actions": [item.to_dict() for item in actions],
            "updated_at": now,
        }

    def _receipt_path(self, timestamp: float) -> Path:
        return (
            self.project_root
            / "storage"
            / "health_system"
            / "maintenance"
            / "runtime_retention_receipts"
            / f"runtime-retention-{int(timestamp * 1000)}.json"
        )


def _checkpoint_threads_with_prunable_history(db_path: Path, *, protected_graph_run_ids: set[str]) -> list[str]:
    try:
        with sqlite3.connect(str(db_path)) as conn:
            tables = _sqlite_tables(conn)
            if "checkpoints" not in tables:
                return []
            rows = conn.execute(
                "SELECT thread_id, COUNT(*) FROM checkpoints GROUP BY thread_id HAVING COUNT(*) > 1"
            ).fetchall()
    except Exception:
        return []
    protected = {str(item) for item in protected_graph_run_ids if str(item)}
    return sorted(str(row[0]) for row in rows if str(row[0]) not in protected)


def _prune_checkpoint_history(db_path: Path, *, thread_ids: list[str]) -> dict[str, int]:
    if not thread_ids:
        return {}
    counts: dict[str, int] = {}
    with sqlite3.connect(str(db_path)) as conn:
        tables = _sqlite_tables(conn)
        if "checkpoints" not in tables:
            return {}
        for thread_id in thread_ids:
            checkpoint_ids = [
                str(row[0])
                for row in conn.execute(
                    "SELECT checkpoint_id FROM checkpoints WHERE thread_id = ? ORDER BY checkpoint_id DESC",
                    (thread_id,),
                ).fetchall()
            ]
            old_ids = checkpoint_ids[1:]
            if not old_ids:
                continue
            placeholders = ",".join("?" for _ in old_ids)
            params = [thread_id, *old_ids]
            if "writes" in tables:
                before_writes = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM writes WHERE thread_id = ? AND checkpoint_id IN ({placeholders})",
                        tuple(params),
                    ).fetchone()[0]
                )
                conn.execute(
                    f"DELETE FROM writes WHERE thread_id = ? AND checkpoint_id IN ({placeholders})",
                    tuple(params),
                )
                counts["writes"] = counts.get("writes", 0) + before_writes
            before_checkpoints = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM checkpoints WHERE thread_id = ? AND checkpoint_id IN ({placeholders})",
                    tuple(params),
                ).fetchone()[0]
            )
            conn.execute(
                f"DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_id IN ({placeholders})",
                tuple(params),
            )
            counts["checkpoints"] = counts.get("checkpoints", 0) + before_checkpoints
        conn.commit()
        try:
            conn.execute("VACUUM")
        except Exception:
            pass
    return {key: value for key, value in counts.items() if value}


def _sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _payload_run_identity(path: Path) -> tuple[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    return str(payload.get("run_id") or payload.get("task_run_id") or ""), str(
        payload.get("safe_run_id") or payload.get("safe_task_run_id") or ""
    )


def _event_payload_paths(payload_dir: Path) -> list[Path]:
    paths = [
        path
        for path in payload_dir.glob("*/*.json")
        if path.is_file()
    ]
    paths.extend(
        path
        for path in payload_dir.glob("hot/by_day/*/*/*.json")
        if path.is_file()
    )
    paths.extend(
        path
        for path in payload_dir.glob("hot/by_time/*/*/*/*.json")
        if path.is_file()
    )
    return sorted(paths)


def _runtime_object_identities(path: Path) -> dict[str, str]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    payload = dict(body.get("payload") or {}) if isinstance(body, dict) else {}
    diagnostics = dict(payload.get("diagnostics") or {})
    outputs = dict(payload.get("outputs") or {})
    return {
        "task_run_id": _first_text(
            payload.get("task_run_id"),
            payload.get("bound_task_run_id"),
            payload.get("current_task_run_id"),
            payload.get("root_task_run_id"),
            diagnostics.get("task_run_id"),
            outputs.get("node_executor_task_run_id"),
        ),
        "graph_run_id": _first_text(payload.get("graph_run_id"), diagnostics.get("graph_run_id")),
        "session_id": _first_text(payload.get("session_id"), diagnostics.get("session_id")),
    }


def _identity_protected(run_id: str, safe_run_id: str, *, protection: dict[str, set[str]]) -> bool:
    return bool(
        (run_id and run_id in protection["task_run_ids"])
        or (run_id and run_id in protection["graph_run_ids"])
        or (safe_run_id and safe_run_id in protection["safe_run_ids"])
        or (run_id and _safe_id(run_id) in protection["safe_run_ids"])
    )


def _object_identity_protected(identities: dict[str, str], *, protection: dict[str, set[str]]) -> bool:
    return bool(
        str(identities.get("task_run_id") or "") in protection["task_run_ids"]
        or str(identities.get("graph_run_id") or "") in protection["graph_run_ids"]
        or str(identities.get("session_id") or "") in protection["session_ids"]
    )


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _mtime(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return 0.0


def _tree_size(path: Path) -> int:
    if path.is_file():
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        try:
            total += int(item.stat().st_size)
        except OSError:
            continue
    return total


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _assert_inside(path: Path, root: Path) -> None:
    path.resolve().relative_to(root.resolve())


def _safe_id(value: str, *, limit: int = 180) -> str:
    raw = str(value or "")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw).strip("_")
    if not safe:
        return "runtime"
    if len(safe) <= limit:
        return safe
    import hashlib

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    head_limit = max(1, limit - len(digest) - 1)
    return f"{safe[:head_limit].rstrip('_')}_{digest}"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _prune_empty_parents(path: Path, *, stop_at: Path) -> None:
    current = path.resolve()
    stop = stop_at.resolve()
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
