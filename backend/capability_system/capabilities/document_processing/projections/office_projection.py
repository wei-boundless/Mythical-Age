from __future__ import annotations

from capability_system.capabilities.document_processing.models import DetectedDocumentFormat, OfficeDocumentIR, OfficeProjection


def build_office_projection(
    *,
    detected_format: DetectedDocumentFormat,
    office_ir: OfficeDocumentIR,
) -> OfficeProjection:
    supported_actions = ["inspect", "read", "rag_index_projection"]
    unsupported_actions: list[str] = []
    preservation_warnings: list[str] = []

    if detected_format.container == "ooxml":
        supported_actions.extend(["anchor_resolution", "patch_plan_preview"])
        unsupported_actions.append("write_patch_execution_not_connected")
    elif detected_format.container == "ole":
        supported_actions.append("convert_via_external_runtime")
        unsupported_actions.append("direct_binary_edit")
        preservation_warnings.append("legacy_ole_requires_converter_for_safe_editing")
    elif detected_format.family == "pdf":
        supported_actions.extend(["page_reference", "render_reference"])
        unsupported_actions.append("native_text_edit")
        preservation_warnings.append("pdf_text_edits_should_target_source_office_document_when_available")
    else:
        unsupported_actions.append("office_write_operations")

    return OfficeProjection(
        office_ir=office_ir,
        editable=False,
        supported_actions=tuple(dict.fromkeys(supported_actions)),
        unsupported_actions=tuple(dict.fromkeys(unsupported_actions)),
        preservation_warnings=tuple(dict.fromkeys(preservation_warnings)),
    )
