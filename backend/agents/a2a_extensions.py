from __future__ import annotations

from typing import Any


A2A_EXTENSION_NAMESPACE = "x-langchain-agent"

EXT_OBJECT_HANDLES = f"{A2A_EXTENSION_NAMESPACE}.object_handles"
EXT_RESULT_HANDLES = f"{A2A_EXTENSION_NAMESPACE}.result_handles"
EXT_SUBSET_HANDLES = f"{A2A_EXTENSION_NAMESPACE}.subset_handles"
EXT_EVIDENCE_REFS = f"{A2A_EXTENSION_NAMESPACE}.evidence_refs"
EXT_ARTIFACT_REFS = f"{A2A_EXTENSION_NAMESPACE}.artifact_refs"
EXT_BINDING_OWNER_TASK_ID = f"{A2A_EXTENSION_NAMESPACE}.binding_owner_task_id"


def build_handle_extensions(
    *,
    object_handle_ids: list[str] | tuple[str, ...] | None = None,
    result_handle_ids: list[str] | tuple[str, ...] | None = None,
    subset_handle_ids: list[str] | tuple[str, ...] | None = None,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    artifact_refs: list[str] | tuple[str, ...] | None = None,
    binding_owner_task_id: str = "",
) -> dict[str, Any]:
    extensions: dict[str, Any] = {}
    if object_handle_ids:
        extensions[EXT_OBJECT_HANDLES] = [str(item) for item in object_handle_ids if str(item).strip()]
    if result_handle_ids:
        extensions[EXT_RESULT_HANDLES] = [str(item) for item in result_handle_ids if str(item).strip()]
    if subset_handle_ids:
        extensions[EXT_SUBSET_HANDLES] = [str(item) for item in subset_handle_ids if str(item).strip()]
    if evidence_refs:
        extensions[EXT_EVIDENCE_REFS] = [str(item) for item in evidence_refs if str(item).strip()]
    if artifact_refs:
        extensions[EXT_ARTIFACT_REFS] = [str(item) for item in artifact_refs if str(item).strip()]
    if str(binding_owner_task_id or "").strip():
        extensions[EXT_BINDING_OWNER_TASK_ID] = str(binding_owner_task_id).strip()
    return extensions


def merge_extensions(*items: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        merged.update(dict(item or {}))
    return merged
