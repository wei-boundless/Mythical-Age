from __future__ import annotations

from typing import Any

from capability_system.capabilities.office_document.models import (
    OfficeExecutionReport,
    OfficePatchOperation,
    OfficePatchPlan,
    OfficeVerificationReport,
)


class OfficeVerificationEngine:
    def verify(
        self,
        *,
        plan: OfficePatchPlan,
        execution: OfficeExecutionReport,
    ) -> OfficeVerificationReport:
        checks: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        if not execution.ok:
            diagnostics.extend(execution.diagnostics)
            checks.append(self._check("execution_success", False, {"applied_operations": list(execution.applied_operations)}))
            return OfficeVerificationReport(
                ok=False,
                level=str(plan.verification_contract.get("level", "semantic") or "semantic"),
                checks=tuple(checks),
                diagnostics=tuple(diagnostics),
                metadata={"output_path": str(plan.output_path)},
            )

        checks.append(self._check("output_exists", plan.output_path.exists(), {"path": str(plan.output_path)}))
        checks.append(self._check("output_nonzero", plan.output_path.exists() and plan.output_path.stat().st_size > 0, {"path": str(plan.output_path)}))
        try:
            if plan.file_type == "word":
                checks.extend(self._verify_word(plan))
            elif plan.file_type == "excel":
                checks.extend(self._verify_excel(plan))
            elif plan.file_type == "powerpoint":
                checks.extend(self._verify_powerpoint(plan))
            elif plan.file_type == "pdf":
                checks.extend(self._verify_pdf(plan))
            else:
                checks.append(self._check("supported_file_type", False, {"file_type": plan.file_type}))
        except Exception as exc:
            diagnostics.append(
                {
                    "code": "office_verification_failed",
                    "severity": "error",
                    "message": str(exc),
                    "details": {"plan_id": plan.plan_id, "output_path": str(plan.output_path)},
                }
            )
        ok = bool(checks) and all(bool(item.get("ok")) for item in checks) and not diagnostics
        return OfficeVerificationReport(
            ok=ok,
            level=str(plan.verification_contract.get("level", "semantic") or "semantic"),
            checks=tuple(checks),
            diagnostics=tuple(diagnostics),
            metadata={"output_path": str(plan.output_path), "plan_id": plan.plan_id},
        )

    def _verify_word(self, plan: OfficePatchPlan) -> list[dict[str, Any]]:
        from docx import Document

        document = Document(str(plan.output_path))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        checks = [self._check("word_reopen", True, {"paragraph_count": len(document.paragraphs)})]
        for operation in plan.operations:
            expected = self._expected_text(operation)
            if expected:
                checks.append(self._check(f"expected_text:{operation.op_id}", expected in text, {"text": expected}))
        return checks

    def _verify_excel(self, plan: OfficePatchPlan) -> list[dict[str, Any]]:
        from openpyxl import load_workbook

        workbook = load_workbook(str(plan.output_path), data_only=False)
        checks = [self._check("excel_reopen", True, {"sheet_names": list(workbook.sheetnames)})]
        for operation in plan.operations:
            if operation.op_type == "create_sheet":
                sheet_name = str(operation.expected_effect.get("sheet_name") or operation.payload.get("sheet_name") or "").strip()
                if sheet_name:
                    checks.append(self._check(f"sheet_created:{operation.op_id}", sheet_name in workbook.sheetnames, {"sheet_name": sheet_name}))
                continue
            if operation.op_type in {"update_cell", "set_formula"}:
                sheet_name = str(operation.target_anchor.get("sheet_name") or operation.payload.get("sheet_name") or workbook.active.title)
                cell_ref = str(operation.target_anchor.get("cell_ref") or operation.payload.get("cell_ref") or "")
                expected = operation.expected_effect.get("value")
                if cell_ref and sheet_name in workbook.sheetnames:
                    value = workbook[sheet_name][cell_ref].value
                    checks.append(
                        self._check(
                            f"cell_value:{operation.op_id}",
                            value == expected,
                            {"sheet_name": sheet_name, "cell_ref": cell_ref, "expected": expected, "actual": value},
                        )
                    )
            if operation.op_type == "append_rows":
                row_count = int(operation.expected_effect.get("row_count", 0) or 0)
                checks.append(self._check(f"rows_appended:{operation.op_id}", row_count > 0, {"row_count": row_count}))
        return checks

    def _verify_powerpoint(self, plan: OfficePatchPlan) -> list[dict[str, Any]]:
        from pptx import Presentation

        presentation = Presentation(str(plan.output_path))
        texts: list[str] = []
        for slide in presentation.slides:
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    texts.append(str(shape.text_frame.text or ""))
        joined = "\n".join(texts)
        checks = [self._check("powerpoint_reopen", True, {"slide_count": len(presentation.slides)})]
        for operation in plan.operations:
            expected = self._expected_text(operation)
            if expected:
                checks.append(self._check(f"expected_text:{operation.op_id}", expected in joined, {"text": expected}))
        return checks

    def _verify_pdf(self, plan: OfficePatchPlan) -> list[dict[str, Any]]:
        from pypdf import PdfReader

        reader = PdfReader(str(plan.output_path))
        checks = [self._check("pdf_reopen", True, {"page_count": len(reader.pages)})]
        for operation in plan.operations:
            if operation.op_type in {"reorder_pages", "split_pages"}:
                expected_pages = list(operation.expected_effect.get("pages") or [])
                if expected_pages:
                    checks.append(
                        self._check(
                            f"pdf_page_count:{operation.op_id}",
                            len(reader.pages) == len(expected_pages),
                            {"expected_page_count": len(expected_pages), "actual_page_count": len(reader.pages)},
                        )
                    )
            if operation.op_type == "delete_pages":
                source_reader = PdfReader(str(plan.source_path))
                deleted = len(list(operation.expected_effect.get("pages") or []))
                checks.append(
                    self._check(
                        f"pdf_deleted_pages:{operation.op_id}",
                        len(reader.pages) == max(0, len(source_reader.pages) - deleted),
                        {"source_page_count": len(source_reader.pages), "deleted": deleted, "actual_page_count": len(reader.pages)},
                    )
                )
        return checks

    def _expected_text(self, operation: OfficePatchOperation) -> str:
        return str(operation.expected_effect.get("text") or operation.payload.get("text") or operation.payload.get("new_text") or "").strip()

    def _check(self, name: str, ok: bool, details: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "name": name,
            "ok": bool(ok),
            "details": dict(details or {}),
        }
