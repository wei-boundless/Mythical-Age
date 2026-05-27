from __future__ import annotations

from typing import Any

from permissions import OperationGate, OperationGateResult, ResourceDecision, ResourcePolicy
from capability_system.agent_capabilities.codebase_search import required_operations_for_codebase_search
from capability_system.agent_capabilities.deepsearch import normalize_runtime_config, required_operations_for_search_config


DELEGATION_OPERATION_BY_KIND = {
    "pdf": "op.mcp_pdf",
    "pdf_reading": "op.mcp_pdf",
    "document_reading": "op.mcp_pdf",
    "structured_data": "op.mcp_structured_data",
    "table_analysis": "op.mcp_structured_data",
    "structured_data_lookup": "op.mcp_structured_data",
    "retrieval": "op.mcp_retrieval",
    "evidence_lookup": "op.mcp_retrieval",
    "knowledge_retrieval": "op.mcp_retrieval",
    "knowledge_search": "op.mcp_retrieval",
    "web": "op.web_search",
    "web_research": "op.web_search",
    "external_web_lookup": "op.web_search",
    "current_information_lookup": "op.web_search",
    "official_source_lookup": "op.web_search",
    "codebase_search": "op.codebase_search",
    "local_search": "op.codebase_search",
    "workspace_search": "op.codebase_search",
    "file_search": "op.codebase_search",
    "memory_search": "op.memory_read",
    "memory_lookup": "op.memory_read",
    "memory_recall": "op.memory_read",
}


def operation_for_delegation(*, delegation_kind: str, profile: Any) -> str:
    allowed = {
        str(item).strip()
        for item in tuple(getattr(profile, "allowed_operations", ()) or ())
        if str(item).strip()
    }
    blocked = {
        str(item).strip()
        for item in tuple(getattr(profile, "blocked_operations", ()) or ())
        if str(item).strip()
    }
    available = allowed - blocked
    kind = str(delegation_kind or "").strip()
    if kind in {"web", "web_research", "external_web_lookup", "current_information_lookup", "official_source_lookup"}:
        if "op.search_agent" in available:
            return "op.search_agent"
    operation_id = DELEGATION_OPERATION_BY_KIND.get(kind, "")
    return operation_id if operation_id in available else ""


def required_operations_for_delegation(*, delegation_kind: str, profile: Any) -> tuple[str, ...]:
    operation_id = operation_for_delegation(delegation_kind=delegation_kind, profile=profile)
    if operation_id == "op.codebase_search":
        return required_operations_for_codebase_search()
    if operation_id == "op.search_agent":
        runtime_config = normalize_runtime_config(dict(getattr(profile, "metadata", {}) or {}).get("runtime_config"))
        search_config = runtime_config.search or normalize_runtime_config({"search": {}}).search
        if search_config is not None:
            return required_operations_for_search_config(search_config)
    if operation_id:
        return ("op.model_response", operation_id)
    return ("op.model_response",)


def mcp_route_for_operation(operation_id: str) -> str:
    return {
        "op.mcp_pdf": "pdf",
        "op.mcp_structured_data": "structured_data",
        "op.mcp_retrieval": "retrieval",
    }.get(str(operation_id or "").strip(), "")


def build_child_operation_resource_policy(
    *,
    request: Any,
    child_agent_run: Any,
    operation_ids: tuple[str, ...],
    profile: Any,
    operation_gate: OperationGate,
) -> ResourcePolicy:
    allowed = {
        str(item).strip()
        for item in tuple(getattr(profile, "allowed_operations", ()) or ())
        if str(item).strip()
    }
    blocked = {
        str(item).strip()
        for item in tuple(getattr(profile, "blocked_operations", ()) or ())
        if str(item).strip()
    }
    decisions = tuple(
        _child_operation_resource_decision(
            operation_id=operation_id,
            allowed=allowed,
            blocked=blocked,
            operation_gate=operation_gate,
        )
        for operation_id in operation_ids
    )
    return ResourcePolicy(
        policy_id=f"respol:{request.task_run_id}:delegation:{request.request_id}",
        task_id=request.task_run_id,
        allowed_operations=tuple(decision.operation_id for decision in decisions if decision.decision == "allow"),
        denied_operations=tuple(decision.operation_id for decision in decisions if decision.decision == "deny"),
        requires_approval_operations=tuple(
            decision.operation_id for decision in decisions if decision.decision == "requires_approval"
        ),
        memory_read_scope="context_package",
        memory_write_scope="none",
        approval_policy="delegated_child_operation",
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
        decisions=decisions,
        diagnostics={
            "authority": "orchestration.agent_delegation_child_operation_policy",
            "delegation_request_ref": request.request_id,
            "child_agent_run_ref": child_agent_run.agent_run_id,
            "target_agent_id": request.target_agent_id,
            "delegation_kind": request.delegation_kind,
            "required_operations": list(operation_ids),
            "headless_child_execution": True,
        },
    )


def merge_child_operation_gate_results(
    *,
    request: Any,
    child_agent_run: Any,
    results: list[Any],
) -> OperationGateResult:
    if not results:
        return OperationGateResult(
            operation_id="op.unknown_child_operation",
            decision="deny",
            reason="child operation set is empty",
            diagnostics={
                "delegation_request_ref": request.request_id,
                "child_agent_run_ref": child_agent_run.agent_run_id,
                "fail_closed": True,
            },
        )
    blocked = next((result for result in results if not bool(result.allowed)), None)
    if blocked is not None:
        return OperationGateResult(
            operation_id=blocked.operation_id,
            decision=blocked.decision,
            reason=blocked.reason,
            allowed=False,
            requires_approval=blocked.requires_approval,
            pipeline_stage=blocked.pipeline_stage,
            diagnostics={
                **dict(blocked.diagnostics or {}),
                "delegation_request_ref": request.request_id,
                "child_agent_run_ref": child_agent_run.agent_run_id,
                "required_operation_results": [result.to_dict() for result in results],
            },
        )
    return OperationGateResult(
        operation_id="op.delegated_child_operation_set",
        decision="allow",
        reason="all delegated child operations allowed",
        allowed=True,
        pipeline_stage="delegated_child_operation_set",
        diagnostics={
            "delegation_request_ref": request.request_id,
            "child_agent_run_ref": child_agent_run.agent_run_id,
            "required_operation_results": [result.to_dict() for result in results],
        },
    )


def _child_operation_resource_decision(
    *,
    operation_id: str,
    allowed: set[str],
    blocked: set[str],
    operation_gate: OperationGate,
) -> ResourceDecision:
    normalized_operation_id = operation_gate.registry.normalize_id(operation_id)
    descriptor = operation_gate.registry.get_operation(normalized_operation_id)
    if not normalized_operation_id or descriptor is None:
        return ResourceDecision(
            operation_id=normalized_operation_id or "op.unknown_child_operation",
            decision="deny",
            reason="child operation descriptor is missing",
            diagnostics={"fail_closed": True},
        )
    if normalized_operation_id in blocked:
        return ResourceDecision(
            operation_id=normalized_operation_id,
            decision="deny",
            reason="child operation blocked by target agent profile",
            risk_tags=tuple(descriptor.risk_tags),
        )
    if normalized_operation_id not in allowed:
        return ResourceDecision(
            operation_id=normalized_operation_id,
            decision="deny",
            reason="child operation outside target agent capability profile",
            risk_tags=tuple(descriptor.risk_tags),
        )
    if descriptor.requires_approval_by_default or descriptor.destructive:
        return ResourceDecision(
            operation_id=normalized_operation_id,
            decision="requires_approval",
            reason="child operation requires approval and delegation runs headless",
            risk_tags=tuple(descriptor.risk_tags),
            requires_user_approval=True,
            approval_channel="runtime_approval",
        )
    return ResourceDecision(
        operation_id=normalized_operation_id,
        decision="allow",
        reason="child operation allowed by target profile and delegation request",
        risk_tags=tuple(descriptor.risk_tags),
    )


