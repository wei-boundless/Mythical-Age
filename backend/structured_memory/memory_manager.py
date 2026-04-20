from __future__ import annotations

from pathlib import Path
import re
from typing import NamedTuple

from memory_layout import DurableMemoryLayout

from .frontmatter import parse_frontmatter
from .models import DEFAULT_DURABLE_SCHEMA_VERSION, MemoryNote
from .note_hygiene import is_runtime_noise_note, normalize_durable_fact_text
from .text_utils import normalize_storage_text, repair_mojibake


MAX_ENTRYPOINT_LINES = 200
MAX_ENTRYPOINT_BYTES = 25_000


class LoadedMemoryNote(NamedTuple):
    filename: str
    schema_version: str
    title: str
    summary: str
    canonical_statement: str
    memory_type: str
    memory_class: str
    retrieval_hints: list[str]
    created_at: str
    updated_at: str
    created_by: str
    source_session_id: str
    source_role: str
    source_message_excerpt: str
    confidence: str
    status: str
    last_confirmed_at: str
    scope: str
    stability: str
    source_kind: str
    eligible_for_injection: str
    review_after: str
    supersedes: str
    invalidation_reason: str
    content: str


class MemoryManager:
    """File-based durable memory store inspired by the TS implementation."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.layout = DurableMemoryLayout(self.root_dir)
        self.layout.ensure_dirs()
        self._migrate_legacy_layout()
        self.index_path = self.layout.index_path
        if not self.index_path.exists():
            self.index_path.write_text(
                "# Memory Index\n\n"
                "<!-- One line per memory: - [Title](file.md) - short hook -->\n",
                encoding="utf-8",
            )

    @staticmethod
    def slugify(text: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
        slug = slug or "memory-note"
        if slug == "memory":
            return "memory-note"
        return slug

    def note_path(self, slug: str) -> Path:
        return self.layout.notes_dir / f"{slug}.md"

    def list_note_paths(self) -> list[Path]:
        return sorted(
            list(self.layout.notes_dir.glob("*.md")),
            key=lambda item: item.name.lower(),
        )

    def save_note(self, note: MemoryNote) -> Path:
        governed_note, notes_to_update = self._apply_save_governance(note)
        for staged_note in notes_to_update:
            self._write_note(staged_note)
        path = self._write_note(governed_note)
        self.sync_index()
        return path

    def repair_store(self) -> dict[str, object]:
        note_paths = self.list_note_paths()
        notes: list[MemoryNote] = []
        repaired_files: list[str] = []

        for path in note_paths:
            note = self._repair_note_file(path)
            notes.append(note)
            repaired_files.append(path.name)

        self._rewrite_index(notes)
        return {
            "status": "ok",
            "notes_rewritten": len(notes),
            "files": repaired_files,
        }

    def delete_note(self, slug: str) -> bool:
        path = self.note_path(slug)
        if not path.exists():
            return False
        path.unlink()
        self._remove_index_line(path.name)
        return True

    def list_index_entries(self) -> list[str]:
        content = repair_mojibake(self.index_path.read_text(encoding="utf-8"))
        return [line.strip() for line in content.splitlines() if line.strip().startswith("- [")]

    def list_index_filenames(self) -> list[str]:
        filenames: list[str] = []
        for entry in self.list_index_entries():
            match = re.search(r"\(([^)]+)\)", entry)
            if match:
                filenames.append(match.group(1))
        return filenames

    def list_notes(self) -> list[LoadedMemoryNote]:
        return [self._load_loaded_note(path) for path in self.list_note_paths()]

    def audit_store(self) -> dict[str, object]:
        note_files = [path.name for path in self.list_note_paths()]
        index_files = self.list_index_filenames()
        note_set = set(note_files)
        index_set = set(index_files)
        return {
            "note_files": note_files,
            "index_files": index_files,
            "ghost_entries": [name for name in index_files if name not in note_set],
            "missing_from_index": [name for name in note_files if name not in index_set],
        }

    def sync_index(self) -> dict[str, object]:
        notes = [
            MemoryNote(
                slug=path.stem,
                schema_version=loaded.schema_version or DEFAULT_DURABLE_SCHEMA_VERSION,
                title=loaded.title,
                summary=loaded.summary or loaded.title,
                canonical_statement=loaded.canonical_statement or loaded.summary or loaded.title,
                body=loaded.content or loaded.summary or loaded.title,
                memory_type=loaded.memory_type,
                memory_class=loaded.memory_class,
                retrieval_hints=list(loaded.retrieval_hints),
                created_at=loaded.created_at or loaded.updated_at or MemoryNote(slug=path.stem, title="", summary="", body="").created_at,
                updated_at=loaded.updated_at or MemoryNote(slug=path.stem, title="", summary="", body="").updated_at,
                created_by=loaded.created_by or "migration",
                source_session_id=loaded.source_session_id,
                source_role=loaded.source_role or "user",
                source_message_excerpt=loaded.source_message_excerpt,
                confidence=loaded.confidence or "medium",
                status=loaded.status or "active",
                last_confirmed_at=loaded.last_confirmed_at,
                scope=loaded.scope or "project",
                stability=loaded.stability or "stable",
                source_kind=loaded.source_kind,
                eligible_for_injection=loaded.eligible_for_injection or "true",
                review_after=loaded.review_after,
                supersedes=loaded.supersedes,
                invalidation_reason=loaded.invalidation_reason,
            )
            for path, loaded in ((path, self._load_loaded_note(path)) for path in self.list_note_paths())
        ]
        self._rewrite_index(notes)
        audit = self.audit_store()
        audit["status"] = "ok"
        return audit

    def ensure_index_consistent(self) -> dict[str, object]:
        audit = self.audit_store()
        if audit["ghost_entries"] or audit["missing_from_index"]:
            synced = self.sync_index()
            synced["repaired"] = True
            return synced
        audit["status"] = "ok"
        audit["repaired"] = False
        return audit

    def load_index(self) -> str:
        return self._truncate_entrypoint(
            repair_mojibake(self.index_path.read_text(encoding="utf-8"))
        )

    def load_note(self, slug: str) -> str | None:
        path = self.note_path(slug)
        if not path.exists():
            return None
        return repair_mojibake(path.read_text(encoding="utf-8"))

    def load_relevant_notes(self, limit: int = 5) -> list[LoadedMemoryNote]:
        active_notes = [note for note in self.list_notes() if self._is_runtime_eligible(note)]
        return active_notes[:limit]

    def build_manifest(self, limit: int = 50) -> str:
        manifest_lines: list[str] = []
        for note in self.load_relevant_notes(limit=limit):
            summary_source = note.summary or note.canonical_statement
            summary = f": {summary_source}" if summary_source else ""
            manifest_lines.append(
                f"- [{note.memory_class}/{note.memory_type}] {note.filename} [{note.confidence}/{note.status}/{note.stability}]{summary}"
            )
        return "\n".join(manifest_lines)

    def govern_note_store(self) -> dict[str, object]:
        updated = 0
        seen_active_keys: dict[tuple[str, str, str], str] = {}
        for loaded in self.list_notes():
            note = self._loaded_to_memory_note(loaded)
            dirty = False
            if is_runtime_noise_note(
                source_role=note.source_role,
                created_by=note.created_by,
                title=note.title,
                summary=note.summary,
                canonical_statement=note.canonical_statement,
                source_message_excerpt=note.source_message_excerpt,
            ):
                if note.status != "deprecated":
                    note.status = "deprecated"
                    dirty = True
                if normalize_storage_text(note.eligible_for_injection).lower() != "false":
                    note.eligible_for_injection = "false"
                    dirty = True
                if not note.invalidation_reason:
                    note.invalidation_reason = "runtime_noise_note"
                    dirty = True
            else:
                note, normalized_dirty = self._normalize_governed_note(note)
                dirty = dirty or normalized_dirty
                canonical_key = self._governance_canonical_key(note)
                if canonical_key is not None:
                    existing_slug = seen_active_keys.get(canonical_key)
                    if existing_slug and existing_slug != note.slug:
                        if note.status != "deprecated":
                            note.status = "deprecated"
                            dirty = True
                        if normalize_storage_text(note.eligible_for_injection).lower() != "false":
                            note.eligible_for_injection = "false"
                            dirty = True
                        if not note.invalidation_reason:
                            note.invalidation_reason = f"duplicate_of:{existing_slug}"
                            dirty = True
                    elif self._is_runtime_visible(note.status) and normalize_storage_text(note.eligible_for_injection).lower() not in {"false", "no", "0"}:
                        seen_active_keys[canonical_key] = note.slug
            if dirty:
                note.updated_at = MemoryNote(slug="", title="", summary="", body="").updated_at
                self._write_note(note)
                updated += 1
        self.sync_index()
        return {"status": "ok", "updated": updated}

    def _normalize_governed_note(self, note: MemoryNote) -> tuple[MemoryNote, bool]:
        dirty = False
        normalized_canonical = normalize_durable_fact_text(note.canonical_statement)
        normalized_summary = normalize_durable_fact_text(note.summary)
        normalized_title = normalize_durable_fact_text(note.title)

        if normalized_canonical and normalized_canonical != note.canonical_statement:
            note.canonical_statement = normalized_canonical
            dirty = True
        if normalized_summary and normalized_summary != note.summary:
            note.summary = normalized_summary
            dirty = True
        if normalized_title and normalized_title != note.title:
            note.title = normalized_title[:24] if any("\u4e00" <= char <= "\u9fff" for char in normalized_title) else normalized_title
            dirty = True

        normalized_excerpt = normalize_durable_fact_text(note.source_message_excerpt)
        if normalized_excerpt and normalized_excerpt != note.source_message_excerpt:
            note.source_message_excerpt = normalized_excerpt
            dirty = True

        merged_hints: list[str] = []
        for hint in note.retrieval_hints:
            normalized_hint = normalize_durable_fact_text(hint) or normalize_storage_text(hint)
            normalized_hint = normalize_storage_text(normalized_hint)
            if normalized_hint and normalized_hint not in merged_hints:
                merged_hints.append(normalized_hint)
        if note.canonical_statement and note.canonical_statement not in merged_hints:
            merged_hints.insert(0, note.canonical_statement)
        if merged_hints != note.retrieval_hints:
            note.retrieval_hints = merged_hints[:8]
            dirty = True

        body_replacement_map = {
            normalize_storage_text(note.title): note.title,
            normalize_storage_text(note.summary): note.summary,
            normalize_storage_text(note.canonical_statement): note.canonical_statement,
        }
        updated_body = note.body
        for original, replacement in body_replacement_map.items():
            normalized_original = normalize_durable_fact_text(original)
            if normalized_original and normalized_original != original and original in updated_body:
                updated_body = updated_body.replace(original, normalized_original)
        if updated_body != note.body:
            note.body = updated_body
            dirty = True

        return note, dirty

    def _governance_canonical_key(self, note: MemoryNote) -> tuple[str, str, str] | None:
        canonical = normalize_storage_text(note.canonical_statement).lower()
        if not canonical:
            return None
        return (
            normalize_storage_text(note.memory_class).lower(),
            normalize_storage_text(note.memory_type).lower(),
            canonical,
        )

    def select_relevant_notes(
        self,
        query: str,
        *,
        preferred_types: list[str] | None = None,
        preferred_classes: list[str] | None = None,
        limit: int = 3,
        exclude_filenames: set[str] | None = None,
        min_score: float = 3.5,
    ) -> list[LoadedMemoryNote]:
        query_terms = self._extract_terms(query)
        if not query_terms:
            return []

        preferred_types = preferred_types or []
        preferred_classes = preferred_classes or []
        exclude_filenames = exclude_filenames or set()

        scored: list[tuple[float, LoadedMemoryNote]] = []
        for path in self.list_note_paths():
            if path.name in exclude_filenames:
                continue
            note = self._load_loaded_note(path)
            if not self._is_runtime_eligible(note):
                continue
            score = self._score_loaded_note(
                note,
                query_terms,
                preferred_types=preferred_types,
                preferred_classes=preferred_classes,
            )
            if score < min_score:
                continue
            scored.append((score, note))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [note for _, note in scored[:limit]]

    def _upsert_index_line(self, title: str, filename: str, summary: str) -> None:
        safe_title = normalize_storage_text(title)
        safe_summary = normalize_storage_text(summary)
        line = f"- [{safe_title}]({filename}) - {safe_summary}"
        lines = repair_mojibake(self.index_path.read_text(encoding="utf-8")).splitlines()
        updated = False
        out: list[str] = []
        for existing in lines:
            if f"]({filename})" in existing:
                out.append(line)
                updated = True
            else:
                out.append(existing)
        if not updated:
            if out and out[-1].strip():
                out.append("")
            out.append(line)
        final = "\n".join(out).rstrip() + "\n"
        self.index_path.write_text(final, encoding="utf-8", newline="\n")

    def _write_note(self, note: MemoryNote) -> Path:
        path = self.note_path(note.slug)
        path.write_text(note.to_markdown(), encoding="utf-8", newline="\n")
        self._upsert_index_line(note.title, path.name, note.summary)
        return path

    def _remove_index_line(self, filename: str) -> None:
        lines = repair_mojibake(self.index_path.read_text(encoding="utf-8")).splitlines()
        kept = [line for line in lines if f"]({filename})" not in line]
        self.index_path.write_text(
            "\n".join(kept).rstrip() + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def _repair_note_file(self, path: Path) -> MemoryNote:
        raw = repair_mojibake(path.read_text(encoding="utf-8"))
        frontmatter, body = parse_frontmatter(raw)

        schema_version = normalize_storage_text(frontmatter.get("schema_version", ""))
        title = normalize_storage_text(frontmatter.get("title", path.stem.replace("-", " ")))
        summary = normalize_storage_text(frontmatter.get("summary", ""))
        canonical_statement = normalize_storage_text(frontmatter.get("canonical_statement", ""))
        memory_type = normalize_storage_text(frontmatter.get("type", "project")) or "project"
        memory_class = normalize_storage_text(
            frontmatter.get("memory_class", self._default_memory_class(memory_type))
        ) or self._default_memory_class(memory_type)
        tags = self._normalize_list_field(frontmatter.get("tags", ""))
        retrieval_hints = self._normalize_list_field(frontmatter.get("retrieval_hints", ""))
        created_at = normalize_storage_text(frontmatter.get("created_at", ""))
        updated_at = normalize_storage_text(frontmatter.get("updated_at", ""))
        created_by = normalize_storage_text(frontmatter.get("created_by", ""))
        source_session_id = normalize_storage_text(frontmatter.get("source_session_id", ""))
        source_role = normalize_storage_text(frontmatter.get("source_role", ""))
        source_message_excerpt = normalize_storage_text(frontmatter.get("source_message_excerpt", ""))
        confidence = normalize_storage_text(frontmatter.get("confidence", ""))
        status = normalize_storage_text(frontmatter.get("status", ""))
        last_confirmed_at = normalize_storage_text(frontmatter.get("last_confirmed_at", ""))
        scope = normalize_storage_text(frontmatter.get("scope", ""))
        stability = normalize_storage_text(frontmatter.get("stability", ""))
        source_kind = normalize_storage_text(frontmatter.get("source_kind", ""))
        eligible_for_injection = normalize_storage_text(frontmatter.get("eligible_for_injection", ""))
        review_after = normalize_storage_text(frontmatter.get("review_after", ""))
        supersedes = normalize_storage_text(frontmatter.get("supersedes", ""))
        invalidation_reason = normalize_storage_text(frontmatter.get("invalidation_reason", ""))
        body_text = normalize_storage_text(body)

        if not frontmatter:
            (
                schema_version,
                title,
                summary,
                canonical_statement,
                memory_type,
                memory_class,
                tags,
                retrieval_hints,
                created_at,
                updated_at,
                created_by,
                source_session_id,
                source_role,
                source_message_excerpt,
                confidence,
                status,
                last_confirmed_at,
                scope,
                stability,
                source_kind,
                eligible_for_injection,
                review_after,
                supersedes,
                invalidation_reason,
                body_text,
            ) = self._repair_legacy_note(raw, path)

        note = MemoryNote(
            slug=path.stem,
            schema_version=schema_version or DEFAULT_DURABLE_SCHEMA_VERSION,
            title=title or path.stem.replace("-", " "),
            summary=summary or title or path.stem.replace("-", " "),
            canonical_statement=canonical_statement or summary or title or path.stem.replace("-", " "),
            body=body_text or summary or title or path.stem.replace("-", " "),
            memory_type=self._normalize_memory_type(memory_type),
            memory_class=self._normalize_memory_class(memory_class, memory_type),
            tags=tags,
            retrieval_hints=retrieval_hints,
            created_at=created_at or updated_at or MemoryNote(slug=path.stem, title="", summary="", body="").created_at,
            updated_at=updated_at or MemoryNote(slug=path.stem, title="", summary="", body="").updated_at,
            created_by=created_by or "legacy-repair",
            source_session_id=source_session_id,
            source_role=source_role or "user",
            source_message_excerpt=source_message_excerpt or summary,
            confidence=confidence or "medium",
            status=status or "active",
            last_confirmed_at=last_confirmed_at,
            scope=scope or "project",
            stability=stability or "stable",
            source_kind=source_kind,
            eligible_for_injection=eligible_for_injection or "true",
            review_after=review_after,
            supersedes=supersedes,
            invalidation_reason=invalidation_reason,
        )
        path.write_text(note.to_markdown(), encoding="utf-8", newline="\n")
        return note

    def _repair_legacy_note(
        self,
        raw: str,
        path: Path,
    ) -> tuple[str, str, str, str, str, str, list[str], list[str], str, str, str, str, str, str, str, str, str, str, str, str, str, str, str, str, str]:
        text = normalize_storage_text(raw)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        schema_version = DEFAULT_DURABLE_SCHEMA_VERSION
        title = path.stem.replace("-", " ")
        summary = ""
        canonical_statement = ""
        memory_type = "project"
        memory_class = self._default_memory_class(memory_type)
        tags: list[str] = []
        retrieval_hints: list[str] = []
        created_at = ""
        updated_at = ""
        created_by = "legacy-repair"
        source_session_id = ""
        source_role = "user"
        source_message_excerpt = ""
        confidence = "medium"
        status = "active"
        last_confirmed_at = ""
        scope = "project"
        stability = "stable"
        source_kind = ""
        eligible_for_injection = "true"
        review_after = ""
        supersedes = ""
        invalidation_reason = ""
        body_lines: list[str] = []
        in_metadata_block = False

        for line in lines:
            lowered = line.lower()
            metadata_line = line[2:].strip() if line.startswith("- ") else line
            metadata_lowered = metadata_line.lower()
            if line.startswith("# "):
                title = normalize_storage_text(line[2:]) or title
                continue
            if lowered.startswith("## metadata"):
                in_metadata_block = True
                continue
            if lowered.startswith("## canonical memory"):
                in_metadata_block = False
                continue
            if metadata_lowered.startswith("title:"):
                title = normalize_storage_text(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("summary:"):
                summary = normalize_storage_text(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("canonical_statement:"):
                canonical_statement = normalize_storage_text(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("type:"):
                memory_type = normalize_storage_text(metadata_line.split(":", 1)[1]) or "project"
                memory_class = self._default_memory_class(memory_type)
                continue
            if metadata_lowered.startswith("memory class:") or metadata_lowered.startswith("memory_class:"):
                memory_class = normalize_storage_text(metadata_line.split(":", 1)[1]) or self._default_memory_class(memory_type)
                continue
            if metadata_lowered.startswith("tags:"):
                tags = self._normalize_list_field(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("retrieval hints:") or metadata_lowered.startswith("retrieval_hints:"):
                retrieval_hints = self._normalize_list_field(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("updated at:") or metadata_lowered.startswith("updated_at:"):
                updated_at = normalize_storage_text(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("created at:") or metadata_lowered.startswith("created_at:"):
                created_at = normalize_storage_text(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("created by:") or metadata_lowered.startswith("created_by:"):
                created_by = normalize_storage_text(metadata_line.split(":", 1)[1]) or "legacy-repair"
                continue
            if metadata_lowered.startswith("source session id:") or metadata_lowered.startswith("source_session_id:"):
                source_session_id = normalize_storage_text(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("source role:") or metadata_lowered.startswith("source_role:"):
                source_role = normalize_storage_text(metadata_line.split(":", 1)[1]) or "user"
                continue
            if metadata_lowered.startswith("source message excerpt:") or metadata_lowered.startswith("source_message_excerpt:"):
                source_message_excerpt = normalize_storage_text(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("confidence:"):
                confidence = normalize_storage_text(metadata_line.split(":", 1)[1]) or "medium"
                continue
            if metadata_lowered.startswith("status:"):
                status = normalize_storage_text(metadata_line.split(":", 1)[1]) or "active"
                continue
            if metadata_lowered.startswith("schema:") or metadata_lowered.startswith("schema_version:"):
                schema_version = normalize_storage_text(metadata_line.split(":", 1)[1]) or DEFAULT_DURABLE_SCHEMA_VERSION
                continue
            if metadata_lowered.startswith("last confirmed at:") or metadata_lowered.startswith("last_confirmed_at:"):
                last_confirmed_at = normalize_storage_text(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("scope:"):
                scope = normalize_storage_text(metadata_line.split(":", 1)[1]) or "project"
                continue
            if metadata_lowered.startswith("stability:"):
                stability = normalize_storage_text(metadata_line.split(":", 1)[1]) or "stable"
                continue
            if metadata_lowered.startswith("source kind:") or metadata_lowered.startswith("source_kind:"):
                source_kind = normalize_storage_text(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("eligible for injection:") or metadata_lowered.startswith("eligible_for_injection:"):
                eligible_for_injection = normalize_storage_text(metadata_line.split(":", 1)[1]) or "true"
                continue
            if metadata_lowered.startswith("review after:") or metadata_lowered.startswith("review_after:"):
                review_after = normalize_storage_text(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("supersedes:"):
                supersedes = normalize_storage_text(metadata_line.split(":", 1)[1])
                continue
            if metadata_lowered.startswith("invalidation reason:") or metadata_lowered.startswith("invalidation_reason:"):
                invalidation_reason = normalize_storage_text(metadata_line.split(":", 1)[1])
                continue
            if in_metadata_block and line.startswith("- "):
                continue
            body_lines.append(line)

        body = normalize_storage_text("\n".join(body_lines))
        if not summary:
            summary = body.splitlines()[0] if body else title
        if not canonical_statement:
            canonical_statement = summary
        if not retrieval_hints:
            retrieval_hints = list(tags)
        if not source_message_excerpt:
            source_message_excerpt = summary
        return (
            schema_version,
            title,
            summary,
            canonical_statement,
            memory_type,
            memory_class,
            tags,
            retrieval_hints,
            created_at,
            updated_at,
            created_by,
            source_session_id,
            source_role,
            source_message_excerpt,
            confidence,
            status,
            last_confirmed_at,
            scope,
            stability,
            source_kind,
            eligible_for_injection,
            review_after,
            supersedes,
            invalidation_reason,
            body,
        )

    def _normalize_list_field(self, raw: str) -> list[str]:
        cleaned = normalize_storage_text(raw)
        if cleaned.startswith("[") and cleaned.endswith("]"):
            cleaned = cleaned[1:-1]
        return [normalize_storage_text(item) for item in cleaned.split(",") if normalize_storage_text(item)]

    def _normalize_memory_type(self, value: str) -> str:
        lowered = normalize_storage_text(value).lower()
        if lowered == "preference":
            return "user"
        if lowered == "workflow":
            return "project"
        if lowered in {"user", "feedback", "project", "reference"}:
            return lowered
        return "project"

    def _default_memory_class(self, memory_type: str) -> str:
        lowered = normalize_storage_text(memory_type).lower()
        if lowered in {"user", "preference"}:
            return "preference"
        return "work"

    def _normalize_memory_class(self, value: str, memory_type: str) -> str:
        lowered = normalize_storage_text(value).lower()
        if lowered in {"work", "preference"}:
            return lowered
        return self._default_memory_class(memory_type)

    def _rewrite_index(self, notes: list[MemoryNote]) -> None:
        lines = ["# Memory Index", ""]
        for note in notes:
            lines.append(
                f"- [{normalize_storage_text(note.title)}]({note.slug}.md) - {normalize_storage_text(note.summary)}"
            )
        final = "\n".join(lines).rstrip() + "\n"
        self.index_path.write_text(final, encoding="utf-8", newline="\n")

    def _load_loaded_note(self, path: Path) -> LoadedMemoryNote:
        raw = repair_mojibake(path.read_text(encoding="utf-8"))
        frontmatter, body = parse_frontmatter(raw)
        if frontmatter:
            return LoadedMemoryNote(
                filename=path.name,
                schema_version=repair_mojibake(frontmatter.get("schema_version", DEFAULT_DURABLE_SCHEMA_VERSION)),
                title=repair_mojibake(frontmatter.get("title", path.stem)),
                summary=repair_mojibake(frontmatter.get("summary", "")),
                canonical_statement=repair_mojibake(frontmatter.get("canonical_statement", frontmatter.get("summary", ""))),
                memory_type=frontmatter.get("type", "project"),
                memory_class=frontmatter.get(
                    "memory_class",
                    self._default_memory_class(frontmatter.get("type", "project")),
                ),
                retrieval_hints=self._normalize_list_field(frontmatter.get("retrieval_hints", "")),
                created_at=repair_mojibake(frontmatter.get("created_at", "")),
                updated_at=repair_mojibake(frontmatter.get("updated_at", "")),
                created_by=repair_mojibake(frontmatter.get("created_by", "")),
                source_session_id=repair_mojibake(frontmatter.get("source_session_id", "")),
                source_role=repair_mojibake(frontmatter.get("source_role", "user")),
                source_message_excerpt=repair_mojibake(frontmatter.get("source_message_excerpt", "")),
                confidence=repair_mojibake(frontmatter.get("confidence", "medium")),
                status=repair_mojibake(frontmatter.get("status", "active")),
                last_confirmed_at=repair_mojibake(frontmatter.get("last_confirmed_at", "")),
                scope=repair_mojibake(frontmatter.get("scope", "project")),
                stability=repair_mojibake(frontmatter.get("stability", "stable")),
                source_kind=repair_mojibake(frontmatter.get("source_kind", "")),
                eligible_for_injection=repair_mojibake(frontmatter.get("eligible_for_injection", "true")),
                review_after=repair_mojibake(frontmatter.get("review_after", "")),
                supersedes=repair_mojibake(frontmatter.get("supersedes", "")),
                invalidation_reason=repair_mojibake(frontmatter.get("invalidation_reason", "")),
                content=repair_mojibake(body.strip()),
            )

        (
            _schema_version,
            title,
            summary,
            canonical_statement,
            memory_type,
            memory_class,
            _tags,
            retrieval_hints,
            _created_at,
            _updated_at,
            _created_by,
            _source_session_id,
            _source_role,
            _source_message_excerpt,
            _confidence,
            _status,
            _last_confirmed_at,
            _scope,
            _stability,
            _source_kind,
            _eligible_for_injection,
            _review_after,
            _supersedes,
            _invalidation_reason,
            body_text,
        ) = self._repair_legacy_note(raw, path)
        return LoadedMemoryNote(
            filename=path.name,
            schema_version=_schema_version,
            title=title,
            summary=summary,
            canonical_statement=canonical_statement,
            memory_type=memory_type,
            memory_class=memory_class,
            retrieval_hints=retrieval_hints,
            created_at=_created_at,
            updated_at=_updated_at,
            created_by=_created_by,
            source_session_id=_source_session_id,
            source_role=_source_role,
            source_message_excerpt=_source_message_excerpt,
            confidence=_confidence,
            status=_status,
            last_confirmed_at=_last_confirmed_at,
            scope=_scope,
            stability=_stability,
            source_kind=_source_kind,
            eligible_for_injection=_eligible_for_injection,
            review_after=_review_after,
            supersedes=_supersedes,
            invalidation_reason=_invalidation_reason,
            content=body_text,
        )

    def _score_loaded_note(
        self,
        note: LoadedMemoryNote,
        query_terms: set[str],
        *,
        preferred_types: list[str],
        preferred_classes: list[str],
    ) -> float:
        title_terms = self._extract_terms(note.title)
        summary_terms = self._extract_terms(note.summary)
        canonical_terms = self._extract_terms(note.canonical_statement)
        filename_terms = self._extract_terms(note.filename)
        body_terms = self._extract_terms(note.content[:800])
        retrieval_hint_terms = {
            term
            for hint in note.retrieval_hints
            for term in self._extract_terms(hint)
        }

        score = 0.0
        score += 4.5 * len(query_terms & title_terms)
        score += 4.0 * len(query_terms & summary_terms)
        score += 4.2 * len(query_terms & canonical_terms)
        score += 3.0 * len(query_terms & retrieval_hint_terms)
        score += 2.0 * len(query_terms & filename_terms)
        score += 1.2 * len(query_terms & body_terms)

        lowered_query = repair_mojibake(" ".join(sorted(query_terms))).lower()
        if note.memory_type.lower() in preferred_types:
            score += 3.0
        if note.memory_class.lower() in preferred_classes:
            score += 2.5

        if note.memory_class == "preference" and any(
            marker in lowered_query for marker in ("喜欢", "偏好", "习惯", "默认", "风格", "要求")
        ):
            score += 2.0
        if note.memory_class == "work" and any(
            marker in lowered_query for marker in ("项目", "架构", "流程", "工作流", "重点", "约定", "规范")
        ):
            score += 2.0

        return score

    def _extract_terms(self, text: str) -> set[str]:
        normalized = repair_mojibake(text).lower()
        terms: set[str] = set()

        for token in re.findall(r"[a-z0-9_.+#-]{2,}", normalized):
            if token not in _STOP_TERMS:
                terms.add(token)

        for chunk in re.findall(r"[\u4e00-\u9fff]{2,12}", normalized):
            if chunk not in _STOP_TERMS:
                terms.add(chunk)
            max_window = min(4, len(chunk))
            for window in range(2, max_window + 1):
                for start in range(0, len(chunk) - window + 1):
                    piece = chunk[start : start + window]
                    if any(char in _STOP_CHARS for char in piece):
                        continue
                    if piece not in _STOP_TERMS:
                        terms.add(piece)

        return terms

    def _truncate_entrypoint(self, content: str, warn: bool = True) -> str:
        trimmed = content.strip()
        if not trimmed:
            return content
        lines = trimmed.splitlines()
        line_truncated = len(lines) > MAX_ENTRYPOINT_LINES
        if line_truncated:
            lines = lines[:MAX_ENTRYPOINT_LINES]
        truncated = "\n".join(lines)
        byte_truncated = len(truncated.encode("utf-8")) > MAX_ENTRYPOINT_BYTES
        if byte_truncated:
            encoded = truncated.encode("utf-8")[:MAX_ENTRYPOINT_BYTES]
            truncated = encoded.decode("utf-8", errors="ignore")
            if "\n" in truncated:
                truncated = truncated[: truncated.rfind("\n")]
        if warn and (line_truncated or byte_truncated):
            truncated += (
                "\n\n> WARNING: MEMORY.md was truncated. Keep index entries short "
                "and store detailed content in topic files.\n"
            )
        return truncated.rstrip() + "\n"

    def _is_runtime_visible(self, status: str) -> bool:
        normalized = normalize_storage_text(status).lower()
        return normalized not in {"archived", "deprecated", "inactive"}

    def _is_runtime_eligible(self, note: LoadedMemoryNote) -> bool:
        if not self._is_runtime_visible(note.status):
            return False
        if normalize_storage_text(note.eligible_for_injection).lower() in {"false", "no", "0"}:
            return False
        return not is_runtime_noise_note(
            source_role=note.source_role,
            created_by=note.created_by,
            title=note.title,
            summary=note.summary,
            canonical_statement=note.canonical_statement,
            source_message_excerpt=note.source_message_excerpt,
        )

    def _migrate_legacy_layout(self) -> None:
        legacy_files = sorted(
            path for path in self.root_dir.glob("*.md")
            if path.is_file()
        )
        for path in legacy_files:
            if path.name == "MEMORY.md":
                target = self.layout.index_path
            elif path.name == "SCHEMA.md":
                target = self.layout.schema_path
            else:
                target = self.layout.notes_dir / path.name
            if target == path:
                continue
            if target.exists():
                if repair_mojibake(target.read_text(encoding="utf-8")) == repair_mojibake(path.read_text(encoding="utf-8")):
                    path.unlink()
                continue
            path.replace(target)

    def _loaded_to_memory_note(self, loaded: LoadedMemoryNote) -> MemoryNote:
        return MemoryNote(
            slug=Path(loaded.filename).stem,
            schema_version=loaded.schema_version or DEFAULT_DURABLE_SCHEMA_VERSION,
            title=loaded.title,
            summary=loaded.summary or loaded.title,
            canonical_statement=loaded.canonical_statement or loaded.summary or loaded.title,
            body=loaded.content or loaded.summary or loaded.title,
            memory_type=loaded.memory_type,
            memory_class=loaded.memory_class,
            retrieval_hints=list(loaded.retrieval_hints),
            created_at=loaded.created_at or loaded.updated_at or MemoryNote(slug="", title="", summary="", body="").created_at,
            updated_at=loaded.updated_at or MemoryNote(slug="", title="", summary="", body="").updated_at,
            created_by=loaded.created_by or "migration",
            source_session_id=loaded.source_session_id,
            source_role=loaded.source_role or "user",
            source_message_excerpt=loaded.source_message_excerpt,
            confidence=loaded.confidence or "medium",
            status=loaded.status or "active",
            last_confirmed_at=loaded.last_confirmed_at,
            scope=loaded.scope or "project",
            stability=loaded.stability or "stable",
            source_kind=loaded.source_kind,
            eligible_for_injection=loaded.eligible_for_injection or "true",
            review_after=loaded.review_after,
            supersedes=loaded.supersedes,
            invalidation_reason=loaded.invalidation_reason,
        )

    def _apply_save_governance(self, note: MemoryNote) -> tuple[MemoryNote, list[MemoryNote]]:
        now = MemoryNote(slug="", title="", summary="", body="").updated_at
        incoming = note
        incoming.updated_at = now
        if not incoming.created_at:
            incoming.created_at = now
        incoming.eligible_for_injection = normalize_storage_text(incoming.eligible_for_injection) or "true"
        incoming.scope = normalize_storage_text(incoming.scope) or "project"
        incoming.stability = normalize_storage_text(incoming.stability) or "stable"

        staged_updates: list[MemoryNote] = []
        for loaded in self.list_notes():
            existing = self._loaded_to_memory_note(loaded)
            if self._notes_are_equivalent(existing, incoming):
                merged = self._merge_equivalent_note(existing, incoming, now)
                return merged, staged_updates
            if self._should_supersede(existing, incoming):
                deprecated = self._deprecate_note(existing, replacement_slug=incoming.slug, now=now)
                staged_updates.append(deprecated)
                if not incoming.supersedes:
                    incoming.supersedes = existing.slug
        return incoming, staged_updates

    def _notes_are_equivalent(self, existing: MemoryNote, incoming: MemoryNote) -> bool:
        if existing.memory_type != incoming.memory_type or existing.memory_class != incoming.memory_class:
            return False
        existing_canonical = normalize_storage_text(existing.canonical_statement).lower()
        incoming_canonical = normalize_storage_text(incoming.canonical_statement).lower()
        existing_title = normalize_storage_text(existing.title).lower()
        incoming_title = normalize_storage_text(incoming.title).lower()
        return bool(existing_canonical and existing_canonical == incoming_canonical) or (
            bool(existing_title) and existing_title == incoming_title and existing_canonical == incoming_canonical
        )

    def _should_supersede(self, existing: MemoryNote, incoming: MemoryNote) -> bool:
        if existing.memory_type != incoming.memory_type or existing.memory_class != incoming.memory_class:
            return False
        if normalize_storage_text(existing.status).lower() in {"deprecated", "inactive", "archived"}:
            return False
        existing_title = normalize_storage_text(existing.title).lower()
        incoming_title = normalize_storage_text(incoming.title).lower()
        existing_canonical = normalize_storage_text(existing.canonical_statement).lower()
        incoming_canonical = normalize_storage_text(incoming.canonical_statement).lower()
        return bool(existing_title and existing_title == incoming_title and existing_canonical and incoming_canonical and existing_canonical != incoming_canonical)

    def _merge_equivalent_note(self, existing: MemoryNote, incoming: MemoryNote, now: str) -> MemoryNote:
        merged = existing
        merged.summary = incoming.summary if len(normalize_storage_text(incoming.summary)) >= len(normalize_storage_text(existing.summary)) else existing.summary
        merged.body = incoming.body if len(normalize_storage_text(incoming.body)) >= len(normalize_storage_text(existing.body)) else existing.body
        merged.canonical_statement = incoming.canonical_statement or existing.canonical_statement
        merged.retrieval_hints = self._merge_unique(existing.retrieval_hints, incoming.retrieval_hints)
        merged.tags = self._merge_unique(existing.tags, incoming.tags)
        merged.updated_at = now
        merged.last_confirmed_at = now
        merged.source_message_excerpt = incoming.source_message_excerpt or existing.source_message_excerpt
        merged.created_by = incoming.created_by or existing.created_by
        merged.status = "active"
        merged.eligible_for_injection = "true"
        return merged

    def _deprecate_note(self, note: MemoryNote, *, replacement_slug: str, now: str) -> MemoryNote:
        note.status = "deprecated"
        note.eligible_for_injection = "false"
        note.invalidation_reason = f"superseded_by:{replacement_slug}"
        note.updated_at = now
        return note

    def _merge_unique(self, left: list[str], right: list[str]) -> list[str]:
        merged: list[str] = []
        for item in list(left) + list(right):
            normalized = normalize_storage_text(item)
            if normalized and normalized not in merged:
                merged.append(normalized)
        return merged


_STOP_TERMS = {
    "user",
    "memory",
    "project",
    "workflow",
    "reference",
    "preference",
    "work",
    "用户",
    "当前",
    "系统",
    "相关",
    "长期",
    "信息",
    "记忆",
    "什么",
    "哪个",
    "现在",
    "已经",
}

_STOP_CHARS = "的是了呢吗吧呀和与及在有就还都"
