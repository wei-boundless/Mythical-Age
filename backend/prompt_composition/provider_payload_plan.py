from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.model_gateway.provider_payload import ProviderPayloadManifest, build_provider_payload_manifest


@dataclass(frozen=True, slots=True)
class ProviderPayloadPlan:
    plan_id: str
    request_id: str
    provider: str
    model: str
    assembly_plan_id: str = ""
    provider_payload_manifest: ProviderPayloadManifest | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.provider_payload_plan"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provider_payload_manifest"] = (
            self.provider_payload_manifest.to_dict()
            if self.provider_payload_manifest is not None
            else {}
        )
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


def build_provider_payload_plan(
    *,
    request_id: str,
    provider: str,
    model: str,
    messages: tuple[dict[str, Any], ...],
    tools: tuple[dict[str, Any], ...],
    segment_bindings: tuple[Any, ...],
    request_params: dict[str, Any] | None = None,
    tool_catalog_manifest: dict[str, Any] | None = None,
    assembly_plan_id: str = "",
) -> ProviderPayloadPlan:
    manifest = build_provider_payload_manifest(
        request_id=request_id,
        provider=provider,
        model=model,
        messages=messages,
        tools=tools,
        segment_bindings=segment_bindings,
        request_params=request_params,
        tool_catalog_manifest=tool_catalog_manifest,
    )
    return ProviderPayloadPlan(
        plan_id="ppplan:" + str(manifest.manifest_id or "").split(":", 1)[-1],
        request_id=str(request_id or ""),
        provider=str(provider or ""),
        model=str(model or ""),
        assembly_plan_id=str(assembly_plan_id or ""),
        provider_payload_manifest=manifest,
        diagnostics={
            "provider_payload_manifest_ref": manifest.manifest_id,
            "provider_payload_cache_boundary": dict(manifest.cache_boundary or {}),
            "tool_schema_boundary_status": _tool_schema_boundary_status(manifest),
            "authority": "prompt_composition.provider_payload_plan.builder",
        },
    )


def _tool_schema_boundary_status(manifest: ProviderPayloadManifest) -> dict[str, Any]:
    segments = [segment.to_dict() for segment in tuple(manifest.segments or ())]
    native = [segment for segment in segments if segment.get("transport_location") == "tools"]
    stable_catalog = [
        segment
        for segment in segments
        if segment.get("kind") == "tool_schema_catalog"
        and segment.get("cache_role") in {"cacheable_prefix", "session_stable"}
        and segment.get("prefix_tier") not in {"volatile", "none"}
    ]
    return {
        "native_tool_schema_segment_count": len(native),
        "stable_tool_schema_catalog_segment_count": len(stable_catalog),
        "native_tool_schema_cache_roles": [str(segment.get("cache_role") or "") for segment in native],
        "stable_tool_schema_catalog_prefix_tiers": [str(segment.get("prefix_tier") or "") for segment in stable_catalog],
        "status": "explained" if native or stable_catalog else "missing_tool_schema_segments",
    }
