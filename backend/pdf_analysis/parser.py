from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .mineru_client import MinerUApiClient, MinerUBlock, MinerUParseResult, build_default_mineru_client


@dataclass(slots=True)
class PdfSegment:
    text: str
    page: int | None = None
    section: str | None = None
    modality: str = "text"
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
            return [self._segment_from_remote_block(block) for block in remote.blocks]
        pages = remote.pages if remote is not None and remote.pages else self._extract_pages_locally(file_path)
        return [
            PdfSegment(
                text=text,
                page=page,
                modality="text",
                metadata={"parser": "local_pdf"},
            )
            for page, text in pages
            if text.strip()
        ]

    def looks_unusable_text(self, text: str) -> bool:
        cleaned = re.sub(r"\s+", "", text or "")
        if len(cleaned) < 20:
            return True
        alnum_ratio = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", cleaned)) / max(len(cleaned), 1)
        return alnum_ratio < 0.35

    def _segment_from_remote_block(self, block: MinerUBlock) -> PdfSegment:
        kind = (block.kind or "text").lower()
        modality = "table" if "table" in kind else "image" if any(token in kind for token in ("figure", "image")) else "text"
        return PdfSegment(
            text=block.text,
            page=block.page,
            section=block.section,
            modality=modality,
            metadata=dict(block.metadata),
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

    def _extract_pages_with_pypdf(self, file_path: Path) -> list[tuple[int, str]]:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            return []

        try:
            reader = PdfReader(str(file_path))
        except Exception:
            return []

        pages: list[tuple[int, str]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            pages.append((page_number, self._normalize_page_text(text)))
        return pages

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
