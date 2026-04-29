from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evidence.models import EvidenceArtifact


@dataclass(frozen=True, slots=True)
class MaterializedTable:
    dataset_path: str
    artifact: EvidenceArtifact
    row_count: int
    column_count: int


class TableMaterializer:
    def __init__(self, *, root_dir: Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.artifact_dir = self.root_dir / "output" / "evidence_artifacts" / "tables"

    def materialize(
        self,
        artifact: EvidenceArtifact,
        *,
        session_id: str,
    ) -> MaterializedTable | None:
        if artifact.artifact_type not in {"pdf_table", "table_object"}:
            return None
        rows = _extract_rows(artifact)
        if not _is_valid_table(rows):
            return None

        safe_session = _safe_token(session_id or "default")
        safe_artifact = _safe_token(artifact.artifact_id)
        target_dir = (self.artifact_dir / safe_session).resolve()
        if self.root_dir not in target_dir.parents and target_dir != self.root_dir:
            return None
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = (target_dir / f"{safe_artifact}.csv").resolve()
        if self.root_dir not in target_path.parents:
            return None

        with target_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)

        dataset_path = str(target_path.relative_to(self.root_dir)).replace("\\", "/")
        table_artifact_id = _stable_id("artifact:table_object", f"{artifact.artifact_id}:{dataset_path}")
        materialized = EvidenceArtifact(
            artifact_id=table_artifact_id,
            artifact_type="table_object",
            source_object_id=artifact.source_object_id,
            parent_artifact_id=artifact.artifact_id,
            content_ref=dataset_path,
            canonical_preview=_preview_rows(rows),
            visibility="debug_only",
            consumable_by=["structured_data"],
            metadata={
                "materialized_from": artifact.artifact_id,
                "row_count": len(rows) - 1,
                "column_count": len(rows[0]),
                "source_artifact_type": artifact.artifact_type,
                "confidence": 1.0,
            },
        )
        return MaterializedTable(
            dataset_path=dataset_path,
            artifact=materialized,
            row_count=len(rows) - 1,
            column_count=len(rows[0]),
        )


def _extract_rows(artifact: EvidenceArtifact) -> list[list[str]]:
    metadata = dict(artifact.metadata or {})
    for key in ("table_rows", "rows", "table"):
        rows = _rows_from_value(metadata.get(key), columns=metadata.get("columns") or metadata.get("headers"))
        if _is_valid_table(rows):
            return rows
    rows = _rows_from_preview(str(artifact.canonical_preview or ""))
    return rows if _is_valid_table(rows) else []


def _rows_from_value(value: Any, *, columns: Any = None) -> list[list[str]]:
    if not isinstance(value, list) or not value:
        return []
    if all(isinstance(item, dict) for item in value):
        headers = _string_list(columns)
        if not headers:
            headers = []
            for row in value:
                for key in row.keys():
                    label = str(key).strip()
                    if label and label not in headers:
                        headers.append(label)
        return [headers] + [[_cell(row.get(header)) for header in headers] for row in value] if headers else []
    if all(isinstance(item, (list, tuple)) for item in value):
        rows = [[_cell(cell) for cell in row] for row in value]
        headers = _string_list(columns)
        if headers and len(headers) == len(rows[0]):
            return [headers] + rows
        return rows
    return []


def _rows_from_preview(preview: str) -> list[list[str]]:
    text = str(preview or "").strip()
    if not text:
        return []
    markdown_rows = _parse_markdown_table(text)
    if _is_valid_table(markdown_rows):
        return markdown_rows
    return _parse_delimited_table(text)


def _parse_markdown_table(text: str) -> list[list[str]]:
    lines = [line.strip() for line in text.splitlines() if "|" in line]
    if len(lines) < 2:
        return []
    rows: list[list[str]] = []
    for line in lines:
        stripped = line.strip().strip("|")
        cells = [cell.strip() for cell in stripped.split("|")]
        if not cells:
            continue
        if all(re.fullmatch(r":?-{2,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        rows.append(cells)
    return _rectangularize(rows)


def _parse_delimited_table(text: str) -> list[list[str]]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    sample = "\n".join(lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        return []
    try:
        rows = [[cell.strip() for cell in row] for row in csv.reader(lines, dialect=dialect)]
    except csv.Error:
        return []
    return _rectangularize(rows)


def _rectangularize(rows: list[list[str]]) -> list[list[str]]:
    cleaned = [[_cell(cell) for cell in row] for row in rows if any(str(cell).strip() for cell in row)]
    if not cleaned:
        return []
    width = len(cleaned[0])
    if width < 2 or any(len(row) != width for row in cleaned):
        return []
    return cleaned


def _is_valid_table(rows: list[list[str]]) -> bool:
    if len(rows) < 2:
        return False
    width = len(rows[0])
    if width < 2:
        return False
    if any(len(row) != width for row in rows):
        return False
    return any(any(cell.strip() for cell in row) for row in rows[1:])


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _cell(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _preview_rows(rows: list[list[str]], *, max_rows: int = 4) -> str:
    return "\n".join(",".join(row) for row in rows[:max_rows])


def _safe_token(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip())
    if text:
        return text[:80]
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"
