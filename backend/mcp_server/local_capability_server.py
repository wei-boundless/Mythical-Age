from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from capability_system.local_mcp_registry import get_local_mcp_unit
from capability_system.operation_registry import build_default_operation_registry
from capability_system.tool_runtime import ToolRuntime
from evidence import MCPExecutionPlan, MCPRequest
from evidence.orchestrator import EvidenceOrchestrator
from evidence.output_policy import RAGEvidenceOutputPolicy
from evidence.pdf_worker import PDFWorker
from evidence.retrieval_worker import RetrievalWorker
from evidence.structured_data_worker import StructuredDataWorker
from execution.model_runtime import ModelRuntime
from orchestration import OperationGate, OperationGatePipelineContext, ResourcePolicy
from retrieval import RetrievalService


@dataclass(slots=True)
class LocalMCPToolRequest:
    route: str
    query: str
    session_id: str = "mcp-session"
    path: str = ""
    mode: str = ""
    top_k: int = 5
    constraints: dict[str, Any] | None = None


class LocalCapabilityMCPExecutor:
    """Executes standard MCP tools through the internal local MCP unit layer."""

    def __init__(
        self,
        *,
        backend_dir: Path,
        retrieval_service: Any | None = None,
        tool_runtime: Any | None = None,
        model_runtime: Any | None = None,
        orchestrator: EvidenceOrchestrator | None = None,
        operation_gate: OperationGate | None = None,
        resource_policy: ResourcePolicy | None = None,
        permission_mode: str = "default",
    ) -> None:
        self.backend_dir = Path(backend_dir).resolve()
        self.retrieval_service = retrieval_service or RetrievalService(self.backend_dir)
        self.tool_runtime = tool_runtime or ToolRuntime(self.backend_dir)
        self.model_runtime = model_runtime or ModelRuntime(_MCPSettingsStub())
        self.operation_registry = build_default_operation_registry()
        self.operation_gate = operation_gate or OperationGate(self.operation_registry)
        self.resource_policy = resource_policy
        self.permission_mode = permission_mode
        self.orchestrator = orchestrator or EvidenceOrchestrator(
            retrieval_worker=RetrievalWorker(retrieval_service=self.retrieval_service),
            pdf_worker=PDFWorker(root_dir=self.backend_dir),
            structured_data_worker=StructuredDataWorker(root_dir=self.backend_dir),
            output_policy=RAGEvidenceOutputPolicy(model_runtime=self.model_runtime),
        )

    async def execute(self, request: LocalMCPToolRequest) -> dict[str, Any]:
        unit = get_local_mcp_unit(request.route)
        if unit is None:
            return {
                "status": "error",
                "error": "unsupported_mcp_route",
                "route": request.route,
            }
        gate_result = self.operation_gate.check(
            unit.operation_id,
            resource_policy=self.resource_policy or _default_mcp_resource_policy(unit.operation_id),
            directive_ref=f"standard-mcp:{unit.route}",
            context=OperationGatePipelineContext(
                permission_mode=self.permission_mode,
                operation_input={
                    "query": request.query,
                    "path": request.path,
                    "mode": request.mode,
                    "route": unit.route,
                },
            ),
        )
        if not gate_result.allowed:
            return {
                "status": "error",
                "error": "operation_gate_denied",
                "route": unit.route,
                "operation_id": unit.operation_id,
                "authorization": gate_result.to_dict(),
            }
        mcp_request = MCPRequest(
            request_id=f"mcp:{unit.route}:{_slug(request.query or request.path or 'request')}",
            session_id=request.session_id,
            query=request.query,
            mcp_route=unit.route,
            task_frame={"source": "standard_mcp_server", "route": unit.route},
            bindings=self._bindings_for_unit(unit, request),
            constraints=self._constraints_for_unit(unit, request),
            arbitration_reason="standard_mcp_tool_call",
            message_id=f"mcp:{unit.route}",
        )
        plan = MCPExecutionPlan(
            mcp_route=unit.route,
            request=mcp_request,
            expected_result="canonical" if unit.route != "retrieval" else "evidence",
            fallback_execution_kind="none",
            cutover_mode="primary",
        )
        done_event: dict[str, Any] | None = None
        events: list[dict[str, Any]] = []
        async for event in self.orchestrator.stream_execution(
            session_id=request.session_id,
            execution=None,
            mcp_plan=plan,
            main_context={},
            trace=None,
        ):
            event_payload = dict(event)
            if event_payload.get("type") == "done":
                done_event = event_payload
            else:
                events.append(event_payload)
        if done_event is None:
            return {
                "status": "error",
                "error": "mcp_execution_missing_done_event",
                "route": unit.route,
                "events": events,
            }
        return _compact_done_event(done_event, route=unit.route, operation_id=unit.operation_id)

    def execute_sync(self, request: LocalMCPToolRequest) -> dict[str, Any]:
        return asyncio.run(self.execute(request))

    def _bindings_for_unit(self, unit: Any, request: LocalMCPToolRequest) -> dict[str, Any]:
        if unit.route == "retrieval":
            return {}
        binding_key = str(unit.followup_binding_key or "").strip()
        if not binding_key or binding_key == "current_turn_context":
            return {}
        return {binding_key: request.path} if request.path else {}

    def _constraints_for_unit(self, unit: Any, request: LocalMCPToolRequest) -> dict[str, Any]:
        constraints = dict(request.constraints or {})
        if request.path:
            constraints[str(unit.request_path_parameter or "path")] = request.path
        if request.mode and unit.request_mode_parameter:
            constraints[str(unit.request_mode_parameter)] = request.mode
        if unit.route == "retrieval":
            constraints["top_k"] = max(int(request.top_k or 1), 1)
        return constraints


def _compact_done_event(done_event: dict[str, Any], *, route: str, operation_id: str) -> dict[str, Any]:
    result = dict(done_event.get("mcp_result") or {})
    canonical = dict(result.get("canonical_result") or {})
    envelope = dict(result.get("evidence_envelope") or {})
    return {
        "status": str(result.get("status") or done_event.get("status") or "unknown"),
        "route": route,
        "operation_id": operation_id,
        "answer": str(canonical.get("answer") or ""),
        "canonical_result": canonical,
        "evidence": envelope,
        "main_context": dict(done_event.get("main_context") or {}),
        "task_summary_refs": [dict(item) for item in list(done_event.get("task_summary_refs") or []) if isinstance(item, dict)],
        "diagnostics": dict(result.get("diagnostics") or {}),
    }


def _slug(value: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").lower()).strip("-")
    return normalized[:64] or "request"


class _MCPSettingsStub:
    def get_model_config(self) -> dict[str, Any]:
        return {}

    def get_active_provider_config(self) -> dict[str, Any]:
        return {}

    def get_provider_api_key(self, _provider: str) -> str:
        return ""


def _default_mcp_resource_policy(operation_id: str) -> ResourcePolicy:
    return ResourcePolicy(
        policy_id=f"respol:standard-mcp:{operation_id}",
        task_id="standard-mcp",
        allowed_operations=(operation_id,),
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
        diagnostics={
            "authority": "standard_mcp_server",
            "deny_first_enforced_by": "OperationGate",
        },
    )
