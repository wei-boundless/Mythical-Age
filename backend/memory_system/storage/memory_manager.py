from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import NamedTuple

from memory_system.layout import DurableMemoryLayout

from .frontmatter import parse_frontmatter
from .models import DEFAULT_DURABLE_SCHEMA_VERSION, MemoryNote, TemporalFactEdge
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
        self.index_path = self.layout.index_path
        self.temporal_edges_path = self.layout.meta_dir / "temporal_fact_edges.jsonl"
        if not self.index_path.exists():
            self.index_path.write_text(
                "# Memory Index\n\n"
                "<!-- One line per memory: - [Title](file.md) - short hook -->\n",
                encoding="utf-8",
            )

    @staticmethod
    def slugify(text: str) -> str:
        normalized = normalize_storage_text(text).strip().lower()
        slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", normalized).strip("-")
        while "--" in slug:
            slug = slug.replace("--", "-")
        slug = slug[:96].strip("-")
        slug = slug or "memory-note"
        if slug == "memory":
            return "memory-note"
        return slug

    def note_path(self, slug: str) -> Path:
        normalized_slug = self.slugify(slug)
        return self.layout.notes_dir / f"{normalized_slug}.md"

    def list_note_paths(self) -> list[Path]:
        return sorted(
            list(self.layout.notes_dir.glob("*.md")),
            key=lambda item: item.name.lower(),
        )

    def save_note(self, note: MemoryNote) -> Path:
        note.slug = self.slugify(note.slug or note.title or note.canonical_statement)
        governed_note, notes_to_update, temporal_edges = self._apply_save_governance(note)
        for staged_note in notes_to_update:
            self._write_note(staged_note)
        path = self._write_note(governed_note)
        for edge in temporal_edges:
            self.record_temporal_fact_edge(edge)
        self.sync_index()
        return path

    def delete_note(self, slug: str) -> bool:
        path = self.note_path(slug)
        if not path.exists():
            return False
        path.unlink()
        self._remove_index_line(path.name)
        return True

    def note_exists(self, slug: str) -> bool:
        return self.note_path(slug).exists()

    def load_note_record(self, slug: str) -> LoadedMemoryNote | None:
        path = self.note_path(slug)
        if not path.exists():
            return None
        return self._load_loaded_note(path)

    def update_note(self, slug: str, *, patch: MemoryNote) -> Path:
        existing = self.load_note_record(slug)
        if existing is None:
            raise KeyError(f"Unknown durable memory note: {slug}")
        target_slug = self.slugify(slug)
        current = self._loaded_to_memory_note(existing)
        current.slug = target_slug
        before_markdown = current.to_markdown()
        now = MemoryNote(slug="", title="", summary="", body="").updated_at
        current.title = patch.title or current.title
        current.summary = patch.summary or current.summary
        current.canonical_statement = patch.canonical_statement or current.canonical_statement
        current.body = patch.body or current.body
        current.retrieval_hints = self._merge_unique(current.retrieval_hints, patch.retrieval_hints)
        current.tags = self._merge_unique(current.tags, patch.tags)
        current.source_message_excerpt = patch.source_message_excerpt or current.source_message_excerpt
        current.confidence = patch.confidence or current.confidence
        current.updated_at = now
        current.last_confirmed_at = now
        current.status = "active"
        current.eligible_for_injection = "true"
        path = self._write_note(current)
        self.sync_index()
        self.record_temporal_fact_edge(
            self.build_temporal_fact_edge(
                relation="refines",
                source_note_id=target_slug,
                target_note_id=target_slug,
                actor=patch.created_by or "memory_manager.update_note",
                reason=patch.source_kind or "durable_memory_update",
                source_evidence_ref=patch.source_message_excerpt,
                before_text=before_markdown,
                after_text=current.to_markdown(),
                metadata={
                    "operation": "update_note",
                    "patch_source_session_id": patch.source_session_id,
                    "patch_confidence": patch.confidence,
                },
            )
        )
        return path

    def deprecate_notes(
        self,
        slugs: list[str],
        *,
        replacement_slug: str,
        reason: str = "",
        actor: str = "memory_manager.deprecate_notes",
        source_evidence_ref: str = "",
        metadata: dict[str, object] | None = None,
    ) -> list[str]:
        deprecated: list[str] = []
        now = MemoryNote(slug="", title="", summary="", body="").updated_at
        for slug in slugs:
            existing = self.load_note_record(slug)
            if existing is None:
                raise KeyError(f"Unknown durable memory note: {slug}")
            note = self._loaded_to_memory_note(existing)
            note.status = "deprecated"
            note.eligible_for_injection = "false"
            note.invalidation_reason = reason or f"merged_into:{replacement_slug}"
            note.updated_at = now
            self._write_note(note)
            self.record_temporal_fact_edge(
                self.build_temporal_fact_edge(
                    relation="merged_into" if replacement_slug else "invalidates",
                    source_note_id=note.slug,
                    target_note_id=replacement_slug,
                    actor=actor,
                    reason=note.invalidation_reason,
                    source_evidence_ref=source_evidence_ref,
                    before_text=existing.content,
                    after_text=note.to_markdown(),
                    metadata={"operation": "deprecate_notes", **dict(metadata or {})},
                )
            )
            deprecated.append(note.slug)
        self.sync_index()
        return deprecated

    def build_temporal_fact_edge(
        self,
        *,
        relation: str,
        source_note_id: str,
        target_note_id: str = "",
        actor: str = "memory_manager",
        reason: str = "",
        source_evidence_ref: str = "",
        source_text: str = "",
        target_text: str = "",
        before_text: str = "",
        after_text: str = "",
        metadata: dict[str, object] | None = None,
    ) -> TemporalFactEdge:
        source = self.slugify(source_note_id)
        target = self.slugify(target_note_id) if target_note_id else ""
        now = MemoryNote(slug="", title="", summary="", body="").updated_at
        edge_seed = {
            "relation": relation,
            "source": source,
            "target": target,
            "created_at": now,
            "before": self._text_sha256(before_text),
            "after": self._text_sha256(after_text),
            "reason": reason,
        }
        edge_id = f"edge:{self._text_sha256(json.dumps(edge_seed, ensure_ascii=False, sort_keys=True))[:20]}"
        return TemporalFactEdge(
            edge_id=edge_id,
            relation=relation,  # type: ignore[arg-type]
            source_note_id=source,
            target_note_id=target,
            created_at=now,
            actor=actor or "memory_manager",
            reason=normalize_storage_text(reason),
            source_evidence_ref=normalize_storage_text(source_evidence_ref),
            source_note_sha256=self._text_sha256(source_text),
            target_note_sha256=self._text_sha256(target_text),
            before_sha256=self._text_sha256(before_text),
            after_sha256=self._text_sha256(after_text),
            metadata=dict(metadata or {}),
        )

    def record_temporal_fact_edge(self, edge: TemporalFactEdge) -> None:
        payload = edge.to_dict()
        self.temporal_edges_path.parent.mkdir(parents=True, exist_ok=True)
        with self.temporal_edges_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def list_temporal_fact_edges(self) -> list[TemporalFactEdge]:
        if not self.temporal_edges_path.exists():
            return []
        edges: list[TemporalFactEdge] = []
        for line in self.temporal_edges_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise ValueError("Temporal fact edge record must be a JSON object")
            edges.append(TemporalFactEdge(**payload))
        return edges

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

    def _normalize_list_field(self, raw: str) -> list[str]:
        cleaned = normalize_storage_text(raw)
        if cleaned.startswith("[") and cleaned.endswith("]"):
            cleaned = cleaned[1:-1]
        return [normalize_storage_text(item) for item in cleaned.split(",") if normalize_storage_text(item)]

    def _default_memory_class(self, memory_type: str) -> str:
        lowered = normalize_storage_text(memory_type).lower()
        if lowered in {"user", "preference"}:
            return "preference"
        return "work"

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

        raise ValueError(f"Durable memory note is missing required frontmatter: {path.name}")

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

    def _apply_save_governance(self, note: MemoryNote) -> tuple[MemoryNote, list[MemoryNote], list[TemporalFactEdge]]:
        now = MemoryNote(slug="", title="", summary="", body="").updated_at
        incoming = note
        incoming.updated_at = now
        if not incoming.created_at:
            incoming.created_at = now
        incoming.eligible_for_injection = normalize_storage_text(incoming.eligible_for_injection) or "true"
        incoming.scope = normalize_storage_text(incoming.scope) or "project"
        incoming.stability = normalize_storage_text(incoming.stability) or "stable"

        staged_updates: list[MemoryNote] = []
        temporal_edges: list[TemporalFactEdge] = []
        for loaded in self.list_notes():
            existing = self._loaded_to_memory_note(loaded)
            if self._notes_are_equivalent(existing, incoming):
                before = existing.to_markdown()
                merged = self._merge_equivalent_note(existing, incoming, now)
                if before != merged.to_markdown():
                    temporal_edges.append(
                        self.build_temporal_fact_edge(
                            relation="refines",
                            source_note_id=existing.slug,
                            target_note_id=merged.slug,
                            actor=incoming.created_by or "memory_manager.save_note",
                            reason="equivalent_note_merged",
                            source_evidence_ref=incoming.source_message_excerpt,
                            source_text=incoming.to_markdown(),
                            target_text=merged.to_markdown(),
                            before_text=before,
                            after_text=merged.to_markdown(),
                            metadata={"operation": "save_note", "governance": "merge_equivalent_note"},
                        )
                    )
                return merged, staged_updates, temporal_edges
            if self._should_supersede(existing, incoming):
                before = existing.to_markdown()
                deprecated = self._deprecate_note(existing, replacement_slug=incoming.slug, now=now)
                staged_updates.append(deprecated)
                if not incoming.supersedes:
                    incoming.supersedes = existing.slug
                temporal_edges.append(
                    self.build_temporal_fact_edge(
                        relation="supersedes",
                        source_note_id=incoming.slug,
                        target_note_id=existing.slug,
                        actor=incoming.created_by or "memory_manager.save_note",
                        reason=deprecated.invalidation_reason,
                        source_evidence_ref=incoming.source_message_excerpt,
                        source_text=incoming.to_markdown(),
                        target_text=existing.to_markdown(),
                        before_text=before,
                        after_text=deprecated.to_markdown(),
                        metadata={"operation": "save_note", "governance": "should_supersede"},
                    )
                )
        return incoming, staged_updates, temporal_edges

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

    def _text_sha256(self, text: str) -> str:
        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return ""
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
