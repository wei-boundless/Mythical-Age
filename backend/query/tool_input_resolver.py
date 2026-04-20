from __future__ import annotations

from pathlib import Path
from typing import Any

from pdf_analysis import PdfAnalysisCatalog
from structured_data import StructuredDataCatalog


class ToolInputResolver:
    def __init__(self, *, base_dir: Path) -> None:
        self.base_dir = base_dir

    def resolve(
        self,
        *,
        plan: Any,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        message = plan.message
        understanding = plan.query_understanding
        tool_input = dict(understanding.tool_input or {"query": message})
        if understanding.tool_name == "pdf_analysis" and not str(tool_input.get("path", "") or "").strip():
            resolved = PdfAnalysisCatalog.resolve_pdf_path_from_history(self.base_dir, history)
            if resolved is None:
                try:
                    resolved = PdfAnalysisCatalog.resolve_pdf_path(
                        self.base_dir,
                        str(tool_input.get("path", "") or ""),
                        message,
                    )
                except ValueError:
                    resolved = None
            if resolved is not None:
                tool_input["path"] = PdfAnalysisCatalog.relative_path(self.base_dir, resolved)
        if (
            understanding.tool_name == "structured_data_analysis"
            and not str(tool_input.get("path", "") or "").strip()
        ):
            resolved = StructuredDataCatalog.resolve_dataset_path_from_history(self.base_dir, history)
            if resolved is None:
                try:
                    resolved = StructuredDataCatalog.resolve_dataset_path(
                        self.base_dir,
                        str(tool_input.get("path", "") or ""),
                        message,
                    )
                except ValueError:
                    resolved = None
            if resolved is not None:
                tool_input["path"] = StructuredDataCatalog.relative_path(self.base_dir, resolved)
        return tool_input
