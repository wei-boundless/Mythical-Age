from __future__ import annotations

from typing import Any

from orchestration import build_agent_runtime_chain_preview
from tasks.contract_builder import build_task_runtime_contract_preview
from understanding import analyze_memory_intent


class AgentRuntimeChainAssembler:
    """Assembles the current single-agent runtime chain from system previews."""

    def __init__(self, *, memory_facade) -> None:
        self.memory_facade = memory_facade

    def build_live_preview(
        self,
        *,
        session_id: str,
        task_id: str,
        message: str,
        source: str,
    ) -> dict[str, Any]:
        memory_intent = analyze_memory_intent(message)
        memory_payload = self.build_memory_runtime_view_payload(
            session_id=session_id,
            message=message,
            memory_intent=memory_intent,
        )
        context_policy_result = self.build_context_policy_result(
            session_id=session_id,
            message=message,
            memory_intent=memory_intent,
        )
        context_payload = _to_dict(context_policy_result)
        task_operation_preview = build_task_runtime_contract_preview(
            session_id=session_id,
            task_id=task_id,
            user_goal=message,
            source=source,
            memory_runtime_view=memory_payload,
            context_policy_preview=context_payload,
        )
        chain = build_agent_runtime_chain_preview(
            session_id=session_id,
            task_operation_preview=task_operation_preview,
            memory_runtime_view=memory_payload,
            context_policy_preview=context_payload,
        )
        return {
            "agent_runtime_chain_preview": chain.to_dict(),
            "memory_runtime_view": memory_payload,
            "context_policy_preview": context_payload,
            "task_operation_preview": task_operation_preview,
            "status": chain.status,
        }

    def build_memory_runtime_view_payload(
        self,
        *,
        session_id: str,
        message: str,
        memory_intent: Any,
    ) -> dict[str, Any]:
        builder = getattr(self.memory_facade, "build_memory_runtime_view", None)
        if not callable(builder):
            return {}
        view = builder(
            session_id=session_id,
            query=message,
            memory_intent=memory_intent,
        )
        return _to_dict(view)

    def build_context_policy_result(
        self,
        *,
        session_id: str,
        message: str | None,
        memory_intent: Any,
        relevant_memory_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
    ):
        builder = getattr(self.memory_facade, "build_memory_context_package_preview", None)
        if not callable(builder):
            return None
        return builder(
            session_id=session_id,
            query=message,
            memory_intent=memory_intent,
            relevant_notes=relevant_memory_notes,
            retrieval_results=retrieval_results,
        )

    def build_context_package_preview(
        self,
        *,
        session_id: str,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_memory_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
    ):
        result = self.build_context_policy_result(
            session_id=session_id,
            message=pending_user_message,
            memory_intent=memory_intent or analyze_memory_intent(pending_user_message or ""),
            relevant_memory_notes=relevant_memory_notes,
            retrieval_results=retrieval_results,
        )
        return getattr(result, "package", None)


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, dict):
        return dict(value)
    return dict(value)
