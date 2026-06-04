from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import threading
import time
from typing import Any

from fastapi import HTTPException

from project_layout import ProjectLayout
from memory_system.layout import durable_memory_layout_from_backend_dir, safe_memory_namespace_id
from memory_system.storage.consolidation import DurableMemoryConsolidator
from memory_system.storage.frontmatter import format_frontmatter, parse_frontmatter

from .contracts import MemoryCommitAction, MemoryCommitLayer, MemoryCommitRecord
from .manifest_scan import MemoryHeader, load_memory_header, scan_memory_headers
from .storage.memory_manager import MemoryManager
from .storage.models import MemoryNote, utc_now_iso


DEFAULT_GOVERNANCE_MIN_INTERVAL_SECONDS = 6 * 60 * 60


class MemoryGovernance:
    """Manual/governance memory commit audit boundary."""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.log_dir = durable_memory_layout_from_backend_dir(self.base_dir).meta_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / "governance_log.jsonl"

    def record(
        self,
        *,
        action: MemoryCommitAction,
        commit_layer: MemoryCommitLayer = "long_term",
        target_refs: tuple[str, ...] | list[str] = (),
        created_ref: str = "",
        reason: str = "",
        actor: str = "memory_governance_ui",
        allowed: bool = True,
        source_candidate_refs: tuple[str, ...] | list[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> MemoryCommitRecord:
        ts = utc_now_iso()
        record = MemoryCommitRecord(
            record_id=f"memory-commit:{commit_layer}:{action}:{_safe_stamp(ts)}",
            commit_layer=commit_layer,
            action=action,
            target_refs=tuple(str(item) for item in target_refs if str(item).strip()),
            created_ref=str(created_ref or ""),
            reason=str(reason or ""),
            actor=str(actor or "memory_governance"),
            allowed=bool(allowed),
            source_candidate_refs=tuple(str(item) for item in source_candidate_refs if str(item).strip()),
            metadata={"ts": ts, **dict(metadata or {})},
        )
        self.append(record)
        return record

    def append(self, record: MemoryCommitRecord) -> None:
        payload = record.to_dict()
        payload.setdefault("ts", dict(record.metadata).get("ts", ""))
        payload.setdefault("filenames", list(record.target_refs))
        payload.setdefault("created", record.created_ref)
        with self.log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


class DurableMemoryGovernanceService:
    """Formal governance boundary for durable-memory files."""

    def __init__(self, base_dir: Path, *, memory_manager: Any) -> None:
        self.base_dir = Path(base_dir)
        self.memory_manager = memory_manager
        self.layout = durable_memory_layout_from_backend_dir(self.base_dir)
        self.governance = MemoryGovernance(base_dir)
        project_layout = ProjectLayout.from_backend_dir(self.base_dir)
        self.runtime_dir = project_layout.runtime_state_dir / "durable_memory_governance"
        self.report_dir = self.runtime_dir / "reports"
        self.state_path = self.runtime_dir / "state.json"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def describe_runtime_state(self) -> dict[str, Any]:
        with self._lock:
            state = self._load_state()
        return {
            "authority": "memory_system.durable_memory_governance_service",
            "state_path": str(self.state_path),
            "report_root": str(self.report_dir),
            "default_min_interval_seconds": DEFAULT_GOVERNANCE_MIN_INTERVAL_SECONDS,
            "namespaces": dict(state.get("namespaces") or {}),
        }

    def mark_namespaces_dirty(
        self,
        saved_namespaces: dict[str, int] | None = None,
        *,
        reason: str = "durable_memory_saved",
    ) -> dict[str, Any]:
        normalized = {
            self._normalize_namespace_id(namespace_id): max(0, int(count or 0))
            for namespace_id, count in dict(saved_namespaces or {"global_common": 1}).items()
        }
        normalized = {namespace_id: count for namespace_id, count in normalized.items() if count > 0}
        if not normalized:
            normalized = {"global_common": 1}
        with self._lock:
            state = self._load_state()
            namespaces = self._state_namespaces(state)
            now = utc_now_iso()
            now_epoch = int(time.time())
            touched: dict[str, Any] = {}
            for namespace_id, count in normalized.items():
                entry = self._namespace_state_entry(namespaces, namespace_id)
                entry["dirty"] = True
                if not entry.get("dirty_since"):
                    entry["dirty_since"] = now
                entry["last_dirty_at"] = now
                entry["last_dirty_epoch"] = now_epoch
                entry["pending_save_count"] = int(entry.get("pending_save_count") or 0) + count
                entry["dirty_reason"] = str(reason or "durable_memory_saved")
                entry["root_dir"] = str(self._namespace_root(namespace_id))
                touched[namespace_id] = dict(entry)
            state["updated_at"] = now
            self._save_state(state)
        return {
            "status": "ok",
            "authority": "memory_system.durable_memory_governance_service",
            "dirty_namespaces": touched,
        }

    def run_governance_tick(
        self,
        *,
        namespace_ids: list[str] | tuple[str, ...] | None = None,
        force: bool = False,
        min_interval_seconds: int = DEFAULT_GOVERNANCE_MIN_INTERVAL_SECONDS,
        reason: str = "background_tick",
        source: str = "memory_system.durable_memory_governance_tick",
    ) -> dict[str, Any]:
        with self._lock:
            state = self._load_state()
            namespaces = self._state_namespaces(state)
            target_namespace_ids = self._target_namespace_ids(
                namespaces,
                namespace_ids=namespace_ids,
                force=force,
            )
            now = utc_now_iso()
            now_epoch = int(time.time())
            ran: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
            for namespace_id in target_namespace_ids:
                entry = self._namespace_state_entry(namespaces, namespace_id)
                decision = self._tick_decision(
                    entry,
                    force=force,
                    min_interval_seconds=max(0, int(min_interval_seconds or 0)),
                    now_epoch=now_epoch,
                )
                if not decision["should_run"]:
                    entry["last_skip_reason"] = decision["reason"]
                    entry["last_skip_at"] = now
                    skipped.append(
                        {
                            "namespace_id": namespace_id,
                            "reason": decision["reason"],
                            "seconds_until_eligible": decision.get("seconds_until_eligible", 0),
                        }
                    )
                    continue
                report_payload = self._run_namespace_governance(
                    namespace_id,
                    entry=entry,
                    force=force,
                    reason=reason,
                    source=source,
                    started_at=now,
                )
                entry["dirty"] = False
                entry["dirty_since"] = ""
                entry["pending_save_count"] = 0
                entry["last_governed_at"] = report_payload["completed_at"]
                entry["last_governed_epoch"] = int(time.time())
                entry["last_report_id"] = report_payload["report_id"]
                entry["last_report_path"] = report_payload["report_path"]
                entry["last_run_status"] = report_payload["status"]
                entry["last_skip_reason"] = ""
                entry["run_count"] = int(entry.get("run_count") or 0) + 1
                entry["root_dir"] = str(self._namespace_root(namespace_id))
                consolidation = dict(report_payload.get("consolidation") or {})
                governance_payload = dict(consolidation.get("governance_payload") or {})
                ran.append(
                    {
                        "namespace_id": namespace_id,
                        "status": report_payload["status"],
                        "report_id": report_payload["report_id"],
                        "report_path": report_payload["report_path"],
                        "updated": int(governance_payload.get("updated") or 0),
                    }
                )
            state["updated_at"] = utc_now_iso()
            self._save_state(state)
        return {
            "status": "ok",
            "authority": "memory_system.durable_memory_governance_tick",
            "force": bool(force),
            "min_interval_seconds": max(0, int(min_interval_seconds or 0)),
            "target_namespace_count": len(target_namespace_ids),
            "ran": ran,
            "skipped": skipped,
        }

    def scan_durable_memory_headers(self, *, limit: int = 200, namespace_id: str = "global_common") -> list[MemoryHeader]:
        return scan_memory_headers(self._namespace_root(namespace_id), limit=limit)

    def load_durable_memory_note(self, filename: str, *, namespace_id: str = "global_common") -> dict[str, Any]:
        path = self._safe_note_path(filename, namespace_id=namespace_id)
        if not path.exists() or path.suffix.lower() != ".md":
            raise HTTPException(status_code=404, detail="Memory note not found")
        return {
            "filename": path.name,
            "path": path,
            "header": load_memory_header(path),
            "content": path.read_text(encoding="utf-8"),
        }

    def create_durable_memory_note(
        self,
        *,
        title: str,
        canonical_statement: str,
        summary: str = "",
        memory_type: str = "project",
        memory_class: str = "work",
        retrieval_hints: list[str] | None = None,
        confidence: str = "medium",
        source_kind: str = "manual",
        source_message_excerpt: str = "",
        namespace_id: str = "global_common",
    ) -> dict[str, Any]:
        manager = self._namespace_manager(namespace_id)
        now = utc_now_iso()
        title = title.strip()
        canonical = canonical_statement.strip()
        summary = summary.strip() or canonical
        slug = self._unique_slug(title, manager=manager)
        memory_type = self._normalize_choice(memory_type, {"user", "feedback", "project", "reference"}, "project")
        memory_class = self._normalize_choice(memory_class, {"work", "preference"}, "work")
        hints = [item.strip() for item in list(retrieval_hints or []) if str(item).strip()][:8]
        note = MemoryNote(
            slug=slug,
            title=title,
            summary=summary,
            canonical_statement=canonical,
            body=self._build_note_body(
                canonical,
                hints,
                "Manual memory governance",
                source_message_excerpt or canonical,
            ),
            memory_type=memory_type,  # type: ignore[arg-type]
            memory_class=memory_class,  # type: ignore[arg-type]
            tags=[memory_type, memory_class],
            retrieval_hints=hints,
            created_at=now,
            updated_at=now,
            created_by="memory_governance_ui",
            source_role="user",
            source_message_excerpt=source_message_excerpt.strip() or canonical,
            confidence=confidence.strip() or "medium",
            status="active",
            scope="project",
            stability="stable",
            source_kind=source_kind.strip() or "manual",
            eligible_for_injection="true",
        )
        path = manager.save_note(note)
        self._append_governance_log("create", [path.name], reason="manual_create", created=path.name)
        return {
            "filename": path.name,
            "header": load_memory_header(path),
        }

    def set_durable_memory_note_status(
        self,
        *,
        filename: str,
        status: str,
        eligible_for_injection: str,
        reason: str,
        action: str,
        namespace_id: str = "global_common",
    ) -> dict[str, Any]:
        manager = self._namespace_manager(namespace_id)
        path = self._safe_note_path(filename, namespace_id=namespace_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Memory note not found")
        self._update_note_frontmatter(
            path,
            {
                "status": status,
                "eligible_for_injection": eligible_for_injection,
                "updated_at": utc_now_iso(),
                "invalidation_reason": reason.strip(),
            },
        )
        manager.sync_index()
        self._append_governance_log(action, [path.name], reason=reason)
        return {
            "filename": path.name,
            "header": load_memory_header(path),
        }

    def delete_durable_memory_note(self, *, filename: str, reason: str = "", namespace_id: str = "global_common") -> dict[str, Any]:
        manager = self._namespace_manager(namespace_id)
        path = self._safe_note_path(filename, namespace_id=namespace_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Memory note not found")
        trash_dir = manager.root_dir / "trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        deleted_at = utc_now_iso()
        target = self._unique_trash_path(trash_dir, path.name)
        path.replace(target)
        manager.sync_index()
        self._append_governance_log(
            "delete",
            [path.name],
            reason=reason or "Deleted from memory UI",
            created=f"durable_memory/trash/{target.name}",
        )
        return {
            "filename": path.name,
            "deleted_at": deleted_at,
            "trash_path": f"durable_memory/trash/{target.name}",
        }

    def merge_durable_memory_notes(
        self,
        *,
        filenames: list[str],
        title: str,
        canonical_statement: str,
        summary: str = "",
        reason: str = "",
        namespace_id: str = "global_common",
    ) -> dict[str, Any]:
        manager = self._namespace_manager(namespace_id)
        paths = [self._safe_note_path(filename, namespace_id=namespace_id) for filename in filenames]
        missing = [path.name for path in paths if not path.exists()]
        if missing:
            raise HTTPException(status_code=404, detail=f"Memory note not found: {', '.join(missing)}")

        now = utc_now_iso()
        loaded = [load_memory_header(path) for path in paths]
        hints: list[str] = []
        for header in loaded:
            if header:
                hints.extend(header.retrieval_hints)
        canonical = canonical_statement.strip()
        summary = summary.strip() or canonical
        slug = self._unique_slug(title.strip())
        source_excerpt = " / ".join(header.title for header in loaded if header)[:1000]
        note = MemoryNote(
            slug=slug,
            title=title.strip(),
            summary=summary,
            canonical_statement=canonical,
            body=self._build_note_body(canonical, hints, reason or "Merged durable memories", source_excerpt),
            memory_type=(loaded[0].memory_type if loaded[0] else "project"),  # type: ignore[arg-type]
            memory_class=(loaded[0].memory_class if loaded[0] else "work"),  # type: ignore[arg-type]
            tags=["merged", "governed"],
            retrieval_hints=self._dedupe(hints + [title.strip(), canonical])[:8],
            created_at=now,
            updated_at=now,
            created_by="memory_governance_ui",
            source_role="user",
            source_message_excerpt=source_excerpt,
            confidence="medium",
            status="active",
            scope="project",
            stability="stable",
            source_kind="manual_merge",
            eligible_for_injection="true",
            supersedes=", ".join(path.stem for path in paths),
        )
        new_path = manager.save_note(note)
        for path in paths:
            self._update_note_frontmatter(
                path,
                {
                    "status": "deprecated",
                    "eligible_for_injection": "false",
                    "updated_at": now,
                    "invalidation_reason": reason.strip() or f"Merged into {new_path.stem}",
                },
            )
        manager.sync_index()
        self._append_governance_log("merge", [path.name for path in paths], reason=reason, created=new_path.name)
        return {
            "filename": new_path.name,
            "merged": [path.name for path in paths],
            "header": load_memory_header(new_path),
        }

    def sync_durable_index(self) -> dict[str, object]:
        return self.memory_manager.sync_index()

    def govern_durable_notes(self) -> dict[str, object]:
        tick = self.run_governance_tick(
            namespace_ids=["global_common"],
            force=True,
            min_interval_seconds=0,
            reason="manual_govern_durable_notes",
            source="memory_system.durable_memory_governance_service.manual",
        )
        return tick

    def _safe_note_path(self, filename: str, *, namespace_id: str = "global_common") -> Path:
        safe_name = filename.strip()
        if (
            not safe_name
            or "/" in safe_name
            or "\\" in safe_name
            or safe_name.startswith(".")
            or not safe_name.endswith(".md")
        ):
            raise HTTPException(status_code=400, detail="Invalid memory filename")
        return self._namespace_manager(namespace_id).layout.notes_dir / safe_name

    def _update_note_frontmatter(self, path: Path, updates: dict[str, str]) -> None:
        raw = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(raw)
        if not frontmatter:
            raise HTTPException(status_code=400, detail="Memory note has no frontmatter")
        merged = {**frontmatter, **updates}
        path.write_text(f"{format_frontmatter(merged)}\n\n{body.strip()}\n", encoding="utf-8", newline="\n")

    def _unique_slug(self, title: str, *, manager: Any | None = None) -> str:
        resolved_manager = manager or self.memory_manager
        base_slug = resolved_manager.slugify(title)
        if base_slug == "memory-note":
            digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
            base_slug = f"memory-{digest}"
        slug = base_slug
        index = 2
        while resolved_manager.note_path(slug).exists():
            slug = f"{base_slug}-{index}"
            index += 1
        return slug

    def _unique_trash_path(self, trash_dir: Path, filename: str) -> Path:
        candidate = trash_dir / filename
        if not candidate.exists():
            return candidate
        stem = candidate.stem
        suffix = candidate.suffix
        timestamp = re.sub(r"[^0-9]", "", utc_now_iso())[:14] or "deleted"
        index = 2
        candidate = trash_dir / f"{stem}.{timestamp}{suffix}"
        while candidate.exists():
            candidate = trash_dir / f"{stem}.{timestamp}-{index}{suffix}"
            index += 1
        return candidate

    def _normalize_choice(self, value: str, allowed: set[str], fallback: str) -> str:
        normalized = re.sub(r"[^a-zA-Z_-]", "", value.strip().lower())
        return normalized if normalized in allowed else fallback

    def _build_note_body(self, canonical: str, hints: list[str], why: str, evidence: str) -> str:
        hint_lines = "\n".join(f"- {item.strip()}" for item in hints if item.strip()) or "- 无"
        return (
            f"## Canonical Memory\n{canonical.strip()}\n\n"
            f"## Retrieval Hints\n{hint_lines}\n\n"
            f"## Why Stored\n{why.strip() or 'Manual durable memory governance'}\n\n"
            f"## Source Evidence\n{evidence.strip() or canonical.strip()}"
        )

    def _dedupe(self, items: list[str]) -> list[str]:
        deduped: list[str] = []
        for item in items:
            normalized = str(item or "").strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped

    def _append_governance_log(
        self,
        action: str,
        filenames: list[str],
        *,
        reason: str = "",
        created: str = "",
    ) -> None:
        mapped_action = {
            "create": "manual_create",
            "disable": "manual_disable",
            "activate": "manual_activate",
            "archive": "manual_archive",
            "delete": "manual_delete",
            "merge": "manual_merge",
        }.get(action, "manual_update")
        self.governance.record(
            action=mapped_action,  # type: ignore[arg-type]
            commit_layer="long_term",
            target_refs=tuple(filenames),
            created_ref=created,
            reason=reason,
            actor="memory_governance_ui",
            allowed=True,
            metadata={"source_action": action},
        )

    def _target_namespace_ids(
        self,
        namespaces: dict[str, Any],
        *,
        namespace_ids: list[str] | tuple[str, ...] | None,
        force: bool,
    ) -> list[str]:
        if namespace_ids:
            return self._dedupe_namespace_ids(namespace_ids)
        dirty = [
            namespace_id
            for namespace_id, entry in sorted(namespaces.items())
            if bool(dict(entry or {}).get("dirty"))
        ]
        if dirty:
            return dirty
        if force:
            known = sorted(namespaces)
            return known or ["global_common"]
        return []

    def _tick_decision(
        self,
        entry: dict[str, Any],
        *,
        force: bool,
        min_interval_seconds: int,
        now_epoch: int,
    ) -> dict[str, Any]:
        if force:
            return {"should_run": True, "reason": "forced"}
        if not bool(entry.get("dirty")):
            return {"should_run": False, "reason": "namespace_clean"}
        last_epoch = int(entry.get("last_governed_epoch") or 0)
        if last_epoch and min_interval_seconds > 0:
            elapsed = max(0, now_epoch - last_epoch)
            if elapsed < min_interval_seconds:
                return {
                    "should_run": False,
                    "reason": "minimum_interval_not_elapsed",
                    "seconds_until_eligible": min_interval_seconds - elapsed,
                }
        return {"should_run": True, "reason": "dirty_namespace"}

    def _run_namespace_governance(
        self,
        namespace_id: str,
        *,
        entry: dict[str, Any],
        force: bool,
        reason: str,
        source: str,
        started_at: str,
    ) -> dict[str, Any]:
        root_dir = self._namespace_root(namespace_id)
        report = DurableMemoryConsolidator(root_dir).run()
        completed_at = utc_now_iso()
        report_id = f"{_safe_stamp(completed_at)}-{time.time_ns() % 1_000_000:06d}-{report.report_id or 'empty'}"
        payload = {
            "authority": "memory_system.durable_memory_governance_report",
            "status": "ok",
            "namespace_id": namespace_id,
            "root_dir": str(root_dir),
            "started_at": started_at,
            "completed_at": completed_at,
            "force": bool(force),
            "reason": str(reason or ""),
            "source": str(source or ""),
            "pending_save_count": int(entry.get("pending_save_count") or 0),
            "report_id": report_id,
            "consolidation": report.to_dict(),
        }
        report_path = self._persist_report(namespace_id, report_id, payload)
        payload["report_path"] = str(report_path)
        return payload

    def _persist_report(self, namespace_id: str, report_id: str, payload: dict[str, Any]) -> Path:
        namespace_dir = self.report_dir / self._safe_report_namespace(namespace_id)
        namespace_dir.mkdir(parents=True, exist_ok=True)
        report_path = namespace_dir / f"{report_id}.json"
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        latest_path = namespace_dir / "latest.json"
        latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        return report_path

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "authority": "memory_system.durable_memory_governance_state",
                "version": 1,
                "namespaces": {},
                "updated_at": "",
            }
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Durable memory governance state must be a JSON object")
        payload.setdefault("authority", "memory_system.durable_memory_governance_state")
        payload.setdefault("version", 1)
        payload.setdefault("namespaces", {})
        return payload

    def _save_state(self, state: dict[str, Any]) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        tmp_path.replace(self.state_path)

    def _state_namespaces(self, state: dict[str, Any]) -> dict[str, Any]:
        namespaces = state.get("namespaces")
        if not isinstance(namespaces, dict):
            namespaces = {}
            state["namespaces"] = namespaces
        return namespaces

    def _namespace_state_entry(self, namespaces: dict[str, Any], namespace_id: str) -> dict[str, Any]:
        normalized = self._normalize_namespace_id(namespace_id)
        entry = namespaces.get(normalized)
        if not isinstance(entry, dict):
            entry = {
                "namespace_id": normalized,
                "dirty": False,
                "dirty_since": "",
                "pending_save_count": 0,
                "last_governed_at": "",
                "last_governed_epoch": 0,
                "last_report_id": "",
                "last_report_path": "",
                "run_count": 0,
                "root_dir": str(self._namespace_root(normalized)),
            }
            namespaces[normalized] = entry
        return entry

    def _namespace_root(self, namespace_id: str) -> Path:
        normalized = self._normalize_namespace_id(namespace_id)
        if normalized == "global_common":
            return self.layout.root_dir
        if normalized.startswith("env:"):
            safe_id = safe_memory_namespace_id(normalized.removeprefix("env:"))
            return self.layout.root_dir / "environments" / safe_id
        raise ValueError(f"Unsupported durable memory namespace: {namespace_id}")

    def _namespace_manager(self, namespace_id: str) -> MemoryManager:
        normalized = self._normalize_namespace_id(namespace_id)
        if normalized == "global_common":
            return self.memory_manager
        return MemoryManager(self._namespace_root(normalized))

    def _normalize_namespace_id(self, namespace_id: str) -> str:
        normalized = str(namespace_id or "").strip()
        if not normalized or normalized in {"global", "global_common"}:
            return "global_common"
        if normalized.startswith("env:"):
            return f"env:{safe_memory_namespace_id(normalized.removeprefix('env:'))}"
        return f"env:{safe_memory_namespace_id(normalized)}"

    def _dedupe_namespace_ids(self, namespace_ids: list[str] | tuple[str, ...]) -> list[str]:
        result: list[str] = []
        for namespace_id in namespace_ids:
            normalized = self._normalize_namespace_id(namespace_id)
            if normalized not in result:
                result.append(normalized)
        return result

    def _safe_report_namespace(self, namespace_id: str) -> str:
        normalized = self._normalize_namespace_id(namespace_id)
        if normalized == "global_common":
            return "global_common"
        return f"env-{safe_memory_namespace_id(normalized.removeprefix('env:'))}"


def _safe_stamp(value: str) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())[:14] or "record"



