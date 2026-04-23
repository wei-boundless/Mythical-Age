from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from pdf_agent import PDFReadAgentRuntime, PDFReadRequest
from pdf_analysis import PdfAnalysisCatalog


class PdfAnalysisInput(BaseModel):
    query: str = Field(
        ...,
        description="User request about a PDF, such as a page follow-up or a deeper reading request.",
    )
    path: str = Field(
        default="",
        description="Optional PDF path relative to the backend root. If omitted, the tool will try to resolve it from the query or session context.",
    )
    mode: str = Field(
        default="document",
        description="Optional PDF query scope. Use document, section, or page; legacy values are normalized internally.",
    )
    max_chunks: int = Field(
        default=4,
        ge=1,
        le=12,
        description="Upper bound for how many relevant pages are surfaced for document or section answers.",
    )


class PdfAnalysisTool(BaseTool):
    name: str = "pdf_analysis"
    description: str = (
        "Read local PDF files with page-aware parsing. Use this for explicit PDF questions, page follow-ups, "
        "or focused document browsing."
    )
    args_schema: Type[BaseModel] = PdfAnalysisInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()
    _runtime: PDFReadAgentRuntime = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir.resolve()
        self._runtime = PDFReadAgentRuntime(root_dir=self._root_dir)

    def _resolve_explicit_path(self, path: str) -> Path:
        normalized = str(path or "").strip()
        if not normalized:
            raise ValueError("missing_explicit_pdf_path")
        candidates = PdfAnalysisCatalog.list_pdf_paths(self._root_dir)
        matched = PdfAnalysisCatalog._match_filename(self._root_dir, candidates, normalized)
        if matched is not None:
            return matched
        resolved = PdfAnalysisCatalog.resolve_pdf_path(self._root_dir, normalized, normalized)
        if not resolved.exists():
            raise ValueError("file_does_not_exist")
        if resolved.is_dir():
            raise ValueError("path_is_directory")
        return resolved

    def _run(
        self,
        query: str,
        path: str = "",
        mode: str = "document",
        max_chunks: int = 4,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            file_path = self._resolve_explicit_path(path)
        except ValueError as exc:
            code = str(exc)
            if code == "missing_explicit_pdf_path":
                return "PDF analysis failed: explicit path is required."
            if code == "file_does_not_exist":
                return "PDF analysis failed: file does not exist."
            if code == "path_is_directory":
                return "PDF analysis failed: the provided path is a directory."
            return f"PDF analysis failed: {exc}"

        result = self._runtime.run(
            request=PDFReadRequest(
                query=query,
                path=path,
                mode=mode,
                max_chunks=max_chunks,
            ),
            file_path=file_path,
        )
        return result.to_tool_output()

    async def _arun(
        self,
        query: str,
        path: str = "",
        mode: str = "document",
        max_chunks: int = 4,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, query, path, mode, max_chunks, None)
