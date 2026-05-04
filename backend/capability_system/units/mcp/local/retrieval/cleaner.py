from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True)
class CleaningResult:
    text: str
    removed_lines: int
    original_lines: int


class ParsedContentCleaner:
    """Lightweight cleaner for OCR-heavy and document-derived text."""

    def clean_text(
        self,
        text: str,
        *,
        modality: str = "text",
        section: str | None = None,
    ) -> CleaningResult:
        normalized = self._normalize_whitespace(text)
        original_lines = self._split_lines(normalized)
        if not original_lines:
            return CleaningResult(text="", removed_lines=0, original_lines=0)

        repeated = self._detect_repeated_noise(original_lines)
        cleaned_lines: list[str] = []
        seen: set[str] = set()

        for raw_line in original_lines:
            line = self._normalize_line(raw_line)
            if not line:
                continue
            if self._is_noise_line(line, repeated=repeated, modality=modality):
                continue
            dedupe_key = self._dedupe_key(line, modality=modality, section=section)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            cleaned_lines.append(line)

        cleaned_text = self._join_lines(cleaned_lines, modality=modality)
        removed_lines = max(0, len(original_lines) - len(cleaned_lines))
        return CleaningResult(
            text=cleaned_text,
            removed_lines=removed_lines,
            original_lines=len(original_lines),
        )

    def clean_table_rows(self, rows: list[list[str]]) -> list[list[str]]:
        cleaned_rows: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()
        for row in rows:
            normalized = [self._normalize_cell(cell) for cell in row]
            if not any(normalized):
                continue
            row_key = tuple(normalized)
            if row_key in seen:
                continue
            seen.add(row_key)
            cleaned_rows.append(normalized)

        if not cleaned_rows:
            return []

        max_cols = max(len(row) for row in cleaned_rows)
        keep_indices: list[int] = []
        for idx in range(max_cols):
            column_values = []
            for row in cleaned_rows:
                value = row[idx] if idx < len(row) else ""
                column_values.append(value)
            if any(value for value in column_values):
                keep_indices.append(idx)

        trimmed_rows: list[list[str]] = []
        for row in cleaned_rows:
            padded = row + [""] * (max_cols - len(row))
            trimmed_rows.append([padded[idx] for idx in keep_indices])
        return trimmed_rows

    def _normalize_whitespace(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\u00a0", " ").replace("\t", " ")
        text = re.sub(r"[ ]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _split_lines(self, text: str) -> list[str]:
        return [line for line in (part.strip() for part in text.splitlines()) if line]

    def _normalize_line(self, line: str) -> str:
        line = re.sub(r"\s+", " ", line).strip()
        line = re.sub(r"[|]{2,}", "|", line)
        return line

    def _normalize_cell(self, cell: str) -> str:
        cell = str(cell or "").replace("\u00a0", " ").strip()
        cell = re.sub(r"\s+", " ", cell)
        return cell

    def _detect_repeated_noise(self, lines: Iterable[str]) -> set[str]:
        counter = Counter(
            self._noise_key(line)
            for line in lines
            if len(line.strip()) <= 80 and not self._looks_like_table_row(line)
        )
        return {key for key, count in counter.items() if key and count >= 3}

    def _noise_key(self, line: str) -> str:
        lowered = line.lower().strip()
        lowered = re.sub(r"\bpage\s+\d+\b", "page", lowered)
        lowered = re.sub(r"\d+", "#", lowered)
        return lowered

    def _is_noise_line(self, line: str, *, repeated: set[str], modality: str) -> bool:
        lowered = line.lower()
        if self._noise_key(line) in repeated:
            return True
        if re.fullmatch(r"page\s*\d+(\s*of\s*\d+)?", lowered):
            return True
        if re.fullmatch(r"\d+", line):
            return True
        if len(line) <= 2 and modality != "table":
            return True
        if line.count("_") >= 5 or line.count("-") >= 8:
            return True
        if modality != "table" and self._looks_like_table_rule(line):
            return True
        return False

    def _dedupe_key(self, line: str, *, modality: str, section: str | None) -> str:
        base = self._noise_key(line)
        if modality == "table":
            return f"table::{section or ''}::{base}"
        return base

    def _join_lines(self, lines: list[str], *, modality: str) -> str:
        if not lines:
            return ""
        if modality == "table":
            return "\n".join(lines).strip()
        paragraphs: list[str] = []
        buffer: list[str] = []
        for line in lines:
            if self._is_heading_like(line):
                if buffer:
                    paragraphs.append(" ".join(buffer).strip())
                    buffer = []
                paragraphs.append(line)
                continue
            buffer.append(line)
            if self._ends_sentence(line):
                paragraphs.append(" ".join(buffer).strip())
                buffer = []
        if buffer:
            paragraphs.append(" ".join(buffer).strip())
        return "\n\n".join(part for part in paragraphs if part).strip()

    def _is_heading_like(self, line: str) -> bool:
        if len(line) > 100:
            return False
        if line.startswith("#"):
            return True
        words = line.split()
        if 0 < len(words) <= 10 and line == line.upper():
            return True
        return False

    def _ends_sentence(self, line: str) -> bool:
        return line.endswith(
            (
                ".",
                "!",
                "?",
                "\u3002",
                "\uff01",
                "\uff1f",
                ":",
                "\uff1a",
            )
        )

    def _looks_like_table_row(self, line: str) -> bool:
        return "|" in line or "\t" in line

    def _looks_like_table_rule(self, line: str) -> bool:
        compact = line.replace(" ", "")
        return bool(re.fullmatch(r"[-|:]+", compact))
