from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from memory_layout import DurableMemoryLayout

from .frontmatter import parse_frontmatter
from .note_hygiene import is_runtime_noise_note
from .text_utils import repair_mojibake

STOP_TERMS = {
    "user",
    "memory",
    "project",
    "workflow",
    "reference",
    "\u7528\u6237",
    "\u5f53\u524d",
    "\u7cfb\u7edf",
    "\u76f8\u5173",
    "\u957f\u671f",
    "\u4fe1\u606f",
    "\u8bb0\u5fc6",
    "\u4ec0\u4e48",
    "\u54ea\u4e2a",
    "\u73b0\u5728",
    "\u5df2\u7ecf",
}

STOP_CHARS = "\u7684\u662f\u4e86\u5462\u5417\u5427\u5440\u548c\u4e0e\u53ca\u5728\u6709\u5c31\u8fd8\u90fd"


@dataclass(slots=True)
class ExactMemoryMatch:
    filename: str
    schema_version: str
    title: str
    summary: str
    canonical_statement: str
    memory_type: str
    memory_class: str
    tags: list[str]
    retrieval_hints: list[str]
    created_by: str
    source_message_excerpt: str
    confidence: str
    status: str
    body: str
    score: float


def find_exact_memory_matches(
    memory_root: Path,
    query: str,
    *,
    preferred_types: list[str] | None = None,
    limit: int = 3,
) -> list[ExactMemoryMatch]:
    query_terms = _extract_terms(query)
    if not query_terms:
        return []

    note_root = DurableMemoryLayout(memory_root).notes_dir
    matches: list[ExactMemoryMatch] = []
    for path in sorted(note_root.glob("*.md")):
        note = _load_note(path)
        if is_runtime_noise_note(
            source_role=str(note.get("source_role", "")),
            created_by=str(note.get("created_by", "")),
            title=str(note.get("title", "")),
            summary=str(note.get("summary", "")),
            canonical_statement=str(note.get("canonical_statement", "")),
            source_message_excerpt=str(note.get("source_message_excerpt", "")),
        ):
            continue
        score = _score_note(note, query_terms, preferred_types or [])
        if score <= 0:
            continue
        matches.append(
            ExactMemoryMatch(
                filename=path.name,
                schema_version=note["schema_version"],
                title=note["title"],
                summary=note["summary"],
                canonical_statement=note["canonical_statement"],
                memory_type=note["memory_type"],
                memory_class=note["memory_class"],
                tags=note["tags"],
                retrieval_hints=note["retrieval_hints"],
                created_by=note["created_by"],
                source_message_excerpt=note["source_message_excerpt"],
                confidence=note["confidence"],
                status=note["status"],
                body=note["body"],
                score=score,
            )
        )

    matches.sort(key=lambda item: item.score, reverse=True)
    return matches[:limit]


def _load_note(path: Path) -> dict[str, str | list[str]]:
    raw = repair_mojibake(path.read_text(encoding="utf-8"))
    frontmatter, body = parse_frontmatter(raw)
    if frontmatter:
        return {
            "filename": path.name,
            "schema_version": repair_mojibake(frontmatter.get("schema_version", "durable-memory.v2")),
            "title": repair_mojibake(frontmatter.get("title", path.stem)),
            "summary": repair_mojibake(frontmatter.get("summary", "")),
            "canonical_statement": repair_mojibake(frontmatter.get("canonical_statement", frontmatter.get("summary", ""))),
            "memory_type": frontmatter.get("type", "project"),
            "memory_class": frontmatter.get(
                "memory_class",
                _default_memory_class(frontmatter.get("type", "project")),
            ),
            "tags": _parse_tags(frontmatter.get("tags", "")),
            "retrieval_hints": _parse_tags(frontmatter.get("retrieval_hints", "")),
            "created_by": repair_mojibake(frontmatter.get("created_by", "")),
            "source_role": repair_mojibake(frontmatter.get("source_role", "user")),
            "source_message_excerpt": repair_mojibake(frontmatter.get("source_message_excerpt", "")),
            "confidence": repair_mojibake(frontmatter.get("confidence", "medium")),
            "status": repair_mojibake(frontmatter.get("status", "active")),
            "body": repair_mojibake(body.strip()),
        }

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    memory_type = "project"
    memory_class = _default_memory_class(memory_type)
    summary = ""
    title = path.stem.replace("-", " ")
    canonical_statement = ""
    retrieval_hints: list[str] = []
    confidence = "medium"
    status = "active"
    source_role = "user"
    source_message_excerpt = ""
    body_lines: list[str] = []
    in_metadata_block = False
    for line in lines:
        lowered = line.lower()
        metadata_line = line[2:].strip() if line.startswith("- ") else line
        metadata_lowered = metadata_line.lower()
        if line.startswith("# "):
            title = line[2:].strip() or title
            continue
        if lowered.startswith("## metadata"):
            in_metadata_block = True
            continue
        if lowered.startswith("## canonical memory"):
            in_metadata_block = False
            continue
        if metadata_lowered.startswith("type:"):
            memory_type = metadata_line.split(":", 1)[1].strip() or "project"
            memory_class = _default_memory_class(memory_type)
            continue
        if metadata_lowered.startswith("memory class:") or metadata_lowered.startswith("memory_class:"):
            memory_class = metadata_line.split(":", 1)[1].strip() or _default_memory_class(memory_type)
            continue
        if metadata_lowered.startswith("summary:"):
            summary = metadata_line.split(":", 1)[1].strip()
            continue
        if metadata_lowered.startswith("retrieval hints:") or metadata_lowered.startswith("retrieval_hints:"):
            retrieval_hints = _parse_tags(metadata_line.split(":", 1)[1].strip())
            continue
        if metadata_lowered.startswith("confidence:"):
            confidence = metadata_line.split(":", 1)[1].strip() or "medium"
            continue
        if metadata_lowered.startswith("status:"):
            status = metadata_line.split(":", 1)[1].strip() or "active"
            continue
        if metadata_lowered.startswith("source role:") or metadata_lowered.startswith("source_role:"):
            source_role = metadata_line.split(":", 1)[1].strip() or "user"
            continue
        if metadata_lowered.startswith("source message excerpt:") or metadata_lowered.startswith("source_message_excerpt:"):
            source_message_excerpt = metadata_line.split(":", 1)[1].strip()
            continue
        if in_metadata_block and line.startswith("- "):
            continue
        body_lines.append(line)

    return {
        "filename": path.name,
        "schema_version": "durable-memory.v2",
        "title": repair_mojibake(title),
        "summary": repair_mojibake(summary),
        "canonical_statement": repair_mojibake(canonical_statement or summary),
        "memory_type": memory_type,
        "memory_class": memory_class,
        "tags": [],
        "retrieval_hints": retrieval_hints,
        "created_by": "",
        "source_role": source_role,
        "source_message_excerpt": source_message_excerpt,
        "confidence": confidence,
        "status": status,
        "body": repair_mojibake("\n".join(body_lines).strip()),
    }


def _parse_tags(raw: str) -> list[str]:
    cleaned = raw.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    return [tag.strip() for tag in cleaned.split(",") if tag.strip()]


def _default_memory_class(memory_type: str) -> str:
    lowered = repair_mojibake(memory_type).strip().lower()
    if lowered in {"user", "preference"}:
        return "preference"
    return "work"


def _score_note(
    note: dict[str, str | list[str]],
    query_terms: set[str],
    preferred_types: list[str],
) -> float:
    if str(note.get("status", "active")).lower() in {"archived", "deprecated", "inactive"}:
        return 0.0

    title_terms = _extract_terms(str(note["title"]))
    summary_terms = _extract_terms(str(note["summary"]))
    canonical_terms = _extract_terms(str(note["canonical_statement"]))
    body_terms = _extract_terms(str(note["body"])[:600])
    tag_terms = {
        repair_mojibake(str(tag)).lower()
        for tag in note["tags"]
    } if isinstance(note["tags"], list) else set()
    retrieval_hint_terms = {
        term
        for hint in note["retrieval_hints"]
        for term in _extract_terms(str(hint))
    } if isinstance(note["retrieval_hints"], list) else set()
    filename_terms = _extract_terms(str(note["filename"]) if "filename" in note else str(note["title"]))

    score = 0.0
    score += 5.0 * len(query_terms & title_terms)
    score += 4.0 * len(query_terms & summary_terms)
    score += 4.5 * len(query_terms & canonical_terms)
    score += 3.0 * len(query_terms & tag_terms)
    score += 3.0 * len(query_terms & retrieval_hint_terms)
    score += 2.0 * len(query_terms & filename_terms)
    score += 1.5 * len(query_terms & body_terms)

    if preferred_types and str(note["memory_type"]) in preferred_types:
        score += 3.0

    return score


def _extract_terms(text: str) -> set[str]:
    normalized = repair_mojibake(text).lower()
    terms: set[str] = set()

    for token in re.findall(r"[a-z0-9_.+#-]{2,}", normalized):
        if token not in STOP_TERMS:
            terms.add(token)

    for chunk in re.findall(r"[\u4e00-\u9fff]{2,12}", normalized):
        if chunk not in STOP_TERMS:
            terms.add(chunk)
        max_window = min(4, len(chunk))
        for window in range(2, max_window + 1):
            for start in range(0, len(chunk) - window + 1):
                piece = chunk[start : start + window]
                if any(char in STOP_CHARS for char in piece):
                    continue
                if piece not in STOP_TERMS:
                    terms.add(piece)

    return terms
