from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .admission import admit_engagement
from .contract_issuer import EngagementContractIssuer
from .dispatcher import EngagementDispatcher
from .models import EngagementRequest
from .resolver import resolve_engagement_plan


FORBIDDEN_START_FIELDS = {"environment_id", "task_environment_id", "execution_strategy_override", "runtime_policy_override", "requires_approval"}


class EngagementService:
    def __init__(self, backend_dir: Path | str) -> None:
        self.backend_dir = Path(backend_dir)

    def start(
        self,
        *,
        runtime_host: Any,
        plan_id: str,
        session_id: str,
        startup_parameters: dict[str, Any],
        requested_by: str = "user",
        source_ref: str = "",
        turn_id: str = "",
    ) -> dict[str, Any]:
        forbidden = sorted(key for key in FORBIDDEN_START_FIELDS if key in startup_parameters)
        if forbidden:
            return {
                "decision": "invalid_request",
                "errors": [f"forbidden_start_field:{key}" for key in forbidden],
                "authority": "task_system.engagement_service",
            }
        request = EngagementRequest(
            request_id=f"engreq:{uuid.uuid4().hex[:12]}",
            plan_id=plan_id,
            startup_parameters=dict(startup_parameters or {}),
            requested_by=requested_by,  # type: ignore[arg-type]
            source_ref=source_ref,
            session_id=session_id,
        )
        try:
            resolved = resolve_engagement_plan(backend_dir=self.backend_dir, request=request)
        except KeyError as exc:
            return {"decision": "invalid", "errors": [str(exc)], "authority": "task_system.engagement_service"}
        admission = admit_engagement(resolved)
        if admission.decision != "allow":
            return {
                "decision": admission.decision,
                "admission": admission.to_dict(),
                "authority": "task_system.engagement_service",
            }
        contract = EngagementContractIssuer().issue(resolved)
        contract_ref = runtime_host.runtime_objects.put_object(
            "engagement_contract",
            contract.contract_id,
            contract.to_dict(),
        )
        result = EngagementDispatcher(self.backend_dir).dispatch(
            runtime_host=runtime_host,
            session_id=session_id,
            turn_id=turn_id or f"engagement:{request.request_id}",
            contract=contract,
            agent_profile_ref=str(resolved.assignee_profile.get("agent_profile_id") or "main_interactive_agent"),
        )
        return {
            **result,
            "engagement_contract_ref": contract_ref,
            "engagement_contract": contract.to_dict(),
            "admission": admission.to_dict(),
            "authority": "task_system.engagement_service",
        }
