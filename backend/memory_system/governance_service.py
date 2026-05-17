from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

from fastapi import HTTPException

from memory_layout import durable_memory_layout_from_backend_dir
from structured_memory.frontmatter import format_frontmatter, parse_frontmatter

from .governance import MemoryGovernance
from .compat_types import MemoryNote, utc_now_iso
from .manifest_scan import MemoryHeader, load_memory_header, scan_memory_headers


class DurableMemoryGovernanceService:
    """Formal governance boundary for durable-memory files."""

    def __init__(self, base_dir: Path, *, memory_manager: Any) -> None:
        self.base_dir = Path(base_dir)
        self.memory_manager = memory_manager
        self.layout = durable_memory_layout_from_backend_dir(self.base_dir)
        self.governance = MemoryGovernance(base_dir)

    def scan_durable_memory_headers(self, *, limit: int = 200) -> list[MemoryHeader]:
        return scan_memory_headers(self.layout.root_dir, limit=limit)

    def load_durable_memory_note(self, filename: str) -> dict[str, Any]:
        path = self._safe_note_path(filename)
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
    ) -> dict[str, Any]:
        now = utc_now_iso()
        title = title.strip()
        canonical = canonical_statement.strip()
        summary = summary.strip() or canonical
        slug = self._unique_slug(title)
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
        path = self.memory_manager.save_note(note)
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
    ) -> dict[str, Any]:
        path = self._safe_note_path(filename)
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
        self.sync_durable_index()
        self._append_governance_log(action, [path.name], reason=reason)
        return {
            "filename": path.name,
            "header": load_memory_header(path),
        }

    def delete_durable_memory_note(self, *, filename: str, reason: str = "") -> dict[str, Any]:
        path = self._safe_note_path(filename)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Memory note not found")
        trash_dir = self.layout.root_dir / "trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        deleted_at = utc_now_iso()
        target = self._unique_trash_path(trash_dir, path.name)
        path.replace(target)
        self.sync_durable_index()
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
    ) -> dict[str, Any]:
        paths = [self._safe_note_path(filename) for filename in filenames]
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
        new_path = self.memory_manager.save_note(note)
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
        self.sync_durable_index()
        self._append_governance_log("merge", [path.name for path in paths], reason=reason, created=new_path.name)
        return {
            "filename": new_path.name,
            "merged": [path.name for path in paths],
            "header": load_memory_header(new_path),
        }

    def sync_durable_index(self) -> dict[str, object]:
        return self.memory_manager.sync_index()

    def govern_durable_notes(self) -> dict[str, object]:
        return self.memory_manager.govern_note_store()

    def _safe_note_path(self, filename: str) -> Path:
        safe_name = filename.strip()
        if (
            not safe_name
            or "/" in safe_name
            or "\\" in safe_name
            or safe_name.startswith(".")
            or not safe_name.endswith(".md")
        ):
            raise HTTPException(status_code=400, detail="Invalid memory filename")
        return self.layout.notes_dir / safe_name

    def _update_note_frontmatter(self, path: Path, updates: dict[str, str]) -> None:
        raw = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(raw)
        if not frontmatter:
            raise HTTPException(status_code=400, detail="Memory note has no frontmatter")
        merged = {**frontmatter, **updates}
        path.write_text(f"{format_frontmatter(merged)}\n\n{body.strip()}\n", encoding="utf-8", newline="\n")

    def _unique_slug(self, title: str) -> str:
        base_slug = self.memory_manager.slugify(title)
        if base_slug == "memory-note":
            digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
            base_slug = f"memory-{digest}"
        slug = base_slug
        index = 2
        while self.memory_manager.note_path(slug).exists():
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
