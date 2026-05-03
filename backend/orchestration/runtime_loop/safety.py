from __future__ import annotations

from pathlib import Path
from typing import Any

from operations import OperationGateResult


def build_task_safety_validators(*, root_dir: Path, safety_envelope: dict[str, Any] | None) -> dict[str, Any]:
    envelope = dict(safety_envelope or {})
    return {
        "filesystem_path": _filesystem_validator(root_dir=root_dir, safety_envelope=envelope),
    }


def _filesystem_validator(*, root_dir: Path, safety_envelope: dict[str, Any]):
    workspace_root = Path(root_dir).resolve()
    if workspace_root.name == "backend" and workspace_root.parent.exists():
        workspace_root = workspace_root.parent.resolve()

    write_roots = [
        _normalize_relative_path(item)
        for item in list(safety_envelope.get("write_roots") or [])
        if _normalize_relative_path(item)
    ]
    forbidden_paths = [
        _normalize_relative_path(item)
        for item in list(safety_envelope.get("forbidden_paths") or [])
        if _normalize_relative_path(item)
    ]
    write_mode = str(safety_envelope.get("write_mode") or "none").strip()

    def _validate(operation_input: dict[str, Any]) -> bool | tuple[bool, str] | OperationGateResult:
        input_payload = dict(operation_input or {})
        operation_id = str(input_payload.get("operation_id") or "").strip()
        args = dict(input_payload.get("args") or {})
        raw_path = str(input_payload.get("path") or args.get("path") or "").strip()
        if not raw_path:
            return True
        normalized = _normalize_relative_path(raw_path)
        if not normalized:
            return False, "filesystem path is required"
        candidate = (workspace_root / normalized).resolve()
        if workspace_root not in candidate.parents and candidate != workspace_root:
            return False, "path traversal detected"
        normalized_candidate = candidate.relative_to(workspace_root).as_posix()
        write_sensitive = operation_id in {"op.write_file", "op.edit_file", "op.index_multimodal_file"}
        if not write_sensitive and not operation_id:
            write_sensitive = any(key in input_payload for key in ("content", "old_text", "new_text"))
        if write_sensitive:
            if any(
                normalized_candidate == blocked or normalized_candidate.startswith(f"{blocked}/")
                for blocked in forbidden_paths
            ):
                return False, f"path blocked by task safety envelope: {normalized_candidate}"
            if write_mode in {"bounded_create", "scoped_patch"} and write_roots:
                if not any(
                    normalized_candidate == allowed or normalized_candidate.startswith(f"{allowed}/")
                    for allowed in write_roots
                ):
                    return False, f"path outside task write roots: {normalized_candidate}"
        return True

    return _validate


def _normalize_relative_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip().strip("/")
    while "//" in text:
        text = text.replace("//", "/")
    return text
