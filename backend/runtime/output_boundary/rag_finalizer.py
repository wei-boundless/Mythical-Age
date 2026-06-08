from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from typing import Any

from prompt_library import RAG_FINALIZER_SYSTEM_PROMPT
from runtime.output_boundary.boundary import sanitize_visible_assistant_content


_NOISY_WHITESPACE_RE = re.compile(r"\s+")
_PATH_SPLIT_RE = re.compile(r"[\\/]")


@dataclass(slots=True)
class RAGEvidenceItem:
    source_label: str
    snippet: str
    score: float = 0.0
    page: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RAGEvidencePack:
    user_query: str
    rewritten_query: str = ""
    items: list[RAGEvidenceItem] = field(default_factory=list)


def build_rag_evidence_pack(
    *,
    user_query: str,
    retrieval_results: list[dict[str, Any]] | None,
    max_items: int = 3,
) -> RAGEvidencePack | None:
    items: list[RAGEvidenceItem] = []
    seen: set[str] = set()
    for result in list(retrieval_results or []):
        snippet = _normalize_retrieval_snippet(result)
        if not snippet:
            continue
        dedupe_key = _NOISY_WHITESPACE_RE.sub("", snippet).lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        items.append(
            RAGEvidenceItem(
                source_label=_format_retrieval_source_label(result),
                snippet=snippet,
                score=float(result.get("score") or 0.0),
                page=int(result.get("page")) if isinstance(result.get("page"), int) else None,
                metadata=dict(result.get("metadata", {}) or {}),
            )
        )
        if len(items) >= max(int(max_items or 1), 1):
            break
    if not items:
        return None
    rewritten_query = ""
    for result in list(retrieval_results or []):
        candidate = str(result.get("rewritten_query", "") or "").strip()
        if candidate:
            rewritten_query = candidate
            break
    return RAGEvidencePack(
        user_query=str(user_query or "").strip(),
        rewritten_query=rewritten_query,
        items=items,
    )


def build_rag_answer_finalization_messages(
    *,
    evidence_pack: RAGEvidencePack,
) -> list[dict[str, str]]:
    evidence_lines = []
    for index, item in enumerate(evidence_pack.items, start=1):
        prefix = f"{index}. "
        source_text = f"（来源：{item.source_label}）" if item.source_label else ""
        evidence_lines.append(f"{prefix}{item.snippet}{source_text}")
    evidence_block = "\n".join(evidence_lines) if evidence_lines else "无可用证据"
    user_prompt = (
        f"用户问题：{evidence_pack.user_query}\n"
        f"重写后的查询：{evidence_pack.rewritten_query or '无'}\n"
        f"当前检索证据：\n{evidence_block}\n\n"
        "请直接给出最终回答。"
    )
    return [
        {"role": "system", "content": RAG_FINALIZER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def normalize_finalized_answer(text: str) -> str:
    return sanitize_visible_assistant_content(str(text or "")).strip()


def total_compact_chars(evidence_pack: RAGEvidencePack) -> int:
    return sum(len(_NOISY_WHITESPACE_RE.sub("", item.snippet)) for item in evidence_pack.items)


def answer_looks_like_snippet_dump(answer: str, evidence_pack: RAGEvidencePack) -> bool:
    normalized_answer = _normalized_compare_key(answer)
    if not normalized_answer:
        return False
    return normalized_answer in {
        _normalized_compare_key(item.snippet)
        for item in evidence_pack.items
    }


def _normalize_retrieval_snippet(result: dict[str, Any]) -> str:
    raw = sanitize_visible_assistant_content(str(result.get("text", "") or "")).strip()
    if not raw:
        return ""
    normalized = _NOISY_WHITESPACE_RE.sub(" ", raw).strip(" -\n\t")
    if len(_NOISY_WHITESPACE_RE.sub("", normalized)) < 20:
        return ""
    return normalized[:220].rstrip("，,;；:： ")


def _format_retrieval_source_label(result: dict[str, Any]) -> str:
    source = str(result.get("source", "") or "").strip()
    page = result.get("page")
    parts: list[str] = []
    if source:
        source_parts = [part for part in _PATH_SPLIT_RE.split(source) if part]
        label = source_parts[-1] if source_parts else source
        parts.append(os.path.basename(label) or label)
    if isinstance(page, int) and page > 0:
        parts.append(f"P{page}")
    return " ".join(parts).strip()


def _normalized_compare_key(text: str) -> str:
    return _NOISY_WHITESPACE_RE.sub("", str(text or "")).lower()


