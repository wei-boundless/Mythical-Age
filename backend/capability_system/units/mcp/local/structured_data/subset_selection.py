from __future__ import annotations

from dataclasses import dataclass, field
import re

from .catalog import StructuredDataCatalog


_RESULT_BLOCK_RE = re.compile(
    r"^(?:前\s*\d+\s*(?:条记录|项)|结果（前\s*\d+\s*项）)[:：]?\s*$"
)


@dataclass(slots=True)
class StructuredSubsetSelection:
    labels: list[str] = field(default_factory=list)
    filter_column: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.labels or not self.filter_column


def extract_structured_subset_selection(text: str) -> StructuredSubsetSelection:
    lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").splitlines()]
    start_index = _find_result_block_start(lines)
    if start_index < 0:
        return StructuredSubsetSelection()

    header_line = ""
    data_lines: list[str] = []
    for raw in lines[start_index:]:
        stripped = raw.strip()
        if not stripped:
            continue
        if not header_line:
            header_line = stripped
            continue
        data_lines.append(stripped)

    if not header_line or not data_lines:
        return StructuredSubsetSelection()

    filter_column = _canonicalize_header_token(_first_header_token(header_line))
    if not filter_column:
        return StructuredSubsetSelection()

    labels: list[str] = []
    for raw in data_lines:
        label = _extract_first_value_token(raw)
        if not label:
            continue
        if label not in labels:
            labels.append(label)
    return StructuredSubsetSelection(labels=labels[:20], filter_column=filter_column)
def _find_result_block_start(lines: list[str]) -> int:
    for idx, line in enumerate(lines):
        if _RESULT_BLOCK_RE.match(str(line or "").strip()):
            return idx + 1
    return -1


def _first_header_token(line: str) -> str:
    parts = [part for part in re.split(r"\s{2,}|\t+", str(line or "").strip()) if part]
    if parts:
        return parts[0]
    tokens = str(line or "").strip().split()
    return tokens[0] if tokens else ""


def _extract_first_value_token(line: str) -> str:
    parts = [part for part in re.split(r"\s{2,}|\t+", str(line or "").strip()) if part]
    if parts:
        if parts[0].isdigit() and len(parts) >= 2:
            return str(parts[1]).strip()
        return str(parts[0]).strip()
    tokens = str(line or "").strip().split()
    if not tokens:
        return ""
    if tokens[0].isdigit() and len(tokens) >= 2:
        return str(tokens[1]).strip()
    return str(tokens[0]).strip()


def _canonicalize_header_token(token: str) -> str:
    normalized = str(token or "").strip()
    if not normalized:
        return ""
    lowered = normalized.lower()
    for canonical, aliases in StructuredDataCatalog.COLUMN_ALIASES.items():
        lowered_aliases = {str(alias).lower() for alias in aliases}
        if normalized in aliases or lowered in lowered_aliases:
            return canonical
    if normalized == "缺口":
        return "shortage_qty"
    return ""
