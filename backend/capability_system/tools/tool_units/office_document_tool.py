from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Type

from capability_system.capabilities.office_document import OfficeDocumentRequest, OfficeDocumentRuntime
from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from capability_system.tools.workspace_file_service import WorkspaceFileService
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


OFFICE_DOCUMENT_TOOL_GUIDANCE = (
    "Use for real .docx, .xlsx, .pptx, and .pdf artifacts. "
    "Supported create/edit operations: Word append_paragraph, append_section, replace_paragraph_text, insert_paragraph_after; "
    "Excel create_sheet, update_cell, set_formula, append_rows; "
    "PowerPoint add_slide, insert_text_box, replace_shape_text; "
    "PDF create add_page/append_text and page-level edit delete_pages, reorder_pages, split_pages, merge_pdfs. "
    "Inspect first when anchors are unclear. Prefer output_path for edits so source files remain protected. "
    "Set allow_overwrite only when the user explicitly requests replacement. "
    "Do not use write_file or scripts for Office/PDF binary structure."
)


class OfficeDocumentToolResult(dict):
    def __str__(self) -> str:
        return str(self.get("text") or "")


class OfficeDocumentInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "action": "create",
                    "path": "reports/summary.docx",
                    "target_file_type": "word",
                    "operations": [
                        {"op_type": "append_section", "payload": {"heading": "Summary", "text": "Draft content"}}
                    ],
                },
                {
                    "action": "edit",
                    "path": "sheets/budget.xlsx",
                    "output_path": "sheets/budget-updated.xlsx",
                    "operations": [
                        {
                            "op_type": "update_cell",
                            "target_anchor": {"sheet_name": "Sheet1", "cell_ref": "B2"},
                            "payload": {"value": 42},
                        }
                    ],
                },
            ],
            "usage_guidance": OFFICE_DOCUMENT_TOOL_GUIDANCE,
        },
    )

    action: str = Field(
        default="inspect",
        description=(
            "One of inspect, read, create, edit, convert, or render_verify. "
            "Use inspect/read before edit when the target paragraph, sheet, slide, shape, or page anchor is not known."
        ),
    )
    path: str = Field(
        ...,
        description=(
            "Workspace-relative source path. For create, this is the target file path when output_path is omitted. "
            "For edit/convert/render_verify, this is the source document path."
        ),
    )
    output_path: str = Field(
        default="",
        description=(
            "Workspace-relative output path for create/edit/convert actions. "
            "Prefer setting output_path for edits to avoid overwriting the source; omit only when the runtime default copy path is acceptable."
        ),
    )
    target_file_type: str = Field(
        default="",
        description=(
            "Optional create target: word, excel, powerpoint, or pdf. Usually inferred from output_path/path suffix. "
            "Required when the path suffix is missing or ambiguous."
        ),
    )
    operations: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Serializable office patch operations. Each item needs op_type plus target_anchor and payload as needed. "
            "Word: append_paragraph, append_section, replace_paragraph_text, insert_paragraph_after. "
            "Excel: create_sheet, update_cell, set_formula, append_rows. "
            "PowerPoint: add_slide, insert_text_box, replace_shape_text. "
            "PDF: add_page, append_text for create; delete_pages, reorder_pages, split_pages, merge_pdfs for page-level edits. "
            "Use stable anchors such as paragraph_index/contains, sheet_name/cell_ref, slide_number/shape_id/contains, or pages."
        ),
    )
    read_scope: str = Field(default="document", description="Read scope for inspect/read.")
    max_blocks: int = Field(default=80, ge=1, le=400, description="Maximum extracted text blocks returned for inspect/read.")
    allow_overwrite: bool = Field(default=False, description="Allow replacing an existing output file only when the user explicitly requested overwrite.")
    verification_level: str = Field(default="semantic", description="basic, structural, semantic, render, or strict. Treat failed verification as not complete.")


class OfficeDocumentTool(BaseTool):
    name: str = "office_document"
    description: str = (
        "Inspect, create, edit, and verify Word, Excel, PowerPoint, and PDF files through the unified OfficeDocumentRuntime. "
        "Use structured operations instead of calling low-level document libraries directly. "
        "Write-like actions create a patch plan, execute against a copy or new artifact, and return verification diagnostics. "
        + OFFICE_DOCUMENT_TOOL_GUIDANCE
    )
    args_schema: Type[BaseModel] = OfficeDocumentInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _files: WorkspaceFileService = PrivateAttr()
    _runtime: OfficeDocumentRuntime = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)
        self._runtime = OfficeDocumentRuntime(repo_root=self._files.workspace_root)

    def _run(
        self,
        action: str,
        path: str,
        output_path: str = "",
        target_file_type: str = "",
        operations: list[dict[str, Any]] | None = None,
        read_scope: str = "document",
        max_blocks: int = 80,
        allow_overwrite: bool = False,
        verification_level: str = "semantic",
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> OfficeDocumentToolResult:
        _ = run_manager
        try:
            source_path = self._files.resolve(path, require_path=True)
            resolved_output = self._files.resolve(output_path, require_path=True) if str(output_path or "").strip() else None
        except Exception as exc:
            return _tool_error(f"Office document operation failed: {exc}")
        result = self._runtime.run(
            OfficeDocumentRequest(
                action=str(action or "inspect").strip().lower(),
                source_path=source_path,
                output_path=resolved_output,
                target_file_type=str(target_file_type or "").strip().lower(),
                root_dir=self._files.workspace_root,
                read_scope=str(read_scope or "document").strip() or "document",
                max_blocks=max(1, min(int(max_blocks or 80), 400)),
                metadata={
                    "operations": [dict(item) for item in list(operations or []) if isinstance(item, dict)],
                    "allow_overwrite": bool(allow_overwrite),
                    "verification_level": str(verification_level or "semantic").strip() or "semantic",
                    "target_file_type": str(target_file_type or "").strip().lower(),
                },
            )
        )
        payload = result.to_dict()
        summary = payload.get("summary") or ("Office document operation completed." if result.ok else "Office document operation failed.")
        return OfficeDocumentToolResult(
            {
                "text": _compact_text(str(summary), payload),
                "structured_payload": {
                    "tool_result": {
                        "kind": "office_document",
                        **payload,
                    }
                },
            }
        )

    async def _arun(
        self,
        action: str,
        path: str,
        output_path: str = "",
        target_file_type: str = "",
        operations: list[dict[str, Any]] | None = None,
        read_scope: str = "document",
        max_blocks: int = 80,
        allow_overwrite: bool = False,
        verification_level: str = "semantic",
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> OfficeDocumentToolResult:
        return await asyncio.to_thread(
            self._run,
            action,
            path,
            output_path,
            target_file_type,
            operations,
            read_scope,
            max_blocks,
            allow_overwrite,
            verification_level,
            None,
        )


def _tool_error(message: str) -> OfficeDocumentToolResult:
    return OfficeDocumentToolResult(
        {
            "text": str(message or ""),
            "structured_payload": {
                "tool_result": {
                    "kind": "office_document",
                    "ok": False,
                    "status": "error",
                    "summary": str(message or ""),
                }
            },
        }
    )


def _compact_text(summary: str, payload: dict[str, Any]) -> str:
    lines = [summary.strip()]
    output_path = str(payload.get("output_path") or "").strip()
    if output_path:
        lines.append(f"output_path: {output_path}")
    diagnostics = list(payload.get("diagnostics") or [])
    if diagnostics:
        lines.append("diagnostics: " + json.dumps(diagnostics[:4], ensure_ascii=False))
    return "\n".join(line for line in lines if line)
