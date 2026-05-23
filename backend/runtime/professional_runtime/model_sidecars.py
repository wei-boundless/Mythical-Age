from __future__ import annotations

from typing import Any

from runtime.model_gateway.structured_sidecar import invoke_structured_json_sidecar

from .agent_plan import (
    AgentPlanDraft,
    agent_plan_draft_from_payload,
    with_agent_plan_diagnostics,
)
from .completion_judgment import VerificationReview, verification_review_from_payload
from .planner_verifier_requests import build_readonly_planner_request, build_readonly_verifier_request


async def invoke_readonly_planner_draft(
    *,
    invoker: Any,
    task_id: str,
    semantic_contract: dict[str, Any],
    domain_playbook: dict[str, Any] | None = None,
    workspace_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    model_spec: Any | None = None,
) -> tuple[AgentPlanDraft | None, dict[str, Any]]:
    request = build_readonly_planner_request(
        task_id=task_id,
        semantic_contract=semantic_contract,
        domain_playbook=dict(domain_playbook or {}),
        workspace_observations=workspace_observations,
    )
    sidecar = await invoke_structured_json_sidecar(
        invoker=invoker,
        request_payload=request.to_dict(),
        sidecar_name="readonly_planner",
        model_spec=model_spec,
    )
    plan, validation = agent_plan_draft_from_payload(
        sidecar.payload,
        task_id=task_id,
        semantic_contract=semantic_contract,
    )
    request_payload = _performed_request_payload(request.to_dict(), sidecar.diagnostics)
    diagnostics = {
        **dict(sidecar.diagnostics or {}),
        **dict(validation or {}),
        "readonly_planner_request": request_payload,
    }
    if plan is None:
        return None, diagnostics
    return with_agent_plan_diagnostics(
        plan,
        {
            **diagnostics,
            "model_call_performed": True,
            "model_plan_authority_used": True,
            "readonly_planner_request": request_payload,
        },
    ), {
        **diagnostics,
        "sidecar_status": "accepted",
        "model_call_performed": True,
        "model_plan_authority_used": True,
    }


async def invoke_readonly_verifier_review(
    *,
    invoker: Any,
    task_run_id: str,
    semantic_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
    agent_plan_draft: dict[str, Any] | None = None,
    deliverable_validation: dict[str, Any] | None = None,
    obligation_validation: dict[str, Any] | None = None,
    model_spec: Any | None = None,
) -> tuple[VerificationReview | None, dict[str, Any]]:
    request = build_readonly_verifier_request(
        task_run_id=task_run_id,
        semantic_contract=semantic_contract,
        evidence_packet=evidence_packet,
        agent_plan_draft=dict(agent_plan_draft or {}),
        deliverable_validation=dict(deliverable_validation or {}),
        obligation_validation=dict(obligation_validation or {}),
    )
    sidecar = await invoke_structured_json_sidecar(
        invoker=invoker,
        request_payload=request.to_dict(),
        sidecar_name="readonly_verifier",
        model_spec=model_spec,
    )
    review, validation = verification_review_from_payload(
        sidecar.payload,
        task_run_id=task_run_id,
        semantic_contract=semantic_contract,
        evidence_packet=evidence_packet,
        deliverable_validation=dict(deliverable_validation or {}),
        obligation_validation=dict(obligation_validation or {}),
    )
    request_payload = _performed_request_payload(request.to_dict(), sidecar.diagnostics)
    diagnostics = {
        **dict(sidecar.diagnostics or {}),
        **dict(validation or {}),
        "readonly_verifier_request": request_payload,
    }
    if review is None:
        return None, diagnostics
    return review, {
        **diagnostics,
        "sidecar_status": "accepted",
        "model_call_performed": True,
        "model_verifier_authority_used": True,
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
