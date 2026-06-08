from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactScopeManifest:
    manifest_id: str
    invocation_kind: str
    source_ref: str
    scope_hash: str
    artifact_root: str = ""
    write_roots: tuple[str, ...] = ()
    canonical_output_paths: tuple[str, ...] = ()
    model_visible_scope: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.artifact_scope_manifest"

    def to_model_visible_payload(self) -> dict[str, Any]:
        return {"artifact_execution_scope": _deepcopy_json_dict(self.model_visible_scope)}

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["write_roots"] = list(self.write_roots)
        payload["canonical_output_paths"] = list(self.canonical_output_paths)
        payload["model_visible_scope"] = _deepcopy_json_dict(self.model_visible_scope)
        payload["diagnostics"] = _deepcopy_json_dict(self.diagnostics)
        return payload


def build_artifact_scope_manifest(
    *,
    invocation_kind: str,
    sandbox_execution_scope: Any,
    source_ref: str,
) -> ArtifactScopeManifest:
    model_visible_scope = (
        sandbox_execution_scope.to_model_visible_payload()
        if hasattr(sandbox_execution_scope, "to_model_visible_payload")
        else {}
    )
    diagnostics = (
        sandbox_execution_scope.to_diagnostics()
        if hasattr(sandbox_execution_scope, "to_diagnostics")
        else {}
    )
    model_visible_scope = _deepcopy_json_dict(model_visible_scope if isinstance(model_visible_scope, dict) else {})
    diagnostics = _deepcopy_json_dict(diagnostics if isinstance(diagnostics, dict) else {})
    scope_hash = _stable_json_hash(model_visible_scope)
    seed = {
        "invocation_kind": str(invocation_kind or ""),
        "source_ref": str(source_ref or ""),
        "scope_hash": scope_hash,
    }
    return ArtifactScopeManifest(
        manifest_id="artifactscope:" + _digest(seed),
        invocation_kind=str(invocation_kind or ""),
        source_ref=str(source_ref or ""),
        scope_hash=scope_hash,
        artifact_root=str(model_visible_scope.get("artifact_root") or diagnostics.get("artifact_root") or ""),
        write_roots=tuple(str(item) for item in list(model_visible_scope.get("write_roots") or []) if str(item)),
        canonical_output_paths=tuple(
            str(item)
            for item in list(model_visible_scope.get("canonical_output_paths") or [])
            if str(item)
        ),
        model_visible_scope=model_visible_scope,
        diagnostics=diagnostics,
    )


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _digest(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _deepcopy_json_dict(value: dict[str, Any]) -> dict[str, Any]:
    return dict(_json_stable(dict(value or {})))
