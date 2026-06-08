from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ActionSchemaManifest:
    manifest_id: str
    invocation_kind: str
    source_ref: str
    schema_hash: str
    allowed_action_types: tuple[str, ...] = ()
    schema: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.action_schema_manifest"

    def to_model_visible_payload(self) -> dict[str, Any]:
        return {"schema": _deepcopy_json_dict(self.schema)}

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_action_types"] = list(self.allowed_action_types)
        payload["schema"] = _deepcopy_json_dict(self.schema)
        return payload


def build_action_schema_manifest(
    *,
    invocation_kind: str,
    schema: dict[str, Any],
    source_ref: str,
) -> ActionSchemaManifest:
    schema_payload = _deepcopy_json_dict(schema)
    schema_hash = _stable_json_hash(schema_payload)
    allowed_action_types = tuple(
        item.strip()
        for item in str(schema_payload.get("action_type") or "").split("|")
        if item.strip()
    )
    seed = {
        "invocation_kind": str(invocation_kind or ""),
        "source_ref": str(source_ref or ""),
        "schema_hash": schema_hash,
        "allowed_action_types": allowed_action_types,
    }
    return ActionSchemaManifest(
        manifest_id="actionschema:" + _digest(seed),
        invocation_kind=str(invocation_kind or ""),
        source_ref=str(source_ref or ""),
        schema_hash=schema_hash,
        allowed_action_types=allowed_action_types,
        schema=schema_payload,
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
