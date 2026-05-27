from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


class PdfAnalysisCatalog:
    GENERIC_DOC_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("白皮书", ("白皮书", "whitepaper")),
        ("深度报告", ("深度报告",)),
        ("报告", ("报告", "report")),
        ("财报", ("财报", "q1", "q2", "q3", "q4")),
        ("指南", ("指南", "guide")),
    )
    PDF_REFERENCE_PATTERNS: tuple[str, ...] = (
        r"((?:[A-Za-z]:)?(?:\.{1,2}[\\/])?(?:knowledge|Knowledge)[^\n\"'，。；;（）()]*?\.pdf)",
        r"[\"'`]([^\"'`\n]+?\.pdf)[\"'`]",
        r"([^\s\n,，。；;（）()]+\.pdf)",
    )

    @staticmethod
    def list_pdf_paths(root_dir: Path) -> list[Path]:
        knowledge_dir = ProjectLayout.from_backend_dir(root_dir).knowledge_storage_dir
        return sorted(path for path in knowledge_dir.rglob("*.pdf") if path.is_file())

    @staticmethod
    def resolve_pdf_path(root_dir: Path, path: str, query: str) -> Path:
        normalized = (path or "").strip()
        knowledge_dir = ProjectLayout.from_backend_dir(root_dir).knowledge_storage_dir.resolve()
        if normalized:
            candidate = (knowledge_dir / normalized).resolve()
            if knowledge_dir not in candidate.parents and candidate != knowledge_dir:
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
        knowledge_dir = ProjectLayout.from_backend_dir(root_dir).knowledge_storage_dir.resolve()
        return str(path.resolve().relative_to(knowledge_dir)).replace("\\", "/")

    @staticmethod
    def extract_explicit_pdf_references(text: str) -> list[str]:
        references: list[str] = []
        seen: set[str] = set()
        source = str(text or "").strip()
        if not source:
            return references
        for pattern in PdfAnalysisCatalog.PDF_REFERENCE_PATTERNS:
            for matched in re.finditer(pattern, source, flags=re.IGNORECASE):
                candidate = next((group for group in matched.groups() if group), "").strip()
                if not candidate:
                    continue
                normalized = candidate.strip("\"'`").strip()
                if not normalized.lower().endswith(".pdf"):
                    continue
                key = normalized.lower()
                if key in seen:
                    continue
                seen.add(key)
                references.append(normalized)
        return references

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

        # History restore only recovers explicit prior references. It must not
        # re-decide the current turn by semantically scoring the transcript.
        for text in recent_texts:
            for matched_name in PdfAnalysisCatalog.extract_explicit_pdf_references(text):
                resolved = PdfAnalysisCatalog._match_filename(root_dir, candidates, matched_name)
                if resolved is not None:
                    return resolved
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


