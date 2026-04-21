from __future__ import annotations

from pathlib import Path
from typing import Any

from pdf_analysis import PdfAnalysisCatalog


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
        structured_binding = getattr(plan, "structured_binding", None)
        if understanding.tool_name == "pdf_analysis" and not str(tool_input.get("path", "") or "").strip():
            try:
                resolved = PdfAnalysisCatalog.resolve_pdf_path(
                    self.base_dir,
                    str(tool_input.get("path", "") or ""),
                    message,
                )
            except ValueError:
                resolved = None
            if resolved is None:
                resolved = PdfAnalysisCatalog.resolve_pdf_path_from_history(self.base_dir, history)
            if resolved is not None:
                tool_input["path"] = PdfAnalysisCatalog.relative_path(self.base_dir, resolved)
        if (
            understanding.tool_name == "structured_data_analysis"
            and not str(tool_input.get("path", "") or "").strip()
        ):
            binding_path = str(getattr(structured_binding, "dataset_path", "") or "").strip()
            if binding_path:
                tool_input["path"] = binding_path
        return tool_input
