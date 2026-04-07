from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Type

from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from RAG.parser_adapter import MultimodalParserAdapter


class AnalyzeMultimodalFileInput(BaseModel):
    path: str = Field(
        ...,
        description="Relative path inside the backend project, for example knowledge/foo.pdf or RAG/data/example.png",
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

    def _run(
        self,
        path: str,
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

        summary_lines = [
            f"Source: {path}",
            f"Extracted chunks: {len(chunks)}",
        ]

        modality_counts: dict[str, int] = {}
        xlsx_summaries: list[str] = []
        for chunk in chunks:
            modality_counts[chunk.modality] = modality_counts.get(chunk.modality, 0) + 1
            if chunk.metadata.get("format") == "xlsx":
                total_rows = chunk.metadata.get("total_rows")
                section = chunk.section or "sheet"
                summary = f"{section} rows={total_rows}"
                if summary not in xlsx_summaries:
                    xlsx_summaries.append(summary)
        summary_lines.append(
            "Modalities: "
            + ", ".join(f"{key}={value}" for key, value in sorted(modality_counts.items()))
        )
        if xlsx_summaries:
            summary_lines.append("Sheets: " + ", ".join(xlsx_summaries))

        rendered_chunks: list[str] = []
        for idx, chunk in enumerate(chunks[:max_chunks], start=1):
            metadata = {
                "modality": chunk.modality,
                "page": chunk.page,
                "section": chunk.section,
                "row_start": chunk.metadata.get("row_start"),
                "row_end": chunk.metadata.get("row_end"),
                "total_rows": chunk.metadata.get("total_rows"),
            }
            preview_limit = 2400 if chunk.modality == "table" else 1800
            preview_text = chunk.text[:preview_limit]
            if len(chunk.text) > preview_limit:
                preview_text += "\n...[chunk preview truncated]"
            rendered_chunks.append(
                self._format_chunk(idx, preview_text, metadata)
            )

        if len(chunks) > max_chunks:
            rendered_chunks.append(f"... {len(chunks) - max_chunks} more chunks omitted.")

        return "\n\n".join(summary_lines + [""] + rendered_chunks)[:20000]

    async def _arun(
        self,
        path: str,
        max_chunks: int = 8,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, path, max_chunks, None)
