from __future__ import annotations

from typing import Any

from orchestration.adapters import build_shadow_orchestration_plan
from orchestration.models import OrchestrationPlan


class OrchestrationPlanner:
    """Shadow control-plane planner.

    Stage one deliberately wraps the legacy QueryPlanner. This establishes the
    canonical OrchestrationPlan shape without changing runtime behavior.
    """

    def __init__(self, legacy_planner: Any) -> None:
        self.legacy_planner = legacy_planner

    def build_plan(
        self,
        *,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        ephemeral_system_messages: list[str] | None = None,
        authority_context: dict[str, Any] | None = None,
        explicit_subtasks: list[dict[str, Any]] | None = None,
        source: str = "live-session",
    ) -> tuple[Any, OrchestrationPlan]:
        query_plan = self.legacy_planner.build_plan(
            session_id=session_id,
            message=message,
            history=history,
            ephemeral_system_messages=ephemeral_system_messages,
            authority_context=authority_context,
            explicit_subtasks=explicit_subtasks,
        )
        orchestration_plan = build_shadow_orchestration_plan(
            session_id=session_id,
            message=message,
            query_plan=query_plan,
            source=source,
        )
        return query_plan, orchestration_plan
