from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from evidence import MCPExecutionPlan, MCPRequest, PDFWorker, StructuredDataWorker

from .delegation_models import AgentDelegationRequest


class ChildAgentRuntimeExecutor:
    """Runs a registered child Agent through its profile-authorized specialist capability."""

    def __init__(self, root_dir: Path, *, evidence_orchestrator: Any | None = None) -> None:
        self.root_dir = Path(root_dir)
        self.evidence_orchestrator = evidence_orchestrator

    async def run(self, *, request: AgentDelegationRequest, agent: Any, profile: Any) -> dict[str, Any]:
        operation_id = _operation_for_delegation(request=request, profile=profile)
        if not operation_id:
            return {
                "status": "failed",
                "summary": "子 Agent 未获得可执行的专业能力。",
                "limitations": ["child_operation_not_authorized"],
                "diagnostics": {"child_execution_mode": "profile_authorized_specialist"},
            }
        mcp_route = _mcp_route_for_operation(operation_id)
        if not mcp_route:
            return {
                "status": "failed",
                "summary": "子 Agent 的专业能力暂不支持当前委派类型。",
                "limitations": ["unsupported_child_operation"],
                "diagnostics": {"operation_id": operation_id, "child_execution_mode": "profile_authorized_specialist"},
            }
        mcp_request = _build_mcp_request(request, mcp_route=mcp_route, agent_id=str(getattr(agent, "agent_id", "") or ""))
        mcp_result_payload = await self._run_mcp(mcp_route=mcp_route, mcp_request=mcp_request)
        canonical = dict(mcp_result_payload.get("canonical_result") or {})
        answer = str(canonical.get("answer") or "").strip()
        ok = bool(canonical.get("ok", False))
        status = "completed" if ok else "failed"
        limitations: list[str] = []
        degraded_reason = str(canonical.get("degraded_reason_typed") or canonical.get("degraded_reason") or "").strip()
        if degraded_reason:
            limitations.append(degraded_reason)
        if not answer:
            status = "failed"
            answer = "子 Agent 专业能力执行完成，但没有形成可用结果。"
            limitations.append("child_specialist_empty_answer")
        return {
            "status": status,
            "summary": answer,
            "answer_candidate": answer,
            "evidence_refs": list(canonical.get("evidence_refs") or []),
            "artifact_refs": list(canonical.get("artifact_refs") or []),
            "confidence": "high" if ok else "low",
            "limitations": limitations,
            "diagnostics": {
                "child_execution_mode": "profile_authorized_specialist",
                "operation_id": operation_id,
                "mcp_route": mcp_route,
                "mcp_status": str(mcp_result_payload.get("status") or ""),
                "mcp_result": mcp_result_payload,
            },
        }

    async def _run_mcp(self, *, mcp_route: str, mcp_request: MCPRequest) -> dict[str, Any]:
        if self.evidence_orchestrator is not None:
            done_event: dict[str, Any] = {}
            mcp_end_event: dict[str, Any] = {}
            plan = MCPExecutionPlan(
                mcp_route=mcp_route,
                request=mcp_request,
                expected_result="canonical",
                fallback_execution_kind="none",
                cutover_mode="primary",
            )
            async for event in self.evidence_orchestrator.stream_execution(
                session_id=mcp_request.session_id,
                execution=None,
                mcp_plan=plan,
                main_context={},
                trace=None,
            ):
                if event.get("type") == "mcp_end":
                    mcp_end_event = dict(event)
                if event.get("type") == "done":
                    done_event = dict(event)
            result = dict(mcp_end_event.get("result") or done_event.get("result") or {})
            return {
                "mcp_name": mcp_route,
                "status": "ok" if bool(result.get("ok", False)) else "error",
                "canonical_result": result,
                "diagnostics": {"source": "evidence_orchestrator.stream_execution"},
            }
        if mcp_route == "pdf":
            return (await PDFWorker(root_dir=self.root_dir).run(mcp_request)).to_dict()
        if mcp_route == "structured_data":
            return (await StructuredDataWorker(root_dir=self.root_dir).run(mcp_request)).to_dict()
        return {
            "mcp_name": mcp_route,
            "status": "error",
            "canonical_result": {
                "ok": False,
                "answer": "当前检索服务不可用，无法完成证据检索。",
                "degraded_reason": "retrieval_worker_unavailable",
                "degraded_reason_typed": "retrieval_worker_unavailable",
            },
            "diagnostics": {"source": "child_runtime_fallback"},
        }


def _operation_for_delegation(*, request: AgentDelegationRequest, profile: Any) -> str:
    allowed = {str(item).strip() for item in tuple(getattr(profile, "allowed_operations", ()) or ()) if str(item).strip()}
    blocked = {str(item).strip() for item in tuple(getattr(profile, "blocked_operations", ()) or ()) if str(item).strip()}
    available = allowed - blocked
    kind = str(request.delegation_kind or "").strip()
    if kind in {"pdf", "pdf_reading", "document_reading"} and "op.mcp_pdf" in available:
        return "op.mcp_pdf"
    if kind in {"structured_data", "table_analysis", "structured_data_lookup"} and "op.mcp_structured_data" in available:
        return "op.mcp_structured_data"
    if kind in {"retrieval", "evidence_lookup", "knowledge_retrieval"} and "op.mcp_retrieval" in available:
        return "op.mcp_retrieval"
    for operation_id in ("op.mcp_pdf", "op.mcp_structured_data", "op.mcp_retrieval"):
        if operation_id in available:
            return operation_id
    return ""


def _mcp_route_for_operation(operation_id: str) -> str:
    return {
        "op.mcp_pdf": "pdf",
        "op.mcp_structured_data": "structured_data",
        "op.mcp_retrieval": "retrieval",
    }.get(str(operation_id or "").strip(), "")


def _build_mcp_request(request: AgentDelegationRequest, *, mcp_route: str, agent_id: str) -> MCPRequest:
    payload = dict(request.input_payload or {})
    query = str(payload.get("query") or request.instruction or "").strip()
    path = str(payload.get("file_path") or payload.get("path") or payload.get("active_pdf") or payload.get("active_dataset") or "").strip()
    bindings: dict[str, Any] = {}
    constraints: dict[str, Any] = dict(payload)
    if mcp_route == "pdf" and path:
        bindings["active_pdf"] = path
        constraints.setdefault("path", path)
        constraints.setdefault("mode", str(payload.get("mode") or payload.get("extract_mode") or "document"))
    if mcp_route == "structured_data" and path:
        bindings["active_dataset"] = path
        constraints.setdefault("path", path)
    return MCPRequest(
        request_id=f"mcpreq:delegation:{uuid.uuid4().hex[:10]}",
        session_id=request.session_id,
        query=query,
        mcp_route=mcp_route,
        task_frame={"delegation_request_id": request.request_id, "target_agent_id": request.target_agent_id},
        bindings=bindings,
        constraints=constraints,
        owner_task_id=request.task_run_id,
        arbitration_reason=f"agent_delegation:{request.delegation_kind}",
        agent_id=agent_id,
        message_id=f"{request.request_id}:{mcp_route}",
    )
