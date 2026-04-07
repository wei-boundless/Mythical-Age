from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .parser import PdfTextParser


class PdfAnalysisEngine:
    def __init__(
        self,
        root_dir: Path | None = None,
        *,
        parser: PdfTextParser | None = None,
    ) -> None:
        self._parser = parser or PdfTextParser(root_dir=root_dir)

    def execute(
        self,
        *,
        query: str,
        file_path: Path,
        max_chunks: int = 4,
        mode: str = "browse",
    ) -> str:
        pages = self._extract_pages(file_path)
        if not pages:
            return f"PDF analysis failed: {file_path.name} produced no readable text."

        normalized_mode = self._normalize_mode(mode)
        target_page = self._extract_target_page(query)
        if normalized_mode == "page_read" or target_page is not None:
            return self._read_page(file_path, pages, target_page)
        if normalized_mode == "deep_read":
            return self._deep_read(file_path, pages, query, max_chunks=max_chunks)
        return self._browse(file_path, pages, query, max_chunks=max_chunks)

    def _extract_pages(self, file_path: Path) -> list[tuple[int, str]]:
        return self._parser.extract_pages(file_path)

    def _browse(
        self,
        file_path: Path,
        pages: list[tuple[int, str]],
        query: str,
        *,
        max_chunks: int,
    ) -> str:
        top_pages = self._rank_pages(query, pages)[: max(1, max_chunks)]
        lines = [
            f"Source: {file_path.name}",
            "Mode: PDF browse",
            f"Total pages: {len(pages)}",
            "",
            "Relevant pages:",
        ]
        for page_number, score, text in top_pages:
            lines.append(f"[P{page_number}] score={score}")
            lines.append(self._snippet(text, target_length=520))
            lines.append("")
        return "\n".join(line for line in lines if line is not None).strip()

    def _deep_read(
        self,
        file_path: Path,
        pages: list[tuple[int, str]],
        query: str,
        *,
        max_chunks: int,
    ) -> str:
        top_pages = self._rank_pages(query, pages)[: max(2, min(max_chunks, 6))]
        merged_text = "\n\n".join(text for _, _, text in top_pages)
        keywords = self._keywords(merged_text)
        lines = [
            f"Source: {file_path.name}",
            "Mode: PDF deep read",
            f"Coverage pages: {', '.join(f'P{page}' for page, _, _ in top_pages)}",
        ]
        if keywords:
            lines.append("Keywords: " + ", ".join(keywords[:12]))
        lines.extend(
            [
                "",
                "Summary:",
                self._block_summary(merged_text, sentence_limit=6, char_limit=1200),
                "",
                "Evidence snippets:",
            ]
        )
        for page_number, score, text in top_pages:
            lines.append(f"[P{page_number}] score={score}")
            lines.append(self._snippet(text, target_length=700))
            lines.append("")
        return "\n".join(lines).strip()

    def _read_page(
        self,
        file_path: Path,
        pages: list[tuple[int, str]],
        target_page: int | None,
    ) -> str:
        if target_page is None:
            return (
                f"PDF analysis failed: no target page was detected for {file_path.name}. "
                "Please specify a page number."
            )

        page_map = {page_number: text for page_number, text in pages}
        if target_page not in page_map:
            max_page = max((page_number for page_number, _ in pages), default=0)
            return (
                f"PDF analysis failed: target page P{target_page} does not exist. "
                f"Detected page count is about {max_page}."
            )

        text = page_map[target_page]
        if self._parser.looks_unusable_text(text):
            return "\n".join(
                [
                    f"Source: {file_path.name}",
                    "Mode: PDF page read",
                    f"Target page: P{target_page}",
                    "This page did not produce stable readable text.",
                ]
            )

        title = self._heading_candidate(text)
        keywords = self._keywords(text)
        lines = [
            f"Source: {file_path.name}",
            "Mode: PDF page read",
            f"Target page: P{target_page}",
        ]
        if title:
            lines.append(f"Heading candidate: {title}")
        if keywords:
            lines.append("Keywords: " + ", ".join(keywords[:10]))
        lines.extend(
            [
                "",
                "Summary:",
                self._block_summary(text, sentence_limit=4, char_limit=800),
                "",
                "Page snippet:",
                self._snippet(text, target_length=1200),
            ]
        )
        return "\n".join(lines).strip()

    def _rank_pages(self, query: str, pages: list[tuple[int, str]]) -> list[tuple[int, int, str]]:
        query_tokens = self._tokens(query)
        scored: list[tuple[int, int, str]] = []
        for page_number, text in pages:
            if not text:
                continue
            lowered = text.lower()
            score = 0
            for token in query_tokens:
                if len(token) < 2:
                    continue
                score += lowered.count(token) * max(1, len(token))
            if score == 0 and not query_tokens:
                score = 1
            if score > 0:
                scored.append((page_number, score, text))
        scored.sort(key=lambda item: item[1], reverse=True)
        if scored:
            return scored
        return [(page_number, 1, text) for page_number, text in pages[: min(len(pages), 5)] if text]

    def _heading_candidate(self, text: str) -> str:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if len(line) < 4 or len(line) > 80:
                continue
            if self._looks_numeric(line):
                continue
            return line
        return ""

    def _block_summary(self, text: str, *, sentence_limit: int, char_limit: int) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return "No readable text was extracted from this page."
        sentences = re.split(r"(?<=[\u3002\uff01\uff1f.!?])\s+", cleaned)
        summary = " ".join(sentence.strip() for sentence in sentences[:sentence_limit] if sentence.strip())
        return summary[:char_limit] if summary else cleaned[:char_limit]

    def _keywords(self, text: str) -> list[str]:
        tokens = [token for token in self._tokens(text) if len(token) >= 2]
        if not tokens:
            return []
        counter = Counter(tokens)
        return [token for token, _ in counter.most_common(12)]

    def _tokens(self, text: str) -> list[str]:
        lowered = (text or "").lower()
        return re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{2,}", lowered)

    def _looks_numeric(self, text: str) -> bool:
        normalized = text.replace(".", "").replace("%", "").replace("-", "").replace(":", "").replace("/", "")
        return normalized.isdigit()

    def _snippet(self, text: str, target_length: int = 420) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if len(cleaned) <= target_length:
            return cleaned
        return cleaned[:target_length].rstrip() + " ..."

    def _normalize_mode(self, mode: str) -> str:
        normalized = (mode or "browse").strip().lower()
        if normalized in {"page_read", "page", "page-read"}:
            return "page_read"
        if normalized in {"deep_read", "deep", "deep-read"}:
            return "deep_read"
        return "browse"

    def _extract_target_page(self, query: str) -> int | None:
        text = query or ""
        digit_match = re.search(r"\u7b2c\s*(\d+)\s*\u9875", text, flags=re.IGNORECASE)
        if digit_match:
            return int(digit_match.group(1))

        english_match = re.search(r"page\s*(\d+)", text, flags=re.IGNORECASE)
        if english_match:
            return int(english_match.group(1))

        cn_match = re.search(
            r"\u7b2c\s*([\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343\u4e24\d]+)\s*\u9875",
            text,
        )
        if cn_match:
            return self._parse_chinese_number(cn_match.group(1))
        return None

    def _parse_chinese_number(self, text: str) -> int | None:
        digits = {
            "\u96f6": 0,
            "\u4e00": 1,
            "\u4e8c": 2,
            "\u4e24": 2,
            "\u4e09": 3,
            "\u56db": 4,
            "\u4e94": 5,
            "\u516d": 6,
            "\u4e03": 7,
            "\u516b": 8,
            "\u4e5d": 9,
        }
        units = {"\u5341": 10, "\u767e": 100, "\u5343": 1000}

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
