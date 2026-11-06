from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from capability_system.capabilities.office_document.models import OfficeExecutionReport, OfficePatchOperation, OfficePatchPlan


class OfficePatchExecutor:
    def execute(self, plan: OfficePatchPlan) -> OfficeExecutionReport:
        if str(plan.preservation_policy.get("mode") or "") == "create_new":
            return self._execute_create(plan)
        if plan.source_path.resolve() == plan.output_path.resolve():
            return self._failure(
                plan,
                code="office_output_path_matches_source",
                message="Office patch output path must not overwrite the source file.",
            )
        try:
            if plan.file_type == "word":
                return self._execute_word(plan)
            if plan.file_type == "excel":
                return self._execute_excel(plan)
            if plan.file_type == "powerpoint":
                return self._execute_powerpoint(plan)
            if plan.file_type == "pdf":
                return self._execute_pdf(plan)
        except Exception as exc:
            return self._failure(
                plan,
                code="office_patch_execution_failed",
                message=str(exc),
            )
        return self._failure(
            plan,
            code="unsupported_office_file_type",
            message=f"Unsupported office patch file type: {plan.file_type}",
        )

    def _execute_create(self, plan: OfficePatchPlan) -> OfficeExecutionReport:
        try:
            if plan.file_type == "word":
                return self._create_word(plan)
            if plan.file_type == "excel":
                return self._create_excel(plan)
            if plan.file_type == "powerpoint":
                return self._create_powerpoint(plan)
            if plan.file_type == "pdf":
                return self._create_pdf(plan)
        except Exception as exc:
            return self._failure(
                plan,
                code="office_document_create_failed",
                message=str(exc),
            )
        return self._failure(
            plan,
            code="unsupported_office_file_type",
            message=f"Unsupported office document create file type: {plan.file_type}",
        )

    def _create_word(self, plan: OfficePatchPlan) -> OfficeExecutionReport:
        from docx import Document

        document = Document()
        applied: list[str] = []
        skipped: list[dict[str, Any]] = []
        for operation in plan.operations:
            if operation.op_type == "append_paragraph":
                document.add_paragraph(self._payload_text(operation))
            elif operation.op_type == "append_section":
                heading = str(operation.payload.get("heading") or "").strip()
                if heading:
                    document.add_heading(heading, level=int(operation.payload.get("level", 1) or 1))
                text = self._payload_text(operation)
                if text:
                    document.add_paragraph(text)
            else:
                skipped.append(self._skip(operation, "unsupported_word_create_operation"))
                if operation.fallback_policy == "reject":
                    break
                continue
            applied.append(operation.op_id)
        plan.output_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(plan.output_path))
        return self._report(plan=plan, applied=applied, skipped=skipped)

    def _create_excel(self, plan: OfficePatchPlan) -> OfficeExecutionReport:
        from openpyxl import Workbook

        workbook = Workbook()
        applied: list[str] = []
        skipped: list[dict[str, Any]] = []
        for operation in plan.operations:
            if operation.op_type == "create_sheet":
                sheet_name = str(operation.payload.get("sheet_name") or operation.target_anchor.get("sheet_name") or "").strip()
                if not sheet_name:
                    skipped.append(self._skip(operation, "missing_sheet_name"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                if sheet_name not in workbook.sheetnames:
                    workbook.create_sheet(sheet_name)
            elif operation.op_type in {"update_cell", "set_formula"}:
                worksheet = self._worksheet(workbook, operation)
                cell_ref = str(operation.target_anchor.get("cell_ref") or operation.payload.get("cell_ref") or "").strip()
                if not cell_ref:
                    skipped.append(self._skip(operation, "missing_cell_ref"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                value = operation.payload.get("formula") if operation.op_type == "set_formula" else operation.payload.get("value")
                if operation.op_type == "set_formula" and value is not None and not str(value).startswith("="):
                    value = f"={value}"
                worksheet[cell_ref] = value
            elif operation.op_type == "append_rows":
                worksheet = self._worksheet(workbook, operation)
                rows = list(operation.payload.get("rows") or [])
                if not rows:
                    skipped.append(self._skip(operation, "missing_rows"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                for row in rows:
                    worksheet.append(list(row) if isinstance(row, (list, tuple)) else [row])
            else:
                skipped.append(self._skip(operation, "unsupported_excel_create_operation"))
                if operation.fallback_policy == "reject":
                    break
                continue
            applied.append(operation.op_id)
        plan.output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(str(plan.output_path))
        return self._report(plan=plan, applied=applied, skipped=skipped)

    def _create_powerpoint(self, plan: OfficePatchPlan) -> OfficeExecutionReport:
        from pptx import Presentation
        from pptx.util import Inches

        presentation = Presentation()
        applied: list[str] = []
        skipped: list[dict[str, Any]] = []
        for operation in plan.operations:
            if operation.op_type == "add_slide":
                layout_index = int(operation.payload.get("layout_index", 5) or 5)
                layout_index = max(0, min(layout_index, len(presentation.slide_layouts) - 1))
                slide = presentation.slides.add_slide(presentation.slide_layouts[layout_index])
                title = str(operation.payload.get("title") or "").strip()
                if title and slide.shapes.title is not None:
                    slide.shapes.title.text = title
            elif operation.op_type == "insert_text_box":
                slide = self._ppt_slide(presentation, operation)
                if slide is None:
                    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
                left = Inches(float(operation.payload.get("left", 1) or 1))
                top = Inches(float(operation.payload.get("top", 1) or 1))
                width = Inches(float(operation.payload.get("width", 6) or 6))
                height = Inches(float(operation.payload.get("height", 1) or 1))
                text_box = slide.shapes.add_textbox(left, top, width, height)
                text_box.text_frame.text = self._payload_text(operation)
            else:
                skipped.append(self._skip(operation, "unsupported_powerpoint_create_operation"))
                if operation.fallback_policy == "reject":
                    break
                continue
            applied.append(operation.op_id)
        if len(presentation.slides) == 0:
            presentation.slides.add_slide(presentation.slide_layouts[6])
        plan.output_path.parent.mkdir(parents=True, exist_ok=True)
        presentation.save(str(plan.output_path))
        return self._report(plan=plan, applied=applied, skipped=skipped)

    def _create_pdf(self, plan: OfficePatchPlan) -> OfficeExecutionReport:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        plan.output_path.parent.mkdir(parents=True, exist_ok=True)
        document = canvas.Canvas(str(plan.output_path), pagesize=letter)
        width, height = letter
        y = height - 72
        applied: list[str] = []
        skipped: list[dict[str, Any]] = []
        page_started = False
        for operation in plan.operations:
            if operation.op_type == "add_page":
                if page_started:
                    document.showPage()
                page_started = True
                y = height - 72
            elif operation.op_type == "append_text":
                text = self._payload_text(operation) or str(operation.payload.get("value") or "")
                if not text:
                    skipped.append(self._skip(operation, "missing_text"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                page_started = True
                for line in str(text).splitlines() or [text]:
                    if y < 72:
                        document.showPage()
                        y = height - 72
                    document.drawString(72, y, line[:120])
                    y -= 16
            else:
                skipped.append(self._skip(operation, "unsupported_pdf_create_operation"))
                if operation.fallback_policy == "reject":
                    break
                continue
            applied.append(operation.op_id)
        if not page_started:
            document.drawString(72, height - 72, "")
        document.showPage()
        document.save()
        return self._report(plan=plan, applied=applied, skipped=skipped)

    def _execute_word(self, plan: OfficePatchPlan) -> OfficeExecutionReport:
        from docx import Document

        self._copy_source(plan)
        document = Document(str(plan.output_path))
        applied: list[str] = []
        skipped: list[dict[str, Any]] = []
        for operation in plan.operations:
            if operation.op_type == "replace_paragraph_text":
                paragraph = self._word_paragraph(document, operation)
                if paragraph is None:
                    skipped.append(self._skip(operation, "word_paragraph_not_found"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                paragraph.text = self._payload_text(operation)
            elif operation.op_type == "append_paragraph":
                document.add_paragraph(self._payload_text(operation))
            elif operation.op_type == "append_section":
                heading = str(operation.payload.get("heading") or "").strip()
                if heading:
                    document.add_heading(heading, level=int(operation.payload.get("level", 1) or 1))
                text = self._payload_text(operation)
                if text:
                    document.add_paragraph(text)
            elif operation.op_type == "insert_paragraph_after":
                paragraph = self._word_paragraph(document, operation)
                if paragraph is None:
                    skipped.append(self._skip(operation, "word_paragraph_not_found"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                self._insert_word_paragraph_after(paragraph, self._payload_text(operation))
            else:
                skipped.append(self._skip(operation, "unsupported_word_operation"))
                if operation.fallback_policy == "reject":
                    break
                continue
            applied.append(operation.op_id)
        document.save(str(plan.output_path))
        return self._report(plan=plan, applied=applied, skipped=skipped)

    def _execute_excel(self, plan: OfficePatchPlan) -> OfficeExecutionReport:
        from openpyxl import load_workbook

        self._copy_source(plan)
        workbook = load_workbook(str(plan.output_path))
        applied: list[str] = []
        skipped: list[dict[str, Any]] = []
        for operation in plan.operations:
            if operation.op_type == "create_sheet":
                sheet_name = str(operation.payload.get("sheet_name") or operation.target_anchor.get("sheet_name") or "").strip()
                if not sheet_name:
                    skipped.append(self._skip(operation, "missing_sheet_name"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                if sheet_name not in workbook.sheetnames:
                    workbook.create_sheet(sheet_name)
            elif operation.op_type in {"update_cell", "set_formula"}:
                worksheet = self._worksheet(workbook, operation)
                cell_ref = str(operation.target_anchor.get("cell_ref") or operation.payload.get("cell_ref") or "").strip()
                if not cell_ref:
                    skipped.append(self._skip(operation, "missing_cell_ref"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                value = operation.payload.get("formula") if operation.op_type == "set_formula" else operation.payload.get("value")
                if operation.op_type == "set_formula" and value is not None and not str(value).startswith("="):
                    value = f"={value}"
                worksheet[cell_ref] = value
            elif operation.op_type == "append_rows":
                worksheet = self._worksheet(workbook, operation)
                rows = list(operation.payload.get("rows") or [])
                if not rows:
                    skipped.append(self._skip(operation, "missing_rows"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                for row in rows:
                    worksheet.append(list(row) if isinstance(row, (list, tuple)) else [row])
            else:
                skipped.append(self._skip(operation, "unsupported_excel_operation"))
                if operation.fallback_policy == "reject":
                    break
                continue
            applied.append(operation.op_id)
        workbook.save(str(plan.output_path))
        return self._report(plan=plan, applied=applied, skipped=skipped)

    def _execute_powerpoint(self, plan: OfficePatchPlan) -> OfficeExecutionReport:
        from pptx import Presentation
        from pptx.util import Inches

        self._copy_source(plan)
        presentation = Presentation(str(plan.output_path))
        applied: list[str] = []
        skipped: list[dict[str, Any]] = []
        for operation in plan.operations:
            if operation.op_type == "replace_shape_text":
                shape = self._ppt_shape(presentation, operation)
                if shape is None or not getattr(shape, "has_text_frame", False):
                    skipped.append(self._skip(operation, "ppt_shape_text_not_found"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                shape.text_frame.text = self._payload_text(operation)
            elif operation.op_type == "add_slide":
                layout_index = int(operation.payload.get("layout_index", 5) or 5)
                layout_index = max(0, min(layout_index, len(presentation.slide_layouts) - 1))
                slide = presentation.slides.add_slide(presentation.slide_layouts[layout_index])
                title = str(operation.payload.get("title") or "").strip()
                if title and slide.shapes.title is not None:
                    slide.shapes.title.text = title
            elif operation.op_type == "insert_text_box":
                slide = self._ppt_slide(presentation, operation)
                if slide is None:
                    skipped.append(self._skip(operation, "ppt_slide_not_found"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                left = Inches(float(operation.payload.get("left", 1) or 1))
                top = Inches(float(operation.payload.get("top", 1) or 1))
                width = Inches(float(operation.payload.get("width", 6) or 6))
                height = Inches(float(operation.payload.get("height", 1) or 1))
                text_box = slide.shapes.add_textbox(left, top, width, height)
                text_box.text_frame.text = self._payload_text(operation)
            else:
                skipped.append(self._skip(operation, "unsupported_powerpoint_operation"))
                if operation.fallback_policy == "reject":
                    break
                continue
            applied.append(operation.op_id)
        presentation.save(str(plan.output_path))
        return self._report(plan=plan, applied=applied, skipped=skipped)

    def _execute_pdf(self, plan: OfficePatchPlan) -> OfficeExecutionReport:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(str(plan.source_path))
        applied: list[str] = []
        skipped: list[dict[str, Any]] = []
        current_pages = list(range(len(reader.pages)))
        for operation in plan.operations:
            if operation.op_type == "delete_pages":
                delete_pages = set(self._page_indexes(operation, max_pages=len(current_pages)))
                current_pages = [page for index, page in enumerate(current_pages) if index not in delete_pages]
            elif operation.op_type in {"reorder_pages", "split_pages"}:
                indexes = self._page_indexes(operation, max_pages=len(reader.pages))
                if not indexes:
                    skipped.append(self._skip(operation, "missing_pages"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                current_pages = indexes
            elif operation.op_type == "merge_pdfs":
                paths = [Path(item).resolve() for item in list(operation.payload.get("paths") or [])]
                if not paths:
                    skipped.append(self._skip(operation, "missing_merge_paths"))
                    if operation.fallback_policy == "reject":
                        break
                    continue
                writer = PdfWriter()
                for page_index in current_pages:
                    writer.add_page(reader.pages[page_index])
                for path in paths:
                    extra_reader = PdfReader(str(path))
                    for page in extra_reader.pages:
                        writer.add_page(page)
                self._write_pdf(writer, plan.output_path)
                applied.append(operation.op_id)
                continue
            else:
                skipped.append(self._skip(operation, "unsupported_pdf_operation"))
                if operation.fallback_policy == "reject":
                    break
                continue
            applied.append(operation.op_id)
        if not any(operation.op_type == "merge_pdfs" for operation in plan.operations):
            writer = PdfWriter()
            for page_index in current_pages:
                writer.add_page(reader.pages[page_index])
            self._write_pdf(writer, plan.output_path)
        return self._report(plan=plan, applied=applied, skipped=skipped)

    def _copy_source(self, plan: OfficePatchPlan) -> None:
        plan.output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plan.source_path, plan.output_path)

    def _write_pdf(self, writer: Any, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wb") as handle:
            writer.write(handle)

    def _word_paragraph(self, document: Any, operation: OfficePatchOperation) -> Any | None:
        index = self._optional_int(operation.target_anchor.get("paragraph_index"))
        if index is None:
            paragraph_number = self._optional_int(operation.target_anchor.get("paragraph_number"))
            index = paragraph_number - 1 if paragraph_number is not None else None
        if index is not None and 0 <= index < len(document.paragraphs):
            return document.paragraphs[index]
        contains = str(operation.target_anchor.get("contains") or operation.payload.get("contains") or "").strip()
        if contains:
            return next((paragraph for paragraph in document.paragraphs if contains in paragraph.text), None)
        return None

    def _insert_word_paragraph_after(self, paragraph: Any, text: str) -> None:
        from docx.oxml import OxmlElement
        from docx.text.paragraph import Paragraph

        new_element = OxmlElement("w:p")
        paragraph._p.addnext(new_element)
        new_paragraph = Paragraph(new_element, paragraph._parent)
        new_paragraph.text = text

    def _worksheet(self, workbook: Any, operation: OfficePatchOperation) -> Any:
        sheet_name = str(operation.target_anchor.get("sheet_name") or operation.payload.get("sheet_name") or "").strip()
        if sheet_name:
            if sheet_name not in workbook.sheetnames:
                workbook.create_sheet(sheet_name)
            return workbook[sheet_name]
        return workbook.active

    def _ppt_slide(self, presentation: Any, operation: OfficePatchOperation) -> Any | None:
        slide_number = self._optional_int(operation.target_anchor.get("slide_number"))
        if slide_number is not None:
            index = slide_number - 1
        else:
            index = self._optional_int(operation.target_anchor.get("slide_index"))
        if index is None:
            index = 0
        if 0 <= index < len(presentation.slides):
            return presentation.slides[index]
        return None

    def _ppt_shape(self, presentation: Any, operation: OfficePatchOperation) -> Any | None:
        slide = self._ppt_slide(presentation, operation)
        if slide is None:
            return None
        shape_id = self._optional_int(operation.target_anchor.get("shape_id"))
        if shape_id is not None:
            found = next((shape for shape in slide.shapes if int(getattr(shape, "shape_id", -1)) == shape_id), None)
            if found is not None:
                return found
        shape_index = self._optional_int(operation.target_anchor.get("shape_index"))
        if shape_index is not None and 0 <= shape_index < len(slide.shapes):
            return slide.shapes[shape_index]
        contains = str(operation.target_anchor.get("contains") or operation.payload.get("contains") or "").strip()
        if contains:
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False) and contains in str(shape.text_frame.text or ""):
                    return shape
        return None

    def _page_indexes(self, operation: OfficePatchOperation, *, max_pages: int) -> list[int]:
        raw_pages = list(operation.payload.get("pages") or operation.target_anchor.get("pages") or [])
        indexes: list[int] = []
        for raw in raw_pages:
            value = self._optional_int(raw)
            if value is None:
                continue
            index = value - 1
            if 0 <= index < max_pages:
                indexes.append(index)
        return indexes

    def _payload_text(self, operation: OfficePatchOperation) -> str:
        return str(
            operation.payload.get("text")
            or operation.payload.get("new_text")
            or operation.payload.get("replacement_text")
            or ""
        )

    def _optional_int(self, value: Any) -> int | None:
        try:
            if value in (None, ""):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def _skip(self, operation: OfficePatchOperation, reason: str) -> dict[str, Any]:
        return {
            "op_id": operation.op_id,
            "op_type": operation.op_type,
            "reason": reason,
        }

    def _failure(self, plan: OfficePatchPlan, *, code: str, message: str) -> OfficeExecutionReport:
        return OfficeExecutionReport(
            ok=False,
            output_path=plan.output_path,
            diagnostics=(
                {
                    "code": code,
                    "severity": "error",
                    "message": message,
                    "details": {"plan_id": plan.plan_id},
                },
            ),
        )

    def _report(
        self,
        *,
        plan: OfficePatchPlan,
        applied: list[str],
        skipped: list[dict[str, Any]],
    ) -> OfficeExecutionReport:
        return OfficeExecutionReport(
            ok=not skipped and len(applied) == len(plan.operations),
            output_path=plan.output_path,
            applied_operations=tuple(applied),
            skipped_operations=tuple(skipped),
            diagnostics=(
                {
                    "code": "office_patch_operations_skipped",
                    "severity": "warning",
                    "message": "One or more office patch operations were skipped.",
                    "details": {"skipped_operations": skipped},
                },
            )
            if skipped
            else (),
        )
