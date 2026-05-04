from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Type

from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.units.mcp.local.retrieval.parser_adapter import MultimodalParserAdapter


class AnalyzeMultimodalFileInput(BaseModel):
    path: str = Field(
        ...,
        description="Relative path inside the backend project, for example knowledge/foo.pdf or RAG/data/example.png",
    )
    query: str = Field(
        default="",
        description="Optional user question used to focus the returned file summary.",
    )
    max_chunks: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Maximum number of parsed chunks to summarize in the tool output",
    )


class AnalyzeMultimodalFileTool(BaseTool):
    name: str = "analyze_multimodal_file"
    description: str = (
        "Parse a local PDF, image, spreadsheet, presentation, or document file and return "
        "normalized multimodal content. Use this when the user asks about a specific local file."
    )
    args_schema: Type[BaseModel] = AnalyzeMultimodalFileInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()
    _adapter: MultimodalParserAdapter = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir.resolve()
        self._adapter = MultimodalParserAdapter(repo_root=self._root_dir.parent)

    def _resolve_path(self, path: str) -> Path:
        candidate = (self._root_dir / path).resolve()
        if self._root_dir not in candidate.parents and candidate != self._root_dir:
            raise ValueError("Path traversal detected.")
        return candidate

    def _format_chunk(self, idx: int, chunk_text: str, metadata: dict[str, object]) -> str:
        labels: list[str] = []
        modality = str(metadata.get("modality", "") or "")
        if modality:
            labels.append(f"modality={modality}")
        page = metadata.get("page")
        if page not in (None, ""):
            labels.append(f"page={page}")
        section = str(metadata.get("section", "") or "")
        if section:
            labels.append(f"section={section}")
        row_start = metadata.get("row_start")
        row_end = metadata.get("row_end")
        total_rows = metadata.get("total_rows")
        if row_start not in (None, "") and row_end not in (None, ""):
            labels.append(f"rows={row_start}-{row_end}")
        if total_rows not in (None, ""):
            labels.append(f"total_rows={total_rows}")
        header = f"[{idx}]"
        if labels:
            header += " " + ", ".join(labels)
        return f"{header}\n{chunk_text}"

    def _query_terms(self, query: str) -> list[str]:
        tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", str(query or ""))
        blocked = {"这个", "那个", "一下", "文件", "文档", "内容", "读取", "分析", "总结", "看看"}
        terms: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            lowered = token.lower()
            if lowered in blocked or lowered in seen:
                continue
            seen.add(lowered)
            terms.append(token)
        return terms[:8]

    def _chunk_score(self, chunk, terms: list[str]) -> tuple[int, int]:
        text = str(chunk.text or "")
        lowered_text = text.lower()
        hits = 0
        for term in terms:
            hits += lowered_text.count(term.lower())
        section_bonus = 1 if str(chunk.section or "").strip() else 0
        return hits, section_bonus

    def _select_chunks(self, chunks: list, *, query: str, max_chunks: int) -> list:
        if not chunks:
            return []
        terms = self._query_terms(query)
        if not terms:
            return list(chunks[:max_chunks])
        ranked = sorted(chunks, key=lambda item: self._chunk_score(item, terms), reverse=True)
        if self._chunk_score(ranked[0], terms)[0] <= 0:
            return list(chunks[:max_chunks])
        return ranked[:max_chunks]

    def _chunk_locator(self, chunk) -> str:
        labels: list[str] = []
        if chunk.page not in (None, ""):
            labels.append(f"P{chunk.page}")
        if str(chunk.section or "").strip():
            labels.append(str(chunk.section).strip())
        modality = str(chunk.modality or "").strip()
        if modality and modality not in {"text", "table"}:
            labels.append(modality)
        return " / ".join(labels)

    def _preview_text(self, text: str, *, limit: int) -> str:
        normalized = " ".join(str(text or "").split()).strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."

    def _run(
        self,
        path: str,
        query: str = "",
        max_chunks: int = 8,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            file_path = self._resolve_path(path)
        except ValueError as exc:
            return f"Analyze failed: {exc}"

        if not file_path.exists():
            return "Analyze failed: file does not exist."
        if file_path.is_dir():
            return "Analyze failed: path is a directory."
        if not self._adapter.is_supported_file(file_path):
            return "Analyze failed: unsupported file type for multimodal parsing."

        chunks = self._adapter.parse_file(file_path)
        if not chunks:
            return "No parsable multimodal content was extracted from this file."

        selected_chunks = self._select_chunks(chunks, query=query, max_chunks=min(max_chunks, 4))

        modality_counts: dict[str, int] = {}
        for chunk in chunks:
            modality_counts[chunk.modality] = modality_counts.get(chunk.modality, 0) + 1
        modality_summary = ", ".join(f"{key}={value}" for key, value in sorted(modality_counts.items()))
        file_type = file_path.suffix.lower().lstrip(".") or "file"
        intro = f"结论：已读取本地文件 {path}。"
        if query.strip():
            intro += f" 围绕“{query.strip()}”，当前能直接确认的内容如下。"
        else:
            intro += " 当前可以给出文件概览。"
        summary_lines = [
            intro,
            f"文件类型：{file_type}；解析片段：{len(chunks)}；模态分布：{modality_summary}。",
        ]

        if not selected_chunks:
            summary_lines.append("当前没有提取到可展示的正文片段。")
            return "\n".join(summary_lines)

        summary_lines.append("关键片段：")
        for idx, chunk in enumerate(selected_chunks, start=1):
            locator = self._chunk_locator(chunk)
            preview_limit = 420 if chunk.modality == "table" else 280
            preview = self._preview_text(chunk.text, limit=preview_limit)
            line = f"{idx}. "
            if locator:
                line += f"{locator}："
            line += preview
            summary_lines.append(line)

        remaining = max(0, len(chunks) - len(selected_chunks))
        if remaining:
            summary_lines.append(f"其余还有 {remaining} 个片段未展开。")

        return "\n".join(summary_lines)[:20000]

    async def _arun(
        self,
        path: str,
        query: str = "",
        max_chunks: int = 8,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, path, query, max_chunks, None)
