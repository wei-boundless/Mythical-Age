from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class PdfAnalysisCatalog:
    GENERIC_DOC_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("白皮书", ("白皮书", "whitepaper")),
        ("深度报告", ("深度报告",)),
        ("报告", ("报告", "report")),
        ("财报", ("财报", "q1", "q2", "q3", "q4")),
        ("指南", ("指南", "guide")),
    )

    @staticmethod
    def list_pdf_paths(root_dir: Path) -> list[Path]:
        knowledge_dir = root_dir / "knowledge"
        return sorted(path for path in knowledge_dir.rglob("*.pdf") if path.is_file())

    @staticmethod
    def resolve_pdf_path(root_dir: Path, path: str, query: str) -> Path:
        normalized = (path or "").strip()
        if normalized:
            candidate = (root_dir / normalized).resolve()
            if root_dir not in candidate.parents and candidate != root_dir:
                raise ValueError("检测到非法路径访问。")
            return candidate

        candidates = PdfAnalysisCatalog.list_pdf_paths(root_dir)
        if not candidates:
            raise ValueError("知识库中没有可用的 PDF 文件。")

        generic_match = PdfAnalysisCatalog._match_generic_doc_type(root_dir, candidates, query)
        if generic_match is not None:
            return generic_match

        scored = PdfAnalysisCatalog._score_candidates(root_dir, candidates, query)
        if not scored or scored[0][0] <= 0:
            raise ValueError("未能根据问题自动判断 PDF 文件，请显式提供 path。")
        return scored[0][1]

    @staticmethod
    def relative_path(root_dir: Path, path: Path) -> str:
        return str(path.relative_to(root_dir)).replace("\\", "/")

    @staticmethod
    def resolve_pdf_path_from_history(root_dir: Path, history: list[dict[str, Any]]) -> Path | None:
        candidates = PdfAnalysisCatalog.list_pdf_paths(root_dir)
        if not candidates:
            return None

        recent_texts: list[str] = []
        for item in reversed(history[-12:]):
            content = str(item.get("content", "") or "").strip()
            if content:
                recent_texts.append(content)

        # 1. Prefer explicit PDF filenames from recent assistant/tool outputs.
        for text in recent_texts:
            for matched_name in re.findall(r"([^\s:：\n]+\.pdf)", text, flags=re.IGNORECASE):
                resolved = PdfAnalysisCatalog._match_filename(root_dir, candidates, matched_name)
                if resolved is not None:
                    return resolved

        # 2. Fall back to scoring recent transcript against known PDFs.
        transcript = "\n".join(recent_texts)
        if not transcript:
            return None
        scored = PdfAnalysisCatalog._score_candidates(root_dir, candidates, transcript)
        if scored and scored[0][0] > 0:
            return scored[0][1]
        return None

    @staticmethod
    def _score_candidates(root_dir: Path, candidates: list[Path], query: str) -> list[tuple[int, Path]]:
        query_text = (query or "").lower()
        query_tokens = PdfAnalysisCatalog._extract_tokens(query_text)
        scored: list[tuple[int, Path]] = []
        for candidate in candidates:
            rel = PdfAnalysisCatalog.relative_path(root_dir, candidate).lower()
            stem = candidate.stem.lower()
            tokens = PdfAnalysisCatalog._extract_tokens(stem) + PdfAnalysisCatalog._extract_tokens(rel)
            score = 0
            for token in set(tokens):
                if len(token) < 2:
                    continue
                if token in query_text:
                    score += max(2, len(token))
            for token in query_tokens:
                if token and token in stem:
                    score += max(1, len(token))
            scored.append((score, candidate))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored

    @staticmethod
    def _match_generic_doc_type(root_dir: Path, candidates: list[Path], query: str) -> Path | None:
        query_text = (query or "").lower()
        for marker, aliases in PdfAnalysisCatalog.GENERIC_DOC_MARKERS:
            if marker.lower() not in query_text and not any(alias.lower() in query_text for alias in aliases):
                continue
            matched: list[Path] = []
            for candidate in candidates:
                rel = PdfAnalysisCatalog.relative_path(root_dir, candidate).lower()
                stem = candidate.stem.lower()
                if any(alias.lower() in stem or alias.lower() in rel for alias in aliases):
                    matched.append(candidate)
            if len(matched) == 1:
                return matched[0]
        return None

    @staticmethod
    def _extract_tokens(text: str) -> list[str]:
        parts = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{2,}", text)
        return [part.strip() for part in parts if part.strip()]

    @staticmethod
    def _match_filename(root_dir: Path, candidates: list[Path], filename: str) -> Path | None:
        normalized = filename.strip().lower()
        for candidate in candidates:
            if candidate.name.lower() == normalized:
                return candidate
            rel = PdfAnalysisCatalog.relative_path(root_dir, candidate).lower()
            if rel.endswith(normalized):
                return candidate
        stem = Path(filename).stem.lower()
        for candidate in candidates:
            if candidate.stem.lower() == stem:
                return candidate
        return None
