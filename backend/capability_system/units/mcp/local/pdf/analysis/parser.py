from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pdf_runtime import suppress_pypdf_warnings

from .mineru_client import MinerUApiClient, MinerUBlock, MinerUParseResult, build_default_mineru_client


@dataclass(slots=True)
class PdfSegment:
    text: str
    page: int | None = None
    section: str | None = None
    modality: str = "text"
    element_type: str = "body_text"
    answer_eligible: bool = True
    excluded_from_summary: bool = False
    diagnostic_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class PdfTextParser:
    def __init__(
        self,
        root_dir: Path | None = None,
        *,
        mineru_client: MinerUApiClient | None = None,
    ) -> None:
        self.root_dir = root_dir
        self._mineru_client = mineru_client or build_default_mineru_client()
        self._remote_cache: dict[tuple[str, int, int], MinerUParseResult | None] = {}

    def available(self) -> bool:
        return self._mineru_client.available() or self._local_pdf_available()

    def extract_pages(self, file_path: Path) -> list[tuple[int, str]]:
        remote = self._load_remote_result(file_path)
        if remote is not None and remote.pages:
            return remote.pages
        return self._extract_pages_locally(file_path)

    def extract_segments(self, file_path: Path) -> list[PdfSegment]:
        remote = self._load_remote_result(file_path)
        if remote is not None and remote.blocks:
            segments = [self._segment_from_remote_block(block) for block in remote.blocks]
            segments.extend(self._extract_table_segments_with_pdfplumber(file_path))
            return segments
        local_segments = self._extract_segments_with_pdfplumber(file_path)
        if local_segments:
            return local_segments
        pages = remote.pages if remote is not None and remote.pages else self._extract_pages_locally(file_path)
        segments: list[PdfSegment] = []
        for page, text in pages:
            if not text.strip():
                continue
            classification = self._classify_segment(
                text=text,
                kind="text",
                section=None,
                modality="text",
            )
            segments.append(
                PdfSegment(
                    text=text,
                    page=page,
                    modality="text",
                    element_type=classification["element_type"],
                    answer_eligible=bool(classification["answer_eligible"]),
                    excluded_from_summary=bool(classification["excluded_from_summary"]),
                    diagnostic_only=bool(classification["diagnostic_only"]),
                    metadata={"parser": "local_pdf", **classification["metadata"]},
                )
            )
        return segments

    def _extract_segments_with_pdfplumber(self, file_path: Path) -> list[PdfSegment]:
        try:
            import pdfplumber  # type: ignore
        except Exception:
            return []

        segments: list[PdfSegment] = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    text = (page.extract_text() or "").strip()
                    if text:
                        classification = self._classify_segment(
                            text=text,
                            kind="text",
                            section=None,
                            modality="text",
                        )
                        segments.append(
                            PdfSegment(
                                text=self._normalize_page_text(text),
                                page=page_number,
                                modality="text",
                                element_type=classification["element_type"],
                                answer_eligible=bool(classification["answer_eligible"]),
                                excluded_from_summary=bool(classification["excluded_from_summary"]),
                                diagnostic_only=bool(classification["diagnostic_only"]),
                                metadata={"parser": "pdfplumber_text", **classification["metadata"]},
                            )
                        )
                    for table_index, table in enumerate(page.extract_tables() or [], start=1):
                        table_text = self._table_to_text(table)
                        if not table_text:
                            continue
                        classification = self._classify_segment(
                            text=table_text,
                            kind="table",
                            section=None,
                            modality="table",
                        )
                        segments.append(
                            PdfSegment(
                                text=table_text,
                                page=page_number,
                                modality="table",
                                element_type=classification["element_type"],
                                answer_eligible=bool(classification["answer_eligible"]),
                                excluded_from_summary=False,
                                diagnostic_only=bool(classification["diagnostic_only"]),
                                metadata={
                                    "parser": "pdfplumber_table",
                                    "table_index": table_index,
                                    **classification["metadata"],
                                },
                            )
                        )
        except Exception:
            return []
        return segments

    def _extract_table_segments_with_pdfplumber(self, file_path: Path) -> list[PdfSegment]:
        return [
            segment
            for segment in self._extract_segments_with_pdfplumber(file_path)
            if segment.element_type == "table_text"
        ]

    def _table_to_text(self, table: list[list[object | None]]) -> str:
        rows: list[str] = []
        for raw_row in table:
            if not raw_row:
                continue
            cells = [self._normalize_table_cell(cell) for cell in raw_row]
            if not any(cells):
                continue
            rows.append(" ; ".join(cells))
        return "\n".join(rows).strip()

    def _normalize_table_cell(self, value: object | None) -> str:
        if value is None:
            return ""
        return re.sub(r"\s+", " ", str(value)).strip()

    def document_total_pages(self, file_path: Path) -> int:
        remote = self._load_remote_result(file_path)
        if remote is not None:
            metadata = dict(remote.metadata or {})
            for key in ("total_pages", "page_count", "document_total_pages"):
                value = metadata.get(key)
                if isinstance(value, int) and value > 0:
                    return value
            remote_max_page = max(
                [
                    *[int(page) for page, _text in list(remote.pages or []) if int(page) > 0],
                    *[int(block.page) for block in list(remote.blocks or []) if int(block.page or 0) > 0],
                ],
                default=0,
            )
            if remote_max_page > 0:
                return remote_max_page
        total_pages = self._count_pages_with_pdfplumber(file_path)
        if total_pages > 0:
            return total_pages
        return self._count_pages_with_pypdf(file_path)

    def looks_unusable_text(self, text: str) -> bool:
        cleaned = re.sub(r"\s+", "", text or "")
        if len(cleaned) < 20:
            return True
        alnum_ratio = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", cleaned)) / max(len(cleaned), 1)
        if alnum_ratio < 0.35:
            return True
        replacement_ratio = len(re.findall(r"[�□�]", cleaned)) / max(len(cleaned), 1)
        if replacement_ratio > 0.03:
            return True
        rare_cjk_ratio = len(re.findall(r"[\u3400-\u4dbf]", cleaned)) / max(len(cleaned), 1)
        if rare_cjk_ratio > 0.2:
            return True
        odd_letter_ratio = len(re.findall(r"[\u3400-\u4dbf\uf900-\ufaff]", cleaned)) / max(len(cleaned), 1)
        if odd_letter_ratio > 0.08:
            return True
        return False

    def _segment_from_remote_block(self, block: MinerUBlock) -> PdfSegment:
        kind = (block.kind or "text").lower()
        modality = "table" if "table" in kind else "image" if any(token in kind for token in ("figure", "image")) else "text"
        classification = self._classify_segment(
            text=block.text,
            kind=kind,
            section=block.section,
            modality=modality,
        )
        return PdfSegment(
            text=block.text,
            page=block.page,
            section=block.section,
            modality=modality,
            element_type=classification["element_type"],
            answer_eligible=bool(classification["answer_eligible"]),
            excluded_from_summary=bool(classification["excluded_from_summary"]),
            diagnostic_only=bool(classification["diagnostic_only"]),
            metadata={**dict(block.metadata), **classification["metadata"]},
        )

    def _classify_segment(
        self,
        *,
        text: str,
        kind: str,
        section: str | None,
        modality: str,
    ) -> dict[str, Any]:
        normalized = self._normalize_page_text(text)
        lowered = normalized.lower()
        flags: list[str] = []
        element_type = "body_text"
        answer_eligible = True
        excluded_from_summary = False
        diagnostic_only = False

        if self.looks_unusable_text(normalized):
            flags.append("unusable_text")
            element_type = "diagnostic_only"
            answer_eligible = False
            excluded_from_summary = True
            diagnostic_only = True
        elif modality == "table":
            element_type = "table_text"
            excluded_from_summary = True
        elif modality == "image":
            element_type = "figure_caption"
            excluded_from_summary = True
        elif self._looks_reference_text(lowered) or self._looks_reference_heavy_text(normalized):
            flags.append("reference_page")
            element_type = "references"
            answer_eligible = False
            excluded_from_summary = True
        elif self._looks_toc_text(normalized, lowered):
            flags.append("toc_page")
            element_type = "toc_index"
            answer_eligible = False
            excluded_from_summary = True
        elif self._looks_copyright_text(lowered):
            flags.append("copyright_page")
            element_type = "cover_copyright"
            answer_eligible = False
            excluded_from_summary = True
        elif self._looks_header_footer_text(normalized):
            flags.append("header_footer")
            element_type = "header_footer"
            answer_eligible = False
            excluded_from_summary = True
        elif self._looks_heading_text(normalized, section):
            element_type = "section_heading"

        return {
            "element_type": element_type,
            "answer_eligible": answer_eligible,
            "excluded_from_summary": excluded_from_summary,
            "diagnostic_only": diagnostic_only,
            "metadata": {
                "quality_flags": flags,
            },
        }

    def _looks_reference_text(self, lowered: str) -> bool:
        return any(token in lowered for token in ("参考文献", "references", "bibliography"))

    def _looks_reference_heavy_text(self, text: str) -> bool:
        urls = len(re.findall(r"https?://|www\.", text, flags=re.IGNORECASE))
        years = len(re.findall(r"\b(?:19|20)\d{2}\b", text))
        numbered_entries = len(
            re.findall(r"(?:^|\s)(?:\[?\d{1,3}\]?\.|\d{1,3}\.\s+[A-Z])", text, flags=re.MULTILINE)
        )
        return urls >= 2 and years >= 2 and numbered_entries >= 2

    def _looks_toc_text(self, normalized: str, lowered: str) -> bool:
        return ("目录" in normalized or "contents" in lowered) and bool(re.search(r"(?:\.{4,}|…{2,}|·{4,})", normalized))

    def _looks_copyright_text(self, lowered: str) -> bool:
        return any(token in lowered for token in ("copyright", "all rights reserved", "免责声明", "版权所有"))

    def _looks_header_footer_text(self, normalized: str) -> bool:
        compact = re.sub(r"\s+", " ", normalized).strip()
        if not compact:
            return False
        if len(compact) <= 16 and bool(re.fullmatch(r"(?:page\s*)?\d+(?:\s*/\s*\d+)?", compact, flags=re.IGNORECASE)):
            return True
        return False

    def _looks_heading_text(self, normalized: str, section: str | None) -> bool:
        if section and normalized.strip() == str(section).strip():
            return True
        first_line = normalized.splitlines()[0].strip() if normalized.strip() else ""
        if not first_line:
            return False
        return bool(
            re.match(
                r"^(?:第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节)|[0-9]+(?:\.[0-9]+){0,3}\s+\S+)",
                first_line,
                flags=re.IGNORECASE,
            )
        )

    def _load_remote_result(self, file_path: Path) -> MinerUParseResult | None:
        if not self._mineru_client.available():
            return None
        try:
            stat = file_path.stat()
        except OSError:
            return None

        cache_key = (str(file_path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))
        if cache_key in self._remote_cache:
            return self._remote_cache[cache_key]

        try:
            result = self._mineru_client.parse_pdf(file_path)
        except Exception:
            result = None
        self._remote_cache[cache_key] = result
        return result

    def _extract_pages_locally(self, file_path: Path) -> list[tuple[int, str]]:
        pages = self._extract_pages_with_pdfplumber(file_path)
        if pages:
            return pages
        return self._extract_pages_with_pypdf(file_path)

    def _extract_pages_with_pdfplumber(self, file_path: Path) -> list[tuple[int, str]]:
        try:
            import pdfplumber  # type: ignore
        except Exception:
            return []

        pages: list[tuple[int, str]] = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    text = (page.extract_text() or "").strip()
                    if not text:
                        continue
                    pages.append((page_number, self._normalize_page_text(text)))
        except Exception:
            return []
        return pages

    def _count_pages_with_pdfplumber(self, file_path: Path) -> int:
        try:
            import pdfplumber  # type: ignore
        except Exception:
            return 0

        try:
            with pdfplumber.open(file_path) as pdf:
                return len(pdf.pages)
        except Exception:
            return 0

    def _extract_pages_with_pypdf(self, file_path: Path) -> list[tuple[int, str]]:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            return []

        try:
            with suppress_pypdf_warnings():
                reader = PdfReader(str(file_path))
                pages_iterable = list(reader.pages)
        except Exception:
            return []

        pages: list[tuple[int, str]] = []
        for page_number, page in enumerate(pages_iterable, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            pages.append((page_number, self._normalize_page_text(text)))
        return pages

    def _count_pages_with_pypdf(self, file_path: Path) -> int:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            return 0

        try:
            with suppress_pypdf_warnings():
                reader = PdfReader(str(file_path))
                return len(reader.pages)
        except Exception:
            return 0

    def _normalize_page_text(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cleaned = "\n".join(lines)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _local_pdf_available(self) -> bool:
        try:
            import pdfplumber  # type: ignore  # noqa: F401
            return True
        except Exception:
            pass
        try:
            import pypdf  # type: ignore  # noqa: F401
            return True
        except Exception:
            return False
