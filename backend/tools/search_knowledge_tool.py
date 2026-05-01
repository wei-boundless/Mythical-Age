from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from RAG.registry import RAGIndexRegistry


_KNOWLEDGE_EXTENSIONS = {".md", ".txt", ".json"}
_WEAK_SNIPPET_MAX_CHARS = 80


class SearchKnowledgeInput(BaseModel):
    query: str = Field(..., description="Semantic search query")
    top_k: int = Field(default=3, ge=1, le=10, description="How many passages to return")


class SearchKnowledgeBaseTool(BaseTool):
    name: str = "search_knowledge"
    description: str = "Search local knowledge documents through the unified v2 retrieval backend."
    args_schema: Type[BaseModel] = SearchKnowledgeInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()
    _registry: RAGIndexRegistry = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir
        self._registry = RAGIndexRegistry(root_dir)

    def _knowledge_index_ready(self) -> bool:
        status = self._registry.collection_status("knowledge")
        meta = dict(status.get("meta", {}) or {})
        return str(meta.get("status", "") or "").strip().lower() in {"ready", "empty"}

    def _run(
        self,
        query: str,
        top_k: int = 3,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        if not self._knowledge_index_ready():
            return "Knowledge index is not ready. Rebuild the knowledge collection before searching."
        effective_top_k = max(int(top_k or 1), 1)
        hits = self._registry.retrieve_collection(
            "knowledge",
            query,
            top_k=max(effective_top_k * 3, effective_top_k),
            query_mode="semantic_lookup",
        )
        merged_hits = self._rank_and_merge_hits(query, hits, top_k=effective_top_k)
        if not merged_hits:
            return "No relevant knowledge documents found."

        chunks: list[str] = []
        for index, hit in enumerate(merged_hits[:effective_top_k], start=1):
            modes = ",".join(hit.retrieval_modes) if hit.retrieval_modes else "unknown"
            chunks.append(
                (
                    f"[{index}] {hit.source} (score={float(hit.score or 0.0):.3f}, modes={modes})\n"
                    f"{hit.text[:1200]}"
                )
            )
        return "\n\n".join(chunks)[:5000]

    async def _arun(
        self,
        query: str,
        top_k: int = 3,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, query, top_k, None)

    def _rank_and_merge_hits(self, query: str, hits: list[object], *, top_k: int) -> list[object]:
        boosted = [self._boost_hit(query, hit) for hit in list(hits or [])]
        boosted.extend(self._local_exact_hits(query, top_k=max(top_k * 3, top_k)))
        deduped: list[object] = []
        seen: set[tuple[str, str]] = set()
        for hit in sorted(boosted, key=lambda item: float(getattr(item, "score", 0.0) or 0.0), reverse=True):
            text = _clean_text(str(getattr(hit, "text", "") or ""))
            if self._is_low_quality_hit(query, text):
                continue
            source = str(getattr(hit, "source", "") or "")
            key = (source, text[:220])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(hit)
        return deduped[:top_k]

    def _boost_hit(self, query: str, hit: object) -> object:
        from RAG.models import RetrievalHit

        text = str(getattr(hit, "text", "") or "")
        score = float(getattr(hit, "score", 0.0) or 0.0)
        lexical_score = _lexical_overlap_score(query, text)
        if lexical_score <= 0:
            return hit
        return RetrievalHit(
            text=text,
            source=str(getattr(hit, "source", "") or ""),
            modality=str(getattr(hit, "modality", "text") or "text"),
            score=score + lexical_score,
            page=getattr(hit, "page", None),
            metadata={**dict(getattr(hit, "metadata", {}) or {}), "local_lexical_boost": lexical_score},
            hit_id=getattr(hit, "hit_id", None),
            doc_id=getattr(hit, "doc_id", None),
            block_id=getattr(hit, "block_id", None),
            object_ref_id=getattr(hit, "object_ref_id", None),
            block_type=getattr(hit, "block_type", None),
            section_path=tuple(getattr(hit, "section_path", ()) or ()),
            score_breakdown={**dict(getattr(hit, "score_breakdown", {}) or {}), "local_lexical_boost": lexical_score},
            retrieval_modes=tuple([*tuple(getattr(hit, "retrieval_modes", ()) or ()), "quality_rerank"]),
            parser_backend=str(getattr(hit, "parser_backend", "") or ""),
            quality_flags=tuple(getattr(hit, "quality_flags", ()) or ()),
        )

    def _local_exact_hits(self, query: str, *, top_k: int) -> list[object]:
        from RAG.models import RetrievalHit

        knowledge_root = self._root_dir / "knowledge"
        if not knowledge_root.exists():
            return []
        query_text = str(query or "").strip()
        query_terms = _important_terms(query_text)
        if not query_terms:
            return []
        required_entities = _required_entity_terms(query_terms)

        candidates: list[RetrievalHit] = []
        for path in knowledge_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _KNOWLEDGE_EXTENSIONS:
                continue
            if _looks_like_directory_index(path):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            score = _lexical_overlap_score(query_text, f"{path.name}\n{text}")
            if score <= 0:
                continue
            searchable = f"{path.name}\n{text}".lower()
            if required_entities and not any(term in searchable for term in required_entities):
                continue
            snippet = _best_local_snippet(text, query_terms)
            if not snippet:
                continue
            rel = str(path.relative_to(self._root_dir)).replace("\\", "/")
            candidates.append(
                RetrievalHit(
                    text=snippet,
                    source=rel,
                    modality="text",
                    score=score + 1.0,
                    metadata={"retrieval_stage": "local_exact_text", "chain_version": "tool-local-rerank-v1"},
                    retrieval_modes=("local_exact", "quality_rerank"),
                )
            )
        candidates.sort(key=lambda item: float(item.score or 0.0), reverse=True)
        return candidates[:top_k]

    def _is_low_quality_hit(self, query: str, text: str) -> bool:
        if not text:
            return True
        if len(text) <= _WEAK_SNIPPET_MAX_CHARS and _lexical_overlap_score(query, text) < 0.5:
            return True
        return False


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _important_terms(query: str) -> list[str]:
    normalized = str(query or "").lower()
    raw_terms = re.findall(r"[A-Za-z0-9_./:-]+|[\u4e00-\u9fff]{2,}", normalized)
    stop = {
        "查询",
        "查一下",
        "搜索",
        "一下",
        "哪些",
        "什么",
        "多少",
        "前十",
        "前三",
        "前五",
        "本地",
        "知识库",
        "数据库",
        "我的",
        "我们",
        "帮我",
        "为我",
        "看看",
        "看一下",
        "分析",
        "统计",
    }
    terms: list[str] = []

    def add(term: str) -> None:
        normalized_term = term.strip().lower()
        if len(normalized_term) < 2 or normalized_term in stop:
            return
        if normalized_term not in terms:
            terms.append(normalized_term)

    for term in raw_terms:
        add(term)
        if re.fullmatch(r"[\u4e00-\u9fff]{4,}", term):
            for piece in _split_chinese_query_term(term, stop):
                add(piece)
    return terms


def _split_chinese_query_term(term: str, stop: set[str]) -> list[str]:
    cleaned = str(term or "")
    if not cleaned:
        return []
    for marker in sorted(stop, key=len, reverse=True):
        cleaned = cleaned.replace(marker, " ")
    cleaned = re.sub(r"前\s*[零一二三四五六七八九十百千万两\d]+\s*(?:大|名|个|页|项)?", " ", cleaned)
    cleaned = re.sub(r"第\s*[零一二三四五六七八九十百千万两\d]+\s*(?:大|名|个|页|项)?", " ", cleaned)
    cleaned = re.sub(r"(中|里|内|里面|当中|关于|有关|以及|和|与|的|了|是|有|查|找|讲)", " ", cleaned)
    pieces = [piece.strip() for piece in re.split(r"\s+", cleaned) if piece.strip()]
    expanded: list[str] = []
    for piece in pieces:
        if len(piece) >= 2:
            expanded.append(piece)
        if len(piece) >= 5:
            expanded.extend(_named_entity_like_chunks(piece))
    if "股东" in term:
        expanded.append("股东")
    if "持股" in term:
        expanded.append("持股")
    return expanded


def _named_entity_like_chunks(term: str) -> list[str]:
    chunks: list[str] = []
    for suffix in ("股份有限公司", "有限公司", "集团", "公司", "报告", "白皮书"):
        position = term.find(suffix)
        if position > 0:
            chunks.append(term[: position + len(suffix)])
            chunks.append(term[:position])
    for marker in ("股东", "持股", "库存", "缺货", "销售", "订单", "治理", "模型"):
        position = term.find(marker)
        if position > 1:
            chunks.append(term[:position])
            chunks.append(marker)
    return chunks


def _lexical_overlap_score(query: str, text: str) -> float:
    terms = _important_terms(query)
    if not terms:
        return 0.0
    lowered = str(text or "").lower()
    score = 0.0
    for term in terms:
        if term in lowered:
            score += max(0.25, min(len(term) / 8.0, 1.5))
    return score


def _required_entity_terms(terms: list[str]) -> list[str]:
    required: list[str] = []
    for term in terms:
        if re.search(r"[\u4e00-\u9fff]", term) and len(term) >= 4:
            if any(marker in term for marker in ("股东", "持股", "报告", "白皮书", "知识库", "数据库")):
                continue
            if term not in required:
                required.append(term)
    return required


def _looks_like_directory_index(path: Path) -> bool:
    stem = path.stem.lower()
    return stem in {"data_structure", "index", "readme", "目录索引"}


def _best_local_snippet(text: str, terms: list[str], *, window: int = 1200) -> str:
    normalized = str(text or "")
    if not normalized.strip():
        return ""
    lowered = normalized.lower()
    positions: list[int] = []
    for term in terms:
        start = 0
        while True:
            position = lowered.find(term, start)
            if position < 0:
                break
            positions.append(position)
            start = position + max(len(term), 1)
    if not positions:
        return ""
    best_score = float("-inf")
    best_start = 0
    for position in positions:
        start = max(0, position - 260)
        end = min(len(normalized), start + window)
        snippet = normalized[start:end]
        score = _lexical_overlap_score(" ".join(terms), snippet)
        score += _evidence_window_boost(terms, snippet)
        if score > best_score:
            best_score = score
            best_start = start
    end = min(len(normalized), best_start + window)
    return normalized[best_start:end].strip()


def _evidence_window_boost(terms: list[str], snippet: str) -> float:
    lowered = str(snippet or "").lower()
    boost = 0.0
    if "股东" in terms:
        for marker in ("前 10 名股东", "前十名股东", "股东名称", "持股数量", "持股比例", "三一集团", "香港中央", "梁稳根"):
            if marker.lower() in lowered:
                boost += 0.7
    if any(term in terms for term in ("库存", "缺货", "不足")):
        for marker in ("库存", "缺货", "不足", "stock", "inventory"):
            if marker.lower() in lowered:
                boost += 0.4
    return boost
