from __future__ import annotations

from pathlib import Path
import re
from typing import NamedTuple

from .frontmatter import parse_frontmatter
from .models import DEFAULT_DURABLE_SCHEMA_VERSION, MemoryNote
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
    content: str


class MemoryManager:
    """File-based durable memory store inspired by the TS implementation."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root_dir / "MEMORY.md"
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
        return self.root_dir / f"{slug}.md"

    def list_note_paths(self) -> list[Path]:
        return sorted(
            [path for path in self.root_dir.glob("*.md") if path.name != "MEMORY.md"],
            key=lambda item: item.name.lower(),
        )

    def save_note(self, note: MemoryNote) -> Path:
        path = self.note_path(note.slug)
        path.write_text(note.to_markdown(), encoding="utf-8", newline="\n")
        self._upsert_index_line(note.title, path.name, note.summary)
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
        active_notes = [note for note in self.list_notes() if self._is_runtime_visible(note.status)]
        return active_notes[:limit]

    def build_manifest(self, limit: int = 50) -> str:
        manifest_lines: list[str] = []
        for note in self.load_relevant_notes(limit=limit):
            summary_source = note.summary or note.canonical_statement
            summary = f": {summary_source}" if summary_source else ""
            manifest_lines.append(
                f"- [{note.memory_class}/{note.memory_type}] {note.filename} [{note.confidence}/{note.status}]{summary}"
            )
        return "\n".join(manifest_lines)

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
        for path in sorted(self.root_dir.glob("*.md")):
            if path.name == "MEMORY.md" or path.name in exclude_filenames:
                continue
            note = self._load_loaded_note(path)
            if not self._is_runtime_visible(note.status):
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
        )
        path.write_text(note.to_markdown(), encoding="utf-8", newline="\n")
        return note

    def _repair_legacy_note(
        self,
        raw: str,
        path: Path,
    ) -> tuple[str, str, str, str, str, str, list[str], list[str], str, str, str, str, str, str, str, str, str, str]:
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
        body_lines: list[str] = []

        for line in lines:
            lowered = line.lower()
            if lowered.startswith("title:"):
                title = normalize_storage_text(line.split(":", 1)[1])
                continue
            if lowered.startswith("summary:"):
                summary = normalize_storage_text(line.split(":", 1)[1])
                continue
            if lowered.startswith("canonical_statement:"):
                canonical_statement = normalize_storage_text(line.split(":", 1)[1])
                continue
            if lowered.startswith("type:"):
                memory_type = normalize_storage_text(line.split(":", 1)[1]) or "project"
                memory_class = self._default_memory_class(memory_type)
                continue
            if lowered.startswith("memory_class:"):
                memory_class = normalize_storage_text(line.split(":", 1)[1]) or self._default_memory_class(memory_type)
                continue
            if lowered.startswith("tags:"):
                tags = self._normalize_list_field(line.split(":", 1)[1])
                continue
            if lowered.startswith("retrieval_hints:"):
                retrieval_hints = self._normalize_list_field(line.split(":", 1)[1])
                continue
            if lowered.startswith("updated_at:"):
                updated_at = normalize_storage_text(line.split(":", 1)[1])
                continue
            if lowered.startswith("created_at:"):
                created_at = normalize_storage_text(line.split(":", 1)[1])
                continue
            if lowered.startswith("created_by:"):
                created_by = normalize_storage_text(line.split(":", 1)[1]) or "legacy-repair"
                continue
            if lowered.startswith("source_session_id:"):
                source_session_id = normalize_storage_text(line.split(":", 1)[1])
                continue
            if lowered.startswith("source_role:"):
                source_role = normalize_storage_text(line.split(":", 1)[1]) or "user"
                continue
            if lowered.startswith("source_message_excerpt:"):
                source_message_excerpt = normalize_storage_text(line.split(":", 1)[1])
                continue
            if lowered.startswith("confidence:"):
                confidence = normalize_storage_text(line.split(":", 1)[1]) or "medium"
                continue
            if lowered.startswith("status:"):
                status = normalize_storage_text(line.split(":", 1)[1]) or "active"
                continue
            if lowered.startswith("last_confirmed_at:"):
                last_confirmed_at = normalize_storage_text(line.split(":", 1)[1])
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
            body,
        )

    def _normalize_list_field(self, raw: str) -> list[str]:
        cleaned = normalize_storage_text(raw)
        if cleaned.startswith("[") and cleaned.endswith("]"):
            cleaned = cleaned[1:-1]
        return [normalize_storage_text(item) for item in cleaned.split(",") if normalize_storage_text(item)]

    def _normalize_memory_type(self, value: str) -> str:
        lowered = normalize_storage_text(value).lower()
        if lowered in {"user", "preference", "project", "workflow", "reference"}:
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
