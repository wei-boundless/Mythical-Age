from __future__ import annotations

from pathlib import Path

from capability_system.capabilities.document_processing.kernel import DocumentProcessingKernel
from capability_system.capabilities.document_processing.models import DocumentProcessingBundle
from capability_system.capabilities.office_document.executor import OfficePatchExecutor
from capability_system.capabilities.office_document.models import (
    OfficeDocumentRequest,
    OfficeDocumentResult,
    OfficeExecutionReport,
    OfficePatchPlan,
    OfficeVerificationReport,
)
from capability_system.capabilities.office_document.planner import OfficePatchPlanner
from capability_system.capabilities.office_document.verifier import OfficeVerificationEngine
from knowledge_system.conversion.models import SourceFileRecord

_READ_ACTIONS = {"inspect", "read"}
_WRITE_ACTIONS = {"edit", "convert", "render_verify"}


class OfficeDocumentRuntime:
    def __init__(
        self,
        *,
        document_kernel: DocumentProcessingKernel | None = None,
        planner: OfficePatchPlanner | None = None,
        executor: OfficePatchExecutor | None = None,
        verifier: OfficeVerificationEngine | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.document_kernel = document_kernel or DocumentProcessingKernel(repo_root=repo_root)
        self.planner = planner or OfficePatchPlanner()
        self.executor = executor or OfficePatchExecutor()
        self.verifier = verifier or OfficeVerificationEngine()

    def run(self, request: OfficeDocumentRequest) -> OfficeDocumentResult:
        action = str(request.action or "").strip().lower() or "inspect"
        if action not in _READ_ACTIONS | _WRITE_ACTIONS | {"create"}:
            return self._error_result(
                request=request,
                action=action,
                code="unsupported_office_action",
                message=f"Unsupported office document action: {action}",
            )
        if action == "create":
            return self._create_result(request=request, action=action)
        try:
            bundle = self._parse_request(
                request,
                parse_profile="office_write" if action in _WRITE_ACTIONS else "full",
            )
        except Exception as exc:
            return self._error_result(
                request=request,
                action=action,
                code="office_document_parse_failed",
                message=f"Office document parsing failed: {exc}",
            )
        if action in _WRITE_ACTIONS:
            return self._write_result(request=request, action=action, bundle=bundle)
        return self._read_result(request=request, action=action, bundle=bundle)

    def inspect_path(
        self,
        path: Path,
        *,
        collection: str = "office_document",
        root_dir: Path | None = None,
    ) -> OfficeDocumentResult:
        return self.run(
            OfficeDocumentRequest(
                action="inspect",
                source_path=path,
                collection=collection,
                root_dir=root_dir,
            )
        )

    def _parse_request(self, request: OfficeDocumentRequest, *, parse_profile: str = "full") -> DocumentProcessingBundle:
        path = request.source_path.resolve()
        root_dir = (request.root_dir or path.parent).resolve()
        record = SourceFileRecord.from_path(
            path,
            collection=request.collection,
            root_dir=root_dir,
        )
        return self.document_kernel.parse(record, parse_profile=parse_profile)

    def _read_result(
        self,
        *,
        request: OfficeDocumentRequest,
        action: str,
        bundle: DocumentProcessingBundle,
    ) -> OfficeDocumentResult:
        conversion = bundle.rag_projection.conversion_result
        blocks = tuple(
            {
                "block_id": block.block_id,
                "ir_block_id": block.metadata.get("ir_block_id", ""),
                "anchor_id": block.metadata.get("anchor_id", ""),
                "block_type": block.block_type,
                "modality": block.modality,
                "page": block.page,
                "section": block.section_label,
                "text": block.text,
            }
            for block in conversion.blocks[: max(1, int(request.max_blocks or 1))]
        )
        summary = self._summary(bundle=bundle, visible_block_count=len(blocks), total_block_count=len(conversion.blocks))
        limitations = tuple(bundle.office_projection.unsupported_actions) + tuple(bundle.office_projection.preservation_warnings)
        return OfficeDocumentResult(
            ok=True,
            status="ok",
            action=action,
            file_type=bundle.detected_format.family,
            source_path=bundle.source_record.source_path,
            summary=summary,
            extracted_content=blocks,
            diagnostics=tuple(diagnostic.to_dict() for diagnostic in bundle.diagnostics),
            limitations=limitations,
            metadata={
                "document_kernel_version": conversion.metadata.get("document_kernel_version"),
                "document_bundle_id": bundle.bundle_id,
                "detected_format": bundle.detected_format.to_metadata(),
                "parser_route": list(conversion.parser_route),
                "supported_actions": list(bundle.office_projection.supported_actions),
                "editable": bundle.office_projection.editable,
                "anchor_count": len(bundle.office_ir.anchors),
                "table_count": len(bundle.office_ir.tables),
                "block_count": len(bundle.office_ir.blocks),
            },
        )

    def _write_result(
        self,
        *,
        request: OfficeDocumentRequest,
        action: str,
        bundle: DocumentProcessingBundle,
    ) -> OfficeDocumentResult:
        conversion = bundle.rag_projection.conversion_result
        try:
            plan = self.planner.build_plan(request=request, bundle=bundle)
        except Exception as exc:
            return self._planning_error_result(request=request, action=action, bundle=bundle, error=str(exc))
        execution = self.executor.execute(plan)
        verification = self.verifier.verify(plan=plan, execution=execution)
        ok = bool(execution.ok and verification.ok)
        status = "ok" if ok else "error" if not execution.ok else "degraded"
        diagnostics = (
            tuple(diagnostic.to_dict() for diagnostic in bundle.diagnostics)
            + tuple(execution.diagnostics)
            + tuple(verification.diagnostics)
        )
        limitations = self._limitations_from_reports(execution=execution, verification=verification)
        return OfficeDocumentResult(
            ok=ok,
            status=status,
            action=action,
            file_type=bundle.detected_format.family,
            source_path=bundle.source_record.source_path,
            output_path=str(plan.output_path),
            summary=self._write_summary(plan=plan, execution=execution, verification=verification),
            artifact_refs=(
                {
                    "artifact_type": "office_document",
                    "path": str(plan.output_path),
                    "plan_id": plan.plan_id,
                    "verified": verification.ok,
                },
            )
            if plan.output_path.exists()
            else (),
            patch_plan_id=plan.plan_id,
            verification_report=verification.to_dict(),
            diagnostics=diagnostics,
            limitations=limitations,
            metadata={
                "document_kernel_version": conversion.metadata.get("document_kernel_version"),
                "document_bundle_id": bundle.bundle_id,
                "detected_format": bundle.detected_format.to_metadata(),
                "parser_route": list(conversion.parser_route),
                "supported_actions": list(bundle.office_projection.supported_actions),
                "editable": bundle.office_projection.editable,
                "patch_plan": plan.to_dict(),
                "execution_report": execution.to_dict(),
            },
        )

    def _create_result(self, *, request: OfficeDocumentRequest, action: str) -> OfficeDocumentResult:
        try:
            plan = self.planner.build_create_plan(request=request)
        except Exception as exc:
            return self._planless_error_result(
                request=request,
                action=action,
                code=str(exc).split(":", 1)[0],
                message=f"Office document creation planning failed: {exc}",
            )
        execution = self.executor.execute(plan)
        verification = self.verifier.verify(plan=plan, execution=execution)
        ok = bool(execution.ok and verification.ok)
        status = "ok" if ok else "error" if not execution.ok else "degraded"
        diagnostics = tuple(execution.diagnostics) + tuple(verification.diagnostics)
        limitations = self._limitations_from_reports(execution=execution, verification=verification)
        return OfficeDocumentResult(
            ok=ok,
            status=status,
            action=action,
            file_type=plan.file_type,
            source_path=str(request.source_path),
            output_path=str(plan.output_path),
            summary=self._write_summary(plan=plan, execution=execution, verification=verification),
            artifact_refs=(
                {
                    "artifact_type": "office_document",
                    "path": str(plan.output_path),
                    "plan_id": plan.plan_id,
                    "verified": verification.ok,
                },
            )
            if plan.output_path.exists()
            else (),
            patch_plan_id=plan.plan_id,
            verification_report=verification.to_dict(),
            diagnostics=diagnostics,
            limitations=limitations,
            metadata={
                "document_kernel_version": "",
                "document_bundle_id": "",
                "detected_format": {
                    "detected_family": plan.file_type,
                    "detected_container": "created",
                    "detected_extension": plan.output_path.suffix.lower(),
                    "detected_confidence": 1.0,
                    "format_signals": ["create_request"],
                    "format_limitations": [],
                    "declared_type": request.target_file_type,
                },
                "parser_route": ["office_document_create"],
                "supported_actions": ["create"],
                "editable": True,
                "patch_plan": plan.to_dict(),
                "execution_report": execution.to_dict(),
            },
        )

    def _planning_error_result(
        self,
        *,
        request: OfficeDocumentRequest,
        action: str,
        bundle: DocumentProcessingBundle,
        error: str,
    ) -> OfficeDocumentResult:
        status = "clarify" if error == "office_patch_operations_required" else "error"
        return OfficeDocumentResult(
            ok=False,
            status=status,
            action=action,
            file_type=bundle.detected_format.family,
            source_path=bundle.source_record.source_path,
            summary=f"Office patch planning failed: {error}",
            diagnostics=(
                {
                    "code": error.split(":", 1)[0],
                    "severity": "warning" if status == "clarify" else "error",
                    "message": error,
                    "details": {"action": action},
                },
            ),
            limitations=(error.split(":", 1)[0],),
            metadata={
                "document_bundle_id": bundle.bundle_id,
                "detected_format": bundle.detected_format.to_metadata(),
            },
        )

    def _error_result(
        self,
        *,
        request: OfficeDocumentRequest,
        action: str,
        code: str,
        message: str,
    ) -> OfficeDocumentResult:
        return OfficeDocumentResult(
            ok=False,
            status="error",
            action=action,
            file_type="unknown",
            source_path=str(request.source_path),
            summary=message,
            diagnostics=(
                {
                    "code": code,
                    "severity": "error",
                    "message": message,
                    "details": {},
                },
            ),
            limitations=(code,),
        )

    def _planless_error_result(
        self,
        *,
        request: OfficeDocumentRequest,
        action: str,
        code: str,
        message: str,
    ) -> OfficeDocumentResult:
        return OfficeDocumentResult(
            ok=False,
            status="error",
            action=action,
            file_type=str(request.target_file_type or request.metadata.get("target_file_type") or "unknown"),
            source_path=str(request.source_path),
            output_path=str(request.output_path or request.source_path),
            summary=message,
            diagnostics=(
                {
                    "code": code or "office_document_plan_failed",
                    "severity": "error",
                    "message": message,
                    "details": {"action": action},
                },
            ),
            limitations=(code or "office_document_plan_failed",),
        )

    def _summary(
        self,
        *,
        bundle: DocumentProcessingBundle,
        visible_block_count: int,
        total_block_count: int,
    ) -> str:
        detected = bundle.detected_format
        return (
            f"Detected {detected.family}/{detected.container} document with "
            f"{total_block_count} text blocks, {len(bundle.office_ir.tables)} tables, "
            f"{len(bundle.office_ir.anchors)} anchors. Returning {visible_block_count} blocks."
        )

    def _write_summary(
        self,
        *,
        plan: OfficePatchPlan,
        execution: OfficeExecutionReport,
        verification: OfficeVerificationReport,
    ) -> str:
        if execution.ok and verification.ok:
            return (
                f"Applied {len(execution.applied_operations)} office patch operations and verified output: "
                f"{plan.output_path}"
            )
        if not execution.ok:
            return f"Office patch execution failed for plan {plan.plan_id}."
        return f"Office patch executed but verification did not pass for plan {plan.plan_id}."

    def _limitations_from_reports(
        self,
        *,
        execution: OfficeExecutionReport,
        verification: OfficeVerificationReport,
    ) -> tuple[str, ...]:
        limitations: list[str] = []
        for diagnostic in (*execution.diagnostics, *verification.diagnostics):
            code = str(diagnostic.get("code", "") or "").strip()
            if code:
                limitations.append(code)
        for skipped in execution.skipped_operations:
            reason = str(skipped.get("reason", "") or "").strip()
            if reason:
                limitations.append(reason)
        for check in verification.checks:
            if not bool(check.get("ok")):
                limitations.append(str(check.get("name") or "verification_check_failed"))
        return tuple(dict.fromkeys(limitations))
