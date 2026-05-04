from __future__ import annotations

from typing import Any

from .supply import (
    MemoryRequest,
    MemoryScopePolicy,
    apply_memory_scope_policy,
    build_memory_request,
    build_memory_scope_policy,
)


class MemoryRequestService:
    """Formal request/scope boundary for memory reads."""

    def build_memory_request(
        self,
        *,
        task_id: str,
        session_id: str,
        agent_id: str,
        memory_request_profile: dict[str, Any] | None = None,
        reason: str = "",
    ) -> MemoryRequest:
        return build_memory_request(
            task_id=task_id,
            session_id=session_id,
            agent_id=agent_id,
            memory_request_profile=memory_request_profile,
            reason=reason,
        )

    def build_memory_scope_policy(
        self,
        *,
        agent_id: str,
        memory_request_profile: dict[str, Any] | None = None,
    ) -> MemoryScopePolicy:
        return build_memory_scope_policy(
            agent_id=agent_id,
            memory_request_profile=memory_request_profile,
        )

    def apply_memory_scope_policy(
        self,
        request: MemoryRequest,
        scope_policy: MemoryScopePolicy,
    ) -> MemoryRequest:
        return apply_memory_scope_policy(request, scope_policy)

    def build_effective_memory_request(
        self,
        *,
        task_id: str,
        session_id: str,
        agent_id: str,
        memory_request_profile: dict[str, Any] | None = None,
        reason: str = "",
    ) -> tuple[MemoryRequest, MemoryScopePolicy]:
        request = self.build_memory_request(
            task_id=task_id,
            session_id=session_id,
            agent_id=agent_id,
            memory_request_profile=memory_request_profile,
            reason=reason,
        )
        scope_policy = self.build_memory_scope_policy(
            agent_id=agent_id,
            memory_request_profile=memory_request_profile,
        )
        return self.apply_memory_scope_policy(request, scope_policy), scope_policy
