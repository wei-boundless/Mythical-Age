from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from RAG.cleaner import ParsedContentCleaner
from pdf_agent.models import (
    PDFCanonicalEvidence,
    PDFCanonicalResult,
    PDFPreparedDocument,
    PDFPreparedPage,
    PDFReadRequest,
    PDFRouteDecision,
)
from pdf_analysis import PdfTextParser
from pdf_analysis.parser import PdfSegment
from runtime_encoding import count_mojibake_markers, looks_like_mojibake
from structured_memory.text_utils import normalize_storage_text


_OVERVIEW_HINT_RE = re.compile(
    r"(?:全文|全篇|整体|总览|概览|概述|总结|摘要|核心结论|主要内容|行动建议|关键结论|重点)",
    re.IGNORECASE,
)
_PAGE_HINT_RE = re.compile(r"(?:第\s*\d+\s*页|page\s*\d+)", re.IGNORECASE)
_SECTION_HINT_RE = re.compile(
    r"(第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节)|(?:这一|那一|这|那)\s*(?:部分|章|节))",
    re.IGNORECASE,
)
_SECTION_TITLE_RE = re.compile(
    r"^(第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节)[^\n]{0,40})$",
    re.IGNORECASE,
)
_REFERENCE_HINT_RE = re.compile(r"(?:参考文献|references|bibliography|致谢)", re.IGNORECASE)
_TOC_HINT_RE = re.compile(r"(?:目录|contents)(?:\s|$)", re.IGNORECASE)
_COPYRIGHT_HINT_RE = re.compile(r"(?:版权所有|copyright|all rights reserved|免责声明|联系方式)", re.IGNORECASE)
_DOT_LEADER_RE = re.compile(r"(?:\.{4,}|·{4,}|…{2,})")
_WHITESPACE_RE = re.compile(r"\s+")
_CHINESE_NUMERAL_RE = re.compile(r"[零一二三四五六七八九十百千两]+")
_PAGE_QUALITY_MIN = 0.45
_PAGE_BODY_CHARS_MIN = 30
_SECTION_BODY_CHARS_MIN = 50
_DOCUMENT_BODY_PAGES_MIN = 2
_EXCLUDED_RATIO_MAX = 0.45
_SUSPICIOUS_TOKEN_COMMON_CHARS = set(
    "的一是在不了人有和为以对将从与及等中后前多可把或其主要当前全球发展治理规则数据模型应用报告国家产业风险安全系统能力重点结论部分页面文档问题内容建议约束实现机制立法政策工具标准方向实践建设要求管理业务"
)


@dataclass(slots=True)
class _PDFExecutionOutcome:
    stable_summary: str = ""
    evidence: list[PDFCanonicalEvidence] = field(default_factory=list)
    degraded_reason: str = ""
    error: str = ""


class PDFReadAgentRuntime:
    def __init__(
        self,
        *,
        root_dir: Path | None = None,
        parser: PdfTextParser | None = None,
    ) -> None:
        self._root_dir = root_dir.resolve() if root_dir is not None else None
        self._parser = parser or PdfTextParser(root_dir=self._root_dir)
        self._content_cleaner = ParsedContentCleaner()

    def run(
        self,
        *,
        request: PDFReadRequest,
        file_path: Path,
    ) -> PDFCanonicalResult:
        prepared = self._prepare_document(file_path)
        route = self._decide_route(query=request.query, requested_mode=self._normalize_mode(request.mode))
        if not prepared.pages:
            return PDFCanonicalResult(
                status="error",
                source=file_path.name,
                requested_mode=route.requested_mode,
                effective_mode=route.effective_mode,
                error=f"PDF analysis failed: {file_path.name} produced no readable text.",
                metadata={
                    "query": request.query,
                    "route_reason": route.reason,
                    "document_total_pages": prepared.total_pages,
                    "readable_pages": prepared.readable_pages,
                    "usable_pages": 0,
                },
            )

        outcome = self._execute_route(
            prepared=prepared,
            route=route,
            query=request.query,
            max_chunks=request.max_chunks,
        )
        evidence = list(outcome.evidence or [])
        pages = [item.page_number for item in evidence]
        stable_summary = outcome.stable_summary.strip()
        status = "ok" if stable_summary else "degraded" if outcome.degraded_reason else "error"
        error = outcome.error.strip() if status == "error" else ""
        return PDFCanonicalResult(
            status=status,
            source=prepared.source,
            requested_mode=route.requested_mode,
            effective_mode=route.effective_mode,
            summary=stable_summary,
            degraded_reason=outcome.degraded_reason.strip() if status != "ok" else "",
            pages=pages,
            evidence=evidence,
            error=error,
            metadata={
                "query": request.query,
                "route_reason": route.reason,
                "target_page": route.target_page,
                "target_section": route.target_section,
                "document_total_pages": prepared.total_pages,
                "readable_pages": prepared.readable_pages,
                "usable_pages": prepared.usable_pages,
                "parse_strategy": prepared.parse_strategy,
                "parse_confidence": prepared.parse_confidence,
            },
        )

    def _prepare_document(self, file_path: Path) -> PDFPreparedDocument:
        pages = list(self._parser.extract_pages(file_path))
        segments = list(self._parser.extract_segments(file_path))
        section_by_page = self._sections_by_page(segments)
        segments_by_page = self._segments_by_page(segments)
        prepared_pages: list[PDFPreparedPage] = []
        for page_number, text in pages:
            profile = self._profile_page(
                page_number=page_number,
                text=text,
                section=section_by_page.get(page_number, ""),
                segments=segments_by_page.get(page_number, []),
            )
            prepared_pages.append(profile)
        total_pages = self._document_total_pages(file_path=file_path, pages=pages, segments=segments)
        usable_count = sum(1 for page in prepared_pages if page.usable)
        parse_strategy = self._document_parse_strategy(prepared_pages, segments)
        parse_confidence = self._document_parse_confidence(prepared_pages, total_pages)
        return PDFPreparedDocument(
            source=file_path.name,
            pages=prepared_pages,
            total_pages=total_pages,
            readable_pages=len(prepared_pages),
            usable_pages=usable_count,
            parse_strategy=parse_strategy,
            parse_confidence=parse_confidence,
        )

    def _document_total_pages(
        self,
        *,
        file_path: Path,
        pages: list[tuple[int, str]],
        segments: list[PdfSegment],
    ) -> int:
        parser_total_pages = getattr(self._parser, "document_total_pages", None)
        if callable(parser_total_pages):
            try:
                total_pages = int(parser_total_pages(file_path) or 0)
            except Exception:
                total_pages = 0
            if total_pages > 0:
                return total_pages
        return max(
            [
                *[int(page_number) for page_number, _text in pages if int(page_number) > 0],
                *[int(segment.page) for segment in segments if int(segment.page or 0) > 0],
            ],
            default=0,
        )

    def _sections_by_page(self, segments: list[PdfSegment]) -> dict[int, str]:
        mapping: dict[int, str] = {}
        for segment in segments:
            page = int(segment.page or 0)
            section = str(segment.section or "").strip()
            if page <= 0 or not section:
                continue
            mapping.setdefault(page, section)
        return mapping

    def _segments_by_page(self, segments: list[PdfSegment]) -> dict[int, list[PdfSegment]]:
        mapping: dict[int, list[PdfSegment]] = {}
        for segment in segments:
            page = int(segment.page or 0)
            if page <= 0:
                continue
            mapping.setdefault(page, []).append(segment)
        return mapping

    def _profile_page(
        self,
        *,
        page_number: int,
        text: str,
        section: str,
        segments: list[PdfSegment],
    ) -> PDFPreparedPage:
        flags: list[str] = []
        normalized = self._collapse(text)
        body_text = self._clean_body_text_for_summary(self._body_text_from_segments(segments, fallback_text=text))
        body_chars = len(self._collapse(body_text))
        excluded_ratio = self._excluded_ratio(segments=segments, fallback_text=text)
        dominant_element_type = self._dominant_element_type(segments=segments)
        parse_strategy = self._page_parse_strategy(segments=segments)
        score = 1.0
        if self._parser.looks_unusable_text(text):
            flags.append("unusable_text")
            score -= 0.8
        if _REFERENCE_HINT_RE.search(normalized) or self._looks_reference_heavy_text(normalized):
            flags.append("reference_page")
            score -= 0.55
        if _TOC_HINT_RE.search(normalized) and _DOT_LEADER_RE.search(normalized):
            flags.append("toc_page")
            score -= 0.45
        if _COPYRIGHT_HINT_RE.search(normalized):
            flags.append("copyright_page")
            score -= 0.35
        if self._looks_sparse(normalized):
            flags.append("sparse_text")
            score -= 0.25
        if excluded_ratio > _EXCLUDED_RATIO_MAX:
            flags.append("excluded_content_dominant")
            score -= 0.3
        if body_chars < _PAGE_BODY_CHARS_MIN:
            flags.append("body_text_thin")
            score -= 0.2
        if normalized and not body_text:
            flags.append("body_text_dirty")
            score -= 0.35
        elif normalized and len(body_text) < max(20, int(len(normalized) * 0.35)):
            flags.append("body_text_heavily_cleaned")
            score -= 0.12
        quality_score = round(max(0.0, min(score, 1.0)), 3)
        usable = quality_score > 0.2 and "unusable_text" not in flags
        return PDFPreparedPage(
            page_number=page_number,
            text=text.strip(),
            section=section,
            body_text=self._collapse(body_text),
            quality_score=quality_score,
            quality_flags=list(dict.fromkeys(flags)),
            parse_strategy=parse_strategy,
            parse_confidence=quality_score,
            page_has_text=bool(normalized),
            dominant_element_type=dominant_element_type,
            excluded_ratio=round(excluded_ratio, 3),
            body_chars=body_chars,
            usable=usable,
        )

    def _execute_route(
        self,
        *,
        prepared: PDFPreparedDocument,
        route: PDFRouteDecision,
        query: str,
        max_chunks: int,
    ) -> _PDFExecutionOutcome:
        if route.effective_mode == "page":
            return self._run_page_scope(prepared=prepared, route=route)
        if route.effective_mode == "section":
            return self._run_section_scope(prepared=prepared, route=route, query=query, max_chunks=max_chunks)
        return self._run_document_scope(prepared=prepared, query=query, max_chunks=max_chunks)

    def _run_page_scope(
        self,
        *,
        prepared: PDFPreparedDocument,
        route: PDFRouteDecision,
    ) -> _PDFExecutionOutcome:
        target_page = int(route.target_page or 0)
        page = next((item for item in prepared.pages if item.page_number == target_page), None)
        if page is None:
            if 0 < target_page <= prepared.total_pages:
                return _PDFExecutionOutcome(
                    degraded_reason="target_page_has_no_stable_text",
                    evidence=[],
                )
            return _PDFExecutionOutcome(
                error=f"PDF analysis failed: target page P{target_page} does not exist. Detected page count is about {prepared.total_pages}.",
                evidence=[],
            )
        evidence = [self._evidence_from_page(page, score=1.0, snippet_chars=900)]
        if not self._page_meets_stable_gate(page):
            return _PDFExecutionOutcome(
                degraded_reason="target_page_text_quality_low",
                evidence=evidence,
            )
        section = f"（章节：{page.section}）" if page.section else ""
        summary = self._summarize_text(page.body_text or page.text, sentence_limit=4, char_limit=700)
        if not summary:
            return _PDFExecutionOutcome(
                degraded_reason="target_page_text_quality_low",
                evidence=evidence,
            )
        return _PDFExecutionOutcome(
            stable_summary=f"已读取 P{page.page_number}{section}。页面要点：{summary}",
            evidence=evidence,
        )

    def _run_section_scope(
        self,
        *,
        prepared: PDFPreparedDocument,
        route: PDFRouteDecision,
        query: str,
        max_chunks: int,
    ) -> _PDFExecutionOutcome:
        target_section = route.target_section.strip()
        section_pages = self._match_section_pages(prepared=prepared, target_section=target_section)
        if not section_pages:
            ranked = self._rank_pages(query=query, pages=prepared.pages)
            selected = ranked[: max(1, min(max_chunks, 3))]
            evidence = [self._evidence_from_page(page, score=score) for page, score in selected]
            if not evidence:
                return _PDFExecutionOutcome(
                    degraded_reason="target_section_not_located",
                    evidence=[],
                )
            return _PDFExecutionOutcome(
                degraded_reason="target_section_not_located",
                evidence=evidence,
            )
        selected_pages = [page for page in section_pages if self._page_eligible_for_section_summary(page)][
            : max(1, min(max_chunks, 4))
        ]
        if not self._section_meets_stable_gate(selected_pages):
            evidence = [
                self._evidence_from_page(page, score=max(page.quality_score, 0.1), snippet_chars=700)
                for page in section_pages[: max(1, min(max_chunks, 4))]
            ]
            return _PDFExecutionOutcome(
                degraded_reason="target_section_not_stably_located",
                evidence=evidence,
            )
        evidence = [self._evidence_from_page(page, score=max(page.quality_score, 0.1), snippet_chars=700) for page in selected_pages]
        summary = self._summarize_text(
            self._merge_summary_source(selected_pages),
            sentence_limit=5,
            char_limit=900,
        )
        if not summary:
            return _PDFExecutionOutcome(
                degraded_reason="target_section_not_stably_located",
                evidence=evidence,
            )
        pages_label = "、".join(f"P{page.page_number}" for page in selected_pages[:3])
        return _PDFExecutionOutcome(
            stable_summary=f"已定位到“{target_section}”相关内容，覆盖页面：{pages_label}。章节要点：{summary}",
            evidence=evidence,
        )

    def _run_document_scope(
        self,
        *,
        prepared: PDFPreparedDocument,
        query: str,
        max_chunks: int,
    ) -> _PDFExecutionOutcome:
        ranked = self._rank_pages(
            query=query,
            pages=[page for page in prepared.pages if self._page_eligible_for_document_summary(page)],
        )
        selected = ranked[: max(1, min(max_chunks, 3))]
        evidence = [self._evidence_from_page(page, score=score, snippet_chars=520) for page, score in selected]
        if not evidence or not self._document_meets_stable_gate([page for page, _score in selected]):
            return _PDFExecutionOutcome(
                degraded_reason="no_stable_document_evidence",
                evidence=evidence,
            )
        selected_label = "、".join(f"P{item.page_number}" for item in evidence[:3])
        merged = self._merge_summary_source(page for page, _score in selected)
        if len(merged) < max(30, _PAGE_BODY_CHARS_MIN):
            return _PDFExecutionOutcome(
                degraded_reason="document_summary_text_quality_low",
                evidence=evidence,
            )
        summary = self._summarize_text(merged, sentence_limit=5, char_limit=900)
        if not summary:
            return _PDFExecutionOutcome(
                degraded_reason="document_summary_text_quality_low",
                evidence=evidence,
            )
        return _PDFExecutionOutcome(
            stable_summary=f"已定位与当前问题最相关的页面：{selected_label}。文档要点：{summary}",
            evidence=evidence,
        )

    def _match_section_pages(
        self,
        *,
        prepared: PDFPreparedDocument,
        target_section: str,
    ) -> list[PDFPreparedPage]:
        if not target_section:
            return []
        normalized_target = self._normalize_section_label(target_section)
        matched: list[PDFPreparedPage] = []
        for page in prepared.pages:
            haystacks = [page.section, self._heading_candidate(page.text), self._first_line(page.text), page.text[:200]]
            normalized_haystacks = [self._normalize_section_label(item) for item in haystacks if item]
            if any(normalized_target and normalized_target in hay for hay in normalized_haystacks):
                if page.page_has_text:
                    matched.append(page)
        return matched

    def _rank_pages(
        self,
        *,
        query: str,
        pages: list[PDFPreparedPage],
    ) -> list[tuple[PDFPreparedPage, float]]:
        tokens = self._tokens(query)
        scored: list[tuple[PDFPreparedPage, float]] = []
        for page in pages:
            if not page.page_has_text:
                continue
            score = page.quality_score
            lowered = (page.body_text or page.text).lower()
            for token in tokens:
                if len(token) < 2:
                    continue
                score += lowered.count(token) * max(1.0, len(token) / 4.0)
                if token in str(page.section or "").lower():
                    score += max(1.5, len(token) / 3.0)
            if not tokens:
                score += 0.2
            if page.page_number <= 3:
                score += 0.08
            if page.excluded_ratio > _EXCLUDED_RATIO_MAX:
                score -= 0.35
            if "reference_page" in page.quality_flags or "toc_page" in page.quality_flags:
                score -= 0.45
            if page.body_chars >= _PAGE_BODY_CHARS_MIN or score > 0.95:
                scored.append((page, round(score, 3)))
        scored.sort(key=lambda item: (item[1], -item[0].page_number), reverse=True)
        return scored

    def _decide_route(self, *, query: str, requested_mode: str) -> PDFRouteDecision:
        target_page = self._extract_target_page(query)
        if requested_mode == "page" or target_page is not None or _PAGE_HINT_RE.search(query or ""):
            return PDFRouteDecision(
                requested_mode=requested_mode,
                effective_mode="page",
                target_page=target_page,
                reason="page_marker",
            )
        target_section = self._extract_target_section(query)
        if target_section:
            return PDFRouteDecision(
                requested_mode=requested_mode,
                effective_mode="section",
                target_section=target_section,
                reason="section_marker",
            )
        if _OVERVIEW_HINT_RE.search(query or ""):
            return PDFRouteDecision(requested_mode=requested_mode, effective_mode="document", reason="overview_hint")
        if requested_mode == "document":
            return PDFRouteDecision(
                requested_mode=requested_mode,
                effective_mode="document",
                reason="requested_document",
            )
        return PDFRouteDecision(
            requested_mode=requested_mode,
            effective_mode="document",
            reason="default_document",
        )

    def _normalize_mode(self, mode: str) -> str:
        normalized = (mode or "document").strip().lower()
        if normalized in {"page", "page-read", "page_read"}:
            return "page"
        if normalized in {"section", "section-read", "section_read"}:
            return "section"
        return "document"

    def _extract_target_page(self, text: str) -> int | None:
        normalized = str(text or "")
        digit_match = re.search(r"第\s*(\d+)\s*页", normalized, flags=re.IGNORECASE)
        if digit_match:
            return int(digit_match.group(1))
        english_match = re.search(r"page\s*(\d+)", normalized, flags=re.IGNORECASE)
        if english_match:
            return int(english_match.group(1))
        chinese_match = re.search(r"第\s*([零一二三四五六七八九十百千两]+)\s*页", normalized)
        if chinese_match:
            return self._parse_chinese_number(chinese_match.group(1))
        return None

    def _extract_target_section(self, text: str) -> str:
        normalized = str(text or "").strip()
        match = _SECTION_HINT_RE.search(normalized)
        if not match:
            return ""
        section = str(match.group(1) or "").strip()
        if section.startswith(("这一", "那一", "这", "那")):
            return section
        return self._normalize_section_label(section, preserve_surface=True)

    def _evidence_from_page(
        self,
        page: PDFPreparedPage,
        *,
        score: float,
        snippet_chars: int = 640,
    ) -> PDFCanonicalEvidence:
        return PDFCanonicalEvidence(
            page_number=page.page_number,
            score=round(score, 3),
            snippet=self._snippet(page.body_text or page.text, target_length=snippet_chars),
        )

    def _summarize_text(self, text: str, *, sentence_limit: int, char_limit: int) -> str:
        cleaned = self._clean_body_text_for_summary(text)
        if not cleaned:
            return ""
        sentences = re.split(r"(?<=[\u3002\uff01\uff1f.!?])\s+", cleaned)
        summary = " ".join(sentence.strip() for sentence in sentences[:sentence_limit] if sentence.strip())
        return summary[:char_limit].strip() if summary else cleaned[:char_limit].strip()

    def _first_line(self, text: str) -> str:
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if line:
                return line
        return ""

    def _heading_candidate(self, text: str) -> str:
        for raw_line in str(text or "").splitlines()[:8]:
            line = raw_line.strip()
            if not line or len(line) < 4 or len(line) > 80:
                continue
            if _SECTION_TITLE_RE.search(line):
                return line
            if not self._looks_sparse(line) and len(line) <= 36:
                return line
        return ""

    def _normalize_section_label(self, text: str, *, preserve_surface: bool = False) -> str:
        normalized = self._collapse(text)
        if not normalized:
            return ""
        normalized = normalized.replace("这一", "第1").replace("那一", "第1")
        if preserve_surface:
            return normalized
        return _CHINESE_NUMERAL_RE.sub(lambda item: str(self._parse_chinese_number(item.group(0)) or item.group(0)), normalized)

    def _looks_sparse(self, text: str) -> bool:
        normalized = self._collapse(text)
        if len(normalized) < 40:
            return True
        unique_ratio = len(set(normalized)) / max(len(normalized), 1)
        return unique_ratio < 0.12

    def _looks_reference_heavy_text(self, text: str) -> bool:
        urls = len(re.findall(r"https?://|www\.", text, flags=re.IGNORECASE))
        years = len(re.findall(r"\b(?:19|20)\d{2}\b", text))
        numbered_entries = len(
            re.findall(r"(?:^|\s)(?:\[?\d{1,3}\]?\.|\d{1,3}\.\s+[A-Z])", text, flags=re.MULTILINE)
        )
        return urls >= 2 and years >= 2 and numbered_entries >= 2

    def _snippet(self, text: str, *, target_length: int) -> str:
        cleaned = self._collapse(text)
        if len(cleaned) <= target_length:
            return cleaned
        return cleaned[:target_length].rstrip() + " ..."

    def _tokens(self, text: str) -> list[str]:
        lowered = str(text or "").lower()
        return re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{2,}", lowered)

    def _parse_chinese_number(self, text: str) -> int | None:
        digits = {
            "零": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        units = {"十": 10, "百": 100, "千": 1000}
        if text.isdigit():
            return int(text)
        total = 0
        current = 0
        for char in text:
            if char in digits:
                current = digits[char]
            elif char in units:
                unit = units[char]
                if current == 0:
                    current = 1
                total += current * unit
                current = 0
            else:
                return None
        total += current
        return total or None

    def _collapse(self, text: str) -> str:
        return _WHITESPACE_RE.sub(" ", str(text or "")).strip()

    def _body_text_from_segments(self, segments: list[PdfSegment], *, fallback_text: str) -> str:
        body_parts = [
            self._collapse(segment.text)
            for segment in segments
            if segment.element_type == "body_text" and self._collapse(segment.text)
        ]
        fallback = self._collapse(fallback_text)
        if body_parts:
            candidate = " ".join(body_parts)
            if len(fallback) >= len(candidate) + 8:
                return fallback
            return candidate
        return fallback_text

    def _merge_summary_source(self, pages) -> str:
        merged = " ".join(self._page_summary_source(page) for page in pages if self._page_summary_source(page))
        return self._clean_body_text_for_summary(merged)

    def _page_summary_source(self, page: PDFPreparedPage) -> str:
        return self._clean_body_text_for_summary(page.body_text or page.text)

    def _clean_body_text_for_summary(self, text: str) -> str:
        normalized = normalize_storage_text(str(text or ""))
        if not normalized:
            return ""
        cleaned = self._content_cleaner.clean_text(normalized, modality="text").text
        cleaned = self._drop_suspicious_token_runs(cleaned)
        units = [self._normalize_summary_unit(unit) for unit in self._split_summary_units(cleaned)]
        kept_units = [unit for unit in units if self._summary_unit_allowed(unit)]
        return self._collapse(" ".join(kept_units))

    def _split_summary_units(self, text: str) -> list[str]:
        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.strip():
            return []
        units = re.split(r"(?<=[\u3002\uff01\uff1f.!?；;：:])\s+|\n+", normalized)
        return [unit for unit in units if self._collapse(unit)]

    def _summary_unit_allowed(self, text: str) -> bool:
        normalized = self._collapse(text)
        if not normalized:
            return False
        if self._parser.looks_unusable_text(normalized):
            return False
        if self._looks_reference_heavy_text(normalized):
            return False
        if looks_like_mojibake(normalized) or count_mojibake_markers(normalized) > 0:
            return False
        compact = re.sub(r"\s+", "", normalized)
        if not compact:
            return False
        weird_symbol_ratio = len(re.findall(r"[][=<>~`|{}]+", normalized)) / max(len(normalized), 1)
        if weird_symbol_ratio > 0.03:
            return False
        odd_unicode_ratio = len(re.findall(r"[\u3400-\u4dbf\uf900-\ufaff]", compact)) / max(len(compact), 1)
        if odd_unicode_ratio > 0.08:
            return False
        return True

    def _normalize_summary_unit(self, text: str) -> str:
        normalized = self._collapse(text)
        if not normalized:
            return ""
        normalized = re.sub(r"\bAl(?=[\u4e00-\u9fff])", "AI", normalized)
        normalized = re.sub(r"^(?:\d{4}\s+)?(?:AI|Al)\s+(?=[\u4e00-\u9fff])", "", normalized)
        normalized = re.sub(r"^(?:AI\s+)+(?=AI[\u4e00-\u9fff])", "", normalized)
        return self._collapse(normalized)

    def _drop_suspicious_token_runs(self, text: str) -> str:
        tokens = [token for token in re.split(r"(\s+)", str(text or "")) if token]
        content_indexes = [index for index, token in enumerate(tokens) if not token.isspace()]
        suspicious_map = {index: self._classify_suspicious_token(tokens[index]) for index in content_indexes}
        kept: list[str] = []
        for position, index in enumerate(content_indexes):
            token = tokens[index]
            classification = suspicious_map.get(index, "")
            if classification == "strong":
                continue
            if classification == "weak":
                window_start = max(0, position - 2)
                window_end = min(len(content_indexes), position + 3)
                neighbor_is_suspicious = any(
                    suspicious_map.get(content_indexes[cursor], "") in {"strong", "weak"}
                    for cursor in range(window_start, window_end)
                    if cursor != position
                )
                if neighbor_is_suspicious:
                    continue
            kept.append(token)
        return " ".join(kept)

    def _classify_suspicious_token(self, token: str) -> str:
        normalized = self._collapse(token).strip("[](){}<>|")
        if not normalized:
            return ""
        compact = re.sub(r"\s+", "", normalized)
        if not compact:
            return ""
        if looks_like_mojibake(compact) or count_mojibake_markers(compact) > 0:
            return "strong"
        if re.search(r"[][=<>~`|{}]", compact):
            return "strong"
        if re.search(r"[\u3400-\u4dbf\uf900-\ufaff]", compact):
            return "strong"
        if re.fullmatch(r"[\u4e00-\u9fff]{2,6}", compact):
            if not any(char in _SUSPICIOUS_TOKEN_COMMON_CHARS for char in compact):
                return "weak"
        return ""

    def _excluded_ratio(self, *, segments: list[PdfSegment], fallback_text: str) -> float:
        if not segments:
            normalized = self._collapse(fallback_text)
            if not normalized:
                return 1.0
            if _REFERENCE_HINT_RE.search(normalized) or (
                _TOC_HINT_RE.search(normalized) and _DOT_LEADER_RE.search(normalized)
            ) or _COPYRIGHT_HINT_RE.search(normalized):
                return 1.0
            return 0.0
        total = sum(len(self._collapse(segment.text)) for segment in segments if self._collapse(segment.text))
        if total <= 0:
            return 1.0
        excluded = sum(
            len(self._collapse(segment.text))
            for segment in segments
            if self._collapse(segment.text) and (segment.excluded_from_summary or segment.diagnostic_only)
        )
        return excluded / total

    def _dominant_element_type(self, *, segments: list[PdfSegment]) -> str:
        if not segments:
            return "body_text"
        scores: dict[str, int] = {}
        for segment in segments:
            element_type = str(segment.element_type or "body_text")
            scores[element_type] = scores.get(element_type, 0) + len(self._collapse(segment.text))
        return max(scores.items(), key=lambda item: item[1])[0]

    def _page_parse_strategy(self, *, segments: list[PdfSegment]) -> str:
        if any(str(segment.metadata.get("parser", "")).startswith("mineru") for segment in segments):
            return "layout_structured"
        if any(segment.diagnostic_only for segment in segments):
            return "diagnostic_only"
        return "text_fast"

    def _document_parse_strategy(self, pages: list[PDFPreparedPage], segments: list[PdfSegment]) -> str:
        if any(page.parse_strategy == "layout_structured" for page in pages) or any(
            str(segment.metadata.get("parser", "")).startswith("mineru") for segment in segments
        ):
            return "layout_structured"
        if pages and all(not page.usable for page in pages):
            return "diagnostic_only"
        return "text_fast"

    def _document_parse_confidence(self, pages: list[PDFPreparedPage], total_pages: int) -> float:
        if not pages or total_pages <= 0:
            return 0.0
        usable_ratio = sum(1 for page in pages if page.usable) / max(total_pages, 1)
        avg_quality = sum(page.quality_score for page in pages) / max(len(pages), 1)
        return round(min(1.0, usable_ratio * 0.6 + avg_quality * 0.4), 3)

    def _page_meets_stable_gate(self, page: PDFPreparedPage) -> bool:
        if page.dominant_element_type in {"references", "toc_index", "header_footer", "diagnostic_only", "cover_copyright"}:
            return False
        content_chars = len(self._collapse(page.body_text or page.text))
        return (
            page.page_has_text
            and page.quality_score >= _PAGE_QUALITY_MIN
            and content_chars >= max(40, _PAGE_BODY_CHARS_MIN - 20)
            and (page.excluded_ratio <= _EXCLUDED_RATIO_MAX or page.dominant_element_type in {"table_text", "figure_caption"})
        )

    def _page_eligible_for_document_summary(self, page: PDFPreparedPage) -> bool:
        return (
            page.page_has_text
            and page.body_chars >= _PAGE_BODY_CHARS_MIN
            and page.excluded_ratio <= _EXCLUDED_RATIO_MAX
            and page.dominant_element_type in {"body_text", "section_heading"}
            and "reference_page" not in page.quality_flags
            and "toc_page" not in page.quality_flags
            and "copyright_page" not in page.quality_flags
        )

    def _document_meets_stable_gate(self, pages: list[PDFPreparedPage]) -> bool:
        unique_pages = len({page.page_number for page in pages})
        total_body_chars = sum(page.body_chars for page in pages)
        if unique_pages < _DOCUMENT_BODY_PAGES_MIN and total_body_chars < max(30, _PAGE_BODY_CHARS_MIN):
            return False
        return all(page.excluded_ratio <= _EXCLUDED_RATIO_MAX for page in pages)

    def _section_meets_stable_gate(self, pages: list[PDFPreparedPage]) -> bool:
        if not pages:
            return False
        total_body_chars = sum(page.body_chars for page in pages)
        if total_body_chars < _SECTION_BODY_CHARS_MIN:
            return False
        return any(self._page_eligible_for_section_summary(page) for page in pages)

    def _page_eligible_for_section_summary(self, page: PDFPreparedPage) -> bool:
        return (
            page.page_has_text
            and page.body_chars >= max(20, _PAGE_BODY_CHARS_MIN - 10)
            and page.excluded_ratio <= _EXCLUDED_RATIO_MAX
            and page.dominant_element_type in {"body_text", "section_heading"}
            and "reference_page" not in page.quality_flags
            and "toc_page" not in page.quality_flags
            and "copyright_page" not in page.quality_flags
        )
