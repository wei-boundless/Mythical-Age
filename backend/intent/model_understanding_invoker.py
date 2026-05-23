from __future__ import annotations

from typing import Any

from runtime.model_gateway.structured_sidecar import invoke_structured_json_sidecar

from .model_understanding_request import build_model_understanding_request
from .understanding_arbitration import model_understanding_draft_from_payload


async def invoke_model_understanding_draft(
    *,
    invoker: Any,
    user_message: str,
    deterministic_signals: dict[str, Any],
    communication_frame: dict[str, Any] | None = None,
    model_spec: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request = build_model_understanding_request(
        request_id=f"model-understanding-request:{_slug(user_message)[:48] or 'runtime'}",
        user_message=user_message,
        deterministic_signals=dict(deterministic_signals or {}),
        communication_frame=dict(communication_frame or {}),
    )
    sidecar = await invoke_structured_json_sidecar(
        invoker=invoker,
        request_payload=request.to_dict(),
        sidecar_name="model_understanding",
        model_spec=model_spec,
    )
    draft, validation = model_understanding_draft_from_payload(
        sidecar.payload,
        user_message=user_message,
    )
    diagnostics = {
        **dict(sidecar.diagnostics or {}),
        **dict(validation or {}),
        "request": _performed_request_payload(request.to_dict(), sidecar.diagnostics),
    }
    if draft is None:
        return {}, diagnostics
    return draft.to_dict(), {
        **diagnostics,
        "sidecar_status": "accepted",
        "model_call_performed": True,
        "model_authority_used": True,
    }


def _performed_request_payload(request: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
    request_payload = dict(request or {})
    request_diagnostics = dict(request_payload.get("diagnostics") or {})
    request_payload["diagnostics"] = {
        **request_diagnostics,
        "request_contract_only": False,
        "model_call_performed": bool(dict(diagnostics or {}).get("model_call_performed") is True),
        "sidecar_status": str(dict(diagnostics or {}).get("sidecar_status") or ""),
    }
    return request_payload


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "runtime"
