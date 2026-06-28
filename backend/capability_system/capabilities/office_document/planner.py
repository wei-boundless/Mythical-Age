from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from capability_system.capabilities.document_processing.models import DocumentProcessingBundle
from capability_system.capabilities.office_document.models import OfficeDocumentRequest, OfficePatchOperation, OfficePatchPlan

_SUPPORTED_OPERATIONS: dict[str, set[str]] = {
    "word": {
        "replace_paragraph_text",
        "insert_paragraph_after",
        "append_paragraph",
        "append_section",
    },
    "excel": {
        "update_cell",
        "set_formula",
        "append_rows",
        "create_sheet",
    },
    "powerpoint": {
        "replace_shape_text",
        "add_slide",
        "insert_text_box",
    },
    "pdf": {
        "delete_pages",
        "reorder_pages",
        "split_pages",
        "merge_pdfs",
    },
}

_CREATE_SUPPORTED_OPERATIONS: dict[str, set[str]] = {
    "word": {
        "append_paragraph",
        "append_section",
    },
    "excel": {
        "create_sheet",
        "update_cell",
        "set_formula",
        "append_rows",
    },
    "powerpoint": {
        "add_slide",
        "insert_text_box",
    },
    "pdf": {
        "add_page",
        "append_text",
    },
}

_EXTENSION_TO_FILE_TYPE = {
    ".docx": "word",
    ".docm": "word",
    ".dotx": "word",
    ".xlsx": "excel",
    ".xlsm": "excel",
    ".xltx": "excel",
    ".pptx": "powerpoint",
    ".pptm": "powerpoint",
    ".potx": "powerpoint",
    ".pdf": "pdf",
}


class OfficePatchPlanner:
    def build_plan(
        self,
        *,
        request: OfficeDocumentRequest,
        bundle: DocumentProcessingBundle,
    ) -> OfficePatchPlan:
        file_type = bundle.detected_format.family
        operations = self._operations_from_request(request)
        if not operations:
            raise ValueError("office_patch_operations_required")
        supported = _SUPPORTED_OPERATIONS.get(file_type, set())
        if not supported:
            raise ValueError(f"unsupported_office_file_type:{file_type}")
        unsupported = [operation.op_type for operation in operations if operation.op_type not in supported]
        if unsupported:
            raise ValueError(f"unsupported_office_operation:{','.join(unsupported)}")

        output_path = self._output_path(request=request, bundle=bundle)
        plan_id = self._plan_id(
            source_path=bundle.source_record.absolute_path,
            output_path=output_path,
            operations=operations,
        )
        return OfficePatchPlan(
            plan_id=plan_id,
            source_path=bundle.source_record.absolute_path,
            output_path=output_path,
            file_type=file_type,
            operations=operations,
            preconditions=(
                {
                    "kind": "source_exists",
                    "path": str(bundle.source_record.absolute_path),
                },
                {
                    "kind": "format_family",
                    "expected": file_type,
                    "detected_container": bundle.detected_format.container,
                },
            ),
            preservation_policy={
                "mode": "copy_then_patch",
                "overwrite": bool(request.metadata.get("allow_overwrite", False)),
            },
            verification_contract={
                "level": str(request.metadata.get("verification_level", "semantic") or "semantic"),
                "expected_effects": [operation.expected_effect for operation in operations],
            },
            risk_level=self._risk_level(operations),
        )

    def build_create_plan(self, *, request: OfficeDocumentRequest) -> OfficePatchPlan:
        file_type = self._target_file_type(request)
        if not file_type:
            raise ValueError("missing_office_target_file_type")
        supported = _CREATE_SUPPORTED_OPERATIONS.get(file_type, set())
        if not supported:
            raise ValueError(f"unsupported_office_file_type:{file_type}")
        operations = self._operations_from_request(request)
        unsupported = [operation.op_type for operation in operations if operation.op_type not in supported]
        if unsupported:
            raise ValueError(f"unsupported_office_create_operation:{','.join(unsupported)}")
        output_path = self._create_output_path(request)
        plan_id = self._plan_id(
            source_path=output_path,
            output_path=output_path,
            operations=operations,
        )
        return OfficePatchPlan(
            plan_id=plan_id,
            source_path=output_path,
            output_path=output_path,
            file_type=file_type,
            operations=operations,
            preconditions=(
                {
                    "kind": "target_file_type",
                    "expected": file_type,
                    "source": "create_request",
                },
            ),
            preservation_policy={
                "mode": "create_new",
                "overwrite": bool(request.metadata.get("allow_overwrite", False)),
            },
            verification_contract={
                "level": str(request.metadata.get("verification_level", "semantic") or "semantic"),
                "expected_effects": [operation.expected_effect for operation in operations],
            },
            risk_level=self._risk_level(operations) if operations else "low",
        )

    def _operations_from_request(self, request: OfficeDocumentRequest) -> tuple[OfficePatchOperation, ...]:
        if request.operations:
            operations: list[OfficePatchOperation] = []
            for index, operation in enumerate(request.operations, start=1):
                if isinstance(operation, OfficePatchOperation):
                    operations.append(self._normalize_operation(operation, index))
                elif isinstance(operation, dict):
                    operations.append(self._operation_from_dict(operation, index))
                else:
                    raise ValueError(f"invalid_office_operation:{index}")
            return tuple(operations)
        raw_operations = request.metadata.get("operations")
        if raw_operations is None and request.metadata.get("operation") is not None:
            raw_operations = [request.metadata.get("operation")]
        if raw_operations is None and request.metadata.get("op_type"):
            raw_operations = [request.metadata]
        operations: list[OfficePatchOperation] = []
        for index, raw in enumerate(list(raw_operations or []), start=1):
            if isinstance(raw, OfficePatchOperation):
                operations.append(self._normalize_operation(raw, index))
            elif isinstance(raw, dict):
                operations.append(self._operation_from_dict(raw, index))
            else:
                raise ValueError(f"invalid_office_operation:{index}")
        return tuple(operations)

    def _operation_from_dict(self, payload: dict[str, Any], index: int) -> OfficePatchOperation:
        op_type = str(payload.get("op_type") or payload.get("type") or "").strip().lower()
        if not op_type:
            raise ValueError(f"missing_office_operation_type:{index}")
        target_anchor = dict(payload.get("target_anchor") or payload.get("target") or {})
        operation_payload = dict(payload.get("payload") or {})
        if not operation_payload:
            operation_payload = {
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "op_id",
                    "op_type",
                    "type",
                    "target",
                    "target_anchor",
                    "payload",
                    "precondition",
                    "expected_effect",
                    "fallback_policy",
                }
            }
        expected_effect = dict(payload.get("expected_effect") or {})
        if not expected_effect:
            expected_effect = self._infer_expected_effect(op_type=op_type, target_anchor=target_anchor, payload=operation_payload)
        return OfficePatchOperation(
            op_id=str(payload.get("op_id") or f"op:{index}"),
            op_type=op_type,
            target_anchor=target_anchor,
            payload=operation_payload,
            precondition=dict(payload.get("precondition") or {}),
            expected_effect=expected_effect,
            fallback_policy=str(payload.get("fallback_policy") or "reject"),
        )

    def _normalize_operation(self, operation: OfficePatchOperation, index: int) -> OfficePatchOperation:
        op_type = operation.op_type.strip().lower()
        if not op_type:
            raise ValueError(f"missing_office_operation_type:{index}")
        expected_effect = dict(operation.expected_effect) or self._infer_expected_effect(
            op_type=op_type,
            target_anchor=operation.target_anchor,
            payload=operation.payload,
        )
        return OfficePatchOperation(
            op_id=operation.op_id or f"op:{index}",
            op_type=op_type,
            target_anchor=dict(operation.target_anchor),
            payload=dict(operation.payload),
            precondition=dict(operation.precondition),
            expected_effect=expected_effect,
            fallback_policy=operation.fallback_policy or "reject",
        )

    def _infer_expected_effect(
        self,
        *,
        op_type: str,
        target_anchor: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if op_type in {"replace_paragraph_text", "append_paragraph", "append_section", "replace_shape_text", "insert_text_box"}:
            return {"text": str(payload.get("text") or payload.get("new_text") or payload.get("replacement_text") or "")}
        if op_type in {"update_cell", "set_formula"}:
            return {
                "sheet_name": str(target_anchor.get("sheet_name") or payload.get("sheet_name") or ""),
                "cell_ref": str(target_anchor.get("cell_ref") or payload.get("cell_ref") or ""),
                "value": payload.get("formula") if op_type == "set_formula" else payload.get("value"),
            }
        if op_type == "append_rows":
            return {"row_count": len(list(payload.get("rows") or []))}
        if op_type == "create_sheet":
            return {"sheet_name": str(payload.get("sheet_name") or target_anchor.get("sheet_name") or "")}
        if op_type in {"delete_pages", "reorder_pages", "split_pages"}:
            return {"pages": list(payload.get("pages") or target_anchor.get("pages") or [])}
        if op_type == "merge_pdfs":
            return {"merged_paths": [str(item) for item in list(payload.get("paths") or [])]}
        return {}

    def _output_path(self, *, request: OfficeDocumentRequest, bundle: DocumentProcessingBundle) -> Path:
        allow_overwrite = bool(request.metadata.get("allow_overwrite", False))
        if request.output_path is not None:
            output_path = request.output_path.resolve()
        else:
            output_path = self._default_output_path(bundle.source_record.absolute_path)
        if output_path.exists() and not allow_overwrite:
            output_path = self._dedupe_path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path

    def _create_output_path(self, request: OfficeDocumentRequest) -> Path:
        output_path = (request.output_path or request.source_path).resolve()
        allow_overwrite = bool(request.metadata.get("allow_overwrite", False))
        if output_path.exists() and not allow_overwrite:
            output_path = self._dedupe_path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path

    def _target_file_type(self, request: OfficeDocumentRequest) -> str:
        explicit = str(request.target_file_type or request.metadata.get("target_file_type") or "").strip().lower()
        aliases = {
            "doc": "word",
            "docx": "word",
            "word": "word",
            "xls": "excel",
            "xlsx": "excel",
            "excel": "excel",
            "sheet": "excel",
            "spreadsheet": "excel",
            "ppt": "powerpoint",
            "pptx": "powerpoint",
            "powerpoint": "powerpoint",
            "presentation": "powerpoint",
            "pdf": "pdf",
        }
        if explicit in aliases:
            return aliases[explicit]
        suffix = (request.output_path or request.source_path).suffix.lower()
        return _EXTENSION_TO_FILE_TYPE.get(suffix, "")

    def _default_output_path(self, source_path: Path) -> Path:
        return source_path.with_name(f"{source_path.stem}.office-output{source_path.suffix}")

    def _dedupe_path(self, path: Path) -> Path:
        for index in range(1, 1000):
            candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise ValueError(f"office_output_path_unavailable:{path}")

    def _risk_level(self, operations: tuple[OfficePatchOperation, ...]) -> str:
        destructive = {"delete_pages", "reorder_pages", "replace_paragraph_text", "replace_shape_text"}
        if any(operation.op_type in destructive for operation in operations):
            return "high"
        if len(operations) > 5:
            return "medium"
        return "low"

    def _plan_id(
        self,
        *,
        source_path: Path,
        output_path: Path,
        operations: tuple[OfficePatchOperation, ...],
    ) -> str:
        digest = hashlib.sha1()
        digest.update(str(source_path).encode("utf-8", errors="ignore"))
        digest.update(str(output_path).encode("utf-8", errors="ignore"))
        for operation in operations:
            digest.update(str(operation.to_dict()).encode("utf-8", errors="ignore"))
        return f"office-plan:{digest.hexdigest()[:16]}"
