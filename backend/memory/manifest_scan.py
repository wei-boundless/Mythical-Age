from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_MANIFEST_HEADERS = 200
HEADER_PREVIEW_LINES = 24


@dataclass(frozen=True, slots=True)
class MemoryHeader:
    note_id: str
    filename: str
    file_path: str
    memory_type: str
    memory_class: str
    title: str
    description: str
    status: str
    confidence: str
    updated_at: str
    retrieval_hints: list[str]
    eligible_for_injection: bool
    canonical_statement: str = ""
    summary: str = ""
    mtime_ms: float = 0.0

def scan_memory_headers(root_dir: Path, limit: int = MAX_MANIFEST_HEADERS) -> list[MemoryHeader]:
    notes_dir = root_dir / "notes"
    if not notes_dir.exists():
        return []

    headers: list[MemoryHeader] = []
    for path in notes_dir.rglob("*.md"):
        if path.name.upper() == "MEMORY.MD":
            continue
        header = load_memory_header(path)
        if header is not None:
            headers.append(header)

    headers.sort(key=lambda item: (item.updated_at, item.mtime_ms, item.filename), reverse=True)
    return headers[: max(1, limit)]


def load_memory_header(file_path: Path) -> MemoryHeader | None:
    try:
        raw = repair_mojibake(file_path.read_text(encoding="utf-8"))
    except OSError:
        return None

    frontmatter, body = parse_frontmatter(raw)
    stat = file_path.stat()
    filename = file_path.name
    note_id = normalize_storage_text(str(frontmatter.get("id", "") or "")) or file_path.stem
    title = normalize_storage_text(str(frontmatter.get("title", "") or "")) or file_path.stem
    summary = normalize_storage_text(str(frontmatter.get("summary", "") or ""))
    canonical_statement = normalize_storage_text(str(frontmatter.get("canonical_statement", "") or ""))
    description = summary or canonical_statement or _body_preview(body)
    retrieval_hints = _normalize_list_field(frontmatter.get("retrieval_hints", []))
    updated_at = normalize_storage_text(str(frontmatter.get("updated_at", "") or ""))
    if not updated_at:
        updated_at = f"{stat.st_mtime:.6f}"

    return MemoryHeader(
        note_id=note_id,
        filename=filename,
        file_path=str(file_path),
        memory_type=normalize_storage_text(str(frontmatter.get("type", "") or "")) or "project",
        memory_class=normalize_storage_text(str(frontmatter.get("memory_class", "") or "")) or "work",
        title=title,
        description=description,
        status=normalize_storage_text(str(frontmatter.get("status", "") or "")) or "active",
        confidence=normalize_storage_text(str(frontmatter.get("confidence", "") or "")) or "medium",
        updated_at=updated_at,
        retrieval_hints=retrieval_hints,
        eligible_for_injection=_coerce_bool(frontmatter.get("eligible_for_injection", "true")),
        canonical_statement=canonical_statement,
        summary=summary,
        mtime_ms=stat.st_mtime,
    )


def format_memory_manifest(headers: list[MemoryHeader]) -> str:
    lines: list[str] = []
    for header in headers:
        type_tag = f"[{header.memory_class}/{header.memory_type}]"
        status_tag = f"[{header.status}/{header.confidence}]"
        description = normalize_storage_text(header.description)
        hint_block = ""
        if header.retrieval_hints:
            hint_block = f" | hints: {', '.join(header.retrieval_hints[:4])}"
        lines.append(
            f"- {type_tag} {header.filename} {status_tag}: {description}{hint_block}"
        )
    return "\n".join(lines).strip()


def _normalize_list_field(value: object) -> list[str]:
    if isinstance(value, list):
        items = value
    else:
        raw = normalize_storage_text(str(value or ""))
        items = [part.strip() for part in raw.split(",")] if raw else []
    deduped: list[str] = []
    for item in items:
        normalized = normalize_storage_text(str(item or ""))
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped[:8]


def _body_preview(body: str) -> str:
    lines: list[str] = []
    for raw_line in normalize_storage_text(body).splitlines()[:HEADER_PREVIEW_LINES]:
        line = raw_line.strip(" -*#\t")
        if not line:
            continue
        if line.lower().startswith(("canonical:", "why:", "how to apply:", "evidence:")):
            line = line.split(":", 1)[-1].strip()
        if line:
            lines.append(line)
    return " ".join(lines)[:240].strip()


def _coerce_bool(value: object) -> bool:
    normalized = normalize_storage_text(str(value or "")).lower()
    if normalized in {"false", "0", "no"}:
        return False
    return True


def parse_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    if not markdown.startswith("---\n"):
        return {}, markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return {}, markdown
    raw = markdown[4:end]
    body = markdown[end + 5 :]
    data: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data, body


def repair_mojibake(text: str) -> str:
    return text or ""


def normalize_storage_text(text: str) -> str:
    return repair_mojibake(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
