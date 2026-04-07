from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from pdf_analysis import PdfAnalysisCatalog, PdfAnalysisEngine


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
        default="browse",
        description="Reading mode: browse, deep_read, or page_read.",
    )
    max_chunks: int = Field(
        default=4,
        ge=1,
        le=12,
        description="Upper bound for how many relevant pages are surfaced for browse or deep-read mode.",
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
    _engine: PdfAnalysisEngine = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir.resolve()
        self._engine = PdfAnalysisEngine(root_dir=self._root_dir)

    def _run(
        self,
        query: str,
        path: str = "",
        mode: str = "browse",
        max_chunks: int = 4,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            file_path = PdfAnalysisCatalog.resolve_pdf_path(self._root_dir, path, query)
        except ValueError as exc:
            return f"PDF analysis failed: {exc}"

        if not file_path.exists():
            return "PDF analysis failed: file does not exist."
        if file_path.is_dir():
            return "PDF analysis failed: the provided path is a directory."

        return self._engine.execute(
            query=query,
            file_path=file_path,
            max_chunks=max_chunks,
            mode=mode,
        )

    async def _arun(
        self,
        query: str,
        path: str = "",
        mode: str = "browse",
        max_chunks: int = 4,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, query, path, mode, max_chunks, None)
