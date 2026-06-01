from __future__ import annotations

import re
import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pdf_runtime import suppress_pypdf_warnings
from project_layout import ProjectLayout

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


@dataclass(slots=True)
class PdfPageSnapshot:
    page_number: int
    raw_text: str = ""
    text_block_count: int = 0
    table_block_count: int = 0
    image_block_count: int = 0
    diagnostic_block_count: int = 0
    has_text: bool = False
    has_usable_text: bool = False
    likely_page_state: str = ""
    state_confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class PdfTextParser:
    def __init__(
        self,
        root_dir: Path | None = None,
        *,
        mineru_client: MinerUApiClient | None = None,
        ocr_reader: Callable[[Path, int], str] | None = None,
        enable_ocr_fallback: bool = True,
        ocr_render_scale: float = 2.2,
    ) -> None:
        self.root_dir = root_dir
        self._mineru_client = mineru_client or build_default_mineru_client()
        self._remote_cache: dict[tuple[str, int, int], MinerUParseResult | None] = {}
        self._document_cache: dict[tuple[str, int, int], tuple[list[tuple[int, str]], list[PdfSegment], int]] = {}
        self._ocr_reader = ocr_reader
        self._ocr_engine: object | None = None
        self.enable_ocr_fallback = enable_ocr_fallback
        self.ocr_render_scale = ocr_render_scale

    def available(self) -> bool:
        return self._mineru_client.available() or self._local_pdf_available() or self._ocr_available()

    def extract_pages(self, file_path: Path) -> list[tuple[int, str]]:
        pages, _segments, _total_pages = self._extract_document_content(file_path)
        return list(pages)

    def extract_segments(self, file_path: Path) -> list[PdfSegment]:
        _pages, segments, _total_pages = self._extract_document_content(file_path)
        return list(segments)

    def _extract_segments_without_ocr(self, file_path: Path, remote: MinerUParseResult | None) -> list[PdfSegment]:
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

    def extract_page_snapshots(self, file_path: Path) -> list[PdfPageSnapshot]:
        pages_list, segments, total_pages = self._extract_document_content(file_path)
        pages = dict(pages_list)
        snapshots: list[PdfPageSnapshot] = []
        for page_number in range(1, max(total_pages, 0) + 1):
            page_segments = [segment for segment in segments if int(segment.page or 0) == page_number]
            raw_text = str(pages.get(page_number, "") or "")
            text_block_count = sum(1 for segment in page_segments if segment.modality == "text")
            table_block_count = sum(1 for segment in page_segments if segment.modality == "table")
            image_block_count = sum(1 for segment in page_segments if segment.modality == "image")
            diagnostic_block_count = sum(1 for segment in page_segments if segment.diagnostic_only)
            has_text = bool(self._normalize_page_text(raw_text))
            has_usable_text = any(
                not segment.diagnostic_only
                and segment.element_type in {"body_text", "section_heading", "table_text"}
                and self._normalize_page_text(segment.text)
                for segment in page_segments
            )
            likely_page_state, state_confidence = self._infer_page_state(
                raw_text=raw_text,
                segments=page_segments,
                has_text=has_text,
                has_usable_text=has_usable_text,
            )
            snapshots.append(
                PdfPageSnapshot(
                    page_number=page_number,
                    raw_text=raw_text,
                    text_block_count=text_block_count,
                    table_block_count=table_block_count,
                    image_block_count=image_block_count,
                    diagnostic_block_count=diagnostic_block_count,
                    has_text=has_text,
                    has_usable_text=has_usable_text,
                    likely_page_state=likely_page_state,
                    state_confidence=state_confidence,
                    metadata={
                        "segment_count": len(page_segments),
                    },
                )
            )
        return snapshots

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
        _pages, _segments, total_pages = self._extract_document_content(file_path)
        return total_pages

    def _document_total_pages_without_ocr(
        self,
        file_path: Path,
        *,
        remote: MinerUParseResult | None,
        pages: list[tuple[int, str]],
        segments: list[PdfSegment],
    ) -> int:
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

    def _extract_document_content(self, file_path: Path) -> tuple[list[tuple[int, str]], list[PdfSegment], int]:
        cache_key = self._file_cache_key(file_path)
        if cache_key in self._document_cache:
            return self._document_cache[cache_key]

        local_pages = self._extract_pages_locally(file_path)
        local_segments = self._extract_segments_with_pdfplumber(file_path)
        remote: MinerUParseResult | None = None

        if local_pages or local_segments:
            pages = list(local_pages)
            segments = self._extract_segments_without_ocr(file_path, None)
        else:
            remote = self._load_remote_result(file_path)
            pages = list(remote.pages) if remote is not None and remote.pages else []
            segments = self._extract_segments_without_ocr(file_path, remote)
            if not pages and not segments:
                pages = list(local_pages)
                segments = list(local_segments)

        total_pages = self._document_total_pages_without_ocr(
            file_path,
            remote=remote,
            pages=pages,
            segments=segments,
        )
        if total_pages <= 0:
            total_pages = max(
                [
                    *[int(page_number) for page_number, _text in pages if int(page_number) > 0],
                    *[int(segment.page or 0) for segment in segments if int(segment.page or 0) > 0],
                ],
                default=0,
            )

        if self.enable_ocr_fallback:
            pages, segments = self._merge_ocr_fallback_pages(
                file_path=file_path,
                pages=pages,
                segments=segments,
                total_pages=total_pages,
            )

        result = (pages, segments, total_pages)
        self._document_cache[cache_key] = result
        return result

    def _merge_ocr_fallback_pages(
        self,
        *,
        file_path: Path,
        pages: list[tuple[int, str]],
        segments: list[PdfSegment],
        total_pages: int,
    ) -> tuple[list[tuple[int, str]], list[PdfSegment]]:
        if total_pages <= 0 or not self._ocr_available():
            return pages, segments

        page_text = {int(page_number): str(text or "") for page_number, text in pages if int(page_number) > 0}
        segments_by_page: dict[int, list[PdfSegment]] = {}
        for segment in segments:
            page_number = int(segment.page or 0)
            if page_number <= 0:
                continue
            segments_by_page.setdefault(page_number, []).append(segment)

        candidate_pages = [
            page_number
            for page_number in range(1, total_pages + 1)
            if self._page_needs_ocr_fallback(
                raw_text=page_text.get(page_number, ""),
                segments=segments_by_page.get(page_number, []),
            )
        ]
        if not candidate_pages:
            return pages, segments

        ocr_pages: dict[int, str] = {}
        for page_number in candidate_pages:
            text = self._read_ocr_page_text(file_path, page_number)
            if text and not self.looks_unusable_text(text):
                ocr_pages[page_number] = text
        if not ocr_pages:
            return pages, segments

        merged_pages: dict[int, str] = {
            int(page_number): str(text or "") for page_number, text in pages if int(page_number) > 0
        }
        merged_pages.update(ocr_pages)
        kept_segments = [segment for segment in segments if int(segment.page or 0) not in ocr_pages]
        for page_number in sorted(ocr_pages):
            text = ocr_pages[page_number]
            classification = self._classify_segment(
                text=text,
                kind="ocr_text",
                section=None,
                modality="text",
            )
            kept_segments.append(
                PdfSegment(
                    text=text,
                    page=page_number,
                    modality="text",
                    element_type=classification["element_type"],
                    answer_eligible=bool(classification["answer_eligible"]),
                    excluded_from_summary=bool(classification["excluded_from_summary"]),
                    diagnostic_only=bool(classification["diagnostic_only"]),
                    metadata={
                        "parser": "rapidocr_page",
                        "ocr": True,
                        "ocr_fallback": True,
                        **classification["metadata"],
                    },
                )
            )
        kept_segments.sort(key=lambda item: (int(item.page or 0), str(item.metadata.get("parser", ""))))
        return sorted(merged_pages.items()), kept_segments

    def _page_needs_ocr_fallback(self, *, raw_text: str, segments: list[PdfSegment]) -> bool:
        normalized = self._normalize_page_text(raw_text)
        if normalized and self.looks_unusable_text(normalized):
            return True
        usable_segments = [
            segment
            for segment in segments
            if not segment.diagnostic_only
            and segment.element_type in {"body_text", "section_heading", "table_text"}
            and self._normalize_page_text(segment.text)
        ]
        if usable_segments:
            return False
        if not normalized:
            return True
        return self.looks_unusable_text(normalized)

    def _read_ocr_page_text(self, file_path: Path, page_number: int) -> str:
        cached = self._read_persisted_ocr_page(file_path=file_path, page_number=page_number)
        if cached is not None:
            return cached
        if self._ocr_reader is not None:
            text = self._normalize_page_text(self._ocr_reader(file_path, page_number))
            self._write_persisted_ocr_page(file_path=file_path, page_number=page_number, text=text)
            return text
        text = self._normalize_page_text(self._rapidocr_page(file_path=file_path, page_number=page_number))
        self._write_persisted_ocr_page(file_path=file_path, page_number=page_number, text=text)
        return text

    def _rapidocr_page(self, *, file_path: Path, page_number: int) -> str:
        try:
            image_path = self._render_pdf_page_to_temp_png(file_path=file_path, page_number=page_number)
        except Exception:
            return ""
        try:
            engine = self._rapidocr_engine()
            if engine is None:
                return ""
            result = engine(str(image_path))
            texts = list(getattr(result, "txts", ()) or ())
            return self._normalize_page_text("\n".join(str(item) for item in texts if str(item).strip()))
        except Exception:
            return ""
        finally:
            try:
                image_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _render_pdf_page_to_temp_png(self, *, file_path: Path, page_number: int) -> Path:
        try:
            import pypdfium2 as pdfium  # type: ignore
        except Exception as exc:
            raise RuntimeError("pypdfium2 is required for OCR PDF page rendering.") from exc

        output = Path(tempfile.gettempdir()) / f"pdf_ocr_{self._file_cache_key(file_path)[1]}_{page_number}.png"
        document = pdfium.PdfDocument(str(file_path))
        try:
            page = document[page_number - 1]
            try:
                bitmap = page.render(scale=self.ocr_render_scale)
                image = bitmap.to_pil()
                image.save(output)
            finally:
                close_page = getattr(page, "close", None)
                if callable(close_page):
                    close_page()
        finally:
            close_doc = getattr(document, "close", None)
            if callable(close_doc):
                close_doc()
        return output

    def _rapidocr_engine(self) -> object | None:
        if self._ocr_engine is not None:
            return self._ocr_engine
        try:
            from rapidocr import RapidOCR  # type: ignore
        except Exception:
            return None
        self._ocr_engine = RapidOCR()
        return self._ocr_engine

    def _ocr_available(self) -> bool:
        if self._ocr_reader is not None:
            return True
        try:
            import pypdfium2  # type: ignore  # noqa: F401
            from rapidocr import RapidOCR  # type: ignore  # noqa: F401
            return True
        except Exception:
            return False

    def _file_cache_key(self, file_path: Path) -> tuple[str, int, int]:
        try:
            stat = file_path.stat()
        except OSError:
            return (str(file_path.resolve()), 0, 0)
        return (str(file_path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))

    def _ocr_cache_path(self, *, file_path: Path, page_number: int) -> Path | None:
        if self.root_dir is None:
            return None
        key = self._file_cache_key(file_path)
        digest = hashlib.sha1("|".join(str(item) for item in key).encode("utf-8")).hexdigest()
        cache_root = ProjectLayout.from_backend_dir(self.root_dir).document_cache_dir / "pdf_ocr"
        return cache_root / digest / f"page_{page_number:04d}.txt"

    def _read_persisted_ocr_page(self, *, file_path: Path, page_number: int) -> str | None:
        path = self._ocr_cache_path(file_path=file_path, page_number=page_number)
        if path is None or not path.exists():
            return None
        try:
            return self._normalize_page_text(path.read_text(encoding="utf-8"))
        except OSError:
            return None

    def _write_persisted_ocr_page(self, *, file_path: Path, page_number: int, text: str) -> None:
        path = self._ocr_cache_path(file_path=file_path, page_number=page_number)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError:
            return

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

    def _infer_page_state(
        self,
        *,
        raw_text: str,
        segments: list[PdfSegment],
        has_text: bool,
        has_usable_text: bool,
    ) -> tuple[str, float]:
        normalized = self._normalize_page_text(raw_text)
        compact = re.sub(r"\s+", "", normalized)
        if not normalized and not segments:
            return ("page_structure_missing", 0.95)
        if any(segment.element_type == "toc_index" for segment in segments):
            return ("toc_like", 0.92)
        if any(segment.element_type == "cover_copyright" for segment in segments):
            return ("cover_or_copyright", 0.88)
        if any(segment.element_type == "references" for segment in segments):
            return ("reference_like", 0.86)
        if not has_text and any(segment.modality == "image" for segment in segments):
            return ("image_or_scan_without_text", 0.82)
        if has_usable_text:
            return ("body_content", 0.9)
        if normalized and self.looks_unusable_text(normalized):
            return ("text_corrupted", 0.84)
        if normalized and self._looks_transition_title_only(normalized, compact):
            return ("transition_title_only", 0.87)
        if has_text:
            return ("thin_text", 0.62)
        return ("page_structure_missing", 0.72)

    def _looks_transition_title_only(self, normalized: str, compact: str) -> bool:
        lines = [line.strip() for line in normalized.splitlines() if line.strip()]
        if not lines or len(lines) > 4:
            return False
        if len(compact) > 40:
            return False
        if re.search(r"(?:\.{4,}|…{2,}|·{4,})", normalized):
            return False
        if re.search(r"\b(?:19|20)\d{2}\b", normalized) and len(compact) > 28:
            return False
        return all(len(re.sub(r"\s+", "", line)) <= 24 for line in lines)

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
        pdfplumber_pages = self._extract_pages_with_pdfplumber(file_path)
        pypdf_pages = self._extract_pages_with_pypdf(file_path)
        if not pdfplumber_pages:
            return pypdf_pages
        if not pypdf_pages:
            return pdfplumber_pages

        pdfplumber_by_page = {page_number: text for page_number, text in pdfplumber_pages}
        pypdf_by_page = {page_number: text for page_number, text in pypdf_pages}
        page_numbers = sorted(set(pdfplumber_by_page) | set(pypdf_by_page))
        merged: list[tuple[int, str]] = []
        for page_number in page_numbers:
            plumber_text = str(pdfplumber_by_page.get(page_number, "") or "")
            pypdf_text = str(pypdf_by_page.get(page_number, "") or "")
            merged.append((page_number, self._choose_better_page_text(plumber_text, pypdf_text)))
        return merged

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

    def _choose_better_page_text(self, pdfplumber_text: str, pypdf_text: str) -> str:
        plumber_score = self._page_text_quality_score(pdfplumber_text)
        pypdf_score = self._page_text_quality_score(pypdf_text)
        if pypdf_score > plumber_score:
            return self._normalize_page_text(pypdf_text)
        if plumber_score > pypdf_score:
            return self._normalize_page_text(pdfplumber_text)
        if len(self._normalize_page_text(pypdf_text)) >= len(self._normalize_page_text(pdfplumber_text)):
            return self._normalize_page_text(pypdf_text)
        return self._normalize_page_text(pdfplumber_text)

    def _page_text_quality_score(self, text: str) -> float:
        normalized = self._normalize_page_text(text)
        if not normalized:
            return 0.0
        compact = re.sub(r"\s+", "", normalized)
        if not compact:
            return 0.0
        if self.looks_unusable_text(normalized):
            return 0.05
        score = 0.0
        score += min(len(compact) / 200.0, 1.0)
        alnum_ratio = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", compact)) / max(len(compact), 1)
        score += alnum_ratio
        line_count = max(len([line for line in normalized.splitlines() if line.strip()]), 1)
        if line_count <= 40:
            score += 0.2
        if re.search(r"[。！？；：]", normalized):
            score += 0.2
        if re.search(r"\d{4}", normalized):
            score += 0.1
        if re.search(r"[A-Za-z]{4,}", normalized):
            score += 0.1
        return score

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


